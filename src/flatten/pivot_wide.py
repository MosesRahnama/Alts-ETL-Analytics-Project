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

Beside them every row carries the printed grouping read under one taxonomy
(`sector` and the four `canonical_` columns) and what its values mean
(`method`, `fee_basis`, `definition_keys`, `value_scope`), so a return is never
presented as one measure. The two sets are filled differently, and the grain is
not split for either. A taxonomy column describes the printed row, so the first
cell of the group supplies it, as it does for every other context column;
measured on the published facts no group's cells disagree on one. A qualifier
describes the cell, and only the cells of a qualified category state one, so
the group's first stated value fills the column: taking the first cell instead
would publish a blank method on 72 rows, a blank value_scope on 73, and blank
`definition_keys` on 76. The method and the fee basis describe one measure and
are read together from one cell, the first that states a method or, failing
that, a fee basis; read one column at a time they were assembled from two cells
on 69 SRC457 rows, `time_weighted` from the return and `unstated` from the irr
beside it. A row whose cells state two different values for one qualifier,
which a return and an irr printed on one line legitimately do, keeps the
anchoring cell's value and names both in `qualifier_note`.
Every wide row lists the observation IDs it was built from, and
`bridge_pivot_observation` records the same link one row per observation with a
foreign key back to `fact_observation`, so a wide value can always be traced to
the page, the quote, and the two extractors that produced it.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from src.catalog.simple_pdf_extraction import csv_wide_contract as contract
from src.common import matrices
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

# Every decision below is a row in a matrix under
# data/normalization/transformations, read here and checked by release stage 20.
FAMILY_PIVOT = "family-pivot"
TEXT_SOURCES = "text-categories"
COLUMN_TYPES = "category-column-type"
WIDE_GRAIN = "wide-grain"
COLUMN_RENAMES = "wide-column-renames"
CATEGORY_ORDER = "category-field-precedence"
CELL_SOURCES = "wide-cell-value-source"
GROUPING = "wide-column-grouping"
CONTEXT_PRECEDENCE = "wide-context-precedence"
UNPARSED_POLICY = "wide-unparsed-value-policy"
COLLISION_POLICY = "wide-collision-policy"
SCALE_STATUS = "wide-scale-status"
ALIAS_FALLBACK = "context-alias-fallback"
FAMILY_ROUTING = "record-family-routing"


def _pivot_ranked(name: str, context: str) -> tuple[str, ...]:
    rows = sorted(matrices.rows_in(name, context), key=lambda row: int(row["input_value"]))
    return tuple(row["output_value"] for row in rows)


CONTEXT_FAMILY = matrices.resolve(FAMILY_PIVOT, "context_family")
DEFINITION_FAMILY = matrices.resolve(FAMILY_PIVOT, "definition_family")
HOLDING_TABLE = matrices.resolve(FAMILY_PIVOT, "holding_table")

# Categories whose value is a printed phrase rather than a number become
# VARCHAR columns holding the printed text; every other category is DECIMAL and
# holds the number as printed, never rescaled. A number that fails to parse
# into a DECIMAL column is kept in `unparsed_values` on the same row. The set
# is the contract's, named by text-categories.csv: metric names with a text or
# date unit hint, and every term.
def _text_categories() -> frozenset[str]:
    catalogues = {
        "contract.TEXT_METRICS": frozenset(contract.TEXT_METRICS),
        "contract.TERM_CATEGORIES": frozenset(contract.TERM_CATEGORIES),
    }
    selected: set[str] = set()
    for source in matrices.mapping(TEXT_SOURCES).values():
        if source not in catalogues:
            raise matrices.MatrixError(f"{TEXT_SOURCES}: unsupported category source {source!r}")
        selected.update(catalogues[source])
    return frozenset(selected)


TEXT_CATEGORIES: frozenset[str] = _text_categories()

# The grain of a wide row, before any split on column label; the ranked rows
# of wide-grain.csv.
GRAIN = _pivot_ranked(WIDE_GRAIN, "")

