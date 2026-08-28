"""Apply deterministic fund-period quality rules and write reviewable CSV results."""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.common.finance import xirr

RESULT_COLUMNS = [
    "quality_result_id",
    "run_id",
    "record_table",
    "record_id",
    "fund_id",
    "rule_id",
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
]

RULES: tuple[tuple[str, str], ...] = (
    ("R01_NONNEGATIVE_BALANCES", "error"),
    ("R02_TVPI_COMPONENTS", "error"),
    ("R03_DPI_RECOMPUTE", "error"),
    ("R04_RVPI_RECOMPUTE", "error"),
    ("R05_TVPI_RECOMPUTE", "error"),
    ("R06_COMMITMENT_RECONCILIATION", "warning"),
    ("R07_NAV_ROLLFORWARD", "error"),
    ("R08_XIRR_RECOMPUTE", "error"),
    ("R09_VINTAGE_DATE", "error"),
    ("R10_FUND_SIZE_BOUND", "warning"),
    ("R11_PROVENANCE_REQUIREMENTS", "error"),
    ("R12_SYNTHETIC_IDENTITY_SEPARATION", "error"),
    ("R13_DUPLICATE_CASHFLOW", "warning"),
    ("R14_CURRENCY_CONSISTENCY", "error"),
    ("R15_CASHFLOW_SIGN_CONVENTION", "error"),
)

EXTENDED_RULES: tuple[tuple[str, str], ...] = (
    ("R16_MANAGER_IDENTITY", "error"),
    ("R17_MANAGER_AUM_NONNEGATIVE", "error"),
    ("R18_TERM_SCOPE_IDENTITY", "error"),
    ("R19_TERM_RATE_BOUNDS", "error"),
    ("R20_TERM_EFFECTIVE_RANGE", "error"),
    ("R21_CASHFLOW_DATE_LINEAGE", "error"),
    ("R22_HOLDING_INSTRUMENT_GRAIN", "error"),
    ("R23_PERIOD_SOURCE_GRAIN", "error"),
)

DEFAULT_TOLERANCES = {
    "money_absolute": 1.0,
    "multiple_absolute": 0.005,
    "rate_absolute": 0.0005,
    "xirr_absolute": 0.005,
}

# The vocabulary name a printed cell carries in fact_observation, mapped to
# the fund_periods column the promotion wrote it into. The precision of the
# printed cell is what bounds how far a recomputation can drift from the
# printed ratio.
PRECISION_FIELDS = {
    "paid_in_capital": "paid_in_capital_itd",
    "distribution": "distributions_itd",
    "nav": "nav",
    "dpi": "dpi",
    "rvpi": "rvpi",
    "tvpi": "tvpi",
    "commitment": "commitment",
    "unfunded_commitment": "unfunded_commitment",
}

PrintedPrecision = Mapping[str, Mapping[str, float]]

_NUMBER_IN_TEXT = re.compile(r"-?\d[\d,]*(?:\.(\d+))?")


def printed_half_unit(value_raw: str, multiplier: float = 1.0) -> float | None:
    """Half of the last printed digit's place, in the units the table stores.

    A page that prints $90.5 in millions has told the reader the value to the
    nearest hundred thousand, so any recomputation from it can be off by up to
    fifty thousand before the page itself is contradicted. `$90.5` with a
    multiplier of 1,000,000 gives 50,000; `1.05x` gives 0.005; `22,909,961`
    gives 0.5."""

    match = _NUMBER_IN_TEXT.search(_text(value_raw))
    if not match:
        return None
    decimals = len(match.group(1) or "")
    return 0.5 * (10.0 ** -decimals) * float(multiplier or 1.0)


def printed_precision_from_observations(
    fund_periods: Sequence[Mapping[str, str]],
    observations: Sequence[Mapping[str, str]],
) -> dict[str, dict[str, float]]:
    """Map each period to the half-unit of every printed input it was built from.

    Only a period that names its input observations gets an entry, so a
    generated period, which names none, keeps the configured tolerance
    alone."""

    by_id = {
        _text(row.get("observation_id")): row
        for row in observations
        if _text(row.get("observation_id"))
    }
    precision: dict[str, dict[str, float]] = {}
    for period in fund_periods:
        period_id = _text(period.get("fund_period_id"))
        ids = re.split(r"[;|]", _text(period.get("input_observation_ids")))
        fields: dict[str, float] = {}
        for observation_id in (item.strip() for item in ids):
            row = by_id.get(observation_id)
            if row is None:
                continue
            field = PRECISION_FIELDS.get(_text(row.get("metric_category")))
            if field is None:
                continue
            half = printed_half_unit(
                _text(row.get("value_raw")),
                _number(row.get("unit_scale_multiplier")) or 1.0,
            )
            if half is not None:
                fields[field] = max(fields.get(field, 0.0), half)
        if fields:
            precision[period_id] = fields
    return precision


