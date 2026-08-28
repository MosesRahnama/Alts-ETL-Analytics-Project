"""Calculate fund metrics, PME, and a bounded portfolio from fund-model CSV rows."""

from __future__ import annotations

import argparse
import csv
import re
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, getcontext
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.common.finance import xirr
from src.quality.run_fund_checks import (
    RESULT_COLUMNS as QUALITY_RESULT_COLUMNS,
    RULES as QUALITY_RULES,
    load_tolerances,
    run_quality_checks,
)


ANALYSIS_RESULT_COLUMNS = (
    "analysis_result_id",
    "entity_id",
    "as_of_date",
    "metric_id",
    "value_numeric",
    "unit",
    "formula_id",
    "input_record_ids",
    "benchmark_id",
    "provenance_type",
    "quality_population",
    "notes",
)

PORTFOLIO_ALLOCATION_COLUMNS = (
    "allocation_id",
    "portfolio_id",
    "as_of_date",
    "fund_id",
    "strategy",
    "sub_strategy",
    "target_weight",
    "minimum_weight",
    "maximum_weight",
    "commitment_amount",
    "nav_amount",
    "unfunded_amount",
    "expected_return",
    "expected_volatility",
    "liquidity_score",
    "provenance_type",
    "source_document_id",
    "synthetic_parameter_set_id",
    "optimization_run_id",
    "record_status",
)

QUALITY_POPULATION = "ERROR_SEVERITY_APPROVED"
WEIGHT_QUANTUM = Decimal("0.0000000001")
PositionKey = tuple[str, str, str, str]


class AnalyticsError(ValueError):
    """Raised when analytics inputs violate a calculation or data contract."""


@dataclass(frozen=True)
class _QualityState:
    run_id: str
    checked_at: str
    reviewed_period_ids: frozenset[str]
    failed_period_ids: frozenset[str]

    @property
    def population_label(self) -> str:
        approved = len(self.reviewed_period_ids - self.failed_period_ids)
        return (
            f"{QUALITY_POPULATION};run_id={self.run_id};"
            f"approved={approved};reviewed={len(self.reviewed_period_ids)}"
        )


@dataclass(frozen=True)
class _BenchmarkPoint:
    return_date: date
    level: float
    record_id: str


class _BenchmarkSeries:
    """Cumulative return index with backward-only date lookup."""

    def __init__(self, points: Sequence[_BenchmarkPoint]) -> None:
        if not points:
            raise AnalyticsError("benchmark series has no usable observations")
        self.points = tuple(points)
        self.dates = tuple(point.return_date for point in points)

    def as_of(self, target_date: date) -> _BenchmarkPoint:
        position = bisect_right(self.dates, target_date) - 1
        if position < 0:
            raise AnalyticsError(
                f"benchmark has no observation on or before {target_date.isoformat()}"
            )
        return self.points[position]


def read_csv_rows(
    path: str | Path,
    *,
    required_columns: Iterable[str] = (),
) -> list[dict[str, str]]:
    """Read fund-model CSV strings and validate the columns used by the calculation."""
    csv_path = Path(path)
    if not csv_path.is_file():
        raise AnalyticsError(f"missing CSV: {csv_path}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise AnalyticsError(f"CSV has no header: {csv_path}")
        missing = sorted(set(required_columns) - set(reader.fieldnames))
        if missing:
            raise AnalyticsError(
                f"CSV is missing required columns {', '.join(missing)}: {csv_path}"
            )
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in reader
        ]


