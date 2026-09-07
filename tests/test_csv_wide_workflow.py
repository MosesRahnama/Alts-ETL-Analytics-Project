from __future__ import annotations

import contextlib
import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.catalog.simple_pdf_extraction import csv_workflow as workflow
from src.pipeline import combine_extracted_raw, publish_review_release as release
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
            mock.patch.object(workflow, "grid_built", return_value=True),
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
                "method": "unstated",
                "fee_basis": "unstated",
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

    def _build_valid_final(self) -> None:
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

    def test_end_to_end_exact_pair_builds_final(self) -> None:
        self._build_valid_final()

    def test_final_refuses_replacement_characters_without_changing_candidates(self) -> None:
        self._build_valid_final()
        candidates = [path for agent in ("A", "B")
                      for path in workflow.candidate_paths("02-performance", "SRC999", agent)]
        before = {path: path.read_bytes() for path in candidates}
        path, _ = workflow.final_paths("02-performance", "SRC999")
        for field in ("text_raw", "evidence_quote"):
            with self.subTest(field=field):
                rows = workflow.read_strict_csv(path, RECORD_COLUMNS)
                old = rows[0][field]
                rows[0][field] = old + "\ufffd"
                workflow.write_csv(path, RECORD_COLUMNS, rows)
                _, _, errors = workflow.validate_final_data("02-performance", "SRC999")
                self.assertTrue(any(field in error and "unreadable character" in error
                                    for error in errors))
                rows[0][field] = old
                workflow.write_csv(path, RECORD_COLUMNS, rows)
        self.assertEqual(before, {path: path.read_bytes() for path in candidates})

    def test_final_preflight_preserves_previous_outputs_on_incomplete_page(self) -> None:
        self._build_valid_final()
        paths = workflow.final_paths("02-performance", "SRC999")
        before = {p: p.read_bytes() for p in paths}
        with mock.patch.object(workflow, "grid_page_shape", return_value={1: (60, 8)}):
            with self.assertRaisesRegex(workflow.ContractFailure, "Final preflight"):
                workflow.build_final_command("02-performance", "SRC999")
            _, _, errors = workflow.validate_final_data("02-performance", "SRC999")
            self.assertTrue(any("partly extracted" in e for e in errors))
        self.assertEqual(before, {p: p.read_bytes() for p in paths})

    def test_final_validation_requires_the_grid(self) -> None:
        self._build_valid_final()
        with mock.patch.object(workflow, "grid_built", return_value=False):
            _, _, errors = workflow.validate_final_data("02-performance", "SRC999")
            self.assertTrue(any("no page grid" in e for e in errors))

    def test_invalid_final_holds_review_without_reopening_candidates(self) -> None:
        self._build_valid_final()
        candidates = workflow.candidate_paths("02-performance", "SRC999", "A")
        before = {p: p.read_bytes() for p in candidates}
        with mock.patch.object(workflow, "grid_page_shape", return_value={1: (60, 8)}):
            self.assertEqual(workflow._lane_state("02-performance", "SRC999", "A"), "REVIEW_REQUIRED")
            self.assertIn("retain original candidates", workflow._lane_reason("02-performance", "SRC999", "A"))
        self.assertEqual(before, {p: p.read_bytes() for p in candidates})

    def test_agreeing_coverage_notes_survive_final_construction(self) -> None:
        self._build_valid_final()
        note = "PARTIAL_BY_SCOPE: Other columns contain employee counts outside permitted fund metric categories."
        for agent in ("A", "B"):
            _, path = workflow.candidate_paths("02-performance", "SRC999", agent)
            rows = workflow.read_strict_csv(path, COVERAGE_COLUMNS)
            rows[0]["notes"] = note
            workflow.write_csv(path, COVERAGE_COLUMNS, rows)
        paths = workflow.pair_paths("02-performance", "SRC999")
        # Exercise an agreeing page outside the mandatory coverage sample.
        with mock.patch.object(workflow, "pair_coverage", return_value=[]):
            workflow.compare_command("02-performance", "SRC999")
        workflow.write_csv(paths["coverage_resolution"], COVERAGE_RESOLUTION_COLUMNS, [])
        with mock.patch.object(workflow, "grid_page_shape", return_value={1: (60, 8)}):
            workflow.build_final_command("02-performance", "SRC999")
        _, path = workflow.final_paths("02-performance", "SRC999")
        self.assertEqual(workflow.read_strict_csv(path, COVERAGE_COLUMNS)[0]["notes"], note)

    def test_current_candidate_refuses_historical_header(self) -> None:
        self.write_candidate("A")
        path, _ = workflow.candidate_paths("02-performance", "SRC999", "A")
        columns = min(workflow.RECORD_HEADERS_BY_VERSION.values(), key=len)
        workflow.write_csv(path, columns, self.candidate_records("A"))
        _, _, errors = workflow.validate_candidate_data("02-performance", "SRC999", "A")
        self.assertTrue(any("issued" in e and "header" in e for e in errors))
        _, _, errors = workflow.validate_candidate_data(
            "02-performance", "SRC999", "A", allow_legacy_qualifiers=True)
        self.assertFalse(any("issued" in e and "header" in e for e in errors))

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

    def test_cross_page_definition_key_must_be_unique_in_the_document(self) -> None:
        records = self.candidate_records("A")
        records[1]["definition_keys"] = "1"
        definitions = []
        for page, text in (("2", "1 First definition"), ("3", "1 Other definition")):
            row = self.base_record("A")
            row.update(
                {
                    "record_family": "definition_context",
                    "source_page": page,
                    "source_structure_type": "FOOTNOTE",
                    "source_section": "Notes",
                    "source_row_label": "1",
                    "definition_keys": "1",
                    "text_raw": text,
                    "evidence_quote": text,
                }
            )
            definitions.append(row)
        routing = dict(self.routing, page_count="3")
        page_text = {
            "1": "Test Performance Report Fund A 5.0%",
            "2": "1 First definition",
            "3": "1 Other definition",
        }
        with mock.patch.object(workflow, "source_page_texts", return_value=page_text):
            errors = workflow.validate_record_rows(
                self.root / "records.csv",
                [*records, *definitions],
                routing,
                "A",
                final=False,
            )
            self.assertTrue(any("definitions on multiple pages" in error for error in errors))

            errors = workflow.validate_record_rows(
                self.root / "records.csv",
                [*records, definitions[0]],
                routing,
                "A",
                final=False,
            )
            self.assertFalse(any("definition_keys names" in error for error in errors))

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

    def _cover_page_only_context(self, agent: str, status: str) -> list[str]:
        """Page 1 is a cover: it carries the identity row and nothing else."""
        record_path, coverage_path = workflow.candidate_paths(
            "02-performance", "SRC999", agent
        )
        context = self.candidate_records(agent)[0]
        coverage = self.candidate_coverage(agent)[0]
        coverage.update(
            {
                "page_status": status,
                "layout_checked": "NO",
                "source_structures": "Test Performance Report",
                "relevant_record_families": "document_context",
                "expected_observation_count": "1",
                "records_written": "1",
                "notes": "Cover page: title block only, no printed values.",
            }
        )
        workflow.write_csv(record_path, RECORD_COLUMNS, [context])
        workflow.write_csv(coverage_path, COVERAGE_COLUMNS, [coverage])
        workflow.claim_command("02-performance", agent, "test-model", "unit-test")
        _, _, errors = workflow.validate_candidate_data("02-performance", "SRC999", agent)
        return errors

    def test_a_cover_page_carrying_only_the_identity_row_validates(self) -> None:
        """The contract had no valid status for this page, and it is common.

        The document_context row must sit on page 1, but page 1 is often a
        cover with nothing extractable on it. Counting that row as an
        observation made ELIGIBLE_DATA_EXTRACTED refuse it for holding no
        observation, while every other status refused it for holding a record,
        so ten of twenty-nine published documents escaped by filing the row on
        a later page, which is the one thing that row may not do.
        """
        self.assertEqual(self._cover_page_only_context("A", "REFERENCE_ONLY"), [])

    def test_a_cover_page_may_not_claim_data_was_extracted(self) -> None:
        """Relaxing the status must not let a page claim work it never did."""
        errors = self._cover_page_only_context("B", "ELIGIBLE_DATA_EXTRACTED")
        self.assertTrue(errors)
        self.assertIn("only the document_context row cites page 1", errors[0])

    def _two_document_worklist(self) -> list[dict[str, str]]:
        second = dict(self.routing)
        second["file_id"] = "SRC998"
        return [self.routing, second]

    def _lane_env(self, worklist: list[dict[str, str]]):
        """The lane gate under test, with the grid checks stubbed out.

        The grid lives outside the temporary root, and what these tests ask is
        whether the gate reads the worklist rather than the lane's own account
        of itself.
        """
        return (
            mock.patch.object(workflow, "worklist_for_scope", return_value=worklist),
            mock.patch.object(workflow, "grid_built", return_value=True),
            mock.patch.object(workflow, "grid_page_shape", return_value={}),
        )

    def test_lane_check_passes_when_every_assigned_document_is_finished(self) -> None:
        self.write_candidate("A")
        with contextlib.ExitStack() as stack:
            for patcher in self._lane_env([self.routing]):
                stack.enter_context(patcher)
            workflow.lane_check_command("02-performance", "A")

    def test_lane_check_fails_on_a_document_the_lane_never_opened(self) -> None:
        """The defect every per-file gate is blind to.

        `validate-candidate` and `audit-file` each take one `--file`, so a
        document nobody named produces no failing command and the lane reports
        itself finished. One round lost three documents that way, one of them
        never opened. The lane gate reads the worklist instead of the lane's
        own account of what it did.
        """
        self.write_candidate("A")
        with contextlib.ExitStack() as stack:
            for patcher in self._lane_env(self._two_document_worklist()):
                stack.enter_context(patcher)
            with self.assertRaises(workflow.ContractFailure) as caught:
                workflow.lane_check_command("02-performance", "A")
        self.assertIn("SRC998", str(caught.exception))
        self.assertNotIn("SRC999", str(caught.exception))

    def test_lane_check_reads_only_its_own_lane(self) -> None:
        """Lane B finishing does not finish lane A, and neither can see the other."""
        self.write_candidate("B")
        with contextlib.ExitStack() as stack:
            for patcher in self._lane_env([self.routing]):
                stack.enter_context(patcher)
            workflow.lane_check_command("02-performance", "B")
            with self.assertRaises(workflow.ContractFailure):
                workflow.lane_check_command("02-performance", "A")

    def _audit_with_grid(self, agent: str, cells: int, note: str) -> None:
        """Run the completeness audit against a page the grid says is dense."""
        coverage = self.candidate_coverage(agent)
        coverage[0]["notes"] = note
        _, coverage_path = workflow.candidate_paths("02-performance", "SRC999", agent)
        workflow.write_csv(coverage_path, COVERAGE_COLUMNS, coverage)
        with (
            mock.patch.object(workflow, "grid_built", return_value=True),
            mock.patch.object(workflow, "grid_page_shape", return_value={1: (cells, 5)}),
        ):
            workflow.audit_file_command(
                "02-performance", "SRC999", agent, quiet=True, require_images=False
            )

    def test_a_thin_page_with_no_reason_fails_the_audit(self) -> None:
        """The check that never fired.

        Its trigger sat at three times the cell count that challenges a page
        declared empty, and at a quarter of the values; on no page of the
        corpus did both hold, while two pages of one audited financial
        statement published 2 and 4 rows against 23 and 32 printed values
        with an empty note. The trigger is now the same twelve cells, and
        what a thin page owes is the reason, not more rows for their own sake.
        """
        self.write_candidate("A")
        with self.assertRaises(workflow.ContractFailure) as caught:
            self._audit_with_grid("A", cells=20, note="")
        self.assertIn("partly extracted with no reason", str(caught.exception))
        self.assertIn(workflow.PARTIAL_REASON, str(caught.exception))

    def test_a_thin_page_with_a_category_reason_passes_the_audit(self) -> None:
        self.write_candidate("A")
        self._audit_with_grid(
            "A", cells=20,
            note=f"{workflow.PARTIAL_REASON} benchmark index levels, no allowed category",
        )

    def test_a_thin_page_excused_by_difficulty_still_fails(self) -> None:
        """Hard to read is not a category test, on a thin page as on an empty one."""
        self.write_candidate("A")
        excuse = workflow.DIFFICULTY_EXCUSES[0]
        with self.assertRaises(workflow.ContractFailure) as caught:
            self._audit_with_grid("A", cells=20, note=f"{workflow.PARTIAL_REASON} {excuse}")
        self.assertIn("how hard the page is to read", str(caught.exception))

    def test_a_page_below_the_grid_trigger_is_not_audited_for_thinness(self) -> None:
        self.write_candidate("A")
        self._audit_with_grid("A", cells=11, note="")

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

    # A1-01: the qualified-category check reads the file's header, never the
    # row's own contract stamp.

    def _return_row_missing_its_qualifiers(self, stamp: str) -> list[str]:
        records = self.candidate_records("A")
        records[1].update({"contract_version": stamp, "method": "", "fee_basis": ""})
        return workflow.validate_record_rows(
            self.root / "records.csv", records, self.routing, "A", final=True
        )

    def test_a_bare_return_is_refused_whatever_contract_the_row_is_stamped_with(
        self,
    ) -> None:
        """Every published return row carried a stamp older than the qualifier
        columns, so a gate keyed on the stamp ran on nothing. The file's header
        is what says whether a row can state a method."""

        for stamp in ("2026-08-22.2", CONTRACT_VERSION):
            with self.subTest(stamp=stamp):
                errors = self._return_row_missing_its_qualifiers(stamp)
                self.assertEqual(
                    2,
                    sum("qualified category 'return' requires" in error for error in errors),
                    errors,
                )

    def test_a_file_that_predates_the_qualifier_columns_is_not_held_to_them(self) -> None:
        """A file whose header has no `method` column cannot state one, so the
        check reads the columns the file carries and asks for nothing else."""

        legacy = [
            column
            for column in RECORD_COLUMNS
            if column not in {"definition_keys", "method", "fee_basis", "value_scope", "sector"}
        ]
        path = self.root / "legacy.csv"
        rows = self.candidate_records("A")
        for row in rows:
            row["contract_version"] = "2026-08-22.2"
        workflow.write_csv(path, legacy, rows)
        loaded = workflow.read_strict_csv(path, RECORD_COLUMNS)
        self.assertNotIn("method", workflow.columns_carried(loaded[0]))
        errors = workflow.validate_record_rows(
            path, loaded, self.routing, "A", final=True
        )
        self.assertFalse(
            any("qualified category" in error for error in errors), errors
        )

    # A1-03: a printed grouping the taxonomy matrix cannot read.

    def _grouping_errors(self, final: bool, **overrides) -> tuple[list[str], list[str]]:
        records = self.candidate_records("A")
        records[1].update(overrides)
        warnings: list[str] = []
        errors = workflow.validate_record_rows(
            self.root / "records.csv", records, self.routing, "A",
            final=final, warnings=warnings,
        )
        return errors, warnings

    def test_an_industry_filed_under_asset_class_is_refused_at_final(self) -> None:
        errors, _ = self._grouping_errors(True, asset_class="Media")
        self.assertTrue(
            any("is an industry, not an asset class" in error for error in errors), errors
        )

    def test_a_grouping_the_matrix_does_not_carry_is_refused_at_final(self) -> None:
        errors, _ = self._grouping_errors(True, asset_class="Bloomberg Barclays Aggregate")
        self.assertTrue(
            any("has no row in context-grouping-map.csv" in error for error in errors), errors
        )

    def test_a_mapped_grouping_passes(self) -> None:
        errors, warnings = self._grouping_errors(
            True, asset_class="Private Equity", strategy="Buyout"
        )
        self.assertFalse(any("context-grouping-map" in error for error in errors), errors)
        self.assertEqual(warnings, [])

    def test_a_candidate_only_warns_about_a_grouping(self) -> None:
        """A lane reads a whole document before an adjudicator settles a new
        heading, so an unknown grouping is reported and the reading continues."""

        errors, warnings = self._grouping_errors(False, asset_class="Media")
        self.assertFalse(any("context-grouping-map" in error or "industry" in error
                             for error in errors), errors)
        self.assertTrue(any("is an industry" in warning for warning in warnings), warnings)

    # A1-06: one document reports one contract.

    def test_coverage_final_carries_the_contract_of_its_own_records(self) -> None:
        for agent in ("A", "B"):
            record_path, coverage_path = workflow.candidate_paths(
                "02-performance", "SRC999", agent
            )
            records = self.candidate_records(agent)
            for row in records:
                row["contract_version"] = "2026-08-22.2"
            workflow.write_csv(record_path, RECORD_COLUMNS, records)
            workflow.write_csv(
                coverage_path, COVERAGE_COLUMNS, self.candidate_coverage(agent)
            )
            workflow.claim_command("02-performance", agent, "test-model", "unit-test")
        self._resolve_every_reviewed_pair()
        workflow.build_final_command("02-performance", "SRC999")
        records, coverage, errors = workflow.validate_final_data("02-performance", "SRC999")
        self.assertEqual(errors, [])
        self.assertEqual({row["contract_version"] for row in records}, {"2026-08-22.2"})
        self.assertEqual(
            {row["contract_version"] for row in coverage}, {"2026-08-22.2"},
            "coverage-final must report the contract its own records report",
        )

    def _resolve_every_reviewed_pair(self, expected_rows: int = 2) -> None:
        workflow.compare_command("02-performance", "SRC999")
        paths = workflow.pair_paths("02-performance", "SRC999")
        resolutions = []
        for pair in workflow.read_strict_csv(paths["pair"], workflow.PAIR_COLUMNS):
            if pair["requires_review"] != "YES":
                continue
            row = {column: "" for column in RESOLUTION_COLUMNS}
            row.update({"pair_id": pair["pair_id"], "decision": "CONFIRM",
                        "reason": "Verified against source"})
            resolutions.append(row)
        workflow.write_csv(paths["resolution"], RESOLUTION_COLUMNS, resolutions)
        coverage_resolution = {column: "" for column in COVERAGE_RESOLUTION_COLUMNS}
        coverage_resolution.update({
            "source_page": "1",
            "final_page_status": "ELIGIBLE_DATA_EXTRACTED",
            "final_expected_observation_count": str(expected_rows),
            "reason": "Verified deterministic page sample",
        })
        workflow.write_csv(
            paths["coverage_resolution"], COVERAGE_RESOLUTION_COLUMNS, [coverage_resolution]
        )

    # A2-01: republishing a route does not re-attribute finished work.

    def test_republishing_keeps_the_attribution_of_rows_already_in_the_round(self) -> None:
        """`model_that_wrote` reads a candidate file's mtime against the claim
        ledger, so a slot claimed by a new model re-attributed every document
        on the route, including documents that lane never opened. A row already
        in the round file publishes under the model the round already named."""

        worklist = self.working.parent.parent.parent / "instructions" / (
            "01-pdf-extraction-csv") / "worklists" / "active" / "02-performance.csv"
        worklist.parent.mkdir(parents=True, exist_ok=True)
        worklist.write_text("work_order,file_id\n1,SRC999\n", encoding="utf-8")
        with mock.patch.object(workflow, "WORKLIST_ROOT", worklist.parent.parent):
            self.write_candidate("A")
            self.write_candidate("B")
            self._resolve_every_reviewed_pair()
            workflow.build_final_command("02-performance", "SRC999")
            workflow.publish_round("02-performance", "active")
            first = workflow.read_strict_csv(
                workflow.round_records("02-performance"), workflow.ROUND_RECORD_COLUMNS
            )
            self.assertTrue(all(row["extractor_model"] for row in first))

            # A new model claims both lanes and the route is published again.
            for agent in ("A", "B"):
                workflow.claim_command("02-performance", agent, "later-model", "unit-test")
            workflow.publish_round("02-performance", "active")
            second = workflow.read_strict_csv(
                workflow.round_records("02-performance"), workflow.ROUND_RECORD_COLUMNS
            )
            self.assertEqual(
                {workflow._attribution_key(row, workflow.ATTRIBUTION_RECORD_KEY):
                 row["extractor_model"] for row in first},
                {workflow._attribution_key(row, workflow.ATTRIBUTION_RECORD_KEY):
                 row["extractor_model"] for row in second},
            )
            self.assertNotIn("later-model", {row["extractor_model"] for row in second})

    # F10: a qualifier dimension nobody was asked to read is a debt, not a defect.

    OLD_STAMP = "2026-08-22.2"

    def _active_worklist(self, *file_ids: str) -> Path:
        """The scope worklist publication reads, holding these documents.

        Returns the worklist root to patch, so a test names its documents and
        publication sees exactly them.
        """

        active = (
            self.root / "instructions" / "01-pdf-extraction-csv" / "worklists" / "active"
        )
        active.mkdir(parents=True, exist_ok=True)
        for route in workflow.ROUTES:
            (active / f"{route}.csv").write_text("work_order,file_id\n", encoding="utf-8")
        rows = "".join(
            f"{order},{file_id}\n" for order, file_id in enumerate(file_ids, 1)
        )
        (active / "02-performance.csv").write_text(
            "work_order,file_id\n" + rows, encoding="utf-8"
        )
        return active.parent

    def _nav_records(self, agent: str, stamp: str) -> list[dict[str, str]]:
        """The fixture document plus one NAV cell, stamped as asked.

        NAV is qualified on `value_scope` alone, so the row states one
        dimension and the test can take it away again.
        """

        rows = self.candidate_records(agent)
        nav = self.base_record(agent)
        nav.update(
            {
                "record_family": "fund_economics_observation",
                "source_structure_type": "TABLE",
                "source_section": "Results",
                "source_table": "Returns",
                "source_row_label": "Fund A",
                "source_column_label": "NAV",
                "subject_name": "Fund A",
                "metric_category": "nav",
                "metric_name": "Net Asset Value",
                "metric_value_raw": "5.0%",
                "unit": "%",
                "value_scope": "unstated",
                "evidence_quote": "Fund A 5.0%",
            }
        )
        rows.append(nav)
        for row in rows:
            row["contract_version"] = stamp
        return sorted(rows, key=workflow.record_sort_key)

    def _final_with_a_blank_nav_scope(self, stamp: str, *, blank: bool = True) -> None:
        """An adjudicated final carrying a NAV row with no `value_scope`.

        Built through the ordinary flow and then emptied, because the live gate
        refuses a blank qualified dimension at every writing step. The finals in
        the corpus are exactly this shape: written before the column existed,
        and carrying the stamp that says so.
        """

        for agent in ("A", "B"):
            record_path, coverage_path = workflow.candidate_paths(
                "02-performance", "SRC999", agent
            )
            workflow.write_csv(record_path, RECORD_COLUMNS, self._nav_records(agent, stamp))
            coverage = self.candidate_coverage(agent)
            coverage[0].update(
                {
                    "contract_version": stamp,
                    "expected_observation_count": "3",
                    "records_written": "3",
                    "relevant_record_families": (
                        "document_context | fund_economics_observation | "
                        "performance_observation"
                    ),
                }
            )
            workflow.write_csv(coverage_path, COVERAGE_COLUMNS, coverage)
            workflow.claim_command("02-performance", agent, "test-model", "unit-test")
        self._resolve_every_reviewed_pair(expected_rows=3)
        workflow.build_final_command("02-performance", "SRC999")
        record_path, _ = workflow.final_paths("02-performance", "SRC999")
        records = workflow.read_strict_csv(record_path, RECORD_COLUMNS)
        for row in records:
            if blank and row["metric_category"] == "nav":
                row["value_scope"] = ""
        workflow.write_csv(record_path, RECORD_COLUMNS, records)

    def test_historical_blank_qualifiers_block_publication(self) -> None:
        """A historical stamp cannot exempt an unreviewed dimension."""
        worklist_root = self._active_worklist("SRC999")
        with mock.patch.object(workflow, "WORKLIST_ROOT", worklist_root):
            self._final_with_a_blank_nav_scope(self.OLD_STAMP)
            _, _, errors = workflow.validate_final_data("02-performance", "SRC999")
            self.assertTrue(any("value_scope" in error for error in errors), errors)
            records, _, errors, backlog, _ = workflow.collect_round("02-performance", "active")
            self.assertTrue(any("value_scope" in error for error in errors), errors)
            self.assertEqual(records, [])
            self.assertEqual(backlog, [])
            with self.assertRaisesRegex(workflow.ContractFailure, "value_scope"):
                workflow.publish_round("02-performance", "active")

    def test_a_blank_the_row_contract_carries_blocks_publication(self) -> None:
        """A reader stamped at the current contract was asked and answered nothing.

        The same blank cell, the same category, one stamp later: `2026-09-01.2`
        carries `value_scope`, so the blank is a hard error and the round stops.
        """

        worklist_root = self._active_worklist("SRC999")
        with mock.patch.object(workflow, "WORKLIST_ROOT", worklist_root):
            self._final_with_a_blank_nav_scope(CONTRACT_VERSION)
            _, _, errors, backlog, _ = workflow.collect_round("02-performance", "active")
            self.assertEqual(backlog, [])
            self.assertTrue(
                any("requires value_scope" in error for error in errors), errors
            )
            with self.assertRaisesRegex(workflow.ContractFailure, "requires value_scope"):
                workflow.publish_round("02-performance", "active")

    def test_a_document_with_no_final_is_named_and_blocks_nothing(self) -> None:
        """A worklisted document nobody adjudicated is a name, not a failure.

        `collect_round` read every assigned document through `validate_final_data`
        and reported a missing final as a contract failure, so five unstarted
        documents blocked the whole corpus.
        """

        worklist_root = self._active_worklist("SRC999", "SRC998")
        with mock.patch.object(workflow, "WORKLIST_ROOT", worklist_root):
            self._final_with_a_blank_nav_scope(self.OLD_STAMP, blank=False)
            records, _, errors, _, unfinished = workflow.collect_round(
                "02-performance", "active"
            )
            self.assertEqual(errors, [])
            self.assertEqual(unfinished, ["02-performance/SRC998"])
            self.assertEqual({row["file_id"] for row in records}, {"SRC999"})

    def test_the_published_ledger_is_the_table_the_release_stage_re_derives(self) -> None:
        """The ledger on disk and the finals in scope state one backlog.

        Publication writes it while it validates each final; stage 05 reads the
        finals again and rebuilds the table from the same rule, so a ledger left
        behind by an older publication cannot pass as the live list.
        """

        worklist_root = self._active_worklist("SRC999", "SRC998")
        with mock.patch.object(workflow, "WORKLIST_ROOT", worklist_root):
            self._final_with_a_blank_nav_scope(self.OLD_STAMP, blank=False)
            workflow.publish_round("02-performance", "active")
            _, _, backlog, unfinished = workflow.publish_corpus("active")
        self.assertEqual(unfinished, ["02-performance/SRC998"])
        ledger = workflow.qualifier_backlog_ledger()
        with ledger.open("r", encoding="utf-8-sig", newline="") as handle:
            published = list(csv.DictReader(handle))
        self.assertEqual(published, backlog)
        with (
            mock.patch.object(release, "WORKLIST_ROOT", worklist_root),
            mock.patch.object(combine_extracted_raw, "WORKING_DIR", self.working),
        ):
            self.assertEqual(release.scope_qualifier_backlog(), published)
            release.require_backlog_ledger(published)

    def test_a_backlog_policy_the_publisher_does_not_implement_is_refused(self) -> None:
        """The policy is a matrix row, read the way `republish_attribution` is.

        A value publication has no code for is refused before a document is
        opened, so the matrix cannot quietly change what publication does.
        """

        resolve = workflow.matrices.resolve

        def named(name: str, input_value: str, *args: object, **kwargs: object) -> str:
            if (name, input_value) == (workflow.RECORD_STATUS_POLICY, "qualifier_backlog"):
                return "refused_and_counted"
            return resolve(name, input_value, *args, **kwargs)

        with mock.patch.object(workflow.matrices, "resolve", side_effect=named):
            with self.assertRaisesRegex(
                workflow.ContractFailure, "unsupported qualifier_backlog"
            ):
                workflow.qualifier_backlog_policy()
            with self.assertRaisesRegex(
                workflow.ContractFailure, "unsupported qualifier_backlog"
            ):
                workflow.collect_round("02-performance", "active")

    def test_a_key_new_to_the_round_takes_the_derived_model(self) -> None:
        rows = [{"file_id": "SRC999", "source_page": "1", "source_row_label": "Fund A",
                 "source_column_label": "1 Year", "source_occurrence": "1",
                 "record_family": "performance_observation", "extractor_model": "derived"}]
        published = {("SRC999", "1", "Other", "1 Year", "1", "performance_observation"): "old"}
        workflow.freeze_attribution(rows, published, workflow.ATTRIBUTION_RECORD_KEY)
        self.assertEqual(rows[0]["extractor_model"], "derived")


