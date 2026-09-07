"""Reviewer-facing field guide, generated from the field list.

A hand-written companion to the machine schema would drift the moment a field
changed, and this repository has already been burned by that. So the
prose lives here and the structure is read from `csv_wide_contract`, which means
the guide cannot describe a field that does not exist or omit one that does.

Deliberately contains no tables: it is read top to bottom, one field per line.
"""
from __future__ import annotations

from .csv_wide_contract import (
    CANONICAL_DOC_TYPES,
    CONTRACT_VERSION,
    DEFAULT_PRODUCT_TIER,
    DOC_TYPE_FAMILIES,
    DOC_TYPE_TO_ROUTE,
    FAMILY_CONTRACTS,
    METRIC_CATEGORIES,
    RECORD_COLUMNS,
    SOURCE_STRUCTURE_TYPES,
    SUBJECT_TYPES,
    TERM_CATEGORIES,
    preferred_categories,
)

from src.common import matrices

DESCRIPTIONS = "field-descriptions"


FIELD_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("IDs the work fills",
     "Written by the work from the worklist. An extractor copies these from that list.",
     ("contract_version", "file_id", "source_sha256", "canonical_doc_type", "route",
      "product_tier", "agent_role")),
    ("Printed address of the value",
     "The physical address of the fact inside the document. Two extractors reading the same cell must map to the same address, which is what makes their work comparable.",
     ("record_family", "source_page", "source_structure_type", "source_section",
      "source_table", "source_row_label", "source_column_label", "source_occurrence")),
    ("Subject of the value",
     "The entity the number describes, and the analytical dimensions a reviewer filters on.",
     ("subject_type", "subject_name", "asset_class", "strategy", "sector", "geography",
      "manager_name", "investor_name", "portfolio_name", "vintage_year")),
    ("Dates, scale, and units",
     "These fields place the number in time and make the number usable.",
     ("period_start", "period_end", "as_of_date", "horizon")),
    ("The measurement itself",
     "The fact being captured, and everything needed to read it correctly.",
     ("currency_scale", "metric_category", "metric_name", "metric_value_raw", "unit")),
    ("Legal and narrative provisions",
     "Used by the legal families only, where the fact is printed wording, not a number.",
     ("term_category", "text_raw", "basis_raw", "condition_raw")),
    ("Proof and lineage",
     "How the row can be checked against the page, and how it was settled between the two extractors.",
     ("evidence_quote", "evidence_class", "notes", "source_agents", "adjudication_status")),
    ("Definitions and qualifiers",
     "The printed footnotes and methodology notes that define the numbers, captured as definition_context rows, and the stated dimensions that make a qualified category's number mean one thing.",
     ("definition_keys", "method", "fee_basis", "value_scope")),
)

DOC_TYPE_NOTES: dict[str, str] = {
    "Financials": "Audited or unaudited fund financial statements: statements of assets and liabilities, operations, changes in partners' capital, and the investment schedules and fair-value notes behind them.",
    "Performance": "Performance schedules reporting returns, multiples and IRRs, usually by partnership or by asset class, often against benchmarks.",
    "Institutional_Report": "An asset owner's periodic report on its whole portfolio: allocations, returns by asset class, and manager-level detail.",
    "Quarterly_Report": "A quarterly report to investors combining commentary with performance, capital account and partnership-level schedules.",
    "PPM": "Private placement memorandum. The offering document stating fund terms, fees and structure.",
    "LPA": "Limited partnership agreement. The operative contract governing the fund.",
    "Subscription": "Subscription agreement recording an investor's commitment and eligibility representations.",
    "Side_Letter": "Negotiated terms granted to a specific investor, amending or supplementing the LPA.",
    "DDQ": "Due diligence questionnaire. Structured answers about the manager, including quantitative firm and fund figures.",
    "Schedule_Inv": "Schedule of investments: the holdings list, one row per position, with cost and fair value.",
    "Fee_Report": "Fee transparency reporting: management fees, carried interest, partnership expenses and the basis they are charged on.",
    "Valuation": "Valuation policy and results: methods, frequency, who values, what oversight applies, and resulting marks.",
    "NAV_Statement": "Net asset value statement, including per-share values and any repurchase or liquidity limits.",
    "Cash_Flow_Notice": "Capital call or distribution notice stating the amounts due or paid and their components.",
    "PCAP": "Partners' capital account statement: an investor's beginning balance, contributions, distributions, allocations and ending balance.",
    "Foundations_Annual": "A foundation's annual return or report, including investment holdings and programme-related investments.",
    "Stewardship_Proxy_Report": "Stewardship and proxy voting reporting: engagement and voting activity and the policies behind them.",
}


