"""Flatten the adjudicated wide rows into a relational star schema.

`data/extracted/rounds/*-records.csv` carries one wide row per extracted cell:
the document, the page, the printed grid position, the subject, the metric, the
value, and the evidence quote all on one line. That shape is right for
adjudication and wrong for querying. This stage splits it into dimensions and
facts under `data/extracted/tables/`, which `sql/duckdb/03_extracted_star_ddl.sql`
loads into `data/warehouse/extracted.duckdb`.

Three rules govern the flatten:

Nothing is dropped. Every published row reaches `fact_observation` or
`fact_holding`. A name the normalization matrix has yet to decide becomes an
unresolved alias, never a discarded row, so the entity backlog stays visible
instead of shrinking the corpus.

Nothing printed is altered. `value_numeric` is the number verbatim as printed and
`unit_scale` records the thousands or millions annotation beside it. The two are
never multiplied together here: a table headed "Dollars in thousands" sometimes
prints the full figure anyway, and silently scaling would corrupt those rows.
`vw_observation_scaled` in the DDL does the multiplication in the open, where a
reviewer can see and override it.

Nothing is guessed. A date shape the parser does not recognise leaves the ISO
column empty and keeps the printed text in `*_raw`, with `date_precision` saying
how much of it was understood.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.common import matrices
from src.catalog.simple_pdf_extraction.name_normalization import (
    COLUMN_KIND,
    DECIDED,
    KINDS,
    NON_NAMES,
    SUBJECT_KIND,
    match_key,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUNDS_DIR = PROJECT_ROOT / "data" / "extracted" / "rounds"
SOURCE_LEDGER = PROJECT_ROOT / "data-gathering" / "source_ledger.csv"
CATEGORY_CATALOGUE = PROJECT_ROOT / "data" / "schemas" / "EXTRACTION-METRIC-CATEGORIES.csv"
STANDARD_MEASURES = PROJECT_ROOT / "data" / "schemas" / "METRIC-STANDARD-MEASURES.csv"
NORMALIZATION_DIR = PROJECT_ROOT / "data" / "normalization"
REGISTRY = NORMALIZATION_DIR / "entity-ids.csv"
FUND_MATRIX = NORMALIZATION_DIR / "fund-names-matrix.csv"
WEB_MANAGERS = NORMALIZATION_DIR / "web-manager-names.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "extracted" / "tables"

# Every decision below is a row in a matrix under
# data/normalization/transformations, read here and checked by release stage
FAMILY_ROUTING = "record-family-routing"
HOLDING_COLUMN_MAP = "metric-to-holding-column"
MONTH_NAMES = "month-names"
SCALE_WORD_MAP = "scale-words"
CURRENCY_TOKENS = "currency-token-map"
CELL_SERIALIZATION = "csv-value-serialization"
NUMERIC_SERIALIZATION = "numeric-serialization"
IDENTIFIER_RULES = "identifier-generation-rules"
DATE_SHAPES = "date-shapes"
DATE_POLICY = "date-precision-policy"
SCALE_DEFAULTS = "scale-defaults"
UNIT_SCALE_DEFAULTS = "unit-scale-defaults"
NUMBER_PATTERN = "number-pattern"
VALUE_PARSE = "value-kind-parse"
VALUE_DEFAULTS = "value-kind-defaults"
NUMBER_RULES = "number-format-rules"
VALUE_KINDS = "value-kind-classification"
UNMATCHED_POLICY = "unmatched-entity-policy"
SUBJECT_KIND_POLICY = "subject-type-entity-kind"
ALIAS_AGGREGATION = "alias-evidence-aggregation"
MANAGER_INHERITANCE = "fund-manager-inheritance"
METRIC_ID_RULES = "metric-identifier-rules"
GROUPING_MAP = "context-grouping-map"
TEXT_FALLBACK = "text-value-fallback"
FIELD_ORDER = "field-fallback-order"
CURRENCY_ORDER = "currency-precedence"
HOLDING_CONTEXT = "holding-context-precedence"
HOLDING_VALUES = "holding-value-source"
HOLDING_COLLISIONS = "holding-collision-policy"
PAGE_ORDER = "page-row-precedence"
PAGE_DATA = "page-data-status"
DOCUMENT_ORDER = "document-row-precedence"
NAME_ORDER = "entity-name-precedence"
CATALOGUE_STATUS = "metric-catalogue-status"
METRIC_KIND_POLICY = "metric-value-kind-policy"
RESOLUTION_STATUS = "entity-resolution-status"


HOLDING_FAMILY = matrices.resolve(FAMILY_ROUTING, "holding_family", context="flatten")
HOLDING_COLUMNS = matrices.mapping(HOLDING_COLUMN_MAP)


def _grouping_index() -> dict[tuple[str, str], dict[str, str]]:
    """The grouping matrix keyed by context and printed value."""

    return {
        (row.get("context", ""), row["input_value"]): row
        for row in matrices.load(GROUPING_MAP)
    }


_GROUPING: dict[tuple[str, str], dict[str, str]] | None = None


def canonical_grouping(record: Mapping[str, str]) -> dict[str, str]:
    """What a row's printed groupings are under one taxonomy, and whether the
    row states an amount of money.

    The printed columns keep the page's own words, each in the column its
    heading names: an asset-class grouping in `asset_class`, a strategy or
    style grouping in `strategy`, and a company industry in `sector`. These
    columns read each printed value through the grouping matrix under the
    context of the column it sits in, so `Real Estate` printed as a strategy
    heading still names the class, and an industry never names a class.

    `value_kind` records the form the cell itself printed, so a figure under a
    dollar heading prints as a number. `is_monetary` answers the question a
    reader actually asks by reading the currency first, exactly as promotion's
    money test does.
    """

    global _GROUPING
    if _GROUPING is None:
        _GROUPING = _grouping_index()
    out = {
        "canonical_asset_class": "",
        "canonical_strategy": "",
        "canonical_sub_strategy": "",
        "canonical_sector": "",
        "is_monetary": "",
    }
    for context in ("asset_class", "strategy", "sector"):
        printed = (record.get(context, "") or "").strip()
        if not printed:
            continue
        row = _GROUPING.get((context, printed))
        if row is None:
            continue
        if not out["canonical_asset_class"]:
            out["canonical_asset_class"] = matrices.decode(row["output_value"])
        for source, target in (
            ("canonical_strategy", "canonical_strategy"),
            ("canonical_sub_strategy", "canonical_sub_strategy"),
        ):
            if row[source] and not out[target]:
                out[target] = row[source]
        # The industry reading comes from a sector heading and from nothing
        # else. Reading the matrix row's `sector` column under the asset_class
        # or strategy context would publish a fund strategy as a company
        # industry, which is the one direction the sector column exists to
        # prevent; two strategy_enum rows carry a sector value today.
        if context == "sector" and row["sector"] and not out["canonical_sector"]:
            out["canonical_sector"] = row["sector"]
    return out
MONTHS = {name: int(number) for name, number in matrices.mapping(MONTH_NAMES).items()}
MONTHS.update({name[:3]: number for name, number in list(MONTHS.items())})
SCALE_WORDS = tuple(
    (row["input_value"], row["output_value"], float(row["multiplier"]))
    for row in matrices.load(SCALE_WORD_MAP)
)
CURRENCY_WORDS = tuple(
    (word, code) for word, code in matrices.mapping(CURRENCY_TOKENS, context="word").items()
    if word != "dollar"
)
CURRENCY_SYMBOLS = matrices.mapping(CURRENCY_TOKENS, context="symbol")

DOCUMENT_COLUMNS = (
    "document_id", "filename", "canonical_doc_type", "route", "product_tier",
    "source_sha256", "issuer", "issuer_type", "file_ext",
    "ledger_page_count", "is_redacted", "source_url", "retrieved_at",
    "pages_covered", "pages_with_data", "observation_count", "holding_count",
)

PAGE_COLUMNS = (
    "page_id", "document_id", "route", "source_page", "page_status",
    "layout_checked", "source_structures", "relevant_record_families",
    "expected_observation_count", "records_written", "notes",
)

ENTITY_COLUMNS = (
    "entity_id", "entity_kind", "canonical_name", "fund_family",
    "manager_name", "manager_source", "alias_count", "observation_count",
)

ALIAS_COLUMNS = (
    "alias_id", "raw_name", "normalized_name", "entity_kind", "entity_id",
    "standardized_name", "match_method", "first_seen_document", "documents", "occurrences",
)

METRIC_COLUMNS = (
    "metric_id", "record_family", "metric_category", "in_catalogue",
    "value_kind", "observation_count", "standard_measure", "measure_scope", "note",
)

# The fact_observation field list is a matrix: one row per column, ordered by
# position. Appending a column is a row there plus its DDL line, never a code
# edit here.
OBSERVATION_COLUMNS_MATRIX = "observation-columns"
OBSERVATION_COLUMNS = tuple(
    row["output_value"]
    for row in sorted(
        matrices.load(OBSERVATION_COLUMNS_MATRIX), key=lambda row: int(row["input_value"])
    )
)

HOLDING_COLUMN_NAMES = (
    "holding_id", "document_id", "route", "page_id", "source_page", "source_table",
    "holding_label", "holding_alias_id", "holding_entity_id", "subject_type",
    # The industry the schedule printed beside the position. It is the fund
    # model's only path from a printed industry to fund_holdings.sector, which
    # promotion fills from here.
    "sector",
    "source_occurrence", "as_of_date_raw", "as_of_date", "currency",
    "unit_scale", "unit_scale_multiplier",
    "fair_value", "market_value", "cost", "notional_amount", "quantity",
    "portfolio_weight", "interest_rate", "maturity_date_raw",
    "observation_ids", "observation_count", "collision_note",
)


UNRESOLVED_COLUMNS = (
    "entity_kind", "raw_name", "normalized_name", "occurrences", "documents", "reason",
)

MANIFEST_COLUMNS = ("table", "file", "rows")


class FlattenError(RuntimeError):
    """Raised when the flatten refuses to publish an inconsistent build."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_standard_measures(path: Path = STANDARD_MEASURES) -> dict[str, dict[str, str]]:
    """Load one complete, unique description for every published metric ID."""
    rows = read_csv(path)
    if not rows:
        raise FlattenError(f"Missing or empty standard-measure file: {path}")
    required = ("metric_id", "standard_measure", "measure_scope", "note", "decided_by", "evidence")
    loaded: dict[str, dict[str, str]] = {}
    for line_number, row in enumerate(rows, start=2):
        missing = [column for column in required if not (row.get(column) or "").strip()]
        if missing:
            raise FlattenError(
                f"{path.name}:{line_number} has blank required fields: {', '.join(missing)}"
            )
        metric_id = row["metric_id"].strip()
        if metric_id in loaded:
            raise FlattenError(f"{path.name}:{line_number} repeats metric_id {metric_id}")
        loaded[metric_id] = row
    return loaded


