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
LABELS: list[tuple[str, str, str, str]] = [
    # ---- identity -------------------------------------------------------
    ("fund_legal_name", "identity", "txt", r"\b[A-Z][A-Za-z&.,'\- ]{3,60}(?:Fund|Partners|Partnership|Trust)[A-Za-z0-9 ,.\-]{0,20}(?:L\.?P\.?|LLC|L\.?L\.?C\.?|Ltd|Limited|Inc\.?)\b"),
    ("manager_general_partner", "identity", "txt", r"\bGeneral Partner\b"),
    ("manager_investment_manager", "identity", "txt", r"\bInvestment (?:Manager|Adviser|Advisor)\b"),
    ("manager_managed_by", "identity", "txt", r"\bmanaged by\b"),
    ("lp_name_limited_partner", "identity", "txt", r"\bLimited Partner\b"),
    ("share_class_name", "identity", "txt", r"\bClass\s+[A-Z](?:-\d)?\b"),
    ("portfolio_company_name", "identity", "pdf_table", r"\bPortfolio Compan(?:y|ies)\b"),
    ("fund_domicile", "identity", "txt", r"\b(?:organized|formed|incorporated|domiciled)\s+(?:under|in|pursuant)\b"),
    ("vintage_year", "identity", "both", r"\bVintage\s*(?:Year)?\b"),
    ("strategy", "identity", "both", r"\b(?:Strategy|Asset Class|Sub-?Strategy)\b"),
    ("geography", "identity", "both", r"\b(?:Geograph|Region|Country of|North America|Western Europe|Asia[- ]Pacific)\w*\b"),
    # ---- dates ----------------------------------------------------------
    ("as_of_date", "date", "txt", r"\bas of\s+(?:the\s+)?[A-Z][a-z]+\s+\d{1,2},\s*\d{4}"),
    ("period_end_date", "date", "txt", r"\b(?:quarter|period|year)\s+ended?\s+[A-Z][a-z]+\s+\d{1,2},\s*\d{4}"),
    ("fiscal_year", "date", "txt", r"\bfiscal\s+year\s+(?:ended?|ending)\b"),
    ("report_date", "date", "txt", r"\b(?:dated|Report Date|Statement Date|As At)\b"),
    ("cashflow_due_date", "date", "txt", r"\b(?:due (?:on|by|date)|payment date|wire.{0,12}by)\b"),
    # ---- capital --------------------------------------------------------
    ("commitment", "capital", "pdf_table", r"\b(?:Total )?Commitment\b"),
    ("unfunded_commitment", "capital", "pdf_table", r"\b(?:Unfunded|Remaining|Uncalled)\s+Commitment\b"),
    ("contributions", "capital", "pdf_table", r"\b(?:Contributions?|Paid[- ]in Capital|Capital Called|Drawdowns?)\b"),
    ("distributions", "capital", "pdf_table", r"\bDistributions?\b"),
    ("recallable_distributions", "capital", "pdf_table", r"\bRecallable\b"),
    ("capital_call_amount", "capital", "pdf_table", r"\b(?:Capital Call|Drawdown Notice|Amount Called|Call Amount)\b"),
    # ---- value ----------------------------------------------------------
    ("nav", "value", "pdf_table", r"\b(?:Net Asset Value|NAV)\b"),
    ("nav_per_share", "value", "pdf_table", r"\bNAV per (?:share|unit)\b"),
    ("net_assets", "value", "pdf_table", r"\bNet Assets\b"),
    ("beginning_balance", "value", "pdf_table", r"\b(?:Beginning|Opening)\s+(?:Balance|Capital|NAV)\b"),
    ("ending_balance", "value", "pdf_table", r"\b(?:Ending|Closing)\s+(?:Balance|Capital|NAV)\b"),
    ("fair_value", "value", "pdf_table", r"\bFair Value\b"),
    ("cost_basis", "value", "pdf_table", r"\bCost\b"),
    ("realized_gain", "value", "pdf_table", r"\bRealized\s+(?:Gain|Loss)\b"),
    ("unrealized_gain", "value", "pdf_table", r"\bUnrealized\s+(?:Gain|Loss|Appreciation|Depreciation)\b"),
    ("net_income", "value", "pdf_table", r"\bNet (?:Income|Investment Income)\b"),
    # ---- fees and terms -------------------------------------------------
    ("management_fee", "fee", "pdf_table", r"\bManagement Fee\b"),
    ("carried_interest", "fee", "both", r"\bCarried Interest\b"),
    ("partnership_expenses", "fee", "pdf_table", r"\b(?:Partnership|Fund|Operating)\s+Expenses\b"),
    ("carry_rate", "term", "txt", r"\b(?:carried interest of|carry of|20%\s+of\s+profits|Carry Rate)\b"),
    ("hurdle_rate", "term", "txt", r"\b(?:Hurdle|Preferred Return)\b"),
    ("fund_term_years", "term", "txt", r"\b(?:term of the (?:Fund|Partnership)|Fund Term)\b"),
    ("extension_years", "term", "txt", r"\b(?:extension|extend the term)\b"),
    ("expense_ratio", "fee", "pdf_table", r"\bExpense Ratio\b"),
    # ---- performance ----------------------------------------------------
    ("irr", "performance", "pdf_table", r"\b(?:IRR|Internal Rate of Return)\b"),
    ("tvpi", "performance", "pdf_table", r"\bTVPI\b|\bTotal Value to Paid[- ]?In\b"),
    ("dpi", "performance", "pdf_table", r"\bDPI\b|\bDistributions? to Paid[- ]?In\b"),
    ("rvpi", "performance", "pdf_table", r"\bRVPI\b"),
    ("moic", "performance", "pdf_table", r"\bMOIC\b|\bMultiple of Invested Capital\b|\bMultiple\b"),
    ("period_return", "performance", "pdf_table", r"\b(?:Total Return|Period Return|Return \()"),
    ("benchmark_return", "performance", "pdf_table", r"\b(?:Benchmark|Index)\s+Return\b"),
    # ---- table hazards --------------------------------------------------
    ("table_scale_qualifier", "hazard", "pdf_table", r"\((?:in|amounts in|dollars in)\s+(?:thousands|millions|billions)\)"),
    ("parenthesised_negative", "hazard", "pdf_table", r"\(\s?[\d,]{3,}(?:\.\d+)?\s?\)"),
    ("split_number_artifact", "hazard", "pdf_table", r"(?<![\d,.])\d{1,3}\s,?\d{1,3},\d{3}(?:,\d{3})*(?:\.\d+)?(?![\d,])"),
    ("not_disclosed_marker", "hazard", "pdf_table", r"\b(?:Not Disclosed|N/?A|Confidential|Redacted)\b"),
    ("continued_table_marker", "hazard", "pdf_table", r"\((?:continued|cont\.?)\)"),
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