def read_csv(path: str | Path) -> list[dict[str, str]]:
    """Read a CSV as strings; a header-only file yields an empty list."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_tolerances(path: str | Path | None) -> dict[str, float]:
    """Read the numeric tolerance block using the standard library alone."""
    tolerances = dict(DEFAULT_TOLERANCES)
    if path is None:
        return tolerances
    in_tolerances = False
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        if raw_line.strip() == "tolerances:":
            in_tolerances = True
            continue
        if in_tolerances and raw_line and not raw_line.startswith((" ", "\t")):
            break
        if in_tolerances:
            match = re.match(r"\s+([a-z_]+):\s*([-+0-9.eE]+)\s*$", raw_line)
            if match and match.group(1) in tolerances:
                tolerances[match.group(1)] = float(match.group(2))
    return tolerances


def run_quality_checks(
    fund_periods: Sequence[Mapping[str, str]],
    fund_cashflows: Sequence[Mapping[str, str]],
    fund_master: Sequence[Mapping[str, str]] | None = None,
    *,
    manager_observations: Sequence[Mapping[str, str]] | None = None,
    manager_master: Sequence[Mapping[str, str]] | None = None,
    fund_terms: Sequence[Mapping[str, str]] | None = None,
    fund_term_clauses: Sequence[Mapping[str, str]] | None = None,
    fund_holdings: Sequence[Mapping[str, str]] | None = None,
    run_id: str = "FUND_QC_V1",
    checked_at: str = "1970-01-01T00:00:00Z",
    tolerances: Mapping[str, float] | None = None,
    printed_precision: PrintedPrecision | None = None,
) -> list[dict[str, str]]:
    """Evaluate period rules and the optional cross-entity integrity rules.

    `printed_precision` maps a period to the half-unit of each printed input,
    built by `printed_precision_from_observations`. With it, the multiple
    rules widen their tolerance to what the page's own rounding allows, so a
    ratio the page printed to two decimals is held to two decimals and no
    tighter. Without it every period keeps the configured tolerance."""
    effective_tolerances = dict(DEFAULT_TOLERANCES)
    if tolerances:
        effective_tolerances.update(tolerances)
    precision = printed_precision or {}

    cashflows_by_position: dict[
        tuple[str, str, str, str], list[Mapping[str, str]]
    ] = defaultdict(list)
    for row in fund_cashflows:
        cashflows_by_position[_position_key(row)].append(row)
    masters_by_fund = {
        _text(row.get("fund_id")): row for row in (fund_master or []) if _text(row.get("fund_id"))
    }

    output: list[dict[str, str]] = []
    for row_number, period in enumerate(fund_periods, start=1):
        record_id = _text(period.get("fund_period_id")) or f"ROW{row_number:06d}"
        fund_id = _text(period.get("fund_id"))
        evaluations = _evaluate_period(
            period,
            cashflows_by_position.get(_position_key(period), []),
            masters_by_fund.get(fund_id),
            effective_tolerances,
            precision.get(record_id, {}),
        )
        for rule_id, severity in RULES:
            evaluation = evaluations[rule_id]
            output.append(
                {
                    "quality_result_id": _quality_result_id(run_id, record_id, rule_id),
                    "run_id": run_id,
                    "record_table": "fund_periods",
                    "record_id": record_id,
                    "fund_id": fund_id,
                    "rule_id": rule_id,
                    "severity": severity,
                    "status": evaluation["status"],
                    "actual_value": evaluation["actual_value"],
                    "expected_value": evaluation["expected_value"],
                    "difference": evaluation["difference"],
                    "tolerance": evaluation["tolerance"],
                    "source_document_id": _text(period.get("source_document_id")),
                    "synthetic_parameter_set_id": _text(period.get("synthetic_parameter_set_id")),
                    "checked_at": checked_at,
                    "notes": evaluation["notes"],
                }
            )
    extended_checks = any(
        value is not None
        for value in (
            manager_observations,
            manager_master,
            fund_terms,
            fund_term_clauses,
            fund_holdings,
        )
    )
    if extended_checks:
        output.extend(
            _evaluate_entity_quality(
            fund_periods=fund_periods,
            fund_cashflows=fund_cashflows,
            manager_observations=manager_observations or [],
            manager_master=manager_master or [],
            fund_terms=fund_terms or [],
            fund_term_clauses=fund_term_clauses or [],
            fund_holdings=fund_holdings or [],
            run_id=run_id,
            checked_at=checked_at,
            )
        )
    return output


def _evaluate_entity_quality(
    *,
    fund_periods: Sequence[Mapping[str, str]],
    fund_cashflows: Sequence[Mapping[str, str]],
    manager_observations: Sequence[Mapping[str, str]],
    manager_master: Sequence[Mapping[str, str]],
    fund_terms: Sequence[Mapping[str, str]],
    fund_term_clauses: Sequence[Mapping[str, str]],
    fund_holdings: Sequence[Mapping[str, str]],
    run_id: str,
    checked_at: str,
) -> list[dict[str, str]]:
    """Return row-level results for manager, date, term, and grain controls."""

    output: list[dict[str, str]] = []
    manager_ids = {_text(row.get("manager_id")) for row in manager_master}
    for row_number, row in enumerate(manager_observations, start=1):
        record_id = _text(row.get("manager_observation_id")) or f"MANAGER_ROW{row_number:06d}"
        manager_id = _text(row.get("manager_id"))
        identity_ok = bool(manager_id) and manager_id in manager_ids and _text(
            row.get("perspective")
        ) == "manager_total"
        output.append(
            _entity_result(
                run_id, "manager_observations", record_id, "", "R16_MANAGER_IDENTITY",
                "error", _categorical_result(
                    identity_ok,
                    "resolved" if identity_ok else "unresolved",
                    "resolved manager_total",
                    "manager observation identity and perspective",
                ),
                row, checked_at,
            )
        )
        if _text(row.get("metric_id")) == "mgr.aum":
            aum = _number(row.get("value_numeric"))
            evaluation = (
                _skip("manager AUM numeric value is missing")
                if aum is None
                else _threshold_result(aum >= 0, aum, 0, aum, 0.0, "manager AUM must be nonnegative")
            )
        else:
            evaluation = _skip("manager observation is not an AUM metric")
        output.append(
            _entity_result(
                run_id, "manager_observations", record_id, "", "R17_MANAGER_AUM_NONNEGATIVE",
                "error", evaluation, row, checked_at,
            )
        )

    for table, rows, id_field in (
        ("fund_terms", fund_terms, "fund_term_id"),
        ("fund_term_clauses", fund_term_clauses, "fund_term_clause_id"),
    ):
        for row_number, row in enumerate(rows, start=1):
            record_id = _text(row.get(id_field)) or f"TERM_ROW{row_number:06d}"
            scope_ok = _term_scope_ok(row)
            output.append(
                _entity_result(
                    run_id, table, record_id, _text(row.get("fund_id")), "R18_TERM_SCOPE_IDENTITY",
                    "error", _categorical_result(
                        scope_ok,
                        "valid" if scope_ok else "invalid",
                        "valid scope identity",
                        "term scope, perspective, and scoped identity",
                    ), row, checked_at,
                )
            )
            start = _date(row.get("effective_date"))
            end = _date(row.get("effective_end_date"))
            range_evaluation = (
                _skip("one or both effective dates are missing")
                if start is None or end is None
                else _threshold_result(end >= start, end.toordinal(), start.toordinal(), (end - start).days, 0.0, "effective end date must follow the start date")
            )
            output.append(
                _entity_result(
                    run_id, table, record_id, _text(row.get("fund_id")), "R20_TERM_EFFECTIVE_RANGE",
                    "error", range_evaluation, row, checked_at,
                )
            )
            if table == "fund_terms":
                rate_fields = (
                    "management_fee_rate", "carry_rate", "hurdle_rate",
                    "catch_up_rate", "expense_cap_rate",
                )
                rates = [_number(row.get(field)) for field in rate_fields if _text(row.get(field))]
                if not rates:
                    rate_evaluation = _skip("the term row carries zero contractual rates")
                else:
                    invalid_count = sum(value is None or value < 0 or value > 1 for value in rates)
                    rate_evaluation = _threshold_result(
                        invalid_count == 0, invalid_count, 0, invalid_count, 0.0,
                        "contractual rates must fall between zero and one",
                    )
                output.append(
                    _entity_result(
                        run_id, table, record_id, _text(row.get("fund_id")), "R19_TERM_RATE_BOUNDS",
                        "error", rate_evaluation, row, checked_at,
                    )
                )

    for row_number, row in enumerate(fund_cashflows, start=1):
        record_id = _text(row.get("cashflow_id")) or f"CASHFLOW_ROW{row_number:06d}"
        role = _text(row.get("date_role"))
        precision = _text(row.get("date_precision"))
        valid = role in {"cashflow", "due", "report"} and bool(
            _text(row.get("date_raw"))
        ) and precision in {"day", "month", "quarter", "year", "unknown"}
        report_date = _date(row.get("report_date"))
        due_date = _date(row.get("due_date"))
        if report_date is not None and due_date is not None:
            valid = valid and due_date >= report_date
        output.append(
            _entity_result(
                run_id, "fund_cashflows", record_id, _text(row.get("fund_id")),
                "R21_CASHFLOW_DATE_LINEAGE", "error",
                _categorical_result(
                    valid, "complete" if valid else "incomplete", "complete",
                    "cash-flow date role, raw date, precision, and due-date order",
                ), row, checked_at,
            )
        )

    holding_signatures: defaultdict[tuple[str, ...], list[str]] = defaultdict(list)
    for row_number, row in enumerate(fund_holdings, start=1):
        record_id = _text(row.get("holding_id")) or f"HOLDING_ROW{row_number:06d}"
        signature = (
            _text(row.get("fund_id")), _text(row.get("source_document_id")),
            _text(row.get("portfolio_company_id")) or _text(row.get("portfolio_company_name")),
            _text(row.get("instrument_id")) or _text(row.get("instrument_name")),
            _text(row.get("as_of_date")),
        )
        holding_signatures[signature].append(record_id)
    duplicated_holdings = {
        record_id for ids in holding_signatures.values() if len(ids) > 1 for record_id in ids
    }
    for row_number, row in enumerate(fund_holdings, start=1):
        record_id = _text(row.get("holding_id")) or f"HOLDING_ROW{row_number:06d}"
        valid = record_id not in duplicated_holdings
        output.append(
            _entity_result(
                run_id, "fund_holdings", record_id, _text(row.get("fund_id")),
                "R22_HOLDING_INSTRUMENT_GRAIN", "error",
                _categorical_result(valid, "unique" if valid else "duplicate", "unique", "holding source and instrument grain"),
                row, checked_at,
            )
        )

    period_signatures: defaultdict[tuple[str, ...], list[str]] = defaultdict(list)
    for row_number, row in enumerate(fund_periods, start=1):
        record_id = _text(row.get("fund_period_id")) or f"ROW{row_number:06d}"
        source_key = _text(row.get("source_document_id"))
        if not source_key and _text(row.get("provenance_type")) == "SYNTHETIC":
            source_key = f"SYNTHETIC:{_text(row.get('synthetic_parameter_set_id'))}"
        signature = (*_position_key(row), _text(row.get("as_of_date")), _text(row.get("perspective")), source_key)
        period_signatures[signature].append(record_id)
    duplicated_periods = {
        record_id for ids in period_signatures.values() if len(ids) > 1 for record_id in ids
    }
    for row_number, row in enumerate(fund_periods, start=1):
        record_id = _text(row.get("fund_period_id")) or f"ROW{row_number:06d}"
        source_key = _text(row.get("source_document_id"))
        if not source_key and _text(row.get("provenance_type")) == "SYNTHETIC":
            source_key = f"SYNTHETIC:{_text(row.get('synthetic_parameter_set_id'))}"
        valid = record_id not in duplicated_periods and bool(source_key)
        output.append(
            _entity_result(
                run_id, "fund_periods", record_id, _text(row.get("fund_id")),
                "R23_PERIOD_SOURCE_GRAIN", "error",
                _categorical_result(valid, "unique" if valid else "duplicate_or_missing_source", "unique", "fund-period source grain"),
                row, checked_at,
            )
        )
    return output


def _term_scope_ok(row: Mapping[str, str]) -> bool:
    scope = _text(row.get("term_scope"))
    perspective = _text(row.get("perspective"))
    if scope == "base_fund":
        return perspective == "fund_total"
    if scope == "lp_override":
        return perspective == "lp_position" and bool(
            _text(row.get("lp_id")) or _text(row.get("lp_name"))
        )
    if scope == "share_class_override":
        return perspective == "share_class" and bool(_text(row.get("share_class_name")))
    return False


def _entity_result(
    run_id: str,
    record_table: str,
    record_id: str,
    fund_id: str,
    rule_id: str,
    severity: str,
    evaluation: Mapping[str, str],
    source: Mapping[str, str],
    checked_at: str,
) -> dict[str, str]:
    return {
        "quality_result_id": _quality_result_id(run_id, record_id, rule_id),
        "run_id": run_id,
        "record_table": record_table,
        "record_id": record_id,
        "fund_id": fund_id,
        "rule_id": rule_id,
        "severity": severity,
        "status": evaluation["status"],
        "actual_value": evaluation["actual_value"],
        "expected_value": evaluation["expected_value"],
        "difference": evaluation["difference"],
        "tolerance": evaluation["tolerance"],
        "source_document_id": _text(source.get("source_document_id")) or _text(source.get("file_id")),
        "synthetic_parameter_set_id": _text(source.get("synthetic_parameter_set_id")),
        "checked_at": checked_at,
        "notes": evaluation["notes"],
    }


def _position_key(row: Mapping[str, str]) -> tuple[str, str, str, str]:
    """Return the stable fund and position key used for period cash-flow checks."""
    lp_id = _text(row.get("lp_id"))
    return (
        _text(row.get("fund_id")),
        lp_id,
        "" if lp_id else _text(row.get("lp_name")),
        _text(row.get("share_class_name")),
    )


def write_results(path: str | Path, rows: Iterable[Mapping[str, str]]) -> None:
    """Write quality rows with the fund-model database column order."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in RESULT_COLUMNS})


