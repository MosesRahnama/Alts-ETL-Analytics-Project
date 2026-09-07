from __future__ import annotations

import csv
import re
import tempfile
import unittest
from pathlib import Path

import duckdb
import yaml

from src.analytics.run_round04_analytics import (
    FUND_METRIC_COLUMNS,
    PME_RESULT_COLUMNS,
    PORTFOLIO_ALLOCATION_COLUMNS,
)
from src.common import matrices
from src.load.load_csv_to_duckdb import TABLE_FILES, database_file_parity


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DDL_PATH = PROJECT_ROOT / "sql" / "duckdb" / "02_fund_level_ddl.sql"
SCHEMA_PATH = PROJECT_ROOT / "config" / "fund_level_schema.yml"
CSV_DIR = PROJECT_ROOT / "data" / "csv"

# A table-level clause is not a column, and both live in the same list.
CONSTRAINT_KEYWORDS = {"CHECK", "FOREIGN", "PRIMARY", "UNIQUE", "CONSTRAINT"}

# The three analytics tables are written from a column constant instead of an
# existing header, so the constant is what the next release puts on disk.
ANALYTICS_COLUMNS = {
    "fund_metrics": list(FUND_METRIC_COLUMNS),
    "pme_results": list(PME_RESULT_COLUMNS),
    "portfolio_allocations": list(PORTFOLIO_ALLOCATION_COLUMNS),
}


def ddl_columns(table: str) -> list[str]:
    """The column names one CREATE TABLE declares, in declaration order.

    Split on top-level commas so a multi-line CHECK does not read as columns."""

    body = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table} \(\n(.*?)\n\);",
        DDL_PATH.read_text(encoding="utf-8"),
        re.S,
    )
    if body is None:
        raise AssertionError(f"{DDL_PATH.name} declares no table {table}")
    text = "\n".join(line.split("--")[0] for line in body.group(1).splitlines())
    items: list[str] = []
    depth = 0
    current: list[str] = []
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character == "," and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(character)
    items.append("".join(current))
    return [
        item.split()[0]
        for item in items
        if item.split() and item.split()[0].upper() not in CONSTRAINT_KEYWORDS
    ]


def published_columns(table: str, filename: str) -> list[str]:
    """The header the next release writes for one table.

    A promoted table keeps the header already on disk and gains the columns
    promotion-schema-additions.csv appends, in matrix order, which is the rule
    promote_extracted_to_fund_level.write_csv follows."""

    if table in ANALYTICS_COLUMNS:
        return ANALYTICS_COLUMNS[table]
    with (CSV_DIR / filename).open("r", encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle))
    for addition in matrices.load("promotion-schema-additions"):
        owner, _, column = addition["input_value"].partition(":")
        if owner == table and column not in header:
            header.append(column)
    return header


class SchemaParityTests(unittest.TestCase):
    """One column list, stated three times, and the three agree.

    alts.duckdb carried the canonical taxonomy on one table out of eighteen and
    no printed industry at all, and nothing compared the DDL with the header it
    is supposed to load. The loader compares the two in order, so a column added
    to one side and not the other refuses the table at load time."""

    def test_the_ddl_declares_the_header_each_table_publishes(self) -> None:
        for table, filename in TABLE_FILES.items():
            self.assertEqual(
                ddl_columns(table), published_columns(table, filename), table
            )

    def test_the_schema_document_names_the_columns_the_ddl_declares(self) -> None:
        spec = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
        for table, block in spec["tables"].items():
            self.assertEqual(list(block["columns"]), ddl_columns(table), table)

    def test_the_taxonomy_reaches_every_table_that_publishes_a_grouping(self) -> None:
        for table in ("fund_master", "fund_periods", "portfolio_allocations"):
            columns = ddl_columns(table)
            for field in (
                "sector",
                "canonical_asset_class",
                "canonical_strategy",
                "canonical_sub_strategy",
                "canonical_sector",
            ):
                self.assertIn(field, columns, f"{table}.{field}")


class DatabaseParityTests(unittest.TestCase):
    def test_full_content_difference_is_detected_when_counts_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "test.duckdb"
            source = root / "items.csv"
            source.write_text("item_id,value\nA,1\nB,2\n", encoding="utf-8")
            connection = duckdb.connect(str(database))
            connection.execute("CREATE TABLE items(item_id VARCHAR, value INTEGER)")
            connection.execute("INSERT INTO items VALUES ('A', 1), ('B', 2)")
            connection.close()
            self.assertEqual(database_file_parity({"items": source}, database), {})

            source.write_text("item_id,value\nA,1\nB,3\n", encoding="utf-8")
            self.assertGreater(database_file_parity({"items": source}, database)["items"], 0)

    def test_header_drift_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "test.duckdb"
            source = root / "items.csv"
            source.write_text("value,item_id\n1,A\n", encoding="utf-8")
            connection = duckdb.connect(str(database))
            connection.execute("CREATE TABLE items(item_id VARCHAR, value INTEGER)")
            connection.close()
            self.assertEqual(database_file_parity({"items": source}, database), {"items": -1})


if __name__ == "__main__":
    unittest.main()
