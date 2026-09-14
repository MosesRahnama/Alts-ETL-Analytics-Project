"""Read-only analytical explanations from published CSVs and DuckDB files."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .policy import query_definitions
from .types import QueryScope

QUERY_IDS = (
    "fund_evidence",
    "observation_context",
    "result_origin",
    "fund_metrics",
    "document_coverage",
)

TARGET_ID_COLUMNS = {
    "benchmark_returns": "benchmark_return_id",
    "fund_cashflows": "cashflow_id",
    "fund_holdings": "holding_id",
    "fund_master": "fund_id",
    "fund_periods": "fund_period_id",
    "fund_term_clauses": "fund_term_clause_id",
    "fund_terms": "fund_term_id",
}


class AnalyticsUnavailable(RuntimeError):
    execution_state = "DATABASE_UNAVAILABLE"


def _csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise AnalyticsUnavailable(f"required analytical table is absent: {path.name}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _entity_fund_id(entity_id: str, fund_ids: set[str]) -> str:
    if entity_id in fund_ids:
        return entity_id
    return next(
        (fund_id for fund_id in fund_ids if entity_id.startswith(f"POSITION_{fund_id}_")),
        "",
    )


def _source_document(row: dict[str, str]) -> str:
    return row.get("source_document_id") or row.get("file_id") or ""


def _target_owner_document(
    project_root: Path,
    table: str,
    record_id: str,
    masters: dict[str, dict[str, str]],
    cache: dict[str, dict[str, dict[str, str]]],
) -> str:
    id_column = TARGET_ID_COLUMNS.get(table)
    if not id_column or not record_id or table == "benchmark_returns":
        return ""
    if table not in cache:
        cache[table] = {
            row.get(id_column, ""): row
            for row in _csv(project_root / "data/csv" / f"{table}.csv")
        }
    target = cache[table].get(record_id)
    if not target:
        return ""
    fund_id = target.get("fund_id", "") or (record_id if table == "fund_master" else "")
    return _source_document(masters.get(fund_id, {}))


def explain(
    project_root: Path,
    scope: QueryScope,
    query_id: str,
    parameters: dict[str, str],
    data_group: str = "extracted",
) -> dict[str, Any]:
    definitions = query_definitions()
    if query_id not in QUERY_IDS or query_id not in definitions:
        return {"execution_state": "QUERY_UNSUPPORTED", "query_id": query_id, "rows": []}
    if scope.role not in {"reviewer"}:
        raise PermissionError("ACCESS_DENIED")
    permitted = set(scope.permitted_document_ids)
    if not data_group or data_group not in scope.permitted_data_groups:
        raise PermissionError("ACCESS_DENIED")
    query_groups = set(definitions[query_id].get("data_groups") or [])
    if data_group not in query_groups:
        return {
            "execution_state": "QUERY_UNSUPPORTED",
            "query_id": query_id,
            "data_group": data_group,
            "rows": [],
        }
    if query_id == "observation_context":
        observation_id = parameters.get("observation_id", "")
        rows = [
            row
            for row in _csv(project_root / "data/extracted/tables/fact_observation.csv")
            if row.get("observation_id") == observation_id and row.get("document_id") in permitted
        ]
        return {"query_id": query_id, "data_group": data_group, "rows": rows[:50], "origin_labels": ["EXTRACTED"]}
    if query_id == "fund_evidence":
        subject = (parameters.get("subject") or parameters.get("fund_name") or "").lower()
        rows = []
        for row in _csv(project_root / "data/extracted/tables/fact_observation.csv"):
            if row.get("document_id") not in permitted:
                continue
            blob = " ".join(row.get(key) or "" for key in ("subject_name", "subject_standardized_name", "investor_alias_id"))
            if subject and subject not in blob.lower():
                continue
            rows.append(row)
            if len(rows) >= 50:
                break
        return {"query_id": query_id, "data_group": data_group, "rows": rows, "origin_labels": ["EXTRACTED"]}
    if query_id == "result_origin":
        target_table = parameters.get("target_table", "")
        record_id = parameters.get("row_id") or parameters.get("target_record_id", "")
        field = parameters.get("field") or parameters.get("target_field", "")
        candidates = []
        for row in _csv(project_root / "data/integrated/cell-lineage.csv"):
            if target_table and row.get("target_table") != target_table:
                continue
            if record_id and row.get("target_record_id") != record_id:
                continue
            if field and row.get("target_field") != field:
                continue
            candidates.append(row)
        grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
        for row in candidates:
            key = (
                row.get("target_table", ""),
                row.get("target_record_id", ""),
                row.get("target_field", ""),
            )
            grouped.setdefault(key, []).append(row)
        masters = {
            row.get("fund_id", ""): row
            for row in _csv(project_root / "data/csv/fund_master.csv")
        }
        target_cache: dict[str, dict[str, dict[str, str]]] = {}
        rows = []
        for (table, target_id, _field), group in grouped.items():
            source_docs = {_source_document(row) for row in group} - {""}
            if not source_docs:
                owner_document = _target_owner_document(
                    project_root, table, target_id, masters, target_cache
                )
                if owner_document:
                    source_docs = {owner_document}
            if not source_docs or not source_docs.issubset(permitted):
                continue
            rows.extend(group)
            if len(rows) >= 50:
                rows = rows[:50]
                break
        return {"query_id": query_id, "data_group": data_group, "rows": rows, "origin_labels": sorted({row.get("provenance_type", "") for row in rows})}
    if query_id == "fund_metrics":
        fund_id = parameters.get("fund_id", "")
        root = project_root / ("data/extracted/fund-level" if data_group == "extracted" else "data/csv")
        periods = {row.get("fund_period_id", ""): row for row in _csv(root / "fund_periods.csv")}
        cashflows = {row.get("cashflow_id", ""): row for row in _csv(root / "fund_cashflows.csv")}
        masters = {row.get("fund_id", ""): row for row in _csv(root / "fund_master.csv")}
        fund_ids = set(masters)
        rows = []
        for row in _csv(root / "fund_metrics.csv"):
            entity_id = row.get("entity_id", "")
            if fund_id and entity_id != fund_id and not entity_id.startswith(f"POSITION_{fund_id}_"):
                continue
            input_ids = [
                part.strip()
                for part in re.split(r"[|;]", row.get("input_record_ids") or "")
                if part.strip()
            ]
            inputs = [periods.get(item) or cashflows.get(item) for item in input_ids]
            if not input_ids or any(item is None for item in inputs):
                continue
            source_docs = {_source_document(item) for item in inputs if item is not None} - {""}
            owner = masters.get(_entity_fund_id(entity_id, fund_ids))
            owner_document = _source_document(owner) if owner else ""
            if not source_docs and owner_document:
                source_docs = {owner_document}
            if not source_docs or not source_docs.issubset(permitted):
                continue
            rows.append(row)
            if len(rows) >= 50:
                break
        return {"query_id": query_id, "data_group": data_group, "rows": rows, "origin_labels": sorted({row.get("provenance_type", "") for row in rows})}
    if query_id == "document_coverage":
        file_id = parameters.get("file_id", "")
        if file_id and file_id not in permitted:
            raise PermissionError("ACCESS_DENIED")
        ledger = {row["file_id"]: row for row in _csv(project_root / "data-gathering/source_ledger.csv")}
        summary = {row.get("file_id") or row.get("document_id"): row for row in _csv(project_root / "data/extracted/review/document-summary.csv")}
        observations = _csv(project_root / "data/extracted/tables/fact_observation.csv")
        definitions = [row for row in observations if row.get("record_family") == "definition_context"]
        target_ids = [file_id] if file_id else [item for item in permitted]
        rows = []
        for item in target_ids:
            rows.append(
                {
                    "file_id": item,
                    "catalogued": item in ledger,
                    "extracted": item in summary,
                    "observation_count": sum(1 for row in observations if row.get("document_id") == item),
                    "definition_count": sum(1 for row in definitions if row.get("document_id") == item),
                }
            )
        return {"query_id": query_id, "data_group": data_group, "rows": rows, "origin_labels": ["EXTRACTED"]}
    return {"execution_state": "QUERY_UNSUPPORTED", "query_id": query_id, "rows": []}
