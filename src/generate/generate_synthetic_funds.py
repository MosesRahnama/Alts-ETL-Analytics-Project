"""Generate a deterministic, mathematically reconciled synthetic fund universe.

Production runs require source-backed, adjudicated calibration inputs. The
``--allow-assumed-only`` switch is a declared demo exception and emits every
built-in assumption to the parameter output as a visible row.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.common.finance import xirr as shared_xirr, xnpv as shared_xnpv


FUND_MODEL_FILES = (
    "manager_master.csv",
    "manager_observations.csv",
    "fund_master.csv",
    "fund_periods.csv",
    "fund_cashflows.csv",
    "fund_terms.csv",
    "fund_term_clauses.csv",
    "fund_holdings.csv",
    "fund_observations.csv",
    "benchmark_returns.csv",
    "portfolio_allocations.csv",
    "synthetic_parameters.csv",
    "defect_injections.csv",
)

REQUIRED_PARAMETERS = (
    "strategy_weight",
    "fund_size_mean",
    "fund_size_cv",
    "commitment_ratio",
    "paid_in_ratio",
    "dpi_mean",
    "dpi_sd",
    "rvpi_mean",
    "rvpi_sd",
    "management_fee_rate",
    "carry_rate",
    "hurdle_rate",
    "fund_term_years",
    "extension_years",
    "vintage_min",
    "vintage_max",
    "geography",
    "domicile",
    "sub_strategy",
)

NUMERIC_PARAMETERS = set(REQUIRED_PARAMETERS) - {
    "geography",
    "domicile",
    "sub_strategy",
}

# strategy, sub_strategy, weight, fund size mean, and the multiples a fully
# realized fund of this strategy lands on: dpi_mean plus rvpi_mean is the
# terminal TVPI, and the standard deviations set its dispersion.
DEFAULT_STRATEGIES: tuple[
    tuple[str, str, float, float, float, float, float, float], ...
] = (
    ("buyout", "middle_market", 0.22, 650.0, 1.68, 0.17, 0.34, 0.11),
    ("growth", "growth_equity", 0.12, 425.0, 1.68, 0.22, 0.46, 0.14),
    ("venture", "early_stage", 0.13, 250.0, 1.95, 0.35, 0.95, 0.35),
    ("private_credit", "direct_lending", 0.16, 500.0, 1.34, 0.11, 0.16, 0.05),
    ("real_estate", "value_add", 0.13, 575.0, 1.44, 0.16, 0.30, 0.10),
    ("infrastructure", "core_plus", 0.10, 900.0, 1.38, 0.17, 0.23, 0.08),
    ("secondaries", "lp_led", 0.08, 800.0, 1.40, 0.15, 0.21, 0.07),
    ("fund_of_funds", "diversified", 0.06, 700.0, 1.44, 0.16, 0.24, 0.08),
)

ALLOWED_DEFECTS = (
    "tvpi_component_mismatch",
    "dpi_recompute_mismatch",
    "rvpi_recompute_mismatch",
    "commitment_reconciliation_mismatch",
    "nav_rollforward_mismatch",
    "irr_recompute_mismatch",
    "cashflow_sign_error",
    "impossible_vintage",
    "missing_fund_name",
    "duplicate_cashflow",
    "currency_mismatch",
    "synthetic_real_identity_collision",
)

EXPECTED_RULES = {
    "tvpi_component_mismatch": "R02_TVPI_COMPONENTS",
    "dpi_recompute_mismatch": "R03_DPI_RECOMPUTE",
    "rvpi_recompute_mismatch": "R04_RVPI_RECOMPUTE",
    "commitment_reconciliation_mismatch": "R06_COMMITMENT_RECONCILIATION",
    "nav_rollforward_mismatch": "R07_NAV_ROLLFORWARD",
    "irr_recompute_mismatch": "R08_XIRR_RECOMPUTE",
    "cashflow_sign_error": "R15_CASHFLOW_SIGN_CONVENTION",
    "impossible_vintage": "R09_VINTAGE_DATE",
    "missing_fund_name": "R12_SYNTHETIC_IDENTITY_SEPARATION",
    "duplicate_cashflow": "R13_DUPLICATE_CASHFLOW",
    "currency_mismatch": "R14_CURRENCY_CONSISTENCY",
    "synthetic_real_identity_collision": "R12_SYNTHETIC_IDENTITY_SEPARATION",
}

SECTORS = (
    "Business Services",
    "Healthcare",
    "Software",
    "Industrials",
    "Consumer",
    "Energy Transition",
)

SECURITY_TYPES = ("Equity", "Preferred Equity", "Senior Debt", "Unitranche")

QUARTER_END_MONTH_DAY = ((3, 31), (6, 30), (9, 30), (12, 31))

# Funds hold their first close inside a quarter, so no capital event ever lands
# on a reporting date and collapses into the terminal NAV of an IRR.
CLOSE_MONTH_DAY = ((2, 15), (5, 15), (8, 15), (11, 15))

# benchmark_id, display name, quarterly drift, quarterly standard deviation
BENCHMARK_SERIES: tuple[tuple[str, str, float, float], ...] = (
    ("BM_SYNTH_PUBLIC_EQUITY", "Synthetic Public Equity Benchmark", 0.0225, 0.0780),
    ("BM_SYNTH_SMALL_CAP_EQUITY", "Synthetic Small Cap Equity Benchmark", 0.0240, 0.1020),
    ("BM_SYNTH_HIGH_YIELD_CREDIT", "Synthetic High Yield Credit Benchmark", 0.0150, 0.0450),
    ("BM_SYNTH_LISTED_REAL_ESTATE", "Synthetic Listed Real Estate Benchmark", 0.0175, 0.0860),
    ("BM_SYNTH_LISTED_INFRASTRUCTURE", "Synthetic Listed Infrastructure Benchmark", 0.0190, 0.0620),
)

STRATEGY_BENCHMARK = {
    "buyout": "BM_SYNTH_PUBLIC_EQUITY",
    "growth": "BM_SYNTH_SMALL_CAP_EQUITY",
    "venture": "BM_SYNTH_SMALL_CAP_EQUITY",
    "private_credit": "BM_SYNTH_HIGH_YIELD_CREDIT",
    "real_estate": "BM_SYNTH_LISTED_REAL_ESTATE",
    "infrastructure": "BM_SYNTH_LISTED_INFRASTRUCTURE",
    "secondaries": "BM_SYNTH_PUBLIC_EQUITY",
    "fund_of_funds": "BM_SYNTH_PUBLIC_EQUITY",
}

# Annual income yield carried on NAV; strategies outside the map earn almost none.
STRATEGY_INCOME_YIELD = {
    "private_credit": 0.0850,
    "real_estate": 0.0350,
    "infrastructure": 0.0450,
    "secondaries": 0.0100,
}

# Reporting currency mix. A fund reports every fact in its own currency.
FUND_CURRENCY_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("USD", 0.78),
    ("EUR", 0.12),
    ("GBP", 0.07),
    ("CAD", 0.03),
)

FX_TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.74}

PORTFOLIO_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("PORTFOLIO_SYNTH_EQUAL_WEIGHT", "equal_weight"),
    ("PORTFOLIO_SYNTH_STRATEGY_TILT", "strategy_tilt"),
    ("PORTFOLIO_SYNTH_LIQUIDITY_TILT", "liquidity_tilt"),
)

STRATEGY_VOLATILITY = {
    "buyout": 0.18,
    "growth": 0.24,
    "venture": 0.34,
    "private_credit": 0.10,
    "real_estate": 0.16,
    "infrastructure": 0.13,
    "secondaries": 0.15,
    "fund_of_funds": 0.14,
}

STRATEGY_LIQUIDITY = {
    "buyout": 0.35,
    "growth": 0.30,
    "venture": 0.20,
    "private_credit": 0.65,
    "real_estate": 0.32,
    "infrastructure": 0.38,
    "secondaries": 0.70,
    "fund_of_funds": 0.45,
}

# Share of a fund's economics held by each named limited partner, when a fund
# carries reported positions. The remainder stays unnamed.
LP_POSITION_SHARES = (0.14, 0.09)
SHARE_CLASS_SHARES = (("Class A", 0.62), ("Class B", 0.38))


class GenerationError(ValueError):
    """Raised when a generation gate or data contract fails."""


@dataclass(frozen=True)
class GenerationConfig:
    seed: int
    target_fund_count: int
    minimum_fund_count: int
    base_currency: str
    as_of_date: date
    fund_id_prefix: str
    defects_enabled: bool
    defect_seed_offset: int
    defect_target_rate: float
    allowed_defects: tuple[str, ...]


def _yaml_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value[0:1] in {'"', "'"} and value[-1:] == value[0:1]:
        return value[1:-1]
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\.\d+)", value):
        return float(value)
    return value


def read_generation_config(path: Path) -> GenerationConfig:
    """Read the small subset of YAML used by the generator with stdlib only."""

    if not path.is_file():
        raise GenerationError(f"Missing generation config file: {path}")
    sections: dict[str, dict[str, Any]] = defaultdict(dict)
    current_section = ""
    current_list = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if indent == 0 and stripped.endswith(":"):
            current_section = stripped[:-1]
            current_list = ""
            continue
        if indent == 2 and stripped.endswith(":"):
            current_list = stripped[:-1]
            sections[current_section][current_list] = []
            continue
        if indent >= 4 and stripped.startswith("- ") and current_list:
            sections[current_section][current_list].append(_yaml_scalar(stripped[2:]))
            continue
        if indent == 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            sections[current_section][key] = _yaml_scalar(value)
            current_list = ""

    generation = sections.get("generation", {})
    defects = sections.get("intentional_defects", {})
    required_generation = {
        "seed",
        "target_fund_count",
        "minimum_fund_count",
        "base_currency",
        "as_of_date",
        "fund_id_prefix",
    }
    missing = sorted(required_generation - set(generation))
    if missing:
        raise GenerationError(f"Generation config is missing: {', '.join(missing)}")
    allowed = tuple(str(item) for item in defects.get("allowed_types", ALLOWED_DEFECTS))
    unknown = sorted(set(allowed) - set(ALLOWED_DEFECTS))
    if unknown:
        raise GenerationError(f"Unsupported configured defect types: {', '.join(unknown)}")
    return GenerationConfig(
        seed=int(generation["seed"]),
        target_fund_count=int(generation["target_fund_count"]),
        minimum_fund_count=int(generation["minimum_fund_count"]),
        base_currency=str(generation["base_currency"]),
        as_of_date=date.fromisoformat(str(generation["as_of_date"])),
        fund_id_prefix=str(generation["fund_id_prefix"]),
        defects_enabled=bool(defects.get("enabled", True)),
        defect_seed_offset=int(defects.get("seed_offset", 101)),
        defect_target_rate=float(defects.get("target_row_rate", 0.08)),
        allowed_defects=allowed,
    )


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise GenerationError(f"Missing CSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise GenerationError(f"CSV lacks a header row: {path}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def fund_model_headers(fund_model_dir: Path) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    for filename in FUND_MODEL_FILES:
        path = fund_model_dir / filename
        if not path.is_file():
            raise GenerationError(f"Fund-model CSV contract is missing: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            try:
                headers[filename] = next(reader)
            except StopIteration as exc:
                raise GenerationError(f"Fund-model CSV contract is empty: {path}") from exc
    return headers


def is_active(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def validate_inventory(path: Path, source_ledger_path: Path) -> int:
    rows = read_csv_rows(path)
    if not rows:
        raise GenerationError("Document inventory contains zero source rows.")
    if "file_id" not in rows[0]:
        raise GenerationError("Document inventory must contain a file_id column.")
    ids = [row.get("file_id", "") for row in rows]
    if any(not file_id for file_id in ids):
        raise GenerationError("Document inventory contains a blank file_id.")
    if len(ids) != len(set(ids)):
        raise GenerationError("Document inventory contains duplicate file_id values.")
    source_rows = read_csv_rows(source_ledger_path)
    if not source_rows or "file_id" not in source_rows[0]:
        raise GenerationError("Source ledger must contain at least one file_id row.")
    source_ids = [row.get("file_id", "") for row in source_rows]
    if any(not file_id for file_id in source_ids) or len(source_ids) != len(set(source_ids)):
        raise GenerationError("Source ledger has blank or duplicate file_id values.")
    missing = sorted(set(source_ids) - set(ids))
    extra = sorted(set(ids) - set(source_ids))
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing {len(missing)} source IDs")
        if extra:
            details.append(f"contains {len(extra)} unknown IDs")
        raise GenerationError(
            "Document inventory differs from the source ledger: "
            + "; ".join(details)
            + "."
        )
    required_status_columns = {
        "agent_a_status",
        "agent_b_status",
        "adjudication_status",
        "extraction_status",
    }
    missing_columns = sorted(required_status_columns - set(rows[0]))
    if missing_columns:
        raise GenerationError(
            "Document inventory lacks production-gate columns: "
            + ", ".join(missing_columns)
            + "."
        )
    incomplete_tokens = {"", "NOT_STARTED", "PENDING", "PENDING_DOUBLE_REVIEW", "UNRESOLVED"}
    mapping_incomplete = [
        row["file_id"]
        for row in rows
        if any(row.get(field, "").upper() in incomplete_tokens for field in (
            "agent_a_status",
            "agent_b_status",
            "adjudication_status",
        ))
    ]
    allowed_extraction_statuses = {
        "ADJUDICATED_COMPLETE",
        "NO_EXTRACTABLE_DATA",
        "NOT_APPLICABLE_TEMPLATE",
        "MANAGER_ONLY",
        "UNREADABLE",
    }
    extraction_incomplete = [
        row["file_id"]
        for row in rows
        if row.get("extraction_status", "").upper() not in allowed_extraction_statuses
    ]
    if mapping_incomplete or extraction_incomplete:
        raise GenerationError(
            "Production generation is locked until two-agent mapping and extraction "
            "adjudication are complete for every source artifact: "
            f"{len(mapping_incomplete)} mapping rows and "
            f"{len(extraction_incomplete)} extraction rows remain open."
        )
    return len(rows)


def assumed_parameter_rows(parameter_set_id: str) -> list[dict[str, str]]:
    """Create visible demo assumptions; every fallback reaches the parameter output."""

    rows: list[dict[str, str]] = []
    for (
        strategy,
        sub_strategy,
        weight,
        size_mean,
        dpi,
        rvpi,
        dpi_sd,
        rvpi_sd,
    ) in DEFAULT_STRATEGIES:
        values: dict[str, float | str] = {
            "strategy_weight": weight,
            "fund_size_mean": size_mean,
            "fund_size_cv": 0.45,
            "commitment_ratio": 1.0,
            "paid_in_ratio": 0.85,
            "dpi_mean": dpi,
            "dpi_sd": dpi_sd,
            "rvpi_mean": rvpi,
            "rvpi_sd": rvpi_sd,
            "management_fee_rate": 0.018,
            "carry_rate": 0.20,
            "hurdle_rate": 0.08,
            "fund_term_years": 10,
            "extension_years": 2,
            "vintage_min": 2012,
            "vintage_max": 2025,
            "geography": "North America",
            "domicile": "Delaware, US",
            "sub_strategy": sub_strategy,
        }
        for parameter_name, value in values.items():
            numeric = parameter_name in NUMERIC_PARAMETERS
            rows.append(
                {
                    "parameter_id": (
                        f"PAR_ASSUMED_{strategy.upper()}_{parameter_name.upper()}"
                    ),
                    "parameter_set_id": parameter_set_id,
                    "strategy": strategy,
                    "sub_strategy": "",
                    "parameter_name": parameter_name,
                    "value_numeric": _plain_number(float(value)) if numeric else "",
                    "value_text": "" if numeric else str(value),
                    "unit": _parameter_unit(parameter_name),
                    "provenance_type": "ASSUMED",
                    "source_document_id": "",
                    "source_page": "",
                    "source_anchor": "",
                    "formula_id": "",
                    "input_record_ids": "",
                    "assumption_basis": (
                        "Demonstration-only private-markets range selected to exercise "
                        "pipeline identities; replace with adjudicated source calibration."
                    ),
                    "adjudication_status": "NOT_APPLICABLE",
                    "active": "true",
                }
            )
    return rows


def _parameter_unit(name: str) -> str:
    if name.endswith("_rate") or name.endswith("_ratio") or name in {
        "strategy_weight",
        "fund_size_cv",
        "dpi_sd",
        "rvpi_sd",
    }:
        return "decimal"
    if name in {"fund_size_mean"}:
        return "USD_millions"
    if name in {"vintage_min", "vintage_max"}:
        return "year"
    if name in {"fund_term_years", "extension_years"}:
        return "years"
    return "text"


def select_and_validate_parameters(
    rows: list[dict[str, str]],
    parameter_set_id: str | None,
    allow_assumed_only: bool,
    source_rows: Sequence[Mapping[str, str]] | None = None,
) -> tuple[str, list[dict[str, str]], tuple[str, ...]]:
    active = [row for row in rows if is_active(row.get("active", ""))]
    available_sets = sorted({row.get("parameter_set_id", "") for row in active if row.get("parameter_set_id")})
    if parameter_set_id is None:
        if len(available_sets) == 1:
            parameter_set_id = available_sets[0]
        elif allow_assumed_only and not available_sets:
            parameter_set_id = "SYNTH_ASSUMED_DEMO_V1"
        else:
            raise GenerationError(
                "Select a single parameter set with --parameter-set-id; "
                f"active sets found: {available_sets or 'none'}."
            )
    selected = [row for row in active if row.get("parameter_set_id") == parameter_set_id]
    if not selected and allow_assumed_only:
        selected = assumed_parameter_rows(parameter_set_id)
    if not selected:
        raise GenerationError(f"Parameter set {parameter_set_id} has zero active rows.")

    source_formats: dict[str, str] = {}
    for source in source_rows or ():
        source_id = str(source.get("file_id", "")).strip()
        source_format = str(source.get("file_ext", "")).strip().lower().lstrip(".")
        if not source_id:
            raise GenerationError("Source ledger contains a blank file_id.")
        if source_id in source_formats:
            raise GenerationError(f"Source ledger contains duplicate file_id: {source_id}")
        source_formats[source_id] = source_format

    seen_ids: set[str] = set()
    for row in selected:
        parameter_id = row.get("parameter_id", "")
        name = row.get("parameter_name", "")
        provenance = row.get("provenance_type", "").upper()
        if not parameter_id or not name:
            raise GenerationError("Every parameter needs parameter_id and parameter_name.")
        if parameter_id in seen_ids:
            raise GenerationError(f"Duplicate parameter_id: {parameter_id}")
        seen_ids.add(parameter_id)
        if provenance == "EXTRACTED":
            missing = [
                field
                for field in ("source_document_id", "source_anchor", "input_record_ids")
                if not row.get(field)
            ]
            if missing:
                raise GenerationError(
                    f"Extracted parameter {parameter_id} lacks {', '.join(missing)}."
                )
            source_document_id = row["source_document_id"]
            if not source_formats:
                raise GenerationError(
                    f"Extracted parameter {parameter_id} requires source ledger metadata."
                )
            if source_document_id not in source_formats:
                raise GenerationError(
                    f"Extracted parameter {parameter_id} cites unknown source_document_id "
                    f"{source_document_id}."
                )
            source_format = source_formats[source_document_id]
            if source_format == "pdf" and not row.get("source_page"):
                raise GenerationError(
                    f"Extracted PDF parameter {parameter_id} lacks source_page."
                )
            if source_format in {"xlsx", "zip"} and row.get("source_page"):
                raise GenerationError(
                    f"Extracted {source_format.upper()} parameter {parameter_id} "
                    "must leave source_page empty."
                )
            if source_format not in {"pdf", "xlsx", "zip"}:
                raise GenerationError(
                    f"Extracted parameter {parameter_id} cites unsupported source format "
                    f"{source_format!r}."
                )
            if row.get("adjudication_status", "").upper() != "ADJUDICATED":
                raise GenerationError(
                    f"Extracted parameter {parameter_id} lacks adjudication_status ADJUDICATED."
                )
        elif provenance == "DERIVED":
            if not row.get("formula_id"):
                raise GenerationError(f"Derived parameter {parameter_id} lacks formula_id.")
            if not row.get("input_record_ids"):
                raise GenerationError(
                    f"Derived parameter {parameter_id} lacks input_record_ids."
                )
            if row.get("adjudication_status", "").upper() != "ADJUDICATED":
                raise GenerationError(
                    f"Derived parameter {parameter_id} lacks adjudication_status ADJUDICATED."
                )
        elif provenance == "ASSUMED":
            if not row.get("assumption_basis"):
                raise GenerationError(
                    f"Assumed parameter {parameter_id} lacks assumption_basis."
                )
        else:
            raise GenerationError(
                f"Parameter {parameter_id} has unsupported provenance_type {provenance!r}."
            )
        if name in NUMERIC_PARAMETERS:
            try:
                float(row.get("value_numeric", ""))
            except ValueError as exc:
                raise GenerationError(
                    f"Parameter {parameter_id} requires a numeric value."
                ) from exc
        elif not row.get("value_text"):
            raise GenerationError(f"Parameter {parameter_id} requires value_text.")

    strategies = tuple(
        sorted(
            {
                row.get("strategy", "")
                for row in selected
                if row.get("strategy", "") not in {"", "*", "ALL", "all"}
            }
        )
    )
    if not strategies:
        raise GenerationError("The parameter set identifies zero strategies.")
    for strategy in strategies:
        names = {
            row["parameter_name"]
            for row in selected
            if row.get("strategy") in {strategy, "", "*", "ALL", "all"}
        }
        missing = sorted(set(REQUIRED_PARAMETERS) - names)
        if missing:
            raise GenerationError(
                f"Strategy {strategy} lacks required parameters: {', '.join(missing)}."
            )
        extracted = [
            row
            for row in selected
            if row.get("strategy") == strategy
            and row.get("provenance_type", "").upper() == "EXTRACTED"
        ]
        if not extracted and not allow_assumed_only:
            raise GenerationError(
                f"Strategy {strategy} lacks an adjudicated EXTRACTED calibration parameter."
            )
    return parameter_set_id, selected, strategies


class ParameterBook:
    def __init__(self, rows: Sequence[Mapping[str, str]]) -> None:
        self.rows = rows

    def _row(self, strategy: str, name: str) -> Mapping[str, str]:
        ranked: list[tuple[int, Mapping[str, str]]] = []
        for row in self.rows:
            if row.get("parameter_name") != name:
                continue
            row_strategy = row.get("strategy", "")
            if row_strategy == strategy:
                ranked.append((0, row))
            elif row_strategy in {"", "*", "ALL", "all"}:
                ranked.append((1, row))
        if not ranked:
            raise GenerationError(f"Missing parameter {name!r} for strategy {strategy!r}.")
        best_rank = min(item[0] for item in ranked)
        best = [item[1] for item in ranked if item[0] == best_rank]
        if len(best) > 1:
            ids = ", ".join(sorted(row.get("parameter_id", "") for row in best))
            raise GenerationError(
                f"Multiple active values for {strategy}/{name}: {ids}. "
                "Adjudicate to one generator input."
            )
        return best[0]

    def number(self, strategy: str, name: str) -> float:
        return float(self._row(strategy, name).get("value_numeric", ""))

    def text(self, strategy: str, name: str) -> str:
        return str(self._row(strategy, name).get("value_text", ""))


def validate_parameter_ranges(
    book: ParameterBook, strategies: Sequence[str], as_of_year: int
) -> None:
    for strategy in strategies:
        values = {
            name: book.number(strategy, name)
            for name in NUMERIC_PARAMETERS
        }
        if values["strategy_weight"] <= 0:
            raise GenerationError(f"{strategy}: strategy_weight must be positive.")
        if values["fund_size_mean"] <= 0 or values["fund_size_cv"] < 0:
            raise GenerationError(f"{strategy}: fund-size parameters are invalid.")
        for name in ("commitment_ratio", "paid_in_ratio"):
            if not 0 < values[name] <= 1:
                raise GenerationError(f"{strategy}: {name} must be in (0, 1].")
        for name in ("dpi_mean", "dpi_sd", "rvpi_mean", "rvpi_sd"):
            if values[name] < 0:
                raise GenerationError(f"{strategy}: {name} must be zero or greater.")
        for name in ("management_fee_rate", "carry_rate", "hurdle_rate"):
            if not 0 <= values[name] <= 1:
                raise GenerationError(f"{strategy}: {name} must be in [0, 1].")
        if values["fund_term_years"] <= 0 or values["extension_years"] < 0:
            raise GenerationError(f"{strategy}: fund life parameters are invalid.")
        vintage_min = int(round(values["vintage_min"]))
        vintage_max = int(round(values["vintage_max"]))
        if vintage_min > vintage_max or vintage_max > as_of_year:
            raise GenerationError(
                f"{strategy}: vintage range {vintage_min} to {vintage_max} is invalid "
                f"for as-of year {as_of_year}."
            )


def _plain_number(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _money(value: float) -> str:
    return f"{round(value + 1e-12, 2):.2f}"


def _ratio(value: float) -> str:
    return f"{value:.6f}"


def _rate(value: float) -> str:
    return f"{value:.8f}"


def _truth(value: bool) -> str:
    return "true" if value else "false"


def _weighted_choice(rng: random.Random, values: Sequence[str], weights: Sequence[float]) -> str:
    total = sum(weights)
    if total <= 0:
        raise GenerationError("Strategy weights must sum to a positive value.")
    point = rng.random() * total
    cumulative = 0.0
    for value, weight in zip(values, weights):
        cumulative += weight
        if point <= cumulative:
            return value
    return values[-1]


def _split_money(total: float, proportions: Sequence[float]) -> list[float]:
    cents = int(round(total * 100))
    parts: list[int] = []
    remaining = cents
    for proportion in proportions[:-1]:
        value = int(round(cents * proportion))
        parts.append(value)
        remaining -= value
    parts.append(remaining)
    return [part / 100.0 for part in parts]


def _interpolate_dates(start: date, end: date, fractions: Sequence[float]) -> list[date]:
    days = max((end - start).days, 1)
    return [start + timedelta(days=min(days, max(0, round(days * fraction)))) for fraction in fractions]


def _quarter_ends(start: date, end: date) -> list[date]:
    """Return every calendar quarter end from start through end, inclusive."""

    if end < start:
        return []
    dates: list[date] = []
    year = start.year
    while year <= end.year:
        for month, day in QUARTER_END_MONTH_DAY:
            when = date(year, month, day)
            if when < start:
                continue
            if when > end:
                return dates
            dates.append(when)
        year += 1
    return dates


def _normalized(weights: Sequence[float]) -> list[float]:
    total = sum(weights)
    if total <= 0:
        return [0.0] * len(weights)
    return [weight / total for weight in weights]


def _call_weights(quarter_count: int, investment_quarters: int, rng: random.Random) -> list[float]:
    """Front-loaded drawdown weights; the first quarter always carries a call."""

    weights = [0.0] * quarter_count
    span = max(1, min(investment_quarters, quarter_count))
    for index in range(span):
        decay = math.exp(-2.1 * index / span)
        draw = rng.random()
        weights[index] = decay * rng.uniform(0.55, 1.45) if draw < 0.72 else 0.0
    if sum(weights) <= 0:
        weights[0] = 1.0
    if weights[0] <= 0:
        weights[0] = max(weights) * rng.uniform(0.9, 1.6)
    return _normalized(weights)


def _distribution_weights(
    quarter_count: int, first_index: int, rng: random.Random
) -> list[float]:
    """Back-loaded realization weights that begin after the harvest date."""

    weights = [0.0] * quarter_count
    if first_index >= quarter_count:
        return weights
    span = quarter_count - first_index
    for offset in range(span):
        ramp = 0.25 + 1.75 * (offset / max(span - 1, 1))
        weights[first_index + offset] = ramp * rng.uniform(0.4, 1.6) if rng.random() < 0.58 else 0.0
    if sum(weights) <= 0:
        weights[quarter_count - 1] = 1.0
    return _normalized(weights)


def _tvpi_path(
    quarter_count: int, terminal_tvpi: float, dip_depth: float
) -> list[float]:
    """Return a J-curve total-value path that lands on the terminal multiple."""

    path: list[float] = []
    for index in range(quarter_count):
        progress = index / max(quarter_count - 1, 1)
        ramp = progress ** 0.78
        dip = dip_depth * math.exp(-4.4 * progress) * (1.0 - progress)
        path.append(1.0 + (terminal_tvpi - 1.0) * ramp - dip)
    path[-1] = terminal_tvpi
    return path


def _cumulative(amounts: Sequence[float]) -> list[float]:
    running = 0.0
    totals: list[float] = []
    for amount in amounts:
        running = round(running + amount, 2)
        totals.append(running)
    return totals


def xnpv(rate: float, dated_values: Sequence[tuple[date, float]]) -> float:
    """Discount dated values with the shared project convention."""

    return shared_xnpv(rate, dated_values)


def xirr(dated_values: Sequence[tuple[date, float]]) -> float:
    """Return XIRR using the shared engine the quality rules also recompute with."""

    try:
        return shared_xirr(dated_values)
    except ValueError as exc:
        raise GenerationError(f"XIRR failed for the generated cash flows: {exc}") from exc


def _empty_tables() -> dict[str, list[dict[str, str]]]:
    return {filename: [] for filename in FUND_MODEL_FILES}


@dataclass(frozen=True)
class PositionSpec:
    """One reported perspective on a fund: the fund itself, an LP, or a class."""

    perspective: str
    lp_id: str
    lp_name: str
    share_class_name: str
    share: float
    suffix: str


@dataclass
class FundSchedule:
    """The dated, fund-total economics every reported position scales from."""

    timeline: list[date]
    first_close: date
    call_dates: list[date]
    distribution_dates: list[date]
    calls: list[float]
    distributions: list[float]
    recallable: list[float]
    navs: list[float]
    commitment: float
    investment_quarters: int
    fee_rate: float
    income_yield: float


def _horizon_multiples(
    *,
    mature_dpi: float,
    mature_rvpi: float,
    dispersion: float,
    lifecycle: float,
    rng: random.Random,
) -> tuple[float, float]:
    """Split a fund's value into realized and residual multiples at its horizon.

    ``mature_dpi`` plus ``mature_rvpi`` is the total multiple a fully realized
    fund of this strategy reaches. A fund observed part way through its life has
    accrued only part of that value, and has realized only part of what it has
    accrued, so a young fund shows a low DPI beside a high RVPI.
    """

    mature_total = max(mature_dpi + mature_rvpi, 0.05)
    total = max(0.30, mature_total + rng.gauss(0.0, max(dispersion, 0.0)))
    accrued = 1.0 + (total - 1.0) * min(1.0, max(lifecycle, 0.0) ** 0.80)
    mature_realized_share = mature_dpi / mature_total
    realized_share = mature_realized_share * min(1.0, max(lifecycle, 0.0) ** 1.45)
    realized = max(0.0, accrued * realized_share)
    residual = max(0.02, accrued - realized)
    return realized, residual


def _build_fund_schedule(
    *,
    commitment: float,
    vintage: int,
    first_close: date,
    horizon: date,
    fee_rate: float,
    income_yield: float,
    paid_in_ratio: float,
    dpi_terminal: float,
    rvpi_terminal: float,
    rng: random.Random,
) -> FundSchedule:
    """Build one fund's quarterly drawdown, realization, and NAV history."""

    timeline = _quarter_ends(first_close, horizon)
    if len(timeline) < 2:
        timeline = _quarter_ends(date(vintage, 1, 1), horizon)
    if len(timeline) < 2:
        raise GenerationError(
            f"Vintage {vintage} produces fewer than two reporting quarters through {horizon}."
        )
    quarter_count = len(timeline)
    investment_quarters = min(quarter_count, max(4, int(round(quarter_count * 0.45))))
    paid_in_total = round(commitment * paid_in_ratio, 2)

    call_weights = _call_weights(quarter_count, investment_quarters, rng)
    calls = _amounts_from_weights(paid_in_total, call_weights)
    paid_in = _cumulative(calls)

    harvest_index = min(quarter_count - 1, max(2, int(round(quarter_count * 0.32))))
    distribution_weights = _distribution_weights(quarter_count, harvest_index, rng)
    distributions_total = round(paid_in[-1] * dpi_terminal, 2)
    distributions = _amounts_from_weights(distributions_total, distribution_weights)
    distributed = _cumulative(distributions)

    recallable_cutoff = min(quarter_count, harvest_index + 12)
    recallable = [
        round(amount * 0.18, 2) if index < recallable_cutoff else 0.0
        for index, amount in enumerate(distributions)
    ]

    terminal_tvpi = dpi_terminal + rvpi_terminal
    dip_depth = rng.uniform(0.06, 0.22)
    tvpi_path = _tvpi_path(quarter_count, terminal_tvpi, dip_depth)
    navs: list[float] = []
    for index in range(quarter_count):
        contributed = paid_in[index]
        if contributed <= 0:
            navs.append(0.0)
            continue
        realized_multiple = distributed[index] / contributed
        implied = (tvpi_path[index] - realized_multiple) * contributed
        floor = max(1.0, 0.015 * contributed)
        navs.append(round(max(implied, floor), 2))
    navs[-1] = round(max(paid_in[-1] * rvpi_terminal, 1.0), 2)

    call_dates = [
        max(first_close, when - timedelta(days=rng.randrange(24, 78)))
        for when in timeline
    ]
    distribution_dates = [
        max(first_close, when - timedelta(days=rng.randrange(8, 40)))
        for when in timeline
    ]

    return FundSchedule(
        timeline=timeline,
        first_close=first_close,
        call_dates=call_dates,
        distribution_dates=distribution_dates,
        calls=calls,
        distributions=distributions,
        recallable=recallable,
        navs=navs,
        commitment=commitment,
        investment_quarters=investment_quarters,
        fee_rate=fee_rate,
        income_yield=income_yield,
    )


