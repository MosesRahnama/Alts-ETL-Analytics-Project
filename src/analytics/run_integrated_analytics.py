"""Run metrics, PME, and allocation on the filled fund-date table."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Sequence

import yaml

from src.analytics.run_round04_analytics import run_round04


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "csv"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "integrated_completion.yml"


def run(data_directory: Path = DEFAULT_DATA_DIR, config_path: Path = DEFAULT_CONFIG) -> dict[str, int]:
    settings = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return run_round04(
        data_directory,
        data_directory,
        benchmark_id=str(settings["benchmark_id"]),
        portfolio_id=str(settings["portfolio_id"]),
        as_of_date=date.fromisoformat(str(settings["as_of_date"])),
        periodicity=str(settings["benchmark_periodicity"]),
        minimum_weight=float(settings["minimum_weight"]),
        maximum_weight=float(settings["maximum_weight"]),
        portfolio_perspective="fund_total",
        fund_period_parameter_set_id=str(settings["parameter_set_id"]),
        quality_config=PROJECT_ROOT / "config" / "quality_rules.yml",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-directory", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    counts = run(args.data_directory, args.config)
    print(
        "PASS: integrated analytics; "
        + ", ".join(f"{name}={count:,}" for name, count in counts.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
