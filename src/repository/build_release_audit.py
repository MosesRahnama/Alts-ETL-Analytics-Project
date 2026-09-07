"""Generate the complete release table from stage descriptions and recorded checks."""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from src.pipeline import release_checks

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "docs/RELEASE-STEPS.csv"
OUTPUT = ROOT / "docs/FINAL-RELEASE-AUDIT.csv"
COLUMNS = ("order", "phase", "stage", "input", "output", "check_description", "status",
           "checked_at_utc", "stage_id", "execution_order", "source", "test", "evidence",
           "result_detail", "next_readme")
PREPARATION_IDS = ("source-catalog", "document-preparation", "blind-extraction", "adjudication")
FINAL_IDS = ("reviewer-check", "repository-and-tests")
INPUT_COMMAND = "python -m src.repository.build_release_audit --verify-inputs"
REPOSITORY_COMMAND = "python -m src.repository.build_release_audit --verify-repository"


def stage_catalog(path: Path = CATALOG, release_stages=None) -> list[dict[str, str]]:
    if release_stages is None:
        from src.pipeline.publish_review_release import stages
        release_stages = stages()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ids = [row["stage_id"] for row in rows]
    expected = [*PREPARATION_IDS, *(item.stage_id for item in release_stages), *FINAL_IDS]
    if ids != expected or len(set(ids)) != len(ids):
        raise ValueError("Release descriptions must contain preparation, every execution stage, and closing checks in order")
    for row in rows:
        if any(value is None or key is None for key, value in row.items()):
            raise ValueError("Malformed release description row")
        for field in ("source", "next_readme"):
            if not row[field] or not (ROOT / row[field]).exists():
                raise ValueError(f"{row['stage_id']}: missing {field} path {row[field]}")
    for row, item in zip(rows[4:-2], release_stages):
        if row["phase"] != "Publication" or row["execution_order"] != str(item.order):
            raise ValueError(f"{item.stage_id}: execution order disagrees with the release command")
        row["test"] = item.command
    for row in rows[:4]:
        if row["execution_order"]:
            raise ValueError("Preparation and extraction do not have automated execution IDs")
        row["test"] = INPUT_COMMAND
    rows[-2]["test"] = "python -m src.pipeline.reviewer_check"
    rows[-1]["test"] = REPOSITORY_COMMAND
    return rows


def report_rows(catalog=None, results=None) -> list[dict[str, str]]:
    catalog = stage_catalog() if catalog is None else catalog
    results = release_checks.read_results() if results is None else results
    latest = {row["stage_id"]: row for row in results}
    rows = []
    for order, description in enumerate(catalog, 1):
        row = {key: description.get(key, "") for key in COLUMNS}
        row["order"] = str(order)
        record = latest.get(row["stage_id"])
        row["status"] = "NOT_RUN"
        if record:
            row["status"] = record["status"] if record["command"] == row["test"] else "STALE"
            row["checked_at_utc"] = record["checked_at_utc"]
            row["evidence"] = "ledgers/pipeline/release-checks.csv#" + record["check_id"]
            row["result_detail"] = record["detail"]
        rows.append(row)
    return rows


def render() -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(report_rows())
    return stream.getvalue()


def build(*, check: bool = False) -> None:
    expected = render()
    if check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8-sig") != expected:
            raise ValueError("Release audit table is stale; regenerate it before the dashboard")
    else:
        OUTPUT.write_text(expected, encoding="utf-8", newline="\n")


def assignments():
    from src.catalog.simple_pdf_extraction import csv_workflow as workflow
    rows = [workflow.routing_for(route, row["file_id"])
            for route in workflow.ROUTES for row in workflow.worklist_for_scope(route, "active")]
    if not rows or len({row["file_id"] for row in rows}) != len(rows):
        raise ValueError("Active assignments must contain unique documents")
    return rows


def verify_sources() -> str:
    from src.repository.release_audit import source_pdf_findings
    errors = source_pdf_findings(ROOT)
    if errors:
        raise ValueError("; ".join(str(error) for error in errors))
    with (ROOT / "data-gathering/source_ledger.csv").open(encoding="utf-8-sig", newline="") as handle:
        count = len(list(csv.DictReader(handle)))
    return f"{count} catalogued PDFs matched their source entries and physical page counts"


