from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.catalog.simple_pdf_extraction import csv_workflow as workflow
from src.catalog.simple_pdf_extraction.csv_wide_contract import (
    CONTRACT_VERSION,
    COVERAGE_COLUMNS,
    COVERAGE_RESOLUTION_COLUMNS,
    RECORD_COLUMNS,
    RESOLUTION_COLUMNS,
)


class WideWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.working = self.root / "ledgers" / "working" / "pdf-extraction-csv"
        txt = self.root / "data" / "documents" / "txt" / "test.txt"
        txt.parent.mkdir(parents=True, exist_ok=True)
        txt.write_text(
            "# file_id: SRC999\n"
            "# doc_type: Performance\n"
            "==============================================================================\n"
            "===== SRC999 PAGE 1 of 1 | chars 45 | text native =====\n"
            "==============================================================================\n"
            "Test Performance Report\n"
            "Fund A 5.0%\n",
            encoding="utf-8",
        )
        self.routing = {
            "file_id": "SRC999",
            "filename": "test.pdf",
            "page_count": "1",
            "canonical_doc_type": "Performance",
            "source_header_doc_type": "Performance",
            "route": "02-performance",
            "product_tier": "CORE",
            "routing_status": "MATCH",
            "routing_reason": "TEST",
            "issuer": "Test Institution",
            "source_sha256": "a" * 64,
            "txt_path": "data/documents/txt/test.txt",
            "pdf_path": "data/documents/pdf/test.pdf",
            "image_dir": "data/documents/images/test",
        }
        image_dir = self.root / "data" / "documents" / "images" / "test"
        image_dir.mkdir(parents=True, exist_ok=True)
        (image_dir / "page-001.png").write_bytes(b"png")
        self.patchers = [
            mock.patch.object(workflow, "PROJECT_ROOT", self.root),
            mock.patch.object(workflow, "WORKING_ROOT", self.working),
            mock.patch.object(workflow, "routing_for", return_value=self.routing),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.addCleanup(self._cleanup_patches)

    def _cleanup_patches(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def base_record(self, agent: str) -> dict[str, str]:
        row = {column: "" for column in RECORD_COLUMNS}
        row.update(
            {
                "contract_version": CONTRACT_VERSION,
                "file_id": "SRC999",
                "source_sha256": "a" * 64,
                "canonical_doc_type": "Performance",
                "route": "02-performance",
                "product_tier": "CORE",
                "agent_role": agent,
                "source_page": "1",
                "source_occurrence": "1",
                "evidence_class": "actual",
            }
        )
        return row

    def candidate_records(self, agent: str) -> list[dict[str, str]]:
        context = self.base_record(agent)
        context.update(
            {
                "record_family": "document_context",
                "source_structure_type": "DOCUMENT",
                "source_section": "Cover",
                "source_table": "Test Performance Report",
                "source_row_label": "DOCUMENT",
                "subject_type": "reporting_entity",
                "subject_name": "Test Institution",
                "text_raw": "Test Performance Report",
                "evidence_quote": "Test Performance Report",
            }
        )
        performance = self.base_record(agent)
        performance.update(
            {
                "record_family": "performance_observation",
                "source_structure_type": "TABLE",
                "source_section": "Results",
                "source_table": "Returns",
                "source_row_label": "Fund A",
                "source_column_label": "1 Year",
                "subject_type": "portfolio",
                "subject_name": "Fund A",
                "horizon": "1 Year",
                "metric_category": "return",
                "metric_name": "Return",
                "metric_value_raw": "5.0%",
                "unit": "%",
                "evidence_quote": "Fund A 5.0%",
            }
        )
        return [context, performance]

    def candidate_coverage(self, agent: str) -> list[dict[str, str]]:
        row = {column: "" for column in COVERAGE_COLUMNS}
        row.update(
            {
                "contract_version": CONTRACT_VERSION,
                "file_id": "SRC999",
                "source_sha256": "a" * 64,
                "canonical_doc_type": "Performance",
                "route": "02-performance",
                "product_tier": "CORE",
                "agent_role": agent,
                "source_page": "1",
                "page_status": "ELIGIBLE_DATA_EXTRACTED",
                "layout_checked": "YES",
                "source_structures": "Returns | Test Performance Report",
                "relevant_record_families": "document_context | performance_observation",
                "expected_observation_count": "2",
                "records_written": "2",
            }
        )
        return [row]

    def write_candidate(self, agent: str) -> None:
        record_path, coverage_path = workflow.candidate_paths(
            "02-performance", "SRC999", agent
        )
        workflow.write_csv(record_path, RECORD_COLUMNS, self.candidate_records(agent))
        workflow.write_csv(
            coverage_path, COVERAGE_COLUMNS, self.candidate_coverage(agent)
        )
        # A real run declares its model before validating; the fixture does the
        # same so the test exercises the same path an extractor takes.
        workflow.claim_command("02-performance", agent, "test-model", "unit-test")

    def test_end_to_end_exact_pair_builds_final(self) -> None:
        self.write_candidate("A")
        self.write_candidate("B")
        for agent in ("A", "B"):
            _, _, errors = workflow.validate_candidate_data(
                "02-performance", "SRC999", agent
            )
            self.assertEqual(errors, [])

        workflow.compare_command("02-performance", "SRC999")
        paths = workflow.pair_paths("02-performance", "SRC999")
        pairs = workflow.read_strict_csv(paths["pair"], workflow.PAIR_COLUMNS)
        resolutions: list[dict[str, str]] = []
        for pair in pairs:
            if pair["requires_review"] != "YES":
                continue
            row = {column: "" for column in RESOLUTION_COLUMNS}
            row.update(
                {
                    "pair_id": pair["pair_id"],
                    "decision": "CONFIRM",
                    "reason": "Verified against source",
                }
            )
            resolutions.append(row)
        workflow.write_csv(paths["resolution"], RESOLUTION_COLUMNS, resolutions)
        coverage_resolution = {
            column: "" for column in COVERAGE_RESOLUTION_COLUMNS
        }
        coverage_resolution.update(
            {
                "source_page": "1",
                "final_page_status": "ELIGIBLE_DATA_EXTRACTED",
                "final_expected_observation_count": "2",
                "reason": "Verified deterministic page sample",
            }
        )
        workflow.write_csv(
            paths["coverage_resolution"],
            COVERAGE_RESOLUTION_COLUMNS,
            [coverage_resolution],
        )
        workflow.build_final_command("02-performance", "SRC999")
        records, coverage, errors = workflow.validate_final_data(
            "02-performance", "SRC999"
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 2)
        self.assertEqual(len(coverage), 1)
        self.assertTrue(all(row["source_agents"] == "A+B" for row in records))
        self.assertTrue(
            all(row["adjudication_status"] == "AGREED" for row in records)
        )

    def test_missing_page_picture_blocks_extraction(self) -> None:
        image = self.root / "data" / "documents" / "images" / "test" / "page-001.png"
        image.unlink()
        self.write_candidate("A")
        _, _, errors = workflow.validate_candidate_data(
            "02-performance", "SRC999", "A"
        )
        self.assertEqual(errors, [])
        with self.assertRaisesRegex(
            workflow.ContractFailure, "extraction requires a 300 DPI PNG"
        ):
            workflow.validate_candidate_command(
                "02-performance", "SRC999", "A"
            )

    def test_null_metric_value_is_rejected(self) -> None:
        records = self.candidate_records("A")
        records[1]["metric_value_raw"] = "-"
        record_path, coverage_path = workflow.candidate_paths(
            "02-performance", "SRC999", "A"
        )
        workflow.write_csv(record_path, RECORD_COLUMNS, records)
        workflow.write_csv(
            coverage_path, COVERAGE_COLUMNS, self.candidate_coverage("A")
        )
        _, _, errors = workflow.validate_candidate_data(
            "02-performance", "SRC999", "A"
        )
        self.assertTrue(any("null-like metric value" in error for error in errors))

    def test_bad_quote_is_rejected(self) -> None:
        records = self.candidate_records("A")
        records[1]["evidence_quote"] = "not present on source page"
        record_path, coverage_path = workflow.candidate_paths(
            "02-performance", "SRC999", "A"
        )
        workflow.write_csv(record_path, RECORD_COLUMNS, records)
        workflow.write_csv(
            coverage_path, COVERAGE_COLUMNS, self.candidate_coverage("A")
        )
        _, _, errors = workflow.validate_candidate_data(
            "02-performance", "SRC999", "A"
        )
        self.assertTrue(any("evidence_quote is absent" in error for error in errors))

    def test_shifted_width_is_rejected_before_semantic_validation(self) -> None:
        path = self.root / "bad.csv"
        path.write_text(
            ",".join(RECORD_COLUMNS) + "\n" + ",".join(["x"] * (len(RECORD_COLUMNS) - 1)) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(workflow.ContractFailure):
            workflow.read_strict_csv(path, RECORD_COLUMNS)

    @staticmethod
    def _cell(occurrence: str, value: str, quote: str) -> dict[str, str]:
        return {
            "file_id": "SRC384", "source_page": "3",
            "source_row_label": "Value Added", "source_column_label": "10 Year",
            "source_occurrence": occurrence, "metric_value_raw": value,
            "evidence_quote": quote,
        }

    def _maps(self, a_rows, b_rows):
        return (
            {workflow.record_key(r): (i, r) for i, r in enumerate(a_rows, 1)},
            {workflow.record_key(r): (i, r) for i, r in enumerate(b_rows, 1)},
        )

    def test_occurrence_drift_is_realigned_by_the_cited_line(self) -> None:
        """A lane that misses one row renumbers every row beneath it.

        Both lanes read this cell correctly; they numbered it 4 and 7. Without
        realignment it reaches the adjudicator as a value conflict where
        neither side is wrong.
        """
        line = "Value Added 0.2 0.4 0.3 0.2 0.1 0.2 0.0 0.1 0.7"
        a_map, b_map = self._maps([self._cell("4", "0.1", line)],
                                  [self._cell("7", "0.1", line)])
        self.assertEqual(len(set(a_map) & set(b_map)), 0)
        self.assertEqual(workflow.realign_by_cited_line(a_map, b_map), 1)
        self.assertEqual(len(set(a_map) & set(b_map)), 1)

    def test_realignment_refuses_to_guess_when_the_line_is_ambiguous(self) -> None:
        """Two candidates for one line is not a match, it is a coin flip."""
        a_map, b_map = self._maps(
            [self._cell("4", "0.1", "same line"), self._cell("5", "0.2", "same line")],
            [self._cell("9", "0.1", "same line")],
        )
        self.assertEqual(workflow.realign_by_cited_line(a_map, b_map), 0)

    def test_realignment_ignores_rows_with_no_cited_line(self) -> None:
        """Blank quotes would otherwise collapse unrelated rows together."""
        a_map, b_map = self._maps([self._cell("1", "5", "")],
                                  [self._cell("2", "9", "")])
        self.assertEqual(workflow.realign_by_cited_line(a_map, b_map), 0)

    @staticmethod
    def _col(page: str, label: str, column: str, occurrence: str, value: str) -> dict[str, str]:
        return {"file_id": "SRC457", "source_page": page, "source_row_label": label,
                "source_column_label": column, "source_occurrence": occurrence,
                "metric_value_raw": value, "evidence_quote": ""}

    def test_renamed_column_is_paired_on_row_and_value(self) -> None:
        """`Market Value ($)` and `Market Value` are one printed column.

        Unpaired, 162 such rows on one document reached the adjudicator as
        one-sided; paired, the header convention settles the name.
        """
        a_map, b_map = self._maps(
            [self._col("9", "Lone Star Fund XI", "Market Value ($)", "1", "1,250,218")],
            [self._col("9", "Lone Star Fund XI", "Market Value", "1", "1,250,218")])
        self.assertEqual(workflow.realign_by_renamed_column(a_map, b_map), 1)
        self.assertEqual(len(set(a_map) & set(b_map)), 1)

    def test_renamed_column_refuses_two_real_columns_with_equal_values(self) -> None:
        """A's `20 Year` and B's `25 Year` both exist on both sides.

        Fusing them on a coincidental value would make a missed cell vanish.
        """
        a_map, b_map = self._maps(
            [self._col("3", "Value Added", "20 Year", "1", "0.6"),
             self._col("3", "Value Added", "25 Year", "1", "0.9")],
            [self._col("3", "Value Added", "25 Year", "2", "0.6"),
             self._col("3", "Value Added", "20 Year", "2", "0.2")])
        self.assertEqual(workflow.realign_by_renamed_column(a_map, b_map), 0)

    def test_renamed_column_pairs_same_column_occurrence_drift(self) -> None:
        a_map, b_map = self._maps(
            [self._col("3", "Value Added", "30 Year", "4", "0.6")],
            [self._col("3", "Value Added", "30 Year", "7", "0.6")])
        self.assertEqual(workflow.realign_by_renamed_column(a_map, b_map), 1)

    def test_dropped_unit_symbol_is_detected_from_the_rows_own_quote(self) -> None:
        """The value must keep a symbol its own cited line prints on it.

        Stated only in prose, this convention held on two documents of a round
        and not the third, where 61 of 73 rows dropped a printed `%` their own
        quote still shows.
        """
        for value, quote, expected in (
            ("~97.8", "~97.8%", "%"),
            ("9.00", "As of April 30, 2026 $24.69 $0.19 9.00%", "%"),
            ("1.02", "Q1 2008 (9.00) - (9.00) 9.18 1.02x 2.38%", "x"),
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    workflow.dropped_unit_symbol(
                        {"metric_value_raw": value, "evidence_quote": quote}), expected)

    def test_dropped_unit_symbol_ignores_a_comparison_prefixed_neighbour(self) -> None:
        """`Risk Rating D <1% 1`: the `1%` is a threshold, the cell is the bare 1.

        Reading the threshold as this cell rewrote a borrower count of 1 into
        `1%`. An adjudicator caught it against the page image. The lookbehind
        now excludes comparison and approximation prefixes, and a standalone
        bare occurrence in the same quote proves the page does print the value
        without the symbol.
        """
        for value, quote in (
            ("1", "Risk Rating D <1% 1"),
            ("1", "Risk Rating D >1% 1"),
            ("2", "approximately ~2% of the fund 2"),
            ("5", "at least =5% and 5 borrowers"),
            ("3", "up to ≤3% 3"),
            ("4", "≥4% 4"),
        ):
            with self.subTest(value=value, quote=quote):
                self.assertEqual(
                    workflow.dropped_unit_symbol(
                        {"metric_value_raw": value, "evidence_quote": quote}), "")

    def test_dropped_unit_symbol_does_not_fire_on_a_neighbouring_number(self) -> None:
        """`4` must not match the tail of a printed `34%`, and a value the page
        prints bare must stay bare."""
        for value, quote in (
            ("4", "Natural Resources (Net) $923,369,447 34% $282,009,117"),
            ("1.0", "Q1 2008 (9.00) - (9.00) 9.18 1.02x 2.38%"),
            ("1.24", "Natural Resources (Net) 1.24 0.92 0.32 0.79"),
            ("51.90%", "Lone Star Fund XI, L.P. (51.90%)"),
            ("3.6", "the pension returned 3.6 percent and working"),
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    workflow.dropped_unit_symbol(
                        {"metric_value_raw": value, "evidence_quote": quote}), "")

    @staticmethod
    def _round_row(**overrides) -> dict[str, str]:
        row = {"file_id": "SRC1", "source_page": "1", "source_row_label": "r",
               "source_column_label": "c", "source_occurrence": "1",
               "metric_value_raw": "5"}
        row.update(overrides)
        return row

    def test_round_drift_passes_an_unchanged_round(self) -> None:
        row = self._round_row()
        self.assertEqual(workflow._round_drift([row], [dict(row)]), "")

    def test_round_drift_catches_every_way_a_round_goes_stale(self) -> None:
        """The corpus is built from round files, so a round edited or
        re-adjudicated after publication is the one way stale data could reach
        the end of the pipeline. Each kind of drift must name itself."""
        row = self._round_row()
        for label, expected, changed in (
            ("count", "records", [dict(row), self._round_row(source_occurrence="2")]),
            ("value", "values differ", [self._round_row(metric_value_raw="9")]),
            ("key", "record keys differ", [self._round_row(source_row_label="other")]),
        ):
            with self.subTest(drift=label):
                self.assertIn(expected, workflow._round_drift([row], changed))

    def test_renamed_column_ignores_blank_values(self) -> None:
        a_map, b_map = self._maps([self._col("3", "x", "A", "1", "")],
                                  [self._col("3", "x", "B", "1", "")])
        self.assertEqual(workflow.realign_by_renamed_column(a_map, b_map), 0)

    @staticmethod
    def _full_row(**overrides) -> dict[str, str]:
        row = {column: "" for column in RECORD_COLUMNS}
        row.update({
            "file_id": "SRC063", "source_page": "2", "record_family": "performance_observation",
            "source_row_label": "Harbert Power Fund V", "source_column_label": "Ending Market Value (MM)",
            "source_occurrence": "1", "subject_type": "fund", "subject_name": "Harbert Power Fund V",
            "asset_class": "Real Assets", "metric_category": "nav", "metric_name": "Ending Market Value",
            "metric_value_raw": "$ 24.6", "evidence_quote": "Harbert Power Fund V $ 24.6",
            "evidence_class": "actual",
        })
        row.update(overrides)
        return row

    def test_shifted_row_is_repaired_against_the_other_lane(self) -> None:
        """One lane dropped `asset_class`; everything after it slid left.

        Standalone the repair is ambiguous. Against the other lane's row for
        the same cell it is not, and the restored value is still this lane's
        own reading.
        """
        reference = self._full_row()
        short = [reference[c] for c in RECORD_COLUMNS if c != "asset_class"]
        repaired, reason = workflow.repair_shifted_rows(
            short, {workflow.record_key(reference): reference})
        self.assertIsNotNone(repaired, reason)
        self.assertEqual(repaired["metric_value_raw"], "$ 24.6")
        self.assertEqual(repaired["metric_name"], "Ending Market Value")
        self.assertEqual(repaired["evidence_class"], "actual")
        self.assertEqual(repaired["asset_class"], "")
        self.assertTrue(repaired["notes"].startswith("REPAIRED_SHIFT"))

    def test_shifted_row_with_no_reference_is_refused(self) -> None:
        """No other-lane row for the cell means no way to know what dropped."""
        reference = self._full_row(source_page="9")
        short = [self._full_row()[c] for c in RECORD_COLUMNS if c != "asset_class"]
        repaired, reason = workflow.repair_shifted_rows(
            short, {workflow.record_key(reference): reference})
        self.assertIsNone(repaired)
        self.assertIn("no reference row", reason)

    def test_claim_rejects_a_placeholder_instead_of_a_model_name(self) -> None:
        """An agent that will not name itself must not be able to say so.

        One route was claimed as `unknown`, which sits in the ledger looking
        just like a real model name and silently loses the attribution the
        claim exists to capture.
        """
        for placeholder in ("unknown", "UNKNOWN", " n/a ", "TBD", "",
                            "<the model you are running as>"):
            with self.subTest(placeholder=placeholder):
                with self.assertRaises(workflow.ContractFailure):
                    workflow.claim_command("02-performance", "A", placeholder)

    def test_claim_accepts_a_real_model_name(self) -> None:
        recorded: list[dict[str, str]] = []
        with mock.patch.object(workflow, "read_claims", return_value={}), \
             mock.patch.object(workflow, "write_csv",
                               side_effect=lambda p, c, rows: recorded.extend(rows)), \
             mock.patch.object(workflow, "write_header_if_missing"), \
             mock.patch.object(workflow, "model_ledger") as ledger:
            ledger.return_value.open = mock.mock_open()
            workflow.claim_command("02-performance", "A", "claude-sonnet-5")
        self.assertEqual(recorded[0]["extractor_model"], "claude-sonnet-5")

    def test_shifted_row_is_refused_when_insertions_tie_on_a_real_field(self) -> None:
        """Two insertion points that fit equally but place a value differently.

        The reference leaves asset_class and strategy blank; the shifted row
        carries `Opportunistic` that could be either. Restoring the gap before
        it or after it scores the same, and the two readings disagree on which
        field holds the word. That is a guess, and a guess is refused.
        """
        reference = self._full_row(asset_class="", strategy="", geography="")
        source = self._full_row(asset_class="", strategy="Opportunistic", geography="")
        short = [source[c] for c in RECORD_COLUMNS if c != "asset_class"]
        repaired, reason = workflow.repair_shifted_rows(
            short, {workflow.record_key(reference): reference})
        self.assertIsNone(repaired)
        self.assertIn("tie", reason)


if __name__ == "__main__":
    unittest.main()
