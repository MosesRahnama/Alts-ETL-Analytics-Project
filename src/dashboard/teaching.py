"""Reviewer teaching copy for the dashboard: words, page guide, section primers.

The page is for a reader who has the HTML file and has not read the rest of
the repository. Column names stay as published. The sentences around them
define the work in ordinary words.
"""

from __future__ import annotations

from copy import deepcopy


# Words a first-time reader meets on more than one section. The page guide
# lists all of them. Each section also repeats the subset it uses.

WORDS: list[dict[str, str]] = [
    {
        "word": "observation",
        "meaning": (
            "One printed cell: one number or short text in one place on one page. "
            "That cell becomes one row. A printed table line with five filled numbers "
            "produces five rows."
        ),
    },
    {
        "word": "evidence row",
        "meaning": (
            "A kept observation after two LLMs typed it and a third LLM checked "
            "the page picture. The row holds the value, the subject, the date, the unit, "
            "the physical page, the quote, and the review decision."
        ),
    },
    {
        "word": "extractor proposal",
        "meaning": (
            "One PDF value or statement as one LLM recorded it before third-reader review. "
            "A proposal remains in the audit files even when the reviewer rejects or corrects it."
        ),
    },
    {
        "word": "adjudication",
        "meaning": (
            "Third-reader review of the two independent proposals against the PDF page. "
            "The decision records which value became retained evidence and why."
        ),
    },
    {
        "word": "normalization matrix",
        "meaning": (
            "A CSV rule table that states how a printed label, unit, name, or category is "
            "standardized. The original printed text remains beside the standardized value."
        ),
    },
    {
        "word": "lineage",
        "meaning": (
            "The stored link from an output value to the prior row, rule, source file, and PDF "
            "page that supplied it. Lineage records added values as well as printed values."
        ),
    },
    {
        "word": "LLM",
        "meaning": (
            "One language model working alone on its own file. LLM A and LLM B "
            "type the same pages. A third LLM opens the page picture and decides "
            "clashes and one-LLM findings."
        ),
    },
    {
        "word": "physical page",
        "meaning": (
            "Page count from the front of the PDF file, starting at 1. The printed "
            "number in the footer can differ. Extraction cites the physical page."
        ),
    },
    {
        "word": "document grid",
        "meaning": (
            "A measuring list of printed table numbers by page, row label, column, "
            "and heading. A small program builds it from the PDF's own positions. "
            "LLMs use it to find cells. Where the grid and the page picture "
            "disagree, the picture is the source. Grid values stay out of fund tables."
        ),
    },
    {
        "word": "FOIA",
        "meaning": (
            "A file a public body handed over under an open-records request. Many "
            "source PDFs arrived this way."
        ),
    },
    {
        "word": "EXTRACTED",
        "meaning": "The value is printed on a cited PDF page.",
    },
    {
        "word": "DERIVED",
        "meaning": (
            "Copied inside one fund from a value that page printed. Example: a vintage "
            "year stated once, copied onto that fund's other rows."
        ),
    },
    {
        "word": "IMPUTED",
        "meaning": (
            "No page states the field, so a declared rule supplied a default: a seeded "
            "draw across a configured range, the configured strategy, or a keyword from "
            "the fund's own name. imputation_method names which."
        ),
    },
    {
        "word": "SYNTHETIC",
        "meaning": (
            "Made from stated settings because the PDFs omit it. SYNTHETIC periods sit "
            "on real FUND_ IDs. Test-only funds use FUND_SYNTH_ IDs in a separate file."
        ),
    },
    {
        "word": "NAV",
        "meaning": "Net asset value: what the remaining position is said to be worth.",
    },
    {
        "word": "DPI",
        "meaning": (
            "Cash returned to the investor, per dollar paid in. 1.00x on DPI is "
            "dollar-for-dollar cash back on that slice."
        ),
    },
    {
        "word": "RVPI",
        "meaning": (
            "Value still held, per dollar paid in. 1.00x on RVPI is dollar-for-dollar "
            "remaining value on that slice."
        ),
    },
    {
        "word": "TVPI",
        "meaning": "DPI plus RVPI. Total value per dollar paid in.",
    },
    {
        "word": "IRR / XIRR",
        "meaning": (
            "A yearly rate that fits the dated cash flows. XIRR uses the actual dates. "
            "The page uses a 365-day year."
        ),
    },
    {
        "word": "PME",
        "meaning": (
            "Public-market equivalent. The same dated cash, if it had bought a public "
            "index instead, compared with the fund. KS-PME is that comparison as a "
            "multiple. Direct Alpha is the yearly gap versus the index."
        ),
    },
    {
        "word": "DuckDB",
        "meaning": (
            "A database file built from the CSVs so a checker can query them. The CSV "
            "is the source a spreadsheet can open. A check requires the same rows and "
            "values in both."
        ),
    },
    {
        "word": "stored table",
        "meaning": "Rows the database file keeps on disk.",
    },
    {
        "word": "view / saved query",
        "meaning": (
            "A stored instruction that selects or calculates rows when opened. Italic "
            "names in the database list are saved queries. Plain names are stored tables. "
            "A view holds no separate copy of the rows."
        ),
    },
    {
        "word": "CORE / SECONDARY / REFERENCE",
        "meaning": (
            "CORE: numbers may go into fund tables. SECONDARY: extra facts, read under "
            "the same checks. REFERENCE: sample forms, listed only."
        ),
    },
    {
        "word": "MERGE / ACCEPT / ADD / REJECT",
        "meaning": (
            "MERGE joins two readings that match the page. ACCEPT_A or ACCEPT_B keeps "
            "one LLM's version against the page. ADD types a field both LLMs missed. "
            "REJECT drops a row empty of a printed fact."
        ),
    },
    {
        "word": "PASS / FAIL / SKIP",
        "meaning": (
            "Quality-rule marks. PASS: the recomputed value agrees within the allowed "
            "gap. FAIL: the printed or filled figures break the money rule. SKIP: the "
            "rule lacked an input, so it stayed out of PASS and FAIL."
        ),
    },
    {
        "word": "FUND_ versus FUND_SYNTH_",
        "meaning": (
            "FUND_ IDs are named funds from the reports (printed rows plus labelled fill). "
            "FUND_SYNTH_ IDs are the 800-fund test set. Those IDs stay in the test files."
        ),
    },
]