def verify_preparation() -> str:
    from src.catalog.simple_pdf_extraction import csv_workflow as workflow
    rows = assignments()
    errors = []
    for row in rows:
        errors.extend(workflow.page_image_errors(row))
        for field in ("txt_path", "grid_path"):
            path = ROOT / row[field]
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f"{row['file_id']}: missing {field}")
        if len(workflow.source_page_texts(row)) != int(row["page_count"]):
            errors.append(f"{row['file_id']}: text page count differs from PDF")
    if errors:
        raise ValueError("; ".join(errors))
    return f"{len(rows)} assigned documents; {sum(int(row['page_count']) for row in rows)} pages; text, images, and grids present"


def verify_proposals() -> str:
    from src.catalog.simple_pdf_extraction import csv_workflow as workflow
    rows = assignments()
    count = 0
    for row in rows:
        for agent in ("A", "B"):
            records_path, coverage_path = workflow.candidate_paths(row["route"], row["file_id"], agent)
            records = workflow.read_strict_csv(records_path, workflow.RECORD_COLUMNS)
            coverage = workflow.read_strict_csv(coverage_path, workflow.COVERAGE_COLUMNS)
            if any(record["file_id"] != row["file_id"] or record["agent_role"] != agent
                   for record in records + coverage):
                raise ValueError(f"{records_path}: proposal identity mismatch")
            expected = list(range(1, int(row["page_count"]) + 1))
            if sorted(int(record["source_page"]) for record in coverage) != expected:
                raise ValueError(f"{coverage_path}: incomplete or duplicate page coverage")
            actual = Counter(int(record["source_page"]) for record in records)
            if set(actual) - set(expected) or any(
                actual[int(record["source_page"])] != int(record["records_written"]) for record in coverage
            ):
                raise ValueError(f"{coverage_path}: proposal row counts do not reconcile")
            count += len(records)
    return (f"{len(rows) * 2} retained proposal sets; {count} rows; complete page and row-count records. "
            "Original proposals remain unchanged; current field semantics are checked on adjudicated finals.")


def verify_adjudication() -> str:
    from src.catalog.simple_pdf_extraction import csv_workflow as workflow
    rows = assignments()
    count = 0
    for row in rows:
        records, _, errors = workflow.validate_final_data(row["route"], row["file_id"])
        if errors:
            raise ValueError("; ".join(errors))
        count += len(records)
    return f"{len(rows)} adjudicated documents; {count} final records; source, field, and page-completeness checks passed"


def verify_inputs() -> None:
    actions = (verify_sources, verify_preparation, verify_proposals, verify_adjudication)
    for stage_id, action in zip(PREPARATION_IDS, actions):
        result = release_checks.run_check(stage_id, INPUT_COMMAND, action)
        print(f"PASS: {stage_id}; {result}")


def verify_repository() -> str:
    commands = (
        ["-m", "src.repository.check_project_structure", "--verify-hashes"],
        ["-m", "src.repository.release_audit"],
        ["-m", "pytest", "-q", "-p", "no:cacheprovider"],
    )
    summaries = []
    for args in commands:
        result = subprocess.run([sys.executable, *args], cwd=ROOT, text=True,
                                encoding="utf-8", errors="replace", capture_output=True,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        print(result.stdout, end="", flush=True)
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="", flush=True)
        if result.returncode:
            raise ValueError(f"{' '.join(args)} failed ({result.returncode}): {result.stdout[-3000:]} {result.stderr[-1000:]}")
        summaries.append(next((line for line in reversed(result.stdout.splitlines()) if line.strip()), "PASS"))
    return "; ".join(summaries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--verify-inputs", action="store_true")
    mode.add_argument("--verify-repository", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_inputs:
            verify_inputs()
        if args.verify_repository:
            release_checks.run_check("repository-and-tests", REPOSITORY_COMMAND, verify_repository)
        build(check=args.check)
    except (ValueError, OSError) as exc:
        if args.verify_inputs or args.verify_repository:
            build()
        print(f"FAIL: {exc}")
        return 1
    print("PASS: complete release audit table matches stage definitions and recorded checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
