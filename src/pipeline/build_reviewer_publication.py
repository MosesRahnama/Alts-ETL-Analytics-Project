"""Build the flattened reviewer CSVs, including augmentation lineage."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from src.catalog.simple_pdf_extraction.fund_attributes import (
    FIELDS as ATTRIBUTE_FIELDS,
    attribute_evidence_lookup,
    decided_lookup,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TABLE_DIR = PROJECT_ROOT / "data" / "extracted" / "tables"
CSV_DIR = PROJECT_ROOT / "data" / "csv"
AUDIT_DIR = PROJECT_ROOT / "data" / "extracted" / "audit"
REVIEW_DIR = PROJECT_ROOT / "data" / "extracted" / "review"
INTEGRATED_DIR = PROJECT_ROOT / "data" / "integrated"
EXTRACTED_FUND_DIR = PROJECT_ROOT / "data" / "extracted" / "fund-level"

OBSERVATION_OUTPUT = REVIEW_DIR / "reviewer-observations.csv"
PERIOD_OUTPUT = REVIEW_DIR / "reviewer-fund-periods.csv"
CELL_LINEAGE_OUTPUT = REVIEW_DIR / "reviewer-cell-lineage.csv"
GAP_OUTPUT = REVIEW_DIR / "reviewer-gap-ledger.csv"
ANALYTICS_SUMMARY_OUTPUT = REVIEW_DIR / "reviewer-analytics-summary.csv"

LINEAGE_FIELDS = (
    "pair_id",
    "pair_status",
    "a_row_number",
    "b_row_number",
    "difference_fields",
    "resolution_decision",
    "resolution_reason",
    "source_sha256",
)
ATTRIBUTE_REVIEW_FIELDS = tuple(
    value
    for field in ATTRIBUTE_FIELDS
    for value in (
        f"effective_{field}",
        f"{field}_origin",
        f"{field}_source_observation_id",
        f"{field}_source_document_id",
        f"{field}_source_page",
        f"{field}_source_quote",
    )
)
OBSERVATION_REVIEW_FIELDS = (
    "promotion_status",
    "fund_period_ids",
    "quality_status",
    "failed_quality_rules",
    "analysis_result_ids",
)
PERIOD_REVIEW_FIELDS = (
    "fund_name",
    "fund_manager_name",
    "source_observation_count",
    "quality_pass_count",
    "quality_fail_count",
    "quality_skip_count",
    "quality_status",
    "failed_quality_rules",
    "analytics_provenance_type",
    "recomputed_dpi",
    "recomputed_rvpi",
    "recomputed_tvpi",
    "recomputed_irr",
    "recomputed_ks_pme",
    "recomputed_direct_alpha",
    "analysis_benchmark_ids",
    "analysis_result_ids",
    "attribute_change_ids",
    "term_management_fee_rate",
    "term_management_fee_basis",
    "term_carry_rate",
    "term_hurdle_rate",
    "term_catch_up_rate",
    "term_catch_up_present",
    "term_waterfall_type",
    "term_fund_term_years",
    "term_extension_years",
    "term_preferred_return_compounding",
    "term_expense_cap_rate",
    "term_maximum_offering",
    "term_currency",
    "term_id",
    "term_scope",
    "term_effective_date",
    "term_effective_end_date",
    "term_provenance_type",
    "term_source_document_id",
    "term_source_page",
    "term_source_anchor",
    "term_synthetic_parameter_set_id",
    "term_clause_id",
    "term_clause_metric_id",
    "term_clause_title",
    "term_clause_value_raw",
    "term_clause_value_text",
    "term_clause_effective_date",
    "term_clause_effective_end_date",
    "term_clause_provenance_type",
    "term_clause_source_document_id",
    "term_clause_source_page",
    "term_clause_source_anchor",
    "term_clause_synthetic_parameter_set_id",
    "holding_count",
    "holding_fair_value_total",
    "holding_ids",
    "holding_as_of_date",
    "holding_provenance_type",
    "holding_source_document_ids",
    "holding_source_pages",
    "holding_source_anchors",
    "holding_synthetic_parameter_set_ids",
    "allocation_id",
    "portfolio_id",
    "portfolio_as_of_date",
    "portfolio_target_weight",
    "portfolio_minimum_weight",
    "portfolio_maximum_weight",
    "portfolio_commitment_amount",
    "portfolio_nav_amount",
    "portfolio_unfunded_amount",
    "portfolio_expected_return",
    "portfolio_expected_volatility",
    "portfolio_liquidity_score",
    "portfolio_strategy",
    "portfolio_sub_strategy",
    "portfolio_provenance_type",
    "portfolio_source_document_id",
    "portfolio_synthetic_parameter_set_id",
    "portfolio_optimization_run_id",
)
ANALYTICS_SUMMARY_FIELDS = (
    "record_type",
    "population",
    "metric_id",
    "group_name",
    "row_count",
    "min_value",
    "p25_value",
    "median_value",
    "p75_value",
    "max_value",
    "weighted_value",
    "unit",
    "provenance_type",
    "source_file",
    "notes",
)


class ReviewerPublicationError(ValueError):
    """Raised when a reviewer join cannot be reproduced from issued artifacts."""


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise ReviewerPublicationError(f"missing input: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ReviewerPublicationError(f"CSV has no header: {path}")
        return list(reader.fieldnames), [
            {key: (value or "").strip() for key, value in row.items()} for row in reader
        ]


def write_csv(path: Path, header: Iterable[str], rows: Iterable[Mapping[str, str]]) -> int:
    fields = list(header)
    if len(fields) != len(set(fields)):
        raise ReviewerPublicationError(f"duplicate output column in {path.name}")
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in materialized)
    return len(materialized)


def split_ids(value: str) -> list[str]:
    normalized = value.replace(" | ", ";").replace("|", ";")
    return [part.strip() for part in normalized.split(";") if part.strip()]


def join_ids(values: Iterable[str]) -> str:
    return " | ".join(sorted({value for value in values if value}))


def _format_number(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ReviewerPublicationError("cannot summarize an empty analytical population")
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _distribution_row(
    *,
    population: str,
    metric_id: str,
    values: list[float],
    unit: str,
    provenance_type: str,
    source_file: str,
) -> dict[str, str]:
    return {
        "record_type": "distribution",
        "population": population,
        "metric_id": metric_id,
        "group_name": "ALL",
        "row_count": str(len(values)),
        "min_value": _format_number(min(values)),
        "p25_value": _format_number(_percentile(values, 0.25)),
        "median_value": _format_number(_percentile(values, 0.50)),
        "p75_value": _format_number(_percentile(values, 0.75)),
        "max_value": _format_number(max(values)),
        "weighted_value": "",
        "unit": unit,
        "provenance_type": provenance_type,
        "source_file": source_file,
        "notes": "Reviewer-facing distribution; source rows remain unchanged.",
    }


def quality_summary(rows: Iterable[Mapping[str, str]]) -> dict[str, str]:
    materialized = list(rows)
    counts = {
        status: sum(row.get("status", "").upper() == status for row in materialized)
        for status in ("PASS", "FAIL", "SKIP")
    }
    if counts["FAIL"]:
        status = "FAIL"
    elif counts["PASS"]:
        status = "PASS"
    elif counts["SKIP"]:
        status = "NOT_TESTABLE"
    else:
        status = "NOT_CHECKED"
    return {
        "quality_pass_count": str(counts["PASS"]),
        "quality_fail_count": str(counts["FAIL"]),
        "quality_skip_count": str(counts["SKIP"]),
        "quality_status": status,
        "failed_quality_rules": join_ids(
            row.get("rule_id", "")
            for row in materialized
            if row.get("status", "").upper() == "FAIL"
        ),
    }


def attribute_review(
    observation: Mapping[str, str],
    settled: Mapping[str, Mapping[str, str]],
    evidence: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> dict[str, str]:
    fund_id = observation.get("subject_entity_id", "")
    out: dict[str, str] = {}
    for field in ATTRIBUTE_FIELDS:
        printed = observation.get(field, "")
        chosen = settled.get(fund_id, {}).get(field, "")
        source = evidence.get(fund_id, {}).get(field, {})
        if printed:
            value = printed
            origin = "PRINTED_ON_ROW"
            source = {
                "source_observation_id": observation.get("observation_id", ""),
                "source_document_id": observation.get("document_id", ""),
                "source_page": observation.get("source_page", ""),
                "source_quote": observation.get("evidence_quote", ""),
            }
        elif chosen:
            value = chosen
            origin = "INHERITED_FROM_SAME_FUND"
        else:
            value = ""
            origin = "MISSING"
        out.update(
            {
                f"effective_{field}": value,
                f"{field}_origin": origin,
                f"{field}_source_observation_id": source.get("source_observation_id", ""),
                f"{field}_source_document_id": source.get("source_document_id", ""),
                f"{field}_source_page": source.get("source_page", ""),
                f"{field}_source_quote": source.get("source_quote", ""),
            }
        )
    return out


def build_observations() -> int:
    observation_header, observations = read_csv(TABLE_DIR / "fact_observation.csv")
    _, lineage_rows = read_csv(TABLE_DIR / "observation_lineage.csv")
    _, fund_observations = read_csv(CSV_DIR / "fund_observations.csv")
    _, periods = read_csv(CSV_DIR / "fund_periods.csv")
    _, quality = read_csv(EXTRACTED_FUND_DIR / "quality_results.csv")
    _, metrics = read_csv(CSV_DIR / "fund_metrics.csv")
    _, extracted_metrics = read_csv(EXTRACTED_FUND_DIR / "fund_metrics.csv")
    _, pme = read_csv(CSV_DIR / "pme_results.csv")
    _, mismatches = read_csv(AUDIT_DIR / "promotion-category-mismatches.csv")

    lineage = {row["observation_id"]: row for row in lineage_rows}
    if len(lineage) != len(lineage_rows):
        raise ReviewerPublicationError("observation_lineage has duplicate observation_id values")
    if {row["observation_id"] for row in observations} != set(lineage):
        raise ReviewerPublicationError("observation_lineage does not cover fact_observation exactly")

    promoted = {row["observation_id"] for row in fund_observations}
    withheld = {row["observation_id"] for row in mismatches}
    periods_by_observation: dict[str, list[str]] = defaultdict(list)
    qualities_by_period: dict[str, list[dict[str, str]]] = defaultdict(list)
    metrics_by_period: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in periods:
        for observation_id in split_ids(row.get("input_observation_ids", "")):
            periods_by_observation[observation_id].append(row["fund_period_id"])
    for row in quality:
        if row.get("record_table") == "fund_periods":
            qualities_by_period[row.get("record_id", "")].append(row)
    for row in [*metrics, *extracted_metrics, *pme]:
        for period_id in split_ids(row.get("input_record_ids", "")):
            metrics_by_period[period_id].append(row)

    settled = decided_lookup()
    evidence = attribute_evidence_lookup(observations=observations)
    output = []
    for observation in observations:
        observation_id = observation["observation_id"]
        period_ids = periods_by_observation.get(observation_id, [])
        q_rows = [row for period_id in period_ids for row in qualities_by_period.get(period_id, [])]
        metric_rows = [row for period_id in period_ids for row in metrics_by_period.get(period_id, [])]
        if observation_id in promoted:
            promotion_status = "PROMOTED_OBSERVATION"
        elif observation_id in withheld:
            promotion_status = "WITHHELD_CATEGORY_MISMATCH"
        elif observation.get("subject_type") == "fund" and observation.get("subject_entity_id"):
            promotion_status = "FUND_CONTEXT_NOT_PROMOTED"
        else:
            promotion_status = "NON_FUND_GRAIN"
        q_summary = quality_summary(q_rows)
        line = lineage[observation_id]
        output.append(
            {
                **observation,
                **{f"lineage_{field}": line.get(field, "") for field in LINEAGE_FIELDS},
                **attribute_review(observation, settled, evidence),
                "promotion_status": promotion_status,
                "fund_period_ids": join_ids(period_ids),
                "quality_status": q_summary["quality_status"],
                "failed_quality_rules": q_summary["failed_quality_rules"],
                "analysis_result_ids": join_ids(
                    row.get("analysis_result_id", "") for row in metric_rows
                ),
            }
        )
    return write_csv(
        OBSERVATION_OUTPUT,
        (
            *observation_header,
            *(f"lineage_{field}" for field in LINEAGE_FIELDS),
            *ATTRIBUTE_REVIEW_FIELDS,
            *OBSERVATION_REVIEW_FIELDS,
        ),
        output,
    )


def _period_attribute_source(
    period: Mapping[str, str],
    field: str,
    changes: Mapping[tuple[str, str], Mapping[str, str]],
    observations: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    change = changes.get((period["fund_period_id"], field))
    if change:
        return {
            "origin": change.get("change_type", ""),
            "source_observation_id": change.get("source_observation_id", ""),
            "source_document_id": change.get("source_document_id", ""),
            "source_page": change.get("source_page", ""),
            "source_quote": change.get("source_quote", ""),
            "change_id": change.get("change_id", ""),
        }
    for observation_id in split_ids(period.get("input_observation_ids", "")):
        observation = observations.get(observation_id, {})
        if observation.get(field) and observation.get(field) == period.get(field):
            return {
                "origin": "PRINTED_IN_PERIOD_INPUT",
                "source_observation_id": observation_id,
                "source_document_id": observation.get("document_id", ""),
                "source_page": observation.get("source_page", ""),
                "source_quote": observation.get("evidence_quote", ""),
                "change_id": "",
            }
    if not period.get(field):
        return {"origin": "MISSING"}
    if period.get("provenance_type") == "SYNTHETIC" and period.get(
        "synthetic_parameter_set_id"
    ):
        return {"origin": "SYNTHETIC_COMPLETION"}
    raise ReviewerPublicationError(
        f"{period.get('fund_period_id', '<unknown period>')}: {field} has a value "
        "without printed, inherited, or synthetic lineage"
    )


def build_analytics_summary() -> int:
    _, extracted_periods = read_csv(EXTRACTED_FUND_DIR / "fund_periods.csv")
    _, integrated_periods = read_csv(CSV_DIR / "fund_periods.csv")
    _, extracted_metrics = read_csv(EXTRACTED_FUND_DIR / "fund_metrics.csv")
    _, integrated_metrics = read_csv(CSV_DIR / "fund_metrics.csv")
    _, pme_rows = read_csv(CSV_DIR / "pme_results.csv")
    _, allocations = read_csv(CSV_DIR / "portfolio_allocations.csv")

    rows: list[dict[str, str]] = []
    metric_sources = (
        (
            "EXTRACTED",
            extracted_metrics,
            "EXTRACTED",
            "data/extracted/fund-level/fund_metrics.csv",
        ),
        (
            "INTEGRATED",
            [*integrated_metrics, *pme_rows],
            "SYNTHETIC",
            "data/csv/fund_metrics.csv | data/csv/pme_results.csv",
        ),
    )
    for population, source_rows, provenance, source_file in metric_sources:
        by_metric: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in source_rows:
            by_metric[row.get("metric_id", "")].append(row)
        for metric_id in sorted(value for value in by_metric if value):
            metric_rows = by_metric[metric_id]
            values = [float(row["value_numeric"]) for row in metric_rows]
            rows.append(
                _distribution_row(
                    population=population,
                    metric_id=metric_id,
                    values=values,
                    unit=metric_rows[0].get("unit", ""),
                    provenance_type=provenance,
                    source_file=source_file,
                )
            )

    coverage_specs = (
        (
            "EXTRACTED",
            extracted_periods,
            extracted_metrics,
            "data/extracted/fund-level/fund_periods.csv | data/extracted/fund-level/fund_metrics.csv",
            "Source-only periods with recomputable DPI, RVPI, and TVPI.",
        ),
        (
            "INTEGRATED",
            [
                row
                for row in integrated_periods
                if row.get("synthetic_parameter_set_id") == "INTEGRATED_COMPLETION_V1"
            ],
            integrated_metrics,
            "data/csv/fund_periods.csv | data/csv/fund_metrics.csv",
            "Completed real-fund periods with the four configured metrics.",
        ),
    )
    for population, periods, metric_rows, source_file, note in coverage_specs:
        analyzed = {
            period_id
            for row in metric_rows
            for period_id in split_ids(row.get("input_record_ids", ""))
        }
        denominator = len(periods)
        numerator = len(analyzed & {row.get("fund_period_id", "") for row in periods})
        rows.append(
            {
                "record_type": "coverage",
                "population": population,
                "metric_id": "analyzable_periods",
                "group_name": "ALL",
                "row_count": str(numerator),
                "min_value": "",
                "p25_value": "",
                "median_value": "",
                "p75_value": "",
                "max_value": "",
                "weighted_value": _format_number(numerator / denominator) if denominator else "",
                "unit": "fraction_of_periods",
                "provenance_type": "EXTRACTED" if population == "EXTRACTED" else "SYNTHETIC",
                "source_file": source_file,
                "notes": f"{note} Denominator={denominator}.",
            }
        )

    weights = [float(row["target_weight"]) for row in allocations]
    weighted_return = sum(
        float(row["target_weight"]) * float(row["expected_return"]) for row in allocations
    )
    allocation_summary = _distribution_row(
        population="INTEGRATED_PORTFOLIO",
        metric_id="target_weight",
        values=weights,
        unit="portfolio_fraction",
        provenance_type="DERIVED",
        source_file="data/csv/portfolio_allocations.csv",
    )
    allocation_summary["weighted_value"] = _format_number(weighted_return)
    allocation_summary["notes"] = (
        "Bounded equal-weight demonstration; weighted_value is portfolio expected return. "
        "Volatility and liquidity remain blank because no defensible risk panel was supplied."
    )
    rows.append(allocation_summary)

    by_strategy: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in allocations:
        by_strategy[row.get("strategy", "") or "UNCLASSIFIED"].append(row)
    for strategy in sorted(by_strategy):
        strategy_rows = by_strategy[strategy]
        strategy_weights = [float(row["target_weight"]) for row in strategy_rows]
        rows.append(
            {
                "record_type": "strategy_exposure",
                "population": "INTEGRATED_PORTFOLIO",
                "metric_id": "target_weight",
                "group_name": strategy,
                "row_count": str(len(strategy_rows)),
                "min_value": _format_number(min(strategy_weights)),
                "p25_value": _format_number(_percentile(strategy_weights, 0.25)),
                "median_value": _format_number(_percentile(strategy_weights, 0.50)),
                "p75_value": _format_number(_percentile(strategy_weights, 0.75)),
                "max_value": _format_number(max(strategy_weights)),
                "weighted_value": _format_number(sum(strategy_weights)),
                "unit": "portfolio_fraction",
                "provenance_type": "DERIVED",
                "source_file": "data/csv/portfolio_allocations.csv",
                "notes": "Exposure reflects the completed demonstration population, not an investment recommendation.",
            }
        )
    return write_csv(ANALYTICS_SUMMARY_OUTPUT, ANALYTICS_SUMMARY_FIELDS, rows)


def build_periods() -> int:
    period_header, periods = read_csv(CSV_DIR / "fund_periods.csv")
    _, masters = read_csv(CSV_DIR / "fund_master.csv")
    _, integrated_quality = read_csv(CSV_DIR / "quality_results.csv")
    _, extracted_quality = read_csv(EXTRACTED_FUND_DIR / "quality_results.csv")
    _, metrics = read_csv(CSV_DIR / "fund_metrics.csv")
    _, extracted_metrics = read_csv(EXTRACTED_FUND_DIR / "fund_metrics.csv")
    _, pme = read_csv(CSV_DIR / "pme_results.csv")
    _, terms = read_csv(CSV_DIR / "fund_terms.csv")
    _, term_clauses = read_csv(CSV_DIR / "fund_term_clauses.csv")
    _, holdings = read_csv(CSV_DIR / "fund_holdings.csv")
    _, allocations = read_csv(CSV_DIR / "portfolio_allocations.csv")
    _, change_rows = read_csv(AUDIT_DIR / "attribute-changes.csv")
    _, observation_rows = read_csv(TABLE_DIR / "fact_observation.csv")

    master_by_fund = {row["fund_id"]: row for row in masters}
    term_by_fund: dict[str, dict[str, str]] = {}
    for row in terms:
        if row.get("perspective") != "fund_total" or row.get("record_status") not in {"", "ACTIVE"}:
            continue
        current = term_by_fund.get(row.get("fund_id", ""))
        if current is None or (
            row.get("provenance_type") == "EXTRACTED"
            and current.get("provenance_type") != "EXTRACTED"
        ):
            term_by_fund[row.get("fund_id", "")] = row
    clause_by_fund: dict[str, dict[str, str]] = {}
    for row in term_clauses:
        if row.get("perspective") != "fund_total" or row.get("record_status") not in {"", "ACTIVE"}:
            continue
        current = clause_by_fund.get(row.get("fund_id", ""))
        if current is None or (
            row.get("provenance_type") == "EXTRACTED"
            and current.get("provenance_type") != "EXTRACTED"
        ):
            clause_by_fund[row.get("fund_id", "")] = row
    holdings_by_fund_date: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in holdings:
        if row.get("record_status") in {"", "ACTIVE"} and row.get("as_of_date"):
            holdings_by_fund_date[row.get("fund_id", "")][row["as_of_date"]].append(row)
    allocation_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in allocations:
        key = (row.get("fund_id", ""), row.get("as_of_date", ""))
        if key in allocation_by_key:
            raise ReviewerPublicationError(f"duplicate portfolio allocation key: {key}")
        allocation_by_key[key] = row
    observations = {row["observation_id"]: row for row in observation_rows}
    changes = {
        (row["target_record_id"], row["field"]): row
        for row in change_rows
        if row.get("target_table") == "fund_periods"
    }
    integrated_quality_by_period: dict[str, list[dict[str, str]]] = defaultdict(list)
    extracted_quality_by_period: dict[str, list[dict[str, str]]] = defaultdict(list)
    metrics_by_period: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in integrated_quality:
        if row.get("record_table") == "fund_periods":
            integrated_quality_by_period[row.get("record_id", "")].append(row)
    for row in extracted_quality:
        if row.get("record_table") == "fund_periods":
            extracted_quality_by_period[row.get("record_id", "")].append(row)
    for row in [*metrics, *extracted_metrics, *pme]:
        for period_id in split_ids(row.get("input_record_ids", "")):
            metrics_by_period[period_id].append(row)

    output = []
    attribute_columns = tuple(
        value
        for field in ("vintage_year", "strategy")
        for value in (
            f"{field}_origin",
            f"{field}_source_observation_id",
            f"{field}_source_document_id",
            f"{field}_source_page",
            f"{field}_source_quote",
        )
    )
    for period in periods:
        period_id = period["fund_period_id"]
        quality_rows = (
            extracted_quality_by_period.get(period_id, [])
            if period.get("provenance_type") == "EXTRACTED"
            else integrated_quality_by_period.get(period_id, [])
        )
        q_summary = quality_summary(quality_rows)
        period_metrics = metrics_by_period.get(period_id, [])
        metric_values = {
            row.get("metric_id", ""): row.get("value_numeric", "") for row in period_metrics
        }
        attribute_values: dict[str, str] = {}
        change_ids = []
        for field in ("vintage_year", "strategy"):
            source = _period_attribute_source(period, field, changes, observations)
            attribute_values.update(
                {
                    f"{field}_origin": source.get("origin", ""),
                    f"{field}_source_observation_id": source.get("source_observation_id", ""),
                    f"{field}_source_document_id": source.get("source_document_id", ""),
                    f"{field}_source_page": source.get("source_page", ""),
                    f"{field}_source_quote": source.get("source_quote", ""),
                }
            )
            change_ids.append(source.get("change_id", ""))
        master = master_by_fund.get(period.get("fund_id", ""), {})
        term = term_by_fund.get(period.get("fund_id", ""), {})
        clause = clause_by_fund.get(period.get("fund_id", ""), {})
        holding_dates = [
            value
            for value in holdings_by_fund_date.get(period.get("fund_id", ""), {})
            if value <= period.get("as_of_date", "")
        ]
        period_holdings = (
            holdings_by_fund_date[period.get("fund_id", "")][max(holding_dates)]
            if holding_dates
            else []
        )
        fair_value_total = sum(
            float(row.get("fair_value") or 0) for row in period_holdings
        )
        holding_as_of_date = max(holding_dates) if holding_dates else ""
        allocation = allocation_by_key.get(
            (period.get("fund_id", ""), period.get("as_of_date", "")), {}
        )
        output.append(
            {
                **period,
                "fund_name": master.get("fund_name", ""),
                "fund_manager_name": master.get("fund_manager_name", ""),
                "source_observation_count": str(len(split_ids(period.get("input_observation_ids", "")))),
                **q_summary,
                "analytics_provenance_type": join_ids(
                    row.get("provenance_type", "") for row in period_metrics
                ),
                "recomputed_dpi": metric_values.get("dpi", ""),
                "recomputed_rvpi": metric_values.get("rvpi", ""),
                "recomputed_tvpi": metric_values.get("tvpi", ""),
                "recomputed_irr": metric_values.get("xirr", ""),
                "recomputed_ks_pme": metric_values.get("ks_pme", ""),
                "recomputed_direct_alpha": metric_values.get("direct_alpha", ""),
                "analysis_benchmark_ids": join_ids(
                    row.get("benchmark_id", "") for row in period_metrics
                ),
                "analysis_result_ids": join_ids(
                    row.get("analysis_result_id", "") for row in period_metrics
                ),
                "attribute_change_ids": join_ids(change_ids),
                "term_management_fee_rate": term.get("management_fee_rate", ""),
                "term_management_fee_basis": term.get("management_fee_basis", ""),
                "term_carry_rate": term.get("carry_rate", ""),
                "term_hurdle_rate": term.get("hurdle_rate", ""),
                "term_catch_up_rate": term.get("catch_up_rate", ""),
                "term_catch_up_present": term.get("catch_up_present", ""),
                "term_waterfall_type": term.get("waterfall_type", ""),
                "term_fund_term_years": term.get("fund_term_years", ""),
                "term_extension_years": term.get("extension_years", ""),
                "term_preferred_return_compounding": term.get(
                    "preferred_return_compounding", ""
                ),
                "term_expense_cap_rate": term.get("expense_cap_rate", ""),
                "term_maximum_offering": term.get("maximum_offering", ""),
                "term_currency": term.get("currency", ""),
                "term_id": term.get("fund_term_id", ""),
                "term_scope": term.get("term_scope", ""),
                "term_effective_date": term.get("effective_date", ""),
                "term_effective_end_date": term.get("effective_end_date", ""),
                "term_provenance_type": term.get("provenance_type", ""),
                "term_source_document_id": term.get("source_document_id", ""),
                "term_source_page": term.get("source_page", ""),
                "term_source_anchor": term.get("source_anchor", ""),
                "term_synthetic_parameter_set_id": term.get("synthetic_parameter_set_id", ""),
                "term_clause_id": clause.get("fund_term_clause_id", ""),
                "term_clause_metric_id": clause.get("metric_id", ""),
                "term_clause_title": clause.get("clause_title", ""),
                "term_clause_value_raw": clause.get("value_raw", ""),
                "term_clause_value_text": clause.get("value_text", ""),
                "term_clause_effective_date": clause.get("effective_date", ""),
                "term_clause_effective_end_date": clause.get("effective_end_date", ""),
                "term_clause_provenance_type": clause.get("provenance_type", ""),
                "term_clause_source_document_id": clause.get("source_document_id", ""),
                "term_clause_source_page": clause.get("source_page", ""),
                "term_clause_source_anchor": clause.get("source_anchor", ""),
                "term_clause_synthetic_parameter_set_id": clause.get(
                    "synthetic_parameter_set_id", ""
                ),
                "holding_count": str(len(period_holdings)),
                "holding_fair_value_total": f"{fair_value_total:.6f}" if period_holdings else "",
                "holding_ids": join_ids(row.get("holding_id", "") for row in period_holdings),
                "holding_as_of_date": holding_as_of_date,
                "holding_provenance_type": join_ids(
                    row.get("provenance_type", "") for row in period_holdings
                ),
                "holding_source_document_ids": join_ids(
                    row.get("source_document_id", "") for row in period_holdings
                ),
                "holding_source_pages": join_ids(
                    row.get("source_page", "") for row in period_holdings
                ),
                "holding_source_anchors": join_ids(
                    row.get("source_anchor", "") for row in period_holdings
                ),
                "holding_synthetic_parameter_set_ids": join_ids(
                    row.get("synthetic_parameter_set_id", "") for row in period_holdings
                ),
                "allocation_id": allocation.get("allocation_id", ""),
                "portfolio_id": allocation.get("portfolio_id", ""),
                "portfolio_as_of_date": allocation.get("as_of_date", ""),
                "portfolio_target_weight": allocation.get("target_weight", ""),
                "portfolio_minimum_weight": allocation.get("minimum_weight", ""),
                "portfolio_maximum_weight": allocation.get("maximum_weight", ""),
                "portfolio_commitment_amount": allocation.get("commitment_amount", ""),
                "portfolio_nav_amount": allocation.get("nav_amount", ""),
                "portfolio_unfunded_amount": allocation.get("unfunded_amount", ""),
                "portfolio_expected_return": allocation.get("expected_return", ""),
                "portfolio_expected_volatility": allocation.get("expected_volatility", ""),
                "portfolio_liquidity_score": allocation.get("liquidity_score", ""),
                "portfolio_strategy": allocation.get("strategy", ""),
                "portfolio_sub_strategy": allocation.get("sub_strategy", ""),
                "portfolio_provenance_type": allocation.get("provenance_type", ""),
                "portfolio_source_document_id": allocation.get("source_document_id", ""),
                "portfolio_synthetic_parameter_set_id": allocation.get(
                    "synthetic_parameter_set_id", ""
                ),
                "portfolio_optimization_run_id": allocation.get("optimization_run_id", ""),
                **attribute_values,
            }
        )
    return write_csv(
        PERIOD_OUTPUT,
        (*period_header, *PERIOD_REVIEW_FIELDS, *attribute_columns),
        output,
    )


def build() -> dict[str, int]:
    lineage_header, lineage_rows = read_csv(INTEGRATED_DIR / "cell-lineage.csv")
    gap_header, gap_rows = read_csv(INTEGRATED_DIR / "gap-ledger.csv")
    counts = {
        "reviewer_observations": build_observations(),
        "reviewer_fund_periods": build_periods(),
        "reviewer_cell_lineage": write_csv(CELL_LINEAGE_OUTPUT, lineage_header, lineage_rows),
        "reviewer_gap_ledger": write_csv(GAP_OUTPUT, gap_header, gap_rows),
        "reviewer_analytics_summary": build_analytics_summary(),
    }
    return counts


def main() -> int:
    counts = build()
    print(
        "PASS: reviewer publication written; "
        + ", ".join(f"{name}={count:,}" for name, count in counts.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
