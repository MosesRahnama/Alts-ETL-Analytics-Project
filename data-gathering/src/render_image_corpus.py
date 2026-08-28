"""Write one 300 DPI PNG per physical page. Extraction requires those files.

Each PDF gets its own folder under data/documents/images. Each page is rendered from
that page's own crop box and rotation, so mixed sizes and orientations in one
file stay correct. Default is 300 DPI PNG, no alpha. PDFs are processed in
parallel; pages inside one PDF stay sequential. Git tracks MANIFEST.csv. The PNG
files stay on the local machine because 300 DPI pages are large.

    python data-gathering/src/render_image_corpus.py
    python data-gathering/src/render_image_corpus.py --workers 16
    python data-gathering/src/render_image_corpus.py --dpi 300
    python data-gathering/src/render_image_corpus.py --limit 1
    python data-gathering/src/render_image_corpus.py --pdf SRC011-name.pdf
    python data-gathering/src/render_image_corpus.py --published-slice
    python data-gathering/src/render_image_corpus.py --manifest-only

Resume is the default: existing page-NNN.png files are skipped.
`--published-slice` renders only the 29 published extraction documents.
`--manifest-only` writes `data/documents/images/MANIFEST.csv` for those 311
pages without rendering.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
import traceback
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
CORPUS = PROJECT_ROOT / "data" / "documents" / "pdf"
OUT_ROOT = PROJECT_ROOT / "data" / "documents" / "images"
LOG_PATH = OUT_ROOT / "render-log.csv"
MANIFEST_PATH = OUT_ROOT / "MANIFEST.csv"
DIM_DOCUMENT = PROJECT_ROOT / "data" / "extracted" / "tables" / "dim_document.csv"
DIM_PAGE = PROJECT_ROOT / "data" / "extracted" / "tables" / "dim_page.csv"
DEFAULT_DPI = 300
LOG_FIELDS = ["pdf", "folder", "pages", "written", "skipped", "failed", "seconds", "error"]
MANIFEST_FIELDS = [
    "file_id",
    "filename",
    "source_sha256",
    "page_number",
    "dpi",
    "image_path",
    "image_sha256",
    "present",
]


def page_target(folder: Path, number: int) -> Path:
    return folder / f"page-{number:03d}.png"


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def published_pages() -> list[dict[str, str]]:
    documents: dict[str, dict[str, str]] = {}
    with DIM_DOCUMENT.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            documents[row["document_id"]] = row
    pages: list[dict[str, str]] = []
    with DIM_PAGE.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            document = documents[row["document_id"]]
            pages.append(
                {
                    "file_id": row["document_id"],
                    "filename": document["filename"],
                    "source_sha256": document["source_sha256"],
                    "page_number": str(int(float(row["source_page"]))),
                }
            )
    pages.sort(key=lambda item: (item["file_id"], int(item["page_number"])))
    return pages


def write_published_manifest(dpi: int = DEFAULT_DPI) -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for page in published_pages():
        number = int(page["page_number"])
        relative = (
            Path("data") / "documents" / "images" / Path(page["filename"]).stem
            / f"page-{number:03d}.png"
        )
        target = PROJECT_ROOT / relative
        present = target.is_file() and target.stat().st_size > 0
        rows.append(
            {
                "file_id": page["file_id"],
                "filename": page["filename"],
                "source_sha256": page["source_sha256"],
                "page_number": page["page_number"],
                "dpi": str(dpi),
                "image_path": relative.as_posix(),
                "image_sha256": file_sha256(target) if present else "",
                "present": "1" if present else "0",
            }
        )
    with MANIFEST_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def published_pdfs() -> list[Path]:
    names = sorted({page["filename"] for page in published_pages()})
    paths = [CORPUS / name for name in names]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit("missing published PDFs: " + "; ".join(missing[:5]))
    return paths


def render_pdf(pdf_path: Path, out_dir: Path, dpi: int, force: bool) -> dict:
    import fitz

    out_dir.mkdir(parents=True, exist_ok=True)
    written = skipped = failed = 0
    page_count = 0
    errors: list[str] = []

    document = fitz.open(pdf_path)
    try:
        if document.is_encrypted:
            document.authenticate("")
        page_count = document.page_count
        for index in range(page_count):
            number = index + 1
            target = page_target(out_dir, number)
            if target.exists() and target.stat().st_size > 0 and not force:
                skipped += 1
                continue
            try:
                page = document[index]
                pixmap = page.get_pixmap(dpi=dpi, alpha=False, annots=True)
                pixmap.save(target)
                written += 1
            except Exception as exc:
                failed += 1
                errors.append(f"p{number}: {exc}")
    finally:
        document.close()

    return {
        "pdf": pdf_path.name,
        "folder": out_dir.name,
        "pages": page_count,
        "written": written,
        "skipped": skipped,
        "failed": failed,
        "error": " | ".join(errors),
    }


def render_one(job: tuple[str, int, bool]) -> dict:
    pdf_str, dpi, force = job
    pdf_path = Path(pdf_str)
    t0 = time.time()
    try:
        row = render_pdf(pdf_path, OUT_ROOT / pdf_path.stem, dpi, force)
    except Exception:
        row = {
            "pdf": pdf_path.name,
            "folder": pdf_path.stem,
            "pages": 0,
            "written": 0,
            "skipped": 0,
            "failed": 1,
            "error": traceback.format_exc(limit=1).strip().replace("\n", " "),
        }
    row["seconds"] = time.time() - t0
    return row


def append_log(row: dict) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    new_file = not LOG_PATH.exists()
    with LOG_PATH.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS, lineterminator="\n")
        if new_file:
            writer.writeheader()
        writer.writerow(
            {
                "pdf": row["pdf"],
                "folder": row["folder"],
                "pages": row["pages"],
                "written": row["written"],
                "skipped": row["skipped"],
                "failed": row["failed"],
                "seconds": f"{row['seconds']:.1f}",
                "error": row["error"],
            }
        )


def default_workers() -> int:
    cpus = os.cpu_count() or 4
    return max(1, cpus - 2)


def record_result(row: dict, index: int, total: int, totals: dict) -> None:
    append_log(row)
    totals["written"] += row["written"]
    totals["skipped"] += row["skipped"]
    totals["failed"] += row["failed"]
    if row["failed"] or row["error"]:
        totals["files_fail"] += 1
    else:
        totals["files_ok"] += 1
    print(
        f"[{index}/{total}] {row['pdf']} pages {row['pages']} "
        f"wrote {row['written']} skip {row['skipped']} fail {row['failed']} "
        f"{row['seconds']:.1f}s",
        flush=True,
    )
    if row["error"]:
        print(f"  ERROR {row['error']}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--force", action="store_true", help="re-render pages that already exist")
    parser.add_argument("--limit", type=int, default=0, help="stop after N PDFs (0 means all)")
    parser.add_argument("--pdf", help="render one PDF filename instead of the whole corpus")
    parser.add_argument(
        "--published-slice",
        action="store_true",
        help="render only the 29 published extraction documents",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="write the published-slice image manifest without rendering",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=default_workers(),
        help="parallel PDF processes (default is CPU count minus 2)",
    )
    args = parser.parse_args(argv)
    warnings.filterwarnings("ignore")

    if args.manifest_only:
        count = write_published_manifest(args.dpi)
        print(f"wrote {MANIFEST_PATH} rows {count} dpi {args.dpi}", flush=True)
        return 0

    if args.pdf:
        pdfs = [CORPUS / args.pdf]
        if not pdfs[0].is_file():
            raise SystemExit(f"not a file: {pdfs[0]}")
    elif args.published_slice:
        pdfs = published_pdfs()
    else:
        pdfs = sorted(CORPUS.glob("*.pdf"))
        if args.limit:
            pdfs = pdfs[: args.limit]

    workers = max(1, min(args.workers, len(pdfs)))
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"PDFs {len(pdfs)} dpi {args.dpi} workers {workers} out {OUT_ROOT}", flush=True)

    totals = {"written": 0, "skipped": 0, "failed": 0, "files_ok": 0, "files_fail": 0}
    started = time.time()
    jobs = [(str(path), args.dpi, args.force) for path in pdfs]

    if workers == 1:
        for i, job in enumerate(jobs, 1):
            record_result(render_one(job), i, len(jobs), totals)
    else:
        done = 0
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(render_one, job) for job in jobs]
            for future in as_completed(futures):
                done += 1
                record_result(future.result(), done, len(jobs), totals)

    print(
        f"done files_ok {totals['files_ok']} files_fail {totals['files_fail']} "
        f"wrote {totals['written']} skipped {totals['skipped']} failed {totals['failed']} "
        f"{time.time() - started:.1f}s",
        flush=True,
    )
    if args.published_slice:
        count = write_published_manifest(args.dpi)
        print(f"wrote {MANIFEST_PATH} rows {count} dpi {args.dpi}", flush=True)
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    sys.exit(main())
