"""Build owner-aware normalized holdings without changing source evidence."""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.common import matrices

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TABLE_DIR = PROJECT_ROOT / "data" / "extracted" / "tables"
CSV_DIR = PROJECT_ROOT / "data" / "csv"
EXTRACTED_FUND_DIR = PROJECT_ROOT / "data" / "extracted" / "fund-level"
OWNER_MAP = PROJECT_ROOT / "data" / "normalization" / "holding-owner-map.csv"
REFUSAL_PATH = PROJECT_ROOT / "data" / "extracted" / "audit" / "normalized-holdings-refusals.csv"

OWNER_COLUMNS = (
    "owner_id", "owner_kind", "owner_role", "canonical_name", "source_entity_id",
    "owner_fund_id", "parent_owner_id", "identity_status", "identity_confidence",
    "identity_confidence_basis", "identity_confidence_reason", "decision_id",
    "provenance_type", "source_document_id", "source_page", "source_anchor",
    "synthetic_parameter_set_id", "record_status", "created_at",
)
TARGET_COLUMNS = (
    "target_id", "target_kind", "canonical_name", "printed_name_primary", "legal_name",
    "company_entity_id", "investee_fund_id", "parent_target_id", "sector",
    "canonical_sector", "sub_sector", "country", "identity_status",
    "identity_confidence", "identity_confidence_basis", "identity_confidence_reason",
    "provenance_type", "synthetic_parameter_set_id", "record_status", "created_at",
)
INSTRUMENT_COLUMNS = (
    "instrument_id", "target_id", "instrument_kind", "security_title_raw",
    "security_type_raw", "currency", "seniority", "secured_status", "stated_rate",
    "rate_type", "rate_basis_raw", "spread_bps", "maturity_date_raw", "maturity_date",
    "identifier_type", "identifier_value", "instrument_status", "classification_confidence",
    "classification_confidence_basis", "classification_confidence_reason", "provenance_type",
    "synthetic_parameter_set_id", "record_status",
)
POSITION_COLUMNS = (
    "position_id", "source_holding_id", "owner_id", "owner_fund_id", "instrument_id",
    "position_class", "accounting_scope", "date_role", "date_raw", "date_precision",
    "as_of_date", "report_date", "period_start_date", "period_end_date", "effective_date",
    "quantity_raw", "quantity", "quantity_unit", "currency", "cost", "fair_value",
    "market_value", "reported_value", "realized_proceeds", "commitment",
    "unfunded_commitment", "principal_amount", "notional_amount", "fund_ownership_fraction",
    "portfolio_weight_fraction", "initial_investment_date", "exit_date",
    "classification_confidence", "classification_confidence_basis",
    "classification_confidence_reason", "provenance_type", "origin_type",
    "source_document_id", "source_page", "source_anchor", "synthetic_parameter_set_id",
    "record_status",
)
LOOKTHROUGH_COLUMNS = (
    "lookthrough_id", "root_fund_id", "parent_position_id", "underlying_fund_id",
    "child_position_id", "child_target_id", "as_of_date", "depth", "relationship_type",
    "weight_raw", "weight_fraction", "weight_basis", "effective_exposure_value",
    "effective_exposure_fraction", "coverage_status", "coverage_fraction",
    "relationship_confidence", "relationship_confidence_basis",
    "relationship_confidence_reason", "provenance_type", "formula_id",
    "synthetic_parameter_set_id", "record_status",
)
LINEAGE_COLUMNS = (
    "lineage_id", "record_type", "record_id", "field_name", "value_raw",
    "normalized_value", "provenance_type", "origin_type", "source_holding_id",
    "source_observation_id", "source_document_id", "source_sha256", "source_page",
    "source_table", "source_row_label", "source_column_label", "source_occurrence",
    "evidence_quote", "definition_keys", "pair_id", "pair_status", "adjudication_status",
    "source_agents", "source_review_decision_id", "formula_id", "parent_lineage_ids",
    "matrix_rule_id", "confidence_level", "confidence_basis", "effective_date",
    "available_at", "synthetic_parameter_set_id", "notes",
)
REFUSAL_COLUMNS = (
    "source_holding_id", "source_document_id", "source_page", "holding_label", "subject_type",
    "refusal_code", "refusal_reason", "owner_id", "source_observation_ids",
)

NORMALIZED_FILES = {
    "investment_owner": ("investment_owner.csv", OWNER_COLUMNS, "owner_id"),
    "investment_target": ("investment_target.csv", TARGET_COLUMNS, "target_id"),
    "investment_instrument": ("investment_instrument.csv", INSTRUMENT_COLUMNS, "instrument_id"),
    "fund_position": ("fund_position.csv", POSITION_COLUMNS, "position_id"),
    "lookthrough_edge": ("lookthrough_edge.csv", LOOKTHROUGH_COLUMNS, "lookthrough_id"),
    "holding_field_lineage": ("holding_field_lineage.csv", LINEAGE_COLUMNS, "lineage_id"),
}

POSITION_ADMISSION = "holding-position-admission"
CLASS_RULE = "NORMALIZED_HOLDING_CLASS_V2"
OWNER_RULE = "HOLDING_OWNER_MAP_V1"


class NormalizedHoldingError(RuntimeError):
    pass


def _text(value: object) -> str:
    return str(value or "").strip()


