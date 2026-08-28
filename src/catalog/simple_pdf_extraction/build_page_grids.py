"""Build one positional grid CSV per corpus document.

Reads the frozen routing registry, writes ``data/documents/grids/<stem>.csv``
and a manifest recording what each document produced. A document with no
gridded page still gets a header-only CSV and a manifest row, so a reader can
tell "no tables on this document" from "not built yet".

    python -m src.catalog.simple_pdf_extraction.build_page_grids
    python -m src.catalog.simple_pdf_extraction.build_page_grids --scope active
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import pdfplumber

from .page_grid import GRID_COLUMNS, grid_rows, page_grid

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ROUTING = PROJECT_ROOT / "data" / "schemas" / "EXTRACTION-ROUTING.csv"
SCOPE = PROJECT_ROOT / "data" / "schemas" / "EXTRACTION-DISPATCH-SCOPE.csv"
GRID_ROOT = PROJECT_ROOT / "data" / "documents" / "grids"
MANIFEST = GRID_ROOT / "MANIFEST.csv"

MANIFEST_COLUMNS = (
    "file_id", "filename", "pages", "gridded_pages", "value_cells",
    "named_columns", "total_columns", "text_layer", "note",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, columns, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(columns), quoting=csv.QUOTE_ALL,
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def text_layer_of(txt_path: Path) -> str:
    """native, ocr, mixed or unknown, from the page-aligned TXT header."""
    if not txt_path.is_file():
        return "unknown"
    head = txt_path.read_text(encoding="utf-8", errors="replace")[:900]
    native = ocr = None
    for token, name in (("native_text_pages:", "native"), ("ocr_pages:", "ocr")):
        if token in head:
            try:
                value = int(head.split(token, 1)[1].split()[0].strip("|"))
            except (ValueError, IndexError):
                continue
            if name == "native":
                native = value
            else:
                ocr = value
    if native is None or ocr is None:
        return "unknown"
    if native and ocr:
        return "mixed"
    return "ocr" if ocr else "native"


def build_document(pdf_path: Path, out_path: Path, file_id: str) -> dict:
    rows, gridded, named, cols = [], 0, 0, 0
    with pdfplumber.open(pdf_path) as pdf:
        pages = len(pdf.pages)
        for page in pdf.pages:
            grid = page_grid(page, file_id)
            if not grid:
                continue
            gridded += 1
            cols += len(grid["columns"])
            named += sum(1 for h in grid["headers"] if h and any(c.isalpha() for c in h))
            rows.extend(grid_rows(grid))
    write_csv(out_path, GRID_COLUMNS, rows)
    return {"pages": pages, "gridded_pages": gridded, "value_cells": len(rows),
            "named_columns": named, "total_columns": cols}


def main() -> int:
    ap = argparse.ArgumentParser(description="Build positional page grids for the corpus.")
    ap.add_argument("--scope", choices=("all", "active"), default="all")
    ap.add_argument("--file-id", help="build a single document")
    args = ap.parse_args()

    routing = {r["file_id"]: r for r in read_csv(ROUTING)}
    wanted = list(routing)
    if args.file_id:
        wanted = [args.file_id]
    elif args.scope == "active":
        wanted = [r["file_id"] for r in read_csv(SCOPE) if r["dispatch_scope"] == "ACTIVE"]

    manifest = {r["file_id"]: r for r in read_csv(MANIFEST)} if MANIFEST.is_file() else {}
    started, built, failed = time.time(), 0, 0
    for file_id in wanted:
        row = routing.get(file_id)
        if not row:
            continue
        pdf_path = PROJECT_ROOT / row["pdf_path"]
        out = GRID_ROOT / f"{Path(row['filename']).stem}.csv"
        layer = text_layer_of(PROJECT_ROOT / row["txt_path"])
        entry = {"file_id": file_id, "filename": row["filename"],
                 "text_layer": layer, "note": ""}
        if not pdf_path.is_file():
            entry.update(pages=0, gridded_pages=0, value_cells=0, named_columns=0,
                         total_columns=0, note="PDF missing")
            failed += 1
        else:
            try:
                entry.update(build_document(pdf_path, out, file_id))
                built += 1
            except Exception as exc:  # a damaged PDF must not stop the batch
                entry.update(pages=0, gridded_pages=0, value_cells=0, named_columns=0,
                             total_columns=0, note=f"{type(exc).__name__}: {exc}"[:120])
                failed += 1
        if entry.get("gridded_pages") == 0 and not entry["note"]:
            entry["note"] = ("no text layer to grid; read the page images"
                             if layer == "ocr" else "no numeric tables detected")
        manifest[file_id] = entry

    write_csv(MANIFEST, MANIFEST_COLUMNS,
              [manifest[k] for k in sorted(manifest)])
    cells = sum(int(r.get("value_cells") or 0) for r in manifest.values())
    gp = sum(int(r.get("gridded_pages") or 0) for r in manifest.values())
    print(f"PASS: built {built} documents ({failed} skipped), {gp} gridded pages, "
          f"{cells:,} value cells in {time.time() - started:.0f}s -> {GRID_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