HELP = {
    "title": "Page guide",
    "intro": (
        "This file copies numbers from the project's published CSVs and database files "
        "at build time. The browser displays those copies. A count on the screen and a "
        "count in the named CSV are the same figure when this file matches the builder."
    ),
    "sections": [
        {
            "title": "Using the tables",
            "paragraphs": [
                (
                    "Every data table works the same way. Open Column meanings to read a "
                    "one-line definition for each column, including columns hidden from the "
                    "compact grid."
                ),
                (
                    "Type any fragment in Search. The grid keeps rows that contain that text "
                    "in any field. Select a column heading to sort; select it again to reverse "
                    "the order."
                ),
                (
                    "Select a row. A panel opens with every field, including fields the compact "
                    "grid hides. Select the row again to close it. File paths in that panel open "
                    "as links to the PDF, the page text, or the review file."
                ),
                (
                    "Previous and Next show 25 rows at a time unless the panel says otherwise. "
                    "Some large files embed the first 400 rows and still print the full row count."
                ),
                (
                    "Headline cards, bars, rings, and box plots are pictures of the same files. "
                    "They add no extra data."
                ),
            ],
        },
        {
            "title": "The work in short",
            "paragraphs": [
                (
                    "Pension funds, endowments, and similar public bodies publish PDF reports "
                    "about private funds. This project lists those PDFs, types printed fields "
                    "into rows, checks the typing against the page picture, and builds fund "
                    "tables from the kept rows."
                ),
                (
                    "Two LLMs each work alone on the same pages. A third LLM opens the "
                    "page picture and decides every clash and every field found by one LLM "
                    "only. A fixed ten percent sample of matching rows is checked the same way."
                ),
                (
                    "Kept fields become fund tables after printed names map to stable IDs. Empty "
                    "cells get filled and marked EXTRACTED, DERIVED, IMPUTED, or SYNTHETIC. "
                    "Money rules and performance measures run on those tables."
                ),
                (
                    "{published_documents} of the {catalogued_documents} listed reports have "
                    "completed extraction and adjudication. Their {published_pages} reviewed "
                    "pages supply the published evidence rows. The other reports remain in the "
                    "source inventory and do not enter the extracted fund data."
                ),
            ],
        },
        {
            "title": "Four files for each report",
            "paragraphs": [
                (
                    "The PDF is the published report. A text file lines the words up to each "
                    "physical page. A 300 DPI picture of each physical page is the authority "
                    "for layout and for review. A document grid lists printed table numbers by "
                    "position so a skipped table is visible."
                ),
            ],
        },
        {
            "title": "Three database files",
            "paragraphs": [
                (
                    "extracted.duckdb holds kept PDF facts, page locations, name decisions, "
                    "review history, holdings, and reconstructed source tables."
                ),
                (
                    "alts.duckdb holds fund tables after fill, quality results, and measures. "
                    "alts_mock.duckdb holds the same table shapes filled with FUND_SYNTH_ test "
                    "funds only."
                ),
                (
                    "Each database file is loaded from CSVs. A checker who wants a spreadsheet "
                    "opens the CSV. A checker who wants a query opens the DuckDB file."
                ),
            ],
        },
        {
            "title": "The evidence chain",
            "paragraphs": [
                (
                    "records-a.csv and records-b.csv contain the two independent extractor "
                    "proposals. records-final.csv contains the third reader's accepted records "
                    "for one document. coverage-final.csv accounts for every reviewed page."
                ),
                (
                    "fact_observation.csv combines the accepted records from all completed "
                    "documents. observation_lineage.csv links each accepted record to both "
                    "proposals, their comparison, and the review decision."
                ),
                (
                    "CSV rule tables under data/normalization standardize names, categories, "
                    "units, and fixed fund attributes. Source-only fund tables preserve the "
                    "reported values before analytical completion adds labelled values."
                ),
                (
                    "reviewer-cell-lineage.csv identifies the source or declared method behind "
                    "each completed fund field. fund_metrics.csv and pme_results.csv identify "
                    "the input record IDs and formulas behind each calculated result."
                ),
            ],
        },
        {
            "title": "The named reference files",
            "paragraphs": [
                (
                    "data-gathering/source_ledger.csv is the inventory of acquired reports. A "
                    "row in that file describes a PDF; it is not a reported investment value."
                ),
                (
                    "docs/FINAL-RELEASE-AUDIT.csv is the current 27-step process table. "
                    "ledgers/pipeline/release-checks.csv stores the latest result and time for "
                    "each step. transformation-receipts.csv is the longer history of files "
                    "written by release commands, including earlier failed runs."
                ),
                (
                    "data/extracted/fund-level contains source-only fund tables. data/csv contains "
                    "the completed analytical tables. data/extracted/review contains flattened "
                    "reviewer exports that place evidence, fund values, origins, and results in "
                    "one reading area."
                ),
                (
                    "A panel's Source line names the file used for its figures. A row detail can "
                    "name an earlier row, a rule matrix, or a PDF location; those references form "
                    "the evidence path rather than additional measurements."
                ),
            ],
        },
    ],
}