def write_csv_rows(
    path: str | Path,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    """Write rows with a fixed header, LF endings, and deterministic field order."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def calculate_fund_metrics(
    fund_periods: Sequence[Mapping[str, str]],
    fund_cashflows: Sequence[Mapping[str, str]],
    quality_results: Sequence[Mapping[str, str]],
    *,
    through_date: date | None = None,
    strict_quality: bool = True,
    require_xirr: bool = True,
) -> list[dict[str, str]]:
    """Calculate DPI, RVPI, TVPI, and terminal-NAV XIRR for approved periods.

    `require_xirr` stays on for a population built with a full cash-flow history,
    where a period that cannot produce an IRR is a defect. It is turned off for
    promoted extraction, where a report often prints a NAV and a multiple and no
    cash flows at all: there the multiples are still measurable and the IRR row
    is left out rather than invented from one flow."""
    selected_periods = [
        row
        for row in fund_periods
        if _active(row)
        and (
            through_date is None
            or _date(row.get("as_of_date"), "fund_periods.as_of_date") <= through_date
        )
    ]
    quality_state = _quality_state(
        quality_results,
        {_required_text(row, "fund_period_id", "fund_periods") for row in selected_periods},
    )
    cashflows_by_position = _cashflows_by_position(fund_cashflows)
    output: list[dict[str, str]] = []

    for period in sorted(selected_periods, key=_period_sort_key):
        period_date = _date(period.get("as_of_date"), "fund_periods.as_of_date")
        if not _period_is_approved(period, quality_state, strict_quality):
            continue

        fund_id = _required_text(period, "fund_id", "fund_periods")
        entity_id = _entity_id(period)
        period_id = _required_text(period, "fund_period_id", "fund_periods")
        provenance_type = _analysis_provenance(period)
        paid_in = _positive_number(period.get("paid_in_capital_itd"), "paid_in_capital_itd")
        distributions = _nonnegative_number(
            period.get("distributions_itd"), "distributions_itd"
        )
        nav = _nonnegative_number(period.get("nav"), "nav")
        base_inputs = period_id
        metric_values = (
            ("dpi", distributions / paid_in, "multiple", "DPI_DISTRIBUTIONS_OVER_PAID_IN_V1"),
            ("rvpi", nav / paid_in, "multiple", "RVPI_NAV_OVER_PAID_IN_V1"),
            (
                "tvpi",
                (distributions + nav) / paid_in,
                "multiple",
                "TVPI_VALUE_OVER_PAID_IN_V1",
            ),
        )
        for metric_id, value, unit, formula_id in metric_values:
            output.append(
                _analysis_row(
                    entity_id,
                    period_date,
                    metric_id,
                    value,
                    unit,
                    formula_id,
                    base_inputs,
                    "",
                    provenance_type,
                    "Period components recomputed from paid-in capital, distributions, and NAV.",
                )
            )

        dated_cashflows, cashflow_ids = _dated_cashflows(
            cashflows_by_position.get(_position_key(period, "fund_periods"), ()),
            period_date,
            period.get("currency", ""),
        )
        if nav > 0:
            dated_cashflows.append((period_date, nav))
        try:
            calculated_xirr = xirr(dated_cashflows)
        except ValueError as exc:
            if require_xirr:
                raise AnalyticsError(
                    f"XIRR failed for {fund_id} at {period_date.isoformat()}: {exc}"
                ) from exc
            continue
        output.append(
            _analysis_row(
                entity_id,
                period_date,
                "xirr",
                calculated_xirr,
                "decimal_rate",
                "XIRR_ACTUAL_365_TERMINAL_NAV_V1",
                _join_ids([period_id, *cashflow_ids]),
                "",
                provenance_type,
                "Dated cash flows use the sign convention and terminal NAV is added on the as-of date.",
            )
        )
    if not output:
        raise AnalyticsError("no quality-approved fund periods are available for metrics")
    for row in output:
        row["quality_population"] = quality_state.population_label
    return output


def calculate_pme_results(
    fund_periods: Sequence[Mapping[str, str]],
    fund_cashflows: Sequence[Mapping[str, str]],
    benchmark_returns: Sequence[Mapping[str, str]],
    quality_results: Sequence[Mapping[str, str]],
    *,
    benchmark_id: str,
    periodicity: str | None = None,
    through_date: date | None = None,
    strict_quality: bool = True,
) -> list[dict[str, str]]:
    """Calculate Kaplan-Schoar PME and Direct Alpha with backward-only joins."""
    if not benchmark_id.strip():
        raise AnalyticsError("benchmark_id is required")
    series = _build_benchmark_series(benchmark_returns, benchmark_id, periodicity)
    selected_periods = [
        row
        for row in fund_periods
        if _active(row)
        and (
            through_date is None
            or _date(row.get("as_of_date"), "fund_periods.as_of_date") <= through_date
        )
    ]
    quality_state = _quality_state(
        quality_results,
        {_required_text(row, "fund_period_id", "fund_periods") for row in selected_periods},
    )
    cashflows_by_position = _cashflows_by_position(fund_cashflows)
    output: list[dict[str, str]] = []

    for period in sorted(selected_periods, key=_period_sort_key):
        period_date = _date(period.get("as_of_date"), "fund_periods.as_of_date")
        if not _period_is_approved(period, quality_state, strict_quality):
            continue

        fund_id = _required_text(period, "fund_id", "fund_periods")
        entity_id = _entity_id(period)
        period_id = _required_text(period, "fund_period_id", "fund_periods")
        provenance_type = _analysis_provenance(period)
        nav = _nonnegative_number(period.get("nav"), "nav")
        dated_cashflows, cashflow_ids = _dated_cashflows(
            cashflows_by_position.get(_position_key(period, "fund_periods"), ()),
            period_date,
            period.get("currency", ""),
        )
        terminal_point = series.as_of(period_date)
        terminal_level = terminal_point.level
        discounted_contributions = 0.0
        discounted_value = nav / terminal_level
        transformed_cashflows: list[tuple[date, float]] = []
        matched_benchmark_ids: list[str] = []
        for cashflow_date, amount in dated_cashflows:
            cashflow_point = series.as_of(cashflow_date)
            cashflow_level = cashflow_point.level
            matched_benchmark_ids.append(cashflow_point.record_id)
            if amount < 0:
                discounted_contributions += (-amount) / cashflow_level
            elif amount > 0:
                discounted_value += amount / cashflow_level
            transformed_cashflows.append(
                (cashflow_date, amount * terminal_level / cashflow_level)
            )
        if discounted_contributions <= 0:
            raise AnalyticsError(f"KS-PME requires a contribution for {fund_id}")
        ks_pme = discounted_value / discounted_contributions
        if nav > 0:
            transformed_cashflows.append((period_date, nav))
        try:
            direct_alpha = xirr(transformed_cashflows)
        except ValueError as exc:
            raise AnalyticsError(
                f"Direct Alpha failed for {fund_id} at {period_date.isoformat()}: {exc}"
            ) from exc

        input_ids = _join_ids(
            [period_id, *cashflow_ids, *matched_benchmark_ids, terminal_point.record_id]
        )
        output.extend(
            (
                _analysis_row(
                    entity_id,
                    period_date,
                    "ks_pme",
                    ks_pme,
                    "multiple",
                    "KS_PME_ASOF_BENCHMARK_V1",
                    input_ids,
                    benchmark_id,
                    provenance_type,
                    "Each cash flow uses the latest benchmark observation on or before its date; terminal NAV uses the as-of benchmark level.",
                ),
                _analysis_row(
                    entity_id,
                    period_date,
                    "direct_alpha",
                    direct_alpha,
                    "decimal_rate",
                    "DIRECT_ALPHA_ASOF_BENCHMARK_XIRR_V1",
                    input_ids,
                    benchmark_id,
                    provenance_type,
                    "Benchmark-scaled dated cash flows include terminal NAV on the as-of date.",
                ),
            )
        )
    if not output:
        raise AnalyticsError("no quality-approved fund periods are available for PME")
    for row in output:
        row["quality_population"] = quality_state.population_label
    return output


def bounded_equal_weights(
    bounds: Mapping[str, tuple[float | Decimal, float | Decimal]],
) -> dict[str, Decimal]:
    """Project equal weights onto per-fund bounds and return 10-decimal weights."""
    if not bounds:
        raise AnalyticsError("portfolio requires at least one fund")
    parsed: dict[str, tuple[Decimal, Decimal]] = {}
    for fund_id in sorted(bounds):
        minimum = _decimal(bounds[fund_id][0], f"{fund_id} minimum weight")
        maximum = _decimal(bounds[fund_id][1], f"{fund_id} maximum weight")
        if minimum < 0 or maximum > 1 or minimum > maximum:
            raise AnalyticsError(f"invalid bounds for {fund_id}: {minimum} to {maximum}")
        parsed[fund_id] = (minimum, maximum)
    minimum_sum = sum((pair[0] for pair in parsed.values()), Decimal(0))
    maximum_sum = sum((pair[1] for pair in parsed.values()), Decimal(0))
    if minimum_sum > 1 or maximum_sum < 1:
        raise AnalyticsError(
            f"infeasible bounds: minimum sum {minimum_sum}, maximum sum {maximum_sum}"
        )

    getcontext().prec = 40
    lower = min(minimum for minimum, _ in parsed.values())
    upper = max(maximum for _, maximum in parsed.values())
    for _ in range(200):
        level = (lower + upper) / 2
        total = sum(
            (min(max(level, minimum), maximum) for minimum, maximum in parsed.values()),
            Decimal(0),
        )
        if total < 1:
            lower = level
        else:
            upper = level
    level = (lower + upper) / 2
    weights = {
        fund_id: min(max(level, minimum), maximum).quantize(
            WEIGHT_QUANTUM, rounding=ROUND_HALF_EVEN
        )
        for fund_id, (minimum, maximum) in parsed.items()
    }
    residual = Decimal(1) - sum(weights.values(), Decimal(0))
    if residual:
        for fund_id in sorted(weights):
            minimum, maximum = parsed[fund_id]
            candidate = weights[fund_id] + residual
            if minimum <= candidate <= maximum:
                weights[fund_id] = candidate
                residual = Decimal(0)
                break
    if residual or sum(weights.values(), Decimal(0)) != 1:
        raise AnalyticsError("rounded portfolio weights failed the sum-to-one identity")
    for fund_id, weight in weights.items():
        minimum, maximum = parsed[fund_id]
        if weight < minimum or weight > maximum:
            raise AnalyticsError(f"rounded weight violates bounds for {fund_id}")
    return weights


def build_portfolio_allocations(
    fund_periods: Sequence[Mapping[str, str]],
    quality_results: Sequence[Mapping[str, str]],
    *,
    portfolio_id: str,
    as_of_date: date | None = None,
    minimum_weight: float = 0.0,
    maximum_weight: float = 1.0,
    fund_bounds: Mapping[str, tuple[float | Decimal, float | Decimal]] | None = None,
    perspective: str | None = None,
    strict_quality: bool = True,
    optimization_run_id: str = "BOUNDED_EQUAL_WEIGHT_V1",
) -> list[dict[str, str]]:
    """Build a deterministic bounded equal-weight allocation from approved periods."""
    if not portfolio_id.strip():
        raise AnalyticsError("portfolio_id is required")
    active_periods = [row for row in fund_periods if _active(row)]
    if perspective is not None:
        active_periods = [
            row for row in active_periods if _text(row.get("perspective")) == perspective
        ]
    if not active_periods:
        raise AnalyticsError("portfolio has no active fund periods")
    target_date = as_of_date or max(
        _date(row.get("as_of_date"), "fund_periods.as_of_date") for row in active_periods
    )
    latest_by_position: dict[PositionKey, Mapping[str, str]] = {}
    for row in sorted(active_periods, key=_period_sort_key):
        row_date = _date(row.get("as_of_date"), "fund_periods.as_of_date")
        if row_date > target_date:
            continue
        position_key = _position_key(row, "fund_periods")
        current = latest_by_position.get(position_key)
        if current is not None:
            current_date = _date(current.get("as_of_date"), "fund_periods.as_of_date")
            if current_date == row_date and _text(current.get("perspective")) != _text(
                row.get("perspective")
            ):
                raise AnalyticsError(
                    f"multiple perspectives exist for {_entity_id(row)} on {row_date}; select a perspective"
                )
        latest_by_position[position_key] = row

    quality_state = _quality_state(
        quality_results,
        {
            _required_text(row, "fund_period_id", "fund_periods")
            for row in active_periods
            if _date(row.get("as_of_date"), "fund_periods.as_of_date") <= target_date
        },
    )
    approved_positions = [
        row
        for row in latest_by_position.values()
        if _period_is_approved(row, quality_state, strict_quality)
    ]
    positions_by_fund: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in approved_positions:
        positions_by_fund[_required_text(row, "fund_id", "fund_periods")].append(row)
    ambiguous_funds = sorted(
        fund_id for fund_id, rows in positions_by_fund.items() if len(rows) > 1
    )
    if ambiguous_funds:
        raise AnalyticsError(
            "portfolio allocation requires one approved position per fund; "
            f"select a perspective for {', '.join(ambiguous_funds)}"
        )
    approved = {fund_id: rows[0] for fund_id, rows in positions_by_fund.items()}
    if not approved:
        raise AnalyticsError("portfolio has no quality-approved fund periods")
    effective_bounds = {
        fund_id: (fund_bounds or {}).get(fund_id, (minimum_weight, maximum_weight))
        for fund_id in approved
    }
    weights = bounded_equal_weights(effective_bounds)

    output: list[dict[str, str]] = []
    for fund_id in sorted(approved):
        row = approved[fund_id]
        minimum, maximum = effective_bounds[fund_id]
        output.append(
            {
                "allocation_id": _stable_id(
                    "ALLOC", portfolio_id, target_date.strftime("%Y%m%d"), fund_id
                ),
                "portfolio_id": portfolio_id,
                "as_of_date": target_date.isoformat(),
                "fund_id": fund_id,
                "strategy": _text(row.get("strategy")),
                "sub_strategy": _text(row.get("sub_strategy")),
                "target_weight": _format_decimal(weights[fund_id]),
                "minimum_weight": _format_decimal(_decimal(minimum, "minimum_weight")),
                "maximum_weight": _format_decimal(_decimal(maximum, "maximum_weight")),
                "commitment_amount": _text(row.get("commitment")),
                "nav_amount": _text(row.get("nav")),
                "unfunded_amount": _text(row.get("unfunded_commitment")),
                "expected_return": _first_text(
                    row.get("calculated_irr"), row.get("reported_irr"), row.get("period_return")
                ),
                "expected_volatility": "",
                "liquidity_score": "",
                "provenance_type": "DERIVED",
                "source_document_id": "",
                "synthetic_parameter_set_id": _text(row.get("synthetic_parameter_set_id")),
                "optimization_run_id": f"{optimization_run_id};quality_run={quality_state.run_id}",
                "record_status": "ACTIVE",
            }
        )
    return output


def run_round04(
    data_directory: str | Path,
    output_directory: str | Path,
    *,
    benchmark_id: str,
    portfolio_id: str = "PORTFOLIO_RECRUITMENT_BASELINE",
    as_of_date: date | None = None,
    periodicity: str | None = None,
    minimum_weight: float = 0.0,
    maximum_weight: float = 1.0,
    portfolio_perspective: str | None = None,
    fund_period_parameter_set_id: str | None = None,
    quality_config: str | Path | None = None,
) -> dict[str, int]:
    """Read fund-model inputs, write the three Round 04 outputs, and count rows."""
    data_root = Path(data_directory)
    output_root = Path(output_directory)
    periods = read_csv_rows(
        data_root / "fund_periods.csv",
        required_columns=(
            "fund_period_id",
            "fund_id",
            "lp_id",
            "lp_name",
            "share_class_name",
            "as_of_date",
            "currency",
            "paid_in_capital_itd",
            "distributions_itd",
            "nav",
            "provenance_type",
            "record_status",
        ),
    )
    cashflows = read_csv_rows(
        data_root / "fund_cashflows.csv",
        required_columns=(
            "cashflow_id",
            "fund_id",
            "lp_id",
            "lp_name",
            "share_class_name",
            "cashflow_date",
            "amount",
            "currency",
            "amount_base_currency",
            "base_currency",
            "record_status",
        ),
    )
    benchmarks = read_csv_rows(
        data_root / "benchmark_returns.csv",
        required_columns=(
            "benchmark_return_id",
            "benchmark_id",
            "return_date",
            "periodicity",
            "return_value",
            "record_status",
        ),
    )
    quality = read_csv_rows(
        data_root / "quality_results.csv",
        required_columns=QUALITY_RESULT_COLUMNS,
    )
    fund_master = read_csv_rows(
        data_root / "fund_master.csv",
        required_columns=("fund_id", "fund_name", "provenance_type"),
    )
    if fund_period_parameter_set_id is not None:
        periods = [
            row
            for row in periods
            if _text(row.get("synthetic_parameter_set_id"))
            == fund_period_parameter_set_id
        ]
        if not periods:
            raise AnalyticsError(
                "no fund periods match parameter set "
                f"{fund_period_parameter_set_id}"
            )
    _verify_quality_results(
        periods,
        cashflows,
        fund_master,
        quality,
        quality_config=quality_config,
    )
    metrics = calculate_fund_metrics(periods, cashflows, quality, through_date=as_of_date)
    pme = calculate_pme_results(
        periods,
        cashflows,
        benchmarks,
        quality,
        benchmark_id=benchmark_id,
        periodicity=periodicity,
        through_date=as_of_date,
    )
    allocations = build_portfolio_allocations(
        periods,
        quality,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        minimum_weight=minimum_weight,
        maximum_weight=maximum_weight,
        perspective=portfolio_perspective,
    )
    _require_unique_rows(
        metrics,
        "fund_metrics",
        (("analysis_result_id",), ("entity_id", "as_of_date", "metric_id")),
    )
    _require_unique_rows(
        pme,
        "pme_results",
        (
            ("analysis_result_id",),
            ("entity_id", "as_of_date", "metric_id", "benchmark_id"),
        ),
    )
    _require_unique_rows(
        allocations,
        "portfolio_allocations",
        (("allocation_id",), ("portfolio_id", "as_of_date", "fund_id")),
    )
    write_csv_rows(output_root / "fund_metrics.csv", ANALYSIS_RESULT_COLUMNS, metrics)
    write_csv_rows(output_root / "pme_results.csv", ANALYSIS_RESULT_COLUMNS, pme)
    write_csv_rows(
        output_root / "portfolio_allocations.csv",
        PORTFOLIO_ALLOCATION_COLUMNS,
        allocations,
    )
    return {
        "fund_metrics.csv": len(metrics),
        "pme_results.csv": len(pme),
        "portfolio_allocations.csv": len(allocations),
    }


def _quality_state(
    rows: Sequence[Mapping[str, str]], expected_period_ids: set[str]
) -> _QualityState:
    """Select one complete quality run covering every analytical period."""

    if not expected_period_ids:
        raise AnalyticsError("quality gate has zero active fund periods")
    expected_rules = {rule_id: severity for rule_id, severity in QUALITY_RULES}
    by_run: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        if _text(row.get("record_table")).lower() != "fund_periods":
            continue
        run_id = _text(row.get("run_id"))
        if run_id:
            by_run[run_id].append(row)

    complete: list[tuple[datetime, str, str, set[str]]] = []
    for run_id, run_rows in by_run.items():
        indexed: dict[tuple[str, str], Mapping[str, str]] = {}
        duplicate = False
        checked_at_values: set[str] = set()
        for row in run_rows:
            record_id = _text(row.get("record_id"))
            rule_id = _text(row.get("rule_id"))
            if record_id not in expected_period_ids or rule_id not in expected_rules:
                continue
            key = (record_id, rule_id)
            if key in indexed:
                duplicate = True
                break
            indexed[key] = row
            checked_at_values.add(_text(row.get("checked_at")))
        if duplicate or len(checked_at_values) != 1 or "" in checked_at_values:
            continue
        checked_at = next(iter(checked_at_values))
        checked_at_time = _timestamp(checked_at, f"quality run {run_id} checked_at")
        required_keys = {
            (record_id, rule_id)
            for record_id in expected_period_ids
            for rule_id in expected_rules
        }
        if set(indexed) != required_keys:
            continue
        invalid = False
        failed: set[str] = set()
        for (record_id, rule_id), row in indexed.items():
            if _text(row.get("severity")).lower() != expected_rules[rule_id]:
                invalid = True
                break
            status = _text(row.get("status")).upper()
            if status not in {"PASS", "FAIL", "SKIP"}:
                invalid = True
                break
            if expected_rules[rule_id] == "error" and status == "FAIL":
                failed.add(record_id)
        if not invalid:
            complete.append((checked_at_time, run_id, checked_at, failed))
    if not complete:
        raise AnalyticsError(
            "quality gate lacks one coherent R01-through-R15 run for every active fund period"
        )
    _, run_id, checked_at, failed = max(complete, key=lambda item: (item[0], item[1]))
    return _QualityState(
        run_id,
        checked_at,
        frozenset(expected_period_ids),
        frozenset(failed),
    )


def _verify_quality_results(
    fund_periods: Sequence[Mapping[str, str]],
    fund_cashflows: Sequence[Mapping[str, str]],
    fund_master: Sequence[Mapping[str, str]],
    quality_results: Sequence[Mapping[str, str]],
    *,
    quality_config: str | Path | None,
) -> _QualityState:
    """Recompute the selected quality run from its fund-model source rows."""

    active_periods = [row for row in fund_periods if _active(row)]
    expected_period_ids = {
        _required_text(row, "fund_period_id", "fund_periods") for row in active_periods
    }
    state = _quality_state(quality_results, expected_period_ids)
    supplied = {
        (_text(row.get("record_id")), _text(row.get("rule_id"))): row
        for row in quality_results
        if _text(row.get("run_id")) == state.run_id
        and _text(row.get("record_table")).lower() == "fund_periods"
        and _text(row.get("record_id")) in expected_period_ids
    }
    recomputed_rows = run_quality_checks(
        active_periods,
        fund_cashflows,
        fund_master,
        run_id=state.run_id,
        checked_at=state.checked_at,
        tolerances=load_tolerances(quality_config),
    )
    comparison_fields = (
        "quality_result_id",
        "fund_id",
        "severity",
        "status",
        "actual_value",
        "expected_value",
        "difference",
        "tolerance",
        "source_document_id",
        "synthetic_parameter_set_id",
        "checked_at",
        "notes",
    )
    mismatches: list[str] = []
    for expected in recomputed_rows:
        key = (expected["record_id"], expected["rule_id"])
        actual = supplied.get(key)
        if actual is None:
            mismatches.append(f"{key[0]}.{key[1]} is missing")
            continue
        different = [
            field
            for field in comparison_fields
            if _text(actual.get(field)) != _text(expected.get(field))
        ]
        if different:
            mismatches.append(f"{key[0]}.{key[1]} differs in {','.join(different)}")
    if mismatches:
        raise AnalyticsError(
            "quality_results.csv differs from deterministic R01-through-R15 recomputation: "
            + "; ".join(mismatches[:20])
        )
    return state


def _require_unique_rows(
    rows: Sequence[Mapping[str, str]],
    table: str,
    key_sets: Sequence[Sequence[str]],
) -> None:
    """Reject blank or repeated primary and analytical business keys."""

    for fields in key_sets:
        seen: set[tuple[str, ...]] = set()
        for row_number, row in enumerate(rows, start=1):
            key = tuple(_text(row.get(field)) for field in fields)
            if any(not value for value in key):
                raise AnalyticsError(
                    f"{table} row {row_number} has a blank key component in {','.join(fields)}"
                )
            if key in seen:
                raise AnalyticsError(
                    f"{table} has a duplicate {','.join(fields)} key: {'|'.join(key)}"
                )
            seen.add(key)


def _period_is_approved(
    period: Mapping[str, str], quality_state: _QualityState, strict_quality: bool
) -> bool:
    period_id = _required_text(period, "fund_period_id", "fund_periods")
    if period_id in quality_state.failed_period_ids:
        return False
    if strict_quality and period_id not in quality_state.reviewed_period_ids:
        return False
    return True


def _cashflows_by_position(
    rows: Sequence[Mapping[str, str]],
) -> dict[PositionKey, list[Mapping[str, str]]]:
    grouped: dict[PositionKey, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        if _active(row):
            grouped[_position_key(row, "fund_cashflows")].append(row)
    return grouped


def _position_key(row: Mapping[str, object], table: str) -> PositionKey:
    """Return the fund, LP, and share-class identity carried by a fund-model row."""
    return (
        _required_text(row, "fund_id", table),
        _text(row.get("lp_id")),
        _text(row.get("lp_name")),
        _text(row.get("share_class_name")),
    )


def _entity_id(row: Mapping[str, object]) -> str:
    fund_id, lp_id, lp_name, share_class_name = _position_key(row, "fund_periods")
    if not any((lp_id, lp_name, share_class_name)):
        return fund_id
    return _stable_id(
        "POSITION",
        fund_id,
        lp_id or "UNSPECIFIED_LP",
        lp_name or "UNNAMED_LP",
        share_class_name or "ALL_CLASSES",
    )


def _dated_cashflows(
    rows: Sequence[Mapping[str, str]], terminal_date: date, period_currency: object
) -> tuple[list[tuple[date, float]], list[str]]:
    selected: list[tuple[date, str, float]] = []
    expected_currency = _text(period_currency)
    for row in rows:
        cashflow_date = _date(row.get("cashflow_date"), "fund_cashflows.cashflow_date")
        if cashflow_date > terminal_date:
            continue
        amount_base = _text(row.get("amount_base_currency"))
        if amount_base:
            base_currency = _text(row.get("base_currency"))
            if expected_currency and base_currency and base_currency != expected_currency:
                raise AnalyticsError(
                    f"cash flow base currency {base_currency} differs from period currency {expected_currency}"
                )
            amount = _number(amount_base, "amount_base_currency")
        else:
            currency = _text(row.get("currency"))
            if expected_currency and currency and currency != expected_currency:
                raise AnalyticsError(
                    f"cash flow currency {currency} differs from period currency {expected_currency}"
                )
            amount = _number(row.get("amount"), "amount")
        selected.append(
            (
                cashflow_date,
                _required_text(row, "cashflow_id", "fund_cashflows"),
                amount,
            )
        )
    selected.sort(key=lambda item: (item[0], item[1]))
    return (
        [(cashflow_date, amount) for cashflow_date, _, amount in selected],
        [cashflow_id for _, cashflow_id, _ in selected],
    )


def _build_benchmark_series(
    rows: Sequence[Mapping[str, str]], benchmark_id: str, periodicity: str | None
) -> _BenchmarkSeries:
    selected = [
        row
        for row in rows
        if _active(row) and _text(row.get("benchmark_id")) == benchmark_id
    ]
    if not selected:
        raise AnalyticsError(f"benchmark {benchmark_id} has no active return rows")
    periodicities = {_text(row.get("periodicity")).upper() for row in selected}
    if periodicity is None:
        if len(periodicities) != 1:
            raise AnalyticsError(
                f"benchmark {benchmark_id} has multiple periodicities; select one"
            )
        periodicity = next(iter(periodicities))
    periodicity = periodicity.upper()
    selected = [
        row for row in selected if _text(row.get("periodicity")).upper() == periodicity
    ]
    if not selected:
        raise AnalyticsError(
            f"benchmark {benchmark_id} has no active {periodicity} return rows"
        )
    selected.sort(
        key=lambda row: (
            _date(row.get("return_date"), "benchmark_returns.return_date"),
            _text(row.get("benchmark_return_id")),
        )
    )
    seen_dates: set[date] = set()
    points: list[_BenchmarkPoint] = []
    level = 1.0
    for row in selected:
        return_date = _date(row.get("return_date"), "benchmark_returns.return_date")
        if return_date in seen_dates:
            raise AnalyticsError(
                f"benchmark {benchmark_id} has multiple {periodicity} returns on {return_date}"
            )
        seen_dates.add(return_date)
        return_value = _number(row.get("return_value"), "return_value")
        if return_value <= -1.0:
            raise AnalyticsError(
                f"benchmark return must be greater than -1 on {return_date.isoformat()}"
            )
        level *= 1.0 + return_value
        points.append(
            _BenchmarkPoint(
                return_date,
                level,
                _required_text(row, "benchmark_return_id", "benchmark_returns"),
            )
        )
    return _BenchmarkSeries(points)


def _analysis_row(
    entity_id: str,
    as_of_date: date,
    metric_id: str,
    value: float,
    unit: str,
    formula_id: str,
    input_record_ids: str,
    benchmark_id: str,
    provenance_type: str,
    notes: str,
) -> dict[str, str]:
    return {
        "analysis_result_id": _stable_id(
            "ANL", entity_id, as_of_date.strftime("%Y%m%d"), metric_id
        ),
        "entity_id": entity_id,
        "as_of_date": as_of_date.isoformat(),
        "metric_id": metric_id,
        "value_numeric": _format_float(value),
        "unit": unit,
        "formula_id": formula_id,
        "input_record_ids": input_record_ids,
        "benchmark_id": benchmark_id,
        "provenance_type": provenance_type,
        "quality_population": QUALITY_POPULATION,
        "notes": notes,
    }


def _analysis_provenance(row: Mapping[str, str]) -> str:
    value = _required_text(row, "provenance_type", "fund_periods").upper()
    if value not in {"EXTRACTED", "DERIVED", "SYNTHETIC", "IMPUTED"}:
        raise AnalyticsError(f"fund_periods.provenance_type is invalid: {value!r}")
    return value


def _period_sort_key(row: Mapping[str, str]) -> tuple[str, str, str]:
    return (
        _text(row.get("fund_id")),
        _text(row.get("as_of_date")),
        _text(row.get("fund_period_id")),
    )


def _active(row: Mapping[str, str]) -> bool:
    status = _text(row.get("record_status")).upper()
    return status in {"", "ACTIVE"}


def _date(value: object, label: str) -> date:
    text = _text(value)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise AnalyticsError(f"{label} must be an ISO date, got {text!r}") from exc


def _timestamp(value: object, label: str) -> datetime:
    text = _text(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AnalyticsError(f"{label} must be an ISO-8601 timestamp, got {text!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AnalyticsError(f"{label} requires a timezone offset")
    return parsed


def _number(value: object, label: str) -> float:
    text = _text(value)
    try:
        number = float(text)
    except ValueError as exc:
        raise AnalyticsError(f"{label} must be numeric, got {text!r}") from exc
    if number != number or number in {float("inf"), float("-inf")}:
        raise AnalyticsError(f"{label} must be finite")
    return number


def _positive_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number <= 0:
        raise AnalyticsError(f"{label} must be positive")
    return number


def _nonnegative_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number < 0:
        raise AnalyticsError(f"{label} must be nonnegative")
    return number


def _decimal(value: object, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise AnalyticsError(f"{label} must be numeric") from exc
    if not number.is_finite():
        raise AnalyticsError(f"{label} must be finite")
    return number


def _required_text(row: Mapping[str, object], key: str, table: str) -> str:
    value = _text(row.get(key))
    if not value:
        raise AnalyticsError(f"{table}.{key} is required")
    return value


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _first_text(*values: object) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _format_float(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".") or "0"


def _format_decimal(value: Decimal) -> str:
    return format(value.quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def _stable_id(*parts: str) -> str:
    return "_".join(re.sub(r"[^A-Za-z0-9]+", "_", part).strip("_").upper() for part in parts)


def _join_ids(ids: Iterable[str]) -> str:
    return ";".join(dict.fromkeys(item for item in ids if item))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-directory", type=Path, default=Path("data/csv"))
    parser.add_argument("--output-directory", type=Path, default=Path("data/csv"))
    parser.add_argument("--benchmark-id", required=True)
    parser.add_argument("--portfolio-id", default="PORTFOLIO_RECRUITMENT_BASELINE")
    parser.add_argument("--as-of-date", type=date.fromisoformat)
    parser.add_argument("--periodicity")
    parser.add_argument("--minimum-weight", type=float, default=0.0)
    parser.add_argument("--maximum-weight", type=float, default=1.0)
    parser.add_argument(
        "--portfolio-perspective",
        help=(
            "Restrict portfolio construction to one reported perspective, for "
            "example fund_total, when a fund also reports LP or share-class "
            "positions."
        ),
    )
    parser.add_argument("--quality-config", type=Path)
    parser.add_argument(
        "--fund-period-parameter-set-id",
        help="Restrict analytics to one completed analytical-period population.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    counts = run_round04(
        args.data_directory,
        args.output_directory,
        benchmark_id=args.benchmark_id,
        portfolio_id=args.portfolio_id,
        as_of_date=args.as_of_date,
        periodicity=args.periodicity,
        minimum_weight=args.minimum_weight,
        maximum_weight=args.maximum_weight,
        portfolio_perspective=args.portfolio_perspective,
        fund_period_parameter_set_id=args.fund_period_parameter_set_id,
        quality_config=args.quality_config,
    )
    for filename, count in counts.items():
        print(f"{filename}: {count} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
