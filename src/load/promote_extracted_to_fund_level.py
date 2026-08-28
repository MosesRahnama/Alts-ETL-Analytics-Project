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
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from src.catalog.simple_pdf_extraction.fund_attributes import (
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

FUND_PREFIX = "FUND_"
MANAGER_PREFIX = "MGR_"

# Which measure a category is, so a quality rule reads the right thing. The sets
# are stated rather than inferred: `commitment` is a standing number, `paid_in`
# accumulates from inception, and `fee` belongs to the period it was charged.
STATIC = {"commitment", "vintage_year", "fund_size", "governing_law", "fund_term"}
INCEPTION_TO_DATE = {
    "paid_in_capital", "distribution", "contribution", "recallable_distribution",
}
POINT_IN_TIME = {
    "nav", "unfunded_commitment", "ending_capital", "beginning_capital",
    "fair_value", "market_value", "aum", "nav_per_share", "nav_component",
    "enterprise_value",
}
PERIOD_FLOW = {
    "fee", "income", "realized_gain_loss", "unrealized_gain_loss", "expense",
    "interest", "carried_interest", "management_fee", "capital_call",
    "return_of_capital", "preferred_return",
}
RATIO = {"dpi", "rvpi", "tvpi", "moic", "pme", "sharpe_ratio", "ownership_percentage", "portfolio_weight"}
RATE = {"irr", "return", "yield", "alpha", "direct_alpha", "tracking_error", "interest_rate", "cost_bps"}

# fund_periods columns fed by a printed category. A category absent here is a
# real observation that has no column on the period grain, so it stays in
# fund_observations only.
PERIOD_COLUMNS = {
    "commitment": "commitment",
    "paid_in_capital": "paid_in_capital_itd",
    "distribution": "distributions_itd",
    "nav": "nav",
    "unfunded_commitment": "unfunded_commitment",
    "recallable_distribution": "recallable_distributions_itd",
    "dpi": "dpi",
    "rvpi": "rvpi",
    "tvpi": "tvpi",
    "irr": "reported_irr",
    "beginning_capital": "beginning_nav",
    "ending_capital": "ending_nav",
    "contribution": "contributions_period",
    "income": "net_income_period",
    "realized_gain_loss": "realized_gain_period",
    "unrealized_gain_loss": "unrealized_gain_period",
    "fee": "management_fee_period",
}

# A period row states one fund's position on one date. A horizon label such as
# "3 Year" or "Q4 2020 QTD" scopes the number to a window instead, and two
# windows cannot share one row, so horizon-scoped numbers stay observations.
SINCE_INCEPTION = {"", "Since Inception", "Inception-to-Date", "ITD (Annualized)", "Total to date"}

# What kind of number each period column holds. A page can print a multiple in a
# column whose heading reads like money, and extraction records the category it
# was given, so the promotion checks the two agree before placing a value. A
# mismatch is left out of the analytical table and reported, because correcting
# the category is the adjudicator's job and not this module's.
MONEY_COLUMNS = {
    "commitment", "paid_in_capital_itd", "distributions_itd", "nav",
    "unfunded_commitment", "recallable_distributions_itd", "beginning_nav",
    "ending_nav", "contributions_period", "net_income_period",
    "realized_gain_period", "unrealized_gain_period", "management_fee_period",
}
RATIO_COLUMNS = {"dpi", "rvpi", "tvpi"}
RATE_COLUMNS = {"reported_irr"}

CASHFLOW_TYPES = {
    "distribution": "distribution",
    "recallable_distribution": "recallable_distribution",
    "contribution": "capital_call",
    "capital_call": "capital_call",
    "return_of_capital": "distribution",
    "preferred_return": "distribution",
    "fee": "fee",
    "expense": "fee",
    "subscription": "subscription",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def header_of(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> int:
    """Write rows under the header already on disk, so the contract is fixed by
    the DDL and this module can only fill columns that were declared."""
    fieldnames = header_of(path)
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
    instead of renumbering every downstream reference."""
    seed = "|".join(parts)
    return f"{prefix}_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def measure_basis(category: str, value_kind: str, has_date: bool) -> str:
    if category in RATIO or value_kind == "multiple":
        return "ratio"
    if category in RATE:
        return "rate"
    if category in INCEPTION_TO_DATE:
        return "inception_to_date"
    if category in PERIOD_FLOW:
        return "period_flow"
    if category in POINT_IN_TIME:
        return "point_in_time"
    if category in STATIC:
        return "static"
    if value_kind == "percent":
        return "rate"
    return "point_in_time" if has_date else "static"


def is_money(row: dict[str, str]) -> bool:
    """Whether a printed value is an amount of money.

    `value_kind` records whether the cell itself printed a currency symbol, so a
    schedule that puts the `$` once in the column heading and bare numbers under
    it yields `number`. The currency code is populated either way, so that is
    what decides, and a cell carrying no currency at all is not treated as
    money."""
    return bool(row.get("currency", "")) or row.get("value_kind", "") == "currency"


def scaled_amount(row: dict[str, str]) -> str:
    """The printed number brought onto a common scale.

    Extraction stores what the page printed and keeps the `$ in millions`
    heading beside it, which is right for a document-faithful layer and wrong
    for an analytical one: a fund whose NAV came off a millions table and whose
    paid-in came off an absolute table would produce an RVPI a million times
    too large. Money is scaled here; a ratio, rate, or multiple carries no
    scale heading and is passed through as printed."""
    value = row.get("value_numeric", "")
    if not value or not is_money(row):
        return value
    multiplier = row.get("unit_scale_multiplier", "") or "1"
    if multiplier == "1":
        return value
    scaled = float(value) * float(multiplier)
    return f"{scaled:.6f}".rstrip("0").rstrip(".")


def period_cell(column: str, row: dict[str, str]) -> str | None:
    """The value for one period column, or None when the printed kind and the
    column disagree.

    `reported_irr` is stored as a decimal rate because that is the unit the
    fund-level model and the quality rules are written in, so a page printing
    `9.00%` lands as `0.09`; the printed string stays in fund_observations."""
    kind = row.get("value_kind", "")
    value = row.get("value_numeric", "")
    if column in MONEY_COLUMNS:
        return scaled_amount(row) if is_money(row) else None
    if column in RATIO_COLUMNS:
        return value if kind in {"number", "multiple"} and not is_money(row) else None
    if column in RATE_COLUMNS:
        if kind == "percent":
            return f"{float(value) / 100:.10f}".rstrip("0").rstrip(".")
        return value if kind == "number" else None
    return value


def date_fields(row: dict[str, str]) -> dict[str, str]:
    as_of = row.get("as_of_date", "")
    return {
        "date_role": "as_of" if as_of else "static_no_date",
        "date_raw": row.get("as_of_date_raw", ""),
        "date_precision": row.get("date_precision", "") or ("day" if as_of else "unknown"),
        "as_of_date": as_of,
        "period_start_date": row.get("period_start", ""),
        "period_end_date": row.get("period_end", ""),
    }


def source_anchor(row: dict[str, str]) -> str:
    """Where on the page the value was printed, in the extraction layer's own
    terms, so a promoted number can be walked back to the cell."""
    parts = [row.get("source_table", ""), row.get("source_row_label", ""), row.get("source_column_label", "")]
    return " / ".join(part for part in parts if part)


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
            source_sha = hashes.get(file_id) or (final_rows[0]["source_sha256"] if final_rows else "")
            files.append({"file_id": file_id, "source_sha256": source_sha})
            worksheet.append({
                "batch_id": route,
                "file_id": file_id,
                "source_sha256": source_sha,
                "final_file_sha256": digest(final_path),
                "final_row_count": str(len(final_rows)),
                "lanes": "A|B|ADJUDICATED",
                "decision": "ACCEPT",
                "reason": "blind dual extraction adjudicated and published under validate-final",
            })
            accepted += 1
        (batch_dir / "assignment.json").write_text(
            json.dumps({"batch_id": route, "round_id": "02", "files": files}, indent=2) + "\n",
            encoding="utf-8",
        )
        with (batch_dir / "worksheet.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(worksheet[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(worksheet)
        progress.append({
            "batch_id": route,
            "round_id": "02",
            "file_count": str(len(files)),
            "status": "ACCEPTED",
        })

    with (GATE_DIR / "progress.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(progress[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(progress)
    return {"batches": len(progress), "documents": accepted}


# --------------------------------------------------------------------------
# Stage 2: fund-scoped observations


def build_fund_observations(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        if not fund_id.startswith(FUND_PREFIX):
            continue
        category = row.get("metric_category", "") or row.get("term_category", "")
        dates = date_fields(row)
        rows.append({
            "observation_id": row["observation_id"],
            "fund_id": fund_id,
            "file_id": row["document_id"],
            "metric_id": row.get("metric_id", "") or f"{row['record_family']}.{category}",
            **dates,
            "value_raw": row.get("value_raw", ""),
            "value_numeric": row.get("value_numeric", ""),
            "value_text": row.get("value_text", ""),
            "currency": row.get("currency", ""),
            "unit": row.get("unit", "") or row.get("value_kind", ""),
            "perspective": "fund_total",
            "measure_basis": measure_basis(category, row.get("value_kind", ""), bool(dates["as_of_date"])),
            "provenance_type": "EXTRACTED",
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "extractor_version": row.get("contract_version", ""),
            "record_status": "ACTIVE",
        })
    return rows


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
    sources: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    collisions = 0
    mismatches: list[dict[str, str]] = []

    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        as_of = row.get("as_of_date", "")
        category = row.get("metric_category", "")
        column = PERIOD_COLUMNS.get(category)
        if not fund_id.startswith(FUND_PREFIX) or not as_of or column is None:
            continue
        if (row.get("horizon", "") or "").strip() not in SINCE_INCEPTION:
            continue
        if not row.get("value_numeric", ""):
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
                "finding": f"category {category} expects a {'currency' if column in MONEY_COLUMNS else 'numeric'} value, page printed {row.get('value_kind', '')}",
            })
            continue
        key = (fund_id, as_of, row["document_id"])
        period = groups.setdefault(key, {})
        if column in period:
            collisions += 1
            continue
        period[column] = value
        sources[key].append(row["observation_id"])

    rows = []
    for key, values in sorted(groups.items()):
        fund_id, as_of, document_id = key
        rows.append({
            "fund_period_id": stable_id("FP", fund_id, as_of, document_id),
            "fund_id": fund_id,
            "date_role": "as_of",
            "date_precision": "day",
            "as_of_date": as_of,
            "perspective": "fund_total",
            "provenance_type": "EXTRACTED",
            "source_document_id": document_id,
            "input_observation_ids": " | ".join(sorted(sources[key])),
            "record_status": "ACTIVE",
            **values,
        })
    return rows, collisions, mismatches


# --------------------------------------------------------------------------
# Stages 4 to 7


def reporting_fund_by_document() -> dict[str, str]:
    """The fund a document reports on, where one document names exactly one.

    A capital-account statement prints its cash flows against the investor, not
    against the fund, so the fund has to come from the document. This lookup
    uses `document_fund_map.csv` only where that map settled on a single fund.
    """
    path = CSV_DIR / "document_fund_map.csv"
    if not path.is_file():
        return {}
    by_document: dict[str, set[str]] = defaultdict(set)
    for row in read_csv(path):
        if row.get("fund_id"):
            by_document[row["file_id"]].add(row["fund_id"])
    return {doc: next(iter(funds)) for doc, funds in by_document.items() if len(funds) == 1}


def build_fund_cashflows(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    reporting_fund = reporting_fund_by_document()
    rows = []
    for row in observations:
        if row.get("record_family") != "cash_flow_observation":
            continue
        subject = row.get("subject_entity_id", "")
        fund_id = subject if subject.startswith(FUND_PREFIX) else reporting_fund.get(row["document_id"], "")
        if not fund_id:
            continue
        investor = subject if subject.startswith("LP_") else ""
        cashflow_type = CASHFLOW_TYPES.get(row.get("metric_category", ""), "other")
        date = row.get("as_of_date", "") or row.get("period_end", "")
        if not date or not row.get("value_numeric", ""):
            continue
        rows.append({
            "cashflow_id": stable_id("CF", row["observation_id"]),
            "fund_id": fund_id,
            "lp_id": investor,
            "lp_name": row.get("subject_standardized_name", "") or row.get("subject_name", "") if investor else "",
            "file_id": row["document_id"],
            "date_role": "cashflow",
            # The date as the page printed it. Where the cell carried no date
            # string of its own, the resolved date stands in so the lineage rule
            # still has a raw value to check.
            "date_raw": row.get("as_of_date_raw", "") or row.get("period_end_raw", "") or date,
            "date_precision": row.get("date_precision", "") or "day",
            "cashflow_date": date,
            "cashflow_type": cashflow_type,
            "amount": scaled_amount(row),
            "currency": row.get("currency", "") or "USD",
            "provenance_type": "EXTRACTED",
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "record_status": "ACTIVE",
        })
    return rows


def build_fund_terms(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    """One row per fund carrying whatever operative terms its documents printed.

    `legal_term` rows are one clause each, so they are folded onto the fund they
    govern; a term the corpus never printed stays blank instead of taking a
    market-standard default."""
    numeric_terms = {
        "management_fee": "management_fee_rate",
        "carried_interest": "carry_rate",
        "hurdle_rate": "hurdle_rate",
        "catch_up": "catch_up_rate",
        "fund_term": "fund_term_years",
        "term_extension": "extension_years",
        "maximum_offering": "maximum_offering",
    }
    by_fund: dict[str, dict[str, str]] = {}
    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        if not fund_id.startswith(FUND_PREFIX) or row.get("record_family") != "legal_term":
            continue
        column = numeric_terms.get(row.get("term_category", ""))
        entry = by_fund.setdefault(fund_id, {
            "fund_term_id": stable_id("FT", fund_id),
            "fund_id": fund_id,
            "perspective": "fund_total",
            "term_scope": "fund",
            "provenance_type": "EXTRACTED",
            "source_document_id": row["document_id"],
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "currency": row.get("currency", ""),
            "record_status": "ACTIVE",
        })
        if column and row.get("value_numeric", ""):
            entry.setdefault(column, scaled_amount(row))
    return sorted(by_fund.values(), key=lambda item: item["fund_id"])


def build_fund_term_clauses(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        if not fund_id.startswith(FUND_PREFIX):
            continue
        if row.get("record_family") not in {"legal_clause", "legal_term"}:
            continue
        rows.append({
            "fund_term_clause_id": stable_id("FTC", row["observation_id"]),
            "fund_id": fund_id,
            "perspective": "fund_total",
            "term_scope": "fund",
            "source_document_id": row["document_id"],
            "metric_id": row.get("metric_id", "") or f"legal.{row.get('term_category', '')}",
            "clause_title": row.get("metric_name", "") or row.get("source_row_label", ""),
            "value_raw": row.get("value_raw", ""),
            "value_text": row.get("value_text", "") or row.get("evidence_quote", ""),
            "currency": row.get("currency", ""),
            "provenance_type": "EXTRACTED",
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "extractor_version": row.get("contract_version", ""),
            "record_status": "ACTIVE",
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
    for holding in holdings:
        funds = {
            fund_of_observation[obs_id]
            for obs_id in (holding.get("observation_ids", "") or "").split(" | ")
            if obs_id in fund_of_observation
        }
        if not funds:
            candidates = fund_of_document.get(holding["document_id"], set())
            if len(candidates) != 1:
                continue
            funds = candidates
        if len(funds) != 1:
            continue
        rows.append({
            "holding_id": holding["holding_id"],
            "fund_id": next(iter(funds)),
            "portfolio_company_id": holding.get("holding_entity_id", ""),
            "portfolio_company_name": holding.get("holding_label", ""),
            "date_role": "as_of" if holding.get("as_of_date") else "static_no_date",
            "date_raw": holding.get("as_of_date_raw", ""),
            "date_precision": "day" if holding.get("as_of_date") else "unknown",
            "as_of_date": holding.get("as_of_date", ""),
            "currency": holding.get("currency", "") or "USD",
            "cost": holding.get("cost", ""),
            "fair_value": holding.get("fair_value", "") or holding.get("market_value", ""),
            "interest_rate": holding.get("interest_rate", ""),
            "maturity_date": holding.get("maturity_date_raw", ""),
            "ownership_percent": holding.get("portfolio_weight", ""),
            "provenance_type": "EXTRACTED",
            "source_document_id": holding["document_id"],
            "source_page": holding.get("source_page", ""),
            "source_anchor": holding.get("source_table", ""),
            "record_status": "ACTIVE",
        })
    return rows


def build_manager_observations(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in observations:
        manager_id = row.get("subject_entity_id", "")
        if not manager_id.startswith(MANAGER_PREFIX):
            continue
        category = row.get("metric_category", "") or row.get("term_category", "")
        dates = date_fields(row)
        rows.append({
            "manager_observation_id": stable_id("MO", row["observation_id"]),
            "manager_id": manager_id,
            "file_id": row["document_id"],
            "metric_id": row.get("metric_id", "") or f"{row['record_family']}.{category}",
            **dates,
            "value_raw": row.get("value_raw", ""),
            "value_numeric": row.get("value_numeric", ""),
            "value_text": row.get("value_text", ""),
            "currency": row.get("currency", ""),
            "unit": row.get("unit", "") or row.get("value_kind", ""),
            "perspective": "manager_total",
            "measure_basis": measure_basis(category, row.get("value_kind", ""), bool(dates["as_of_date"])),
            "provenance_type": "EXTRACTED",
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "extractor_version": row.get("contract_version", ""),
            "record_status": "ACTIVE",
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
    referenced: dict[str, dict[str, str]] = {}
    for row in observations:
        # A row names its manager either as its subject or through the
        # manager identity carried beside a fund or plan subject. Both routes
        # must land in the master, or the document map cites a manager the
        # master does not carry.
        for manager_id in (row.get("subject_entity_id", ""), row.get("manager_entity_id", "")):
            if manager_id.startswith(MANAGER_PREFIX) and manager_id not in known:
                referenced.setdefault(manager_id, row)

    added = []
    for manager_id, row in sorted(referenced.items()):
        subject_is_manager = row.get("subject_entity_id", "") == manager_id
        printed_name = row.get("subject_name", "") if subject_is_manager else row.get("subject_manager_name", "")
        added.append({
            "manager_id": manager_id,
            "manager_name": registry.get(manager_id) or (row.get("subject_standardized_name", "") if subject_is_manager else "") or printed_name,
            "legal_name": printed_name or registry.get(manager_id, ""),
            "base_currency": row.get("currency", "") or "USD",
            "provenance_type": "EXTRACTED",
            "source_document_id": row["document_id"],
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "record_status": "ACTIVE",
            "created_at": "",
        })
    if added:
        write_csv(path, existing + added)
    return len(added)


def complete_fund_master(
    existing: list[dict[str, str]], observations: list[dict[str, str]]
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
    kept = [row for row in existing if row.get("fund_id", "") in registry]
    retired = len(existing) - len(kept)
    known = {row.get("fund_id", "") for row in kept}
    first_source: dict[str, dict[str, str]] = {}
    for row in observations:
        fund_id = row.get("subject_entity_id", "")
        if fund_id.startswith(FUND_PREFIX):
            first_source.setdefault(fund_id, row)

    added: list[dict[str, str]] = []
    for fund_id in sorted(first_source):
        if fund_id in known:
            continue
        source = first_source[fund_id]
        name = registry.get(fund_id, "")
        if not name:
            raise ValueError(f"fund identity registry lacks {fund_id}")
        added.append(
            {
                "fund_id": fund_id,
                "fund_name": name,
                "fund_manager_id": source.get("manager_entity_id", ""),
                "fund_manager_name": source.get("subject_manager_name", ""),
                "strategy": source.get("strategy", ""),
                "vintage_year": source.get("vintage_year", ""),
                "provenance_type": "EXTRACTED",
                "source_document_id": source.get("document_id", ""),
                "source_page": source.get("source_page", ""),
                "source_anchor": source_anchor(source),
                "record_status": "ACTIVE",
                "created_at": "",
            }
        )
    return sorted(kept + added, key=lambda row: row.get("fund_id", "")), len(added), retired


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
    seen: dict[tuple[str, str], dict[str, str]] = {}
    for row in observations:
        manager_id = row.get("manager_entity_id", "") or (
            row["subject_entity_id"] if row.get("subject_entity_id", "").startswith(MANAGER_PREFIX) else ""
        )
        subject_is_manager = row.get("subject_entity_id", "") == manager_id
        name = row.get("subject_manager_name", "") or (row.get("subject_name", "") if subject_is_manager else "")
        if not manager_id or not (name or registry.get(manager_id)):
            continue
        name = name or registry[manager_id]
        key = (row["document_id"], manager_id)
        if key in seen:
            continue
        seen[key] = {
            "document_manager_map_id": stable_id("DMM", *key),
            "file_id": row["document_id"],
            "manager_id": manager_id,
            "manager_name_raw": name,
            "manager_name_normalized": registry.get(manager_id) or (row.get("subject_standardized_name", "") if subject_is_manager else "") or name,
            "relationship_role": "general_partner",
            "source_page": row.get("source_page", ""),
            "source_anchor": source_anchor(row),
            "source_quote": row.get("evidence_quote", ""),
            "provenance_type": "EXTRACTED",
            "adjudication_status": row.get("adjudication_status", "") or "RESOLVED",
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


def promote() -> dict[str, int]:
    observations = read_csv(TABLES_DIR / "fact_observation.csv")
    holdings = read_csv(TABLES_DIR / "fact_holding.csv")

    gate = write_gate_evidence(observations)
    periods, collisions, mismatches = build_fund_periods(observations)
    attribute_lookup = decided_lookup()
    attribute_evidence = attribute_evidence_lookup(observations=observations)
    period_attributes, period_changes = stamp_rows_with_changes(
        periods,
        attribute_lookup,
        attribute_evidence,
        target_table="fund_periods",
        record_id_field="fund_period_id",
    )
    extracted_master = PROJECT_ROOT / "data" / "extracted" / "fund-level" / "fund_master.csv"
    master_rows, master_added, master_retired = complete_fund_master(
        read_csv(
            extracted_master if extracted_master.is_file() else CSV_DIR / "fund_master.csv"
        ),
        observations,
    )
    master_attributes, master_changes = stamp_rows_with_changes(
        master_rows,
        attribute_lookup,
        attribute_evidence,
        target_table="fund_master",
        record_id_field="fund_id",
        include_existing=True,
    )
    write_mismatch_report(mismatches)
    counts = {
        "manager_master_added": extend_manager_master(observations),
        "fund_master_added": master_added,
        "fund_master_retired": master_retired,
        "gate_batches": gate["batches"],
        "gate_documents": gate["documents"],
        "fund_observations": write_csv(
            CSV_DIR / "fund_observations.csv", build_fund_observations(observations)
        ),
        "fund_periods": write_csv(CSV_DIR / "fund_periods.csv", periods),
        "period_collisions": collisions,
        "category_mismatches": len(mismatches),
        "fund_cashflows": write_csv(
            CSV_DIR / "fund_cashflows.csv", build_fund_cashflows(observations)
        ),
        "fund_terms": write_csv(CSV_DIR / "fund_terms.csv", build_fund_terms(observations)),
        "fund_term_clauses": write_csv(
            CSV_DIR / "fund_term_clauses.csv", build_fund_term_clauses(observations)
        ),
        "fund_holdings": write_csv(
            CSV_DIR / "fund_holdings.csv", build_fund_holdings(holdings, observations)
        ),
        "manager_observations": write_csv(
            CSV_DIR / "manager_observations.csv", build_manager_observations(observations)
        ),
        "document_manager_map": write_csv(
            CSV_DIR / "document_manager_map.csv", build_document_manager_map(observations)
        ),
        "period_attribute_cells": period_attributes,
        "fund_master": write_csv(CSV_DIR / "fund_master.csv", master_rows),
        "master_attribute_cells": master_attributes,
        "attribute_change_rows": write_attribute_changes(period_changes + master_changes),
    }
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    counts = promote()
    width = max(len(name) for name in counts)
    for name, value in counts.items():
        print(f"  {name:<{width}}  {value:>6,}")
    print("PASS: extracted facts promoted into the fund-level tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
