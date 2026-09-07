"""Keep extracted fund tables, then fill the same fund IDs.

The extracted snapshot is not edited in place. The integrated layer keeps every extracted
row, creates one complete demonstration period for every extracted fund ID, and
records each added cell in a gap ledger and a cell-lineage ledger.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import statistics
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml

from src.catalog.simple_pdf_extraction.fund_attributes import SETTLED as SETTLED_ATTRIBUTE_STATUSES
from src.common.finance import xirr
from src.quality.run_fund_checks import (
    _position_key as quality_position_key,
    load_tolerances,
    run_quality_checks,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV_DIR = PROJECT_ROOT / "data" / "csv"
EXTRACTED_DIR = PROJECT_ROOT / "data" / "extracted" / "fund-level"
INTEGRATED_DIR = PROJECT_ROOT / "data" / "integrated"
NORMALIZATION_DIR = PROJECT_ROOT / "data" / "normalization"
PUBLIC_MARKET_DIR = PROJECT_ROOT / "data" / "public_markets" / "staging"
ATTRIBUTE_CHANGES_PATH = PROJECT_ROOT / "data" / "extracted" / "audit" / "attribute-changes.csv"
CONFIG_PATH = PROJECT_ROOT / "config" / "integrated_completion.yml"
QUALITY_CONFIG = PROJECT_ROOT / "config" / "quality_rules.yml"

EXTRACTED_FILES = (
    "manager_master.csv",
    "document_manager_map.csv",
    "fund_master.csv",
    "document_fund_map.csv",
    "fund_observations.csv",
    "manager_observations.csv",
    "fund_cashflows.csv",
    "fund_periods.csv",
    "fund_terms.csv",
    "fund_term_clauses.csv",
    "fund_holdings.csv",
)

INTEGRATED_FUND_MODEL_FILES = (
    "fund_master.csv",
    "fund_periods.csv",
    "fund_cashflows.csv",
    "fund_terms.csv",
    "fund_term_clauses.csv",
    "fund_holdings.csv",
    "benchmark_returns.csv",
    "synthetic_parameters.csv",
    "defect_injections.csv",
)

LINEAGE_COLUMNS = (
    "lineage_id",
    "target_table",
    "target_record_id",
    "target_field",
    "target_value",
    "provenance_type",
    "source_table",
    "source_record_id",
    "source_document_id",
    "source_anchor",
    "formula_id",
    "synthetic_parameter_set_id",
    "imputation_method",
    "precedence",
    "notes",
)

GAP_COLUMNS = (
    "gap_id",
    "fund_id",
    "target_table",
    "target_record_id",
    "field_name",
    "original_value",
    "resolution_value",
    "resolution_type",
    "lineage_id",
    "status",
)

RECONCILIATION_COLUMNS = (
    "check_id",
    "scope",
    "record_id",
    "fund_id",
    "rule",
    "status",
    "actual_value",
    "expected_value",
    "difference",
    "notes",
)

BENCHMARK_POLICY_COLUMNS = (
    "benchmark_id",
    "benchmark_name",
    "rights_status",
    "use_status",
    "source_file_id",
    "first_observation_date",
    "last_observation_date",
    "observation_count",
    "note",
)

SCORECARD_COLUMNS = (
    "defect_type",
    "expected_rule_id",
    "injected",
    "detected",
    "missed",
    "detection_rate",
)

from src.common import matrices

# Every decision below reads from a matrix under
# data/normalization/transformations; formula-shaped parameters stay in code
# with refusal checks that stop the build when the matrix and the code
TARGET_FIELD_RULES = "completion-target-fields"
CELL_RULES = "integrated-input-cell-normalization"
OUTPUT_RULES = "integrated-output-defaults"
ID_RULES = "integrated-identifier-rules"
NUMBER_RULES = "integrated-number-parsing"
FORMAT_RULES = "integrated-numeric-formatting"
DATE_RULES = "integrated-date-parsing"
UNIVERSE_SOURCES = "integrated-fund-universe-sources"
RECORD_ID_FIELDS = "table-record-id-fields"
EVIDENCE_PRIORITY = "fund-evidence-priority"
EVIDENCE_FALLBACKS = "evidence-field-fallbacks"
PERIOD_ORDER = "period-selection-order"
STRATEGY_KEYWORDS = "name-keyword-strategy"
UNIT_INTERVAL = "deterministic-unit-interval"
GAP_DEFAULTS = "gap-ledger-defaults"
PARAMETER_POPULATIONS = "integrated-parameter-populations"
PARAMETER_FORMULAS = "integrated-parameter-formulas"
PARAMETER_KEYS = "parameter-input-key-map"
PARAMETER_PROVENANCE = "parameter-provenance-policy"
PARAMETER_STATUSES = "parameter-status-defaults"
PARAMETER_UNITS = "parameter-unit-map"
ASSUMPTION_UNITS = "assumption-unit-map"
ASSUMPTION_CHANNELS = "assumption-value-channel"
BENCHMARK_SELECTION = "benchmark-master-selection"
BENCHMARK_WINDOW = "benchmark-return-window"
BENCHMARK_ELIGIBILITY = "benchmark-return-eligibility"
BENCHMARK_PERIODICITY = "benchmark-periodicity"
BENCHMARK_FALLBACKS = "benchmark-field-fallbacks"
BENCHMARK_LABELS = "benchmark-promotion-labels"
BENCHMARK_FORMULA = "benchmark-return-formula"
BENCHMARK_SUMMARY = "benchmark-policy-summary"
BENCHMARK_MAP = "strategy-benchmark-map"
BENCHMARK_IDENTIFIERS = "public-market-identifiers"
MASTER_DUPES = "fund-master-duplicate-policy"
MASTER_NAME_ORDER = "fund-master-field-precedence"
NEW_MASTER_FIELDS = "new-fund-master-fields"
NEW_MASTER_DEFAULTS = "new-fund-master-defaults"
MANAGER_SELECTION = "fund-manager-selection"
STRATEGY_ORDER = "fund-strategy-precedence"
VINTAGE_ORDER = "fund-vintage-precedence"
SIZE_ORDER = "fund-size-precedence"
MASTER_DEFAULTS = "fund-master-field-defaults"
FILL_POLICY = "fund-master-fill-policy"
MASTER_PROVENANCE = "fund-master-provenance"
PROVENANCE_TABLES = "provenance-assignment"
RECONCILIATION_POLICY = "integrated-reconciliation-policy"
LINEAGE_ROUTING = "fund-master-lineage-routing"
COMPLETION_PARAMETERS = "period-completion-parameters"
CASHFLOW_SCHEDULE = "integrated-cashflow-schedule"
TERMS_PARAMETERS = "terms-generation-parameters"
DEFECTS = "defect-definitions"


def _ranked_outputs(name: str, context: str = "") -> tuple[str, ...]:
    return tuple(
        row["output_value"]
        for row in sorted(matrices.rows_in(name, context), key=lambda item: int(item["input_value"]))
    )


def _require(name: str, key: str, expected: str, context: str = "") -> None:
    if matrices.resolve(name, key, context=context) != expected:
        raise IntegrationError(f"{name}.csv names an unexpected {key}")


def _parameter(context: str, key: str) -> float:
    return float(matrices.resolve(COMPLETION_PARAMETERS, key, context=context))


class IntegrationError(RuntimeError):
    """Raised when extracted facts would be lost or integrated math fails."""


TARGET_PERIOD_FIELDS = _ranked_outputs(TARGET_FIELD_RULES)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise IntegrationError(f"CSV has no header: {path}")
        if matrices.resolve(CELL_RULES, "cell_whitespace") != "stripped":
            raise IntegrationError("integrated-input-cell-normalization.csv names an unknown rule")
        return list(reader.fieldnames), [
            {key: (value or "").strip() for key, value in row.items()} for row in reader
        ]


def write_csv(
    path: Path,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        for row in materialized:
            writer.writerow(
                {column: row.get(column, matrices.resolve(OUTPUT_RULES, "missing_column")) for column in columns}
            )
    return len(materialized)


def stable_id(prefix: str, *parts: object) -> str:
    payload = matrices.resolve(ID_RULES, "part_join").join(str(part) for part in parts)
    _require(ID_RULES, "digest", "sha256_first20_upper")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20].upper()
    return matrices.resolve(ID_RULES, "id_format").format(prefix=prefix, digest=digest)


def number(value: object) -> float | None:
    _require(NUMBER_RULES, "thousands_separator", "removed")
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    return result if result == result and abs(result) != float("inf") else None


def fmt(value: float | Decimal, places: int | None = None) -> str:
    if places is None:
        places = int(matrices.resolve(FORMAT_RULES, "default_places"))
    _require(FORMAT_RULES, "rounding", "half_even")
    quantum = Decimal(1).scaleb(-places)
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    rendered = decimal_value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    return format(rendered, "f")


def parse_date(value: object) -> date | None:
    _require(DATE_RULES, "accepted_shape", "iso_date")
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


def config(path: Path = CONFIG_PATH) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise IntegrationError(f"invalid configuration: {path}")
    return payload


def extracted_outputs() -> tuple[Path, ...]:
    return tuple(EXTRACTED_DIR / filename for filename in EXTRACTED_FILES)


def integrated_outputs() -> tuple[Path, ...]:
    return (
        *(CSV_DIR / filename for filename in INTEGRATED_FUND_MODEL_FILES),
        INTEGRATED_DIR / "gap-ledger.csv",
        INTEGRATED_DIR / "cell-lineage.csv",
        INTEGRATED_DIR / "reconciliation-results.csv",
        INTEGRATED_DIR / "benchmark-policy.csv",
        INTEGRATED_DIR / "defect-periods.csv",
        INTEGRATED_DIR / "defect-quality-results.csv",
        INTEGRATED_DIR / "detection-scorecard.csv",
    )


def snapshot_extracted() -> dict[str, int]:
    """Copy the promoted source-backed tables before augmentation begins."""
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for filename in EXTRACTED_FILES:
        source = CSV_DIR / filename
        if not source.is_file():
            raise IntegrationError(f"missing fund-model extraction table: {source}")
        target = EXTRACTED_DIR / filename
        shutil.copyfile(source, target)
        _, rows = read_csv(target)
        counts[filename] = len(rows)
    return counts


def _fund_ids(tables: Mapping[str, Sequence[Mapping[str, str]]]) -> list[str]:
    names = _ranked_outputs(UNIVERSE_SOURCES)
    return sorted(
        {
            row.get("fund_id", "")
            for table in names
            for row in tables.get(table, ())
            if row.get("fund_id", "")
        }
    )


def _record_id(table: str, row: Mapping[str, str]) -> str:
    return row.get(matrices.resolve(RECORD_ID_FIELDS, table), "")


def _evidence_by_fund(
    tables: Mapping[str, Sequence[Mapping[str, str]]]
) -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    order = _ranked_outputs(EVIDENCE_PRIORITY)
    for table in order:
        for row in tables.get(table, ()):
            fund_id = row.get("fund_id", "")
            if not fund_id or fund_id in evidence:
                continue
            evidence[fund_id] = {
                "source_table": table,
                "source_record_id": _record_id(table, row),
                "source_document_id": next(
                    (row.get(field, "") for field in _ranked_outputs(EVIDENCE_FALLBACKS, "document") if row.get(field, "")),
                    "",
                ),
                "source_page": row.get("source_page", ""),
                "source_anchor": next(
                    (row.get(field, "") for field in _ranked_outputs(EVIDENCE_FALLBACKS, "anchor") if row.get(field, "")),
                    "",
                ),
            }
    return evidence


def _attribute_sources(
    rows: Sequence[Mapping[str, str]], target_table: str = "fund_master"
) -> dict[str, dict[str, dict[str, str]]]:
    """Return the printed observation behind each attribute cell one table carries.

    Keyed by the record the change names, which on fund_master is the fund ID
    and on fund_periods is the period ID."""

    sources: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        record_id = row.get("target_record_id", "")
        field = row.get("field", "")
        if row.get("target_table") != target_table or not record_id or not field:
            continue
        anchor_parts = [
            f"page {row['source_page']}" if row.get("source_page") else "",
            f"table {row['source_table']}" if row.get("source_table") else "",
            (
                f"observation {row['source_observation_id']}"
                if row.get("source_observation_id")
                else ""
            ),
        ]
        sources[record_id][field] = {
            "value": row.get("new_value", ""),
            "source_table": matrices.resolve(
                PROVENANCE_TABLES, "canonical_attribute_value"
            ),
            "source_record_id": row.get("change_id", ""),
            "source_document_id": row.get("source_document_id", ""),
            "source_anchor": "; ".join(part for part in anchor_parts if part),
        }
    return {record_id: dict(fields) for record_id, fields in sources.items()}


def _period_lineage_source(
    row: Mapping[str, str] | None,
) -> dict[str, str] | None:
    if row is None:
        return None
    return {
        "source_table": matrices.resolve(PROVENANCE_TABLES, "period_value"),
        "source_record_id": row.get("fund_period_id", ""),
        "source_document_id": row.get("source_document_id", ""),
        "source_anchor": row.get("source_anchor", ""),
    }


def _latest_periods(
    periods: Sequence[Mapping[str, str]],
) -> dict[str, list[Mapping[str, str]]]:
    by_fund: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in periods:
        if row.get("fund_id", ""):
            by_fund[row["fund_id"]].append(row)
    for rows in by_fund.values():
        rows.sort(key=lambda row, _keys=_ranked_outputs(PERIOD_ORDER): tuple(row.get(k, "") for k in _keys))
    return by_fund


def _first_value(rows: Sequence[Mapping[str, str]], field: str) -> tuple[str, Mapping[str, str] | None]:
    _require("evidence-preference-order", "latest_first", "reversed_period_order", context="integrated")
    for row in reversed(rows):
        value = row.get(field, "")
        if value:
            return value, row
    return "", None


NAME_HINT_POLICY = "name-hint-policy"
GROUPING_MAP = "context-grouping-map"


def _canonical_of(printed: str, context: str) -> tuple[str, str, str]:
    """The canonical class, strategy, and sub-strategy the grouping matrix
    reads off one printed grouping value; blank where the value was never
    printed. The three are distinct dimensions: `Buyout` names the strategy
    buyout inside the class private_equity, and conflating them is the defect
    the matrix exists to end."""

    for row in matrices.rows_in(GROUPING_MAP, context):
        if row["input_value"] == printed:
            return row["output_value"], row["canonical_strategy"], row["canonical_sub_strategy"]
    return "", "", ""


GROUPING_CONTEXTS = ("strategy", "classifier_output")
CANONICAL_PERIOD_COLUMNS = (
    "canonical_asset_class",
    "canonical_strategy",
    "canonical_sub_strategy",
    "canonical_sector",
)


def _period_grouping(master: Mapping[str, str]) -> dict[str, str]:
    """The taxonomy reading a completed period carries beside its printed words.

    The completed period states the fund's own printed strategy and sector, so
    it states what they read as too: a grouping published with no reading beside
    it is a word the analytics group on and no one can resolve. The printed
    strategy is read under the strategy context and then under the classifier
    context, and the printed industry under the sector context. A printed word
    the matrix carries no row for leaves the reading blank; the caller records
    that as an open gap rather than inventing a class.
    """

    printed_strategy = (master.get("strategy", "") or "").strip()
    printed_sector = (master.get("sector", "") or "").strip()
    reading = {name: "" for name in CANONICAL_PERIOD_COLUMNS}
    for context in GROUPING_CONTEXTS:
        if not printed_strategy:
            break
        found = _canonical_of(printed_strategy, context)
        if any(found):
            (
                reading["canonical_asset_class"],
                reading["canonical_strategy"],
                reading["canonical_sub_strategy"],
            ) = found
            break
    if printed_sector:
        # A sector row states the industry in its own `sector` column; its
        # output_value is the asset class, which an industry does not name.
        for row in matrices.rows_in(GROUPING_MAP, "sector"):
            if row["input_value"] == printed_sector:
                reading["canonical_sector"] = row["sector"]
                break
    return reading


def _name_hint(name: str) -> tuple[str, str]:
    """The keyword a fund's own name fires, and the class that keyword names.

    A hint, never a value: a fund called Adventure Fund I is not a venture fund,
    and matching `venture` inside `adVENTURE` is what made it look like one. The
    match mode is a row in name-hint-policy.csv, and the caller records the hint
    on `name_hint` instead of publishing it.
    """

    if matrices.resolve(NAME_HINT_POLICY, "match_mode") != "word_boundary":
        raise IntegrationError(f"{NAME_HINT_POLICY}: unsupported match_mode")
    lowered = name.lower()
    for row in matrices.load(STRATEGY_KEYWORDS):
        if row["input_value"] == "*":
            continue
        for keyword in row["input_value"].split("|"):
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                return keyword, row["output_value"]
    return "", ""


def _accepted_name_hint(name: str, stated_class: str) -> tuple[str, str]:
    """Return a name hint unless printed fund evidence contradicts its class."""

    keyword, label = _name_hint(name)
    hinted_class, _, _ = _canonical_of(label, "strategy")
    if keyword and stated_class and hinted_class and hinted_class != stated_class:
        if matrices.resolve(NAME_HINT_POLICY, "contradiction") != "drop_when_print_disagrees":
            raise IntegrationError(f"{NAME_HINT_POLICY}: unsupported contradiction policy")
        return "", ""
    return keyword, label


def _strategy_from_name(name: str, fallback: str) -> str:
    """The strategy a fund with no printed strategy is published with.

    The keyword branch is gone: name-hint-policy.csv sets promotion to
    never_promoted, so a name fires a hint and the published value falls to the
    configured fallback, which at least says it is a default. The function
    returns that fallback and nothing else; it used to return the catch-all
    row's sub-strategy beside it, which the caller assigned and never read, so
    one unused assignment was all that kept `Multi-Strategy` off 933 funds.
    """

    if matrices.resolve(NAME_HINT_POLICY, "promotion") != "never_promoted":
        raise IntegrationError(f"{NAME_HINT_POLICY}: unsupported promotion policy")
    return fallback


def _unit_interval(seed: int, *parts: object) -> float:
    _require(UNIT_INTERVAL, "digest", "sha256_first8_bytes")
    digest = hashlib.sha256("|".join(map(str, (seed, *parts))).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)


def _imputation_method(field: str, is_canonical: bool) -> str:
    """The rule that filled this blank fund-master field, named per field.

    One label covered two unrelated rules for a while: `vintage_year`, which
    comes from a hash of the seed and fund ID spread across a configured year
    range, and `strategy`, which is the configured fallback constant. The label
    said both were a median of extracted values, and the reviewer glossary
    repeated it, so 1,043 cells were published under a method none of them
    used. Every field now names its own rule and a field with no declared rule
    stops the build instead of borrowing another field's label."""

    if is_canonical:
        return matrices.resolve(MASTER_PROVENANCE, "canonical_imputation_method")
    if field == "name_hint":
        return matrices.resolve(NAME_HINT_POLICY, "imputation_method")
    key = f"{field}_imputation_method"
    declared = {row["input_value"] for row in matrices.load(MASTER_PROVENANCE)}
    if key not in declared:
        raise IntegrationError(
            f"{MASTER_PROVENANCE}.csv declares no imputation rule for fund_master.{field}"
        )
    return matrices.resolve(MASTER_PROVENANCE, key)


