from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping


class BriefingError(ValueError):
    pass


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _select_cards(scorecards: list[dict[str, str]], policy: Mapping[str, Any]) -> list[dict[str, str]]:
    initial_strategy = str(policy.get("initial_strategy", ""))
    ranked = [row for row in scorecards if row.get("status") == "RANKED_DEMO"]
    ranked.sort(
        key=lambda row: (
            row.get("strategy") != initial_strategy,
            int(row.get("rank") or 10**9),
            row.get("manager_id", ""),
        )
    )
    return ranked[: int(policy.get("brief_manager_limit", 3))]


def _feature_packet(card: Mapping[str, str], features: list[dict[str, str]]) -> dict[str, Any]:
    fund_ids = set(json.loads(card.get("constituent_fund_ids", "[]")))
    fund_rows = [row for row in features if row.get("fund_id") in fund_ids]
    evidence_ids: list[str] = []
    for row in fund_rows:
        evidence_ids.extend(json.loads(row.get("evidence_ids", "[]")))
    return {
        "manager_id": card.get("manager_id", ""),
        "manager_name": card.get("manager_name", ""),
        "strategy": card.get("strategy", ""),
        "as_of_date": card.get("as_of_date", ""),
        "status": card.get("status", ""),
        "rank": card.get("rank", ""),
        "score": card.get("score", ""),
        "avg_tvpi_percentile": card.get("avg_tvpi_percentile", ""),
        "avg_dpi_percentile": card.get("avg_dpi_percentile", ""),
        "eligible_funds": card.get("eligible_funds", ""),
        "total_funds": card.get("total_funds", ""),
        "coverage": card.get("coverage", ""),
        "scenario_score": card.get("scenario_score", ""),
        "scenario_rank": card.get("scenario_rank", ""),
        "score_change_nav_haircut": card.get("score_change_nav_haircut", ""),
        "funds": [
            {
                "fund_id": row.get("fund_id", ""),
                "vintage_year": row.get("vintage_year", ""),
                "currency": row.get("currency", ""),
                "dpi": row.get("dpi", ""),
                "rvpi": row.get("rvpi", ""),
                "tvpi": row.get("tvpi", ""),
                "nav_dependence": row.get("nav_dependence", ""),
                "tvpi_percentile": row.get("tvpi_percentile", ""),
                "dpi_percentile": row.get("dpi_percentile", ""),
                "fund_score": row.get("fund_score", ""),
                "scenario_score": row.get("scenario_score", ""),
                "evidence_ids": json.loads(row.get("evidence_ids", "[]")),
            }
            for row in fund_rows
        ],
        "evidence_ids": sorted(set(evidence_ids)),
        "missing_fields": [
            "complete realized-loss history",
            "team stability",
            "deal-level valuation support",
            "governance and key-person evidence",
        ],
    }


def _claim(text: str, evidence_ids: list[str]) -> dict[str, Any]:
    return {"text": text, "evidence_ids": sorted(set(evidence_ids))}


def template_briefs(
    scorecards: list[dict[str, str]],
    features: list[dict[str, str]],
    policy: Mapping[str, Any],
    fallback_reason: str = "",
    *,
    provider: str = "off",
    model: str = "",
) -> list[dict[str, Any]]:
    briefs: list[dict[str, Any]] = []
    for card in _select_cards(scorecards, policy):
        packet = _feature_packet(card, features)
        score = float(card["score"])
        tvpi = float(card["avg_tvpi_percentile"])
        dpi = float(card["avg_dpi_percentile"])
        scenario = float(card["scenario_score"])
        coverage = 100.0 * float(card["coverage"])
        evidence_ids = packet["evidence_ids"]
        strengths: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []
        if tvpi >= 50:
            strengths.append(_claim("Total-value performance is above the supplied peer midpoint.", evidence_ids))
        else:
            risks.append(_claim("Total-value performance is below the supplied peer midpoint.", evidence_ids))
        if dpi >= 50:
            strengths.append(_claim("Cash realization is above the supplied peer midpoint.", evidence_ids))
        else:
            risks.append(_claim("Cash realization is below the supplied peer midpoint.", evidence_ids))
        if scenario < score - 5:
            risks.append(_claim("The stated NAV reduction materially lowers the manager score.", evidence_ids))
        else:
            strengths.append(_claim("The stated NAV reduction has a smaller effect on the manager score.", evidence_ids))
        briefs.append(
            {
                "manager_key": f"{card['manager_id']}|{card['strategy']}",
                "manager_id": card["manager_id"],
                "manager_name": card["manager_name"],
                "strategy": card["strategy"],
                "mode": "template",
                "provider": provider,
                "model": model,
                "review_status": "TEMPLATE",
                "summary": (
                    f"This fictional manager has a composite score of {score:.1f} and rank {card['rank']} within the supplied {card['strategy']} sample, "
                    f"using {card['eligible_funds']} qualifying funds with {coverage:.0f}% series coverage."
                ),
                "summary_evidence_ids": evidence_ids,
                "strengths": strengths,
                "risks": risks,
                "questions": [
                    _claim("What evidence supports the current NAV marks for the largest remaining positions?", []),
                    _claim("Which realized exits drove the cash-return profile, and which outcomes were written off or impaired?", []),
                    _claim("Have team ownership, strategy, or underwriting standards changed across the funds in this track record?", []),
                ],
                "evidence_ids": evidence_ids,
                "packet_hash": _hash_json(packet),
                "usage": {},
                "actual_cost_usd": 0.0,
                "fallback_reason": fallback_reason,
            }
        )
    return briefs


