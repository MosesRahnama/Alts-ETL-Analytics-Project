"""Tests for deterministic fund metrics, PME, and bounded allocations."""

from __future__ import annotations

import csv
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.analytics import (
    ANALYSIS_RESULT_COLUMNS,
    PORTFOLIO_ALLOCATION_COLUMNS,
    AnalyticsError,
    bounded_equal_weights,
    build_portfolio_allocations,
    calculate_fund_metrics,
    calculate_pme_results,
)
from src.analytics import run_extracted_analytics as extracted
from src.analytics.run_round04_analytics import (
    FUND_METRIC_COLUMNS,
    GROUPING_COLUMNS,
    PME_RESULT_COLUMNS,
    QUALITY_RESULT_COLUMNS,
    benchmark_for_fund,
    funds_with_one_basis,
    grouping_reading,
    stated_qualifiers,
)
from src.common import matrices
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


class FeeBasisTests(unittest.TestCase):
    """A measured rate names the basis it was measured on.

    An unstated basis is measurable and says so; a fund whose own series states
    net on one period and gross on another is two series, and a measure built
    across both compares two different things."""

    def test_an_unstated_basis_is_measurable_and_labelled(self) -> None:
        self.assertEqual(extracted.stated_basis(period("FUND_1", "P1")), "unstated")
        self.assertEqual(
            extracted.stated_basis(dict(period("FUND_1", "P1"), reported_irr_fee_basis="net")),
            "net",
        )

    def test_a_fund_mixing_net_and_gross_is_refused_and_counted(self) -> None:
        periods = [
            dict(period("FUND_1", "P1"), reported_irr_fee_basis="net"),
            dict(period("FUND_1", "P2"), reported_irr_fee_basis="gross"),
            dict(period("FUND_2", "P3"), reported_irr_fee_basis="net"),
            period("FUND_3", "P4"),
        ]
        kept, refused = extracted.funds_with_one_basis(periods)
        self.assertNotIn("FUND_1", kept)
        self.assertIn("FUND_2", kept)
        self.assertIn("FUND_3", kept)
        self.assertEqual(refused, 1)

    def test_the_policy_is_read_from_the_matrix(self) -> None:
        with patch.object(extracted.matrices, "resolve", return_value="something_else"):
            with self.assertRaises(extracted.matrices.MatrixError):
                extracted.stated_basis(period("FUND_1", "P1"))

    def test_every_extracted_metric_row_names_its_basis_and_method(self) -> None:
        """The written result carries the qualifiers of the period behind it,
        so a reader never meets a measured rate of unknown meaning."""

        measured = [{
            "analysis_result_id": "AR1",
            "entity_id": "FUND_1",
            "as_of_date": "2021-09-30",
            "metric_id": "tvpi",
            "value_numeric": "1.3",
            "input_record_ids": "P1",
        }]
        with TemporaryDirectory() as raw:
            root = Path(raw)
            _write(root / "fund_periods.csv", [
                dict(
                    period("FUND_1", "P1", provenance_type="EXTRACTED"),
                    reported_irr_fee_basis="net",
                    reported_irr_method="modified_dietz",
                )
            ])
            _write(root / "fund_cashflows.csv", [
                cashflow("CF1", "FUND_1", "2020-01-01", "-100"),
                cashflow("CF2", "FUND_1", "2021-09-30", "130"),
            ])
            _write(root / "quality_results.csv", [])
            with patch.object(extracted, "calculate_fund_metrics", return_value=measured):
                extracted.run(root, quality_path=root / "quality_results.csv")
            written = _read(root / "fund_metrics.csv")
        self.assertTrue(written)
        self.assertEqual({row["input_fee_basis"] for row in written}, {"net"})
        self.assertEqual({row["input_method"] for row in written}, {"modified_dietz"})

    def test_a_result_built_across_two_bases_is_labelled_unstated(self) -> None:
        """A measure whose inputs disagree names no single basis, and saying
        `net` there would be the mislabelling this column exists to stop."""

        measured = [{
            "analysis_result_id": "AR1",
            "entity_id": "FUND_1",
            "as_of_date": "2021-09-30",
            "metric_id": "tvpi",
            "value_numeric": "1.3",
            "input_record_ids": "P1;P2",
        }]
        with TemporaryDirectory() as raw:
            root = Path(raw)
            _write(root / "fund_periods.csv", [
                dict(period("FUND_1", "P1", provenance_type="EXTRACTED"), reported_irr_fee_basis="net"),
                dict(
                    period("FUND_2", "P2", as_of_date="2021-06-30", provenance_type="EXTRACTED"),
                    reported_irr_fee_basis="gross",
                ),
            ])
            _write(root / "fund_cashflows.csv", [
                cashflow("CF1", "FUND_1", "2020-01-01", "-100"),
                cashflow("CF2", "FUND_1", "2021-09-30", "130"),
            ])
            _write(root / "quality_results.csv", [])
            with patch.object(extracted, "calculate_fund_metrics", return_value=measured):
                extracted.run(root, quality_path=root / "quality_results.csv")
            written = _read(root / "fund_metrics.csv")
        self.assertEqual(written[0]["input_fee_basis"], "unstated")


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    columns = list(rows[0]) if rows else ["fund_period_id"]
    if path.name == "quality_results.csv":
        columns = list(QUALITY_RESULT_COLUMNS)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in columns})


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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

    def test_pme_refuses_an_as_of_date_past_the_end_of_the_series(self) -> None:
        """The terminal index level must come from a date the series covers.

        The join is backward-only, so a period dated past the last observation
        silently takes the last level the series holds. One run priced 1,868
        PME rows at a period end 25 days after the SPY proxy stopped, and no
        output said so.
        """
        daily = [
            dict(benchmark(f"BM_{day:03d}", f"2021-06-{day:02d}", "0.001"),
                 periodicity="daily")
            for day in range(1, 29)
        ]
        with self.assertRaisesRegex(AnalyticsError, "days before the as-of date"):
            calculate_pme_results(
                [period("FUND_A", "PERIOD_A", as_of_date="2021-09-30")],
                [cashflow("CF_A_1", "FUND_A", "2021-06-10", "-100")],
                daily,
                quality_rows("PERIOD_A", "FUND_A"),
                benchmark_id="BM",
                periodicity="daily",
            )

    def test_pme_accepts_a_weekend_gap_at_the_end_of_a_daily_series(self) -> None:
        """A daily series prints no observation on a Sunday, and that is fine."""
        daily = [
            dict(benchmark(f"BM_{day:03d}", f"2021-06-{day:02d}", "0.001"),
                 periodicity="daily")
            for day in range(1, 29)
        ]
        rows = calculate_pme_results(
            [period("FUND_A", "PERIOD_A", as_of_date="2021-06-30")],
            [cashflow("CF_A_1", "FUND_A", "2021-06-10", "-100")],
            daily,
            quality_rows("PERIOD_A", "FUND_A"),
            benchmark_id="BM",
            periodicity="daily",
        )
        self.assertTrue(rows)

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

    def test_output_constants_only_ever_extend_the_published_header(self) -> None:
        """The published file's header is the head of the constant that writes it.

        The three tables are rewritten by the release, so a column added here
        reaches the file on the next run. Requiring equality would fail every
        change between the edit and the run; requiring the published header to
        be the head of the constant catches a renamed or reordered column, which
        is the drift that would break the database load. The DDL comparison in
        tests/test_database_parity.py holds the other end."""

        for filename, columns in (
            ("fund_metrics.csv", FUND_METRIC_COLUMNS),
            ("pme_results.csv", PME_RESULT_COLUMNS),
            ("portfolio_allocations.csv", PORTFOLIO_ALLOCATION_COLUMNS),
        ):
            with (PROJECT_ROOT / "data" / "csv" / filename).open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                published = tuple(next(csv.reader(handle)))
            self.assertEqual(published, columns[: len(published)], filename)

    def test_the_extracted_lane_writes_the_same_metric_header(self) -> None:
        """One fund_metrics header, whichever stage wrote the file."""

        self.assertEqual(
            ANALYSIS_RESULT_COLUMNS + ("input_fee_basis", "input_method"),
            FUND_METRIC_COLUMNS,
        )


