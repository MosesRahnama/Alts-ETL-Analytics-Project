"""The generated prompts must agree with the code that judges their output.

These tests make the generator prove agreement with the validator: every
permitted field, vocabulary name, contract version, and cell count.
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.catalog.simple_pdf_extraction.csv_wide_contract import (  # noqa: E402
    BENCH_AGENTS,
    CANDIDATE_AGENTS,
    CONTRACT_VERSION,
    COVERAGE_COLUMNS,
    EXTRACTOR_AGENTS,
    DOC_TYPE_FAMILIES,
    EVIDENCE_CLASSES,
    FAMILY_CONTRACTS,
    PAGE_STATUSES,
    RECORD_COLUMNS,
    RETIRED_FIELDS,
    ROUTES,
    SOURCE_STRUCTURE_TYPES,
    SUBJECT_TYPES,
    allowed_metric_categories,
    allowed_term_categories,
)

PROMPT_ROOT = PROJECT_ROOT / "instructions" / "01-pdf-extraction-csv" / "dispatch-prompts"
SNAKE = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`")

# Names that appear in prompt prose but are not contract fields: worklist
# columns, grid columns, pair columns, and the two invented family names the
# prompt cites as examples of what to reject.
PROSE_NAMES = frozenset({
    "source_ledger", "record_sort_key", "work_order", "txt_path", "grid_path",
    "image_dir", "pdf_path", "page_count", "text_layer", "value_raw",
    "column_index", "column_x", "requires_review", "pair_status",
    "no_eligible_reason", "dispatch_scope", "routing_status",
    "source_header_doc_type", "holding_position", "allocation_bucket",
})
# Provenance and lineage columns: present on every row regardless of family.
UNIVERSAL = frozenset({
    "contract_version", "file_id", "source_sha256", "canonical_doc_type",
    "route", "product_tier", "agent_role", "record_family", "source_page",
    "source_structure_type", "source_section", "source_table",
    "source_row_label", "source_column_label", "source_occurrence",
    "evidence_quote", "evidence_class", "notes", "source_agents",
    "adjudication_status",
})


def extractor_prompts() -> list[Path]:
    """Every extractor lane, including any comparison lanes."""
    return sorted(PROMPT_ROOT.glob("*/0[125]-EXTRACTOR-*.md"))


def route_of(path: Path) -> str:
    return path.parent.name


def usable_values(route: str) -> set[str]:
    values: set[str] = set()
    for doc_type in ROUTES[route]:
        for family in DOC_TYPE_FAMILIES[doc_type]:
            values |= set(allowed_metric_categories(family))
            values |= set(allowed_term_categories(family, doc_type))
    return values


def allowed_fields(route: str) -> set[str]:
    fields: set[str] = set()
    for doc_type in ROUTES[route]:
        for family in DOC_TYPE_FAMILIES[doc_type]:
            fields |= FAMILY_CONTRACTS[family].allowed_fields
    return fields


class PromptContractAgreementTests(unittest.TestCase):
    def test_prompts_exist_for_every_route_and_role(self) -> None:
        """Both candidates on every route, plus bench lanes where one runs."""
        from src.catalog.simple_pdf_extraction.build_csv_pipeline import BENCH_ROUTES
        expected = (len(ROUTES) * len(CANDIDATE_AGENTS)
                    + len(BENCH_ROUTES) * len(BENCH_AGENTS))
        self.assertEqual(len(extractor_prompts()), expected)

    def test_every_named_field_is_a_real_column(self) -> None:
        columns = set(RECORD_COLUMNS) | set(COVERAGE_COLUMNS)
        controlled = (set(SUBJECT_TYPES) | set(SOURCE_STRUCTURE_TYPES)
                      | set(PAGE_STATUSES) | set(EVIDENCE_CLASSES)
                      | set(FAMILY_CONTRACTS))
        for prompt in extractor_prompts():
            route = route_of(prompt)
            known = columns | controlled | usable_values(route) | PROSE_NAMES
            for name in sorted(set(SNAKE.findall(prompt.read_text(encoding="utf-8")))):
                self.assertIn(name, known, f"{prompt.name} names unknown `{name}`")

    def test_no_prompt_names_a_category_its_route_forbids(self) -> None:
        """A route is told about the vocabulary of the kinds its families fill:
        a numeric-only route sees no term names, a legal route sees both."""
        every_category = set()
        for family in FAMILY_CONTRACTS:
            every_category |= set(allowed_metric_categories(family))
        for prompt in extractor_prompts():
            route = route_of(prompt)
            usable = usable_values(route)
            named = set(SNAKE.findall(prompt.read_text(encoding="utf-8")))
            for category in sorted(named & every_category - usable):
                if category in set(RECORD_COLUMNS) | PROSE_NAMES:
                    continue
                self.fail(f"{prompt.name} names category `{category}`, which "
                          f"no family on {route} permits")

    def test_no_prompt_offers_a_family_its_route_forbids(self) -> None:
        """The chooser named `performance_observation` on Financials, which
        forbids it, while omitting the fee and financing families it permits."""
        for prompt in extractor_prompts():
            route = route_of(prompt)
            permitted = {
                family
                for doc_type in ROUTES[route]
                for family in DOC_TYPE_FAMILIES[doc_type]
            }
            text = prompt.read_text(encoding="utf-8")
            chooser = re.search(
                r"\| The table's columns include \| Family \| Applies to \|\n(.*?)\n\n",
                text, re.S)
            self.assertIsNotNone(chooser, f"{prompt.name} has no family chooser")
            offered = set(re.findall(r"`([a-z_]+_observation|legal_\w+|"
                                     r"stewardship_\w+|subscription_reference)`",
                                     chooser.group(1)))
            forbidden = offered - permitted
            self.assertFalse(forbidden,
                             f"{prompt.name} offers {sorted(forbidden)}, forbidden on {route}")

    def test_every_permitted_family_has_a_chooser_rule(self) -> None:
        for prompt in extractor_prompts():
            route = route_of(prompt)
            text = prompt.read_text(encoding="utf-8")
            chooser = re.search(
                r"\| The table's columns include \| Family \| Applies to \|\n(.*?)\n\n",
                text, re.S)
            offered = set(re.findall(r"`([a-z_]+)`", chooser.group(1)))
            for doc_type in ROUTES[route]:
                for family in DOC_TYPE_FAMILIES[doc_type]:
                    if family == "document_context":
                        continue
                    self.assertIn(family, offered,
                                  f"{prompt.name} gives no rule for permitted `{family}`")

    def test_no_prompt_asks_for_a_field_no_family_permits(self) -> None:
        for prompt in extractor_prompts():
            route = route_of(prompt)
            permitted = allowed_fields(route) | UNIVERSAL
            named = set(SNAKE.findall(prompt.read_text(encoding="utf-8")))
            for field in sorted(named & set(RECORD_COLUMNS) - permitted):
                self.fail(f"{prompt.name} tells the agent to fill `{field}`, "
                          f"which no family on {route} permits")

    def test_printed_header_matches_the_contract(self) -> None:
        for prompt in extractor_prompts():
            text = prompt.read_text(encoding="utf-8")
            match = re.search(r'```csv\n("contract_version".*?)\n```', text, re.S)
            self.assertIsNotNone(match, f"{prompt.name} prints no record header")
            printed = [c.strip('"') for c in match.group(1).split(",")]
            self.assertEqual(printed, list(RECORD_COLUMNS), prompt.name)

    def test_cell_counts_in_prose_match_the_header(self) -> None:
        # `findall` over a phrase that has drifted returns an empty list, so the
        # assertion loop never runs and the test passes having checked nothing.
        # Each prompt must yield both claims, which makes a reworded prompt fail
        # here rather than silently stop being checked.
        for prompt in extractor_prompts():
            text = prompt.read_text(encoding="utf-8")
            cells = re.findall(r"(\d+) cells on every single row", text)
            commas = re.findall(r"contains (\d+) commas outside quotes", text)
            self.assertTrue(cells, f"{prompt.name} states no cell count")
            self.assertTrue(commas, f"{prompt.name} states no comma count")
            for claim in cells:
                self.assertEqual(int(claim), len(RECORD_COLUMNS), prompt.name)
            for claim in commas:
                self.assertEqual(int(claim), len(RECORD_COLUMNS) - 1, prompt.name)

    def test_contract_version_is_current(self) -> None:
        for prompt in sorted(PROMPT_ROOT.rglob("*.md")):
            for version in set(re.findall(r"`(2026-\d\d-\d\d\.\d)`",
                                          prompt.read_text(encoding="utf-8"))):
                self.assertEqual(version, CONTRACT_VERSION, prompt.name)

    def test_no_prompt_names_a_retired_field(self) -> None:
        for prompt in sorted(PROMPT_ROOT.rglob("*.md")):
            text = prompt.read_text(encoding="utf-8")
            for field in RETIRED_FIELDS:
                self.assertNotIn(field, text, f"{prompt.name} names retired `{field}`")

    def test_every_named_command_exists(self) -> None:
        help_text = subprocess.run(
            [sys.executable, "instructions/01-pdf-extraction-csv/workflow.py", "--help"],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        ).stdout
        self.assertTrue(help_text, "workflow.py --help produced nothing")
        for prompt in sorted(PROMPT_ROOT.rglob("*.md")):
            text = prompt.read_text(encoding="utf-8")
            for command in sorted(set(re.findall(r"workflow\.py ([a-z][a-z-]+)", text))):
                self.assertIn(command, help_text,
                              f"{prompt.name} names command `{command}`")

    def test_working_memory_checklist_is_intact(self) -> None:
        """The checklist is the agent's only in-flight reference; it must parse."""
        words = {"twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
                 "sixteen": 16, "seventeen": 17, "eighteen": 18}
        for prompt in extractor_prompts():
            text = prompt.read_text(encoding="utf-8")
            block = re.search(r"RE-READ BEFORE THE NEXT DOCUMENT.*?\n```", text, re.S)
            self.assertIsNotNone(block, f"{prompt.name} has no working memory")
            body = block.group(0)
            numbers = [int(n) for n in re.findall(r"^\s*(\d+)\.", body, re.M)]
            self.assertEqual(numbers, sorted(numbers),
                             f"{prompt.name} checklist is out of order")
            self.assertEqual(numbers, list(range(1, len(numbers) + 1)),
                             f"{prompt.name} checklist numbering is not contiguous")
            claimed = re.search(r"the (\w+) rules that decay", body)
            self.assertIsNotNone(claimed, f"{prompt.name} checklist has no count")
            self.assertEqual(words.get(claimed.group(1)), len(numbers),
                             f"{prompt.name} checklist count is wrong")

    def test_lanes_differ_only_by_role(self) -> None:
        """Every extractor lane must read identical instructions.

        A model comparison is only fair if the lanes differ solely in which
        file they write and which candidates they must not open.
        """
        for route in ROUTES:
            folder = PROMPT_ROOT / route
            lanes = {}
            numbered = dict(zip(EXTRACTOR_AGENTS, ("01", "02", "05", "06")))
            for lane, number in numbered.items():
                path = folder / f"{number}-EXTRACTOR-{lane}.md"
                if path.is_file():
                    lanes[lane] = path.read_text(encoding="utf-8")
            self.assertGreaterEqual(len(lanes), 2, f"{route}: fewer than two lanes")

            def normalise(text: str, lane: str) -> str:
                others = ", ".join(a for a in EXTRACTOR_AGENTS if a != lane)
                return (text.replace(f"EXTRACTOR {lane}", "EXTRACTOR X")
                        .replace(f"records-{lane.lower()}", "records-x")
                        .replace(f"coverage-{lane.lower()}", "coverage-x")
                        .replace(f"--agent {lane}", "--agent X")
                        .replace(f"`agent_role` is `{lane}`", "`agent_role` is `X`")
                        .replace(f"candidate ({others})", "candidate (OTHERS)"))

            reference = normalise(lanes["A"], "A")
            for lane, text in lanes.items():
                self.assertEqual(normalise(text, lane), reference,
                                 f"{route}: lane {lane} differs beyond its role")


if __name__ == "__main__":
    unittest.main()
