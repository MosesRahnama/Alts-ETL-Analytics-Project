"""Verify the reviewer-facing baseline from published project artifacts."""

from __future__ import annotations

import argparse
import csv
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from src.analytics import run_extracted_analytics
from src.catalog.simple_pdf_extraction import csv_wide_contract as contract
from src.catalog.simple_pdf_extraction import csv_workflow, name_normalization
from src.catalog.simple_pdf_extraction.build_csv_pipeline import DISPATCH_SCOPES
from src.common import matrices
from src.flatten import flatten_extracted, load_star, pivot_wide
from src.load.load_csv_to_duckdb import database_parity, database_file_parity
from src.load import promote_extracted_to_fund_level as promotion
from src.load.validate_round02_promotion import validate_fund_model_extracted_rows, GATED_TABLES
from src.pipeline.transformation_lineage import missing_current_receipts, receipt_errors


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReviewerCheckError(ValueError):
    """Raised when a reviewer artifact is missing or malformed."""


# Both fund-model databases are built from one schema file. A database built
# before an edit to that file keeps the shape it was born with, and nothing
# compared the two: the mock warehouse shipped with none of the declared foreign
# keys while the schema beside it declared fourteen. This names that gap.
FUND_MODEL_DDL = Path("sql") / "duckdb" / "02_fund_level_ddl.sql"
FUND_MODEL_DATABASES = ("alts.duckdb", "alts_mock.duckdb")


def _schema_shape(connection: object) -> set[tuple[str, ...]]:
    """Every column, constraint, and view a database's catalogue states."""

    shape: set[tuple[str, ...]] = set()
    for table, column, data_type in connection.execute(  # type: ignore[attr-defined]
        "select table_name, column_name, data_type from duckdb_columns() where not internal"
    ).fetchall():
        shape.add(("column", table, column, data_type))
    for table, kind, text in connection.execute(  # type: ignore[attr-defined]
        "select table_name, constraint_type, constraint_text from duckdb_constraints()"
    ).fetchall():
        shape.add(("constraint", table, kind, text))
    for name, sql in connection.execute(  # type: ignore[attr-defined]
        "select view_name, sql from duckdb_views() where not internal"
    ).fetchall():
        # The catalogue renders a view's SQL from its parsed form, and quotes
        # a type name in one database and not the other (`AS "DOUBLE"` in
        # memory, `AS DOUBLE` on disk), so identifier quotes are dropped
        # before the two texts are compared.
        shape.add(("view", name, sql.replace('"', "")))
    return shape


