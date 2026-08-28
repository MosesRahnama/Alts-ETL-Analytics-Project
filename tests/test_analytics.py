"""Tests for deterministic fund metrics, PME, and bounded allocations."""

from __future__ import annotations

import csv
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.analytics import (
    ANALYSIS_RESULT_COLUMNS,
    PORTFOLIO_ALLOCATION_COLUMNS,
    AnalyticsError,
    bounded_equal_weights,
    build_portfolio_allocations,
    calculate_fund_metrics,
    calculate_pme_results,
)
from src.common.finance import xirr
from src.quality.run_fund_checks import RULES


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def period(
    fund_id: str,
    period_id: str,
    *,
    paid_in: str = "100",
    distributions: str = "20",
    nav: str = "110",
    as_of_date: str = "2021-09-30",
    lp_id: str = "",
    lp_name: str = "",
    share_class_name: str = "",
    provenance_type: str = "SYNTHETIC",
) -> dict[str, str]:
    return {
        "fund_period_id": period_id,
        "fund_id": fund_id,
        "lp_id": lp_id,
        "lp_name": lp_name,
        "share_class_name": share_class_name,
        "as_of_date": as_of_date,
        "perspective": "lp_position",
        "currency": "USD",
        "commitment": "125",
        "paid_in_capital_itd": paid_in,
        "distributions_itd": distributions,
        "nav": nav,
        "unfunded_commitment": "25",
        "calculated_irr": "0.12",
        "reported_irr": "0.11",
        "period_return": "0.10",
        "strategy": "buyout",
        "sub_strategy": "middle_market",
        "provenance_type": provenance_type,
        "synthetic_parameter_set_id": "TEST_SET",
        "record_status": "ACTIVE",
    }


def cashflow(
    cashflow_id: str,
    fund_id: str,
    cashflow_date: str,
    amount: str,
    *,
    lp_id: str = "",
    lp_name: str = "",
    share_class_name: str = "",
) -> dict[str, str]:
    return {
        "cashflow_id": cashflow_id,
        "fund_id": fund_id,
        "lp_id": lp_id,
        "lp_name": lp_name,
        "share_class_name": share_class_name,
        "cashflow_date": cashflow_date,
        "amount": amount,
        "currency": "USD",
        "amount_base_currency": amount,
        "base_currency": "USD",
        "record_status": "ACTIVE",
    }


def quality_rows(
    period_id: str,
    fund_id: str,
    *,
    failed_rule: str = "",
    run_id: str = "RUN_COMPLETE",
) -> list[dict[str, str]]:
    return [
        {
            "quality_result_id": f"{run_id}_{period_id}_{rule_id}",
            "run_id": run_id,
            "record_table": "fund_periods",
            "record_id": period_id,
            "fund_id": fund_id,
            "rule_id": rule_id,
            "severity": severity,
            "status": "FAIL" if rule_id == failed_rule else "PASS",
            "checked_at": "2026-08-09T12:00:00Z",
        }
        for rule_id, severity in RULES
    ]


def benchmark(
    record_id: str, return_date: str, return_value: str
) -> dict[str, str]:
    return {
        "benchmark_return_id": record_id,
        "benchmark_id": "BM",
        "return_date": return_date,
        "periodicity": "annual",
        "return_value": return_value,
        "record_status": "ACTIVE",
    }


