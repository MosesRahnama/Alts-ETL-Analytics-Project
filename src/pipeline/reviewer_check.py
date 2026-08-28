"""Verify the reviewer-facing baseline from published project artifacts."""

from __future__ import annotations

import argparse
import csv
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.flatten import load_star
from src.load.load_csv_to_duckdb import database_parity, database_file_parity
from src.load.validate_round02_promotion import validate_fund_model_extracted_rows
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


def schema_drift(root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Databases whose live foreign keys differ from the shipped schema."""

    try:
        import duckdb
    except ImportError:
        return {}
    declared = sum(
        1
        for line in (root / FUND_MODEL_DDL).read_text(encoding="utf-8-sig").splitlines()
        if line.strip().startswith("FOREIGN KEY (")
    )
    drift: dict[str, str] = {}
    for name in FUND_MODEL_DATABASES:
        path = root / "data" / "warehouse" / name
        if not path.is_file():
            drift[name] = "absent"
            continue
        connection = duckdb.connect(str(path), read_only=True)
        try:
            live = connection.execute(
                "select count(*) from duckdb_constraints()"
                " where constraint_type = 'FOREIGN KEY'"
            ).fetchone()[0]
        finally:
            connection.close()
        if live != declared:
            drift[name] = f"{live} foreign keys against {declared} in {FUND_MODEL_DDL.as_posix()}"
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


def _check(name: str, actual: object, expected: object) -> Check:
    return Check(name, actual, expected, actual == expected)


def _git_paths(root: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


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
            _check("source files", len(source), 442),
            _check("source file IDs unique", len({row["file_id"] for row in source}), 442),
            _check("source document types", len({row["doc_type"] for row in source}), 17),
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
    scope_counts: dict[str, int] = {}
    for row in dispatch_scope:
        value = row.get(scope_field, "").strip().lower()
        scope_counts[value] = scope_counts.get(value, 0) + 1
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
            _check("active dispatch rows", scope_counts.get("active", 0), 29),
            _check("deferred dispatch rows", scope_counts.get("deferred", 0), 61),
            _check("reference dispatch rows", scope_counts.get("reference", 0), 8),
            _check("unscheduled dispatch rows", scope_counts.get("unscheduled", 0), 344),
            _check(
                "local TXT files",
                len(list((root / "data" / "documents" / "txt").glob("*.txt"))),
                442,
            ),
        ]
    )

    published = _rows(root / "data" / "extracted" / "pdf-wide-records.csv")
    coverage = _rows(root / "data" / "extracted" / "pdf-wide-coverage.csv")
    checks.extend(
        [
            _check("published observations", len(published), 7_201),
            _check(
                "published documents",
                len(
                    {row["file_id"] for row in published}
                    | {row["file_id"] for row in coverage}
                ),
                29,
            ),
            _check("published page coverage", len(coverage), 311),
            _check(
                "coverage page keys unique",
                len({(row["file_id"], row["source_page"]) for row in coverage}),
                311,
            ),
        ]
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
            _check("review document summaries", len(document_summary), 29),
            _check(
                "review final-row tie-out",
                sum(int(row["final_rows"]) for row in document_summary),
                len(published),
            ),
            _check("review physical pairs", physical_pairs, 6_111),
            _check("review value agreements", value_agreements, 5_661),
            _check("review value conflicts", value_conflicts, 450),
            _check("review one-sided rows", one_sided, 1_258),
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

    checks.extend(
        [
            _check("fund-model fund_observations printed rows", labelled("fund_observations", "EXTRACTED"), 3_803),
            _check("fund-model fund_observations rows", len(fund_model["fund_observations"]), 3_803),
            _check("fund-model fund_periods printed rows", labelled("fund_periods", "EXTRACTED"), 378),
            _check("fund-model fund_periods generated rows", labelled("fund_periods", "SYNTHETIC"), 934),
            _check("fund-model fund_cashflows printed rows", labelled("fund_cashflows", "EXTRACTED"), 16),
            _check("fund-model fund_cashflows generated rows", labelled("fund_cashflows", "SYNTHETIC"), 6_538),
            _check("fund-model fund_holdings printed rows", labelled("fund_holdings", "EXTRACTED"), 32),
            _check("fund-model fund_holdings generated rows", labelled("fund_holdings", "SYNTHETIC"), 2_802),
            _check("fund-model fund_master rows", len(fund_model["fund_master"]), 934),
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
    expected_tables = {
        "dim_document.csv": 29,
        "dim_entity.csv": 1008,
        "dim_metric.csv": 109,
        "dim_page.csv": 311,
        "entity_alias.csv": 1_454,
        "fact_holding.csv": 469,
        "fact_observation.csv": 7_201,
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
            _check("fund-name matrix rows", len(fund_names), 1_055),
            _check("fund-name decided rows", status_counts.get("decided", 0), 1_055),
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
        if row.get("decision_status") == "decided"
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
            _check("standardized fund universe", len(fund_standards), 1_011),
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

    attributes = _rows(root / "data" / "normalization" / "fund-attributes-matrix.csv")
    settled = {"unique", "unique_canonical", "decided"}
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
            _check("fund-attribute matrix rows", len(attributes), 853),
            _check("funds with settled vintage", vintage_settled, 311),
            _check("fund-attribute conflicts", attr_conflicts, 0),
            _check("attribute inherit log rows", len(inherit), 330),
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

    extracted_fund_root = root / "data" / "extracted" / "fund-level"
    extracted_master_rows = _rows(extracted_fund_root / "fund_master.csv")
    integrated_master = _rows(root / "data" / "csv" / "fund_master.csv")
    integrated_periods = _rows(root / "data" / "csv" / "fund_periods.csv")
    integrated_cashflows = _rows(root / "data" / "csv" / "fund_cashflows.csv")
    target_periods = [
        row
        for row in integrated_periods
        if row.get("synthetic_parameter_set_id") == "INTEGRATED_COMPLETION_V1"
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
            _check("resolved integration gaps", sum(row.get("status") == "RESOLVED" for row in gaps), len(gaps)),
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
            _check("extracted-only metric rows", len(extracted_metrics), 804),
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
            _check("integrated holdings", len(integrated_holdings), len(target_periods) * 3),
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
            _check("benchmark strategy mappings", market_live["strategy_map_rows"], 19),
            _check("benchmark strategy mappings resolve", market_live["strategy_map_resolved"], 19),
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
            _check("source-derived integrated parameters", sum(row.get("provenance_type") == "DERIVED" for row in accepted_parameters), 3),
        ]
    )
    benchmark_policy = _rows(root / "data" / "integrated" / "benchmark-policy.csv")
    promotion_rows = validate_fund_model_extracted_rows(
        root / "data" / "csv",
        root / "ledgers" / "promotion-gate",
        root / "data" / "public_markets" / "audit",
        root / "data" / "public_markets" / "staging",
        root / "ledgers" / "promotion-gate",
        root / "data" / "integrated" / "benchmark-policy.csv",
    )
    checks.extend(
        [
            _check("source promotion and benchmark gate", promotion_rows, 4_284),
            _check("benchmark policy rows", len(benchmark_policy), 1),
            _check("benchmark demo use labelled", benchmark_policy[0].get("use_status"), "DEMO_PROXY_ONLY"),
            _check(
                "benchmark production use restricted",
                benchmark_policy[0].get("rights_status"),
                "DEMONSTRATION_ONLY",
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
    if failures:
        print(f"FAIL: {len(failures)} of {len(checks)} reviewer baseline checks failed")
        return 1
    print(f"PASS: {len(checks)} reviewer baseline checks")
    print("OPEN: " + "; ".join(open_items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
