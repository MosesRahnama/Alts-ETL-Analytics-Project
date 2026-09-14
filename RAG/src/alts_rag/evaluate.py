"""Offline evaluation of keyword retrieval and the approved field assessor."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from .models import model_configuration, model_is_configured, model_method
from .paths import EVALUATION_DIR
from .service import Engine
from .types import ClaimRequest

RESULT_COLUMNS = [
    "case_id",
    "split",
    "configuration",
    "model_version",
    "scope",
    "evidence_ids",
    "expected_fields",
    "returned_fields",
    "result",
    "execution_state",
    "latency_ms",
    "usage",
    "cost",
    "label",
    "publication_permission",
]


def _pages(results: list[dict]) -> set[int]:
    return {int(item["physical_page"]) for item in results if item.get("physical_page") is not None}


def _ids(results: list[dict], with_context: bool) -> list[str]:
    found = []
    for item in results:
        found.append(item.get("block_id", ""))
        if with_context:
            for related in item.get("context") or []:
                found.append(related.get("block_id", ""))
    return [item for item in found if item]


def _context_items(results: list[dict]) -> list[dict]:
    items: list[dict] = []
    for result in results:
        items.extend(result.get("context") or [])
    return items


def _required_context_met(raw: str, results: list[dict]) -> bool:
    requirements = [item.strip() for item in (raw or "").split("|") if item.strip()]
    if not requirements:
        return True
    context = list(results) + _context_items(results)
    for requirement in requirements:
        lowered = requirement.lower()
        if lowered in {"note", "footnote"}:
            if not any(item.get("block_kind") in {"note", "footnote"} for item in context):
                return False
        elif lowered.startswith("page:"):
            page = lowered.split(":", 1)[1]
            if not any(str(item.get("physical_page")) == page for item in context):
                return False
        elif lowered.startswith("kind:"):
            kind = lowered.split(":", 1)[1]
            if not any(str(item.get("block_kind", "")).lower() == kind for item in context):
                return False
        elif lowered.startswith("block:"):
            block_id = requirement.split(":", 1)[1]
            if not any(str(item.get("block_id", "")) == block_id for item in context):
                return False
        elif lowered.startswith("text:"):
            phrase = lowered.split(":", 1)[1]
            if not any(phrase in str(item.get("original_text", "")).lower() for item in context):
                return False
        else:
            return False
    return True


def _validate_cases(engine: Engine, cases: list[dict[str, str]]) -> None:
    ids = [row.get("case_id", "") for row in cases]
    if any(not case_id for case_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("evaluation case IDs must be populated and unique")
    for row in cases:
        if not row.get("split"):
            raise ValueError(f"{row['case_id']}: split is required")
        expected_version = row.get("source_version", "")
        for file_id in _file_ids(row.get("file_ids", "")):
            document = engine.store.document(file_id)
            if document is None:
                raise ValueError(f"{row['case_id']}: {file_id} is absent from the index")
            if not expected_version or document["source_version"] != expected_version:
                raise ValueError(f"{row['case_id']}: source_version does not match {file_id}")


def _claim_fields(raw: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key.strip()] = value.strip()
    return fields


def _expected_assessments(raw: str) -> dict[str, str]:
    return _claim_fields(raw)


def _file_ids(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in (raw or "").split("|") if part.strip())


def _passed(case: dict[str, str], *, complete: bool, state: str, assessments: dict[str, str] | None) -> bool:
    kind = case.get("case_kind", "lookup")
    if kind == "access_denied":
        return state == "ACCESS_DENIED"
    if kind == "constructed_claim":
        expected = _expected_assessments(case.get("expected_field_assessments", ""))
        if assessments and expected:
            return all(assessments.get(field) == label for field, label in expected.items()) and state == "OK"
        return assessments is not None and assessments.get("fee_basis") != "SUPPORTED" and state == "OK"
    if kind == "quote_other_number":
        return assessments is not None and assessments.get("value") == "INSUFFICIENT_EVIDENCE" and state == "OK"
    return complete and state in {"OK", "EMPTY_RESULTS"}


def _assessor_fields(case: dict[str, str]) -> dict[str, str]:
    claimed = _claim_fields(case.get("claim_fields", ""))
    if claimed:
        return claimed
    return {"retrieved_fact": case.get("query", "")}


def _assessor_expected(case: dict[str, str]) -> dict[str, str]:
    expected = _expected_assessments(case.get("expected_field_assessments", ""))
    if expected:
        return expected
    if case.get("case_kind") == "lookup":
        return {"retrieved_fact": "SUPPORTED"}
    return {}


def _assessor_passed(
    case: dict[str, str],
    *,
    state: str,
    assessments: dict[str, str] | None,
    pages: set[int],
    expected_pages: set[int],
) -> bool:
    kind = case.get("case_kind", "lookup")
    if kind == "access_denied":
        return state == "ACCESS_DENIED"
    if state != "OK":
        return False
    expected = _assessor_expected(case)
    if expected:
        if not assessments:
            return False
        if not all(assessments.get(field) == label for field, label in expected.items()):
            return False
    if kind == "lookup" and expected_pages and not expected_pages.issubset(pages):
        return False
    return True


def _write_results(destination: Path, rows: list[dict[str, str]]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _merge_results(destination: Path, new_rows: list[dict[str, str]], configuration: str) -> None:
    existing: list[dict[str, str]] = []
    if destination.is_file():
        with destination.open(encoding="utf-8-sig", newline="") as handle:
            existing = list(csv.DictReader(handle))
    config = model_configuration()
    for row in existing:
        if row.get("configuration") != "approved_assessor":
            continue
        if not model_is_configured(config) or row.get("model_version") != config["model_id"]:
            row["label"] = "historical_model_unverified_authorization"
    by_key = {(row.get("case_id", ""), row.get("configuration", "")): row for row in existing}
    for row in new_rows:
        by_key[(row["case_id"], row["configuration"])] = row
    ordered: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in existing:
        key = (row.get("case_id", ""), row.get("configuration", ""))
        merged = by_key[key]
        ordered.append(merged)
        seen.add(key)
    for row in new_rows:
        key = (row["case_id"], row["configuration"])
        if key not in seen:
            ordered.append(row)
            seen.add(key)
    _write_results(destination, ordered)
    del configuration


def _write_offline_summary(
    destination: Path,
    cases: list[dict[str, str]],
) -> Path:
    with destination.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    offline = {
        (row.get("case_id", ""), row.get("configuration", "")): row
        for row in rows
        if row.get("configuration") in {
            "keyword",
            "keyword_context",
            "keyword_vector_context",
        }
    }
    case_by_id = {row["case_id"]: row for row in cases}

    def selected(*, semantic: bool | None = None, split: str | None = None) -> list[str]:
        output = []
        for case_id, case in case_by_id.items():
            is_semantic = case_id.startswith("SEM-")
            if semantic is not None and is_semantic != semantic:
                continue
            if split is not None and case.get("split") != split:
                continue
            output.append(case_id)
        return output

    groups = {
        "all": selected(),
        "exact": selected(semantic=False),
        "semantic": selected(semantic=True),
        "semantic_held_out": selected(semantic=True, split="held-out"),
        "exact_held_out": selected(semantic=False, split="held-out"),
    }
    metrics: dict[str, dict[str, dict[str, int | float]]] = {}
    for group, ids in groups.items():
        metrics[group] = {}
        for configuration in ("keyword", "keyword_context", "keyword_vector_context"):
            relevant = [offline.get((case_id, configuration)) for case_id in ids]
            run = [row for row in relevant if row and row.get("result") != "unrun"]
            passed = sum(row.get("result") == "pass" for row in run)
            metrics[group][configuration] = {
                "cases": len(ids),
                "run": len(run),
                "passed": passed,
                "pass_rate": round(passed / len(run), 4) if run else 0.0,
            }
    safety_ids = [
        case_id
        for case_id, case in case_by_id.items()
        if case.get("case_kind") in {"access_denied", "constructed_claim", "quote_other_number"}
    ]
    no_safety_regression = all(
        offline.get((case_id, "keyword_context"), {}).get("result") != "pass"
        or offline.get((case_id, "keyword_vector_context"), {}).get("result") == "pass"
        for case_id in safety_ids
    )
    semantic = metrics["semantic_held_out"]
    exact = metrics["exact_held_out"]
    hybrid_complete = (
        semantic["keyword_vector_context"]["run"] == semantic["keyword_vector_context"]["cases"]
        and semantic["keyword_vector_context"]["cases"] > 0
    )
    semantic_improved = (
        semantic["keyword_vector_context"]["passed"]
        > semantic["keyword_context"]["passed"]
    )
    exact_not_worse = (
        exact["keyword_vector_context"]["passed"]
        >= exact["keyword_context"]["passed"]
    )
    recommended = bool(
        hybrid_complete and semantic_improved and exact_not_worse and no_safety_regression
    )
    summary = {
        "case_count": len(cases),
        "semantic_case_count": len(groups["semantic"]),
        "metrics": metrics,
        "activation": {
            "hybrid_default_recommended": recommended,
            "semantic_held_out_improved": semantic_improved,
            "exact_held_out_not_worse": exact_not_worse,
            "safety_regression": not no_safety_regression,
            "rule": "Improve held-out semantic retrieval without reducing held-out exact or safety results.",
        },
    }
    path = destination.with_name("summary.json")
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return path


def evaluate_offline(
    engine: Engine,
    session_id: str,
    cases_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    path = cases_path or (EVALUATION_DIR / "cases.csv")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        cases = list(csv.DictReader(handle))
    _validate_cases(engine, cases)
    rows = []
    vector_ready = engine.status()["vector_enabled"]
    for case in cases:
        query = case["query"]
        file_ids = _file_ids(case.get("file_ids", ""))
        expected = {int(part) for part in case.get("expected_pages", "").split("|") if part.strip().isdigit()}
        kind = case.get("case_kind", "lookup")
        for configuration, with_context in (("keyword", False), ("keyword_context", True)):
            started = time.perf_counter()
            if kind == "access_denied":
                extractor = engine.issue_session("extractor_a", purpose="offline access case")
                search = engine.search_sources(
                    extractor.session_id,
                    query,
                    file_ids=file_ids or None,
                    retrieval_methods=("keyword",),
                )
                elapsed = int((time.perf_counter() - started) * 1000)
                assessments = None
                evidence_ids = "|".join(_ids(search.results, with_context))
                returned = "|".join(str(page) for page in sorted(_pages(search.results)))
                state = search.execution_state
                complete = False
            elif kind in {"constructed_claim", "quote_other_number"}:
                claim = ClaimRequest(
                    observation_id=None,
                    subject=case.get("query", ""),
                    field_values=_claim_fields(case.get("claim_fields", "")),
                    date_meanings={},
                    file_ids=file_ids,
                )
                verified = engine.verify_claim(
                    session_id, claim, retrieval_methods=("keyword",)
                )
                elapsed = int((time.perf_counter() - started) * 1000)
                assessments = {item.field: (item.assessment or "") for item in verified.assessments}
                complete = _passed(case, complete=True, state=verified.execution_state, assessments=assessments)
                evidence_ids = "|".join(_ids(verified.results, with_context))
                returned = ";".join(f"{field}={label}" for field, label in assessments.items())
                state = verified.execution_state
            else:
                search = engine.search_sources(
                    session_id,
                    query,
                    file_ids=file_ids or None,
                    result_limit=5,
                    retrieval_methods=("keyword",),
                )
                elapsed = int((time.perf_counter() - started) * 1000)
                pages = _pages(search.results)
                page_complete = expected.issubset(pages) if expected else bool(search.results)
                context_complete = not with_context or _required_context_met(
                    case.get("required_context", ""), search.results
                )
                complete = page_complete and context_complete
                assessments = None
                evidence_ids = "|".join(_ids(search.results, with_context))
                returned = "|".join(str(page) for page in sorted(pages))
                state = search.execution_state
            rows.append(
                {
                    "case_id": case["case_id"],
                    "split": case.get("split", ""),
                    "configuration": configuration,
                    "model_version": "unrun",
                    "scope": session_id,
                    "evidence_ids": evidence_ids,
                    "expected_fields": case.get("expected_field_assessments", ""),
                    "returned_fields": returned,
                    "result": "pass" if _passed(case, complete=complete, state=state, assessments=assessments) else "fail",
                    "execution_state": state,
                    "latency_ms": str(elapsed),
                    "usage": "",
                    "cost": "0",
                    "label": "offline_keyword" if configuration == "keyword" else "offline_keyword_context",
                    "publication_permission": case.get("publication_permission", ""),
                }
            )
        if vector_ready:
            started = time.perf_counter()
            if kind == "access_denied":
                extractor = engine.issue_session("extractor_a", purpose="hybrid access case")
                hybrid = engine.search_sources(
                    extractor.session_id,
                    query,
                    file_ids=file_ids or None,
                    result_limit=5,
                    retrieval_methods=("keyword", "vector"),
                )
                assessments = None
                pages = _pages(hybrid.results)
                complete = False
                returned = "|".join(str(page) for page in sorted(pages))
            elif kind in {"constructed_claim", "quote_other_number"}:
                claim = ClaimRequest(
                    observation_id=None,
                    subject=case.get("query", ""),
                    field_values=_claim_fields(case.get("claim_fields", "")),
                    date_meanings={},
                    file_ids=file_ids,
                )
                hybrid = engine.verify_claim(
                    session_id,
                    claim,
                    retrieval_methods=("keyword", "vector"),
                )
                assessments = {
                    item.field: (item.assessment or "") for item in hybrid.assessments
                }
                complete = _passed(
                    case,
                    complete=True,
                    state=hybrid.execution_state,
                    assessments=assessments,
                )
                pages = _pages(hybrid.results)
                returned = ";".join(
                    f"{field}={label}" for field, label in assessments.items()
                )
            else:
                hybrid = engine.search_sources(
                    session_id,
                    query,
                    file_ids=file_ids or None,
                    result_limit=5,
                    retrieval_methods=("keyword", "vector"),
                )
                assessments = None
                pages = _pages(hybrid.results)
                complete = (
                    expected.issubset(pages) if expected else bool(hybrid.results)
                ) and _required_context_met(
                    case.get("required_context", ""), hybrid.results
                )
                returned = "|".join(str(page) for page in sorted(pages))
            elapsed = int((time.perf_counter() - started) * 1000)
            rows.append(
                {
                    "case_id": case["case_id"],
                    "split": case.get("split", ""),
                    "configuration": "keyword_vector_context",
                    "model_version": engine.store.meta("embedding_model_key"),
                    "scope": session_id,
                    "evidence_ids": "|".join(_ids(hybrid.results, True)),
                    "expected_fields": case.get("expected_field_assessments", ""),
                    "returned_fields": returned,
                    "result": "pass" if _passed(
                        case,
                        complete=complete,
                        state=hybrid.execution_state,
                        assessments=assessments,
                    ) else "fail",
                    "execution_state": hybrid.execution_state,
                    "latency_ms": str(elapsed),
                    "usage": "",
                    "cost": "0",
                    "label": "offline_local_hybrid",
                    "publication_permission": case.get("publication_permission", ""),
                }
            )
        else:
            rows.append(
                {
                    "case_id": case["case_id"],
                    "split": case.get("split", ""),
                    "configuration": "keyword_vector_context",
                    "model_version": "unrun",
                    "scope": session_id,
                    "evidence_ids": "",
                    "expected_fields": case.get("expected_field_assessments", ""),
                    "returned_fields": "",
                    "result": "unrun",
                    "execution_state": "MODEL_DISABLED",
                    "latency_ms": "",
                    "usage": "",
                    "cost": "",
                    "label": "offline_vector_unrun",
                    "publication_permission": case.get("publication_permission", ""),
                }
            )
    destination = output_path or (EVALUATION_DIR / "results.csv")
    _merge_results(destination, rows, "offline")
    _write_offline_summary(destination, cases)
    return destination


def evaluate_assessor(
    engine: Engine,
    session_id: str,
    cases_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    path = cases_path or (EVALUATION_DIR / "cases.csv")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        cases = list(csv.DictReader(handle))
    _validate_cases(engine, cases)
    rows = []
    for case in cases:
        query = case["query"]
        file_ids = _file_ids(case.get("file_ids", ""))
        expected_pages = {int(part) for part in case.get("expected_pages", "").split("|") if part.strip().isdigit()}
        kind = case.get("case_kind", "lookup")
        started = time.perf_counter()
        if kind == "access_denied":
            extractor = engine.issue_session("extractor_a", purpose="assessor access case")
            search = engine.search_sources(extractor.session_id, query, file_ids=file_ids or None)
            elapsed = int((time.perf_counter() - started) * 1000)
            assessments: dict[str, str] | None = None
            evidence_ids = "|".join(_ids(search.results, True))
            returned = ""
            state = search.execution_state
            usage = ""
            cost = "0"
            pages: set[int] = set()
        else:
            claim = ClaimRequest(
                observation_id=None,
                subject=query,
                field_values=_assessor_fields(case),
                date_meanings={},
                file_ids=file_ids,
            )
            verified = engine.model_assess(session_id, claim)
            elapsed = int((time.perf_counter() - started) * 1000)
            assessments = {item.field: (item.assessment or "") for item in verified.assessments}
            evidence_ids = "|".join(_ids(verified.results, True))
            returned = ";".join(f"{field}={label}" for field, label in assessments.items())
            state = verified.execution_state
            usage_payload = verified.usage or {}
            usage = (
                f"in={usage_payload.get('input_tokens', '')};"
                f"out={usage_payload.get('output_tokens', '')}"
            )
            cost = str(usage_payload.get("cost") or "0")
            pages = _pages(verified.results)
        passed = _assessor_passed(
            case,
            state=state,
            assessments=assessments,
            pages=pages,
            expected_pages=expected_pages,
        )
        if case.get("case_kind") != "access_denied" and not _required_context_met(
            case.get("required_context", ""), verified.results
        ):
            passed = False
        rows.append(
            {
                "case_id": case["case_id"],
                "split": case.get("split", ""),
                "configuration": "approved_assessor",
                "model_version": model_method(),
                "scope": session_id,
                "evidence_ids": evidence_ids,
                "expected_fields": case.get("expected_field_assessments", "")
                or (";".join(f"{k}={v}" for k, v in _assessor_expected(case).items())),
                "returned_fields": returned,
                "result": "pass" if passed else "fail",
                "execution_state": state,
                "latency_ms": str(elapsed),
                "usage": usage,
                "cost": cost,
                "label": "model",
                "publication_permission": case.get("publication_permission", ""),
            }
        )
    destination = output_path or (EVALUATION_DIR / "results.csv")
    _merge_results(destination, rows, "approved_assessor")
    return destination