FIELD_DESCRIPTIONS: dict[str, str] = matrices.mapping(DESCRIPTIONS)


def _line(name: str) -> str:
    return f"- `{name}`: {FIELD_DESCRIPTIONS.get(name, 'No description recorded.')}"


def field_guide_markdown() -> str:
    out: list[str] = []
    add = out.append

    add("# Extracted fields, one by one")
    add("")
    add(f"Field-list `{CONTRACT_VERSION}`. Companion to `MASTER-EXTRACTION-SCHEMA.md`,")
    add("which states the same field list for code. This file is written for a")
    add("reader: every field appears on its own line with what it means, followed by")
    add("what each document type produces.")
    add("")
    add("Generated from the field list. Edit `src/catalog/simple_pdf_extraction/field_guide.py`, then rebuild.")
    add("")
    add("## The unit of one row")
    add("")
    add("One row is one fact printed in one place: a single value cell in a table, or a")
    add("single whitelisted provision in a legal document. A table row with five")
    add("populated columns produces five rows, each carrying its own column label. A")
    add("blank, a dash, or an N/A produces no row at all.")
    add("")
    add("Every value is copied verbatim as printed. Nothing is calculated, converted,")
    add("rounded, or inferred. If the page does not state it, the field stays blank.")
    add("")
    add(f"There are {len(RECORD_COLUMNS)} fields on every row. Most are blank on any given")
    add("row, because a field only applies where the page supports it.")
    add("")

    for title, blurb, fields in FIELD_GROUPS:
        add(f"## {title}")
        add("")
        add(blurb)
        add("")
        for name in fields:
            if name in RECORD_COLUMNS:
                add(_line(name))
        add("")

    missing = [c for c in RECORD_COLUMNS
               if not any(c in f for _, _, f in FIELD_GROUPS)]
    if missing:
        add("## Not yet grouped")
        add("")
        for name in missing:
            add(_line(name))
        add("")

    add("## Controlled vocabularies")
    add("")
    add("Three fields accept only listed values, matched character for character.")
    add("")
    add(f"- `source_structure_type`: {', '.join(SOURCE_STRUCTURE_TYPES)}")
    add(f"- `subject_type`: {', '.join(SUBJECT_TYPES)}")
    add("- `metric_category`: any name in the metric vocabulary of `EXTRACTION-METRIC-CATEGORIES.csv`,")
    add(f"  {len(METRIC_CATEGORIES)} names, each with a definition and unit hint; `term_category`: any of its")
    add(f"  {len(TERM_CATEGORIES)} term names. A family fills one of the two by its kind; the preferred")
    add("  family listed for a name is guidance for a mixed table, never a rule.")
    add("")

    add("## Output by document type")
    add("")
    add("A document's type fixes which kinds of row it can yield. Within a document,")
    add("the family follows the table the value sits in, not the document type: a")
    add("financial statement can still yield a holdings row where it prints a holdings")
    add("schedule.")
    add("")

    for doc_type in sorted(CANONICAL_DOC_TYPES):
        route = DOC_TYPE_TO_ROUTE[doc_type]
        tier = DEFAULT_PRODUCT_TIER.get(doc_type, "CORE")
        add(f"### {doc_type}")
        add("")
        add(DOC_TYPE_NOTES.get(doc_type, ""))
        add("")
        add(f"Extracted in route `{route}`, default product tier `{tier}`.")
        add("")
        for family in DOC_TYPE_FAMILIES[doc_type]:
            contract = FAMILY_CONTRACTS[family]
            add(f"**`{family}`**: {contract.description}")
            add("")
            add(f"- Grain: {contract.grain}")
            required = sorted(contract.required_fields)
            add(f"- Always filled: {', '.join(f'`{f}`' for f in required)}")
            preferred = preferred_categories(family)
            if contract.kind == "metric":
                add(f"- `metric_category`: any metric name; usual here: {', '.join(preferred) or 'none'}")
            elif contract.kind == "term":
                add(f"- `term_category`: any term name; usual here: {', '.join(preferred) or 'none'}")
            add("")
    return "\n".join(out).rstrip() + "\n"
