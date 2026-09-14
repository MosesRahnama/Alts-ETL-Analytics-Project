"""OpenRouter model adapter with explicit, request-bound approval checks."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .approvals import Approval, ApprovalMissing, matching_approval, require_approval
from .network import OutboundRefused
from .policy import retrieval_policy
from .store import AccessStore
from .types import AssessmentLabel, FieldAssessment

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ALLOWED = frozenset({"SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"})
ASSESSMENT_KEYS = frozenset(
    {"field", "claimed_value", "assessment", "reason", "supporting_ids", "conflicting_ids"}
)


class ModelConfigurationError(RuntimeError):
    """The selected model cannot run until its exact provider contract is recorded."""


class ModelResponseError(RuntimeError):
    """The provider returned output that does not satisfy the assessment contract."""


def model_configuration() -> dict[str, Any]:
    settings = retrieval_policy()
    return {
        "provider": str(settings.get("provider") or "").strip(),
        "model_name": str(settings.get("reasoning_model_name") or "").strip(),
        "model_id": str(settings.get("reasoning_model") or "").strip(),
        "reasoning_setting": str(settings.get("reasoning_setting") or "").strip(),
        "identifier_status": str(settings.get("identifier_status") or "unverified").strip(),
        "reasoning_request": settings.get("reasoning_request"),
    }


def model_is_configured(settings: dict[str, Any] | None = None) -> bool:
    config = settings or model_configuration()
    return bool(
        config["provider"] == "openrouter"
        and config["model_id"]
        and config["reasoning_setting"]
        and config["identifier_status"] == "verified"
        and isinstance(config["reasoning_request"], dict)
        and config["reasoning_request"]
    )


def model_contract_hash(settings: dict[str, Any] | None = None) -> str:
    config = settings or model_configuration()
    contract = {
        "provider": config["provider"],
        "model_id": config["model_id"],
        "reasoning_setting": config["reasoning_setting"],
        "reasoning_request": config["reasoning_request"],
    }
    payload = json.dumps(contract, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def model_method(settings: dict[str, Any] | None = None) -> str:
    config = settings or model_configuration()
    return config["model_id"] or f"{config['model_name']} (identifier unverified)"


class ModelAdapter:
    role = "reasoning"

    def available(self) -> bool:
        return False

    def assess(self, *_args: Any, **_kwargs: Any) -> None:
        raise ApprovalMissing("verify_claim")


class EmbeddingAdapter(ModelAdapter):
    role = "embedding"

    def embed(self, *_args: Any, **_kwargs: Any) -> list[float]:
        raise ApprovalMissing("embed")


def load_openrouter_key() -> str:
    return str(
        os.environ.get("ALTS_RAG_OPENROUTER_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or ""
    ).strip()


def _money(value: str, field: str) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ModelConfigurationError(f"invalid {field}") from exc
    if amount < 0:
        raise ModelConfigurationError(f"negative {field}")
    return amount


def estimate_cost(input_tokens: int, output_tokens: int, approval: Approval) -> Decimal:
    input_rate = _money(approval.input_usd_per_m, "input price")
    output_rate = _money(approval.output_usd_per_m, "output price")
    return (
        Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate
    ) / Decimal(1_000_000)


def reservation_cost(approval: Approval) -> Decimal:
    return estimate_cost(approval.max_input_tokens, approval.max_output_tokens, approval)


def disabled_model_result(operation: str) -> dict[str, str]:
    config = model_configuration()
    reason = "Exact OpenRouter model identifier, request settings, pricing, and job approval are required."
    if model_is_configured(config):
        reason = f"{operation} requires a matching, explicit job approval before any provider request."
    return {
        "execution_state": "MODEL_DISABLED",
        "reason": reason,
        "provider": config["provider"],
        "requested_model": config["model_id"] or config["model_name"],
        "requested_reasoning": config["reasoning_setting"],
        "identifier_status": config["identifier_status"],
    }


def _spent(store: AccessStore, approval_id: str) -> tuple[int, Decimal]:
    rows = store.conn.execute(
        "SELECT cost, reserved_cost, cost_status FROM usage WHERE approval_id=?",
        (approval_id,),
    ).fetchall()
    total = Decimal("0")
    for row in rows:
        value = row["cost"] if row["cost_status"] == "ACTUAL" else row["reserved_cost"]
        total += _money(str(value or "0"), "recorded cost")
    return len(rows), total


def _reserve(store: AccessStore, approval: Approval, request_id: str) -> Decimal:
    reserve = reservation_cost(approval)
    cap = _money(approval.spending_cap, "spending cap")
    try:
        store.conn.execute("BEGIN IMMEDIATE")
        used, spent = _spent(store, approval.approval_id)
        if approval.request_limit and used >= approval.request_limit:
            raise RuntimeError("budget exceeded: request_limit")
        if spent + reserve > cap:
            raise RuntimeError("budget exceeded: spending_cap")
        store.conn.execute(
            """
            INSERT INTO usage(
                request_id, approval_id, provider, model_id, input_tokens, output_tokens,
                cost, outcome, recorded_at, reasoning_setting, reserved_cost,
                provider_request_id, cost_status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                request_id,
                approval.approval_id,
                approval.provider,
                approval.model_id,
                0,
                0,
                "0",
                "RESERVED",
                datetime.now(timezone.utc).isoformat(),
                approval.reasoning_setting,
                f"{reserve:.6f}",
                "",
                "RESERVED",
            ),
        )
        store.conn.commit()
        return reserve
    except Exception:
        store.conn.rollback()
        raise


