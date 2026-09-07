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

from src.common import matrices

TOKEN_RULES = "numeric-token"
GEOMETRY = "grid-geometry"
STOPWORD_RULES = "header-stopwords"

NUMERIC = re.compile(matrices.resolve(TOKEN_RULES, "numeric_pattern"))
UNIT_SUFFIX = re.compile(matrices.resolve(TOKEN_RULES, "unit_suffix_pattern"))
YEAR_TOKEN = re.compile(matrices.resolve(TOKEN_RULES, "year_pattern"))
HEADER_FOOTNOTE = re.compile(matrices.resolve(TOKEN_RULES, "header_footnote_pattern"))
HEADER_NUMBER = re.compile(matrices.resolve(TOKEN_RULES, "header_number_pattern"))
PERIOD_LABEL = re.compile(matrices.resolve(TOKEN_RULES, "period_label_pattern"))
DECORATED_NUMBER = re.compile(matrices.resolve(TOKEN_RULES, "data_decoration_pattern"))


def _geometry_number(name: str) -> float:
    return float(matrices.resolve(GEOMETRY, name))


HEADER_PHRASE_GAP = _geometry_number("header_phrase_gap")
HEADER_FRAGMENT_GAP = _geometry_number("header_fragment_gap")
HEADER_ANNOTATION_GAP = _geometry_number("header_annotation_gap")
HEADER_OVERLAP_MIN = _geometry_number("header_overlap_min")
HEADER_FALLBACK_TOLERANCE = _geometry_number("header_fallback_tolerance")
HEADER_SEARCH_REACH = _geometry_number("header_search_reach")
HEADER_FIRST_GAP = _geometry_number("header_first_gap")
HEADER_STACK_ROWS = int(_geometry_number("header_stack_rows"))
HEADER_MIN_HITS = int(_geometry_number("header_min_hits"))
HEADER_MIN_NAMES = int(_geometry_number("header_min_names"))
HEADER_MIN_YEARS = int(_geometry_number("header_min_years"))
UNIT_SUFFIX_GAP = _geometry_number("unit_suffix_gap")
LEADING_YEAR_MIN_COUNT = int(_geometry_number("leading_year_min_count"))
CONTINUATION_TOLERANCE = _geometry_number("header_continuation_tolerance")
CONTINUATION_PAGE_GAP = int(_geometry_number("header_continuation_page_gap"))
COORDINATE_DEDUPE_BUCKET = _geometry_number("coordinate_dedupe_bucket")
LINE_TOLERANCE = _geometry_number("line_tolerance")
CLUSTER_TOLERANCE = _geometry_number("cluster_tolerance")
VALUE_ASSIGNMENT_TOLERANCE = _geometry_number("value_assignment_tolerance")
LABEL_BAND_OFFSET = _geometry_number("label_band_offset")
PROSE_STOPWORD_MIN = int(_geometry_number("prose_stopword_min"))
BLOCK_GAP_RATIO = _geometry_number("block_gap_ratio")
BLOCK_GAP_ADDITION = _geometry_number("block_gap_addition")
DOUBLED_LABEL_MIN_LENGTH = int(_geometry_number("doubled_label_min_length"))
GRID_COLUMNS = (
    "file_id", "source_page", "row_index", "source_row_label",
    "column_index", "column_x", "source_column_label", "value_raw",
)


def _dedupe_words(words):
    seen = {}
    for w in words:
        seen.setdefault((
            w["text"],
            round(w["x0"] / COORDINATE_DEDUPE_BUCKET),
            round(w["top"] / COORDINATE_DEDUPE_BUCKET),
        ), w)
    return sorted(seen.values(), key=lambda w: (w["top"], w["x0"]))


def _join_value_units(words):
    """Join a detached percent, multiple, or basis-point unit to its number."""
    out = []
    index = 0
    while index < len(words):
        word = words[index]
        if index + 1 < len(words):
            suffix = words[index + 1]
            gap = suffix["x0"] - word["x1"]
            if (
                NUMERIC.fullmatch(word["text"])
                and UNIT_SUFFIX.fullmatch(suffix["text"])
                and abs(suffix["top"] - word["top"]) <= LINE_TOLERANCE
                and 0 <= gap <= UNIT_SUFFIX_GAP
            ):
                merged = dict(word)
                merged["text"] = f"{word['text']} {suffix['text']}"
                merged["x1"] = suffix["x1"]
                if "bottom" in suffix:
                    merged["bottom"] = max(word.get("bottom", 0), suffix["bottom"])
                out.append(merged)
                index += 2
                continue
        out.append(word)
        index += 1
    return out


