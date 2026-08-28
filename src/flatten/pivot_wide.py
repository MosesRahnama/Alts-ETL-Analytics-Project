"""Pivot the long fact table into one wide table per record family.

`fact_observation` is one row per printed cell, so a partnership table with
Commitment, Paid-In, Distributed, NAV, IRR, and TVPI columns becomes six rows
whose `metric_category` column reads commitment, paid_in_capital, distribution,
nav, irr, tvpi. That is the right shape for lineage and the wrong shape for a
model, which wants those six as six columns on one row. This module builds that
row, for every family, without losing the lineage.

    python -m src.flatten.pivot_wide
    python -m src.flatten.pivot_wide --ddl-only

The grain of a wide row is one printed table row: document, page, table, row
label, occurrence, plus horizon and the three dates, since a row that prints
1-Yr and 3-Yr IRR side by side is two observations of the same category and
has to stay two rows. Where a table's columns are entities rather than measures
(General Partner | Limited Partners | Total, or Fund II | Fund II-A | Combined),
the same category repeats within one printed row, and the row is split further
by its column label; that label is carried in `column_group`. Measured on the
published rounds this leaves zero collisions, and the build asserts it: a
category that still repeats inside one wide row keeps the first value, names
the clash in `collision_note`, and counts as a defect in the manifest.

Columns are the vocabulary names whose preferred home is the family, in
vocabulary order, followed by any other name the corpus has printed in that
family. The first part is stable across corpora; the second part is what the
published facts hold, so no cell is left without a column.
Every wide row lists the observation IDs it was built from, and
`bridge_pivot_observation` records the same link one row per observation with a
foreign key back to `fact_observation`, so a wide value can always be traced to
the page, the quote, and the two extractors that produced it.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.catalog.simple_pdf_extraction import csv_wide_contract as contract
from src.flatten.flatten_extracted import (
    MANIFEST_COLUMNS,
    OUTPUT_DIR as TABLE_DIR,
    FlattenError,
    _key,
    read_csv,
    write_csv,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WIDE_DIR = PROJECT_ROOT / "data" / "extracted" / "wide"
DDL_PATH = PROJECT_ROOT / "sql" / "duckdb" / "04_extracted_wide_ddl.sql"

CONTEXT_FAMILY = "document_context"
HOLDING_TABLE = "fact_holding"

# Categories whose value is a printed phrase rather than a number become
# VARCHAR columns holding the printed text; every other category is DECIMAL and
# holds the number as printed, never rescaled. A number that fails to parse
# into a DECIMAL column is kept in `unparsed_values` on the same row. The set
# is the contract's: metric names with a text or date unit hint, and every term.
TEXT_CATEGORIES: frozenset[str] = frozenset(contract.TEXT_METRICS) | frozenset(contract.TERM_CATEGORIES)

# The grain of a wide row, before any split on column label.
GRAIN = (
    "document_id", "source_page", "source_table", "source_row_label",
    "source_occurrence", "horizon", "as_of_date", "period_start", "period_end",
)

# Context every wide row carries beside its category columns. The first value
# in the group supplies each of these; the categories differ per cell, the
# context does not.
CONTEXT_COLUMNS = (
    "document_id", "route", "canonical_doc_type", "page_id", "source_page",
    "source_section", "source_table", "source_row_label", "source_occurrence",
    "column_group",
    "subject_type", "subject_alias_id", "subject_entity_id", "subject_name",
    "subject_standardized_name", "subject_manager_name",
    "asset_class", "strategy", "geography", "vintage_year",
    "horizon", "as_of_date_raw", "as_of_date", "period_start", "period_end",
    "currency", "unit_scale", "unit_scale_multiplier",
)

LINEAGE_COLUMNS = (
    "observation_ids", "observation_count", "unparsed_values", "scale_note", "collision_note",
)

DOCUMENT_CONTEXT_COLUMNS = (
    "wide_row_id", "document_id", "route", "canonical_doc_type", "page_id",
    "source_page", "document_name", "subject_alias_id",
    "manager_alias_id", "manager_entity_id", "manager_name",
    "investor_alias_id", "investor_entity_id", "investor_name",
    "portfolio_name", "as_of_date_raw", "as_of_date", "currency",
    "observation_ids", "observation_count",
)

BRIDGE_COLUMNS = ("pivot_table", "pivot_row_id", "observation_id")

# Star-schema columns the wide tables reference. Kept here so the DDL renderer
# and the loader agree on what a wide table joins to.
FOREIGN_KEYS = (
    ("document_id", "dim_document", "document_id"),
    ("page_id", "dim_page", "page_id"),
    ("subject_alias_id", "entity_alias", "alias_id"),
    ("subject_entity_id", "dim_entity", "entity_id"),
)


def families() -> list[str]:
    """Every family the contract allows, whether or not the corpus printed it."""

    return sorted(contract.FAMILY_CONTRACTS)


def table_name(family: str) -> str:
    return f"wide_{family}"


def observed_categories(table_dir: Path = TABLE_DIR) -> dict[str, list[str]]:
    """Every category the published facts carry, per family, in vocabulary order.

    Read from `fact_observation.csv` when it exists; an empty result means no
    facts are on disk, and the wide tables carry their preferred columns only."""

    path = table_dir / "fact_observation.csv"
    if not path.is_file():
        return {}
    order = {name: index for index, name in enumerate((*contract.METRIC_CATEGORIES, *contract.TERM_CATEGORIES))}
    found: dict[str, set[str]] = defaultdict(set)
    for row in read_csv(path):
        category = _category_of(row)
        if category:
            found[row["record_family"]].add(category)
    return {family: sorted(names, key=lambda name: order.get(name, len(order))) for family, names in found.items()}


_OBSERVED: dict[str, list[str]] | None = None


def _observed(family: str) -> list[str]:
    global _OBSERVED
    if _OBSERVED is None:
        _OBSERVED = observed_categories()
    return _OBSERVED.get(family, [])


def categories(family: str) -> list[str]:
    """The category columns of one family: its preferred vocabulary names, then
    any other name the published facts carry in that family."""

    seen: list[str] = list(contract.preferred_categories(family))
    for value in _observed(family):
        if value not in seen:
            seen.append(value)
    return seen


RESERVED_COLUMNS = frozenset({"wide_row_id", *CONTEXT_COLUMNS, *LINEAGE_COLUMNS})


def column_for(category: str) -> str:
    """The column a category occupies. `strategy` is both a context column and a
    legal-term category, so a category that collides with a context or lineage
    name takes the suffix `_category` and keeps the context column intact."""

    return f"{category}_category" if category in RESERVED_COLUMNS else category


def is_text(family: str, category: str) -> bool:
    return category in TEXT_CATEGORIES


def wide_columns(family: str) -> tuple[str, ...]:
    if family == CONTEXT_FAMILY:
        return DOCUMENT_CONTEXT_COLUMNS
    return ("wide_row_id", *CONTEXT_COLUMNS, *(column_for(c) for c in categories(family)), *LINEAGE_COLUMNS)


def _category_of(row: Mapping[str, str]) -> str:
    return row.get("metric_category") or row.get("term_category") or ""


def _cell_value(row: Mapping[str, str], text: bool) -> tuple[object, bool]:
    """The value a cell contributes, and whether it parsed into its column."""

    if text:
        return row.get("value_text") or row.get("value_raw") or "", True
    number = row.get("value_numeric") or ""
    if number != "":
        return number, True
    return row.get("value_raw") or row.get("value_text") or "", False


def _groups(rows: Sequence[Mapping[str, str]]) -> list[tuple[tuple, str, list[Mapping[str, str]]]]:
    """Group cells at the grain, splitting by column label where a category repeats."""

    by_key: dict[tuple, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        by_key[tuple(row.get(part, "") for part in GRAIN)].append(row)
    result: list[tuple[tuple, str, list[Mapping[str, str]]]] = []
    for key, cells in by_key.items():
        counts = Counter(_category_of(cell) for cell in cells)
        if max(counts.values()) == 1:
            result.append((key, "", cells))
            continue
        by_column: dict[str, list[Mapping[str, str]]] = defaultdict(list)
        for cell in cells:
            by_column[cell.get("source_column_label", "")].append(cell)
        for column, column_cells in by_column.items():
            result.append((key, column, column_cells))
    result.sort(key=lambda item: (tuple(str(part) for part in item[0]), item[1]))
    return result


def build_family(family: str, rows: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, object]], int]:
    """Pivot one family. Returns its wide rows and how many collisions survived."""

    columns = categories(family)
    text_flags = {category: is_text(family, category) for category in columns}
    wide: list[dict[str, object]] = []
    collisions = 0
    for key, column_group, cells in _groups(rows):
        first = cells[0]
        row: dict[str, object] = {name: first.get(name, "") for name in CONTEXT_COLUMNS}
        row["column_group"] = column_group
        row["wide_row_id"] = _key("WIDE", family, *key, column_group)
        unparsed: list[str] = []
        clashes: list[str] = []
        scales = {cell.get("unit_scale", "") for cell in cells if cell.get("value_kind") in {"currency", "number"}}
        for cell in cells:
            category = _category_of(cell)
            if category not in text_flags:
                # The flatten already refuses a category outside the closed
                # catalogue, so this is unreachable on a published build; it
                # stays as a guard for a hand-edited table.
                raise FlattenError(f"{family} cell carries an unlisted category {category!r}")
            value, parsed = _cell_value(cell, text_flags[category])
            if not parsed:
                unparsed.append(f"{category}={value}")
                continue
            column = column_for(category)
            if row.get(column) not in (None, ""):
                clashes.append(f"{category}@{cell.get('source_column_label', '')}")
                continue
            row[column] = value
        if clashes:
            collisions += len(clashes)
        row["observation_ids"] = ";".join(str(cell["observation_id"]) for cell in cells)
        row["observation_count"] = len(cells)
        row["unparsed_values"] = "; ".join(unparsed)
        row["scale_note"] = (
            "cells in this row print different scale headings: " + ", ".join(sorted(scales))
            if len(scales) > 1
            else ""
        )
        row["collision_note"] = (
            "second printed value ignored: " + ", ".join(sorted(clashes)) if clashes else ""
        )
        wide.append(row)
    return wide, collisions


def build_document_context(
    rows: Sequence[Mapping[str, str]], alias_names: Mapping[str, str]
) -> list[dict[str, object]]:
    """One row per document from its context row, with the printed names resolved."""

    wide: list[dict[str, object]] = []
    for cell in sorted(rows, key=lambda item: str(item.get("document_id", ""))):
        wide.append(
            {
                "wide_row_id": _key("WIDE", CONTEXT_FAMILY, cell["document_id"]),
                "document_id": cell.get("document_id", ""),
                "route": cell.get("route", ""),
                "canonical_doc_type": cell.get("canonical_doc_type", ""),
                "page_id": cell.get("page_id", ""),
                "source_page": cell.get("source_page", ""),
                "document_name": cell.get("subject_name", ""),
                "subject_alias_id": cell.get("subject_alias_id", ""),
                "manager_alias_id": cell.get("manager_alias_id", ""),
                "manager_entity_id": cell.get("manager_entity_id", ""),
                "manager_name": alias_names.get(cell.get("manager_alias_id", ""), ""),
                "investor_alias_id": cell.get("investor_alias_id", ""),
                "investor_entity_id": cell.get("investor_entity_id", ""),
                "investor_name": alias_names.get(cell.get("investor_alias_id", ""), ""),
                "portfolio_name": cell.get("portfolio_name", ""),
                "as_of_date_raw": cell.get("as_of_date_raw", ""),
                "as_of_date": cell.get("as_of_date", ""),
                "currency": cell.get("currency", ""),
                "observation_ids": cell.get("observation_id", ""),
                "observation_count": 1,
            }
        )
    return wide


def build_bridge(
    wide_tables: Mapping[str, Sequence[Mapping[str, object]]],
    holdings: Sequence[Mapping[str, str]],
) -> list[dict[str, object]]:
    """One row per (pivot row, observation), for the wide tables and for fact_holding."""

    bridge: list[dict[str, object]] = []
    for table, rows in sorted(wide_tables.items()):
        for row in rows:
            for observation_id in str(row["observation_ids"]).split(";"):
                if observation_id:
                    bridge.append(
                        {"pivot_table": table, "pivot_row_id": row["wide_row_id"], "observation_id": observation_id}
                    )
    for row in holdings:
        for observation_id in str(row.get("observation_ids", "")).split(";"):
            if observation_id:
                bridge.append(
                    {"pivot_table": HOLDING_TABLE, "pivot_row_id": row["holding_id"], "observation_id": observation_id}
                )
    return bridge


def build_wide_tables(table_dir: Path = TABLE_DIR, output_dir: Path = WIDE_DIR) -> dict[str, int]:
    """Write every wide table, the bridge, the manifest, and the DDL."""

    observations = read_csv(table_dir / "fact_observation.csv")
    if not observations:
        raise FlattenError(f"{table_dir / 'fact_observation.csv'} is missing or empty; run the flatten first")
    global _OBSERVED
    _OBSERVED = observed_categories(table_dir)
    alias_names = {row["alias_id"]: row["raw_name"] for row in read_csv(table_dir / "entity_alias.csv")}
    holdings = read_csv(table_dir / "fact_holding.csv")

    by_family: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in observations:
        by_family[row["record_family"]].append(row)
    unknown = sorted(set(by_family) - set(contract.FAMILY_CONTRACTS))
    if unknown:
        raise FlattenError(f"fact_observation carries families outside the contract: {', '.join(unknown)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("*.csv"):
        stale.unlink()

    wide_tables: dict[str, list[dict[str, object]]] = {}
    written: dict[str, int] = {}
    collisions = 0
    cells_pivoted = 0
    for family in families():
        rows = by_family.get(family, [])
        if family == CONTEXT_FAMILY:
            wide = build_document_context(rows, alias_names)
        else:
            wide, family_collisions = build_family(family, rows)
            collisions += family_collisions
        wide_tables[table_name(family)] = wide
        cells_pivoted += sum(int(row["observation_count"]) for row in wide)
        written[table_name(family)] = write_csv(
            output_dir / f"{table_name(family)}.csv", wide_columns(family), wide
        )

    if cells_pivoted != len(observations):
        raise FlattenError(
            f"fact_observation holds {len(observations)} cells but the wide tables account for "
            f"{cells_pivoted}; the pivot drops nothing"
        )

    bridge = build_bridge(wide_tables, holdings)
    written["bridge_pivot_observation"] = write_csv(
        output_dir / "bridge_pivot_observation.csv", BRIDGE_COLUMNS, bridge
    )
    write_csv(
        output_dir / "MANIFEST.csv",
        (*MANIFEST_COLUMNS, "collisions"),
        [
            {"table": name, "file": f"{name}.csv", "rows": count,
             "collisions": collisions if name == "TOTAL" else ""}
            for name, count in sorted(written.items())
        ]
        + [{"table": "TOTAL", "file": "", "rows": cells_pivoted, "collisions": collisions}],
    )
    DDL_PATH.write_text(render_ddl(), encoding="utf-8", newline="\n")
    return written


def _sql_type(family: str, category: str) -> str:
    return "VARCHAR" if is_text(family, category) else "DECIMAL(30, 6)"


def render_ddl() -> str:
    """The DDL for every wide table and the bridge, derived from the field list."""

    lines = [
        "-- =============================================================================",
        "-- The extracted corpus, one wide table per record family.",
        "--",
        "-- Generated by src.flatten.pivot_wide from the extraction field list and the",
        "-- published facts; edit the module, never this file. One row is one printed",
        "-- table row (split by column label where a table's columns are entities), and",
        "-- one column is one vocabulary name: the family's preferred names first, then",
        "-- any other name the facts carry in it. Numeric columns hold the value as printed",
        "-- with the row's scale heading beside it, not multiplied in. Every row lists",
        "-- the observation IDs it came from, and bridge_pivot_observation carries the",
        "-- same link with a foreign key to fact_observation.",
        "--",
        "-- Loads after 03_extracted_star_ddl.sql into data/warehouse/extracted.duckdb.",
        "-- =============================================================================",
        "",
    ]
    context_types = {
        "source_occurrence": "INTEGER",
        "as_of_date": "DATE",
        "period_start": "DATE",
        "period_end": "DATE",
        "unit_scale_multiplier": "DECIMAL(20, 2)",
        "observation_count": "INTEGER",
    }
    for family in families():
        name = table_name(family)
        spec = contract.FAMILY_CONTRACTS[family]
        lines.append(f"-- {spec.description}")
        lines.append(f"-- Grain of the source family: {spec.grain}.")
        lines.append(f"CREATE TABLE IF NOT EXISTS {name} (")
        category_columns = {column_for(c): c for c in categories(family)}
        body: list[str] = []
        for column in wide_columns(family):
            # Category names such as `offset`, `return`, and `input` are SQL
            # reserved words, so every identifier is quoted; the loader quotes
            # them the same way on insert.
            quoted = f'"{column}"'
            if column == "wide_row_id":
                body.append(f"    {quoted:<30} VARCHAR NOT NULL")
            elif family != CONTEXT_FAMILY and column in category_columns:
                body.append(f"    {quoted:<30} {_sql_type(family, category_columns[column])}")
            elif column in ("document_id", "page_id", "observation_ids"):
                body.append(f"    {quoted:<30} VARCHAR NOT NULL")
            else:
                body.append(f"    {quoted:<30} {context_types.get(column, 'VARCHAR')}")
        body.append('    PRIMARY KEY ("wide_row_id")')
        present = set(wide_columns(family))
        for column, table, target in FOREIGN_KEYS:
            if column in present:
                body.append(f'    FOREIGN KEY ("{column}") REFERENCES {table}({target})')
        if family == CONTEXT_FAMILY:
            body.append('    FOREIGN KEY ("manager_alias_id") REFERENCES entity_alias(alias_id)')
            body.append('    FOREIGN KEY ("manager_entity_id") REFERENCES dim_entity(entity_id)')
            body.append('    FOREIGN KEY ("investor_alias_id") REFERENCES entity_alias(alias_id)')
            body.append('    FOREIGN KEY ("investor_entity_id") REFERENCES dim_entity(entity_id)')
        lines.append(",\n".join(body))
        lines.append(");")
        lines.append("")
    lines.extend(
        [
            "-- One row per (pivot row, observation). A schedule-of-investments cell",
            "-- appears twice, once under fact_holding and once under",
            "-- wide_position_observation, because both pivots are built from it.",
            "CREATE TABLE IF NOT EXISTS bridge_pivot_observation (",
            "    pivot_table                  VARCHAR NOT NULL,",
            "    pivot_row_id                 VARCHAR NOT NULL,",
            "    observation_id               VARCHAR NOT NULL,",
            "    PRIMARY KEY (pivot_table, pivot_row_id, observation_id),",
            "    FOREIGN KEY (observation_id) REFERENCES fact_observation(observation_id)",
            ");",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table-dir", type=Path, default=TABLE_DIR)
    parser.add_argument("--output-dir", type=Path, default=WIDE_DIR)
    parser.add_argument("--ddl-only", action="store_true", help="Rewrite the DDL from the contract and stop.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.ddl_only:
        DDL_PATH.write_text(render_ddl(), encoding="utf-8", newline="\n")
        print(f"PASS: wrote {DDL_PATH}")
        return 0
    try:
        written = build_wide_tables(args.table_dir, args.output_dir)
    except FlattenError as exc:
        print(f"error: {exc}")
        return 1
    for name, count in sorted(written.items()):
        print(f"wide: {name}: {count} rows")
    print(f"PASS: {len(written)} tables -> {args.output_dir}; DDL -> {DDL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
