"""Guards for the flatten stage: its parsers, its contracts, and its refusals."""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

import duckdb

from src.catalog.simple_pdf_extraction import csv_wide_contract as contract
from src.flatten import flatten_extracted as flatten
from src.flatten import load_star
from src.pipeline import build_extraction_review

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DDL = PROJECT_ROOT / "sql" / "duckdb" / "03_extracted_star_ddl.sql"
TABLE_DIR = PROJECT_ROOT / "data" / "extracted" / "tables"
STANDARD_MEASURES = PROJECT_ROOT / "data" / "schemas" / "METRIC-STANDARD-MEASURES.csv"
RETURN_METHODS = PROJECT_ROOT / "data" / "schemas" / "RETURN-METHOD-BY-DOCUMENT.csv"


class ValueParsingTests(unittest.TestCase):
    def test_printed_numbers_keep_the_magnitude_the_document_shows(self) -> None:
        cases = [
            ("$415,489,109", "", "currency", 415489109.0, "USD"),
            ("34.22%", "%", "percent", 34.22, ""),
            ("1.85x", "x", "multiple", 1.85, ""),
            ("(1,234.50)", "", "number", -1234.5, ""),
            ("13,307,614", "", "number", 13307614.0, ""),
            ("", "", "none", None, ""),
            ("independent valuation advisor", "", "text", None, ""),
        ]
        for raw, unit, kind, number, currency in cases:
            with self.subTest(raw=raw):
                got_kind, got_number, _sign, got_currency = flatten.parse_value(raw, unit)
                self.assertEqual(got_kind, kind)
                self.assertEqual(got_number, number)
                self.assertEqual(got_currency, currency)

    def test_a_percent_is_never_converted_into_a_fraction(self) -> None:
        _kind, number, _sign, _currency = flatten.parse_value("9.81%", "%")
        self.assertEqual(number, 9.81)

    def test_parentheses_make_a_value_negative(self) -> None:
        _kind, number, sign, _currency = flatten.parse_value("($2,000)", "")
        self.assertEqual(number, -2000.0)
        self.assertEqual(sign, "negative")


class DateParsingTests(unittest.TestCase):
    def test_every_printed_shape_the_corpus_uses(self) -> None:
        cases = [
            ("December 31, 2024", "2024-12-31", "day"),
            ("Dec 31, 2024", "2024-12-31", "day"),
            ("9/30/2021", "2021-09-30", "day"),
            ("01 June 2019", "2019-06-01", "day"),
            ("MONDAY, 01 MAY 2006", "2006-05-01", "day"),
            ("July 2024", "2024-07-31", "month"),
            ("2021", "2021-12-31", "year"),
            ("FY24", "2024-12-31", "year"),
        ]
        for raw, iso, precision in cases:
            with self.subTest(raw=raw):
                self.assertEqual(flatten.parse_date(raw), (iso, precision))

    def test_an_ambiguous_date_is_left_empty_rather_than_guessed(self) -> None:
        iso, precision = flatten.parse_date("June 30, 2017 and 2016")
        self.assertEqual(iso, "")
        self.assertEqual(precision, "unknown")

    def test_a_blank_date_reports_nothing(self) -> None:
        self.assertEqual(flatten.parse_date(""), ("", ""))


class ScaleParsingTests(unittest.TestCase):
    def test_scale_headings_read_currency_and_multiplier(self) -> None:
        cases = [
            ("($ in millions)", "USD", "millions", 1_000_000.0),
            ("(Dollars in thousands)", "USD", "thousands", 1_000.0),
            ("(Expressed in Canadian dollars)", "CAD", "absolute", 1.0),
            ("(MM)", "", "millions", 1_000_000.0),
            ("$", "USD", "absolute", 1.0),
            ("", "", "absolute", 1.0),
        ]
        for raw, currency, scale, multiplier in cases:
            with self.subTest(raw=raw):
                self.assertEqual(flatten.parse_scale(raw), (currency, scale, multiplier))


