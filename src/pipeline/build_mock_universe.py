"""Build the standalone regression universe one checkable stage at a time.

This fixture stress-tests generation, checks, and analytics without touching or
completing the fund-model data.

Every stage writes to a fixed folder, prints its own row counts, and refuses to
continue when its gate fails, so a failure names the stage that caused it.

    clean      seeded generation with no deliberate defect
    clean-qc   quality rules over the clean population; zero failures required
    analytics  fund metrics, PME, and portfolio weights over the clean population
    defects    a second population carrying one deliberate defect per selected fund
    defects-qc quality rules over the defect population
    score      detection scorecard for the deliberate defects
    warehouse  the clean population plus its analytics loaded into DuckDB
    manifest   row counts for every published file
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.analytics.run_round04_analytics import run_round04
from src.generate import generate_synthetic_funds as generator
from src.load.load_csv_to_duckdb import load as load_duckdb
from src.quality.run_fund_checks import (
    load_tolerances,
    read_csv,
    run_quality_checks,
    write_results,
)

STAGES = (
    "clean",
    "clean-qc",
    "analytics",
    "defects",
    "defects-qc",
    "score",
    "warehouse",
    "manifest",
)

QUALITY_INPUTS = (
    "fund_periods",
    "fund_cashflows",
    "fund_master",
    "manager_master",
    "manager_observations",
    "fund_terms",
    "fund_term_clauses",
    "fund_holdings",
)

MANIFEST_COLUMNS = ("stage", "directory", "file", "rows")

SCORECARD_COLUMNS = (
    "defect_type",
    "expected_rule_id",
    "injected",
    "detected",
    "missed",
    "detection_rate",
)


class PipelineError(RuntimeError):
    """Raised when a stage gate refuses to publish its output."""


def _generate(
    output_dir: Path,
    *,
    fund_count: int,
    seed: int | None,
    inject_defects: bool,
    defect_rate: float | None,
    fund_model_dir: Path,
    config: Path,
    parameters: Path,
    source_ledger: Path,
) -> dict[str, int]:
    argv = [
        "--allow-assumed-only",
        "--allow-small-demo",
        "--count",
        str(fund_count),
        "--output-dir",
        str(output_dir),
        "--fund-model-dir",
        str(fund_model_dir),
        "--config",
        str(config),
        "--parameters",
        str(parameters),
        "--source-ledger",
        str(source_ledger),
        "--inject-defects" if inject_defects else "--no-inject-defects",
    ]
    if seed is not None:
        argv += ["--seed", str(seed)]
    if defect_rate is not None:
        argv += ["--defect-rate", str(defect_rate)]
    args = generator.build_parser().parse_args(argv)
    return generator.run(args)


def _run_quality(directory: Path, run_id: str, checked_at: str, quality_config: Path) -> Counter:
    inputs = {name: read_csv(directory / f"{name}.csv") for name in QUALITY_INPUTS}
    results = run_quality_checks(
        inputs["fund_periods"],
        inputs["fund_cashflows"],
        inputs["fund_master"],
        manager_master=inputs["manager_master"],
        manager_observations=inputs["manager_observations"],
        fund_terms=inputs["fund_terms"],
        fund_term_clauses=inputs["fund_term_clauses"],
        fund_holdings=inputs["fund_holdings"],
        run_id=run_id,
        checked_at=checked_at,
        tolerances=load_tolerances(quality_config) if quality_config.is_file() else None,
    )
    write_results(directory / "quality_results.csv", results)
    return Counter(row["status"] for row in results)


def score_detection(directory: Path) -> list[dict[str, str]]:
    """Score each deliberate defect against the quality failures it should raise."""

    injections = read_csv(directory / "defect_injections.csv")
    if not injections:
        raise PipelineError(
            f"{directory / 'defect_injections.csv'} carries zero rows; run the defects stage first."
        )
    results = read_csv(directory / "quality_results.csv")
    failed = {
        (row.get("fund_id", ""), row.get("rule_id", ""))
        for row in results
        if row.get("status") == "FAIL"
    }
    by_type: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in injections:
        key = (row.get("defect_type", ""), row.get("expected_rule_id", ""))
        by_type[key].append((row.get("fund_id", ""), row.get("expected_rule_id", "")) in failed)
    scorecard: list[dict[str, str]] = []
    for (defect_type, rule_id), outcomes in sorted(by_type.items()):
        injected = len(outcomes)
        detected = sum(1 for outcome in outcomes if outcome)
        scorecard.append(
            {
                "defect_type": defect_type,
                "expected_rule_id": rule_id,
                "injected": str(injected),
                "detected": str(detected),
                "missed": str(injected - detected),
                "detection_rate": f"{detected / injected:.6f}",
            }
        )
    _write_csv(directory / "detection_scorecard.csv", SCORECARD_COLUMNS, scorecard)
    return scorecard


def _write_csv(path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(sum(1 for _ in csv.reader(handle)) - 1, 0)


def write_manifest(root: Path, stages: Mapping[str, Path]) -> list[dict[str, str]]:
    """Record one row per published file so a reviewer can see the whole build."""

    rows: list[dict[str, str]] = []
    for stage, directory in stages.items():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.csv")):
            rows.append(
                {
                    "stage": stage,
                    "directory": directory.relative_to(root).as_posix(),
                    "file": path.name,
                    "rows": str(_row_count(path)),
                }
            )
    _write_csv(root / "MANIFEST.csv", MANIFEST_COLUMNS, rows)
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--stage",
        action="append",
        choices=STAGES,
        help="Run one stage. Repeat the flag to run several. Omit to run all.",
    )
    parser.add_argument("--output-root", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--fund-model-dir", type=Path, default=Path("data/csv"))
    parser.add_argument("--config", type=Path, default=Path("config/synthetic_generation.yml"))
    parser.add_argument("--quality-config", type=Path, default=Path("config/quality_rules.yml"))
    parser.add_argument(
        "--parameters", type=Path, default=Path("data/synthetic/fixture-parameters.csv")
    )
    parser.add_argument(
        "--source-ledger", type=Path, default=Path("data-gathering/source_ledger.csv")
    )
    parser.add_argument("--fund-count", type=int, default=800)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--defect-rate", type=float, default=0.18)
    parser.add_argument("--benchmark-id", default="BM_SYNTH_PUBLIC_EQUITY")
    parser.add_argument("--portfolio-id", default="PORTFOLIO_SYNTH_EQUAL_WEIGHT")
    parser.add_argument("--portfolio-perspective", default="fund_total")
    parser.add_argument("--periodicity", default="quarterly")
    parser.add_argument("--checked-at", default="2026-06-30T00:00:00Z")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/warehouse/alts_mock.duckdb"),
        help=(
            "DuckDB file the warehouse stage rebuilds. It stays apart from the "
            "fund-model warehouse so a mock build cannot reach extracted rows."
        ),
    )
    return parser


def run(args: argparse.Namespace) -> int:
    root: Path = args.output_root
    clean_dir = root / "clean"
    defect_dir = root / "defects"
    analytics_dir = root / "analytics"
    stages = args.stage or list(STAGES)

    if "clean" in stages:
        counts = _generate(
            clean_dir,
            fund_count=args.fund_count,
            seed=args.seed,
            inject_defects=False,
            defect_rate=None,
            fund_model_dir=args.fund_model_dir,
            config=args.config,
            parameters=args.parameters,
            source_ledger=args.source_ledger,
        )
        print(f"clean: {sum(counts.values())} rows across {len(counts)} tables -> {clean_dir}")

    if "clean-qc" in stages:
        tally = _run_quality(clean_dir, "SYNTH_CLEAN_QC", args.checked_at, args.quality_config)
        print(
            f"clean-qc: {tally['PASS']} pass, {tally['FAIL']} fail, {tally['SKIP']} skip"
        )
        if tally["FAIL"]:
            raise PipelineError(
                f"The clean population raised {tally['FAIL']} quality failures; "
                "analytics stays gated until it reconciles."
            )

    if "analytics" in stages:
        counts = run_round04(
            clean_dir,
            analytics_dir,
            benchmark_id=args.benchmark_id,
            portfolio_id=args.portfolio_id,
            periodicity=args.periodicity,
            portfolio_perspective=args.portfolio_perspective,
            quality_config=args.quality_config,
        )
        for filename, count in counts.items():
            print(f"analytics: {filename}: {count} rows")

    if "defects" in stages:
        counts = _generate(
            defect_dir,
            fund_count=args.fund_count,
            seed=args.seed,
            inject_defects=True,
            defect_rate=args.defect_rate,
            fund_model_dir=args.fund_model_dir,
            config=args.config,
            parameters=args.parameters,
            source_ledger=args.source_ledger,
        )
        print(
            f"defects: {counts['defect_injections.csv']} deliberate defects -> {defect_dir}"
        )

    if "defects-qc" in stages:
        tally = _run_quality(defect_dir, "SYNTH_DEFECT_QC", args.checked_at, args.quality_config)
        print(
            f"defects-qc: {tally['PASS']} pass, {tally['FAIL']} fail, {tally['SKIP']} skip"
        )
        if not tally["FAIL"]:
            raise PipelineError(
                "The defect population raised zero quality failures; the rules are not "
                "seeing the injected defects."
            )

    if "score" in stages:
        scorecard = score_detection(defect_dir)
        missed = sum(int(row["missed"]) for row in scorecard)
        injected = sum(int(row["injected"]) for row in scorecard)
        print(f"score: {injected - missed} of {injected} deliberate defects detected")
        if missed:
            for row in scorecard:
                if int(row["missed"]):
                    print(
                        f"score: MISSED {row['missed']} of {row['injected']} "
                        f"{row['defect_type']} ({row['expected_rule_id']})"
                    )

    if "warehouse" in stages:
        if args.database.resolve() == Path("data/warehouse/alts.duckdb").resolve():
            raise PipelineError(
                "The warehouse stage refuses to write the fund-model warehouse; "
                "point --database at a separate file."
            )
        counts = load_duckdb(clean_dir, args.database, replace=True, rebuild=True)
        appended = load_duckdb(analytics_dir, args.database, replace=False)
        for table, count in appended.items():
            counts[table] = counts.get(table, 0) + count
        loaded = sum(counts.values())
        print(f"warehouse: {loaded} rows across {len(counts)} tables -> {args.database}")

    if "manifest" in stages:
        rows = write_manifest(
            root, {"clean": clean_dir, "defects": defect_dir, "analytics": analytics_dir}
        )
        total = sum(int(row["rows"]) for row in rows)
        print(f"manifest: {len(rows)} files, {total} rows -> {root / 'MANIFEST.csv'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (PipelineError, generator.GenerationError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
