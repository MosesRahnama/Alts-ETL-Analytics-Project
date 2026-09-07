"""Merge a JSON rows file into data-gathering/source_ledger.csv.

Usage: python _merge_rows.py <rows.json> [<rows2.json> ...]

Accepts either {"rows": [...]} or a bare [...] list. Skips any row whose
sha256 or filename already exists in the ledger. Verifies every kept row's
file exists on disk with a matching hash, and re-probes any PDF with a
missing probe value so gate 9 (every value measured from the file) always holds.
"""
import csv
from datetime import date
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _acquire_lib import full_report  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # <repo>/data-gathering
PROJECT_ROOT = os.path.dirname(_ROOT)
LEDGER = os.path.join(_ROOT, "source_ledger.csv")
DOCUMENT_TYPES = os.path.join(_ROOT, "document-types.csv")
CORPUS = os.path.join(PROJECT_ROOT, "data", "documents", "pdf")

# fund_type, jurisdiction, and strategy were gatherer labels applied during
# acquisition, not values any report printed. Extraction harvests strategy and
# geography at observation and fund grain from the documents themselves, so the
# ledger carries acquisition facts only.
COLUMNS = [
    "file_id", "filename", "doc_type", "tier", "issuer", "issuer_type",
    "period_covered", "source_url", "retrieved_at", "file_ext",
    "file_size_bytes", "page_count", "has_text_layer", "char_count_sample",
    "n_tables_detected", "max_table_cols", "has_landscape_page", "layout_features",
    "sha256", "is_redacted", "expected_fields", "license_note", "notes",
    "report_subtype", "wave",
]

VALID_TIERS = {"A", "B", "C", "D"}
VALID_EXTENSIONS = {"pdf"}
VALID_LICENSE_NOTES = {
    "public_filing", "freely_published", "foia_release", "public_domain", "model_template"
}


def valid_doc_types():
    with open(DOCUMENT_TYPES, newline="", encoding="utf-8-sig") as handle:
        return {
            (row.get("doc_type") or "").strip()
            for row in csv.DictReader(handle)
            if (row.get("doc_type") or "").strip()
        }


def fmt_bool(v):
    if v is True:
        return "TRUE"
    if v is False:
        return "FALSE"
    if isinstance(v, str) and v.upper() in ("TRUE", "FALSE"):
        return v.upper()
    return ""


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("rows", [])
    return data


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: _merge_rows.py <rows.json> [...]")

    allowed_doc_types = valid_doc_types()
    with open(LEDGER, newline="", encoding="utf-8") as f:
        existing = list(csv.DictReader(f))
    seen_sha = {r["sha256"] for r in existing}
    seen_fn = {r["filename"] for r in existing}
    next_id = max(int(r["file_id"][3:]) for r in existing) + 1

    added, skipped, problems = [], [], []

    for path in sys.argv[1:]:
        for r in load_rows(path):
            fn = r.get("filename", "")
            p = os.path.join(CORPUS, fn)
            retrieved_at = str(r.get("retrieved_at", "")).strip()

            if not fn or not r.get("source_url") or not r.get("sha256") or not retrieved_at:
                problems.append((fn or "<blank>", "incomplete row"))
                continue
            try:
                date.fromisoformat(retrieved_at)
            except ValueError:
                problems.append((fn, f"bad retrieved_at {retrieved_at!r}; expected YYYY-MM-DD"))
                continue
            if r["sha256"] in seen_sha:
                skipped.append((fn, "duplicate sha256"))
                continue
            if fn in seen_fn:
                skipped.append((fn, "duplicate filename"))
                continue
            if not os.path.isfile(p):
                problems.append((fn, "file missing from disk"))
                continue

            probe = full_report(p)
            if probe["sha256"] != r["sha256"]:
                problems.append((fn, "sha256 mismatch vs disk"))
                continue
            if probe.get("ext") not in VALID_EXTENSIONS:
                problems.append((fn, f"unsupported file extension {probe.get('ext')!r}"))
                continue
            if not probe.get("size_ok"):
                problems.append((fn, "file is 20 KB or smaller"))
                continue
            if not probe.get("magic_ok"):
                problems.append((fn, "file signature disagrees with its extension"))
                continue
            if probe.get("probe_error"):
                problems.append((fn, f"PDF probe failed: {probe['probe_error']}"))
                continue
            if r.get("doc_type") not in allowed_doc_types:
                problems.append((fn, f"bad doc_type {r.get('doc_type')!r}"))
                continue
            if r.get("tier") not in VALID_TIERS:
                problems.append((fn, f"bad tier {r.get('tier')!r}"))
                continue
            if r.get("license_note") not in VALID_LICENSE_NOTES:
                problems.append((fn, f"bad license_note {r.get('license_note')!r}"))
                continue

            row = {
                "file_id": f"SRC{next_id:03d}",
                "filename": fn,
                "doc_type": r["doc_type"],
                "tier": r["tier"],
                "issuer": r.get("issuer", ""),
                "issuer_type": r.get("issuer_type", "other"),
                "period_covered": r.get("period_covered", ""),
                "source_url": r["source_url"],
                "retrieved_at": retrieved_at,
                "file_ext": probe["ext"],
                "file_size_bytes": probe["file_size_bytes"],
                # probe values always come from the live probe, overriding the agent's claim
                "page_count": probe.get("page_count", ""),
                "has_text_layer": fmt_bool(probe.get("has_text_layer")),
                "char_count_sample": probe.get("char_count_sample", ""),
                "n_tables_detected": probe.get("n_tables_detected", ""),
                "max_table_cols": probe.get("max_table_cols", ""),
                "has_landscape_page": fmt_bool(probe.get("has_landscape_page")),
                "layout_features": r.get("layout_features", ""),
                "sha256": probe["sha256"],
                "is_redacted": fmt_bool(r.get("is_redacted")),
                "expected_fields": r.get("expected_fields", ""),
                "license_note": r["license_note"],
                "notes": r.get("notes", ""),
                "report_subtype": r.get("report_subtype", ""),
            }
            existing.append(row)
            seen_sha.add(row["sha256"])
            seen_fn.add(fn)
            added.append(fn)
            next_id += 1

    with open(LEDGER, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for row in existing:
            row.setdefault("report_subtype", "")
            w.writerow(row)

    print(f"added {len(added)}, skipped {len(skipped)}, problems {len(problems)}")
    for fn, why in skipped:
        print(f"  SKIP    {fn}  ({why})")
    for fn, why in problems:
        print(f"  PROBLEM {fn}  ({why})")
    print(f"ledger now has {len(existing)} rows")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