class CombineRoundMembershipTests(unittest.TestCase):
    """A2-05: stage 10 and `publish` read the same worklist.

    `combine_round` used to take every subdirectory of the route folder and
    refuse the whole route when one of them had no `records-final.csv`, while
    `publish_round` took its documents from the scope worklist. A document
    parked with two candidate lanes and no final therefore blocked a route that
    published fine at the other end of the pipeline.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.route = root / "ledgers" / "working" / "pdf-extraction-csv" / "02-performance"
        for file_id, finished in (("SRC001", True), ("SRC002", False)):
            folder = self.route / file_id
            folder.mkdir(parents=True)
            (folder / "records-a.csv").write_text("x\n", encoding="utf-8")
            (folder / "records-b.csv").write_text("x\n", encoding="utf-8")
            if finished:
                (folder / "records-final.csv").write_text(
                    "file_id,value\nSRC001,1\n", encoding="utf-8"
                )
        worklists = root / "worklists"
        (worklists / "active").mkdir(parents=True)
        (worklists / "active" / "02-performance.csv").write_text(
            "work_order,file_id\n1,SRC001\n2,SRC002\n", encoding="utf-8"
        )
        for patcher in (
            mock.patch.object(workflow, "WORKLIST_ROOT", worklists),
            mock.patch.object(combine_extracted_raw, "WORKING_DIR", self.route.parent),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_an_unfinished_worklisted_document_is_named_and_skipped(self) -> None:
        header, rows, documents, unfinished = combine_extracted_raw.combine_round(
            self.route, "active"
        )
        self.assertEqual(header, ["file_id", "value"])
        self.assertEqual(rows, [["SRC001", "1"]])
        self.assertEqual(documents, ["SRC001"])
        self.assertEqual(unfinished, ["SRC002"])

    def test_a_document_outside_the_worklist_is_not_part_of_the_round(self) -> None:
        stray = self.route / "SRC999"
        stray.mkdir()
        (stray / "records-final.csv").write_text("file_id,value\nSRC999,9\n", encoding="utf-8")
        _, rows, documents, unfinished = combine_extracted_raw.combine_round(
            self.route, "active"
        )
        self.assertEqual(documents, ["SRC001"])
        self.assertEqual(unfinished, ["SRC002"])
        self.assertEqual(rows, [["SRC001", "1"]])

    def test_documents_are_combined_in_file_id_order_not_worklist_order(self) -> None:
        # publish_round sorts its round by file_id; a raw file in worklist
        # order holds the same rows in another sequence, and stage 15 compares
        # the two row for row. Route 01's worklist listed SRC152 before SRC034
        # and the release refused the route on 2026-09-02.
        later = self.route / "SRC000"
        later.mkdir()
        (later / "records-final.csv").write_text("file_id,value\nSRC000,0\n", encoding="utf-8")
        (Path(workflow.WORKLIST_ROOT) / "active" / "02-performance.csv").write_text(
            "work_order,file_id\n1,SRC001\n2,SRC002\n3,SRC000\n", encoding="utf-8"
        )
        _, rows, documents, unfinished = combine_extracted_raw.combine_round(
            self.route, "active"
        )
        self.assertEqual(documents, ["SRC000", "SRC001"])
        self.assertEqual(rows, [["SRC000", "0"], ["SRC001", "1"]])
        self.assertEqual(unfinished, ["SRC002"])


class RestoreAttributionTests(unittest.TestCase):
    """A republish that re-derived attribution is undone key by key."""

    ROUTE = "02-performance"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        patcher = mock.patch.object(workflow, "PROJECT_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def row(self, label: str, value: str, model: str) -> dict[str, str]:
        row = {column: "" for column in workflow.ROUND_RECORD_COLUMNS}
        row.update(
            {
                "contract_version": CONTRACT_VERSION,
                "file_id": "SRC999",
                "route": self.ROUTE,
                "record_family": "performance_observation",
                "source_page": "1",
                "source_row_label": label,
                "source_column_label": "1 Year",
                "source_occurrence": "1",
                "metric_value_raw": value,
                "extractor_model": model,
            }
        )
        return row

    def test_an_unchanged_key_takes_back_its_prior_model(self) -> None:
        prior = [
            self.row("Fund A", "5.0%", "claude-sonnet-5+gpt-5"),
            self.row("Fund B", "6.0%", "claude-sonnet-5+gpt-5"),
        ]
        # Fund A is the same printed cell under a model no lane re-read it with.
        # Fund B was read again, which is why its value moved, so the model that
        # read it is the current one.
        current = [
            self.row("Fund A", "5.0%", "claude-fable-5"),
            self.row("Fund B", "6.5%", "claude-fable-5"),
        ]
        path = workflow.round_records(self.ROUTE)
        workflow.write_csv(path, workflow.ROUND_RECORD_COLUMNS, current)
        with mock.patch.object(
            workflow, "_prior_publication", return_value=(Path("archived.csv"), prior)
        ):
            restored, archived = workflow.restore_attribution(self.ROUTE)
        self.assertEqual(restored, {"SRC999": 1})
        self.assertEqual(archived, Path("archived.csv"))
        written = workflow.read_strict_csv(path, workflow.ROUND_RECORD_COLUMNS)
        models = {row["source_row_label"]: row["extractor_model"] for row in written}
        self.assertEqual(models["Fund A"], "claude-sonnet-5+gpt-5")
        self.assertEqual(models["Fund B"], "claude-fable-5")
        self.assertEqual(
            [row["metric_value_raw"] for row in written],
            ["5.0%", "6.5%"],
            "the restore writes attribution and no other field",
        )

    def test_a_round_already_carrying_its_prior_models_is_left_alone(self) -> None:
        rows = [self.row("Fund A", "5.0%", "claude-sonnet-5+gpt-5")]
        path = workflow.round_records(self.ROUTE)
        workflow.write_csv(path, workflow.ROUND_RECORD_COLUMNS, rows)
        before = path.read_bytes()
        with mock.patch.object(
            workflow, "_prior_publication", return_value=(Path("archived.csv"), rows)
        ):
            restored, _ = workflow.restore_attribution(self.ROUTE)
        self.assertEqual(restored, {})
        self.assertEqual(path.read_bytes(), before)

    def test_a_round_with_no_archived_publication_is_refused(self) -> None:
        path = workflow.round_records(self.ROUTE)
        workflow.write_csv(
            path, workflow.ROUND_RECORD_COLUMNS, [self.row("Fund A", "5.0%", "claude-fable-5")]
        )
        with mock.patch.object(workflow, "_prior_publication", return_value=(None, [])):
            with self.assertRaises(workflow.ContractFailure):
                workflow.restore_attribution(self.ROUTE)


if __name__ == "__main__":
    unittest.main()
