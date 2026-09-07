"""Guards for the flatten stage: its parsers, its contracts, and its refusals."""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

import duckdb

from src.catalog.simple_pdf_extraction import csv_wide_contract as contract
from src.flatten import flatten_extracted as flatten
from src.flatten import load_star

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DDL = PROJECT_ROOT / "sql" / "duckdb" / "03_extracted_star_ddl.sql"
TABLE_DIR = PROJECT_ROOT / "data" / "extracted" / "tables"
STANDARD_MEASURES = PROJECT_ROOT / "data" / "schemas" / "METRIC-STANDARD-MEASURES.csv"
VOCABULARIES = "closed-vocabularies"


def _vocabulary(context: str) -> tuple[str, ...]:
    """One closed set, in the order the matrix states it."""

    return tuple(
        row["input_value"] for row in flatten.matrices.rows_in(VOCABULARIES, context)
    )


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
        # Every published metric needs a standard measure, or the flatten stage
        # refuses the row. The other direction is looser on purpose: a category
        # is declared here before the round that carries it publishes, so a
        # matrix row without published data is allowed while its category is in
        # the vocabulary, and rejected once it is not.
        self.assertEqual(set(dimension) - set(matrix), set())
        undeclared = {
            metric_id
            for metric_id in set(matrix) - set(dimension)
            if metric_id.split(".", 1)[-1] not in contract.METRIC_CATEGORIES
        }
        self.assertEqual(undeclared, set())
        for metric_id, row in dimension.items():
            with self.subTest(metric_id=metric_id):
                self.assertEqual(row["standard_measure"], matrix[metric_id]["standard_measure"])
                self.assertEqual(row["measure_scope"], matrix[metric_id]["measure_scope"])
                self.assertEqual(row["note"], matrix[metric_id]["note"])

    def test_every_published_return_states_its_method_and_fee_basis(self) -> None:
        """A return is a family of measures. Every published return row
        states the method and fee basis its own page gives, `unstated`
        included, and a stated value names the footnote or printed phrase it
        was read from, so no bare percentage passes as a defined measure."""

        allowed = {
            dimension: {
                row["input_value"].split(":", 1)[1]
                for row in flatten.matrices.load("dimension-values")
                if row["input_value"].startswith(dimension + ":")
            }
            for dimension in ("method", "fee_basis")
        }
        returns = [row for row in self.tables["fact_observation"] if row["metric_category"] == "return"]
        self.assertTrue(returns)
        for row in returns:
            for dimension in ("method", "fee_basis"):
                self.assertIn(row[dimension], allowed[dimension], (row["observation_id"], dimension))
                if row[dimension] != "unstated":
                    self.assertTrue(
                        row["definition_keys"] or row["basis_raw"],
                        (row["observation_id"], dimension),
                    )

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


class HoldingSectorTests(unittest.TestCase):
    """A printed industry has to reach the fund model, and the only path runs
    through fact_holding. The column was declared on fund_holdings and in its
    DDL while fact_holding carried no industry at all, so every promoted
    holding's sector was blank and no page could fill it."""

    def _observation(self, category: str, **overrides: str) -> dict[str, str]:
        row = {
            "observation_id": f"OBS_{category}",
            "record_family": flatten.HOLDING_FAMILY,
            "document_id": "SRC001",
            "route": "06-statements-and-economics",
            "page_id": "PAGE_1",
            "source_page": "4",
            "source_table": "Schedule of Investments",
            "source_row_label": "Acme Industrial Holdings",
            "source_column_label": "Fair Value",
            "source_occurrence": "1",
            "subject_type": "investment",
            "subject_alias_id": "ALIAS_1",
            "subject_entity_id": "ENT_1",
            "sector": "Manufacturing",
            "as_of_date_raw": "December 31, 2024",
            "as_of_date": "2024-12-31",
            "currency": "USD",
            "unit_scale": "thousands",
            "unit_scale_multiplier": "1000.0",
            "metric_category": category,
            "value_numeric": "1250.0",
            "value_raw": "1,250",
            "value_text": "",
        }
        row.update(overrides)
        return row

    def test_fact_holding_carries_the_printed_industry(self) -> None:
        holdings = flatten.build_holdings(
            [self._observation("fair_value"), self._observation("cost")]
        )
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0]["sector"], "Manufacturing")
        self.assertIn("sector", flatten.HOLDING_COLUMN_NAMES)

    def test_a_holding_with_no_printed_industry_stays_blank(self) -> None:
        holdings = flatten.build_holdings([self._observation("fair_value", sector="")])
        self.assertEqual(holdings[0]["sector"], "")

    def test_the_industry_column_sits_where_the_star_schema_declares_it(self) -> None:
        """load_star inserts by header and the parity check compares the CSV
        header against the table's column order, so the position in
        HOLDING_COLUMN_NAMES and in the DDL has to be the same one."""

        connection = duckdb.connect(":memory:")
        try:
            connection.execute(DDL.read_text(encoding="utf-8"))
            declared = [
                row[1]
                for row in connection.execute(
                    "SELECT * FROM pragma_table_info('fact_holding') ORDER BY cid"
                ).fetchall()
            ]
        finally:
            connection.close()
        self.assertEqual(declared, list(flatten.HOLDING_COLUMN_NAMES))
        self.assertEqual(
            declared.index("sector"), flatten.HOLDING_COLUMN_NAMES.index("sector")
        )