def write_csv(path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, object]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(columns), lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _cell(row.get(key)) for key in columns})
            count += 1
    return count


def _cell(value: object) -> str:
    if value is None:
        return matrices.resolve(CELL_SERIALIZATION, "none_value")
    if isinstance(value, bool):
        return matrices.resolve(CELL_SERIALIZATION, "true" if value else "false")
    if isinstance(value, float):
        float_format = matrices.resolve(NUMERIC_SERIALIZATION, "float_format")
        if float_format == "shortest_round_trip":
            # The shortest text that reads back as the same float, so a value
            # parsed from a printed `$17,996,547.30` writes as 17996547.3.
            # Fixed at ten places it wrote 17996547.3000000007, the binary
            # float's expansion, on 35 rows, and the DECIMAL(30, 6) column of
            # the database then rounded what the CSV printed.
            text = repr(value)
            if "e" in text or "E" in text:
                text = format(value, ".10f")
            if "." in text:
                text = text.rstrip("0").rstrip(".")
        else:
            text = format(value, float_format).rstrip("0").rstrip(".")
        return text or matrices.resolve(NUMERIC_SERIALIZATION, "stripped_to_empty")
    return str(value)


_KEY_LENGTH = int(
    next(
        row["hash_length"]
        for row in matrices.load(IDENTIFIER_RULES)
        if row.get("context") == "flatten"
    )
)


