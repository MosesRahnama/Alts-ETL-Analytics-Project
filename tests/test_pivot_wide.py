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

    def test_every_measure_table_carries_the_taxonomy_and_the_qualifiers(self) -> None:
        """A printed grouping with no reading beside it, and a return with no
        method or fee basis, are the two ways a wide table presents a value a
        reader cannot interpret. Every measure family carries both sets."""

        expected = {
            "sector", "canonical_asset_class", "canonical_strategy",
            "canonical_sub_strategy", "canonical_sector",
            "method_qualifier", "fee_basis", "definition_keys", "value_scope",
        }
        for family in pivot_wide.families():
            if family in (pivot_wide.CONTEXT_FAMILY, pivot_wide.DEFINITION_FAMILY):
                continue
            with self.subTest(family=family):
                columns = set(pivot_wide.wide_columns(family))
                self.assertEqual(expected - columns, set())
                self.assertIn("qualifier_note", columns)

    def test_the_return_qualifiers_sit_beside_the_return_column(self) -> None:
        for family in ("performance_observation", "fund_economics_observation"):
            with self.subTest(family=family):
                columns = pivot_wide.wide_columns(family)
                self.assertIn("return", columns)
                self.assertIn("method_qualifier", columns)
                self.assertIn("fee_basis", columns)

    def test_carrying_the_qualifiers_renamed_no_measure_column(self) -> None:
        """`method` is the valuation family's own printed measure as well as
        the return qualifier. Putting the qualifier in CONTEXT_COLUMNS under
        its own name would have reserved `method` and renamed that measure to
        `method_category`, so the qualifier takes the name the rename matrix
        gives it and every measure column keeps the name it had."""

        self.assertEqual(pivot_wide.context_column_for("method"), "method_qualifier")
        self.assertEqual(pivot_wide.column_for("method"), "method")
        self.assertIn("method", pivot_wide.wide_columns("valuation_observation"))
        self.assertIn("method_qualifier", pivot_wide.wide_columns("valuation_observation"))
        # The one rename that predates the taxonomy carry stays exactly as it was.
        self.assertEqual(pivot_wide.column_for("strategy"), "strategy_category")
        for family in pivot_wide.families():
            for category in pivot_wide.categories(family):
                if category not in ("strategy",):
                    self.assertEqual(
                        pivot_wide.column_for(category), category, (family, category)
                    )

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


class DefinitionIdentityTests(unittest.TestCase):
    """A printed note is identified by its physical cell, like a value."""

    def test_two_notes_under_one_marker_on_one_page_keep_distinct_ids(self) -> None:
        # SRC375 page 2, 2026-09-02: "Annualized" under a figure and under a
        # table, one occurrence each, told apart only by the column label.
        shared = {
            "document_id": "SRC375", "route": "03-institutional-report",
            "source_page": "2", "definition_keys": "ANNUALIZED",
            "source_row_label": "Annualized", "source_occurrence": "1",
        }
        figure = {**shared, "source_column_label": "", "observation_id": "a" * 20,
                  "source_table": "Long Term Pool Relative Performance"}
        table = {**shared, "source_column_label": "Annualized", "observation_id": "b" * 20,
                 "source_table": "Long Term Pool Strategy Allocation and Investment Returns"}
        wide = pivot_wide.build_definition_context([figure, table])
        self.assertEqual(len(wide), 2)
        self.assertNotEqual(wide[0]["wide_row_id"], wide[1]["wide_row_id"])
        self.assertEqual(
            {row["observation_ids"] for row in wide}, {"a" * 20, "b" * 20}
        )