def _rounding_slack(
    half: Mapping[str, float],
    *,
    ratio: str,
    numerators: Sequence[str] = (),
    denominator: str | None = None,
    quotient: float | None = None,
    components: Sequence[str] = (),
) -> float:
    """How far a recomputed ratio can sit from the printed one before the
    page is contradicted.

    For a sum of printed components the slack is the sum of their half-units.
    For a quotient the numerator half-units divide by the denominator and the
    denominator's half-unit scales by the quotient itself, which is the
    first-order error of a division. The printed ratio's own half-unit is
    added in both cases."""

    slack = half.get(ratio, 0.0)
    slack += sum(half.get(name, 0.0) for name in components)
    if denominator is not None:
        base = half.get("_denominator_value", 0.0)
        if base > 0:
            slack += sum(half.get(name, 0.0) for name in numerators) / base
            slack += abs(quotient or 0.0) * half.get(denominator, 0.0) / base
    return slack


def _multiple_check(
    actual: float | None,
    expected: float | None,
    base_tolerance: float,
    slack: float,
    note: str,
) -> dict[str, str]:
    """Compare a printed multiple with its recomputation.

    The tolerance the row records is the one applied, so a widened tolerance
    is visible in the result and never silent."""

    if slack <= 0:
        return _comparison_or_skip(actual, expected, base_tolerance, note)
    return _comparison_or_skip(
        actual,
        expected,
        base_tolerance + slack,
        f"{note}; tolerance widened by {_format_number(slack)} for the printed precision of the inputs",
    )