class SchemaContractTests(unittest.TestCase):
    def test_ddl_enums_match_the_extraction_contract(self) -> None:
        """Every closed vocabulary the star schema constrains has one home.

        Four of the seven CHECK lists cited a contract constant; the other
        three, value_kind, unit_scale, and adjudication_status, were SQL
        literals with no source, so the vocabulary was stated twice and nothing
        compared the copies. Adding a scale word would have made the flatten
        emit a value the load rejected as a constraint error naming no rule.
        The three now live in closed-vocabularies.csv under a context apiece."""

        text = DDL.read_text(encoding="utf-8")
        sources = {
            "page_status": contract.PAGE_STATUSES,
            "evidence_class": contract.EVIDENCE_CLASSES,
            "source_structure_type": contract.SOURCE_STRUCTURE_TYPES,
            "subject_type": contract.SUBJECT_TYPES,
            "value_kind": _vocabulary("value_kind"),
            "unit_scale": _vocabulary("unit_scale"),
            "adjudication_status": _vocabulary("adjudication_status"),
        }
        for column, values in sources.items():
            with self.subTest(column=column):
                self.assertTrue(values, f"{column} has no declared vocabulary")
                rendered = ", ".join(f"'{value}'" for value in values)
                self.assertIn(rendered, text, column)

    def test_each_constrained_vocabulary_names_its_source(self) -> None:
        """A CHECK list with no source comment is a vocabulary stated twice.

        value_kind, unit_scale, and adjudication_status were the three with no
        source. The comment above each is what tells a reader where to add a
        value so the flatten and the load stay in step, instead of a new scale
        word reaching the load as a constraint error naming no rule."""

        lines = DDL.read_text(encoding="utf-8").splitlines()
        for column in (
            "page_status", "evidence_class", "source_structure_type", "subject_type",
            "value_kind", "unit_scale", "adjudication_status",
        ):
            with self.subTest(column=column):
                found = [
                    number
                    for number, line in enumerate(lines)
                    if line.strip().startswith(f"CHECK ({column} ")
                ]
                self.assertEqual(len(found), 1, column)
                self.assertTrue(
                    lines[found[0] - 1].strip().startswith("--"),
                    f"{DDL.name}:{found[0] + 1} constrains {column} and names no source",
                )

    def test_the_scale_words_the_flatten_writes_are_all_declared(self) -> None:
        """A scale word added to scale-words.csv reaches unit_scale, so the
        DDL's closed set has to carry its output name or the load rejects the
        row the flatten wrote."""

        declared = set(_vocabulary("unit_scale"))
        written = {
            row["output_value"] for row in flatten.matrices.load("scale-words")
        } | {flatten.matrices.resolve("unit-scale-defaults", "no_scale_word_scale")}
        self.assertEqual(written - declared, set())

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


