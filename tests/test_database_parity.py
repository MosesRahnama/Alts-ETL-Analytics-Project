from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from src.load.load_csv_to_duckdb import database_file_parity


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