def _finish_usage(
    store: AccessStore,
    request_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cost: Decimal,
    outcome: str,
    provider_request_id: str,
    cost_status: str,
) -> None:
    store.conn.execute(
        """
        UPDATE usage SET input_tokens=?, output_tokens=?, cost=?, outcome=?,
            provider_request_id=?, cost_status=? WHERE request_id=?
        """,
        (
            input_tokens,
            output_tokens,
            f"{cost:.6f}",
            outcome,
            provider_request_id,
            cost_status,
            request_id,
        ),
    )
    store.conn.commit()


def _passages(blocks: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in blocks[:limit]:
        candidates = [(item, 1500)] + [
            (related, 800) for related in (item.get("context") or [])[:4]
        ]
        for passage, char_limit in candidates:
            if passage.get("instruction_like"):
                continue
            block_id = str(passage.get("block_id") or "")
            if not block_id or block_id in seen:
                continue
            seen.add(block_id)
            output.append(
                {
                    "block_id": block_id,
                    "file_id": passage.get("file_id"),
                    "physical_page": passage.get("physical_page"),
                    "block_kind": passage.get("block_kind"),
                    "original_text": (passage.get("original_text") or "")[:char_limit],
                }
            )
    return output


def _prompt(subject: str, field_values: dict[str, str], passages: list[dict[str, Any]]) -> list[dict[str, str]]:
    system = (
        "Assess each claim only against the supplied financial-report passages. "
        "Return one record for every requested field and no other fields. "
        "Use SUPPORTED, CONTRADICTED, or INSUFFICIENT_EVIDENCE. "
        "Citations must use supplied block_id values. Return JSON only."
    )
    user = json.dumps(
        {
            "subject": subject,
            "claims": field_values,
            "passages": passages,
            "response_schema": {
                "assessments": [
                    {
                        "field": "string",
                        "claimed_value": "string",
                        "assessment": "SUPPORTED|CONTRADICTED|INSUFFICIENT_EVIDENCE",
                        "reason": "string",
                        "supporting_ids": ["block_id"],
                        "conflicting_ids": ["block_id"],
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _message_text(payload: dict[str, Any]) -> str:
    choice = (payload.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content")
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content or "")


def openrouter_chat(
    messages: list[dict[str, str]],
    *,
    approval: Approval,
    settings: dict[str, Any],
) -> dict[str, Any]:
    if not model_is_configured(settings):
        raise ModelConfigurationError("OpenRouter model contract is unverified")
    if (
        approval.provider != settings["provider"]
        or approval.model_id != settings["model_id"]
        or approval.reasoning_setting != settings["reasoning_setting"]
        or approval.provider_contract_hash != model_contract_hash(settings)
    ):
        raise ApprovalMissing("verify_claim")
    key = load_openrouter_key()
    if not key:
        raise ApprovalMissing("verify_claim")
    request_options = dict(settings["reasoning_request"])
    forbidden = {"model", "messages", "max_tokens", "temperature"} & set(request_options)
    if forbidden:
        raise ModelConfigurationError("reasoning_request overrides protected request fields")
    payload = {
        "model": approval.model_id,
        "messages": messages,
        "temperature": 0,
        "max_tokens": approval.max_output_tokens,
        **request_options,
    }
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "AltsRAG",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
            result["_provider_request_id"] = response.headers.get("X-Request-ID", "")
            return result
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenRouter HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, OutboundRefused):
            raise exc.reason
        raise RuntimeError("OpenRouter connection failed") from exc


def parse_assessments(
    raw: str,
    field_values: dict[str, str],
    evidence_ids: set[str] | None = None,
    *,
    model_id: str = "model",
) -> list[FieldAssessment]:
    text = (raw or "").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelResponseError("model response is not one JSON object") from exc
    if not isinstance(data, dict) or set(data) != {"assessments"} or not isinstance(data["assessments"], list):
        raise ModelResponseError("model response has the wrong top-level shape")
    by_field: dict[str, dict[str, Any]] = {}
    for item in data["assessments"]:
        if not isinstance(item, dict) or set(item) != ASSESSMENT_KEYS:
            raise ModelResponseError("assessment record has the wrong fields")
        field = item.get("field")
        if not isinstance(field, str) or field not in field_values or field in by_field:
            raise ModelResponseError("assessment field is missing, extra, or duplicated")
        by_field[field] = item
    if set(by_field) != set(field_values):
        raise ModelResponseError("model omitted a requested field")
    supplied = evidence_ids or set()
    rows: list[FieldAssessment] = []
    for field, claimed in field_values.items():
        item = by_field[field]
        if item["claimed_value"] != claimed:
            raise ModelResponseError("model changed a claimed value")
        label = str(item["assessment"]).upper()
        if label not in ALLOWED:
            raise ModelResponseError("model returned an unknown assessment")
        reason = item["reason"]
        supporting_raw = item["supporting_ids"]
        conflicting_raw = item["conflicting_ids"]
        if not isinstance(reason, str) or not reason.strip():
            raise ModelResponseError("assessment reason is empty")
        if not isinstance(supporting_raw, list) or not isinstance(conflicting_raw, list):
            raise ModelResponseError("citation fields must be lists")
        supporting = tuple(str(value) for value in supporting_raw)
        conflicting = tuple(str(value) for value in conflicting_raw)
        if any(value not in supplied for value in (*supporting, *conflicting)):
            raise ModelResponseError("model cited evidence that was not supplied")
        if set(supporting) & set(conflicting):
            raise ModelResponseError("one evidence block cannot support and conflict")
        if label == "SUPPORTED" and not supporting:
            raise ModelResponseError("SUPPORTED requires supporting evidence")
        if label == "CONTRADICTED" and not conflicting:
            raise ModelResponseError("CONTRADICTED requires conflicting evidence")
        scored: AssessmentLabel = label  # type: ignore[assignment]
        rows.append(
            FieldAssessment(
                field=field,
                claimed_value=claimed,
                assessment=scored,
                reason=reason.strip(),
                supporting_ids=supporting,
                conflicting_ids=conflicting,
                method=model_id,
                review_state="model",
            )
        )
    return rows


class OpenRouterAdapter(ModelAdapter):
    def __init__(self, store: AccessStore) -> None:
        self.store = store

    def available(self) -> bool:
        settings = model_configuration()
        if not model_is_configured(settings):
            return False
        return matching_approval(
            self.store,
            "verify_claim",
            (),
            provider=settings["provider"],
            model_id=settings["model_id"],
            reasoning_setting=settings["reasoning_setting"],
            provider_contract_hash=model_contract_hash(settings),
        ) is not None

    def assess(
        self,
        file_ids: tuple[str, ...],
        subject: str,
        field_values: dict[str, str],
        blocks: list[dict[str, Any]],
        request_id: str,
    ) -> tuple[list[FieldAssessment], dict[str, Any]]:
        settings = model_configuration()
        if not model_is_configured(settings):
            raise ApprovalMissing("verify_claim")
        if not field_values or not blocks:
            raise ModelResponseError("assessment requires claims and retrieved evidence")
        approval = require_approval(
            self.store,
            "verify_claim",
            file_ids,
            provider=settings["provider"],
            model_id=settings["model_id"],
            reasoning_setting=settings["reasoning_setting"],
            provider_contract_hash=model_contract_hash(settings),
            fields=tuple(field_values),
        )
        passages = _passages(blocks)
        if not passages:
            raise ModelResponseError("retrieved passages were instruction-like or empty")
        messages = _prompt(subject, field_values, passages)
        # UTF-8 bytes are a conservative token ceiling for the request payload.
        estimated_input = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        if estimated_input > approval.max_input_tokens:
            raise RuntimeError("input exceeds approved token limit")
        reserve = _reserve(self.store, approval, request_id)
        try:
            payload = openrouter_chat(messages, approval=approval, settings=settings)
        except OutboundRefused:
            _finish_usage(
                self.store, request_id, input_tokens=0, output_tokens=0,
                cost=Decimal("0"), outcome="NOT_SENT", provider_request_id="", cost_status="NOT_SENT",
            )
            raise
        except Exception:
            _finish_usage(
                self.store, request_id, input_tokens=0, output_tokens=0,
                cost=reserve, outcome="MODEL_ERROR", provider_request_id="",
                cost_status="RESERVED_UNCERTAIN",
            )
            raise
        usage = payload.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        outcome = "OK"
        try:
            cost = Decimal(str(usage["cost"])) if usage.get("cost") is not None else estimate_cost(input_tokens, output_tokens, approval)
        except (InvalidOperation, ValueError):
            cost = estimate_cost(input_tokens, output_tokens, approval)
        if (
            input_tokens > approval.max_input_tokens
            or output_tokens > approval.max_output_tokens
            or cost > reserve
        ):
            outcome = "MODEL_ERROR"
        provider_request_id = str(payload.get("_provider_request_id") or payload.get("id") or "")
        _finish_usage(
            self.store, request_id, input_tokens=input_tokens, output_tokens=output_tokens,
            cost=cost, outcome=outcome, provider_request_id=provider_request_id, cost_status="ACTUAL",
        )
        if outcome != "OK":
            raise ModelResponseError("provider usage exceeded the approved token limit")
        supplied_ids = {str(item["block_id"]) for item in passages}
        try:
            assessments = parse_assessments(
                _message_text(payload), field_values, supplied_ids, model_id=settings["model_id"]
            )
        except ModelResponseError:
            self.store.conn.execute(
                "UPDATE usage SET outcome='MODEL_ERROR' WHERE request_id=?", (request_id,)
            )
            self.store.conn.commit()
            raise
        return assessments, {
            "execution_state": "OK",
            "provider": settings["provider"],
            "model": settings["model_id"],
            "reasoning_setting": settings["reasoning_setting"],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": f"{cost:.6f}",
            "provider_request_id": provider_request_id,
        }


def guarded_call(*_args: Any, **_kwargs: Any) -> None:
    raise OutboundRefused("model adapters require an explicit approved job")