def _evaluate_period(
    row: Mapping[str, str],
    cashflow_rows: Sequence[Mapping[str, str]],
    master: Mapping[str, str] | None,
    tolerances: Mapping[str, float],
    printed: Mapping[str, float] | None = None,
) -> dict[str, dict[str, str]]:
    money_tolerance = tolerances["money_absolute"]
    multiple_tolerance = tolerances["multiple_absolute"]
    xirr_tolerance = tolerances["xirr_absolute"]
    results: dict[str, dict[str, str]] = {}

    paid_in = _number(row.get("paid_in_capital_itd"))
    distributions = _number(row.get("distributions_itd"))
    nav = _number(row.get("nav"))
    dpi = _number(row.get("dpi"))
    rvpi = _number(row.get("rvpi"))
    tvpi = _number(row.get("tvpi"))
    half = dict(printed or {})
    if paid_in is not None and paid_in > 0:
        half["_denominator_value"] = paid_in

    if _all_present(paid_in, distributions, nav):
        actual = min(paid_in, distributions, nav)
        results["R01_NONNEGATIVE_BALANCES"] = _threshold_result(
            actual >= 0, actual, 0.0, actual, 0.0, "minimum of paid-in capital, distributions, and NAV"
        )
    else:
        results["R01_NONNEGATIVE_BALANCES"] = _skip("paid-in capital, distributions, or NAV is missing")

    expected_dpi = None if paid_in is None or paid_in <= 0 or distributions is None else distributions / paid_in
    expected_rvpi = None if paid_in is None or paid_in <= 0 or nav is None else nav / paid_in
    expected_tvpi = (
        None
        if paid_in is None or paid_in <= 0 or distributions is None or nav is None
        else (distributions + nav) / paid_in
    )
    results["R02_TVPI_COMPONENTS"] = _multiple_check(
        tvpi,
        None if dpi is None or rvpi is None else dpi + rvpi,
        multiple_tolerance,
        _rounding_slack(half, ratio="tvpi", components=("dpi", "rvpi")),
        "tvpi compared with dpi plus rvpi",
    )
    results["R03_DPI_RECOMPUTE"] = _multiple_check(
        dpi,
        expected_dpi,
        multiple_tolerance,
        _rounding_slack(
            half, ratio="dpi", numerators=("distributions_itd",),
            denominator="paid_in_capital_itd", quotient=expected_dpi,
        ),
        "dpi compared with distributions divided by paid-in capital",
    )
    results["R04_RVPI_RECOMPUTE"] = _multiple_check(
        rvpi,
        expected_rvpi,
        multiple_tolerance,
        _rounding_slack(
            half, ratio="rvpi", numerators=("nav",),
            denominator="paid_in_capital_itd", quotient=expected_rvpi,
        ),
        "rvpi compared with nav divided by paid-in capital",
    )
    results["R05_TVPI_RECOMPUTE"] = _multiple_check(
        tvpi,
        expected_tvpi,
        multiple_tolerance,
        _rounding_slack(
            half, ratio="tvpi", numerators=("distributions_itd", "nav"),
            denominator="paid_in_capital_itd", quotient=expected_tvpi,
        ),
        "tvpi compared with distributions plus nav divided by paid-in capital",
    )

    commitment = _number(row.get("commitment"))
    unfunded = _number(row.get("unfunded_commitment"))
    recallable = _number(row.get("recallable_distributions_itd"))
    if _all_present(commitment, paid_in, unfunded, recallable):
        results["R06_COMMITMENT_RECONCILIATION"] = _comparison_or_skip(
            commitment,
            paid_in + unfunded - recallable,
            money_tolerance,
            "commitment compared with paid-in capital plus unfunded commitment minus recallable distributions",
        )
    else:
        results["R06_COMMITMENT_RECONCILIATION"] = _skip(
            "commitment, paid-in capital, unfunded commitment, or recallable treatment is missing"
        )

    rollforward_fields = (
        "beginning_nav",
        "contributions_period",
        "distributions_period",
        "realized_gain_period",
        "unrealized_gain_period",
        "net_income_period",
        "management_fee_period",
        "other_expenses_period",
        "ending_nav",
    )
    rollforward = {field: _number(row.get(field)) for field in rollforward_fields}
    if all(value is not None for value in rollforward.values()):
        expected_ending_nav = (
            rollforward["beginning_nav"]
            + rollforward["contributions_period"]
            - rollforward["distributions_period"]
            + rollforward["realized_gain_period"]
            + rollforward["unrealized_gain_period"]
            + rollforward["net_income_period"]
            - rollforward["management_fee_period"]
            - rollforward["other_expenses_period"]
        )
        results["R07_NAV_ROLLFORWARD"] = _comparison_or_skip(
            rollforward["ending_nav"], expected_ending_nav, money_tolerance, "ending nav roll-forward"
        )
    else:
        results["R07_NAV_ROLLFORWARD"] = _skip("one or more NAV roll-forward components are missing")

    results["R08_XIRR_RECOMPUTE"] = _evaluate_xirr(row, cashflow_rows, xirr_tolerance)

    vintage_year = _integer(row.get("vintage_year"))
    as_of_date = _date(row.get("as_of_date"))
    if vintage_year is None or as_of_date is None:
        results["R09_VINTAGE_DATE"] = _skip("vintage year or as-of date is missing or invalid")
    else:
        results["R09_VINTAGE_DATE"] = _threshold_result(
            vintage_year <= as_of_date.year,
            vintage_year,
            as_of_date.year,
            vintage_year - as_of_date.year,
            0.0,
            "vintage year must fall on or before the as-of year",
        )

    perspective = _text(row.get("perspective")).lower()
    fund_size = _number(row.get("fund_size"))
    if fund_size is None and master is not None:
        fund_size = _number(master.get("fund_size"))
    if perspective != "lp_position":
        results["R10_FUND_SIZE_BOUND"] = _skip("rule applies only to lp_position rows")
    elif fund_size is None or commitment is None:
        results["R10_FUND_SIZE_BOUND"] = _skip("fund size or LP commitment is missing")
    else:
        results["R10_FUND_SIZE_BOUND"] = _threshold_result(
            fund_size + money_tolerance >= commitment,
            fund_size,
            commitment,
            fund_size - commitment,
            money_tolerance,
            "fund size must be at least the LP commitment",
        )

    results["R11_PROVENANCE_REQUIREMENTS"] = _evaluate_provenance(row)
    results["R12_SYNTHETIC_IDENTITY_SEPARATION"] = _evaluate_synthetic_identity(row, master)
    results["R13_DUPLICATE_CASHFLOW"] = _evaluate_duplicate_cashflows(cashflow_rows)
    results["R14_CURRENCY_CONSISTENCY"] = _evaluate_currency_consistency(
        row, cashflow_rows, money_tolerance
    )
    results["R15_CASHFLOW_SIGN_CONVENTION"] = _evaluate_cashflow_signs(cashflow_rows)
    return results