# The wide column a context field occupies. A field whose own name is already
# a printed measure in some family takes the name wide-column-renames.csv gives
# it, so the measure column keeps its name and the context column gets its own.
CONTEXT_RENAMES = matrices.mapping(COLUMN_RENAMES, "context_column")


def context_column_for(field: str) -> str:
    return CONTEXT_RENAMES.get(field, field)


# The printed grouping read under one taxonomy. Measured on the published
# facts, these never differ between the cells of one wide row, so the first
# cell supplies them like every other context column.
TAXONOMY_SOURCES = _pivot_ranked(CONTEXT_PRECEDENCE, "taxonomy_column")

# What a value means rather than where it was printed: the method and fee basis
# behind a return, the scope behind a valuation, and the note the cell cites.
# These belong to the cell, not to the printed row, and only some cells of a
# row state one, so they are read across the group and a row whose cells
# disagree says so in `qualifier_note`.
QUALIFIER_SOURCES = _pivot_ranked(CONTEXT_PRECEDENCE, "qualifier_column")

# A method and a fee basis describe one measure, so the two are read together
# from one cell: the first that states a method (a return), or on a row with
# no return the first that states a fee basis (an irr). Read one column at a
# time, 69 SRC457 rows carried `time_weighted` from their return beside
# `unstated` from the irr printed next to it, a pair no cell of the row
# states. The grouping is wide-context-precedence.csv context qualifier_group,
# one row per qualifier column.
_QUALIFIER_GROUP_OF = matrices.mapping(CONTEXT_PRECEDENCE, "qualifier_group")
if set(_QUALIFIER_GROUP_OF) != set(QUALIFIER_SOURCES):
    raise matrices.MatrixError(
        f"{CONTEXT_PRECEDENCE}: every qualifier_column row needs one qualifier_group row"
    )
QUALIFIER_GROUPS: tuple[tuple[str, ...], ...] = tuple(
    tuple(field for field in QUALIFIER_SOURCES if _QUALIFIER_GROUP_OF[field] == group)
    for group in dict.fromkeys(_QUALIFIER_GROUP_OF[field] for field in QUALIFIER_SOURCES)
)

# The fields every wide row carries beside its category columns.
CONTEXT_SOURCES = (
    "document_id", "route", "canonical_doc_type", "page_id", "source_page",
    "source_section", "source_table", "source_row_label", "source_occurrence",
    "column_group",
    "subject_type", "subject_alias_id", "subject_entity_id", "subject_name",
    "subject_standardized_name", "subject_manager_name",
    "asset_class", "strategy", "geography", "vintage_year",
    *TAXONOMY_SOURCES,
    "horizon", "as_of_date_raw", "as_of_date", "period_start", "period_end",
    "currency", "unit_scale", "unit_scale_multiplier",
    *QUALIFIER_SOURCES,
)

CONTEXT_COLUMNS = tuple(context_column_for(field) for field in CONTEXT_SOURCES)

LINEAGE_COLUMNS = (
    "observation_ids", "observation_count", "unparsed_values", "scale_note",
    "collision_note", "qualifier_note",
)

# The document's own row: identity, the grouping it prints for itself with
# its taxonomy readings, and its dates. The order is the order
# build_document_context writes, and the DDL is rendered from it.
DOCUMENT_CONTEXT_COLUMNS = (
    "wide_row_id", "document_id", "route", "canonical_doc_type", "page_id",
    "source_page", "document_name", "subject_type", "subject_alias_id",
    "manager_alias_id", "manager_entity_id", "manager_name",
    "investor_alias_id", "investor_entity_id", "investor_name",
    "portfolio_name",
    "asset_class", "strategy", "geography", "vintage_year",
    *TAXONOMY_SOURCES,
    "as_of_date_raw", "as_of_date", "period_start_raw", "period_start",
    "period_end_raw", "period_end", "currency",
    "observation_ids", "observation_count",
)