def _first_ranked(name: str, context: str, sources: Mapping[str, str]) -> str:
    """The first non-blank source, in the order the matrix ranks them."""

    for row in sorted(matrices.rows_in(name, context), key=lambda item: int(item["input_value"])):
        value = sources[row["output_value"]]
        if value:
            return value
    return ""


def _key(*parts: object) -> str:
    digest = hashlib.sha256("".join(str(part) for part in parts).encode("utf-8"))
    return digest.hexdigest()[:_KEY_LENGTH]


def load_rounds() -> list[dict[str, str]]:
    paths = sorted(ROUNDS_DIR.glob("*-records.csv"))
    if not paths:
        raise FlattenError(
            f"No published rounds in {ROUNDS_DIR}. "
            "Run `csv_workflow publish --route <route>` for every route first."
        )
    rows: list[dict[str, str]] = []
    for path in paths:
        rows.extend(read_csv(path))
    return rows


def load_coverage() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(ROUNDS_DIR.glob("*-coverage.csv")):
        rows.extend(read_csv(path))
    return rows


# ---------------------------------------------------------------------------
# Printed-value parsing. Every helper returns what it understood and says so.
# ---------------------------------------------------------------------------


def parse_date(raw: str, file_id: str = "") -> tuple[str, str]:
    """Return an ISO date and the precision the printed text supports.

    A shape the parser does not recognise returns an empty date and precision
    `unknown`, leaving the printed text as the only claim the row makes.
    """

    text = unicodedata.normalize("NFKC", raw or "").strip().rstrip(".")
    if not text:
        return "", ""
    compact = re.sub(r"\s+", " ", text)
    # A weekday prefix names the same day the rest of the string already gives.
    compact = re.sub(
        r"^(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s*", "", compact, flags=re.IGNORECASE
    )

    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", compact)
    if match:
        first, second, year = (int(part) for part in match.groups())
        order = matrices.mapping("source-date-order").get(file_id, "")
        if order == "DMY":
            day, month = first, second
        elif order == "MDY":
            month, day = first, second
        elif first > 12 and second <= 12:
            day, month = first, second
        elif second > 12 and first <= 12:
            month, day = first, second
        else:
            return "", "unknown"
        parsed = _iso(year, month, day)
        return (parsed, "day") if parsed else ("", "unknown")

    match = re.fullmatch(r"([A-Za-z]+)\.? (\d{1,2}),? (\d{4})", compact)
    if match:
        month = MONTHS.get(match.group(1).lower())
        if month:
            return _iso(int(match.group(3)), month, int(match.group(2))), matrices.resolve(DATE_SHAPES, "month_day_year")

    match = re.fullmatch(r"(\d{1,2}) ([A-Za-z]+),? (\d{4})", compact)
    if match:
        month = MONTHS.get(match.group(2).lower())
        if month:
            return _iso(int(match.group(3)), month, int(match.group(1))), matrices.resolve(DATE_SHAPES, "day_month_year")

    match = re.fullmatch(r"([A-Za-z]+)\.? (\d{4})", compact)
    if match:
        month = MONTHS.get(match.group(1).lower())
        if month:
            return _iso(match.group(2) and int(match.group(2)), month, _month_end(int(match.group(2)), month)), matrices.resolve(DATE_SHAPES, "month_year")

    match = re.fullmatch(r"(?:FY)?(\d{4})", compact)
    if match:
        return f"{match.group(1)}-12-31", matrices.resolve(DATE_SHAPES, "bare_year")

    match = re.fullmatch(r"FY(\d{2})", compact)
    if match:
        return f"20{match.group(1)}-12-31", matrices.resolve(DATE_SHAPES, "fy_two_digit")

    return "", matrices.resolve(DATE_POLICY, "unrecognized_shape")