def _group_lines(words, tol=None):
    tol = LINE_TOLERANCE if tol is None else tol
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


def _clusters(lines, tol=None):
    tol = CLUSTER_TOLERANCE if tol is None else tol
    xs = sorted(
        w["x0"] for ln in lines for w in ln["words"]
        if NUMERIC.fullmatch(w["text"])
    )
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
    if matrices.resolve(GEOMETRY, "value_band") != "right_of_dense_core_with_extension":
        raise ValueError("grid-geometry.csv names an unknown value band")
    cl = [c for c in cl if c[1] >= int(matrices.resolve(GEOMETRY, "column_min_population"))]
    if len(cl) < 2:
        return cl
    peak = max(n for _, n in cl)
    dense_floor = int(_geometry_number("dense_core_floor"))
    dense_ratio = _geometry_number("dense_core_ratio")
    core = [c for c in cl if c[1] >= max(dense_floor, peak * dense_ratio)] or cl
    if len(core) < 2:
        return core
    gaps = [(core[i + 1][0] - core[i][0], i) for i in range(len(core) - 1)]
    typical = statistics.median(g for g, _ in gaps)
    wide = [
        (g, i) for g, i in gaps
        if g > typical * _geometry_number("wide_gap_ratio")
    ]
    if wide:
        _, i = max(wide)
        # Cut only label junk: one or two clusters of footnote marks or label
        # digits left of the gap. A populated run of three or more columns is
        # a real column group (capital columns before a returns block, with a
        # visual divider between), and cutting it swallows every money value
        # into the row label.
        if (
            len(core[i + 1:]) >= 2
            and i + 1 <= int(_geometry_number("max_left_junk_clusters"))
        ):
            core = core[i + 1:]
    extension_width = min(
        max(typical, 1.0) * _geometry_number("band_edge_ratio"),
        _geometry_number("band_extension_max_gap"),
    )
    edge = core[0][0] - extension_width
    extension_floor = max(
        dense_floor, peak * _geometry_number("band_extension_min_ratio")
    )
    return [
        c for c in cl
        if c[0] >= core[0][0]
        or (c[0] >= edge and c[1] >= extension_floor)
    ]


STOPWORDS = frozenset(matrices.mapping(STOPWORD_RULES))


def _reads_as_prose(labels) -> bool:
    """Does this line look like a sentence someone wrote, not a header row?

    Column headers are short noun phrases and almost never contain function
    words. A running sentence that happens to cross the value band does, and
    it also tends to fill every bucket with a couple of words each.
    """
    words = [w for label in labels for w in label.lower().split()]
    if not words:
        return True
    return sum(w.strip(",.;:()") in STOPWORDS for w in words) >= PROSE_STOPWORD_MIN


