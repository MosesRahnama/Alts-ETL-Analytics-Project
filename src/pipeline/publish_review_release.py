"""Rebuild the review release in order and receipt every generated artifact."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Callable, Iterable

from src.analytics import run_extracted_analytics, run_integrated_analytics
from src.catalog.simple_pdf_extraction import fund_attributes, name_normalization
from src.flatten import flatten_extracted, load_star, pivot_wide
from src.load import load_csv_to_duckdb, promote_extracted_to_fund_level
from src.load.validate_round02_promotion import validate_fund_model_extracted_rows
from src.pipeline import (
    build_extraction_review,
    build_integrated_universe,
    build_reviewer_publication,
    combine_extracted_raw,
    reviewer_check,
)
from src.pipeline.transformation_lineage import missing_current_receipts, run_stage
from src.quality import run_fund_checks


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV_DIR = PROJECT_ROOT / "data" / "csv"
TABLE_DIR = PROJECT_ROOT / "data" / "extracted" / "tables"
WIDE_DIR = PROJECT_ROOT / "data" / "extracted" / "wide"
REVIEW_DIR = PROJECT_ROOT / "data" / "extracted" / "review"
AUDIT_DIR = PROJECT_ROOT / "data" / "extracted" / "audit"
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
EXTRACTED_FUND_DIR = PROJECT_ROOT / "data" / "extracted" / "fund-level"

TABLE_OUTPUTS = tuple(
    TABLE_DIR / f"{name}.csv"
    for name in (
        "dim_document",
        "dim_page",
        "dim_entity",
        "entity_alias",
        "dim_metric",
        "fact_observation",
        "fact_holding",
        "unresolved_names",
        "MANIFEST",
    )
)
FUND_MODEL_OUTPUTS = tuple(
    CSV_DIR / filename
    for filename in (
        "manager_master.csv",
        "document_manager_map.csv",
        "fund_master.csv",
        "fund_observations.csv",
        "manager_observations.csv",
        "fund_cashflows.csv",
        "fund_periods.csv",
        "fund_terms.csv",
        "fund_term_clauses.csv",
        "fund_holdings.csv",
    )
)
REVIEWER_OUTPUTS = (
    build_reviewer_publication.OBSERVATION_OUTPUT,
    build_reviewer_publication.PERIOD_OUTPUT,
    build_reviewer_publication.CELL_LINEAGE_OUTPUT,
    build_reviewer_publication.GAP_OUTPUT,
    build_reviewer_publication.ANALYTICS_SUMMARY_OUTPUT,
)
EXTRACTION_REVIEW_OUTPUTS = (
    TABLE_DIR / "observation_lineage.csv",
    TABLE_DIR / "MANIFEST.csv",
    *(REVIEW_DIR / name for name in (
        "document-summary.csv",
        "disagreement-fields.csv",
        "observation-lineage.csv",
        "trace-sample.csv",
        "reviewer-queries.sql",
    )),
)
GOVERNED_OUTPUTS = (
    TABLE_DIR / "fact_observation.csv",
    TABLE_DIR / "observation_lineage.csv",
    WAREHOUSE_DIR / "extracted.duckdb",
    *FUND_MODEL_OUTPUTS,
    *build_integrated_universe.extracted_outputs(),
    EXTRACTED_FUND_DIR / "quality_results.csv",
    EXTRACTED_FUND_DIR / "fund_metrics.csv",
    *build_integrated_universe.integrated_outputs(),
    AUDIT_DIR / "attribute-inherit.csv",
    AUDIT_DIR / "attribute-changes.csv",
    CSV_DIR / "quality_results.csv",
    CSV_DIR / "fund_metrics.csv",
    CSV_DIR / "pme_results.csv",
    CSV_DIR / "portfolio_allocations.csv",
    *REVIEWER_OUTPUTS,
    WAREHOUSE_DIR / "alts.duckdb",
)


class ReleaseError(RuntimeError):
    """Raised when a release stage or closing gate fails."""


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def require_zero(label: str, action: Callable[[], int]) -> int:
    result = action()
    if result != 0:
        raise ReleaseError(f"{label} returned {result}")
    return result


def stage(
    order: int,
    stage_id: str,
    command: str,
    inputs: Iterable[Path],
    outputs: Iterable[Path],
    action: Callable[[], object],
) -> None:
    result, receipts = run_stage(
        stage_id=stage_id,
        stage_order=order,
        command=command,
        inputs=inputs,
        outputs=outputs,
        action=action,
    )
    print(f"PASS: {order:03d} {stage_id}; new_receipts={len(receipts)}")


def working_final_files() -> list[Path]:
    return sorted(
        path
        for path in (PROJECT_ROOT / "ledgers" / "working" / "pdf-extraction-csv").glob(
            "*/SRC*/records-final.csv"
        )
    )


def raw_files() -> list[Path]:
    return [
        combine_extracted_raw.RAW_DIR / f"{route.name}.csv"
        for route in combine_extracted_raw.rounds()
    ]


def round_files() -> list[Path]:
    return sorted(flatten_extracted.ROUNDS_DIR.glob("*.csv"))


def extraction_review_inputs() -> list[Path]:
    paths = [
        TABLE_DIR / "fact_observation.csv",
        PROJECT_ROOT / "data" / "schemas" / "EXTRACTION-ROUTING.csv",
        PROJECT_ROOT / "data-gathering" / "source_ledger.csv",
    ]
    for folder in build_extraction_review.data_folders(build_extraction_review.WORKING_ROOT):
        paths.extend(
            folder / name
            for name in (
                "records-a.csv",
                "records-b.csv",
                "records-final.csv",
                "coverage-final.csv",
                "pair-index.csv",
                "resolution.csv",
            )
        )
    return paths


def verify_raw_round_relation() -> int:
    compared = 0
    for raw_path in raw_files():
        route = raw_path.stem
        round_path = flatten_extracted.ROUNDS_DIR / f"{route}-records.csv"
        if not round_path.is_file():
            raise ReleaseError(f"missing published records file for {route}")
        with raw_path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw_reader = csv.DictReader(handle)
            raw_header = list(raw_reader.fieldnames or [])
            raw_rows = list(raw_reader)
        with round_path.open("r", encoding="utf-8-sig", newline="") as handle:
            round_reader = csv.DictReader(handle)
            round_header = list(round_reader.fieldnames or [])
            published_rows = list(round_reader)
        if round_header != [*raw_header, "extractor_model"]:
            raise ReleaseError(f"{round_path.name}: expected raw columns plus extractor_model")
        projected = [{field: row.get(field, "") for field in raw_header} for row in published_rows]
        if projected != raw_rows:
            raise ReleaseError(f"{route}: raw and published record bytes differ by core field")
        if any(not row.get("extractor_model", "") for row in published_rows):
            raise ReleaseError(f"{route}: published row lacks extractor_model attribution")
        compared += len(raw_rows)
    return compared


def wide_outputs() -> list[Path]:
    names = [pivot_wide.table_name(family) for family in pivot_wide.families()]
    names.append("bridge_pivot_observation")
    return [*(WIDE_DIR / f"{name}.csv" for name in names), WIDE_DIR / "MANIFEST.csv", pivot_wide.DDL_PATH]


def gate_outputs() -> list[Path]:
    routes = sorted({row["route"] for row in csv_rows(TABLE_DIR / "fact_observation.csv")})
    outputs = [promote_extracted_to_fund_level.GATE_DIR / "progress.csv"]
    for route in routes:
        outputs.extend(
            (
                promote_extracted_to_fund_level.GATE_DIR / route / "assignment.json",
                promote_extracted_to_fund_level.GATE_DIR / route / "worksheet.csv",
            )
        )
    return outputs


def quality_action() -> int:
    periods = run_fund_checks.read_csv(CSV_DIR / "fund_periods.csv")
    results = run_fund_checks.run_quality_checks(
        periods,
        run_fund_checks.read_csv(CSV_DIR / "fund_cashflows.csv"),
        run_fund_checks.read_csv(CSV_DIR / "fund_master.csv"),
        manager_observations=run_fund_checks.read_csv(CSV_DIR / "manager_observations.csv"),
        manager_master=run_fund_checks.read_csv(CSV_DIR / "manager_master.csv"),
        fund_terms=run_fund_checks.read_csv(CSV_DIR / "fund_terms.csv"),
        fund_term_clauses=run_fund_checks.read_csv(CSV_DIR / "fund_term_clauses.csv"),
        fund_holdings=run_fund_checks.read_csv(CSV_DIR / "fund_holdings.csv"),
        run_id="INTEGRATED_QC_V1",
        checked_at="1970-01-01T00:00:00Z",
        tolerances=run_fund_checks.load_tolerances(PROJECT_ROOT / "config" / "quality_rules.yml"),
        printed_precision=run_fund_checks.printed_precision_from_observations(
            periods, run_fund_checks.read_csv(TABLE_DIR / "fact_observation.csv")
        ),
    )
    run_fund_checks.write_results(CSV_DIR / "quality_results.csv", results)
    return len(results)


def extracted_quality_action() -> int:
    periods = run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_periods.csv")
    results = run_fund_checks.run_quality_checks(
        periods,
        run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_cashflows.csv"),
        run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_master.csv"),
        manager_observations=run_fund_checks.read_csv(
            EXTRACTED_FUND_DIR / "manager_observations.csv"
        ),
        manager_master=run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "manager_master.csv"),
        fund_terms=run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_terms.csv"),
        fund_term_clauses=run_fund_checks.read_csv(
            EXTRACTED_FUND_DIR / "fund_term_clauses.csv"
        ),
        fund_holdings=run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_holdings.csv"),
        run_id="EXTRACTED_QC_V1",
        checked_at="1970-01-01T00:00:00Z",
        tolerances=run_fund_checks.load_tolerances(
            PROJECT_ROOT / "config" / "quality_rules.yml"
        ),
        printed_precision=run_fund_checks.printed_precision_from_observations(
            periods, run_fund_checks.read_csv(TABLE_DIR / "fact_observation.csv")
        ),
    )
    run_fund_checks.write_results(EXTRACTED_FUND_DIR / "quality_results.csv", results)
    return len(results)


def closing_gate() -> None:
    checks, open_items = reviewer_check.run_checks(PROJECT_ROOT)
    failures = [check for check in checks if not check.passed]
    if failures:
        rendered = "; ".join(
            f"{check.name}={check.actual!r} expected {check.expected!r}" for check in failures
        )
        raise ReleaseError(f"reviewer gate failed: {rendered}")
    missing = missing_current_receipts(GOVERNED_OUTPUTS)
    if missing:
        raise ReleaseError("current outputs lack receipts: " + ", ".join(missing))
    print(f"PASS: closing reviewer gate; checks={len(checks)}, open_items={len(open_items)}")


def publish() -> None:
    finals = working_final_files()
    if not finals:
        raise ReleaseError("no adjudicated records-final.csv files found")
    raw = raw_files()
    rounds = round_files()
    if not rounds:
        raise ReleaseError("no published round CSVs found")

    stage(
        10,
        "source-verification",
        "python -m src.pipeline.combine_extracted_raw --check",
        finals,
        raw,
        lambda: require_zero("raw verification", lambda: combine_extracted_raw.combine(True)),
    )
    record_rounds = [path for path in rounds if path.name.endswith("-records.csv")]
    stage(
        15,
        "round-publication-verification",
        "verify raw core fields; record extractor_model publication attribution",
        raw,
        record_rounds,
        verify_raw_round_relation,
    )
    stage(
        20,
        "normalization-gates",
        "name_normalization check; fund_attributes conflicts --strict",
        (
            name_normalization.FUND_MATRIX,
            name_normalization.MANAGER_MATRIX,
            name_normalization.LP_MATRIX,
            name_normalization.PLAN_MATRIX,
            name_normalization.COMPANY_MATRIX,
            fund_attributes.MATRIX,
        ),
        (fund_attributes.CONFLICTS,),
        lambda: (
            require_zero("name normalization", name_normalization.check),
            require_zero("attribute conflicts", lambda: fund_attributes.conflicts(True)),
        ),
    )
    stage(
        30,
        "flatten",
        "python -m src.flatten.flatten_extracted",
        (
            *rounds,
            flatten_extracted.SOURCE_LEDGER,
            flatten_extracted.CATEGORY_CATALOGUE,
            flatten_extracted.STANDARD_MEASURES,
            flatten_extracted.REGISTRY,
            flatten_extracted.FUND_MATRIX,
        ),
        TABLE_OUTPUTS,
        lambda: flatten_extracted.build_tables(TABLE_DIR),
    )
    stage(
        40,
        "extraction-review",
        "python -m src.pipeline.build_extraction_review",
        extraction_review_inputs(),
        EXTRACTION_REVIEW_OUTPUTS,
        build_extraction_review.build,
    )
    stage(
        50,
        "wide",
        "python -m src.flatten.pivot_wide",
        (TABLE_DIR / "fact_observation.csv", TABLE_DIR / "fact_holding.csv"),
        wide_outputs(),
        lambda: pivot_wide.build_wide_tables(TABLE_DIR, WIDE_DIR),
    )
    stage(
        60,
        "extracted-database",
        "python -m src.flatten.load_star",
        (*TABLE_OUTPUTS, TABLE_DIR / "observation_lineage.csv", *wide_outputs()),
        (WAREHOUSE_DIR / "extracted.duckdb",),
        lambda: load_star.load(
            TABLE_DIR, WAREHOUSE_DIR / "extracted.duckdb", rebuild=True, wide_dir=WIDE_DIR
        ),
    )
    stage(
        70,
        "attribute-audit",
        "python -m src.catalog.simple_pdf_extraction.fund_attributes apply",
        (TABLE_DIR / "fact_observation.csv", fund_attributes.MATRIX),
        (fund_attributes.INHERIT_LOG,),
        fund_attributes.apply,
    )
    promotion_outputs = (
        *FUND_MODEL_OUTPUTS,
        AUDIT_DIR / "promotion-category-mismatches.csv",
        fund_attributes.ATTRIBUTE_CHANGES,
        *gate_outputs(),
    )
    stage(
        80,
        "fund-model-promotion",
        "python -m src.load.promote_extracted_to_fund_level",
        (
            TABLE_DIR / "fact_observation.csv",
            TABLE_DIR / "fact_holding.csv",
            fund_attributes.MATRIX,
            PROJECT_ROOT / "data" / "normalization" / "entity-ids.csv",
            *finals,
        ),
        promotion_outputs,
        promote_extracted_to_fund_level.promote,
    )
    stage(
        90,
        "promotion-gate",
        "python -m src.load.validate_round02_promotion",
        promotion_outputs,
        FUND_MODEL_OUTPUTS,
        lambda: validate_fund_model_extracted_rows(CSV_DIR),
    )
    stage(
        95,
        "extracted-fund-level-snapshot",
        "python -m src.pipeline.build_integrated_universe --snapshot-only",
        tuple(
            CSV_DIR / filename for filename in build_integrated_universe.EXTRACTED_FILES
        ),
        build_integrated_universe.extracted_outputs(),
        build_integrated_universe.snapshot_extracted,
    )
    stage(
        100,
        "integrated-completion",
        "python -m src.pipeline.build_integrated_universe",
        (
            *build_integrated_universe.extracted_outputs(),
            build_integrated_universe.CONFIG_PATH,
            build_integrated_universe.NORMALIZATION_DIR / "entity-ids.csv",
            build_integrated_universe.NORMALIZATION_DIR / "fund-attributes-matrix.csv",
            build_integrated_universe.PUBLIC_MARKET_DIR / "benchmark_master_candidates.csv",
            build_integrated_universe.PUBLIC_MARKET_DIR / "benchmark_return_candidates.csv",
        ),
        build_integrated_universe.integrated_outputs(),
        build_integrated_universe.build,
    )
    stage(
        105,
        "benchmark-rights-gate",
        "python -m src.load.validate_round02_promotion",
        (
            CSV_DIR / "benchmark_returns.csv",
            PROJECT_ROOT / "data" / "public_markets" / "audit" / "source_file_inventory.csv",
            PROJECT_ROOT / "data" / "public_markets" / "audit" / "quality_results.csv",
            PROJECT_ROOT / "data" / "public_markets" / "staging" / "benchmark_master_candidates.csv",
            PROJECT_ROOT / "data" / "integrated" / "benchmark-policy.csv",
        ),
        (CSV_DIR / "benchmark_returns.csv",),
        lambda: validate_fund_model_extracted_rows(CSV_DIR),
    )
    stage(
        110,
        "quality",
        "python -m src.quality.run_fund_checks --run-id INTEGRATED_QC_V1",
        (*FUND_MODEL_OUTPUTS, *build_integrated_universe.integrated_outputs()),
        (CSV_DIR / "quality_results.csv",),
        quality_action,
    )
    stage(
        112,
        "extracted-only-quality",
        "python -m src.quality.run_fund_checks --run-id EXTRACTED_QC_V1",
        (
            EXTRACTED_FUND_DIR / "fund_periods.csv",
            EXTRACTED_FUND_DIR / "fund_cashflows.csv",
            EXTRACTED_FUND_DIR / "fund_master.csv",
            EXTRACTED_FUND_DIR / "manager_observations.csv",
            EXTRACTED_FUND_DIR / "manager_master.csv",
            EXTRACTED_FUND_DIR / "fund_terms.csv",
            EXTRACTED_FUND_DIR / "fund_term_clauses.csv",
            EXTRACTED_FUND_DIR / "fund_holdings.csv",
            PROJECT_ROOT / "config" / "quality_rules.yml",
        ),
        (EXTRACTED_FUND_DIR / "quality_results.csv",),
        extracted_quality_action,
    )
    stage(
        115,
        "extracted-only-analytics",
        "python -m src.analytics.run_extracted_analytics",
        (
            EXTRACTED_FUND_DIR / "fund_periods.csv",
            EXTRACTED_FUND_DIR / "fund_cashflows.csv",
            EXTRACTED_FUND_DIR / "quality_results.csv",
        ),
        (EXTRACTED_FUND_DIR / "fund_metrics.csv",),
        lambda: run_extracted_analytics.run(
            EXTRACTED_FUND_DIR,
            quality_path=EXTRACTED_FUND_DIR / "quality_results.csv",
        ),
    )
    stage(
        120,
        "analytics",
        "python -m src.analytics.run_integrated_analytics",
        (
            CSV_DIR / "fund_periods.csv",
            CSV_DIR / "fund_cashflows.csv",
            CSV_DIR / "fund_master.csv",
            CSV_DIR / "benchmark_returns.csv",
            CSV_DIR / "quality_results.csv",
            build_integrated_universe.CONFIG_PATH,
        ),
        (
            CSV_DIR / "fund_metrics.csv",
            CSV_DIR / "pme_results.csv",
            CSV_DIR / "portfolio_allocations.csv",
        ),
        lambda: run_integrated_analytics.run(CSV_DIR),
    )
    stage(
        130,
        "reviewer-publication",
        "python -m src.pipeline.build_reviewer_publication",
        (
            TABLE_DIR / "fact_observation.csv",
            TABLE_DIR / "observation_lineage.csv",
            *FUND_MODEL_OUTPUTS,
            CSV_DIR / "quality_results.csv",
            EXTRACTED_FUND_DIR / "quality_results.csv",
            CSV_DIR / "fund_metrics.csv",
            EXTRACTED_FUND_DIR / "fund_metrics.csv",
            CSV_DIR / "pme_results.csv",
            CSV_DIR / "portfolio_allocations.csv",
            build_integrated_universe.INTEGRATED_DIR / "cell-lineage.csv",
            build_integrated_universe.INTEGRATED_DIR / "gap-ledger.csv",
            fund_attributes.ATTRIBUTE_CHANGES,
        ),
        REVIEWER_OUTPUTS,
        build_reviewer_publication.build,
    )
    stage(
        140,
        "fund-model-database",
        "python -m src.load.load_csv_to_duckdb --rebuild",
        tuple(CSV_DIR / filename for filename in load_csv_to_duckdb.TABLE_FILES.values()),
        (WAREHOUSE_DIR / "alts.duckdb",),
        lambda: load_csv_to_duckdb.load(
            CSV_DIR, WAREHOUSE_DIR / "alts.duckdb", rebuild=True
        ),
    )
    closing_gate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        publish()
    except (OSError, ValueError, ReleaseError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print("PASS: review release is reproducible, receipted, and publication-ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