class BuiltTableTests(unittest.TestCase):
    """The published build has to hold together; these read what is on disk."""

    @classmethod
    def setUpClass(cls) -> None:
        if not (TABLE_DIR / "fact_observation.csv").is_file():
            raise unittest.SkipTest("run `src.pipeline.build_extracted_database` first")
        cls.tables = {}
        for path in TABLE_DIR.glob("*.csv"):
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                cls.tables[path.stem] = list(csv.DictReader(handle))

    def test_the_fact_table_holds_every_published_row(self) -> None:
        published = sum(
            len(flatten.read_csv(path))
            for path in sorted(flatten.ROUNDS_DIR.glob("*-records.csv"))
        )
        self.assertEqual(len(self.tables["fact_observation"]), published)

    def test_observation_ids_are_unique(self) -> None:
        ids = [row["observation_id"] for row in self.tables["fact_observation"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_an_unresolved_alias_never_carries_an_entity(self) -> None:
        for row in self.tables["entity_alias"]:
            if row["match_method"] in {"unresolved", "scope_label"}:
                self.assertEqual(row["entity_id"], "", row["raw_name"])
            if row["match_method"].startswith("matrix_"):
                self.assertTrue(row["standardized_name"], row["raw_name"])

    def test_every_resolved_subject_points_at_a_known_entity(self) -> None:
        entities = {row["entity_id"] for row in self.tables["dim_entity"]}
        for row in self.tables["fact_observation"]:
            if row["subject_entity_id"]:
                self.assertIn(row["subject_entity_id"], entities)

    def test_every_metric_stays_inside_the_closed_catalogue(self) -> None:
        escaped = [
            row["metric_id"]
            for row in self.tables["dim_metric"]
            if row["in_catalogue"] != "true"
        ]
        self.assertEqual(escaped, [])

    def test_standard_measure_matrix_matches_the_published_dimension(self) -> None:
        matrix = flatten.load_standard_measures(STANDARD_MEASURES)
        dimension = {row["metric_id"]: row for row in self.tables["dim_metric"]}
        self.assertEqual(set(matrix), set(dimension))
        for metric_id, row in dimension.items():
            with self.subTest(metric_id=metric_id):
                self.assertEqual(row["standard_measure"], matrix[metric_id]["standard_measure"])
                self.assertEqual(row["measure_scope"], matrix[metric_id]["measure_scope"])
                self.assertEqual(row["note"], matrix[metric_id]["note"])

    def test_return_method_matrix_covers_every_published_return(self) -> None:
        rows = flatten.read_csv(RETURN_METHODS)
        keys = [
            (row["file_id"], row["metric_id"], row["source_table"], row["source_column_label"])
            for row in rows
        ]
        self.assertEqual(len(keys), len(set(keys)))
        facts = [
            row for row in self.tables["fact_observation"]
            if row["metric_id"] in {
                "fund_economics_observation.return",
                "performance_observation.return",
            }
        ]
        for fact in facts:
            matches = [
                row for row in rows
                if row["file_id"] == fact["document_id"]
                and row["metric_id"] == fact["metric_id"]
                and row["source_table"] == fact["source_table"]
                and (
                    not row["source_column_label"]
                    or row["source_column_label"] == fact["source_column_label"]
                )
            ]
            self.assertEqual(len(matches), 1, fact["observation_id"])
        for row in rows:
            matched = any(
                fact["document_id"] == row["file_id"]
                and fact["metric_id"] == row["metric_id"]
                and fact["source_table"] == row["source_table"]
                and (
                    not row["source_column_label"]
                    or fact["source_column_label"] == row["source_column_label"]
                )
                for fact in facts
            )
            self.assertTrue(matched, row)

    def test_the_backlog_matches_the_unresolved_aliases(self) -> None:
        unresolved = {
            (row["entity_kind"], row["raw_name"])
            for row in self.tables["entity_alias"]
            if row["match_method"] == "unresolved"
        }
        backlog = {
            (row["entity_kind"], row["raw_name"]) for row in self.tables["unresolved_names"]
        }
        self.assertEqual(unresolved, backlog)

    def test_holdings_cite_the_observations_they_were_built_from(self) -> None:
        observation_ids = {row["observation_id"] for row in self.tables["fact_observation"]}
        for row in self.tables["fact_holding"]:
            cited = row["observation_ids"].split(";")
            self.assertEqual(len(cited), int(row["observation_count"]))
            for observation_id in cited:
                self.assertIn(observation_id, observation_ids)


class SchemaContractTests(unittest.TestCase):
    def test_ddl_enums_match_the_extraction_contract(self) -> None:
        text = DDL.read_text(encoding="utf-8")
        for values in (
            contract.PAGE_STATUSES,
            contract.EVIDENCE_CLASSES,
            contract.SOURCE_STRUCTURE_TYPES,
            contract.SUBJECT_TYPES,
        ):
            rendered = ", ".join(f"'{value}'" for value in values)
            self.assertIn(rendered, text)

    def test_ddl_columns_match_the_written_csv_columns(self) -> None:
        connection = duckdb.connect(":memory:")
        try:
            connection.execute(DDL.read_text(encoding="utf-8"))
            # The star table observation_lineage is the thirteen-column file
            # under data/extracted/tables/; the review lineage under
            # data/extracted/review/ is a wider reviewer file with paths and row
            # numbers and is not loaded into the star.
            with (TABLE_DIR / "observation_lineage.csv").open(encoding="utf-8-sig", newline="") as handle:
                lineage_columns = next(csv.reader(handle))
            expected = {
                "dim_document": flatten.DOCUMENT_COLUMNS,
                "dim_page": flatten.PAGE_COLUMNS,
                "dim_entity": flatten.ENTITY_COLUMNS,
                "entity_alias": flatten.ALIAS_COLUMNS,
                "dim_metric": flatten.METRIC_COLUMNS,
                "fact_observation": flatten.OBSERVATION_COLUMNS,
                "observation_lineage": lineage_columns,
                "fact_holding": flatten.HOLDING_COLUMN_NAMES,
                "unresolved_names": flatten.UNRESOLVED_COLUMNS,
            }
            for table, columns in expected.items():
                found = [
                    row[1]
                    for row in connection.execute(
                        f"SELECT * FROM pragma_table_info('{table}') ORDER BY cid"
                    ).fetchall()
                ]
                self.assertEqual(found, list(columns), table)
            self.assertEqual(sorted(expected), sorted(load_star.TABLE_ORDER))
        finally:
            connection.close()

    def test_the_loader_refuses_the_fund_model_warehouse(self) -> None:
        with self.assertRaises(load_star.LoadError):
            load_star.load(TABLE_DIR, load_star.FUND_MODEL_DATABASE)


class ManagerCoverageTests(unittest.TestCase):
    """The GP queue is a second review backlog and has to stay complete."""

    def setUp(self) -> None:
        from src.catalog.simple_pdf_extraction import name_normalization

        self.names = name_normalization
        if not name_normalization.WEB_MANAGER_NAMES.is_file():
            self.skipTest("run the managers stage first")
        self.rows = name_normalization.read_csv(name_normalization.WEB_MANAGER_NAMES)

    def test_every_settled_fund_has_a_manager_row(self) -> None:
        queued = {
            (row.get("standardized_fund_name") or "").strip() for row in self.rows
        }
        for standard in self.names.settled_fund_standards():
            self.assertIn(standard, queued)

    def test_the_manager_worksheet_keeps_its_columns_and_one_row_per_fund(self) -> None:
        with self.names.WEB_MANAGER_NAMES.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle))
        self.assertEqual(header, self.names.WEB_MANAGER_HEADER)
        names = [(row.get("standardized_fund_name") or "").strip() for row in self.rows]
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn("", names)

    def test_a_resolved_row_cites_a_source(self) -> None:
        for row in self.rows:
            if (row.get("final_manager_name") or "").strip():
                self.assertTrue(
                    (row.get("final_source") or "").strip(),
                    row["standardized_fund_name"],
                )

    def test_queueing_is_idempotent(self) -> None:
        before = len(self.rows)
        self.names.managers()
        self.assertEqual(len(self.names.read_csv(self.names.WEB_MANAGER_NAMES)), before)


class WorksheetCsvValidityTests(unittest.TestCase):
    """Regression guard for the citation-truncation defect found 2026-08-24:
    an unescaped comma inside a free-text WEB_MANAGER source split one CSV row
    into two, silently truncating the cited sentence. Every worksheet the
    manager round produces must parse back to its own declared column count.
    """

    def test_every_manager_worksheet_row_matches_its_header_width(self) -> None:
        worksheets = sorted(
            (PROJECT_ROOT / "data" / "normalization" / "worksheets").glob(
                "manager-*.csv"
            )
        )
        if not worksheets:
            self.skipTest("no manager worksheets on disk")
        for path in worksheets:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            expected = len(rows[0])
            for line_number, row in enumerate(rows[1:], start=2):
                self.assertEqual(
                    len(row), expected, f"{path.name}:{line_number}"
                )


if __name__ == "__main__":
    unittest.main()
