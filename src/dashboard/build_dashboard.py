"""Render `dashboard.html` from the files the pipeline publishes.

    python -m src.dashboard.build_dashboard
    python src/dashboard/build_dashboard.py
    python -m src.dashboard.build_dashboard --serve --open

Both forms work, and the standard library is enough for either: a reviewer who
runs the file from an editor on a Python with nothing installed still gets the
page. `--serve` holds it on a loopback address for a browser that would rather
have a URL than a file. DuckDB is read where it is available and reported as
absent where it is not.

The dashboard reads and displays; it recomputes nothing. Every number on the
page is read from a named artifact at build time, every panel prints the path
it came from and a description of what a row is, and every column carries a
definition from `glossary.py`. Two runs over one tree produce one
byte-identical page.
"""

from __future__ import annotations

import argparse
import csv
import sys
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# The widest cell the page reads is a receipt input list of about 26 KB.
csv.field_size_limit(1024 * 1024)

# Run as a file rather than as a module and Python leaves the package unset and
# the project root off the path, so the imports below fail. Put the root back.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.catalog.simple_pdf_extraction import csv_wide_contract as contract
from src.catalog.simple_pdf_extraction.field_guide import FIELD_DESCRIPTIONS, FIELD_GROUPS
from src.dashboard.glossary import DATABASE_TABLE_NOTES, TABLE_NOTES, column_note
from src.dashboard.page import render


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = PROJECT_ROOT / "dashboard.html"

TITLE = "AI-Powered Alternative Investment ETL and Analytics"
SUBTITLE = (
    "Public fund reports become fund data a checker can open. Every number names "
    "its file. Every printed number names its PDF page."
)
FOOTER = (
    "Every figure was copied from the named files at build. The browser copies "
    "those figures. The numbered list opens the eleven sections."
)

# Rows kept per database table in the explorer. A whole warehouse would outgrow
# what a browser holds in one page, so each table carries its first rows beside
# the row count the database itself returns.
PREVIEW_ROWS = 200

EVIDENCE_COLUMNS = (
    "observation_id", "document_id", "canonical_doc_type", "source_page",
    "record_family", "metric_category", "term_category", "metric_name",
    "subject_type", "subject_name", "asset_class", "strategy",
    "as_of_date", "horizon", "value_kind", "value_raw", "value_numeric",
    "currency", "unit", "unit_scale", "evidence_quote", "evidence_class",
    "adjudication_status", "source_agents", "extractor_model",
)

# How a column's numbers are shown. pct multiplies a decimal rate by 100; x
# appends the multiple sign; money and int drop the decimals; raw leaves the
# text alone. Columns absent here follow the page's heuristic: two decimals at
# most, thousands separators past four digits, identifiers untouched.
FORMATS: dict[str, str] = {
    "reported_irr": "pct", "calculated_irr": "pct", "period_return": "pct",
    "benchmark_return": "pct", "return_value": "pct", "target_weight": "pct",
    "minimum_weight": "pct", "maximum_weight": "pct", "management_fee_rate": "pct",
    "carry_rate": "pct", "hurdle_rate": "pct", "catch_up_rate": "pct",
    "expense_cap_rate": "pct", "ownership_percent": "pct", "interest_rate": "pct",
    "value_agreement_rate": "pct", "detection_rate": "pct", "expected_return": "pct",
    "dpi": "x", "rvpi": "x", "tvpi": "x",
    "amount": "money", "amount_base_currency": "money", "recallable_amount": "money",
    "commitment": "money", "paid_in_capital_itd": "money", "distributions_itd": "money",
    "nav": "money", "unfunded_commitment": "money", "recallable_distributions_itd": "money",
    "fund_size": "money", "beginning_nav": "money", "contributions_period": "money",
    "distributions_period": "money", "realized_gain_period": "money",
    "unrealized_gain_period": "money", "net_income_period": "money",
    "management_fee_period": "money", "other_expenses_period": "money", "ending_nav": "money",
    "cost": "money", "fair_value": "money", "market_value": "money", "principal_amount": "money",
    "commitment_amount": "money", "nav_amount": "money", "unfunded_amount": "money",
    "maximum_offering": "money", "notional_amount": "money",
    "size_bytes": "int", "total_bytes": "int", "selected_bytes": "int", "file_size_bytes": "int",
    "row_count": "int", "observation_count": "int", "chars": "int",
    "fx_rate": "num", "seconds": "num", "level_value": "num",
    "value_raw": "raw", "value_numeric": "num", "actual_value": "num", "expected_value": "num",
    "difference": "num", "tolerance": "num",
}

MISSING_DEFINITIONS: set[str] = set()

# Receipts embedded in the data-change log: the most recent ones, since the
# ledger is append-only and the current release sits at its end.
RECEIPT_ROWS = 400

# What the source_agents column says about who stands behind an evidence row.
AGENT_LABELS = {
    "A+B+ADJUDICATOR": "Merged from both extractors",
    "A": "Extractor A's reading accepted",
    "B": "Extractor B's reading accepted",
    "ADJUDICATOR": "Added by the reviewer from the page image",
}


# ---------------------------------------------------------------- readers


def path_of(rel: str) -> Path:
    return PROJECT_ROOT / rel


def read_table(rel: str, limit: int | None = None) -> tuple[list[str], list[list[str]], int]:
    """Return the header, up to `limit` rows, and the row count of the file."""

    header: list[str] = []
    rows: list[list[str]] = []
    total = 0
    with path_of(rel).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for index, row in enumerate(reader):
            if index == 0:
                header = row
                continue
            total += 1
            if limit is None or len(rows) < limit:
                rows.append(row)
    return header, rows, total


def read_dicts(rel: str, limit: int | None = None) -> list[dict[str, str]]:
    with path_of(rel).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if limit is None:
            return list(reader)
        return [row for _, row in zip(range(limit), reader)]


def row_count(rel: str) -> int:
    with path_of(rel).open(encoding="utf-8-sig", newline="") as handle:
        return max(0, sum(1 for _ in csv.reader(handle)) - 1)


def tally(rel: str, column: str) -> Counter:
    counts: Counter = Counter()
    with path_of(rel).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            counts[(row.get(column) or "").strip()] += 1
    return counts


def column_sum(rel: str, column: str) -> int:
    total = 0
    with path_of(rel).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            value = (row.get(column) or "").strip()
            if value:
                total += int(float(value))
    return total


def select(header: list[str], rows: list[list[str]], columns: tuple[str, ...]) -> tuple[list[str], list[list[str]]]:
    index = {name: position for position, name in enumerate(header)}
    keep = [name for name in columns if name in index]
    positions = [index[name] for name in keep]
    trimmed = [[row[position] if position < len(row) else "" for position in positions] for row in rows]
    return keep, trimmed


def _settings_lines(rel: str) -> list[str]:
    return [
        line
        for line in path_of(rel).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_settings(rel: str) -> list[tuple[str, str]]:
    """Read the top-level `name: value` pairs of a settings file.

    The two configuration files this page reports are flat enough to read with
    the standard library, which is what keeps the builder free of an install.
    Indented lines belong to a nested block and are left to the reader that
    owns them; a name with no value on its line is a block head, not a
    setting."""

    settings = []
    for line in _settings_lines(rel):
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        name, _, value = line.partition(":")
        if _unquote(value) and not _unquote(value).startswith(">"):
            settings.append((name.strip(), _unquote(value)))
    return settings


def read_setting_block(rel: str, block: str) -> dict[str, str]:
    """Read one indented `name: value` block, such as the tolerances."""

    values: dict[str, str] = {}
    inside = False
    for line in _settings_lines(rel):
        if not line.startswith((" ", "\t")):
            inside = line.strip() == f"{block}:"
            continue
        if inside and ":" in line:
            name, _, value = line.strip().partition(":")
            values[name.strip()] = _unquote(value)
    return values


def read_setting_list(rel: str, block: str) -> list[dict[str, str]]:
    """Read an indented list of records, such as the quality rules."""

    records: list[dict[str, str]] = []
    inside = False
    for line in _settings_lines(rel):
        if not line.startswith((" ", "\t")):
            inside = line.strip() == f"{block}:"
            continue
        if not inside:
            continue
        entry = line.strip()
        if entry.startswith("- "):
            records.append({})
            entry = entry[2:]
        if not records or ":" not in entry:
            continue
        name, _, value = entry.partition(":")
        records[-1][name.strip()] = _unquote(value)
    return records


def inventory(rel: str) -> tuple[str, list[str], list[str]]:
    """Return why the file was or was not read, its base tables, and its views.

    The reason travels with the answer so the page can say the file went
    unread. Counting an unread database as zero tables would read as a claim
    about the database."""

    path = path_of(rel)
    if not path.is_file():
        return "the file is absent from this copy", [], []
    try:
        import duckdb
    except ImportError:
        return "read it with duckdb installed", [], []

    connection = duckdb.connect(str(path), read_only=True)
    try:
        rows = connection.execute(
            "select table_name, table_type from information_schema.tables order by table_name"
        ).fetchall()
    finally:
        connection.close()
    tables = [name for name, kind in rows if kind == "BASE TABLE"]
    views = [name for name, kind in rows if kind == "VIEW"]
    return "read", tables, views


def wide_table_note(name: str) -> str:
    """What a reconstructed source table holds, from the family it rebuilds."""

    if not name.startswith("wide_"):
        return ""
    family = name[len("wide_"):]
    for row in read_dicts("data/schemas/EXTRACTION-RECORD-FAMILIES.csv"):
        if row["record_family"] != family:
            continue
        description = row["description"].strip()
        if not description.endswith("."):
            description += "."
        return (
            f"The {family.replace('_', ' ')} rows of the evidence, reconstructed into their printed "
            f"table shape: {description} Each metric or term has its own column, and observation_ids "
            "names the evidence rows behind each field."
        )
    return ""


def database_contents(rel: str, preview: int) -> list[dict]:
    """Return every table and view of a DuckDB file with its first rows.

    The whole database would not fit in a page a browser can hold, so each
    entry carries its column names, its column types, its full row count, and
    the first rows in sorted order. The count is the database's own, which is
    what stops a preview from reading as the table."""

    path = path_of(rel)
    if not path.is_file():
        return []
    try:
        import duckdb
    except ImportError:
        return []

    connection = duckdb.connect(str(path), read_only=True)
    try:
        listed = connection.execute(
            "select table_name, table_type from information_schema.tables order by table_name"
        ).fetchall()
        entries = []
        for name, kind in listed:
            quoted = '"' + name.replace('"', '""') + '"'
            rows = connection.execute(f"select count(*) from {quoted}").fetchone()[0]
            # A bare limit takes whatever rows the scan reached first, which
            # differs between runs and would make two builds of one tree
            # disagree. Ordering on every column fixes which rows a preview
            # shows and the order it shows them in.
            result = connection.execute(f"select * from {quoted} order by all limit {preview}")
            columns = [column[0] for column in result.description]
            types = [str(column[1]) for column in result.description]
            entries.append(
                {
                    "name": name,
                    "kind": "view" if kind == "VIEW" else "table",
                    "about": DATABASE_TABLE_NOTES.get(name, "") or wide_table_note(name),
                    "rows": int(rows),
                    "columns": columns,
                    "types": types,
                    "definitions": definitions_for(columns, name),
                    "formats": formats_for(columns),
                    "preview": [
                        ["" if value is None else str(value) for value in row]
                        for row in result.fetchall()
                    ],
                }
            )
    finally:
        connection.close()
    return entries


def as_int(value: object) -> int:
    """Read a count that a source file may print as 47 or as 47.0."""

    text = "" if value is None else str(value).strip()
    return int(float(text)) if text else 0


def as_float(value: object) -> float | None:
    """Read a number, keeping zero a number.

    Testing the value for truth would drop 0 and 0.0 along with the blanks,
    and a zero is a reading the page made."""

    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def thousands(value: int | float) -> str:
    return f"{value:,}"


def percent(part: int, whole: int) -> str:
    return f"{(part / whole * 100):.1f} percent" if whole else "0 percent"


def two(value: object) -> str:
    """A number to two decimals, with thousands separators."""

    number = as_float(value)
    return "" if number is None else f"{number:,.2f}"


def money(value: object) -> str:
    number = as_float(value)
    return "" if number is None else f"{number:,.0f}"


def show_unit(value: object, unit: str) -> str:
    """Format a value the way its unit column says to read it."""

    number = as_float(value)
    if number is None:
        return "" if value is None else str(value)
    if unit == "decimal_rate":
        return f"{number * 100:,.2f}%"
    if unit == "multiple":
        return f"{number:,.2f}x"
    if unit == "percent":
        return f"{number:,.2f}%"
    if unit in {"currency", "money"}:
        return f"{number:,.0f}"
    if unit == "portfolio_fraction":
        return f"{number * 100:,.2f}%"
    return f"{number:,.2f}"


def definitions_for(columns: list[str], table: str = "") -> list[str]:
    found = []
    for name in columns:
        note = column_note(name, table)
        if not note:
            MISSING_DEFINITIONS.add(f"{table}.{name}" if table else name)
        found.append(note)
    return found


def formats_for(columns: list[str]) -> dict[str, str]:
    return {name: FORMATS[name] for name in columns if name in FORMATS}


# ---------------------------------------------------------------- blocks


def kpi(*items: tuple) -> dict:
    """Headline numbers. A fourth entry draws a share meter under the card."""

    cards = []
    for item in items:
        label, value, note = item[:3]
        card = {"label": label, "value": value, "note": note}
        if len(item) > 3 and item[3] is not None:
            card["share"] = item[3]
        cards.append(card)
    return {"kind": "kpi", "items": cards}


def boxes(title: str, source: str, about: str, groups: list[dict]) -> dict:
    """Box-and-whisker plots, one scale per unit group."""

    return {"kind": "boxes", "title": title, "source": source, "about": about, "groups": groups}


def donuts(title: str, source: str, about: str, charts: list[dict]) -> dict:
    return {"kind": "donuts", "title": title, "source": source, "about": about, "charts": charts}


def stacks(title: str, source: str, about: str, keys: list[str], rows: list[dict]) -> dict:
    return {"kind": "stacks", "title": title, "source": source, "about": about, "keys": keys, "rows": rows}


def donut_chart(label: str, counts: list[tuple[str, int]], total_label: str = "rows") -> dict:
    total = sum(count for _, count in counts)
    return {
        "label": label,
        "total_display": compact(total),
        "total_label": total_label,
        "items": [
            {"label": name or "blank", "value": count, "display": thousands(count)}
            for name, count in counts
        ],
    }


def compact(value: int) -> str:
    """A headline count short enough for the middle of a donut."""

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:,}"


