"""Rule-based field assessment over retrieved source blocks."""

from __future__ import annotations

import re

from .citations import number_in_quote, rounding_note
from .types import FieldAssessment

FEE_NET = re.compile(
    r"\bnet(?:-|\s+)of(?:\s+\w+){0,4}\s+fees?\b|\bnet(?:\s+return|\s+performance)\b|\(\s*net of fees\s*\)",
    re.I,
)
FEE_GROSS = re.compile(r"\bgross(?:\s+of|\s+return)?\b|\bbefore\s+fees\b", re.I)
DIETZ = re.compile(r"modified\s+dietz", re.I)
IRR = re.compile(r"\birr\b|internal\s+rate\s+of\s+return", re.I)
PERCENT = re.compile(r"%|\bpercent\b|\bbps\b|\bbasis\s+points\b", re.I)
CURRENCY = re.compile(r"(?:\b(?:usd|million|billion)\b|\$)", re.I)


def _ids_matching(blocks: list[dict], predicate) -> tuple[str, ...]:
    found = []
    for block in blocks:
        if predicate(block.get("original_text", "")):
            found.append(block["block_id"])
        for item in block.get("context") or []:
            if predicate(item.get("original_text", "")):
                found.append(item["block_id"])
    return tuple(dict.fromkeys(found))


def _value_ids(blocks: list[dict], claimed: str) -> tuple[str, ...]:
    return _ids_matching(blocks, lambda text: number_in_quote(claimed, text) if any(ch.isdigit() for ch in claimed) else claimed.lower() in text.lower())


def _claim_predicate(claimed: str, pattern: re.Pattern[str] | None = None):
    if pattern is not None:
        return lambda item: bool(pattern.search(item))
    lowered = claimed.lower()
    return lambda item: bool(lowered) and lowered in item.lower()


def _ids_in_value_context(
    blocks: list[dict],
    predicate,
    value_ids: tuple[str, ...],
    *,
    value_claimed: bool,
) -> tuple[str, ...]:
    if not value_claimed:
        return _ids_matching(blocks, predicate)
    anchors = set(value_ids)
    if not anchors:
        return ()
    found: list[str] = []
    for block in blocks:
        group = [block, *(block.get("context") or [])]
        if not anchors.intersection(str(item.get("block_id") or "") for item in group):
            continue
        for item in group:
            if predicate(item.get("original_text", "")):
                found.append(item["block_id"])
    return tuple(dict.fromkeys(found))


