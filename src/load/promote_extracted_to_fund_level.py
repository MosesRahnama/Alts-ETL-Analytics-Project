"""Write decided extraction into the fund tables.

The extraction layer is document-faithful: one row per printed cell, keyed by the
page it came from. The fund-level layer is what an analyst queries: one row per
fund and date, with commitment, paid-in, distributions, NAV, and the multiples
beside each other. This module is the mapping between them.

Three rules govern every row written here.

A fund-level row names its fund. An extracted observation whose subject is an
asset class, a pension plan, a portfolio, or a limited partner is a real fact
about something other than a fund, so it stays in the extraction layer instead
of being attached to a fund the document never printed on that row.

Printed values are carried, never recomputed. Where a document prints both TVPI
and the paid-in and distributions behind it, all three are promoted as printed
and the quality rules then test the identity. A promoted table that silently
recomputed its own inputs could not fail that test.

Promotion is gated. Every row carries `provenance_type=EXTRACTED`, and
`validate_round02_promotion.py` refuses any such row whose source document is
absent from the accepted batches under `ledgers/promotion-gate/round02/`. This
module writes that acceptance evidence from the published extraction ledger, so
the gate is answered with the dual-lane adjudication that actually happened.

Settled vintage and strategy from `data/normalization/fund-attributes-matrix.csv`
fill empty columns on `fund_periods` and `fund_master`. Printed context columns
on `fact_observation` are left as the page printed them.
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from src.common import matrices
from src.catalog.simple_pdf_extraction.fund_attributes import (
    STAMP_FIELDS,
    attribute_evidence_lookup,
    decided_lookup,
    stamp_rows_with_changes,
    write_attribute_changes,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TABLES_DIR = PROJECT_ROOT / "data" / "extracted" / "tables"
ROUNDS_DIR = PROJECT_ROOT / "data" / "extracted" / "rounds"
WORKING_DIR = PROJECT_ROOT / "ledgers" / "working" / "pdf-extraction-csv"
GATE_DIR = PROJECT_ROOT / "ledgers" / "promotion-gate" / "round02"
CSV_DIR = PROJECT_ROOT / "data" / "csv"
NORMALIZATION_DIR = PROJECT_ROOT / "data" / "normalization"

PREFIXES = "entity-prefix-routing"
TERM_COLUMN = "term-to-fund-terms-column"
IDENTIFIER_RULES = "identifier-generation-rules"
METRIC_ID_RULE = "identifier-composition"
MONEY_SIGNALS = "money-detection"
UNIT_SCALE = "unit-scale"
RATE_CONVERSION = "rate-unit-conversion"
OBSERVATION_DATES = "date-role-precision"
HOLDING_DATES = "date-role-precedence"
CASHFLOW_DATES = "cashflow-date-precedence"
ANCHOR_FORMAT = "evidence-anchor-format"
GATE_HASHES = "promotion-evidence-precedence"
GATE_LABELS = "promotion-decision-policy"
REPORTING_FUND = "document-reporting-fund-policy"
PERIOD_ADMISSION = "fund-period-admission"
CASHFLOW_ADMISSION = "cashflow-admission"
TERM_ADMISSION = "fund-term-admission"
CLAUSE_ADMISSION = "fund-term-clause-admission"
CASHFLOW_ATTRIBUTION = "cashflow-fund-attribution"
HOLDING_ATTRIBUTION = "holding-fund-attribution"
LINEAGE_DELIMITERS = "lineage-delimiter-rules"
HOLDING_VALUE = "holding-column-source"
HOLDING_FIELDS = "holding-field-map"
CURRENCY_DEFAULTS = "currency-defaults"
PERIOD_COLLISIONS = "collision-policy"
TERM_CONTEXT = "fund-term-context-precedence"
TERM_COLLISIONS = "fund-term-collision-policy"
FIXED_FIELDS = "promotion-fixed-fields"
POSITION_SCOPE = "fund-position-scope"
SOURCE_MASTER_FIELDS = "source-master-fields"
MAP_LABELS = "document-manager-role"
CATEGORY_ORDER = "category-field-precedence"
FIELD_ORDER = "field-fallback-order"
NAME_ORDER = "entity-name-precedence"
MANAGER_FIELD_ORDER = "observation-field-precedence"
MANAGER_MASTER_SOURCES = "manager-master-source-precedence"
MANAGER_MASTER_FIELDS = "manager-master-field-precedence"
MAP_IDENTITY = "document-manager-identity-precedence"
MAP_SOURCES = "document-manager-source-precedence"
MASTER_RETIREMENT = "fund-master-retirement-policy"
MASTER_SOURCES = "fund-master-source-precedence"
MASTER_FIELDS = "fund-master-field-map"
MASTER_INPUTS = "fund-master-input-precedence"

FUND_PREFIX = matrices.resolve(PREFIXES, "fund")
MANAGER_PREFIX = matrices.resolve(PREFIXES, "manager")
LP_PREFIX = matrices.resolve(PREFIXES, "investor")

# Which measure a category is, so a quality rule reads the right thing, which
# fund_periods column a printed category feeds, which horizons a period row may
# carry, what kind of number each column holds, and which cash-flow type a
# category becomes. Every one of those decisions is a row in a matrix under
# data/normalization/transformations, read here and checked by release stage 20.
# decisions; the asserts underneath prove the matrices say what the pipeline
MEASURE_BASIS = "metric-measure-basis"
PERIOD_COLUMN = "metric-to-period-column"
HORIZON_SCOPE = "horizon-scope"
COLUMN_KIND = "period-column-value-kind"
CASHFLOW_TYPE = "metric-to-cashflow-type"

# What each printed grouping reads as under one taxonomy. The flatten reads the
# same matrix under the same contexts, so a fund table and an evidence row agree
# on what `Real Estate` printed as a strategy heading names.
GROUPING_MAP = "context-grouping-map"
GROUPING_CONTEXTS = ("asset_class", "strategy", "sector")
CANONICAL_COLUMNS = (
    "canonical_asset_class", "canonical_strategy",
    "canonical_sub_strategy", "canonical_sector",
)

# How a canonical cell is labelled in the audit ledger. The same matrix carries
# the formula id and the imputation label stage 100 reads, so the stage that
# fills a canonical cell and the stage that carries it name it the same way.
CANONICAL_PROVENANCE = "fund-master-provenance"
CANONICAL_NOTE = (
    "Canonical grouping read from context-grouping-map.csv under the "
    "{context} context; the printed word and its page are unchanged."
)

_GROUPING: dict[tuple[str, str], dict[str, str]] | None = None


def _grouping_index() -> dict[tuple[str, str], dict[str, str]]:
    """The grouping matrix keyed by context and printed value."""

    return {
        (row.get("context", ""), row["input_value"]): row
        for row in matrices.load(GROUPING_MAP)
    }


def canonical_grouping_with_origins(
    record: dict[str, str],
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """The taxonomy reading, and the printed word each canonical cell came from.

    Each printed column is read under the context of the column it sits in, so a
    class heading names a class and an industry names an industry and never a
    class. A printed word the matrix does not carry leaves the reading blank
    rather than guessing one. The second return value names, per filled column,
    the context and the printed value the matrix row was found under, which is
    what the audit row for that cell has to cite."""

    global _GROUPING
    if _GROUPING is None:
        _GROUPING = _grouping_index()
    out = {name: "" for name in CANONICAL_COLUMNS}
    origins: dict[str, tuple[str, str]] = {}
    for context in GROUPING_CONTEXTS:
        printed = (record.get(context, "") or "").strip()
        if not printed:
            continue
        row = _GROUPING.get((context, printed))
        if row is None:
            continue
        if not out["canonical_asset_class"]:
            out["canonical_asset_class"] = matrices.decode(row["output_value"])
            if out["canonical_asset_class"]:
                origins["canonical_asset_class"] = (context, printed)
        for source, target in (
            ("canonical_strategy", "canonical_strategy"),
            ("canonical_sub_strategy", "canonical_sub_strategy"),
            ("sector", "canonical_sector"),
        ):
            if row.get(source, "") and not out[target]:
                out[target] = row[source]
                origins[target] = (context, printed)
    return out, origins


def canonical_grouping(record: dict[str, str]) -> dict[str, str]:
    """What a row's printed groupings are under one taxonomy."""

    return canonical_grouping_with_origins(record)[0]


def canonical_change_row(
    *,
    target_table: str,
    record_id: str,
    fund_id: str,
    field: str,
    value: str,
    context: str,
    printed: str,
    source: dict[str, str],
) -> dict[str, str]:
    """One attribute-changes row for a canonical cell this stage filled.

    A canonical cell is a reading of a printed word, so its audit row cites the
    observation that printed the word and names the matrix row the reading came
    from. Without it the cell reaches the published tables with no lineage at
    either grain, which is what stage 100 refuses."""

    seed = "|".join((target_table, record_id, field, value, source["source_observation_id"]))
    return {
        "change_id": "AC_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20],
        "stage_id": "canonical-grouping",
        "target_table": target_table,
        "target_record_id": record_id,
        "fund_id": fund_id,
        "field": field,
        "old_value": "",
        "new_value": value,
        "change_type": matrices.resolve(CANONICAL_PROVENANCE, "canonical_change_type"),
        **source,
        "rule_id": ":".join(
            (matrices.resolve(CANONICAL_PROVENANCE, "canonical_rule_prefix"), context, printed)
        ),
        "matrix_status": "",
        "notes": CANONICAL_NOTE.format(context=context),
    }


