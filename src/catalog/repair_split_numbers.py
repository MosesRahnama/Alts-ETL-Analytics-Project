"""Recover numbers that the PDF text layer splits into fragments.

`pdfplumber.Page.extract_text()` inserts a space between two character clusters
whose horizontal gap falls below its word threshold, which in right-aligned
numeric columns splits the leading digit off the rest of the number:

    printed on the page   135,465,564.65
    text layer returns    1 35,465,564.65

The two word boxes physically touch (gap -0.06pt on SRC137 page 1), so the join
is recoverable without guessing: re-read the page as word boxes, sort each line
left to right, and glue two neighbours when the gap is at or below the epsilon
AND both sides look numeric.

    python -m src.catalog.repair_split_numbers --file-id SRC137 --page 1
    python -m src.catalog.repair_split_numbers --audit

This module exists for two consumers:

1. the evidence validator, which today REJECTS the correct printed number and
   ACCEPTS the corrupted one, and
2. a Round 2 consolidator cross-checking a number read off the page image.

It is a repair of a rendering defect, not an extraction method. No agent may
substitute it for reading the page.
"""

from __future__ import annotations

import argparse
import csv
import re
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORPUS = PROJECT_ROOT / "data" / "documents" / "pdf"
MANIFEST = PROJECT_ROOT / "data" / "documents" / "txt" / "MANIFEST.csv"
CSV_OUT = PROJECT_ROOT / "ledgers" / "analysis" / "split_number_audit.csv"

GAP_EPSILON = 0.6           # points; touching or overlapping boxes
ROW_BUCKET = 3.0            # points; group word boxes into visual lines
NUM_TAIL = re.compile(r"[\d,.]$")
NUM_HEAD = re.compile(r"^[\d,.]")
SPLIT = re.compile(r"(?<![\d,.])\d{1,3}\s,?\d{1,3},\d{3}(?:,\d{3})*(?:\.\d+)?(?![\d,])")


def repaired_page_lines(page, gap_epsilon: float = GAP_EPSILON) -> list[str]:
    """Visual lines with touching numeric fragments glued back together."""
    words = page.extract_words()
    if not words:
        return []
    rows: dict[int, list[dict]] = {}
    for word in words:
        rows.setdefault(round(word["top"] / ROW_BUCKET), []).append(word)

    lines: list[str] = []
    for key in sorted(rows):
        ordered = sorted(rows[key], key=lambda w: w["x0"])
        merged = [dict(ordered[0])]
        for word in ordered[1:]:
            previous = merged[-1]
            gap = word["x0"] - previous["x1"]
            glue = (
                gap <= gap_epsilon
                and NUM_TAIL.search(previous["text"])
                and NUM_HEAD.match(word["text"])
            )
            if glue:
                previous["text"] += word["text"]
                previous["x1"] = word["x1"]
            else:
                merged.append(dict(word))
        lines.append(" ".join(item["text"] for item in merged))
    return lines


def repaired_page_text(pdf_path: Path, page_number: int) -> str:
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(repaired_page_lines(pdf.pages[page_number - 1]))


def audit(limit: int | None = None) -> int:
    """Count pages where the repair changes the reading, corpus-wide."""
    import pdfplumber

    warnings.filterwarnings("ignore")
    with MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    targets = [row for row in manifest if not row["error"]]
    if limit:
        targets = targets[:limit]

    rows: list[dict[str, str]] = []
    for record in targets:
        pdf_path = CORPUS / record["filename"]
        if not pdf_path.exists():
            continue
        damaged_pages = 0
        repaired_pages = 0
        first_example = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for index, page in enumerate(pdf.pages, start=1):
                    raw = page.extract_text() or ""
                    if not SPLIT.search(raw):
                        continue
                    damaged_pages += 1
                    fixed = "\n".join(repaired_page_lines(page))
                    if not SPLIT.search(fixed):
                        repaired_pages += 1
                    if not first_example:
                        hit = SPLIT.search(raw)
                        first_example = f"p{index}: {hit.group(0)}"
        except Exception as exc:
            rows.append({
                "source": record["filename"], "file_id": record["file_id"],
                "pages": record["pages"], "damaged_pages": "", "repaired_pages": "",
                "example": "", "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        if damaged_pages:
            rows.append({
                "source": record["filename"], "file_id": record["file_id"],
                "pages": record["pages"], "damaged_pages": str(damaged_pages),
                "repaired_pages": str(repaired_pages), "example": first_example, "error": "",
            })

    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    header = ["source", "file_id", "pages", "damaged_pages", "repaired_pages", "example", "error"]
    with CSV_OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    damaged = sum(int(r["damaged_pages"] or 0) for r in rows)
    fixed = sum(int(r["repaired_pages"] or 0) for r in rows)
    print(f"files with split numbers: {len(rows)}")
    print(f"pages with split numbers: {damaged}")
    print(f"pages fully repaired by box merging: {fixed} ({100 * fixed / max(damaged, 1):.1f}%)")
    print(f"wrote {CSV_OUT.relative_to(PROJECT_ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-id")
    parser.add_argument("--page", type=int)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    if args.audit:
        return audit(args.limit)
    if not (args.file_id and args.page):
        parser.error("pass --file-id and --page, or --audit")

    warnings.filterwarnings("ignore")
    with MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        record = {row["file_id"]: row for row in csv.DictReader(handle)}[args.file_id]
    print(repaired_page_text(CORPUS / record["filename"], args.page))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
