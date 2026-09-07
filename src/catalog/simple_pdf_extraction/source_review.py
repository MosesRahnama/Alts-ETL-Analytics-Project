"""Apply authored, page-backed field corrections through adjudication records."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from . import csv_workflow as workflow
from src.pipeline.build_extraction_review import selected_record
from src.pipeline.transformation_lineage import run_stage

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "data/normalization/source-review-corrections.csv"
CHANGES = ROOT / "data/extracted/audit/source-review-changes.csv"
FIELDS = ("rule_id", "route", "file_id", "pair_id", "field", "old_value", "new_value",
          "source_page", "evidence_page", "source_quote", "reason")


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if path in (RULES, CHANGES) and tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"Source-review header differs from the required columns: {path}")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError(f"Source-review CSV has inconsistent column counts: {path}")
        return rows


def plans() -> list[tuple[str, str, Path, list[dict[str, str]]]]:
    """Validate every decision before writing any resolution file."""
    rules = read(RULES)
    seen = set()
    rule_ids = set()
    grouped = defaultdict(list)
    for rule in rules:
        key = tuple(rule[key] for key in ("route", "file_id", "pair_id", "field"))
        if key in seen:
            raise ValueError(f"Duplicate source correction {key}")
        seen.add(key)
        if rule["rule_id"] in rule_ids:
            raise ValueError(f"Duplicate source correction ID {rule['rule_id']}")
        rule_ids.add(rule["rule_id"])
        if rule["field"] not in (*workflow.BUSINESS_COLUMNS, "record_family") or rule["field"] == "metric_value_raw":
            raise ValueError(f"Source correction cannot change {rule['field']}")
        if not all(rule[key] for key in ("rule_id", "source_page", "evidence_page", "source_quote", "reason")):
            raise ValueError(f"Incomplete evidence for {rule['rule_id']}")
        if any(not rule[key].isdigit() or int(rule[key]) < 1 for key in ("source_page", "evidence_page")):
            raise ValueError(f"Invalid physical page for {rule['rule_id']}")
        grouped[rule["route"], rule["file_id"]].append(rule)
    output = []
    for (route, file_id), decisions in grouped.items():
        folder = workflow.file_folder(route, file_id)
        a_rows, b_rows = read(folder / "records-a.csv"), read(folder / "records-b.csv")
        pairs = {row["pair_id"]: row for row in read(folder / "pair-index.csv")}
        resolution_path = folder / "resolution.csv"
        resolutions = read(resolution_path)
        by_pair = {row["pair_id"]: row for row in resolutions if row["pair_id"]}
        additions = {f"ADD:{i:04d}": row for i, row in enumerate(
            (r for r in resolutions if r["decision"] == "ADD"), 1)}
        selected = {}
        for rule in decisions:
            pair_id = rule["pair_id"]
            if pair_id not in pairs and pair_id not in additions:
                raise ValueError(f"Unknown pair {pair_id}: {rule['rule_id']}")
            if pair_id not in selected:
                if pair_id in additions:
                    row = {key: additions[pair_id].get(key, "") for key in workflow.RECORD_COLUMNS}
                else:
                    row, _, _ = selected_record(pairs[pair_id], a_rows, b_rows, by_pair.get(pair_id))
                if row is None:
                    raise ValueError(f"Correction names a rejected pair: {pair_id}")
                selected[pair_id] = row
            row = selected[pair_id]
            field = rule["field"]
            if row["source_page"] != rule["source_page"] or row.get(field, "") not in {
                rule["old_value"], rule["new_value"]
            }:
                raise ValueError(f"Source correction drift: {rule['rule_id']}")
            row[field] = rule["new_value"]
        for pair_id, row in selected.items():
            resolution = additions.get(pair_id) if pair_id in additions else by_pair.get(pair_id)
            if resolution is None:
                resolution = {key: "" for key in workflow.RESOLUTION_COLUMNS}
                resolutions.append(resolution)
            decision_rules = [r for r in decisions if r["pair_id"] == pair_id]
            evidence = " | ".join(dict.fromkeys(
                f"p{r['evidence_page']}: {r['source_quote']} ({r['reason']})" for r in decision_rules
            ))
            prior = resolution.get("reason", "").split("; Source review:")[0]
            resolution.update({key: row.get(key, "") for key in workflow.RECORD_COLUMNS})
            resolution.update(pair_id="" if pair_id in additions else pair_id,
                decision="ADD" if pair_id in additions else "MERGE",
                reason=prior + "; Source review: " + evidence)
        output.append((route, file_id, resolution_path, resolutions))
    return output


def check() -> int:
    errors = []
    for route, file_id, path, proposed in plans():
        if read(path) != proposed:
            errors.append(f"{route}/{file_id}")
    if errors:
        raise ValueError("Unapplied source reviews: " + ", ".join(errors[:10]))
    if not CHANGES.is_file() or read(CHANGES) != read(RULES):
        raise ValueError("Source-review change log differs from the authored decisions")
    print(f"PASS: {len(read(RULES))} authored source-field corrections match resolution records")
    return 0


def apply() -> int:
    prepared = plans()
    inputs = [RULES]
    outputs = [CHANGES]
    for route, file_id, path, _ in prepared:
        inputs.extend([path.parent / "records-a.csv", path.parent / "records-b.csv",
                       path.parent / "pair-index.csv"])
        outputs.extend([path, *workflow.final_paths(route, file_id)])

    def action():
        for route, file_id, path, rows in prepared:
            workflow.write_csv(path, workflow.RESOLUTION_COLUMNS, rows)
            workflow.build_final_command(route, file_id)
        workflow.write_csv(CHANGES, FIELDS, read(RULES))
        return 0

    run_stage(stage_id="source-review", stage_order=2,
              command="python -m src.catalog.simple_pdf_extraction.source_review --apply",
              inputs=inputs, outputs=outputs, action=action)
    return check()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    apply() if args.apply else check()


if __name__ == "__main__":
    main()