def grouping_evidence(row: dict[str, str], printed: str) -> dict[str, str]:
    """The six evidence cells naming the observation that printed a grouping."""

    return {
        "source_observation_id": row.get("observation_id", ""),
        "source_document_id": row.get("document_id", ""),
        "source_page": row.get("source_page", ""),
        "source_table": row.get("source_table", ""),
        "source_quote": row.get("evidence_quote", ""),
        "source_printed_value": printed,
    }


def master_canonical_changes(
    rows: list[dict[str, str]], evidence: dict[str, dict[str, dict[str, str]]]
) -> list[dict[str, str]]:
    """One audit row per canonical cell on fund_master.

    The printed word a master cell reads is a settled fund attribute, so the
    observation behind it is the one `attribute_evidence_lookup` already found
    for that attribute. A cell whose printed word this run cannot re-read, or
    whose attribute has no printed source, is named instead of published
    unsupported."""

    changes: list[dict[str, str]] = []
    for row in rows:
        fund_id = row.get("fund_id", "")
        reading, origins = canonical_grouping_with_origins(row)
        for field in CANONICAL_COLUMNS:
            value = (row.get(field, "") or "").strip()
            if not value:
                continue
            if reading.get(field) != value:
                raise ValueError(
                    f"fund_master {fund_id}: {field}={value!r} is not what "
                    f"{GROUPING_MAP}.csv reads off this row's printed groupings"
                )
            context, printed = origins[field]
            source = evidence.get(fund_id, {}).get(context)
            if source is None:
                raise ValueError(
                    f"fund_master {fund_id}: {field}={value!r} reads printed {context} "
                    f"{printed!r}, which no settled attribute of this fund cites"
                )
            changes.append(
                canonical_change_row(
                    target_table="fund_master",
                    record_id=fund_id,
                    fund_id=fund_id,
                    field=field,
                    value=value,
                    context=context,
                    printed=printed,
                    source=dict(source),
                )
            )
    return changes


def _period_policy(category: str, field: str) -> tuple[str, ...]:
    """The qualifier fields one column policy names for a printed category."""

    for row in matrices.load(PERIOD_COLUMN):
        if row["input_value"] == category:
            return tuple(part for part in (row.get(field, "") or "").split("|") if part)
    return ()


def required_qualifiers(category: str) -> tuple[str, ...]:
    """Which qualifiers the page must state before this category is admitted."""

    return _period_policy(category, "requires_stated")


def carried_qualifiers(category: str) -> tuple[str, ...]:
    """Which qualifiers travel onto the period row beside the placed value."""

    return _period_policy(category, "carries_qualifiers")


def routed_target_table(row: dict[str, str], category: str) -> str:
    """The table the map routes this observation to, before any table filter.

    Read without a target_table so a rule that routes to `none` is seen by every
    builder. Filtering by table first hides such a rule behind the absence of a
    rule for the table being built, which is how an evidence-only figure reached
    a promoted table."""

    rule = semantic_rule_for(row, category)
    return rule["target_table"] if rule else ""


def _ranked(name: str, context: str) -> tuple[str, ...]:
    rows = sorted(matrices.rows_in(name, context), key=lambda row: int(row["input_value"]))
    return tuple(row["output_value"] for row in rows)


def _ordered_outputs(name: str, context: str, input_prefix: str) -> tuple[str, ...]:
    rows = [
        row for row in matrices.rows_in(name, context)
        if row["input_value"].startswith(input_prefix)
    ]
    rows.sort(key=lambda row: int(row["input_value"].rsplit("_", 1)[-1]))
    return tuple(row["output_value"] for row in rows)


def _first_policy_value(name: str, context: str, values: dict[str, str]) -> str:
    return next((values.get(token, "") for token in _ranked(name, context) if values.get(token, "")), "")


def _policy_true(name: str, input_value: str, context: str = "") -> bool:
    value = matrices.resolve(name, input_value, context=context)
    if value not in {"true", "false"}:
        raise matrices.MatrixError(f"{name}: {input_value} must resolve to true or false")
    return value == "true"


def id_prefix(kind: str) -> str:
    return matrices.resolve(IDENTIFIER_RULES, kind)


def fixed(table: str) -> dict[str, str]:
    return {
        field: value
        for field, value in matrices.mapping(FIXED_FIELDS, context=table).items()
        if not field.endswith("_default")
    }


def currency_or_default(value: str, table: str) -> str:
    return value or matrices.resolve(CURRENCY_DEFAULTS, "", context=table)


def first_field(row: dict[str, str], name: str, context: str) -> str:
    """The first non-blank source named by a ranked chain of plain fields."""

    for field in _ranked(name, context):
        value = row.get(field, "")
        if value:
            return value
    return ""


def basis_order() -> tuple[str, ...]:
    """The category sets in the order the matrix ranks them."""

    ranked = {
        row["context"]: int(row["rank"])
        for row in matrices.load(MEASURE_BASIS)
        if row["context"] not in {"value_kind", "date"}
    }
    return tuple(sorted(ranked, key=lambda context: ranked[context]))


SEMANTIC_MAP = "metric-semantic-map"
SCHEMA_ADDITIONS = "promotion-schema-additions"

# The map's own token for a rule that routes a figure to no table: the value is
# evidence and is never promoted. assert_no_target_table_is_live proves the
# token still names rules, so renaming it in the matrix cannot quietly turn the
# refusal into a promotion.
NO_TARGET_TABLE = "none"
STANDARD_MEASURES_PATH = "data/schemas/METRIC-STANDARD-MEASURES.csv"
STANDARD_MEASURE_TOKEN = "standard_measure_of_metric"

_STANDARD_MEASURE_BY_ID: dict[str, str] | None = None


def _standard_measure_by_id() -> dict[str, str]:
    global _STANDARD_MEASURE_BY_ID
    if _STANDARD_MEASURE_BY_ID is None:
        _STANDARD_MEASURE_BY_ID = {
            row["metric_id"]: row["standard_measure"]
            for row in read_csv(PROJECT_ROOT / STANDARD_MEASURES_PATH)
        }
    return _STANDARD_MEASURE_BY_ID


def semantic_rule_for(
    row: dict[str, str], category: str, target_table: str = ""
) -> dict[str, str] | None:
    """The highest-priority semantic-map rule this observation matches.

    A blank condition cell is a wildcard; label_pattern is a case-insensitive
    regex over the printed metric_name. Priority ascends; conflicting ties fail.
    A row matching no rule is UNMAPPED, never silently routed.
    """
    rules = sorted(matrices.load(SEMANTIC_MAP), key=lambda rule: int(rule["priority"]))
    matches = []
    for rule in rules:
        if rule.get("document_id") and rule["document_id"] != row.get("document_id"):
            continue
        if rule.get("excluded_record_family") and rule["excluded_record_family"] == row.get("record_family"):
            continue
        if rule["source_category"] and rule["source_category"] != category:
            continue
        if rule["record_family"] and rule["record_family"] != row.get("record_family", ""):
            continue
        if rule["subject_type"] and rule["subject_type"] != row.get("subject_type", ""):
            continue
        if rule["value_scope"] and rule["value_scope"] != row.get("value_scope", ""):
            continue
        if rule["method"] and rule["method"] != row.get("method", ""):
            continue
        if rule["fee_basis"] and rule["fee_basis"] != row.get("fee_basis", ""):
            continue
        if rule["unit"] and rule["unit"] != row.get("unit", ""):
            continue
        if rule["label_pattern"] and not re.search(
            rule["label_pattern"], row.get("metric_name", ""), re.IGNORECASE
        ):
            continue
        matches.append(rule)
    if not matches:
        return None
    best = [rule for rule in matches if rule["priority"] == matches[0]["priority"]]
    decisions = {(r["output_value"], r["target_table"], r["target_column"]) for r in best}
    if len(decisions) != 1:
        raise ValueError(f"Conflicting semantic rules for {row.get('observation_id', category)}: "
                         + ", ".join(r["input_value"] for r in best))
    chosen = best[0]
    return chosen if not target_table or chosen["target_table"] == target_table else None


def assert_map_restates_period_columns() -> None:
    """metric-to-period-column.csv stays the authority the map's baseline rows
    restate; a divergence between the two is an error, not a preference."""
    expected = matrices.mapping(PERIOD_COLUMN)
    baseline = {
        rule["source_category"]: rule["target_column"]
        for rule in matrices.load(SEMANTIC_MAP)
        if rule["target_table"] == "fund_periods" and int(rule["priority"]) == 100
    }
    if baseline != expected:
        drift = sorted(set(baseline.items()) ^ set(expected.items()))
        raise matrices.MatrixError(
            f"{SEMANTIC_MAP}: baseline period rules diverge from {PERIOD_COLUMN}: {drift}"
        )