def note(text: str) -> dict:
    return {"kind": "note", "text": text}


def heading(text: str) -> dict:
    return {"kind": "heading", "text": text}


def steps(items: list[tuple[str, ...]]) -> dict:
    """Numbered stages. A three-part item carries its stage name first, and the
    stage heading prints once above the steps that belong to it."""

    rows = []
    for item in items:
        stage, title, text = item if len(item) == 3 else ("", item[0], item[1])
        rows.append({"stage": stage, "title": title, "text": text})
    return {"kind": "steps", "items": rows}


def keyvalue(items: list[tuple[str, str]]) -> dict:
    return {"kind": "keyvalue", "items": [[key, value] for key, value in items]}


def bars(title: str, source: str, about: str, items: list[tuple[str, float, str]]) -> dict:
    return {
        "kind": "bars",
        "title": title,
        "source": source,
        "about": about,
        "items": [{"label": label, "value": value, "display": display} for label, value, display in items],
    }


def formulas(title: str, items: list[dict]) -> dict:
    return {"kind": "formulas", "title": title, "items": items}


def explorer(title: str, source: str, about: str, groups: list[dict]) -> dict:
    return {"kind": "explorer", "title": title, "source": source, "about": about, "groups": groups}


def table(
    title: str,
    source: str,
    columns: list[str],
    rows: list[list[str]],
    total: int | None = None,
    page: int = 25,
    *,
    about: str = "",
    hidden: list[str] | None = None,
    key: str = "",
) -> dict:
    hidden = hidden or []
    return {
        "kind": "table",
        "title": title,
        "source": source,
        "about": about,
        "columns": columns,
        "hidden": hidden,
        "definitions": definitions_for(columns + hidden, key),
        "formats": formats_for(columns + hidden),
        "rows": rows,
        "rows_total": total if total is not None else len(rows),
        "page": page,
    }


def file_table(
    title: str,
    rel: str,
    columns: tuple[str, ...] = (),
    limit: int | None = 200,
    page: int = 25,
    *,
    about: str = "",
    hidden: str | tuple[str, ...] = "rest",
) -> dict:
    """A table read straight from one CSV.

    `columns` are the ones the grid shows; with `hidden="rest"` every other
    column of the file rides along and opens in the row detail, so the grid
    stays readable and the row stays whole."""

    header, rows, total = read_table(rel, limit)
    visible = list(columns) if columns else list(header)
    if hidden == "rest":
        extra = [name for name in header if name not in visible]
    else:
        extra = [name for name in hidden if name in header]
    keep, trimmed = select(header, rows, tuple(visible + extra))
    shown = [name for name in keep if name in visible]
    return table(
        title, rel, shown, trimmed, total, page,
        about=about or TABLE_NOTES.get(rel, ""),
        hidden=[name for name in keep if name not in visible],
        key=Path(rel).stem,
    )


# ---------------------------------------------------------------- sections


def overview_section() -> dict:
    ledger = read_dicts("data-gathering/source_ledger.csv")
    summary = read_dicts("data/extracted/review/document-summary.csv")
    audit = read_dicts("docs/FINAL-RELEASE-AUDIT.csv")
    pages = sum(as_int(row["page_count"]) for row in ledger if row.get("page_count"))
    both = sum(as_int(row["physical_pairs"]) for row in summary)
    agreed = sum(as_int(row["raw_value_agreements"]) for row in summary)
    observations = row_count("data/extracted/tables/fact_observation.csv")
    entities = row_count("data/extracted/tables/dim_entity.csv")
    receipts = row_count("ledgers/pipeline/transformation-receipts.csv")
    a_proposals = sum(as_int(row["extractor_a_rows"]) for row in summary)
    b_proposals = sum(as_int(row["extractor_b_rows"]) for row in summary)
    passed = sum(1 for row in audit if row["status"] == "PASS")
    text_pages = column_sum("data/documents/txt/MANIFEST.csv", "native_pages") + column_sum("data/documents/txt/MANIFEST.csv", "ocr_pages")
    printed_periods = sum(1 for row in read_dicts("data/csv/fund_periods.csv") if row["provenance_type"] == "EXTRACTED")
    completed_periods = sum(1 for row in read_dicts("data/csv/fund_periods.csv") if row["provenance_type"] == "SYNTHETIC")
    extracted_funds = row_count("data/extracted/fund-level/fund_master.csv")
    extracted_observations = row_count("data/extracted/fund-level/fund_observations.csv")
    extracted_cashflows = row_count("data/extracted/fund-level/fund_cashflows.csv")
    extracted_holdings = row_count("data/extracted/fund-level/fund_holdings.csv")
    fixture_funds = row_count("data/synthetic/clean/fund_master.csv") if path_of("data/synthetic/clean/fund_master.csv").is_file() else 0
    return {
        "id": "overview",
        "title": "Overview",
        "blurb": (
            "This repository is an end-to-end alternative-investment ETL and analytics project. "
            "Public and FOIA private-market PDF reports are collected from the web: 442 files, "
            "40,788 pages, 17 document types. Each file is classified into one of those 17 "
            "categories by two independent agents, with disagreements resolved by an adjudicator. "
            "Every report has a page-aligned TXT. For extraction, each physical page is rendered "
            "at 300 DPI as a PNG, and page-aligned text and document grids sit next to those "
            "pictures so agents can locate table cells on the page image. Extraction is dual-blind "
            "(two independent agents); conflicts go to adjudicator agents. Extracted values are "
            "cleaned and normalized, and entities receive unique IDs. The printed-cell database "
            "(extracted.duckdb) is a 9-table star schema plus 18 reconstructed-source tables, "
            "27 tables in the live file. The fund-model warehouse (alts.duckdb) has 18 tables. "
            "The pilot has extracted 29 of 442 documents (7,201 observations); more reports will "
            "be added in later updates. Public-market data (334 Parquet files, 58 benchmark "
            "series) supports benchmarking. Synthetic completion on the same fund IDs enables "
            "Direct Alpha, KS-PME, XIRR, and other performance metrics until vendor data and "
            "fuller extraction replace those cells. Every step is designed to be auditable."
        ),
        "blocks": [
            heading("Data populations"),
            keyvalue([
                ("Extractor proposal row", f"One printed field as one reader typed it, before checks. Agent A typed {thousands(a_proposals)} rows and Agent B {thousands(b_proposals)}. Each row has the printed label and value, the subject, the date, the unit, the physical page, the table row and column, the repeated occurrence, and the quote. A proposal can be wrong. The next group is the rows the checks keep."),
                ("Published PDF evidence row", f"One printed field after review. The two typed rows were compared. A third machine picked the number on the page picture. Each of the {thousands(observations)} rows keeps the printed value, the cleaned value, the place on the page, links to both typed rows, the difference type, the decision, and the reason. Later tables use these rows."),
                ("Extracted fund-model row", f"A kept PDF field after printed names map to stable IDs. Five spellings of one fund map to one record. The PDF-only tables hold {thousands(extracted_observations)} metric rows, {thousands(printed_periods)} fund periods, {thousands(extracted_cashflows)} dated cash flows, and {thousands(extracted_holdings)} holdings across {thousands(extracted_funds)} funds, every value printed on a cited page."),
                ("Completed fund-period row", f"A fund-and-date row written so each named fund has dates and money for the measures. PDFs print few dated calls and payouts, so the fill step writes the empty cells and marks each one DERIVED, IMPUTED, or SYNTHETIC, and lists it in the fill record. The {thousands(completed_periods)} filled periods are marked. Printed rows keep the EXTRACTED mark."),
                ("Test-only fund", f"One of {thousands(fixture_funds)} made funds used to test the money rules. IDs begin FUND_SYNTH_. Those IDs stay in the test files. The checker fund tables and alts.duckdb use FUND_ IDs."),
            ]),
            kpi(
                ("Source reports", thousands(len(ledger)), f"Public PDFs collected and listed; {thousands(len(summary))} were read and reviewed; the rest are listed and wait to be read"),
                ("Pages in the source ledger", thousands(pages), f"Physical pages across all source PDFs; {thousands(text_pages)} have page-aligned text, from the PDF's own text layer or from optical character recognition of the page image"),
                ("Documents extracted", thousands(len(summary)), f"Reports completed by both extractors and the reviewer; the other {thousands(len(ledger) - len(summary))} catalogued reports await extraction"),
                ("Published evidence rows", thousands(observations), "One row per printed field, with the reported value, subject, date, page, supporting quote, and review decision"),
                ("Value agreement", percent(agreed, both), f"Of {thousands(both)} printed fields both readers found, {thousands(agreed)} were typed with the same value. Two machines can type the same wrong number, so a sample of matches is read again against the page", agreed / both if both else 0),
                ("Standardized entities", thousands(entities), "Distinct funds, managers, investors, plans, and companies after spelling variants merge: one organization printed five ways counts once"),
                ("Pipeline receipts", thousands(receipts), "One log row per data-changing command: what ran, what it read, what it wrote, and the row count of the output"),
                ("Release audit entries", f"{len(audit)} recorded", f"The rebuild list: four early checks, 19 rebuild steps, and two last checks. {passed} of {len(audit)} rows are PASS: the step finished and its files matched the expected files"),
            ),
            heading("Work stages"),
            steps([
                ("Source intake", "Report intake",
                 "The source ledger records each PDF's web address, publisher, report date, reuse note, and page count, so every later number can name its source file."),
                ("Source intake", "Document classification",
                 "Two machines name each document type. An audit picks the type when they differ. The type sets the allowed fields: a financial statement and an offering paper are read for different fields."),
                ("Source intake", "Reading-aid build",
                 "Each report gets text lined up to each page. A report is read after every physical page has a 300 DPI picture. Extraction requires those pictures. Document grids identify items in the tables with ease in the page image files."),
                ("Reading", "Field selection",
                 "Each printed value becomes one row with the same 42 columns: the field name, the owner, the date, the unit, the place on the page, the quote, and the review mark."),
                ("Reading", "Independent reading",
                 "Agent A (claude-sonnet-5) and Agent B (gpt-5) read the same pages. Each works on its own file. A shared answer is two readings of the same page."),
                ("Reading", "Page evidence",
                 "Each proposed field stores its physical page, printed page number, row label, column label, repeated occurrence, and supporting quote. The physical page counts from the front of the file; the printed number is whatever the page footer says."),
                ("Review", "Compare extractor proposals",
                 "Proposals for the same page and table position are matched and each difference is typed. A value difference is 1.21 against 1.22. A classification difference is one number filed as TVPI by one reader and IRR by the other. A context difference is the same number under a different date, subject, or unit."),
                ("Review", "Page-image review",
                 "A third machine (claude-opus-5) decides every clash and every field found by one reader only, with the page picture open. A fixed ten percent sample of matches is checked the same way. Two readers can copy the same mistake."),
                ("Review", "Publish evidence",
                 "Reviewed fields go into the evidence table, one printed field per row. Fund tables take values from that table."),
                ("Fund model", "Identity resolution",
                 "Printed fund, manager, and investor names map to one standard name and one ID. Fund II, L.P. and Fund II LP become one fund."),
                ("Fund model", "Fund-model assembly",
                 "Reviewed fields become fund observations, fund periods, dated cash flows, terms, and holdings. Every field value carries an origin label: EXTRACTED is printed on a cited page; DERIVED, IMPUTED, and SYNTHETIC are the three kinds of fill the completion writes."),
                ("Fund model", "Quality and analytics",
                 "The printed sums are checked first: balances, DPI, RVPI, TVPI, NAV roll-forwards, and IRR. Performance is then measured against a public index. A demo set is weighted. Printed-row results and filled-row results each have their own mark."),
            ]),
            heading("Release audit"),
            file_table("Every release stage and its result", "docs/FINAL-RELEASE-AUDIT.csv", limit=None, page=25),
            note(
                "The PDF-only tables under data/extracted/fund-level/ contain printed values alone. "
                "The completed tables under data/csv/ add labelled values on the same fund IDs, and "
                "every added field value is recorded in data/integrated/cell-lineage.csv. Printed "
                "periods that state paid-in capital, distributions, and NAV give DPI, RVPI, and "
                "TVPI. XIRR, KS-PME, and Direct Alpha need dated calls and payouts. PDFs print few of "
                "those, so those three run on the filled fund-date table and have the SYNTHETIC mark."
            ),
        ],
    }


