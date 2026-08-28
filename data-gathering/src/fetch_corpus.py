"""Re-fetch the PDF corpus from data-gathering/source_ledger.csv.

Every ledger file lands in data/documents/pdf/ and is checked against its SHA-256.

Usage:
    python fetch_corpus.py               # download everything missing or hash-mismatched
    python fetch_corpus.py --dry-run     # print the full file list and planned actions; skips the network
    python fetch_corpus.py --timeout 90  # per-file timeout in seconds (default 60)
"""
import argparse
import csv
import hashlib
import os
import sys
import time

# this file lives at <repo>/data-gathering/src/, so two levels up is data-gathering/
DATA_GATHERING_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(DATA_GATHERING_ROOT)
LEDGER_PATH = os.path.join(DATA_GATHERING_ROOT, "source_ledger.csv")
CORPUS_ROOT = os.path.join(PROJECT_ROOT, "data", "documents", "pdf")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_ledger():
    if not os.path.isfile(LEDGER_PATH):
        print(f"ERROR: missing ledger at {LEDGER_PATH}", file=sys.stderr)
        sys.exit(2)
    with open(LEDGER_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def already_present_and_matching(dest_path, expected_sha256):
    if not os.path.isfile(dest_path):
        return False
    try:
        return sha256_file(dest_path) == expected_sha256
    except OSError:
        return False


def fetch_one(row, timeout, dry_run):
    filename = row["filename"]
    url = row["source_url"]
    expected_sha256 = row["sha256"]
    dest_path = os.path.join(CORPUS_ROOT, filename)

    if already_present_and_matching(dest_path, expected_sha256):
        return "skipped"

    if dry_run:
        return "would_fetch"

    import requests

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        with requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True) as r:
            if r.status_code != 200:
                return "http_error"
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            tmp_path = dest_path + ".part"
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
    except requests.RequestException:
        return "http_error"

    actual_sha256 = sha256_file(tmp_path)
    if actual_sha256 != expected_sha256:
        os.replace(tmp_path, dest_path + ".hash_mismatch")
        return "hash_mismatch"

    os.replace(tmp_path, dest_path)
    return "ok"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the plan and skip every network call")
    ap.add_argument("--timeout", type=int, default=60, help="per-file timeout in seconds")
    args = ap.parse_args()

    rows = load_ledger()
    print(f"Ledger: {LEDGER_PATH} ({len(rows)} rows)")
    print(f"Corpus root: {CORPUS_ROOT}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}\n")

    counts = {
        "ok": 0,
        "hash_mismatch": 0,
        "http_error": 0,
        "incomplete": 0,
        "skipped": 0,
        "would_fetch": 0,
    }

    for i, row in enumerate(rows, start=1):
        filename = row.get("filename", "").strip()
        url = row.get("source_url", "").strip()
        expected_sha256 = row.get("sha256", "").strip()
        if not filename or not url or not expected_sha256:
            counts["incomplete"] += 1
            print(f"[{i}/{len(rows)}] ERROR: incomplete row (filename, source_url, or sha256 missing)")
            continue

        status = fetch_one(row, args.timeout, args.dry_run)
        counts[status] = counts.get(status, 0) + 1
        print(f"[{i}/{len(rows)}] {status:>13}  {filename}")

        if not args.dry_run and status == "ok":
            time.sleep(0.2)  # light rate limiting across many hosts

    print("\n--- fetch_corpus.py report ---")
    for key in ("ok", "hash_mismatch", "http_error", "incomplete", "skipped", "would_fetch"):
        print(f"{key:>13}: {counts.get(key, 0)}")
    return 1 if counts["hash_mismatch"] or counts["http_error"] or counts["incomplete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