def assert_no_target_table_is_live() -> None:
    """The evidence-only routing token still names rules in the map.

    Both builders refuse a row the map routes to `none`. If the matrix renamed
    that token, every refusal would silently become a promotion, so the token is
    checked against the map rather than trusted."""

    if not any(rule["target_table"] == NO_TARGET_TABLE for rule in matrices.load(SEMANTIC_MAP)):
        raise matrices.MatrixError(
            f"{SEMANTIC_MAP}: no rule routes to {NO_TARGET_TABLE!r}; the evidence-only refusal is dead"
        )


def canonical_measure_of(rule: dict[str, str] | None, metric_id: str) -> str:
    if rule is None:
        return ""
    if rule["output_value"] == STANDARD_MEASURE_TOKEN:
        return _standard_measure_by_id().get(metric_id, "")
    return rule["output_value"]


def column_of(category: str) -> str | None:
    """The fund_periods column a printed category feeds, or None."""

    return matrices.mapping(PERIOD_COLUMN).get(category)


def period_eligible(horizon: str) -> bool:
    return matrices.mapping(HORIZON_SCOPE).get(horizon) == "period_eligible"


def column_kind(column: str) -> str:
    return matrices.resolve_or_star(COLUMN_KIND, column)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def header_of(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], header_path: Path | None = None) -> int:
    """Write rows under the header already on disk, so the contract is fixed by
    the DDL and this module can only fill columns that were declared. A column
    appended by a later contract is declared in promotion-schema-additions.csv
    and joins the header here, matching its DDL line.

    `header_path` names where the contract is read from when the rows are being
    written somewhere else, which is how a trial run into another directory
    keeps the published header without writing to the published file."""
    fieldnames = header_of(header_path or path)
    for addition in matrices.load(SCHEMA_ADDITIONS):
        table, _, column = addition["input_value"].partition(":")
        if table == (header_path or path).stem and column not in fieldnames:
            if addition["output_value"] != "append":
                raise matrices.MatrixError(
                    f"{SCHEMA_ADDITIONS}: unsupported placement {addition['output_value']!r}"
                )
            fieldnames.append(column)
    for row in rows:
        unknown = set(row) - set(fieldnames)
        if unknown:
            raise ValueError(f"{path.name}: undeclared column(s) {sorted(unknown)}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    return len(rows)


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def stable_id(prefix: str, *parts: str) -> str:
    """A deterministic key, so rerunning the promotion rewrites the same rows
    instead of renumbering every downstream reference. The prefixes, the
    algorithm, and the length are the rows of identifier-generation-rules.csv;
    every call site takes its prefix through id_prefix."""
    rules = matrices.rows_in(IDENTIFIER_RULES, "rule")
    if len(rules) != 1:
        raise matrices.MatrixError(f"{IDENTIFIER_RULES}: expected one rule row")
    rule = rules[0]
    algorithm = rule["algorithm"]
    separator = rule["separator"]
    hash_length = int(rule["hash_length"])
    seed = separator.join(parts)
    digest_value = hashlib.new(algorithm, seed.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest_value[:hash_length]}"


def metric_id_from_policy(
    row: dict[str, str], category: str, name: str, context: str, fallback_prefix: str
) -> str:
    return _first_policy_value(
        name,
        context,
        {
            "metric_id": row.get("metric_id", ""),
            "<record_family_dot_category>": f"{row['record_family']}.{category}",
            "<legal_dot_term_category>": f"{fallback_prefix}.{row.get('term_category', '')}",
        },
    )


def measure_basis(category: str, value_kind: str, has_date: bool) -> str:
    """The measure a value carries, from the matrix, in its ranked order.

    A printed multiple is tested first and returns the same bucket the ratio
    categories do, which is what the sequence of membership tests did before the
    rows moved to `metric-measure-basis.csv`."""

    if value_kind == "multiple":
        return matrices.resolve(MEASURE_BASIS, "multiple", context="value_kind")
    for basis in basis_order():
        if category in matrices.mapping(MEASURE_BASIS, context=basis):
            return matrices.resolve(MEASURE_BASIS, category, context=basis)
    if value_kind == "percent":
        return matrices.resolve(MEASURE_BASIS, "percent", context="value_kind")
    return matrices.resolve(MEASURE_BASIS, "dated" if has_date else "undated", context="date")


def is_money(row: dict[str, str]) -> bool:
    """Whether a printed value is an amount of money.

    `value_kind` records whether the cell itself printed a currency symbol, so a
    schedule that puts the `$` once in the column heading and bare numbers under
    it yields `number`. The currency code is populated either way, so that is
    what decides, and a cell carrying no currency at all is not treated as
    money. The signals that count are the rows of money-detection.csv."""
    signals = matrices.mapping(MONEY_SIGNALS)
    if signals.get("currency_field_populated") == "money" and row.get("currency", ""):
        return True
    return signals.get("value_kind_currency") == "money" and row.get("value_kind", "") == "currency"


def scaled_amount(row: dict[str, str]) -> str:
    """The printed number brought onto a common scale.

    Extraction stores what the page printed and keeps the `$ in millions`
    heading beside it, which is right for a document-faithful layer and wrong
    for an analytical one: a fund whose NAV came off a millions table and whose
    paid-in came off an absolute table would produce an RVPI a million times
    too large. Money is scaled here; a ratio, rate, or multiple carries no
    scale heading and is passed through as printed."""
    value = row.get("value_numeric", "")
    applies_to = matrices.resolve(UNIT_SCALE, "applies_to")
    if applies_to != "money_only":
        raise matrices.MatrixError(f"{UNIT_SCALE}: unsupported applies_to {applies_to!r}")
    if not value or not is_money(row):
        return value
    source = matrices.resolve(UNIT_SCALE, "multiplier_source")
    blank = matrices.resolve(UNIT_SCALE, "blank_multiplier")
    multiplier = row.get(source, "") or blank
    if multiplier == blank:
        return value
    scaled = float(value) * float(multiplier)
    decimals = int(matrices.resolve(UNIT_SCALE, "rounding_decimals"))
    return f"{scaled:.{decimals}f}".rstrip("0").rstrip(".")


def period_cell(column: str, row: dict[str, str]) -> str | None:
    """The value for one period column, or None when the printed kind and the
    column disagree.

    `reported_irr` is stored as a decimal rate because that is the unit the
    fund-level model and the quality rules are written in, so a page printing
    `9.00%` lands as `0.09`; the printed string stays in fund_observations."""
    kind = row.get("value_kind", "")
    value = row.get("value_numeric", "")
    holds = column_kind(column)
    if holds == "money":
        return scaled_amount(row) if is_money(row) else None
    if holds == "ratio":
        return value if kind in {"number", "multiple"} and not is_money(row) else None
    if holds == "rate":
        if kind == "percent":
            divisor = float(matrices.resolve(RATE_CONVERSION, "divisor"))
            decimals = int(matrices.resolve(RATE_CONVERSION, "rounding_decimals"))
            return f"{float(value) / divisor:.{decimals}f}".rstrip("0").rstrip(".")
        number_policy = matrices.resolve(RATE_CONVERSION, "number_kind")
        if number_policy != "as_printed":
            raise matrices.MatrixError(f"{RATE_CONVERSION}: unsupported number_kind {number_policy!r}")
        return value if kind == "number" else None
    return value


def date_fields(row: dict[str, str]) -> dict[str, str]:
    as_of = row.get("as_of_date", "")
    dates = matrices.mapping(OBSERVATION_DATES, context="observation")
    return {
        "date_role": dates["dated_role"] if as_of else dates["undated_role"],
        "date_raw": row.get("as_of_date_raw", ""),
        "date_precision": row.get("date_precision", "")
        or (dates["dated_precision_default"] if as_of else dates["undated_precision"]),
        "as_of_date": as_of,
        "period_start_date": row.get("period_start", ""),
        "period_end_date": row.get("period_end", ""),
    }


def anchor_fields(context: str) -> tuple[tuple[str, ...], str]:
    rows = matrices.rows_in(ANCHOR_FORMAT, context)
    ranked = sorted(
        (row for row in rows if row["output_value"] == "anchor_part"),
        key=lambda row: int(row["rank"]),
    )
    separator = next(row["output_value"] for row in rows if row["input_value"] == "separator")
    return tuple(row["input_value"] for row in ranked), separator


def source_anchor(row: dict[str, str], context: str = "observation") -> str:
    """Where on the page the value was printed, in the extraction layer's own
    terms, so a promoted number can be walked back to the cell. The fields and
    their order are the rows of evidence-anchor-format.csv."""
    fields, separator = anchor_fields(context)
    return separator.join(part for field in fields if (part := row.get(field, "")))


# --------------------------------------------------------------------------
# Stage 1: the acceptance evidence the promotion gate reads


def write_gate_evidence(observations: list[dict[str, str]]) -> dict[str, int]:
    """Record, per extraction route, which documents were adjudicated and are
    therefore admissible. Every fact comes off the published ledger: the route,
    the document, its source hash, and the hash of the adjudicated final file."""
    by_route: dict[str, set[str]] = defaultdict(set)
    for row in observations:
        by_route[row["route"]].add(row["document_id"])

    hashes = {row["document_id"]: row.get("source_sha256", "") for row in observations if row.get("source_sha256")}
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    progress: list[dict[str, str]] = []
    accepted = 0

    for route in sorted(by_route):
        batch_dir = GATE_DIR / route
        batch_dir.mkdir(parents=True, exist_ok=True)
        files = []
        worksheet = []
        for file_id in sorted(by_route[route]):
            final_path = WORKING_DIR / route / file_id / "records-final.csv"
            if not final_path.is_file():
                raise FileNotFoundError(f"no adjudicated final file for {route}/{file_id}")
            final_rows = read_csv(final_path)
            hash_values = {
                "published_ledger_hash": hashes.get(file_id, ""),
                "final_file_first_row_hash": final_rows[0]["source_sha256"] if final_rows else "",
            }
            source_sha = next(
                (
                    hash_values.get(source_name, "")
                    for source_name in _ordered_outputs(GATE_HASHES, "gate", "source_sha_")
                    if hash_values.get(source_name, "")
                ),
                "",
            )
            files.append({"file_id": file_id, "source_sha256": source_sha})
            worksheet.append({
                "batch_id": route,
                "file_id": file_id,
                "source_sha256": source_sha,
                "final_file_sha256": digest(final_path),
                "final_row_count": str(len(final_rows)),
                "lanes": matrices.resolve(GATE_LABELS, "lanes", context="gate"),
                "decision": matrices.resolve(GATE_LABELS, "decision", context="gate"),
                "reason": matrices.resolve(GATE_LABELS, "reason", context="gate"),
            })
            accepted += 1
        (batch_dir / "assignment.json").write_text(
            json.dumps(
                {
                    "batch_id": route,
                    "round_id": matrices.resolve(GATE_LABELS, "round_id", context="gate"),
                    "files": files,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        with (batch_dir / "worksheet.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(worksheet[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(worksheet)
        progress.append({
            "batch_id": route,
            "round_id": matrices.resolve(GATE_LABELS, "round_id", context="gate"),
            "file_count": str(len(files)),
            "status": matrices.resolve(GATE_LABELS, "status", context="gate"),
        })

    with (GATE_DIR / "progress.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(progress[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(progress)
    return {"batches": len(progress), "documents": accepted}


# --------------------------------------------------------------------------
# Stage 2: fund-scoped observations


def fund_position_context(observations: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    """Resolve explicitly qualified fund positions to their document's investor."""
    investors = {r["document_id"]: r.get("investor_entity_id", "") for r in observations
                 if r.get("record_family") == "document_context"}
    policy = matrices.mapping(POSITION_SCOPE)
    scopes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in observations:
        if row.get("subject_entity_id", "").startswith(FUND_PREFIX) and row.get("value_scope") in policy:
            scopes[row["subject_entity_id"], row["document_id"]].add(policy[row["value_scope"]])
    result = {}
    for key, values in scopes.items():
        if len(values) > 1:
            raise ValueError(f"Conflicting whole-fund and investor scopes for {key}")
        if "lp_position" in values:
            investor = investors.get(key[1], "")
            if not investor:
                raise ValueError(f"Fund position lacks a named document investor: {key}")
            result[key] = {"perspective": "lp_position", "lp_id": investor}
    return result


def build_fund_observations(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    positions = fund_position_context(observations)
    unmapped = 0
    refused = 0
    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        if not fund_id.startswith(FUND_PREFIX):
            continue
        category = first_field(row, CATEGORY_ORDER, "fund_observations.category")
        dates = date_fields(row)
        metric_id = metric_id_from_policy(
            row,
            category,
            METRIC_ID_RULE,
            "fund_observations.metric_id",
            row["record_family"],
        )
        rule = semantic_rule_for(row, category)
        if rule is None:
            unmapped += 1
        # A rule that routes to `none` says the figure is evidence and never a
        # promoted value. build_fund_periods reads the same routing, so an
        # actuarial assumed rate is refused at both grains instead of one.
        elif rule["target_table"] == NO_TARGET_TABLE:
            refused += 1
            continue
        rows.append({
            "observation_id": row["observation_id"],
            "fund_id": fund_id,
            "file_id": row["document_id"],
            "metric_id": metric_id,
            "canonical_measure_id": canonical_measure_of(rule, metric_id),
            "mapping_rule_id": rule["input_value"] if rule else "UNMAPPED",
            **dates,
            "value_raw": row.get("value_raw", ""),
            "value_numeric": row.get("value_numeric", ""),
            "value_text": row.get("value_text", ""),
            "currency": row.get("currency", ""),
            "unit": first_field(row, FIELD_ORDER, "fund_observations.unit"),
            "measure_basis": measure_basis(category, row.get("value_kind", ""), bool(dates["as_of_date"])),
            # What the number means, carried from the page's own statement. A
            # rate whose method and fee basis stay behind in the extraction
            # layer is a number a reader cannot compare with another.
            "method": row.get("method", ""),
            "fee_basis": row.get("fee_basis", ""),
            "definition_keys": row.get("definition_keys", ""),
            "value_scope": row.get("value_scope", ""),
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "extractor_version": row.get("contract_version", ""),
            **fixed("fund_observations"),
            **positions.get((fund_id, row["document_id"]), {}),
        })
    global _LAST_UNMAPPED, _LAST_EVIDENCE_ONLY
    _LAST_UNMAPPED = unmapped
    _LAST_EVIDENCE_ONLY = refused
    return rows


# The last build's count of fund-scoped rows no semantic-map rule matched,
# reported by promote() so the release output carries it.
_LAST_UNMAPPED = 0

# The last build's count of fund-scoped rows the map routes to no table.
_LAST_EVIDENCE_ONLY = 0


# --------------------------------------------------------------------------
# Stage 3: one row per fund and date


def build_fund_periods(
    observations: list[dict[str, str]],
) -> tuple[list[dict[str, str]], int, list[dict[str, str]]]:
    """Collapse the fund-scoped economics onto the (fund, date) grain.

    The grain carries the document as well as the fund and the date. Two reports
    can state the same fund's NAV on the same quarter end and disagree, and a row
    that averaged them or picked one would bury that; keeping the document on the
    key leaves the disagreement visible and traceable to two pages.

    A cell is placed only where the contract category has a column at this grain
    and the number is not scoped to a horizon window. Where one document prints
    the same category twice for one fund and date, the first is kept and the
    collision is counted, because choosing between two printed values is an
    adjudication and this module performs none."""
    groups: dict[tuple[str, str, str], dict[str, str]] = {}
    positions = fund_position_context(observations)
    first_evidence: dict[tuple[str, str, str], dict[str, str]] = {}
    currencies: dict[tuple[str, str, str], str] = {}
    sources: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    # The printed grouping words the period's own observations carried, first
    # non-blank per column, read into the taxonomy once the group is complete.
    groupings: dict[tuple[str, str, str], dict[str, str]] = defaultdict(dict)
    # The observation that printed each of those words, so the canonical cell
    # read off it cites a page instead of the group as a whole.
    grouping_rows: dict[tuple[str, str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    collisions = 0
    mismatches: list[dict[str, str]] = []
    period_admission = matrices.mapping(PERIOD_ADMISSION)
    subject_prefix = matrices.resolve(PREFIXES, period_admission["subject_prefix"])
    repeat_policy = matrices.resolve(
        PERIOD_COLLISIONS, "repeat_within_document", context="fund_periods"
    )
    collision_record = matrices.resolve(
        PERIOD_COLLISIONS, "collision_record", context="fund_periods"
    )
    lineage_separator = matrices.resolve(LINEAGE_DELIMITERS, "observation_ids_separator")

    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        as_of = row.get("as_of_date", "")
        category = row.get("metric_category", "")
        period_rule = semantic_rule_for(row, category, target_table="fund_periods")
        column = period_rule["target_column"] if period_rule else None
        if not fund_id.startswith(subject_prefix):
            continue
        # The map's own routing decides first. A rule that sends this figure to
        # no table means it is evidence, and a baseline column rule for its
        # category must not overturn that.
        if routed_target_table(row, category) == NO_TARGET_TABLE:
            continue
        if _policy_true(PERIOD_ADMISSION, "requires_as_of_date") and not as_of:
            continue
        if _policy_true(PERIOD_ADMISSION, "requires_period_column") and column is None:
            continue
        if column is None:
            continue
        # A qualified category joins a comparable column only where the page
        # states its qualifiers. `unstated` is a statement and is admitted; a
        # blank is a row the extraction never qualified, so it stays an
        # observation and is reported as a mismatch rather than dropped quietly.
        missing = [
            qualifier
            for qualifier in required_qualifiers(category)
            if not (row.get(qualifier, "") or "").strip()
        ]
        if missing:
            mismatches.append({
                "observation_id": row["observation_id"],
                "document_id": row["document_id"],
                "source_page": row.get("source_page", ""),
                "source_row_label": row.get("source_row_label", ""),
                "source_column_label": row.get("source_column_label", ""),
                "fund_id": fund_id,
                "metric_category": category,
                "period_column": column,
                "value_kind": row.get("value_kind", ""),
                "value_raw": row.get("value_raw", ""),
                "finding": (
                    f"category {category} states no {' and no '.join(missing)}; "
                    f"{PERIOD_COLUMN} admits it to {column} only with a stated qualifier, "
                    "so it stays in fund_observations"
                ),
            })
            continue
        if _policy_true(PERIOD_ADMISSION, "requires_eligible_horizon") and not period_eligible(
            (row.get("horizon", "") or "").strip()
        ):
            continue
        if _policy_true(PERIOD_ADMISSION, "requires_numeric_value") and not row.get(
            "value_numeric", ""
        ):
            continue
        value = period_cell(column, row)
        if value is None:
            mismatches.append({
                "observation_id": row["observation_id"],
                "document_id": row["document_id"],
                "source_page": row.get("source_page", ""),
                "source_row_label": row.get("source_row_label", ""),
                "source_column_label": row.get("source_column_label", ""),
                "fund_id": fund_id,
                "metric_category": category,
                "period_column": column,
                "value_kind": row.get("value_kind", ""),
                "value_raw": row.get("value_raw", ""),
                "finding": f"category {category} expects a {'currency' if column_kind(column) == 'money' else 'numeric'} value, page printed {row.get('value_kind', '')}",
            })
            continue
        key = (fund_id, as_of, row["document_id"])
        denomination = row.get(period_admission["currency_field"], "") if column_kind(column) == "money" else ""
        if denomination:
            if currencies.get(key, denomination) != denomination:
                if period_admission["currency_conflict"] != "reject":
                    raise matrices.MatrixError("Unsupported fund-period currency conflict policy")
                raise ValueError(f"Conflicting monetary currencies for fund period {key}")
            currencies[key] = denomination
        period = groups.setdefault(key, {})
        first_evidence.setdefault(key, row)
        if column in period:
            if collision_record == "count_only":
                collisions += 1
            else:
                raise matrices.MatrixError(
                    f"{PERIOD_COLLISIONS}: unsupported collision_record {collision_record!r}"
                )
            if repeat_policy == "first_value_kept":
                continue
            raise matrices.MatrixError(
                f"{PERIOD_COLLISIONS}: unsupported repeat policy {repeat_policy!r}"
            )
        period[column] = value
        # The qualifiers travel with the value they qualify, under that column's
        # own name, so a net and a gross money-weighted rate never share
        # reported_irr with nothing to tell them apart.
        for qualifier in carried_qualifiers(category):
            period[f"{column}_{qualifier}"] = (row.get(qualifier, "") or "").strip()
        for name, printed in _printed_groupings(row).items():
            if printed and not groupings[key].get(name):
                groupings[key][name] = printed
                grouping_rows[key][name] = row
        sources[key].append(row["observation_id"])

    rows = []
    changes: list[dict[str, str]] = []
    for key, values in sorted(groups.items()):
        fund_id, as_of, document_id = key
        printed = groupings[key]
        reading, origins = canonical_grouping_with_origins(printed)
        period_id = stable_id(id_prefix("fund_period"), fund_id, as_of, document_id)
        position = positions.get((fund_id, document_id), {})
        if position:
            period_id = stable_id(id_prefix("fund_period"), fund_id, as_of, document_id, position["lp_id"])
        for field, value in reading.items():
            if not value:
                continue
            context, printed_value = origins[field]
            changes.append(
                canonical_change_row(
                    target_table="fund_periods",
                    record_id=period_id,
                    fund_id=fund_id,
                    field=field,
                    value=value,
                    context=context,
                    printed=printed_value,
                    source=grouping_evidence(grouping_rows[key][context], printed_value),
                )
            )
        rows.append({
            "fund_period_id": period_id,
            "fund_id": fund_id,
            "as_of_date": as_of,
            "source_document_id": document_id,
            "input_observation_ids": lineage_separator.join(sorted(sources[key])),
            "sector": printed.get("sector", ""),
            **reading,
            **fixed("fund_periods"),
            **positions.get((fund_id, document_id), {}),
            "currency": currencies.get(key, ""),
            "date_raw": first_evidence[key].get("as_of_date_raw", ""),
            "source_page": first_evidence[key].get("source_page", ""),
            "source_anchor": source_anchor(first_evidence[key]),
            **values,
        })
    global _LAST_PERIOD_CANONICAL_CHANGES
    _LAST_PERIOD_CANONICAL_CHANGES = changes
    return rows, collisions, mismatches


# The last build's audit rows for the canonical cells it read onto the periods,
# reported through promote() the way the unmapped counts above are. The builder
# keeps its three-value return, and the printed words a canonical cell was read
# from live only inside it, so they are recorded here as they are found.
_LAST_PERIOD_CANONICAL_CHANGES: list[dict[str, str]] = []


def _printed_groupings(row: dict[str, str]) -> dict[str, str]:
    """The printed grouping words an observation carries, by their own column."""

    return {
        context: (row.get(context, "") or "").strip() for context in GROUPING_CONTEXTS
    }


# --------------------------------------------------------------------------
# Stages 4 to 7


def reporting_fund_by_document() -> dict[str, str]:
    """The fund a document reports on, where one document names exactly one.

    A capital-account statement prints its cash flows against the investor, not
    against the fund, so the fund has to come from the document. This lookup
    uses `document_fund_map.csv` only where that map settled on a single fund.
    """
    path = PROJECT_ROOT / matrices.resolve(REPORTING_FUND, "map_source")
    required = int(matrices.resolve(REPORTING_FUND, "distinct_funds_required"))
    if not path.is_file():
        return {}
    by_document: dict[str, set[str]] = defaultdict(set)
    for row in read_csv(path):
        if row.get("fund_id"):
            by_document[row["file_id"]].add(row["fund_id"])
    return {doc: next(iter(funds)) for doc, funds in by_document.items() if len(funds) == required}


def cashflow_event_rows(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    """Select dated event totals without adding their components or schedule totals."""
    policy = matrices.mapping("cashflow-selection")
    groups: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in observations:
        if row.get("record_family") == matrices.resolve(CASHFLOW_ADMISSION, "record_family"):
            groups[tuple(row.get(key, "") for key in policy["schedule_key"].split("|"))].append(row)
    selected = []
    for schedule in groups.values():
        events: dict[str, list[dict[str, str]]] = defaultdict(list)
        has_events = any(
            not re.search(policy["summary_row_pattern"], row.get("source_row_label", ""))
            and row.get("as_of_date") for row in schedule
        )
        for row in schedule:
            label = row.get("source_row_label", "")
            if has_events and re.search(policy["summary_row_pattern"], label):
                continue
            events[label].append(row)
        for event in events.values():
            totals = [row for row in event if re.search(
                policy["total_column_pattern"], row.get("source_column_label", "")
            )]
            if len(totals) > 1:
                raise ValueError(f"Multiple cash-flow totals at {totals[0].get('document_id')} "
                                 f"page {totals[0].get('source_page')}: {totals[0].get('source_row_label')}")
            selected.extend(totals or event)
    return selected


def economic_cashflow_amount(row: dict[str, str], cashflow_type: str) -> str:
    """Normalize the investor's economic sign; the printed value remains in evidence."""
    amount = scaled_amount(row)
    sign = matrices.resolve_or_star("cashflow-sign-policy", cashflow_type)
    if sign == "negative" and amount:
        return format(-abs(Decimal(amount)), "f")
    if sign == "positive" and amount:
        return format(abs(Decimal(amount)), "f")
    return amount


def build_fund_cashflows(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    reporting_fund = reporting_fund_by_document()
    rows = []
    admitted_family = matrices.resolve(CASHFLOW_ADMISSION, "record_family")
    attribution_order = _ordered_outputs(
        CASHFLOW_ATTRIBUTION, "fund_cashflows", "source_"
    )
    for row in cashflow_event_rows(observations):
        if row.get("record_family") != admitted_family:
            continue
        subject = row.get("subject_entity_id", "")
        attribution_values = {
            "subject_when_fund": subject if subject.startswith(FUND_PREFIX) else "",
            "document_reporting_fund": reporting_fund.get(row["document_id"], ""),
        }
        fund_id = next(
            (attribution_values[source] for source in attribution_order if attribution_values[source]),
            "",
        )
        if _policy_true(CASHFLOW_ADMISSION, "requires_fund_attribution") and not fund_id:
            continue
        investor = subject if subject.startswith(LP_PREFIX) else ""
        cashflow_type = matrices.resolve_or_star(CASHFLOW_TYPE, row.get("metric_category", ""))
        date = next(
            (
                row.get(field, "")
                for field in _ordered_outputs(CASHFLOW_DATES, "cashflow", "date_source_")
                if row.get(field, "")
            ),
            "",
        )
        if _policy_true(CASHFLOW_ADMISSION, "requires_date") and not date:
            continue
        if _policy_true(CASHFLOW_ADMISSION, "requires_numeric_value") and not row.get(
            "value_numeric", ""
        ):
            continue
        raw_values = {"<resolved_date>": date, **row}
        date_raw = next(
            (
                raw_values.get(field, "")
                for field in _ordered_outputs(CASHFLOW_DATES, "cashflow", "raw_source_")
                if raw_values.get(field, "")
            ),
            "",
        )
        rows.append({
            "cashflow_id": stable_id(id_prefix("cashflow"), row["observation_id"]),
            "fund_id": fund_id,
            "lp_id": investor,
            "lp_name": first_field(row, NAME_ORDER, "fund_cashflows.lp_name") if investor else "",
            "file_id": row["document_id"],
            "date_role": matrices.resolve(CASHFLOW_DATES, "role", context="cashflow"),
            # The date as the page printed it. Where the cell carried no date
            # string of its own, the resolved date stands in so the lineage rule
            # still has a raw value to check.
            "date_raw": date_raw,
            "date_precision": row.get("date_precision", "")
            or matrices.resolve(CASHFLOW_DATES, "precision_default", context="cashflow"),
            "cashflow_date": date,
            "cashflow_type": cashflow_type,
            "amount": economic_cashflow_amount(row, cashflow_type),
            "currency": currency_or_default(row.get("currency", ""), "fund_cashflows"),
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            **fixed("fund_cashflows"),
        })
    return rows


def build_fund_terms(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    """One row per fund carrying whatever operative terms its documents printed.

    `legal_term` rows are one clause each, so they are folded onto the fund they
    govern; a term the corpus never printed stays blank instead of taking a
    market-standard default."""
    numeric_terms = matrices.mapping(TERM_COLUMN)
    admitted_family = matrices.resolve(TERM_ADMISSION, "record_family")
    subject_prefix = matrices.resolve(
        PREFIXES, matrices.resolve(TERM_ADMISSION, "subject_prefix")
    )
    context_policy = matrices.resolve(
        TERM_CONTEXT, "shared_context_source", context="fund_terms"
    )
    repeat_policy = matrices.resolve(
        TERM_COLLISIONS, "repeat_within_fund", context="fund_terms"
    )
    by_fund: dict[str, dict[str, str]] = {}
    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        if not fund_id.startswith(subject_prefix) or row.get("record_family") != admitted_family:
            continue
        column = numeric_terms.get(row.get("term_category", ""))
        if context_policy != "first_admitted_row":
            raise matrices.MatrixError(
                f"{TERM_CONTEXT}: unsupported shared_context_source {context_policy!r}"
            )
        entry = by_fund.setdefault(fund_id, {
            "fund_term_id": stable_id(id_prefix("fund_term"), fund_id),
            "fund_id": fund_id,
            "source_document_id": row["document_id"],
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "currency": row.get("currency", ""),
            **fixed("fund_terms"),
        })
        if column and row.get("value_numeric", ""):
            if column not in entry:
                entry[column] = scaled_amount(row)
            elif repeat_policy != "first_value_kept":
                raise matrices.MatrixError(
                    f"{TERM_COLLISIONS}: unsupported repeat policy {repeat_policy!r}"
                )
    return sorted(by_fund.values(), key=lambda item: item["fund_id"])


def build_fund_term_clauses(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    subject_prefix = matrices.resolve(
        PREFIXES, matrices.resolve(CLAUSE_ADMISSION, "subject_prefix")
    )
    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        if not fund_id.startswith(subject_prefix):
            continue
        if row.get("record_family") not in set(matrices.resolve(CLAUSE_ADMISSION, "record_family").split("|")):
            continue
        rows.append({
            "fund_term_clause_id": stable_id(id_prefix("fund_term_clause"), row["observation_id"]),
            "fund_id": fund_id,
            "source_document_id": row["document_id"],
            "metric_id": matrices.resolve_or_star(
                CLAUSE_ADMISSION, row.get("term_category", ""),
                context="canonical_metric",
            ),
            "clause_title": first_field(row, FIELD_ORDER, "fund_term_clauses.clause_title"),
            "value_raw": first_field(row, FIELD_ORDER, "fund_term_clauses.value_raw"),
            "value_text": first_field(row, FIELD_ORDER, "fund_term_clauses.value_text"),
            "currency": row.get("currency", ""),
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "extractor_version": row.get("contract_version", ""),
            **fixed("fund_term_clauses"),
        })
    return rows


def build_fund_holdings(
    holdings: list[dict[str, str]], observations: list[dict[str, str]]
) -> list[dict[str, str]]:
    """A holding belongs to the fund that reported it. `fact_holding` names the
    held company, so the reporting fund is read from the observations the
    holding was built from, and a holding whose document names no fund is left
    in the extraction layer."""
    fund_of_observation = {
        row["observation_id"]: row["subject_entity_id"]
        for row in observations
        if row.get("subject_entity_id", "").startswith(FUND_PREFIX)
    }
    fund_of_document: dict[str, set[str]] = defaultdict(set)
    for row in observations:
        if row.get("subject_entity_id", "").startswith(FUND_PREFIX):
            fund_of_document[row["document_id"]].add(row["subject_entity_id"])

    rows = []
    separator = matrices.resolve(LINEAGE_DELIMITERS, "observation_ids_separator")
    attribution_order = _ordered_outputs(
        HOLDING_ATTRIBUTION, "fund_holdings", "source_"
    )
    ambiguous_result = matrices.resolve(
        HOLDING_ATTRIBUTION, "ambiguous_result", context="fund_holdings"
    )
    for holding in holdings:
        linked_funds = {
            fund_of_observation[obs_id]
            for obs_id in (holding.get("observation_ids", "") or "").split(separator)
            if obs_id in fund_of_observation
        }
        document_funds = fund_of_document.get(holding["document_id"], set())
        attribution_values = {
            "linked_observation_funds": linked_funds,
            "document_single_fund": document_funds if len(document_funds) == 1 else set(),
        }
        funds = next(
            (
                attribution_values[source]
                for source in attribution_order
                if attribution_values[source]
            ),
            set(),
        )
        if len(funds) != 1:
            if ambiguous_result == "refused":
                continue
            raise matrices.MatrixError(
                f"{HOLDING_ATTRIBUTION}: unsupported ambiguous_result {ambiguous_result!r}"
            )
        dated = bool(holding.get("as_of_date"))
        holding_dates = matrices.mapping(HOLDING_DATES, context="holding")
        field_map = matrices.mapping(HOLDING_FIELDS)
        fair_sources = matrices.resolve(HOLDING_VALUE, "fair_value").split("|")
        rows.append({
            "holding_id": holding["holding_id"],
            "fund_id": next(iter(funds)),
            "portfolio_company_id": holding.get(field_map["portfolio_company_id"], ""),
            "portfolio_company_name": holding.get(field_map["portfolio_company_name"], ""),
            "date_role": holding_dates["dated_role"] if dated else holding_dates["undated_role"],
            "date_raw": holding.get("as_of_date_raw", ""),
            "date_precision": holding_dates["dated_precision"] if dated else holding_dates["undated_precision"],
            "as_of_date": holding.get("as_of_date", ""),
            "currency": currency_or_default(holding.get("currency", ""), "fund_holdings"),
            "cost": holding.get(field_map["cost"], ""),
            "fair_value": next((holding.get(field, "") for field in fair_sources if holding.get(field, "")), ""),
            "interest_rate": holding.get(field_map["interest_rate"], ""),
            "maturity_date": holding.get(field_map["maturity_date"], ""),
            "ownership_percent": holding.get(field_map["ownership_percent"], ""),
            # The printed company industry, read off fact_holding by the name
            # holding-field-map.csv gives it. The column is read by name so it
            # fills the day the flatten writes it and stays blank until then.
            "sector": holding.get(field_map["sector"], ""),
            "canonical_sector": canonical_grouping(
                {"sector": holding.get(field_map["sector"], "")}
            )["canonical_sector"],
            "source_document_id": holding["document_id"],
            "source_page": holding.get("source_page", ""),
            "source_anchor": source_anchor(holding, context="holding"),
            **fixed("fund_holdings"),
        })
    return rows


def build_manager_observations(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in observations:
        manager_id = row.get("subject_entity_id", "")
        if not manager_id.startswith(MANAGER_PREFIX):
            continue
        category = first_field(row, MANAGER_FIELD_ORDER, "manager_observations.category")
        dates = date_fields(row)
        rows.append({
            "manager_observation_id": stable_id(id_prefix("manager_observation"), row["observation_id"]),
            "manager_id": manager_id,
            "file_id": row["document_id"],
            "metric_id": metric_id_from_policy(
                row,
                category,
                MANAGER_FIELD_ORDER,
                "manager_observations.metric_id",
                row["record_family"],
            ),
            **dates,
            "value_raw": row.get("value_raw", ""),
            "value_numeric": row.get("value_numeric", ""),
            "value_text": row.get("value_text", ""),
            "currency": row.get("currency", ""),
            "unit": first_field(row, MANAGER_FIELD_ORDER, "manager_observations.unit"),
            "measure_basis": measure_basis(category, row.get("value_kind", ""), bool(dates["as_of_date"])),
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "extractor_version": row.get("contract_version", ""),
            **fixed("manager_observations"),
        })
    return rows


def extend_manager_master(observations: list[dict[str, str]]) -> int:
    """Add the managers the extracted rows name and the master has yet to carry.

    Existing rows stay. Missing managers from the identity registry are appended
    so rule R16 can resolve every manager observation to a master row.
    """
    path = CSV_DIR / "manager_master.csv"
    existing = read_csv(path)
    known = {row["manager_id"] for row in existing}
    registry = {
        row["entity_id"]: row["standardized_name"]
        for row in read_csv(NORMALIZATION_DIR / "entity-ids.csv")
        if row["entity_id"].startswith(MANAGER_PREFIX)
    }
    source_policy = matrices.mapping(MANAGER_MASTER_SOURCES, context="manager_master")
    source_fields = tuple(
        source_policy[key]
        for key in sorted(
            (key for key in source_policy if key.startswith("id_source_")),
            key=lambda key: int(key.rsplit("_", 1)[-1]),
        )
    )
    reference_policy = source_policy["reference_kept"]
    referenced: dict[str, dict[str, str]] = {}
    for row in observations:
        # A row names its manager either as its subject or through the
        # manager identity carried beside a fund or plan subject. Both routes
        # must land in the master, or the document map cites a manager the
        # master does not carry.
        for manager_id in (row.get(field, "") for field in source_fields):
            if manager_id.startswith(MANAGER_PREFIX) and manager_id not in known:
                if reference_policy == "first_observation":
                    referenced.setdefault(manager_id, row)
                else:
                    raise matrices.MatrixError(
                        f"{MANAGER_MASTER_SOURCES}: unsupported reference policy {reference_policy!r}"
                    )

    added = []
    for manager_id, row in sorted(referenced.items()):
        subject_is_manager = row.get("subject_entity_id", "") == manager_id
        printed_name = row.get("subject_name", "") if subject_is_manager else row.get("subject_manager_name", "")
        name_values = {
            "<registry_name>": registry.get(manager_id, ""),
            "<subject_standardized_name_if_subject_is_manager>": (
                row.get("subject_standardized_name", "") if subject_is_manager else ""
            ),
            "<printed_manager_name>": printed_name,
        }
        added.append({
            "manager_id": manager_id,
            "manager_name": _first_policy_value(
                MANAGER_MASTER_FIELDS, "manager_master.manager_name", name_values
            ),
            "legal_name": _first_policy_value(
                MANAGER_MASTER_FIELDS, "manager_master.legal_name", name_values
            ),
            "base_currency": currency_or_default(row.get("currency", ""), "manager_master"),
            "source_document_id": row["document_id"],
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "created_at": "",
            **fixed("manager_master"),
        })
    # Written on every run, added rows or none: the stage declares this file
    # as an output, and the release refuses a declared output the stage left
    # untouched (2026-09-02, guard_outputs). A run that adds no manager
    # rewrites the same bytes, so the receipt hash is unchanged.
    write_csv(path, existing + added)
    return len(added)


def retain_supported_master_attributes(
    rows: list[dict[str, str]], lookup: dict[str, dict[str, str]]
) -> list[dict[str, str]]:
    """Keep only fund constants backed by the settled printed-value matrix."""

    cleaned: list[dict[str, str]] = []
    for source in rows:
        row = dict(source)
        attributes = lookup.get(row.get("fund_id", ""), {})
        for field in STAMP_FIELDS:
            supported = (attributes.get(field) or "").strip()
            current = (row.get(field) or "").strip()
            if current and current != supported:
                row[field] = ""
        cleaned.append(row)
    return cleaned


def complete_fund_master(
    existing: list[dict[str, str]],
    observations: list[dict[str, str]],
    attribute_lookup: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], int, int]:
    """Keep the source-only fund identity spine aligned with promoted facts.

    Round 01 supplies some master rows, while Round 02 can identify many more
    funds inside schedules. Every promoted fund therefore receives a minimal,
    source-backed master row before the extracted snapshot is frozen. IDs no
    longer present in the settled registry are retired instead of surviving as
    stale fund masters.
    """
    registry = {
        row["entity_id"]: row["standardized_name"]
        for row in read_csv(NORMALIZATION_DIR / "entity-ids.csv")
        if row["entity_id"].startswith(FUND_PREFIX)
    }
    registry_policy = matrices.resolve(MASTER_RETIREMENT, "registry_membership")
    if registry_policy != "required":
        raise matrices.MatrixError(
            f"{MASTER_RETIREMENT}: unsupported registry_membership {registry_policy!r}"
        )
    kept = [row for row in existing if row.get("fund_id", "") in registry]
    retired = len(existing) - len(kept)
    known = {row.get("fund_id", "") for row in kept}
    first_source: dict[str, dict[str, str]] = {}
    new_row_source = matrices.resolve(MASTER_SOURCES, "new_row_source")
    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        if fund_id.startswith(FUND_PREFIX):
            if new_row_source == "first_observation_per_fund":
                first_source.setdefault(fund_id, row)
            else:
                raise matrices.MatrixError(
                    f"{MASTER_SOURCES}: unsupported new_row_source {new_row_source!r}"
                )

    added: list[dict[str, str]] = []
    for fund_id in sorted(first_source):
        if fund_id in known:
            continue
        source = first_source[fund_id]
        fund_name_source = matrices.resolve(MASTER_SOURCES, "fund_name_source")
        if fund_name_source != "registry_standardized_name":
            raise matrices.MatrixError(
                f"{MASTER_SOURCES}: unsupported fund_name_source {fund_name_source!r}"
            )
        name = registry.get(fund_id, "")
        if not name:
            missing_name_policy = matrices.resolve(MASTER_RETIREMENT, "missing_registry_name")
            if missing_name_policy == "refused":
                raise ValueError(f"fund identity registry lacks {fund_id}")
            raise matrices.MatrixError(
                f"{MASTER_RETIREMENT}: unsupported missing_registry_name {missing_name_policy!r}"
            )
        master_fields = matrices.mapping(MASTER_FIELDS)
        added.append(
            {
                "fund_id": fund_id,
                "fund_name": name,
                "fund_manager_id": source.get(master_fields["fund_manager_id"], ""),
                "fund_manager_name": source.get(master_fields["fund_manager_name"], ""),
                "strategy": source.get(master_fields["strategy"], ""),
                "vintage_year": source.get(master_fields["vintage_year"], ""),
                "sector": source.get("sector", ""),
                "source_document_id": source.get("document_id", ""),
                "source_page": source.get("source_page", ""),
                "source_anchor": source_anchor(source),
                "created_at": "",
                **fixed("fund_master"),
            }
        )
    supported = retain_supported_master_attributes(kept + added, attribute_lookup)
    supported = source_master_fields(supported, observations)
    return (
        sorted(read_master_groupings(supported), key=lambda row: row.get("fund_id", "")),
        len(added),
        retired,
    )


def source_master_fields(rows: list[dict[str, str]], observations: list[dict[str, str]]) -> list[dict[str, str]]:
    """Rebuild numeric master fields from source evidence, excluding prior completion."""
    size_sources: dict[str, dict[tuple[str, str], dict[str, str]]] = defaultdict(dict)
    for observation in observations:
        if observation.get("metric_category") == "fund_size" and observation.get("subject_entity_id", "").startswith(FUND_PREFIX):
            value = scaled_amount(observation)
            if value:
                size_sources[observation["subject_entity_id"]].setdefault((value, observation.get("currency", "")), observation)
    policy = matrices.mapping(SOURCE_MASTER_FIELDS)
    for row in rows:
        candidates = size_sources.get(row["fund_id"], {})
        source = next(iter(candidates.values())) if len(candidates) == 1 else None
        for field, rule in policy.items():
            if rule == "unique_fund_size_observation":
                row[field] = scaled_amount(source) if source else ""
            elif rule == "currency_of_fund_size_observation":
                row[field] = source.get("currency", "") if source else ""
            elif rule == "blank_without_explicit_source_field":
                row[field] = ""
            else:
                raise ValueError(f"Unsupported source master field rule: {rule}")
        if source:
            anchor = f"fund_size observation={source['observation_id']} {source_anchor(source)}"
            previous = row.get("source_anchor", "").split("; fund_size observation=")[0]
            row["source_anchor"] = previous + "; " + anchor
    return rows


def read_master_groupings(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Fill each fund's taxonomy reading from the printed words it carries.

    Every fund the stage keeps and every fund it adds is read through
    context-grouping-map.csv here, which is what promotion-schema-additions.csv
    says this stage does. A printed word the matrix does not carry leaves the
    reading blank; the printed columns are never touched."""

    filled: list[dict[str, str]] = []
    for source in rows:
        row = dict(source)
        reading = canonical_grouping(row)
        for name, value in reading.items():
            if value or not (row.get(name) or "").strip():
                row[name] = value
        filled.append(row)
    return filled


def build_document_manager_map(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    """Which manager each document names, from the manager identity already
    carried on the extracted rows. One row per document and manager.

    The printed name is the manager's own: the subject name when the subject
    is the manager, otherwise the manager name carried beside the subject.
    A document title never stands in for a manager name."""
    registry = {
        row["entity_id"]: row["standardized_name"]
        for row in read_csv(NORMALIZATION_DIR / "entity-ids.csv")
        if row["entity_id"].startswith(MANAGER_PREFIX)
    }
    identity_policy = matrices.mapping(MAP_IDENTITY, context="document_manager_map")
    identity_sources = tuple(
        identity_policy[key]
        for key in sorted(
            (key for key in identity_policy if key.startswith("id_source_")),
            key=lambda key: int(key.rsplit("_", 1)[-1]),
        )
    )
    source_policy = matrices.mapping(MAP_SOURCES, context="document_manager_map")
    seen: dict[tuple[str, str], dict[str, str]] = {}
    for row in observations:
        identity_values = {
            "manager_entity_id": row.get("manager_entity_id", ""),
            "subject_entity_id_when_manager": (
                row.get("subject_entity_id", "")
                if row.get("subject_entity_id", "").startswith(MANAGER_PREFIX)
                else ""
            ),
        }
        manager_id = next(
            (identity_values[source] for source in identity_sources if identity_values[source]),
            "",
        )
        subject_is_manager = row.get("subject_entity_id", "") == manager_id
        name_values = {
            "subject_manager_name": row.get("subject_manager_name", ""),
            "<subject_name_if_subject_is_manager>": (
                row.get("subject_name", "") if subject_is_manager else ""
            ),
            "<registry_name>": registry.get(manager_id, ""),
            "<subject_standardized_name_if_subject_is_manager>": (
                row.get("subject_standardized_name", "") if subject_is_manager else ""
            ),
        }
        name = _first_policy_value(
            NAME_ORDER, "document_manager_map.manager_name_raw", name_values
        )
        if not manager_id:
            continue
        if _policy_true(MAP_SOURCES, "requires_name_or_registry", "document_manager_map") and not (
            name or registry.get(manager_id)
        ):
            continue
        key = (row["document_id"], manager_id)
        if key in seen:
            row_policy = source_policy["row_kept"]
            if row_policy == "first_per_document_and_manager":
                continue
            raise matrices.MatrixError(f"{MAP_SOURCES}: unsupported row policy {row_policy!r}")
        seen[key] = {
            "document_manager_map_id": stable_id(id_prefix("document_manager_map"), *key),
            "file_id": row["document_id"],
            "manager_id": manager_id,
            "manager_name_raw": name,
            "manager_name_normalized": _first_policy_value(
                NAME_ORDER,
                "document_manager_map.manager_name_normalized",
                {**name_values, "<manager_name_raw>": name},
            ),
            "relationship_role": matrices.resolve(MAP_LABELS, "relationship_role", context="document_manager_map"),
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "source_quote": row.get("evidence_quote", ""),
            "provenance_type": matrices.resolve(MAP_LABELS, "provenance_type", context="document_manager_map"),
            "adjudication_status": row.get("adjudication_status", "")
            or matrices.resolve(MAP_LABELS, "adjudication_status_default", context="document_manager_map"),
        }
    return [seen[key] for key in sorted(seen)]


# --------------------------------------------------------------------------


MISMATCH_REPORT = PROJECT_ROOT / "data" / "extracted" / "audit" / "promotion-category-mismatches.csv"
MISMATCH_COLUMNS = [
    "observation_id", "document_id", "source_page", "source_row_label",
    "source_column_label", "fund_id", "metric_category", "period_column",
    "value_kind", "value_raw", "finding",
]


def write_mismatch_report(mismatches: list[dict[str, str]]) -> int:
    """Report every cell whose category and printed kind disagree.

    These are extraction findings, and repairing them means changing the
    adjudicator instructions and rerunning the affected document, never editing
    an adjudicated file. The report is the handoff for that work."""
    MISMATCH_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with MISMATCH_REPORT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MISMATCH_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(mismatches, key=lambda row: (row["document_id"], row["observation_id"])))
    return len(mismatches)


def promote(output_dir: Path | None = None) -> dict[str, int]:
    """Write the fund tables from the decided extraction.

    `output_dir` sends every table this stage writes somewhere other than
    data/csv while the contract is still read from the published header, so a
    trial run can be compared column by column without rewriting the release."""

    assert_map_restates_period_columns()
    assert_no_target_table_is_live()
    target_dir = output_dir or CSV_DIR
    trial = target_dir != CSV_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    def write_table(name: str, rows: list[dict[str, str]]) -> int:
        return write_csv(target_dir / name, rows, header_path=CSV_DIR / name)

    observations = read_csv(TABLES_DIR / "fact_observation.csv")
    holdings = read_csv(TABLES_DIR / "fact_holding.csv")

    # A trial run reads the published acceptance evidence and writes none: the
    # gate ledger is the release's record, not this run's.
    gate = {"batches": 0, "documents": 0} if trial else write_gate_evidence(observations)
    periods, collisions, mismatches = build_fund_periods(observations)
    period_canonical_changes = _LAST_PERIOD_CANONICAL_CHANGES
    attribute_lookup = decided_lookup()
    attribute_evidence = attribute_evidence_lookup(observations=observations)
    period_attributes, period_changes = stamp_rows_with_changes(
        periods,
        attribute_lookup,
        attribute_evidence,
        target_table="fund_periods",
        record_id_field="fund_period_id",
    )
    master_inputs = [
        PROJECT_ROOT / matrices.resolve(MASTER_INPUTS, f"input_source_{rank}") for rank in (1, 2)
    ]
    master_input = next((path for path in master_inputs if path.is_file()), master_inputs[-1])
    master_rows, master_added, master_retired = complete_fund_master(
        read_csv(master_input),
        observations,
        attribute_lookup,
    )
    master_attributes, master_changes = stamp_rows_with_changes(
        master_rows,
        attribute_lookup,
        attribute_evidence,
        target_table="fund_master",
        record_id_field="fund_id",
        include_existing=True,
    )
    canonical_changes = period_canonical_changes + master_canonical_changes(
        master_rows, attribute_evidence
    )
    if not trial:
        write_mismatch_report(mismatches)
    fund_observations = build_fund_observations(observations)
    counts = {
        "manager_master_added": 0 if trial else extend_manager_master(observations),
        "fund_master_added": master_added,
        "fund_master_retired": master_retired,
        "gate_batches": gate["batches"],
        "gate_documents": gate["documents"],
        "fund_observations": write_table("fund_observations.csv", fund_observations),
        "unmapped_fund_observations": _LAST_UNMAPPED,
        "evidence_only_fund_observations": _LAST_EVIDENCE_ONLY,
        "fund_periods": write_table("fund_periods.csv", periods),
        "period_collisions": collisions,
        "category_mismatches": len(mismatches),
        "fund_cashflows": write_table("fund_cashflows.csv", build_fund_cashflows(observations)),
        "fund_terms": write_table("fund_terms.csv", build_fund_terms(observations)),
        "fund_term_clauses": write_table(
            "fund_term_clauses.csv", build_fund_term_clauses(observations)
        ),
        "fund_holdings": write_table(
            "fund_holdings.csv", build_fund_holdings(holdings, observations)
        ),
        "manager_observations": write_table(
            "manager_observations.csv", build_manager_observations(observations)
        ),
        "document_manager_map": write_table(
            "document_manager_map.csv", build_document_manager_map(observations)
        ),
        "period_attribute_cells": period_attributes,
        "fund_master": write_table("fund_master.csv", master_rows),
        "master_attribute_cells": master_attributes,
        "canonical_attribute_cells": len(canonical_changes),
        "attribute_change_rows": (
            0
            if trial
            else write_attribute_changes(period_changes + master_changes + canonical_changes)
        ),
    }
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="write the fund tables here instead of data/csv, keeping the published header",
    )
    args = parser.parse_args()
    counts = promote(args.output_dir)
    width = max(len(name) for name in counts)
    for name, value in counts.items():
        print(f"  {name:<{width}}  {value:>6,}")
    print("PASS: extracted facts promoted into the fund-level tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