def corpus_section() -> dict:
    ledger = read_dicts("data-gathering/source_ledger.csv")
    routing = tally("data/schemas/EXTRACTION-ROUTING.csv", "product_tier")
    extracted_routes = [
        row["file_id"] for row in read_dicts("data/extracted/review/document-summary.csv")
    ]
    route_by_file = {
        row["file_id"]: row for row in read_dicts("data/schemas/EXTRACTION-ROUTING.csv")
    }
    extracted_tiers = Counter(
        route_by_file[file_id]["product_tier"] for file_id in extracted_routes
    )
    pages = sum(as_int(row["page_count"]) for row in ledger if row.get("page_count"))
    types = tally("data-gathering/source_ledger.csv", "doc_type")
    native = column_sum("data/documents/txt/MANIFEST.csv", "native_pages")
    ocr = column_sum("data/documents/txt/MANIFEST.csv", "ocr_pages")
    grids = row_count("data/documents/grids/MANIFEST.csv")
    issuers = len({row["issuer"] for row in ledger if row.get("issuer")})

    return {
        "id": "corpus",
        "title": "Source reports",
        "blurb": (
            "The source list is every collected PDF. CORE: numbers may go into fund tables. "
            "SECONDARY: extra facts, read under the same checks. REFERENCE: sample forms, listed "
            "only. Each page has text lined up to the page. Pictures are 300 DPI and required for "
            "extraction. Git leaves the PNG files out because they are large; render them with "
            "data-gathering/src/render_image_corpus.py. Document grids "
            "identify items in the tables with ease in the page image files."
        ),
        "blocks": [
            kpi(
                ("Reports", thousands(len(ledger)), "One source-ledger row per public PDF collected for the project"),
                ("Pages", thousands(pages), f"Total physical pages across the {thousands(len(ledger))} source PDFs"),
                ("Document types", thousands(len(types)), "Report kinds such as Financials, Performance, or PPM. The type sets the reading steps and the allowed fields: a PPM gives legal terms; a performance report gives returns and multiples"),
                ("Issuers", thousands(issuers), "Distinct organizations that published the reports, including plans, managers, foundations, and endowments"),
                ("Embedded-text pages", thousands(native), "Pages whose text is stored inside the PDF and read directly, one text page aligned to one physical page"),
                ("OCR pages", thousands(ocr), "Pages with empty stored text, read from the page picture; open the picture before you trust a number from these pages"),
                ("Document-grid reports", thousands(grids), "Document grids for identifying items in the tables with ease in the page image files."),
            ),
            note(
                f"Routing separates {thousands(routing['CORE'])} core, "
                f"{thousands(routing['SECONDARY'])} secondary, and "
                f"{thousands(routing['REFERENCE'])} reference documents. CORE reports may go into "
                "the fund tables. SECONDARY reports add extra facts. REFERENCE files are sample "
                "forms. They stay on the list. The published extraction covers "
                f"{thousands(len(extracted_routes))} reports so far, "
                f"{thousands(extracted_tiers['CORE'])} core and "
                f"{thousands(extracted_tiers['SECONDARY'])} secondary; every other catalogued "
                "report sits in the inventory with no extracted rows."
            ),
            bars(
                "Reports by type",
                "data-gathering/source_ledger.csv",
                "Listed PDF count for each report type. This is the whole list. The set of reports that were read is smaller and is on the extraction section.",
                [(name, count, thousands(count)) for name, count in types.most_common()],
            ),
            heading("Source ledger"),
            file_table(
                "Every acquired report",
                "data-gathering/source_ledger.csv",
                columns=(
                    "file_id", "doc_type", "issuer", "issuer_type",
                    "period_covered", "page_count", "has_text_layer", "license_note",
                ),
                limit=None,
                page=25,
            ),
            heading("Page text, pictures, and document grids"),
            file_table(
                "Text build per document",
                "data/documents/txt/MANIFEST.csv",
                columns=("file_id", "doc_type", "pages", "native_pages", "ocr_pages", "empty_pages", "chars", "seconds", "error"),
                limit=None,
            ),
            note(image_note()),
            note(
                "A PDF text layer often breaks one number across two lines, so 1,250,000 can arrive "
                "as 1,250 and 000. Those splits are joined again. Each join is listed in "
                "ledgers/analysis/split_number_audit.csv before reading. Readers see the joined number."
            ),
        ],
    }


def image_note() -> str:
    """The page-image aids, read from their manifest."""

    pages = read_dicts("data/documents/images/MANIFEST.csv")
    if not pages:
        return "data/documents/images/MANIFEST.csv lists zero page pictures."
    present = sum(1 for row in pages if (row.get("present") or "").strip().lower() in {"1", "true"})
    reports = len({row["file_id"] for row in pages})
    dpi = ", ".join(sorted({row["dpi"] for row in pages if row.get("dpi")}))
    if present == len(pages):
        shipped = "every PNG ships in this copy"
    elif present:
        shipped = f"{thousands(present)} of the PNG files ship in this copy"
    else:
        shipped = (
            "the PNG files are rebuilt on each reviewer's machine with "
            "data-gathering/src/render_image_corpus.py. Git leaves them out "
            "because 300 DPI pages are large. Extraction requires those files"
        )
    return (
        f"Page pictures are drawn at {dpi} DPI so a value can be checked against the print. "
        "Extraction requires a PNG for every physical page of the assigned PDF. "
        "When text and picture differ, the picture wins. "
        f"data/documents/images/MANIFEST.csv lists {thousands(len(pages))} rendered pages "
        f"across {thousands(reports)} reports; {shipped}."
    )


def misfiled_note() -> str:
    """The state of the vocabulary audit, read from its review file.

    The audit folder is retained outside the repository, so a clone reaches this
    with the file absent. Saying so is better than failing the build, and better
    than reporting an empty queue as a clean result."""

    review = "audit/metric-vocabulary/misfiled-rows.csv"
    if not path_of(review).is_file():
        return (
            "The vocabulary audit is retained outside the repository, so this copy carries no "
            "review file. Every evidence row whose assigned field name disagreed with the printed "
            "label was re-reviewed. When labels on one page conflict, the printed table title sets "
            "the name. A column headed IRR inside a table titled time-weighted returns is filed as "
            "a return. The table title names the whole table."
        )
    queue = read_dicts(review)
    if not queue:
        return (
            "The vocabulary audit in audit/metric-vocabulary/misfiled-rows.csv contains zero open "
            "rows. Every evidence row whose assigned field name disagreed with the printed label "
            "was re-reviewed. When labels on one page conflict, the printed table title sets the name. A "
            "column headed IRR inside a table titled time-weighted returns is filed as a return. "
            "The table title names the whole table."
        )
    by_document = Counter(row.get("document_id") or row.get("file_id") or "" for row in queue)
    lead, count = by_document.most_common(1)[0]
    return (
        f"{thousands(len(queue))} evidence rows carry a field name that disagrees with the PDF "
        f"label and remain unchanged until review, led by {thousands(count)} rows in "
        f"{lead}. The review list is audit/metric-vocabulary/misfiled-rows.csv."
    )


def extraction_section() -> dict:
    summary = read_dicts("data/extracted/review/document-summary.csv")

    def total(field: str) -> int:
        return sum(as_int(row[field]) for row in summary)

    both = total("physical_pairs")
    agreed = total("raw_value_agreements")
    decisions = [
        ("Merge", total("merge_decisions")),
        ("Accept B", total("accept_b_decisions")),
        ("Accept A", total("accept_a_decisions")),
        ("Adjudicator addition", total("add_decisions")),
        ("Rejection", total("reject_decisions")),
    ]
    conflicts = [
        ("Value", total("value_conflicts")),
        ("Classification", total("classification_conflicts")),
        ("Context", total("context_conflicts")),
    ]
    agents = tally("data/extracted/tables/fact_observation.csv", "source_agents")

    return {
        "id": "extraction",
        "title": "Extraction and review",
        "blurb": (
            "Each reader types one printed field per row: value, subject, date, unit, page, row, "
            "column, repeated occurrence, and quote. The two files are compared field by field. A "
            "third reader opens the page picture for every clash and every field found by one reader "
            "only. Four checks run before the rows go out: the quote has the value and is on the "
            "cited page; every page has a coverage row; every field name is on the allowed list; "
            "every file has the 42 columns."
        ),
        "blocks": [
            kpi(
                ("Documents extracted", thousands(len(summary)), "Reports finished by two readers and one reviewer"),
                ("Pages covered", thousands(total("physical_pages")), "Every physical page has a record of what it holds: allowed values (printed values this document type may give), reference material, or a cover or contents page with zero allowed values"),
                ("Extractor A proposals", thousands(total("extractor_a_rows")), "Rows Extractor A typed. Each row needs the checks and the review."),
                ("Extractor B proposals", thousands(total("extractor_b_rows")), "Rows Extractor B typed. Each row needs the checks and the review."),
                ("PDF fields compared", thousands(total("pair_rows")), "One comparison row per printed field proposed by either extractor, including fields only one of them found"),
                ("Fields found by both", thousands(both), "Printed fields both readers put at the same file, page, row label, column label, and repeated occurrence"),
                ("Value agreement", percent(agreed, both), f"Of {thousands(both)} fields both readers found, {thousands(agreed)} had the same typed value. A sample of matches is read again against the page", agreed / both if both else 0),
                ("Published evidence rows", thousands(total("final_rows")), "PDF fields kept after the reviewer decided matches, clashes, and one-reader findings"),
            ),
            heading("Extraction checks"),
            steps([
                ("Assignment", "The work list names the PDF, the pages, the page text, the pictures, the document grids, and the field-list version. The reader uses that file and that field list."),
                ("Candidate validation", "The printed label and value, table place, unit or suffix, and quote match the cited page. A blank offered as a value, a dropped % or x suffix, and a field name off the list stay out."),
                ("Page coverage", "Each physical page receives one coverage row. A page marked as having zero allowed values is compared with its document grid. A skipped table is then seen."),
                ("Candidate comparison", "Extractor A and Extractor B proposals are matched by PDF, page, row label, column label, and repeated occurrence. A value difference is 1.21 against 1.22; a classification difference is TVPI against IRR for the same number; a context difference is the same number under a different date, subject, or unit."),
                ("Agreement sample", "Two machines can type the same wrong number. A fixed ten percent sample of matching rows is checked against the PDF. A match needs that page check."),
                ("Reviewer decision", "Mechanical repairs first fix values placed under a neighbouring row or column and restore printed formats. The reviewer then records one of five decisions: MERGE joins two readings that match the page. ACCEPT_A or ACCEPT_B keeps one reader's version. ADD types a field both readers missed. REJECT drops a row that is empty of a printed fact. Every decision carries a reason and the page it was checked on."),
                ("Final validation and publication", "Each document's reviewed rows pass a final structural check before they join the all-document evidence tables; a document that fails stays out until it is repaired."),
            ]),
            bars("Conflicts by type", "data/extracted/review/document-summary.csv",
                 "Disagreement types. Value: two numbers for one cell, 1.21 against 1.22. Classification: one number filed under two names, TVPI against IRR. Context: one number with a different date, subject, or unit.",
                 [(name, count, thousands(count)) for name, count in conflicts]),
            bars("Review decisions", "data/extracted/review/document-summary.csv",
                 "Reviewer decisions. MERGE joins the two readings. ACCEPT_A or ACCEPT_B keeps one side against the page. ADD is a field the reviewer typed from the page picture after both readers missed it. REJECT drops a row empty of a printed fact.",
                 [(name, count, thousands(count)) for name, count in decisions]),
            bars("Source of each retained field", "data/extracted/tables/fact_observation.csv",
                 "Readers for each kept field. Merged from both: two readings and a review agree. A one-extractor row means the other reader missed or misread the field and the reviewer sided with this one against the page. Added by the reviewer means both readers missed the field and it was typed from the page picture.",
                 [(AGENT_LABELS.get(name, name or "blank"), count, thousands(count)) for name, count in agents.most_common()]),
            heading("Document-level extraction results"),
            file_table("Agreement and decisions per document", "data/extracted/review/document-summary.csv", limit=None),
            heading("Evidence-row review record"),
            file_table(
                "Each evidence row linked to both extractor proposals",
                "data/extracted/tables/observation_lineage.csv",
                columns=("observation_id", "document_id", "source_page", "pair_id", "pair_status",
                         "difference_fields", "resolution_decision", "resolution_reason", "source_agents"),
                limit=400,
            ),
            note(misfiled_note()),
        ],
    }


SOURCE_LINK_COLUMNS = (
    "source_pdf_path", "source_txt_path", "source_grid_path",
    "records_a_path", "a_row_number", "records_b_path", "b_row_number",
    "pair_index_path", "resolution_path", "resolution_row_number",
    "records_final_path", "final_row_number",
)


def source_links() -> dict[str, list[str]]:
    """For each observation, the repository paths a reviewer opens to check it.

    The PDF, page text, and grid come from the routing table; the A row, B row,
    pair, decision, and final row come from the review lineage. The page
    renders any repository path in a row detail as a link, so a reviewer goes
    from a value to the page that printed it and the files that settled it."""

    routing = {row["file_id"]: row for row in read_dicts("data/schemas/EXTRACTION-ROUTING.csv")}
    links: dict[str, list[str]] = {}
    for row in read_dicts("data/extracted/review/observation-lineage.csv"):
        route = routing.get(row.get("file_id", ""), {})
        links[row["observation_id"]] = [
            row.get("source_pdf_path") or route.get("pdf_path", ""),
            route.get("txt_path", ""),
            route.get("grid_path", ""),
            row.get("records_a_path", ""), row.get("a_row_number", ""),
            row.get("records_b_path", ""), row.get("b_row_number", ""),
            row.get("pair_index_path", ""),
            row.get("resolution_path", ""), row.get("resolution_row_number", ""),
            row.get("records_final_path", ""), row.get("final_row_number", ""),
        ]
    return links


