"""Stage 115 of the rebuild: metrics the extracted periods support alone.

`run_integrated_analytics` (stage 120) covers the filled fund-date table; this module
measures what the source-backed snapshot supports before any completion, and
writes data/extracted/fund-level/fund_metrics.csv labelled EXTRACTED.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from src.analytics.run_round04_analytics import (
    ANALYSIS_RESULT_COLUMNS,
    QUALITY_RESULT_COLUMNS,
    calculate_fund_metrics,
    read_csv_rows,
    write_csv_rows,
)

from src.common import matrices

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# measurability-rule.csv names what a measurable period must carry; the
# agreement, and batch 3 deletes it.
MEASURABILITY = "measurability-rule"
DEFAULT_DIR = PROJECT_ROOT / "data" / "extracted" / "fund-level"
DEFAULT_QUALITY = DEFAULT_DIR / "quality_results.csv"


def is_measurable(period: dict[str, str]) -> bool:
    """Whether a period carries the three numbers a multiple is built from.

    A generated population always prints paid-in, distributions, and NAV
    together. A real report frequently prints a NAV and a multiple and nothing
    else, and a period like that is not a gap to be filled with a zero: it is a
    period this document does not support measuring, so it is left out."""
    for column, requirement in matrices.mapping(MEASURABILITY, context="period_inputs").items():
        try:
            value = float(period.get(column) or "")
        except ValueError:
            return False
        if requirement == "positive_number_required" and value <= 0:
            return False
    return True


# Which qualifier columns a period carries for the rates the analytics read, and
# the label a page that states none takes. Both are rows of measurability-rule.csv.
RATE_QUALIFIERS = ("reported_irr_fee_basis", "reported_irr_method")
UNSTATED = "unstated"


def stated_basis(period: dict[str, str]) -> str:
    """The fee basis a period states for its rate, or the unstated label.

    measurability-rule.csv says an unstated basis is measurable and labelled, so
    a period whose page states none is measured and carries the word rather than
    being dropped or being passed off as net."""

    if matrices.resolve(MEASURABILITY, "unstated_fee_basis", context="fee_basis") != "measurable_labelled":
        raise matrices.MatrixError(f"{MEASURABILITY}: unsupported unstated_fee_basis policy")
    return (period.get("reported_irr_fee_basis") or "").strip() or UNSTATED


def stated_method(period: dict[str, str]) -> str:
    return (period.get("reported_irr_method") or "").strip() or UNSTATED


def funds_with_one_basis(periods: list[dict[str, str]]) -> tuple[set[str], int]:
    """The funds whose periods agree on a fee basis, and how many were refused.

    A fund stating net on some periods and gross on others has two series, not
    one, and a multiple or a rate built across both compares two different
    measures. measurability-rule.csv refuses that fund and the count is
    reported, so the refusal is visible rather than silent."""

    if matrices.resolve(
        MEASURABILITY, "mixed_fee_basis_within_fund", context="fee_basis"
    ) != "refused_and_counted":
        raise matrices.MatrixError(f"{MEASURABILITY}: unsupported mixed_fee_basis_within_fund policy")
    seen: dict[str, set[str]] = {}
    for period in periods:
        basis = stated_basis(period)
        if basis == UNSTATED:
            continue
        seen.setdefault(period.get("fund_id", ""), set()).add(basis)
    kept = {fund for fund, bases in seen.items() if len(bases) <= 1}
    return kept | {p.get("fund_id", "") for p in periods if p.get("fund_id", "") not in seen}, sum(
        1 for bases in seen.values() if len(bases) > 1
    )


def run(
    data_root: Path,
    through_date: date | None = None,
    *,
    quality_path: Path = DEFAULT_QUALITY,
    output_path: Path | None = None,
) -> int:
    periods = read_csv_rows(
        data_root / "fund_periods.csv",
        required_columns=(
            "fund_period_id",
            "fund_id",
            "as_of_date",
            "provenance_type",
            "record_status",
        ),
    )
    cashflows = read_csv_rows(
        data_root / "fund_cashflows.csv",
        required_columns=(
            "cashflow_id", "fund_id", "lp_id", "lp_name", "share_class_name",
            "cashflow_date", "amount", "currency", "amount_base_currency",
            "base_currency", "record_status",
        ),
    )
    quality = read_csv_rows(
        quality_path, required_columns=QUALITY_RESULT_COLUMNS
    )
    measurable = [row for row in periods if is_measurable(row)]
    one_basis, refused_funds = funds_with_one_basis(measurable)
    measurable = [row for row in measurable if row.get("fund_id", "") in one_basis]
    metrics = calculate_fund_metrics(
        measurable, cashflows, quality, through_date=through_date, require_xirr=False
    )
    # Every result names the fee basis and method of the rate behind it, so a
    # reader never meets a measured number whose meaning is unrecoverable.
    basis_by_period = {row["fund_period_id"]: stated_basis(row) for row in measurable}
    method_by_period = {row["fund_period_id"]: stated_method(row) for row in measurable}
    for metric in metrics:
        inputs = [part for part in (metric.get("input_record_ids") or "").split(";") if part]
        bases = {basis_by_period[part] for part in inputs if part in basis_by_period}
        methods = {method_by_period[part] for part in inputs if part in method_by_period}
        metric["input_fee_basis"] = bases.pop() if len(bases) == 1 else UNSTATED
        metric["input_method"] = methods.pop() if len(methods) == 1 else UNSTATED
    write_csv_rows(
        output_path or data_root / "fund_metrics.csv",
        ANALYSIS_RESULT_COLUMNS + ("input_fee_basis", "input_method"),
        metrics,
    )
    _LAST_REFUSED_FUNDS.append(refused_funds)
    return len(metrics)


# How many funds the last run refused for mixing a net and a gross basis inside
# one series, reported by main() so the refusal is counted where it is seen.
_LAST_REFUSED_FUNDS: list[int] = []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-directory", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--quality-results", type=Path, default=DEFAULT_QUALITY)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    written = run(
        args.data_directory,
        args.as_of_date,
        quality_path=args.quality_results,
        output_path=args.output,
    )
    refused = _LAST_REFUSED_FUNDS[-1] if _LAST_REFUSED_FUNDS else 0
    print(
        f"PASS: {written:,} fund metric row(s) from the promoted extraction; "
        f"{refused:,} fund(s) refused for mixing a fee basis inside one series"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