def _lineage_row(
    *,
    target_table: str,
    target_record_id: str,
    target_field: str,
    target_value: object,
    provenance_type: str,
    source_table: str = "",
    source_record_id: str = "",
    source_document_id: str = "",
    source_anchor: str = "",
    formula_id: str = "",
    parameter_set_id: str = "",
    imputation_method: str = "",
    precedence: str = "",
    notes: str = "",
) -> dict[str, str]:
    lineage_id = stable_id("LIN", target_table, target_record_id, target_field)
    return {
        "lineage_id": lineage_id,
        "target_table": target_table,
        "target_record_id": target_record_id,
        "target_field": target_field,
        "target_value": str(target_value),
        "provenance_type": provenance_type,
        "source_table": source_table,
        "source_record_id": source_record_id,
        "source_document_id": source_document_id,
        "source_anchor": source_anchor,
        "formula_id": formula_id,
        "synthetic_parameter_set_id": parameter_set_id,
        "imputation_method": imputation_method,
        "precedence": precedence,
        "notes": notes,
    }


def _carried_canonical_lineage(
    target_table: str,
    record_id: str,
    values: Mapping[str, str],
    sources: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> list[dict[str, str]]:
    """Lineage for the canonical cells promotion filled and this stage carries.

    Promotion reads these cells off `context-grouping-map.csv` and writes one
    `attribute-changes.csv` row per cell naming the observation that printed the
    word. This stage leaves the cell alone, so its origin is that audit row, and
    a cell arriving without one is refused by name: the alternative is a
    published grouping with no lineage at either grain, which is what the 514
    funds carrying a printed strategy had."""

    rows: list[dict[str, str]] = []
    for field in CANONICAL_PERIOD_COLUMNS:
        value = (values.get(field, "") or "").strip()
        if not value:
            continue
        source = sources.get(record_id, {}).get(field)
        if source is None or source.get("value", "") != value:
            raise IntegrationError(
                f"{target_table} {record_id}: {field}={value!r} has no attribute-changes "
                "row stating the printed word it reads; stage 080 fund-model-promotion "
                "(python -m src.load.promote_extracted_to_fund_level) writes one for "
                "every canonical cell it fills"
            )
        rows.append(
            _lineage_row(
                target_table=target_table,
                target_record_id=record_id,
                target_field=field,
                target_value=value,
                provenance_type=matrices.resolve(MASTER_PROVENANCE, "carried_canonical_value"),
                source_table=source["source_table"],
                source_record_id=source["source_record_id"],
                source_document_id=source["source_document_id"],
                source_anchor=source["source_anchor"],
                formula_id=matrices.resolve(MASTER_PROVENANCE, "canonical_formula"),
                precedence=matrices.resolve(MASTER_PROVENANCE, "precedence"),
                notes=(
                    "Canonical grouping read at promotion from context-grouping-map.csv; "
                    "this stage carries the cell unchanged."
                ),
            )
        )
    return rows


def _gap_row(
    fund_id: str,
    table: str,
    record_id: str,
    field: str,
    value: object,
    resolution_type: str,
    lineage_id: str,
    *,
    open_gap: bool = False,
) -> dict[str, str]:
    return {
        "gap_id": stable_id("GAP", table, record_id, field),
        "fund_id": fund_id,
        "target_table": table,
        "target_record_id": record_id,
        "field_name": field,
        "original_value": matrices.resolve(GAP_DEFAULTS, "original_value"),
        "resolution_value": str(value),
        "resolution_type": resolution_type,
        "lineage_id": lineage_id,
        "status": matrices.resolve(GAP_DEFAULTS, "unfilled_status" if open_gap else "status"),
    }


def _parameter_rows(
    cfg: Mapping[str, object],
    periods: Sequence[Mapping[str, str]],
    master_rows: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, str]], dict[str, float]]:
    header, _ = read_csv(CSV_DIR / "synthetic_parameters.csv")
    del header
    parameter_set = str(cfg["parameter_set_id"])
    ratios: dict[str, list[float]] = {"dpi": [], "rvpi": [], "paid_in_ratio": []}
    inputs: dict[str, list[str]] = defaultdict(list)
    observed_size: list[float] = []
    _require(PARAMETER_POPULATIONS, "fund_size_currency", "configured_currency_only", context="eligibility")
    for row in (*master_rows, *periods):
        value = number(row.get("fund_size"))
        denomination = row.get("fund_size_currency") or row.get("currency")
        if value is not None and value > 0 and denomination == str(cfg["currency_fallback"]):
            observed_size.append(value)
            inputs["fund_size"].append(
                row.get("fund_period_id", "") or row.get("fund_id", "")
            )
    for row in periods:
        paid = number(row.get("paid_in_capital_itd"))
        commitment = number(row.get("commitment"))
        if paid is not None and paid > 0 and commitment is not None and commitment > 0:
            ratios["paid_in_ratio"].append(
                min(paid / commitment, float(matrices.resolve(PARAMETER_POPULATIONS, "paid_in_ratio_cap", context="eligibility")))
            )
            inputs["paid_in_ratio"].append(row.get("fund_period_id", ""))
        for metric in ("dpi", "rvpi"):
            value = number(row.get(metric))
            if value is not None and 0 <= value <= 10:
                ratios[metric].append(value)
                inputs[metric].append(row.get("fund_period_id", ""))
    derived = {
        "fund_size_median": statistics.median(observed_size)
        if observed_size
        else float(cfg["fund_size_fallback"]),
        "dpi_median": statistics.median(ratios["dpi"])
        if ratios["dpi"]
        else float(matrices.resolve(PARAMETER_POPULATIONS, "dpi_fallback", context="fallback")),
        "rvpi_median": statistics.median(ratios["rvpi"])
        if ratios["rvpi"]
        else float(matrices.resolve(PARAMETER_POPULATIONS, "rvpi_fallback", context="fallback")),
        "paid_in_ratio_median": statistics.median(ratios["paid_in_ratio"])
        if ratios["paid_in_ratio"]
        else float(matrices.resolve(PARAMETER_POPULATIONS, "paid_in_ratio_fallback", context="fallback")),
    }
    rows: list[dict[str, str]] = []
    for name, value in derived.items():
        key = name.replace(matrices.resolve(PARAMETER_KEYS, "median_suffix"), "")
        record_ids = inputs.get(key, [])
        provenance = matrices.resolve(PARAMETER_PROVENANCE, "with_inputs" if record_ids else "without_inputs")
        rows.append(
            {
                "parameter_id": stable_id("PAR", parameter_set, name),
                "parameter_set_id": parameter_set,
                "strategy": matrices.resolve(PARAMETER_STATUSES, "strategy_scope"),
                "sub_strategy": matrices.resolve(PARAMETER_STATUSES, "strategy_scope"),
                "parameter_name": name,
                "value_numeric": fmt(value, 10),
                "value_text": "",
                "unit": matrices.resolve_or_star(PARAMETER_UNITS, name),
                "provenance_type": provenance,
                "source_document_id": "",
                "source_page": "",
                "source_anchor": matrices.resolve(PARAMETER_FORMULAS, "derived_anchor" if record_ids else "assumed_anchor"),
                "formula_id": matrices.resolve(PARAMETER_FORMULAS, "derived_formula") if record_ids else "",
                "input_record_ids": " | ".join(sorted(set(record_ids))),
                "assumption_basis": (
                    "Median of eligible source-backed values."
                    if record_ids
                    else "No eligible extracted values exist; the declared configuration fallback is used."
                ),
                "adjudication_status": matrices.resolve(PARAMETER_STATUSES, "adjudication_status"),
                "active": matrices.resolve(PARAMETER_STATUSES, "active"),
            }
        )
    assumed = (
        tuple(
            (name, str(cfg[name]), matrices.resolve(ASSUMPTION_UNITS, name))
            for name in ("seed", "as_of_date", "benchmark_id", "strategy_fallback",
                         "currency_fallback", "fund_size_fallback")
        )
    )
    for name, value, unit in assumed:
        numeric = value if matrices.resolve_or_star(ASSUMPTION_CHANNELS, name) == "numeric" else ""
        rows.append(
            {
                "parameter_id": stable_id("PAR", parameter_set, name),
                "parameter_set_id": parameter_set,
                "strategy": "ALL",
                "sub_strategy": "ALL",
                "parameter_name": name,
                "value_numeric": numeric,
                "value_text": "" if numeric else value,
                "unit": unit,
                "provenance_type": "ASSUMED",
                "source_document_id": "",
                "source_page": "",
                "source_anchor": "config/integrated_completion.yml",
                "formula_id": "",
                "input_record_ids": "",
                "assumption_basis": "Declared integration parameter; it is not represented as an extracted fact.",
                "adjudication_status": matrices.resolve(PARAMETER_STATUSES, "adjudication_status"),
                "active": matrices.resolve(PARAMETER_STATUSES, "active"),
            }
        )
    return rows, derived