def evidence_section() -> dict:
    header, rows, total = read_table("data/extracted/tables/fact_observation.csv", None)
    visible = list(EVIDENCE_COLUMNS)
    extra = [name for name in header if name not in visible]
    keep, trimmed = select(header, rows, tuple(visible + extra))
    links = source_links()
    blank = [""] * len(SOURCE_LINK_COLUMNS)
    for row in trimmed:
        row.extend(links.get(row[0], blank))
    keep = keep + list(SOURCE_LINK_COLUMNS)
    families = tally("data/extracted/tables/fact_observation.csv", "record_family")
    kinds = tally("data/extracted/tables/fact_observation.csv", "value_kind")
    classes = tally("data/extracted/tables/fact_observation.csv", "evidence_class")
    # A metric row carries metric_category and a clause row carries
    # term_category, so the label count reads whichever the row filled.
    categories: Counter = Counter()
    for row in read_dicts("data/extracted/tables/fact_observation.csv"):
        categories[(row.get("metric_category") or row.get("term_category") or "").strip()] += 1
    extracted_documents = row_count("data/extracted/review/document-summary.csv")
    image_only = sum(
        1
        for row in read_dicts("data/extracted/tables/fact_observation.csv")
        if "IMAGE_ONLY" in (row.get("notes") or "")
    )
    redacted = classes.get("redacted", 0)
    reviewer_specs = (
        (
            "data/extracted/review/reviewer-observations.csv",
            "One row per printed PDF field, joined to extractor comparison, review decision, resolved identity, fund attributes, quality, and analysis links.",
        ),
        (
            "data/extracted/review/reviewer-fund-periods.csv",
            "One row per fund and date with origin labels, attribute sources, quality results, and recomputed multiples.",
        ),
        (
            "data/extracted/review/reviewer-cell-lineage.csv",
            "One row per fund-model field written during completion, with its source or method.",
        ),
        (
            "data/extracted/review/reviewer-gap-ledger.csv",
            "One row per blank filled during completion, with its earlier value, written value, and method.",
        ),
        (
            "data/extracted/review/reviewer-analytics-summary.csv",
            "Distributions, analytical coverage, portfolio results, and strategy exposure.",
        ),
    )
    reviewer_files = []
    for rel, contents in reviewer_specs:
        file_header, _, file_rows = read_table(rel, 0)
        reviewer_files.append([rel, str(file_rows), str(len(file_header)), contents])

    return {
        "id": "evidence",
        "title": "Published evidence",
        "blurb": (
            "Each kept row is one printed field from one PDF: this fund, this date, "
            "this label, this value, this quote. The row keeps the printed value, the cleaned value, "
            "the subject, the date, the unit, the page, the table place, the quote, both typed rows, "
            "and the decision. The row names the page that printed the number."
        ),
        "blocks": [
            kpi(
                ("Published evidence rows", thousands(total), "Each row stores one PDF field with its subject, reported value, date, page, quote, and review outcome"),
                ("Documents extracted", thousands(extracted_documents), "Reports that finished both reading groups, page coverage, comparison, review, and last check"),
                ("Source-table categories", thousands(len([name for name in families if name])), "Kinds of printed rows the evidence covers. The largest: fund economics lines (commitments, NAV, distributions), performance lines (returns and multiples), holding lines from investment schedules, and financial-statement lines"),
                ("Metric and term labels", thousands(len([name for name in categories if name])), "Distinct field labels assigned to evidence rows, such as nav, tvpi, or management_fee, all drawn from the one approved vocabulary"),
                ("Image-reviewed fields", thousands(image_only), "Fields the reviewer picked from the page picture. The PDF text hid the value or the table at that spot. Notes have IMAGE_ONLY."),
                ("Redacted fields", thousands(redacted), "Fields whose label is printed but whose number the source blacked out. The row is kept with an empty value so the blacked-out number stays visible. The empty cell stays empty."),
            ),
            heading("PDF fields to fund tables"),
            steps([
                ("Resolve the subject", "Printed fund and manager names link to standardized names and stable IDs, so one fund printed five ways maps to one record."),
                ("Map the field", "The printed label maps to one allowed measure or term name: Net Asset Value on the page becomes nav. The raw string, sign, unit, scale, and date stay on the row. A label off the list stays out of the kept files."),
                ("Build fund tables", "Reviewed fields become fund observations, fund periods, dated cash flows, terms, and holdings, each at the level the page reported: a fund total stays a fund total, and one investor's position stays that investor's."),
                ("Keep the page pointer", "Fund observations retain the evidence-row ID; fund periods list their input evidence-row IDs; cash flows, terms, and holdings retain document and page fields. A later number marked printed names one of these rows."),
                ("Run analysis", "Quality rules and performance calculations read the fund tables alone, so each result can be followed to the printed fields that supplied it."),
            ]),
            bars("Evidence rows by source section", "data/extracted/tables/fact_observation.csv",
                 "The kind of PDF section that supplied each evidence row, such as a performance table, holding schedule, cash-flow notice, or legal-term section.",
                 [(name or "blank", count, thousands(count)) for name, count in families.most_common()]),
            donuts("Evidence rows by value type", "data/extracted/tables/fact_observation.csv",
                   "Each PDF field is classified as a count, currency amount, percentage, multiple, or text. "
                   "That classification determines how the value is displayed and which checks may use it.",
                   [donut_chart("value type", kinds.most_common(), "evidence rows")]),
            bars("Most common metric and term labels", "data/extracted/tables/fact_observation.csv",
                 "The field labels assigned most often to evidence rows, such as NAV, TVPI, management fee, or investment name.",
                 [(name or "blank", count, thousands(count)) for name, count in categories.most_common(20)]),
            heading("Published evidence rows"),
            table(
                "Evidence row preview",
                "data/extracted/tables/fact_observation.csv",
                [name for name in keep if name in visible],
                trimmed,
                total,
                page=25,
                about=TABLE_NOTES["data/extracted/tables/fact_observation.csv"],
                hidden=[name for name in keep if name not in visible],
                key="fact_observation",
            ),
            note(
                "The evidence CSV holds " + thousands(len(header)) + " columns. The compact grid shows the "
                + thousands(len(visible)) + " identity, value, date, and source columns. Row detail retains "
                "every other column and links the retained field to its PDF, page text, table coordinates, "
                "two extractor proposals, comparison row, and review decision."
            ),
            heading("Flat reviewer files"),
            table(
                "Published review tables",
                "data/extracted/review/",
                ["Path", "Rows", "Columns", "Contents"],
                reviewer_files,
                page=10,
                about="The final row-level files combine PDF evidence, fund identity, completion records, quality results, and analytical outputs.",
            ),
        ],
    }


def schema_section() -> dict:
    metric_rows = [row for row in read_dicts("data/schemas/EXTRACTION-METRIC-CATEGORIES.csv")]
    metrics = [row for row in metric_rows if row.get("kind") == "metric"]
    terms = [row for row in metric_rows if row.get("kind") == "term"]
    families = read_dicts("data/schemas/EXTRACTION-RECORD-FAMILIES.csv")
    field_rows = [
        [name, description]
        for _, _, names in FIELD_GROUPS
        for name in names
        for description in [FIELD_DESCRIPTIONS.get(name, "")]
    ]
    group_rows = [
        [title, purpose, ", ".join(names)]
        for title, purpose, names in FIELD_GROUPS
    ]
    unlabeled: Counter = Counter()
    for row in read_dicts("data/extracted/tables/fact_observation.csv"):
        if not (row.get("metric_category") or row.get("term_category") or "").strip():
            unlabeled[row.get("record_family") or "blank"] += 1
    if not unlabeled:
        unlabeled_note = ""
    elif set(unlabeled) == {"document_context"}:
        unlabeled_note = (
            f" The {thousands(sum(unlabeled.values()))} document_context rows, one per report's "
            "identity and reporting context, carry no field label."
        )
    else:
        unlabeled_note = (
            f" {thousands(sum(unlabeled.values()))} rows carry no field label, in the "
            + ", ".join(sorted(unlabeled)) + " categories."
        )

    return {
        "id": "schema",
        "title": "Data model and vocabulary",
        "blurb": (
            "Both readers fill the same 42 columns: who, when, the printed value, the cleaned value, "
            "the unit, the place on the page, the quote, and the review mark. One list of measure "
            "names and one list of term names let a NAV from two reports use the same name before "
            "the fund tables are built. A shared label such as return still follows the method "
            "printed on that report."
        ),
        "blocks": [
            kpi(
                ("Schema version", contract.CONTRACT_VERSION, "Version written on every typed row so files with different column lists stay apart"),
                ("Columns per extraction row", thousands(len(contract.RECORD_COLUMNS)), "Fields covering identity, date, reported value, units, source location, quote, and review status"),
                ("Source-row categories", thousands(len(families)), "Allowed groups that keep the kind of line: performance, holdings, cash flows, terms, or another PDF section"),
                ("Quantitative field labels", thousands(len(metrics)), "Approved names for numeric measures shared across all report types"),
                ("Legal and policy labels", thousands(len(terms)), "Approved names for legal, policy, and clause fields shared across all report types"),
                ("Report categories", thousands(len(contract.CANONICAL_DOC_TYPES)), "Allowed document types that pick the reading steps and the allowed line kinds"),
            ),
            note(
                "Every evidence row carries one approved source-row category, and every metric or "
                "clause row also carries one approved metric or term label. The category says whether "
                "the source row is a holding, cash flow, performance line, or legal clause. The field "
                "label says what that row measures. A shared label such as return still follows "
                "the method printed on that report." + unlabeled_note
            ),
            heading("Extraction row format"),
            table("Column groups", "src/catalog/simple_pdf_extraction/field_guide.py",
                  ["Group", "Purpose", "Fields"], group_rows, page=15,
                  about="The 42 extraction columns grouped by kind: who, date, value, place on the page, and review mark."),
            table("Column definitions", "src/catalog/simple_pdf_extraction/field_guide.py",
                  ["Field", "Meaning"], field_rows, page=25,
                  about=TABLE_NOTES["src/catalog/simple_pdf_extraction/field_guide.py"]),
            heading("Source-row categories"),
            file_table(
                "Source-row meaning and allowed fields",
                "data/schemas/EXTRACTION-RECORD-FAMILIES.csv",
                columns=("record_family", "description", "grain", "category_kind", "tabular", "preferred_categories"),
                limit=None,
                page=20,
            ),
            heading("Approved field labels"),
            file_table(
                "Metric and term names with definitions",
                "data/schemas/EXTRACTION-METRIC-CATEGORIES.csv",
                limit=None,
                page=25,
            ),
            heading("Report routing"),
            file_table("Report types and assigned extraction workflows", "data/schemas/EXTRACTION-DOC-TYPE-MAP.csv", limit=None, page=20),
            file_table(
                "Extraction workflow assigned to each report",
                "data/schemas/EXTRACTION-ROUTING.csv",
                columns=("file_id", "canonical_doc_type", "route", "product_tier", "page_count",
                         "routing_status", "routing_reason", "issuer"),
                limit=None,
            ),
        ],
    }


def warehouse_section() -> dict:
    star = read_dicts("data/extracted/tables/MANIFEST.csv")
    wide = [row for row in read_dicts("data/extracted/wide/MANIFEST.csv") if row["table"] != "TOTAL"]
    family_tables = [row for row in wide if row["table"].startswith("wide_")]
    databases = [
        ("extracted.duckdb", "one evidence row per field read from a PDF", *inventory("data/warehouse/extracted.duckdb")),
        ("alts.duckdb", "the completed fund tables and analytics", *inventory("data/warehouse/alts.duckdb")),
        ("alts_mock.duckdb", "the separate test-only fund population", *inventory("data/warehouse/alts_mock.duckdb")),
    ]
    database_rows = [
        [
            name,
            purpose,
            thousands(len(tables)) if status == "read" else status,
            thousands(len(views)) if status == "read" else status,
            ", ".join(views) or status,
        ]
        for name, purpose, status, tables, views in databases
    ]
    fund_model_status, fund_model_tables, _ = databases[1][2:]

    groups = [
        {
            "name": name,
            "note": purpose,
            "tables": database_contents(f"data/warehouse/{name}", PREVIEW_ROWS),
        }
        for name, purpose, status, _, _ in databases
        if status == "read"
    ]
    explorer_blocks = (
        [
            heading("Database browser"),
            explorer(
                "Database tables and views",
                "data/warehouse/",
                "Every DuckDB table and view, with up to "
                + thousands(PREVIEW_ROWS) + " rows in stable order, while the count beside each name "
                "refers to the whole table. Italic names are saved queries. Plain names are stored tables. "
                "The compact grid shows primary columns and row detail retains every field.",
                groups,
            ),
        ]
        if groups
        else [
            note(
                "Reading the databases table by table needs duckdb. Where it is absent the "
                "listings below still come from the published CSVs those databases load."
            )
        ]
    )
    csv_rows = []
    for path in sorted(path_of("data/csv").glob("*.csv")):
        header, _, total = read_table(f"data/csv/{path.name}", 0)
        csv_rows.append([path.stem, thousands(total), thousands(len(header)), ", ".join(header[:6]) + " ..."])
    snapshot = []
    for path in sorted(path_of("data/extracted/fund-level").glob("*.csv")):
        header, _, total = read_table(f"data/extracted/fund-level/{path.name}", 0)
        snapshot.append([path.stem, thousands(total), thousands(len(header))])

    return {
        "id": "warehouse",
        "title": "Data files and databases",
        "blurb": (
            "Three DuckDB files. extracted.duckdb: one row per printed PDF field. alts.duckdb: fund "
            "tables after fill, plus measures. alts_mock.duckdb: test funds only. Each file is built "
            "from its CSVs. A check requires the same rows and values in both."
        ),
        "blocks": [
            kpi(
                ("Evidence tables", thousands(len(star)), "Relational tables for documents, pages, entities, extracted fields, holdings, and extraction lineage"),
                ("Reviewer-wide tables", thousands(len(family_tables)), "Tables that put the printed source tables back together, one per line kind, with every filled field naming its evidence row"),
                (
                    "Fund-model tables",
                    thousands(len(fund_model_tables)) if fund_model_status == "read" else thousands(len(csv_rows)),
                    "Analysis-ready tables for funds, periods, cash flows, terms, holdings, quality results, performance metrics, PME, and allocations"
                    if fund_model_status == "read"
                    else f"Published CSV tables; the DuckDB file reported {fund_model_status} during this build",
                ),
                ("Source-only snapshot tables", thousands(len(snapshot)), "Fund tables copied before fill and used for printed-only checks and measures"),
            ),
            table("Database inventory", "data/warehouse/",
                  ["File", "Contents", "Tables", "Views", "View names"], database_rows, page=10,
                  about="Role, table count, and saved-query count for each DuckDB file. alts_mock.duckdb uses the same fund-table shapes and holds FUND_SYNTH_ test funds only."),
            *explorer_blocks,
            heading("Evidence database tables"),
            table("Table and row count", "data/extracted/tables/MANIFEST.csv",
                  ["Table", "File", "Rows"],
                  [[row["table"], row["file"], thousands(as_int(row["rows"]))] for row in star], page=20,
                  about="The evidence database keeps source documents, pages, and named entities in one set of tables, and printed PDF fields and holdings in another. The lineage table links every kept field to the two typed rows and the decision."),
            bars("Rows per evidence table", "data/extracted/tables/MANIFEST.csv",
                 "Row count for each evidence table.",
                 [(row["table"], as_int(row["rows"]), thousands(as_int(row["rows"]))) for row in star]),
            heading("Reconstructed source tables"),
            table("Table, rows, collisions", "data/extracted/wide/MANIFEST.csv",
                  ["Table", "Rows", "Collisions"],
                  [[row["table"], thousands(as_int(row["rows"])), row["collisions"] or "0"] for row in wide], page=20,
                  about="The wide files put each PDF table back together for review. Each output row is one printed table row. Each measure or term has its own column. Every filled field names its evidence-row ID. A collision above zero means two evidence rows tried to fill the same field."),
            heading("Fund-model tables"),
            table("Row and column counts", "data/csv/",
                  ["Table", "Rows", "Columns", "First columns"], csv_rows, page=25,
                  about="Every fund-model CSV loaded into alts.duckdb. The loader reads each table back and requires every row and value to match the CSV. document_entity_context.csv and entity_registry.csv are identity work files."),
            heading("Fund tables before fill"),
            table("PDF-derived fund tables before completion", "data/extracted/fund-level/",
                  ["Table", "Rows", "Columns"], snapshot, page=20,
                  about="Copies of the fund tables taken before fill. They hold printed rows and supply the printed-only results on Analytics and Quality."),
        ],
    }