def response_schema() -> dict[str, Any]:
    claim = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["text", "evidence_ids"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "summary_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "strengths": {"type": "array", "items": claim},
            "risks": {"type": "array", "items": claim},
            "questions": {"type": "array", "items": claim},
        },
        "required": ["summary", "summary_evidence_ids", "strengths", "risks", "questions"],
        "additionalProperties": False,
    }


def _validate_claim(value: Any, permitted: set[str], *, evidence_required: bool) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"text", "evidence_ids"}:
        raise BriefingError("LLM claim does not match the expected schema")
    if not isinstance(value["text"], str) or not value["text"].strip():
        raise BriefingError("LLM claim text is missing")
    ids = value["evidence_ids"]
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise BriefingError("LLM claim evidence_ids must be a string array")
    unknown = set(ids) - permitted
    if unknown:
        raise BriefingError("LLM cited unknown evidence IDs: " + ",".join(sorted(unknown)))
    if evidence_required and not ids:
        raise BriefingError("LLM factual claim has no evidence ID")
    return {"text": value["text"].strip(), "evidence_ids": sorted(set(ids))}


def validate_llm_response(value: Any, permitted_evidence_ids: set[str]) -> dict[str, Any]:
    expected = {"summary", "summary_evidence_ids", "strengths", "risks", "questions"}
    if not isinstance(value, dict) or set(value) != expected:
        raise BriefingError("LLM response fields do not match the expected schema")
    if not isinstance(value["summary"], str) or not value["summary"].strip():
        raise BriefingError("LLM summary is missing")
    summary_ids = value["summary_evidence_ids"]
    if not isinstance(summary_ids, list) or not all(isinstance(item, str) for item in summary_ids):
        raise BriefingError("LLM summary_evidence_ids must be a string array")
    unknown = set(summary_ids) - permitted_evidence_ids
    if unknown:
        raise BriefingError("LLM cited unknown evidence IDs: " + ",".join(sorted(unknown)))
    if permitted_evidence_ids and not summary_ids:
        raise BriefingError("LLM summary has no evidence ID")
    output = {
        "summary": value["summary"].strip(),
        "summary_evidence_ids": sorted(set(summary_ids)),
        "strengths": [],
        "risks": [],
        "questions": [],
    }
    for key in ("strengths", "risks", "questions"):
        items = value[key]
        if not isinstance(items, list):
            raise BriefingError(f"LLM field {key} must be an array")
        output[key] = [
            _validate_claim(item, permitted_evidence_ids, evidence_required=key in {"strengths", "risks"})
            for item in items
        ]
    return output


def validate_claude_response(value: Any, permitted_evidence_ids: set[str]) -> dict[str, Any]:
    """Backward-compatible name for older callers and tests."""
    return validate_llm_response(value, permitted_evidence_ids)


def resolve_llm_config(
    policy: Mapping[str, Any], provider: str, model_override: str = ""
) -> dict[str, Any]:
    llm = policy.get("llm", {})
    providers = llm.get("providers", {}) if isinstance(llm, Mapping) else {}
    if provider not in providers:
        raise BriefingError(f"unknown LLM provider: {provider}")
    config = dict(providers[provider])
    model = model_override.strip() or str(config.get("default_model", "")).strip()
    if not model:
        raise BriefingError(f"no model configured for provider: {provider}")
    models = config.get("models", {})
    price = models.get(model) if isinstance(models, Mapping) else None
    if not isinstance(price, Mapping):
        raise BriefingError(f"MODEL_PRICE_UNKNOWN:{provider}:{model}")
    return {
        "provider": provider,
        "model": model,
        "api_key_env": str(config.get("api_key_env", "")),
        "endpoint": str(config.get("endpoint", "")),
        "routing": dict(config.get("routing", {})),
        "effort": str(config.get("effort", "")),
        "input_usd_per_million": float(price["input_usd_per_million"]),
        "output_usd_per_million": float(price["output_usd_per_million"]),
        "max_run_cost_usd": float(llm.get("max_run_cost_usd", 0.0)),
    }