def benchmark_ids_in_use(cfg: Mapping[str, object]) -> list[str]:
    """Every benchmark the release prices a fund against.

    PME keys the comparison on the fund's canonical strategy, so the stage that
    promotes benchmark returns has to promote the series for every benchmark
    strategy-benchmark-map.csv can name, not only the one the configuration
    calls the default. Promoting one and selecting many is how every fund came
    to be priced against the same index."""

    identifier = matrices.resolve(
        BENCHMARK_IDENTIFIERS, "benchmark_format", context="benchmark"
    )
    named = {
        identifier.format(ticker=row["output_value"])
        for row in matrices.load(BENCHMARK_MAP)
    }
    return sorted(named | {str(cfg["benchmark_id"])})


def _benchmark_rows(
    cfg: Mapping[str, object],
    lineage: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], float]:
    default_benchmark_id = str(cfg["benchmark_id"])
    wanted = benchmark_ids_in_use(cfg)
    master_header, masters = read_csv(PUBLIC_MARKET_DIR / "benchmark_master_candidates.csv")
    del master_header
    return_header, candidates = read_csv(PUBLIC_MARKET_DIR / "benchmark_return_candidates.csv")
    del return_header
    selection_key = matrices.resolve(BENCHMARK_SELECTION, "selection_key")
    masters_by_id = {row.get(selection_key, ""): row for row in masters}
    missing = [name for name in wanted if name not in masters_by_id]
    if missing and matrices.resolve(BENCHMARK_SELECTION, "missing_candidate") == "refused":
        raise IntegrationError(f"benchmark candidate is missing: {', '.join(missing)}")
    policy = cfg.get("benchmark_policy", {})
    if not isinstance(policy, dict):
        raise IntegrationError("benchmark_policy must be a mapping")
    rows: list[dict[str, str]] = []
    recent_growth = 1.0
    target = date.fromisoformat(str(cfg["as_of_date"]))
    trailing_start = target - timedelta(days=int(matrices.resolve(BENCHMARK_WINDOW, "trailing_days")))
    for source in candidates:
        benchmark_id = source.get("benchmark_id", "")
        if benchmark_id not in masters_by_id or benchmark_id not in wanted:
            continue
        master = masters_by_id[benchmark_id]
        return_date = parse_date(source.get("return_date"))
        value = number(source.get("return_value"))
        if return_date is None or value is None:
            continue
        row = {
            "benchmark_return_id": source["benchmark_return_id"],
            "benchmark_id": benchmark_id,
            "benchmark_name": master.get("benchmark_name", ""),
            "return_date": return_date.isoformat(),
            "periodicity": source.get("periodicity", matrices.resolve(BENCHMARK_PERIODICITY, "default_periodicity")).upper(),
            "return_value": source.get("return_value", ""),
            "currency": next(
                (
                    value
                    for field, value in zip(
                        _ranked_outputs(BENCHMARK_FALLBACKS),
                        (source.get("currency", ""), master.get("currency", "")),
                    )
                    if value and field in ("source_currency", "master_currency")
                ),
                "",
            ),
            "provenance_type": matrices.resolve(BENCHMARK_LABELS, "provenance_type"),
            "source_document_id": master.get("source_file_id", ""),
            "source_page": "",
            "source_anchor": (
                f"data/public_markets/staging/benchmark_return_candidates.csv:{source['benchmark_return_id']}; "
                f"rights_status={policy.get('rights_status', '')}; use_status={policy.get('use_status', '')}"
            ),
            "synthetic_parameter_set_id": matrices.resolve(BENCHMARK_LABELS, "parameter_set_id"),
            "record_status": matrices.resolve(BENCHMARK_LABELS, "record_status"),
        }
        rows.append(row)
        # The completed period states one benchmark return, and it is the
        # configured benchmark's. Compounding every promoted series into one
        # number would state a return no index earned.
        if benchmark_id == default_benchmark_id and trailing_start < return_date <= target:
            _require(BENCHMARK_FORMULA, "trailing_growth", "product_of_one_plus_return")
            recent_growth *= 1.0 + value
        lineage.append(
            _lineage_row(
                target_table="benchmark_returns",
                target_record_id=row["benchmark_return_id"],
                target_field="*row",
                target_value=row["return_value"],
                provenance_type="DERIVED",
                source_table="benchmark_return_candidates",
                source_record_id=source["benchmark_return_id"],
                source_document_id=master.get("source_file_id", ""),
                source_anchor=row["source_anchor"],
                formula_id=matrices.resolve(BENCHMARK_LABELS, "promotion_formula"),
                precedence=matrices.resolve(BENCHMARK_LABELS, "precedence"),
                notes=matrices.resolve(BENCHMARK_LABELS, "lineage_note"),
            )
        )
    rows.sort(key=lambda row: (row["return_date"], row["benchmark_return_id"]))
    by_benchmark: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_benchmark[row["benchmark_id"]].append(row)
    empty = [name for name in wanted if not by_benchmark.get(name)]
    if empty and matrices.resolve(BENCHMARK_ELIGIBILITY, "zero_usable_rows") == "refused":
        raise IntegrationError(f"benchmark has zero usable return rows: {', '.join(empty)}")
    # One policy row per promoted benchmark: the rights gate reads the policy by
    # benchmark_id, so a benchmark promoted without one is refused at stage 105.
    policy_rows = [
        {
            "benchmark_id": name,
            "benchmark_name": masters_by_id[name].get("benchmark_name", ""),
            "rights_status": str(policy.get("rights_status", "")),
            "use_status": str(policy.get("use_status", "")),
            "source_file_id": masters_by_id[name].get("source_file_id", ""),
            "first_observation_date": by_benchmark[name][0]["return_date"] if matrices.resolve(BENCHMARK_SUMMARY, "first_observation") == "earliest_return_date" else "",
            "last_observation_date": by_benchmark[name][-1]["return_date"] if matrices.resolve(BENCHMARK_SUMMARY, "last_observation") == "latest_return_date" else "",
            "observation_count": str(len(by_benchmark[name])),
            "note": str(policy.get("note", "")),
        }
        for name in wanted
    ]
    return rows, policy_rows, recent_growth - 1.0