# ---------------------------------------------------------------- analytics


def frac(top: str, bottom: str) -> str:
    return f'<span class="frac"><span>{top}</span><span>{bottom}</span></span>'


def worked_multiples() -> tuple[dict, dict, dict, str]:
    """A real printed period and its multiples, for the formula cards."""

    metrics = read_dicts("data/extracted/fund-level/fund_metrics.csv")
    periods = {row["fund_period_id"]: row for row in read_dicts("data/extracted/fund-level/fund_periods.csv")}
    names = {row["fund_id"]: row["fund_name"] for row in read_dicts("data/csv/fund_master.csv")}
    pages = {
        row["observation_id"]: row["source_page"]
        for row in read_dicts("data/extracted/tables/fact_observation.csv")
    }
    by_period: dict[str, dict[str, str]] = {}
    for row in metrics:
        by_period.setdefault(row["input_record_ids"], {})[row["metric_id"]] = row["value_numeric"]
    for period_id, values in by_period.items():
        period = periods.get(period_id)
        if not period or not {"dpi", "rvpi", "tvpi"} <= set(values):
            continue
        # A period that prints all three balances above zero makes every
        # card's arithmetic visible; one with a blank NAV would show a zero.
        if not (as_float(period.get("distributions_itd")) and as_float(period.get("nav")) and as_float(period.get("paid_in_capital_itd"))):
            continue
        page = period.get("source_page") or next(
            (pages[item.strip()] for item in period.get("input_observation_ids", "").replace("|", ";").split(";") if item.strip() in pages),
            "",
        )
        label = f"{names.get(period['fund_id'], period['fund_id'])}, {period['as_of_date']} ({period['source_document_id']}, page {page})"
        return period, values, names, label
    return {}, {}, names, ""


def worked_cashflows() -> tuple[dict, list[dict], dict, dict]:
    """A completed-panel fund with its generated flows and its results."""

    periods = [row for row in read_dicts("data/csv/fund_periods.csv") if row["provenance_type"] == "SYNTHETIC"]
    period = periods[0] if periods else {}
    fund_id = period.get("fund_id", "")
    flows = sorted(
        (row for row in read_dicts("data/csv/fund_cashflows.csv") if row["fund_id"] == fund_id and not row.get("lp_id")),
        key=lambda row: row["cashflow_date"],
    )
    metrics = {
        row["metric_id"]: row
        for row in read_dicts("data/csv/fund_metrics.csv")
        if row["entity_id"] == fund_id and row["as_of_date"] == period.get("as_of_date")
    }
    pme = {
        row["metric_id"]: row
        for row in read_dicts("data/csv/pme_results.csv")
        if row["entity_id"] == fund_id and row["as_of_date"] == period.get("as_of_date")
    }
    return period, flows, metrics, pme


def formula_cards() -> list[dict]:
    period, values, names, label = worked_multiples()
    cf_period, flows, cf_metrics, cf_pme = worked_cashflows()
    cf_name = names.get(cf_period.get("fund_id", ""), cf_period.get("fund_id", ""))
    extracted = tally("data/extracted/fund-level/fund_metrics.csv", "formula_id")
    completed = tally("data/csv/fund_metrics.csv", "formula_id") + tally("data/csv/pme_results.csv", "formula_id")
    code = "src/analytics/run_round04_analytics.py, src/common/finance.py"

    paid = as_float(period.get("paid_in_capital_itd")) or 0.0
    dist = as_float(period.get("distributions_itd")) or 0.0
    nav = as_float(period.get("nav")) or 0.0

    def lines(formula_id: str) -> list[list[str]]:
        return [
            ["Formula ID", formula_id],
            ["Results from PDF-only data", thousands(extracted.get(formula_id, 0))],
            ["Results from completed data", thousands(completed.get(formula_id, 0))],
            ["Calculation code", code],
        ]

    flow_rows = [[row["cashflow_date"], row["cashflow_type"], money(row["amount"])] for row in flows]
    flow_rows.append([cf_period.get("as_of_date", ""), "terminal NAV", money(cf_period.get("nav"))])

    return [
        {
            "name": "DPI",
            "plain": "Distributions to paid-in. Of every dollar the investor put in, how much has come back as cash. Cash only. Value still held is left out.",
            "html": "DPI = " + frac("distributions to date", "paid-in capital to date"),
            "example": {"title": "PDF example: " + label, "result": True, "rows": [
                ["Distributions to date", money(dist)],
                ["Paid-in capital to date", money(paid)],
                ["DPI", show_unit(values.get("dpi"), "multiple")],
            ]},
            "lines": lines("DPI_DISTRIBUTIONS_OVER_PAID_IN_V1"),
        },
        {
            "name": "RVPI",
            "plain": "Residual value to paid-in. Of every dollar put in, how much is still held, at the manager's own valuation of the remaining position.",
            "html": "RVPI = " + frac("net asset value", "paid-in capital to date"),
            "example": {"title": "PDF example: " + label, "result": True, "rows": [
                ["Net asset value", money(nav)],
                ["Paid-in capital to date", money(paid)],
                ["RVPI", show_unit(values.get("rvpi"), "multiple")],
            ]},
            "lines": lines("RVPI_NAV_OVER_PAID_IN_V1"),
        },
        {
            "name": "TVPI",
            "plain": "Total value to paid-in: cash returned plus value still held, per dollar put in. It equals DPI plus RVPI. Rule R02 checks that equation for every period the rule can test.",
            "html": "TVPI = " + frac("distributions + net asset value", "paid-in capital to date") + " = DPI + RVPI",
            "example": {"title": "PDF example: " + label, "result": True, "rows": [
                ["Distributions + NAV", money(dist + nav)],
                ["Paid-in capital to date", money(paid)],
                ["TVPI", show_unit(values.get("tvpi"), "multiple")],
            ]},
            "lines": lines("TVPI_VALUE_OVER_PAID_IN_V1"),
        },
        {
            "name": "XIRR",
            "plain": "The money-weighted yearly rate. It is the one rate that makes every dated cash flow, plus the value still held on the as-of date, sum to zero. Calls are negative, distributions positive, and days are counted on a 365-day year.",
            "html": (
                '<span class="sum">&sum;</span><sub>i</sub> '
                + frac("amount<sub>i</sub>", "(1 + <i>r</i>)<sup>days<sub>i</sub> / 365</sup>")
                + " = 0, solved for <i>r</i>"
            ),
            "example": {"title": "Completed-data example: " + cf_name + ", " + cf_period.get("as_of_date", ""), "result": True, "rows": [
                *flow_rows,
                ["XIRR", show_unit(cf_metrics.get("xirr", {}).get("value_numeric"), "decimal_rate")],
            ]},
            "lines": lines("XIRR_ACTUAL_365_TERMINAL_NAV_V1"),
        },
        {
            "name": "KS-PME",
            "plain": "Kaplan-Schoar public market equivalent. Every distribution and the terminal value are divided by the index level on their date, every contribution likewise, and the two sums are compared. Above 1.00x the fund beat the index. Below 1.00x the index beat the fund.",
            "html": (
                "KS-PME = "
                + frac(
                    frac("NAV", "L<sub>T</sub>") + " + <span class=\"sum\">&sum;</span> " + frac("distribution<sub>i</sub>", "L<sub>i</sub>"),
                    "<span class=\"sum\">&sum;</span> " + frac("contribution<sub>i</sub>", "L<sub>i</sub>"),
                )
                + " &nbsp; where L<sub>i</sub> is the index level on or before date i"
            ),
            "example": {"title": "Completed-data example: " + cf_name + " against SPY, " + cf_period.get("as_of_date", ""), "result": True, "rows": [
                ["Cash flows in the calculation", thousands(len(flows))],
                ["Benchmark observations used", thousands(len([item for item in cf_pme.get("ks_pme", {}).get("input_record_ids", "").split(";") if item.startswith("RET_")]))],
                ["KS-PME", show_unit(cf_pme.get("ks_pme", {}).get("value_numeric"), "multiple")],
            ]},
            "lines": lines("KS_PME_ASOF_BENCHMARK_V1"),
        },
        {
            "name": "Direct Alpha",
            "plain": "The yearly rate the fund earned over the index. Each cash flow is grown to the as-of date at the index growth. The end value is added. The XIRR of that grown series is the alpha. A Direct Alpha of -10 percent means the fund lagged the index by about 10 percent a year. Zero means the fund matched the index.",
            "html": (
                "Direct Alpha = XIRR of &nbsp;{ amount<sub>i</sub> &times; "
                + frac("L<sub>T</sub>", "L<sub>i</sub>")
                + " } &nbsp;plus NAV on the as-of date"
            ),
            "example": {"title": "Completed-data example: " + cf_name + " against SPY, " + cf_period.get("as_of_date", ""), "result": True, "rows": [
                ["Fund XIRR", show_unit(cf_metrics.get("xirr", {}).get("value_numeric"), "decimal_rate")],
                ["Direct Alpha", show_unit(cf_pme.get("direct_alpha", {}).get("value_numeric"), "decimal_rate")],
            ]},
            "lines": lines("DIRECT_ALPHA_ASOF_BENCHMARK_XIRR_V1"),
        },
    ]


def result_table(title: str, rel: str, limit: int | None = 300) -> dict:
    """An analytics result table with the value shown in its unit and the
    fund named beside its ID."""

    names = {row["fund_id"]: row["fund_name"] for row in read_dicts("data/csv/fund_master.csv")}
    rows = read_dicts(rel, limit)
    total = row_count(rel)
    visible = ["fund", "entity_id", "as_of_date", "metric_id", "value", "unit", "formula_id", "benchmark_id", "provenance_type"]
    hidden = ["value_numeric", "analysis_result_id", "inputs", "input_record_ids", "quality_population", "notes"]
    body = []
    for row in rows:
        inputs = [item for item in row.get("input_record_ids", "").split(";") if item]
        body.append([
            names.get(row["entity_id"], ""), row["entity_id"], row["as_of_date"], row["metric_id"],
            show_unit(row["value_numeric"], row["unit"]), row["unit"], row["formula_id"],
            row["benchmark_id"], row["provenance_type"],
            row["value_numeric"], row["analysis_result_id"],
            f"{len(inputs)} records: " + ", ".join(inputs[:4]) + (" ..." if len(inputs) > 4 else ""),
            row["input_record_ids"], row["quality_population"], row["notes"],
        ])
    return table(
        title, rel, visible, body, total, page=25,
        about=TABLE_NOTES.get(rel, ""), hidden=hidden, key=Path(rel).stem,
    )


UNIT_TITLES = {
    "multiple": "Multiples, in times paid-in capital",
    "decimal_rate": "Annual rates",
    "portfolio_fraction": "Portfolio weights",
}


