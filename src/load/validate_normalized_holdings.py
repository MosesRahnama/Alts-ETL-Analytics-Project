"""Validate normalized holdings tables, source coverage, and DuckDB constraints."""
from __future__ import annotations

import argparse
import csv
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

import duckdb

from . import build_normalized_holdings as normalized

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_DIR = PROJECT_ROOT / "data" / "csv"
DEFAULT_FUND_MASTER = DEFAULT_CSV_DIR / "fund_master.csv"
DEFAULT_FACT_HOLDING = PROJECT_ROOT / "data" / "extracted" / "tables" / "fact_holding.csv"
DEFAULT_REFUSALS = PROJECT_ROOT / "data" / "extracted" / "audit" / "normalized-holdings-refusals.csv"
DDL = PROJECT_ROOT / "Expansion" / "holdings" / "normalized_holdings_ddl.sql"
QA = PROJECT_ROOT / "Expansion" / "holdings" / "normalized_holdings_qa.sql"

LOAD_ORDER = (
    "investment_owner",
    "investment_target",
    "investment_instrument",
    "fund_position",
    "lookthrough_edge",
    "holding_field_lineage",
)


class NormalizedHoldingValidationError(RuntimeError):
    pass


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise NormalizedHoldingValidationError(f"missing required file: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _load_csv(connection: duckdb.DuckDBPyConnection, table: str, path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise NormalizedHoldingValidationError(f"empty CSV: {path}") from exc
        row_count = sum(1 for _ in reader)
    schema = connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='main' AND table_name=? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    expected = [row[0] for row in schema]
    if header != expected:
        raise NormalizedHoldingValidationError(
            f"header mismatch for {table}: expected {expected}, got {header}"
        )
    if row_count:
        columns = ", ".join(_quote(column) for column in header)
        if table == "investment_owner":
            # DuckDB checks a self-referencing foreign key per inserted row.
            # The builder writes parents before children, so insert this table
            # in that order instead of as one bulk INSERT SELECT.
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            placeholders = ", ".join("?" for _ in header)
            for row in rows:
                values = [row.get(column) or None for column in header]
                connection.execute(
                    f"INSERT INTO {_quote(table)} ({columns}) VALUES ({placeholders})",
                    values,
                )
        else:
            escaped = path.resolve().as_posix().replace("'", "''")
            connection.execute(
                f"INSERT INTO {_quote(table)} ({columns}) "
                f"SELECT {columns} FROM read_csv('{escaped}', header=true, all_varchar=true, nullstr='')"
            )
    return row_count


def _source_coverage(
    csv_dir: Path,
    fact_holding_path: Path | None,
    refusal_path: Path | None,
) -> dict[str, int]:
    if fact_holding_path is None or refusal_path is None:
        return {"source_holdings": 0, "mapped_source_positions": 0, "refusals": 0}
    facts = _read(fact_holding_path)
    positions = _read(csv_dir / normalized.NORMALIZED_FILES["fund_position"][0])
    refusals = _read(refusal_path)
    source_ids = {row["holding_id"] for row in facts}
    if len(source_ids) != len(facts):
        raise NormalizedHoldingValidationError("fact_holding contains duplicate holding_id values")
    mapped_rows = [
        row for row in positions
        if row.get("provenance_type") == "EXTRACTED" and row.get("source_holding_id")
    ]
    mapped_ids = [row["source_holding_id"] for row in mapped_rows]
    refusal_ids = [row.get("source_holding_id", "") for row in refusals]
    if len(mapped_ids) != len(set(mapped_ids)):
        raise NormalizedHoldingValidationError("a source holding maps to more than one extracted fund_position")
    if len(refusal_ids) != len(set(refusal_ids)):
        raise NormalizedHoldingValidationError("a source holding has more than one refusal")
    mapped = set(mapped_ids)
    refused = set(refusal_ids)
    overlap = mapped & refused
    missing = source_ids - mapped - refused
    extra = (mapped | refused) - source_ids
    if overlap or missing or extra:
        raise NormalizedHoldingValidationError(
            "source holding coverage failed: "
            f"overlap={len(overlap)} missing={len(missing)} extra={len(extra)}"
        )
    return {
        "source_holdings": len(source_ids),
        "mapped_source_positions": len(mapped),
        "refusals": len(refused),
    }


def validate(
    csv_dir: Path = DEFAULT_CSV_DIR,
    *,
    fund_master_path: Path = DEFAULT_FUND_MASTER,
    fact_holding_path: Path | None = DEFAULT_FACT_HOLDING,
    refusal_path: Path | None = DEFAULT_REFUSALS,
    ddl_path: Path = DDL,
    qa_path: Path = QA,
) -> dict[str, int]:
    csv_dir = csv_dir.resolve()
    fund_master_path = fund_master_path.resolve()
    if not ddl_path.is_file() or not qa_path.is_file():
        raise NormalizedHoldingValidationError("normalized holdings DDL or QA SQL is missing")
    coverage = _source_coverage(csv_dir, fact_holding_path, refusal_path)
    fund_master = _read(fund_master_path)
    fund_ids = [row.get("fund_id", "") for row in fund_master if row.get("fund_id")]
    if len(fund_ids) != len(set(fund_ids)):
        raise NormalizedHoldingValidationError("fund_master contains duplicate fund_id values")

    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / "normalized.duckdb"
        connection = duckdb.connect(str(db))
        try:
            connection.execute("CREATE TABLE fund_master(fund_id VARCHAR PRIMARY KEY)")
            if fund_ids:
                connection.executemany("INSERT INTO fund_master VALUES (?)", [(item,) for item in fund_ids])
            connection.execute(ddl_path.read_text(encoding="utf-8"))
            counts: dict[str, int] = {}
            for table in LOAD_ORDER:
                filename = normalized.NORMALIZED_FILES[table][0]
                counts[table] = _load_csv(connection, table, csv_dir / filename)
            connection.execute(qa_path.read_text(encoding="utf-8"))
            qa_counts = connection.execute(
                "SELECT "
                "COUNT(*) FILTER (WHERE severity='ERROR') AS error_count, "
                "COUNT(*) FILTER (WHERE severity='WARN') AS warning_count, "
                "COUNT(*) AS total_findings "
                "FROM vw_normalized_holdings_qa"
            ).fetchone()
            errors, warnings, total = (int(value or 0) for value in qa_counts)
            if errors:
                sample = connection.execute(
                    "SELECT rule_id, record_table, record_id, details "
                    "FROM vw_normalized_holdings_qa WHERE severity='ERROR' "
                    "ORDER BY rule_id, record_table, record_id LIMIT 20"
                ).fetchall()
                rendered = "; ".join(f"{r[0]}:{r[1]}:{r[2]}:{r[3]}" for r in sample)
                raise NormalizedHoldingValidationError(
                    f"normalized holdings QA has {errors} ERROR finding(s): {rendered}"
                )
        finally:
            connection.close()
    return {
        **coverage,
        **counts,
        "qa_errors": errors,
        "qa_warnings": warnings,
        "qa_findings": total,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_CSV_DIR)
    parser.add_argument("--fund-master", type=Path, default=DEFAULT_FUND_MASTER)
    parser.add_argument("--fact-holding", type=Path, default=DEFAULT_FACT_HOLDING)
    parser.add_argument("--refusals", type=Path, default=DEFAULT_REFUSALS)
    parser.add_argument(
        "--skip-source-coverage",
        action="store_true",
        help="Validate tables and QA without comparing them with fact_holding/refusals.",
    )
    args = parser.parse_args(argv)
    try:
        counts = validate(
            args.csv_dir,
            fund_master_path=args.fund_master,
            fact_holding_path=None if args.skip_source_coverage else args.fact_holding,
            refusal_path=None if args.skip_source_coverage else args.refusals,
        )
    except (NormalizedHoldingValidationError, duckdb.Error, OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print("PASS: " + ", ".join(f"{name}={value}" for name, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