def _complete_master(
    cfg: Mapping[str, object],
    fund_ids: Sequence[str],
    tables: Mapping[str, Sequence[Mapping[str, str]]],
    names: Mapping[str, str],
    attributes: Mapping[str, Mapping[str, str]],
    attribute_sources: Mapping[str, Mapping[str, Mapping[str, str]]],
    evidence: Mapping[str, Mapping[str, str]],
    period_map: Mapping[str, Sequence[Mapping[str, str]]],
    derived: Mapping[str, float],
    lineage: list[dict[str, str]],
    gaps: list[dict[str, str]],
) -> list[dict[str, str]]:
    seed = int(cfg["seed"])
    parameter_set = str(cfg["parameter_set_id"])
    _require(MASTER_DUPES, "repeated_fund_id", "last_row_wins")
    existing = {row["fund_id"]: dict(row) for row in tables["fund_master"]}
    maps_by_fund: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in tables["document_fund_map"]:
        maps_by_fund[row.get("fund_id", "")].append(row)
    output: list[dict[str, str]] = []
    for fund_id in fund_ids:
        if _ranked_outputs(MASTER_NAME_ORDER, "fund_name") != ("identity_registry", "existing_master"):
            raise IntegrationError("fund-master-field-precedence.csv names an unknown order")
        name = names.get(fund_id, "") or existing.get(fund_id, {}).get("fund_name", "")
        if not name:
            raise IntegrationError(f"identity registry lacks a name for {fund_id}")
        is_new = fund_id not in existing
        source = evidence.get(fund_id, {})
        row = dict(existing.get(fund_id, {}))
        # What promotion already read onto this fund, before the fill below can
        # touch a blank one. The fill skips a nonblank cell, so without this the
        # carried readings reached the published master with no lineage row.
        carried_canonical = {
            field: row.get(field, "") for field in CANONICAL_PERIOD_COLUMNS
        }
        lineage.extend(
            _carried_canonical_lineage(
                "fund_master", fund_id, carried_canonical, attribute_sources
            )
        )
        if is_new:
            row.update(
                {
                    "fund_id": fund_id,
                    "fund_name": name,
                    "legal_name": name,
                    "provenance_type": matrices.resolve(NEW_MASTER_FIELDS, "provenance_type"),
                    "source_document_id": source.get("source_document_id", ""),
                    "source_page": source.get("source_page", ""),
                    "source_anchor": source.get("source_anchor", ""),
                    "synthetic_parameter_set_id": "",
                    "record_status": matrices.resolve(NEW_MASTER_FIELDS, "record_status"),
                    "created_at": "",
                }
            )
            for field in ("fund_name", "legal_name"):
                lin = _lineage_row(
                    target_table="fund_master",
                    target_record_id=fund_id,
                    target_field=field,
                    target_value=row[field],
                    provenance_type="EXTRACTED" if field == "fund_name" else "DERIVED",
                    source_table=source.get("source_table", ""),
                    source_record_id=source.get("source_record_id", ""),
                    source_document_id=source.get("source_document_id", ""),
                    source_anchor=source.get("source_anchor", ""),
                    formula_id="" if field == "fund_name" else matrices.resolve(NEW_MASTER_DEFAULTS, "legal_name_formula"),
                    precedence=matrices.resolve(NEW_MASTER_DEFAULTS, "identity_precedence"),
                    notes="Identity came from the normalized source-backed fund registry.",
                )
                lineage.append(lin)
                gaps.append(_gap_row(fund_id, "fund_master", fund_id, field, row[field], lin["provenance_type"], lin["lineage_id"]))

        period_rows = list(period_map.get(fund_id, ()))
        attr = attributes.get(fund_id, {})
        _require(MANAGER_SELECTION, "manager_source", "first_nonblank_document_fund_map")
        manager_name = next(
            (item.get("fund_manager_raw", "") for item in maps_by_fund.get(fund_id, ()) if item.get("fund_manager_raw", "")),
            "",
        )
        if len(_ranked_outputs(STRATEGY_ORDER)) != 5 or len(_ranked_outputs(VINTAGE_ORDER)) != 4 or len(_ranked_outputs(SIZE_ORDER)) != 3:
            raise IntegrationError("a fund-master precedence matrix names an unexpected chain")
        strategy_value = row.get("strategy", "") or attr.get("strategy", "")
        strategy_source: Mapping[str, str] | None = None
        if not strategy_value:
            strategy_value, strategy_source = _first_value(period_rows, "strategy")
        printed_strategy, printed_strategy_row = _first_value(period_rows, "strategy")
        printed_class, printed_canonical_strategy, printed_sub = _canonical_of(
            printed_strategy, "strategy"
        )
        class_source = _period_lineage_source(printed_strategy_row) if printed_class else None
        canonical_strategy_source = (
            _period_lineage_source(printed_strategy_row)
            if printed_canonical_strategy
            else None
        )
        if not printed_class:
            printed_asset_class, printed_asset_class_row = _first_value(
                period_rows, "asset_class"
            )
            printed_class, _, _ = _canonical_of(printed_asset_class, "asset_class")
            class_source = (
                _period_lineage_source(printed_asset_class_row)
                if printed_class
                else None
            )

        attribute_strategy_source = attribute_sources.get(fund_id, {}).get("strategy")
        if attribute_strategy_source and attribute_strategy_source.get("value") != strategy_value:
            attribute_strategy_source = None
        classifier_group = _canonical_of(strategy_value, "classifier_output")
        strategy_group = _canonical_of(strategy_value, "strategy")
        mapped_class = classifier_group[0] or strategy_group[0]
        mapped_strategy = classifier_group[1] or strategy_group[1]
        source_strategy_row = _period_lineage_source(strategy_source)
        strategy_is_stated = bool(source_strategy_row or attribute_strategy_source)
        stated_class = printed_class or (mapped_class if strategy_is_stated else "")
        # The name fires a hint. It is dropped outright when the pages that
        # print this fund say something else, and it is never published either
        # way: it is recorded on name_hint so a reader can see what the name
        # suggested and what the corpus actually states.
        hint_keyword, _ = _accepted_name_hint(name, stated_class)
        inferred_strategy = _strategy_from_name(name, str(cfg["strategy_fallback"]))
        if not strategy_value:
            strategy_value = inferred_strategy
            classifier_group = _canonical_of(strategy_value, "classifier_output")
            strategy_group = _canonical_of(strategy_value, "strategy")
            mapped_class = classifier_group[0] or strategy_group[0]
            mapped_strategy = classifier_group[1] or strategy_group[1]

        if not class_source and mapped_class and strategy_is_stated:
            class_source = source_strategy_row or attribute_strategy_source
        if not canonical_strategy_source and mapped_strategy and strategy_is_stated:
            canonical_strategy_source = source_strategy_row or attribute_strategy_source
        canonical_sources = {
            "canonical_asset_class": class_source,
            "canonical_strategy": canonical_strategy_source,
        }
        # sub_strategy is filled only where the corpus prints a grouping this
        # fund sits under; nothing else closes that gap.
        sub_strategy = row.get("sub_strategy", "") or printed_sub
        sub_strategy_source = printed_strategy_row if (printed_sub and not row.get("sub_strategy", "")) else None

        vintage_value = row.get("vintage_year", "") or attr.get("vintage_year", "")
        vintage_source: Mapping[str, str] | None = None
        if not vintage_value:
            vintage_value, vintage_source = _first_value(period_rows, "vintage_year")
        if not vintage_value:
            vintage_value = str(
                int(matrices.resolve(MASTER_DEFAULTS, "vintage_base_year"))
                + int(_unit_interval(seed, fund_id, "vintage") * int(matrices.resolve(MASTER_DEFAULTS, "vintage_span_years")))
            )

        size_value = row.get("fund_size", "")
        size_source: Mapping[str, str] | None = None
        if not size_value:
            size_value, size_source = _first_value(period_rows, "fund_size")
        if not size_value:
            scale = float(matrices.resolve(MASTER_DEFAULTS, "size_scale_base")) + float(
                matrices.resolve(MASTER_DEFAULTS, "size_scale_span")
            ) * _unit_interval(seed, fund_id, "fund_size")
            size_value = fmt(max(float(derived["fund_size_median"]), float(cfg["fund_size_fallback"])) * scale)

        candidates = {
            "legal_name": row.get("legal_name", "") or name,
            "fund_manager_name": row.get("fund_manager_name", "") or manager_name,
            "strategy": strategy_value,
            "sub_strategy": sub_strategy,
            "vintage_year": vintage_value,
            "base_currency": row.get("base_currency", "") or row.get("fund_size_currency", "") or str(cfg["currency_fallback"]),
            "fund_size": size_value,
            "fund_size_currency": row.get("fund_size_currency", "") or str(cfg["currency_fallback"]),
            "fund_status": row.get("fund_status", "") or matrices.resolve(MASTER_DEFAULTS, "fund_status"),
            "name_hint": hint_keyword,
            # The two canonical dimensions every strategy vocabulary maps into,
            # each holding only what its name says: the class (private_equity,
            # venture_capital) and the strategy inside it (buyout, secondaries),
            # blank where the corpus states no finer split.
            "canonical_asset_class": (
                printed_class
                or mapped_class
            ),
            "canonical_strategy": (
                printed_canonical_strategy
                or mapped_strategy
            ),
        }
        _require(FILL_POLICY, "nonblank_cell", "retained")
        for field, value in candidates.items():
            if row.get(field, "") or not value:
                continue
            canonical_source = canonical_sources.get(field)
            propagated = (
                field in {"strategy", "vintage_year"}
                and (attr.get(field, "") or (strategy_source if field == "strategy" else vintage_source))
            ) or (field == "fund_size" and size_source is not None) or (
                field == "fund_manager_name" and bool(manager_name)
            ) or (field == "sub_strategy" and sub_strategy_source is not None)
            if field in canonical_sources:
                provenance = (
                    matrices.resolve(MASTER_PROVENANCE, "propagated_value")
                    if canonical_source
                    else matrices.resolve(MASTER_PROVENANCE, "otherwise")
                )
            else:
                provenance = (
                    matrices.resolve(MASTER_PROVENANCE, "propagated_value")
                    if propagated
                    else matrices.resolve(MASTER_PROVENANCE, field)
                    if field == "legal_name"
                    else matrices.resolve(MASTER_PROVENANCE, "otherwise")
                )
            row[field] = value
            source_row = (
                strategy_source if field == "strategy"
                else sub_strategy_source if field == "sub_strategy"
                else vintage_source if field == "vintage_year"
                else size_source if field == "fund_size"
                else None
            )
            imputation_method = ""
            if provenance == "IMPUTED":
                imputation_method = _imputation_method(field, field in canonical_sources)
            lin = _lineage_row(
                target_table="fund_master",
                target_record_id=fund_id,
                target_field=field,
                target_value=value,
                provenance_type=provenance,
                source_table=canonical_source.get("source_table", "")
                if canonical_source
                else matrices.resolve(PROVENANCE_TABLES, "period_value")
                if source_row
                else matrices.resolve(PROVENANCE_TABLES, "attribute_value")
                if attr.get(field, "")
                else matrices.resolve(PROVENANCE_TABLES, "manager_value")
                if field == "fund_manager_name" and manager_name
                else "",
                source_record_id=canonical_source.get("source_record_id", "")
                if canonical_source
                else (source_row or {}).get("fund_period_id", ""),
                # An imputed value cites no page. Pointing a reader at the
                # document that named the fund, for a value that document never
                # states, is what made a name guess read as a printed fact.
                source_document_id=""
                if provenance == "IMPUTED"
                else canonical_source.get("source_document_id", "")
                if canonical_source
                else (source_row or {}).get("source_document_id", "") or source.get("source_document_id", ""),
                source_anchor=""
                if provenance == "IMPUTED"
                else canonical_source.get("source_anchor", "")
                if canonical_source
                else (source_row or {}).get("source_anchor", "") or source.get("source_anchor", ""),
                formula_id=(
                    matrices.resolve(MASTER_PROVENANCE, "canonical_formula")
                    if provenance == "DERIVED" and field in canonical_sources
                    else matrices.resolve(MASTER_PROVENANCE, "derived_formula")
                    if provenance == "DERIVED"
                    else ""
                ),
                parameter_set_id=parameter_set if provenance == "IMPUTED" and field != "name_hint" else "",
                imputation_method=imputation_method,
                precedence=matrices.resolve(MASTER_PROVENANCE, "precedence"),
                notes=(
                    "Canonical grouping derived from a source-backed printed fund attribute."
                    if field in canonical_sources and canonical_source
                    else "Canonical grouping derived from the configured strategy fallback; no source page states it."
                    if field in canonical_sources
                    else "Only a blank fund-model cell was filled; every nonblank extracted cell was retained."
                ),
            )
            _require(LINEAGE_ROUTING, "filled_field", "lineage_and_gap_row")
            lineage.append(lin)
            gaps.append(_gap_row(fund_id, "fund_master", fund_id, field, value, provenance, lin["lineage_id"]))

        # A gap no printed evidence closes stays open.
        for field in ("sub_strategy",):
            if not row.get(field, ""):
                gaps.append(
                    _gap_row(fund_id, "fund_master", fund_id, field, "", "UNRESOLVED", "", open_gap=True)
                )
        output.append(row)
    return output