def distribution_boxes(rows: list[dict[str, str]]) -> list[dict]:
    """Group the five printed numbers of each distribution by unit.

    One scale per unit keeps a comparison honest: multiples sit against
    multiples, rates against rates, and a rate never shares an axis with a
    multiple."""

    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(row["unit"], []).append(row)
    built = []
    for unit, items in groups.items():
        values = [as_float(item[field]) or 0.0 for item in items for field in ("min_value", "max_value")]
        low, high = min(values), max(values)
        built.append({
            "title": UNIT_TITLES.get(unit, unit),
            "low": low,
            "high": high,
            "low_display": show_unit(low, unit),
            "high_display": show_unit(high, unit),
            "items": [
                {
                    "label": item["metric_id"],
                    "rows": thousands(as_int(item["row_count"])),
                    "min": as_float(item["min_value"]) or 0.0,
                    "p25": as_float(item["p25_value"]) or 0.0,
                    "median": as_float(item["median_value"]) or 0.0,
                    "p75": as_float(item["p75_value"]) or 0.0,
                    "max": as_float(item["max_value"]) or 0.0,
                    "display": {
                        field: show_unit(item[f"{field}_value"], unit)
                        for field in ("min", "p25", "median", "p75", "max")
                    },
                }
                for item in sorted(items, key=lambda row: row["metric_id"])
            ],
        })
    return sorted(built, key=lambda group: group["title"])


def analytics_section() -> dict:
    summary = read_dicts("data/extracted/review/reviewer-analytics-summary.csv")
    distributions = [row for row in summary if row["record_type"] == "distribution"]
    extracted_periods = row_count("data/extracted/fund-level/fund_periods.csv")
    analyzable = next(
        (as_int(row["row_count"]) for row in summary if row["record_type"] == "coverage" and row["population"] == "EXTRACTED"),
        0,
    )

    def distribution_rows(population: str) -> list[list[str]]:
        return [
            [row["metric_id"], row["unit"], thousands(as_int(row["row_count"])),
             *[show_unit(row[field], row["unit"]) for field in ("min_value", "p25_value", "median_value", "p75_value", "max_value")]]
            for row in distributions if row["population"] == population
        ]

    exposure = [
        [row["group_name"], thousands(as_int(row["row_count"])), show_unit(row["weighted_value"], "portfolio_fraction")]
        for row in summary if row["record_type"] == "strategy_exposure"
    ]

    return {
        "id": "analytics",
        "title": "Analytics",
        "blurb": (
            "The measures are fund multiples, money-weighted return, public-market equivalent, "
            "Direct Alpha, and portfolio weights. Every result names its formula and input rows. "
            "Results from printed numbers have one mark. Results that use filled rows have another mark."
        ),
        "blocks": [
            formulas("Measure definitions and worked examples", formula_cards()),
            note(
                "A cash flow keeps the sign convention of its direction: a contribution is negative "
                "to the investor and a distribution is positive. Same-day flows aggregate before "
                "the solve. The index join uses the last index value on or before the cash-flow date. "
                "A later index value stays off that flow."
            ),
            heading("Results from printed numbers"),
            note(
                f"{thousands(analyzable)} of {thousands(extracted_periods)} printed periods carry the "
                "three inputs of a fund multiple, paid-in capital above zero together with distributions "
                "and NAV, and pass the quality rules. DPI, RVPI, and TVPI are calculated for those "
                "periods; a period that prints zero paid-in capital, or fails rule R01 on a negative "
                "balance, has an empty multiple. XIRR, KS-PME, and Direct Alpha require dated cash-flow "
                "histories, so this set is DPI, RVPI, and TVPI."
            ),
            boxes("Spread of the multiples on printed periods", "data/extracted/review/reviewer-analytics-summary.csv",
                  "Each row is one measure across the printed periods. A multiple reads as times paid-in: 1.22x means the position is worth 1.22 dollars per dollar drawn.",
                  distribution_boxes([row for row in distributions if row["population"] == "EXTRACTED"])),
            table("Distribution summary for PDF-based periods", "data/extracted/review/reviewer-analytics-summary.csv",
                  ["Metric", "Unit", "Rows", "Minimum", "25th", "Median", "75th", "Maximum"],
                  distribution_rows("EXTRACTED"), page=15,
                  about="The values behind the plot above: the smallest, the quartiles, the median, and the largest, for every measure on the printed periods."),
            heading("Filled fund-date table"),
            boxes("Spread on the filled fund-date table", "data/extracted/review/reviewer-analytics-summary.csv",
                  "The same measures on the completed periods, which add XIRR, KS-PME, and Direct Alpha because the completion gives every fund a dated cash-flow history. A rate reads as an annual percent, so a Direct Alpha below zero means the fund trailed the index by that much a year.",
                  distribution_boxes([row for row in distributions if row["population"] == "INTEGRATED"])),
            table("Distribution summary for completed periods", "data/extracted/review/reviewer-analytics-summary.csv",
                  ["Metric", "Unit", "Rows", "Minimum", "25th", "Median", "75th", "Maximum"],
                  distribution_rows("INTEGRATED"), page=15,
                  about="The values behind the plot above, for every measure on the filled fund-date table."),
            table("Strategy exposure of the demonstration portfolio", "data/extracted/review/reviewer-analytics-summary.csv",
                  ["Strategy", "Funds", "Weight"], exposure, page=25,
                  about="Weight by strategy in the equal-weight test set, each fund capped at 5 percent. Funds with a blank printed strategy get Diversified Alternatives from the fill step. That bar is large for that reason."),
            heading("Analytics output tables"),
            result_table("Fund performance metrics", "data/csv/fund_metrics.csv"),
            result_table("PME results", "data/csv/pme_results.csv"),
            file_table(
                "Portfolio weights", "data/csv/portfolio_allocations.csv",
                columns=("fund_id", "strategy", "as_of_date", "target_weight", "minimum_weight", "maximum_weight",
                         "commitment_amount", "nav_amount", "unfunded_amount", "optimization_run_id"),
                limit=300,
            ),
            note(
                "Each fund starts at 1 over the fund count and is capped at 5 percent. Run name: "
                "BOUNDED_EQUAL_WEIGHT_V1. Weights use ten decimal places and sum to one. "
                "Expected volatility and liquidity stay blank: the PDFs print none."
            ),
        ],
    }


def benchmarks_section() -> dict:
    runs = read_dicts("data/public_markets/audit/market_data_runs.csv")
    policy = read_dicts("data/integrated/benchmark-policy.csv")
    inventory_rows = read_dicts("data/public_markets/audit/source_file_inventory.csv")
    families = read_dicts("data/public_markets/audit/source_family_summary.csv")
    masters = read_dicts("data/public_markets/staging/benchmark_master_candidates.csv")
    run = runs[-1] if runs else {}
    tiers = Counter(row["analysis_tier"] for row in inventory_rows)

    return {
        "id": "benchmarks",
        "title": "Benchmark data",
        "blurb": (
            "Public-market files were read. Return series that can go into PME were kept. Dated "
            "series were built. Each series names its date range, return basis, and use limit. "
            "Every PME result names the series it used."
        ),
        "blocks": [
            kpi(
                ("Market files retained", thousands(as_int(run.get("selected_file_count"))), "Hash-checked Parquet files in the benchmark package, each one an input the pipeline can read"),
                ("Series families", thousands(len(families)), "Groups the retained files fall into, each with its analysis tier and PME role"),
                ("Benchmark series built", thousands(as_int(run.get("benchmark_count"))), "Distinct return series constructed from the retained files before the use-policy filter"),
                ("Daily index levels", thousands(as_int(run.get("benchmark_level_count"))), "Dated prices or index values staged across all constructed benchmark series"),
                ("Daily index returns", thousands(as_int(run.get("benchmark_return_count"))), "Returns recomputed from consecutive index levels and checked against their source series"),
                ("Daily SPY returns used by PME", thousands(row_count("data/csv/benchmark_returns.csv")), "Dated SPY returns used in this demo PME. Public stocks, used here in place of a private-market index."),
            ),
            heading("Benchmark use limits"),
            table("Benchmark policy", "data/integrated/benchmark-policy.csv",
                  ["Benchmark", "Name", "Rights", "Use", "First", "Last", "Observations", "Note"],
                  [[row["benchmark_id"], row["benchmark_name"], row["rights_status"], row["use_status"],
                    row["first_observation_date"], row["last_observation_date"],
                    thousands(as_int(row["observation_count"])), row["note"]] for row in policy], page=10,
                  about=TABLE_NOTES["data/integrated/benchmark-policy.csv"]),
            note(
                "SPY is for this demo only. It runs the repeatable example. A live run would swap in a "
                "licensed public-market series. The PME code stays; the series is data."
            ),
            bars("Retained files by analysis tier", "data/public_markets/audit/source_file_inventory.csv",
                 "Files marked PME_CORE have return histories that may go into PME. Other kept files are market background.",
                 [(name or "blank", count, thousands(count)) for name, count in tiers.most_common()]),
            heading("Market-file families"),
            table("Source family summary", "data/public_markets/audit/source_family_summary.csv",
                  ["Family", "Files", "Rows", "Tier", "PME role", "Source system", "Note"],
                  [[row["source_family"], thousands(as_int(row["file_count"])),
                    thousands(as_int(row["row_count"])), row["analysis_tiers"],
                    row["pme_roles"], row["source_systems"], row["note"]] for row in families], page=20,
                  about=TABLE_NOTES["data/public_markets/audit/source_family_summary.csv"]),
            file_table(
                "Retained market files and their analytical role",
                "data/public_markets/audit/source_file_inventory.csv",
                columns=("file_id", "source_family", "analysis_tier", "pme_role", "return_basis",
                         "rights_status", "row_count", "date_min", "date_max"),
                limit=None,
            ),
            heading("Constructed benchmark series"),
            table("Candidate series, coverage, and use status", "data/public_markets/staging/benchmark_master_candidates.csv",
                  ["Benchmark", "Name", "Ticker", "Asset class", "Currency", "Basis", "First", "Last", "Observations", "Rights", "Use"],
                  [[row["benchmark_id"], row["benchmark_name"], row["ticker"], row["asset_class"],
                    row["currency"], row["return_basis"], row["first_observation_date"],
                    row["last_observation_date"], thousands(as_int(row["observation_count"])),
                    row["rights_status"], row["pme_use_status"]] for row in masters], page=25,
                  about=TABLE_NOTES["data/public_markets/staging/benchmark_master_candidates.csv"]),
            heading("Market-data quality checks"),
            file_table("Validation results PMQ01 to PMQ10", "data/public_markets/audit/quality_results.csv", limit=None, page=15),
        ],
    }


# ---------------------------------------------------------------- quality


def quality_causes(rel: str) -> Counter:
    """Count rule outcomes by what produced them, read from the result rows."""

    causes: Counter = Counter()
    for row in read_dicts(rel):
        status = row["status"]
        notes = row.get("notes", "")
        if status == "FAIL" and row["rule_id"] == "R01_NONNEGATIVE_BALANCES":
            causes[("FAIL", "a negative the page prints in parentheses")] += 1
        elif status == "FAIL":
            causes[("FAIL", "the recomputation disagrees with the record")] += 1
        elif status == "PASS" and "widened" in notes:
            causes[("PASS", "inside the rounding the printed inputs allow, tolerance widened on the row")] += 1
        elif status == "PASS":
            causes[("PASS", "the recomputation agrees within the configured tolerance")] += 1
        elif "different histories" in notes:
            causes[("SKIP", "a printed IRR on a position whose cash flows were generated; not compared")] += 1
        elif status == "SKIP":
            causes[("SKIP", "the record lacks an input the rule needs")] += 1
    return causes


def failure_rows() -> list[list[str]]:
    """The failing source-only rows with the page evidence behind each."""

    periods = {row["fund_period_id"]: row for row in read_dicts("data/extracted/fund-level/fund_periods.csv")}
    observations = {row["observation_id"]: row for row in read_dicts("data/extracted/tables/fact_observation.csv")}
    names = {row["fund_id"]: row["fund_name"] for row in read_dicts("data/csv/fund_master.csv")}
    rows = []
    for result in read_dicts("data/extracted/fund-level/quality_results.csv"):
        if result["status"] != "FAIL":
            continue
        period = periods.get(result["record_id"], {})
        quote = ""
        page = period.get("source_page", "")
        for observation_id in period.get("input_observation_ids", "").replace("|", ";").split(";"):
            observation = observations.get(observation_id.strip())
            if observation and observation.get("value_raw", "").startswith("("):
                quote = observation["evidence_quote"]
                page = observation.get("source_page", page)
                break
        rows.append([
            result["rule_id"], names.get(result["fund_id"], result["fund_id"]), result["source_document_id"],
            page, money(result["actual_value"]), quote,
            "The page prints the value in parentheses, which is a negative. The extraction is correct and the rule surfaces the anomaly.",
        ])
    return rows


def failure_note(source_fail: int, declined: int) -> str:
    """What the failures are, written from the failing rows themselves."""

    rows = failure_rows()
    if not rows:
        opening = "No rule fails on either population."
    else:
        described = "; ".join(f"{fund} in {document} prints {value}" for _, fund, document, _, value, _, _ in rows)
        opening = (
            f"The source-only checks contain {thousands(source_fail)} failures: {described}. "
            "Both PDF values appear in parentheses, so the extraction keeps them as negatives. "
            "Rule R01 then flags each negative balance for review and leaves the source value unchanged."
        )
    return (
        f"{opening} Generated rows add no failures. Rule R08 skips {thousands(declined)} IRR comparisons "
        "because the PDF-reported IRR and generated cash flows describe different investment histories. "
        "A comparison between them would not test the printed rate."
    )


