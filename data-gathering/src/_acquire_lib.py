"""
Shared acquisition and PDF layout-probe helpers for Agent A1 corpus gathering.
Used by every gathering sub-agent so measurements are consistent across the corpus.
Every corpus path resolves under CORPUS_ROOT.

CLI usage:
    python _acquire_lib.py download <url> <dest_path> [--timeout 60]
    python _acquire_lib.py verify <path>
    python _acquire_lib.py probe <path>
    python _acquire_lib.py hash <path>
    python _acquire_lib.py full <path>      # verify + probe + hash in one JSON blob
"""
import sys
import os
import json
import hashlib
import argparse

# This file lives at <repo>/data-gathering/src/.
DATA_GATHERING_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(DATA_GATHERING_ROOT)
CORPUS_ROOT = os.path.join(PROJECT_ROOT, "data", "documents", "pdf")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest_path, timeout=60):
    import requests
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    with requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True) as r:
        status = r.status_code
        if status != 200:
            return {"ok": False, "http_status": status, "error": f"HTTP {status}"}
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    return {"ok": True, "http_status": status}


def verify_file(path):
    """Size + magic byte checks. Returns dict."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(8)
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    magic_ok = False
    if ext == "pdf":
        magic_ok = head.startswith(b"%PDF")
    elif ext in ("xlsx", "zip", "docx"):
        magic_ok = head.startswith(b"PK")
    elif ext == "csv":
        magic_ok = True  # CSV lacks reliable magic bytes
    else:
        magic_ok = True
    return {
        "file_size_bytes": size,
        "size_ok": size > 20 * 1024,
        "magic_ok": magic_ok,
        "ext": ext,
    }


def probe_pdf(path, sample_pages=6):
    """Section 7 step 4 layout probe. Returns dict whose values are measured from the file."""
    import pdfplumber

    page_count = 0
    char_count_sample = 0
    n_tables_detected = 0
    max_table_cols = 0
    has_landscape_page = False

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        if page_count <= sample_pages:
            sample_idx = list(range(page_count))
        else:
            # spread the sample across the whole document
            step = page_count / float(sample_pages)
            sample_idx = sorted(set(int(i * step) for i in range(sample_pages)))

        for i in sample_idx:
            page = pdf.pages[i]
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            char_count_sample += len(text)

            if page.width > page.height:
                has_landscape_page = True

            try:
                tables = page.extract_tables()
            except Exception:
                tables = []
            n_tables_detected += len(tables)
            for t in tables:
                if t:
                    ncols = max((len(row) for row in t if row), default=0)
                    max_table_cols = max(max_table_cols, ncols)

    has_text_layer = char_count_sample >= 200

    return {
        "page_count": page_count,
        "char_count_sample": char_count_sample,
        "has_text_layer": has_text_layer,
        "n_tables_detected": n_tables_detected,
        "max_table_cols": max_table_cols,
        "has_landscape_page": has_landscape_page,
    }


def full_report(path):
    out = {"path": path}
    out.update(verify_file(path))
    out["sha256"] = sha256_file(path)
    ext = out["ext"]
    if ext == "pdf":
        try:
            out.update(probe_pdf(path))
        except Exception as e:
            out["probe_error"] = str(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["download", "verify", "probe", "hash", "full"])
    ap.add_argument("arg1")
    ap.add_argument("arg2", nargs="?")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    if args.cmd == "download":
        result = download(args.arg1, args.arg2, timeout=args.timeout)
    elif args.cmd == "verify":
        result = verify_file(args.arg1)
    elif args.cmd == "probe":
        result = probe_pdf(args.arg1)
    elif args.cmd == "hash":
        result = {"sha256": sha256_file(args.arg1)}
    elif args.cmd == "full":
        result = full_report(args.arg1)
    else:
        raise SystemExit(2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
