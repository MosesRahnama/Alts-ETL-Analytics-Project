from __future__ import annotations

import csv
import unittest
from pathlib import Path

from src.load import promote_extracted_to_fund_level as promote
from src.pipeline import build_integrated_universe as integrated


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class IntegratedUniverseTests(unittest.TestCase):
    def test_name_hint_is_dropped_when_printed_strategy_disagrees(self) -> None:
        self.assertEqual(
            integrated._accepted_name_hint(
                "Insight Venture Partners XI, L.P.", "private_equity"
            ),
            ("", ""),
        )
        self.assertEqual(integrated._name_hint("Adventure Fund I, L.P."), ("", ""))

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

    def test_canonical_grouping_lineage_separates_print_from_fallback(self) -> None:
        canonical = [
            row
            for row in rows(PROJECT_ROOT / "data" / "integrated" / "cell-lineage.csv")
            if row.get("target_table") == "fund_master"
            and row.get("target_field") in {"canonical_asset_class", "canonical_strategy"}
        ]
        self.assertTrue(canonical)
        self.assertIn("DERIVED", {row["provenance_type"] for row in canonical})
        self.assertIn("IMPUTED", {row["provenance_type"] for row in canonical})
        for row in canonical:
            if row["provenance_type"] == "DERIVED":
                self.assertIn(row["source_table"], {"attribute_changes", "fund_periods"})
                self.assertTrue(row["source_record_id"])
                self.assertTrue(row["source_document_id"])
                self.assertEqual(row["formula_id"], "CONTEXT_GROUPING_MAP_V1")
                self.assertFalse(row["synthetic_parameter_set_id"])
            else:
                self.assertEqual(row["provenance_type"], "IMPUTED")
                self.assertFalse(row["source_document_id"])
                self.assertFalse(row["formula_id"])
                self.assertEqual(
                    row["imputation_method"], "CONFIGURED_STRATEGY_FALLBACK_V1"
                )
                self.assertTrue(row["synthetic_parameter_set_id"])


class CarriedCanonicalLineageTests(unittest.TestCase):
    """A canonical cell promotion filled states where it was read from.

    The fill in `_complete_master` skips a cell that already carries a value, so
    the 514 funds whose canonical grouping comes from a printed strategy reached
    the published master with no lineage row at all, and the only canonical rows
    in the ledger were the 420 the configured fallback produced."""

    SOURCES = {
        "FUND_A": {
            "canonical_asset_class": {
                "value": "private_equity",
                "source_table": "attribute_changes",
                "source_record_id": "AC_FIXTURE01",
                "source_document_id": "SRC001",
                "source_anchor": "page 5; observation OBS_1",
            }
        }
    }

    def test_a_fund_with_a_printed_strategy_cites_the_change_row(self) -> None:
        rows = integrated._carried_canonical_lineage(
            "fund_master", "FUND_A", {"canonical_asset_class": "private_equity"}, self.SOURCES
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provenance_type"], "DERIVED")
        self.assertEqual(rows[0]["source_table"], "attribute_changes")
        self.assertEqual(rows[0]["source_record_id"], "AC_FIXTURE01")
        self.assertEqual(rows[0]["source_document_id"], "SRC001")
        self.assertEqual(rows[0]["formula_id"], "CONTEXT_GROUPING_MAP_V1")
        self.assertFalse(rows[0]["synthetic_parameter_set_id"])
        self.assertFalse(rows[0]["imputation_method"])

    def test_a_fund_with_no_printed_strategy_carries_nothing_and_stays_imputed(self) -> None:
        """A fund whose master cell is blank leaves this reader with nothing to
        carry; the fill below it writes the row, and it reads IMPUTED."""

        self.assertEqual(
            integrated._carried_canonical_lineage(
                "fund_master", "FUND_B", {"canonical_asset_class": ""}, self.SOURCES
            ),
            [],
        )
        self.assertEqual(
            integrated.matrices.resolve(
                integrated.MASTER_PROVENANCE, "canonical_imputation_method"
            ),
            "CONFIGURED_STRATEGY_FALLBACK_V1",
        )

    def test_a_canonical_cell_with_no_change_row_is_refused_by_name(self) -> None:
        with self.assertRaises(integrated.IntegrationError) as raised:
            integrated._carried_canonical_lineage(
                "fund_master", "FUND_C", {"canonical_strategy": "buyout"}, self.SOURCES
            )
        self.assertIn("FUND_C", str(raised.exception))
        self.assertIn("canonical_strategy", str(raised.exception))

    def test_a_change_row_naming_another_value_is_refused(self) -> None:
        with self.assertRaises(integrated.IntegrationError):
            integrated._carried_canonical_lineage(
                "fund_master", "FUND_A", {"canonical_asset_class": "real_estate"}, self.SOURCES
            )


class PromotedCanonicalChangeTests(unittest.TestCase):
    """Promotion writes the audit row the lineage above cites."""

    def test_a_printed_strategy_yields_a_derived_change_row(self) -> None:
        changes = promote.master_canonical_changes(
            [{"fund_id": "FUND_A", "strategy": "Buyout", "canonical_asset_class": "private_equity"}],
            {
                "FUND_A": {
                    "strategy": {
                        "source_observation_id": "OBS_1",
                        "source_document_id": "SRC001",
                        "source_page": "5",
                        "source_table": "Schedule of Investments",
                        "source_quote": "Buyout",
                        "source_printed_value": "Buyout",
                    }
                }
            },
        )
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["change_type"], "DERIVED")
        self.assertEqual(changes[0]["field"], "canonical_asset_class")
        self.assertEqual(changes[0]["new_value"], "private_equity")
        self.assertEqual(changes[0]["rule_id"], "CONTEXT_GROUPING_MAP:strategy:Buyout")
        self.assertEqual(changes[0]["source_observation_id"], "OBS_1")
        self.assertIn("context-grouping-map.csv", changes[0]["notes"])

    def test_a_fund_with_no_printed_strategy_yields_no_change_row(self) -> None:
        self.assertEqual(
            promote.master_canonical_changes(
                [{"fund_id": "FUND_B", "strategy": "", "canonical_asset_class": ""}], {}
            ),
            [],
        )

    def test_a_canonical_cell_with_no_printed_source_is_refused_by_name(self) -> None:
        with self.assertRaises(ValueError) as raised:
            promote.master_canonical_changes(
                [{"fund_id": "FUND_C", "strategy": "Buyout", "canonical_asset_class": "private_equity"}],
                {},
            )
        self.assertIn("FUND_C", str(raised.exception))