def _performance_anchor(
    rows: Sequence[Mapping[str, str]], field: str, maximum: float | None = None
) -> float | None:
    value, _ = _first_value(rows, field)
    parsed = number(value)
    return (
        parsed
        if parsed is not None and parsed >= 0 and (maximum is None or parsed <= maximum)
        else None
    )


def _target_period(
    cfg: Mapping[str, object],
    master: Mapping[str, str],
    source_rows: Sequence[Mapping[str, str]],
    derived: Mapping[str, float],
    benchmark_return: float,
) -> dict[str, str]:
    seed = int(cfg["seed"])
    fund_id = master["fund_id"]
    target = str(cfg["as_of_date"])
    target_year = date.fromisoformat(target).year
    vintage = int(master["vintage_year"])
    age = max(target_year - vintage, 1)
    jitter = _unit_interval(seed, fund_id, "performance") - 0.5
    fund_size = number(master.get("fund_size")) or float(cfg["fund_size_fallback"])
    currency = master.get("base_currency", "") or str(cfg["currency_fallback"])
    _require(COMPLETION_PARAMETERS, "monetary_anchor_currency", "match_target_currency", context="anchors")
    money_rows = [row for row in source_rows if row.get("currency") == currency]
    commitment_anchor = _performance_anchor(money_rows, "commitment")
    commitment = max(commitment_anchor or fund_size, _parameter("anchors", "commitment_floor"))
    paid_anchor = _performance_anchor(money_rows, "paid_in_capital_itd")
    _low, _high = (float(part) for part in matrices.resolve(COMPLETION_PARAMETERS, "paid_ratio_clamp", context="paid_ratio").split(".."))
    paid_ratio = min(_high, max(_low, float(derived["paid_in_ratio_median"])
        + _parameter("paid_ratio", "paid_ratio_age_slope") * (age - _parameter("paid_ratio", "paid_ratio_age_center"))
        + jitter * _parameter("paid_ratio", "paid_ratio_jitter")))
    paid_in = paid_anchor if paid_anchor and paid_anchor <= commitment else commitment * paid_ratio
    if paid_in > commitment:
        commitment = paid_in / _parameter("anchors", "paid_over_commitment_cap")

    dpi = _performance_anchor(source_rows, "dpi", 10)
    rvpi = _performance_anchor(source_rows, "rvpi", 10)
    if dpi is None:
        distributions_anchor = _performance_anchor(money_rows, "distributions_itd")
        anchor_paid = _performance_anchor(money_rows, "paid_in_capital_itd")
        if distributions_anchor is not None and anchor_paid and anchor_paid > 0:
            dpi = distributions_anchor / anchor_paid
    if rvpi is None:
        nav_anchor = _performance_anchor(money_rows, "nav")
        anchor_paid = _performance_anchor(money_rows, "paid_in_capital_itd")
        if nav_anchor is not None and anchor_paid and anchor_paid > 0:
            rvpi = nav_anchor / anchor_paid
    tvpi_anchor = _performance_anchor(source_rows, "tvpi", 10)
    if dpi is None and rvpi is None and tvpi_anchor is not None:
        _require(COMPLETION_PARAMETERS, "maturity_share", "age/15 clamped 0.15..0.9", context="ratios")
        maturity_share = min(max(age / 15.0, 0.15), 0.9)
        dpi = tvpi_anchor * maturity_share
        rvpi = max(tvpi_anchor - dpi, 0.0)
    dpi = max(
        dpi if dpi is not None else float(derived["dpi_median"]) + _parameter("ratios", "dpi_age_slope") * (age - 8) + jitter * _parameter("ratios", "dpi_jitter"),
        _parameter("ratios", "dpi_floor"),
    )
    rvpi = max(
        rvpi if rvpi is not None else float(derived["rvpi_median"]) + _parameter("ratios", "rvpi_age_slope") * (age - 8) + jitter * _parameter("ratios", "rvpi_jitter"),
        _parameter("ratios", "rvpi_floor"),
    )
    dpi = min(dpi, _parameter("ratios", "ratio_cap"))
    rvpi = min(rvpi, _parameter("ratios", "ratio_cap"))
    distributions = paid_in * dpi
    nav = paid_in * rvpi
    unfunded = commitment - paid_in

    beginning_nav = nav * _parameter("period_flows", "beginning_nav_share")
    contributions_period = paid_in * _parameter("period_flows", "contributions_share")
    distributions_period = distributions * _parameter("period_flows", "distributions_share")
    unrealized_gain = nav * _parameter("period_flows", "unrealized_gain_share")
    net_income = beginning_nav * _parameter("period_flows", "net_income_share")
    management_fee = commitment * _parameter("period_flows", "management_fee_share")
    other_expenses = commitment * _parameter("period_flows", "other_expenses_share")
    realized_gain = nav - (
        beginning_nav
        + contributions_period
        - distributions_period
        + unrealized_gain
        + net_income
        - management_fee
        - other_expenses
    )
    period_return = (
        (nav - beginning_nav - contributions_period + distributions_period) / beginning_nav
        if beginning_nav > 0
        else 0.0
    )
    return {
        "fund_period_id": stable_id("FPRINT", fund_id, target),
        "fund_id": fund_id,
        "lp_id": "",
        "lp_name": "",
        "share_class_name": "",
        "date_role": "as_of",
        "date_raw": target,
        "date_precision": "day",
        "as_of_date": target,
        "report_date": "",
        "period_start_date": f"{target_year}-01-01"
        if matrices.resolve(COMPLETION_PARAMETERS, "period_start", context="dates") == "january_first_of_target_year"
        else "",
        "period_end_date": target,
        "effective_date": "",
        "perspective": "fund_total",
        "currency": currency,
        "commitment": fmt(commitment),
        "paid_in_capital_itd": fmt(paid_in),
        "distributions_itd": fmt(distributions),
        "nav": fmt(nav),
        "unfunded_commitment": fmt(unfunded),
        "recallable_distributions_itd": fmt(0),
        "dpi": fmt(dpi, 10),
        "rvpi": fmt(rvpi, 10),
        "tvpi": fmt(dpi + rvpi, 10),
        "reported_irr": "",
        "calculated_irr": "",
        "beginning_nav": fmt(beginning_nav),
        "contributions_period": fmt(contributions_period),
        "distributions_period": fmt(distributions_period),
        "realized_gain_period": fmt(realized_gain),
        "unrealized_gain_period": fmt(unrealized_gain),
        "net_income_period": fmt(net_income),
        "management_fee_period": fmt(management_fee),
        "other_expenses_period": fmt(other_expenses),
        "ending_nav": fmt(nav),
        "period_return": fmt(period_return, 10),
        "benchmark_return": fmt(benchmark_return, 10),
        "fund_size": fmt(max(fund_size, commitment)),
        "vintage_year": str(vintage),
        "strategy": master.get("strategy", ""),
        "sub_strategy": master.get("sub_strategy", ""),
        # The printed industry and the taxonomy reading travel with the printed
        # grouping. Every surface downstream groups on these columns, and a
        # printed word with no reading beside it is a grouping nobody can join.
        "sector": master.get("sector", ""),
        **_period_grouping(master),
        "provenance_type": "SYNTHETIC",
        "source_document_id": "",
        "source_page": "",
        "source_anchor": "data/integrated/cell-lineage.csv",
        "formula_id": matrices.resolve(COMPLETION_PARAMETERS, "completion_formula"),
        # No printed cell feeds this row directly; the printed periods it is
        # completed from are cited in data/integrated/cell-lineage.csv.
        "input_observation_ids": "",
        "synthetic_parameter_set_id": str(cfg["parameter_set_id"]),
        "defect_expected": "FALSE",
        "record_status": "ACTIVE",
    }


