"""Build a positional grid for every page of a PDF.

Flat text extraction loses which column a number belongs to, which is the single
largest source of wrong values in this pipeline: an extractor reading linearised
text has to guess column membership, and on pages whose text layer is drawn
twice (a fake-bold effect) the guess is usually wrong.

This module recovers the grid arithmetically from word coordinates:

  * characters are clustered into lines by their y position;
  * the value columns are found by clustering the x positions of numeric cells
    and keeping the right-hand band of well-populated, evenly spaced columns;
  * each printed value is assigned to its nearest column centre;
  * a row label is everything printed to the left of that band;
  * a header is read from the line above the data, repairing the doubled-draw
    artifact where the whole header is rendered twice.

Nothing here decides meaning. It reports what is printed and where, so that
choosing the record family, category and scope stays with the reader.
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics
from pathlib import Path

import pdfplumber

NUMERIC = re.compile(r"^\(?-?[$€£]?\s?[\d,]+\.?\d*\)?%?$")
GRID_COLUMNS = (
    "file_id", "source_page", "row_index", "source_row_label",
    "column_index", "column_x", "source_column_label", "value_raw",
)


def _dedupe_words(words):
    seen = {}
    for w in words:
        seen.setdefault((w["text"], round(w["x0"] / 2.0), round(w["top"] / 2.0)), w)
    return sorted(seen.values(), key=lambda w: (w["top"], w["x0"]))


def _group_lines(words, tol=3.0):
    lines = []
    for w in words:
        for ln in lines:
            if abs(ln["top"] - w["top"]) <= tol:
                ln["words"].append(w)
                ln["top"] = min(ln["top"], w["top"])
                break
        else:
            lines.append({"top": w["top"], "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
    return sorted(lines, key=lambda ln: ln["top"])


def _clusters(lines, tol=12.0):
    xs = sorted(w["x0"] for ln in lines for w in ln["words"] if NUMERIC.match(w["text"]))
    if not xs:
        return []
    out, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] <= tol:
            cur.append(x)
        else:
            out.append(cur)
            cur = [x]
    out.append(cur)
    return [(statistics.median(c), len(c)) for c in out]


def _value_band(cl):
    """Keep the right-hand run of populated, evenly spaced columns.

    Footnote markers and digits inside labels also cluster, but they sit far to
    the left of the value band and are separated from it by a large x gap.

    The well-populated columns locate the band, but they do not define its
    right edge. The rightmost columns of a horizon table (``20 Year``, ``25
    Year``, ``30 Year``) are printed only for the few rows old enough to have
    them, so keeping columns by population deletes real ones along with every
    value under them. Find the left edge from the dense core, then keep
    everything at or right of it.
    """
    cl = [c for c in cl if c[1] >= 2]
    if len(cl) < 2:
        return cl
    peak = max(n for _, n in cl)
    core = [c for c in cl if c[1] >= max(3, peak * 0.4)] or cl
    if len(core) < 2:
        return core
    gaps = [(core[i + 1][0] - core[i][0], i) for i in range(len(core) - 1)]
    typical = statistics.median(g for g, _ in gaps)
    wide = [(g, i) for g, i in gaps if g > typical * 2.2]
    if wide:
        _, i = max(wide)
        if len(core[i + 1:]) >= 2:
            core = core[i + 1:]
    edge = core[0][0] - max(typical, 1.0) * 0.6
    return [c for c in cl if c[0] >= edge]


STOPWORDS = frozenset(
    "a an and as at but by for from in into is it of on or the to up was were "
    "with that this those these than then over under after before its".split()
)


def _reads_as_prose(labels) -> bool:
    """Does this line look like a sentence someone wrote, not a header row?

    Column headers are short noun phrases and almost never contain function
    words. A running sentence that happens to cross the value band does, and
    it also tends to fill every bucket with a couple of words each.
    """
    words = [w for label in labels for w in label.lower().split()]
    if not words:
        return True
    return sum(w.strip(",.;:()") in STOPWORDS for w in words) >= 2


def _nearest(x, centres, tol=25.0):
    best, dist = None, float("inf")
    for i, (c, _) in enumerate(centres):
        if abs(x - c) < dist:
            best, dist = i, abs(x - c)
    return best if dist <= tol else None


def undouble(text: str) -> str:
    """Repair a label whose text is rendered twice by an overlapping draw.

    The duplicate is offset by about a point, so words interleave into nonsense
    such as ``1 Year1 Year`` or ``10 Yea1r 0 Year``. Ignoring whitespace the
    sequence is a literal repeat, so the printed label is the first half. The
    prefix of the original string carrying that half keeps the real spacing.
    """
    text = " ".join(text.split())
    solid = re.sub(r"\s+", "", text)
    n = len(solid)
    if n < 4 or n % 2 or solid[: n // 2] != solid[n // 2:]:
        return text
    want, seen, out = n // 2, 0, []
    for ch in text:
        if seen == want:
            break
        out.append(ch)
        if not ch.isspace():
            seen += 1
    return "".join(out).strip()


def _blocks(rows):
    """Split data rows into vertically contiguous runs, one per printed table."""
    if len(rows) < 2:
        return [rows]
    gaps = sorted(rows[i + 1]["top"] - rows[i]["top"] for i in range(len(rows) - 1))
    pitch = statistics.median(gaps)
    out, cur = [], [rows[0]]
    for prev, row in zip(rows, rows[1:]):
        if row["top"] - prev["top"] > max(pitch * 2.5, pitch + 8):
            out.append(cur)
            cur = [row]
        else:
            cur.append(row)
    out.append(cur)
    return out


def _header_above(block, lines, centres, left):
    """The nearest header-like line above a block, and the y it was found at.

    Scanning upward and stopping at the first qualifying line beats taking the
    line with the most words in the band: a prose paragraph puts more words
    across those x positions than a real header does.
    """
    top = block[0]["top"]
    reach = top - 120.0
    for ln in reversed(lines):
        if ln["top"] > top:
            continue
        if ln["top"] < reach:
            break
        buckets, hits = [[] for _ in centres], 0
        for w in ln["words"]:
            if w["x0"] < left:
                continue
            i = _nearest(w["x0"], centres, tol=42.0)
            if i is not None:
                buckets[i].append(w["text"])
                hits += 1
        if hits < 2:
            continue
        labels = [undouble(" ".join(b)) for b in buckets]
        # A header names several columns. One alphabetic bucket means a stray
        # word from a sentence landed in the band, not a row of column names.
        if sum(bool(re.search(r"[A-Za-z]", x)) for x in labels) < 2:
            continue
        if _reads_as_prose(labels):
            continue  # a sentence between the header and the table, not the header
        return labels, ln["top"]
    return [""] * len(centres), None


def page_grid(page, file_id: str = "") -> dict | None:
    words = _dedupe_words(page.extract_words(use_text_flow=False, keep_blank_chars=False))
    lines = _group_lines(words)
    centres = _value_band(_clusters(lines))
    if len(centres) < 2:
        return None
    left = centres[0][0] - 8

    rows = []
    for ln in lines:
        vals = [w for w in ln["words"] if NUMERIC.match(w["text"]) and w["x0"] >= left]
        if not vals:
            continue
        label = " ".join(w["text"] for w in ln["words"] if w["x0"] < left).strip()
        cells = [""] * len(centres)
        for w in vals:
            i = _nearest(w["x0"], centres)
            if i is not None:
                cells[i] = (cells[i] + " " + w["text"]).strip()
        if label and any(cells):
            rows.append({"top": ln["top"], "label": label, "cells": cells})
    if not rows:
        return None

    # A page can hold more than one table, and narrative text above a table
    # also lands a stray number in the value band. Split the rows into
    # vertically contiguous blocks and read a header for each, so a sentence
    # higher up the page cannot supply the column names for the table below it.
    kept = []
    for block in _blocks(rows):
        headers, header_top = _header_above(block, lines, centres, left)
        body = [r for r in block if r["top"] != header_top]
        if not body:
            continue
        for row in body:
            row["headers"] = headers
        kept.extend(body)
    if not kept:
        return None

    return {
        "file_id": file_id,
        "page": page.page_number,
        "columns": [round(c) for c, _ in centres],
        "headers": kept[0]["headers"],
        "rows": kept,
    }


def grid_rows(grid: dict):
    for r_i, row in enumerate(grid["rows"], start=1):
        headers = row.get("headers") or grid["headers"]
        for c_i, value in enumerate(row["cells"]):
            if not value:
                continue
            yield {
                "file_id": grid["file_id"],
                "source_page": grid["page"],
                "row_index": r_i,
                "source_row_label": row["label"],
                "column_index": c_i + 1,
                "column_x": grid["columns"][c_i],
                "source_column_label": headers[c_i],
                "value_raw": value,
            }


def build(pdf_path: Path, out_path: Path, file_id: str) -> tuple[int, int]:
    pages = grids = 0
    rows: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages += 1
            g = page_grid(page, file_id)
            if g:
                grids += 1
                rows.extend(grid_rows(g))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(GRID_COLUMNS), quoting=csv.QUOTE_ALL,
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return grids, len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build positional page grids for a PDF.")
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--file-id", default="")
    a = ap.parse_args()
    grids, n = build(Path(a.pdf), Path(a.out), a.file_id)
    print(f"PASS: {grids} gridded pages, {n} value cells -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
