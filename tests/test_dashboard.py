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
from src.dashboard.glossary import column_note
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

    def test_quality_detail_includes_all_failed_results(self) -> None:
        section = next(item for item in self.payload["sections"] if item["id"] == "quality")
        table = next(item for item in section["blocks"] if item.get("title") == "Failed results and source evidence")
        expected = [row for row in build_dashboard.read_dicts("data/csv/quality_results.csv") if row["status"] == "FAIL"]
        self.assertEqual(len(table["rows"]), len(expected))
        self.assertEqual(sorted(row[0] for row in table["rows"]), sorted(row["rule_id"] for row in expected))
        self.assertNotIn("Generated rows add no failures", json.dumps(section))
        self.assertNotIn("same two FAIL rows", json.dumps(section))

    def test_benchmark_caption_counts_all_series(self) -> None:
        section = next(item for item in self.payload["sections"] if item["id"] == "benchmarks")
        cards = next(item["items"] for item in section["blocks"] if item["kind"] == "kpi")
        card = next(item for item in cards if item["label"] == "Daily benchmark returns")
        series = build_dashboard.tally("data/csv/benchmark_returns.csv", "benchmark_id")
        used = build_dashboard.tally("data/csv/pme_results.csv", "benchmark_id")
        self.assertEqual(card["value"], build_dashboard.thousands(sum(series.values())))
        self.assertIn(f"{len(series)} series", card["note"])
        self.assertIn(f"use {len(used)}", card["note"])

    def test_imputation_description_uses_recorded_method_count(self) -> None:
        section = next(item for item in self.payload["sections"] if item["id"] == "generated")
        count = len({row[0] for row in build_dashboard.imputation_method_rows()})
        self.assertIn(f"identifies {count} methods", json.dumps(section))
        self.assertNotIn("The three rules", json.dumps(section))
        self.assertNotIn("cohort median", column_note("Imputed"))

    def test_publication_excludes_private_and_unfinished_files(self) -> None:
        from src.dashboard.publish_dashboard import allowed_path
        completed = {"SRC034"}
        self.assertTrue(allowed_path("ledgers/working/pdf-extraction-csv/01-financials/SRC034/records-final.csv", completed))
        for path in (".gitignore", "src/dashboard/page.py", "audit/project-notes.md", "data/../secret.csv", "C:/private.csv",
                     "ledgers/working/pdf-extraction-csv/07-institutional-mission/SRC373/records-a.csv"):
            self.assertFalse(allowed_path(path, completed), path)

    def test_database_archive_contains_the_original_bytes(self) -> None:
        import zipfile
        from src.dashboard.publish_dashboard import write_zip
        with TemporaryDirectory() as directory:
            target = Path(directory) / "database.zip"
            content = b"database-test\x00\xff" * 100
            write_zip(target, "test.duckdb", content)
            first = target.read_bytes()
            write_zip(target, "test.duckdb", content)
            self.assertEqual(first, target.read_bytes())
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.namelist(), ["test.duckdb"])
                self.assertEqual(archive.read("test.duckdb"), content)

    def test_public_downloads_use_the_published_file_map(self) -> None:
        self.assertIn("if (DATA.downloads) return DATA.downloads[value] || '';", SCRIPT)
        self.assertIn("link.href = downloadHref(raw)", SCRIPT)
        self.assertIn("minmax(0, 1fr)", STYLE)

    def test_every_section_carries_a_title_and_blocks(self) -> None:
        sections = self.payload["sections"]
        self.assertEqual(len(sections), len(build_dashboard.SECTION_BUILDERS))
        identifiers = [section["id"] for section in sections]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for section in sections:
            self.assertTrue(section["title"])
            self.assertTrue(section["blurb"])
            self.assertTrue(section["blocks"])

    def test_overview_opens_with_the_github_repository_link(self) -> None:
        overview = self.payload["sections"][0]
        self.assertEqual(overview["id"], "overview")
        first = overview["blocks"][0]
        self.assertEqual(first["kind"], "link")
        self.assertEqual(
            first["href"],
            "https://github.com/MosesRahnama/Alts-ETL-Analytics-Project",
        )
        self.assertEqual(first["prefix"], "Link to repository:")
        self.assertEqual(
            first["label"],
            "https://github.com/MosesRahnama/Alts-ETL-Analytics-Project",
        )
        self.assertIn("renderLink", SCRIPT)
        self.assertIn("repo-line", SCRIPT)

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
            if block.get("kind") in {
                "heading", "table", "bars", "boxes", "donuts", "stacks",
                "formulas", "explorer", "guide", "terms",
            }
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
            "One printed cell",
            "Page guide",
            "listed type",
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
        self.assertEqual(documents["value"], str(len(build_dashboard.read_dicts("data/extracted/tables/dim_document.csv"))))

    def test_every_section_carries_a_guide_box(self) -> None:
        for section in self.payload["sections"]:
            kinds = [block["kind"] for block in section["blocks"]]
            self.assertIn("guide", kinds, section["id"])

    def test_page_guide_and_words_are_on_the_payload(self) -> None:
        self.assertEqual(self.payload["help"]["title"], "Page guide")
        self.assertGreaterEqual(len(self.payload["terms"]), 10)
        self.assertIn("observation", [row["word"] for row in self.payload["terms"]])
        self.assertIn("renderGuide", SCRIPT)
        self.assertIn("renderHelpOverlay", SCRIPT)
        self.assertIn("twelve sections", self.payload["footer"])

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
                    contrast_ratio("#101030", background),
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

    def test_no_glossary_entry_is_written_twice(self) -> None:
        """One definition per key, checked against the source text.

        Python keeps the last value when a dict literal repeats a key, so four
        columns carried a second definition that silently replaced the first
        and no reader could see which one the page used. The collapsed dict
        cannot show the repeat, so this parses the file. A column that means
        two things in two tables takes a `table.column` key, which
        `column_note` prefers over the bare name."""

        source = (PROJECT_ROOT / "src" / "dashboard" / "glossary.py").read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Dict):
                continue
            keys = [key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
            repeated = sorted({key for key in keys if keys.count(key) > 1})
            self.assertEqual(repeated, [], f"glossary.py line {node.lineno} repeats {repeated}")

    def test_a_column_meaning_two_things_resolves_per_table(self) -> None:
        """A table-qualified key wins over the bare name for that table.

        `source_table` names the fund-model table a DERIVED value was copied
        from in the completion record and the printed title of a table in the
        evidence record. Both readings are published, so both must resolve."""

        cases = (
            ("cell-lineage", "source_table", "copied from"),
            ("fact_observation", "source_table", "printed title"),
            ("synthetic_parameters", "adjudication_status", "generation parameter"),
            ("fact_observation", "adjudication_status", "adjudicated"),
        )
        for table, column, expected in cases:
            note = column_note(column, table)
            self.assertIn(expected, note, f"{table}.{column}: {note}")

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
            __import__("src.dashboard.teaching", fromlist=["teaching"]),
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

    # what a heading claims about the cell under it

    def test_every_evidence_cell_sits_under_its_own_heading(self) -> None:
        """A cell is checked against the column the heading names.

        Comparing widths alone passed while 39 of 88 positions carried another
        column's value, because the row was built in the order of the file and
        the page reads it against `columns + hidden`. This reads one named
        observation out of `fact_observation.csv` and compares every heading."""

        grid = self.block_titled("evidence", "Evidence row preview")
        names = grid["columns"] + grid["hidden"]
        self.assertEqual(sorted({name for name in names if names.count(name) > 1}), [])
        source = {
            row["observation_id"]: row
            for row in build_dashboard.read_dicts("data/extracted/tables/fact_observation.csv")
        }
        joined = set(build_dashboard.SOURCE_LINK_COLUMNS)
        for row in (grid["rows"][0], grid["rows"][len(grid["rows"]) // 2], grid["rows"][-1]):
            record = source[row[0]]
            self.assertEqual(len(row), len(names))
            for name, cell in zip(names, row):
                if name in joined:
                    continue
                self.assertEqual(cell, record.get(name, ""), f"{row[0]}: {name}")

    def test_the_evidence_grid_leads_with_the_taxonomy_reading(self) -> None:
        grid = self.block_titled("evidence", "Evidence row preview")
        for name in ("canonical_asset_class", "canonical_strategy", "canonical_sub_strategy",
                     "canonical_sector", "asset_class", "strategy"):
            self.assertIn(name, grid["columns"], name)
        self.assertLess(
            grid["columns"].index("canonical_asset_class"),
            grid["columns"].index("asset_class"),
        )

    def test_no_published_column_reaches_the_page_twice(self) -> None:
        """The reviewer file repeats the evidence file's canonical columns, so
        joining a second copy printed five headings twice with nothing saying
        which copy a cell came from."""

        for section, block in self.blocks("table"):
            names = block["columns"] + block.get("hidden", [])
            repeated = sorted({name for name in names if names.count(name) > 1})
            self.assertEqual(repeated, [], f"{section['id']}: {block['title']}")

    def test_a_blank_grid_column_states_how_many_rows_fill_it(self) -> None:
        """An empty column is a fact about this release, not about the funds."""

        evidence = next(s for s in self.payload["sections"] if s["id"] == "evidence")
        notes = " ".join(b.get("text", "") for b in evidence["blocks"] if b["kind"] == "note")
        counts = build_dashboard.fill_counts(
            "data/extracted/tables/fact_observation.csv", build_dashboard.GRID_FILL_COLUMNS
        )
        grid = self.block_titled("evidence", "Evidence row preview")
        for name, filled in counts.items():
            self.assertIn(f"{name} {filled:,}", notes, name)
            if filled == 0:
                self.assertNotIn(name, grid["columns"], f"{name} is blank on every row")
                self.assertIn(name, grid["hidden"], name)
            else:
                self.assertIn(name, grid["columns"], name)

    def test_the_grouping_grid_reads_all_four_canonical_columns(self) -> None:
        grid = self.block_titled("evidence", "Taxonomy reading of every published row")
        for name in build_dashboard.CANONICAL_COLUMNS:
            self.assertIn(name, grid["columns"], name)
        counts = build_dashboard.fill_counts(
            "data/extracted/review/reviewer-observations.csv", build_dashboard.CANONICAL_COLUMNS
        )
        for name, filled in counts.items():
            self.assertIn(f"{name} {filled:,}", grid["about"], name)

    def test_no_panel_counts_return_as_one_measure(self) -> None:
        """`return` names a family. One bar of 1,117 draws a net time-weighted
        return and a gross money-weighted one as one length."""

        rows = [
            row for row in build_dashboard.read_dicts("data/extracted/tables/fact_observation.csv")
            if row.get("metric_category") == "return"
        ]
        pairs = {
            (build_dashboard.qualifier_label(row.get("method")),
             build_dashboard.qualifier_label(row.get("fee_basis")))
            for row in rows
        }
        labels = next(b for _, b in self.blocks("bars") if b["title"] == "Most common metric and term labels")
        self.assertNotIn("return", [item["label"] for item in labels["items"]])
        split = next(b for _, b in self.blocks("bars") if b["title"] == "Printed returns by method and fee basis")
        self.assertEqual(
            sorted(item["label"] for item in split["items"]),
            sorted(f"{method} / {fee}" for method, fee in pairs),
        )
        self.assertEqual(sum(item["value"] for item in split["items"]), len(rows))

    def test_a_blank_qualifier_is_never_labelled_unstated(self) -> None:
        """`unstated` is the page stating none. A blank is a row read before
        the column existed. Printing one as the other invents a reading."""

        self.assertEqual(build_dashboard.qualifier_label(""), build_dashboard.NOT_STATED_YET)
        self.assertEqual(build_dashboard.qualifier_label(None), build_dashboard.NOT_STATED_YET)
        self.assertEqual(build_dashboard.qualifier_label("  "), build_dashboard.NOT_STATED_YET)
        self.assertNotEqual(build_dashboard.NOT_STATED_YET, build_dashboard.UNSTATED)
        self.assertEqual(build_dashboard.qualifier_label("unstated"), "unstated")
        self.assertEqual(build_dashboard.qualifier_label("net"), "net")

    def test_the_qualifier_cards_count_unstated_apart_from_stated(self) -> None:
        rows = [
            row for row in build_dashboard.read_dicts("data/extracted/tables/fact_observation.csv")
            if row.get("metric_category") == "return"
        ]

        def counted(column: str) -> int:
            return sum(1 for row in rows if (row.get(column) or "").strip() not in ("", "unstated"))

        cards = {
            item["label"]: item["value"]
            for _, block in self.blocks("kpi")
            for item in block["items"]
        }
        self.assertEqual(cards["Returns stating a method"], f"{counted('method'):,}")
        self.assertEqual(cards["Returns stating a fee basis"], f"{counted('fee_basis'):,}")
        self.assertEqual(
            cards["Returns whose page states none"],
            f"{sum(1 for row in rows if (row.get('method') or '').strip() in ('', 'unstated') and (row.get('fee_basis') or '').strip() in ('', 'unstated')):,}",
        )
        self.assertEqual(
            cards["Returns missing required qualifiers"],
            f"{sum(1 for row in rows if not (row.get('method') or '').strip() or not (row.get('fee_basis') or '').strip()):,}",
        )

    def test_the_backlog_and_the_unfinished_documents_are_on_the_page(self) -> None:
        backlog_rows, documents = build_dashboard.backlog_totals()
        cards = {
            item["label"]: item
            for _, block in self.blocks("kpi")
            for item in block["items"]
        }
        self.assertEqual(cards["Missing required qualifiers"]["value"], f"{backlog_rows:,}")
        self.assertIn(str(documents), cards["Missing required qualifiers"]["note"])
        self.assertIn("requires this count to be zero", cards["Missing required qualifiers"]["note"])
        copy = json.dumps(self.payload["sections"])
        for name in build_dashboard.unfinished_documents():
            self.assertIn(name, copy, name)

    def test_no_industry_and_no_benchmark_name_sits_under_asset_class(self) -> None:
        """The grid heads a column Asset class, so every value under it is one.

        The reading is the grouping matrix's own: a value with no row under the
        asset_class context, or one that is a sector-context input, is filed in
        the wrong column and reaches the page under that heading."""

        matrix = build_dashboard.read_dicts(
            "data/normalization/transformations/context-grouping-map.csv"
        )
        classes = {row["input_value"].strip().lower() for row in matrix if row.get("context") == "asset_class"}
        industries = {row["input_value"].strip().lower() for row in matrix if row.get("context") == "sector"}
        printed = {
            (row.get("asset_class") or "").strip()
            for row in build_dashboard.read_dicts("data/extracted/tables/fact_observation.csv")
        }
        printed.discard("")
        self.assertEqual(sorted(value for value in printed if value.lower() in industries), [])
        self.assertEqual(sorted(value for value in printed if value.lower() not in classes), [])

    def test_the_portfolio_panels_show_the_taxonomy_beside_the_printed_word(self) -> None:
        weights = self.block_titled("analytics", "Portfolio weights")
        self.assertIn("strategy", weights["columns"])
        self.assertIn("canonical_strategy", weights["columns"])
        self.assertLess(
            weights["columns"].index("strategy"),
            weights["columns"].index("canonical_strategy"),
        )
        counts = build_dashboard.fill_counts(
            "data/csv/portfolio_allocations.csv",
            ("strategy", "sub_strategy") + build_dashboard.CANONICAL_COLUMNS,
        )
        for name, filled in counts.items():
            if filled == 0:
                self.assertNotIn(name, weights["columns"], f"{name} is blank on every row")
                self.assertIn(name, weights["about"], name)
            else:
                self.assertIn(f"{name} {filled:,}", weights["about"], name)
        # The exposure file now carries the reading beside the printed word, so
        # the panel may head the column either way; what it may never do is show
        # a printed grouping without naming the matrix that reads it.
        exposure = self.block_titled("analytics", "Exposure of the demonstration portfolio by printed grouping")
        summary = build_dashboard.read_dicts(
            "data/extracted/review/reviewer-analytics-summary.csv"
        )
        for field in ("canonical_asset_class", "canonical_strategy", "canonical_sector"):
            self.assertIn(field, summary[0])
        self.assertIn("context-grouping-map.csv", exposure["about"])

    def test_every_new_column_carries_its_own_definition(self) -> None:
        """A column resolving through the `canonical_` prefix note is defined
        but says nothing about itself; the four canonical columns each name
        what they read."""

        for name in build_dashboard.CANONICAL_COLUMNS:
            note = column_note(name)
            self.assertTrue(note, name)
            self.assertNotIn("context-grouping-map.csv; the printed column beside it", note, name)
        self.assertIn("sub-strategy", column_note("canonical_sub_strategy"))
        for name in ("method_qualifier", "reported_irr_fee_basis", "reported_irr_method",
                     "period_return_fee_basis", "period_return_method",
                     "input_fee_basis", "input_method", "benchmark_selection"):
            self.assertTrue(column_note(name), name)

    def test_the_model_that_typed_a_row_is_never_shown(self) -> None:
        self.assertIn("extractor_model", build_dashboard.WITHHELD_COLUMNS)
        for section, block in self.blocks("table"):
            self.assertNotIn(
                "extractor_model",
                block["columns"] + block.get("hidden", []),
                f"{section['id']}: {block['title']}",
            )
        for _, block in self.blocks("explorer"):
            for group in block["groups"]:
                for entry in group["tables"]:
                    self.assertNotIn("extractor_model", entry["columns"], entry["name"])

    def test_every_warehouse_return_column_carries_its_qualifier(self) -> None:
        """The explorer picks its columns from the file, so this reads what the
        warehouse now holds beside each return."""

        explorers = [block for _, block in self.blocks("explorer")]
        if not explorers:
            self.skipTest("duckdb is absent, so no explorer is rendered")
        qualifiers = ("method", "method_qualifier", "fee_basis", "definition_keys", "value_scope")
        # A rate the optimizer was configured with states no fee basis because
        # no page printed it; the rule covers the returns read off a page.
        modelled = {"expected_return"}
        for group in explorers[0]["groups"]:
            for entry in group["tables"]:
                columns = entry["columns"]
                returns = [
                    name for name in columns
                    if (name == "return" or name.endswith("_return") or "irr" in name)
                    and name not in modelled
                    and not any(name.endswith("_" + qualifier) for qualifier in qualifiers)
                ]
                if not returns or group["name"] == "alts_mock.duckdb":
                    continue
                carried = [name for name in columns if name in qualifiers] + [
                    name for name in columns
                    if any(name.endswith("_" + qualifier) for qualifier in qualifiers)
                ]
                self.assertTrue(
                    carried,
                    f"{group['name']}.{entry['name']} publishes {returns} with no qualifier column",
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