def page_help(*, catalogued_documents: int, published_documents: int, published_pages: int) -> dict:
    """Return the help copy with counts read from the current release."""

    result = deepcopy(HELP)
    values = {
        "catalogued_documents": f"{catalogued_documents:,}",
        "published_documents": f"{published_documents:,}",
        "published_pages": f"{published_pages:,}",
    }
    for section in result["sections"]:
        section["paragraphs"] = [paragraph.format(**values) for paragraph in section["paragraphs"]]
    return result


def guide(
    title: str,
    paragraphs: list[str],
    items: list[tuple[str, str]] | None = None,
    *,
    tone: str = "teach",
    lead: str = "",
) -> dict:
    """A teaching box. tone is teach, warn, or fact."""

    return {
        "kind": "guide",
        "title": title,
        "tone": tone,
        "lead": lead,
        "paragraphs": paragraphs,
        "items": [[key, value] for key, value in (items or [])],
    }


def terms(*words: str) -> dict:
    """A compact word list for the words this section uses."""

    lookup = {row["word"]: row["meaning"] for row in WORDS}
    items = []
    for word in words:
        meaning = lookup.get(word)
        if meaning:
            items.append([word, meaning])
    return {"kind": "terms", "title": "Words on this page", "items": items}


def overview_primer() -> list[dict]:
    return [
        guide(
            "This page and the files behind it",
            [
                (
                    "The numbered list on the left opens the twelve sections. Page guide in the "
                    "left column defines the words and the table controls. This file is a "
                    "snapshot of the published CSVs and database files. It recalculates nothing. "
                    "Every panel names the file it read."
                ),
                (
                    "ETL here means three jobs: extract (type the printed fields), transform "
                    "(map names, attach origin labels, fill empty cells), and load (write CSV "
                    "and DuckDB files). A FOIA file is one a public body handed over under an "
                    "open-records request."
                ),
                (
                    "One observation is one printed cell. Each report that has been read "
                    "produces one row per printed field it states, and the Overview cards "
                    "count the reports and the rows as the published files hold them today. "
                    "Each physical page used for extraction has a 300 DPI picture. Document "
                    "grids list printed table numbers by position."
                ),
            ],
            [
                ("Extractor proposal", "One printed field as one LLM typed it, before checks."),
                ("Published evidence row", "One printed field after review against the page picture."),
                ("PDF-only fund row", "A kept field after printed names map to stable IDs. Every value cites a page."),
                ("Filled fund-date row", "A fund-and-date row with empty cells written and marked."),
                ("Test-only fund", "A FUND_SYNTH_ ID used to test the money rules. It stays in the test files."),
            ],
            lead="Start here if this is the first opening of the file.",
        ),
        terms(
            "observation",
            "evidence row",
            "LLM",
            "physical page",
            "document grid",
            "FOIA",
            "EXTRACTED",
            "DERIVED",
            "IMPUTED",
            "SYNTHETIC",
            "DuckDB",
        ),
    ]


