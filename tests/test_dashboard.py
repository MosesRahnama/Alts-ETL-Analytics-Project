"""The reviewer dashboard renders from the published files and cites them.

A page a reviewer opens instead of the tree earns the same treatment as the
tree: it has to open with no network, carry the counts the source files carry,
and name a path for every panel that a reader can go and check.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import threading
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from src.dashboard import build_dashboard
from src.dashboard.page import SCRIPT, STYLE, render


PROJECT_ROOT = build_dashboard.PROJECT_ROOT
PAYLOAD = re.compile(
    r'<script id="payload" type="application/json">(.*?)</script>', re.S
)
REMOTE = re.compile(r'(?:src|href)\s*=\s*["\']\s*(?:https?:)?//', re.I)


def contrast_ratio(foreground: str, background: str) -> float:
    def luminance(value: str) -> float:
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def build_to(directory: str) -> tuple[Path, str, dict]:
    output = Path(directory) / "dashboard.html"
    build_dashboard.build(output)
    text = output.read_text(encoding="utf-8")
    match = PAYLOAD.search(text)
    assert match is not None, "the page carries no payload"
    return output, text, json.loads(match.group(1))


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = TemporaryDirectory()
        cls.output, cls.text, cls.payload = build_to(cls._directory.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._directory.cleanup()

    def test_page_loads_from_disk_with_no_remote_asset(self) -> None:
        self.assertNotRegex(self.text, REMOTE)
        self.assertNotIn("<link", self.text)
        self.assertNotIn("<script src", self.text)
        self.assertTrue(self.text.startswith("<!doctype html>"))

    def test_the_same_tree_renders_the_same_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            _, second, _ = build_to(directory)
        self.assertEqual(self.text, second)

    def test_checked_in_dashboard_matches_the_builder(self) -> None:
        current = (PROJECT_ROOT / "dashboard.html").read_text(encoding="utf-8")
        self.assertEqual(current, self.text)

    def test_every_section_carries_a_title_and_blocks(self) -> None:
        sections = self.payload["sections"]
        self.assertEqual(len(sections), len(build_dashboard.SECTION_BUILDERS))
        identifiers = [section["id"] for section in sections]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for section in sections:
            self.assertTrue(section["title"])
            self.assertTrue(section["blurb"])
            self.assertTrue(section["blocks"])

    def test_titles_are_declarative(self) -> None:
        question_opening = re.compile(
            r"^(what|how|why|when|where|who|which|whether|is|are|was|were|do|does|did|can|could|should|would|will|has|have)\b",
            re.I,
        )
        titles = [section["title"] for section in self.payload["sections"]]
        titles.extend(
            block.get("text") or block.get("title", "")
            for section in self.payload["sections"]
            for block in section["blocks"]
            if block.get("kind") in {"heading", "table", "bars", "boxes", "donuts", "stacks", "formulas", "explorer"}
        )
        for title in titles:
            self.assertNotRegex(title, question_opening, title)
            self.assertNotIn("?", title)

    def test_interface_copy_is_descriptive(self) -> None:
        for phrase in (
            "Open a database",
            "What the columns mean",
            "Pick a file",
            "Click a row",
            "Hover a column",
            "No row matched",
            "accepted printed value or fact",
            "published cell",
            "table grain",
            "open queues",
        ):
            self.assertNotIn(phrase, self.text)

    def test_pdf_extraction_story_covers_source_to_fund_data(self) -> None:
        copy = json.dumps(self.payload["sections"])
        for phrase in (
            "300 DPI",
            "document grids",
            "physical page",
            "repeated occurrence",
            "ten percent",
            "stable IDs",
            "input evidence-row IDs",
            "fund periods",
        ):
            self.assertIn(phrase, copy)

        evidence = next(section for section in self.payload["sections"] if section["id"] == "evidence")
        documents = next(
            item
            for block in evidence["blocks"]
            if block["kind"] == "kpi"
            for item in block["items"]
            if item["label"] == "Documents extracted"
        )
        self.assertEqual(documents["value"], "29")

    def test_primary_text_colours_meet_normal_text_contrast(self) -> None:
        colours = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", STYLE))
        pairs = (
            ("ink", "page"),
            ("ink-soft", "page"),
            ("ink-faint", "panel"),
            ("nav-soft", "nav"),
        )
        for foreground, background in pairs:
            self.assertGreaterEqual(
                contrast_ratio(colours[foreground], colours[background]),
                7.0,
                f"{foreground} on {background}",
            )

    def test_stacked_chart_labels_choose_accessible_text_colour(self) -> None:
        palette = re.search(r"const PALETTE = \[(.*?)\];", SCRIPT, re.S)
        named = re.search(r"const NAMED = \{(.*?)\};", SCRIPT, re.S)
        self.assertIsNotNone(palette)
        self.assertIsNotNone(named)
        backgrounds = re.findall(
            r"#[0-9a-fA-F]{6}", palette.group(1) + named.group(1)
        )
        for background in backgrounds:
            self.assertGreaterEqual(
                max(
                    contrast_ratio("#ffffff", background),
                    contrast_ratio("#102a43", background),
                ),
                4.5,
                background,
            )
        self.assertIn("segment.style.color = textColourFor(background)", SCRIPT)

    def test_every_table_row_matches_its_column_count(self) -> None:
        for section, block in self.blocks("table"):
            width = len(block["columns"]) + len(block.get("hidden", []))
            self.assertGreater(len(block["columns"]), 0, f"{section['id']}: {block['title']}")
            for row in block["rows"]:
                self.assertEqual(len(row), width, f"{section['id']}: {block['title']}")
            self.assertGreaterEqual(block["rows_total"], len(block["rows"]))

    def test_every_table_says_what_a_row_is(self) -> None:
        """A reviewer should never meet a grid without being told what they are
        looking at, so every table and every bar chart carries a description."""

        for section, block in self.blocks("table", "bars", "explorer"):
            self.assertTrue(
                block.get("about", "").strip(),
                f"{section['id']}: {block['title']} has no description",
            )

    def test_every_column_on_the_page_has_a_definition(self) -> None:
        """Every column a grid shows, every column a row detail opens, and
        every column of every database table resolves to a definition."""

        self.assertEqual(sorted(build_dashboard.MISSING_DEFINITIONS), [])
        for section, block in self.blocks("table"):
            names = block["columns"] + block.get("hidden", [])
            self.assertEqual(len(block["definitions"]), len(names), f"{section['id']}: {block['title']}")
            for name, definition in zip(names, block["definitions"]):
                self.assertTrue(definition.strip(), f"{section['id']}: {block['title']}: {name}")
        for _, block in self.blocks("explorer"):
            for group in block["groups"]:
                for entry in group["tables"]:
                    self.assertEqual(len(entry["definitions"]), len(entry["columns"]), entry["name"])
                    for name, definition in zip(entry["columns"], entry["definitions"]):
                        self.assertTrue(definition.strip(), f"{group['name']}.{entry['name']}.{name}")

    def test_formula_cards_carry_a_worked_example_from_the_data(self) -> None:
        cards = [block for _, block in self.blocks("formulas")]
        self.assertEqual(len(cards), 1)
        names = [item["name"] for item in cards[0]["items"]]
        self.assertEqual(names, ["DPI", "RVPI", "TVPI", "XIRR", "KS-PME", "Direct Alpha"])
        for item in cards[0]["items"]:
            self.assertTrue(item["plain"])
            self.assertIn("frac", item["html"])
            self.assertTrue(item["example"]["rows"], item["name"])
            self.assertTrue(item["example"]["rows"][-1][-1], f"{item['name']} example has no result")

    def test_a_zero_stays_a_number(self) -> None:
        """A zero is a reading the page made, so it survives every reader."""

        self.assertEqual(build_dashboard.as_float(0.0), 0.0)
        self.assertEqual(build_dashboard.as_float("0"), 0.0)
        self.assertEqual(build_dashboard.as_float(0), 0.0)
        self.assertIsNone(build_dashboard.as_float(""))
        self.assertIsNone(build_dashboard.as_float(None))
        self.assertEqual(build_dashboard.as_int(0), 0)
        self.assertEqual(build_dashboard.show_unit(0.0, "multiple"), "0.00x")
        self.assertEqual(build_dashboard.money(0.0), "0")

    def test_box_plots_carry_five_numbers_on_one_scale_per_unit(self) -> None:
        for section, block in self.blocks("boxes"):
            self.assertTrue(block["groups"], block["title"])
            for group in block["groups"]:
                self.assertLess(group["low"], group["high"], group["title"])
                self.assertTrue(group["low_display"], f"{group['title']} has no low label")
                self.assertTrue(group["high_display"], f"{group['title']} has no high label")
                for item in group["items"]:
                    where = f"{section['id']}: {item['label']}"
                    self.assertLessEqual(item["min"], item["p25"], where)
                    self.assertLessEqual(item["p25"], item["median"], where)
                    self.assertLessEqual(item["median"], item["p75"], where)
                    self.assertLessEqual(item["p75"], item["max"], where)
                    self.assertGreaterEqual(item["min"], group["low"], where)
                    self.assertLessEqual(item["max"], group["high"], where)
                    self.assertEqual(len(item["display"]), 5, where)
                    for label, text in item["display"].items():
                        self.assertTrue(text, f"{where}: {label} has no label")

    def test_composition_charts_add_up(self) -> None:
        for _, block in self.blocks("donuts"):
            for chart in block["charts"]:
                self.assertTrue(chart["items"], chart["label"])
                self.assertTrue(all(item["value"] >= 0 for item in chart["items"]))
                self.assertGreater(sum(item["value"] for item in chart["items"]), 0, chart["label"])
        for _, block in self.blocks("stacks"):
            width = len(block["keys"])
            self.assertGreater(width, 0)
            for row in block["rows"]:
                self.assertEqual(len(row["values"]), width, row["label"])

    def test_values_are_shown_in_their_unit(self) -> None:
        self.assertEqual(build_dashboard.show_unit("0.5065666041", "multiple"), "0.51x")
        self.assertEqual(build_dashboard.show_unit("0.0213106485", "decimal_rate"), "2.13%")
        self.assertEqual(build_dashboard.show_unit("-0.1018093899", "decimal_rate"), "-10.18%")
        self.assertEqual(build_dashboard.show_unit("250000000", "currency"), "250,000,000")
        self.assertEqual(build_dashboard.money("90500000"), "90,500,000")
        self.assertEqual(build_dashboard.two("1.05524861878"), "1.06")

    def test_the_explorer_carries_every_table_of_every_database(self) -> None:
        try:
            import duckdb  # noqa: F401
        except ImportError:  # pragma: no cover - the panel is absent without it
            self.skipTest("duckdb is absent, so the page renders the CSV listings instead")
        explorers = [block for _, block in self.blocks("explorer")]
        self.assertEqual(len(explorers), 1)
        groups = explorers[0]["groups"]
        self.assertEqual(
            [group["name"] for group in groups],
            ["extracted.duckdb", "alts.duckdb", "alts_mock.duckdb"],
        )
        for group in groups:
            expected = build_dashboard.inventory(f"data/warehouse/{group['name']}")
            self.assertEqual(
                sorted(entry["name"] for entry in group["tables"]),
                sorted(expected[1] + expected[2]),
                f"{group['name']} lists a different set of tables than the file holds",
            )
            for entry in group["tables"]:
                where = f"{group['name']}.{entry['name']}"
                self.assertIn(entry["kind"], {"table", "view"}, where)
                self.assertEqual(len(entry["types"]), len(entry["columns"]), where)
                self.assertLessEqual(len(entry["preview"]), build_dashboard.PREVIEW_ROWS, where)
                self.assertLessEqual(len(entry["preview"]), entry["rows"], where)
                for row in entry["preview"]:
                    self.assertEqual(len(row), len(entry["columns"]), where)

    def test_a_preview_row_matches_the_database_row(self) -> None:
        """The grid shows the database, so one row is compared against it."""

        try:
            import duckdb
        except ImportError:  # pragma: no cover
            self.skipTest("duckdb is absent")
        entries = {
            entry["name"]: entry
            for entry in build_dashboard.database_contents("data/warehouse/alts.duckdb", 5)
        }
        entry = entries["fund_master"]
        connection = duckdb.connect(str(PROJECT_ROOT / "data" / "warehouse" / "alts.duckdb"), read_only=True)
        try:
            rows = connection.execute("select * from fund_master order by all limit 5").fetchall()
            count = connection.execute("select count(*) from fund_master").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(entry["rows"], count)
        self.assertEqual(
            entry["preview"],
            [["" if value is None else str(value) for value in row] for row in rows],
        )

    def test_every_cited_path_exists(self) -> None:
        for section, block in self.blocks("table", "bars", "explorer"):
            source = block.get("source", "")
            if not source or " " in source:
                continue
            self.assertTrue(
                (PROJECT_ROOT / source).exists(),
                f"{section['id']} cites a missing path: {source}",
            )

    def test_counts_come_from_the_published_files(self) -> None:
        observations = build_dashboard.row_count("data/extracted/tables/fact_observation.csv")
        evidence = self.block_titled("evidence", "Evidence row preview")
        self.assertEqual(evidence["rows_total"], observations)
        self.assertEqual(len(evidence["rows"]), observations)

        ledger = build_dashboard.row_count("data-gathering/source_ledger.csv")
        corpus = self.block_titled("corpus", "Every acquired report")
        self.assertEqual(corpus["rows_total"], ledger)

        vocabulary = self.block_titled("schema", "Metric and term names with definitions")
        self.assertEqual(
            vocabulary["rows_total"],
            len(build_dashboard.contract.METRIC_CATEGORIES)
            + len(build_dashboard.contract.TERM_CATEGORIES),
        )

    def test_the_builder_runs_as_a_file(self) -> None:
        """A reviewer opens the file in an editor and presses run, so that path
        has to work as well as `python -m` does."""

        with TemporaryDirectory() as directory:
            output = Path(directory) / "dashboard.html"
            finished = subprocess.run(
                [sys.executable, str(build_dashboard.__file__), "--output", str(output)],
                cwd=directory,
                capture_output=True,
                text=True,
            )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertIn("PASS", finished.stdout)

    def test_the_builder_imports_nothing_it_needs_installed(self) -> None:
        """The page has to render on a Python with nothing installed, so every
        module-level import is either the standard library or this project."""

        for module in (
            build_dashboard,
            __import__("src.dashboard.page", fromlist=["page"]),
            __import__("src.dashboard.glossary", fromlist=["glossary"]),
        ):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            for node in tree.body:
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module.split(".")[0]]
                for name in names:
                    self.assertTrue(
                        name == "src" or name in sys.stdlib_module_names,
                        f"{Path(module.__file__).name} imports {name} at module level",
                    )

    def test_the_settings_readers_agree_with_a_yaml_parse(self) -> None:
        try:
            import yaml
        except ImportError:  # pragma: no cover - the comparison is optional
            self.skipTest("pyyaml is absent")
        rules = yaml.safe_load(
            (PROJECT_ROOT / "config" / "quality_rules.yml").read_text(encoding="utf-8")
        )
        read = build_dashboard.read_setting_list("config/quality_rules.yml", "rules")
        self.assertEqual([row["id"] for row in read], [row["id"] for row in rules["rules"]])
        self.assertEqual(
            [row.get("severity") for row in read],
            [row.get("severity") for row in rules["rules"]],
        )
        tolerances = build_dashboard.read_setting_block("config/quality_rules.yml", "tolerances")
        self.assertEqual(
            {name: float(value) for name, value in tolerances.items()},
            {name: float(value) for name, value in rules["tolerances"].items()},
        )
        completion = yaml.safe_load(
            (PROJECT_ROOT / "config" / "integrated_completion.yml").read_text(encoding="utf-8")
        )
        settings = dict(build_dashboard.read_settings("config/integrated_completion.yml"))
        self.assertEqual(
            settings,
            {
                name: str(value)
                for name, value in completion.items()
                if isinstance(value, (str, int, float, date))
            },
        )

    def test_the_local_address_serves_the_page_and_nothing_else(self) -> None:
        page = b"<!doctype html>\n<title>served</title>"
        server = build_dashboard.page_server(page, 8531)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address[0], server.server_address[1]
            self.assertEqual(host, "127.0.0.1")
            base = f"http://127.0.0.1:{port}"
            with urlopen(f"{base}/"):
                pass
            with urlopen(f"{base}/") as answer:
                self.assertEqual(answer.read(), page)
            # A path that names a repository file returns the page, so the
            # server exposes one document and never the tree around it.
            with urlopen(f"{base}/README.md") as answer:
                self.assertEqual(answer.read(), page)
            with urlopen(f"{base}/favicon.ico") as answer:
                self.assertEqual(answer.status, 204)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_a_taken_port_moves_to_the_next_one(self) -> None:
        first = build_dashboard.page_server(b"x", 8541)
        second = build_dashboard.page_server(b"x", 8541)
        try:
            self.assertNotEqual(first.server_address[1], second.server_address[1])
        finally:
            first.server_close()
            second.server_close()

    def test_an_unread_database_says_so(self) -> None:
        status, tables, views = build_dashboard.inventory("data/warehouse/no-such.duckdb")
        self.assertEqual((tables, views), ([], []))
        self.assertNotEqual(status, "read")

    def test_the_payload_survives_being_inlined(self) -> None:
        page = render({"title": "t", "subtitle": "s", "sections": [
            {"id": "x", "title": "T", "blurb": "b", "blocks": [
                {"kind": "note", "text": "</script><script>alert(1)</script>"}
            ]}
        ]})
        self.assertEqual(page.count("<script"), 2)
        payload = json.loads(PAYLOAD.search(page).group(1))
        self.assertEqual(
            payload["sections"][0]["blocks"][0]["text"],
            "</script><script>alert(1)</script>",
        )

    # helpers

    def blocks(self, *kinds: str):
        for section in self.payload["sections"]:
            for block in section["blocks"]:
                if block.get("kind") in kinds:
                    yield section, block

    def block_titled(self, section_id: str, title: str) -> dict:
        for section, block in self.blocks("table"):
            if section["id"] == section_id and block["title"] == title:
                return block
        raise AssertionError(f"{section_id} holds no table titled {title}")


if __name__ == "__main__":
    unittest.main()
