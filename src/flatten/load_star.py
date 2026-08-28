"""Load the flattened extraction tables and the wide tables into one DuckDB file.

The CSVs under `data/extracted/tables/` are the portable review layer; this is
the query layer. The database is rebuilt from the CSVs every run, so the CSVs
stay the single source and the warehouse never drifts from them.
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Sequence

import duckdb

from src.load.load_csv_to_duckdb import database_file_parity
from src.pipeline.transformation_lineage import snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TABLE_DIR = PROJECT_ROOT / "data" / "extracted" / "tables"
DEFAULT_WIDE_DIR = PROJECT_ROOT / "data" / "extracted" / "wide"
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "warehouse" / "extracted.duckdb"
DDL = PROJECT_ROOT / "sql" / "duckdb" / "03_extracted_star_ddl.sql"
WIDE_DDL = PROJECT_ROOT / "sql" / "duckdb" / "04_extracted_wide_ddl.sql"

# Dimensions load before the facts that reference them.
TABLE_ORDER = (
    "dim_document",
    "dim_page",
    "dim_entity",
    "entity_alias",
    "dim_metric",
    "fact_observation",
    "observation_lineage",
    "fact_holding",
    "unresolved_names",
)


def wide_table_order() -> tuple[str, ...]:
    """The wide tables, then the bridge that points back at fact_observation."""

    from src.flatten import pivot_wide

    return (*(pivot_wide.table_name(family) for family in pivot_wide.families()), "bridge_pivot_observation")


FUND_MODEL_DATABASE = PROJECT_ROOT / "data" / "warehouse" / "alts.duckdb"


class LoadError(RuntimeError):
    """Raised when the load refuses to run against the wrong target."""


def headers(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def load(
    table_dir: Path, database: Path, rebuild: bool = True, wide_dir: Path | None = None
) -> dict[str, int]:
    if database.resolve() == FUND_MODEL_DATABASE.resolve():
        raise LoadError(
            "The extracted star schema refuses to write the fund-model "
            "warehouse; point --database at a separate file."
        )
    missing = [name for name in TABLE_ORDER if not (table_dir / f"{name}.csv").is_file()]
    if missing:
        raise LoadError(
            f"{table_dir} is missing {', '.join(missing)}. Run `src.flatten.flatten_extracted` first."
        )
    wide_dir = wide_dir or DEFAULT_WIDE_DIR
    wide_order = wide_table_order()
    missing_wide = [name for name in wide_order if not (wide_dir / f"{name}.csv").is_file()]
    if missing_wide:
        raise LoadError(
            f"{wide_dir} is missing {', '.join(missing_wide)}. Run `src.flatten.pivot_wide` first."
        )
    sources = [(name, table_dir / f"{name}.csv") for name in TABLE_ORDER]
    sources += [(name, wide_dir / f"{name}.csv") for name in wide_order]
    database.parent.mkdir(parents=True, exist_ok=True)
    target = database
    if rebuild:
        target = database.with_name(f".{database.name}.building")
        if target.exists():
            if target.is_dir():
                raise IsADirectoryError(f"Database build target is a directory: {target}")
            target.unlink()
    connection = duckdb.connect(str(target))
    counts: dict[str, int] = {}
    try:
        connection.execute(DDL.read_text(encoding="utf-8"))
        connection.execute(WIDE_DDL.read_text(encoding="utf-8"))
        # Children first: a foreign key refuses to delete a parent row that is
        # still referenced, so an append-mode reload empties the facts before
        # the dimensions they point at.
        for table, _path in reversed(sources):
            connection.execute(f'DELETE FROM "{table}"')
        for table, path in sources:
            columns = ", ".join(f'"{column}"' for column in headers(path))
            escaped = path.resolve().as_posix().replace("'", "''")
            connection.execute(
                f'''INSERT INTO "{table}" ({columns})
                    SELECT {columns}
                    FROM read_csv('{escaped}', header = true, all_varchar = true, nullstr = '')'''
            )
            counts[table] = connection.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]
        connection.commit()
    finally:
        connection.close()
    if rebuild:
        file_map = {table: path for table, path in sources}
        mismatches = database_file_parity(file_map, target)
        if mismatches:
            target.unlink(missing_ok=True)
            rendered = ", ".join(
                f"{table}={count}" for table, count in sorted(mismatches.items())
            )
            raise LoadError(f"extracted CSV-to-DuckDB content mismatch: {rendered}")
        if database.exists() and database.resolve() == DEFAULT_DATABASE.resolve():
            snapshot(database)
        os.replace(target, database)
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table-dir", type=Path, default=DEFAULT_TABLE_DIR)
    parser.add_argument("--wide-dir", type=Path, default=DEFAULT_WIDE_DIR)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--append", action="store_true", help="Keep the existing database file.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    counts = load(args.table_dir, args.database, rebuild=not args.append, wide_dir=args.wide_dir)
    for table, count in counts.items():
        print(f"{table}: {count} rows")
    print(f"PASS: loaded -> {args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