def corpus_primer() -> list[dict]:
    return [
        guide(
            "The source list and the reports that were read",
            [
                (
                    "The catalog contains collected PDFs and their acquisition details. "
                    "The extraction summary counts published documents against the active assignments."
                ),
                (
                    "Each report has four working forms: the PDF, page-aligned text, a 300 DPI "
                    "picture of each physical page, and a document grid of printed table numbers. "
                    "Git leaves the PNG pictures out because they are large; render them with "
                    "data-gathering/src/render_image_corpus.py."
                ),
            ],
            [
                ("CORE", "Numbers may go into fund tables."),
                ("SECONDARY", "Extra facts, read under the same checks."),
                ("REFERENCE", "Sample forms. They stay on the list."),
            ],
        ),
        terms("document grid", "physical page", "CORE / SECONDARY / REFERENCE", "FOIA"),
    ]


def extraction_primer() -> list[dict]:
    return [
        guide(
            "Two LLMs, a third LLM, and the checks",
            [
                (
                    "Each LLM types one printed field per row: value, subject, date, unit, "
                    "physical page, row label, column label, repeated occurrence, and quote. "
                    "The two files are compared field by field."
                ),
                (
                    "A third LLM opens the page picture for every clash and every field found "
                    "by one LLM only. Two LLMs can type the same wrong number, so a fixed "
                    "ten percent sample of matches is checked against the page as well."
                ),
                (
                    "A value difference is 1.21 against 1.22. A classification difference is one "
                    "number filed as TVPI by one LLM and IRR by the other. A context difference "
                    "is the same number under a different date, subject, or unit."
                ),
            ],
            [
                ("MERGE", "Two readings match the page; they join."),
                ("ACCEPT_A / ACCEPT_B", "One LLM's version matches the page."),
                ("ADD", "The third LLM typed a field both LLMs missed."),
                ("REJECT", "The row is empty of a printed fact."),
            ],
        ),
        terms("LLM", "observation", "physical page", "document grid", "MERGE / ACCEPT / ADD / REJECT"),
    ]


def evidence_primer() -> list[dict]:
    return [
        guide(
            "One printed cell, one row",
            [
                (
                    "Each kept row is one printed field from one PDF: this fund, this date, this "
                    "label, this value, this quote. Fund tables take values from these rows. Fund "
                    "periods list their input evidence-row IDs."
                ),
                (
                    "The asset_class column copies the grouping heading printed on the page. On a "
                    "schedule of portfolio companies that heading is often an industry "
                    "(Manufacturing). On a policy report it is often a sleeve or a benchmark name. "
                    "The listed type columns beside it map that heading into one shared list."
                ),
                (
                    "value_kind is the printed form of the cell: number, currency, percent, "
                    "multiple, or text. A figure under a dollar heading can print as a number. "
                    "The currency column holds USD in that case, and is_monetary reads the "
                    "currency first."
                ),
            ],
            [
                ("IMAGE_ONLY", "The reviewer picked the value from the page picture. The PDF text hid it."),
                ("redacted", "The page prints the label and blacks out the number. The empty cell stays empty."),
                ("actual", "The page prints the value. Only actual rows become fund numbers."),
            ],
            tone="fact",
        ),
        terms("observation", "evidence row", "NAV", "DPI", "RVPI", "TVPI"),
    ]