class GroupingReadingTests(unittest.TestCase):
    """A published grouping states what its printed word reads as.

    Grouping on a printed word alone gives the analytics a key nothing else
    joins on, which is what put `Secondary Investments` on 934 allocation rows
    with no taxonomy column beside it."""

    def test_an_allocation_carries_the_reading_of_the_strategy_it_prints(self) -> None:
        rows = build_portfolio_allocations(
            [dict(period("FUND_A", "PERIOD_A"), strategy="Secondary Investments")],
            quality_rows("PERIOD_A", "FUND_A"),
            portfolio_id="PORT",
        )
        self.assertEqual(rows[0]["strategy"], "Secondary Investments")
        self.assertEqual(rows[0]["canonical_asset_class"], "private_equity")
        self.assertEqual(rows[0]["canonical_strategy"], "secondaries")

    def test_a_printed_word_the_matrix_does_not_read_stays_blank(self) -> None:
        rows = build_portfolio_allocations(
            [period("FUND_A", "PERIOD_A")],
            quality_rows("PERIOD_A", "FUND_A"),
            portfolio_id="PORT",
        )
        self.assertEqual(rows[0]["strategy"], "buyout")
        for column in GROUPING_COLUMNS:
            self.assertEqual(rows[0][column], "", column)

    def test_the_reading_the_period_already_carries_is_the_one_published(self) -> None:
        """Promotion and completion read the matrix once; this stage carries it."""

        carried = grouping_reading(
            dict(
                period("FUND_A", "PERIOD_A"),
                strategy="Secondary Investments",
                canonical_asset_class="private_equity",
                canonical_strategy="secondaries",
                sector="Defense",
                canonical_sector="Defense",
            )
        )
        self.assertEqual(carried["canonical_sector"], "Defense")
        self.assertEqual(carried["sector"], "Defense")

    def test_every_grouping_column_is_published(self) -> None:
        for column in GROUPING_COLUMNS:
            self.assertIn(column, PORTFOLIO_ALLOCATION_COLUMNS)


