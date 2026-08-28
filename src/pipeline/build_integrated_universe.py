"""Keep extracted fund tables, then fill the same fund IDs.

The extracted snapshot is not edited in place. The integrated layer keeps every extracted
row, creates one complete demonstration period for every extracted fund ID, and
records each added cell in a gap ledger and a cell-lineage ledger.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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
    load_tolerances,
    run_quality_checks,
    write_results,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV_DIR = PROJECT_ROOT / "data" / "csv"
EXTRACTED_DIR = PROJECT_ROOT / "data" / "extracted" / "fund-level"
INTEGRATED_DIR = PROJECT_ROOT / "data" / "integrated"
NORMALIZATION_DIR = PROJECT_ROOT / "data" / "normalization"
PUBLIC_MARKET_DIR = PROJECT_ROOT / "data" / "public_markets" / "staging"
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

TARGET_PERIOD_FIELDS = (
    "commitment",
    "paid_in_capital_itd",
    "distributions_itd",
    "nav",
    "unfunded_commitment",
    "recallable_distributions_itd",
    "dpi",
    "rvpi",
    "tvpi",
    "calculated_irr",
    "beginning_nav",
    "contributions_period",
    "distributions_period",
    "realized_gain_period",
    "unrealized_gain_period",
    "net_income_period",
    "management_fee_period",
    "other_expenses_period",
    "ending_nav",
    "period_return",
    "benchmark_return",
    "fund_size",
    "vintage_year",
    "strategy",
    "sub_strategy",
)


class IntegrationError(RuntimeError):
    """Raised when extracted facts would be lost or integrated math fails."""


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise IntegrationError(f"CSV has no header: {path}")
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
            writer.writerow({column: row.get(column, "") for column in columns})
    return len(materialized)


def stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20].upper()
    return f"{prefix}_{digest}"


def number(value: object) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    return result if result == result and abs(result) != float("inf") else None


def fmt(value: float | Decimal, places: int = 6) -> str:
    quantum = Decimal(1).scaleb(-places)
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    rendered = decimal_value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    return format(rendered, "f")


def parse_date(value: object) -> date | None:
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
    names = (
        "fund_master",
        "document_fund_map",
        "fund_observations",
        "fund_cashflows",
        "fund_periods",
        "fund_terms",
        "fund_term_clauses",
        "fund_holdings",
    )
    return sorted(
        {
            row.get("fund_id", "")
            for table in names
            for row in tables.get(table, ())
            if row.get("fund_id", "")
        }
    )


def _record_id(table: str, row: Mapping[str, str]) -> str:
    fields = {
        "fund_master": "fund_id",
        "document_fund_map": "document_fund_map_id",
        "fund_observations": "observation_id",
        "fund_cashflows": "cashflow_id",
        "fund_periods": "fund_period_id",
        "fund_terms": "fund_term_id",
        "fund_term_clauses": "fund_term_clause_id",
        "fund_holdings": "holding_id",
    }
    return row.get(fields[table], "")


def _evidence_by_fund(
    tables: Mapping[str, Sequence[Mapping[str, str]]]
) -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    order = (
        "document_fund_map",
        "fund_observations",
        "fund_master",
        "fund_periods",
        "fund_holdings",
        "fund_cashflows",
        "fund_terms",
        "fund_term_clauses",
    )
    for table in order:
        for row in tables.get(table, ()):
            fund_id = row.get("fund_id", "")
            if not fund_id or fund_id in evidence:
                continue
            evidence[fund_id] = {
                "source_table": table,
                "source_record_id": _record_id(table, row),
                "source_document_id": row.get("source_document_id", "")
                or row.get("file_id", ""),
                "source_page": row.get("source_page", ""),
                "source_anchor": row.get("source_anchor", "")
                or row.get("source_quote", ""),
            }
    return evidence


def _latest_periods(
    periods: Sequence[Mapping[str, str]],
) -> dict[str, list[Mapping[str, str]]]:
    by_fund: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in periods:
        if row.get("fund_id", ""):
            by_fund[row["fund_id"]].append(row)
    for rows in by_fund.values():
        rows.sort(key=lambda row: (row.get("as_of_date", ""), row.get("fund_period_id", "")))
    return by_fund


def _first_value(rows: Sequence[Mapping[str, str]], field: str) -> tuple[str, Mapping[str, str] | None]:
    for row in reversed(rows):
        value = row.get(field, "")
        if value:
            return value, row
    return "", None


def _strategy_from_name(name: str, fallback: str) -> tuple[str, str]:
    lowered = name.lower()
    rules = (
        (("venture", "seed", "angel"), ("Venture Capital", "Venture Capital")),
        (("real estate", "realty", "property"), ("Real Estate", "Diversified Real Estate")),
        (("infrastructure",), ("Infrastructure", "Infrastructure")),
        (("credit", "debt", "mezzanine", "lending"), ("Private Credit", "Direct Lending")),
        (("secondary",), ("Secondary Investments", "Secondaries")),
        (("energy", "resource", "timber", "agriculture", "water"), ("Natural Resources", "Natural Resources")),
        (("growth",), ("Growth Equity", "Growth Equity")),
        (("buyout", "equity partners"), ("Buyout", "Buyout")),
    )
    for keywords, result in rules:
        if any(keyword in lowered for keyword in keywords):
            return result
    return fallback, "Multi-Strategy"


def _unit_interval(seed: int, *parts: object) -> float:
    digest = hashlib.sha256("|".join(map(str, (seed, *parts))).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)


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


def _gap_row(
    fund_id: str,
    table: str,
    record_id: str,
    field: str,
    value: object,
    resolution_type: str,
    lineage_id: str,
) -> dict[str, str]:
    return {
        "gap_id": stable_id("GAP", table, record_id, field),
        "fund_id": fund_id,
        "target_table": table,
        "target_record_id": record_id,
        "field_name": field,
        "original_value": "",
        "resolution_value": str(value),
        "resolution_type": resolution_type,
        "lineage_id": lineage_id,
        "status": "RESOLVED",
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
    for row in (*master_rows, *periods):
        value = number(row.get("fund_size"))
        if value is not None and value > 0:
            observed_size.append(value)
            inputs["fund_size"].append(
                row.get("fund_period_id", "") or row.get("fund_id", "")
            )
    for row in periods:
        paid = number(row.get("paid_in_capital_itd"))
        commitment = number(row.get("commitment"))
        if paid is not None and paid > 0 and commitment is not None and commitment > 0:
            ratios["paid_in_ratio"].append(min(paid / commitment, 1.25))
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
        "dpi_median": statistics.median(ratios["dpi"]) if ratios["dpi"] else 0.55,
        "rvpi_median": statistics.median(ratios["rvpi"]) if ratios["rvpi"] else 0.75,
        "paid_in_ratio_median": statistics.median(ratios["paid_in_ratio"])
        if ratios["paid_in_ratio"]
        else 0.85,
    }
    rows: list[dict[str, str]] = []
    for name, value in derived.items():
        key = name.replace("_median", "")
        record_ids = inputs.get(key, [])
        provenance = "DERIVED" if record_ids else "ASSUMED"
        rows.append(
            {
                "parameter_id": stable_id("PAR", parameter_set, name),
                "parameter_set_id": parameter_set,
                "strategy": "ALL",
                "sub_strategy": "ALL",
                "parameter_name": name,
                "value_numeric": fmt(value, 10),
                "value_text": "",
                "unit": "currency" if name == "fund_size_median" else "ratio",
                "provenance_type": provenance,
                "source_document_id": "",
                "source_page": "",
                "source_anchor": "data/extracted/fund-level/fund_periods.csv" if record_ids else "config/integrated_completion.yml",
                "formula_id": "MEDIAN_OF_POSITIVE_EXTRACTED_VALUES_V1" if record_ids else "",
                "input_record_ids": " | ".join(sorted(set(record_ids))),
                "assumption_basis": (
                    "Median of eligible source-backed values."
                    if record_ids
                    else "No eligible extracted values exist; the declared configuration fallback is used."
                ),
                "adjudication_status": "APPROVED_FOR_DEMO",
                "active": "TRUE",
            }
        )
    assumed = (
        ("seed", str(cfg["seed"]), "integer"),
        ("as_of_date", str(cfg["as_of_date"]), "date"),
        ("benchmark_id", str(cfg["benchmark_id"]), "identifier"),
        ("strategy_fallback", str(cfg["strategy_fallback"]), "text"),
        ("currency_fallback", str(cfg["currency_fallback"]), "currency"),
        ("fund_size_fallback", str(cfg["fund_size_fallback"]), "currency"),
    )
    for name, value, unit in assumed:
        numeric = value if name in {"seed", "fund_size_fallback"} else ""
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
                "adjudication_status": "APPROVED_FOR_DEMO",
                "active": "TRUE",
            }
        )
    return rows, derived


def _benchmark_rows(
    cfg: Mapping[str, object],
    lineage: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, str], float]:
    benchmark_id = str(cfg["benchmark_id"])
    master_header, masters = read_csv(PUBLIC_MARKET_DIR / "benchmark_master_candidates.csv")
    del master_header
    return_header, candidates = read_csv(PUBLIC_MARKET_DIR / "benchmark_return_candidates.csv")
    del return_header
    master = next((row for row in masters if row.get("benchmark_id") == benchmark_id), None)
    if master is None:
        raise IntegrationError(f"benchmark candidate is missing: {benchmark_id}")
    policy = cfg.get("benchmark_policy", {})
    if not isinstance(policy, dict):
        raise IntegrationError("benchmark_policy must be a mapping")
    rows: list[dict[str, str]] = []
    recent_growth = 1.0
    target = date.fromisoformat(str(cfg["as_of_date"]))
    trailing_start = target - timedelta(days=365)
    for source in candidates:
        if source.get("benchmark_id") != benchmark_id:
            continue
        return_date = parse_date(source.get("return_date"))
        value = number(source.get("return_value"))
        if return_date is None or value is None:
            continue
        row = {
            "benchmark_return_id": source["benchmark_return_id"],
            "benchmark_id": benchmark_id,
            "benchmark_name": master.get("benchmark_name", ""),
            "return_date": return_date.isoformat(),
            "periodicity": source.get("periodicity", "DAILY").upper(),
            "return_value": source.get("return_value", ""),
            "currency": source.get("currency", "") or master.get("currency", ""),
            "provenance_type": "DERIVED",
            "source_document_id": master.get("source_file_id", ""),
            "source_page": "",
            "source_anchor": (
                f"data/public_markets/staging/benchmark_return_candidates.csv:{source['benchmark_return_id']}; "
                f"rights_status={policy.get('rights_status', '')}; use_status={policy.get('use_status', '')}"
            ),
            "synthetic_parameter_set_id": "PUBLIC_PROXY_DEMONSTRATION_ONLY_V1",
            "record_status": "ACTIVE",
        }
        rows.append(row)
        if trailing_start < return_date <= target:
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
                formula_id="PUBLIC_MARKET_CANDIDATE_PROMOTION_V1",
                precedence="PUBLIC_DEMO_PROXY",
                notes="Candidate return is unchanged; policy restricts it to demonstration use.",
            )
        )
    if not rows:
        raise IntegrationError(f"benchmark has zero usable return rows: {benchmark_id}")
    rows.sort(key=lambda row: (row["return_date"], row["benchmark_return_id"]))
    policy_row = {
        "benchmark_id": benchmark_id,
        "benchmark_name": master.get("benchmark_name", ""),
        "rights_status": str(policy.get("rights_status", "")),
        "use_status": str(policy.get("use_status", "")),
        "source_file_id": master.get("source_file_id", ""),
        "first_observation_date": rows[0]["return_date"],
        "last_observation_date": rows[-1]["return_date"],
        "observation_count": str(len(rows)),
        "note": str(policy.get("note", "")),
    }
    return rows, policy_row, recent_growth - 1.0


def _complete_master(
    cfg: Mapping[str, object],
    fund_ids: Sequence[str],
    tables: Mapping[str, Sequence[Mapping[str, str]]],
    names: Mapping[str, str],
    attributes: Mapping[str, Mapping[str, str]],
    evidence: Mapping[str, Mapping[str, str]],
    period_map: Mapping[str, Sequence[Mapping[str, str]]],
    derived: Mapping[str, float],
    lineage: list[dict[str, str]],
    gaps: list[dict[str, str]],
) -> list[dict[str, str]]:
    seed = int(cfg["seed"])
    parameter_set = str(cfg["parameter_set_id"])
    existing = {row["fund_id"]: dict(row) for row in tables["fund_master"]}
    maps_by_fund: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in tables["document_fund_map"]:
        maps_by_fund[row.get("fund_id", "")].append(row)
    output: list[dict[str, str]] = []
    for fund_id in fund_ids:
        name = names.get(fund_id, "") or existing.get(fund_id, {}).get("fund_name", "")
        if not name:
            raise IntegrationError(f"identity registry lacks a name for {fund_id}")
        is_new = fund_id not in existing
        source = evidence.get(fund_id, {})
        row = dict(existing.get(fund_id, {}))
        if is_new:
            row.update(
                {
                    "fund_id": fund_id,
                    "fund_name": name,
                    "legal_name": name,
                    "provenance_type": "EXTRACTED",
                    "source_document_id": source.get("source_document_id", ""),
                    "source_page": source.get("source_page", ""),
                    "source_anchor": source.get("source_anchor", ""),
                    "synthetic_parameter_set_id": "",
                    "record_status": "ACTIVE",
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
                    formula_id="" if field == "fund_name" else "LEGAL_NAME_FROM_CANONICAL_FUND_NAME_V1",
                    precedence="SOURCE_IDENTITY",
                    notes="Identity came from the normalized source-backed fund registry.",
                )
                lineage.append(lin)
                gaps.append(_gap_row(fund_id, "fund_master", fund_id, field, row[field], lin["provenance_type"], lin["lineage_id"]))

        period_rows = list(period_map.get(fund_id, ()))
        attr = attributes.get(fund_id, {})
        manager_name = next(
            (item.get("fund_manager_raw", "") for item in maps_by_fund.get(fund_id, ()) if item.get("fund_manager_raw", "")),
            "",
        )
        strategy_value = row.get("strategy", "") or attr.get("strategy", "")
        strategy_source: Mapping[str, str] | None = None
        if not strategy_value:
            strategy_value, strategy_source = _first_value(period_rows, "strategy")
        inferred_strategy, inferred_sub = _strategy_from_name(name, str(cfg["strategy_fallback"]))
        if not strategy_value:
            strategy_value = inferred_strategy
        sub_strategy = row.get("sub_strategy", "") or inferred_sub

        vintage_value = row.get("vintage_year", "") or attr.get("vintage_year", "")
        vintage_source: Mapping[str, str] | None = None
        if not vintage_value:
            vintage_value, vintage_source = _first_value(period_rows, "vintage_year")
        if not vintage_value:
            vintage_value = str(2000 + int(_unit_interval(seed, fund_id, "vintage") * 25))

        size_value = row.get("fund_size", "")
        size_source: Mapping[str, str] | None = None
        if not size_value:
            size_value, size_source = _first_value(period_rows, "fund_size")
        if not size_value:
            scale = 0.6 + 1.8 * _unit_interval(seed, fund_id, "fund_size")
            size_value = fmt(max(float(derived["fund_size_median"]), float(cfg["fund_size_fallback"])) * scale)

        candidates = {
            "legal_name": row.get("legal_name", "") or name,
            "fund_manager_name": row.get("fund_manager_name", "") or manager_name,
            "strategy": strategy_value,
            "sub_strategy": sub_strategy,
            "vintage_year": vintage_value,
            "base_currency": row.get("base_currency", "") or str(cfg["currency_fallback"]),
            "fund_size": size_value,
            "fund_size_currency": row.get("fund_size_currency", "") or str(cfg["currency_fallback"]),
            "fund_status": row.get("fund_status", "") or "ACTIVE_OR_UNKNOWN",
        }
        for field, value in candidates.items():
            if row.get(field, "") or not value:
                continue
            propagated = (
                field in {"strategy", "vintage_year"}
                and (attr.get(field, "") or (strategy_source if field == "strategy" else vintage_source))
            ) or (field == "fund_size" and size_source is not None) or (
                field == "fund_manager_name" and bool(manager_name)
            )
            provenance = "DERIVED" if propagated or field in {"legal_name", "sub_strategy"} else "IMPUTED"
            row[field] = value
            source_row = strategy_source if field == "strategy" else vintage_source if field == "vintage_year" else size_source if field == "fund_size" else None
            lin = _lineage_row(
                target_table="fund_master",
                target_record_id=fund_id,
                target_field=field,
                target_value=value,
                provenance_type=provenance,
                source_table="fund_periods" if source_row else "fund_attributes_matrix" if attr.get(field, "") else "document_fund_map" if field == "fund_manager_name" and manager_name else "",
                source_record_id=(source_row or {}).get("fund_period_id", ""),
                source_document_id=(source_row or {}).get("source_document_id", "") or source.get("source_document_id", ""),
                source_anchor=(source_row or {}).get("source_anchor", "") or source.get("source_anchor", ""),
                formula_id="FUND_CONSTANT_PROPAGATION_V1" if provenance == "DERIVED" else "",
                parameter_set_id=parameter_set if provenance == "IMPUTED" else "",
                imputation_method="DETERMINISTIC_NAME_AND_EXTRACTED_MEDIAN_V1" if provenance == "IMPUTED" else "",
                precedence="EXTRACTED_THEN_DERIVED_THEN_IMPUTED",
                notes="Only a blank fund-model cell was filled; every nonblank extracted cell was retained.",
            )
            lineage.append(lin)
            gaps.append(_gap_row(fund_id, "fund_master", fund_id, field, value, provenance, lin["lineage_id"]))
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
    commitment_anchor = _performance_anchor(source_rows, "commitment")
    commitment = max(commitment_anchor or fund_size, 100_000.0)
    paid_anchor = _performance_anchor(source_rows, "paid_in_capital_itd")
    paid_ratio = min(0.98, max(0.35, float(derived["paid_in_ratio_median"]) + 0.015 * (age - 8) + jitter * 0.05))
    paid_in = paid_anchor if paid_anchor and paid_anchor <= commitment else commitment * paid_ratio
    if paid_in > commitment:
        commitment = paid_in / 0.95

    dpi = _performance_anchor(source_rows, "dpi", 10)
    rvpi = _performance_anchor(source_rows, "rvpi", 10)
    if dpi is None:
        distributions_anchor = _performance_anchor(source_rows, "distributions_itd")
        anchor_paid = _performance_anchor(source_rows, "paid_in_capital_itd")
        if distributions_anchor is not None and anchor_paid and anchor_paid > 0:
            dpi = distributions_anchor / anchor_paid
    if rvpi is None:
        nav_anchor = _performance_anchor(source_rows, "nav")
        anchor_paid = _performance_anchor(source_rows, "paid_in_capital_itd")
        if nav_anchor is not None and anchor_paid and anchor_paid > 0:
            rvpi = nav_anchor / anchor_paid
    tvpi_anchor = _performance_anchor(source_rows, "tvpi", 10)
    if dpi is None and rvpi is None and tvpi_anchor is not None:
        maturity_share = min(max(age / 15.0, 0.15), 0.9)
        dpi = tvpi_anchor * maturity_share
        rvpi = max(tvpi_anchor - dpi, 0.0)
    dpi = max(dpi if dpi is not None else float(derived["dpi_median"]) + 0.045 * (age - 8) + jitter * 0.12, 0.01)
    rvpi = max(rvpi if rvpi is not None else float(derived["rvpi_median"]) - 0.04 * (age - 8) - jitter * 0.08, 0.05)
    dpi = min(dpi, 4.0)
    rvpi = min(rvpi, 4.0)
    distributions = paid_in * dpi
    nav = paid_in * rvpi
    unfunded = commitment - paid_in

    beginning_nav = nav * 0.92
    contributions_period = paid_in * 0.03
    distributions_period = distributions * 0.04
    unrealized_gain = nav * 0.025
    net_income = beginning_nav * 0.012
    management_fee = commitment * 0.003
    other_expenses = commitment * 0.0005
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
        "period_start_date": f"{target_year}-01-01",
        "period_end_date": target,
        "effective_date": "",
        "perspective": "fund_total",
        "currency": master.get("base_currency", "") or str(cfg["currency_fallback"]),
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
        "provenance_type": "SYNTHETIC",
        "source_document_id": "",
        "source_page": "",
        "source_anchor": "data/integrated/cell-lineage.csv",
        "formula_id": "INTEGRATED_PERIOD_COMPLETION_V1",
        # No printed cell feeds this row directly; the printed periods it is
        # completed from are cited in data/integrated/cell-lineage.csv.
        "input_observation_ids": "",
        "synthetic_parameter_set_id": str(cfg["parameter_set_id"]),
        "defect_expected": "FALSE",
        "record_status": "ACTIVE",
    }


def _cashflow_dates(vintage: int, target: date) -> list[date]:
    start = max(date(vintage, 1, 15), date(1993, 2, 1))
    if start >= target - timedelta(days=730):
        start = target - timedelta(days=730)
    span = (target - start).days
    fractions = (0.05, 0.18, 0.31, 0.44, 0.60, 0.76, 0.90)
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
    call_fractions = (Decimal("0.30"), Decimal("0.30"), Decimal("0.25"), Decimal("0.15"))
    distribution_fractions = (Decimal("0.25"), Decimal("0.35"), Decimal("0.40"))
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
    by_fund: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in cashflows:
        by_fund[row.get("fund_id", "")].append(row)
    for period in target_periods:
        target = date.fromisoformat(period["as_of_date"])
        dated: list[tuple[date, float]] = []
        for flow in by_fund[period["fund_id"]]:
            flow_date = parse_date(flow.get("cashflow_date"))
            amount = number(flow.get("amount_base_currency"))
            if amount is None:
                amount = number(flow.get("amount"))
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
    sectors = ("Technology", "Healthcare", "Industrials")
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
                "management_fee_basis": "committed_capital",
                "carry_rate": fmt(carry_rate, 10),
                "hurdle_rate": fmt(hurdle_rate, 10),
                "catch_up_rate": fmt(1.0, 10),
                "catch_up_present": "TRUE",
                "waterfall_type": "whole_fund",
                "fund_term_years": fmt(10, 4),
                "extension_years": fmt(2, 4),
                "preferred_return_compounding": "annual",
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
        fair_values = [
            (nav * Decimal("0.45")).quantize(Decimal("0.000001")),
            (nav * Decimal("0.35")).quantize(Decimal("0.000001")),
        ]
        fair_values.append(nav - sum(fair_values, Decimal(0)))
        for index, (sector, fair_value) in enumerate(zip(sectors, fair_values, strict=True), start=1):
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
                    "security_type": "Debt" if master.get("strategy") == "Private Credit" else "Equity",
                    "sector": sector,
                    "geography": "United States",
                    "currency": period["currency"],
                    "cost": fmt(cost),
                    "fair_value": fmt(fair_value),
                    "principal_amount": "",
                    "interest_rate": "",
                    "spread_bps": "",
                    "maturity_date": "",
                    "ownership_percent": fmt(0.10 + 0.05 * index, 10),
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
            lin = _lineage_row(
                target_table="fund_periods",
                target_record_id=row["fund_period_id"],
                target_field=field,
                target_value=value,
                provenance_type="SYNTHETIC",
                source_table="fund_periods",
                source_record_id=source_period_ids,
                source_document_id="",
                source_anchor=row["source_anchor"],
                formula_id=row["formula_id"],
                parameter_set_id=parameter_set,
                imputation_method="DETERMINISTIC_SAME_FUND_COMPLETION_V1",
                precedence="EXTRACTED_THEN_DERIVED_THEN_SYNTHETIC",
                notes="This is a new analytical-period cell; no extracted cell was overwritten.",
            )
            lineage.append(lin)
            gaps.append(
                _gap_row(
                    row["fund_id"],
                    "fund_periods",
                    row["fund_period_id"],
                    field,
                    value,
                    "SYNTHETIC",
                    lin["lineage_id"],
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
                formula_id="INTEGRATED_CASHFLOW_SCHEDULE_V1",
                parameter_set_id=parameter_set,
                imputation_method="DETERMINISTIC_SEVEN_EVENT_SCHEDULE_V1",
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
            maximum <= 0.005,
            fmt(maximum, 10),
            "<=0.005",
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
    mutations = (
        ("WRONG_TVPI", "tvpi", "R02_TVPI_COMPONENTS"),
        ("NEGATIVE_NAV", "nav", "R01_NONNEGATIVE_BALANCES"),
        ("FUTURE_VINTAGE", "vintage_year", "R09_VINTAGE_DATE"),
        ("COMMITMENT_BREAK", "commitment", "R06_COMMITMENT_RECONCILIATION"),
        ("NAV_ROLLFORWARD_BREAK", "ending_nav", "R07_NAV_ROLLFORWARD"),
        ("WRONG_DPI", "dpi", "R03_DPI_RECOMPUTE"),
    )
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
    evidence = _evidence_by_fund(tables)
    period_map = _latest_periods(tables["fund_periods"])
    parameter_rows, derived = _parameter_rows(cfg, tables["fund_periods"], tables["fund_master"])

    lineage: list[dict[str, str]] = []
    gaps: list[dict[str, str]] = []
    benchmarks, benchmark_policy, trailing_benchmark_return = _benchmark_rows(cfg, lineage)
    masters = _complete_master(
        cfg,
        fund_ids,
        tables,
        names,
        attributes,
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
        "benchmark-policy.csv": write_csv(INTEGRATED_DIR / "benchmark-policy.csv", BENCHMARK_POLICY_COLUMNS, [benchmark_policy]),
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