def schema_primer() -> list[dict]:
    return [
        guide(
            "The 47 columns and the name lists",
            [
                (
                    "Both LLMs fill the same 47 columns: who, when, the printed value, the "
                    "cleaned value, the unit, the place on the page, the quote, and the review "
                    "mark. A later field-list version stays apart from this one."
                ),
                (
                    "metric_name is the page's own words (Total Value to Paid In). metric_category "
                    "is the shared name (tvpi). record_family is the kind of printed line "
                    "(a holding, a performance line, a cash-flow notice)."
                ),
                (
                    "unit is % or x or a currency code. unit_scale is millions or thousands. "
                    "currency_scale_raw is the verbatim line the page printed, such as $ in millions."
                ),
            ],
        ),
        terms("observation", "NAV", "TVPI"),
    ]


def generated_primer() -> list[dict]:
    return [
        guide(
            "Four origin labels on the same fund IDs",
            [
                (
                    "PDFs print different fields and dates, so the fund-date table has empty "
                    "cells. The fill step writes marked values on the same FUND_ IDs. One seed "
                    "makes the same filled table on a rerun. The seed is an input, empty of page "
                    "evidence. Fallback fund size 250,000,000 is an assumed setting."
                ),
                (
                    "ASSUMED is a generation parameter used to make SYNTHETIC cells. It is empty "
                    "of a row label on fund_master. SYNTHETIC is the cell label."
                ),
                (
                    "A fund's own name is empty of evidence about the strategy it runs. Where a "
                    "name contains a keyword, that keyword sits in name_hint and stays out of "
                    "strategy and sub_strategy."
                ),
            ],
            [
                ("EXTRACTED", "Printed on a cited page."),
                ("DERIVED", "Copied inside one fund from a printed value."),
                ("IMPUTED", "A declared rule supplied a default; imputation_method names it."),
                ("SYNTHETIC", "Made from stated settings. Sits on real FUND_ IDs."),
            ],
            tone="warn",
        ),
        terms("EXTRACTED", "DERIVED", "IMPUTED", "SYNTHETIC", "FUND_ versus FUND_SYNTH_"),
    ]


def quality_primer() -> list[dict]:
    return [
        guide(
            "Money rules on printed rows and on filled rows",
            [
                (
                    "Each quality row runs one rule on one fund record the rule can test. The "
                    "row stores the stored value, the value from the parts, the gap, the allowed "
                    "gap, and PASS, FAIL, or SKIP."
                ),
                (
                    "A FAIL can be a number the page printed in parentheses (a negative) or a "
                    "filled row that breaks a money identity. Currency checks also compare "
                    "fund periods with their cash flows. Each data group has its own result count."
                ),
                (
                    "SKIP on a printed IRR versus made cash flows is the intended mark: those "
                    "cash flows are a different history from the printed rate. Printed DPI with "
                    "paid-in absent beside it also SKIPs, because the parts are absent."
                ),
                (
                    "The reconciliation table proves the fill left each printed cell as it was. "
                    "A fail there is a pipeline break. The detection scorecard counts 12 deliberate "
                    "errors in defect-periods.csv; those errors stay out of data/csv fund tables."
                ),
            ],
            [
                ("PASS", "Recomputed value agrees within the allowed gap."),
                ("FAIL", "The figures break the money rule."),
                ("SKIP", "The rule lacked an input."),
            ],
            tone="warn",
        ),
        terms("PASS / FAIL / SKIP", "EXTRACTED", "SYNTHETIC"),
    ]


def benchmarks_primer() -> list[dict]:
    return [
        guide(
            "Public prices used as a stand-in index",
            [
                (
                    "PME asks what the same dated cash would have become if it had bought a "
                    "public index instead. Each calculation uses daily returns from the "
                    "benchmark named on its result row. The policy table records each series' use restrictions."
                ),
                (
                    "A level is the index price that day. A return is today's level over "
                    "yesterday's. PME consumes returns."
                ),
                (
                    "rights_status is whether the file may be redistributed. use_status is "
                    "whether this project may treat it as a real benchmark. DEMO_PROXY_ONLY "
                    "and DEMONSTRATION_ONLY mark this demo."
                ),
            ],
            [
                ("PME_CORE", "Return history that may go into the comparison."),
                ("ADVANCED_DAILY / MARKET_CONTEXT", "Background files. They stay out of KS-PME."),
            ],
        ),
        terms("PME", "IRR / XIRR"),
    ]


