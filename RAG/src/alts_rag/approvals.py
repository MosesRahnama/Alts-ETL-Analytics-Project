"""Model approval records. Configuration values confer zero spending permission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .store import AccessStore


@dataclass(frozen=True)
class Approval:
    approval_id: str
    operation: str
    provider: str
    model_id: str
    reasoning_setting: str
    documents: tuple[str, ...]
    fields: tuple[str, ...]
    request_limit: int
    spending_cap: str
    expires_at: str
    granted_by: str
    authorization_reference: str
    provider_contract_hash: str
    max_input_tokens: int
    max_output_tokens: int
    input_usd_per_m: str
    output_usd_per_m: str


class ApprovalMissing(RuntimeError):
    def __init__(self, operation: str) -> None:
        super().__init__(f"MODEL_DISABLED:{operation}")
        self.execution_state = "MODEL_DISABLED"


def matching_approval(
    store: AccessStore,
    operation: str,
    file_ids: tuple[str, ...],
    *,
    provider: str = "",
    model_id: str = "",
    reasoning_setting: str = "",
    provider_contract_hash: str = "",
    fields: tuple[str, ...] = (),
) -> Approval | None:
    rows = store.conn.execute("SELECT * FROM approvals WHERE operation=?", (operation,)).fetchall()
    now = datetime.now(timezone.utc)
    for row in rows:
        if row["granted_by"] != "Moses":
            continue
        if not row["authorization_reference"]:
            continue
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except (TypeError, ValueError):
            continue
        if expires.tzinfo is None or expires <= now:
            continue
        if provider and row["provider"] != provider:
            continue
        if model_id and row["model_id"] != model_id:
            continue
        if reasoning_setting and row["reasoning_setting"] != reasoning_setting:
            continue
        if provider_contract_hash and row["provider_contract_hash"] != provider_contract_hash:
            continue
        permitted = tuple(part for part in (row["documents"] or "").split(",") if part)
        if file_ids and (not permitted or any(file_id not in permitted for file_id in file_ids)):
            continue
        permitted_fields = tuple(part for part in (row["fields"] or "").split(",") if part)
        if fields and (not permitted_fields or any(field not in permitted_fields for field in fields)):
            continue
        return Approval(
            approval_id=row["approval_id"],
            operation=row["operation"],
            provider=row["provider"] or "",
            model_id=row["model_id"] or "",
            reasoning_setting=row["reasoning_setting"] or "",
            documents=permitted,
            fields=permitted_fields,
            request_limit=int(row["request_limit"] or 0),
            spending_cap=row["spending_cap"] or "",
            expires_at=row["expires_at"] or "",
            granted_by=row["granted_by"],
            authorization_reference=row["authorization_reference"],
            provider_contract_hash=row["provider_contract_hash"],
            max_input_tokens=int(row["max_input_tokens"] or 0),
            max_output_tokens=int(row["max_output_tokens"] or 0),
            input_usd_per_m=row["input_usd_per_m"] or "",
            output_usd_per_m=row["output_usd_per_m"] or "",
        )
    return None


def require_approval(
    store: AccessStore,
    operation: str,
    file_ids: tuple[str, ...],
    **requirements,
) -> Approval:
    approval = matching_approval(store, operation, file_ids, **requirements)
    if approval is None:
        raise ApprovalMissing(operation)
    return approval


def record_approval(
    store: AccessStore,
    *,
    approval_id: str,
    authorization_reference: str,
    operation: str,
    provider: str,
    model_id: str,
    reasoning_setting: str,
    provider_contract_hash: str,
    documents: tuple[str, ...],
    fields: tuple[str, ...],
    request_limit: int,
    spending_cap: str,
    max_input_tokens: int,
    max_output_tokens: int,
    input_usd_per_m: str,
    output_usd_per_m: str,
    expires_at: str,
) -> Approval:
    required_text = {
        "approval_id": approval_id,
        "authorization_reference": authorization_reference,
        "operation": operation,
        "provider": provider,
        "model_id": model_id,
        "reasoning_setting": reasoning_setting,
        "provider_contract_hash": provider_contract_hash,
        "spending_cap": spending_cap,
        "input_usd_per_m": input_usd_per_m,
        "output_usd_per_m": output_usd_per_m,
        "expires_at": expires_at,
    }
    missing = [name for name, value in required_text.items() if not value.strip()]
    if missing or not documents or request_limit <= 0 or max_input_tokens <= 0 or max_output_tokens <= 0:
        detail = ", ".join(missing) or "documents and positive numeric limits"
        raise ValueError(f"incomplete approval record: {detail}")
    try:
        expires = datetime.fromisoformat(expires_at)
        cap = Decimal(spending_cap)
        input_rate = Decimal(input_usd_per_m)
        output_rate = Decimal(output_usd_per_m)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError("approval dates and prices must be valid") from exc
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError("approval expiry must be a future timezone-aware timestamp")
    if cap <= 0 or input_rate < 0 or output_rate < 0:
        raise ValueError("approval cap must be positive and prices cannot be negative")
    store.conn.execute(
        """
        INSERT INTO approvals(
            approval_id, operation, provider, model_id, reasoning_setting, documents, fields,
            request_limit, spending_cap, expires_at, granted_by, authorization_reference,
            provider_contract_hash, max_input_tokens, max_output_tokens,
            input_usd_per_m, output_usd_per_m
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            approval_id,
            operation,
            provider,
            model_id,
            reasoning_setting,
            ",".join(documents),
            ",".join(fields),
            request_limit,
            spending_cap,
            expires_at,
            "Moses",
            authorization_reference,
            provider_contract_hash,
            max_input_tokens,
            max_output_tokens,
            input_usd_per_m,
            output_usd_per_m,
        ),
    )
    store.conn.commit()
    approval = matching_approval(
        store,
        operation,
        documents,
        provider=provider,
        model_id=model_id,
        reasoning_setting=reasoning_setting,
        provider_contract_hash=provider_contract_hash,
        fields=fields,
    )
    if approval is None:
        raise RuntimeError("approval record failed validation")
    return approval
