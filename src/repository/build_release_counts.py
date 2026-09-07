"""Write the one file every reviewer-facing count is read from.

Six numbers a reviewer sees on the landing page and the dashboard disagreed
with the data behind them: the page said 7,201 observations while the cards
said 7,284, and the prose said 42 record columns against a contract of 47. Each
number had been typed into prose and then left behind by a release.

This counts the published release once and writes the answers to
`docs/RELEASE-COUNTS.csv`. Prose that states a number cites this file, and
`tests/test_release_counts.py` fails when a document states a number this file
contradicts.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalog.simple_pdf_extraction.csv_wide_contract import (  # noqa: E402
    CONTRACT_VERSION,
    CANONICAL_DOC_TYPES,
    METRIC_CATEGORIES,
    RECORD_COLUMNS,
)

OUTPUT = PROJECT_ROOT / "docs" / "RELEASE-COUNTS.csv"
COLUMNS = ("name", "value", "source", "note")

FACT_OBSERVATION = "data/extracted/tables/fact_observation.csv"
QUALIFIER_BACKLOG = "ledgers/pipeline/qualifier-backlog.csv"
EXTRACTION_SCOPE = "ledgers/pipeline/extraction-scope.csv"
CATEGORY_CSV = "docs/EXTRACTION-CATEGORY-COVERAGE.csv"
CATEGORY_MD = "docs/EXTRACTION-CATEGORY-COVERAGE.md"
CATEGORY_COLUMNS = (
    "file_id", "canonical_doc_type", "filename", "issuer", "page_count", "route",
    "dispatch_scope", "published_pages", "pdf_path", "txt_path", "image_dir",
    "grid_path", "candidate_folder", "source",
)


def rows_in(relative: str) -> int:
    path = PROJECT_ROOT / relative
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for row in reader if row and any(cell.strip() for cell in row))


def distinct_in(relative: str, column: str) -> int:
    path = PROJECT_ROOT / relative
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return len({row[column] for row in csv.DictReader(handle) if row.get(column)})


def summed_in(relative: str, column: str) -> int:
    """Add one column of a per-document summary into a release total."""

    path = PROJECT_ROOT / relative
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return sum(int(row[column]) for row in csv.DictReader(handle) if row.get(column))


def matching_in(relative: str, column: str, value: str) -> int:
    path = PROJECT_ROOT / relative
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return sum(1 for row in csv.DictReader(handle) if row.get(column) == value)


def blank_in(relative: str, column: str) -> int:
    path = PROJECT_ROOT / relative
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return sum(1 for row in csv.DictReader(handle) if not row.get(column))


def read_rows(relative: str) -> list[dict[str, str]]:
    path = PROJECT_ROOT / relative
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def return_count_name(method: str, fee_basis: str) -> str:
    return f"return_rows_{method or 'blank'}_{fee_basis or 'blank'}"


def return_qualifier_counts(relative: str = FACT_OBSERVATION) -> list[tuple[str, str, int]]:
    """Published return rows by the pair of qualifiers each one states.

    A percentage is a different number under a different calculation method and
    a different fee basis, so one return total answers no reviewer question.
    The release counts each (method, fee_basis) pair and every sentence that
    states a return figure states the pair beside it.
    """

    tally: Counter[tuple[str, str]] = Counter()
    for row in read_rows(relative):
        if row.get("metric_category", "").strip() != "return":
            continue
        tally[(row.get("method", "").strip(), row.get("fee_basis", "").strip())] += 1
    return [
        (method, fee_basis, count)
        for (method, fee_basis), count in sorted(
            tally.items(), key=lambda item: (-item[1], item[0])
        )
    ]


def backlog_count_name(file_id: str) -> str:
    return f"qualifier_backlog_{file_id}"


def qualifier_backlog(relative: str = QUALIFIER_BACKLOG) -> list[tuple[str, str, int]]:
    """Published rows blank in a qualified dimension, per document.

    Their own `contract_version` predates the column, so the blank records that
    nobody read the dimension. Page reading writes the value or `unstated` and
    takes this list to zero.
    """

    tally: Counter[tuple[str, str]] = Counter()
    for row in read_rows(relative):
        tally[(row.get("route", ""), row.get("file_id", ""))] += int(row.get("row_count") or 0)
    return [(route, file_id, count) for (route, file_id), count in sorted(tally.items())]


def unfinished_documents(relative: str = EXTRACTION_SCOPE) -> list[str]:
    """Documents in the active scope with no `records-final.csv`."""

    names: list[str] = []
    for row in read_rows(relative):
        names.extend(
            part.strip()
            for part in row.get("unfinished_documents", "").split("|")
            if part.strip()
        )
    return sorted(names)


def counts() -> list[dict[str, str]]:
    published = "data/extracted/pdf-wide-records.csv"
    summary = "data/extracted/review/document-summary.csv"
    measured = [
        ("contract_version", CONTRACT_VERSION, "csv_wide_contract.CONTRACT_VERSION",
         "The record field list in force."),
        ("record_columns", len(RECORD_COLUMNS), "record-columns.csv",
         "Columns every extractor writes on every row."),
        ("metric_categories", len(METRIC_CATEGORIES), "metric-vocabulary.csv",
         "Controlled metric names."),
        # A document that prints nothing this route may extract is published
        # with full page coverage and no observation, so the document count
        # comes from coverage. SRC147 is one, and counting records instead
        # reports 28 where the release published 29.
        ("published_documents",
         distinct_in("data/extracted/pdf-wide-coverage.csv", "file_id"),
         "data/extracted/pdf-wide-coverage.csv",
         "Documents with completed extraction and page coverage."),
        ("documents_with_observations", distinct_in(published, "file_id"), published,
         "Published documents with accepted source records."),
        ("published_observations", rows_in(published), published,
         "Accepted source records, including values, definitions and document context."),
        ("published_pages", rows_in("data/extracted/pdf-wide-coverage.csv"),
         "data/extracted/pdf-wide-coverage.csv", "Pages carrying a coverage row."),
        ("transformation_matrices",
         len(list((PROJECT_ROOT / "data/normalization/transformations").glob("*.csv"))),
         "data/normalization/transformations", "Decision matrices."),
        ("fund_identities", rows_in("data/csv/fund_master.csv"), "data/csv/fund_master.csv",
         "Funds in the integrated model."),
        ("fund_periods", rows_in("data/csv/fund_periods.csv"), "data/csv/fund_periods.csv",
         "Periods in the integrated model."),
        ("quality_results", rows_in("data/csv/quality_results.csv"),
         "data/csv/quality_results.csv",
         "Quality-rule evaluations over the completed fund model."),
        ("source_only_quality_results",
         rows_in("data/extracted/fund-level/quality_results.csv"),
         "data/extracted/fund-level/quality_results.csv",
         "Quality-rule evaluations over the printed rows alone, before any fill."),
        ("pme_results", rows_in("data/csv/pme_results.csv"), "data/csv/pme_results.csv",
         "Kaplan-Schoar PME and Direct Alpha rows."),
        # The two-reader numbers. A release stated 7,201 observations for a
        # while and passed this gate because the gate held twelve counts and
        # none of them was a reading count. Everything a reviewer file states
        # about the extraction is measured here.
        ("extractor_a_rows", summed_in(summary, "extractor_a_rows"), summary,
         "Candidate rows the first reader wrote across the published documents."),
        ("extractor_b_rows", summed_in(summary, "extractor_b_rows"), summary,
         "Candidate rows the second reader wrote across the published documents."),
        ("physical_ab_pairs", summed_in(summary, "physical_pairs"), summary,
         "Page locations both readers wrote a row for."),
        ("raw_value_agreements", summed_in(summary, "raw_value_agreements"), summary,
         "Two-reader pairs whose printed value or text matched."),
        ("value_conflicts", summed_in(summary, "value_conflicts"), summary,
         "Two-reader pairs whose printed value disagreed and went to adjudication."),
        ("reconstructed_wide_tables",
         len(list((PROJECT_ROOT / "data/extracted/wide").glob("wide_*.csv"))),
         "data/extracted/wide", "Record families rebuilt as one table per family."),
        # The fund model separates what a page printed from what the completion
        # wrote. Both populations are reviewer-facing and both drifted.
        ("source_backed_fund_periods", rows_in("data/extracted/fund-level/fund_periods.csv"),
         "data/extracted/fund-level/fund_periods.csv",
         "Fund periods built only from printed values."),
        ("source_only_fund_metrics", rows_in("data/extracted/fund-level/fund_metrics.csv"),
         "data/extracted/fund-level/fund_metrics.csv",
         "Multiples computed from printed values alone."),
        ("fund_observations", rows_in("data/extracted/fund-level/fund_observations.csv"),
         "data/extracted/fund-level/fund_observations.csv",
         "Evidence rows promoted to the fund model."),
        ("unmapped_fund_observations",
         blank_in("data/extracted/fund-level/fund_observations.csv", "canonical_measure_id"),
         "data/extracted/fund-level/fund_observations.csv",
         "Promoted rows no semantic-map rule has yet assigned a listed measure."),
        # The completion's own record. A reviewer judging how much of the model
        # is printed reads these three.
        ("cell_lineage_rows", rows_in("data/integrated/cell-lineage.csv"),
         "data/integrated/cell-lineage.csv",
         "Fund-model field values with a recorded origin."),
        ("gap_rows", rows_in("data/integrated/gap-ledger.csv"),
         "data/integrated/gap-ledger.csv", "Blank fund-model fields the completion recorded."),
        ("open_gaps", matching_in("data/integrated/gap-ledger.csv", "status", "OPEN"),
         "data/integrated/gap-ledger.csv",
         "Recorded blanks the corpus prints nothing to close; they stay blank."),
        ("imputed_cells",
         matching_in("data/integrated/cell-lineage.csv", "provenance_type", "IMPUTED"),
         "data/integrated/cell-lineage.csv",
         "Fund-model cells a declared rule filled; imputation_method names the rule."),
    ]
    # Returns, split. A release that states 1,117 returns and nothing else has
    # told a reviewer how many are net of fees and how many were computed the
    # same way, which is the whole of what the number is for.
    returns = return_qualifier_counts()
    measured.append(
        ("return_rows", sum(count for _, _, count in returns), FACT_OBSERVATION,
         "Published return rows; the pair counts below carry the split.")
    )
    measured.extend(
        (return_count_name(method, fee_basis), count, FACT_OBSERVATION,
         f"Published return rows computed {method or 'blank'} on a "
         f"{fee_basis or 'blank'} fee basis.")
        for method, fee_basis, count in returns
    )
    # The two boundaries the extraction declares: rows nobody read a dimension
    # for, and documents nobody has finished reading.
    backlog = qualifier_backlog()
    measured.append(
        ("qualifier_backlog_rows", sum(count for _, _, count in backlog), QUALIFIER_BACKLOG,
         "Published rows blank in a qualified dimension their own contract predates.")
    )
    measured.append(
        ("qualifier_backlog_documents", len(backlog), QUALIFIER_BACKLOG,
         "Documents holding those rows.")
    )
    measured.extend(
        (backlog_count_name(file_id), count, QUALIFIER_BACKLOG,
         f"Blank-qualifier rows in {file_id}, route {route}.")
        for route, file_id, count in backlog
    )
    unfinished = unfinished_documents()
    measured.append(
        ("unfinished_documents", len(unfinished), EXTRACTION_SCOPE,
         "Documents in the active scope with no final: "
         + (", ".join(unfinished) or "none") + ".")
    )
    return [
        {"name": name, "value": str(value), "source": source, "note": note}
        for name, value, source, note in measured
    ]


def category_documents() -> list[dict[str, str]]:
    """Join published page coverage and active assignments to source categories."""
    sources = {row["file_id"]: row for row in read_rows("data-gathering/source_ledger.csv")}
    routing = {row["file_id"]: row for row in read_rows("data/schemas/EXTRACTION-ROUTING.csv")}
    scope = {row["file_id"]: row for row in read_rows("data/schemas/EXTRACTION-DISPATCH-SCOPE.csv")}
    pages = Counter(row["file_id"] for row in read_rows("data/extracted/pdf-wide-coverage.csv"))
    selected = set(pages) | {key for key, row in scope.items() if row["dispatch_scope"] == "ACTIVE"}
    result = []
    for file_id in sorted(selected):
        if any(file_id not in table for table in (sources, routing, scope)):
            raise ValueError(f"{file_id}: category report requires source, routing and scope rows")
        source, route = sources[file_id], routing[file_id]
        category = source["doc_type"]
        if category not in CANONICAL_DOC_TYPES or category != route["canonical_doc_type"]:
            raise ValueError(f"{file_id}: source and routing categories disagree")
        result.append({
            **{field: route[field] for field in CATEGORY_COLUMNS if field in route},
            "file_id": file_id, "canonical_doc_type": category,
            "dispatch_scope": scope[file_id]["dispatch_scope"],
            "published_pages": str(pages[file_id]),
            "candidate_folder": f"ledgers/working/pdf-extraction-csv/{route['route']}/{file_id}",
            "source": "data-gathering/source_ledger.csv|data/extracted/pdf-wide-coverage.csv|data/schemas/EXTRACTION-DISPATCH-SCOPE.csv",
        })
    return result


def category_markdown(documents: list[dict[str, str]]) -> str:
    """Format report categories, completed documents and pending assignments."""
    corpus = Counter(row["doc_type"] for row in read_rows("data-gathering/source_ledger.csv"))
    completed = [row for row in documents if int(row["published_pages"]) > 0]
    pending = [row for row in documents if row["published_pages"] == "0"]
    lines = [
        "# Extraction by report category", "",
        f"Published extraction covers {len(completed)} documents in "
        f"{len({row['canonical_doc_type'] for row in completed})} of {len(CANONICAL_DOC_TYPES)} categories; "
        f"{len(pending)} additional documents await extraction.", "",
        "| Report category | Corpus documents | Documents extracted | Completed file IDs |",
        "|---|---:|---:|---|",
    ]
    for category in CANONICAL_DOC_TYPES:
        ids = [row["file_id"] for row in completed if row["canonical_doc_type"] == category]
        lines.append(f"| {category} | {corpus[category]} | {len(ids)} | {', '.join(ids)} |")
    lines += ["", "## Pending assignments", "",
              "| File | Report category | Pages | Instructions |",
              "|---|---|---:|---|"]
    for row in pending:
        brief = f"../instructions/01-pdf-extraction-csv/dispatch-prompts/{row['route']}"
        lines.append(
            f"| [{row['file_id']}: {row['issuer']}](../{row['pdf_path']}) | "
            f"{row['canonical_doc_type']} | {row['page_count']} | "
            f"[A]({brief}/01-EXTRACTOR-A.md), [B]({brief}/02-EXTRACTOR-B.md), "
            f"[review assignments]({brief}/README.md) |"
        )
    lines += ["", "Categories use the source ledger; filenames and older text headers may differ.", "",
              "[Document register](EXTRACTION-CATEGORY-COVERAGE.csv): filenames, issuers, page counts, source paths, assignments, and published coverage.", "",
              "Reproduction: `python -m src.repository.build_release_counts`.", ""]
    return "\n".join(lines)


def write() -> list[dict[str, str]]:
    rows = counts()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    documents = category_documents()
    with (PROJECT_ROOT / CATEGORY_CSV).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CATEGORY_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(documents)
    (PROJECT_ROOT / CATEGORY_MD).write_text(category_markdown(documents), encoding="utf-8")
    return rows


def read() -> dict[str, str]:
    if not OUTPUT.is_file():
        return {}
    with OUTPUT.open(encoding="utf-8-sig", newline="") as handle:
        return {row["name"]: row["value"] for row in csv.DictReader(handle)}


def main() -> None:
    rows = write()
    print(f"PASS: {OUTPUT.relative_to(PROJECT_ROOT).as_posix()} carries "
          f"{len(rows)} release counts")
    for row in rows:
        print(f"  {row['name']:<26}{row['value']}")


if __name__ == "__main__":
    main()
