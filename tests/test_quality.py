"""Tests for deterministic private-fund calculations and quality results."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.common.finance import xirr, xnpv
from src.quality.run_fund_checks import (
    RESULT_COLUMNS,
    printed_half_unit,
    printed_precision_from_observations,
    run_quality_checks,
    write_results,
)


class FinanceTests(unittest.TestCase):
    def test_xirr_for_one_year_cashflows(self) -> None:
        cashflows = [(date(2021, 1, 1), -100.0), (date(2022, 1, 1), 110.0)]
        self.assertAlmostEqual(xirr(cashflows), 0.10, places=8)
        self.assertAlmostEqual(xnpv(0.10, cashflows), 0.0, places=8)

    def test_xirr_requires_both_signs(self) -> None:
        with self.assertRaisesRegex(ValueError, "negative and one positive"):
            xirr([(date(2021, 1, 1), -100.0), (date(2022, 1, 1), -10.0)])


class QualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.period = {
            "fund_period_id": "FP_SYNTH_001",
            "fund_id": "FUND_SYNTH_001",
            "as_of_date": "2024-12-31",
            "perspective": "lp_position",
            "currency": "USD",
            "commitment": "100",
            "paid_in_capital_itd": "90",
            "distributions_itd": "45",
            "nav": "90",
            "unfunded_commitment": "10",
            "recallable_distributions_itd": "0",
            "dpi": "0.5",
            "rvpi": "1.0",
            "tvpi": "1.5",
            "reported_irr": "0.2110768792",
            "beginning_nav": "75",
            "contributions_period": "20",
            "distributions_period": "35",
            "realized_gain_period": "10",
            "unrealized_gain_period": "20",
            "net_income_period": "0",
            "management_fee_period": "0",
            "other_expenses_period": "0",
            "ending_nav": "90",
            "fund_size": "500",
            "vintage_year": "2020",
            "provenance_type": "SYNTHETIC",
            "source_document_id": "",
            "synthetic_parameter_set_id": "PARAM_V1",
        }
        self.cashflows = [
            {"cashflow_id": "CF_1", "fund_id": "FUND_SYNTH_001", "cashflow_date": "2020-06-30", "cashflow_type": "capital_call", "amount": "-40", "currency": "USD", "base_currency": "USD", "amount_base_currency": "-40", "fx_rate": "1"},
            {"cashflow_id": "CF_2", "fund_id": "FUND_SYNTH_001", "cashflow_date": "2021-06-30", "cashflow_type": "capital_call", "amount": "-30", "currency": "USD", "base_currency": "USD", "amount_base_currency": "-30", "fx_rate": "1"},
            {"cashflow_id": "CF_3", "fund_id": "FUND_SYNTH_001", "cashflow_date": "2022-06-30", "cashflow_type": "capital_call", "amount": "-20", "currency": "USD", "base_currency": "USD", "amount_base_currency": "-20", "fx_rate": "1"},
            {"cashflow_id": "CF_4", "fund_id": "FUND_SYNTH_001", "cashflow_date": "2023-06-30", "cashflow_type": "distribution", "amount": "10", "currency": "USD", "base_currency": "USD", "amount_base_currency": "10", "fx_rate": "1"},
            {"cashflow_id": "CF_5", "fund_id": "FUND_SYNTH_001", "cashflow_date": "2024-06-30", "cashflow_type": "distribution", "amount": "35", "currency": "USD", "base_currency": "USD", "amount_base_currency": "35", "fx_rate": "1"},
        ]
        expected_irr = xirr(
            [(date.fromisoformat(row["cashflow_date"]), float(row["amount"])) for row in self.cashflows]
            + [(date(2024, 12, 31), 90.0)]
        )
        self.period["reported_irr"] = str(expected_irr)
        self.master = {
            "fund_id": "FUND_SYNTH_001",
            "fund_name": "Synthetic Demonstration Fund I",
            "provenance_type": "SYNTHETIC",
            "source_document_id": "",
            "synthetic_parameter_set_id": "PARAM_V1",
            "fund_size": "500",
        }

    def test_clean_period_passes_every_applicable_rule(self) -> None:
        rows = run_quality_checks(
            [self.period], self.cashflows, [self.master], run_id="TEST", checked_at="2026-08-02T00:00:00Z"
        )
        self.assertEqual(len(rows), 15)
        self.assertTrue(all(row["status"] == "PASS" for row in rows), rows)

    def test_synthetic_fact_can_complete_a_resolved_real_fund(self) -> None:
        period = dict(self.period, fund_id="FUND_0001")
        cashflows = [dict(row, fund_id="FUND_0001") for row in self.cashflows]
        master = {
            "fund_id": "FUND_0001",
            "fund_name": "Source Fund I, L.P.",
            "provenance_type": "EXTRACTED",
            "source_document_id": "SRC001",
            "synthetic_parameter_set_id": "",
        }
        rows = run_quality_checks([period], cashflows, [master])
        identity = next(row for row in rows if row["rule_id"] == "R12_SYNTHETIC_IDENTITY_SEPARATION")
        self.assertEqual(identity["status"], "PASS")

    def test_xirr_checks_calculated_irr_when_reported_irr_is_absent(self) -> None:
        period = dict(self.period)
        period["calculated_irr"] = period["reported_irr"]
        period["reported_irr"] = ""
        rows = run_quality_checks([period], self.cashflows, [self.master])
        result = next(row for row in rows if row["rule_id"] == "R08_XIRR_RECOMPUTE")
        self.assertEqual(result["status"], "PASS")
        self.assertIn("calculated IRR", result["notes"])

    def test_injected_errors_are_detected(self) -> None:
        bad = dict(self.period)
        bad.update({"tvpi": "1.45", "unfunded_commitment": "30", "ending_nav": "92", "reported_irr": "0.4"})
        rows = run_quality_checks([bad], self.cashflows, [self.master])
        failed = {row["rule_id"] for row in rows if row["status"] == "FAIL"}
        self.assertTrue(
            {
                "R02_TVPI_COMPONENTS",
                "R05_TVPI_RECOMPUTE",
                "R06_COMMITMENT_RECONCILIATION",
                "R07_NAV_ROLLFORWARD",
                "R08_XIRR_RECOMPUTE",
            }.issubset(failed)
        )

    def test_printed_half_unit_reads_the_page_precision(self) -> None:
        self.assertEqual(printed_half_unit("$90.5", 1_000_000), 50_000)
        self.assertEqual(printed_half_unit("1.05x"), 0.005)
        self.assertEqual(printed_half_unit("22,909,961"), 0.5)
        self.assertEqual(printed_half_unit("($1.5)", 1_000_000), 50_000)
        self.assertIsNone(printed_half_unit("n.m."))

    def test_page_rounding_passes_and_a_real_break_still_fails(self) -> None:
        """A page prints DPI 0.47, RVPI 0.58, TVPI 1.04: each to two decimals,
        so the sum can sit 0.01 from the printed total with the page telling
        the truth. The rule accepts that gap and no larger one."""

        period = dict(self.period)
        period.update({
            "fund_period_id": "FP_PRINTED",
            "provenance_type": "EXTRACTED",
            "source_document_id": "SRC457",
            "input_observation_ids": "OBS_DPI;OBS_RVPI;OBS_TVPI",
            "dpi": "0.47", "rvpi": "0.58", "tvpi": "1.04",
            "paid_in_capital_itd": "", "distributions_itd": "", "nav": "",
            "reported_irr": "",
        })
        observations = [
            {"observation_id": "OBS_DPI", "metric_category": "dpi", "value_raw": "0.47", "unit_scale_multiplier": "1"},
            {"observation_id": "OBS_RVPI", "metric_category": "rvpi", "value_raw": "0.58", "unit_scale_multiplier": "1"},
            {"observation_id": "OBS_TVPI", "metric_category": "tvpi", "value_raw": "1.04", "unit_scale_multiplier": "1"},
        ]
        precision = printed_precision_from_observations([period], observations)
        self.assertEqual(precision, {"FP_PRINTED": {"dpi": 0.005, "rvpi": 0.005, "tvpi": 0.005}})

        strict = {row["rule_id"]: row for row in run_quality_checks([period], [], [self.master])}
        self.assertEqual(strict["R02_TVPI_COMPONENTS"]["status"], "FAIL")

        aware = {
            row["rule_id"]: row
            for row in run_quality_checks([period], [], [self.master], printed_precision=precision)
        }
        self.assertEqual(aware["R02_TVPI_COMPONENTS"]["status"], "PASS")
        self.assertEqual(aware["R02_TVPI_COMPONENTS"]["tolerance"], "0.02")
        self.assertIn("widened by 0.015", aware["R02_TVPI_COMPONENTS"]["notes"])

        broken = dict(period)
        broken["tvpi"] = "1.10"
        rows = {
            row["rule_id"]: row
            for row in run_quality_checks([broken], [], [self.master], printed_precision=precision)
        }
        self.assertEqual(rows["R02_TVPI_COMPONENTS"]["status"], "FAIL")

    def test_amounts_printed_in_millions_widen_the_quotient_rules(self) -> None:
        """$90.5M paid in, $6.1M distributed, $89.4M NAV, TVPI 1.05x: the exact
        quotient is 1.055, and the page is right at its own precision."""

        period = dict(self.period)
        period.update({
            "fund_period_id": "FP_MILLIONS",
            "provenance_type": "EXTRACTED",
            "source_document_id": "SRC058",
            "input_observation_ids": "O1|O2|O3|O4",
            "paid_in_capital_itd": "90500000", "distributions_itd": "6100000", "nav": "89400000",
            "dpi": "", "rvpi": "", "tvpi": "1.05", "reported_irr": "",
        })
        observations = [
            {"observation_id": "O1", "metric_category": "paid_in_capital", "value_raw": "$90.5", "unit_scale_multiplier": "1000000"},
            {"observation_id": "O2", "metric_category": "distribution", "value_raw": "$6.1", "unit_scale_multiplier": "1000000"},
            {"observation_id": "O3", "metric_category": "nav", "value_raw": "$89.4", "unit_scale_multiplier": "1000000"},
            {"observation_id": "O4", "metric_category": "tvpi", "value_raw": "1.05x", "unit_scale_multiplier": ""},
        ]
        precision = printed_precision_from_observations([period], observations)
        rows = {
            row["rule_id"]: row
            for row in run_quality_checks([period], [], [self.master], printed_precision=precision)
        }
        self.assertEqual(rows["R05_TVPI_RECOMPUTE"]["status"], "PASS")
        self.assertIn("widened", rows["R05_TVPI_RECOMPUTE"]["notes"])
        strict = {row["rule_id"]: row for row in run_quality_checks([period], [], [self.master])}
        self.assertEqual(strict["R05_TVPI_RECOMPUTE"]["status"], "FAIL")

    def test_generated_periods_keep_the_configured_tolerance(self) -> None:
        rows = {row["rule_id"]: row for row in run_quality_checks([self.period], self.cashflows, [self.master], printed_precision={})}
        self.assertEqual(rows["R02_TVPI_COMPONENTS"]["tolerance"], "0.005")
        self.assertNotIn("widened", rows["R02_TVPI_COMPONENTS"]["notes"])

    def test_printed_irr_is_not_compared_with_generated_flows(self) -> None:
        period = dict(self.period)
        period.update({"provenance_type": "EXTRACTED", "source_document_id": "SRC001"})
        generated = [dict(row, provenance_type="SYNTHETIC") for row in self.cashflows]
        rows = {row["rule_id"]: row for row in run_quality_checks([period], generated, [self.master])}
        self.assertEqual(rows["R08_XIRR_RECOMPUTE"]["status"], "SKIP")
        self.assertIn("different histories", rows["R08_XIRR_RECOMPUTE"]["notes"])
        printed = [dict(row, provenance_type="EXTRACTED") for row in self.cashflows]
        rows = {row["rule_id"]: row for row in run_quality_checks([period], printed, [self.master])}
        self.assertEqual(rows["R08_XIRR_RECOMPUTE"]["status"], "PASS")

    def test_recallable_distributions_reconcile_unfunded_commitment(self) -> None:
        period = dict(self.period)
        period["recallable_distributions_itd"] = "5"
        period["unfunded_commitment"] = "15"
        rows = run_quality_checks([period], self.cashflows, [self.master])
        commitment_check = next(
            row for row in rows if row["rule_id"] == "R06_COMMITMENT_RECONCILIATION"
        )
        self.assertEqual(commitment_check["status"], "PASS")

    def test_output_is_byte_deterministic_and_has_the_fixed_header(self) -> None:
        rows = run_quality_checks([self.period], self.cashflows, [self.master], run_id="STABLE")
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory) / "first.csv"
            second = Path(temporary_directory) / "second.csv"
            write_results(first, rows)
            write_results(second, rows)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first.read_text(encoding="utf-8").splitlines()[0], ",".join(RESULT_COLUMNS))

    def test_duplicate_and_currency_defects_are_detected(self) -> None:
        cashflows = [dict(row) for row in self.cashflows]
        for index, row in enumerate(cashflows, 1):
            row.update(
                {
                    "cashflow_id": f"CF_{index}",
                    "currency": "USD",
                    "base_currency": "USD",
                    "amount_base_currency": row["amount"],
                    "fx_rate": "1",
                }
            )
        duplicate = dict(cashflows[0])
        duplicate["cashflow_id"] = "CF_DUP"
        cashflows.append(duplicate)
        cashflows[1]["currency"] = "EUR"
        rows = run_quality_checks([self.period], cashflows, [self.master])
        failed = {row["rule_id"] for row in rows if row["status"] == "FAIL"}
        self.assertIn("R13_DUPLICATE_CASHFLOW", failed)
        self.assertIn("R14_CURRENCY_CONSISTENCY", failed)

    def test_cashflow_sign_defect_is_detected(self) -> None:
        cashflows = [dict(row) for row in self.cashflows]
        cashflows[0]["amount"] = "40"
        cashflows[0]["amount_base_currency"] = "40"
        rows = run_quality_checks([self.period], cashflows, [self.master])
        failed = {row["rule_id"] for row in rows if row["status"] == "FAIL"}
        self.assertIn("R15_CASHFLOW_SIGN_CONVENTION", failed)

    def test_cashflow_checks_preserve_lp_and_share_class_grain(self) -> None:
        first_flows = [dict(row) for row in self.cashflows]
        for row in first_flows:
            row.update(
                {
                    "lp_id": "LP_001",
                    "lp_name": "Test LP One",
                    "share_class_name": "Class A",
                }
            )
        second_flows = [dict(row) for row in self.cashflows]
        shifted_dates = (
            "2022-01-15",
            "2022-12-15",
            "2023-09-15",
            "2024-04-15",
            "2024-10-15",
        )
        for index, (row, shifted_date) in enumerate(zip(second_flows, shifted_dates), 1):
            row.update(
                {
                    "cashflow_id": f"CF_LP2_{index}",
                    "lp_id": "LP_002",
                    "lp_name": "Test LP Two",
                    "share_class_name": "Class B",
                    "cashflow_date": shifted_date,
                }
            )

        first_period = dict(self.period)
        first_period.update(
            {
                "fund_period_id": "FP_LP_001",
                "lp_id": "LP_001",
                "lp_name": "Test LP One",
                "share_class_name": "Class A",
                "reported_irr": str(
                    xirr(
                        [
                            (date.fromisoformat(row["cashflow_date"]), float(row["amount"]))
                            for row in first_flows
                        ]
                        + [(date(2024, 12, 31), 90.0)]
                    )
                ),
            }
        )
        second_period = dict(self.period)
        second_period.update(
            {
                "fund_period_id": "FP_LP_002",
                "lp_id": "LP_002",
                "lp_name": "Test LP Two",
                "share_class_name": "Class B",
                "reported_irr": str(
                    xirr(
                        [
                            (date.fromisoformat(row["cashflow_date"]), float(row["amount"]))
                            for row in second_flows
                        ]
                        + [(date(2024, 12, 31), 90.0)]
                    )
                ),
            }
        )

        rows = run_quality_checks(
            [first_period, second_period],
            first_flows + second_flows,
            [self.master],
        )
        xirr_rows = [row for row in rows if row["rule_id"] == "R08_XIRR_RECOMPUTE"]
        self.assertEqual([row["status"] for row in xirr_rows], ["PASS", "PASS"])


if __name__ == "__main__":
    unittest.main()