def _amounts_from_weights(total: float, weights: Sequence[float]) -> list[float]:
    """Split a total across weights so the rounded parts re-sum to the total."""

    amounts = [round(total * weight, 2) for weight in weights]
    difference = round(total - sum(amounts), 2)
    if difference:
        positions = [index for index, amount in enumerate(amounts) if amount > 0]
        if positions:
            amounts[positions[-1]] = round(amounts[positions[-1]] + difference, 2)
        else:
            amounts[-1] = round(amounts[-1] + difference, 2)
    return amounts


def _position_history(
    *,
    fund_id: str,
    strategy: str,
    sub_strategy: str,
    vintage: int,
    fund_size: float,
    currency: str,
    schedule: FundSchedule,
    spec: PositionSpec,
    parameter_set_id: str,
    benchmark_by_quarter: Mapping[str, str],
    rng: random.Random,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return reconciled fund_periods and fund_cashflows rows for one position."""

    share = spec.share
    commitment = round(schedule.commitment * share, 2)
    periods: list[dict[str, str]] = []
    cashflows: list[dict[str, str]] = []
    dated_values: list[tuple[date, float]] = []

    calls = [round(amount * share, 2) for amount in schedule.calls]
    distributions = [round(amount * share, 2) for amount in schedule.distributions]
    recallable = [round(amount * share, 2) for amount in schedule.recallable]
    navs = [round(max(amount * share, 0.01), 2) for amount in schedule.navs]
    paid_in_running = _cumulative(calls)
    distributed_running = _cumulative(distributions)
    recallable_running = _cumulative(recallable)

    flow_index = 0
    beginning_nav = 0.0
    for index, when in enumerate(schedule.timeline):
        contributions = calls[index]
        distributed = distributions[index]
        if contributions > 0.004:
            flow_index += 1
            call_date = schedule.call_dates[index]
            cashflows.append(
                _cashflow_row(
                    fund_id,
                    flow_index,
                    call_date,
                    "capital_call",
                    -contributions,
                    currency,
                    parameter_set_id,
                    spec=spec,
                )
            )
            dated_values.append((call_date, -contributions))
        if distributed > 0.004:
            flow_index += 1
            distribution_date = schedule.distribution_dates[index]
            cashflows.append(
                _cashflow_row(
                    fund_id,
                    flow_index,
                    distribution_date,
                    "distribution",
                    distributed,
                    currency,
                    parameter_set_id,
                    spec=spec,
                    recallable_amount=recallable[index],
                )
            )
            dated_values.append((distribution_date, distributed))

        paid_in = paid_in_running[index]
        if paid_in <= 0:
            beginning_nav = navs[index]
            continue

        nav = navs[index]
        distributions_itd = distributed_running[index]
        recallable_itd = recallable_running[index]
        unfunded = round(commitment - paid_in + recallable_itd, 2)
        if unfunded < 0:
            commitment = round(paid_in - recallable_itd, 2)
            unfunded = 0.0

        fee_base = commitment if index < schedule.investment_quarters else beginning_nav
        management_fee = round(max(fee_base, 0.0) * schedule.fee_rate / 4.0, 2)
        other_expenses = round(
            max(beginning_nav, contributions, 1.0) * rng.uniform(0.0004, 0.0022), 2
        )
        net_income = round(beginning_nav * schedule.income_yield / 4.0, 2)
        gross_gain = round(
            nav
            - beginning_nav
            - contributions
            + distributed
            - net_income
            + management_fee
            + other_expenses,
            2,
        )
        realized_gain = round(min(max(gross_gain, 0.0), distributed * 0.55), 2)
        unrealized_gain = round(gross_gain - realized_gain, 2)
        period_return = (
            (nav - beginning_nav - contributions + distributed) / beginning_nav
            if beginning_nav > 0
            else 0.0
        )

        irr = xirr(dated_values + [(when, nav)]) if dated_values else 0.0
        dpi = distributions_itd / paid_in
        rvpi = nav / paid_in

        periods.append(
            {
                "fund_period_id": f"FP_{fund_id}{spec.suffix}_{when.strftime('%Y%m%d')}",
                "fund_id": fund_id,
                "lp_id": spec.lp_id,
                "lp_name": spec.lp_name,
                "share_class_name": spec.share_class_name,
                "date_role": "as_of",
                "date_raw": when.isoformat(),
                "date_precision": "day",
                "as_of_date": when.isoformat(),
                "report_date": (when + timedelta(days=45)).isoformat(),
                "period_start_date": (
                    schedule.timeline[index - 1] + timedelta(days=1)
                ).isoformat()
                if index > 0
                else "",
                "period_end_date": when.isoformat(),
                "effective_date": "",
                "perspective": spec.perspective,
                "currency": currency,
                "commitment": _money(commitment),
                "paid_in_capital_itd": _money(paid_in),
                "distributions_itd": _money(distributions_itd),
                "nav": _money(nav),
                "unfunded_commitment": _money(unfunded),
                "recallable_distributions_itd": _money(recallable_itd),
                "dpi": _ratio(dpi),
                "rvpi": _ratio(rvpi),
                "tvpi": _ratio(dpi + rvpi),
                "reported_irr": _rate(irr),
                "calculated_irr": _rate(irr),
                "beginning_nav": _money(beginning_nav),
                "contributions_period": _money(contributions),
                "distributions_period": _money(distributed),
                "realized_gain_period": _money(realized_gain),
                "unrealized_gain_period": _money(unrealized_gain),
                "net_income_period": _money(net_income),
                "management_fee_period": _money(management_fee),
                "other_expenses_period": _money(other_expenses),
                "ending_nav": _money(nav),
                "period_return": _rate(period_return),
                "benchmark_return": benchmark_by_quarter.get(when.isoformat(), ""),
                "fund_size": _money(fund_size),
                "vintage_year": str(vintage),
                "strategy": strategy,
                "sub_strategy": sub_strategy,
                "provenance_type": "SYNTHETIC",
                "source_document_id": "",
                "source_page": "",
                "source_anchor": "",
                "formula_id": "",
                "input_observation_ids": "",
                "synthetic_parameter_set_id": parameter_set_id,
                "defect_expected": "false",
                "record_status": "ACTIVE",
            }
        )
        beginning_nav = nav
    return periods, cashflows


def _position_specs(index: int, rng: random.Random) -> list[PositionSpec]:
    """Return the fund total plus any reported LP or share-class positions."""

    specs = [PositionSpec("fund_total", "", "", "", 1.0, "")]
    if index % 8 == 0:
        for order, share in enumerate(LP_POSITION_SHARES, 1):
            lp_id = f"LP_SYNTH_{index:06d}_{order:02d}"
            specs.append(
                PositionSpec(
                    "lp_position",
                    lp_id,
                    f"Synthetic Institutional LP {index:04d}-{order:02d}",
                    "",
                    share,
                    f"_{lp_id}",
                )
            )
    elif index % 17 == 0:
        for name, share in SHARE_CLASS_SHARES:
            slug = name.replace(" ", "_").upper()
            specs.append(
                PositionSpec("share_class", "", "", name, share, f"_{slug}")
            )
    return specs


def generate_clean_universe(
    config: GenerationConfig,
    parameter_set_id: str,
    parameter_rows: Sequence[Mapping[str, str]],
    strategies: Sequence[str],
    count: int,
    seed: int,
) -> dict[str, list[dict[str, str]]]:
    rng = random.Random(seed)
    book = ParameterBook(parameter_rows)
    validate_parameter_ranges(book, strategies, config.as_of_date.year)
    tables = _empty_tables()
    manager_totals: dict[str, float] = defaultdict(float)
    manager_names: dict[str, str] = {}
    manager_funds: dict[str, int] = defaultdict(int)
    weights = [book.number(strategy, "strategy_weight") for strategy in strategies]
    as_of = config.as_of_date
    created_at = f"{as_of.isoformat()}T00:00:00Z"
    benchmark_index = _build_benchmark_returns(tables, config, parameter_set_id, rng)

    for index in range(1, count + 1):
        strategy = _weighted_choice(rng, strategies, weights)
        sub_strategy = book.text(strategy, "sub_strategy")
        vintage_min = int(round(book.number(strategy, "vintage_min")))
        vintage_max = min(int(round(book.number(strategy, "vintage_max"))), as_of.year)
        if vintage_min > vintage_max:
            raise GenerationError(
                f"Invalid vintage range for {strategy}: {vintage_min} to {vintage_max}."
            )
        vintage = rng.randint(vintage_min, vintage_max)
        fund_id = f"{config.fund_id_prefix}{index:06d}"
        fund_name = f"Synthetic {strategy.replace('_', ' ').title()} Fund {index:04d}"
        manager_id = f"MANAGER_SYNTH_{((index - 1) // 4) + 1:05d}"
        manager_name = f"Synthetic Alternatives Manager {((index - 1) // 4) + 1:04d}"
        currency = _weighted_choice(
            rng,
            [code for code, _ in FUND_CURRENCY_WEIGHTS],
            [weight for _, weight in FUND_CURRENCY_WEIGHTS],
        )
        size_mean = book.number(strategy, "fund_size_mean")
        size_cv = max(book.number(strategy, "fund_size_cv"), 0.01)
        sigma = math.sqrt(math.log(1.0 + size_cv * size_cv))
        mu = math.log(max(size_mean, 1.0)) - (sigma * sigma / 2.0)
        fund_size = round(max(25.0, rng.lognormvariate(mu, sigma)), 2)
        manager_totals[manager_id] += fund_size * FX_TO_USD.get(currency, 1.0)
        manager_names[manager_id] = manager_name
        manager_funds[manager_id] += 1
        commitment = round(fund_size * book.number(strategy, "commitment_ratio"), 2)

        term_years = int(round(book.number(strategy, "fund_term_years")))
        extensions = int(round(book.number(strategy, "extension_years")))
        termination = date(vintage + term_years + extensions, 12, 31)
        horizon = min(as_of, termination)
        close_month, close_day = CLOSE_MONTH_DAY[rng.randrange(4)]
        first_close = date(vintage, close_month, close_day)
        if first_close > horizon:
            first_close = date(vintage, 2, 15)

        age_years = max((horizon - date(vintage, 1, 1)).days / 365.25, 0.25)
        lifecycle = min(age_years / 10.0, 1.0)
        paid_in_ratio = min(
            0.99,
            max(
                0.10,
                book.number(strategy, "paid_in_ratio") * (0.35 + 0.75 * lifecycle)
                + rng.uniform(-0.08, 0.08),
            ),
        )
        dpi_terminal, rvpi_terminal = _horizon_multiples(
            mature_dpi=book.number(strategy, "dpi_mean"),
            mature_rvpi=book.number(strategy, "rvpi_mean"),
            dispersion=max(book.number(strategy, "dpi_sd"), 0.0)
            + max(book.number(strategy, "rvpi_sd"), 0.0),
            lifecycle=lifecycle,
            rng=rng,
        )
        fee_rate = book.number(strategy, "management_fee_rate")
        schedule = _build_fund_schedule(
            commitment=commitment,
            vintage=vintage,
            first_close=first_close,
            horizon=horizon,
            fee_rate=fee_rate,
            income_yield=STRATEGY_INCOME_YIELD.get(strategy, 0.004),
            paid_in_ratio=paid_in_ratio,
            dpi_terminal=dpi_terminal,
            rvpi_terminal=rvpi_terminal,
            rng=rng,
        )
        benchmark_id = STRATEGY_BENCHMARK.get(strategy, BENCHMARK_SERIES[0][0])
        benchmark_by_quarter = benchmark_index[benchmark_id]

        fund_periods: list[dict[str, str]] = []
        for spec in _position_specs(index, rng):
            position_periods, position_cashflows = _position_history(
                fund_id=fund_id,
                strategy=strategy,
                sub_strategy=sub_strategy,
                vintage=vintage,
                fund_size=fund_size,
                currency=currency,
                schedule=schedule,
                spec=spec,
                parameter_set_id=parameter_set_id,
                benchmark_by_quarter=benchmark_by_quarter,
                rng=rng,
            )
            tables["fund_periods.csv"].extend(position_periods)
            tables["fund_cashflows.csv"].extend(position_cashflows)
            if spec.perspective == "fund_total":
                fund_periods = position_periods
        if not fund_periods:
            raise GenerationError(f"{fund_id} produced zero fund-total periods.")

        final_close = schedule.timeline[
            min(len(schedule.timeline) - 1, schedule.investment_quarters - 1)
        ]
        tables["fund_master.csv"].append(
            {
                "fund_id": fund_id,
                "fund_name": fund_name,
                "legal_name": f"{fund_name}, L.P.",
                "fund_manager_id": manager_id,
                "fund_manager_name": manager_name,
                "strategy": strategy,
                "sub_strategy": sub_strategy,
                "vintage_year": str(vintage),
                "domicile": book.text(strategy, "domicile"),
                "base_currency": currency,
                "fund_size": _money(fund_size),
                "fund_size_currency": currency,
                "first_close_date": schedule.first_close.isoformat(),
                "final_close_date": final_close.isoformat(),
                "termination_date": termination.isoformat(),
                "fund_status": "active" if termination >= as_of else "liquidated",
                "provenance_type": "SYNTHETIC",
                "source_document_id": "",
                "source_page": "",
                "source_anchor": "",
                "synthetic_parameter_set_id": parameter_set_id,
                "record_status": "ACTIVE",
                "created_at": created_at,
            }
        )
        tables["fund_terms.csv"].extend(
            _term_rows(
                fund_id,
                strategy,
                book,
                schedule.timeline[0],
                currency,
                parameter_set_id,
                index,
                term_years,
                extensions,
            )
        )
        tables["fund_term_clauses.csv"].extend(
            _clause_rows(fund_id, schedule.timeline[0], parameter_set_id, index, strategy)
        )
        tables["fund_holdings.csv"].extend(
            _holding_rows(
                fund_id,
                fund_periods,
                book.text(strategy, "geography"),
                currency,
                parameter_set_id,
                rng,
            )
        )

    for manager_id in sorted(manager_totals):
        manager_name = manager_names[manager_id]
        tables["manager_master.csv"].append(
            {
                "manager_id": manager_id,
                "manager_name": manager_name,
                "legal_name": f"{manager_name}, LLC",
                "domicile": "United States",
                "headquarters": "Synthetic City",
                "website": "",
                "base_currency": config.base_currency,
                "provenance_type": "SYNTHETIC",
                "source_document_id": "",
                "source_page": "",
                "source_anchor": "",
                "synthetic_parameter_set_id": parameter_set_id,
                "record_status": "ACTIVE",
                "created_at": created_at,
            }
        )
        for metric_id, value_numeric, value_text, basis, unit in (
            ("mgr.aum", _money(manager_totals[manager_id]), "", "point_in_time", "currency"),
            (
                "mgr.fund_count",
                str(manager_funds[manager_id]),
                "",
                "point_in_time",
                "count",
            ),
            (
                "mgr.operational_control",
                "",
                "institutional_controls_documented",
                "static",
                "text",
            ),
        ):
            dated = metric_id != "mgr.operational_control"
            tables["manager_observations.csv"].append(
                {
                    "manager_observation_id": f"MOBS_{manager_id}_{metric_id.upper().replace('.', '_')}",
                    "manager_id": manager_id,
                    # The contract requires a document key on every manager fact.
                    # A generated fact originates in its parameter set, so the
                    # parameter set is the record of origin it cites.
                    "file_id": f"SYNTH_PARAMETER_SET_{parameter_set_id}",
                    "metric_id": metric_id,
                    "date_role": "as_of" if dated else "static_no_date",
                    "date_raw": as_of.isoformat() if dated else "",
                    "date_precision": "day" if dated else "unknown",
                    "as_of_date": as_of.isoformat() if dated else "",
                    "report_date": "",
                    "period_start_date": "",
                    "period_end_date": "",
                    "cashflow_date": "",
                    "effective_date": "",
                    "due_date": "",
                    "maturity_date": "",
                    "value_raw": value_numeric or value_text,
                    "value_numeric": value_numeric,
                    "value_text": value_text,
                    "currency": config.base_currency if metric_id == "mgr.aum" else "",
                    "unit": unit,
                    "perspective": "manager_total",
                    "measure_basis": basis,
                    "provenance_type": "SYNTHETIC",
                    "source_page": "",
                    "source_anchor": "",
                    "extractor_version": "",
                    "formula_id": "",
                    "synthetic_parameter_set_id": parameter_set_id,
                    "imputation_method": "",
                    "confidence": "1.000000",
                    "record_status": "ACTIVE",
                }
            )

    _attach_observations(tables, parameter_set_id)
    _attach_allocations(tables, as_of, parameter_set_id)
    return tables


def _term_rows(
    fund_id: str,
    strategy: str,
    book: ParameterBook,
    effective: date,
    currency: str,
    parameter_set_id: str,
    index: int,
    term_years: int,
    extensions: int,
) -> list[dict[str, str]]:
    base_term_id = f"FT_{fund_id}_V1"
    rows = [
        {
            "fund_term_id": base_term_id,
            "fund_id": fund_id,
            "lp_id": "",
            "lp_name": "",
            "share_class_name": "",
            "perspective": "fund_total",
            "term_scope": "base_fund",
            "overrides_fund_term_id": "",
            "effective_date": effective.isoformat(),
            "effective_end_date": "",
            "management_fee_rate": _rate(book.number(strategy, "management_fee_rate")),
            "management_fee_basis": "committed_capital_then_nav",
            "carry_rate": _rate(book.number(strategy, "carry_rate")),
            "hurdle_rate": _rate(book.number(strategy, "hurdle_rate")),
            "catch_up_rate": "1.00000000",
            "catch_up_present": "true",
            "waterfall_type": "whole_fund" if strategy != "venture" else "deal_by_deal",
            "fund_term_years": str(term_years),
            "extension_years": str(extensions),
            "preferred_return_compounding": "annual",
            "expense_cap_rate": "",
            "maximum_offering": "",
            "currency": currency,
            "provenance_type": "SYNTHETIC",
            "source_document_id": "",
            "source_page": "",
            "source_anchor": "",
            "synthetic_parameter_set_id": parameter_set_id,
            "record_status": "ACTIVE",
        }
    ]
    if index % 8 == 0:
        for order, _ in enumerate(LP_POSITION_SHARES, 1):
            lp_id = f"LP_SYNTH_{index:06d}_{order:02d}"
            rows.append(
                {
                    "fund_term_id": f"FT_{fund_id}_{lp_id}_OVERRIDE_V1",
                    "fund_id": fund_id,
                    "lp_id": lp_id,
                    "lp_name": f"Synthetic Institutional LP {index:04d}-{order:02d}",
                    "share_class_name": "",
                    "perspective": "lp_position",
                    "term_scope": "lp_override",
                    "overrides_fund_term_id": base_term_id,
                    "effective_date": effective.isoformat(),
                    "effective_end_date": "",
                    "management_fee_rate": _rate(
                        max(book.number(strategy, "management_fee_rate") - 0.0025 * order, 0.0)
                    ),
                    "management_fee_basis": "committed_capital_then_nav",
                    "carry_rate": "",
                    "hurdle_rate": "",
                    "catch_up_rate": "",
                    "catch_up_present": "",
                    "waterfall_type": "",
                    "fund_term_years": "",
                    "extension_years": "",
                    "preferred_return_compounding": "",
                    "expense_cap_rate": "",
                    "maximum_offering": "",
                    "currency": currency,
                    "provenance_type": "SYNTHETIC",
                    "source_document_id": "",
                    "source_page": "",
                    "source_anchor": "",
                    "synthetic_parameter_set_id": parameter_set_id,
                    "record_status": "ACTIVE",
                }
            )
    elif index % 17 == 0:
        for name, _ in SHARE_CLASS_SHARES:
            slug = name.replace(" ", "_").upper()
            rows.append(
                {
                    "fund_term_id": f"FT_{fund_id}_{slug}_OVERRIDE_V1",
                    "fund_id": fund_id,
                    "lp_id": "",
                    "lp_name": "",
                    "share_class_name": name,
                    "perspective": "share_class",
                    "term_scope": "share_class_override",
                    "overrides_fund_term_id": base_term_id,
                    "effective_date": effective.isoformat(),
                    "effective_end_date": "",
                    "management_fee_rate": _rate(
                        max(
                            book.number(strategy, "management_fee_rate")
                            - (0.0 if name == "Class A" else 0.0040),
                            0.0,
                        )
                    ),
                    "management_fee_basis": "committed_capital_then_nav",
                    "carry_rate": "",
                    "hurdle_rate": "",
                    "catch_up_rate": "",
                    "catch_up_present": "",
                    "waterfall_type": "",
                    "fund_term_years": "",
                    "extension_years": "",
                    "preferred_return_compounding": "",
                    "expense_cap_rate": "",
                    "maximum_offering": "",
                    "currency": currency,
                    "provenance_type": "SYNTHETIC",
                    "source_document_id": "",
                    "source_page": "",
                    "source_anchor": "",
                    "synthetic_parameter_set_id": parameter_set_id,
                    "record_status": "ACTIVE",
                }
            )
    return rows


# metric_id stays inside the two values the clause contract allows.
CLAUSE_LIBRARY: tuple[tuple[str, str, str], ...] = (
    ("RISK_01", "terms.risk_factor", "Synthetic concentration risk"),
    ("RISK_02", "terms.risk_factor", "Synthetic valuation policy risk"),
    ("SPEC_01", "terms.special_term", "Synthetic advisory committee right"),
    ("SPEC_02", "terms.special_term", "Synthetic key person suspension"),
)

CLAUSE_TEXT = {
    "RISK_01": "Portfolio concentration can increase valuation volatility.",
    "RISK_02": "Unquoted holdings carry a valuation estimate the manager reviews each quarter.",
    "SPEC_01": "An advisory committee reviews conflicts and valuation policy each quarter.",
    "SPEC_02": "Departure of two named principals suspends the investment period.",
}


def _clause_rows(
    fund_id: str,
    effective: date,
    parameter_set_id: str,
    index: int,
    strategy: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for suffix, metric_id, title in CLAUSE_LIBRARY:
        rows.append(
            {
                "fund_term_clause_id": f"FTC_{fund_id}_{suffix}",
                "fund_id": fund_id,
                "lp_id": "",
                "lp_name": "",
                "share_class_name": "",
                "perspective": "fund_total",
                "term_scope": "base_fund",
                "overrides_fund_term_id": "",
                "effective_date": effective.isoformat(),
                "effective_end_date": "",
                "source_document_id": "",
                "metric_id": metric_id,
                "clause_title": title,
                "value_raw": CLAUSE_TEXT[suffix],
                "value_text": CLAUSE_TEXT[suffix],
                "currency": "",
                "provenance_type": "SYNTHETIC",
                "source_page": "",
                "source_anchor": "",
                "extractor_version": "",
                "synthetic_parameter_set_id": parameter_set_id,
                "record_status": "ACTIVE",
            }
        )
    if index % 8 == 0:
        base_term_id = f"FT_{fund_id}_V1"
        for order, _ in enumerate(LP_POSITION_SHARES, 1):
            lp_id = f"LP_SYNTH_{index:06d}_{order:02d}"
            rows.append(
                {
                    "fund_term_clause_id": f"FTC_{fund_id}_{lp_id}_SPECIAL_01",
                    "fund_id": fund_id,
                    "lp_id": lp_id,
                    "lp_name": f"Synthetic Institutional LP {index:04d}-{order:02d}",
                    "share_class_name": "",
                    "perspective": "lp_position",
                    "term_scope": "lp_override",
                    "overrides_fund_term_id": base_term_id,
                    "effective_date": effective.isoformat(),
                    "effective_end_date": "",
                    "source_document_id": "",
                    "metric_id": "terms.special_term",
                    "clause_title": "Synthetic fee discount",
                    "value_raw": f"The LP receives a {25 * order} basis point management-fee discount.",
                    "value_text": f"The LP receives a {25 * order} basis point management-fee discount.",
                    "currency": "",
                    "provenance_type": "SYNTHETIC",
                    "source_page": "",
                    "source_anchor": "",
                    "extractor_version": "",
                    "synthetic_parameter_set_id": parameter_set_id,
                    "record_status": "ACTIVE",
                }
            )
    return rows


def _cashflow_row(
    fund_id: str,
    flow_index: int,
    when: date,
    cashflow_type: str,
    amount: float,
    currency: str,
    parameter_set_id: str,
    *,
    spec: PositionSpec | None = None,
    recallable_amount: float = 0.0,
) -> dict[str, str]:
    suffix = spec.suffix if spec is not None else ""
    return {
        "cashflow_id": f"CF_{fund_id}{suffix}_{flow_index:03d}",
        "fund_id": fund_id,
        "lp_id": spec.lp_id if spec is not None else "",
        "lp_name": spec.lp_name if spec is not None else "",
        "share_class_name": spec.share_class_name if spec is not None else "",
        "file_id": "",
        "cashflow_event_id": f"CFE_{fund_id}{suffix}_{flow_index:03d}",
        "date_role": "cashflow",
        "date_raw": when.isoformat(),
        "date_precision": "day",
        "cashflow_date": when.isoformat(),
        "report_date": (when - timedelta(days=10)).isoformat()
        if cashflow_type == "capital_call"
        else when.isoformat(),
        "due_date": when.isoformat() if cashflow_type == "capital_call" else "",
        "cashflow_type": cashflow_type,
        "amount": _money(amount),
        "currency": currency,
        "amount_base_currency": _money(amount),
        "base_currency": currency,
        "fx_rate": "1.00000000",
        "recallable_amount": _money(recallable_amount),
        "provenance_type": "SYNTHETIC",
        "source_page": "",
        "source_anchor": "",
        "synthetic_parameter_set_id": parameter_set_id,
        "defect_expected": "false",
        "record_status": "ACTIVE",
    }


def _holding_rows(
    fund_id: str,
    fund_periods: Sequence[Mapping[str, str]],
    geography: str,
    currency: str,
    parameter_set_id: str,
    rng: random.Random,
) -> list[dict[str, str]]:
    """Build a dated look-through whose fair values re-sum to NAV each quarter."""

    if not fund_periods:
        return []
    quarter_count = len(fund_periods)
    company_count = rng.randint(3, 8)
    entries = [0] + sorted(
        rng.randrange(0, max(1, int(quarter_count * 0.55)))
        for _ in range(company_count - 1)
    )
    exits: list[int | None] = []
    for order, entry in enumerate(entries):
        latest_exit = quarter_count
        if order > 0 and rng.random() < 0.45:
            earliest = min(entry + 4, quarter_count)
            exits.append(rng.randrange(earliest, latest_exit) if earliest < latest_exit else None)
        else:
            exits.append(None)
    profiles = [
        {
            "security_type": rng.choice(SECURITY_TYPES),
            "sector": rng.choice(SECTORS),
            "weight": rng.uniform(0.5, 2.0),
            "ownership": rng.uniform(0.05, 0.80),
            "cost_ratio": rng.uniform(0.55, 1.30),
            "interest_rate": rng.uniform(0.07, 0.13),
            "spread_bps": rng.randrange(350, 751, 25),
        }
        for _ in range(company_count)
    ]

    rows: list[dict[str, str]] = []
    for index, period in enumerate(fund_periods):
        as_of = date.fromisoformat(period["as_of_date"])
        nav = float(period["nav"])
        active = [
            order
            for order in range(company_count)
            if entries[order] <= index and (exits[order] is None or exits[order] > index)
        ]
        if not active:
            active = [0]
        proportions = _normalized([profiles[order]["weight"] for order in active])
        values = _split_money(nav, proportions)
        for order, fair_value in zip(active, values):
            profile = profiles[order]
            is_debt = profile["security_type"] in {"Senior Debt", "Unitranche"}
            rows.append(
                {
                    "holding_id": f"HOLD_{fund_id}_{order + 1:02d}_{as_of.strftime('%Y%m%d')}",
                    "fund_id": fund_id,
                    "portfolio_company_id": f"COMPANY_SYNTH_{fund_id[-6:]}_{order + 1:02d}",
                    "portfolio_company_name": f"Synthetic Portfolio Company {fund_id[-6:]}-{order + 1:02d}",
                    "instrument_id": f"INSTR_SYNTH_{fund_id[-6:]}_{order + 1:02d}",
                    "instrument_name": f"Synthetic Instrument {fund_id[-6:]}-{order + 1:02d}",
                    "date_role": "as_of",
                    "date_raw": as_of.isoformat(),
                    "date_precision": "day",
                    "as_of_date": as_of.isoformat(),
                    "report_date": "",
                    "period_start_date": "",
                    "period_end_date": "",
                    "effective_date": "",
                    "security_type": profile["security_type"],
                    "sector": profile["sector"],
                    "geography": geography,
                    "currency": currency,
                    "cost": _money(fair_value * profile["cost_ratio"]),
                    "fair_value": _money(fair_value),
                    "principal_amount": _money(fair_value * profile["cost_ratio"]) if is_debt else "",
                    "interest_rate": _rate(profile["interest_rate"]) if is_debt else "",
                    "spread_bps": str(profile["spread_bps"]) if is_debt else "",
                    "maturity_date": date(as_of.year + 4 + order % 3, 12, 31).isoformat()
                    if is_debt
                    else "",
                    "ownership_percent": _rate(profile["ownership"]),
                    "provenance_type": "SYNTHETIC",
                    "source_document_id": "",
                    "source_page": "",
                    "source_anchor": "",
                    "synthetic_parameter_set_id": parameter_set_id,
                    "record_status": "ACTIVE",
                }
            )
    return rows


def _build_benchmark_returns(
    tables: dict[str, list[dict[str, str]]],
    config: GenerationConfig,
    parameter_set_id: str,
    rng: random.Random,
) -> dict[str, dict[str, str]]:
    """Emit one quarterly series per public-market comparison and index them."""

    start = date(config.as_of_date.year - 22, 1, 1)
    quarters = _quarter_ends(start, config.as_of_date)
    index: dict[str, dict[str, str]] = {}
    for benchmark_id, benchmark_name, drift, deviation in BENCHMARK_SERIES:
        by_quarter: dict[str, str] = {}
        for counter, when in enumerate(quarters, 1):
            value = max(-0.36, min(0.38, rng.gauss(drift, deviation)))
            formatted = _rate(value)
            by_quarter[when.isoformat()] = formatted
            tables["benchmark_returns.csv"].append(
                {
                    "benchmark_return_id": f"BMR_{benchmark_id[9:]}_Q{counter:04d}",
                    "benchmark_id": benchmark_id,
                    "benchmark_name": benchmark_name,
                    "return_date": when.isoformat(),
                    "periodicity": "quarterly",
                    "return_value": formatted,
                    "currency": config.base_currency,
                    "provenance_type": "SYNTHETIC",
                    "source_document_id": "",
                    "source_page": "",
                    "source_anchor": "",
                    "synthetic_parameter_set_id": parameter_set_id,
                    "record_status": "ACTIVE",
                }
            )
        index[benchmark_id] = by_quarter
    return index


def _attach_observations(
    tables: dict[str, list[dict[str, str]]], parameter_set_id: str
) -> None:
    metric_map = {
        "commitment": ("cap.commitment", "currency", "static"),
        "paid_in_capital_itd": ("cap.contributions_itd", "currency", "inception_to_date"),
        "distributions_itd": ("cap.distributions_itd", "currency", "inception_to_date"),
        "nav": ("val.nav", "currency", "point_in_time"),
        "unfunded_commitment": ("cap.unfunded_commitment", "currency", "point_in_time"),
        "dpi": ("perf.dpi", "multiple", "ratio"),
        "rvpi": ("perf.rvpi", "multiple", "ratio"),
        "tvpi": ("perf.tvpi", "multiple", "ratio"),
        "reported_irr": ("perf.irr", "decimal", "rate"),
        "fund_size": ("attr.fund_size", "currency", "static"),
    }
    rows: list[dict[str, str]] = []
    for period in tables["fund_periods.csv"]:
        for period_field, (metric_id, unit, basis) in metric_map.items():
            value = period[period_field]
            rows.append(
                {
                    "observation_id": (
                        f"OBS_{period['fund_period_id']}_{metric_id.upper().replace('.', '_')}"
                    ),
                    "fund_id": period["fund_id"],
                    "lp_id": period["lp_id"],
                    "lp_name": period["lp_name"],
                    "share_class_name": period["share_class_name"],
                    "file_id": "",
                    "metric_id": metric_id,
                    "date_role": "as_of",
                    "date_raw": period["as_of_date"],
                    "date_precision": "day",
                    "as_of_date": period["as_of_date"],
                    "report_date": period["as_of_date"],
                    "period_start_date": "",
                    "period_end_date": "",
                    "cashflow_date": "",
                    "effective_date": "",
                    "due_date": "",
                    "maturity_date": "",
                    "value_raw": value,
                    "value_numeric": value,
                    "value_text": "",
                    "currency": period["currency"] if unit == "currency" else "",
                    "unit": unit,
                    "perspective": period["perspective"],
                    "measure_basis": basis,
                    "fee_basis": "net"
                    if metric_id in {"perf.irr", "perf.dpi", "perf.rvpi", "perf.tvpi"}
                    else "",
                    "provenance_type": "SYNTHETIC",
                    "source_page": "",
                    "source_anchor": "",
                    "extractor_version": "",
                    "formula_id": "",
                    "synthetic_parameter_set_id": parameter_set_id,
                    "imputation_method": "",
                    "confidence": "1.000000",
                    "record_status": "ACTIVE",
                }
            )
    tables["fund_observations.csv"] = rows


def _latest_fund_total_periods(
    fund_periods: Sequence[Mapping[str, str]]
) -> list[Mapping[str, str]]:
    latest: dict[str, Mapping[str, str]] = {}
    for period in fund_periods:
        if period.get("perspective") != "fund_total":
            continue
        fund_id = period["fund_id"]
        current = latest.get(fund_id)
        if current is None or period["as_of_date"] > current["as_of_date"]:
            latest[fund_id] = period
    return [latest[fund_id] for fund_id in sorted(latest)]


def _attach_allocations(
    tables: dict[str, list[dict[str, str]]],
    as_of: date,
    parameter_set_id: str,
) -> None:
    """Emit one baseline allocation per portfolio definition over the latest NAV."""

    periods = _latest_fund_total_periods(tables["fund_periods.csv"])
    if not periods:
        return
    counter = 0
    for portfolio_id, scheme in PORTFOLIO_DEFINITIONS:
        if scheme == "equal_weight":
            raw = [1.0 for _ in periods]
        elif scheme == "strategy_tilt":
            raw = [
                1.0 / max(STRATEGY_VOLATILITY.get(period["strategy"], 0.20), 0.01)
                for period in periods
            ]
        else:
            raw = [
                STRATEGY_LIQUIDITY.get(period["strategy"], 0.35) for period in periods
            ]
        weights = _normalized(raw)
        for period, weight in zip(periods, weights):
            counter += 1
            tables["portfolio_allocations.csv"].append(
                {
                    "allocation_id": f"ALLOC_SYNTH_{counter:07d}",
                    "portfolio_id": portfolio_id,
                    "as_of_date": as_of.isoformat(),
                    "fund_id": period["fund_id"],
                    "strategy": period["strategy"],
                    "sub_strategy": period["sub_strategy"],
                    "target_weight": _rate(weight),
                    "minimum_weight": "0.00000000",
                    "maximum_weight": _rate(max(0.05, weight * 3.0)),
                    "commitment_amount": period["commitment"],
                    "nav_amount": period["nav"],
                    "unfunded_amount": period["unfunded_commitment"],
                    "expected_return": period["calculated_irr"],
                    "expected_volatility": _rate(
                        STRATEGY_VOLATILITY.get(period["strategy"], 0.20)
                    ),
                    "liquidity_score": _rate(
                        STRATEGY_LIQUIDITY.get(period["strategy"], 0.35)
                    ),
                    "provenance_type": "SYNTHETIC",
                    "source_document_id": "",
                    "synthetic_parameter_set_id": parameter_set_id,
                    "optimization_run_id": f"NOT_OPTIMIZED_BASELINE_{scheme.upper()}",
                    "record_status": "ACTIVE",
                }
            )

def _is_fund_total_cashflow(row: Mapping[str, str], fund_id: str) -> bool:
    """Return true for a fund-total flow, excluding LP and share-class rows."""

    return (
        row.get("fund_id") == fund_id
        and not row.get("lp_id")
        and not row.get("share_class_name")
    )


def inject_defects(
    tables: dict[str, list[dict[str, str]]],
    config: GenerationConfig,
    parameter_set_id: str,
    seed: int,
) -> None:
    periods = tables["fund_periods.csv"]
    if not periods or config.defect_target_rate <= 0:
        return
    rng = random.Random(seed + config.defect_seed_offset)
    # One defect per fund keeps the ground truth readable when a fund reports a
    # long quarterly history: a fund-level defect would otherwise fail every one
    # of its periods and drown the period-level cases in the detection score.
    indices_by_fund: dict[str, list[int]] = defaultdict(list)
    for position, period in enumerate(periods):
        if period.get("perspective", "fund_total") == "fund_total":
            indices_by_fund[period["fund_id"]].append(position)
    fund_ids = sorted(indices_by_fund)
    if not fund_ids:
        return
    defect_count = min(
        len(fund_ids), max(1, int(round(len(fund_ids) * config.defect_target_rate)))
    )
    selected = [
        rng.choice(indices_by_fund[fund_id])
        for fund_id in rng.sample(fund_ids, defect_count)
    ]
    master_by_fund = {row["fund_id"]: row for row in tables["fund_master.csv"]}
    defects: list[dict[str, str]] = []
    for sequence, period_index in enumerate(selected, 1):
        period = periods[period_index]
        fund_id = period["fund_id"]
        defect_type = config.allowed_defects[(sequence - 1) % len(config.allowed_defects)]
        period["defect_expected"] = "true"
        record_table = "fund_periods"
        record_id = period["fund_period_id"]
        field_name = ""
        clean_value = ""
        injected_value = ""

        if defect_type == "tvpi_component_mismatch":
            field_name = "tvpi"
            clean_value = period[field_name]
            period[field_name] = _ratio(float(clean_value) + 0.25)
            injected_value = period[field_name]
        elif defect_type == "dpi_recompute_mismatch":
            field_name = "dpi"
            clean_value = period[field_name]
            period[field_name] = _ratio(float(clean_value) + 0.20)
            injected_value = period[field_name]
        elif defect_type == "rvpi_recompute_mismatch":
            field_name = "rvpi"
            clean_value = period[field_name]
            period[field_name] = _ratio(float(clean_value) + 0.20)
            injected_value = period[field_name]
        elif defect_type == "commitment_reconciliation_mismatch":
            field_name = "unfunded_commitment"
            clean_value = period[field_name]
            period[field_name] = _money(float(clean_value) + float(period["commitment"]) * 0.10)
            injected_value = period[field_name]
        elif defect_type == "nav_rollforward_mismatch":
            field_name = "ending_nav"
            clean_value = period[field_name]
            period[field_name] = _money(float(clean_value) + max(10.0, float(clean_value) * 0.10))
            injected_value = period[field_name]
        elif defect_type == "irr_recompute_mismatch":
            field_name = "reported_irr"
            clean_value = period[field_name]
            period[field_name] = _rate(float(clean_value) + 0.15)
            injected_value = period[field_name]
        elif defect_type == "cashflow_sign_error":
            cashflow = next(
                row
                for row in tables["fund_cashflows.csv"]
                if _is_fund_total_cashflow(row, fund_id)
                and row["cashflow_type"] == "capital_call"
            )
            cashflow["defect_expected"] = "true"
            record_table = "fund_cashflows"
            record_id = cashflow["cashflow_id"]
            field_name = "amount"
            clean_value = cashflow[field_name]
            cashflow[field_name] = _money(abs(float(clean_value)))
            cashflow["amount_base_currency"] = cashflow[field_name]
            injected_value = cashflow[field_name]
        elif defect_type == "impossible_vintage":
            field_name = "vintage_year"
            clean_value = period[field_name]
            period[field_name] = str(config.as_of_date.year + 1)
            master_by_fund[fund_id][field_name] = period[field_name]
            injected_value = period[field_name]
        elif defect_type == "missing_fund_name":
            master = master_by_fund[fund_id]
            record_table = "fund_master"
            record_id = fund_id
            field_name = "fund_name"
            clean_value = master[field_name]
            master[field_name] = ""
            injected_value = "<BLANK>"
        elif defect_type == "duplicate_cashflow":
            original = next(
                row
                for row in tables["fund_cashflows.csv"]
                if _is_fund_total_cashflow(row, fund_id)
            )
            duplicate = dict(original)
            duplicate["cashflow_id"] = f"{original['cashflow_id']}_DUP"
            duplicate["defect_expected"] = "true"
            tables["fund_cashflows.csv"].append(duplicate)
            record_table = "fund_cashflows"
            record_id = duplicate["cashflow_id"]
            field_name = "economic_cashflow"
            clean_value = "unique"
            injected_value = f"duplicate_of:{original['cashflow_id']}"
        elif defect_type == "currency_mismatch":
            cashflow = next(
                row
                for row in tables["fund_cashflows.csv"]
                if _is_fund_total_cashflow(row, fund_id)
            )
            cashflow["defect_expected"] = "true"
            record_table = "fund_cashflows"
            record_id = cashflow["cashflow_id"]
            field_name = "currency"
            clean_value = cashflow[field_name]
            cashflow[field_name] = "EUR" if clean_value != "EUR" else "USD"
            injected_value = cashflow[field_name]
        elif defect_type == "synthetic_real_identity_collision":
            old_fund_id = fund_id
            new_fund_id = f"FUND_REAL_COLLISION_{old_fund_id[-6:]}"
            record_table = "fund_master"
            record_id = new_fund_id
            field_name = "fund_id"
            clean_value = old_fund_id
            injected_value = new_fund_id
            for filename in (
                "fund_master.csv",
                "fund_periods.csv",
                "fund_cashflows.csv",
                "fund_terms.csv",
                "fund_term_clauses.csv",
                "fund_holdings.csv",
                "fund_observations.csv",
                "portfolio_allocations.csv",
            ):
                for row in tables[filename]:
                    if row.get("fund_id") == old_fund_id:
                        row["fund_id"] = new_fund_id
            period["fund_id"] = new_fund_id
            fund_id = new_fund_id
        else:
            raise GenerationError(f"Unhandled defect type: {defect_type}")

        defects.append(
            {
                "defect_id": f"DEFECT_{sequence:06d}",
                "parameter_set_id": parameter_set_id,
                "record_table": record_table,
                "record_id": record_id,
                "fund_id": fund_id,
                "defect_type": defect_type,
                "field_name": field_name,
                "clean_value": clean_value,
                "injected_value": injected_value,
                "expected_rule_id": EXPECTED_RULES[defect_type],
                "seed": str(seed + config.defect_seed_offset),
                "notes": "Deliberate synthetic defect for quality-engine evaluation.",
            }
        )
    tables["defect_injections.csv"] = defects
    _attach_observations(tables, parameter_set_id)


def write_tables(
    output_dir: Path,
    headers: Mapping[str, Sequence[str]],
    tables: Mapping[str, Sequence[Mapping[str, str]]],
    parameter_rows: Sequence[Mapping[str, str]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    materialized: dict[str, Sequence[Mapping[str, str]]] = dict(tables)
    materialized["synthetic_parameters.csv"] = parameter_rows
    sort_keys = {
        "manager_master.csv": ("manager_id",),
        "manager_observations.csv": ("manager_observation_id",),
        "fund_master.csv": ("fund_id",),
        "fund_periods.csv": ("fund_period_id",),
        "fund_cashflows.csv": ("cashflow_date", "cashflow_id"),
        "fund_terms.csv": ("fund_term_id",),
        "fund_term_clauses.csv": ("fund_term_clause_id",),
        "fund_holdings.csv": ("holding_id",),
        "fund_observations.csv": ("observation_id",),
        "benchmark_returns.csv": ("return_date", "benchmark_return_id"),
        "portfolio_allocations.csv": ("allocation_id",),
        "synthetic_parameters.csv": ("parameter_id",),
        "defect_injections.csv": ("defect_id",),
    }
    for filename in FUND_MODEL_FILES:
        rows = list(materialized.get(filename, []))
        keys = sort_keys[filename]
        rows.sort(key=lambda row: tuple(row.get(key, "") for key in keys))
        expected = list(headers[filename])
        for row in rows:
            extras = sorted(set(row) - set(expected))
            if extras:
                raise GenerationError(
                    f"{filename} row contains columns outside the fund-model contract: {extras}"
                )
        target = output_dir / filename
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=expected,
                lineterminator="\n",
                extrasaction="raise",
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/synthetic_generation.yml"),
        help="Synthetic generation configuration.",
    )
    parser.add_argument(
        "--parameters",
        type=Path,
        default=Path("data/csv/synthetic_parameters.csv"),
        help="Calibration parameter CSV.",
    )
    parser.add_argument("--parameter-set-id", help="Active parameter set to use.")
    parser.add_argument(
        "--inventory-ledger",
        type=Path,
        default=Path("ledgers/analysis/document_field_inventory.csv"),
        help="Complete document inventory required by production generation.",
    )
    parser.add_argument(
        "--source-ledger",
        type=Path,
        default=Path("data-gathering/source_ledger.csv"),
        help="Authoritative source IDs used to prove inventory completeness.",
    )
    parser.add_argument(
        "--fund-model-dir",
        type=Path,
        default=Path("data/csv"),
        help="Folder containing fund-model CSV headers.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/synthetic"), help="Output folder."
    )
    parser.add_argument("--count", type=int, help="Override configured fund count.")
    parser.add_argument("--seed", type=int, help="Override configured random seed.")
    parser.add_argument(
        "--allow-assumed-only",
        action="store_true",
        help="Explicit demo exception for a parameter set that lacks extracted calibration.",
    )
    parser.add_argument(
        "--allow-small-demo",
        action="store_true",
        help="Allow fewer than the configured minimum funds for a test or demonstration.",
    )
    parser.add_argument(
        "--inject-defects",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Override the configured deliberate-defect switch.",
    )
    parser.add_argument(
        "--defect-rate",
        type=float,
        help=(
            "Override the configured share of funds that carry one deliberate "
            "defect. Each selected fund receives one."
        ),
    )
    return parser


def run(args: argparse.Namespace) -> dict[str, int]:
    config = read_generation_config(args.config)
    headers = fund_model_headers(args.fund_model_dir)
    parameter_rows = read_csv_rows(args.parameters)
    source_rows = read_csv_rows(args.source_ledger)
    parameter_set_id, selected, strategies = select_and_validate_parameters(
        parameter_rows,
        args.parameter_set_id,
        args.allow_assumed_only,
        source_rows,
    )
    if not args.allow_assumed_only:
        validate_inventory(args.inventory_ledger, args.source_ledger)
    count = args.count if args.count is not None else config.target_fund_count
    seed = args.seed if args.seed is not None else config.seed
    if count <= 0:
        raise GenerationError("Fund count must be positive.")
    if count < config.minimum_fund_count and not args.allow_small_demo:
        raise GenerationError(
            f"Fund count {count} is below configured minimum {config.minimum_fund_count}; "
            "use --allow-small-demo only for tests or demonstrations."
        )
    tables = generate_clean_universe(
        config,
        parameter_set_id,
        selected,
        strategies,
        count,
        seed,
    )
    inject = config.defects_enabled if args.inject_defects is None else args.inject_defects
    if args.defect_rate is not None:
        if not 0.0 <= args.defect_rate <= 1.0:
            raise GenerationError("Defect rate must fall between 0 and 1.")
        config = replace(config, defect_target_rate=args.defect_rate)
    if inject:
        inject_defects(tables, config, parameter_set_id, seed)
    write_tables(args.output_dir, headers, tables, selected)
    counts = {filename: len(tables.get(filename, [])) for filename in FUND_MODEL_FILES}
    counts["synthetic_parameters.csv"] = len(selected)
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        counts = run(args)
    except (GenerationError, OSError) as exc:
        parser.error(str(exc))
    for filename in FUND_MODEL_FILES:
        count = counts.get(filename, 0)
        print(f"{filename}: {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
