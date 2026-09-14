from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER = HERE / "V2-LIVE-LEDGER.csv"
EXECUTION = HERE / "V2-EXECUTION.csv"
FIELDS = ["event_id", "timestamp_utc", "task_id", "status", "artifact", "verification", "notes"]


def append_event(task_id: str, status: str, artifact: str = "", verification: str = "", notes: str = "") -> None:
    rows = []
    if LEDGER.is_file():
        with LEDGER.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    event_id = f"E{len(rows) + 1:04d}"
    row = {
        "event_id": event_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "status": status,
        "artifact": artifact,
        "verification": verification,
        "notes": notes,
    }
    write_header = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    if EXECUTION.is_file() and task_id.startswith("V2-"):
        with EXECUTION.open(encoding="utf-8", newline="") as handle:
            execution_rows = list(csv.DictReader(handle))
            fields = list(execution_rows[0]) if execution_rows else []
        mapped = {
            "STARTED": "IN_PROGRESS",
            "DONE": "DONE",
            "BLOCKED": "BLOCKED",
            "DEFERRED": "DEFERRED_BY_POLICY",
            "READY": "READY_FOR_OPERATOR_DECISION",
        }.get(status)
        if mapped:
            found = False
            for item in execution_rows:
                if item.get("task_id") == task_id:
                    item["status"] = mapped
                    found = True
                    break
            if not found:
                raise ValueError(f"unknown task_id: {task_id}")
            temporary = EXECUTION.with_suffix(".csv.tmp")
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(execution_rows)
            temporary.replace(EXECUTION)
    print(f"{event_id} {task_id} {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Append one GP Scoring V2 implementation event")
    parser.add_argument("task_id")
    parser.add_argument("status", choices=("STARTED", "DONE", "BLOCKED", "DEFERRED", "READY", "NOTE"))
    parser.add_argument("--artifact", default="")
    parser.add_argument("--verification", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    append_event(args.task_id, args.status, args.artifact, args.verification, args.notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