def maximum_run_cost(policy: Mapping[str, Any], config: Mapping[str, Any], request_count: int) -> float:
    input_cap = int(policy.get("brief_input_token_cap", 0))
    output_cap = int(policy.get("brief_output_tokens", 0))
    per_request = (
        input_cap * float(config["input_usd_per_million"])
        + output_cap * float(config["output_usd_per_million"])
    ) / 1_000_000.0
    return per_request * request_count


def _actual_cost(usage: Mapping[str, Any], config: Mapping[str, Any]) -> float:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return (
        input_tokens * float(config["input_usd_per_million"])
        + output_tokens * float(config["output_usd_per_million"])
    ) / 1_000_000.0


def _approx_input_tokens(prompt: str, packet: Mapping[str, Any]) -> int:
    payload = prompt + "\n" + json.dumps(packet, sort_keys=True, separators=(",", ":"))
    return math.ceil(len(payload) / 3.0)


def _openrouter_request(
    api_key: str,
    config: Mapping[str, Any],
    prompt: str,
    packet: Mapping[str, Any],
    schema: Mapping[str, Any],
    max_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    import requests

    body = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(packet, sort_keys=True)},
        ],
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "gp_diligence_brief", "strict": True, "schema": schema},
        },
        "provider": config.get("routing", {}),
    }
    response = requests.post(
        str(config["endpoint"]),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "Alts ETL GP Scoring",
        },
        json=body,
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise BriefingError("OpenRouter returned no choices")
    content = choices[0].get("message", {}).get("content", "")
    parsed = json.loads(content)
    raw_usage = payload.get("usage") or {}
    usage = {
        "input_tokens": raw_usage.get("prompt_tokens"),
        "output_tokens": raw_usage.get("completion_tokens"),
        "total_tokens": raw_usage.get("total_tokens"),
    }
    return parsed, usage, str(payload.get("model") or config["model"])


def _anthropic_request(
    api_key: str,
    config: Mapping[str, Any],
    prompt: str,
    packet: Mapping[str, Any],
    schema: Mapping[str, Any],
    max_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    import anthropic  # type: ignore

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=str(config["model"]),
        max_tokens=max_tokens,
        system=prompt,
        messages=[{"role": "user", "content": json.dumps(packet, sort_keys=True)}],
        output_config={
            "effort": str(config.get("effort") or "low"),
            "format": {"type": "json_schema", "schema": schema},
        },
    )
    text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
    parsed = json.loads(text)
    usage = {
        "input_tokens": getattr(message.usage, "input_tokens", None),
        "output_tokens": getattr(message.usage, "output_tokens", None),
        "total_tokens": None,
    }
    return parsed, usage, str(getattr(message, "model", config["model"]))


def _flatten_evidence(value: Mapping[str, Any]) -> list[str]:
    ids = set(value.get("summary_evidence_ids", []))
    for key in ("strengths", "risks", "questions"):
        for item in value.get(key, []):
            ids.update(item.get("evidence_ids", []))
    return sorted(ids)


def _load_cache(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"responses": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"responses": {}}
    return value if isinstance(value, dict) and isinstance(value.get("responses"), dict) else {"responses": {}}


