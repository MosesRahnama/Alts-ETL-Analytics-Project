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

FIELD_DESCRIPTIONS: dict[str, str] = {
    "contract_version": "Which release of this field list the row was written under. Filled by the workflow.",
    "file_id": "The corpus identifier of the source document, such as SRC377.",
    "source_sha256": "SHA-256 of the source PDF, binding the row to one binary. A mismatch means the document changed and the extraction is void.",
    "canonical_doc_type": "The listed type, such as Financials or PPM. Readers keep the listed type.",
    "route": "The reading group the document belongs to, derived from its type.",
    "product_tier": "CORE, SECONDARY, or REFERENCE. Controls what evidence classes are acceptable and keeps template material out of the fund dataset.",
    "agent_role": "Which blind extractor wrote the row, A or B. Becomes ADJUDICATED on a final row.",
    "record_family": "What kind of fact this row is, chosen from the closed family list. Follows the table the value sits in, not the document type.",
    "source_page": "The physical PDF page number the value is printed on.",
    "source_structure_type": "The kind of layout the value came from: TABLE, FIGURE, NARRATIVE, FORM, FOOTNOTE, SCHEDULE, or DOCUMENT. Always uppercase.",
    "source_section": "The printed section heading above the table, such as Statements of Financial Position.",
    "source_table": "The printed table or figure title that names the whole table. Never a date and never a heading that covers only some columns.",
    "source_row_label": "The printed row label the value sits on. The primary physical anchor for a value.",
    "source_column_label": "The printed column header the value sits under, taken from the lowest header directly above the column. Kept unique within a row, so stacked headers such as 1-Yr Total Return are preserved whole.",
    "source_occurrence": "Which instance this is when the same row and column labels repeat on one page, counted top to bottom then left to right. Normally 1.",
    "subject_type": "What kind of thing the row measures, in lowercase, from the closed list. Read from the row's own printed label, not decided once per document.",
    "subject_name": "The printed name of the thing being measured: the fund, portfolio, position, asset class, or benchmark named on that row.",
    "asset_class": "The printed asset class governing the row, such as Private Equity or Fixed Income. Taken from the group heading, table title, or document statement that covers the row. A core analytical dimension: fill it whenever the page states it, never infer it, and never restate the row label here.",
    "strategy": "The printed strategy governing the row, such as Buyout, Venture, or Core Real Estate. Same sourcing rule as asset class.",
    "geography": "The printed geographic scope governing the row, such as North America or Europe. Same sourcing rule as asset class.",
    "manager_name": "The printed manager or general partner. Recorded once on the document row, not repeated on every observation.",
    "investor_name": "The printed asset owner, verbatim as the page renders it. Recorded once on the document row.",
    "portfolio_name": "The printed portfolio or programme the document reports on. Recorded once on the document row.",
    "vintage_year": "The printed vintage year of the fund on that row.",
    "period_start": "The printed start of the period the value covers.",
    "period_end": "The printed end of the period the value covers.",
    "as_of_date": "The printed date the value is stated as of, in the fullest printed form. December 31, 2015, not 2015, and never reformatted to ISO.",
    "horizon": "The printed measurement period for a return or risk figure, such as 1-Yr, 5 Year, ITD, or Fiscal YTD 9 Months. Required whenever the column header carries a period qualifier.",
    "currency_scale": "The printed currency and scale statement that makes the number readable, such as $ in millions, copied verbatim including any parentheses.",
    "metric_category": "What the value measures, chosen from the one metric vocabulary by the printed meaning; the family says where the cell sat, the category says what it is. This is the field the database joins on.",
    "metric_name": "The printed label for the measure, taken from whichever axis names it: the row label where rows are measures and columns are periods, the leaf column header where rows are entities and columns are measures, and the table's own title only where neither axis names a measure. Never a section heading, and never identical to horizon. The page's own wording, not a controlled value.",
    "metric_value_raw": "The printed value, copied verbatim: currency symbol, thousands separators, decimals, sign, and parentheses all preserved. Never calculated, rounded, rescaled, or repunctuated.",
    "unit": "The unit of measure printed for the value: %, x, bps, years, shares. A currency is never a unit; it belongs in currency_scale.",
    "term_category": "For provisions only: which term of the one term vocabulary the clause states, such as management_fee or key_person.",
    "text_raw": "For legal provisions and qualitative facts: the printed wording of the provision.",
    "basis_raw": "For legal provisions: the printed basis a rate or amount is calculated on, such as committed capital.",
    "condition_raw": "For legal provisions: the printed condition or qualification attached to the term.",
    "evidence_quote": "One short line copied verbatim from the cited page that contains the value. Checked against the page, so it cannot be paraphrased.",
    "evidence_class": "Whether the value is an actual reported figure, an illustrative or template figure, a stated requirement, a definition, or redacted.",
    "notes": "Free-text remarks. Also carries the NO_ELIGIBLE_REASON and IMAGE_ONLY prefixes where the field list requires them.",
    "source_agents": "On a final adjudicated row, which extractors the fact came from: A, B, A+B, or ADJUDICATOR.",
    "adjudication_status": "On a final adjudicated row, how it was settled: AGREED, VERIFIED_ONE_SIDED, RESOLVED, or ADDED.",
}

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
     ("subject_type", "subject_name", "asset_class", "strategy", "geography",
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
