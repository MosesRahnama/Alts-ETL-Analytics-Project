"""Render every corpus PDF to a page-marked TXT companion.

The text is `pdfplumber.Page.extract_text()` per physical page, with the RapidOCR
fallback on a page that carries no text layer. Line breaks are kept so a human
or an agent can read the page; the evidence matcher tokenises on `[a-z0-9]+`, so
whitespace never changes whether a quote validates.

    python -m src.catalog.build_txt_corpus
    python -m src.catalog.build_txt_corpus --only SRC101 SRC102 --force
    python -m src.catalog.build_txt_corpus --workers 8 --no-ocr

Output lands in `data/documents/txt/` as `<pdf stem>.txt`, one
block per physical page, plus `MANIFEST.csv` describing the run.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_LEDGER = PROJECT_ROOT / "data-gathering" / "source_ledger.csv"
CORPUS_DIR = PROJECT_ROOT / "data" / "documents" / "pdf"
TXT_DIR = PROJECT_ROOT / "data" / "documents" / "txt"
MANIFEST_PATH = TXT_DIR / "MANIFEST.csv"

MANIFEST_HEADER = [
    "file_id", "filename", "txt_filename", "doc_type", "pages",
    "native_pages", "ocr_pages", "empty_pages", "chars", "seconds", "error",
]

PAGE_RULE = "=" * 78


def _quiet() -> None:
    """pdfminer narrates malformed colour operators on many corpus files."""
    warnings.filterwarnings("ignore")
    for name in ("pdfminer", "pdfplumber", "pypdf", "PIL"):
        logging.getLogger(name).setLevel(logging.ERROR)


_OCR_ENGINE = None


def squash(text: str) -> str:
    """Collapse whitespace, which is what makes a quote comparable to a page."""
    return " ".join((text or "").split())


# Control characters a PDF text layer can emit that carry no printed meaning:
# the C0 set apart from tab, newline, and carriage return, DEL, and the C1 set.
# A quote copied off the page cannot reproduce them, so a page holding one
# refuses its own evidence at the quote gate. Tab, newline, and return stay.
CONTROL_CHARACTERS = {
    chr(code)
    for code in list(range(0x00, 0x20)) + [0x7F] + list(range(0x80, 0xA0))
    if chr(code) not in "\t\n\r"
}
CONTROL_TABLE = {ord(character): None for character in CONTROL_CHARACTERS}


def sanitize_page_text(text: str) -> tuple[str, int, int, int]:
    """Drop control characters that no quote can reproduce. Count what was
    dropped, separating NUL from the rest, and count the Unicode replacement
    characters that remain, which stand for a glyph the encoding lost."""

    raw = text or ""
    nuls = raw.count("\x00")
    controls = sum(raw.count(character) for character in CONTROL_CHARACTERS) - nuls
    cleaned = raw.translate(CONTROL_TABLE)
    return cleaned, nuls, controls, cleaned.count("\ufffd")


def _ocr_pdf_page(source: Path, page_index: int) -> str | None:
    """Read one textless page from its render."""
    global _OCR_ENGINE
    import numpy as np
    import pypdfium2
    from rapidocr_onnxruntime import RapidOCR

    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR(
            print_verbose=False, text_score=0.5, use_angle_cls=True,
            use_text_det=True, min_height=30, width_height_ratio=8,
        )
    document = pypdfium2.PdfDocument(source)
    page = document[page_index]
    bitmap = None
    try:
        bitmap = page.render(scale=200 / 72, optimize_mode="print", draw_annots=True)
        image = np.ascontiguousarray(bitmap.to_numpy())
        if image.ndim == 3 and image.shape[2] == 4:
            image = np.ascontiguousarray(image[:, :, :3])
        results, _elapsed = _OCR_ENGINE(
            image, box_thresh=0.5, unclip_ratio=1.6, text_score=0.5
        )
        return squash(" ".join(str(item[1]) for item in (results or []))) or None
    finally:
        if bitmap is not None:
            bitmap.close()
        page.close()
        document.close()


def render_pdf(path: Path, use_ocr: bool = True) -> tuple[list[tuple[str, str]], str]:
    """Return ([(page_text, source_tag), ...], error) for one PDF."""
    _quiet()
    import pdfplumber

    pages: list[tuple[str, str]] = []
    try:
        with pdfplumber.open(path) as pdf:
            page_count = len(pdf.pages)
            for index in range(page_count):
                try:
                    raw = pdf.pages[index].extract_text() or ""
                except Exception as exc:  # one bad page must not lose the file
                    pages.append((f"[page extraction failed: {exc}]", "error"))
                    continue
                if squash(raw):
                    pages.append((raw, "native"))
                else:
                    pages.append(("", "empty"))
                try:
                    pdf.pages[index].close()
                except Exception:
                    pass
    except Exception as exc:
        return pages, f"{type(exc).__name__}: {exc}"

    if use_ocr and any(tag == "empty" for _text, tag in pages):
        for index, (_text, tag) in enumerate(pages):
            if tag != "empty":
                continue
            try:
                recovered = _ocr_pdf_page(path, index)
            except Exception as exc:
                pages[index] = (f"[ocr failed: {exc}]", "error")
                continue
            if recovered:
                pages[index] = (recovered, "ocr")
    return pages, ""


def write_txt(
    destination: Path,
    source: dict[str, str],
    pages: list[tuple[str, str]],
    error: str,
) -> dict[str, int]:
    counts = {"native": 0, "ocr": 0, "empty": 0, "error": 0, "nuls": 0, "controls": 0, "fffd": 0, "chars": 0}
    body: list[str] = []
    for number, (text, tag) in enumerate(pages, start=1):
        text, nuls, controls, fffd = sanitize_page_text(text)
        counts[tag] = counts.get(tag, 0) + 1
        counts["nuls"] += nuls
        counts["controls"] += controls
        counts["fffd"] += fffd
        counts["chars"] += len(text)
        body.append(
            f"{PAGE_RULE}\n"
            f"===== {source['file_id']} PAGE {number} of {len(pages)} "
            f"| chars {len(text)} | text {tag} =====\n"
            f"{PAGE_RULE}"
        )
        body.append(text if text else "[no text layer and no OCR output on this page]")
        body.append("")

    header = [
        f"# file_id: {source['file_id']}",
        f"# filename: {source['filename']}",
        f"# doc_type: {source.get('doc_type', '')}",
        f"# issuer: {source.get('issuer', '')}",
        f"# sha256: {source.get('sha256', '')}",
        f"# pages: {len(pages)}",
        f"# native_text_pages: {counts['native']}"
        f" | ocr_pages: {counts['ocr']}"
        f" | pages_with_no_text: {counts['empty']}"
        f" | failed_pages: {counts['error']}",
        "# extractor: pdfplumber.Page.extract_text(), RapidOCR fallback on a textless page",
        "# fidelity: whitespace-squashed the same way the reader was, so a quote copied",
        "#           from here validates against the PDF page of the same number",
        "# location contract: the PAGE number below is the physical PDF page number",
        f"# nul_bytes_stripped: {counts['nuls']}",
        f"# control_chars_stripped: {counts['controls']}",
        f"# replacement_chars_remaining: {counts['fffd']}",
    ]
    if error:
        header.append(f"# error: {error}")
    header.append("")

    destination.write_text("\n".join(header) + "\n".join(body), encoding="utf-8")
    return counts


def convert_one(source: dict[str, str], use_ocr: bool) -> dict[str, str]:
    started = time.time()
    pdf_path = CORPUS_DIR / source["filename"]
    txt_path = TXT_DIR / (Path(source["filename"]).stem + ".txt")
    if not pdf_path.exists():
        return {
            "file_id": source["file_id"], "filename": source["filename"],
            "txt_filename": "", "doc_type": source.get("doc_type", ""),
            "pages": "0", "native_pages": "0", "ocr_pages": "0",
            "empty_pages": "0", "chars": "0", "seconds": "0",
            "error": "source PDF is missing from the corpus",
        }
    pages, error = render_pdf(pdf_path, use_ocr=use_ocr)
    counts = write_txt(txt_path, source, pages, error)
    return {
        "file_id": source["file_id"],
        "filename": source["filename"],
        "txt_filename": txt_path.name,
        "doc_type": source.get("doc_type", ""),
        "pages": str(len(pages)),
        "native_pages": str(counts["native"]),
        "ocr_pages": str(counts["ocr"]),
        "empty_pages": str(counts["empty"]),
        "chars": str(counts["chars"]),
        "seconds": f"{time.time() - started:.1f}",
        "error": error,
    }


def _worker(payload: tuple[dict[str, str], bool]) -> dict[str, str]:
    source, use_ocr = payload
    sys.path.insert(0, str(PROJECT_ROOT))
    return convert_one(source, use_ocr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    parser.add_argument("--only", nargs="*", default=None, help="file_id values to render")
    parser.add_argument("--force", action="store_true", help="re-render files that already have TXT")
    parser.add_argument("--no-ocr", action="store_true", help="skip the OCR fallback on textless pages")
    args = parser.parse_args(argv)

    TXT_DIR.mkdir(parents=True, exist_ok=True)
    with SOURCE_LEDGER.open("r", encoding="utf-8-sig", newline="") as handle:
        ledger = [row for row in csv.DictReader(handle) if row["file_ext"] == "pdf"]
    ledger = [row for row in ledger if (CORPUS_DIR / row["filename"]).is_file()]
    if args.only:
        wanted = set(args.only)
        ledger = [row for row in ledger if row["file_id"] in wanted]

    pending = []
    for row in ledger:
        txt_path = TXT_DIR / (Path(row["filename"]).stem + ".txt")
        if txt_path.exists() and not args.force:
            continue
        pending.append(row)

    print(f"pdf sources: {len(ledger)} | to render: {len(pending)} | workers: {args.workers}", flush=True)
    results: list[dict[str, str]] = []
    started = time.time()
    if pending:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(_worker, (row, not args.no_ocr)): row["file_id"]
                for row in pending
            }
            for done, future in enumerate(as_completed(futures), start=1):
                record = future.result()
                results.append(record)
                if done % 10 == 0 or done == len(pending):
                    rate = done / max(time.time() - started, 0.1)
                    print(
                        f"  {done}/{len(pending)} rendered"
                        f" | {rate:.2f} files/s"
                        f" | last {record['file_id']} {record['pages']}p"
                        f" ocr={record['ocr_pages']}",
                        flush=True,
                    )

    existing: dict[str, dict[str, str]] = {}
    if MANIFEST_PATH.exists():
        with MANIFEST_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            existing = {row["file_id"]: row for row in csv.DictReader(handle)}
    for record in results:
        existing[record["file_id"]] = record
    with MANIFEST_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows([existing[key] for key in sorted(existing)])

    failures = [row for row in existing.values() if row["error"]]
    empties = sum(int(row["empty_pages"] or 0) for row in existing.values())
    print(
        f"txt corpus: {len(existing)} files"
        f" | {sum(int(r['pages'] or 0) for r in existing.values())} pages"
        f" | {sum(int(r['ocr_pages'] or 0) for r in existing.values())} OCR pages"
        f" | {empties} pages still blank"
        f" | {len(failures)} file errors"
        f" | {time.time() - started:.0f}s",
        flush=True,
    )
    for row in failures[:20]:
        print(f"  ERROR {row['file_id']}: {row['error']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
