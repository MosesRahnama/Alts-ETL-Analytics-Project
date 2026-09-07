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
    COMMON_METRIC_FIELDS,
    COMMON_TERM_FIELDS,
    CONTEXT_FIELDS,
    CONTRACT_VERSION,
    COVERAGE_COLUMNS,
    DEFINITION_FIELDS,
    DOC_TYPE_FAMILIES,
    FAMILY_CONTRACTS,
    KNOWN_CONTRACT_VERSIONS,
    METRIC_CATEGORIES,
    PAGE_STATUSES,
    RECORD_COLUMNS,
    RECORD_HEADERS_BY_VERSION,
    REFERENCE_EVIDENCE_CLASSES,
    ROUTES,
    SOURCE_STRUCTURE_TYPES,
    SUBJECT_TYPES,
    TERM_CATEGORIES,
    allowed_metric_categories,
    allowed_term_categories,
    contract_version_key,
)
from src.common import matrices
from src.catalog.simple_pdf_extraction.field_guide import FIELD_DESCRIPTIONS, FIELD_GROUPS


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
        self.assertEqual(len(RECORD_COLUMNS), 47)

    def test_contract_versions_use_numeric_revision_order(self) -> None:
        self.assertGreater(
            contract_version_key("2026-09-01.10"),
            contract_version_key("2026-09-01.2"),
        )
        self.assertEqual(
            list(KNOWN_CONTRACT_VERSIONS),
            sorted(KNOWN_CONTRACT_VERSIONS, key=contract_version_key),
        )
        for earlier, later in zip(KNOWN_CONTRACT_VERSIONS, KNOWN_CONTRACT_VERSIONS[1:]):
            self.assertTrue(
                set(RECORD_HEADERS_BY_VERSION[earlier]).issubset(
                    RECORD_HEADERS_BY_VERSION[later]
                )
            )
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            contract_version_key("2026-09-01.two")

    def test_field_guide_covers_every_contract_column(self) -> None:
        grouped = {
            field
            for _, _, fields in FIELD_GROUPS
            for field in fields
        }
        self.assertEqual(grouped, set(RECORD_COLUMNS))
        self.assertEqual(set(FIELD_DESCRIPTIONS), set(RECORD_COLUMNS))

    def test_prompts_are_complete_per_route_and_bind_atomic_grain(self) -> None:
        from src.catalog.simple_pdf_extraction.build_csv_pipeline import BENCH_ROUTES
        for route in ROUTES:
            prompts = sorted((PROMPT_ROOT / route).glob("[0-9][0-9]-*.md"))
            # Two extractors, two adjudicators, and the definition-backfill
            # brief, plus the comparison lanes on any route running a model
            # bake-off.
            expected = 5 + (len(BENCH_AGENTS) if route in BENCH_ROUTES else 0)
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
                patch.object(
                    csv_workflow,
                    "final_paths",
                    return_value=(folder / "records-final.csv", folder / "coverage-final.csv"),
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

    def test_lane_state_is_done_once_adjudication_wrote_the_final(self) -> None:
        """A finished document is not re-audited under a later contract.

        The lane files of every published document predate the qualifier
        columns, so the audit failed them and lane-check read the finished
        half of each route as IN_PROGRESS. Two lanes sent to "work the one
        not marked DONE" rewrote published documents' candidates.
        """
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            record_path = folder / "records-b.csv"
            coverage_path = folder / "coverage-b.csv"
            record_path.write_text("header\nold-contract-row\n", encoding="utf-8", newline="\n")
            coverage_path.write_text("header\npage-covered\n", encoding="utf-8", newline="\n")
            final_coverage = folder / "coverage-final.csv"
            final_coverage.write_text("header\npage-covered\n", encoding="utf-8", newline="\n")
            with (
                patch.object(
                    csv_workflow,
                    "candidate_paths",
                    return_value=(record_path, coverage_path),
                ),
                patch.object(
                    csv_workflow,
                    "final_paths",
                    return_value=(folder / "records-final.csv", final_coverage),
                ),
                patch.object(
                    csv_workflow,
                    "audit_file_command",
                    side_effect=csv_workflow.ContractFailure("qualified category requires value_scope"),
                ) as audit,
                patch.object(csv_workflow, "validate_final_data", return_value=([], [], [])) as final_check,
            ):
                self.assertEqual(
                    csv_workflow._lane_state("02-performance", "SRC035", "B"),
                    "DONE",
                )
                audit.assert_not_called()
                final_check.assert_called_once_with("02-performance", "SRC035")

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

    def test_a_paid_in_capital_multiple_is_distinct_from_the_amount(self) -> None:
        """A PIC column printed beside TVPI, RVPI, and DPI is a multiple.

        SRC457 prints PIC in the multiples block, and its own footnote reads
        that PIC multiples may exceed 1.00 because capital is recycled. Those
        76 values carried the amount category, which reads a ratio as money.
        """
        from src.catalog.simple_pdf_extraction.csv_wide_contract import (
            METRIC_DEFINITIONS,
        )

        self.assertIn("paid_in_capital_multiple", METRIC_CATEGORIES)
        self.assertEqual(METRIC_DEFINITIONS["paid_in_capital_multiple"][1], "x")
        self.assertEqual(METRIC_DEFINITIONS["paid_in_capital"][1], "currency")

        # The adjudicated final is where the correction lives; the published
        # corpus is downstream of it and lags a round in progress.
        final = Path(
            "ledgers/working/pdf-extraction-csv/04-quarterly-report/SRC457/"
            "records-final.csv"
        )
        if not final.is_file():
            self.skipTest("SRC457 is not adjudicated in this tree")
        with final.open(encoding="utf-8-sig", newline="") as handle:
            rows = [
                row
                for row in csv.DictReader(handle)
                if row["source_column_label"].strip().upper() == "PIC"
            ]
        self.assertTrue(rows, "SRC457 publishes no PIC column")
        for row in rows:
            self.assertEqual(
                row["metric_category"],
                "paid_in_capital_multiple",
                f"PIC cell on page {row['source_page']} reads as an amount",
            )

    def test_a_merge_on_a_one_sided_pair_credits_one_reader(self) -> None:
        """A row only one lane ever read cannot report two readers.

        676 published rows credited A+B+ADJUDICATOR on A_ONLY and B_ONLY pairs,
        which overstates how much of the corpus two independent readers agreed
        on.
        """
        from src.catalog.simple_pdf_extraction.csv_workflow import _outcome

        self.assertEqual(_outcome("MERGE_A_ONLY_outcome")[0], "A+ADJUDICATOR")
        self.assertEqual(_outcome("MERGE_B_ONLY_outcome")[0], "B+ADJUDICATOR")
        self.assertEqual(_outcome("MERGE_outcome")[0], "A+B+ADJUDICATOR")

        for folder in sorted(
            Path("ledgers/working/pdf-extraction-csv").glob("*/*/pair-index.csv")
        ):
            resolution_path = folder.parent / "resolution.csv"
            final_path = folder.parent / "records-final.csv"
            if not (resolution_path.is_file() and final_path.is_file()):
                continue
            with folder.open(encoding="utf-8-sig", newline="") as handle:
                one_sided = {
                    row["pair_id"]
                    for row in csv.DictReader(handle)
                    if row["pair_status"] in ("A_ONLY", "B_ONLY")
                }
            with resolution_path.open(encoding="utf-8-sig", newline="") as handle:
                merged_one_sided = sum(
                    1
                    for row in csv.DictReader(handle)
                    if row["decision"] == "MERGE" and row["pair_id"] in one_sided
                )
            if not merged_one_sided:
                continue
            with final_path.open(encoding="utf-8-sig", newline="") as handle:
                agents = [row["source_agents"] for row in csv.DictReader(handle)]
            self.assertGreaterEqual(
                agents.count("A+ADJUDICATOR") + agents.count("B+ADJUDICATOR"),
                merged_one_sided,
                f"{folder.parent.name} publishes fewer one-sided merges than it decided",
            )

    def test_contract_version_is_embedded_in_master_schema(self) -> None:
        text = (Path("data/schemas/MASTER-EXTRACTION-SCHEMA.md")).read_text(
            encoding="utf-8"
        )
        self.assertIn(CONTRACT_VERSION, text)
        self.assertIn("One populated allowed value cell produces one row", text)

    # A1-07: every closed vocabulary the validator enforces lives in a matrix.

    def test_every_closed_vocabulary_is_read_from_a_matrix(self) -> None:
        """`EVIDENCE_CLASSES` read a matrix while the four enumerations beside
        it and the four family field sets were Python literals, so half the
        contract's closed vocabularies could not be changed without an edit to
        the module the matrices exist to empty."""

        for context, values in (
            ("source_structure_type", SOURCE_STRUCTURE_TYPES),
            ("page_status", PAGE_STATUSES),
            ("subject_type", SUBJECT_TYPES),
            ("reference_evidence_class", REFERENCE_EVIDENCE_CLASSES),
        ):
            with self.subTest(context=context):
                rows = matrices.rows_in("dimension-values", context)
                self.assertTrue(rows)
                self.assertEqual(
                    tuple(row["input_value"] for row in rows), tuple(values),
                    "the matrix and the contract must agree on the values and their order",
                )

    def test_every_family_field_set_is_read_from_a_matrix(self) -> None:
        for context, values in (
            ("common_metric_fields", COMMON_METRIC_FIELDS),
            ("common_term_fields", COMMON_TERM_FIELDS),
            ("definition_fields", DEFINITION_FIELDS),
            ("context_fields", CONTEXT_FIELDS),
        ):
            with self.subTest(context=context):
                rows = matrices.rows_in("dimension-values", context)
                self.assertEqual({row["input_value"] for row in rows}, set(values))
                self.assertLessEqual(set(values), set(RECORD_COLUMNS))

    def test_the_qualifier_dimensions_read_only_the_qualifier_context(self) -> None:
        """The vocabularies added beside them must not become qualifier
        dimensions: `method`, `fee_basis`, and `value_scope` are the three the
        metric vocabulary can require."""

        self.assertEqual(
            set(csv_workflow.QUALIFIER_DIMENSIONS), {"method", "fee_basis", "value_scope"}
        )

    # A1-08: an evidence cell names the line that defines the item.

    def test_matrix_evidence_lines_point_at_the_thing_they_cite(self) -> None:
        """A cell citing a line that holds something else, or a line past the
        end of the file, cannot be checked by the reader it exists for. All 42
        original record columns cited the `BENCH_AGENTS` line and pair-key.csv
        cited line 756 of a 708-line file."""

        module = Path("src/catalog/simple_pdf_extraction/csv_wide_contract.py")
        lines = module.read_text(encoding="utf-8").splitlines()
        expected = {
            "record-columns": ("RECORD_COLUMNS", "RECORD_COLUMNS"),
            "pair-key": ("record_key", "def record_key("),
        }
        for name, (_, defining) in expected.items():
            for row in matrices.load(name):
                evidence = row["evidence"]
                if not evidence.startswith(module.as_posix() + ":"):
                    continue
                number = int(evidence.rsplit(":", 1)[1])
                self.assertLessEqual(number, len(lines), f"{name}: {evidence}")
                if row["input_value"] == "pair_id_format":
                    self.assertTrue(lines[number - 1].startswith("def record_pair_id("))
                else:
                    self.assertTrue(
                        lines[number - 1].startswith(defining),
                        f"{name} row {row['input_value']!r} cites {evidence}, which holds "
                        f"{lines[number - 1]!r}",
                    )


if __name__ == "__main__":
    unittest.main()