def analytics_primer() -> list[dict]:
    return [
        guide(
            "Printed multiples, then filled-table rates",
            [
                (
                    "The six cards define DPI, RVPI, TVPI, XIRR, KS-PME, and Direct Alpha with "
                    "a worked example from the files. Results from printed numbers have one "
                    "mark. Results that use filled rows have another mark."
                ),
                (
                    "A contribution is negative to the investor and a distribution is positive, "
                    "because the measure is the investor's wallet: money out is negative, money "
                    "back is positive."
                ),
                (
                    "XIRR, KS-PME, and Direct Alpha on the filled fund-date table use invented "
                    "cash flows on real FUND_ IDs. Direct Alpha below zero means the fund trailed "
                    "the index by about that much a year."
                ),
                (
                    "Each fund starts at an equal share of the eligible population and is capped at 5 percent. That is equal "
                    "weight with a cap, empty of a risk model. Funds with a blank printed strategy "
                    "receive Diversified Alternatives from the fill step, which is why that bar "
                    "is large."
                ),
            ],
            tone="warn",
        ),
        terms("DPI", "RVPI", "TVPI", "IRR / XIRR", "PME", "SYNTHETIC"),
    ]


def warehouse_primer() -> list[dict]:
    return [
        guide(
            "Three database files, loaded from CSVs",
            [
                (
                    "extracted.duckdb: kept PDF facts, locations, names, review history, holdings, "
                    "and reconstructed source tables. 27 stored tables. Four saved queries."
                ),
                (
                    "alts.duckdb: fund tables after fill, quality results, and measures. 18 stored "
                    "tables. Three saved queries."
                ),
                (
                    "alts_mock.duckdb: the same 18 table shapes filled with FUND_SYNTH_ test funds "
                    "only."
                ),
                (
                    "The number 27 is empty of a count of extraction categories. Five tables "
                    "describe documents, pages, names, and measured items. Three store kept facts, "
                    "review history, and holdings. One stores names still awaiting a decision. "
                    "One links combined rows to their source facts. Seventeen arrange kept facts "
                    "by subject."
                ),
                (
                    "Italic names in the database list are saved queries. Plain names are stored "
                    "tables. Counts beside names are the whole table. The grid shows the first "
                    "200 rows in stable order."
                ),
            ],
            [
                ("CSV", "The spreadsheet file a checker can open. Source of the database load."),
                ("DuckDB", "The query file built from those CSVs."),
            ],
        ),
        terms("DuckDB", "stored table", "view / saved query", "observation", "FUND_ versus FUND_SYNTH_"),
    ]


def reproduce_primer() -> list[dict]:
    return [
        guide(
            "This file is a snapshot",
            [
                (
                    "The commands on this page rebuild and check the files. A reviewer who is "
                    "reading the numbers can leave them unused. dashboard.html copies the files "
                    "that were present at build."
                ),
                (
                    "reviewer_check is the 144-item yes/no gate that the published files still "
                    "match the claimed counts. stage_id on the data-change log is the rebuild "
                    "step number. FAIL on an old receipt is historical; the latest matching "
                    "stage is the live result."
                ),
                (
                    "CSV data flow names where a CSV came from: which prior CSV, which script, "
                    "and which human role if any. The project file map marks TRACK (ships with "
                    "the repository) and LOCAL_ONLY (stays on the machine). Source PDFs are "
                    "public; page pictures are local."
                ),
            ],
        ),
    ]


def costs_primer() -> list[dict]:
    return [
        guide(
            "Price of reading the catalogue",
            [
                (
                    "A run is billed by the turn. A turn is one request to the model. Cost per "
                    "turn held steady across documents that differ ninefold in row count, so "
                    "cost reduces to counting turns."
                ),
                (
                    "Turns split into a cost for opening a page and a small added cost for each "
                    "row written once that page is open. Two readings, each working alone, plus "
                    "the third-LLM review is the full published pipeline."
                ),
                (
                    "The cost of opening a page falls on long reports. A 149-page return took 1.7 "
                    "turns per page against the 23.7 of a short dense schedule, because most of its "
                    "pages were cleared without extraction. The totals here price every page at the "
                    "short-document rate, so they are a ceiling."
                ),
            ],
        ),
    ]


PRIMER_BUILDERS = {
    "overview": overview_primer,
    "corpus": corpus_primer,
    "extraction": extraction_primer,
    "evidence": evidence_primer,
    "schema": schema_primer,
    "generated": generated_primer,
    "quality": quality_primer,
    "benchmarks": benchmarks_primer,
    "analytics": analytics_primer,
    "warehouse": warehouse_primer,
    "reproduce": reproduce_primer,
    "costs": costs_primer,
}


def primers_for(section_id: str) -> list[dict]:
    return PRIMER_BUILDERS[section_id]()
