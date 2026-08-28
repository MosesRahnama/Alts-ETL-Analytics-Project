from __future__ import annotations

import csv
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class IntegratedUniverseTests(unittest.TestCase):
    def test_identity_spine_uses_every_extracted_fund_and_no_fixture_id(self) -> None:
        extracted = PROJECT_ROOT / "data" / "extracted" / "fund-level"
        extracted_ids: set[str] = set()
        for filename in (
            "fund_master.csv",
            "document_fund_map.csv",
            "fund_observations.csv",
            "fund_cashflows.csv",
            "fund_periods.csv",
            "fund_terms.csv",
            "fund_term_clauses.csv",
            "fund_holdings.csv",
        ):
            extracted_ids.update(
                row["fund_id"] for row in rows(extracted / filename) if row.get("fund_id")
            )
        master_ids = {
            row["fund_id"] for row in rows(PROJECT_ROOT / "data" / "csv" / "fund_master.csv")
        }
        self.assertEqual(master_ids, extracted_ids)
        self.assertFalse(any(fund_id.startswith("FUND_SYNTH_") for fund_id in master_ids))

    def test_source_rows_survive_and_completion_is_additive(self) -> None:
        extracted = PROJECT_ROOT / "data" / "extracted" / "fund-level"
        final = PROJECT_ROOT / "data" / "csv"
        for filename, key in (
            ("fund_periods.csv", "fund_period_id"),
            ("fund_cashflows.csv", "cashflow_id"),
            ("fund_holdings.csv", "holding_id"),
        ):
            source_rows = {row[key]: row for row in rows(extracted / filename)}
            final_rows = {row[key]: row for row in rows(final / filename)}
            for record_id, source in source_rows.items():
                self.assertEqual(final_rows[record_id], source)

    def test_completed_periods_reconcile_and_cover_every_fund(self) -> None:
        master = rows(PROJECT_ROOT / "data" / "csv" / "fund_master.csv")
        periods = [
            row
            for row in rows(PROJECT_ROOT / "data" / "csv" / "fund_periods.csv")
            if row.get("synthetic_parameter_set_id") == "INTEGRATED_COMPLETION_V1"
        ]
        self.assertEqual({row["fund_id"] for row in periods}, {row["fund_id"] for row in master})
        for row in periods:
            paid = float(row["paid_in_capital_itd"])
            distributions = float(row["distributions_itd"])
            nav = float(row["nav"])
            self.assertAlmostEqual(float(row["dpi"]), distributions / paid, places=5)
            self.assertAlmostEqual(float(row["rvpi"]), nav / paid, places=5)
            self.assertAlmostEqual(float(row["tvpi"]), float(row["dpi"]) + float(row["rvpi"]), places=5)
            self.assertAlmostEqual(
                float(row["commitment"]),
                paid + float(row["unfunded_commitment"]) - float(row["recallable_distributions_itd"]),
                places=4,
            )

    def test_integrated_analytics_and_defect_detection_are_complete(self) -> None:
        target_count = sum(
            row.get("synthetic_parameter_set_id") == "INTEGRATED_COMPLETION_V1"
            for row in rows(PROJECT_ROOT / "data" / "csv" / "fund_periods.csv")
        )
        metrics = rows(PROJECT_ROOT / "data" / "csv" / "fund_metrics.csv")
        pme = rows(PROJECT_ROOT / "data" / "csv" / "pme_results.csv")
        allocations = rows(PROJECT_ROOT / "data" / "csv" / "portfolio_allocations.csv")
        scorecard = rows(PROJECT_ROOT / "data" / "integrated" / "detection-scorecard.csv")
        self.assertEqual(len(metrics), target_count * 4)
        self.assertEqual(len(pme), target_count * 2)
        self.assertEqual(len(allocations), target_count)
        self.assertEqual({row["provenance_type"] for row in metrics}, {"SYNTHETIC"})
        self.assertEqual({row["provenance_type"] for row in pme}, {"SYNTHETIC"})
        self.assertTrue(all(float(row["detection_rate"]) == 1.0 for row in scorecard))

    def test_extracted_only_metrics_remain_visible(self) -> None:
        extracted = PROJECT_ROOT / "data" / "extracted" / "fund-level"
        metrics = rows(extracted / "fund_metrics.csv")
        period_ids = {row["fund_period_id"] for row in rows(extracted / "fund_periods.csv")}
        self.assertTrue(metrics)
        self.assertEqual({row["provenance_type"] for row in metrics}, {"EXTRACTED"})
        self.assertTrue(
            all(row["input_record_ids"].split(";")[0] in period_ids for row in metrics)
        )

    def test_terms_and_holdings_complete_the_same_funds(self) -> None:
        data = PROJECT_ROOT / "data" / "csv"
        master_ids = {row["fund_id"] for row in rows(data / "fund_master.csv")}
        terms = [
            row
            for row in rows(data / "fund_terms.csv")
            if row.get("synthetic_parameter_set_id") == "INTEGRATED_COMPLETION_V1"
        ]
        holdings = [
            row
            for row in rows(data / "fund_holdings.csv")
            if row.get("synthetic_parameter_set_id") == "INTEGRATED_COMPLETION_V1"
        ]
        self.assertEqual({row["fund_id"] for row in terms}, master_ids)
        self.assertEqual(len(terms), len(master_ids))
        self.assertEqual(len(holdings), len(master_ids) * 3)


if __name__ == "__main__":
    unittest.main()