def _evaluate_duplicate_cashflows(
    cashflow_rows: Sequence[Mapping[str, str]],
) -> dict[str, str]:
    if not cashflow_rows:
        return _skip("the fund has zero cash-flow rows")
    signatures: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for row in cashflow_rows:
        signature = (
            _text(row.get("lp_id")),
            _text(row.get("cashflow_date")),
            _text(row.get("cashflow_type")).lower(),
            _format_number(_number(row.get("amount")) or 0.0),
            _text(row.get("currency")).upper(),
        )
        signatures[signature].append(_text(row.get("cashflow_id")) or "<missing-id>")
    duplicates = [ids for ids in signatures.values() if len(ids) > 1]
    duplicate_rows = sum(len(ids) - 1 for ids in duplicates)
    note = "each economic cash-flow signature must be unique within a fund"
    if duplicates:
        note += "; duplicate IDs: " + "|".join(",".join(ids) for ids in duplicates)
    return _threshold_result(
        not duplicates,
        duplicate_rows,
        0,
        duplicate_rows,
        0.0,
        note,
    )


def _evaluate_currency_consistency(
    period: Mapping[str, str],
    cashflow_rows: Sequence[Mapping[str, str]],
    money_tolerance: float,
) -> dict[str, str]:
    if not cashflow_rows:
        return _skip("the fund has zero cash-flow rows")
    period_currency = _text(period.get("currency")).upper()
    if not period_currency:
        return _skip("period currency is missing")
    invalid_ids: list[str] = []
    for row in cashflow_rows:
        currency = _text(row.get("currency")).upper()
        base_currency = _text(row.get("base_currency")).upper() or period_currency
        amount = _number(row.get("amount"))
        amount_base = _number(row.get("amount_base_currency"))
        fx_rate = _number(row.get("fx_rate"))
        valid = currency == period_currency
        if not valid and currency and base_currency == period_currency:
            valid = (
                amount is not None
                and amount_base is not None
                and fx_rate is not None
                and fx_rate > 0
                and abs(fx_rate - 1.0) > 1e-12
                and abs(amount * fx_rate - amount_base) <= money_tolerance
            )
        if not valid:
            invalid_ids.append(_text(row.get("cashflow_id")) or "<missing-id>")
    note = "cash-flow currencies must match the fund period or carry a reconciling FX conversion"
    if invalid_ids:
        note += "; inconsistent IDs: " + ",".join(invalid_ids)
    return _threshold_result(
        not invalid_ids,
        len(invalid_ids),
        0,
        len(invalid_ids),
        0.0,
        note,
    )


