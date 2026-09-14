"""Real-manager and real-fund scopes for the GP Scoring evidence search."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _manager_key(manager_name: str) -> str:
    digest = hashlib.sha256(manager_name.encode("utf-8")).hexdigest()[:16]
    return f"manager-name:{digest}"


def _document_record(row: dict[str, str], file_id: str) -> dict[str, str]:
    return {
        "file_id": file_id,
        "filename": row.get("filename", ""),
        "doc_type": row.get("doc_type", ""),
        "issuer": row.get("issuer", ""),
        "issuer_type": row.get("issuer_type", ""),
        "period_covered": row.get("period_covered", ""),
        "page_count": row.get("page_count", ""),
    }


def load_real_gp_context(project_root: Path, permitted_document_ids: Iterable[str]) -> dict[str, Any]:
    """Return source-backed managers, funds, and documents within one session scope."""

    permitted = {str(value).strip() for value in permitted_document_ids if str(value).strip()}
    source_rows = _read_rows(project_root / "data-gathering" / "source_ledger.csv")
    source_by_file = {
        row.get("file_id", "").strip(): row
        for row in source_rows
        if row.get("file_id", "").strip() in permitted
    }

    context_by_fund: dict[tuple[str, str], dict[str, str]] = {}
    for row in _read_rows(project_root / "data" / "csv" / "document_entity_context.csv"):
        key = (row.get("file_id", "").strip(), row.get("fund_id", "").strip())
        if key[0] in permitted and key[1] and row.get("manager_name", "").strip():
            context_by_fund[key] = row

    gp_fallbacks: dict[str, list[dict[str, str]]] = {}
    for row in _read_rows(project_root / "data" / "csv" / "document_manager_map.csv"):
        file_id = row.get("file_id", "").strip()
        if (
            file_id in permitted
            and row.get("relationship_role", "").strip() == "general_partner"
            and row.get("adjudication_status", "").strip() == "RESOLVED"
            and row.get("manager_name_raw", "").strip()
        ):
            gp_fallbacks.setdefault(file_id, []).append(row)

    funds: list[dict[str, Any]] = []
    managers: dict[str, dict[str, Any]] = {}
    for row in _read_rows(project_root / "data" / "csv" / "fund_master.csv"):
        file_id = row.get("source_document_id", "").strip()
        fund_id = row.get("fund_id", "").strip()
        if (
            file_id not in permitted
            or row.get("provenance_type", "").strip() != "EXTRACTED"
            or row.get("record_status", "").strip() != "ACTIVE"
            or not fund_id
        ):
            continue

        manager_name = row.get("fund_manager_name", "").strip()
        manager_id = row.get("fund_manager_id", "").strip()
        manager_source = "fund_master"
        context = context_by_fund.get((file_id, fund_id))
        if context is not None:
            manager_name = context.get("manager_name", "").strip()
            manager_id = context.get("manager_id", "").strip() or manager_id
            manager_source = "document_entity_context"
        elif not manager_name and source_by_file.get(file_id, {}).get("issuer_type", "").strip() == "gp":
            candidates = gp_fallbacks.get(file_id, [])
            if len(candidates) == 1:
                manager_name = candidates[0].get("manager_name_raw", "").strip()
                manager_id = candidates[0].get("manager_id", "").strip()
                manager_source = "document_manager_map"

        key = _manager_key(manager_name) if manager_name else ""
        document = _document_record(source_by_file.get(file_id, {}), file_id)
        fund = {
            "fund_id": fund_id,
            "fund_name": row.get("fund_name", "").strip(),
            "manager_key": key,
            "manager_id": manager_id,
            "manager_name": manager_name,
            "manager_name_source": manager_source if manager_name else "not_named",
            "strategy": row.get("strategy", "").strip(),
            "sub_strategy": row.get("sub_strategy", "").strip(),
            "vintage_year": row.get("vintage_year", "").strip(),
            "source_document_id": file_id,
            "source_page": row.get("source_page", "").strip(),
            "source_anchor": row.get("source_anchor", "").strip(),
            "documents": [document],
        }
        funds.append(fund)
        if not manager_name:
            continue
        group = managers.setdefault(
            key,
            {
                "manager_key": key,
                "manager_ids": set(),
                "manager_names": Counter(),
                "funds": [],
                "documents": {},
            },
        )
        if manager_id:
            group["manager_ids"].add(manager_id)
        group["manager_names"][manager_name] += 1
        group["funds"].append(fund)
        group["documents"][file_id] = document

    manager_rows: list[dict[str, Any]] = []
    for group in managers.values():
        names = sorted(group.pop("manager_names").items(), key=lambda item: (-item[1], item[0].casefold()))
        manager_ids = sorted(group.pop("manager_ids"))
        group["manager_name"] = names[0][0]
        group["manager_id"] = manager_ids[0] if len(manager_ids) == 1 else ""
        group["manager_ids"] = manager_ids
        group["manager_name_variants"] = [name for name, _count in names]
        group["funds"] = sorted(group["funds"], key=lambda item: (item["fund_name"].casefold(), item["fund_id"]))
        group["fund_count"] = len(group["funds"])
        group["documents"] = sorted(group["documents"].values(), key=lambda item: item["file_id"])
        group["document_count"] = len(group["documents"])
        manager_rows.append(group)

    manager_rows.sort(key=lambda item: (item["manager_name"].casefold(), item["manager_key"]))
    funds.sort(key=lambda item: (item["fund_name"].casefold(), item["fund_id"]))
    fund_documents = sorted({fund["source_document_id"] for fund in funds})
    return {
        "execution_state": "OK" if funds else "EMPTY_RESULTS",
        "manager_count": len(manager_rows),
        "fund_count": len(funds),
        "fund_document_count": len(fund_documents),
        "permitted_document_count": len(permitted),
        "managers": manager_rows,
        "funds": funds,
    }


def resolve_real_gp_scope(
    context: dict[str, Any],
    *,
    manager_key: str = "",
    fund_id: str = "",
) -> dict[str, Any] | None:
    """Resolve one submitted real-manager or real-fund selector to source documents."""

    if fund_id:
        fund = next((row for row in context.get("funds", []) if row.get("fund_id") == fund_id), None)
        if fund is None:
            return None
        return {
            "scope_type": "fund",
            "scope_key": fund_id,
            "scope_name": fund.get("fund_name", ""),
            "manager_name": fund.get("manager_name", ""),
            "fund_id": fund_id,
            "file_ids": tuple(row["file_id"] for row in fund.get("documents", [])),
            "documents": fund.get("documents", []),
        }
    if manager_key:
        manager = next(
            (row for row in context.get("managers", []) if row.get("manager_key") == manager_key),
            None,
        )
        if manager is None:
            return None
        return {
            "scope_type": "manager",
            "scope_key": manager_key,
            "scope_name": manager.get("manager_name", ""),
            "manager_name": manager.get("manager_name", ""),
            "fund_id": "",
            "file_ids": tuple(row["file_id"] for row in manager.get("documents", [])),
            "documents": manager.get("documents", []),
        }
    return None