class CompletedPeriodGroupingTests(unittest.TestCase):
    """A completed period states what its printed grouping reads as.

    portfolio_allocations and every completed fund_periods row published the
    printed word alone, so the analytics grouped on a vocabulary with no
    taxonomy beside it."""

    def test_a_printed_strategy_is_read_under_the_strategy_context(self) -> None:
        reading = integrated._period_grouping({"strategy": "Secondary Investments"})
        self.assertEqual(reading["canonical_asset_class"], "private_equity")
        self.assertEqual(reading["canonical_strategy"], "secondaries")

    def test_a_classifier_word_is_read_when_the_strategy_context_has_no_row(self) -> None:
        reading = integrated._period_grouping({"strategy": "Diversified Alternatives"})
        self.assertEqual(reading["canonical_asset_class"], "multi_asset")
        self.assertEqual(reading["canonical_strategy"], "")

    def test_a_printed_industry_is_read_under_the_sector_context(self) -> None:
        reading = integrated._period_grouping({"strategy": "", "sector": "Defense"})
        self.assertEqual(reading["canonical_sector"], "Defense")
        self.assertEqual(reading["canonical_asset_class"], "")

    def test_a_word_the_matrix_does_not_carry_is_never_invented(self) -> None:
        reading = integrated._period_grouping({"strategy": "Cryptocurrency"})
        self.assertEqual(set(reading.values()), {""})

    def test_the_completed_period_carries_lineage_for_every_grouping_column(self) -> None:
        for field in ("sector", *integrated.CANONICAL_PERIOD_COLUMNS):
            self.assertIn(field, integrated.TARGET_PERIOD_FIELDS, field)