def _month_end(year: int, month: int) -> int:
    if month == 12:
        return 31
    following = date(year + (month // 12), (month % 12) + 1, 1)
    return (following - date(year, month, 1)).days


def _iso(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def specific_currency(text: str) -> str:
    """Read a currency name, code or specific symbol from the token matrix."""
    for expression, code in matrices.mapping(CURRENCY_TOKENS, context="specific_pattern").items():
        if re.search(expression, text or "", flags=re.IGNORECASE):
            return code
    return ""


def observation_currency(raw: str, heading: str) -> str:
    """Resolve a cell symbol against its printed currency heading."""
    value_currency = next((code for symbol, code in CURRENCY_SYMBOLS.items() if symbol in raw), "")
    return _first_ranked(CURRENCY_ORDER, "", {
        "specific_value": specific_currency(raw),
        "scale_heading": parse_scale(heading)[0],
        "value_symbol": value_currency,
    })


def parse_scale(currency_scale: str) -> tuple[str, str, float]:
    """Read the currency and the scale word printed beside a money column."""

    text = unicodedata.normalize("NFKC", currency_scale or "").strip()
    if not text:
        return (
            "",
            matrices.resolve(SCALE_DEFAULTS, "blank_heading_scale"),
            float(matrices.resolve(SCALE_DEFAULTS, "blank_heading_multiplier")),
        )
    lowered = text.casefold()
    currency = specific_currency(text)
    if not currency:
        for word, code in CURRENCY_WORDS:
            if word in lowered:
                currency = code
                break
    if not currency:
        for symbol, code in CURRENCY_SYMBOLS.items():
            if symbol in text:
                currency = code
                break
    if not currency and "dollar" in lowered:
        currency = matrices.resolve(CURRENCY_TOKENS, "dollar", context="word")
    scale = matrices.resolve(UNIT_SCALE_DEFAULTS, "no_scale_word_scale")
    multiplier = float(matrices.resolve(UNIT_SCALE_DEFAULTS, "no_scale_word_multiplier"))
    for word, name, factor in SCALE_WORDS:
        if re.search(rf"\b{word}s?\b", lowered):
            scale, multiplier = name, factor
            break
    return currency, scale, multiplier


NUMBER_RE = re.compile(matrices.resolve(NUMBER_PATTERN, "number_pattern"))


def parse_value(raw: str, unit: str) -> tuple[str, float | None, str, str]:
    """Return the value kind, the number verbatim as printed, its sign, and currency.

    The number keeps the magnitude the document shows. A percent stays the
    printed percent and a multiple stays the printed multiple; neither is
    converted, because the unit column already says which one it is.
    """

    text = unicodedata.normalize("NFKC", raw or "").strip()
    if not text:
        return matrices.resolve(VALUE_PARSE, "empty_value"), None, "", ""
    currency = observation_currency(text, "")
    minus = matrices.resolve(VALUE_DEFAULTS, "unicode_minus")
    negative = (
        matrices.resolve(VALUE_DEFAULTS, "negative_parentheses") == "negative"
        and bool(re.fullmatch(r"\(.*\)", text))
    ) or (
        matrices.resolve(VALUE_DEFAULTS, "negative_leading_minus") == "negative"
        and text.lstrip().startswith(minus)
    )
    body = text.strip("()").replace("−", minus)
    searched = body.replace(" ", "") if matrices.resolve(NUMBER_RULES, "internal_spaces") == "removed" else body
    word_value = matrices.mapping("printed-number-words").get(body.casefold())
    match = NUMBER_RE.search(searched)
    if not match and word_value is None:
        return matrices.resolve(VALUE_PARSE, "unparsed_text"), None, "", currency
    number_text = word_value if word_value is not None else match.group(0)
    if matrices.resolve(NUMBER_RULES, "thousands_separator") == "removed":
        number_text = number_text.replace(",", "")
    number = float(number_text)
    if negative and number > 0:
        number = -number
    kind = matrices.resolve(VALUE_KINDS, "default_kind")
    percent_unit = matrices.resolve(VALUE_KINDS, "percent_unit")
    multiple_unit = matrices.resolve(VALUE_KINDS, "multiple_unit")
    if unit.strip() == percent_unit or body.rstrip().endswith(percent_unit):
        kind = "percent"
    elif unit.strip().lower() == multiple_unit or re.search(r"\dx\b", body.casefold()):
        kind = "multiple"
    elif currency:
        kind = matrices.resolve(VALUE_KINDS, "currency_symbol_kind")
    return kind, number, "negative" if number < 0 else "positive", currency


# ---------------------------------------------------------------------------
# Entity resolution, read straight off the conversion matrices.
# ---------------------------------------------------------------------------


def load_matrices() -> dict[str, dict[str, tuple[str, str, str]]]:
    """kind -> raw name -> (standardized name, entity id, match method)."""

    lookup: dict[str, dict[str, tuple[str, str, str]]] = {}
    for kind, (path, raw_col, std_col, id_col) in KINDS.items():
        table: dict[str, tuple[str, str, str]] = {}
        for row in read_csv(path):
            status = (row.get("decision_status") or "").strip().lower()
            if status not in DECIDED:
                continue
            raw = (row.get(raw_col) or "").strip()
            if not raw:
                continue
            table[raw] = (
                (row.get(std_col) or "").strip(),
                (row.get(id_col) or "").strip(),
                f"matrix_{status}",
            )
        lookup[kind] = table
    return lookup


def build_alias_index(
    records: Sequence[Mapping[str, str]], entity_matrices: Mapping[str, dict[str, tuple[str, str, str]]]
) -> dict[tuple[str, str], dict[str, object]]:
    """One entry per printed name, whether or not the matrix has decided it."""

    index: dict[tuple[str, str], dict[str, object]] = {}

    def note(kind: str, raw: str, record: Mapping[str, str]) -> None:
        name = (raw or "").strip()
        if not name or name.upper() in NON_NAMES:
            return
        key = (kind, name)
        entry = index.get(key)
        if entry is None:
            standard, entity_id, method = entity_matrices.get(kind, {}).get(name, ("", "", ""))
            if kind == "scope":
                method = matrices.resolve(UNMATCHED_POLICY, "scope_label_method")
            elif not method:
                method = matrices.resolve(UNMATCHED_POLICY, "undecided_name")
            entry = {
                "alias_id": _key("ALIAS", kind, name),
                "raw_name": name,
                "normalized_name": match_key(name),
                "entity_kind": kind,
                "entity_id": entity_id,
                "standardized_name": standard,
                "match_method": method,
                "first_seen_document": record.get("file_id", ""),
                "document_set": set(),
                "occurrences": 0,
            }
            index[key] = entry
        entry["document_set"].add(record.get("file_id", ""))
        entry["occurrences"] = int(entry["occurrences"]) + 1

    for record in records:
        subject_type = record.get("subject_type", "")
        note(
            SUBJECT_KIND.get(subject_type, matrices.resolve(SUBJECT_KIND_POLICY, "unknown_subject_type")),
            record.get("subject_name", ""),
            record,
        )
        for column, kind in COLUMN_KIND.items():
            note(kind, record.get(column, ""), record)
    for entry in index.values():
        entry["documents"] = matrices.resolve(ALIAS_AGGREGATION, "document_join").join(
            sorted(value for value in entry["document_set"] if value)
        )
    return index


def alias_of(
    index: Mapping[tuple[str, str], dict[str, object]], kind: str, raw: str
) -> tuple[str, str]:
    name = (raw or "").strip()
    if not name or name.upper() in NON_NAMES:
        return "", ""
    entry = index.get((kind, name))
    if entry is None:
        return "", ""
    return str(entry["alias_id"]), str(entry["entity_id"])


# ---------------------------------------------------------------------------
# The build.
# ---------------------------------------------------------------------------


def load_fund_families() -> dict[str, str]:
    """standardized fund name -> the sponsor family the normalizer named."""

    families: dict[str, str] = {}
    for row in read_csv(FUND_MATRIX):
        if (row.get("decision_status") or "").strip().lower() not in DECIDED:
            continue
        standard = (row.get("standardized_fund_name") or "").strip()
        family = (row.get("fund_family") or "").strip()
        if standard and family:
            families[standard] = family
    return families


def load_managers(families: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    """standardized fund name -> (general partner, cited source).

    A fund with no settled manager of its own inherits one already settled for
    another vehicle of the same sponsor family, which is the whole point of the
    family column: the web round searches a series once. The inherited source is
    marked so a reader can see the manager was carried across, not looked up.
    """

    direct: dict[str, tuple[str, str]] = {}
    for row in read_csv(WEB_MANAGERS):
        standard = (row.get("standardized_fund_name") or "").strip()
        manager = (row.get("final_manager_name") or "").strip()
        source = (row.get("final_source") or "").strip()
        if standard and manager:
            direct[standard] = (manager, source)
    by_family: dict[str, tuple[str, str, str]] = {}
    for standard, (manager, source) in direct.items():
        family = families.get(standard)
        if family and family not in by_family:
            by_family[family] = (manager, source, standard)
    resolved = dict(direct)
    for standard, family in families.items():
        if standard in resolved or family not in by_family:
            continue
        manager, source, origin = by_family[family]
        resolved[standard] = (
            manager,
            matrices.resolve(MANAGER_INHERITANCE, "inherited_source_format").format(
                family=family, origin=origin, source=source
            ),
        )
    return resolved


def build_tables(output_dir: Path) -> dict[str, int]:
    records = load_rounds()
    coverage = load_coverage()
    entity_matrices = load_matrices()
    aliases = build_alias_index(records, entity_matrices)
    catalogue = {
        row["category"]
        for row in read_csv(CATEGORY_CATALOGUE)
        if row.get("kind") == "metric"
    }
    ledger = {row["file_id"]: row for row in read_csv(SOURCE_LEDGER)}
    fund_families = load_fund_families()
    fund_managers = load_managers(fund_families)

    observations: list[dict[str, object]] = []
    metric_counts: Counter = Counter()
    entity_counts: Counter = Counter()

    for record in records:
        document_id = record["file_id"]
        page = record.get("source_page", "").strip()
        page_id = _key("PAGE", document_id, page)
        family = record.get("record_family", "")
        category = record.get("metric_category", "").strip()
        metric_id = (
            matrices.resolve(METRIC_ID_RULES, "with_category").format(family=family, category=category)
            if category
            else matrices.resolve(METRIC_ID_RULES, "without_category").format(family=family)
        )
        metric_counts[metric_id] += 1

        subject_kind = SUBJECT_KIND.get(
            record.get("subject_type", ""), matrices.resolve(SUBJECT_KIND_POLICY, "unknown_subject_type")
        )
        subject_alias, subject_entity = alias_of(aliases, subject_kind, record.get("subject_name", ""))
        subject_standard = ""
        entry = aliases.get((subject_kind, (record.get("subject_name", "") or "").strip()))
        if entry is not None:
            subject_standard = str(entry["standardized_name"])
        subject_manager = fund_managers.get(subject_standard, ("", ""))[0] if subject_standard else ""
        manager_alias, manager_entity = alias_of(aliases, "manager", record.get("manager_name", ""))
        investor_alias, investor_entity = alias_of(aliases, "lp", record.get("investor_name", ""))
        for entity in (subject_entity, manager_entity, investor_entity):
            if entity:
                entity_counts[entity] += 1

        unit = record.get("unit", "")
        kind, number, sign, value_currency = parse_value(record.get("metric_value_raw", ""), unit)
        scale_currency, scale, multiplier = parse_scale(record.get("currency_scale", ""))
        text_raw = record.get("text_raw", "").strip()
        if kind == "none" and text_raw:
            kind = matrices.resolve(TEXT_FALLBACK, "none_with_text")
        if kind == "text" and not text_raw:
            # A text answer printed into the value column is still a text value.
            text_raw = record.get(matrices.resolve(TEXT_FALLBACK, "text_source_fallback"), "").strip()
        currency_value = observation_currency(record.get("metric_value_raw", ""), record.get("currency_scale", ""))
        as_of_iso, as_of_precision = parse_date(record.get("as_of_date", ""), record["file_id"])
        start_iso, _ = parse_date(record.get("period_start", ""), record["file_id"])
        end_iso, end_precision = parse_date(record.get("period_end", ""), record["file_id"])

        observations.append({
            "observation_id": _key(
                "OBS", document_id, page, record.get("source_table", ""),
                record.get("source_row_label", ""), record.get("source_column_label", ""),
                record.get("source_occurrence", ""), metric_id, record.get("metric_name", ""),
            ),
            "document_id": document_id,
            "route": record.get("route", ""),
            "canonical_doc_type": record.get("canonical_doc_type", ""),
            "product_tier": record.get("product_tier", ""),
            "page_id": page_id,
            "source_page": page,
            "source_structure_type": record.get("source_structure_type", ""),
            "source_section": record.get("source_section", ""),
            "source_table": record.get("source_table", ""),
            "source_row_label": record.get("source_row_label", ""),
            "source_column_label": record.get("source_column_label", ""),
            "source_occurrence": record.get("source_occurrence", ""),
            "record_family": family,
            "metric_id": metric_id,
            "metric_category": category,
            "metric_name": record.get("metric_name", ""),
            "subject_type": record.get("subject_type", ""),
            "subject_alias_id": subject_alias,
            "subject_entity_id": subject_entity,
            "subject_name": record.get("subject_name", ""),
            "subject_standardized_name": subject_standard,
            "subject_manager_name": subject_manager,
            "manager_alias_id": manager_alias,
            "manager_entity_id": manager_entity,
            "investor_alias_id": investor_alias,
            "investor_entity_id": investor_entity,
            "portfolio_name": record.get("portfolio_name", ""),
            "asset_class": record.get("asset_class", ""),
            "strategy": record.get("strategy", ""),
            "geography": record.get("geography", ""),
            "vintage_year": record.get("vintage_year", ""),
            "horizon": record.get("horizon", ""),
            "date_precision": _first_ranked(
                FIELD_ORDER,
                "fact_observation.date_precision",
                {"as_of_precision": as_of_precision, "end_precision": end_precision},
            ),
            "as_of_date_raw": record.get("as_of_date", ""),
            "as_of_date": as_of_iso,
            "period_start_raw": record.get("period_start", ""),
            "period_start": start_iso,
            "period_end_raw": record.get("period_end", ""),
            "period_end": end_iso,
            "value_kind": kind,
            "value_raw": record.get("metric_value_raw", ""),
            "value_numeric": number,
            "value_text": text_raw,
            "value_sign": sign,
            # The currency matrix distinguishes a named denomination from a bare symbol.
            "currency": currency_value,
            "unit": unit,
            "unit_scale": scale,
            "unit_scale_multiplier": multiplier,
            "currency_scale_raw": record.get("currency_scale", ""),
            "term_category": record.get("term_category", ""),
            "basis_raw": record.get("basis_raw", ""),
            "condition_raw": record.get("condition_raw", ""),
            "evidence_quote": record.get("evidence_quote", ""),
            "evidence_class": record.get("evidence_class", ""),
            "adjudication_status": record.get("adjudication_status", ""),
            "source_agents": record.get("source_agents", ""),
            "extractor_model": record.get("extractor_model", ""),
            "contract_version": record.get("contract_version", ""),
            "notes": record.get("notes", ""),
            "definition_keys": record.get("definition_keys", ""),
            "method": record.get("method", ""),
            "fee_basis": record.get("fee_basis", ""),
            "value_scope": record.get("value_scope", ""),
            "sector": record.get("sector", ""),
            **canonical_grouping(record),
            # The currency is read first: a figure under a dollar heading
            # prints as a number and is still money.
            "is_monetary": "true" if (currency_value or kind == "currency") else "false",
            "canonical_measure_id": "",
            "mapping_rule_id": "",
        })

    holdings = build_holdings(observations)
    pages = build_pages(coverage)
    documents = build_documents(records, coverage, holdings, ledger)
    entities = build_entities(aliases, entity_counts, fund_families, fund_managers)
    standard_measures = load_standard_measures()
    metrics = build_metrics(metric_counts, catalogue, observations, standard_measures)
    unresolved = build_unresolved(aliases)

    written = {
        "dim_document": write_csv(output_dir / "dim_document.csv", DOCUMENT_COLUMNS, documents),
        "dim_page": write_csv(output_dir / "dim_page.csv", PAGE_COLUMNS, pages),
        "dim_entity": write_csv(output_dir / "dim_entity.csv", ENTITY_COLUMNS, entities),
        "entity_alias": write_csv(
            output_dir / "entity_alias.csv",
            ALIAS_COLUMNS,
            sorted(aliases.values(), key=lambda row: (row["entity_kind"], row["raw_name"])),
        ),
        "dim_metric": write_csv(output_dir / "dim_metric.csv", METRIC_COLUMNS, metrics),
        "fact_observation": write_csv(
            output_dir / "fact_observation.csv", OBSERVATION_COLUMNS, observations
        ),
        "fact_holding": write_csv(
            output_dir / "fact_holding.csv", HOLDING_COLUMN_NAMES, holdings
        ),
        "unresolved_names": write_csv(
            output_dir / "unresolved_names.csv", UNRESOLVED_COLUMNS, unresolved
        ),
    }
    if written["fact_observation"] != len(records):
        raise FlattenError(
            f"published rounds hold {len(records)} rows but the fact table wrote "
            f"{written['fact_observation']}; the flatten drops nothing"
        )
    write_csv(
        output_dir / "MANIFEST.csv",
        MANIFEST_COLUMNS,
        [
            {"table": name, "file": f"{name}.csv", "rows": count}
            for name, count in sorted(written.items())
        ],
    )
    return written


def build_holdings(observations: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Pivot schedule-of-investments cells into one row per printed holding.

    Two cells of the same category inside one printed row mean the pivot key is
    too coarse for that table. The row still publishes, keeping the first value
    and naming the clash in `collision_note`, so the case is visible instead of
    silently overwritten.
    """

    grain = tuple(
        row["output_value"]
        for row in sorted(matrices.rows_in(HOLDING_CONTEXT, "grain"), key=lambda item: int(item["input_value"]))
    )
    groups: dict[tuple, list[Mapping[str, object]]] = defaultdict(list)
    for row in observations:
        if row["record_family"] != HOLDING_FAMILY:
            continue
        groups[tuple(row[field] for field in grain)].append(row)

    holdings: list[dict[str, object]] = []
    for key, cells in sorted(groups.items(), key=lambda item: tuple(str(part) for part in item[0])):
        document_id, page, table, label, occurrence, as_of_raw = key
        first = cells[0]
        holding: dict[str, object] = {
            "holding_id": _key("HOLD", *key),
            "document_id": document_id,
            "route": first["route"],
            "page_id": first["page_id"],
            "source_page": page,
            "source_table": table,
            "holding_label": label,
            "holding_alias_id": first["subject_alias_id"],
            "holding_entity_id": first["subject_entity_id"],
            "subject_type": first["subject_type"],
            # The industry belongs to the holding, not to any one of its cells,
            # so it comes from the group's first cell exactly as the currency
            # and the scale heading do.
            "sector": first["sector"],
            "source_occurrence": occurrence,
            "as_of_date_raw": as_of_raw,
            "as_of_date": first["as_of_date"],
            "currency": first["currency"],
            "unit_scale": first["unit_scale"],
            "unit_scale_multiplier": first["unit_scale_multiplier"],
            "observation_ids": ";".join(str(cell["observation_id"]) for cell in cells),
            "observation_count": len(cells),
            "collision_note": "",
        }
        clashes: list[str] = []
        for cell in cells:
            column = HOLDING_COLUMNS.get(str(cell["metric_category"]))
            if not column:
                continue
            source = matrices.mapping(HOLDING_VALUES).get(
                column, matrices.resolve(HOLDING_VALUES, "default_source")
            )
            value = (
                cell["value_numeric"]
                if source == "value_numeric"
                else cell["value_raw"] or cell["value_text"]
            )
            if column in holding and holding[column] not in (None, ""):
                clashes.append(f"{column}={cell['source_column_label']}")
                continue
            holding[column] = value
        if clashes:
            holding["collision_note"] = matrices.resolve(
                HOLDING_COLLISIONS, "collision_note_prefix"
            ) + ", ".join(sorted(clashes))
        holdings.append(holding)
    return holdings


def build_pages(coverage: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    seen: dict[str, dict[str, object]] = {}
    for row in coverage:
        document_id = row.get("file_id", "")
        page = row.get("source_page", "").strip()
        page_id = _key("PAGE", document_id, page)
        if page_id in seen and matrices.resolve(PAGE_ORDER, "repeated_page") != "last_row_wins":
            continue
        seen[page_id] = {
            "page_id": page_id,
            "document_id": document_id,
            "route": row.get("route", ""),
            "source_page": page,
            "page_status": row.get("page_status", ""),
            "layout_checked": row.get("layout_checked", ""),
            "source_structures": row.get("source_structures", ""),
            "relevant_record_families": row.get("relevant_record_families", ""),
            "expected_observation_count": row.get("expected_observation_count", ""),
            "records_written": row.get("records_written", ""),
            "notes": row.get("notes", ""),
        }
    return [seen[key] for key in sorted(seen, key=lambda k: (seen[k]["document_id"], seen[k]["source_page"]))]


def build_documents(
    records: Sequence[Mapping[str, str]],
    coverage: Sequence[Mapping[str, str]],
    holdings: Sequence[Mapping[str, object]],
    ledger: Mapping[str, Mapping[str, str]],
) -> list[dict[str, object]]:
    observation_counts = Counter(row["file_id"] for row in records)
    holding_counts = Counter(str(row["document_id"]) for row in holdings)
    pages_covered = Counter(row["file_id"] for row in coverage)
    data_rule = matrices.resolve(PAGE_DATA, "with_data")
    pages_with_data = Counter(
        row["file_id"]
        for row in coverage
        if data_rule == "records_written_positive"
        and (row.get("records_written") or "0").strip() not in {"", "0"}
    )
    first: dict[str, Mapping[str, str]] = {}
    first_wins = matrices.resolve(DOCUMENT_ORDER, "document_attributes") == "first_row_wins"
    for row in records:
        if first_wins:
            first.setdefault(row["file_id"], row)
        else:
            first[row["file_id"]] = row
    for row in coverage:
        if first_wins:
            first.setdefault(row["file_id"], row)
        else:
            first[row["file_id"]] = row

    documents: list[dict[str, object]] = []
    for document_id in sorted(first):
        record = first[document_id]
        entry = ledger.get(document_id, {})
        documents.append({
            "document_id": document_id,
            "filename": entry.get("filename", ""),
            "canonical_doc_type": record.get("canonical_doc_type", ""),
            "route": record.get("route", ""),
            "product_tier": record.get("product_tier", ""),
            "source_sha256": record.get("source_sha256", ""),
            "issuer": entry.get("issuer", ""),
            "issuer_type": entry.get("issuer_type", ""),
            "file_ext": entry.get("file_ext", ""),
            "ledger_page_count": entry.get("page_count", ""),
            "is_redacted": entry.get("is_redacted", ""),
            "source_url": entry.get("source_url", ""),
            "retrieved_at": entry.get("retrieved_at", ""),
            "pages_covered": pages_covered[document_id],
            "pages_with_data": pages_with_data[document_id],
            "observation_count": observation_counts[document_id],
            "holding_count": holding_counts[document_id],
        })
    return documents


def build_entities(
    aliases: Mapping[tuple[str, str], Mapping[str, object]],
    entity_counts: Counter,
    fund_families: Mapping[str, str] | None = None,
    fund_managers: Mapping[str, tuple[str, str]] | None = None,
) -> list[dict[str, object]]:
    registry = {
        (row["kind"], row["entity_id"]): row["standardized_name"]
        for row in read_csv(REGISTRY)
        if row.get("entity_id")
    }
    by_entity: dict[tuple[str, str], dict[str, object]] = {}
    for entry in aliases.values():
        entity_id = str(entry["entity_id"])
        if not entity_id:
            continue
        kind = str(entry["entity_kind"])
        key = (kind, entity_id)
        standard = str(entry["standardized_name"])
        manager, source = (fund_managers or {}).get(standard, ("", ""))
        record = by_entity.setdefault(key, {
            "entity_id": entity_id,
            "entity_kind": kind,
            "canonical_name": _first_ranked(
                NAME_ORDER,
                "dim_entity.canonical_name",
                {"registry_standardized_name": registry.get(key, ""), "alias_standardized_name": standard},
            ) or standard,
            "fund_family": (fund_families or {}).get(standard, ""),
            "manager_name": manager,
            "manager_source": source,
            "alias_count": 0,
            "observation_count": entity_counts.get(entity_id, 0),
        })
        record["alias_count"] = int(record["alias_count"]) + 1
    return [by_entity[key] for key in sorted(by_entity)]


def build_metrics(
    metric_counts: Counter,
    catalogue: set[str],
    observations: Sequence[Mapping[str, object]],
    standard_measures: Mapping[str, Mapping[str, str]],
) -> list[dict[str, object]]:
    """One row per printed metric, joined to its standard measure.

    The standard measure, its grain, and the note come from
    `METRIC-STANDARD-MEASURES.csv`, one authored row per metric_id. A metric
    with no row is a defect in that file and stops the build, because a blank
    standard measure would ship as if the question had been answered."""
    unused = sorted(set(standard_measures).difference(metric_counts))
    if unused:
        raise FlattenError(
            f"{STANDARD_MEASURES.name} has unpublished metric IDs: {', '.join(unused)}"
        )
    kinds: dict[str, Counter] = defaultdict(Counter)
    for row in observations:
        kinds[str(row["metric_id"])][str(row["value_kind"])] += 1
    metrics: list[dict[str, object]] = []
    for metric_id, count in sorted(metric_counts.items()):
        family, _, category = metric_id.partition(".")
        measure = standard_measures.get(metric_id)
        if measure is None:
            raise FlattenError(
                f"{STANDARD_MEASURES.name} has no row for {metric_id}; "
                "every published metric_id needs one"
            )
        metrics.append({
            "metric_id": metric_id,
            "record_family": family,
            "metric_category": category,
            "in_catalogue": (
                category in catalogue
                if category
                else matrices.resolve(CATALOGUE_STATUS, "without_category") == "true"
            ),
            "value_kind": (
                kinds[metric_id].most_common(1)[0][0]
                if kinds[metric_id] and matrices.resolve(METRIC_KIND_POLICY, "value_kind") == "most_common"
                else ""
            ),
            "observation_count": count,
            "standard_measure": measure["standard_measure"],
            "measure_scope": measure["measure_scope"],
            "note": measure["note"],
        })
    return metrics


def build_unresolved(
    aliases: Mapping[tuple[str, str], Mapping[str, object]]
) -> list[dict[str, object]]:
    rows = [
        {
            "entity_kind": entry["entity_kind"],
            "raw_name": entry["raw_name"],
            "normalized_name": entry["normalized_name"],
            "occurrences": entry["occurrences"],
            "documents": entry["documents"],
            "reason": matrices.resolve(RESOLUTION_STATUS, "unresolved_reason"),
        }
        for entry in aliases.values()
        if entry["match_method"] == "unresolved"
    ]
    return sorted(rows, key=lambda row: (row["entity_kind"], -int(row["occurrences"]), row["raw_name"]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        written = build_tables(args.output_dir)
    except FlattenError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    for name, count in sorted(written.items()):
        print(f"{name}: {count} rows")
    print(f"PASS: flattened -> {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