class CanonicalGroupingTests(unittest.TestCase):
    """Each printed grouping is read under the column its heading names.

    The defect this guards: SRC034 prints portfolio-company industries under a
    column headed Industry, and those values once sat in asset_class. An
    industry is a sector and never a class, so a printed sector reaches
    canonical_sector and leaves canonical_asset_class blank, while a class
    printed as a strategy heading still names the class."""

    def test_a_printed_industry_is_a_sector_and_never_a_class(self) -> None:
        reading = flatten.canonical_grouping(
            {"asset_class": "", "strategy": "", "sector": "Commercial Equip. & Services"}
        )
        self.assertEqual(reading["canonical_sector"], "Commercial Equipment & Services")
        self.assertEqual(reading["canonical_asset_class"], "")
        self.assertEqual(reading["canonical_strategy"], "")

    def test_a_class_printed_as_a_strategy_heading_names_the_class(self) -> None:
        reading = flatten.canonical_grouping({"asset_class": "", "strategy": "Real Estate", "sector": ""})
        self.assertEqual(reading["canonical_asset_class"], "real_estate")
        self.assertEqual(reading["canonical_strategy"], "")
        reading = flatten.canonical_grouping({"asset_class": "Real Estate", "strategy": "Value Add", "sector": ""})
        self.assertEqual(reading["canonical_asset_class"], "real_estate")
        self.assertEqual(reading["canonical_strategy"], "value_added")

    def test_a_strategy_never_becomes_an_industry_through_the_matrix(self) -> None:
        """The industry reading comes from a sector heading and nothing else.

        `canonical_grouping` read the matched matrix row's `sector` column
        whatever context matched it, so a strategy row carrying a sector would
        publish a fund strategy as a company industry. Two `strategy_enum` rows
        carry a sector value today, and the loop reaching them is one line
        away."""

        saved = flatten._GROUPING
        flatten._GROUPING = {
            ("strategy", "Healthcare Buyout"): {
                "input_value": "Healthcare Buyout",
                "output_value": "private_equity",
                "canonical_strategy": "buyout",
                "canonical_sub_strategy": "",
                "sector": "Health Care",
                "context": "strategy",
            },
            ("asset_class", "Industrials Sleeve"): {
                "input_value": "Industrials Sleeve",
                "output_value": "private_equity",
                "canonical_strategy": "",
                "canonical_sub_strategy": "",
                "sector": "Manufacturing",
                "context": "asset_class",
            },
        }
        try:
            reading = flatten.canonical_grouping(
                {"asset_class": "", "strategy": "Healthcare Buyout", "sector": ""}
            )
            self.assertEqual(reading["canonical_strategy"], "buyout")
            self.assertEqual(reading["canonical_asset_class"], "private_equity")
            self.assertEqual(reading["canonical_sector"], "")

            reading = flatten.canonical_grouping(
                {"asset_class": "Industrials Sleeve", "strategy": "", "sector": ""}
            )
            self.assertEqual(reading["canonical_asset_class"], "private_equity")
            self.assertEqual(reading["canonical_sector"], "")
        finally:
            flatten._GROUPING = saved

    def test_no_grouping_matrix_row_maps_an_industry_or_a_benchmark_to_a_class(self) -> None:
        rows = flatten.matrices.load("context-grouping-map")
        sectors = {row["input_value"] for row in rows if row["context"] == "sector"}
        for row in rows:
            if row["context"] == "asset_class":
                self.assertNotIn(row["input_value"], sectors, row["input_value"])
                self.assertNotEqual(row["output_value"], "benchmark", row["input_value"])
                self.assertEqual(row["sector"], "", row["input_value"])

    def test_published_rows_keep_industries_out_of_asset_class(self) -> None:
        sectors = {
            row["input_value"]
            for row in flatten.matrices.load("context-grouping-map")
            if row["context"] == "sector"
        }
        for row in flatten.read_csv(TABLE_DIR / "fact_observation.csv"):
            self.assertNotIn(row["asset_class"], sectors, row["observation_id"])
            if row["sector"]:
                self.assertEqual(row["canonical_asset_class"], "", row["observation_id"])
                self.assertTrue(row["canonical_sector"], row["observation_id"])


if __name__ == "__main__":
    unittest.main()