def _evaluate_cashflow_signs(
    cashflow_rows: Sequence[Mapping[str, str]],
) -> dict[str, str]:
    negative_types = {"capital_call", "subscription", "fee"}
    positive_types = {"distribution", "recallable_distribution"}
    recognized = 0
    invalid_ids: list[str] = []
    for row in cashflow_rows:
        flow_type = _text(row.get("cashflow_type")).lower()
        if flow_type not in negative_types | positive_types:
            continue
        recognized += 1
        amount = _number(row.get("amount_base_currency"))
        if amount is None:
            amount = _number(row.get("amount"))
        valid = amount is not None and (
            (flow_type in negative_types and amount < 0)
            or (flow_type in positive_types and amount > 0)
        )
        if not valid:
            invalid_ids.append(_text(row.get("cashflow_id")) or "<missing-id>")
    if recognized == 0:
        return _skip("the cash-flow rows carry zero recognized types")
    note = "calls, subscriptions, and fees must be negative; distributions must be positive"
    if invalid_ids:
        note += "; wrong-sign IDs: " + ",".join(invalid_ids)
    return _threshold_result(
        not invalid_ids,
        len(invalid_ids),
        0,
        len(invalid_ids),
        0.0,
        note,
    )


def _evaluate_xirr(
    row: Mapping[str, str], cashflow_rows: Sequence[Mapping[str, str]], tolerance: float
) -> dict[str, str]:
    reported_irr = _number(row.get("reported_irr"))
    calculated_irr = _number(row.get("calculated_irr"))
    comparison_irr = reported_irr if reported_irr is not None else calculated_irr
    comparison_label = "reported IRR" if reported_irr is not None else "calculated IRR"
    as_of_date = _date(row.get("as_of_date"))
    ending_nav = _number(row.get("ending_nav"))
    if ending_nav is None:
        ending_nav = _number(row.get("nav"))
    if comparison_irr is None or as_of_date is None or ending_nav is None:
        return _skip("reported/calculated IRR, as-of date, or ending NAV is missing")
    # A printed IRR summarizes the fund's own cash flows. Where the flows on
    # the position were generated by the completion, the IRR and the flows
    # describe different histories, and a difference between them says nothing
    # about either. The rule declines the comparison and says why.
    period_provenance = _text(row.get("provenance_type")).upper()
    flow_provenance = {
        _text(cashflow.get("provenance_type")).upper()
        for cashflow in cashflow_rows
        if _text(cashflow.get("provenance_type"))
    }
    if period_provenance == "EXTRACTED" and flow_provenance and flow_provenance != {"EXTRACTED"}:
        return _skip(
            "printed IRR on a position whose cash flows are "
            + "/".join(sorted(flow_provenance))
            + "; a printed rate and generated flows describe different histories, so they are not compared"
        )

    dated_values: list[tuple[date, float]] = []
    invalid_rows = 0
    for cashflow in cashflow_rows:
        cashflow_date = _date(cashflow.get("cashflow_date"))
        amount = _number(cashflow.get("amount_base_currency"))
        if amount is None:
            amount = _number(cashflow.get("amount"))
        cashflow_type = _text(cashflow.get("cashflow_type")).upper()
        if cashflow_type in {"ENDING_NAV", "NAV", "TERMINAL_NAV"}:
            continue
        if cashflow_date is None or amount is None:
            invalid_rows += 1
            continue
        if cashflow_date <= as_of_date:
            dated_values.append((cashflow_date, amount))
    dated_values.append((as_of_date, ending_nav))
    if not any(value < 0 for _, value in dated_values) or not any(value > 0 for _, value in dated_values):
        return _skip("cash flows plus ending NAV omit a negative value or a positive value")
    try:
        expected_irr = xirr(dated_values)
    except ValueError as exc:
        return _skip(str(exc))
    note = f"{comparison_label} compared with XIRR of dated cash flows plus ending NAV"
    if invalid_rows:
        note += f"; ignored {invalid_rows} cash-flow row(s) with invalid date or amount"
    return _comparison_or_skip(comparison_irr, expected_irr, tolerance, note)