DEFINITION_CONTEXT_COLUMNS = (
    "wide_row_id", "document_id", "route", "canonical_doc_type", "page_id",
    "source_page", "source_structure_type", "source_section", "source_table",
    "definition_keys", "definition_text", "applies_to", "evidence_quote",
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

    source = matrices.resolve(FAMILY_ROUTING, "families_source")
    if source != "contract.FAMILY_CONTRACTS":
        raise matrices.MatrixError(f"{FAMILY_ROUTING}: unsupported families_source {source!r}")
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


def _reserved_columns() -> frozenset[str]:
    source = matrices.resolve(COLUMN_RENAMES, "reserved_names")
    if source != "wide_row_id|context_columns|lineage_columns":
        raise matrices.MatrixError(f"{COLUMN_RENAMES}: unsupported reserved_names {source!r}")
    return frozenset({"wide_row_id", *CONTEXT_COLUMNS, *LINEAGE_COLUMNS})


RESERVED_COLUMNS = _reserved_columns()


def column_for(category: str) -> str:
    """The column a category occupies. `strategy` is both a context column and a
    legal-term category, so a category that collides with a context or lineage
    name takes the suffix `_category` and keeps the context column intact."""

    suffix = matrices.resolve(COLUMN_RENAMES, "collision_suffix")
    return f"{category}{suffix}" if category in RESERVED_COLUMNS else category


def is_text(family: str, category: str) -> bool:
    return category in TEXT_CATEGORIES


def wide_columns(family: str) -> tuple[str, ...]:
    if family == CONTEXT_FAMILY:
        return DOCUMENT_CONTEXT_COLUMNS
    if family == DEFINITION_FAMILY:
        return DEFINITION_CONTEXT_COLUMNS
    return ("wide_row_id", *CONTEXT_COLUMNS, *(column_for(c) for c in categories(family)), *LINEAGE_COLUMNS)


def _category_of(row: Mapping[str, str]) -> str:
    for field in _pivot_ranked(CATEGORY_ORDER, "pivot.category"):
        if row.get(field):
            return row[field]
    return ""


def _cell_value(row: Mapping[str, str], text: bool) -> tuple[object, bool]:
    """The value a cell contributes, and whether it parsed into its column."""

    sources = matrices.mapping(CELL_SOURCES)
    if text:
        return row.get(sources["text_source_1"]) or row.get(sources["text_source_2"]) or "", True
    number = row.get(sources["numeric_source"]) or ""
    if number != "":
        return number, True
    return row.get(sources["unparsed_source_1"]) or row.get(sources["unparsed_source_2"]) or "", False


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
        split_field = matrices.resolve(GROUPING, "repeat_split_field")
        by_column: dict[str, list[Mapping[str, str]]] = defaultdict(list)
        for cell in cells:
            by_column[cell.get(split_field, "")].append(cell)
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
    context_source = matrices.resolve(CONTEXT_PRECEDENCE, "context_source")
    if context_source != "first_cell_in_group":
        raise matrices.MatrixError(
            f"{CONTEXT_PRECEDENCE}: unsupported context_source {context_source!r}"
        )
    qualifier_source = matrices.resolve(CONTEXT_PRECEDENCE, "qualifier_source")
    if qualifier_source != "first_stated_cell_per_qualifier_group":
        raise matrices.MatrixError(
            f"{CONTEXT_PRECEDENCE}: unsupported qualifier_source {qualifier_source!r}"
        )
    unparsed_destination = matrices.resolve(UNPARSED_POLICY, "unparsed_destination")
    unparsed_format = matrices.resolve(UNPARSED_POLICY, "unparsed_format")
    if unparsed_format != "category=value":
        raise matrices.MatrixError(
            f"{UNPARSED_POLICY}: unsupported unparsed_format {unparsed_format!r}"
        )
    repeat_policy = matrices.resolve(COLLISION_POLICY, "repeat_within_row")
    collision_format = matrices.resolve(COLLISION_POLICY, "collision_entry_format")
    if collision_format != "category@column":
        raise matrices.MatrixError(
            f"{COLLISION_POLICY}: unsupported collision_entry_format {collision_format!r}"
        )
    for key, column_group, cells in _groups(rows):
        first = cells[0]
        row: dict[str, object] = {
            context_column_for(name): first.get(name, "") for name in CONTEXT_SOURCES
        }
        # A qualifier is stated by the cell it qualifies, so a row whose first
        # cell is a commitment and whose second is a return takes the return's
        # method. The fields of one group come from one cell, the first that
        # states any of them in the group's order, so a method and a fee basis
        # are never assembled from two cells. Where cells state different
        # values, both stay visible in the note instead of one being chosen
        # silently.
        qualifier_clashes: list[str] = []
        for fields in QUALIFIER_GROUPS:
            anchor = next(
                (
                    cell
                    for field in fields
                    for cell in cells
                    if (cell.get(field) or "").strip()
                ),
                None,
            )
            for field in fields:
                stated = {
                    value
                    for value in ((cell.get(field) or "").strip() for cell in cells)
                    if value
                }
                row[context_column_for(field)] = (
                    (anchor.get(field) or "").strip() if anchor is not None else ""
                )
                if len(stated) > 1:
                    qualifier_clashes.append(f"{field}={'|'.join(sorted(stated))}")
        row["column_group"] = column_group
        row["wide_row_id"] = _key("WIDE", family, *key, column_group)
        unparsed: list[str] = []
        clashes: list[str] = []
        scale_kinds = set(matrices.resolve(SCALE_STATUS, "scale_kinds").split("|"))
        scales = {cell.get("unit_scale", "") for cell in cells if cell.get("value_kind") in scale_kinds}
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
                collision_value = (
                    f"{category}@"
                    f"{cell.get(matrices.resolve(GROUPING, 'repeat_split_field'), '')}"
                )
                clashes.append(collision_value)
                if repeat_policy == "first_value_kept":
                    continue
                raise matrices.MatrixError(
                    f"{COLLISION_POLICY}: unsupported repeat policy {repeat_policy!r}"
                )
            row[column] = value
        if clashes:
            collisions += len(clashes)
        row["observation_ids"] = ";".join(str(cell["observation_id"]) for cell in cells)
        row["observation_count"] = len(cells)
        row[unparsed_destination] = "; ".join(unparsed)
        row["scale_note"] = (
            matrices.resolve(SCALE_STATUS, "scale_note_prefix") + ", ".join(sorted(scales))
            if len(scales) > 1
            else ""
        )
        row["collision_note"] = (
            matrices.resolve(COLLISION_POLICY, "collision_note_prefix") + ", ".join(sorted(clashes))
            if clashes
            else ""
        )
        row["qualifier_note"] = (
            matrices.resolve(CONTEXT_PRECEDENCE, "qualifier_note_prefix")
            + ", ".join(sorted(qualifier_clashes))
            if qualifier_clashes
            else ""
        )
        wide.append(row)
    return wide, collisions


def build_definition_context(rows: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    """One row per printed note: the key it defines and its wording.

    A note is not a measure, so the measure pivot has no column for it. The
    wording stays verbatim and the key is what a value row cites in
    `definition_keys`.
    """

    wide: list[dict[str, object]] = []
    for cell in sorted(
        rows,
        key=lambda item: (
            str(item.get("document_id", "")),
            int(item.get("source_page", "0") or 0),
            str(item.get("definition_keys", "")),
        ),
    ):
        wide.append(
            {
                # A page can print two notes under one marker, so the note's
                # identity is its physical cell exactly as it is for a value:
                # page, row label, column label, occurrence. SRC375 page 2
                # prints "Annualized" under a figure (no column label) and
                # under a table (column label "Annualized"), one occurrence
                # each; a key without the column label folded them into one
                # id and the database rebuild refused the duplicate.
                "wide_row_id": _key(
                    "WIDE", DEFINITION_FAMILY, cell.get("document_id", ""),
                    cell.get("source_page", ""), cell.get("definition_keys", ""),
                    cell.get("source_row_label", ""), cell.get("source_column_label", ""),
                    cell.get("source_occurrence", ""),
                ),
                "document_id": cell.get("document_id", ""),
                "route": cell.get("route", ""),
                "canonical_doc_type": cell.get("canonical_doc_type", ""),
                "page_id": cell.get("page_id", ""),
                "source_page": cell.get("source_page", ""),
                "source_structure_type": cell.get("source_structure_type", ""),
                "source_section": cell.get("source_section", ""),
                "source_table": cell.get("source_table", ""),
                "definition_keys": cell.get("definition_keys", ""),
                "definition_text": cell.get("value_text", "") or cell.get("value_raw", ""),
                "applies_to": cell.get("condition_raw", ""),
                "evidence_quote": cell.get("evidence_quote", ""),
                "observation_ids": cell.get("observation_id", ""),
                "observation_count": 1,
            }
        )
    return wide


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
                "subject_type": cell.get("subject_type", ""),
                "subject_alias_id": cell.get("subject_alias_id", ""),
                "manager_alias_id": cell.get("manager_alias_id", ""),
                "manager_entity_id": cell.get("manager_entity_id", ""),
                "manager_name": _alias_fallback(
                    "manager_name_source", cell.get("manager_alias_id", ""), alias_names
                ),
                "investor_alias_id": cell.get("investor_alias_id", ""),
                "investor_entity_id": cell.get("investor_entity_id", ""),
                "investor_name": _alias_fallback(
                    "investor_name_source", cell.get("investor_alias_id", ""), alias_names
                ),
                "portfolio_name": cell.get("portfolio_name", ""),
                # The printed grouping a document states for itself, with its
                # readings under one taxonomy. SRC058 prints asset_class Real
                # Estate and SRC612 Real Asset with a strategy on this row, and
                # a table without these columns dropped both at this stage.
                "asset_class": cell.get("asset_class", ""),
                "strategy": cell.get("strategy", ""),
                "geography": cell.get("geography", ""),
                "vintage_year": cell.get("vintage_year", ""),
                **{name: cell.get(name, "") for name in TAXONOMY_SOURCES},
                "as_of_date_raw": cell.get("as_of_date_raw", ""),
                "as_of_date": cell.get("as_of_date", ""),
                "period_start_raw": cell.get("period_start_raw", ""),
                "period_start": cell.get("period_start", ""),
                "period_end_raw": cell.get("period_end_raw", ""),
                "period_end": cell.get("period_end", ""),
                "currency": cell.get("currency", ""),
                "observation_ids": cell.get("observation_id", ""),
                "observation_count": 1,
            }
        )
    return wide


def _alias_fallback(
    policy_key: str, alias_id: str, alias_names: Mapping[str, str]
) -> str:
    source = matrices.resolve(ALIAS_FALLBACK, policy_key)
    if source != "alias_raw_name":
        raise matrices.MatrixError(f"{ALIAS_FALLBACK}: unsupported alias source {source!r}")
    return alias_names.get(alias_id, "")


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
        unknown_policy = matrices.resolve(FAMILY_ROUTING, "unknown_family")
        if unknown_policy == "refused":
            raise FlattenError(
                f"fact_observation carries families outside the contract: {', '.join(unknown)}"
            )
        raise matrices.MatrixError(
            f"{FAMILY_ROUTING}: unsupported unknown_family policy {unknown_policy!r}"
        )

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
        elif family == DEFINITION_FAMILY:
            wide = build_definition_context(rows)
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
    kind = "text_type" if is_text(family, category) else "numeric_type"
    return matrices.resolve(COLUMN_TYPES, kind)


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