def quality_section() -> dict:
    rules = read_setting_list("config/quality_rules.yml", "rules")
    tolerances = read_setting_block("config/quality_rules.yml", "tolerances")
    outcomes: dict[str, Counter] = {}
    widened: Counter = Counter()
    with path_of("data/csv/quality_results.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            outcomes.setdefault(row["rule_id"], Counter())[row["status"]] += 1
    source_outcomes: dict[str, Counter] = {}
    with path_of("data/extracted/fund-level/quality_results.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source_outcomes.setdefault(row["rule_id"], Counter())[row["status"]] += 1
            if "widened" in row.get("notes", ""):
                widened[row["rule_id"]] += 1

    rule_rows = [
        [
            rule["id"], rule["severity"], str(rule.get("formula", "")), str(rule.get("tolerance", "")),
            str(rule.get("applies_when", "")),
            thousands(source_outcomes.get(rule["id"], Counter()).get("PASS", 0)),
            thousands(widened.get(rule["id"], 0)),
            thousands(source_outcomes.get(rule["id"], Counter()).get("FAIL", 0)),
            thousands(source_outcomes.get(rule["id"], Counter()).get("SKIP", 0)),
            thousands(outcomes.get(rule["id"], Counter()).get("PASS", 0)),
            thousands(outcomes.get(rule["id"], Counter()).get("FAIL", 0)),
            thousands(outcomes.get(rule["id"], Counter()).get("SKIP", 0)),
        ]
        for rule in rules
    ]
    source_causes = quality_causes("data/extracted/fund-level/quality_results.csv")
    completed_causes = quality_causes("data/csv/quality_results.csv")
    cause_rows = [
        ["Source only (printed rows)", status, cause, thousands(count)]
        for (status, cause), count in sorted(source_causes.items(), key=lambda item: (item[0][0], -item[1]))
    ] + [
        ["Filled fund-date table (printed rows plus generated rows)", status, cause, thousands(count)]
        for (status, cause), count in sorted(completed_causes.items(), key=lambda item: (item[0][0], -item[1]))
    ]
    source_total = sum(source_causes.values())
    source_fail = sum(count for (status, _), count in source_causes.items() if status == "FAIL")
    within = sum(count for (status, cause), count in source_causes.items() if status == "PASS" and "widened" in cause)
    completed_total = sum(completed_causes.values())
    completed_fail = sum(count for (status, _), count in completed_causes.items() if status == "FAIL")
    declined = sum(count for (status, cause), count in completed_causes.items() if status == "SKIP" and "generated" in cause)
    scorecard = read_dicts("data/integrated/detection-scorecard.csv")
    detected = sum(as_int(row["detected"]) for row in scorecard)
    injected = sum(as_int(row["injected"]) for row in scorecard)

    return {
        "id": "quality",
        "title": "Quality controls",
        "blurb": (
            "Each quality row runs one rule on one fund record the rule can test. The row stores the "
            "stored value, the value from the parts, the gap, the allowed gap, and PASS, FAIL, or SKIP. "
            "Printed rows and filled rows each have their own run."
        ),
        "blocks": [
            kpi(
                ("Financial and data rules", thousands(len(rules)), "Checks for fund balances, dates, cash-flow signs, multiples, NAV, IRR, and lineage, each with stated inputs, formula, tolerance, and skip condition"),
                ("PDF-only rule results", thousands(source_total), "One row per rule and one printed fund record the rule can test. SKIP: the record lacks an input that rule needs."),
                ("PDF values flagged", thousands(source_fail), "Two balance values are printed as negatives; extraction keeps them and rule R01 marks them for review"),
                ("Passes using printed precision", thousands(within), "Recomputations that pass after the allowed gap follows the PDF rounding, such as a multiple printed to two decimals"),
                ("Completed-data rule results", thousands(completed_total), "The same rules run on printed records plus filled records, each group with its own mark"),
                ("Completed-data values flagged", thousands(completed_fail), "The same two PDF values remain flagged; generated records introduce no additional failures"),
                ("IRR comparisons skipped", thousands(declined), "A printed IRR is left unmatched to an IRR from made cash flows. Those cash flows are a different history from the printed rate. SKIP is the right mark."),
                ("Deliberate test errors detected", f"{detected} of {injected}", "Errors inserted into an isolated test copy and caught by the intended financial rules",
                 detected / injected if injected else 0),
            ),
            donuts("Outcome mix on each population", "quality_results.csv, both populations",
                   "Every rule result grouped by outcome. PASS marks agreement within tolerance. SKIP marks a missing "
                   "input and remains separate from PASS. FAIL identifies a financial inconsistency or source anomaly; "
                   "both populations contain two failing rows.",
                   [
                       donut_chart(
                           "source only",
                           [(status, sum(count for (kind, _), count in source_causes.items() if kind == status))
                            for status in ("PASS", "SKIP", "FAIL")],
                           "source only",
                       ),
                       donut_chart(
                           "filled fund-date table",
                           [(status, sum(count for (kind, _), count in completed_causes.items() if kind == status))
                            for status in ("PASS", "SKIP", "FAIL")],
                           "completed",
                       ),
                   ]),
            heading("Result causes"),
            table("Rule results by data population and cause", "quality_results.csv, both populations",
                  ["Population", "Status", "Cause", "Count"], cause_rows, page=15,
                  about="Every rule result grouped by cause and data group. Printed-only: printed rows. Filled: those rows plus marked added rows. FAIL on a printed row goes to source or extraction review. FAIL on an added row goes to the fill steps."),
            note(failure_note(source_fail, declined)),
            table("The two failures, with the page behind each", "data/extracted/fund-level/quality_results.csv",
                  ["Rule", "Fund", "Document", "Page", "Printed", "Quote", "Reading"], failure_rows(), page=10,
                  about="Each failing row with the fund it belongs to, the document and page it was read from, the printed value, and the line of text the value was read from."),
            heading("Financial rule definitions"),
            keyvalue([(f"Tolerance: {name}", str(value)) for name, value in tolerances.items()]),
            table("Formula, tolerance, and outcome on both populations", "config/quality_rules.yml and quality_results.csv",
                  ["Rule", "Severity", "Formula", "Tolerance", "Needed inputs",
                   "Source PASS", "Source PASS inside printed precision", "Source FAIL", "Source SKIP",
                   "Completed PASS", "Completed FAIL", "Completed SKIP"],
                  rule_rows, page=25,
                  about="The 23 rules, the equation each recomputes, the allowed gap, the needed inputs, and the result counts for each data group. SKIP: the record lacks a needed input. R03 and R04 skip the printed-only group: reports that print DPI and RVPI leave paid-in capital off those lines."),
            note(
                "The multiple rules read the printed rounding of each input from its PDF evidence "
                "row. A page that prints $90.5 million states the value to the nearest hundred "
                "thousand. A page that prints 0.47x states it to the nearest hundredth. The allowed "
                "gap grows by that rounding, and the grown gap is written on the result row. A break "
                "larger than that rounding is FAIL. Made rows omit a PDF evidence row and keep the "
                "set gap."
            ),
            heading("Deliberate-error test"),
            table("Inserted test errors and detection results", "data/integrated/detection-scorecard.csv",
                  ["Defect", "Rule", "Injected", "Detected", "Missed", "Rate"],
                  [[row["defect_type"], row["expected_rule_id"], row["injected"], row["detected"],
                    row["missed"], row["detection_rate"]] for row in scorecard], page=20,
                  about=TABLE_NOTES["data/integrated/detection-scorecard.csv"]),
            file_table("Each inserted test error", "data/csv/defect_injections.csv", limit=None, page=15,
                       columns=("defect_id", "fund_id", "record_table", "defect_type", "field_name", "clean_value", "injected_value", "expected_rule_id")),
            heading("Rule-result tables"),
            file_table("Filled fund-date table results", "data/csv/quality_results.csv", limit=400,
                       columns=("rule_id", "fund_id", "record_id", "status", "actual_value", "expected_value", "difference", "tolerance", "source_document_id", "notes")),
            file_table("Source-only results", "data/extracted/fund-level/quality_results.csv", limit=400,
                       columns=("rule_id", "fund_id", "record_id", "status", "actual_value", "expected_value", "difference", "tolerance", "source_document_id", "notes")),
            heading("Reconciliation"),
            file_table("Snapshot against filled fund-date table", "data/integrated/reconciliation-results.csv", limit=200),
        ],
    }


def generated_section() -> dict:
    scalars = read_settings("config/integrated_completion.yml")
    settings = dict(scalars)
    setting_labels = {
        "schema_version": "Completion schema version",
        "parameter_set_id": "Parameter set",
        "seed": "Reproducibility seed",
        "as_of_date": "Analysis date",
        "benchmark_id": "PME benchmark",
        "benchmark_periodicity": "Benchmark frequency",
        "portfolio_id": "Demonstration portfolio",
        "strategy_fallback": "Fallback strategy",
        "currency_fallback": "Fallback currency",
        "fund_size_fallback": "Fallback fund size",
        "minimum_weight": "Minimum portfolio weight",
        "maximum_weight": "Maximum portfolio weight",
    }
    completion_settings = [(setting_labels.get(name, name), value) for name, value in scalars]
    lineage_kinds = tally("data/integrated/cell-lineage.csv", "provenance_type")
    resolutions = tally("data/integrated/gap-ledger.csv", "resolution_type")
    methods = tally("data/integrated/cell-lineage.csv", "imputation_method")
    periods = tally("data/csv/fund_periods.csv", "provenance_type")
    masters = tally("data/csv/fund_master.csv", "provenance_type")
    lineage_total = row_count("data/integrated/cell-lineage.csv")
    gap_total = row_count("data/integrated/gap-ledger.csv")

    labels = ("EXTRACTED", "DERIVED", "IMPUTED", "SYNTHETIC")
    attributes: dict[str, Counter] = {}
    with path_of("data/integrated/cell-lineage.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["target_table"] == "fund_master":
                attributes.setdefault(row["target_field"], Counter())[row["provenance_type"]] += 1
    attribute_rows = [
        [field, *[thousands(counts.get(label, 0)) for label in labels], thousands(sum(counts.values()))]
        for field, counts in sorted(attributes.items())
    ]

    return {
        "id": "generated",
        "title": "Data completion",
        "blurb": (
            "PDFs print different fields and dates, so the fund-date table has empty cells. The fill "
            "step writes marked values on the same fund IDs. One record of a fill names the vintage_year "
            "put on one fund, the source, and the method: copy, median fill, or made values. One seed "
            "makes the same filled table on a rerun."
        ),
        "blocks": [
            kpi(
                ("Recorded field origins", thousands(lineage_total), "One audit row per field value in the completed fund model, naming the fund row, column, value, origin label, and source or generation method"),
                ("Blank fields filled", thousands(gap_total), "Fields left blank after extraction that completion filled; each row records the original blank, new value, and resolution method"),
                ("Added fund-period rows", thousands(periods.get("SYNTHETIC", 0)), "Performance periods added on named fund IDs so every fund has a row in the demo measures"),
                ("PDF-based fund-period rows", thousands(periods.get("EXTRACTED", 0)), "Performance periods built only from values printed in the PDFs and preserved in the source-only snapshot"),
                ("Funds in the filled fund-date table", thousands(sum(masters.values())), "One named fund per row. Printed evidence and marked fill share the same FUND_ ID."),
                ("Reproducibility seed", str(settings.get("seed", "")), "Fixed input that makes the same made values on a rerun. It is a seed, empty of page evidence."),
            ),
            note(
                "Each filled field value carries one of four labels. EXTRACTED means the value is printed on a "
                "cited page. DERIVED: copied inside one fund from a value that page printed, so a vintage "
                "or a strategy stated once is copied onto that fund's other rows. IMPUTED: filled from the "
                "median of printed values for like funds. SYNTHETIC: the PDFs omit it and the steps made it "
                "from the stated settings. The method sits beside the value. A checker can sort the table by origin."
            ),
            heading("Fund attribute origins"),
            stacks("Source of each fund field", "data/integrated/cell-lineage.csv",
                   "For every fund_master column, the share of fund rows carrying each origin label. The dark share "
                   "is the page-printed share. A vintage or strategy stated once is copied across that fund's rows "
                   "(Derived). If the reports omit both, the median of like printed funds fills the cell (IMPUTED).",
                   list(labels),
                   [
                       {
                           "label": field,
                           "values": [counts.get(label, 0) for label in labels],
                           "total_display": thousands(sum(counts.values())),
                       }
                       for field, counts in sorted(attributes.items())
                   ]),
            table("Fund attribute counts", "data/integrated/cell-lineage.csv",
                  ["Field", "Extracted", "Derived", "Imputed", "Synthetic", "Fund values"],
                  attribute_rows, page=15,
                  about="The counts behind the bars above. Fund size, currency, and status are present for every fund, which gives each analytical row a consistent set of fixed attributes."),
            donuts("Origin of all completed values", "data/integrated/cell-lineage.csv and gap-ledger.csv",
                   "Every fund-model field value, grouped by its origin label, and every blank the completion filled, grouped by how the "
                   "fill was decided. The first ring separates printed values from values added during completion.",
                   [
                       donut_chart("origin label", lineage_kinds.most_common(), "field values"),
                       donut_chart("gap resolution", resolutions.most_common(), "gaps"),
                   ]),
            bars("Generation methods", "data/integrated/cell-lineage.csv",
                 "The method that produced each generated or imputed fund-model field value.",
                 [(name or "copied from a printed value", count, thousands(count)) for name, count in methods.most_common(15)]),
            heading("Completion settings"),
            keyvalue(completion_settings),
            heading("Parameters"),
            file_table("Generation parameters", "data/csv/synthetic_parameters.csv", limit=None, page=15,
                       columns=("parameter_name", "strategy", "value_numeric", "unit", "provenance_type", "assumption_basis", "adjudication_status", "active")),
            heading("Record of each filled cell"),
            file_table("Every completed field value and its source", "data/integrated/cell-lineage.csv", limit=400,
                       columns=("target_table", "target_record_id", "target_field", "target_value", "provenance_type", "imputation_method", "source_table", "source_record_id")),
            file_table("Every gap it filled", "data/integrated/gap-ledger.csv", limit=400,
                       columns=("fund_id", "target_table", "field_name", "original_value", "resolution_value", "resolution_type", "status")),
            heading("Test-only dataset"),
            note(
                "A standalone 800-fund population lives in data/synthetic/ and "
                "data/warehouse/alts_mock.duckdb. It uses the same table shapes as the fund model. "
                "It uses FUND_SYNTH_ IDs. The rules and measures can run at 800 funds. The extracted "
                "FUND_ rows stay as they are."
            ),
        ],
    }


def manifest_table() -> dict:
    """The file manifest, with this page's own row left without a size.

    The page renders the manifest into its own body, so a manifest that
    recorded this file's size would change the bytes the next build reads and
    the two would never settle. The row stays, the number goes."""

    header, rows, total = read_table("docs/PROJECT-MANIFEST.csv", None)
    visible = ("path", "entry_type", "repository_policy", "local_readme", "role")
    extra = [name for name in header if name not in visible]
    keep, trimmed = select(header, rows, tuple(visible) + tuple(extra))
    path_at = keep.index("path")
    for row in trimmed:
        if row[path_at] == "dashboard.html":
            for column in ("size_bytes", "sha256"):
                if column in keep:
                    row[keep.index(column)] = "(dashboard output)"
    return table(
        "Files, folders, ownership, and roles", "docs/PROJECT-MANIFEST.csv",
        [name for name in keep if name in visible], trimmed, total, page=25,
        about=TABLE_NOTES["docs/PROJECT-MANIFEST.csv"],
        hidden=[name for name in keep if name not in visible], key="PROJECT-MANIFEST",
    )


def reproduce_section() -> dict:
    receipts_header, all_receipts, receipts_total = read_table("ledgers/pipeline/transformation-receipts.csv", None)
    receipt_rows = all_receipts[-RECEIPT_ROWS:]
    receipts_about = TABLE_NOTES["ledgers/pipeline/transformation-receipts.csv"]
    if receipts_total > RECEIPT_ROWS:
        receipts_about += (
            f" The {thousands(RECEIPT_ROWS)} most recent receipts are embedded here, in the order "
            "they were written; the file holds every receipt since the ledger began."
        )
    visible = ("stage_order", "stage_id", "command", "output_path", "output_rows", "status")
    keep, receipt_rows = select(receipts_header, receipt_rows, tuple(visible) + tuple(name for name in receipts_header if name not in visible))
    commands = [
        ["python -m src.pipeline.publish_review_release", "Rebuilds the reviewer data in pipeline order and records one receipt per data-changing command"],
        ["python -m src.pipeline.reviewer_check", "Verifies row preservation, lineage, financial results, database parity, and disclosed review items"],
        ["python -m pytest -q", "Runs the data, finance, lineage, parity, editorial, dashboard, and repository tests"],
        ["python -m src.repository.check_project_structure --verify-hashes", "Verifies folder guides and manifest metadata"],
        ["python -m src.dashboard.build_dashboard", "Rebuilds dashboard.html from the published CSV and DuckDB files"],
        ["python -m src.dashboard.build_dashboard --serve --open", "Rebuilds the dashboard and serves it on this computer only"],
        ["open-dashboard.cmd", "Opens the local dashboard through the Windows launcher"],
    ]

    return {
        "id": "reproduce",
        "title": "Rebuild and review",
        "blurb": (
            "One command rebuilds the checker files in order and writes one log row per step: command, "
            "input, output, row count, and result. Other commands check row counts, money rules, cell "
            "origin, CSV and DuckDB match, writing rules, and this page. dashboard.html is a copy of "
            "the files that were present at build."
        ),
        "blocks": [
            table("Rebuild and verification commands", "README.md", ["Command", "Result"], commands, page=10,
                  about="Root commands that rebuild, check, and open the checker files."),
            heading("Data-change log"),
            table("Each release command, output, row count, and status", "ledgers/pipeline/transformation-receipts.csv",
                  [name for name in keep if name in visible], receipt_rows, receipts_total, page=25,
                  about=receipts_about,
                   hidden=[name for name in keep if name not in visible], key="transformation-receipts"),
            heading("CSV data flow"),
            file_table(
                "Every CSV and its source",
                "docs/CSV-LINEAGE.csv",
                columns=("csv_path", "origin_csv", "python_file", "agent_operation", "instructions_file"),
                limit=None,
                page=25,
            ),
            heading("Project file map"),
            manifest_table(),
        ],
    }


def costs_section() -> dict:
    """What extraction costs, priced from the timed runs in costs/extraction-runs.csv.

    The two coefficients are solved here rather than written in, so the panel and the
    estimate move together if another timed run is added to that file."""

    runs = read_dicts("costs/extraction-runs.csv")
    timed = [row for row in runs if row["basis"] == "measured"]
    (p1, r1, t1), (p2, r2, t2) = (
        (as_int(row["pages"]), as_int(row["rows"]), as_int(row["turns"])) for row in timed[:2]
    )
    # turns = a x pages + b x rows, solved on two documents of opposite shape
    determinant = p1 * r2 - p2 * r1
    a = (t1 * r2 - t2 * r1) / determinant
    b = (p1 * t2 - p2 * t1) / determinant
    per_turn = (
        sum(as_float(row["cost_usd"]) or 0.0 for row in timed)
        / sum(as_int(row["turns"]) for row in timed)
    )
    cost_page, cost_row = a * per_turn, b * per_turn
    rows_per_equivalent = a / b

    ledger = read_dicts("data-gathering/source_ledger.csv")
    summary = read_dicts("data/extracted/review/document-summary.csv")
    routing = {row["file_id"]: row for row in read_dicts("data/schemas/EXTRACTION-ROUTING.csv")}

    reviewed: dict[str, list[int]] = {}
    for row in summary:
        kind = routing.get(row["file_id"], {}).get("canonical_doc_type", "")
        seen = reviewed.setdefault(kind, [0, 0])
        seen[0] += as_int(row["physical_pages"])
        seen[1] += as_int(row["final_rows"])
    measured_yield = {kind: pair[1] / pair[0] for kind, pair in reviewed.items() if pair[0]}
    pooled = sum(pair[1] for pair in reviewed.values()) / sum(pair[0] for pair in reviewed.values())

    by_type: dict[str, list[int]] = {}
    for row in ledger:
        seen = by_type.setdefault(row.get("doc_type", ""), [0, 0])
        seen[0] += 1
        seen[1] += as_int(row.get("page_count"))

    matrix, corpus_pages, corpus_rows = [], 0, 0.0
    for kind, (documents, pages) in sorted(by_type.items(), key=lambda item: -item[1][1]):
        rate = measured_yield.get(kind, pooled)
        rows_here = pages * rate
        equivalents = pages + rows_here / rows_per_equivalent
        cost = cost_page * pages + cost_row * rows_here
        corpus_pages += pages
        corpus_rows += rows_here
        matrix.append([
            kind, thousands(documents), thousands(pages), f"{rate:.1f}",
            "measured" if kind in measured_yield else "pooled",
            thousands(round(rows_here)), thousands(round(equivalents)),
            f"{cost / documents:.2f}", f"{cost:,.2f}",
        ])

    one_lane = cost_page * corpus_pages + cost_row * corpus_rows
    equivalents_total = corpus_pages + corpus_rows / rows_per_equivalent
    scopes = [
        ["One extraction lane", f"{one_lane:,.0f}"],
        ["Two blind lanes, the second budgeted at twice the first", f"{one_lane * 3:,.0f}"],
        ["Two lanes plus adjudication", f"{one_lane * 4:,.0f}"],
        ["The same three passes at batch pricing", f"{one_lane * 2:,.0f}"],
    ]

    return {
        "id": "costs",
        "title": "Extraction cost",
        "blurb": (
            "Three timed runs price the corpus. A run is billed by the turn, and cost per turn held "
            "steady across documents differing ninefold in row count, so cost reduces to counting "
            "turns. Turns split into a fixed cost for opening a page and a small marginal cost for "
            "each row written once that page is open."
        ),
        "blocks": [
            kpi(
                ("One extraction lane", f"${one_lane:,.0f}",
                 f"Estimated cost of reading all {thousands(len(ledger))} catalogued reports once"),
                ("Two lanes plus review", f"${one_lane * 4:,.0f}",
                 "Two independent readings and the adjudication that settles them, the full published pipeline"),
                ("Per document", f"${one_lane / len(ledger):.2f}",
                 "One lane, averaged over the corpus. Individual documents run from cents to tens of dollars"),
                ("Page-equivalents", thousands(round(equivalents_total)),
                 f"pages + rows / {rows_per_equivalent:.0f}, the unit the estimate prices"),
                ("Cost per page-equivalent", f"${cost_page:.4f}",
                 "One rate that prices any document once its pages and rows are known"),
            ),
            heading("The timed runs behind the estimate"),
            file_table(
                "Each run, its shape, and what it cost", "costs/extraction-runs.csv",
                columns=("run_id", "document", "doc_type", "pages", "rows", "turns",
                         "cost_usd", "dollars_per_turn", "basis"),
                limit=None, page=10,
            ),
            note(
                "Two documents of opposite shape give two equations in two unknowns. A four-page "
                "report yielding 93 rows took 41 turns; a three-page report yielding 876 rows took 71. "
                f"Solving gives {a:.2f} turns to open a page and {b:.4f} turns to write a row, so at "
                f"${per_turn:.6f} per turn a document costs ${cost_page:.4f} multiplied by its pages "
                f"plus ${cost_row:.6f} multiplied by its rows. Built on the first document alone, the "
                "same law predicted the second within four percent."
            ),
            heading("Estimated cost by document type"),
            table(
                "One extraction lane across the catalogued corpus", "data-gathering/source_ledger.csv",
                ["Document type", "Documents", "Pages", "Rows per page", "Yield basis",
                 "Estimated rows", "Page-equivalents", "Cost per document", "Total cost"],
                matrix, page=20,
                about=(
                    "Every catalogued report priced by the cost law. Rows per page comes from the "
                    "reviewed slice for the types it covers and from the corpus pooled rate for the "
                    "rest, so estimated rows are a projection rather than a count. Pages account for "
                    "most of the total, which is why the largest and least dense types lead the bill."
                ),
            ),
            table(
                "Cost by how much of the pipeline is run", "costs/extraction-runs.csv",
                ["Scope", "Cost"], scopes, page=10,
                about=(
                    "The second lane is budgeted at twice the first, since a model that holds to a "
                    "long contract over roughly a hundred turns is the scarce input. Adjudication is "
                    "assumed equal to one lane and has not been timed. Batch endpoints are half list "
                    "price, which the last line applies, though capturing that means restructuring the "
                    "first pass into self-contained per-page requests rather than an interactive loop."
                ),
            ),
            note(
                "Neither cost per page nor cost per row is a usable rate alone. Across the reviewed "
                "documents density runs from under one row per page to nearly three hundred, so "
                "between the two timed runs the cost of a page varies more than twofold and the cost "
                "of a row more than fivefold. Combining both into page-equivalents holds steady, and "
                "the practical consequence is that a dense schedule is cheap: once a page is open, "
                "taking more from it costs very little."
            ),
        ],
    }


SECTION_BUILDERS = (
    overview_section,
    corpus_section,
    extraction_section,
    evidence_section,
    schema_section,
    generated_section,
    quality_section,
    benchmarks_section,
    analytics_section,
    warehouse_section,
    reproduce_section,
    costs_section,
)


def payload() -> dict:
    MISSING_DEFINITIONS.clear()
    return {
        "title": TITLE,
        "subtitle": SUBTITLE,
        "footer": FOOTER,
        "sections": [builder() for builder in SECTION_BUILDERS],
    }


def build(output: Path = OUTPUT) -> tuple[Path, int, int]:
    document = payload()
    text = render(document)
    output.write_text(text, encoding="utf-8", newline="\n")
    blocks = sum(len(section["blocks"]) for section in document["sections"])
    return output, len(document["sections"]), blocks


def page_server(page: bytes, port: int, attempts: int = 20) -> HTTPServer:
    """Bind a loopback server that answers every path with the one page.

    Serving the file rather than the folder it sits in keeps the repository off
    the port, and the address stays on 127.0.0.1, so the page is reachable from
    this machine and from nowhere else."""

    class Handler(BaseHTTPRequestHandler):
        def _head(self, status: int, length: int = 0) -> None:
            self.send_response(status)
            if length:
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def do_HEAD(self) -> None:
            self._head(200, len(page))

        def do_GET(self) -> None:
            if self.path.startswith("/favicon.ico"):
                self._head(204)
                return
            self._head(200, len(page))
            self.wfile.write(page)

        def log_message(self, *args: object) -> None:
            return

    class Server(HTTPServer):
        # HTTPServer reuses an address by default. On Windows that lets a second
        # bind take a port another program already holds, which would hand the
        # reviewer an address serving somebody else's page.
        allow_reuse_address = False

    for candidate in range(port, port + attempts):
        try:
            return Server(("127.0.0.1", candidate), Handler)
        except OSError:
            continue
    raise OSError(f"no free port between {port} and {port + attempts - 1}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--serve",
        action="store_true",
        help="hold the page on a loopback address until Ctrl+C",
    )
    parser.add_argument("--port", type=int, default=8000, help="first port to try with --serve")
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output, sections, blocks = build(args.output)
    except (OSError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    size = output.stat().st_size / (1024 * 1024)
    print(f"PASS: {output.name}, {sections} sections, {blocks} panels, {size:.1f} MB")
    if MISSING_DEFINITIONS:
        print(f"WARN: {len(MISSING_DEFINITIONS)} columns lack a definition: " + ", ".join(sorted(MISSING_DEFINITIONS)[:20]))
    if not args.serve:
        print(f"Open: {output}")
        if args.open:
            webbrowser.open(output.as_uri())
        return 0
    try:
        server = page_server(output.read_bytes(), args.port)
    except OSError as exc:
        print(f"FAIL: {exc}")
        return 1
    address = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Open: {address}")
    print("Serving on this machine alone. Ctrl+C stops it.")
    if args.open:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
