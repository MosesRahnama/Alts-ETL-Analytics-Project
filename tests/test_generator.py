"""Integration tests for generation gates, clean math, and injected defects."""

from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.generate.generate_synthetic_funds import (
    ALLOWED_DEFECTS,
    BENCHMARK_SERIES,
    PORTFOLIO_DEFINITIONS,
    STRATEGY_BENCHMARK,
    GenerationConfig,
    GenerationError,
    assumed_parameter_rows,
    generate_clean_universe,
    inject_defects,
    select_and_validate_parameters,
    validate_inventory,
)
from src.quality.run_fund_checks import run_quality_checks


class GeneratorIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parameter_set_id = "SYNTH_TEST_V1"
        self.parameters = assumed_parameter_rows(self.parameter_set_id)
        self.strategies = tuple(sorted({row["strategy"] for row in self.parameters}))
        self.config = GenerationConfig(
            seed=20260802,
            target_fund_count=12,
            minimum_fund_count=1,
            base_currency="USD",
            as_of_date=date(2026, 6, 30),
            fund_id_prefix="FUND_SYNTH_",
            defects_enabled=True,
            defect_seed_offset=101,
            defect_target_rate=1.0,
            allowed_defects=ALLOWED_DEFECTS,
        )

    def _single_strategy_parameters(
        self,
        source_document_id: str,
        source_page: str,
    ) -> list[dict[str, str]]:
        rows = [
            dict(row)
            for row in self.parameters
            if row["strategy"] == "buyout"
        ]
        extracted = next(
            row for row in rows if row["parameter_name"] == "management_fee_rate"
        )
        extracted.update(
            {
                "provenance_type": "EXTRACTED",
                "source_document_id": source_document_id,
                "source_page": source_page,
                "source_anchor": "Fees!B12" if not source_page else "fee table row 4",
                "input_record_ids": "TERM_SOURCE_001",
                "assumption_basis": "",
                "adjudication_status": "ADJUDICATED",
            }
        )
        return rows

    def test_extracted_xlsx_and_zip_parameters_use_native_anchor_without_page(self) -> None:
        for source_format in ("xlsx", "zip"):
            with self.subTest(source_format=source_format):
                source_id = f"SRC_{source_format.upper()}"
                selected_set, selected, strategies = select_and_validate_parameters(
                    self._single_strategy_parameters(source_id, ""),
                    self.parameter_set_id,
                    False,
                    [{"file_id": source_id, "file_ext": source_format}],
                )
                self.assertEqual(selected_set, self.parameter_set_id)
                self.assertEqual(strategies, ("buyout",))
                self.assertTrue(selected)
                with self.assertRaisesRegex(GenerationError, "leave source_page empty"):
                    select_and_validate_parameters(
                        self._single_strategy_parameters(source_id, "4"),
                        self.parameter_set_id,
                        False,
                        [{"file_id": source_id, "file_ext": source_format}],
                    )

    def test_extracted_pdf_parameter_requires_page(self) -> None:
        source_rows = [{"file_id": "SRC_PDF", "file_ext": "pdf"}]
        with self.assertRaisesRegex(GenerationError, "PDF parameter.*source_page"):
            select_and_validate_parameters(
                self._single_strategy_parameters("SRC_PDF", ""),
                self.parameter_set_id,
                False,
                source_rows,
            )
        selected_set, selected, strategies = select_and_validate_parameters(
            self._single_strategy_parameters("SRC_PDF", "12"),
            self.parameter_set_id,
            False,
            source_rows,
        )
        self.assertEqual(selected_set, self.parameter_set_id)
        self.assertEqual(strategies, ("buyout",))
        self.assertTrue(selected)

    def test_extracted_parameter_requires_a_fund_model_input_id(self) -> None:
        rows = self._single_strategy_parameters("SRC_PDF", "12")
        extracted = next(
            row for row in rows if row["parameter_name"] == "management_fee_rate"
        )
        extracted["input_record_ids"] = ""
        with self.assertRaisesRegex(GenerationError, "input_record_ids"):
            select_and_validate_parameters(
                rows,
                self.parameter_set_id,
                False,
                [{"file_id": "SRC_PDF", "file_ext": "pdf"}],
            )

    def test_clean_universe_has_no_quality_failures(self) -> None:
        tables = generate_clean_universe(
            self.config,
            self.parameter_set_id,
            self.parameters,
            self.strategies,
            12,
            self.config.seed,
        )
        results = run_quality_checks(
            tables["fund_periods.csv"],
            tables["fund_cashflows.csv"],
            tables["fund_master.csv"],
        )
        failures = [row for row in results if row["status"] == "FAIL"]
        self.assertEqual(failures, [])
        holding_totals: dict[tuple[str, str], float] = {}
        for row in tables["fund_holdings.csv"]:
            key = (row["fund_id"], row["as_of_date"])
            holding_totals[key] = holding_totals.get(key, 0.0) + float(row["fair_value"])
        fund_total_periods = [
            row for row in tables["fund_periods.csv"] if row["perspective"] == "fund_total"
        ]
        self.assertTrue(fund_total_periods)
        for period in fund_total_periods:
            key = (period["fund_id"], period["as_of_date"])
            self.assertIn(key, holding_totals)
            self.assertAlmostEqual(holding_totals[key], float(period["nav"]), places=2)

        expected_metric_ids = {
            "cap.commitment",
            "cap.contributions_itd",
            "cap.distributions_itd",
            "cap.unfunded_commitment",
            "val.nav",
            "perf.dpi",
            "perf.rvpi",
            "perf.tvpi",
            "perf.irr",
            "attr.fund_size",
        }
        observations = tables["fund_observations.csv"]
        self.assertEqual({row["metric_id"] for row in observations}, expected_metric_ids)
        net_metrics = {"perf.dpi", "perf.rvpi", "perf.tvpi", "perf.irr"}
        for row in observations:
            self.assertEqual(row["fee_basis"], "net" if row["metric_id"] in net_metrics else "")
            self.assertTrue({"lp_id", "lp_name", "share_class_name"}.issubset(row))
        for table_name in ("fund_periods.csv", "fund_cashflows.csv"):
            for row in tables[table_name]:
                self.assertTrue({"lp_id", "lp_name", "share_class_name"}.issubset(row))

    def test_every_fund_reports_a_dated_quarterly_history(self) -> None:
        tables = generate_clean_universe(
            self.config,
            self.parameter_set_id,
            self.parameters,
            self.strategies,
            12,
            self.config.seed,
        )
        by_fund: dict[str, list[dict[str, str]]] = {}
        for row in tables["fund_periods.csv"]:
            if row["perspective"] == "fund_total":
                by_fund.setdefault(row["fund_id"], []).append(row)
        self.assertEqual(len(by_fund), 12)
        for fund_id, periods in by_fund.items():
            dates = [row["as_of_date"] for row in periods]
            self.assertEqual(dates, sorted(dates), fund_id)
            self.assertEqual(len(dates), len(set(dates)), fund_id)
            self.assertGreater(len(dates), 1, fund_id)
            paid_in = [float(row["paid_in_capital_itd"]) for row in periods]
            distributed = [float(row["distributions_itd"]) for row in periods]
            self.assertEqual(paid_in, sorted(paid_in), fund_id)
            self.assertEqual(distributed, sorted(distributed), fund_id)
            self.assertGreater(paid_in[0], 0.0, fund_id)
            for row in periods:
                self.assertGreater(float(row["nav"]), 0.0, fund_id)
            beginning = [float(row["beginning_nav"]) for row in periods]
            self.assertEqual(beginning[0], 0.0, fund_id)
            for index in range(1, len(periods)):
                self.assertAlmostEqual(
                    beginning[index], float(periods[index - 1]["nav"]), places=2
                )

    def test_reported_positions_carry_their_own_reconciled_history(self) -> None:
        tables = generate_clean_universe(
            self.config,
            self.parameter_set_id,
            self.parameters,
            self.strategies,
            20,
            self.config.seed,
        )
        perspectives = {row["perspective"] for row in tables["fund_periods.csv"]}
        self.assertIn("lp_position", perspectives)
        position_ids = {
            row["fund_period_id"]
            for row in tables["fund_periods.csv"]
            if row["perspective"] != "fund_total"
        }
        self.assertEqual(
            len(position_ids),
            sum(
                1
                for row in tables["fund_periods.csv"]
                if row["perspective"] != "fund_total"
            ),
        )
        for row in tables["fund_periods.csv"]:
            if row["perspective"] == "lp_position":
                self.assertTrue(row["lp_id"])
                self.assertGreaterEqual(
                    float(row["fund_size"]), float(row["commitment"])
                )
            if row["perspective"] == "share_class":
                self.assertTrue(row["share_class_name"])

    def test_benchmark_series_cover_every_strategy_and_every_period(self) -> None:
        tables = generate_clean_universe(
            self.config,
            self.parameter_set_id,
            self.parameters,
            self.strategies,
            12,
            self.config.seed,
        )
        emitted = {row["benchmark_id"] for row in tables["benchmark_returns.csv"]}
        self.assertEqual(emitted, {item[0] for item in BENCHMARK_SERIES})
        for strategy in self.strategies:
            self.assertIn(STRATEGY_BENCHMARK[strategy], emitted)
        earliest_return = min(row["return_date"] for row in tables["benchmark_returns.csv"])
        earliest_cashflow = min(
            row["cashflow_date"] for row in tables["fund_cashflows.csv"]
        )
        self.assertLess(earliest_return, earliest_cashflow)
        portfolios = {row["portfolio_id"] for row in tables["portfolio_allocations.csv"]}
        self.assertEqual(portfolios, {item[0] for item in PORTFOLIO_DEFINITIONS})
        for portfolio_id in portfolios:
            weight = sum(
                float(row["target_weight"])
                for row in tables["portfolio_allocations.csv"]
                if row["portfolio_id"] == portfolio_id
            )
            self.assertAlmostEqual(weight, 1.0, places=5)

    def test_every_configured_defect_has_its_expected_quality_failure(self) -> None:
        tables = generate_clean_universe(
            self.config,
            self.parameter_set_id,
            self.parameters,
            self.strategies,
            12,
            self.config.seed,
        )
        inject_defects(tables, self.config, self.parameter_set_id, self.config.seed)
        results = run_quality_checks(
            tables["fund_periods.csv"],
            tables["fund_cashflows.csv"],
            tables["fund_master.csv"],
        )
        failed = {(row["fund_id"], row["rule_id"]) for row in results if row["status"] == "FAIL"}
        defects = tables["defect_injections.csv"]
        self.assertEqual({row["defect_type"] for row in defects}, set(ALLOWED_DEFECTS))
        missed = [
            row
            for row in defects
            if (row["fund_id"], row["expected_rule_id"]) not in failed
        ]
        self.assertEqual(missed, [])

    def test_production_inventory_gate_rejects_pending_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.csv"
            inventory = root / "inventory.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["file_id"], lineterminator="\n")
                writer.writeheader()
                writer.writerow({"file_id": "SRC001"})
            with inventory.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "file_id",
                        "agent_a_status",
                        "agent_b_status",
                        "adjudication_status",
                        "extraction_status",
                    ],
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "file_id": "SRC001",
                        "agent_a_status": "PENDING_DOUBLE_REVIEW",
                        "agent_b_status": "PENDING_DOUBLE_REVIEW",
                        "adjudication_status": "PENDING_DOUBLE_REVIEW",
                        "extraction_status": "NOT_STARTED",
                    }
                )
            with self.assertRaisesRegex(GenerationError, "generation is locked"):
                validate_inventory(inventory, source)


if __name__ == "__main__":
    unittest.main()