class AnalyticsTests(unittest.TestCase):
    def test_fund_metrics_recompute_components_and_exclude_failed_period(self) -> None:
        periods = [period("FUND_A", "PERIOD_A"), period("FUND_B", "PERIOD_B")]
        cashflows = [
            cashflow("CF_A_1", "FUND_A", "2020-06-30", "-100"),
            cashflow("CF_A_2", "FUND_A", "2021-06-30", "20"),
            cashflow("CF_B_1", "FUND_B", "2020-06-30", "-100"),
            cashflow("CF_B_2", "FUND_B", "2021-06-30", "20"),
        ]
        rows = calculate_fund_metrics(
            periods,
            cashflows,
            [
                *quality_rows("PERIOD_A", "FUND_A"),
                *quality_rows(
                    "PERIOD_B", "FUND_B", failed_rule="R02_TVPI_COMPONENTS"
                ),
            ],
        )
        values = {row["metric_id"]: float(row["value_numeric"]) for row in rows}
        self.assertEqual({row["entity_id"] for row in rows}, {"FUND_A"})
        self.assertAlmostEqual(values["dpi"], 0.2)
        self.assertAlmostEqual(values["rvpi"], 1.1)
        self.assertAlmostEqual(values["tvpi"], 1.3)
        self.assertEqual({row["provenance_type"] for row in rows}, {"SYNTHETIC"})
        expected_xirr = xirr(
            [
                (date(2020, 6, 30), -100.0),
                (date(2021, 6, 30), 20.0),
                (date(2021, 9, 30), 110.0),
            ]
        )
        self.assertAlmostEqual(values["xirr"], expected_xirr, places=9)

    def test_pme_uses_latest_prior_benchmark_observation(self) -> None:
        periods = [period("FUND_A", "PERIOD_A", nav="80")]
        cashflows = [
            cashflow("CF_A_1", "FUND_A", "2020-06-30", "-100"),
            cashflow("CF_A_2", "FUND_A", "2021-06-30", "30"),
        ]
        benchmarks = [
            benchmark("BM_2019", "2019-12-31", "0"),
            benchmark("BM_2020", "2020-12-31", "1"),
            benchmark("BM_FUTURE", "2021-12-31", "9"),
        ]
        rows = calculate_pme_results(
            periods,
            cashflows,
            benchmarks,
            quality_rows("PERIOD_A", "FUND_A"),
            benchmark_id="BM",
            periodicity="annual",
        )
        values = {row["metric_id"]: float(row["value_numeric"]) for row in rows}
        self.assertAlmostEqual(values["ks_pme"], 0.55)
        expected_alpha = xirr(
            [
                (date(2020, 6, 30), -200.0),
                (date(2021, 6, 30), 30.0),
                (date(2021, 9, 30), 80.0),
            ]
        )
        self.assertAlmostEqual(values["direct_alpha"], expected_alpha, places=9)
        for row in rows:
            self.assertEqual(row["provenance_type"], "SYNTHETIC")
            input_ids = set(row["input_record_ids"].split(";"))
            matched_benchmark_ids = {
                record_id for record_id in input_ids if record_id.startswith("BM_")
            }
            self.assertEqual(matched_benchmark_ids, {"BM_2019", "BM_2020"})

    def test_pme_rejects_missing_prior_benchmark_observation(self) -> None:
        with self.assertRaisesRegex(AnalyticsError, "on or before 2020-06-30"):
            calculate_pme_results(
                [period("FUND_A", "PERIOD_A")],
                [cashflow("CF_A_1", "FUND_A", "2020-06-30", "-100")],
                [benchmark("BM_LATE", "2020-12-31", "0.1")],
                quality_rows("PERIOD_A", "FUND_A"),
                benchmark_id="BM",
                periodicity="annual",
            )

    def test_position_metrics_isolate_cashflows_within_one_fund(self) -> None:
        periods = [
            period(
                "FUND_A",
                "PERIOD_LP_A",
                lp_id="LP_A",
                lp_name="Investor A",
                share_class_name="Class A",
            ),
            period(
                "FUND_A",
                "PERIOD_LP_B",
                paid_in="200",
                distributions="40",
                nav="220",
                lp_id="LP_B",
                lp_name="Investor B",
                share_class_name="Class B",
            ),
        ]
        cashflows = [
            cashflow(
                "CF_LP_A_CALL",
                "FUND_A",
                "2020-06-30",
                "-100",
                lp_id="LP_A",
                lp_name="Investor A",
                share_class_name="Class A",
            ),
            cashflow(
                "CF_LP_A_DIST",
                "FUND_A",
                "2021-06-30",
                "20",
                lp_id="LP_A",
                lp_name="Investor A",
                share_class_name="Class A",
            ),
            cashflow(
                "CF_LP_B_CALL",
                "FUND_A",
                "2020-06-30",
                "-200",
                lp_id="LP_B",
                lp_name="Investor B",
                share_class_name="Class B",
            ),
            cashflow(
                "CF_LP_B_DIST",
                "FUND_A",
                "2021-06-30",
                "40",
                lp_id="LP_B",
                lp_name="Investor B",
                share_class_name="Class B",
            ),
        ]
        rows = calculate_fund_metrics(
            periods,
            cashflows,
            [
                *quality_rows("PERIOD_LP_A", "FUND_A"),
                *quality_rows("PERIOD_LP_B", "FUND_A"),
            ],
        )
        xirr_rows = [row for row in rows if row["metric_id"] == "xirr"]
        self.assertEqual(len({row["entity_id"] for row in xirr_rows}), 2)
        for row in xirr_rows:
            input_ids = row["input_record_ids"]
            self.assertEqual("CF_LP_A" in input_ids, "PERIOD_LP_A" in input_ids)
            self.assertEqual("CF_LP_B" in input_ids, "PERIOD_LP_B" in input_ids)

    def test_bounded_weights_sum_to_one_and_hold_every_bound(self) -> None:
        bounds = {
            "FUND_A": (Decimal("0.10"), Decimal("0.20")),
            "FUND_B": (Decimal("0.10"), Decimal("0.60")),
            "FUND_C": (Decimal("0.10"), Decimal("0.80")),
        }
        weights = bounded_equal_weights(bounds)
        self.assertEqual(sum(weights.values()), Decimal("1"))
        self.assertEqual(weights["FUND_A"], Decimal("0.2000000000"))
        self.assertEqual(weights["FUND_B"], Decimal("0.4000000000"))
        self.assertEqual(weights["FUND_C"], Decimal("0.4000000000"))
        for fund_id, weight in weights.items():
            self.assertGreaterEqual(weight, bounds[fund_id][0])
            self.assertLessEqual(weight, bounds[fund_id][1])

    def test_portfolio_rows_use_a_fixed_order_and_deterministic_weights(self) -> None:
        periods = [
            period("FUND_A", "PERIOD_A"),
            period("FUND_B", "PERIOD_B"),
            period("FUND_C", "PERIOD_C"),
        ]
        quality_rows_input = [
            *quality_rows("PERIOD_A", "FUND_A"),
            *quality_rows("PERIOD_B", "FUND_B"),
            *quality_rows("PERIOD_C", "FUND_C"),
        ]
        rows = build_portfolio_allocations(
            periods,
            quality_rows_input,
            portfolio_id="PORT_TEST",
            as_of_date=date(2021, 9, 30),
            fund_bounds={
                "FUND_A": (0.10, 0.20),
                "FUND_B": (0.10, 0.60),
                "FUND_C": (0.10, 0.80),
            },
        )
        self.assertEqual([row["fund_id"] for row in rows], ["FUND_A", "FUND_B", "FUND_C"])
        self.assertEqual(sum(Decimal(row["target_weight"]) for row in rows), Decimal("1"))
        self.assertTrue(all(tuple(row) == PORTFOLIO_ALLOCATION_COLUMNS for row in rows))

    def test_quality_gate_rejects_partial_or_mixed_runs(self) -> None:
        period_rows = [period("FUND_A", "PERIOD_A")]
        cashflows = [cashflow("CF_A", "FUND_A", "2020-06-30", "-100")]
        partial = quality_rows("PERIOD_A", "FUND_A")[:-1]
        with self.assertRaisesRegex(AnalyticsError, "coherent R01-through-R15"):
            calculate_fund_metrics(period_rows, cashflows, partial)

        mixed = [
            *quality_rows("PERIOD_A", "FUND_A", run_id="RUN_A")[:-1],
            quality_rows("PERIOD_A", "FUND_A", run_id="RUN_B")[-1],
        ]
        with self.assertRaisesRegex(AnalyticsError, "coherent R01-through-R15"):
            calculate_fund_metrics(period_rows, cashflows, mixed)

    def test_benchmark_periodicity_is_case_insensitive(self) -> None:
        rows = calculate_pme_results(
            [period("FUND_A", "PERIOD_A", nav="80")],
            [cashflow("CF_A", "FUND_A", "2020-06-30", "-100")],
            [benchmark("BM_2019", "2019-12-31", "0")],
            quality_rows("PERIOD_A", "FUND_A"),
            benchmark_id="BM",
            periodicity="ANNUAL",
        )
        self.assertEqual(len(rows), 2)

    def test_infeasible_bounds_are_rejected(self) -> None:
        with self.assertRaisesRegex(AnalyticsError, "infeasible bounds"):
            bounded_equal_weights({"FUND_A": (0.0, 0.4), "FUND_B": (0.0, 0.4)})

    def test_output_constants_match_repository_csv_headers(self) -> None:
        with (PROJECT_ROOT / "data" / "csv" / "fund_metrics.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            self.assertEqual(tuple(next(csv.reader(handle))), ANALYSIS_RESULT_COLUMNS)
        with (PROJECT_ROOT / "data" / "csv" / "pme_results.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            self.assertEqual(tuple(next(csv.reader(handle))), ANALYSIS_RESULT_COLUMNS)
        with (PROJECT_ROOT / "data" / "csv" / "portfolio_allocations.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            self.assertEqual(tuple(next(csv.reader(handle))), PORTFOLIO_ALLOCATION_COLUMNS)


if __name__ == "__main__":
    unittest.main()
