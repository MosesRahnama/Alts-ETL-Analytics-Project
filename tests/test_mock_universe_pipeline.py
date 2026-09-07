"""End-to-end guards for the mock-universe wrapper and its stage gates."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.pipeline.build_mock_universe import (
    STAGES,
    PipelineError,
    build_parser,
    run,
    score_detection,
    write_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class MockUniversePipelineTests(unittest.TestCase):
    def _arguments(self, root: Path, *stages: str, fund_count: int = 6):
        argv = [
            "--output-root",
            str(root),
            "--fund-count",
            str(fund_count),
            "--defect-rate",
            "1.0",
            "--fund-model-dir",
            str(PROJECT_ROOT / "data" / "csv"),
            "--config",
            str(PROJECT_ROOT / "config" / "synthetic_generation.yml"),
            "--quality-config",
            str(PROJECT_ROOT / "config" / "quality_rules.yml"),
            "--parameters",
            str(PROJECT_ROOT / "data" / "synthetic" / "fixture-parameters.csv"),
            "--source-ledger",
            str(PROJECT_ROOT / "data-gathering" / "source_ledger.csv"),
            "--database",
            str(root / "mock.duckdb"),
        ]
        for stage in stages:
            argv += ["--stage", stage]
        return build_parser().parse_args(argv)

    def test_clean_population_reaches_analytics_with_a_dated_series(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(
                run(self._arguments(root, "clean", "clean-qc", "analytics")), 0
            )
            quality = read_rows(root / "clean" / "quality_results.csv")
            self.assertTrue(quality)
            self.assertEqual([row for row in quality if row["status"] == "FAIL"], [])

            periods = read_rows(root / "clean" / "fund_periods.csv")
            fund_total = [row for row in periods if row["perspective"] == "fund_total"]
            self.assertGreater(len(fund_total), len({row["fund_id"] for row in fund_total}))

            metrics = read_rows(root / "analytics" / "fund_metrics.csv")
            self.assertEqual(
                {row["metric_id"] for row in metrics}, {"dpi", "rvpi", "tvpi", "xirr"}
            )
            self.assertEqual({row["provenance_type"] for row in metrics}, {"SYNTHETIC"})
            self.assertEqual(len(metrics), 4 * len(periods))
            pme = read_rows(root / "analytics" / "pme_results.csv")
            self.assertEqual({row["metric_id"] for row in pme}, {"ks_pme", "direct_alpha"})
            self.assertEqual({row["provenance_type"] for row in pme}, {"SYNTHETIC"})
            self.assertGreater(
                len({row["as_of_date"] for row in metrics}),
                1,
                "analytics must produce a dated series, not one snapshot",
            )

    def test_every_deliberate_defect_is_scored_against_its_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(run(self._arguments(root, "defects", "defects-qc", "score")), 0)
            scorecard = score_detection(root / "defects")
            self.assertTrue(scorecard)
            self.assertEqual(sum(int(row["missed"]) for row in scorecard), 0)
            injections = read_rows(root / "defects" / "defect_injections.csv")
            self.assertEqual(
                sum(int(row["injected"]) for row in scorecard), len(injections)
            )
            self.assertEqual(
                len({row["fund_id"] for row in injections}),
                len(injections),
                "the injector places at most one defect per fund",
            )

    def test_warehouse_stage_refuses_the_fund_model_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            arguments = self._arguments(root, "warehouse")
            arguments.database = Path("data/warehouse/alts.duckdb")
            with self.assertRaises(PipelineError):
                run(arguments)

    def test_manifest_counts_every_published_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(run(self._arguments(root, "clean")), 0)
            rows = write_manifest(root, {"clean": root / "clean"})
            self.assertTrue(rows)
            by_file = {row["file"]: int(row["rows"]) for row in rows}
            self.assertEqual(by_file["fund_master.csv"], 6)
            self.assertGreater(by_file["fund_periods.csv"], 6)
            self.assertEqual(
                by_file["fund_master.csv"],
                len(read_rows(root / "clean" / "fund_master.csv")),
            )

    def test_stage_list_and_parser_choices_agree(self) -> None:
        parser = build_parser()
        stage_action = next(
            action for action in parser._actions if action.dest == "stage"
        )
        self.assertEqual(tuple(stage_action.choices), STAGES)


if __name__ == "__main__":
    unittest.main()
