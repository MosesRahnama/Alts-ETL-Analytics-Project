"""Guards for the wide layer: the pivot loses nothing and the schema is declared.

Every published observation has to land in one wide row, every wide table has
to carry one column per vocabulary name preferred for its family plus one per
name the facts carry in it, the DDL on disk has to be the DDL the module
renders, and the whole set has to load under the foreign keys it declares.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import duckdb

from src.catalog.simple_pdf_extraction import csv_wide_contract as contract
from src.flatten import load_star, pivot_wide
from src.pipeline import build_extracted_database

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLE_DIR = PROJECT_ROOT / "data" / "extracted" / "tables"
WIDE_DIR = PROJECT_ROOT / "data" / "extracted" / "wide"


def read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class ContractShapeTests(unittest.TestCase):
    def test_one_wide_table_per_contract_family(self) -> None:
        self.assertEqual(
            [pivot_wide.table_name(f) for f in pivot_wide.families()],
            [f"wide_{f}" for f in sorted(contract.FAMILY_CONTRACTS)],
        )

    def test_every_allowed_category_is_a_column(self) -> None:
        for family in pivot_wide.families():
            if family == pivot_wide.CONTEXT_FAMILY:
                continue
            columns = set(pivot_wide.wide_columns(family))
            for category in pivot_wide.categories(family):
                self.assertIn(pivot_wide.column_for(category), columns, (family, category))

    def test_a_category_that_collides_with_a_context_column_is_suffixed(self) -> None:
        self.assertEqual(pivot_wide.column_for("strategy"), "strategy_category")
        self.assertEqual(pivot_wide.column_for("irr"), "irr")
        for family in pivot_wide.families():
            names = list(pivot_wide.wide_columns(family))
            self.assertEqual(len(names), len(set(names)), f"{family} declares a column twice")

    def test_ddl_on_disk_is_the_ddl_the_contract_renders(self) -> None:
        self.assertEqual(
            pivot_wide.DDL_PATH.read_text(encoding="utf-8"), pivot_wide.render_ddl()
        )

    def test_ddl_columns_match_the_csv_columns(self) -> None:
        connection = duckdb.connect(":memory:")
        try:
            connection.execute(load_star.DDL.read_text(encoding="utf-8"))
            connection.execute(load_star.WIDE_DDL.read_text(encoding="utf-8"))
            for family in pivot_wide.families():
                table = pivot_wide.table_name(family)
                found = [
                    row[1]
                    for row in connection.execute(
                        f"SELECT * FROM pragma_table_info('{table}') ORDER BY cid"
                    ).fetchall()
                ]
                self.assertEqual(found, list(pivot_wide.wide_columns(family)), table)
            bridge = [
                row[1]
                for row in connection.execute(
                    "SELECT * FROM pragma_table_info('bridge_pivot_observation') ORDER BY cid"
                ).fetchall()
            ]
            self.assertEqual(bridge, list(pivot_wide.BRIDGE_COLUMNS))
            self.assertEqual(
                sorted(load_star.wide_table_order()),
                sorted([pivot_wide.table_name(f) for f in pivot_wide.families()] + ["bridge_pivot_observation"]),
            )
        finally:
            connection.close()


class BuiltWideTests(unittest.TestCase):
    """The wide layer on disk, read back and reconciled against the facts."""

    @classmethod
    def setUpClass(cls) -> None:
        if not (WIDE_DIR / "bridge_pivot_observation.csv").is_file():
            raise unittest.SkipTest("run `src.pipeline.build_extracted_database --stage wide` first")
        cls.facts = read(TABLE_DIR / "fact_observation.csv")
        cls.holdings = read(TABLE_DIR / "fact_holding.csv")
        cls.bridge = read(WIDE_DIR / "bridge_pivot_observation.csv")
        cls.wide = {
            family: read(WIDE_DIR / f"{pivot_wide.table_name(family)}.csv")
            for family in pivot_wide.families()
        }

    def test_every_observation_lands_in_one_wide_row(self) -> None:
        landed = Counter(
            row["observation_id"] for row in self.bridge if row["pivot_table"].startswith("wide_")
        )
        self.assertEqual(len(landed), len(self.facts))
        self.assertEqual(max(landed.values()), 1, "an observation appears in two wide rows")
        fact_ids = {row["observation_id"] for row in self.facts}
        self.assertEqual(set(landed), fact_ids)

    def test_wide_rows_account_for_every_cell(self) -> None:
        total = sum(
            int(row["observation_count"]) for rows in self.wide.values() for row in rows
        )
        self.assertEqual(total, len(self.facts))

    def test_family_row_counts_match_the_facts(self) -> None:
        by_family = Counter(row["record_family"] for row in self.facts)
        for family, rows in self.wide.items():
            cells = sum(int(row["observation_count"]) for row in rows)
            self.assertEqual(cells, by_family.get(family, 0), family)

    def test_the_pivot_never_overwrote_a_value(self) -> None:
        for family, rows in self.wide.items():
            if family == pivot_wide.CONTEXT_FAMILY:
                continue
            clashes = [row for row in rows if row["collision_note"]]
            self.assertEqual(clashes, [], f"{family}: {clashes[:2]}")

    def test_holdings_bridge_matches_their_observation_lists(self) -> None:
        via_bridge = Counter(
            row["pivot_row_id"] for row in self.bridge if row["pivot_table"] == pivot_wide.HOLDING_TABLE
        )
        for row in self.holdings:
            self.assertEqual(via_bridge[row["holding_id"]], int(row["observation_count"]))

    def test_a_split_row_carries_its_column_label(self) -> None:
        rows = self.wide["financial_statement_observation"]
        split = [row for row in rows if row["column_group"]]
        self.assertTrue(split, "statement tables with entity columns should split")
        for row in split:
            self.assertEqual(int(row["observation_count"]), 1)

    def test_the_wide_layer_loads_under_its_foreign_keys(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "extracted.duckdb"
            counts = load_star.load(TABLE_DIR, database, rebuild=True, wide_dir=WIDE_DIR)
            self.assertEqual(counts["bridge_pivot_observation"], len(self.bridge))
            connection = duckdb.connect(str(database), read_only=True)
            try:
                foreign_keys = connection.execute(
                    "SELECT COUNT(*) FROM duckdb_constraints() WHERE constraint_type = 'FOREIGN KEY'"
                ).fetchone()[0]
                self.assertGreater(foreign_keys, 30)
                joined = connection.execute(
                    'SELECT COUNT(*) FROM bridge_pivot_observation b '
                    'JOIN fact_observation o ON o.observation_id = b.observation_id'
                ).fetchone()[0]
                self.assertEqual(joined, len(self.bridge))
            finally:
                connection.close()


class ScratchRebuildTests(unittest.TestCase):
    def test_all_in_one_builder_supports_scratch_paths(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            table_dir = root / "tables"
            wide_dir = root / "wide"
            database = root / "extracted.duckdb"
            args = build_extracted_database.build_parser().parse_args(
                [
                    "--stage", "flatten",
                    "--stage", "wide",
                    "--stage", "load",
                    "--table-dir", str(table_dir),
                    "--wide-dir", str(wide_dir),
                    "--database", str(database),
                    "--require-all-names-settled",
                ]
            )
            self.assertEqual(build_extracted_database.run(args), 0)
            self.assertTrue((table_dir / "observation_lineage.csv").is_file())
            self.assertTrue(database.is_file())


if __name__ == "__main__":
    unittest.main()
