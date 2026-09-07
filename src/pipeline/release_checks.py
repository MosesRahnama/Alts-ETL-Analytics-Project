"""Record the result of each executed release check, including checks without outputs."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "ledgers/pipeline/release-checks.csv"
COLUMNS = ("check_id", "stage_id", "command", "status", "checked_at_utc", "detail")
T = TypeVar("T")


def read_results(path: Path | None = None) -> list[dict[str, str]]:
    path = path or OUTPUT
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(COLUMNS):
            raise ValueError(f"{path}: invalid release-check header")
        rows = list(reader)
    if any(set(row) != set(COLUMNS) or any(value is None for value in row.values())
           or row["status"] not in {"PASS", "FAIL"} for row in rows):
        raise ValueError(f"{path}: invalid release-check row")
    if len({row["check_id"] for row in rows}) != len(rows):
        raise ValueError(f"{path}: duplicate check identifier")
    for row in rows:
        if any(not row[field].strip() for field in COLUMNS):
            raise ValueError(f"{path}: release-check evidence must be complete")
        stamp = datetime.fromisoformat(row["checked_at_utc"])
        if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError(f"{path}: check time must specify UTC")
    return rows


def run_check(
    stage_id: str, command: str, action: Callable[[], T], *,
    path: Path | None = None, describe: Callable[[T], str] = lambda result: str(result),
) -> T:
    path = path or OUTPUT
    read_results(path)
    status, detail = "FAIL", "Check interrupted before completion"
    try:
        result = action()
        detail = describe(result)
        status = "PASS"
        return result
    except BaseException as exc:
        detail = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
            if new:
                writer.writeheader()
            writer.writerow(dict(zip(COLUMNS, (
                uuid4().hex, stage_id, command, status,
                datetime.now(timezone.utc).isoformat(timespec="seconds"), detail,
            ))))
