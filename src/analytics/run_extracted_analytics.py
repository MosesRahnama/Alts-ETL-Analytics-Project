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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = PROJECT_ROOT / "data" / "extracted" / "fund-level"
DEFAULT_QUALITY = DEFAULT_DIR / "quality_results.csv"


def is_measurable(period: dict[str, str]) -> bool:
    """Whether a period carries the three numbers a multiple is built from.

    A generated population always prints paid-in, distributions, and NAV
    together. A real report frequently prints a NAV and a multiple and nothing
    else, and a period like that is not a gap to be filled with a zero: it is a
    period this document does not support measuring, so it is left out."""
    try:
        paid_in = float(period.get("paid_in_capital_itd") or "")
    except ValueError:
        return False
    if paid_in <= 0:
        return False
    for column in ("distributions_itd", "nav"):
        try:
            float(period.get(column) or "")
        except ValueError:
            return False
    return True


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
    metrics = calculate_fund_metrics(
        measurable, cashflows, quality, through_date=through_date, require_xirr=False
    )
    write_csv_rows(output_path or data_root / "fund_metrics.csv", ANALYSIS_RESULT_COLUMNS, metrics)
    return len(metrics)


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
    print(f"PASS: {written:,} fund metric row(s) from the promoted extraction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
