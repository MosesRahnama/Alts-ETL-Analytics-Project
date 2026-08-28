"""Sweep the TXT corpus for the printed loci that license a `manager` value.

Round 01 accepts a manager name only when the source names an organization as
the manager, general partner, or adviser *of that fund*, in words that say so.
This sweep finds and classifies those printed loci across every rendered page so
the question "is the manager printed at all?" is answered from the corpus rather
than from impression. It is a discovery aid: a hit is a candidate locus for a
reader to confirm, never an accepted manager.

    python -m src.catalog.sweep_manager_loci
    python -m src.catalog.sweep_manager_loci --only SRC101 SRC102

Writes `ledgers/analysis/manager_locus_sweep.csv`, one row per locus, and
prints the locus counts by class and document type.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_LEDGER = PROJECT_ROOT / "data-gathering" / "source_ledger.csv"
TXT_DIR = PROJECT_ROOT / "data" / "documents" / "txt"
FUND_MAP = PROJECT_ROOT / "data" / "csv" / "document_fund_map.csv"
CSV_OUT = PROJECT_ROOT / "ledgers" / "analysis" / "manager_locus_sweep.csv"

CSV_HEADER = [
    "source", "file_id", "doc_type", "issuer_type", "page", "locus_class",
    "trigger", "candidate_manager", "quote", "already_mapped_manager",
]

# The name that follows a locus, stopped at a legal or vehicle suffix.
SUFFIX = (
    r"(?:L\.?P\.?|LLP|L\.?L\.?P\.?|LLC|L\.?L\.?C\.?|Inc\.?|Incorporated|Corp\.?|"
    r"Corporation|Company|Co\.?|Ltd\.?|Limited|PLC|GmbH|N\.?V\.?|B\.?V\.?|S\.?A\.?|"
    r"S\.?a\.?r\.?l\.?|SCSp|SICAV|AG|Partners|Partnership|Management|Advisors|"
    r"Advisers|Capital|Group|Holdings|Trust|Associates|Ventures)"
)
NAME = r"[A-Z][A-Za-z&.,'\-/ ]{2,80}?"

LABELS = [
    "General Partner", "Managing General Partner", "Investment Manager",
    "Investment Adviser", "Investment Advisor", "Management Company",
    "Fund Manager", "Manager", "Adviser", "Advisor", "Sponsor",
    "Managing Member", "Investment Management Company", "AIFM",
]

PATTERNS: list[tuple[str, str, re.Pattern[str]]] = []

for label in LABELS:
    PATTERNS.append((
        "printed_label",
        label,
        re.compile(rf"\b{re.escape(label)}\s*[:–-]\s+({NAME}{SUFFIX})", re.M),
    ))

PATTERNS += [
    ("managed_by", "is managed by", re.compile(
        rf"\b(?:is|are|was|were|being)\s+(?:externally\s+|internally\s+)?managed\s+by\s+({NAME}{SUFFIX})")),
    ("managed_by", "managed and advised by", re.compile(
        rf"\bmanaged\s+and\s+advised\s+by\s+({NAME}{SUFFIX})")),
    ("advised_by", "is advised by", re.compile(
        rf"\b(?:is|are|was|were)\s+advised\s+by\s+({NAME}{SUFFIX})")),
    ("serves_as", "serves as the general partner", re.compile(
        rf"({NAME}{SUFFIX})\s*,?\s+(?:serves|acts|acted|served)\s+as\s+(?:the\s+)?"
        r"(?:general partner|managing general partner|investment manager|"
        r"investment adviser|investment advisor|manager|adviser|advisor|sponsor)")),
    ("serves_as", "the general partner of the fund is", re.compile(
        r"\b(?:the\s+)?(?:general partner|investment manager|investment adviser|"
        rf"management company|fund manager)\s+(?:of|to)\s+the\s+\w+\s+is\s+({NAME}{SUFFIX})")),
    ("defined_term", '(the "Manager")', re.compile(
        rf"({NAME}{SUFFIX})\s*[\(\[]\s*(?:the\s+)?[\"“]?(?:the\s+)?"
        r"(?:Manager|Adviser|Advisor|Investment Manager|Investment Adviser|"
        r"General Partner|Fund Manager|Management Company|Sponsor)"
        r"[\"”]?\s*[\)\]]")),
    ("provides_services", "provides investment management services to", re.compile(
        rf"({NAME}{SUFFIX})\s+provides\s+(?:investment\s+)?(?:management|advisory)"
        r"[A-Za-z, ]{0,60}?\s+(?:services\s+)?to\s+the\s+\w+")),
]

PAGE_RE = re.compile(r"^===== (\S+) PAGE (\d+) of \d+ \| chars \d+ \| text (\w+) =====$", re.M)

NOISE = re.compile(
    r"^(?:The|This|Such|Its|Their|Our|A|An|Any|Each|All|Other|Same|These|Those|"
    r"No|New|If|When|Where|Whether|That|Which|But|And|For|With|From|Under|Section)\b",
)

# A capture that runs across a clause is a regex artefact, not a name.
CLAUSE = re.compile(
    r"\b(?:is|are|was|were|be|been|by|to the|of the|in the|for the|that|which|"
    r"shall|may|will|and the|or the|with respect)\b",
    re.I,
)

# A locus can print a role word where a name belongs; those are not managers.
GENERIC = {
    "COMPANY", "FUND", "THE FUND", "PARTNERSHIP", "GENERAL PARTNER", "MANAGER",
    "ADVISER", "ADVISOR", "INVESTMENT MANAGER", "INVESTMENT ADVISER",
    "INVESTMENT ADVISOR", "MANAGEMENT COMPANY", "MANAGEMENT", "PARTNERS",
    "CAPITAL", "GROUP", "TRUST", "LIMITED", "LIMITED PARTNERSHIP", "SPONSOR",
    "ASSETS UNDER MANAGEMENT", "FUND MANAGER", "MANAGING MEMBER", "ADVISORS",
    "ADVISERS", "INVESTMENT MANAGEMENT COMPANY", "GENERAL PARTNERS",
    "MANAGING GENERAL PARTNER", "PORTFOLIO COMPANY", "INVESTMENT COMPANY",
}

MAX_NAME_WORDS = 9


def pages_of(text: str) -> list[tuple[int, str, str]]:
    """Split a rendered TXT file into (page_number, text_source, page_text)."""
    marks = list(PAGE_RE.finditer(text))
    out: list[tuple[int, str, str]] = []
    for index, mark in enumerate(marks):
        start = mark.end()
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        body = text[start:end].strip("=\n ")
        out.append((int(mark.group(2)), mark.group(3), body))
    return out


def clean(candidate: str) -> str:
    value = " ".join(candidate.split()).strip(" ,;:-")
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.I)
    return value


def plausible(candidate: str) -> bool:
    """Reject role words, clause fragments, and runaway captures."""
    if len(candidate) < 4 or NOISE.match(candidate):
        return False
    if candidate.upper().rstrip(".,") in GENERIC:
        return False
    if CLAUSE.search(candidate):
        return False
    if len(candidate.split()) > MAX_NAME_WORDS:
        return False
    return any(character.isupper() for character in candidate)


def span_for(page_text: str, match: re.Match[str], width: int = 320) -> str:
    start = max(0, match.start() - 60)
    end = min(len(page_text), match.end() + width - (match.end() - match.start()))
    return " ".join(page_text[start:end].split())[:380]


def sweep_file(file_id: str, txt_path: Path) -> list[dict[str, str]]:
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    found: list[dict[str, str]] = []
    seen: set[tuple[int, str, str]] = set()
    for page_number, _source, body in pages_of(text):
        flat = " ".join(body.split())
        for locus_class, trigger, pattern in PATTERNS:
            for match in pattern.finditer(flat):
                candidate = clean(match.group(1))
                if not plausible(candidate):
                    continue
                key = (page_number, locus_class, candidate.upper())
                if key in seen:
                    continue
                seen.add(key)
                found.append({
                    "file_id": file_id,
                    "page": str(page_number),
                    "locus_class": locus_class,
                    "trigger": trigger,
                    "candidate_manager": candidate,
                    "quote": span_for(flat, match),
                })
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args(argv)

    with SOURCE_LEDGER.open("r", encoding="utf-8-sig", newline="") as handle:
        ledger = {row["file_id"]: row for row in csv.DictReader(handle) if row["file_ext"] == "pdf"}
    mapped: dict[str, set[str]] = defaultdict(set)
    if FUND_MAP.exists():
        with FUND_MAP.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["fund_manager_raw"].strip():
                    mapped[row["file_id"]].add(row["fund_manager_raw"].strip())

    targets = sorted(args.only) if args.only else sorted(ledger)
    rows: list[dict[str, str]] = []
    rendered = 0
    missing: list[str] = []
    for file_id in targets:
        source = ledger.get(file_id)
        if source is None:
            continue
        txt_path = TXT_DIR / (Path(source["filename"]).stem + ".txt")
        if not txt_path.exists():
            missing.append(file_id)
            continue
        rendered += 1
        for hit in sweep_file(file_id, txt_path):
            hit.update({
                "source": source["filename"],
                "doc_type": source["doc_type"],
                "issuer_type": source["issuer_type"],
                "already_mapped_manager": " | ".join(sorted(mapped.get(file_id, ()))),
            })
            rows.append(hit)

    rows.sort(key=lambda r: (r["file_id"], int(r["page"]), r["locus_class"]))
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    files_with = {row["file_id"] for row in rows}
    by_class = Counter(row["locus_class"] for row in rows)
    by_doc_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for file_id in targets:
        source = ledger.get(file_id)
        if source is None or file_id in missing:
            continue
        bucket = by_doc_type[source["doc_type"]]
        bucket[1] += 1
        if file_id in files_with:
            bucket[0] += 1

    print(f"swept {rendered} of {len(targets)} files | {len(rows)} loci | {len(files_with)} files with a locus")
    for name, count in by_class.most_common():
        files = len({row["file_id"] for row in rows if row["locus_class"] == name})
        print(f"  {name}: {count} loci in {files} files")
    for doc_type in sorted(by_doc_type, key=lambda k: -by_doc_type[k][1]):
        hit, total = by_doc_type[doc_type]
        print(f"  {doc_type}: {hit} of {total} swept files carry a locus")
    if missing:
        print(f"  not rendered to TXT: {len(missing)} files")
    print(f"wrote {CSV_OUT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