def assess_fields(field_values: dict[str, str], blocks: list[dict], *, method: str = "rule:v1") -> list[FieldAssessment]:
    assessments: list[FieldAssessment] = []
    value = field_values.get("value") or field_values.get("value_raw") or ""
    value_ids = _value_ids(blocks, value) if value else ()
    value_claimed = "value" in field_values or "value_raw" in field_values

    for field, claimed in field_values.items():
        if field in {"value", "value_raw"}:
            if value and value_ids:
                label = "SUPPORTED"
                reason = "The claimed numerals appear at number boundaries in retrieved source text."
                supporting = value_ids
                conflicting: tuple[str, ...] = ()
            else:
                label = "INSUFFICIENT_EVIDENCE"
                reason = (
                    "Retrieved passages do not contain the claimed numerals at number boundaries."
                    if value
                    else "A blank claimed value contains no fact to verify."
                )
                supporting = ()
                conflicting = ()
        elif field in {"date", "as_of_date", "period_end"}:
            supporting = _ids_in_value_context(
                blocks,
                lambda item: bool(claimed) and claimed.lower() in item.lower(),
                value_ids,
                value_claimed=value_claimed,
            )
            present = bool(supporting)
            label = "SUPPORTED" if present else "INSUFFICIENT_EVIDENCE"
            reason = (
                "The claimed date string appears in retrieved source text."
                if present
                else "Retrieved passages omit the claimed date string."
            )
            conflicting = ()
        elif field in {"unit", "unit_scale"}:
            if claimed.lower() in {"percent", "%", "bps"}:
                pattern = PERCENT
            elif claimed.lower() in {"usd", "currency", "$"}:
                pattern = CURRENCY
            else:
                pattern = None
            predicate = _claim_predicate(claimed, pattern)
            supporting = _ids_in_value_context(
                blocks, predicate, value_ids, value_claimed=value_claimed
            )
            present = bool(supporting)
            label = "SUPPORTED" if present else "INSUFFICIENT_EVIDENCE"
            reason = (
                "Unit wording appears beside the retrieved passages."
                if present
                else "Retrieved passages omit matching unit wording."
            )
            conflicting = ()
        elif field == "fee_basis":
            net_ids = _ids_in_value_context(
                blocks, lambda item: bool(FEE_NET.search(item)), value_ids, value_claimed=value_claimed
            )
            gross_ids = _ids_in_value_context(
                blocks, lambda item: bool(FEE_GROSS.search(item)), value_ids, value_claimed=value_claimed
            )
            round_ids = _ids_in_value_context(
                blocks, rounding_note, value_ids, value_claimed=value_claimed
            )
            claimed_net = claimed.lower() in {"net", "net_of_fees", "net of fees"}
            claimed_gross = claimed.lower() in {"gross", "gross_of_fees", "gross of fees"}
            if claimed_net and net_ids:
                label = "SUPPORTED"
                reason = "Retrieved passages print net-fee wording."
                supporting = net_ids
                conflicting = gross_ids
            elif claimed_gross and gross_ids:
                label = "SUPPORTED"
                reason = "Retrieved passages print gross-fee wording."
                supporting = gross_ids
                conflicting = net_ids
            elif claimed_net and gross_ids and not net_ids:
                label = "CONTRADICTED"
                reason = "Retrieved passages print gross-fee wording for this claim."
                supporting = ()
                conflicting = gross_ids
            elif claimed_gross and net_ids and not gross_ids:
                label = "CONTRADICTED"
                reason = "Retrieved passages print net-fee wording for this claim."
                supporting = ()
                conflicting = net_ids
            elif round_ids and value_ids:
                label = "INSUFFICIENT_EVIDENCE"
                reason = "A rounding note beside a matching number is insufficient fee-basis evidence."
                supporting = ()
                conflicting = ()
            else:
                label = "INSUFFICIENT_EVIDENCE"
                reason = "Missing fee wording is insufficient evidence for a gross or net claim."
                supporting = ()
                conflicting = ()
        elif field == "method":
            if "dietz" in claimed.lower():
                pattern = DIETZ
            elif "irr" in claimed.lower():
                pattern = IRR
            else:
                pattern = None
            predicate = _claim_predicate(claimed, pattern)
            found = _ids_matching(blocks, predicate)
            label = "SUPPORTED" if found else "INSUFFICIENT_EVIDENCE"
            reason = (
                "Retrieved passages print the claimed method."
                if found
                else "A citation to an unrelated note is insufficient method evidence."
            )
            supporting = found
            conflicting = ()
        elif field in {"entity_scope", "subject", "subject_name"}:
            supporting = _ids_in_value_context(
                blocks,
                lambda item: bool(claimed) and claimed.lower() in item.lower(),
                value_ids,
                value_claimed=value_claimed,
            )
            present = bool(supporting)
            label = "SUPPORTED" if present else "INSUFFICIENT_EVIDENCE"
            reason = (
                "The claimed subject name appears in retrieved source text."
                if present
                else "Retrieved passages omit the claimed subject name."
            )
            conflicting = ()
        else:
            supporting = _ids_in_value_context(
                blocks,
                lambda item: bool(claimed) and claimed.lower() in item.lower(),
                value_ids,
                value_claimed=value_claimed,
            )
            present = bool(supporting)
            label = "SUPPORTED" if present else "INSUFFICIENT_EVIDENCE"
            reason = "Retrieved passages were compared for the claimed string."
            conflicting = ()
        assessments.append(
            FieldAssessment(
                field=field,
                claimed_value=claimed,
                assessment=label,
                reason=reason,
                supporting_ids=supporting,
                conflicting_ids=conflicting,
                method=method,
                review_state="proposed",
            )
        )
    return assessments
