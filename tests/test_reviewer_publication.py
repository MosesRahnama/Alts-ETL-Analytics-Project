from __future__ import annotations

import csv
import unittest
from pathlib import Path

from src.pipeline.build_reviewer_publication import (
    ANALYTICS_SUMMARY_OUTPUT,
    CANONICAL_REVIEW_FIELDS,
    CELL_LINEAGE_OUTPUT,
    GAP_OUTPUT,
    OBSERVATION_OUTPUT,
    PERIOD_GROUPING_FIELDS,
    PERIOD_OUTPUT,
    ReviewerPublicationError,
    require_canonical_columns,
    require_period_grouping_columns,
)
from src.pipeline.publish_review_release import GOVERNED_OUTPUTS
from src.pipeline.transformation_lineage import missing_current_receipts


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


class ReviewerPublicationTests(unittest.TestCase):
    def test_observation_release_is_complete_and_lineage_backed(self) -> None:
        header, rows = read(OBSERVATION_OUTPUT)
        self.assertEqual(len(rows), len(read(PROJECT_ROOT / "data/extracted/tables/fact_observation.csv")[1]))
        self.assertEqual(len({row["observation_id"] for row in rows}), len(rows))
        self.assertIn("lineage_pair_id", header)
        self.assertIn("effective_vintage_year", header)
        self.assertIn("promotion_status", header)
        self.assertIn("quality_status", header)
        self.assertFalse(any(row["lineage_pair_status"] == "UNMATCHED" for row in rows))

    def test_reviewer_files_name_every_column_once(self) -> None:
        """A column the evidence table already carries must not be appended again.

        The five canonical grouping columns moved into `fact_observation` at the
        flatten stage while this writer still appended them, and the duplicate
        header stopped reviewer publication outright. The writer refuses a
        repeated name, so a build reaching disk is the evidence; this reads the
        shipped files so the next column to move upstream fails here first."""

        for path in (
            OBSERVATION_OUTPUT,
            PERIOD_OUTPUT,
            CELL_LINEAGE_OUTPUT,
            GAP_OUTPUT,
            ANALYTICS_SUMMARY_OUTPUT,
        ):
            header, _ = read(path)
            repeated = sorted({name for name in header if header.count(name) > 1})
            self.assertEqual(repeated, [], f"{path.name} repeats {repeated}")

    def test_canonical_grouping_reaches_review_through_the_evidence_table(self) -> None:
        """One computation of the canonical grouping, at the flatten.

        The reviewer file carries these five columns by passing the evidence
        header through. `require_canonical_columns` refuses an evidence table
        that stopped writing them, so this checks both ends of that contract."""

        evidence_header, _ = read(PROJECT_ROOT / "data" / "extracted" / "tables" / "fact_observation.csv")
        review_header, _ = read(OBSERVATION_OUTPUT)
        for field in CANONICAL_REVIEW_FIELDS:
            self.assertIn(field, evidence_header)
            self.assertIn(field, review_header)
        require_canonical_columns(evidence_header)
        with self.assertRaises(ReviewerPublicationError):
            require_canonical_columns([name for name in evidence_header if name != "is_monetary"])

    def test_the_period_file_states_the_grouping_and_what_it_reads_as(self) -> None:
        """A reviewer period states a printed grouping and its reading.

        reviewer-fund-periods.csv carried strategy and sub_strategy and none of
        sector or the four canonical columns, so the reviewer read a word with
        no taxonomy beside it. The columns are inherited from fund_periods
        rather than derived a second time here, and the guard refuses a period
        table that stopped carrying them."""

        require_period_grouping_columns(
            ["fund_period_id", "strategy", *PERIOD_GROUPING_FIELDS]
        )
        for field in PERIOD_GROUPING_FIELDS:
            with self.assertRaises(ReviewerPublicationError):
                require_period_grouping_columns(
                    [name for name in PERIOD_GROUPING_FIELDS if name != field]
                )

    def test_period_release_carries_enrichment_quality_and_analysis(self) -> None:
        header, rows = read(PERIOD_OUTPUT)
        self.assertEqual(len(rows), len(read(PROJECT_ROOT / "data/csv/fund_periods.csv")[1]))
        self.assertEqual(len({row["fund_period_id"] for row in rows}), len(rows))
        for column in (
            "vintage_year_origin",
            "strategy_origin",
            "quality_status",
            "analytics_provenance_type",
            "recomputed_tvpi",
            "recomputed_ks_pme",
            "recomputed_direct_alpha",
            "analysis_benchmark_ids",
            "analysis_result_ids",
            "term_management_fee_rate",
            "term_effective_date",
            "term_effective_end_date",
            "term_id",
            "term_provenance_type",
            "term_synthetic_parameter_set_id",
            "term_clause_id",
            "term_clause_value_text",
            "term_clause_provenance_type",
            "term_clause_synthetic_parameter_set_id",
            "holding_count",
            "holding_fair_value_total",
            "holding_ids",
            "holding_provenance_type",
            "allocation_id",
            "portfolio_provenance_type",
            "portfolio_optimization_run_id",
        ):
            self.assertIn(column, header)
        self.assertTrue(any(row["attribute_change_ids"] for row in rows))
        self.assertEqual(
            {row["analytics_provenance_type"] for row in rows if row["analytics_provenance_type"]},
            {"EXTRACTED", "SYNTHETIC"},
        )
        self.assertTrue(
            all(
                not row["term_id"]
                or row["term_provenance_type"] != "SYNTHETIC"
                or row["term_synthetic_parameter_set_id"]
                for row in rows
            )
        )
        allocation_rows = [row for row in rows if row["allocation_id"]]
        self.assertEqual(len(allocation_rows), len(read(PROJECT_ROOT / "data/csv/portfolio_allocations.csv")[1]))
        self.assertTrue(
            all(
                row["portfolio_provenance_type"] == "DERIVED"
                and row["portfolio_optimization_run_id"]
                for row in allocation_rows
            )
        )
        completed = [
            row
            for row in rows
            if row["synthetic_parameter_set_id"] == "INTEGRATED_COMPLETION_V1"
        ]
        self.assertEqual(len(completed), sum(r["provenance_type"] == "SYNTHETIC" for r in read(PROJECT_ROOT / "data/csv/fund_periods.csv")[1]))
        self.assertTrue(all(row["term_id"] for row in completed))
        self.assertTrue(all(row["term_clause_id"] for row in completed))
        self.assertTrue(
            all(
                row["vintage_year_origin"] == "SYNTHETIC_COMPLETION"
                and row["strategy_origin"] == "SYNTHETIC_COMPLETION"
                for row in completed
            )
        )
        self.assertFalse(
            any("UNRESOLVED" in value for row in rows for value in row.values())
        )

    def test_augmentation_ledgers_are_published_for_review(self) -> None:
        _, lineage = read(CELL_LINEAGE_OUTPUT)
        _, gaps = read(GAP_OUTPUT)
        _, source_lineage = read(PROJECT_ROOT / "data" / "integrated" / "cell-lineage.csv")
        _, source_gaps = read(PROJECT_ROOT / "data" / "integrated" / "gap-ledger.csv")
        self.assertEqual(len(lineage), len(source_lineage))
        self.assertEqual(len(gaps), len(source_gaps))
        # A gap the corpus prints nothing to close stays OPEN and carries no
        # resolution value; what must never appear is a gap claiming one.
        self.assertTrue(all(row["status"] in ("RESOLVED", "OPEN") for row in gaps))
        self.assertEqual(
            [row for row in gaps if (row["status"] == "RESOLVED") != bool(row["resolution_value"])],
            [],
        )

    def test_attribute_changes_resolve_to_sources_and_targets(self) -> None:
        _, changes = read(PROJECT_ROOT / "data" / "extracted" / "audit" / "attribute-changes.csv")
        _, observations = read(PROJECT_ROOT / "data" / "extracted" / "tables" / "fact_observation.csv")
        _, periods = read(PROJECT_ROOT / "data" / "csv" / "fund_periods.csv")
        _, masters = read(PROJECT_ROOT / "data" / "csv" / "fund_master.csv")
        observation_ids = {row["observation_id"] for row in observations}
        targets = {
            "fund_periods": {row["fund_period_id"]: row for row in periods},
            "fund_master": {row["fund_id"]: row for row in masters},
        }
        self.assertTrue(changes)
        self.assertEqual(len({row["change_id"] for row in changes}), len(changes))
        for master in read(PROJECT_ROOT / "data/extracted/fund-level/fund_master.csv")[1]:
            for field in ("strategy", "vintage_year"):
                if master.get(field):
                    self.assertTrue(any(
                        row["target_table"] == "fund_master"
                        and row["target_record_id"] == master["fund_id"]
                        and row["field"] == field and row["new_value"] == master[field]
                        for row in changes
                    ))
        for change in changes:
            self.assertIn(change["source_observation_id"], observation_ids)
            target = targets[change["target_table"]][change["target_record_id"]]
            self.assertEqual(target[change["field"]], change["new_value"])

    def test_reviewer_analytics_summary_covers_metrics_and_portfolio(self) -> None:
        header, rows = read(ANALYTICS_SUMMARY_OUTPUT)
        self.assertIn("source_file", header)
        distributions = {
            (row["population"], row["metric_id"])
            for row in rows
            if row["record_type"] == "distribution"
        }
        self.assertEqual(
            distributions,
            {
                *(('EXTRACTED', metric) for metric in ('dpi', 'rvpi', 'tvpi')),
                *(('INTEGRATED', metric) for metric in ('dpi', 'rvpi', 'tvpi', 'xirr', 'ks_pme', 'direct_alpha')),
                ('INTEGRATED_PORTFOLIO', 'target_weight'),
            },
        )
        coverage = {
            row["population"]: row
            for row in rows
            if row["record_type"] == "coverage"
        }
        self.assertEqual(coverage["EXTRACTED"]["row_count"], "268")
        self.assertEqual(int(coverage["INTEGRATED"]["row_count"]), sum(r["provenance_type"] == "SYNTHETIC" for r in read(PROJECT_ROOT / "data/csv/fund_periods.csv")[1]))
        exposure_rows = [row for row in rows if row["record_type"] == "strategy_exposure"]
        self.assertAlmostEqual(
            sum(float(row["weighted_value"]) for row in exposure_rows), 1.0, places=8
        )
        # The printed word and what it reads as, side by side. The file carried
        # the word alone, so the dashboard had to head the column with the
        # vocabulary it came from instead of the taxonomy.
        for field in ("canonical_asset_class", "canonical_strategy", "canonical_sector"):
            self.assertIn(field, header)
        self.assertTrue(all(row["canonical_asset_class"] for row in exposure_rows))

    def test_every_governed_output_has_a_current_receipt(self) -> None:
        self.assertEqual(missing_current_receipts(GOVERNED_OUTPUTS), [])


if __name__ == "__main__":
    unittest.main()
