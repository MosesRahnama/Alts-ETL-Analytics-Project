"""Validate copied market sources and staged benchmark candidates."""

from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from src.market_data import curate_public_markets as curate


ROOT = Path(__file__).resolve().parents[1]
MARKET_ROOT = ROOT / "data" / "public_markets"


def read_rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


class PublicMarketTransferTests(unittest.TestCase):
    def test_scratch_output_paths_are_relative_to_the_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output_root = Path(folder)
            source = output_root / "sources" / "sample.parquet"
            self.assertEqual(
                curate.portable_output_path(source, output_root),
                "sources/sample.parquet",
            )
            self.assertEqual(
                curate.portable_output_path(output_root, output_root), "."
            )

    def test_source_inventory_matches_copied_files(self) -> None:
        inventory = list(read_rows(MARKET_ROOT / "audit" / "source_file_inventory.csv"))
        copied = sorted((MARKET_ROOT / "sources").glob("*.parquet"))
        self.assertEqual(len(inventory), 334)
        self.assertEqual(len(copied), 334)
        inventory_paths = {ROOT / row["destination_relative_path"] for row in inventory}
        self.assertEqual(inventory_paths, set(copied))
        self.assertTrue(all("UNRESOLVED" not in row["timezone_status"] for row in inventory))
        by_source = {row["source_relative_path"]: row for row in inventory}
        self.assertEqual(
            by_source["features/ng_balance_weekly.parquet"]["date_column"], "friday"
        )
        self.assertEqual(
            by_source["raw/macro/EIA_ng_state_demand_weights.parquet"]["date_column"],
            "window_start",
        )

    def test_benchmark_levels_and_returns_reconcile(self) -> None:
        masters = list(read_rows(MARKET_ROOT / "staging" / "benchmark_master_candidates.csv"))
        master_ids = {row["benchmark_id"] for row in masters}
        self.assertEqual(len(master_ids), 58)
        levels = {}
        level_keys = set()
        for row in read_rows(MARKET_ROOT / "staging" / "benchmark_level_candidates.csv"):
            self.assertIn(row["benchmark_id"], master_ids)
            key = (row["benchmark_id"], row["observation_date"])
            self.assertNotIn(key, level_keys)
            level_keys.add(key)
            level = float(row["level_value"])
            self.assertGreater(level, 0.0)
            levels[row["benchmark_level_id"]] = level
        return_count = 0
        for row in read_rows(MARKET_ROOT / "staging" / "benchmark_return_candidates.csv"):
            start = levels[row["source_level_start_id"]]
            end = levels[row["source_level_end_id"]]
            reported = float(row["return_value"])
            self.assertGreater(reported, -1.0)
            self.assertAlmostEqual(reported, end / start - 1.0, places=10)
            return_count += 1
        self.assertEqual(len(levels), 279269)
        self.assertEqual(return_count, 279211)

    def test_strategy_map_and_quality_gate(self) -> None:
        master_ids = {
            row["benchmark_id"]
            for row in read_rows(MARKET_ROOT / "staging" / "benchmark_master_candidates.csv")
        }
        strategy_rows = list(
            read_rows(MARKET_ROOT / "staging" / "benchmark_strategy_map_candidates.csv")
        )
        self.assertEqual(len(strategy_rows), 19)
        self.assertTrue(all(row["benchmark_id"] in master_ids for row in strategy_rows))
        quality_rows = list(read_rows(MARKET_ROOT / "audit" / "quality_results.csv"))
        self.assertEqual(len(quality_rows), 10)
        self.assertTrue(all(row["status"] == "PASS" for row in quality_rows))


if __name__ == "__main__":
    unittest.main()