class QualifiedResultTests(unittest.TestCase):
    """A measured multiple or rate names the basis and method behind it."""

    def test_a_period_stating_no_basis_is_measured_and_labelled(self) -> None:
        self.assertEqual(stated_qualifiers(period("FUND_A", "P1")), ("unstated", "unstated"))

    def test_the_money_weighted_qualifiers_are_read_first(self) -> None:
        stated = dict(
            period("FUND_A", "P1"),
            reported_irr_fee_basis="net",
            reported_irr_method="money_weighted",
            period_return_fee_basis="gross",
            period_return_method="time_weighted",
        )
        self.assertEqual(stated_qualifiers(stated), ("net", "money_weighted"))

    def test_a_period_return_qualifier_is_read_when_the_rate_states_none(self) -> None:
        stated = dict(
            period("FUND_A", "P1"),
            period_return_fee_basis="gross",
            period_return_method="time_weighted",
        )
        self.assertEqual(stated_qualifiers(stated), ("gross", "time_weighted"))

    def test_every_metric_row_names_the_basis_of_its_period(self) -> None:
        rows = calculate_fund_metrics(
            [dict(period("FUND_A", "PERIOD_A"), reported_irr_fee_basis="net")],
            [cashflow("CF_A_1", "FUND_A", "2020-06-30", "-100")],
            quality_rows("PERIOD_A", "FUND_A"),
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["input_fee_basis"], "net")
            self.assertEqual(row["input_method"], "unstated")

    def test_a_fund_mixing_net_and_gross_inside_one_series_is_refused(self) -> None:
        periods = [
            dict(period("FUND_A", "P1"), reported_irr_fee_basis="net"),
            dict(period("FUND_A", "P2"), reported_irr_fee_basis="gross"),
            dict(period("FUND_B", "P3"), reported_irr_fee_basis="net"),
            period("FUND_C", "P4"),
        ]
        kept, refused = funds_with_one_basis(periods)
        self.assertNotIn("FUND_A", kept)
        self.assertEqual(kept, {"FUND_B", "FUND_C"})
        self.assertEqual(refused, 1)

    def test_the_refusal_policy_is_read_from_the_matrix(self) -> None:
        with patch.object(matrices, "resolve", return_value="something_else"):
            with self.assertRaises(AnalyticsError):
                funds_with_one_basis([period("FUND_A", "P1")])