def _cashflow_dates(vintage: int, target: date) -> list[date]:
    month, day = (int(part) for part in matrices.resolve(CASHFLOW_SCHEDULE, "start_month_day").split("-"))
    floor = date.fromisoformat(matrices.resolve(CASHFLOW_SCHEDULE, "start_floor"))
    minimum_span = int(matrices.resolve(CASHFLOW_SCHEDULE, "minimum_span_days"))
    start = max(date(vintage, month, day), floor)
    if start >= target - timedelta(days=minimum_span):
        start = target - timedelta(days=minimum_span)
    span = (target - start).days
    fractions = tuple(float(part) for part in matrices.resolve(CASHFLOW_SCHEDULE, "date_fractions").split("|"))
    return [start + timedelta(days=max(int(span * fraction), index)) for index, fraction in enumerate(fractions)]


def _generated_cashflows(
    cfg: Mapping[str, object], period: Mapping[str, str]
) -> list[dict[str, str]]:
    fund_id = period["fund_id"]
    paid = Decimal(period["paid_in_capital_itd"])
    distributions = Decimal(period["distributions_itd"])
    target = date.fromisoformat(period["as_of_date"])
    dates = _cashflow_dates(int(period["vintage_year"]), target)
    amounts: list[tuple[str, Decimal]] = []
    call_fractions = tuple(Decimal(part) for part in matrices.resolve(CASHFLOW_SCHEDULE, "call_fractions").split("|"))
    distribution_fractions = tuple(Decimal(part) for part in matrices.resolve(CASHFLOW_SCHEDULE, "distribution_fractions").split("|"))
    call_values = [(paid * fraction).quantize(Decimal("0.000001")) for fraction in call_fractions[:-1]]
    call_values.append(paid - sum(call_values, Decimal(0)))
    distribution_values = [
        (distributions * fraction).quantize(Decimal("0.000001"))
        for fraction in distribution_fractions[:-1]
    ]
    distribution_values.append(distributions - sum(distribution_values, Decimal(0)))
    amounts.extend(("capital_call", -value) for value in call_values)
    amounts.extend(("distribution", value) for value in distribution_values)
    rows: list[dict[str, str]] = []
    for index, ((flow_type, amount), flow_date) in enumerate(zip(amounts, dates, strict=True), start=1):
        cashflow_id = stable_id("CFINT", fund_id, flow_date.isoformat(), flow_type, index)
        rows.append(
            {
                "cashflow_id": cashflow_id,
                "fund_id": fund_id,
                "lp_id": "",
                "lp_name": "",
                "share_class_name": "",
                "file_id": "",
                "cashflow_event_id": stable_id("EVTINT", fund_id, index),
                "date_role": "cashflow",
                "date_raw": flow_date.isoformat(),
                "date_precision": "day",
                "cashflow_date": flow_date.isoformat(),
                "report_date": "",
                "due_date": "",
                "cashflow_type": flow_type,
                "amount": fmt(amount),
                "currency": period["currency"],
                "amount_base_currency": fmt(amount),
                "base_currency": period["currency"],
                "fx_rate": fmt(1, 10),
                "recallable_amount": fmt(0),
                "provenance_type": "SYNTHETIC",
                "source_page": "",
                "source_anchor": f"generated from {period['fund_period_id']}",
                "synthetic_parameter_set_id": str(cfg["parameter_set_id"]),
                "defect_expected": "FALSE",
                "record_status": "ACTIVE",
            }
        )
    return rows