def schema_drift(root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Databases whose live shape differs from the shipped schema file.

    The schema file is executed into an empty in-memory database and that
    catalogue is compared with the shipped file's: every column with its type,
    every constraint with its text (keys, uniqueness, NOT NULL, and CHECK
    expressions), and every view with its SQL. Counting foreign keys, which
    this did before, passed a key retargeted at another table and a CHECK
    replaced by `1 = 1`.
    """

    try:
        import duckdb
    except ImportError:
        return {}
    declared_connection = duckdb.connect(":memory:")
    try:
        declared_connection.execute((root / FUND_MODEL_DDL).read_text(encoding="utf-8-sig"))
        declared = _schema_shape(declared_connection)
    finally:
        declared_connection.close()
    drift: dict[str, str] = {}
    for name in FUND_MODEL_DATABASES:
        path = root / "data" / "warehouse" / name
        if not path.is_file():
            drift[name] = "absent"
            continue
        connection = duckdb.connect(str(path), read_only=True)
        try:
            live = _schema_shape(connection)
        finally:
            connection.close()
        if live != declared:
            missing = sorted(declared - live)
            extra = sorted(live - declared)
            first = (missing or extra)[0]
            drift[name] = (
                f"{len(missing)} declared and {len(extra)} live catalogue rows differ from "
                f"{FUND_MODEL_DDL.as_posix()}; first: {' '.join(first)[:160]}"
            )
    return drift


@dataclass(frozen=True)
class Check:
    name: str
    actual: object
    expected: object
    passed: bool


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ReviewerCheckError(f"missing CSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ReviewerCheckError(f"CSV has no header: {path}")
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in reader
        ]


def _iter_rows(path: Path):
    if not path.is_file():
        raise ReviewerCheckError(f"missing CSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ReviewerCheckError(f"CSV has no header: {path}")
        for row in reader:
            yield {key: (value or "").strip() for key, value in row.items()}


def _public_market_live_counts(root: Path) -> dict[str, object]:
    market_root = root / "data" / "public_markets"
    inventory = _rows(market_root / "audit" / "source_file_inventory.csv")
    copied = sorted((market_root / "sources").glob("*.parquet"))
    inventory_paths = {root / row["destination_relative_path"] for row in inventory}
    masters = _rows(market_root / "staging" / "benchmark_master_candidates.csv")
    master_ids = {row.get("benchmark_id", "") for row in masters}
    levels: dict[str, float] = {}
    level_keys: set[tuple[str, str]] = set()
    level_count = 0
    positive_levels = 0
    known_level_benchmarks = 0
    for row in _iter_rows(market_root / "staging" / "benchmark_level_candidates.csv"):
        level_count += 1
        level_id = row.get("benchmark_level_id", "")
        level = float(row.get("level_value", "nan"))
        key = (row.get("benchmark_id", ""), row.get("observation_date", ""))
        if level > 0:
            positive_levels += 1
        if row.get("benchmark_id", "") in master_ids:
            known_level_benchmarks += 1
        level_keys.add(key)
        levels[level_id] = level

    return_count = 0
    return_reconciled = 0
    return_sources_resolved = 0
    return_bounds_valid = 0
    for row in _iter_rows(market_root / "staging" / "benchmark_return_candidates.csv"):
        return_count += 1
        start = levels.get(row.get("source_level_start_id", ""))
        end = levels.get(row.get("source_level_end_id", ""))
        reported = float(row.get("return_value", "nan"))
        if start is not None and end is not None:
            return_sources_resolved += 1
            expected = end / start - 1.0
            if abs(reported - expected) <= 5e-11:
                return_reconciled += 1
        if reported > -1.0:
            return_bounds_valid += 1

    strategy_rows = _rows(
        market_root / "staging" / "benchmark_strategy_map_candidates.csv"
    )
    return {
        "inventory_rows": len(inventory),
        "copied_files": len(copied),
        "inventory_paths_match": inventory_paths == set(copied),
        "benchmark_masters": len(masters),
        "benchmark_master_ids": len(master_ids),
        "benchmark_levels": level_count,
        "benchmark_level_keys": len(level_keys),
        "positive_levels": positive_levels,
        "known_level_benchmarks": known_level_benchmarks,
        "benchmark_returns": return_count,
        "return_sources_resolved": return_sources_resolved,
        "return_bounds_valid": return_bounds_valid,
        "return_reconciled": return_reconciled,
        "strategy_map_rows": len(strategy_rows),
        "strategy_map_resolved": sum(
            row.get("benchmark_id", "") in master_ids for row in strategy_rows
        ),
    }


EXPECTATIONS = "release-expectations"
UNMAPPED_DISPOSITIONS = "unmapped-observation-dispositions"


def _check(name: str, actual: object, expected: object) -> Check:
    return Check(name, actual, expected, actual == expected)


def _return_qualifiers_stated(row: dict[str, str]) -> bool:
    """R2 on one published return row.

    Both `method` and `fee_basis` are filled, `unstated` included; and a value
    other than `unstated` was read off the page, so the row cites
    `definition_keys` or `basis_raw`.
    """

    method = row.get("method", "").strip()
    fee_basis = row.get("fee_basis", "").strip()
    if not (method and fee_basis):
        return False
    if method == "unstated" and fee_basis == "unstated":
        return True
    return bool(row.get("definition_keys", "").strip() or row.get("basis_raw", "").strip())


def grouping_and_qualifier_checks(
    published: list[dict[str, str]], grouping_rows: list[dict[str, str]]
) -> list[Check]:
    """The three readings R1 and R2 take over the published corpus.

    A printed grouping is read through the grouping matrix under the column its
    heading names. A value the matrix does not know is a grouping nobody has
    read, and an industry sitting in `asset_class` is the defect the `sector`
    column exists to end. A return with no stated method and fee basis is a
    number whose meaning a reader cannot recover, so every published return row
    states both, `unstated` included, and a stated value cites `definition_keys`
    or `basis_raw`.

    The three live in one function so a fixture can fail each of them by name.
    """

    known_groupings = {(row["context"], row["input_value"]) for row in grouping_rows}
    industries = {row["input_value"] for row in grouping_rows if row["context"] == "sector"}
    unread_groupings = {
        (column, value)
        for row in published
        for column in ("asset_class", "strategy", "sector")
        for value in [row.get(column, "").strip()]
        if value and (column, value) not in known_groupings
    }
    return [
        _check("printed groupings the grouping matrix reads", unread_groupings, set()),
        _check(
            "industries filed under asset_class",
            sum(1 for row in published if row.get("asset_class", "").strip() in industries),
            0,
        ),
        _check(
            "return rows without a stated method and fee basis",
            sum(
                1
                for row in published
                if row.get("metric_category") == "return" and not _return_qualifiers_stated(row)
            ),
            0,
        ),
    ]


# The categories whose number a method or fee basis qualifies: the return
# and the irr, read off the vocabulary matrix rather than typed here.
RETURN_LIKE = frozenset(
    name
    for name, qualifier in contract.METRIC_QUALIFIERS.items()
    if {"method", "fee_basis"} & set(qualifier["required_dimensions"])
)


def qualifier_transport_check(root: Path) -> Check:
    """R2's transport clause on the wide tables.

    A wide row's method and fee basis describe the return or irr printed on
    that row, so the pair must be one a return or irr cell of the row states.
    Read one column at a time, 69 SRC457 rows carried `time_weighted` from
    their return beside `unstated` from the irr printed next to it, a pair no
    cell states, and every check here read the source rows and passed.
    """

    stated_by_cell: dict[str, tuple[str, str]] = {}
    for row in _iter_rows(root / "data" / "extracted" / "tables" / "fact_observation.csv"):
        if row.get("metric_category") in RETURN_LIKE:
            stated_by_cell[row["observation_id"]] = (row.get("method", ""), row.get("fee_basis", ""))
    wide_dir = root / "data" / "extracted" / "wide"
    stated_by_row: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for row in _iter_rows(wide_dir / "bridge_pivot_observation.csv"):
        pair = stated_by_cell.get(row["observation_id"])
        if pair is not None:
            stated_by_row.setdefault((row["pivot_table"], row["pivot_row_id"]), set()).add(pair)
    method_column = pivot_wide.context_column_for("method")
    fee_basis_column = pivot_wide.context_column_for("fee_basis")
    lost = 0
    for path in sorted(wide_dir.glob("wide_*.csv")):
        for row in _iter_rows(path):
            carried = stated_by_row.get((path.stem, row.get("wide_row_id", "")))
            if carried is None:
                continue
            if (row.get(method_column, ""), row.get(fee_basis_column, "")) not in carried:
                lost += 1
    return _check("wide rows whose method and fee basis no return cell of the row states", lost, 0)


def _git_paths(root: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def dispatch_assignment_checks(
    root: Path, dispatch_scope: list[dict[str, str]], source_ids: set[str]
) -> list[Check]:
    """Compare scope membership with the current assignment files."""
    worklists = root / "instructions/01-pdf-extraction-csv/worklists"
    expected = {
        scope.lower(): Counter(row["file_id"] for path in (worklists / scope.lower()).glob("*.csv")
                               for row in _rows(path))
        for scope in DISPATCH_SCOPES if scope != "UNSCHEDULED"
    }
    assigned = set().union(*(set(rows) for rows in expected.values()))
    expected["unscheduled"] = Counter(source_ids - assigned)
    return [
        _check(f"{scope.lower()} dispatch rows",
               Counter(row["file_id"] for row in dispatch_scope
                       if row.get("dispatch_scope", row.get("scope", "")).strip().lower() == scope.lower()),
               expected[scope.lower()])
        for scope in DISPATCH_SCOPES
    ]


def run_checks(root: Path = PROJECT_ROOT) -> tuple[list[Check], list[str]]:
    root = root.resolve()
    checks: list[Check] = []
    open_items: list[str] = []

    source = _rows(root / "data-gathering" / "source_ledger.csv")
    pdf_dir = root / "data" / "documents" / "pdf"
    local_pdfs = sorted(pdf_dir.glob("*.pdf"))
    expected_pdf_paths = {pdf_dir / row["filename"] for row in source}
    checks.extend(
        [
            _check("source files", len(source), int(matrices.resolve(EXPECTATIONS, "source_files", context="reviewer"))),
            _check("source file IDs unique", len({row["file_id"] for row in source}), int(matrices.resolve(EXPECTATIONS, "source_files", context="reviewer"))),
            _check("source document types", len({row["doc_type"] for row in source}), int(matrices.resolve(EXPECTATIONS, "source_document_types", context="reviewer"))),
            _check(
                "source physical pages",
                sum(int(float(row["page_count"])) for row in source),
                40_788,
            ),
            _check(
                "local PDF files",
                len(local_pdfs),
                442,
            ),
            _check("source PDF paths match ledger", set(local_pdfs) == expected_pdf_paths, True),
        ]
    )

    classification = _rows(root / "ledgers" / "doc-type" / "doc-type-audit.csv")
    routing = _rows(root / "data" / "schemas" / "EXTRACTION-ROUTING.csv")
    dispatch_scope = _rows(root / "data" / "schemas" / "EXTRACTION-DISPATCH-SCOPE.csv")
    source_ids = {row["file_id"] for row in source}
    classification_ids = {row["file_id"] for row in classification}
    routing_ids = {row["file_id"] for row in routing}
    scope_ids = {row["file_id"] for row in dispatch_scope}
    scope_field = "dispatch_scope" if "dispatch_scope" in dispatch_scope[0] else "scope"
    checks.extend(
        [
            _check("document-type audit rows", len(classification), 442),
            _check("document-type audit IDs unique", len(classification_ids), 442),
            _check("document-type audit covers source ledger", classification_ids, source_ids),
            _check("routing rows", len(routing), 442),
            _check("routing IDs unique", len(routing_ids), 442),
            _check("routing covers source ledger", routing_ids, source_ids),
            _check("dispatch-scope rows", len(dispatch_scope), 442),
            _check("dispatch-scope IDs unique", len(scope_ids), 442),
            _check("dispatch scope covers source ledger", scope_ids, source_ids),
            *dispatch_assignment_checks(root, dispatch_scope, source_ids),
            _check(
                "local TXT files",
                len(list((root / "data" / "documents" / "txt").glob("*.txt"))),
                442,
            ),
        ]
    )

    published = _rows(root / "data" / "extracted" / "pdf-wide-records.csv")
    coverage = _rows(root / "data" / "extracted" / "pdf-wide-coverage.csv")
    active_ids = {r["file_id"] for r in dispatch_scope if r.get(scope_field, "").lower() == "active"}
    folders = [p for p in (root / "ledgers/working/pdf-extraction-csv").glob("*/*")
               if p.name in active_ids]
    finals = [r for p in folders for r in _rows(p / "records-final.csv")]
    final_coverage = [r for p in folders for r in _rows(p / "coverage-final.csv")]
    def records_key(row):
        return tuple(row.get(c, "") for c in contract.RECORD_COLUMNS)
    native_pairs = [r for p in folders for r in _rows(p / "pair-index.csv")]
    checks.extend([
        _check("published values match current final records",
               Counter(map(records_key, published)) == Counter(map(records_key, finals)), True),
        _check("published page keys match current finals",
               {(r["file_id"], r["source_page"]) for r in coverage},
               {(r["file_id"], r["source_page"]) for r in final_coverage}),
        _check("published coverage includes every active document",
               {r["file_id"] for r in coverage}, active_ids),
        _check("image index matches published pages",
               {(r["file_id"], r["page_number"]) for r in _rows(root / "data/documents/images/MANIFEST.csv")},
               {(r["file_id"], r["source_page"]) for r in coverage}),
    ])
    checks.extend(
        [
            _check("published observations", len(published), len(finals)),
            _check(
                "published documents",
                len(
                    {row["file_id"] for row in published}
                    | {row["file_id"] for row in coverage}
                ),
                len(active_ids),
            ),
            _check("published page coverage", len(coverage), len(final_coverage)),
            _check(
                "coverage page keys unique",
                len({(row["file_id"], row["source_page"]) for row in coverage}),
                len(final_coverage),
            ),
        ]
    )

    checks.extend(
        grouping_and_qualifier_checks(published, matrices.load("context-grouping-map"))
    )
    checks.append(qualifier_transport_check(root))

    # Missing required qualifiers block publication, including historical rows.
    backlog = _rows(root / "ledgers" / "pipeline" / "qualifier-backlog.csv")
    backlog_rows = sum(int(row["row_count"]) for row in backlog)
    backlog_documents = {row["file_id"] for row in backlog}
    checks.append(
        _check(
            "qualifier backlog rows",
            backlog_rows,
            int(matrices.resolve(EXPECTATIONS, "qualifier_backlog_rows", context="reviewer")),
        )
    )
    if backlog_rows:
        open_items.append(
            f"published rows awaiting a qualifier reading={backlog_rows}"
            f" in {len(backlog_documents)} documents"
        )
    # A document the active worklists assign and no adjudication has finished
    # publishes nothing. Stage 005 records it; the gate says it, so the release
    # output names the reading still owed instead of a count a reviewer has to
    # subtract from the worklists.
    unfinished = sorted(
        part
        for row in _rows(root / "ledgers" / "pipeline" / "extraction-scope.csv")
        for part in row.get("unfinished_documents", "").split("|")
        if part
    )
    if unfinished:
        open_items.append(
            f"assigned documents with no final={len(unfinished)} ({', '.join(unfinished)})"
        )

    review_root = root / "data" / "extracted" / "review"
    document_summary = _rows(review_root / "document-summary.csv")
    observation_lineage = _rows(review_root / "observation-lineage.csv")
    physical_pairs = sum(int(row["physical_pairs"]) for row in document_summary)
    value_agreements = sum(int(row["raw_value_agreements"]) for row in document_summary)
    value_conflicts = sum(int(row["value_conflicts"]) for row in document_summary)
    one_sided = sum(int(row["a_only"]) + int(row["b_only"]) for row in document_summary)
    checks.extend(
        [
            _check("review document summaries", len(document_summary), len(active_ids)),
            _check(
                "review final-row tie-out",
                sum(int(row["final_rows"]) for row in document_summary),
                len(published),
            ),
            _check("review physical pairs", physical_pairs, sum(bool(r["a_row_number"] and r["b_row_number"]) for r in native_pairs)),
            _check("review value agreements", value_agreements, sum(bool(r["a_row_number"] and r["b_row_number"]) and r["pair_status"] != "VALUE_CONFLICT" for r in native_pairs)),
            _check("review value conflicts", value_conflicts, sum(r["pair_status"] == "VALUE_CONFLICT" for r in native_pairs)),
            _check("review one-sided rows", one_sided, sum(not r["a_row_number"] or not r["b_row_number"] for r in native_pairs)),
            _check("review observation-lineage rows", len(observation_lineage), len(published)),
            _check(
                "review observation-lineage IDs unique",
                len({row["observation_id"] for row in observation_lineage}),
                len(published),
            ),
        ]
    )

    # The fund-model tables hold the promoted printed rows beside the rows the
    # completion generated, each labelled at row level. These checks pin both
    # halves, so a table that lost its printed rows, or one that lost its
    # labels, fails here instead of reading as complete.
    fund_model = {
        name: _rows(root / "data" / "csv" / f"{name}.csv")
        for name in (
            "fund_observations",
            "fund_periods",
            "fund_cashflows",
            "fund_holdings",
            "fund_master",
            "manager_master",
            "document_manager_map",
        )
    }

    def labelled(name: str, label: str) -> int:
        return sum(row.get("provenance_type") == label for row in fund_model[name])

    source_counts = {name: len(_rows(root / "data/extracted/fund-level" / f"{name}.csv"))
                     for name in fund_model}
    universe_size = len({r["fund_id"] for r in fund_model["fund_master"]})
    flows_per_fund = sum(len(matrices.resolve("integrated-cashflow-schedule", key).split("|"))
                         for key in ("call_fractions", "distribution_fractions"))
    holdings_per_fund = len(matrices.resolve("terms-generation-parameters", "fair_value_split", context="holdings").split("|"))

    checks.extend(
        [
            _check("fund-model fund_observations printed rows", labelled("fund_observations", "EXTRACTED"), source_counts["fund_observations"]),
            _check("fund-model fund_observations rows", len(fund_model["fund_observations"]), source_counts["fund_observations"]),
            _check("fund-model fund_periods printed rows", labelled("fund_periods", "EXTRACTED"), source_counts["fund_periods"]),
            _check("fund-model fund_periods generated rows", labelled("fund_periods", "SYNTHETIC"), universe_size),
            _check("fund-model fund_cashflows printed rows", labelled("fund_cashflows", "EXTRACTED"), source_counts["fund_cashflows"]),
            _check("fund-model fund_cashflows generated rows", labelled("fund_cashflows", "SYNTHETIC"), universe_size * flows_per_fund),
            _check("fund-model fund_holdings printed rows", labelled("fund_holdings", "EXTRACTED"), source_counts["fund_holdings"]),
            _check("fund-model fund_holdings generated rows", labelled("fund_holdings", "SYNTHETIC"), universe_size * holdings_per_fund),
            _check("fund-model fund_master rows", len(fund_model["fund_master"]), source_counts["fund_master"]),
            _check(
                "fund-model document managers carried by manager_master",
                {row.get("manager_id") for row in fund_model["document_manager_map"]}
                - {row.get("manager_id") for row in fund_model["manager_master"]},
                set(),
            ),
            _check(
                "fund-model rows carry a source class",
                all(row.get("provenance_type") for name in fund_model for row in fund_model[name]),
                True,
            ),
            _check(
                "fund-model warehouse present",
                (root / "data" / "warehouse" / "alts.duckdb").is_file(),
                True,
            ),
        ]
    )

    table_root = root / "data" / "extracted" / "tables"
    facts = _rows(table_root / "fact_observation.csv")
    aliases = flatten_extracted.build_alias_index(published, flatten_extracted.load_matrices())
    expected_tables = {
        "dim_document.csv": len(active_ids),
        "dim_entity.csv": len({(r["entity_kind"], r["entity_id"]) for r in aliases.values() if r["entity_id"]}),
        "dim_metric.csv": len({r["metric_id"] for r in facts if r["metric_id"]}),
        "dim_page.csv": len(final_coverage),
        "entity_alias.csv": len(aliases),
        "fact_holding.csv": len(flatten_extracted.build_holdings(facts)),
        "fact_observation.csv": len(finals),
        "unresolved_names.csv": 0,
    }
    for filename, expected in expected_tables.items():
        checks.append(_check(filename.removesuffix(".csv"), len(_rows(table_root / filename)), expected))

    lineage = _rows(table_root / "observation_lineage.csv")
    checks.extend(
        [
            _check("observation lineage rows", len(lineage), len(published)),
            _check(
                "observation lineage IDs unique",
                len({row["observation_id"] for row in lineage}),
                len(lineage),
            ),
            _check(
                "unmatched observation lineage",
                sum(row.get("pair_status") == "UNMATCHED" for row in lineage),
                0,
            ),
        ]
    )

    fund_names = _rows(root / "data" / "normalization" / "fund-names-matrix.csv")
    status_counts: dict[str, int] = {}
    for row in fund_names:
        status = row.get("decision_status", "")
        status_counts[status] = status_counts.get(status, 0) + 1
    checks.extend(
        [
            _check("fund-name matrix rows", len(fund_names), len({r["fund_name_raw"] for r in fund_names})),
            _check("fund-name decided rows", sum(r.get("decision_status") in name_normalization.DECIDED for r in fund_names), len(fund_names)),
            _check(
                "fund-name rows without final classification",
                status_counts.get("review", 0),
                0,
            ),
        ]
    )
    if status_counts.get("review", 0):
        open_items.append(
            f"fund-name rows without final classification={status_counts['review']}"
        )
    unresolved = len(_rows(table_root / "unresolved_names.csv"))
    if unresolved:
        open_items.append(
            f"printed entity strings without canonical classification={unresolved}"
        )

    fund_standards = {
        row.get("standardized_fund_name", "")
        for row in fund_names
        if row.get("decision_status") in name_normalization.DECIDED
        and row.get("standardized_fund_name")
    }
    manager_rows = _rows(
        root / "data" / "normalization" / "web-manager-names.csv"
    )
    manager_by_fund = {
        row.get("standardized_fund_name", ""): row for row in manager_rows
    }
    manager_universe = [manager_by_fund.get(name, {}) for name in fund_standards]
    checks.extend(
        [
            _check("standardized fund universe", len(fund_standards), len({r["fund_id"] for r in fund_names if r.get("standardized_fund_name")})),
            _check(
                "manager classifications complete",
                sum(
                    bool(row.get("final_manager_name") or row.get("final_source"))
                    for row in manager_universe
                ),
                len(fund_standards),
            ),
            _check(
                "manager provenance supports named manager",
                sum(
                    bool(row.get("final_manager_name"))
                    and "no public manager match found"
                    in row.get("final_source", "").casefold()
                    for row in manager_universe
                ),
                0,
            ),
        ]
    )

    from src.catalog.simple_pdf_extraction import fund_attributes
    attributes = _rows(root / "data" / "normalization" / "fund-attributes-matrix.csv")
    attribute_facts = _rows(root / "data/extracted/tables/fact_observation.csv")
    source_fund_ids = {r["subject_entity_id"] for r in attribute_facts
                       if r.get("subject_type") == "fund" and r.get("subject_entity_id", "").startswith("FUND_")}
    attribute_lookup = fund_attributes.decided_lookup(attributes)
    expected_inherit = sum(not r.get(field, "").strip()
        for r in attribute_facts if r.get("subject_type") == "fund" and fund_attributes.attribute_scope_allowed(r)
        for field in attribute_lookup.get(r.get("subject_entity_id"), {}))
    settled = {row["input_value"] for row in matrices.rows_in("attribute-status-policy", "settled_status")}
    vintage_settled = sum(row.get("vintage_year_status") in settled for row in attributes)
    attr_conflicts = sum(
        any(row.get(f"{field}_status") == "conflict" for field in ("vintage_year", "strategy", "asset_class", "geography"))
        for row in attributes
    )
    inherit = _rows(root / "data" / "extracted" / "audit" / "attribute-inherit.csv")
    attribute_changes = _rows(
        root / "data" / "extracted" / "audit" / "attribute-changes.csv"
    )
    mapping_prompts = root / "instructions" / "02-fund-mapping" / "dispatch-prompts"
    dispatch_prompt = mapping_prompts / "attributes" / "ATTRIBUTE-NORMALIZER-01.md"
    worksheet_dir = root / "data" / "normalization" / "worksheets"
    identity_sheets = (
        list(worksheet_dir.glob("fund-part-*.csv"))
        + list(worksheet_dir.glob("manager-*-a.csv"))
        + list(worksheet_dir.glob("manager-*-b.csv"))
        + list(worksheet_dir.glob("manager-*-j.csv"))
    )
    identity_prompts: list[Path] = []
    for folder in ("normalize", "web-manager", "adjudicate"):
        folder_path = mapping_prompts / folder
        if folder_path.is_dir():
            identity_prompts.extend(
                path for path in folder_path.glob("*.md") if path.name != "README.md"
            )
    checks.extend(
        [
            _check("fund-attribute matrix rows", len(attributes), len(source_fund_ids)),
            _check("fund-attribute identity coverage", {r["fund_id"] for r in attributes}, source_fund_ids),
            _check("funds with settled vintage", vintage_settled, sum(bool(r.get("vintage_year")) for r in attributes)),
            _check("fund-attribute conflicts", attr_conflicts, 0),
            _check("attribute inherit log rows", len(inherit), expected_inherit),
            _check(
                "attribute inherit evidence complete",
                sum(
                    bool(row.get("source_observation_id"))
                    and bool(row.get("source_document_id"))
                    and bool(row.get("source_evidence_page"))
                    and bool(row.get("source_printed_value"))
                    for row in inherit
                ),
                len(inherit),
            ),
            _check(
                "attribute change IDs unique",
                len({row.get("change_id") for row in attribute_changes}),
                len(attribute_changes),
            ),
            _check(
                "attribute change evidence complete",
                sum(
                    bool(row.get("target_record_id"))
                    and bool(row.get("new_value"))
                    and bool(row.get("source_observation_id"))
                    and bool(row.get("source_document_id"))
                    and bool(row.get("source_page"))
                    and bool(row.get("source_printed_value"))
                    for row in attribute_changes
                ),
                len(attribute_changes),
            ),
            _check("attribute dispatch prompt present", dispatch_prompt.is_file(), True),
            _check("identity dispatch prompts", len(identity_prompts), len(identity_sheets)),
        ]
    )
    if attr_conflicts:
        open_items.append(f"attribute conflict funds={attr_conflicts}")

    # A promoted row no semantic-map rule matches keeps a blank canonical
    # measure and enters no analytical table. The rows are preserved, so this
    # is a coverage boundary rather than data loss, and a boundary a release
    # states is one a reviewer can judge. Every unmapped measure names its
    # disposition in a matrix; a new one with none stops the gate.
    unmapped_measures = sorted(
        {
            row.get("metric_id", "")
            for row in _rows(root / "data" / "extracted" / "fund-level" / "fund_observations.csv")
            if not row.get("canonical_measure_id")
        }
    )
    declared_dispositions = {
        row["input_value"]: row["output_value"]
        for row in matrices.load(UNMAPPED_DISPOSITIONS)
    }
    checks.append(
        _check(
            "every unmapped measure has a declared disposition",
            [measure for measure in unmapped_measures if measure not in declared_dispositions],
            [],
        )
    )
    checks.append(
        _check(
            "every declared disposition names a measure still unmapped",
            [name for name in declared_dispositions if name not in unmapped_measures],
            [],
        )
    )
    if unmapped_measures:
        by_disposition: dict[str, int] = {}
        for measure in unmapped_measures:
            key = declared_dispositions.get(measure, "UNDECLARED")
            by_disposition[key] = by_disposition.get(key, 0) + 1
        open_items.append(
            "unmapped measures by disposition="
            + ", ".join(f"{key} {value}" for key, value in sorted(by_disposition.items()))
        )

    extracted_fund_root = root / "data" / "extracted" / "fund-level"
    extracted_master_rows = _rows(extracted_fund_root / "fund_master.csv")
    checks.append(_check("source master contains only supported financial fields",
        promotion.source_master_fields([dict(row) for row in extracted_master_rows], facts) == extracted_master_rows, True))
    integrated_master = _rows(root / "data" / "csv" / "fund_master.csv")
    integrated_periods = _rows(root / "data" / "csv" / "fund_periods.csv")
    integrated_cashflows = _rows(root / "data" / "csv" / "fund_cashflows.csv")
    target_periods = [
        row
        for row in integrated_periods
        if row.get("synthetic_parameter_set_id") == matrices.resolve("coverage-population", "integrated_completion_set")
    ]
    target_period_ids = {row.get("fund_period_id") for row in target_periods}
    integrated_quality = _rows(root / "data" / "csv" / "quality_results.csv")
    target_quality = [
        row for row in integrated_quality if row.get("record_id") in target_period_ids
    ]
    extracted_ids: set[str] = set()
    for filename in (
        "fund_master.csv",
        "document_fund_map.csv",
        "fund_observations.csv",
        "fund_cashflows.csv",
        "fund_periods.csv",
        "fund_terms.csv",
        "fund_term_clauses.csv",
        "fund_holdings.csv",
    ):
        extracted_ids.update(
            row.get("fund_id", "")
            for row in _rows(extracted_fund_root / filename)
            if row.get("fund_id", "")
        )
    extracted_master_ids = {row.get("fund_id", "") for row in extracted_master_rows}
    integrated_ids = {row.get("fund_id", "") for row in integrated_master}
    extracted_period_ids = {
        row.get("fund_period_id", "")
        for row in _rows(extracted_fund_root / "fund_periods.csv")
    }
    integrated_period_ids = {row.get("fund_period_id", "") for row in integrated_periods}
    period_provenance = {
        row.get("fund_period_id", ""): row.get("provenance_type", "")
        for row in integrated_periods
    }
    extracted_cashflow_ids = {
        row.get("cashflow_id", "")
        for row in _rows(extracted_fund_root / "fund_cashflows.csv")
    }
    integrated_cashflow_ids = {row.get("cashflow_id", "") for row in integrated_cashflows}
    gaps = _rows(root / "data" / "integrated" / "gap-ledger.csv")
    cell_lineage = _rows(root / "data" / "integrated" / "cell-lineage.csv")
    defects = _rows(root / "data" / "csv" / "defect_injections.csv")
    scorecard = _rows(root / "data" / "integrated" / "detection-scorecard.csv")
    metrics = _rows(root / "data" / "csv" / "fund_metrics.csv")
    pme = _rows(root / "data" / "csv" / "pme_results.csv")
    extracted_metrics = _rows(extracted_fund_root / "fund_metrics.csv")
    measurable = [row for row in _rows(extracted_fund_root / "fund_periods.csv")
                  if run_extracted_analytics.is_measurable(row)]
    one_basis, _ = run_extracted_analytics.funds_with_one_basis(measurable)
    expected_source_metrics = run_extracted_analytics.calculate_fund_metrics(
        [row for row in measurable if row["fund_id"] in one_basis],
        _rows(extracted_fund_root / "fund_cashflows.csv"),
        _rows(extracted_fund_root / "quality_results.csv"), require_xirr=False,
    )
    allocations = _rows(root / "data" / "csv" / "portfolio_allocations.csv")
    integrated_terms = [
        row
        for row in _rows(root / "data" / "csv" / "fund_terms.csv")
        if row.get("synthetic_parameter_set_id") == "INTEGRATED_COMPLETION_V1"
    ]
    integrated_holdings = [
        row
        for row in _rows(root / "data" / "csv" / "fund_holdings.csv")
        if row.get("synthetic_parameter_set_id") == "INTEGRATED_COMPLETION_V1"
    ]
    checks.extend(
        [
            _check("integrated identity spine", integrated_ids, extracted_ids),
            _check("extracted master identity spine", extracted_master_ids, extracted_ids),
            _check("one completed period per extracted fund", len(target_periods), len(extracted_ids)),
            _check("completed period fund IDs", {row.get("fund_id") for row in target_periods}, extracted_ids),
            _check("standalone synthetic IDs in integrated master", sum(value.startswith("FUND_SYNTH_") for value in integrated_ids), 0),
            _check("extracted period IDs preserved", extracted_period_ids <= integrated_period_ids, True),
            _check("extracted cash-flow IDs preserved", extracted_cashflow_ids <= integrated_cashflow_ids, True),
            _check("completed-period quality failures", sum(row.get("status") == "FAIL" for row in target_quality), 0),
            # A gap is RESOLVED when something filled it and OPEN when the corpus
            # prints nothing that can. What must never happen is a gap claiming a
            # resolution it does not carry, or carrying a value while calling
            # itself open.
            _check(
                "integration gaps state what filled them",
                sum(
                    1
                    for row in gaps
                    if (row.get("status") == "RESOLVED") != bool(row.get("resolution_value"))
                ),
                0,
            ),
            _check("cell-lineage IDs unique", len({row.get("lineage_id") for row in cell_lineage}), len(cell_lineage)),
            _check(
                "cell-lineage parameter sets declared in synthetic_parameters",
                {row.get("synthetic_parameter_set_id") for row in cell_lineage if row.get("synthetic_parameter_set_id")}
                - {row.get("parameter_set_id") for row in _rows(root / "data" / "csv" / "synthetic_parameters.csv")},
                set(),
            ),
            _check("integrated planted defects", len(defects), 12),
            _check("integrated defect families", len(scorecard), 6),
            _check("fully detected integrated defect families", sum(float(row.get("detection_rate", "0")) == 1.0 for row in scorecard), 6),
            _check("integrated fund metrics", len(metrics), len(target_periods) * 4),
            _check("integrated PME results", len(pme), len(target_periods) * 2),
            _check(
                "integrated metric provenance",
                {row.get("provenance_type") for row in metrics},
                {"SYNTHETIC"},
            ),
            _check(
                "integrated PME provenance",
                {row.get("provenance_type") for row in pme},
                {"SYNTHETIC"},
            ),
            _check(
                "extracted-only metric provenance",
                {row.get("provenance_type") for row in extracted_metrics},
                {"EXTRACTED"},
            ),
            _check("extracted-only metric rows", len(extracted_metrics), len(expected_source_metrics)),
            _check(
                "metric provenance follows input period",
                all(
                    row.get("provenance_type")
                    == period_provenance.get(row.get("input_record_ids", "").split(";")[0])
                    for row in metrics
                ),
                True,
            ),
            _check(
                "PME provenance follows input period",
                all(
                    row.get("provenance_type")
                    == period_provenance.get(row.get("input_record_ids", "").split(";")[0])
                    for row in pme
                ),
                True,
            ),
            _check("integrated portfolio allocations", len(allocations), len(target_periods)),
            _check("integrated fund terms", len(integrated_terms), len(target_periods)),
            _check("integrated holdings", len(integrated_holdings), len(target_periods) * holdings_per_fund),
        ]
    )

    market_quality = _rows(
        root / "data" / "public_markets" / "audit" / "quality_results.csv"
    )
    market_live = _public_market_live_counts(root)
    checks.extend(
        [
            _check("public-market inventory rows", market_live["inventory_rows"], 334),
            _check("public-market Parquet files", market_live["copied_files"], 334),
            _check("public-market inventory paths match", market_live["inventory_paths_match"], True),
            _check("benchmark masters", market_live["benchmark_masters"], 58),
            _check("benchmark master IDs unique", market_live["benchmark_master_ids"], 58),
            _check("benchmark levels", market_live["benchmark_levels"], 279_269),
            _check("benchmark level keys unique", market_live["benchmark_level_keys"], 279_269),
            _check("benchmark levels positive", market_live["positive_levels"], 279_269),
            _check("benchmark levels resolve to masters", market_live["known_level_benchmarks"], 279_269),
            _check("benchmark returns", market_live["benchmark_returns"], 279_211),
            _check("benchmark return source levels resolve", market_live["return_sources_resolved"], 279_211),
            _check("benchmark return bounds", market_live["return_bounds_valid"], 279_211),
            _check("benchmark returns reconcile", market_live["return_reconciled"], 279_211),
            _check("benchmark strategy mappings", market_live["strategy_map_rows"], len(matrices.rows_in("strategy-benchmark-map", "canonical_strategy"))),
            _check("benchmark strategy mappings resolve", market_live["strategy_map_resolved"], len(matrices.rows_in("strategy-benchmark-map", "canonical_strategy"))),
            _check("public-market checks", len(market_quality), 10),
            _check(
                "passing public-market checks",
                sum(row.get("status") == "PASS" for row in market_quality),
                10,
            ),
        ]
    )

    candidates = _rows(
        root / "ledgers" / "analysis" / "synthetic_parameter_candidates.csv"
    )
    checks.extend(
        [
            _check("calibration candidates", len(candidates), 4),
            _check(
                "inactive calibration candidates",
                sum(row.get("active", "").lower() == "false" for row in candidates),
                4,
            ),
            _check(
                "calibration candidates excluded from release",
                sum(
                    row.get("adjudication_status") == "EXCLUDED_FROM_RELEASE"
                    for row in candidates
                ),
                4,
            ),
        ]
    )
    accepted_parameters = _rows(root / "data" / "csv" / "synthetic_parameters.csv")
    checks.extend(
        [
            _check("active integrated parameters", sum(row.get("active", "").lower() == "true" for row in accepted_parameters), len(accepted_parameters)),
            _check("source-derived integrated parameters", sum(row.get("provenance_type") == "DERIVED" for row in accepted_parameters), sum(bool(row.get("input_record_ids")) for row in accepted_parameters)),
        ]
    )
    benchmark_policy = _rows(root / "data" / "integrated" / "benchmark-policy.csv")
    promotion_rows = validate_fund_model_extracted_rows(
        root / "data" / "csv",
        root / "ledgers" / "promotion-gate",
        root / "data" / "public_markets" / "audit",
        root / "data" / "public_markets" / "staging",
        root / "data" / "integrated" / "benchmark-policy.csv",
    )
    checks.extend(
        [
            _check("source promotion and benchmark gate", promotion_rows,
                   sum(r.get("provenance_type") == "EXTRACTED"
                       for filename, _ in GATED_TABLES.values()
                       for r in _rows(root / "data/csv" / filename))),
            # One policy row per benchmark the strategy map now prices through
            # (A5-03), so every row states the rights, not only the first.
            _check("benchmark policy rows", len(benchmark_policy), 7),
            _check(
                "benchmark demo use labelled",
                sorted({row.get("use_status") for row in benchmark_policy}),
                ["DEMO_PROXY_ONLY"],
            ),
            _check(
                "benchmark production use restricted",
                sorted({row.get("rights_status") for row in benchmark_policy}),
                ["DEMONSTRATION_ONLY"],
            ),
        ]
    )

    reviewer_observations = _rows(
        root / "data" / "extracted" / "review" / "reviewer-observations.csv"
    )
    reviewer_periods = _rows(
        root / "data" / "extracted" / "review" / "reviewer-fund-periods.csv"
    )
    reviewer_lineage = _rows(
        root / "data" / "extracted" / "review" / "reviewer-cell-lineage.csv"
    )
    reviewer_gaps = _rows(
        root / "data" / "extracted" / "review" / "reviewer-gap-ledger.csv"
    )
    reviewer_analytics = _rows(
        root / "data" / "extracted" / "review" / "reviewer-analytics-summary.csv"
    )
    fund_periods = _rows(root / "data" / "csv" / "fund_periods.csv")
    term_rows = [row for row in reviewer_periods if row.get("term_id")]
    term_clause_rows = [row for row in reviewer_periods if row.get("term_clause_id")]
    completed_reviewer_rows = [
        row
        for row in reviewer_periods
        if row.get("synthetic_parameter_set_id") == "INTEGRATED_COMPLETION_V1"
    ]
    reviewer_attribute_origins = [
        row.get(column, "")
        for row in reviewer_periods
        for column in ("vintage_year_origin", "strategy_origin")
    ]
    holding_rows = [
        row for row in reviewer_periods if int(row.get("holding_count") or 0) > 0
    ]
    allocation_rows = [row for row in reviewer_periods if row.get("allocation_id")]
    summary_distributions = {
        (row.get("population", ""), row.get("metric_id", ""))
        for row in reviewer_analytics
        if row.get("record_type") == "distribution"
    }
    expected_distributions = {
        *(('EXTRACTED', metric) for metric in ('dpi', 'rvpi', 'tvpi')),
        *(('INTEGRATED', metric) for metric in ('dpi', 'rvpi', 'tvpi', 'xirr', 'ks_pme', 'direct_alpha')),
        ('INTEGRATED_PORTFOLIO', 'target_weight'),
    }
    strategy_weight = sum(
        float(row.get("weighted_value") or 0)
        for row in reviewer_analytics
        if row.get("record_type") == "strategy_exposure"
    )
    checks.extend(
        [
            _check("reviewer observation rows", len(reviewer_observations), len(published)),
            _check(
                "reviewer observation IDs unique",
                len({row.get("observation_id") for row in reviewer_observations}),
                len(reviewer_observations),
            ),
            _check("reviewer fund-period rows", len(reviewer_periods), len(fund_periods)),
            _check(
                "reviewer fund-period IDs unique",
                len({row.get("fund_period_id") for row in reviewer_periods}),
                len(reviewer_periods),
            ),
            _check(
                "reviewer attribute origins explicit",
                sum("UNRESOLVED" in origin.upper() for origin in reviewer_attribute_origins),
                0,
            ),
            _check(
                "synthetic period attributes labelled",
                sum(
                    row.get(column) == "SYNTHETIC_COMPLETION"
                    for row in completed_reviewer_rows
                    for column in ("vintage_year_origin", "strategy_origin")
                ),
                2 * len(completed_reviewer_rows),
            ),
            _check("reviewer cell-lineage rows", len(reviewer_lineage), len(cell_lineage)),
            _check("reviewer gap-ledger rows", len(reviewer_gaps), len(gaps)),
            _check("reviewer term provenance complete", all(
                row.get("term_provenance_type")
                and (
                    row.get("term_provenance_type") != "SYNTHETIC"
                    or row.get("term_synthetic_parameter_set_id")
                )
                for row in term_rows
            ), True),
            _check(
                "reviewer completed periods carry terms",
                sum(bool(row.get("term_id")) for row in completed_reviewer_rows),
                len(target_periods),
            ),
            _check("reviewer term-clause lineage complete", all(
                row.get("term_clause_provenance_type")
                and (
                    row.get("term_clause_provenance_type") != "SYNTHETIC"
                    or row.get("term_clause_synthetic_parameter_set_id")
                )
                for row in term_clause_rows
            ), True),
            _check(
                "reviewer completed periods carry term clauses",
                sum(bool(row.get("term_clause_id")) for row in completed_reviewer_rows),
                len(target_periods),
            ),
            _check("reviewer holding provenance complete", all(
                row.get("holding_ids")
                and row.get("holding_as_of_date")
                and row.get("holding_provenance_type")
                and (
                    "SYNTHETIC" not in row.get("holding_provenance_type", "")
                    or row.get("holding_synthetic_parameter_set_ids")
                )
                for row in holding_rows
            ), True),
            _check("reviewer allocation rows", len(allocation_rows), len(target_periods)),
            _check("reviewer allocation provenance complete", all(
                row.get("portfolio_id")
                and row.get("portfolio_as_of_date")
                and row.get("portfolio_provenance_type") == "DERIVED"
                and row.get("portfolio_synthetic_parameter_set_id")
                and row.get("portfolio_optimization_run_id")
                for row in allocation_rows
            ), True),
            _check("reviewer analytics distributions", summary_distributions, expected_distributions),
            _check("reviewer analytics coverage rows", {
                row.get("population", "")
                for row in reviewer_analytics
                if row.get("record_type") == "coverage"
            }, {"EXTRACTED", "INTEGRATED"}),
            _check("reviewer strategy exposure totals", round(strategy_weight, 8), 1.0),
        ]
    )

    extracted_files = {
        table: (root / "data" / "extracted" / "tables" / f"{table}.csv")
        for table in load_star.TABLE_ORDER
    }
    extracted_files.update(
        {
            table: root / "data" / "extracted" / "wide" / f"{table}.csv"
            for table in load_star.wide_table_order()
        }
    )
    extracted_database_mismatches = database_file_parity(
        extracted_files, root / "data" / "warehouse" / "extracted.duckdb"
    )
    fund_model_database_mismatches = database_parity(
        root / "data" / "csv", root / "data" / "warehouse" / "alts.duckdb"
    )
    checks.extend(
        [
            _check("extracted DuckDB full-content parity", extracted_database_mismatches, {}),
            _check("fund-model DuckDB full-content parity", fund_model_database_mismatches, {}),
            _check("shipped databases carry the declared keys", schema_drift(root), {}),
        ]
    )

    governed_outputs = (
        root / "data" / "extracted" / "pdf-wide-records.csv",
        root / "data" / "extracted" / "pdf-wide-coverage.csv",
        table_root / "fact_observation.csv",
        table_root / "observation_lineage.csv",
        root / "data" / "warehouse" / "extracted.duckdb",
        root / "data" / "csv" / "fund_periods.csv",
        root / "data" / "csv" / "fund_master.csv",
        root / "data" / "csv" / "quality_results.csv",
        root / "data" / "csv" / "fund_metrics.csv",
        root / "data" / "extracted" / "fund-level" / "fund_metrics.csv",
        root / "data" / "csv" / "pme_results.csv",
        root / "data" / "csv" / "portfolio_allocations.csv",
        root / "data" / "csv" / "benchmark_returns.csv",
        root / "data" / "integrated" / "gap-ledger.csv",
        root / "data" / "integrated" / "cell-lineage.csv",
        root / "data" / "integrated" / "reconciliation-results.csv",
        root / "data" / "extracted" / "audit" / "attribute-inherit.csv",
        root / "data" / "extracted" / "audit" / "attribute-changes.csv",
        root / "data" / "extracted" / "review" / "reviewer-observations.csv",
        root / "data" / "extracted" / "review" / "reviewer-fund-periods.csv",
        root / "data" / "extracted" / "review" / "reviewer-cell-lineage.csv",
        root / "data" / "extracted" / "review" / "reviewer-gap-ledger.csv",
        root / "data" / "extracted" / "review" / "reviewer-analytics-summary.csv",
        root / "data" / "warehouse" / "alts.duckdb",
    )
    checks.append(
        _check(
            "current governed outputs have receipts",
            missing_current_receipts(governed_outputs, root=root),
            [],
        )
    )
    checks.append(
        _check(
            "transformation receipt structure",
            receipt_errors(root=root, require_objects=False),
            [],
        )
    )

    # A blank the corpus prints nothing to close stays OPEN and carries no
    # resolution value. The release states how many and which field, so a
    # reviewer reads a disclosed boundary instead of inferring one from a
    # coverage table.
    open_gaps = [
        row
        for row in _rows(root / "data" / "integrated" / "gap-ledger.csv")
        if row.get("status") == "OPEN"
    ]
    if open_gaps:
        fields = sorted({f"{row['target_table']}.{row['field_name']}" for row in open_gaps})
        open_items.append(
            f"open gaps={len(open_gaps)} on {', '.join(fields)}"
        )

    # An identity read off a page that no published document, observation, or
    # fund yet points at. It is a real reading, so it stays; naming it keeps a
    # dimension row from sitting unexplained in the released database.
    managers = _rows(root / "data" / "csv" / "manager_master.csv")
    linked = {
        row[field]
        for path, field in (
            (root / "data" / "csv" / "document_manager_map.csv", "manager_id"),
            (root / "data" / "csv" / "document_entity_context.csv", "manager_id"),
            (root / "data" / "csv" / "manager_observations.csv", "manager_id"),
            (root / "data" / "csv" / "fund_master.csv", "fund_manager_id"),
        )
        for row in _rows(path)
        if row.get(field)
    }
    unlinked = sorted(row["manager_id"] for row in managers if row["manager_id"] not in linked)
    if unlinked:
        open_items.append(
            f"manager identities with no fund, observation, or document link={len(unlinked)}"
            f" ({', '.join(unlinked)})"
        )
    return checks, open_items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        checks, open_items = run_checks(args.root)
    except (ReviewerCheckError, OSError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    failures = [check for check in checks if not check.passed]
    for check in failures:
        print(f"FAIL: {check.name}; actual={check.actual}; expected={check.expected}")
    # The open items are the release's declared coverage boundaries, and a
    # reviewer wants them most while the gate is red. Printing them only on a
    # clean run hid them exactly when the tree was being repaired.
    if open_items:
        print("OPEN: " + "; ".join(open_items))
    if failures:
        print(f"FAIL: {len(failures)} of {len(checks)} reviewer baseline checks failed")
        return 1
    print(f"PASS: {len(checks)} reviewer baseline checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
