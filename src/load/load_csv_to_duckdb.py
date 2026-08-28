"""Create the local DuckDB warehouse and load fund-model CSV tables."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Sequence

import duckdb

from .validate_round02_promotion import DEFAULT_WORKING_DIR, validate_fund_model_extracted_rows
from src.pipeline.transformation_lineage import snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_DIR = PROJECT_ROOT / "data" / "csv"
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "warehouse" / "alts.duckdb"
DDL_FILES = [
    PROJECT_ROOT / "sql" / "duckdb" / "02_fund_level_ddl.sql",
]

TABLE_FILES = {
    "manager_master": "manager_master.csv",
    "document_manager_map": "document_manager_map.csv",
    "fund_master": "fund_master.csv",
    "document_fund_map": "document_fund_map.csv",
    "fund_observations": "fund_observations.csv",
    "manager_observations": "manager_observations.csv",
    "fund_cashflows": "fund_cashflows.csv",
    "fund_periods": "fund_periods.csv",
    "fund_terms": "fund_terms.csv",
    "fund_term_clauses": "fund_term_clauses.csv",
    "fund_holdings": "fund_holdings.csv",
    "synthetic_parameters": "synthetic_parameters.csv",
    "quality_results": "quality_results.csv",
    "defect_injections": "defect_injections.csv",
    "benchmark_returns": "benchmark_returns.csv",
    "portfolio_allocations": "portfolio_allocations.csv",
    "fund_metrics": "fund_metrics.csv",
    "pme_results": "pme_results.csv",
}


class DatabaseParityError(RuntimeError):
    """Raised when a warehouse differs from the CSVs that own it."""


def read_csv(path: Path) -> tuple[list[str], list[list[str | None]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers = next(reader)
        rows = [[value if value != "" else None for value in row] for row in reader]
    return headers, rows


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def database_parity(
    csv_dir: Path,
    database: Path,
    table_files: dict[str, str] | None = None,
) -> dict[str, int]:
    """Return tables whose loaded rows differ from their CSV rows."""

    table_files = table_files or TABLE_FILES
    return database_file_parity(
        {table: csv_dir / filename for table, filename in table_files.items()},
        database,
    )


def database_file_parity(
    files: dict[str, Path],
    database: Path,
) -> dict[str, int]:
    """Return tables whose loaded rows differ from their named CSV file."""

    mismatches: dict[str, int] = {}
    connection = duckdb.connect(str(database), read_only=True)
    try:
        for table, path in files.items():
            table_name = _quote_identifier(table)
            if not path.is_file():
                count = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                if count:
                    mismatches[table] = int(count)
                continue
            headers, _rows = read_csv(path)
            escaped_table = table.replace("'", "''")
            schema = connection.execute(f"PRAGMA table_info('{escaped_table}')").fetchall()
            types = {str(row[1]): str(row[2]) for row in schema}
            if list(types) != headers:
                mismatches[table] = -1
                continue
            columns = ", ".join(_quote_identifier(column) for column in headers)
            casts = ", ".join(
                f"CAST({_quote_identifier(column)} AS {types[column]}) AS {_quote_identifier(column)}"
                for column in headers
            )
            escaped_path = path.resolve().as_posix().replace("'", "''")
            difference_count = connection.execute(
                f"""
                WITH csv_rows AS (
                    SELECT {casts}
                    FROM read_csv('{escaped_path}', header = true, all_varchar = true, nullstr = '')
                )
                SELECT COUNT(*)
                FROM (
                    (SELECT {columns} FROM {table_name}
                     EXCEPT ALL
                     SELECT {columns} FROM csv_rows)
                    UNION ALL
                    (SELECT {columns} FROM csv_rows
                     EXCEPT ALL
                     SELECT {columns} FROM {table_name})
                ) AS differences
                """
            ).fetchone()[0]
            if difference_count:
                mismatches[table] = int(difference_count)
    finally:
        connection.close()
    return mismatches


def assert_database_parity(csv_dir: Path, database: Path) -> None:
    mismatches = database_parity(csv_dir, database)
    if mismatches:
        rendered = ", ".join(f"{table}={count}" for table, count in sorted(mismatches.items()))
        raise DatabaseParityError(f"CSV-to-DuckDB content mismatch: {rendered}")


def load(
    csv_dir: Path,
    database: Path,
    replace: bool = True,
    rebuild: bool = False,
    working_dir: Path = DEFAULT_WORKING_DIR,
    ddl_files: Sequence[Path] | None = None,
    public_market_audit_dir: Path | None = None,
    public_market_staging_dir: Path | None = None,
    template_root: Path | None = None,
) -> dict[str, int]:
    # Fail before deleting or changing an existing warehouse. The gate validates
    # the Round 02 lineage ledgers in full, then requires promotion lineage for
    # rows whose provenance_type is EXTRACTED, so demo and synthetic rows clear
    # that row check on provenance alone.
    csv_dir = csv_dir.resolve()
    public_market_root = csv_dir.parent / "public_markets"
    promotion_args = (
        csv_dir,
        working_dir.resolve(),
        (public_market_audit_dir or (public_market_root / "audit")).resolve(),
        (public_market_staging_dir or (public_market_root / "staging")).resolve(),
    )
    if template_root is None:
        validate_fund_model_extracted_rows(*promotion_args)
    else:
        validate_fund_model_extracted_rows(*promotion_args, template_root.resolve())
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists() and database.is_dir():
        raise IsADirectoryError(f"Database target is a directory: {database}")
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
        for ddl in (ddl_files or DDL_FILES):
            connection.execute(ddl.read_text(encoding="utf-8"))
        for table, filename in TABLE_FILES.items():
            path = csv_dir / filename
            if not path.exists():
                counts[table] = 0
                continue
            headers, rows = read_csv(path)
            if replace:
                connection.execute(f'DELETE FROM "{table}"')
            if rows:
                columns = ", ".join(f'"{column}"' for column in headers)
                escaped_path = path.resolve().as_posix().replace("'", "''")
                connection.execute(
                    f'''INSERT INTO "{table}" ({columns})
                        SELECT {columns}
                        FROM read_csv('{escaped_path}', header = true, all_varchar = true, nullstr = '')'''
                )
            counts[table] = len(rows)
        connection.commit()
    finally:
        connection.close()
    if rebuild:
        try:
            assert_database_parity(csv_dir, target)
            if database.exists() and database.resolve() == DEFAULT_DATABASE.resolve():
                snapshot(database)
            os.replace(target, database)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_CSV_DIR)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--append", action="store_true", help="Append to table contents instead of replacing them.")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete and recreate the named DuckDB file before loading.",
    )
    parser.add_argument(
        "--working-dir",
        type=Path,
        default=DEFAULT_WORKING_DIR,
        help="Round 02 staging and audit-ledger folder used by the promotion gate.",
    )
    args = parser.parse_args()
    counts = load(
        args.csv_dir,
        args.database,
        replace=not args.append,
        rebuild=args.rebuild,
        working_dir=args.working_dir,
    )
    for table, count in counts.items():
        print(f"{table}: {count} rows")
    assert_database_parity(args.csv_dir.resolve(), args.database.resolve())
    print("PASS: fund-model CSV and DuckDB content match")


if __name__ == "__main__":
    main()