def _evaluate_provenance(row: Mapping[str, str]) -> dict[str, str]:
    provenance = _text(row.get("provenance_type")).upper()
    requirements = {
        "EXTRACTED": ("source_document_id",),
        "DERIVED": ("formula_id",),
        "SYNTHETIC": ("synthetic_parameter_set_id",),
        "IMPUTED": ("imputation_method",),
    }
    if provenance not in requirements:
        return _categorical_result(False, provenance or "MISSING", "EXTRACTED|DERIVED|SYNTHETIC|IMPUTED", "unrecognized provenance type")
    missing = [field for field in requirements[provenance] if not _text(row.get(field))]
    return _categorical_result(
        not missing,
        "complete" if not missing else "missing:" + ";".join(missing),
        "complete",
        f"{provenance} provenance evidence requirements",
    )


def _evaluate_synthetic_identity(
    row: Mapping[str, str], master: Mapping[str, str] | None
) -> dict[str, str]:
    if _text(row.get("provenance_type")).upper() != "SYNTHETIC":
        return _skip("rule applies only to SYNTHETIC rows")
    fund_id = _text(row.get("fund_id"))
    period_parameter_set = _text(row.get("synthetic_parameter_set_id"))
    failures: list[str] = []
    if not period_parameter_set:
        failures.append("fact parameter set")
    if master is None:
        failures.append("fund_master row")
    elif fund_id.startswith("FUND_SYNTH_"):
        if _text(master.get("provenance_type")).upper() != "SYNTHETIC":
            failures.append("fund_master provenance")
        if not _text(master.get("fund_name")):
            failures.append("synthetic fund name")
        if _text(master.get("source_document_id")):
            failures.append("real source document attached to synthetic identity")
        master_parameter_set = _text(master.get("synthetic_parameter_set_id"))
        if not master_parameter_set or master_parameter_set != period_parameter_set:
            failures.append("parameter-set alignment")
    else:
        if not fund_id.startswith("FUND_"):
            failures.append("recognized fund_id prefix")
        if _text(master.get("provenance_type")).upper() == "SYNTHETIC":
            failures.append("real identity provenance")
        if not _text(master.get("fund_name")):
            failures.append("real fund name")
    return _categorical_result(
        not failures,
        "separated" if not failures else "failed:" + ";".join(failures),
        "separated",
        "synthetic facts may complement a resolved real fund, while standalone synthetic identities remain isolated",
    )


