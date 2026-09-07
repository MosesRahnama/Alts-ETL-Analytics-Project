"""Corpus-wide census of printed field labels across the rendered TXT corpus.

The family surveys read a stratified sample in depth. This pass reads every
rendered document shallowly and counts how many carry each printed label, so
every field in the round schema can state a prevalence measured on the whole
corpus instead of on a sample.

    python -m src.catalog.census_field_labels

Writes `ledgers/analysis/field_label_census.csv`, one row per label.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TXT_DIR = PROJECT_ROOT / "data" / "documents" / "txt"
MANIFEST = TXT_DIR / "MANIFEST.csv"
CSV_OUT = PROJECT_ROOT / "ledgers" / "analysis" / "field_label_census.csv"

CSV_HEADER = [
    "field", "group", "channel_hint", "files_with_label", "share_of_corpus",
    "total_occurrences", "top_doc_types", "example_file_id", "example_line",
]

# (field, group, channel_hint, regex)
from src.common import matrices

CENSUS = "field-label-census"


LABELS: list[tuple[str, str, str, str]] = [
    (row["input_value"], row["group"], row["channel"], row["output_value"])
    for row in matrices.load(CENSUS)
]


def main() -> int:
    with MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    compiled = [(f, g, c, re.compile(p)) for f, g, c, p in LABELS]

    files = 0
    hits: dict[str, int] = defaultdict(int)
    occurrences: dict[str, int] = defaultdict(int)
    doc_types: dict[str, defaultdict[str, int]] = {f: defaultdict(int) for f, _g, _c, _p in LABELS}
    examples: dict[str, tuple[str, str]] = {}

    for row in manifest:
        path = TXT_DIR / row["txt_filename"]
        if not row["txt_filename"] or not path.exists():
            continue
        files += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        for field, _group, _channel, pattern in compiled:
            found = pattern.findall(text)
            if not found:
                continue
            hits[field] += 1
            occurrences[field] += len(found)
            doc_types[field][row["doc_type"]] += 1
            if field not in examples:
                match = pattern.search(text)
                start = max(0, match.start() - 70)
                snippet = " ".join(text[start:match.end() + 70].split())[:180]
                examples[field] = (row["file_id"], snippet)

    rows = []
    for field, group, channel, _pattern in LABELS:
        top = sorted(doc_types[field].items(), key=lambda kv: -kv[1])[:3]
        file_id, line = examples.get(field, ("", ""))
        rows.append({
            "field": field,
            "group": group,
            "channel_hint": channel,
            "files_with_label": hits[field],
            "share_of_corpus": f"{100 * hits[field] / max(files, 1):.1f}%",
            "total_occurrences": occurrences[field],
            "top_doc_types": "; ".join(f"{k}={v}" for k, v in top),
            "example_file_id": file_id,
            "example_line": line,
        })
    rows.sort(key=lambda r: (r["group"], -r["files_with_label"]))

    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"censused {files} documents across {len(LABELS)} labels")
    print(f"wrote {CSV_OUT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