class BenchmarkSelectionTests(unittest.TestCase):
    """PME prices a fund against the benchmark its strategy names.

    Every one of 1,868 published PME rows carried BMK_ETF_SPY because the
    strategy map was never read between promotion and analytics."""

    def _benchmarks(self) -> list[dict[str, str]]:
        return [
            dict(benchmark(f"SPY_{year}", f"{year}-12-31", "0.1"), benchmark_id="BMK_ETF_SPY")
            for year in (2018, 2019, 2020, 2021)
        ] + [
            dict(benchmark(f"VTI_{year}", f"{year}-12-31", "0.2"), benchmark_id="BMK_ETF_VTI")
            for year in (2019, 2020, 2021)
        ]

    def test_a_fund_is_priced_against_the_benchmark_its_strategy_names(self) -> None:
        rows = calculate_pme_results(
            [period("FUND_A", "PERIOD_A")],
            [cashflow("CF_A_1", "FUND_A", "2020-06-30", "-100")],
            self._benchmarks(),
            quality_rows("PERIOD_A", "FUND_A"),
            benchmark_id="BMK_ETF_SPY",
            periodicity="annual",
            canonical_strategy_by_fund={"FUND_A": "secondaries"},
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["benchmark_id"], "BMK_ETF_VTI")
            self.assertEqual(row["benchmark_selection"], "mapped")

    def test_a_fund_with_no_canonical_strategy_takes_the_default_and_says_so(self) -> None:
        rows = calculate_pme_results(
            [period("FUND_A", "PERIOD_A")],
            [cashflow("CF_A_1", "FUND_A", "2020-06-30", "-100")],
            self._benchmarks(),
            quality_rows("PERIOD_A", "FUND_A"),
            benchmark_id="BMK_ETF_SPY",
            periodicity="annual",
            canonical_strategy_by_fund={"FUND_A": ""},
        )
        for row in rows:
            self.assertEqual(row["benchmark_id"], "BMK_ETF_SPY")
            self.assertEqual(row["benchmark_selection"], "no_canonical_strategy")

    def test_a_series_starting_after_the_first_cashflow_falls_back(self) -> None:
        """The mapped proxy prices no observation on the fund's first flow."""

        rows = calculate_pme_results(
            [period("FUND_A", "PERIOD_A")],
            [cashflow("CF_A_1", "FUND_A", "2018-12-31", "-100")],
            self._benchmarks(),
            quality_rows("PERIOD_A", "FUND_A"),
            benchmark_id="BMK_ETF_SPY",
            periodicity="annual",
            canonical_strategy_by_fund={"FUND_A": "secondaries"},
        )
        for row in rows:
            self.assertEqual(row["benchmark_id"], "BMK_ETF_SPY")
            self.assertEqual(
                row["benchmark_selection"],
                "mapped_series_starts_after_first_cashflow",
            )

    def test_a_canonical_strategy_the_map_does_not_carry_is_refused(self) -> None:
        with self.assertRaises(matrices.MatrixError):
            benchmark_for_fund("no_such_strategy", None, {}, "BMK_ETF_SPY")

    def test_a_mapped_benchmark_with_no_promoted_series_takes_the_default(self) -> None:
        """A caller running its own benchmark universe still gets a comparison."""

        self.assertEqual(
            benchmark_for_fund("secondaries", None, {}, "BM_SYNTH"),
            ("BM_SYNTH", "mapped_series_absent"),
        )

    def test_every_canonical_strategy_the_grouping_matrix_names_is_mapped(self) -> None:
        named = {
            row["canonical_strategy"]
            for row in matrices.load("context-grouping-map")
            if row["canonical_strategy"]
        }
        mapped = {
            row["input_value"]
            for row in matrices.rows_in("strategy-benchmark-map", "canonical_strategy")
        }
        self.assertEqual(named - mapped, set())


if __name__ == "__main__":
    unittest.main()