class QualifierCarryTests(unittest.TestCase):
    """A qualifier belongs to the cell that states it, not to the printed row.

    Every other context column is taken from the group's first cell, which is
    right for the page and the subject and wrong here: a printed row whose
    first cell is a commitment and whose second is a return states its method
    on the second cell only. Taking the first cell would have published a blank
    method on 72 of the 4,305 wide rows, a blank value_scope on 73, and blank
    definition_keys on 76."""

    FAMILY = "performance_observation"

    def cell(self, category: str, **overrides: str) -> dict[str, str]:
        row = {name: "" for name in (*pivot_wide.CONTEXT_SOURCES, *pivot_wide.GRAIN)}
        row.update(
            {
                "observation_id": f"OBS_{category}_{overrides.get('source_column_label', '1')}",
                "document_id": "SRC001",
                "page_id": "PAGE_1",
                "source_page": "7",
                "source_table": "Performance Summary",
                "source_row_label": "Fund I",
                "source_occurrence": "1",
                "metric_category": category,
                "term_category": "",
                "value_numeric": "12.5",
                "value_raw": "12.5%",
                "value_text": "",
                "value_kind": "percent",
                "source_column_label": "Total",
            }
        )
        row.update(overrides)
        return row

    def build(self, cells):
        rows, _collisions = pivot_wide.build_family(self.FAMILY, cells)
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_a_qualifier_stated_on_a_later_cell_still_reaches_the_row(self) -> None:
        row = self.build(
            [
                self.cell("aum", source_column_label="AUM"),
                self.cell(
                    "return",
                    source_column_label="Net Return",
                    method="modified_dietz",
                    fee_basis="net",
                    definition_keys="FN1",
                ),
            ]
        )
        self.assertEqual(row["method_qualifier"], "modified_dietz")
        self.assertEqual(row["fee_basis"], "net")
        self.assertEqual(row["definition_keys"], "FN1")
        self.assertEqual(row["qualifier_note"], "")

    def test_two_cells_stating_different_qualifiers_say_so(self) -> None:
        """A return and an irr printed on one line legitimately differ."""

        row = self.build(
            [
                self.cell("return", source_column_label="Net", fee_basis="net"),
                self.cell("irr", source_column_label="Gross IRR", fee_basis="gross"),
            ]
        )
        self.assertEqual(row["fee_basis"], "net")
        self.assertIn("fee_basis=gross|net", row["qualifier_note"])

    def test_the_method_and_fee_basis_come_from_one_cell(self) -> None:
        """The SRC457 row: an irr stating `unstated` printed before a net return.

        Read one column at a time, the row took its method from the return
        and its fee basis from the irr, a pair no cell states. The two are
        read together from the first cell that states a method.
        """

        row = self.build(
            [
                self.cell("irr", source_column_label="IRR", fee_basis="unstated"),
                self.cell(
                    "return",
                    source_column_label="Net TWR",
                    method="time_weighted",
                    fee_basis="net",
                ),
            ]
        )
        self.assertEqual((row["method_qualifier"], row["fee_basis"]), ("time_weighted", "net"))
        self.assertIn("fee_basis=net|unstated", row["qualifier_note"])

    def test_a_row_with_no_return_takes_its_fee_basis_from_the_irr(self) -> None:
        row = self.build(
            [
                self.cell("aum", source_column_label="AUM", value_scope="fund"),
                self.cell("irr", source_column_label="IRR", fee_basis="net", definition_keys="2"),
            ]
        )
        self.assertEqual(row["method_qualifier"], "")
        self.assertEqual(row["fee_basis"], "net")
        self.assertEqual(row["definition_keys"], "2")
        self.assertEqual(row["value_scope"], "fund")

    def test_a_row_whose_cells_state_nothing_carries_no_qualifier(self) -> None:
        row = self.build([self.cell("aum"), self.cell("sharpe_ratio")])
        for column in ("method_qualifier", "fee_basis", "definition_keys", "value_scope"):
            self.assertEqual(row[column], "", column)
        self.assertEqual(row["qualifier_note"], "")

    def test_the_taxonomy_comes_from_the_group_like_any_other_context(self) -> None:
        row = self.build(
            [
                self.cell("aum", asset_class="Private Equity",
                          canonical_asset_class="private_equity", sector="Manufacturing",
                          canonical_sector="Manufacturing"),
                self.cell("return"),
            ]
        )
        self.assertEqual(row["canonical_asset_class"], "private_equity")
        self.assertEqual(row["sector"], "Manufacturing")
        self.assertEqual(row["canonical_sector"], "Manufacturing")


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
            # The two context families carry notes and identity, not measures,
            # so no cell of theirs can land on another's column.
            if family in (pivot_wide.CONTEXT_FAMILY, pivot_wide.DEFINITION_FAMILY):
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