class CarriedImputationTests(unittest.TestCase):
    """A copy of an imputed value is an imputed value.

    The configured strategy fallback reached 420 completed periods labelled
    SYNTHETIC, so a reader met a strategy no page states beside a word that
    says the completion generated it."""

    def _lineage(self, period_value: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        # What _complete_master records for a fund with no printed strategy: the
        # configured fallback, and the class read off that fallback, both imputed.
        lineage = [
            integrated._lineage_row(
                target_table="fund_master",
                target_record_id="FUND_A",
                target_field=field,
                target_value=value,
                provenance_type="IMPUTED",
                source_table="",
                source_record_id="",
                imputation_method="CONFIGURED_STRATEGY_FALLBACK_V1",
                precedence="EXTRACTED_THEN_DERIVED_THEN_IMPUTED",
                notes="",
            )
            for field, value in (
                ("strategy", "Diversified Alternatives"),
                ("canonical_asset_class", "multi_asset"),
            )
        ]
        gaps: list[dict[str, str]] = []
        integrated._record_target_lineage(
            {"parameter_set_id": "TEST_SET"},
            [
                {
                    "fund_period_id": "FPRINT_A",
                    "fund_id": "FUND_A",
                    "strategy": period_value,
                    **integrated._period_grouping({"strategy": period_value}),
                    "source_anchor": "data/integrated/cell-lineage.csv",
                    "formula_id": "COMPLETION_V1",
                }
            ],
            [],
            lineage,
            gaps,
            {},
        )
        return lineage, gaps

    def test_a_completed_cell_repeating_an_imputed_master_cell_reads_imputed(self) -> None:
        lineage, gaps = self._lineage("Diversified Alternatives")
        carried = {
            row["target_field"]: row
            for row in lineage
            if row["target_table"] == "fund_periods"
        }
        strategy = carried["strategy"]
        self.assertEqual(strategy["provenance_type"], "IMPUTED")
        self.assertEqual(
            strategy["imputation_method"], "CONFIGURED_STRATEGY_FALLBACK_V1"
        )
        self.assertEqual(strategy["source_table"], "fund_master")
        self.assertFalse(strategy["formula_id"])
        # The class read off that fallback is imputed on fund_master, so the
        # copy of it says so too; a reader never meets multi_asset beside a word
        # that claims the completion computed it.
        self.assertEqual(carried["canonical_asset_class"]["provenance_type"], "IMPUTED")
        self.assertEqual(
            {row["field_name"]: row["resolution_type"] for row in gaps},
            {"strategy": "IMPUTED", "canonical_asset_class": "IMPUTED"},
        )

    def test_a_completed_cell_the_master_did_not_impute_stays_synthetic(self) -> None:
        lineage, _gaps = self._lineage("Secondary Investments")
        carried = [row for row in lineage if row["target_table"] == "fund_periods"]
        self.assertEqual(carried[0]["provenance_type"], "SYNTHETIC")
        self.assertEqual(
            carried[0]["imputation_method"], "DETERMINISTIC_SAME_FUND_COMPLETION_V1"
        )

    def test_the_carried_label_is_read_from_the_matrix(self) -> None:
        self.assertEqual(
            integrated.matrices.resolve(
                integrated.MASTER_PROVENANCE, "carried_imputed_value"
            ),
            "IMPUTED",
        )
        self.assertEqual(
            integrated.matrices.resolve(
                integrated.PROVENANCE_TABLES, "carried_imputed_value"
            ),
            "fund_master",
        )

    def test_a_printed_grouping_with_no_reading_is_an_open_gap(self) -> None:
        _lineage, gaps = self._lineage("Cryptocurrency")
        unresolved = [row for row in gaps if row["resolution_type"] == "UNRESOLVED"]
        self.assertEqual([row["field_name"] for row in unresolved], ["canonical_strategy"])
        self.assertEqual(unresolved[0]["resolution_value"], "Cryptocurrency")


class BenchmarkPromotionTests(unittest.TestCase):
    """Every benchmark PME can select has a promoted series behind it.

    Stage 100 promoted one series and stage 120 selected from a map of
    seventeen, which is why every published PME row carried the same index."""

    def test_the_stage_promotes_every_benchmark_the_map_names(self) -> None:
        cfg = integrated.config()
        promoted = integrated.benchmark_ids_in_use(cfg)
        self.assertIn(str(cfg["benchmark_id"]), promoted)
        for row in integrated.matrices.load("strategy-benchmark-map"):
            self.assertIn(f"BMK_ETF_{row['output_value']}", promoted)

    def test_every_promoted_benchmark_has_a_candidate_series(self) -> None:
        cfg = integrated.config()
        _header, candidates = integrated.read_csv(
            integrated.PUBLIC_MARKET_DIR / "benchmark_return_candidates.csv"
        )
        available = {row["benchmark_id"] for row in candidates}
        self.assertEqual(set(integrated.benchmark_ids_in_use(cfg)) - available, set())


if __name__ == "__main__":
    unittest.main()