def _populate_calculated_irr(
    target_periods: Sequence[dict[str, str]],
    cashflows: Sequence[Mapping[str, str]],
) -> None:
    by_position: dict[tuple[str, str, str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in cashflows:
        by_position[quality_position_key(row)].append(row)
    for period in target_periods:
        target = date.fromisoformat(period["as_of_date"])
        dated: list[tuple[date, float]] = []
        for flow in by_position[quality_position_key(period)]:
            flow_date = parse_date(flow.get("cashflow_date"))
            amount = number(flow.get("amount_base_currency"))
            if amount is None:
                if flow.get("currency") != period.get("currency"):
                    raise IntegrationError("Cash-flow currency differs from the period without a converted amount")
                amount = number(flow.get("amount"))
            elif flow.get("base_currency") != period.get("currency"):
                raise IntegrationError("Converted cash-flow currency differs from the period")
            if flow_date is not None and amount is not None and flow_date <= target:
                dated.append((flow_date, amount))
        dated.append((target, float(period["nav"])))
        period["calculated_irr"] = fmt(xirr(dated), 10)


def _generated_terms_and_holdings(
    cfg: Mapping[str, object],
    masters: Sequence[Mapping[str, str]],
    target_periods: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    seed = int(cfg["seed"])
    parameter_set = str(cfg["parameter_set_id"])
    target = str(cfg["as_of_date"])
    periods = {row["fund_id"]: row for row in target_periods}
    terms: list[dict[str, str]] = []
    clauses: list[dict[str, str]] = []
    holdings: list[dict[str, str]] = []
    _require(TERMS_PARAMETERS, "management_fee", "0.015 + 0.01*u", context="terms")
    _require(TERMS_PARAMETERS, "carry_rate", "0.20 (u<0.85) else 0.25", context="terms")
    _require(TERMS_PARAMETERS, "hurdle_rate", "0.08 with 0.20 carry, 0.06 with 0.25", context="terms")
    _require(TERMS_PARAMETERS, "expense_cap_rate", "0.003", context="terms")
    sectors = tuple(matrices.resolve(TERMS_PARAMETERS, "sectors", context="holdings").split("|"))
    for master in masters:
        fund_id = master["fund_id"]
        period = periods[fund_id]
        vintage = int(master["vintage_year"])
        fee_rate = 0.015 + 0.01 * _unit_interval(seed, fund_id, "management_fee")
        carry_rate = 0.20 if _unit_interval(seed, fund_id, "carry") < 0.85 else 0.25
        hurdle_rate = 0.08 if carry_rate == 0.20 else 0.06
        term_id = stable_id("TERMINT", fund_id)
        terms.append(
            {
                "fund_term_id": term_id,
                "fund_id": fund_id,
                "lp_id": "",
                "lp_name": "",
                "share_class_name": "",
                "perspective": "fund_total",
                "term_scope": "base_fund",
                "overrides_fund_term_id": "",
                "effective_date": f"{vintage}-01-01",
                "effective_end_date": f"{vintage + 12}-12-31",
                "management_fee_rate": fmt(fee_rate, 10),
                "management_fee_basis": matrices.resolve(TERMS_PARAMETERS, "fee_basis", context="terms"),
                "carry_rate": fmt(carry_rate, 10),
                "hurdle_rate": fmt(hurdle_rate, 10),
                "catch_up_rate": fmt(1.0, 10),
                "catch_up_present": "TRUE",
                "waterfall_type": matrices.resolve(TERMS_PARAMETERS, "waterfall_type", context="terms"),
                "fund_term_years": fmt(10, 4),
                "extension_years": fmt(2, 4),
                "preferred_return_compounding": matrices.resolve(TERMS_PARAMETERS, "compounding", context="terms"),
                "expense_cap_rate": fmt(0.003, 10),
                "maximum_offering": master.get("fund_size", ""),
                "currency": master.get("base_currency", "") or str(cfg["currency_fallback"]),
                "provenance_type": "SYNTHETIC",
                "source_document_id": "",
                "source_page": "",
                "source_anchor": "data/integrated/cell-lineage.csv",
                "synthetic_parameter_set_id": parameter_set,
                "record_status": "ACTIVE",
            }
        )
        clauses.append(
            {
                "fund_term_clause_id": stable_id("CLAUSEINT", fund_id, "key_person"),
                "fund_id": fund_id,
                "lp_id": "",
                "lp_name": "",
                "share_class_name": "",
                "perspective": "fund_total",
                "term_scope": "base_fund",
                "overrides_fund_term_id": "",
                "effective_date": f"{vintage}-01-01",
                "effective_end_date": f"{vintage + 12}-12-31",
                "source_document_id": "",
                "metric_id": "terms.special_term",
                "clause_title": "Illustrative key-person provision",
                "value_raw": "Synthetic demonstration clause; no source document reports this term.",
                "value_text": "Investment activity pauses after a declared key-person event until committee approval.",
                "currency": "",
                "provenance_type": "SYNTHETIC",
                "source_page": "",
                "source_anchor": "data/integrated/cell-lineage.csv",
                "extractor_version": "",
                "synthetic_parameter_set_id": parameter_set,
                "record_status": "ACTIVE",
            }
        )
        nav = Decimal(period["nav"])
        _split = matrices.resolve(TERMS_PARAMETERS, "fair_value_split", context="holdings").split("|")
        fair_values = [
            (nav * Decimal(_split[0])).quantize(Decimal("0.000001")),
            (nav * Decimal(_split[1])).quantize(Decimal("0.000001")),
        ]
        fair_values.append(nav - sum(fair_values, Decimal(0)))
        for index, (sector, fair_value) in enumerate(zip(sectors, fair_values, strict=True), start=1):
            _require(TERMS_PARAMETERS, "cost_divisor", "1.05 + 0.10*index", context="holdings")
            cost = fair_value / Decimal(str(1.05 + 0.10 * index))
            holdings.append(
                {
                    "holding_id": stable_id("HOLDINT", fund_id, target, index),
                    "fund_id": fund_id,
                    "portfolio_company_id": "",
                    "portfolio_company_name": f"Illustrative {sector} Holding {index}",
                    "instrument_id": "",
                    "instrument_name": "Private investment",
                    "date_role": "as_of",
                    "date_raw": target,
                    "date_precision": "day",
                    "as_of_date": target,
                    "report_date": "",
                    "period_start_date": "",
                    "period_end_date": "",
                    "effective_date": "",
                    "security_type": "Debt"
                    if matrices.resolve(TERMS_PARAMETERS, "security_type", context="holdings").startswith("Debt for Private Credit")
                    and master.get("strategy") == "Private Credit"
                    else "Equity",
                    "sector": sector,
                    "geography": matrices.resolve(TERMS_PARAMETERS, "holding_geography", context="holdings"),
                    "currency": period["currency"],
                    "cost": fmt(cost),
                    "fair_value": fmt(fair_value),
                    "principal_amount": "",
                    "interest_rate": "",
                    "spread_bps": "",
                    "maturity_date": "",
                    "ownership_percent": fmt(0.10 + 0.05 * index, 10),  # ownership row in terms-generation-parameters.csv
                    "provenance_type": "SYNTHETIC",
                    "source_document_id": "",
                    "source_page": "",
                    "source_anchor": "data/integrated/cell-lineage.csv",
                    "synthetic_parameter_set_id": parameter_set,
                    "record_status": "ACTIVE",
                }
            )
    return terms, clauses, holdings


def _record_row_lineage(
    cfg: Mapping[str, object],
    table: str,
    id_field: str,
    rows: Sequence[Mapping[str, str]],
    lineage: list[dict[str, str]],
    gaps: list[dict[str, str]],
    formula_id: str,
) -> None:
    parameter_set = str(cfg["parameter_set_id"])
    for row in rows:
        record_id = row[id_field]
        lin = _lineage_row(
            target_table=table,
            target_record_id=record_id,
            target_field="*row",
            target_value="created",
            provenance_type="SYNTHETIC",
            source_table="fund_periods",
            source_record_id=stable_id("FPRINT", row["fund_id"], str(cfg["as_of_date"])),
            source_anchor="data/integrated/cell-lineage.csv",
            formula_id=formula_id,
            parameter_set_id=parameter_set,
            imputation_method=formula_id,
            precedence="ADDITIVE_ONLY",
            notes="The generated row complements the source-backed fund and does not replace an extracted row.",
        )
        lineage.append(lin)
        gaps.append(
            _gap_row(
                row["fund_id"],
                table,
                record_id,
                "*row",
                "created",
                "SYNTHETIC",
                lin["lineage_id"],
            )
        )


def _record_target_lineage(
    cfg: Mapping[str, object],
    periods: Sequence[Mapping[str, str]],
    cashflows: Sequence[Mapping[str, str]],
    lineage: list[dict[str, str]],
    gaps: list[dict[str, str]],
    period_map: Mapping[str, Sequence[Mapping[str, str]]],
) -> None:
    parameter_set = str(cfg["parameter_set_id"])
    # A completed cell copied from a fund_master cell this stage imputed is the
    # same imputed value. Read the master lineage already recorded so the copy
    # can carry the label its source carries, instead of taking SYNTHETIC from
    # the row it happens to sit on.
    imputed_master = {
        (row["target_record_id"], row["target_field"]): row
        for row in lineage
        if row["target_table"] == "fund_master"
        and row["provenance_type"] == matrices.resolve(MASTER_PROVENANCE, "carried_imputed_value")
    }
    carried_source = matrices.resolve(PROVENANCE_TABLES, "carried_imputed_value")
    for row in periods:
        # The generated period is completed from the fund's printed periods.
        # Those are period records, so they are cited here as the lineage
        # source and never in `input_observation_ids`, which names only
        # `fact_observation` rows.
        source_period_ids = " | ".join(
            sorted(
                {
                    source.get("fund_period_id", "")
                    for source in period_map.get(row["fund_id"], ())
                    if source.get("fund_period_id", "")
                }
            )
        )
        for field in TARGET_PERIOD_FIELDS:
            value = row.get(field, "")
            if value == "":
                continue
            master_cell = imputed_master.get((row["fund_id"], field))
            carried = master_cell is not None and master_cell["target_value"] == value
            lin = _lineage_row(
                target_table="fund_periods",
                target_record_id=row["fund_period_id"],
                target_field=field,
                target_value=value,
                provenance_type=(
                    matrices.resolve(MASTER_PROVENANCE, "carried_imputed_value")
                    if carried
                    else "SYNTHETIC"
                ),
                source_table=carried_source if carried else "fund_periods",
                source_record_id="" if carried else source_period_ids,
                source_document_id="",
                # An imputed value cites no page, so a copy of one cites none
                # either; it cites the fund_master cell it repeats.
                source_anchor="" if carried else row["source_anchor"],
                formula_id="" if carried else row["formula_id"],
                parameter_set_id=parameter_set,
                imputation_method=(
                    master_cell["imputation_method"]
                    if carried
                    else "DETERMINISTIC_SAME_FUND_COMPLETION_V1"
                ),
                precedence="EXTRACTED_THEN_DERIVED_THEN_SYNTHETIC",
                notes=(
                    "This cell repeats the imputed fund_master cell of the same field; "
                    "no page states it."
                    if carried
                    else "This is a new analytical-period cell; no extracted cell was overwritten."
                ),
            )
            lineage.append(lin)
            gaps.append(
                _gap_row(
                    row["fund_id"],
                    "fund_periods",
                    row["fund_period_id"],
                    field,
                    value,
                    lin["provenance_type"],
                    lin["lineage_id"],
                )
            )
        # A printed grouping the matrix carries no row for leaves every canonical
        # column blank. That is an open gap, not a fund with no grouping, and it
        # is recorded here so the ledger names the printed word to add.
        if row.get("strategy", "") and not any(
            row.get(field, "") for field in CANONICAL_PERIOD_COLUMNS
        ):
            gaps.append(
                _gap_row(
                    row["fund_id"],
                    "fund_periods",
                    row["fund_period_id"],
                    "canonical_strategy",
                    row.get("strategy", ""),
                    "UNRESOLVED",
                    "",
                    open_gap=True,
                )
            )
    for row in cashflows:
        lineage.append(
            _lineage_row(
                target_table="fund_cashflows",
                target_record_id=row["cashflow_id"],
                target_field="*row",
                target_value=row["amount"],
                provenance_type="SYNTHETIC",
                source_table="fund_periods",
                source_record_id=row["source_anchor"].replace("generated from ", ""),
                source_anchor=row["source_anchor"],
                formula_id=matrices.resolve(CASHFLOW_SCHEDULE, "schedule_formula"),
                parameter_set_id=parameter_set,
                imputation_method=matrices.resolve(CASHFLOW_SCHEDULE, "schedule_method"),
                precedence="ADDITIVE_ONLY",
                notes="Generated event complements the source record and does not replace an extracted cash flow.",
            )
        )


def _reconciliation_rows(
    cfg: Mapping[str, object],
    fund_ids: Sequence[str],
    baseline: Mapping[str, Sequence[Mapping[str, str]]],
    master: Sequence[Mapping[str, str]],
    periods: Sequence[Mapping[str, str]],
    cashflows: Sequence[Mapping[str, str]],
    terms: Sequence[Mapping[str, str]],
    holdings: Sequence[Mapping[str, str]],
    target_periods: Sequence[Mapping[str, str]],
    lineage: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    financial_identity_tolerance = float(
        matrices.resolve(RECONCILIATION_POLICY, "financial_identity_tolerance")
    )
    financial_identity_expected = matrices.resolve(
        RECONCILIATION_POLICY, "financial_identity_expected_label"
    )

    def add(
        scope: str,
        record_id: str,
        fund_id: str,
        rule: str,
        passed: bool,
        actual: object,
        expected: object,
        difference: object = "",
        notes: str = "",
    ) -> None:
        rows.append(
            {
                "check_id": stable_id("REC", scope, record_id, rule),
                "scope": scope,
                "record_id": record_id,
                "fund_id": fund_id,
                "rule": rule,
                "status": "PASS" if passed else "FAIL",
                "actual_value": str(actual),
                "expected_value": str(expected),
                "difference": str(difference),
                "notes": notes,
            }
        )

    master_ids = {row.get("fund_id", "") for row in master}
    add("GLOBAL", "FUND_MASTER", "", "IDENTITY_SPINE_COMPLETE", master_ids == set(fund_ids), len(master_ids), len(fund_ids))
    add("GLOBAL", "TARGET_PERIODS", "", "ONE_TARGET_PERIOD_PER_FUND", len(target_periods) == len(fund_ids), len(target_periods), len(fund_ids))
    add(
        "GLOBAL",
        "REAL_IDENTITIES",
        "",
        "NO_STANDALONE_SYNTHETIC_IDS",
        not any(fund_id.startswith("FUND_SYNTH_") for fund_id in master_ids),
        sum(fund_id.startswith("FUND_SYNTH_") for fund_id in master_ids),
        0,
    )
    baseline_period_ids = {row.get("fund_period_id", "") for row in baseline["fund_periods"]}
    final_period_ids = {row.get("fund_period_id", "") for row in periods}
    add("GLOBAL", "FUND_PERIODS", "", "EXTRACTED_PERIOD_ROWS_PRESERVED", baseline_period_ids <= final_period_ids, len(baseline_period_ids & final_period_ids), len(baseline_period_ids))
    baseline_cashflow_ids = {row.get("cashflow_id", "") for row in baseline["fund_cashflows"]}
    final_cashflow_ids = {row.get("cashflow_id", "") for row in cashflows}
    add("GLOBAL", "FUND_CASHFLOWS", "", "EXTRACTED_CASHFLOW_ROWS_PRESERVED", baseline_cashflow_ids <= final_cashflow_ids, len(baseline_cashflow_ids & final_cashflow_ids), len(baseline_cashflow_ids))
    baseline_holding_ids = {row.get("holding_id", "") for row in baseline["fund_holdings"]}
    final_holding_ids = {row.get("holding_id", "") for row in holdings}
    add("GLOBAL", "FUND_HOLDINGS", "", "EXTRACTED_HOLDING_ROWS_PRESERVED", baseline_holding_ids <= final_holding_ids, len(baseline_holding_ids & final_holding_ids), len(baseline_holding_ids))
    completed_terms = [row for row in terms if row.get("synthetic_parameter_set_id") == str(cfg["parameter_set_id"])]
    completed_holdings = [row for row in holdings if row.get("synthetic_parameter_set_id") == str(cfg["parameter_set_id"])]
    add("GLOBAL", "FUND_TERMS", "", "ONE_COMPLETED_TERM_PER_FUND", len(completed_terms) == len(fund_ids), len(completed_terms), len(fund_ids))
    add("GLOBAL", "FUND_HOLDINGS", "", "THREE_COMPLETED_HOLDINGS_PER_FUND", len(completed_holdings) == len(fund_ids) * 3, len(completed_holdings), len(fund_ids) * 3)
    add("GLOBAL", "CELL_LINEAGE", "", "AUGMENTATION_LINEAGE_PRESENT", bool(lineage), len(lineage), ">0")

    for period in target_periods:
        paid = float(period["paid_in_capital_itd"])
        distributions = float(period["distributions_itd"])
        nav = float(period["nav"])
        commitment = float(period["commitment"])
        unfunded = float(period["unfunded_commitment"])
        recallable = float(period["recallable_distributions_itd"])
        dpi = float(period["dpi"])
        rvpi = float(period["rvpi"])
        tvpi = float(period["tvpi"])
        errors = (
            abs(dpi - distributions / paid),
            abs(rvpi - nav / paid),
            abs(tvpi - dpi - rvpi),
            abs(commitment - paid - unfunded + recallable),
        )
        maximum = max(errors)
        add(
            "FUND_PERIOD",
            period["fund_period_id"],
            period["fund_id"],
            "FINANCIAL_IDENTITIES",
            maximum <= financial_identity_tolerance,
            fmt(maximum, 10),
            financial_identity_expected,
            fmt(maximum, 10),
            "DPI, RVPI, TVPI, and commitment identities are checked together.",
        )
    return rows


def _defect_fixture(
    cfg: Mapping[str, object],
    target_periods: Sequence[Mapping[str, str]],
    cashflows: Sequence[Mapping[str, str]],
    master: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    mutations = tuple(
        (row["input_value"], row["field"], row["expected_rule"])
        for row in matrices.rows_in(DEFECTS, "")
        if row["input_value"] != "selection"
    )
    _require(DEFECTS, "selection", "first_twelve_sorted_funds")
    selected = sorted(target_periods, key=lambda row: row["fund_id"])[: len(mutations) * 2]
    damaged: list[dict[str, str]] = []
    injections: list[dict[str, str]] = []
    target_year = date.fromisoformat(str(cfg["as_of_date"])).year
    for index, source in enumerate(selected):
        defect_type, field, rule_id = mutations[index % len(mutations)]
        row = deepcopy(dict(source))
        clean_value = row[field]
        if defect_type == "NEGATIVE_NAV":
            row[field] = fmt(-abs(float(clean_value)) - 1)
        elif defect_type == "FUTURE_VINTAGE":
            row[field] = str(target_year + 1)
        else:
            row[field] = fmt(float(clean_value) + max(abs(float(clean_value)) * 0.25, 100.0), 10 if field in {"tvpi", "dpi"} else 6)
        row["defect_expected"] = "TRUE"
        damaged.append(row)
        injections.append(
            {
                "defect_id": stable_id("DEF", row["fund_id"], defect_type),
                "parameter_set_id": str(cfg["parameter_set_id"]),
                "record_table": "fund_periods",
                "record_id": row["fund_period_id"],
                "fund_id": row["fund_id"],
                "defect_type": defect_type,
                "field_name": field,
                "clean_value": clean_value,
                "injected_value": row[field],
                "expected_rule_id": rule_id,
                "seed": str(cfg["seed"]),
                "notes": "The damaged row is isolated in data/integrated/defect-periods.csv; fund-model data stays clean.",
            }
        )
    quality = run_quality_checks(
        damaged,
        cashflows,
        master,
        run_id="INTEGRATED_DEFECT_QC_V1",
        checked_at="2026-06-30T00:00:00Z",
        tolerances=load_tolerances(QUALITY_CONFIG),
    )
    failed = {
        (row.get("fund_id", ""), row.get("rule_id", ""))
        for row in quality
        if row.get("status") == "FAIL"
    }
    grouped: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in injections:
        grouped[(row["defect_type"], row["expected_rule_id"])].append(
            (row["fund_id"], row["expected_rule_id"]) in failed
        )
    scorecard = []
    for (defect_type, rule_id), outcomes in sorted(grouped.items()):
        detected = sum(outcomes)
        scorecard.append(
            {
                "defect_type": defect_type,
                "expected_rule_id": rule_id,
                "injected": str(len(outcomes)),
                "detected": str(detected),
                "missed": str(len(outcomes) - detected),
                "detection_rate": fmt(detected / len(outcomes), 6),
            }
        )
    return damaged, injections, quality, scorecard


def build() -> dict[str, int]:
    cfg = config()
    headers: dict[str, list[str]] = {}
    tables: dict[str, list[dict[str, str]]] = {}
    for filename in EXTRACTED_FILES:
        header, rows = read_csv(EXTRACTED_DIR / filename)
        key = filename.removesuffix(".csv")
        headers[key] = header
        tables[key] = rows

    fund_ids = _fund_ids(tables)
    registry_header, registry = read_csv(NORMALIZATION_DIR / "entity-ids.csv")
    del registry_header
    names = {
        row["entity_id"]: row["standardized_name"]
        for row in registry
        if row.get("kind") == "fund" and row.get("entity_id")
    }
    attr_header, attr_rows = read_csv(NORMALIZATION_DIR / "fund-attributes-matrix.csv")
    del attr_header
    attributes = {
        row["fund_id"]: {
            field: row.get(field, "")
            if row.get(f"{field}_status", "") in SETTLED_ATTRIBUTE_STATUSES
            else ""
            for field in ("vintage_year", "strategy")
        }
        for row in attr_rows
        if row.get("fund_id")
    }
    _, attribute_change_rows = read_csv(ATTRIBUTE_CHANGES_PATH)
    attribute_sources = _attribute_sources(attribute_change_rows)
    period_attribute_sources = _attribute_sources(attribute_change_rows, "fund_periods")
    evidence = _evidence_by_fund(tables)
    period_map = _latest_periods(tables["fund_periods"])
    parameter_rows, derived = _parameter_rows(cfg, tables["fund_periods"], tables["fund_master"])

    lineage: list[dict[str, str]] = []
    gaps: list[dict[str, str]] = []
    for period in tables["fund_periods"]:
        lineage.extend(
            _carried_canonical_lineage(
                "fund_periods",
                period.get("fund_period_id", ""),
                period,
                period_attribute_sources,
            )
        )
    benchmarks, benchmark_policies, trailing_benchmark_return = _benchmark_rows(cfg, lineage)
    masters = _complete_master(
        cfg,
        fund_ids,
        tables,
        names,
        attributes,
        attribute_sources,
        evidence,
        period_map,
        derived,
        lineage,
        gaps,
    )
    master_by_id = {row["fund_id"]: row for row in masters}
    target_periods = [
        _target_period(
            cfg,
            master_by_id[fund_id],
            period_map.get(fund_id, ()),
            derived,
            trailing_benchmark_return,
        )
        for fund_id in fund_ids
    ]
    generated_cashflows = [
        flow for period in target_periods for flow in _generated_cashflows(cfg, period)
    ]
    final_cashflows = [*tables["fund_cashflows"], *generated_cashflows]
    _populate_calculated_irr(target_periods, final_cashflows)
    _record_target_lineage(cfg, target_periods, generated_cashflows, lineage, gaps, period_map)
    generated_terms, generated_clauses, generated_holdings = _generated_terms_and_holdings(
        cfg, masters, target_periods
    )
    _record_row_lineage(
        cfg,
        "fund_terms",
        "fund_term_id",
        generated_terms,
        lineage,
        gaps,
        "INTEGRATED_FUND_TERMS_V1",
    )
    _record_row_lineage(
        cfg,
        "fund_term_clauses",
        "fund_term_clause_id",
        generated_clauses,
        lineage,
        gaps,
        "INTEGRATED_FUND_CLAUSES_V1",
    )
    _record_row_lineage(
        cfg,
        "fund_holdings",
        "holding_id",
        generated_holdings,
        lineage,
        gaps,
        "INTEGRATED_HOLDINGS_V1",
    )
    final_periods = [*tables["fund_periods"], *target_periods]
    final_terms = [*tables["fund_terms"], *generated_terms]
    final_clauses = [*tables["fund_term_clauses"], *generated_clauses]
    final_holdings = [*tables["fund_holdings"], *generated_holdings]
    reconciliation = _reconciliation_rows(
        cfg,
        fund_ids,
        tables,
        masters,
        final_periods,
        final_cashflows,
        final_terms,
        final_holdings,
        target_periods,
        lineage,
    )
    failures = [row for row in reconciliation if row["status"] == "FAIL"]
    if failures:
        raise IntegrationError(
            "integration reconciliation failed: "
            + "; ".join(f"{row['rule']}:{row['record_id']}" for row in failures[:20])
        )

    damaged, injections, defect_quality, scorecard = _defect_fixture(
        cfg, target_periods, final_cashflows, masters
    )
    if any(row["missed"] != "0" for row in scorecard):
        raise IntegrationError("one or more integrated defects escaped detection")

    counts = {
        "fund_master.csv": write_csv(CSV_DIR / "fund_master.csv", headers["fund_master"], masters),
        "fund_periods.csv": write_csv(CSV_DIR / "fund_periods.csv", headers["fund_periods"], final_periods),
        "fund_cashflows.csv": write_csv(CSV_DIR / "fund_cashflows.csv", headers["fund_cashflows"], final_cashflows),
        "fund_terms.csv": write_csv(CSV_DIR / "fund_terms.csv", headers["fund_terms"], final_terms),
        "fund_term_clauses.csv": write_csv(CSV_DIR / "fund_term_clauses.csv", headers["fund_term_clauses"], final_clauses),
        "fund_holdings.csv": write_csv(CSV_DIR / "fund_holdings.csv", headers["fund_holdings"], final_holdings),
        "benchmark_returns.csv": write_csv(CSV_DIR / "benchmark_returns.csv", read_csv(CSV_DIR / "benchmark_returns.csv")[0], benchmarks),
        "synthetic_parameters.csv": write_csv(CSV_DIR / "synthetic_parameters.csv", read_csv(CSV_DIR / "synthetic_parameters.csv")[0], parameter_rows),
        "defect_injections.csv": write_csv(CSV_DIR / "defect_injections.csv", read_csv(CSV_DIR / "defect_injections.csv")[0], injections),
        "gap-ledger.csv": write_csv(INTEGRATED_DIR / "gap-ledger.csv", GAP_COLUMNS, gaps),
        "cell-lineage.csv": write_csv(INTEGRATED_DIR / "cell-lineage.csv", LINEAGE_COLUMNS, lineage),
        "reconciliation-results.csv": write_csv(INTEGRATED_DIR / "reconciliation-results.csv", RECONCILIATION_COLUMNS, reconciliation),
        "benchmark-policy.csv": write_csv(INTEGRATED_DIR / "benchmark-policy.csv", BENCHMARK_POLICY_COLUMNS, benchmark_policies),
        "defect-periods.csv": write_csv(INTEGRATED_DIR / "defect-periods.csv", headers["fund_periods"], damaged),
        "defect-quality-results.csv": write_csv(INTEGRATED_DIR / "defect-quality-results.csv", read_csv(CSV_DIR / "quality_results.csv")[0], defect_quality),
        "detection-scorecard.csv": write_csv(INTEGRATED_DIR / "detection-scorecard.csv", SCORECARD_COLUMNS, scorecard),
    }
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-only",
        action="store_true",
        help="Freeze the promoted extracted tables without augmenting them.",
    )
    args = parser.parse_args(argv)
    counts = snapshot_extracted() if args.snapshot_only else build()
    print(
        "PASS: "
        + ("extracted fund-level snapshot" if args.snapshot_only else "integrated same-fund universe")
        + "; "
        + ", ".join(f"{name}={count:,}" for name, count in counts.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
