from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.catalog.simple_pdf_extraction import build_csv_pipeline, csv_workflow

from src.catalog.simple_pdf_extraction.build_csv_pipeline import (
    INSTRUCTION_ROOT,
    PROMPT_ROOT,
    ROUTING_PATH,
    SCOPE_PATH,
    WORKLIST_ROOT,
    verify_generated,
)
from src.catalog.simple_pdf_extraction.build_csv_pipeline import corpus_size
from src.catalog.simple_pdf_extraction.csv_wide_contract import (
    BENCH_AGENTS,
    CANONICAL_DOC_TYPES,
    CONTRACT_VERSION,
    COVERAGE_COLUMNS,
    DOC_TYPE_FAMILIES,
    FAMILY_CONTRACTS,
    METRIC_CATEGORIES,
    RECORD_COLUMNS,
    ROUTES,
    TERM_CATEGORIES,
    allowed_metric_categories,
    allowed_term_categories,
)


class WideExtractionContractTests(unittest.TestCase):
    def read_rows(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def read_header(self, path: Path) -> list[str]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle))

    def test_generated_contract_verifies(self) -> None:
        self.assertEqual(verify_generated(), [])

    def test_routing_is_complete_and_unique(self) -> None:
        rows = self.read_rows(ROUTING_PATH)
        self.assertEqual(len(rows), corpus_size())
        self.assertEqual(len({row["file_id"] for row in rows}), corpus_size())
        self.assertEqual(
            {row["canonical_doc_type"] for row in rows}, set(CANONICAL_DOC_TYPES)
        )
        for row in rows:
            self.assertIn(row["route"], ROUTES)
            self.assertIn(row["canonical_doc_type"], ROUTES[row["route"]])
            self.assertIn(row["routing_status"], {"MATCH", "RATIFIED_HEADER_OVERRIDE"})

    def test_dispatch_scopes_do_not_overlap(self) -> None:
        scope = self.read_rows(SCOPE_PATH)
        self.assertEqual(len(scope), corpus_size())
        scheduled: list[str] = []
        for folder in ("active", "deferred", "reference"):
            for route in ROUTES:
                scheduled.extend(
                    row["file_id"]
                    for row in self.read_rows(WORKLIST_ROOT / folder / f"{route}.csv")
                )
        self.assertEqual(len(scheduled), len(set(scheduled)))
        expected = {
            row["file_id"]
            for row in scope
            if row["dispatch_scope"] in {"ACTIVE", "DEFERRED", "REFERENCE"}
        }
        self.assertEqual(set(scheduled), expected)

    def test_wide_headers_replace_eav_header(self) -> None:
        self.assertEqual(
            self.read_header(INSTRUCTION_ROOT / "CSV-TEMPLATE.csv"),
            list(RECORD_COLUMNS),
        )
        self.assertEqual(
            self.read_header(INSTRUCTION_ROOT / "COVERAGE-TEMPLATE.csv"),
            list(COVERAGE_COLUMNS),
        )
        self.assertNotIn("field_name", RECORD_COLUMNS)
        self.assertNotIn("record_label", RECORD_COLUMNS)
        self.assertEqual(len(RECORD_COLUMNS), 42)

    def test_prompts_are_complete_per_route_and_bind_atomic_grain(self) -> None:
        from src.catalog.simple_pdf_extraction.build_csv_pipeline import BENCH_ROUTES
        for route in ROUTES:
            prompts = sorted((PROMPT_ROOT / route).glob("[0-9][0-9]-*.md"))
            # Two extractors and two adjudicators, plus the comparison lanes
            # on any route running a model bake-off.
            expected = 4 + (len(BENCH_AGENTS) if route in BENCH_ROUTES else 0)
            self.assertEqual(len(prompts), expected, route)
            for prompt in prompts:
                text = prompt.read_text(encoding="utf-8")
                self.assertIn("one populated allowed value cell", text.casefold())
                self.assertNotIn("one row = one field occurrence", text.casefold())
                self.assertNotIn("record_label", text)
                self.assertNotIn("field_name,value_raw", text)

    def test_prompt_rebuild_preserves_route_readmes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            prompt_root = Path(temporary)
            for route in ROUTES:
                folder = prompt_root / route
                folder.mkdir(parents=True)
                (folder / "README.md").write_text(
                    f"# {route}\n", encoding="utf-8", newline="\n"
                )
                (folder / "99-EXTRACTOR-Z.md").write_text(
                    "retired lane\n", encoding="utf-8", newline="\n"
                )
            with patch.object(build_csv_pipeline, "PROMPT_ROOT", prompt_root):
                build_csv_pipeline.write_prompts()
            for route in ROUTES:
                folder = prompt_root / route
                self.assertEqual(
                    (folder / "README.md").read_text(encoding="utf-8"),
                    f"# {route}\n",
                )
                self.assertFalse((folder / "99-EXTRACTOR-Z.md").exists())

    def test_lane_state_accepts_complete_coverage_with_zero_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            record_path = folder / "records-a.csv"
            coverage_path = folder / "coverage-a.csv"
            record_path.write_text("header\n", encoding="utf-8", newline="\n")
            coverage_path.write_text(
                "header\npage-covered\n", encoding="utf-8", newline="\n"
            )
            with (
                patch.object(
                    csv_workflow,
                    "candidate_paths",
                    return_value=(record_path, coverage_path),
                ),
                patch.object(csv_workflow, "audit_file_command") as audit,
            ):
                self.assertEqual(
                    csv_workflow._lane_state("01-financials", "SRC147", "A"),
                    "DONE",
                )
                audit.assert_called_once_with(
                    "01-financials", "SRC147", "A", quiet=True,
                    require_images=False,
                )

    def test_audit_rejects_contract_drift_before_completeness_checks(self) -> None:
        with (
            patch.object(csv_workflow, "routing_for", return_value={}),
            patch.object(
                csv_workflow,
                "validate_candidate_data",
                return_value=([], [], ["source_sha256 differs from routing"]),
            ),
        ):
            with self.assertRaisesRegex(
                csv_workflow.ContractFailure,
                "Candidate validation failed before completeness audit",
            ):
                csv_workflow.audit_file_command(
                    "01-financials", "SRC147", "A", quiet=True,
                    require_images=False,
                )

    def test_final_state_rejects_invalid_adjudicated_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "coverage-final.csv").write_text(
                "header\npage-covered\n", encoding="utf-8", newline="\n"
            )
            with (
                patch.object(csv_workflow, "file_folder", return_value=folder),
                patch.object(
                    csv_workflow,
                    "validate_final_data",
                    return_value=([], [], ["source_sha256 differs from routing"]),
                ),
            ):
                self.assertFalse(
                    csv_workflow._final_done("01-financials", "SRC147")
                )

    def test_comparison_state_accepts_zero_observation_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "pair-index.csv").write_text(
                "header\n", encoding="utf-8", newline="\n"
            )
            (folder / "coverage-diff.csv").write_text(
                "header\npage-compared\n", encoding="utf-8", newline="\n"
            )
            self.assertTrue(csv_workflow._comparison_done(folder))

    def test_one_vocabulary_and_family_routing(self) -> None:
        """One term vocabulary for every term family; one metric vocabulary for
        every metric family; the document type routes families, never names."""
        legal = set(allowed_term_categories("legal_term", "PPM"))
        self.assertEqual(legal, set(TERM_CATEGORIES))
        self.assertEqual(set(allowed_term_categories("subscription_reference", "Subscription")), legal)
        self.assertEqual(allowed_term_categories("performance_observation"), ())
        self.assertEqual(set(allowed_metric_categories("performance_observation")), set(METRIC_CATEGORIES))
        self.assertEqual(set(allowed_metric_categories("ddq_quantitative_observation")), set(METRIC_CATEGORIES))
        self.assertEqual(allowed_metric_categories("legal_term"), ())
        for core in ("tvpi", "moic", "irr", "nav", "capital_call", "pme"):
            self.assertIn(core, METRIC_CATEGORIES)
        for core in ("carried_interest", "waterfall", "clawback", "key_person", "mfn"):
            self.assertIn(core, TERM_CATEGORIES)
        self.assertEqual(len(METRIC_CATEGORIES), len(set(METRIC_CATEGORIES)))
        self.assertNotIn("legal_clause", DOC_TYPE_FAMILIES["PPM"])
        self.assertNotIn("market_observation", FAMILY_CONTRACTS)

    def test_contract_version_is_embedded_in_master_schema(self) -> None:
        text = (Path("data/schemas/MASTER-EXTRACTION-SCHEMA.md")).read_text(
            encoding="utf-8"
        )
        self.assertIn(CONTRACT_VERSION, text)
        self.assertIn("One populated allowed value cell produces one row", text)


if __name__ == "__main__":
    unittest.main()
