"""Write a bounded static evidence export without runtime secrets or restricted sources."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import model_configuration, model_is_configured
from .paths import EVALUATION_DIR
from .policy import access_policy, retrieval_policy
from .types import QueryResult


def _context_requirements(raw: str) -> list[str]:
    return [part.strip().lower() for part in (raw or "").split("|") if part.strip()]


def _matches_required_context(item: dict, raw: str) -> bool:
    requirements = _context_requirements(raw)
    if not requirements:
        return False
    text = str(item.get("original_text") or "").lower()
    kind = str(item.get("block_kind") or "").lower()
    page = str(item.get("physical_page") or "")
    for requirement in requirements:
        if requirement in {"note", "footnote"} and kind not in {"note", "footnote"}:
            return False
        if requirement.startswith("page:") and page != requirement.split(":", 1)[1]:
            return False
        if requirement.startswith("kind:") and kind != requirement.split(":", 1)[1]:
            return False
        if requirement.startswith("block:") and str(item.get("block_id") or "").lower() != requirement.split(":", 1)[1]:
            return False
        if requirement.startswith("text:") and requirement.split(":", 1)[1] not in text:
            return False
    return True


def _case_evidence(example: dict[str, Any], results: list[dict], restricted: set[str]) -> list[dict]:
    expected_pages = {
        int(part) for part in str(example.get("expected_pages") or "").split("|") if part.isdigit()
    }
    candidates: list[dict] = []
    for result in results:
        candidates.append(result)
        candidates.extend(result.get("context") or [])
    eligible: list[dict] = []
    seen: set[str] = set()
    for item in candidates:
        block_id = str(item.get("block_id") or "")
        file_id = str(item.get("file_id") or "")
        if not block_id or block_id in seen or file_id in restricted or file_id not in example["file_ids"]:
            continue
        if item.get("block_kind") == "page" or item.get("instruction_like"):
            continue
        seen.add(block_id)
        eligible.append(
            {
                "case_id": example["case_id"],
                "block_id": block_id,
                "file_id": file_id,
                "physical_page": item.get("physical_page"),
                "original_text": str(item.get("original_text") or "")[:800],
                "block_kind": item.get("block_kind"),
                "required_context_match": _matches_required_context(
                    item, str(example.get("required_context") or "")
                ),
            }
        )
    selected: list[dict] = []
    if expected_pages:
        selected.extend(
            item for item in eligible
            if int(item.get("physical_page") or 0) in expected_pages
        )
    selected = selected[:1]
    required = next(
        (item for item in eligible if item["required_context_match"] and item not in selected),
        None,
    )
    if required is not None:
        selected.append(required)
    for item in eligible:
        if len(selected) == 2:
            break
        if item not in selected and (not expected_pages or int(item.get("physical_page") or 0) in expected_pages):
            selected.append(item)
    for item in selected:
        item.pop("required_context_match", None)
    return selected


def export_demo(
    project_root: Path,
    search_result: QueryResult | None = None,
    engine=None,
    destination: Path | None = None,
) -> Path:
    cases_path = EVALUATION_DIR / "cases.csv"
    results_path = EVALUATION_DIR / "results.csv"
    policy = access_policy()
    restricted = set(policy.get("export_restricted_file_ids") or [])
    examples = []
    if cases_path.is_file():
        with cases_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("publication_permission") != "permitted":
                    continue
                file_ids = [part.strip() for part in (row.get("file_ids") or "").split("|") if part.strip()]
                if not file_ids or any(file_id in restricted for file_id in file_ids):
                    continue
                examples.append(
                    {
                        "case_id": row["case_id"],
                        "split": row["split"],
                        "query": row["query"],
                        "file_ids": file_ids,
                        "expected_pages": row.get("expected_pages", ""),
                        "required_context": row.get("required_context", ""),
                        "reference_label": "human_reference",
                        "reference_checked_by": row.get("reference_checked_by", ""),
                    }
                )
    permitted = sorted({file_id for example in examples for file_id in example["file_ids"]})
    evidence: list[dict] = []
    if engine is not None and permitted:
        scope = engine.issue_session("reviewer", purpose="static export", document_ids=tuple(permitted))
        for example in examples:
            result = engine.search_sources(
                scope.session_id,
                example["query"],
                file_ids=tuple(example["file_ids"]),
                result_limit=5,
            )
            if result.execution_state == "OK":
                evidence.extend(_case_evidence(example, result.results, restricted))
    elif search_result is not None:
        for example in examples:
            evidence.extend(_case_evidence(example, search_result.results, restricted))
    config = model_configuration()
    retrieval = retrieval_policy()
    engine_status = engine.status() if engine is not None else {}
    vector_available = bool(engine_status.get("vector_enabled"))
    summary_path = EVALUATION_DIR / "summary.json"
    try:
        evaluation_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        evaluation_summary = {}
    payload: dict[str, Any] = {
        "permitted_document_ids": permitted,
        "evidence": evidence,
        "examples": examples,
        "limits": {
            "model_requests": "disabled",
            "loopback_probes": "disabled",
            "vector_retrieval": "available locally" if vector_available else "not built",
            "hybrid_default": bool(retrieval.get("hybrid_default")) and vector_available,
        },
        "evaluation_summary": evaluation_summary,
        "index_summary": {
            "catalogued_documents": (engine_status.get("coverage") or {}).get("catalogued_documents", 0),
            "indexed_documents": (engine_status.get("coverage") or {}).get("indexed_documents", 0),
            "restricted_documents": (engine_status.get("coverage") or {}).get("restricted_documents", 0),
            "indexed_pages": (engine_status.get("coverage") or {}).get("indexed_pages", 0),
            "block_count": (engine_status.get("coverage") or {}).get("block_count", 0),
            "vector_documents": (engine_status.get("coverage") or {}).get("vector_documents", 0),
            "vector_blocks": (engine_status.get("coverage") or {}).get("vector_blocks", 0),
            "embedding_model": (engine_status.get("embedding") or {}).get("model", ""),
            "embedding_revision": (engine_status.get("embedding") or {}).get("revision", ""),
        },
        "result_labels": {
            "human_reference": "Source answer checked against the native PDF",
            "offline_keyword": "Deterministic keyword retrieval",
            "model": f"{config['model_name']} selected; provider contract unverified",
        },
    }
    measured = []
    if results_path.is_file():
        with results_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("publication_permission") != "permitted":
                    continue
                if row.get("result") == "unrun" or row.get("execution_state") == "MODEL_DISABLED":
                    continue
                if row.get("configuration") == "approved_assessor":
                    if not model_is_configured(config) or row.get("model_version") != config["model_id"]:
                        continue
                measured.append(
                    {
                        "case_id": row.get("case_id"),
                        "configuration": row.get("configuration"),
                        "execution_state": row.get("execution_state"),
                        "result": row.get("result"),
                        "label": row.get("label") or "fixture",
                    }
                )
    payload["measured"] = measured
    path = destination or (EVALUATION_DIR / "public-demo.json")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