def _stable(prefix: str, *parts: object) -> str:
    payload = "|".join(_text(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20].upper()}"


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise NormalizedHoldingError(f"missing required file: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, object]]) -> int:
    materialized = [{key: _text(row.get(key, "")) for key in columns} for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        writer.writerows(materialized)
    return len(materialized)


def _date(value: object) -> str:
    text = _text(value)
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def _fraction(value: object, *, percent_points: bool = False) -> str:
    text = _text(value)
    if not text:
        return ""
    number = float(text)
    if percent_points:
        number /= 100.0
    return f"{number:.10f}"


def _source_owner_rows(path: Path = OWNER_MAP) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    rows = _read(path)
    by_owner: dict[str, dict[str, str]] = {}
    position_owner: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("decision_status") != "AGENT_REVIEWED":
            raise NormalizedHoldingError(f"unsettled owner decision: {row.get('decision_id')}")
        owner_id = _text(row.get("owner_id"))
        if not owner_id:
            raise NormalizedHoldingError(f"owner decision has no owner_id: {row.get('decision_id')}")
        if owner_id in by_owner:
            raise NormalizedHoldingError(f"duplicate owner_id in owner map: {owner_id}")
        by_owner[owner_id] = row
        if _text(row.get("applies_to_positions")).upper() == "TRUE":
            doc = _text(row.get("source_document_id"))
            if doc in position_owner:
                raise NormalizedHoldingError(f"multiple position owners for {doc}")
            position_owner[doc] = row
    for owner_id, row in by_owner.items():
        parent = _text(row.get("parent_owner_id"))
        if parent and parent not in by_owner:
            raise NormalizedHoldingError(f"owner {owner_id} has missing parent {parent}")
    pending = dict(by_owner)
    ordered: list[dict[str, str]] = []
    written: set[str] = set()
    while pending:
        progressed = False
        for owner_id, row in list(pending.items()):
            parent = _text(row.get("parent_owner_id"))
            if not parent or parent in written:
                ordered.append({
                    "owner_id": owner_id,
                    "owner_kind": row["owner_kind"],
                    "owner_role": row["owner_role"],
                    "canonical_name": row["canonical_name"],
                    "source_entity_id": row.get("source_entity_id", ""),
                    "owner_fund_id": row.get("owner_fund_id", ""),
                    "parent_owner_id": parent,
                    "identity_status": row["identity_status"],
                    "identity_confidence": row["identity_confidence"],
                    "identity_confidence_basis": row.get("source_anchor", ""),
                    "identity_confidence_reason": row.get("decision_reason", ""),
                    "decision_id": row["decision_id"],
                    "provenance_type": row["provenance_type"],
                    "source_document_id": row.get("source_document_id", ""),
                    "source_page": row.get("source_page", ""),
                    "source_anchor": row.get("source_anchor", ""),
                    "synthetic_parameter_set_id": "",
                    "record_status": "ACTIVE",
                    "created_at": "",
                })
                written.add(owner_id)
                del pending[owner_id]
                progressed = True
        if not progressed:
            raise NormalizedHoldingError("owner parent graph contains a cycle")
    return ordered, position_owner


def source_position_owners(path: Path = OWNER_MAP) -> dict[str, dict[str, str]]:
    """Reviewed position owner, keyed by source document."""

    return _source_owner_rows(path)[1]


def _entity_map(rows: Sequence[Mapping[str, str]]) -> dict[str, dict[str, str]]:
    return {row["entity_id"]: dict(row) for row in rows if row.get("entity_id")}


def _linked_observations(
    bridges: Sequence[Mapping[str, str]], observations: Mapping[str, Mapping[str, str]]
) -> dict[str, list[dict[str, str]]]:
    output: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in bridges:
        if row.get("pivot_table") != "fact_holding":
            continue
        obs = observations.get(row.get("observation_id", ""))
        if obs is not None:
            output[row.get("pivot_row_id", "")].append(dict(obs))
    for rows in output.values():
        rows.sort(key=lambda row: (row.get("source_occurrence", ""), row.get("observation_id", "")))
    return output


def _observation(rows: Sequence[Mapping[str, str]], metric: str) -> dict[str, str] | None:
    return next((dict(row) for row in rows if row.get("metric_category") == metric), None)


def _assets(rows: Sequence[Mapping[str, str]]) -> str:
    return " | ".join(sorted({_text(row.get("asset_class")) for row in rows if _text(row.get("asset_class"))}))


def _scopes(rows: Sequence[Mapping[str, str]]) -> str:
    return " | ".join(sorted({_text(row.get("value_scope")) for row in rows if _text(row.get("value_scope"))}))


def holding_admission(value: str, context: str) -> tuple[str, str]:
    """Return the matrix disposition and its source-facing explanation."""

    encoded = matrices.encode(value)
    candidates = matrices.rows_in(POSITION_ADMISSION, context)
    row = next((item for item in candidates if item["input_value"] == encoded), None)
    if row is None:
        row = next((item for item in candidates if item["input_value"] == matrices.STAR), None)
    if row is None:
        raise NormalizedHoldingError(
            f"{POSITION_ADMISSION}: no row for {value!r} under context {context!r}"
        )
    return matrices.decode(row["output_value"]), row.get("note", "")


def _pri_name(label: str) -> str:
    value = re.sub(r"^\d+\s+", "", label.strip())
    return value.split(" - TO ", 1)[0].strip() or value


def _source_classification(
    holding: Mapping[str, str], entity: Mapping[str, str] | None, observations: Sequence[Mapping[str, str]]
) -> dict[str, str]:
    subject = _text(holding.get("subject_type"))
    label = _text(holding.get("holding_label"))
    entity_kind = _text((entity or {}).get("entity_kind"))
    entity_id = _text(holding.get("holding_entity_id"))
    assets = _assets(observations).lower()
    source_table = _text(holding.get("source_table")).lower()
    label_lower = label.lower()
    derivative = "forward contract" in source_table or "forward contract" in label_lower
    debt = "debt securities" in assets
    equity = "equity securities" in assets

    if subject == "fund" and entity_kind == "fund" and entity_id:
        return {
            "target_id": f"TARGET_{entity_id}", "target_kind": "FUND",
            "canonical_name": _text((entity or {}).get("canonical_name")) or label,
            "company_entity_id": "", "investee_fund_id": entity_id,
            "identity_status": "RESOLVED", "identity_confidence": "HIGH",
            "identity_reason": "Reviewed source identity resolves the held name to a fund.",
            "instrument_kind": "FUND_INTEREST", "position_class": "FUND_INTEREST",
        }
    if derivative:
        is_named_counterparty = entity_kind == "company" and "contract" not in label_lower
        return {
            "target_id": f"TARGET_{entity_id}" if is_named_counterparty else _stable("TARGET_DERIVATIVE", holding["holding_id"]),
            "target_kind": "COUNTERPARTY" if is_named_counterparty else "UNRESOLVED",
            "canonical_name": _text((entity or {}).get("canonical_name")) if is_named_counterparty else label,
            "company_entity_id": entity_id if is_named_counterparty else "", "investee_fund_id": "",
            "identity_status": "RESOLVED" if is_named_counterparty else "UNRESOLVED",
            "identity_confidence": "HIGH" if is_named_counterparty else "LOW",
            "identity_reason": "Named derivative counterparty." if is_named_counterparty else "The row names a derivative type, not a resolved counterparty.",
            "instrument_kind": "DERIVATIVE", "position_class": "DERIVATIVE",
        }
    if debt:
        return {
            "target_id": _stable("TARGET_DEBT", holding["holding_id"]), "target_kind": "UNRESOLVED",
            "canonical_name": label, "company_entity_id": "", "investee_fund_id": "",
            "identity_status": "UNRESOLVED", "identity_confidence": "LOW",
            "identity_reason": "The printed row is a security title; the current company alias is not treated as issuer identity.",
            "instrument_kind": "OTHER_DEBT", "position_class": "DEBT_INVESTMENT",
        }
    if entity_kind == "company" and entity_id:
        return {
            "target_id": f"TARGET_{entity_id}", "target_kind": "PORTFOLIO_COMPANY",
            "canonical_name": _text((entity or {}).get("canonical_name")) or label,
            "company_entity_id": entity_id, "investee_fund_id": "",
            "identity_status": "RESOLVED", "identity_confidence": "HIGH",
            "identity_reason": "Reviewed source identity resolves the held name to a company.",
            "instrument_kind": "OTHER_EQUITY" if equity or subject == "investment" else "OTHER",
            "position_class": "DIRECT_COMPANY",
        }
    if subject == "program_related_investment":
        return {
            "target_id": _stable("TARGET_PRI", _pri_name(label)), "target_kind": "OTHER",
            "canonical_name": _pri_name(label), "company_entity_id": "", "investee_fund_id": "",
            "identity_status": "PROVISIONAL", "identity_confidence": "MEDIUM",
            "identity_reason": "The source names a program-related investment counterparty but the entity registry has no settled identity.",
            "instrument_kind": "OTHER", "position_class": "OTHER",
        }
    return {
        "target_id": _stable("TARGET_SOURCE", holding["holding_id"]), "target_kind": "UNRESOLVED",
        "canonical_name": label, "company_entity_id": "", "investee_fund_id": "",
        "identity_status": "UNRESOLVED", "identity_confidence": "LOW",
        "identity_reason": "The source row has no settled investee identity.",
        "instrument_kind": "UNCLASSIFIED", "position_class": "UNCLASSIFIED",
    }


def _accounting_scope(owner: Mapping[str, str]) -> str:
    if _text(owner.get("owner_fund_id")):
        return "fund_total"
    if owner.get("owner_kind") == "plan":
        return "plan_total"
    return "portfolio_total"


def _lineage_row(
    *, record_type: str, record_id: str, field_name: str, value_raw: object = "",
    normalized_value: object = "", provenance_type: str, origin_type: str,
    source_holding_id: str = "", observation: Mapping[str, str] | None = None,
    document_sha: str = "", decision_id: str = "", formula_id: str = "",
    parent_lineage_ids: str = "", matrix_rule_id: str = "", confidence: str = "HIGH",
    confidence_basis: str = "", synthetic_parameter_set_id: str = "", notes: str = "",
    observation_lineage: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, str]:
    obs = dict(observation or {})
    ol = dict((observation_lineage or {}).get(obs.get("observation_id", ""), {}))
    source_document_id = obs.get("document_id", "")
    source_page = obs.get("source_page", "")
    source_observation_id = obs.get("observation_id", "")
    payload = (
        record_type, record_id, field_name, source_holding_id, source_observation_id,
        decision_id, formula_id, matrix_rule_id, synthetic_parameter_set_id,
    )
    return {
        "lineage_id": _stable("HFL", *payload), "record_type": record_type,
        "record_id": record_id, "field_name": field_name, "value_raw": _text(value_raw),
        "normalized_value": _text(normalized_value), "provenance_type": provenance_type,
        "origin_type": origin_type, "source_holding_id": source_holding_id,
        "source_observation_id": source_observation_id, "source_document_id": source_document_id,
        "source_sha256": document_sha, "source_page": source_page,
        "source_table": obs.get("source_table", ""), "source_row_label": obs.get("source_row_label", ""),
        "source_column_label": obs.get("source_column_label", ""),
        "source_occurrence": obs.get("source_occurrence", ""), "evidence_quote": obs.get("evidence_quote", ""),
        "definition_keys": obs.get("definition_keys", ""), "pair_id": ol.get("pair_id", ""),
        "pair_status": ol.get("pair_status", ""), "adjudication_status": ol.get("adjudication_status", ""),
        "source_agents": ol.get("source_agents", "") or obs.get("source_agents", ""),
        "source_review_decision_id": decision_id, "formula_id": formula_id,
        "parent_lineage_ids": parent_lineage_ids, "matrix_rule_id": matrix_rule_id,
        "confidence_level": confidence, "confidence_basis": confidence_basis,
        "effective_date": "", "available_at": "", "synthetic_parameter_set_id": synthetic_parameter_set_id,
        "notes": notes,
    }


def _owner_lineage(
    owner_rows: Sequence[Mapping[str, str]], owner_map_rows: Sequence[Mapping[str, str]],
    observations: Mapping[str, Mapping[str, str]], documents: Mapping[str, Mapping[str, str]],
    observation_lineage: Mapping[str, Mapping[str, str]],
) -> list[dict[str, str]]:
    decisions = {row["owner_id"]: row for row in owner_map_rows}
    output: list[dict[str, str]] = []
    for owner in owner_rows:
        decision = decisions[owner["owner_id"]]
        match = re.search(r"fact_observation:([0-9a-f]+)", decision.get("source_anchor", ""))
        obs = observations.get(match.group(1), {}) if match else {}
        provenance = owner["provenance_type"]
        output.append(_lineage_row(
            record_type="OWNER", record_id=owner["owner_id"], field_name="canonical_name",
            value_raw=owner["canonical_name"], normalized_value=owner["canonical_name"],
            provenance_type=provenance, origin_type="SOURCE_REVIEW", observation=obs,
            document_sha=_text(documents.get(owner.get("source_document_id", ""), {}).get("source_sha256")),
            decision_id=owner.get("decision_id", ""), matrix_rule_id=OWNER_RULE if provenance == "DERIVED" else "",
            confidence=owner["identity_confidence"], confidence_basis=owner.get("source_anchor", ""),
            notes=owner.get("identity_confidence_reason", ""), observation_lineage=observation_lineage,
        ))
    return output


def build_source_rows(
    table_dir: Path = TABLE_DIR, owner_map_path: Path = OWNER_MAP,
) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    holdings = _read(table_dir / "fact_holding.csv")
    observations_list = _read(table_dir / "fact_observation.csv")
    observations = {row["observation_id"]: row for row in observations_list}
    bridges = _read(PROJECT_ROOT / "data" / "extracted" / "wide" / "bridge_pivot_observation.csv")
    linked = _linked_observations(bridges, observations)
    entities = _entity_map(_read(table_dir / "dim_entity.csv"))
    document_rows = _read(table_dir / "dim_document.csv")
    documents = {row["document_id"]: row for row in document_rows}
    observation_lineage_rows = _read(table_dir / "observation_lineage.csv")
    observation_lineage = {row["observation_id"]: row for row in observation_lineage_rows}
    owner_map_rows = _read(owner_map_path)
    owners, position_owners = _source_owner_rows(owner_map_path)

    targets: dict[str, dict[str, str]] = {}
    instruments: list[dict[str, str]] = []
    positions: list[dict[str, str]] = []
    refusals: list[dict[str, str]] = []
    lineages = _owner_lineage(owners, owner_map_rows, observations, documents, observation_lineage)

    for holding in holdings:
        holding_id = holding["holding_id"]
        doc = holding["document_id"]
        obs_rows = linked.get(holding_id, [])
        owner = position_owners.get(doc)
        obs_ids = ";".join(row["observation_id"] for row in obs_rows)
        disposition, reason = holding_admission(_text(holding.get("subject_type")), "subject_type")
        if disposition != "ADMIT":
            refusals.append({
                "source_holding_id": holding_id, "source_document_id": doc,
                "source_page": holding.get("source_page", ""), "holding_label": holding.get("holding_label", ""),
                "subject_type": holding.get("subject_type", ""), "refusal_code": disposition,
                "refusal_reason": reason,
                "owner_id": owner.get("owner_id", "") if owner else "", "source_observation_ids": obs_ids,
            })
            continue
        refused_scope: tuple[str, str] | None = None
        for scope in {_text(row.get("value_scope")) for row in obs_rows} or {""}:
            scope_disposition, scope_reason = holding_admission(scope, "value_scope")
            if scope_disposition != "ADMIT":
                refused_scope = (scope_disposition, scope_reason)
                break
        if refused_scope is not None:
            disposition, reason = refused_scope
            refusals.append({
                "source_holding_id": holding_id, "source_document_id": doc,
                "source_page": holding.get("source_page", ""), "holding_label": holding.get("holding_label", ""),
                "subject_type": holding.get("subject_type", ""), "refusal_code": disposition,
                "refusal_reason": reason,
                "owner_id": owner.get("owner_id", "") if owner else "", "source_observation_ids": obs_ids,
            })
            continue
        if owner is None:
            refusals.append({
                "source_holding_id": holding_id, "source_document_id": doc,
                "source_page": holding.get("source_page", ""), "holding_label": holding.get("holding_label", ""),
                "subject_type": holding.get("subject_type", ""), "refusal_code": "OWNER_MISSING",
                "refusal_reason": "No reviewed reporting owner exists for this document.",
                "owner_id": "", "source_observation_ids": obs_ids,
            })
            continue

        entity = entities.get(holding.get("holding_entity_id", ""))
        cls = _source_classification(holding, entity, obs_rows)
        target_id = cls["target_id"]
        target = {
            "target_id": target_id, "target_kind": cls["target_kind"],
            "canonical_name": cls["canonical_name"], "printed_name_primary": holding.get("holding_label", ""),
            "legal_name": "", "company_entity_id": cls["company_entity_id"],
            "investee_fund_id": cls["investee_fund_id"], "parent_target_id": "",
            "sector": holding.get("sector", ""), "canonical_sector": "", "sub_sector": "", "country": "",
            "identity_status": cls["identity_status"], "identity_confidence": cls["identity_confidence"],
            "identity_confidence_basis": f"fact_holding:{holding_id}; dim_entity:{holding.get('holding_entity_id','')}",
            "identity_confidence_reason": cls["identity_reason"], "provenance_type": "DERIVED",
            "synthetic_parameter_set_id": "", "record_status": "ACTIVE", "created_at": "",
        }
        existing = targets.get(target_id)
        if existing is None:
            targets[target_id] = target
        else:
            for field in ("target_kind", "canonical_name", "company_entity_id", "investee_fund_id"):
                if _text(existing.get(field)) != _text(target.get(field)):
                    raise NormalizedHoldingError(f"target collision {target_id}.{field}: {existing.get(field)!r} vs {target.get(field)!r}")

        rate_obs = _observation(obs_rows, "interest_rate")
        maturity_obs = _observation(obs_rows, "maturity_date")
        stated_rate = ""
        if holding.get("interest_rate"):
            percent = bool(rate_obs and (rate_obs.get("value_kind") == "percent" or rate_obs.get("unit") == "%"))
            stated_rate = _fraction(holding.get("interest_rate"), percent_points=percent)
        maturity_raw = holding.get("maturity_date_raw", "")
        maturity = _date(maturity_raw)
        instrument_id = _stable("INSTR_SOURCE", holding_id)
        instruments.append({
            "instrument_id": instrument_id, "target_id": target_id, "instrument_kind": cls["instrument_kind"],
            "security_title_raw": holding.get("holding_label", ""), "security_type_raw": "",
            "currency": holding.get("currency", ""), "seniority": "", "secured_status": "",
            "stated_rate": stated_rate, "rate_type": "", "rate_basis_raw": "", "spread_bps": "",
            "maturity_date_raw": maturity_raw, "maturity_date": maturity, "identifier_type": "",
            "identifier_value": "", "instrument_status": "ACTIVE",
            "classification_confidence": cls["identity_confidence"],
            "classification_confidence_basis": f"asset_class={_assets(obs_rows)}; source_table={holding.get('source_table','')}",
            "classification_confidence_reason": cls["identity_reason"], "provenance_type": "DERIVED",
            "synthetic_parameter_set_id": "", "record_status": "ACTIVE",
        })

        date_value = holding.get("as_of_date", "")
        quantity_obs = _observation(obs_rows, "quantity")
        weight_obs = _observation(obs_rows, "portfolio_weight")
        position_id = _stable("POS_SOURCE", holding_id)
        source_anchor = next((row.get("evidence_quote", "") for row in obs_rows if row.get("evidence_quote")), "")
        positions.append({
            "position_id": position_id, "source_holding_id": holding_id, "owner_id": owner["owner_id"],
            "owner_fund_id": owner.get("owner_fund_id", ""), "instrument_id": instrument_id,
            "position_class": cls["position_class"], "accounting_scope": _accounting_scope(owner),
            "date_role": "as_of" if date_value else "static_no_date",
            "date_raw": holding.get("as_of_date_raw", ""), "date_precision": "day" if date_value else "unknown",
            "as_of_date": date_value, "report_date": "", "period_start_date": "", "period_end_date": "",
            "effective_date": "", "quantity_raw": quantity_obs.get("value_raw", "") if quantity_obs else "",
            "quantity": holding.get("quantity", ""), "quantity_unit": quantity_obs.get("unit", "") if quantity_obs else "",
            "currency": holding.get("currency", ""), "cost": holding.get("cost", ""),
            "fair_value": holding.get("fair_value", ""), "market_value": holding.get("market_value", ""),
            "reported_value": "", "realized_proceeds": "", "commitment": "", "unfunded_commitment": "",
            "principal_amount": "", "notional_amount": holding.get("notional_amount", ""),
            "fund_ownership_fraction": "",
            "portfolio_weight_fraction": _fraction(holding.get("portfolio_weight"), percent_points=True),
            "initial_investment_date": "", "exit_date": "",
            "classification_confidence": cls["identity_confidence"],
            "classification_confidence_basis": f"source_holding={holding_id}; owner_decision={owner['decision_id']}",
            "classification_confidence_reason": cls["identity_reason"], "provenance_type": "EXTRACTED",
            "origin_type": "SOURCE_NORMALIZED", "source_document_id": doc,
            "source_page": holding.get("source_page", ""), "source_anchor": source_anchor,
            "synthetic_parameter_set_id": "", "record_status": "ACTIVE",
        })

        first_obs = obs_rows[0] if obs_rows else None
        doc_sha = _text(documents.get(doc, {}).get("source_sha256"))
        lineages.extend([
            _lineage_row(record_type="TARGET", record_id=target_id, field_name="target_kind",
                         value_raw=holding.get("subject_type", ""), normalized_value=cls["target_kind"],
                         provenance_type="DERIVED", origin_type="MATRIX_NORMALIZATION",
                         source_holding_id=holding_id, observation=first_obs, document_sha=doc_sha,
                         matrix_rule_id=CLASS_RULE, confidence=cls["identity_confidence"],
                         confidence_basis=cls["identity_reason"], observation_lineage=observation_lineage),
            _lineage_row(record_type="INSTRUMENT", record_id=instrument_id, field_name="instrument_kind",
                         value_raw=_assets(obs_rows), normalized_value=cls["instrument_kind"],
                         provenance_type="DERIVED", origin_type="MATRIX_NORMALIZATION",
                         source_holding_id=holding_id, observation=first_obs, document_sha=doc_sha,
                         matrix_rule_id=CLASS_RULE, confidence=cls["identity_confidence"],
                         confidence_basis=cls["identity_reason"], observation_lineage=observation_lineage),
            _lineage_row(record_type="POSITION", record_id=position_id, field_name="owner_id",
                         value_raw=owner["canonical_name"], normalized_value=owner["owner_id"],
                         provenance_type="DERIVED", origin_type="SOURCE_REVIEW",
                         source_holding_id=holding_id, observation=first_obs, document_sha=doc_sha,
                         decision_id=owner["decision_id"], matrix_rule_id=OWNER_RULE,
                         confidence=owner["identity_confidence"], confidence_basis=owner["source_anchor"],
                         observation_lineage=observation_lineage),
            _lineage_row(record_type="POSITION", record_id=position_id, field_name="position_class",
                         value_raw=holding.get("subject_type", ""), normalized_value=cls["position_class"],
                         provenance_type="DERIVED", origin_type="MATRIX_NORMALIZATION",
                         source_holding_id=holding_id, observation=first_obs, document_sha=doc_sha,
                         matrix_rule_id=CLASS_RULE, confidence=cls["identity_confidence"],
                         confidence_basis=cls["identity_reason"], observation_lineage=observation_lineage),
        ])
        metric_fields = {
            "cost": ("POSITION", position_id, "cost", False),
            "fair_value": ("POSITION", position_id, "fair_value", False),
            "market_value": ("POSITION", position_id, "market_value", False),
            "notional": ("POSITION", position_id, "notional_amount", False),
            "quantity": ("POSITION", position_id, "quantity", False),
            "portfolio_weight": ("POSITION", position_id, "portfolio_weight_fraction", True),
            "interest_rate": ("INSTRUMENT", instrument_id, "stated_rate", True),
            "maturity_date": ("INSTRUMENT", instrument_id, "maturity_date_raw", False),
        }
        for obs in obs_rows:
            spec = metric_fields.get(obs.get("metric_category", ""))
            if spec is None:
                continue
            record_type, record_id, field_name, normalized = spec
            raw = obs.get("value_raw", "")
            if obs.get("metric_category") == "portfolio_weight":
                value = _fraction(obs.get("value_numeric", ""), percent_points=True)
                provenance, origin, formula = "DERIVED", "FORMULA", "PERCENT_TO_FRACTION_V1"
            elif obs.get("metric_category") == "interest_rate" and (obs.get("value_kind") == "percent" or obs.get("unit") == "%"):
                value = _fraction(obs.get("value_numeric", ""), percent_points=True)
                provenance, origin, formula = "DERIVED", "FORMULA", "PERCENT_TO_FRACTION_V1"
            else:
                value = obs.get("value_numeric", "") or obs.get("value_text", "") or raw
                provenance, origin, formula = "EXTRACTED", "DIRECT_SOURCE", ""
            lineages.append(_lineage_row(
                record_type=record_type, record_id=record_id, field_name=field_name,
                value_raw=raw, normalized_value=value, provenance_type=provenance, origin_type=origin,
                source_holding_id=holding_id, observation=obs, document_sha=doc_sha, formula_id=formula,
                confidence="HIGH", confidence_basis="Accepted source observation",
                observation_lineage=observation_lineage,
            ))
        if maturity_obs and maturity:
            raw_line = next((row for row in reversed(lineages) if row["record_id"] == instrument_id and row["field_name"] == "maturity_date_raw"), None)
            lineages.append(_lineage_row(
                record_type="INSTRUMENT", record_id=instrument_id, field_name="maturity_date",
                value_raw=maturity_raw, normalized_value=maturity, provenance_type="DERIVED",
                origin_type="FORMULA", source_holding_id=holding_id, observation=maturity_obs,
                document_sha=doc_sha, formula_id="PARSE_DATE_V1",
                parent_lineage_ids=raw_line["lineage_id"] if raw_line else "", confidence="HIGH",
                confidence_basis="Deterministic date parse", observation_lineage=observation_lineage,
            ))

    output = {
        "investment_owner": owners,
        "investment_target": sorted(targets.values(), key=lambda row: row["target_id"]),
        "investment_instrument": sorted(instruments, key=lambda row: row["instrument_id"]),
        "fund_position": sorted(positions, key=lambda row: row["position_id"]),
        "lookthrough_edge": [],
        "holding_field_lineage": sorted(lineages, key=lambda row: row["lineage_id"]),
    }
    return output, sorted(refusals, key=lambda row: row["source_holding_id"])


def write_source(
    output_dir: Path = CSV_DIR, refusal_path: Path = REFUSAL_PATH,
    table_dir: Path = TABLE_DIR, owner_map_path: Path = OWNER_MAP,
) -> dict[str, int]:
    tables, refusals = build_source_rows(table_dir, owner_map_path)
    counts: dict[str, int] = {}
    for table, (filename, columns, _key) in NORMALIZED_FILES.items():
        counts[filename] = _write(output_dir / filename, columns, tables[table])
    counts[refusal_path.name] = _write(refusal_path, REFUSAL_COLUMNS, refusals)
    return counts


def _synthetic_instrument_kind(security_type: str) -> tuple[str, str]:
    value = security_type.strip().lower()
    if value in {"senior debt", "unitranche", "loan", "debt"}:
        return "LOAN", "DEBT_INVESTMENT"
    if value == "preferred equity":
        return "PREFERRED_EQUITY", "DIRECT_COMPANY"
    if value in {"equity", "common equity"}:
        return "OTHER_EQUITY", "DIRECT_COMPANY"
    return "OTHER", "OTHER"


def build_flat_rows(
    holdings: Sequence[Mapping[str, str]], fund_master: Sequence[Mapping[str, str]], *, origin_type: str,
) -> dict[str, list[dict[str, str]]]:
    masters = {row["fund_id"]: dict(row) for row in fund_master if row.get("fund_id")}
    owners: dict[str, dict[str, str]] = {}
    targets: dict[str, dict[str, str]] = {}
    instruments: dict[str, dict[str, str]] = {}
    positions: list[dict[str, str]] = []
    lineages: list[dict[str, str]] = []
    for holding in holdings:
        fund_id = _text(holding.get("fund_id"))
        master = masters.get(fund_id)
        if master is None:
            raise NormalizedHoldingError(f"generated holding has unknown owner fund: {holding.get('holding_id')}")
        parameter_set = _text(holding.get("synthetic_parameter_set_id"))
        owner_id = f"OWNER_{fund_id}"
        master_provenance = _text(master.get("provenance_type"))
        owner_provenance = "SYNTHETIC" if master_provenance == "SYNTHETIC" else "DERIVED"
        owners.setdefault(owner_id, {
            "owner_id": owner_id, "owner_kind": "fund", "owner_role": "REPORTING_FUND",
            "canonical_name": master.get("fund_name", "") or fund_id, "source_entity_id": fund_id,
            "owner_fund_id": fund_id, "parent_owner_id": "", "identity_status": "RESOLVED",
            "identity_confidence": "HIGH", "identity_confidence_basis": "fund_master.fund_id",
            "identity_confidence_reason": "The generated holding owner is the fund_id carried by fund_holdings.",
            "decision_id": "GENERATED_FROM_FUND_MASTER", "provenance_type": owner_provenance,
            "source_document_id": master.get("source_document_id", "") if owner_provenance != "SYNTHETIC" else "",
            "source_page": master.get("source_page", "") if owner_provenance != "SYNTHETIC" else "",
            "source_anchor": master.get("source_anchor", "") if owner_provenance != "SYNTHETIC" else "",
            "synthetic_parameter_set_id": master.get("synthetic_parameter_set_id", "") if owner_provenance == "SYNTHETIC" else "",
            "record_status": "ACTIVE", "created_at": "",
        })
        company_id = _text(holding.get("portfolio_company_id"))
        company_name = _text(holding.get("portfolio_company_name")) or _text(holding.get("instrument_name")) or holding["holding_id"]
        target_id = f"TARGET_{company_id}" if company_id else _stable("TARGET_GENERATED", fund_id, company_name)
        provenance = _text(holding.get("provenance_type")) or "SYNTHETIC"
        targets.setdefault(target_id, {
            "target_id": target_id, "target_kind": "PORTFOLIO_COMPANY",
            "canonical_name": company_name, "printed_name_primary": company_name, "legal_name": "",
            "company_entity_id": company_id, "investee_fund_id": "", "parent_target_id": "",
            "sector": holding.get("sector", ""), "canonical_sector": holding.get("canonical_sector", ""),
            "sub_sector": "", "country": holding.get("geography", ""), "identity_status": "RESOLVED",
            "identity_confidence": "HIGH", "identity_confidence_basis": "generated holding identity",
            "identity_confidence_reason": "The generated holding supplies one explicit portfolio company identity or name.",
            "provenance_type": provenance, "synthetic_parameter_set_id": parameter_set if provenance == "SYNTHETIC" else "",
            "record_status": "ACTIVE", "created_at": "",
        })
        security_type = _text(holding.get("security_type"))
        instrument_kind, position_class = _synthetic_instrument_kind(security_type)
        raw_instrument_id = _text(holding.get("instrument_id"))
        instrument_id = f"NORM_{raw_instrument_id}" if raw_instrument_id else _stable("INSTR_GENERATED", holding["holding_id"])
        instruments.setdefault(instrument_id, {
            "instrument_id": instrument_id, "target_id": target_id, "instrument_kind": instrument_kind,
            "security_title_raw": holding.get("instrument_name", ""), "security_type_raw": security_type,
            "currency": holding.get("currency", ""), "seniority": "", "secured_status": "",
            "stated_rate": holding.get("interest_rate", ""), "rate_type": "", "rate_basis_raw": "",
            "spread_bps": holding.get("spread_bps", ""), "maturity_date_raw": holding.get("maturity_date", ""),
            "maturity_date": _date(holding.get("maturity_date", "")), "identifier_type": "", "identifier_value": "",
            "instrument_status": "ACTIVE", "classification_confidence": "HIGH",
            "classification_confidence_basis": "generated security_type", "classification_confidence_reason": security_type or "generated holding",
            "provenance_type": provenance, "synthetic_parameter_set_id": parameter_set if provenance == "SYNTHETIC" else "",
            "record_status": "ACTIVE",
        })
        position_id = _stable("POS_GENERATED", holding["holding_id"])
        positions.append({
            "position_id": position_id, "source_holding_id": "", "owner_id": owner_id,
            "owner_fund_id": fund_id, "instrument_id": instrument_id, "position_class": position_class,
            "accounting_scope": "fund_total", "date_role": holding.get("date_role", "") or "as_of",
            "date_raw": holding.get("date_raw", ""), "date_precision": holding.get("date_precision", "") or "day",
            "as_of_date": holding.get("as_of_date", ""), "report_date": holding.get("report_date", ""),
            "period_start_date": holding.get("period_start_date", ""), "period_end_date": holding.get("period_end_date", ""),
            "effective_date": holding.get("effective_date", ""), "quantity_raw": "", "quantity": "", "quantity_unit": "",
            "currency": holding.get("currency", ""), "cost": holding.get("cost", ""), "fair_value": holding.get("fair_value", ""),
            "market_value": "", "reported_value": "", "realized_proceeds": "", "commitment": "",
            "unfunded_commitment": "", "principal_amount": holding.get("principal_amount", ""), "notional_amount": "",
            "fund_ownership_fraction": holding.get("ownership_percent", ""), "portfolio_weight_fraction": "",
            "initial_investment_date": "", "exit_date": "", "classification_confidence": "HIGH",
            "classification_confidence_basis": "generated holding schema", "classification_confidence_reason": security_type or "generated holding",
            "provenance_type": provenance, "origin_type": origin_type,
            "source_document_id": holding.get("source_document_id", ""), "source_page": holding.get("source_page", ""),
            "source_anchor": holding.get("source_anchor", ""),
            "synthetic_parameter_set_id": parameter_set if provenance == "SYNTHETIC" else "", "record_status": "ACTIVE",
        })
        if origin_type != "SYNTHETIC_FIXTURE":
            for field in ("owner_id", "position_class", "cost", "fair_value", "principal_amount", "fund_ownership_fraction"):
                value = positions[-1].get(field, "")
                if not _text(value):
                    continue
                lineages.append(_lineage_row(
                    record_type="POSITION", record_id=position_id, field_name=field,
                    value_raw=value, normalized_value=value, provenance_type=provenance,
                    origin_type=origin_type, source_holding_id=holding["holding_id"],
                    synthetic_parameter_set_id=parameter_set if provenance == "SYNTHETIC" else "",
                    confidence="HIGH", confidence_basis="Generated fund_holdings row",
                    notes=f"compatibility holding {holding['holding_id']}",
                ))
    return {
        "investment_owner": sorted(owners.values(), key=lambda row: row["owner_id"]),
        "investment_target": sorted(targets.values(), key=lambda row: row["target_id"]),
        "investment_instrument": sorted(instruments.values(), key=lambda row: row["instrument_id"]),
        "fund_position": sorted(positions, key=lambda row: row["position_id"]),
        "lookthrough_edge": [],
        "holding_field_lineage": sorted(lineages, key=lambda row: row["lineage_id"]),
    }


def write_flat(
    holdings_path: Path, fund_master_path: Path, output_dir: Path, *, origin_type: str,
) -> dict[str, int]:
    tables = build_flat_rows(_read(holdings_path), _read(fund_master_path), origin_type=origin_type)
    counts: dict[str, int] = {}
    for table, (filename, columns, _key) in NORMALIZED_FILES.items():
        counts[filename] = _write(output_dir / filename, columns, tables[table])
    return counts


def merge_rows(
    source_dir: Path, generated: Mapping[str, Sequence[Mapping[str, str]]], output_dir: Path,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, (filename, columns, key) in NORMALIZED_FILES.items():
        source_rows = _read(source_dir / filename)
        merged: dict[str, dict[str, str]] = {row[key]: dict(row) for row in source_rows}
        for row in generated.get(table, ()): 
            record_id = _text(row.get(key))
            if record_id not in merged:
                merged[record_id] = dict(row)
        rows = list(merged.values())
        if table == "investment_owner":
            # Parent rows precede children so DuckDB self-FK insertion remains deterministic.
            rows.sort(key=lambda row: (bool(row.get("parent_owner_id")), row[key]))
        else:
            rows.sort(key=lambda row: row[key])
        counts[filename] = _write(output_dir / filename, columns, rows)
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=CSV_DIR)
    parser.add_argument("--refusal-path", type=Path, default=REFUSAL_PATH)
    args = parser.parse_args(argv)
    counts = write_source(args.output_dir, args.refusal_path)
    print("PASS: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
