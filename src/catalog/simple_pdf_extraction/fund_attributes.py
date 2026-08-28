"""Fund-constant attributes collected from printed observation context.

Vintage, strategy, asset class, and geography are constant for a fund. Extractors
copy a grouping heading onto every row of that page, so blanks inside one page
are already filled. The remaining blanks sit on a different table or a different
document that never printed the heading. This stage copies a printed value across
those rows at fund grain, and stamps the same value onto fund-level tables.

It never edits an adjudicated extraction file. Printed context columns on
fact_observation stay as the page printed them. A fund the corpus never labelled
stays blank.

    harvest    one row per fund from fact_observation, with printed variants
    autofill   unique printed values, including spelling variants that collapse
    conflicts  funds whose remaining variants disagree after that collapse
    export     one worksheet of conflict rows
    merge      fold the worksheet back into the matrix
    dispatch   write the standing pasteable brief for the attribute worksheet;
               keep it after the slice is settled
    apply      inherit log plus vintage and strategy on fund_periods and fund_master
    paths      print the output file each command writes
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FACT_OBSERVATION = PROJECT_ROOT / "data" / "extracted" / "tables" / "fact_observation.csv"
DIM_ENTITY = PROJECT_ROOT / "data" / "extracted" / "tables" / "dim_entity.csv"
MATRIX = PROJECT_ROOT / "data" / "normalization" / "fund-attributes-matrix.csv"
CONFLICTS = PROJECT_ROOT / "data" / "normalization" / "attribute-conflicts.csv"
WORKSHEET_DIR = PROJECT_ROOT / "data" / "normalization" / "worksheets"
WORKSHEET = WORKSHEET_DIR / "attribute-conflicts.csv"
INHERIT_LOG = PROJECT_ROOT / "data" / "extracted" / "audit" / "attribute-inherit.csv"
ATTRIBUTE_CHANGES = PROJECT_ROOT / "data" / "extracted" / "audit" / "attribute-changes.csv"
INSTRUCTIONS_DIR = PROJECT_ROOT / "instructions" / "02-fund-mapping"
BRIEF = INSTRUCTIONS_DIR / "05-ATTRIBUTE-NORMALIZER.md"
DISPATCH_DIR = INSTRUCTIONS_DIR / "dispatch-prompts" / "attributes"
DISPATCH_PROMPT = DISPATCH_DIR / "ATTRIBUTE-NORMALIZER-01.md"

FIELDS = ("vintage_year", "strategy", "asset_class", "geography")
STAMP_FIELDS = ("vintage_year", "strategy")
SETTLED = {"unique", "unique_canonical", "decided"}
FUND_PREFIX = "FUND_"

MATRIX_HEADER = [
    "fund_id",
    "standardized_fund_name",
    "observation_rows",
    "source_files",
]
for _field in FIELDS:
    MATRIX_HEADER.extend(
        [
            _field,
            f"{_field}_status",
            f"{_field}_variants",
            f"{_field}_filled_rows",
            f"{_field}_blank_rows",
            f"{_field}_source_files",
        ]
    )
MATRIX_HEADER.append("merge_note")

INHERIT_HEADER = [
    "observation_id",
    "fund_id",
    "document_id",
    "source_page",
    "source_table",
    "field",
    "printed_value",
    "inherited_value",
    "rule",
    "source_observation_id",
    "source_document_id",
    "source_evidence_page",
    "source_evidence_table",
    "source_evidence_quote",
    "source_printed_value",
]

CHANGE_HEADER = [
    "change_id",
    "stage_id",
    "target_table",
    "target_record_id",
    "fund_id",
    "field",
    "old_value",
    "new_value",
    "change_type",
    "source_observation_id",
    "source_document_id",
    "source_page",
    "source_table",
    "source_quote",
    "source_printed_value",
    "rule_id",
    "matrix_status",
    "notes",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in header})


def canon_vintage(value: str) -> str:
    match = re.search(r"(?:19|20)\d{2}", value)
    return match.group(0) if match else value.strip()


def canon_label(value: str) -> str:
    text = value.casefold().replace("-", " ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\binvestments?\b", "", text)
    text = re.sub(r"\badded\b", "add", text)
    return re.sub(r"\s+", " ", text).strip()


def canon(field: str, value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if field == "vintage_year":
        return canon_vintage(text)
    return canon_label(text)


def pick_spelling(counter: Counter[str]) -> str:
    """Most often printed, then the longest string, then alphabetical."""

    return sorted(counter.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))[0][0]


def classify(field: str, values: Counter[str]) -> tuple[str, str, str]:
    """Return (chosen spelling, status, pipe-separated variants)."""

    variants = " | ".join(sorted(values))
    if not values:
        return "", "none", ""
    if len(values) == 1:
        return next(iter(values)), "unique", variants
    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    for spelling, count in values.items():
        buckets[canon(field, spelling)][spelling] += count
    if len(buckets) == 1:
        merged = Counter()
        for inner in buckets.values():
            merged.update(inner)
        return pick_spelling(merged), "unique_canonical", variants
    return "", "conflict", variants


def _blank_matrix_row(fund_id: str, name: str) -> dict[str, str]:
    row = {key: "" for key in MATRIX_HEADER}
    row["fund_id"] = fund_id
    row["standardized_fund_name"] = name
    row["observation_rows"] = "0"
    return row


def harvest() -> int:
    """One row per resolved fund, with every printed context value counted."""

    observations = read_csv(FACT_OBSERVATION)
    if not observations:
        raise SystemExit(f"No observations at {FACT_OBSERVATION}. Flatten first.")
    names = {
        row["entity_id"]: row.get("canonical_name", "")
        for row in read_csv(DIM_ENTITY)
        if row.get("entity_kind") == "fund"
    }
    existing = {row["fund_id"]: row for row in read_csv(MATRIX) if row.get("fund_id")}

    by_fund: dict[str, dict[str, object]] = {}
    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        if row.get("subject_type") != "fund" or not fund_id.startswith(FUND_PREFIX):
            continue
        bucket = by_fund.setdefault(
            fund_id,
            {
                "name": row.get("subject_standardized_name", "") or names.get(fund_id, ""),
                "files": set(),
                "rows": 0,
                "fields": {field: Counter() for field in FIELDS},
                "filled": {field: 0 for field in FIELDS},
                "blank": {field: 0 for field in FIELDS},
                "field_files": {field: set() for field in FIELDS},
            },
        )
        bucket["rows"] = int(bucket["rows"]) + 1
        bucket["files"].add(row.get("document_id", ""))
        if not bucket["name"]:
            bucket["name"] = row.get("subject_standardized_name", "") or names.get(fund_id, "")
        for field in FIELDS:
            value = (row.get(field) or "").strip()
            if value:
                bucket["fields"][field][value] += 1
                bucket["filled"][field] = int(bucket["filled"][field]) + 1
                bucket["field_files"][field].add(row.get("document_id", ""))
            else:
                bucket["blank"][field] = int(bucket["blank"][field]) + 1

    rows = []
    for fund_id in sorted(by_fund):
        prior = existing.get(fund_id, {})
        bucket = by_fund[fund_id]
        out = _blank_matrix_row(fund_id, str(bucket["name"]) or prior.get("standardized_fund_name", ""))
        out["observation_rows"] = str(bucket["rows"])
        out["source_files"] = " | ".join(sorted(file_id for file_id in bucket["files"] if file_id))
        out["merge_note"] = prior.get("merge_note", "")
        for field in FIELDS:
            chosen, status, variants = classify(field, bucket["fields"][field])
            out[f"{field}_variants"] = variants
            out[f"{field}_filled_rows"] = str(bucket["filled"][field])
            out[f"{field}_blank_rows"] = str(bucket["blank"][field])
            out[f"{field}_source_files"] = " | ".join(
                sorted(file_id for file_id in bucket["field_files"][field] if file_id)
            )
            prior_status = prior.get(f"{field}_status", "")
            prior_value = prior.get(field, "")
            if prior_status == "decided" and prior_value:
                out[field] = prior_value
                out[f"{field}_status"] = "decided"
                if variants and canon(field, prior_value) not in {
                    canon(field, item) for item in variants.split(" | ") if item
                }:
                    out[f"{field}_status"] = "conflict"
                    out["merge_note"] = (
                        f"{out['merge_note']} decided {field}={prior_value} is outside printed variants"
                    ).strip()
            elif prior_status == "none" and status == "conflict":
                out[field] = ""
                out[f"{field}_status"] = "none"
            else:
                out[field] = chosen
                out[f"{field}_status"] = status
        rows.append(out)

    write_csv(MATRIX, MATRIX_HEADER, rows)
    print(f"PASS: {len(rows)} fund attribute rows -> {MATRIX}")
    return 0


def autofill() -> int:
    """Leave unique and unique_canonical rows as they harvested; report counts."""

    rows = read_csv(MATRIX)
    if not rows:
        raise SystemExit(f"No matrix at {MATRIX}. Run harvest first.")
    counts: Counter[str] = Counter()
    fillable = 0
    for row in rows:
        for field in FIELDS:
            status = row.get(f"{field}_status", "")
            counts[f"{field}:{status or 'none'}"] += 1
            if status in SETTLED and int(row.get(f"{field}_blank_rows") or 0) > 0:
                fillable += int(row[f"{field}_blank_rows"])
    write_csv(MATRIX, MATRIX_HEADER, rows)
    for key, count in sorted(counts.items()):
        print(f"  {key:<28} {count:>5}")
    print(f"blank observation cells a settled value can fill: {fillable}")
    print(f"PASS: {MATRIX.name} statuses current")
    return 0


def conflict_rows(rows: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    rows = rows if rows is not None else read_csv(MATRIX)
    return [
        row
        for row in rows
        if any(row.get(f"{field}_status") == "conflict" for field in FIELDS)
    ]


def conflicts(strict: bool = False) -> int:
    rows = conflict_rows()
    write_csv(CONFLICTS, MATRIX_HEADER, rows)
    if not rows:
        print(f"PASS: no fund-constant attribute conflicts -> {CONFLICTS.name}")
        return 0
    print(
        f"{'FAIL' if strict else 'REVIEW'}: {len(rows)} fund(s) carry disagreeing "
        f"printed attributes -> {CONFLICTS.name}"
    )
    for row in rows[:20]:
        fields = [field for field in FIELDS if row.get(f"{field}_status") == "conflict"]
        print(f"  {row['fund_id']}  {row['standardized_fund_name']}: {', '.join(fields)}")
    return 1 if strict else 0


def export_worksheet() -> int:
    rows = conflict_rows()
    write_csv(WORKSHEET, MATRIX_HEADER, rows)
    print(f"PASS: {len(rows)} conflict row(s) -> {WORKSHEET}")
    return 0


def merge_worksheet() -> int:
    matrix = {row["fund_id"]: row for row in read_csv(MATRIX)}
    if not matrix:
        raise SystemExit(f"No matrix at {MATRIX}. Run harvest first.")
    incoming = read_csv(WORKSHEET)
    if not incoming and not WORKSHEET.is_file():
        raise SystemExit(f"No worksheet at {WORKSHEET}. Run export first.")
    updated = 0
    for row in incoming:
        fund_id = row.get("fund_id", "")
        if fund_id not in matrix:
            raise SystemExit(f"worksheet names unknown fund_id {fund_id}")
        target = matrix[fund_id]
        for field in FIELDS:
            value = row.get(field, "").strip()
            status = row.get(f"{field}_status", "").strip()
            if status == "decided":
                if not value:
                    raise SystemExit(f"{fund_id} {field}: decided requires a printed spelling")
                variants = [item.strip() for item in target.get(f"{field}_variants", "").split("|") if item.strip()]
                if variants and canon(field, value) not in {canon(field, item) for item in variants}:
                    raise SystemExit(
                        f"{fund_id} {field}: {value!r} is not among the printed variants"
                    )
                target[field] = value
                target[f"{field}_status"] = "decided"
                updated += 1
            elif status == "none":
                target[field] = ""
                target[f"{field}_status"] = "none"
                updated += 1
        if row.get("merge_note"):
            target["merge_note"] = row["merge_note"]
    write_csv(MATRIX, MATRIX_HEADER, [matrix[key] for key in sorted(matrix)])
    print(f"PASS: merged {updated} field decision(s) -> {MATRIX.name}")
    return 0


def _brief_body(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = 1 if lines and lines[0].startswith("# ") else 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    return "\n".join(lines[start:]).rstrip() + "\n"


def _render_dispatch(worksheet: Path) -> str:
    rows = read_csv(worksheet)
    try:
        relative = worksheet.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        relative = "data/normalization/worksheets/attribute-conflicts.csv"
    count = len(rows)
    noun = "fund" if count == 1 else "funds"
    if count:
        slice_line = (
            f"- **Group:** {count} {noun} with a remaining attribute conflict"
        )
    else:
        slice_line = (
            "- **Group:** `attribute-conflicts.csv` is header-only; every printed split "
            "is decided. This file stays: it is the standing brief for this step."
        )
    header = [
        "# Attribute normalizer: group 01",
        "",
        f"*Generated by `fund_attributes dispatch` from `{BRIEF.name}` and `{worksheet.name}`. "
        "Regenerate this file; do not hand-edit it. Do not delete it when the group is decided.*",
        "",
        "- **Project root:** the repository root, the folder holding `README.md`; every path below is relative to it",
        f"- **Worksheet:** `{relative}`",
        slice_line,
        "- **Written cells:** the chosen spelling, the field `_status` as `decided` or `none`, and `merge_note` "
        "in that file, and nowhere else.",
        "",
        "Resuming. A row already marked `decided` or `none` is finished. Skip it. Start at the first "
        "conflict still open. Do not clear a finished cell.",
        "",
        "",
    ]
    return "\n".join(header) + _brief_body(BRIEF)


def dispatch(check: bool = False) -> int:
    """Write the standing attribute brief. Keep it after every split is settled."""

    if not BRIEF.is_file():
        raise SystemExit(f"Missing brief {BRIEF}")
    if not WORKSHEET.is_file():
        raise SystemExit(f"No worksheet at {WORKSHEET}. Run export first.")
    wanted = {DISPATCH_PROMPT: _render_dispatch(WORKSHEET)}
    existing = {
        path for path in DISPATCH_DIR.glob("*.md") if path.name != "README.md"
    } if DISPATCH_DIR.exists() else set()
    if check:
        stale = [
            path
            for path, content in wanted.items()
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        orphan = sorted(existing - set(wanted))
        if stale or orphan:
            print(f"FAIL: {len(stale)} stale, {len(orphan)} orphaned. Run `dispatch`.")
            return 1
        print(f"PASS: {len(wanted)} attribute dispatch prompt(s) match the brief and the slice")
        return 0
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(existing - set(wanted)):
        path.unlink()
    for path, content in wanted.items():
        # LF on every platform, so the brief's hash in the manifest matches
        # the bytes Git stores and a fresh clone verifies clean.
        path.write_text(content, encoding="utf-8", newline="\n")
    print(f"PASS: {len(wanted)} dispatch prompt(s) -> {DISPATCH_DIR}")
    return 0


def decided_lookup(rows: list[dict[str, str]] | None = None) -> dict[str, dict[str, str]]:
    """fund_id -> settled field values. Conflicts and empty statuses stay out."""

    lookup: dict[str, dict[str, str]] = {}
    for row in rows if rows is not None else read_csv(MATRIX):
        attrs = {
            field: row.get(field, "")
            for field in FIELDS
            if row.get(f"{field}_status") in SETTLED and row.get(field)
        }
        if attrs:
            lookup[row["fund_id"]] = attrs
    return lookup


def attribute_evidence_lookup(
    matrix: list[dict[str, str]] | None = None,
    observations: list[dict[str, str]] | None = None,
) -> dict[str, dict[str, dict[str, str]]]:
    """One reproducible printed source for each settled fund attribute."""

    matrix = matrix if matrix is not None else read_csv(MATRIX)
    observations = observations if observations is not None else read_csv(FACT_OBSERVATION)
    settled = decided_lookup(matrix)
    candidates: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        if row.get("subject_type") != "fund" or fund_id not in settled:
            continue
        for field, chosen in settled[fund_id].items():
            printed = (row.get(field) or "").strip()
            if printed and canon(field, printed) == canon(field, chosen):
                candidates[(fund_id, field)].append(row)

    evidence: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    missing = []
    for fund_id, attrs in sorted(settled.items()):
        for field, chosen in sorted(attrs.items()):
            found = sorted(
                candidates.get((fund_id, field), []),
                key=lambda row: (
                    row.get("document_id", ""),
                    int(row.get("source_page") or 0),
                    row.get("observation_id", ""),
                ),
            )
            if not found:
                missing.append(f"{fund_id}.{field}={chosen}")
                continue
            source = found[0]
            evidence[fund_id][field] = {
                "source_observation_id": source.get("observation_id", ""),
                "source_document_id": source.get("document_id", ""),
                "source_page": source.get("source_page", ""),
                "source_table": source.get("source_table", ""),
                "source_quote": source.get("evidence_quote", ""),
                "source_printed_value": source.get(field, ""),
            }
    if missing:
        raise ValueError(
            "settled fund attributes lack printed source observations: "
            + ", ".join(missing[:20])
        )
    return {fund_id: dict(fields) for fund_id, fields in evidence.items()}


def write_inherit_log(lookup: dict[str, dict[str, str]] | None = None) -> int:
    matrix = read_csv(MATRIX)
    status_by_fund = {row["fund_id"]: row for row in matrix}
    lookup = lookup if lookup is not None else decided_lookup(matrix)
    evidence = attribute_evidence_lookup(matrix)
    out = []
    for row in read_csv(FACT_OBSERVATION):
        fund_id = row.get("subject_entity_id", "")
        if row.get("subject_type") != "fund" or fund_id not in lookup:
            continue
        for field, value in lookup[fund_id].items():
            if (row.get(field) or "").strip():
                continue
            status = status_by_fund.get(fund_id, {}).get(f"{field}_status", "")
            source = evidence[fund_id][field]
            out.append({
                "observation_id": row.get("observation_id", ""),
                "fund_id": fund_id,
                "document_id": row.get("document_id", ""),
                "source_page": row.get("source_page", ""),
                "source_table": row.get("source_table", ""),
                "field": field,
                "printed_value": "",
                "inherited_value": value,
                "rule": f"{field}_status={status}",
                "source_observation_id": source["source_observation_id"],
                "source_document_id": source["source_document_id"],
                "source_evidence_page": source["source_page"],
                "source_evidence_table": source["source_table"],
                "source_evidence_quote": source["source_quote"],
                "source_printed_value": source["source_printed_value"],
            })
    write_csv(INHERIT_LOG, INHERIT_HEADER, out)
    return len(out)


def stamp_rows(rows: list[dict[str, str]], lookup: dict[str, dict[str, str]]) -> int:
    """Fill blank vintage_year and strategy from the matrix. Never overwrite print."""

    filled = 0
    for row in rows:
        attrs = lookup.get(row.get("fund_id", ""), {})
        for field in STAMP_FIELDS:
            if row.get(field):
                continue
            value = attrs.get(field, "")
            if value:
                row[field] = value
                filled += 1
    return filled


def stamp_rows_with_changes(
    rows: list[dict[str, str]],
    lookup: dict[str, dict[str, str]],
    evidence: dict[str, dict[str, dict[str, str]]],
    *,
    target_table: str,
    record_id_field: str,
    include_existing: bool = False,
) -> tuple[int, list[dict[str, str]]]:
    """Fill fund constants and return one source-backed row per affected cell."""

    filled = 0
    changes: list[dict[str, str]] = []
    matrix = {row["fund_id"]: row for row in read_csv(MATRIX) if row.get("fund_id")}
    for row in rows:
        fund_id = row.get("fund_id", "")
        attrs = lookup.get(fund_id, {})
        for field in STAMP_FIELDS:
            value = attrs.get(field, "")
            if not value:
                continue
            old_value = (row.get(field) or "").strip()
            if old_value and (not include_existing or old_value != value):
                continue
            if not old_value:
                row[field] = value
                filled += 1
                change_type = "INHERITED"
            else:
                change_type = "BASELINE_CONFIRMED"
            source = evidence[fund_id][field]
            target_record_id = row.get(record_id_field, "")
            seed = "|".join((target_table, target_record_id, field, value, source["source_observation_id"]))
            changes.append({
                "change_id": "AC_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20],
                "stage_id": "fund-constant-attributes",
                "target_table": target_table,
                "target_record_id": target_record_id,
                "fund_id": fund_id,
                "field": field,
                "old_value": old_value,
                "new_value": value,
                "change_type": change_type,
                **source,
                "rule_id": f"COPY_SETTLED_{field.upper()}",
                "matrix_status": matrix.get(fund_id, {}).get(f"{field}_status", ""),
                "notes": (
                    "Value already populated when cell-level lineage was introduced."
                    if change_type == "BASELINE_CONFIRMED"
                    else "Blank target filled from a printed value on the same fund."
                ),
            })
    return filled, changes


def write_attribute_changes(rows: list[dict[str, str]]) -> int:
    ordered = sorted(rows, key=lambda row: (row["target_table"], row["target_record_id"], row["field"]))
    write_csv(ATTRIBUTE_CHANGES, CHANGE_HEADER, ordered)
    return len(ordered)


def apply() -> int:
    lookup = decided_lookup()
    inherited = write_inherit_log(lookup)
    print(f"inherit log rows          {inherited:>6,}")
    print("fund-model cells filled          0")
    print("PASS: attribute audit written; promotion remains the sole fund-model writer")
    return 0


WRITES: dict[str, tuple[str, ...]] = {
    "harvest": ("data/normalization/fund-attributes-matrix.csv",),
    "autofill": ("data/normalization/fund-attributes-matrix.csv",),
    "conflicts": ("data/normalization/attribute-conflicts.csv",),
    "export": ("data/normalization/worksheets/attribute-conflicts.csv",),
    "merge": ("data/normalization/fund-attributes-matrix.csv",),
    "dispatch": ("instructions/02-fund-mapping/dispatch-prompts/attributes/",),
    "apply": (
        "data/extracted/audit/attribute-inherit.csv",
    ),
    "paths": (),
}

REPORT_ONLY = "prints a report; writes nothing"


def paths() -> int:
    width = max(len(verb) for verb in WRITES)
    for verb in sorted(WRITES):
        targets = WRITES[verb] or (f"({REPORT_ONLY})",)
        for index, target in enumerate(targets):
            print(f"  {verb if index == 0 else '':<{width}}  {target}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("paths", help="print the output file each command writes")
    sub.add_parser("harvest", help="one row per fund from printed observation context")
    sub.add_parser("autofill", help="report unique and spelling-collapsed values already on the matrix")
    conflict_parser = sub.add_parser("conflicts", help="funds whose printed attributes still disagree")
    conflict_parser.add_argument("--strict", action="store_true")
    sub.add_parser("export", help="write the conflict worksheet")
    sub.add_parser("merge", help="fold the conflict worksheet back into the matrix")
    dp = sub.add_parser(
        "dispatch",
        help="write the standing pasteable brief; keep it after the slice is settled",
    )
    dp.add_argument("--check", action="store_true")
    sub.add_parser("apply", help="write the inheritance audit; promotion owns fund-model writes")
    args = parser.parse_args()
    if args.command == "paths":
        sys.exit(paths())
    if args.command == "harvest":
        sys.exit(harvest())
    if args.command == "autofill":
        sys.exit(autofill())
    if args.command == "conflicts":
        sys.exit(conflicts(args.strict))
    if args.command == "export":
        sys.exit(export_worksheet())
    if args.command == "merge":
        sys.exit(merge_worksheet())
    if args.command == "dispatch":
        sys.exit(dispatch(args.check))
    if args.command == "apply":
        sys.exit(apply())


if __name__ == "__main__":
    main()