def _nearest(x, centres, tol=None):
    tol = VALUE_ASSIGNMENT_TOLERANCE if tol is None else tol
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
    if matrices.resolve(GEOMETRY, "doubled_label") != "first_half_kept":
        raise ValueError("grid-geometry.csv names an unknown repair")
    text = " ".join(text.split())
    solid = re.sub(r"\s+", "", text)
    n = len(solid)
    if (
        n < DOUBLED_LABEL_MIN_LENGTH
        or n % 2
        or solid[: n // 2] != solid[n // 2:]
    ):
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
        if row["top"] - prev["top"] > max(
            pitch * BLOCK_GAP_RATIO, pitch + BLOCK_GAP_ADDITION
        ):
            out.append(cur)
            cur = [row]
        else:
            cur.append(row)
    out.append(cur)
    return out


def _column_spans(block, centres):
    """The x extent each column's values occupy across one block."""
    spans = [None] * len(centres)
    for row in block:
        for i, extent in enumerate(row.get("extents", [])):
            if extent is None:
                continue
            if spans[i] is None:
                spans[i] = list(extent)
            else:
                spans[i][0] = min(spans[i][0], extent[0])
                spans[i][1] = max(spans[i][1], extent[1])
    return spans


def _header_phrases(words, left, centres):
    """Consecutive header words grouped into printed phrases.

    Words inside one column label sit a few points apart; a jump wider than
    `gap` is the space between two column labels. Grouping first keeps a
    multi-word header whole instead of scattering it word by word across the
    narrow spans of right-aligned numbers.
    """
    phrases = []
    for w in words:
        if w["x1"] <= left:
            continue
        hint = _nearest(w["x0"], centres, tol=HEADER_FALLBACK_TOLERANCE)
        if phrases:
            prior = phrases[-1]
            gap = w["x0"] - prior["x1"]
            fragment = (
                gap <= HEADER_FRAGMENT_GAP
                and (len(prior["last_text"]) <= 2 or len(w["text"]) <= 2)
            )
            annotation = (
                gap <= HEADER_ANNOTATION_GAP
                and (
                    HEADER_NUMBER.fullmatch(w["text"])
                    or HEADER_FOOTNOTE.fullmatch(w["text"])
                )
            )
            same_column = (
                gap <= HEADER_PHRASE_GAP
                and prior["hint"] is not None
                and prior["hint"] == hint
            )
            tight_phrase = gap <= HEADER_ANNOTATION_GAP
            if fragment or annotation or same_column or tight_phrase:
                separator = "" if fragment else " "
                prior["text"] += separator + w["text"]
                prior["x1"] = max(prior["x1"], w["x1"])
                prior["last_text"] = w["text"]
                if prior["hint"] is None:
                    prior["hint"] = hint
                continue
        phrases.append({
            "text": w["text"], "x0": w["x0"], "x1": w["x1"],
            "hint": hint, "last_text": w["text"],
        })
    for phrase in phrases:
        phrase["hint"] = _nearest(
            (phrase["x0"] + phrase["x1"]) / 2.0,
            centres,
            tol=HEADER_FALLBACK_TOLERANCE,
        )
    return phrases


def _header_line(ln, centres, spans, left):
    """One line read as column labels, or None when it fails the header tests."""
    anchors = [
        span if span is not None else (centre, centre)
        for (centre, _), span in zip(centres, spans)
    ]
    buckets, landed_columns = [[] for _ in centres], set()
    for phrase in _header_phrases(ln["words"], left, centres):
        landed = [phrase["hint"]] if phrase["hint"] is not None else []
        if not landed:
            overlaps = [
                (min(phrase["x1"], stop) - max(phrase["x0"], start), i)
                for i, (start, stop) in enumerate(anchors)
            ]
            overlap, i = max(overlaps, default=(0.0, None))
            landed = [i] if i is not None and overlap >= HEADER_OVERLAP_MIN else []
        if not landed:
            middle = (phrase["x0"] + phrase["x1"]) / 2.0
            i = _nearest(middle, centres, tol=HEADER_FALLBACK_TOLERANCE)
            landed = [i] if i is not None else []
        for i in landed:
            buckets[i].append(phrase["text"])
            landed_columns.add(i)
    return buckets, len(landed_columns)


def _carries_data_values(ln, left) -> bool:
    """Whether a line prints decorated numbers inside the band.

    A header line's only numerals are bare integers (`1 Year`, a year column
    such as `2016`). A currency amount, percentage, decimal, or parenthesized
    figure marks a data line, including a benchmark row whose long printed
    name sits inside the band and so carries no row label.
    """
    return any(
        w["x1"] > left
        and NUMERIC.fullmatch(w["text"])
        and not HEADER_FOOTNOTE.fullmatch(w["text"])
        and DECORATED_NUMBER.search(w["text"])
        for w in ln["words"]
    )


def _qualify_header(buckets, hits):
    """The header tests shared by both lines of a stack."""
    if hits < HEADER_MIN_HITS:
        return None
    labels = [undouble(" ".join(b)) for b in buckets]
    # A header names several columns. A bucket is a name only when it carries a
    # letter and is not itself a numeric token: a data row of multiples
    # (`1.02x`) has letters but names nothing, and one name-like bucket means a
    # stray word from a sentence landed in the band, not a row of column names.
    names = sum(
        bool(re.search(r"[A-Za-z]", x)) and not NUMERIC.fullmatch(x) for x in labels
    )
    # A financial statement's whole header is often the year pair (`2016
    # 2015`): bare years name columns even though they carry no letter.
    years = sum(bool(YEAR_TOKEN.match(x)) for x in labels if x)
    if names < HEADER_MIN_NAMES and years < HEADER_MIN_YEARS:
        return None
    if _reads_as_prose(labels):
        return None  # a sentence between the header and the table, not the header
    return labels


def _stack_labels(upper, lower):
    return [
        (top + " " + bottom).strip() if top else bottom
        for top, bottom in zip(upper, lower)
    ]


def _header_above(block, lines, centres, left, excluded_tops=frozenset()):
    """The nearest header-like line above a block, and the y it was found at.

    Scanning upward and stopping at the first qualifying line beats taking the
    line with the most words in the band: a prose paragraph puts more words
    across those x positions than a real header does. When the line above the
    found header also qualifies, its bucket text is prepended, so a banner over
    leaf headers reads as one label; at most two lines stack. A line named in
    `excluded_tops` is another block's data row, and a data row never headers
    the block beneath it: a benchmark line with a long printed name reads
    enough like a header to pass every text test.
    """
    if matrices.resolve(GEOMETRY, "header_assignment") != "column_hint_then_overlap":
        raise ValueError("grid-geometry.csv names an unknown header assignment")
    if matrices.resolve(GEOMETRY, "header_stack") != "two_lines":
        raise ValueError("grid-geometry.csv names an unknown header stack")
    spans = _column_spans(block, centres)
    top = block[0]["top"]
    reach = top - HEADER_SEARCH_REACH
    first_reach = top - HEADER_FIRST_GAP
    found, found_top, stacked_lines = None, None, 0
    for ln in reversed(lines):
        if ln["top"] > top:
            continue
        if found is None and ln["top"] < first_reach:
            break
        if ln["top"] < reach:
            break
        if ln["top"] in excluded_tops:
            continue
        if _carries_data_values(ln, left):
            if found is not None:
                break
            continue
        labels = _qualify_header(*_header_line(ln, centres, spans, left))
        if labels is None:
            if found is not None:
                break
            continue
        if found is None:
            found, found_top = labels, ln["top"]
            stacked_lines = 1
            if stacked_lines >= HEADER_STACK_ROWS:
                break
            top = ln["top"]
            continue
        found = _stack_labels(labels, found)
        stacked_lines += 1
        if stacked_lines >= HEADER_STACK_ROWS:
            break
        top = ln["top"]
    if found is None:
        return [""] * len(centres), None
    return found, found_top


def _fold_leading_years(centres, rows):
    """Fold a leftmost all-years column into the row labels.

    A date or vintage column of bare four-digit years clusters like a value
    column, which truncates every row label (`Q1 2008` arrives as label `Q1`
    with `2008` as its first cell). When every populated first cell on the
    page, three or more of them, is a bare year, the year belongs to the label
    and the column leaves the band.
    """
    if matrices.resolve(GEOMETRY, "leading_year_column") != "fold_period_labels_only":
        raise ValueError("grid-geometry.csv names an unknown year-column rule")
    if len(centres) < 3:
        return centres, rows
    firsts = [row["cells"][0] for row in rows if row["cells"][0]]
    if (
        len(firsts) < LEADING_YEAR_MIN_COUNT
        or not all(YEAR_TOKEN.fullmatch(cell) for cell in firsts)
        or not all(
            PERIOD_LABEL.fullmatch(row["label"].strip())
            or not re.search(r"[A-Za-z]", row["label"])
            for row in rows if row["cells"][0]
        )
    ):
        return centres, rows
    for row in rows:
        if row["cells"][0]:
            row["label"] = f"{row['label']} {row['cells'][0]}".strip()
        row["cells"] = row["cells"][1:]
        row["extents"] = row["extents"][1:]
    return centres[1:], [row for row in rows if any(row["cells"])]


def _glued_numeric_cell(value: str) -> bool:
    parts = value.split()
    return len(parts) > 1 and all(NUMERIC.fullmatch(part) for part in parts)


def _representative_headers(rows):
    return max(
        (row["headers"] for row in rows),
        key=lambda headers: (
            sum(bool(re.search(r"[A-Za-z]", header)) for header in headers),
            sum(bool(header) for header in headers),
        ),
    )


def page_grid(page, file_id: str = "") -> dict | None:
    words = _join_value_units(
        _dedupe_words(page.extract_words(use_text_flow=False, keep_blank_chars=False))
    )
    lines = _group_lines(words)
    centres = _value_band(_clusters(lines))
    if len(centres) < 2:
        return None
    left = centres[0][0] - LABEL_BAND_OFFSET

    rows = []
    for ln in lines:
        vals = [
            w for w in ln["words"]
            if NUMERIC.fullmatch(w["text"]) and w["x0"] >= left
        ]
        if not vals:
            continue
        label = " ".join(w["text"] for w in ln["words"] if w["x0"] < left).strip()
        cells = [""] * len(centres)
        extents = [None] * len(centres)
        for w in vals:
            i = _nearest(w["x0"], centres)
            if i is not None:
                cells[i] = (cells[i] + " " + w["text"]).strip()
                if extents[i] is None:
                    extents[i] = (w["x0"], w["x1"])
                else:
                    extents[i] = (min(extents[i][0], w["x0"]), max(extents[i][1], w["x1"]))
        if label and any(cells):
            rows.append({"top": ln["top"], "label": label, "cells": cells,
                         "extents": extents})
    if not rows:
        return None
    centres, rows = _fold_leading_years(centres, rows)
    if len(centres) < 2:
        return None

    # A page can hold more than one table, and narrative text above a table
    # also lands a stray number in the value band. Split the rows into
    # vertically contiguous blocks and read a header for each, so a sentence
    # higher up the page cannot supply the column names for the table below it.
    if matrices.resolve(GEOMETRY, "one_row_block") != "drop_prose_numeric_collision_or_headerlike":
        raise ValueError("grid-geometry.csv names an unknown one-row disposition")
    if matrices.resolve(GEOMETRY, "page_block_headers") != "inherit_within_page":
        raise ValueError("grid-geometry.csv names an unknown block-header rule")
    by_top = {ln["top"]: ln for ln in lines}
    data_tops = {row["top"] for row in rows}
    kept = []
    page_headers = None
    for block in _blocks(rows):
        block_tops = {row["top"] for row in block}
        headers, header_top = _header_above(
            block, lines, centres, left, excluded_tops=data_tops - block_tops
        )
        body = [r for r in block if r["top"] != header_top]
        if not body:
            # The whole block was its own header line; release its top so the
            # blocks below may use that line.
            data_tops -= block_tops
            if any(headers):
                page_headers = headers
            continue
        # A block holding a single data row is a stray line, not a table, when
        # its label reads as prose, a cell glued two matched words together
        # (a date fragment such as `30, 2022` arrives as two numeric words in
        # one column), or the line itself qualifies as a header: a header whose
        # period digits (`1 Year`, `3 Year`) land in the band is a caption, not
        # an observation. A total line inside a table sits in a multi-row block
        # and is untouched.
        if len(body) == 1:
            own_line = by_top.get(body[0]["top"])
            own_headers = (
                _qualify_header(
                    *_header_line(own_line, centres, _column_spans(body, centres), left)
                )
                if own_line is not None else None
            )
            headerlike = own_headers is not None
            if headerlike:
                page_headers = (
                    _stack_labels(headers, own_headers) if any(headers) else own_headers
                )
                data_tops -= block_tops
                continue
            if (
                _reads_as_prose([body[0]["label"]])
                or any(_glued_numeric_cell(cell) for cell in body[0]["cells"])
            ):
                continue
        # One header line governs a whole page's table; the blocks below it are
        # split by group headings and blank space, and the ones beyond the
        # header search's reach inherit the page's last found header.
        if any(headers):
            page_headers = headers
        elif page_headers is not None:
            headers = page_headers
        for row in body:
            row["headers"] = headers
        kept.extend(body)
    if not kept:
        return None

    if matrices.resolve(GEOMETRY, "page_header_summary") != "most_named_row":
        raise ValueError("grid-geometry.csv names an unknown page-header summary")
    representative = _representative_headers(kept)

    return {
        "file_id": file_id,
        "page": page.page_number,
        "columns": [round(c) for c, _ in centres],
        "headers": representative,
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


def inherit_headers(grid: dict, previous: dict | None) -> None:
    """Carry the previous page's headers onto a headerless continuation page.

    A long table prints its header once and runs on; the later pages hold the
    same columns and no header line. When this page found no header for a row
    and the previous gridded page has the same column count with every centre
    within 15 points, that page's headers stand in. Coordinates decide, never
    text.
    """
    if matrices.resolve(GEOMETRY, "header_continuation") != "adjacent_previous_page_same_columns":
        raise ValueError("grid-geometry.csv names an unknown header continuation")
    if previous is None:
        return
    if grid["page"] - previous["page"] != CONTINUATION_PAGE_GAP:
        return
    if len(grid["columns"]) != len(previous["columns"]):
        return
    if any(
        abs(current - former) > CONTINUATION_TOLERANCE
        for current, former in zip(grid["columns"], previous["columns"])
    ):
        return
    donor = next(
        (row["headers"] for row in reversed(previous["rows"]) if any(row["headers"])),
        None,
    )
    if donor is None:
        return
    for row in grid["rows"]:
        if not any(row["headers"]):
            row["headers"] = donor
    if not any(grid["headers"]):
        grid["headers"] = donor


def build(pdf_path: Path, out_path: Path, file_id: str) -> tuple[int, int]:
    pages = grids = 0
    rows: list[dict] = []
    previous: dict | None = None
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages += 1
            g = page_grid(page, file_id)
            if g:
                grids += 1
                inherit_headers(g, previous)
                rows.extend(grid_rows(g))
                previous = g
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
