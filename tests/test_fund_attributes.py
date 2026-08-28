"""Fund-constant attribute harvest, spelling collapse, apply, and dispatch paths."""

from __future__ import annotations

import csv
import re
import tempfile
import unittest
from pathlib import Path

from src.catalog.simple_pdf_extraction import fund_attributes as fa

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = PROJECT_ROOT / "instructions" / "02-fund-mapping" / "00-OPERATOR-RUNBOOK.md"
SOURCE = Path(fa.__file__)


def parser_commands() -> set[str]:
    text = SOURCE.read_text(encoding="utf-8")
    return set(re.findall(r'sub\.add_parser\(\s*"([a-z-]+)"', text))


def write_rows(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class WritesRegistryTests(unittest.TestCase):
    def test_every_command_declares_where_it_writes(self) -> None:
        commands = parser_commands()
        self.assertTrue(commands)
        self.assertEqual(commands - set(fa.WRITES), set())
        self.assertEqual(set(fa.WRITES) - commands, set())

    def test_the_runbook_names_each_declared_target(self) -> None:
        runbook = RUNBOOK.read_text(encoding="utf-8")
        for command, targets in fa.WRITES.items():
            for target in targets:
                self.assertIn(
                    target,
                    runbook,
                    f"the runbook does not name where {command} writes: {target}",
                )


class LiveCorpusTests(unittest.TestCase):
    def test_the_matrix_covers_every_resolved_fund(self) -> None:
        observations = fa.read_csv(fa.FACT_OBSERVATION)
        funds = {
            row["subject_entity_id"]
            for row in observations
            if row.get("subject_type") == "fund" and row.get("subject_entity_id", "").startswith("FUND_")
        }
        matrix = {row["fund_id"] for row in fa.read_csv(fa.MATRIX)}
        self.assertEqual(funds, matrix)
        self.assertEqual(len(matrix), 853)

    def test_dispatch_keeps_the_prompt_after_the_worksheet_is_empty(self) -> None:
        self.assertEqual(fa.dispatch(), 0)
        self.assertTrue(fa.DISPATCH_PROMPT.is_file())
        self.assertIn("standing brief", fa.DISPATCH_PROMPT.read_text(encoding="utf-8"))
        self.assertEqual(fa.dispatch(check=True), 0)


class ClassifyTests(unittest.TestCase):
    def test_a_single_printed_vintage_is_unique(self) -> None:
        value, status, variants = fa.classify("vintage_year", fa.Counter({"2014": 3}))
        self.assertEqual(value, "2014")
        self.assertEqual(status, "unique")
        self.assertEqual(variants, "2014")

    def test_hyphen_and_space_collapse_to_one_strategy(self) -> None:
        value, status, _ = fa.classify(
            "strategy", fa.Counter({"Value-Added": 2, "Value Add": 1})
        )
        self.assertEqual(status, "unique_canonical")
        self.assertIn(value, {"Value-Added", "Value Add"})

    def test_investments_suffix_collapses_private_equity(self) -> None:
        value, status, _ = fa.classify(
            "asset_class",
            fa.Counter({"Private Equity": 4, "Private Equity Investments": 1}),
        )
        self.assertEqual(status, "unique_canonical")
        self.assertEqual(value, "Private Equity")

    def test_a_subtype_stays_a_conflict(self) -> None:
        value, status, variants = fa.classify(
            "strategy",
            fa.Counter({
                "Early Secondary Investments": 1,
                "Secondary Investments": 1,
            }),
        )
        self.assertEqual(value, "")
        self.assertEqual(status, "conflict")
        self.assertIn("Early Secondary Investments", variants)

    def test_no_printed_value_stays_none(self) -> None:
        value, status, variants = fa.classify("geography", fa.Counter())
        self.assertEqual((value, status, variants), ("", "none", ""))


class HarvestApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.obs = root / "fact_observation.csv"
        self.dim = root / "dim_entity.csv"
        self.matrix = root / "fund-attributes-matrix.csv"
        self.conflicts = root / "attribute-conflicts.csv"
        self.worksheet = root / "worksheets" / "attribute-conflicts.csv"
        self.inherit = root / "attribute-inherit.csv"
        self.periods = root / "fund_periods.csv"
        self.master = root / "fund_master.csv"
        self.dispatch_dir = root / "attributes"
        self.dispatch_prompt = self.dispatch_dir / "ATTRIBUTE-NORMALIZER-01.md"
        write_rows(
            self.dim,
            ["entity_id", "entity_kind", "canonical_name"],
            [
                {"entity_id": "FUND_0001", "entity_kind": "fund", "canonical_name": "Alpha Fund"},
                {"entity_id": "FUND_0002", "entity_kind": "fund", "canonical_name": "Beta Fund"},
            ],
        )
        write_rows(
            self.obs,
            [
                "observation_id", "document_id", "source_page", "source_table",
                "subject_type", "subject_entity_id", "subject_standardized_name",
                "vintage_year", "strategy", "asset_class", "geography",
            ],
            [
                {
                    "observation_id": "o1", "document_id": "SRC001", "source_page": "9",
                    "source_table": "Investment Detail", "subject_type": "fund",
                    "subject_entity_id": "FUND_0001", "subject_standardized_name": "Alpha Fund",
                    "vintage_year": "2014", "strategy": "Opportunistic",
                    "asset_class": "Private Equity", "geography": "US",
                },
                {
                    "observation_id": "o2", "document_id": "SRC001", "source_page": "11",
                    "source_table": "Management Fees", "subject_type": "fund",
                    "subject_entity_id": "FUND_0001", "subject_standardized_name": "Alpha Fund",
                    "vintage_year": "", "strategy": "",
                    "asset_class": "", "geography": "",
                },
                {
                    "observation_id": "o3", "document_id": "SRC002", "source_page": "3",
                    "source_table": "Fees", "subject_type": "fund",
                    "subject_entity_id": "FUND_0002", "subject_standardized_name": "Beta Fund",
                    "vintage_year": "", "strategy": "Value-Added",
                    "asset_class": "", "geography": "",
                },
                {
                    "observation_id": "o4", "document_id": "SRC003", "source_page": "4",
                    "source_table": "Portfolio", "subject_type": "fund",
                    "subject_entity_id": "FUND_0002", "subject_standardized_name": "Beta Fund",
                    "vintage_year": "", "strategy": "Value Add",
                    "asset_class": "", "geography": "",
                },
                {
                    "observation_id": "o5", "document_id": "SRC001", "source_page": "1",
                    "source_table": "Totals", "subject_type": "asset_class",
                    "subject_entity_id": "", "subject_standardized_name": "Private Equity",
                    "vintage_year": "1999", "strategy": "Buyout",
                    "asset_class": "Private Equity", "geography": "Global",
                },
            ],
        )
        write_rows(
            self.periods,
            ["fund_period_id", "fund_id", "vintage_year", "strategy", "nav"],
            [
                {"fund_period_id": "FP1", "fund_id": "FUND_0001", "vintage_year": "", "strategy": "", "nav": "1"},
                {"fund_period_id": "FP2", "fund_id": "FUND_0002", "vintage_year": "", "strategy": "", "nav": "2"},
            ],
        )
        write_rows(
            self.master,
            ["fund_id", "fund_name", "vintage_year", "strategy"],
            [
                {"fund_id": "FUND_0001", "fund_name": "Alpha Fund", "vintage_year": "", "strategy": ""},
            ],
        )
        self.patches = {
            "FACT_OBSERVATION": self.obs,
            "DIM_ENTITY": self.dim,
            "MATRIX": self.matrix,
            "CONFLICTS": self.conflicts,
            "WORKSHEET": self.worksheet,
            "WORKSHEET_DIR": self.worksheet.parent,
            "INHERIT_LOG": self.inherit,
            "DISPATCH_DIR": self.dispatch_dir,
            "DISPATCH_PROMPT": self.dispatch_prompt,
        }
        self._original = {name: getattr(fa, name) for name in self.patches}
        for name, value in self.patches.items():
            setattr(fa, name, value)

    def tearDown(self) -> None:
        for name, value in self._original.items():
            setattr(fa, name, value)
        self.tmp.cleanup()

    def test_harvest_copies_across_tables_and_documents_without_inventing(self) -> None:
        self.assertEqual(fa.harvest(), 0)
        rows = {row["fund_id"]: row for row in fa.read_csv(self.matrix)}
        self.assertEqual(set(rows), {"FUND_0001", "FUND_0002"})
        alpha = rows["FUND_0001"]
        self.assertEqual(alpha["vintage_year"], "2014")
        self.assertEqual(alpha["vintage_year_status"], "unique")
        self.assertEqual(alpha["vintage_year_blank_rows"], "1")
        self.assertEqual(alpha["strategy"], "Opportunistic")
        beta = rows["FUND_0002"]
        self.assertEqual(beta["strategy_status"], "unique_canonical")
        self.assertEqual(beta["vintage_year_status"], "none")
        self.assertEqual(beta["vintage_year"], "")

    def test_apply_writes_evidence_and_leaves_canonical_rows_alone(self) -> None:
        fa.harvest()
        periods_before = self.periods.read_bytes()
        master_before = self.master.read_bytes()
        self.assertEqual(fa.apply(), 0)
        periods = {row["fund_id"]: row for row in fa.read_csv(self.periods)}
        self.assertEqual(periods["FUND_0001"]["vintage_year"], "")
        self.assertEqual(periods["FUND_0001"]["strategy"], "")
        self.assertEqual(periods["FUND_0002"]["strategy"], "")
        self.assertEqual(periods["FUND_0002"]["vintage_year"], "")
        master = fa.read_csv(self.master)[0]
        self.assertEqual(master["vintage_year"], "")
        self.assertEqual(master["strategy"], "")
        self.assertEqual(self.periods.read_bytes(), periods_before)
        self.assertEqual(self.master.read_bytes(), master_before)
        observations = {row["observation_id"]: row for row in fa.read_csv(self.obs)}
        self.assertEqual(observations["o2"]["vintage_year"], "")
        inherit = fa.read_csv(self.inherit)
        inherited = next(
            row
            for row in inherit
            if row["observation_id"] == "o2" and row["field"] == "vintage_year"
        )
        self.assertEqual(inherited["source_observation_id"], "o1")
        self.assertEqual(inherited["source_document_id"], "SRC001")
        self.assertEqual(inherited["source_evidence_page"], "9")
        self.assertFalse(any(row["observation_id"] == "o5" for row in inherit))

    def test_promotion_stamp_records_each_changed_cell(self) -> None:
        fa.harvest()
        lookup = fa.decided_lookup()
        evidence = fa.attribute_evidence_lookup()
        rows = [
            {"fund_period_id": "FP1", "fund_id": "FUND_0001", "vintage_year": "", "strategy": ""}
        ]
        filled, changes = fa.stamp_rows_with_changes(
            rows,
            lookup,
            evidence,
            target_table="fund_periods",
            record_id_field="fund_period_id",
        )
        self.assertEqual(filled, 2)
        self.assertEqual({row["field"] for row in changes}, {"vintage_year", "strategy"})
        self.assertTrue(all(row["old_value"] == "" for row in changes))
        self.assertTrue(all(row["source_observation_id"] == "o1" for row in changes))

    def test_merge_refuses_an_unprinted_spelling(self) -> None:
        fa.harvest()
        write_rows(
            self.worksheet,
            fa.MATRIX_HEADER,
            [
                {
                    **{key: "" for key in fa.MATRIX_HEADER},
                    "fund_id": "FUND_0001",
                    "strategy": "Venture",
                    "strategy_status": "decided",
                    "strategy_variants": "Opportunistic",
                }
            ],
        )
        with self.assertRaises(SystemExit):
            fa.merge_worksheet()

    def test_none_survives_reharvest_when_labels_still_disagree(self) -> None:
        write_rows(
            self.obs,
            [
                "observation_id", "document_id", "source_page", "source_table",
                "subject_type", "subject_entity_id", "subject_standardized_name",
                "vintage_year", "strategy", "asset_class", "geography",
            ],
            [
                {
                    "observation_id": "g1", "document_id": "SRC407", "source_page": "1",
                    "source_table": "SOI", "subject_type": "fund",
                    "subject_entity_id": "FUND_0001", "subject_standardized_name": "Alpha Fund",
                    "vintage_year": "", "strategy": "Early Secondary Investments",
                    "asset_class": "", "geography": "",
                },
                {
                    "observation_id": "g2", "document_id": "SRC407", "source_page": "4",
                    "source_table": "SOI", "subject_type": "fund",
                    "subject_entity_id": "FUND_0001", "subject_standardized_name": "Alpha Fund",
                    "vintage_year": "", "strategy": "Secondary Investments",
                    "asset_class": "", "geography": "",
                },
            ],
        )
        self.assertEqual(fa.harvest(), 0)
        write_rows(
            self.worksheet,
            fa.MATRIX_HEADER,
            [
                {
                    **{key: "" for key in fa.MATRIX_HEADER},
                    "fund_id": "FUND_0001",
                    "strategy_status": "none",
                    "merge_note": "distinct: two SOI headings",
                }
            ],
        )
        self.assertEqual(fa.merge_worksheet(), 0)
        self.assertEqual(fa.harvest(), 0)
        row = fa.read_csv(self.matrix)[0]
        self.assertEqual(row["strategy_status"], "none")
        self.assertEqual(row["strategy"], "")
        self.assertEqual(row["merge_note"], "distinct: two SOI headings")

    def test_stamp_does_not_overwrite_a_filled_period_cell(self) -> None:
        fa.harvest()
        lookup = fa.decided_lookup()
        rows = [{"fund_id": "FUND_0001", "vintage_year": "2011", "strategy": ""}]
        filled = fa.stamp_rows(rows, lookup)
        self.assertEqual(rows[0]["vintage_year"], "2011")
        self.assertEqual(rows[0]["strategy"], "Opportunistic")
        self.assertEqual(filled, 1)

    def test_dispatch_keeps_the_prompt_when_the_worksheet_is_empty(self) -> None:
        write_rows(self.worksheet, fa.MATRIX_HEADER, [])
        self.assertEqual(fa.dispatch(), 0)
        self.assertTrue(self.dispatch_prompt.is_file())
        text = self.dispatch_prompt.read_text(encoding="utf-8")
        self.assertIn("standing brief", text)
        self.assertIn("header-only", text)
        self.assertEqual(fa.dispatch(check=True), 0)


if __name__ == "__main__":
    unittest.main()
