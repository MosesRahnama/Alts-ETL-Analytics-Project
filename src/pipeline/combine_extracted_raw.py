"""Combine each extraction round's adjudicated documents into one file.

This is the step immediately after extraction and it does one thing: for every
round, concatenate the per-document `records-final.csv` written by the
adjudicator into a single CSV under `data/extracted/raw/`. One file per round,
no subfolders, same names every run.

It is a concatenation and nothing else. No row is dropped, reordered within a
document, rewritten, or re-typed, and no column is added or removed. What comes
out is what the adjudicators wrote, in document order, so anything read off it
can be traced back to a `file_id` and a `source_page` in the working tree.

    python -m src.pipeline.combine_extracted_raw
    python -m src.pipeline.combine_extracted_raw --check

`--check` writes nothing and fails if a combined file is missing or has drifted
from the working tree.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from src.catalog.simple_pdf_extraction import csv_workflow

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKING_DIR = PROJECT_ROOT / "ledgers" / "working" / "pdf-extraction-csv"
RAW_DIR = PROJECT_ROOT / "data" / "extracted" / "raw"
RECORDS = "records-final.csv"
# The scope whose worklist names the documents of a round. `publish` reads the
# same worklist under the same scope, so the two ends of the pipeline agree on
# which documents belong to a route.
DEFAULT_SCOPE = "active"


class CombineError(RuntimeError):
    """Raised when the working tree cannot be combined without losing rows."""


def read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise CombineError(f"{path} is empty; it must carry at least a header")
        return header, [row for row in reader]


def rounds() -> list[Path]:
    if not WORKING_DIR.is_dir():
        raise CombineError(f"No extraction working tree at {WORKING_DIR}")
    return sorted(path for path in WORKING_DIR.iterdir() if path.is_dir())


def combine_round(
    route: Path, scope: str = DEFAULT_SCOPE
) -> tuple[list[str], list[list[str]], list[str], list[str]]:
    """Return the round's header, every row, the documents it drew from, and
    the documents in scope that are not adjudicated yet.

    Membership comes from the same scope worklist `publish_round` reads, not
    from the directory listing. The listing holds a directory for every
    document ever prepared, so a document parked with two candidate lanes and
    no final refused the whole route here while the route published fine at the
    other end of the pipeline. A worklisted document with no `records-final.csv`
    is named and skipped: it is work outstanding, not a broken round, and a
    silently short file is what this function exists to prevent.
    """

    worklisted = [row["file_id"] for row in csv_workflow.worklist_for_scope(route.name, scope)]
    if not worklisted:
        raise CombineError(f"{route.name}: the {scope} worklist names no documents")
    # Documents go in file_id order, the order `publish_round` sorts its round
    # by. The worklist lists them in assignment order, and a raw file written in
    # that order carries the same rows as the round in a different sequence,
    # which the release's row-for-row comparison reads as a changed corpus.
    documents = [route / file_id for file_id in sorted(worklisted)]
    unfinished = [path.name for path in documents if not (path / RECORDS).is_file()]
    finished = [path for path in documents if (path / RECORDS).is_file()]
    if not finished:
        raise CombineError(
            f"{route.name}: no document in the {scope} worklist is adjudicated"
        )
    header: list[str] | None = None
    rows: list[list[str]] = []
    for document in finished:
        found, document_rows = read_rows(document / RECORDS)
        if header is None:
            header = found
        elif found != header:
            raise CombineError(
                f"{route.name}/{document.name}: header differs from the rest of the round. "
                "Every document in a round shares one contract; combining across two "
                "would shift values into the wrong columns."
            )
        rows.extend(document_rows)
    assert header is not None
    return header, rows, [path.name for path in finished], unfinished


def write_round(route_name: str, header: list[str], rows: list[list[str]]) -> Path:
    target = RAW_DIR / f"{route_name}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n", quoting=csv.QUOTE_ALL)
        writer.writerow(header)
        writer.writerows(rows)
    return target


def combine(check: bool = False, scope: str = DEFAULT_SCOPE) -> int:
    total_rows = total_docs = 0
    stale: list[str] = []
    outstanding: list[str] = []
    for route in rounds():
        header, rows, documents, unfinished = combine_round(route, scope)
        total_rows += len(rows)
        total_docs += len(documents)
        outstanding.extend(f"{route.name}/{name}" for name in unfinished)
        target = RAW_DIR / f"{route.name}.csv"
        if check:
            if not target.is_file():
                stale.append(f"{target.name}: missing")
                continue
            found_header, found_rows = read_rows(target)
            if found_header != header or found_rows != rows:
                stale.append(
                    f"{target.name}: {len(found_rows)} row(s) on disk, "
                    f"{len(rows)} in the working tree"
                )
            continue
        write_round(route.name, header, rows)
        print(f"{route.name:<32} {len(documents):2d} document(s)  {len(rows):5d} row(s)")
    # Named every run, in both modes. A document left out of a round is the one
    # thing a reader of the combined file cannot see in it.
    for name in outstanding:
        print(f"unfinished: {name}")
    if check:
        for line in stale:
            print(f"STALE  : {line}")
        if stale:
            print(f"FAIL: {len(stale)} round(s) differ. Run without --check.")
            return 1
        print(
            f"PASS: {total_rows} row(s) across {len(rounds())} round(s) match the "
            f"working tree; {len(outstanding)} document(s) unfinished"
        )
        return 0
    print(
        f"PASS: {total_rows} row(s) from {total_docs} document(s) -> {RAW_DIR}; "
        f"{len(outstanding)} document(s) unfinished"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail if a combined file has drifted from the working tree",
    )
    parser.add_argument(
        "--scope",
        default=DEFAULT_SCOPE,
        help="the worklist scope naming the documents of each round",
    )
    args = parser.parse_args()
    try:
        sys.exit(combine(args.check, args.scope))
    except CombineError as error:
        raise SystemExit(f"FAIL: {error}")


if __name__ == "__main__":
    main()