def generate_briefs(
    scorecards: list[dict[str, str]],
    features: list[dict[str, str]],
    policy: Mapping[str, Any],
    prompt_path: Path,
    provider: str,
    *,
    model_override: str = "",
    dry_run: bool = False,
    existing_cache_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if provider == "off":
        return template_briefs(scorecards, features, policy), {}

    prompt = prompt_path.read_text(encoding="utf-8")
    schema = response_schema()
    cards = _select_cards(scorecards, policy)
    try:
        config = resolve_llm_config(policy, provider, model_override)
    except BriefingError as exc:
        reason = str(exc)
        return template_briefs(scorecards, features, policy, reason, provider=provider, model=model_override), {
            "status": "fallback",
            "provider": provider,
            "model": model_override,
            "reason": reason,
            "responses": {},
        }

    reserved_cost = maximum_run_cost(policy, config, len(cards))
    max_cost = float(config["max_run_cost_usd"])
    if reserved_cost > max_cost + 1e-12:
        reason = "LLM_RUN_BUDGET_EXCEEDED"
        return template_briefs(scorecards, features, policy, reason, provider=provider, model=str(config["model"])), {
            "status": "fallback",
            "provider": provider,
            "model": config["model"],
            "reason": reason,
            "reserved_max_cost_usd": reserved_cost,
            "budget_usd": max_cost,
            "responses": {},
        }

    cache = {"responses": {}} if dry_run else _load_cache(existing_cache_path)
    cache.update(
        {
            "status": "dry_run" if dry_run else "live",
            "provider": provider,
            "model": config["model"],
            "reserved_max_cost_usd": reserved_cost,
            "budget_usd": max_cost,
        }
    )
    cache.setdefault("responses", {})

    api_key = os.environ.get(str(config["api_key_env"]), "").strip()
    if not api_key and not dry_run:
        reason = f"{config['api_key_env']}_MISSING"
        cache.update({"status": "fallback", "reason": reason})
        return template_briefs(scorecards, features, policy, reason, provider=provider, model=str(config["model"])), cache

    output: list[dict[str, Any]] = []
    max_tokens = int(policy.get("brief_output_tokens", 2000))
    input_cap = int(policy.get("brief_input_token_cap", 12000))
    for card in cards:
        packet = _feature_packet(card, features)
        permitted = set(packet["evidence_ids"])
        approximate_tokens = _approx_input_tokens(prompt, packet)
        cache_key = _hash_json(
            {"packet": packet, "provider": provider, "model": config["model"], "prompt": prompt, "schema": schema}
        )
        if approximate_tokens > input_cap:
            reason = "LLM_PACKET_TOKEN_CAP_EXCEEDED"
            output.append(
                template_briefs([card], features, policy, reason, provider=provider, model=str(config["model"]))[0]
            )
            cache["responses"][cache_key] = {"manager_key": f"{card['manager_id']}|{card['strategy']}", "fallback_reason": reason}
            continue
        if dry_run:
            row = template_briefs(
                [card], features, policy, "DRY_RUN_NO_NETWORK", provider=provider, model=str(config["model"])
            )[0]
            row["mode"] = "dry_run"
            row["review_status"] = "NO_MODEL_CALL"
            output.append(row)
            cache["responses"][cache_key] = {
                "manager_key": row["manager_key"],
                "packet_hash": row["packet_hash"],
                "approximate_input_tokens": approximate_tokens,
                "request_would_use": {
                    "provider": provider,
                    "model": config["model"],
                    "max_tokens": max_tokens,
                    "structured_output": True,
                    "tools": False,
                },
            }
            continue
        cached = cache["responses"].get(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("validated_response"), dict):
            try:
                parsed = validate_llm_response(cached["validated_response"], permitted)
                usage = cached.get("usage", {})
                row = {
                    "manager_key": f"{card['manager_id']}|{card['strategy']}",
                    "manager_id": card["manager_id"],
                    "manager_name": card["manager_name"],
                    "strategy": card["strategy"],
                    "mode": "cache",
                    "provider": provider,
                    "model": config["model"],
                    "review_status": "DRAFT_REVIEW_REQUIRED",
                    **parsed,
                    "evidence_ids": _flatten_evidence(parsed),
                    "packet_hash": _hash_json(packet),
                    "usage": usage,
                    "actual_cost_usd": cached.get("actual_cost_usd", 0.0),
                    "fallback_reason": "",
                }
                output.append(row)
                continue
            except BriefingError:
                pass
        try:
            if provider == "openrouter":
                raw, usage, response_model = _openrouter_request(
                    api_key, config, prompt, packet, schema, max_tokens
                )
            elif provider == "anthropic":
                raw, usage, response_model = _anthropic_request(
                    api_key, config, prompt, packet, schema, max_tokens
                )
            else:
                raise BriefingError(f"unknown LLM provider: {provider}")
            parsed = validate_llm_response(raw, permitted)
            actual_cost = _actual_cost(usage, config)
            row = {
                "manager_key": f"{card['manager_id']}|{card['strategy']}",
                "manager_id": card["manager_id"],
                "manager_name": card["manager_name"],
                "strategy": card["strategy"],
                "mode": "live",
                "provider": provider,
                "model": response_model,
                "review_status": "DRAFT_REVIEW_REQUIRED",
                **parsed,
                "evidence_ids": _flatten_evidence(parsed),
                "packet_hash": _hash_json(packet),
                "usage": usage,
                "actual_cost_usd": actual_cost,
                "fallback_reason": "",
            }
            output.append(row)
            cache["responses"][cache_key] = {
                "manager_key": row["manager_key"],
                "validated_response": parsed,
                "usage": usage,
                "actual_cost_usd": actual_cost,
                "response_model": response_model,
            }
        except Exception as exc:  # Provider or validation failures must not affect numerical outputs.
            reason = f"LLM_FALLBACK:{provider}:{type(exc).__name__}"
            fallback = template_briefs(
                [card], features, policy, reason, provider=provider, model=str(config["model"])
            )[0]
            output.append(fallback)
            cache["responses"][cache_key] = {
                "manager_key": fallback["manager_key"],
                "fallback_reason": reason,
            }
    return output, cache
