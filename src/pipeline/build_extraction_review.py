"""Build reviewer tables from extraction candidates, decisions, and published facts.

The command writes summaries and lineage records. It does not change extraction
candidates, adjudication decisions, published observations, or relational facts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.catalog.simple_pdf_extraction.csv_wide_contract import (
    RECORD_COLUMNS,
    normalize_key_text,
    record_key,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKING_ROOT = PROJECT_ROOT / "ledgers" / "working" / "pdf-extraction-csv"
FACT_PATH = PROJECT_ROOT / "data" / "extracted" / "tables" / "fact_observation.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "extracted" / "review"
TABLE_LINEAGE_PATH = PROJECT_ROOT / "data" / "extracted" / "tables" / "observation_lineage.csv"
TABLE_MANIFEST_PATH = PROJECT_ROOT / "data" / "extracted" / "tables" / "MANIFEST.csv"

DOCUMENT_COLUMNS = (
    "route",
    "file_id",
    "source_sha256",
    "physical_pages",
    "pages_with_data",
    "extractor_a_rows",
    "extractor_b_rows",
    "pair_rows",
    "physical_pairs",
    "raw_value_agreements",
    "raw_value_agreement_rate",
    "value_conflicts",
    "classification_conflicts",
    "context_conflicts",
    "exact_all_field_pairs",
    "a_only",
    "b_only",
    "merge_decisions",
    "accept_a_decisions",
    "accept_b_decisions",
    "add_decisions",
    "reject_decisions",
    "final_rows",
)

DISAGREEMENT_COLUMNS = (
    "pair_status",
    "field_name",
    "difference_count",
    "document_count",
)

LINEAGE_COLUMNS = (
    "observation_id",
    "route",
    "file_id",
    "source_page",
    "source_table",
    "source_row_label",
    "source_column_label",
    "source_occurrence",
    "record_family",
    "metric_category",
    "metric_value_raw",
    "unit",
    "pair_id",
    "pair_status",
    "difference_fields",
    "a_row_number",
    "b_row_number",
    "resolution_row_number",
    "resolution_decision",
    "resolution_reason",
    "final_row_number",
    "source_agents",
    "adjudication_status",
    "source_sha256",
    "source_pdf_path",
    "records_a_path",
    "records_b_path",
    "pair_index_path",
    "resolution_path",
    "records_final_path",
)

TABLE_LINEAGE_COLUMNS = (
    "observation_id",
    "document_id",
    "source_page",
    "pair_id",
    "pair_status",
    "a_row_number",
    "b_row_number",
    "difference_fields",
    "resolution_decision",
    "resolution_reason",
    "adjudication_status",
    "source_agents",
    "source_sha256",
)

TRACE_COLUMNS = (
    *LINEAGE_COLUMNS,
    "subject_type",
    "subject_name",
    "as_of_date",
    "period_start",
    "period_end",
    "evidence_quote",
)

SIGNATURE_IGNORED = {
    "agent_role",
    "source_agents",
    "adjudication_status",
    "extractor_model",
    "notes",
}


class ReviewBuildError(RuntimeError):
    """Raised when the reviewer outputs cannot tie to the working evidence."""


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ReviewBuildError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ReviewBuildError(f"Missing CSV header: {path}")
        return [dict(row) for row in reader]


def csv_text(
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
    *,
    quoting: int = csv.QUOTE_ALL,
) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(columns),
        extrasaction="raise",
        quoting=quoting,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()


def table_lineage_text(review_lineage_text: str) -> str:
    review_rows = csv.DictReader(io.StringIO(review_lineage_text))
    rows = (
        {
            "observation_id": row.get("observation_id", ""),
            "document_id": row.get("file_id", ""),
            "source_page": row.get("source_page", ""),
            "pair_id": row.get("pair_id", ""),
            "pair_status": row.get("pair_status", ""),
            "a_row_number": row.get("a_row_number", ""),
            "b_row_number": row.get("b_row_number", ""),
            "difference_fields": row.get("difference_fields", ""),
            "resolution_decision": row.get("resolution_decision", ""),
            "resolution_reason": row.get("resolution_reason", ""),
            "adjudication_status": row.get("adjudication_status", ""),
            "source_agents": row.get("source_agents", ""),
            "source_sha256": row.get("source_sha256", ""),
        }
        for row in review_rows
    )
    return csv_text(TABLE_LINEAGE_COLUMNS, rows, quoting=csv.QUOTE_MINIMAL)


def table_manifest_text(
    root: Path, lineage_rows: int, table_dir: Path | None = None
) -> str:
    table_dir = table_dir or root / "data" / "extracted" / "tables"
    path = table_dir / "MANIFEST.csv"
    rows = [row for row in read_rows(path) if row.get("table") != "observation_lineage"]
    rows.append(
        {
            "table": "observation_lineage",
            "file": "observation_lineage.csv",
            "rows": str(lineage_rows),
        }
    )
    rows.sort(key=lambda row: row.get("table", ""))
    return csv_text(("table", "file", "rows"), rows, quoting=csv.QUOTE_MINIMAL)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(text, encoding="utf-8", newline="")
    temporary.replace(path)


def signature(row: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        normalize_key_text(row.get(column, ""))
        for column in RECORD_COLUMNS
        if column not in SIGNATURE_IGNORED
    )


def fact_key(row: Mapping[str, str], *, published: bool) -> tuple[str, ...]:
    if published:
        return (
            row.get("file_id", ""),
            row.get("source_page", ""),
            row.get("source_table", ""),
            row.get("source_row_label", ""),
            row.get("source_column_label", ""),
            row.get("source_occurrence", ""),
            row.get("record_family", ""),
            row.get("metric_category", ""),
            row.get("metric_name", ""),
        )
    return (
        row.get("document_id", ""),
        row.get("source_page", ""),
        row.get("source_table", ""),
        row.get("source_row_label", ""),
        row.get("source_column_label", ""),
        row.get("source_occurrence", ""),
        row.get("record_family", ""),
        row.get("metric_category", ""),
        row.get("metric_name", ""),
    )


def normalized_fact_key(row: Mapping[str, str], *, published: bool) -> tuple[str, ...]:
    return tuple(normalize_key_text(value) for value in fact_key(row, published=published))


def data_folders(root: Path) -> list[Path]:
    return sorted(
        folder
        for folder in root.glob("*/*")
        if folder.is_dir() and (folder / "records-final.csv").is_file()
    )


def selected_record(
    pair: Mapping[str, str],
    a_rows: Sequence[dict[str, str]],
    b_rows: Sequence[dict[str, str]],
    resolution: Mapping[str, str] | None,
) -> tuple[dict[str, str] | None, str, str]:
    a_number = pair.get("a_row_number", "")
    b_number = pair.get("b_row_number", "")
    a_row = a_rows[int(a_number) - 1] if a_number else None
    b_row = b_rows[int(b_number) - 1] if b_number else None
    if pair.get("requires_review") == "NO":
        if a_row is None or b_row is None or pair.get("pair_status") != "EXACT":
            raise ReviewBuildError(f"Invalid automatic pair {pair.get('pair_id')}")
        return dict(a_row), "CONFIRM", "Automatic exact pair"
    if resolution is None:
        raise ReviewBuildError(f"Missing resolution for {pair.get('pair_id')}")
    decision = resolution.get("decision", "")
    reason = resolution.get("reason", "")
    if decision == "REJECT":
        return None, decision, reason
    if decision == "CONFIRM":
        if a_row is None:
            raise ReviewBuildError(f"CONFIRM has no A row: {pair.get('pair_id')}")
        return dict(a_row), decision, reason
    if decision == "ACCEPT_A":
        if a_row is None:
            raise ReviewBuildError(f"ACCEPT_A has no A row: {pair.get('pair_id')}")
        return dict(a_row), decision, reason
    if decision == "ACCEPT_B":
        if b_row is None:
            raise ReviewBuildError(f"ACCEPT_B has no B row: {pair.get('pair_id')}")
        return dict(b_row), decision, reason
    if decision == "MERGE":
        return {column: resolution.get(column, "") for column in RECORD_COLUMNS}, decision, reason
    raise ReviewBuildError(f"Unsupported decision {decision!r}: {pair.get('pair_id')}")


def build_outputs(
    root: Path = PROJECT_ROOT, table_dir: Path | None = None
) -> dict[str, str]:
    working_root = root / "ledgers" / "working" / "pdf-extraction-csv"
    table_dir = table_dir or root / "data" / "extracted" / "tables"
    facts = read_rows(table_dir / "fact_observation.csv")
    routing_rows = read_rows(root / "data" / "schemas" / "EXTRACTION-ROUTING.csv")
    routing = {row.get("file_id", ""): row for row in routing_rows}
    ledger_rows = read_rows(root / "data-gathering" / "source_ledger.csv")
    source_ledger = {row.get("file_id", ""): row for row in ledger_rows}
    fact_exact: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    fact_normalized: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for fact in facts:
        fact_exact[fact_key(fact, published=False)].append(fact)
        fact_normalized[normalized_fact_key(fact, published=False)].append(fact)

    document_rows: list[dict[str, object]] = []
    lineage_rows: list[dict[str, str]] = []
    disagreement_counts: Counter[tuple[str, str]] = Counter()
    disagreement_documents: dict[tuple[str, str], set[str]] = defaultdict(set)

    for folder in data_folders(working_root):
        route = folder.parent.name
        file_id = folder.name
        route_row = routing.get(file_id, {})
        ledger_row = source_ledger.get(file_id, {})
        route_candidates = sorted(
            {
                Path(str(value).split("?", 1)[0]).name
                for value in route_row.values()
                if value and str(value).split("?", 1)[0].casefold().endswith(".pdf")
            }
        )
        ledger_candidates = sorted(
            {
                Path(str(value).split("?", 1)[0]).name
                for value in ledger_row.values()
                if value and str(value).split("?", 1)[0].casefold().endswith(".pdf")
            }
        )
        source_candidates = route_candidates if len(route_candidates) == 1 else ledger_candidates
        source_pdf_path = (
            f"data/documents/pdf/{source_candidates[0]}" if len(source_candidates) == 1 else ""
        )
        working_prefix = f"ledgers/working/pdf-extraction-csv/{route}/{file_id}"
        a_rows = read_rows(folder / "records-a.csv")
        b_rows = read_rows(folder / "records-b.csv")
        final_rows = read_rows(folder / "records-final.csv")
        coverage = read_rows(folder / "coverage-final.csv")
        pairs = read_rows(folder / "pair-index.csv")
        resolution_rows = read_rows(folder / "resolution.csv")
        resolution_map: dict[str, tuple[int, dict[str, str]]] = {}
        additions: list[tuple[int, dict[str, str]]] = []
        for number, row in enumerate(resolution_rows, 1):
            if row.get("decision") == "ADD":
                additions.append((number, row))
            elif row.get("pair_id"):
                resolution_map[row["pair_id"]] = (number, row)

        pair_counts = Counter(row.get("pair_status", "") for row in pairs)
        decisions = Counter(row.get("decision", "") for row in resolution_rows)
        for pair in pairs:
            status = pair.get("pair_status", "")
            for field in filter(None, pair.get("difference_fields", "").split("|")):
                key = (status, field)
                disagreement_counts[key] += 1
                disagreement_documents[key].add(file_id)

        expected: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
        expected_physical: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
        for pair in pairs:
            pair_id = pair.get("pair_id", "")
            resolution_item = resolution_map.get(pair_id)
            resolution = resolution_item[1] if resolution_item else None
            record, decision, reason = selected_record(pair, a_rows, b_rows, resolution)
            if record is None:
                continue
            metadata = {
                "pair_id": pair_id,
                "pair_status": pair.get("pair_status", ""),
                "difference_fields": pair.get("difference_fields", ""),
                "a_row_number": pair.get("a_row_number", ""),
                "b_row_number": pair.get("b_row_number", ""),
                "resolution_row_number": str(resolution_item[0]) if resolution_item else "",
                "resolution_decision": decision,
                "resolution_reason": reason,
                "record": record,
            }
            expected[signature(record)].append(metadata)
            expected_physical[record_key(record)].append(metadata)
        for resolution_number, addition in additions:
            record = {column: addition.get(column, "") for column in RECORD_COLUMNS}
            metadata = {
                "pair_id": "",
                "pair_status": "ADJUDICATOR_ADD",
                "difference_fields": "",
                "a_row_number": "",
                "b_row_number": "",
                "resolution_row_number": str(resolution_number),
                "resolution_decision": "ADD",
                "resolution_reason": addition.get("reason", ""),
                "record": record,
            }
            expected[signature(record)].append(metadata)
            expected_physical[record_key(record)].append(metadata)

        source_sha256 = ""
        for final_number, final in enumerate(final_rows, 1):
            source_sha256 = final.get("source_sha256", source_sha256)
            candidates = expected.get(signature(final), [])
            metadata = candidates.pop(0) if candidates else None
            if metadata is None:
                physical = expected_physical.get(record_key(final), [])
                if len(physical) == 1:
                    metadata = physical.pop(0)
                elif physical:
                    same_value = [
                        item
                        for item in physical
                        if normalize_key_text(item["record"].get("metric_value_raw", ""))
                        == normalize_key_text(final.get("metric_value_raw", ""))
                        and normalize_key_text(item["record"].get("metric_category", ""))
                        == normalize_key_text(final.get("metric_category", ""))
                    ]
                    if len(same_value) == 1:
                        metadata = same_value[0]
                        physical.remove(metadata)
            if metadata is None:
                raise ReviewBuildError(f"No A/B or adjudication lineage for {file_id} final row {final_number}")

            matching_facts = fact_exact.get(fact_key(final, published=True), [])
            if len(matching_facts) != 1:
                matching_facts = fact_normalized.get(normalized_fact_key(final, published=True), [])
            if len(matching_facts) != 1:
                raise ReviewBuildError(
                    f"Final row does not map to one fact_observation: {file_id} row {final_number}; matches={len(matching_facts)}"
                )
            observation_id = matching_facts[0]["observation_id"]
            lineage_rows.append(
                {
                    "observation_id": observation_id,
                    "route": route,
                    "file_id": file_id,
                    "source_page": final.get("source_page", ""),
                    "source_table": final.get("source_table", ""),
                    "source_row_label": final.get("source_row_label", ""),
                    "source_column_label": final.get("source_column_label", ""),
                    "source_occurrence": final.get("source_occurrence", ""),
                    "record_family": final.get("record_family", ""),
                    "metric_category": final.get("metric_category", ""),
                    "metric_value_raw": final.get("metric_value_raw", ""),
                    "unit": final.get("unit", ""),
                    "pair_id": metadata["pair_id"],
                    "pair_status": metadata["pair_status"],
                    "difference_fields": metadata["difference_fields"],
                    "a_row_number": metadata["a_row_number"],
                    "b_row_number": metadata["b_row_number"],
                    "resolution_row_number": metadata["resolution_row_number"],
                    "resolution_decision": metadata["resolution_decision"],
                    "resolution_reason": metadata["resolution_reason"],
                    "final_row_number": str(final_number),
                    "source_agents": final.get("source_agents", ""),
                    "adjudication_status": final.get("adjudication_status", ""),
                    "source_sha256": final.get("source_sha256", ""),
                    "source_pdf_path": source_pdf_path,
                    "records_a_path": f"{working_prefix}/records-a.csv",
                    "records_b_path": f"{working_prefix}/records-b.csv",
                    "pair_index_path": f"{working_prefix}/pair-index.csv",
                    "resolution_path": f"{working_prefix}/resolution.csv",
                    "records_final_path": f"{working_prefix}/records-final.csv",
                    "_subject_type": final.get("subject_type", ""),
                    "_subject_name": final.get("subject_name", ""),
                    "_as_of_date": final.get("as_of_date", ""),
                    "_period_start": final.get("period_start", ""),
                    "_period_end": final.get("period_end", ""),
                    "_evidence_quote": final.get("evidence_quote", ""),
                }
            )

        physical_pairs = len(pairs) - pair_counts["A_ONLY"] - pair_counts["B_ONLY"]
        value_agreements = physical_pairs - pair_counts["VALUE_CONFLICT"]
        document_rows.append(
            {
                "route": route,
                "file_id": file_id,
                "source_sha256": source_sha256,
                "physical_pages": len(coverage),
                "pages_with_data": sum(row.get("page_status") == "ELIGIBLE_DATA_EXTRACTED" for row in coverage),
                "extractor_a_rows": len(a_rows),
                "extractor_b_rows": len(b_rows),
                "pair_rows": len(pairs),
                "physical_pairs": physical_pairs,
                "raw_value_agreements": value_agreements,
                "raw_value_agreement_rate": f"{value_agreements / physical_pairs:.6f}" if physical_pairs else "",
                "value_conflicts": pair_counts["VALUE_CONFLICT"],
                "classification_conflicts": pair_counts["CLASSIFICATION_CONFLICT"],
                "context_conflicts": pair_counts["CONTEXT_CONFLICT"],
                "exact_all_field_pairs": pair_counts["EXACT"],
                "a_only": pair_counts["A_ONLY"],
                "b_only": pair_counts["B_ONLY"],
                "merge_decisions": decisions["MERGE"],
                "accept_a_decisions": decisions["ACCEPT_A"],
                "accept_b_decisions": decisions["ACCEPT_B"],
                "add_decisions": decisions["ADD"],
                "reject_decisions": decisions["REJECT"],
                "final_rows": len(final_rows),
            }
        )

    if len(lineage_rows) != len(facts):
        raise ReviewBuildError(
            f"Lineage rows {len(lineage_rows)} differ from fact observations {len(facts)}"
        )
    observation_ids = [row["observation_id"] for row in lineage_rows]
    if len(observation_ids) != len(set(observation_ids)):
        raise ReviewBuildError("Observation lineage contains duplicate observation IDs")

    disagreement_rows = [
        {
            "pair_status": status,
            "field_name": field,
            "difference_count": count,
            "document_count": len(disagreement_documents[(status, field)]),
        }
        for (status, field), count in sorted(
            disagreement_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]

    preferred = {"SRC035": 0, "SRC384": 1, "SRC457": 2}
    ordered_lineage = sorted(
        lineage_rows,
        key=lambda row: (
            preferred.get(row["file_id"], 9),
            row["pair_status"],
            int(row["source_page"] or 0),
            int(row["final_row_number"]),
        ),
    )
    trace_rows: list[dict[str, str]] = []
    selected_counts: Counter[str] = Counter()
    for row in ordered_lineage:
        status = row["pair_status"]
        if selected_counts[status] >= 2:
            continue
        selected_counts[status] += 1
        trace_rows.append(
            {
                **{column: row.get(column, "") for column in LINEAGE_COLUMNS},
                "subject_type": row.get("_subject_type", ""),
                "subject_name": row.get("_subject_name", ""),
                "as_of_date": row.get("_as_of_date", ""),
                "period_start": row.get("_period_start", ""),
                "period_end": row.get("_period_end", ""),
                "evidence_quote": row.get("_evidence_quote", ""),
            }
        )

    # The folder guide is written by src.repository.build_readmes with every
    # other guide; a second writer here would leave the two disagreeing.
    queries ="""-- Open with: duckdb data/warehouse/extracted.duckdb\n\n-- Table and view inventory.\nSELECT table_name, table_type\nFROM information_schema.tables\nWHERE table_schema = 'main'\nORDER BY table_type, table_name;\n\n-- Observation counts by document and record family.\nSELECT document_id, record_family, COUNT(*) AS observations\nFROM fact_observation\nGROUP BY document_id, record_family\nORDER BY document_id, observations DESC;\n\n-- Entity resolution coverage.\nSELECT\n  subject_type,\n  COUNT(*) AS observations,\n  COUNT(subject_entity_id) AS resolved_observations,\n  COUNT(DISTINCT subject_entity_id) AS resolved_entities\nFROM fact_observation\nGROUP BY subject_type\nORDER BY observations DESC;\n\n-- Metric coverage.\nSELECT record_family, metric_category, COUNT(*) AS observations\nFROM fact_observation\nGROUP BY record_family, metric_category\nORDER BY record_family, observations DESC;\n\n-- Replace the value with an ID from trace-sample.csv.\nSELECT *\nFROM fact_observation\nWHERE observation_id = 'OBSERVATION_ID';\n\n-- Wide-row lineage back to printed cells.\nSELECT b.pivot_table, b.pivot_row_id, b.observation_id, f.document_id,\n       f.source_page, f.source_row_label, f.source_column_label,\n       f.metric_category, f.value_raw, f.evidence_quote\nFROM bridge_pivot_observation AS b\nJOIN fact_observation AS f USING (observation_id)\nORDER BY b.pivot_table, b.pivot_row_id, f.observation_id;\n"""

    return {
        "document-summary.csv": csv_text(DOCUMENT_COLUMNS, document_rows),
        "disagreement-fields.csv": csv_text(DISAGREEMENT_COLUMNS, disagreement_rows),
        "observation-lineage.csv": csv_text(
            LINEAGE_COLUMNS,
            ({column: row.get(column, "") for column in LINEAGE_COLUMNS} for row in lineage_rows),
        ),
        "trace-sample.csv": csv_text(TRACE_COLUMNS, trace_rows),
        "reviewer-queries.sql": queries,
    }


def build(
    output_dir: Path = DEFAULT_OUTPUT,
    root: Path = PROJECT_ROOT,
    table_dir: Path | None = None,
) -> dict[str, int]:
    table_dir = table_dir or root / "data" / "extracted" / "tables"
    outputs = build_outputs(root, table_dir)
    counts: dict[str, int] = {}
    for name, text in outputs.items():
        write_text(output_dir / name, text)
        counts[name] = text.count("\n") - (1 if text.endswith("\n") else 0)
    star_text = table_lineage_text(outputs["observation-lineage.csv"])
    star_path = table_dir / "observation_lineage.csv"
    write_text(star_path, star_text)
    star_rows = star_text.count("\n") - (1 if star_text.endswith("\n") else 0)
    manifest_text = table_manifest_text(root, star_rows, table_dir)
    write_text(table_dir / "MANIFEST.csv", manifest_text)
    counts["tables/observation_lineage.csv"] = star_rows
    counts["tables/MANIFEST.csv"] = len(read_rows(table_dir / "MANIFEST.csv"))
    return counts


def check(
    output_dir: Path = DEFAULT_OUTPUT,
    root: Path = PROJECT_ROOT,
    table_dir: Path | None = None,
) -> None:
    table_dir = table_dir or root / "data" / "extracted" / "tables"
    outputs = build_outputs(root, table_dir)
    errors: list[str] = []
    for name, expected in outputs.items():
        path = output_dir / name
        if not path.is_file():
            errors.append(f"missing {path}")
            continue
        actual = path.read_text(encoding="utf-8-sig")
        if actual != expected:
            errors.append(f"stale {path}")
    expected_star = table_lineage_text(outputs["observation-lineage.csv"])
    star_path = table_dir / "observation_lineage.csv"
    if not star_path.is_file() or star_path.read_text(encoding="utf-8-sig") != expected_star:
        errors.append(f"stale {star_path}")
    expected_manifest = table_manifest_text(
        root, expected_star.count("\n") - 1, table_dir
    )
    manifest_path = table_dir / "MANIFEST.csv"
    if not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8-sig") != expected_manifest:
        errors.append(f"stale {manifest_path}")
    if errors:
        raise ReviewBuildError("Review outputs differ from the evidence:\n- " + "\n- ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--table-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "extracted" / "tables",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            check(args.output_dir.resolve(), table_dir=args.table_dir.resolve())
            print("PASS: extraction review outputs match the working evidence")
        else:
            counts = build(
                args.output_dir.resolve(), table_dir=args.table_dir.resolve()
            )
            for name, count in counts.items():
                print(f"{name}: {count} line(s)")
    except (ReviewBuildError, OSError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