def _comparison_or_skip(
    actual: float | None, expected: float | None, tolerance: float, note: str
) -> dict[str, str]:
    if actual is None or expected is None:
        return _skip("required reported or recomputed value is missing")
    difference = actual - expected
    return _numeric_result(abs(difference) <= tolerance, actual, expected, difference, tolerance, note)


def _numeric_result(
    passed: bool,
    actual: float,
    expected: float,
    difference: float,
    tolerance: float,
    note: str,
) -> dict[str, str]:
    return {
        "status": "PASS" if passed else "FAIL",
        "actual_value": _format_number(actual),
        "expected_value": _format_number(expected),
        "difference": _format_number(difference),
        "tolerance": _format_number(tolerance),
        "notes": note,
    }


def _threshold_result(
    passed: bool,
    actual: float | int,
    expected: float | int,
    difference: float | int,
    tolerance: float,
    note: str,
) -> dict[str, str]:
    return _numeric_result(passed, float(actual), float(expected), float(difference), tolerance, note)


def _categorical_result(passed: bool, actual: str, expected: str, note: str) -> dict[str, str]:
    return {
        "status": "PASS" if passed else "FAIL",
        "actual_value": actual,
        "expected_value": expected,
        "difference": "",
        "tolerance": "",
        "notes": note,
    }


def _skip(note: str) -> dict[str, str]:
    return {
        "status": "SKIP",
        "actual_value": "",
        "expected_value": "",
        "difference": "",
        "tolerance": "",
        "notes": note,
    }


def _number(value: object) -> float | None:
    text = _text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _integer(value: object) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _date(value: object) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _all_present(*values: float | None) -> bool:
    return all(value is not None for value in values)


def _format_number(value: float) -> str:
    if abs(value) < 5e-13:
        value = 0.0
    return format(value, ".12g")


def _quality_result_id(run_id: str, record_id: str, rule_id: str) -> str:
    raw = f"QR_{run_id}_{record_id}_{rule_id}"
    return re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fund-periods", default="data/csv/fund_periods.csv")
    parser.add_argument("--fund-cashflows", default="data/csv/fund_cashflows.csv")
    parser.add_argument("--fund-master", default="data/csv/fund_master.csv")
    parser.add_argument("--manager-observations", default="data/csv/manager_observations.csv")
    parser.add_argument("--manager-master", default="data/csv/manager_master.csv")
    parser.add_argument("--fund-terms", default="data/csv/fund_terms.csv")
    parser.add_argument("--fund-term-clauses", default="data/csv/fund_term_clauses.csv")
    parser.add_argument("--fund-holdings", default="data/csv/fund_holdings.csv")
    parser.add_argument(
        "--observations",
        default="data/extracted/tables/fact_observation.csv",
        help="printed cells behind each period, for the precision-aware tolerance; skipped where absent",
    )
    parser.add_argument("--quality-config", default="config/quality_rules.yml")
    parser.add_argument("--output", default="data/csv/quality_results.csv")
    parser.add_argument("--run-id", default="FUND_QC_V1")
    parser.add_argument("--checked-at", default="1970-01-01T00:00:00Z")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    periods = read_csv(args.fund_periods)
    observations = read_csv(args.observations) if Path(args.observations).is_file() else []
    results = run_quality_checks(
        periods,
        read_csv(args.fund_cashflows),
        read_csv(args.fund_master),
        manager_observations=read_csv(args.manager_observations),
        manager_master=read_csv(args.manager_master),
        fund_terms=read_csv(args.fund_terms),
        fund_term_clauses=read_csv(args.fund_term_clauses),
        fund_holdings=read_csv(args.fund_holdings),
        run_id=args.run_id,
        checked_at=args.checked_at,
        tolerances=load_tolerances(args.quality_config),
        printed_precision=printed_precision_from_observations(periods, observations),
    )
    write_results(args.output, results)
    print(f"Wrote {len(results)} quality results to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
