"""Parse existing physical-page TXT banners and keep original quotation text."""

from __future__ import annotations

import re
from pathlib import Path

BANNER = re.compile(r"^=====\s+.*?\s+PAGE\s+(\d+)\s+of\s+(\d+)\s+.*?=====$")
PRINTED = re.compile(r"(?:page|p\.)\s+(\d+[A-Za-z]?)\b", re.I)
NOTE_HEAD = re.compile(
    r"^(note|notes|footnote|definition|see note|n\d+\b|\d{1,2}[.)]?\s|\*)",
    re.I,
)
FOOTNOTES_HEAD = re.compile(r"(?im)^\s*footnotes?\s*$")
NUMBERED_FOOTNOTE = re.compile(
    r"(?ms)(?<!\S)(\d{1,2})[.)][^\S\r\n]+(.*?)(?=(?<!\S)\d{1,2}[.)][^\S\r\n]+|\Z)"
)


def parse_pages(path: Path) -> tuple[dict[int, str], int, str]:
    """Return original page text, declared page count, and text state."""

    if not path.is_file():
        return {}, 0, "missing"
    pages: dict[int, list[str]] = {}
    declared = 0
    current: int | None = None
    native = False
    ocr = False
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            match = BANNER.match(line)
            if match:
                current = int(match.group(1))
                declared = int(match.group(2))
                pages.setdefault(current, [])
                if "text native" in line.lower():
                    native = True
                if "ocr" in line.lower():
                    ocr = True
                continue
            if current is not None and not line.startswith("===="):
                pages[current].append(line)
    joined = {page: "\n".join(lines).strip("\n") for page, lines in pages.items()}
    if not joined:
        return {}, declared, "missing"
    state = "native" if native and not ocr else "ocr" if ocr else "native"
    return joined, declared or max(joined), state


def split_paragraphs(text: str, max_chars: int = 1800) -> list[str]:
    chunks: list[str] = []
    for raw_chunk in re.split(r"\n\s*\n", text):
        current: list[str] = []
        for line in raw_chunk.splitlines():
            if NOTE_HEAD.match(line.strip()) and current:
                chunks.append("\n".join(current).strip())
                current = []
            current.append(line)
        if current:
            chunks.append("\n".join(current).strip())
    chunks = [chunk for chunk in chunks if chunk]
    output: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            output.append(chunk)
            continue
        current: list[str] = []
        size = 0
        for line in chunk.splitlines():
            parts = [line[index : index + max_chars] for index in range(0, len(line), max_chars)] or [""]
            for part in parts:
                added = len(part) + (1 if current else 0)
                if current and size + added > max_chars:
                    output.append("\n".join(current).strip())
                    current = []
                    size = 0
                if part:
                    current.append(part)
                    size += len(part) + (1 if size else 0)
        if current:
            output.append("\n".join(current).strip())
    return output


def printed_page_label(text: str) -> str | None:
    match = PRINTED.search(text[:400])
    return match.group(1) if match else None


def is_note_passage(text: str) -> bool:
    first = text.strip().splitlines()[0] if text.strip() else ""
    return bool(NOTE_HEAD.match(first)) or "see note" in text.lower()[:80]


def numbered_footnotes(text: str) -> list[tuple[str, str, int, int]]:
    """Return numbered notes only from a printed Footnotes section."""

    heading = FOOTNOTES_HEAD.search(text)
    if heading is None:
        return []
    # Multi-column PDF text can place later footnotes before the printed heading.
    # Once the page is known to contain that heading, retain numbered notes on both sides.
    segment = text
    rows: list[tuple[str, str, int, int]] = []
    for match in NUMBERED_FOOTNOTE.finditer(segment):
        number = match.group(1)
        note = " ".join(match.group(2).split())
        if not note:
            continue
        start = match.start()
        end = match.end()
        rows.append((number, f"{number}. {note}", start, end))
    return rows
