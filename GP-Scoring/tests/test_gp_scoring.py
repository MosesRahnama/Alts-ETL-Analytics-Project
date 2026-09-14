from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

GP_ROOT = Path(__file__).resolve().parents[1]
PARENT = GP_ROOT.parent
if str(GP_ROOT) not in sys.path:
    sys.path.insert(0, str(GP_ROOT))

import briefing
import dashboard
import inputs
import scoring
from run import _append_missing_fixture_decisions, _report_id


def policy(**updates):
    value = json.loads((GP_ROOT / "policy.json").read_text(encoding="utf-8"))
    value.update(updates)
    return value


def record(fund_id, manager_id, strategy, vintage, dpi, rvpi, *, as_of="2026-06-30", currency="USD"):
    paid = 100.0
    return {
        "population": "fixture",
        "fund_id": fund_id,
        "manager_id": manager_id,
        "manager_name": manager_id,
        "fund_period_id": f"P_{fund_id}",
        "strategy": strategy,
        "currency": currency,
        "vintage_year": str(vintage),
        "as_of_date": as_of,
        "measurement_basis": "synthetic_basis_unspecified",
        "paid_in_capital_itd": str(paid),
        "distributions_itd": str(paid * dpi),
        "nav": str(paid * rvpi),
        "quality_approved": True,
        "quality_reason": "QUALITY_APPROVED:TEST",
        "evidence_id": f"SYNTH:{fund_id}",
        "input_reasons": [],
    }


def masters(records, extra=None):
    fund_master = []
    seen = set()
    for row in records + (extra or []):
        if row["fund_id"] in seen:
            continue
        seen.add(row["fund_id"])
        fund_master.append(
            {
                "fund_id": row["fund_id"],
                "fund_manager_id": row["manager_id"],
                "fund_manager_name": row["manager_id"],
                "strategy": row["strategy"],
            }
        )
    manager_ids = sorted({row["manager_id"] for row in records + (extra or [])})
    manager_master = [{"manager_id": manager_id, "manager_name": manager_id} for manager_id in manager_ids]
    return fund_master, manager_master


def compact_policy(**updates):
    p = policy(
        min_maturity_years=0,
        peer_min_funds=2,
        peer_min_managers=2,
        manager_min_funds=1,
        manager_min_coverage=0.5,
    )
    p.update(updates)
    return p


def test_t01_hash_drift_is_detected(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    fp = {str(path): inputs.sha256_file(path)}
    assert inputs.verify_fingerprints(fp) == []
    path.write_text("a\n2\n", encoding="utf-8")
    assert inputs.verify_fingerprints(fp) == [f"input hash changed: {path}"]


def test_t02_conflicting_duplicate_disposition_remains_excluded():
    decisions = []
    preliminary = {"F1": {"reasons": ["CONFLICTING_FUND_PERIOD_DUPLICATES"]}}
    output = _append_missing_fixture_decisions(decisions, preliminary)
    assert output[0]["status"] == "EXCLUDED"
    assert output[0]["primary_reason"] == "CONFLICTING_FUND_PERIOD_DUPLICATES"


def test_t03_peer_partition_does_not_mix_currency():
    rows = [
        record("F1", "M1", "buyout", 2020, 0.6, 1.0, currency="USD"),
        record("F2", "M2", "buyout", 2020, 0.5, 1.0, currency="USD"),
        record("F3", "M3", "buyout", 2020, 0.7, 1.0, currency="EUR"),
    ]
    fm, mm = masters(rows)
    features, _, _ = scoring.score_fixture(rows, fm, mm, compact_policy())
    f1 = next(row for row in features if row["fund_id"] == "F1")
    assert f1["status"] == "PEERS_INSUFFICIENT"
    assert f1["peer_count"] == "1"


def test_t04_latest_incomplete_quality_run_cannot_inherit_old_pass():
    required = ["R01", "R02"]
    rows = [
        {"run_id": "OLD", "checked_at": "2026-01-01T00:00:00Z", "record_id": "P1", "rule_id": "R01", "severity": "error", "status": "PASS"},
        {"run_id": "OLD", "checked_at": "2026-01-01T00:00:00Z", "record_id": "P1", "rule_id": "R02", "severity": "error", "status": "PASS"},
        {"run_id": "NEW", "checked_at": "2026-02-01T00:00:00Z", "record_id": "P1", "rule_id": "R01", "severity": "error", "status": "PASS"},
    ]
    approval, state = inputs.resolve_quality_approval(rows, {"P1"}, required)
    assert approval["P1"] == (False, "LATEST_QUALITY_RUN_INCOMPLETE")
    assert state["status"] == "LATEST_QUALITY_RUN_INCOMPLETE"


def test_t04_error_failure_blocks_quality_approval():
    rows = [
        {"run_id": "R", "checked_at": "2026-01-01T00:00:00Z", "record_id": "P1", "rule_id": "R01", "severity": "error", "status": "PASS"},
        {"run_id": "R", "checked_at": "2026-01-01T00:00:00Z", "record_id": "P1", "rule_id": "R02", "severity": "error", "status": "FAIL"},
    ]
    approval, _ = inputs.resolve_quality_approval(rows, {"P1"}, ["R01", "R02"])
    assert approval["P1"][0] is False
    assert "R02" in approval["P1"][1]


def test_t05_financial_arithmetic_and_scale_invariance():
    base = scoring.compute_multiples({"paid_in_capital_itd": 100, "distributions_itd": 60, "nav": 80})
    scaled = scoring.compute_multiples({"paid_in_capital_itd": 100_000, "distributions_itd": 60_000, "nav": 80_000})
    assert base["dpi"] == pytest.approx(0.6)
    assert base["rvpi"] == pytest.approx(0.8)
    assert base["tvpi"] == pytest.approx(1.4)
    assert scaled["dpi"] == pytest.approx(base["dpi"])
    assert scaled["tvpi"] == pytest.approx(base["tvpi"])
    with pytest.raises(scoring.ScoringError):
        scoring.compute_multiples({"paid_in_capital_itd": 0, "distributions_itd": 1, "nav": 1})


def test_t06_midpoint_ties_are_equal():
    assert scoring.midpoint_percentile(2.0, [1.0, 2.0, 2.0, 3.0]) == pytest.approx(50.0)


def test_t06_same_manager_funds_are_not_peers():
    rows = [
        record("F1", "M1", "buyout", 2020, 0.6, 1.0),
        record("F1B", "M1", "buyout", 2020, 0.9, 1.2),
        record("F2", "M2", "buyout", 2020, 0.5, 1.0),
        record("F3", "M3", "buyout", 2020, 0.7, 1.0),
    ]
    fm, mm = masters(rows)
    features, _, _ = scoring.score_fixture(rows, fm, mm, compact_policy())
    f1 = next(row for row in features if row["fund_id"] == "F1")
    peers = set(json.loads(f1["peer_fund_ids"]))
    assert peers == {"F2", "F3"}


def test_t06_permutation_does_not_change_scores():
    rows = [
        record("F1", "M1", "buyout", 2020, 0.6, 1.0),
        record("F2", "M2", "buyout", 2020, 0.5, 1.0),
        record("F3", "M3", "buyout", 2020, 0.7, 1.0),
        record("F4", "M4", "buyout", 2020, 0.8, 0.8),
    ]
    fm, mm = masters(rows)
    a = scoring.score_fixture(rows, fm, mm, compact_policy())[0]
    b = scoring.score_fixture(list(reversed(rows)), list(reversed(fm)), list(reversed(mm)), compact_policy())[0]
    assert [(x["fund_id"], x["fund_score"]) for x in a] == [(x["fund_id"], x["fund_score"]) for x in b]


def test_t07_partial_manager_has_blank_score_and_rank():
    selected = [
        record("F1", "M1", "buyout", 2020, 0.6, 1.0),
        record("F2", "M2", "buyout", 2020, 0.5, 1.0),
        record("F3", "M3", "buyout", 2020, 0.7, 1.0),
        record("F4", "M4", "buyout", 2020, 0.8, 0.8),
    ]
    extra = [record("F1X", "M1", "buyout", 2017, 0.5, 0.5), record("F1Y", "M1", "buyout", 2016, 0.5, 0.5)]
    fm, mm = masters(selected, extra)
    _, cards, _ = scoring.score_fixture(selected, fm, mm, compact_policy(manager_min_funds=1, manager_min_coverage=0.75))
    m1 = next(row for row in cards if row["manager_id"] == "M1")
    assert float(m1["coverage"]) == pytest.approx(1 / 3)
    assert m1["status"] == "PARTIAL_TRACK_RECORD"
    assert m1["score"] == ""
    assert m1["rank"] == ""


def test_t08_nav_haircut_never_raises_fund_score():
    rows = [
        record("F1", "M1", "buyout", 2020, 0.2, 1.8),
        record("F2", "M2", "buyout", 2020, 0.8, 0.8),
        record("F3", "M3", "buyout", 2020, 1.0, 0.5),
        record("F4", "M4", "buyout", 2020, 0.4, 1.0),
    ]
    fm, mm = masters(rows)
    features, _, _ = scoring.score_fixture(rows, fm, mm, compact_policy())
    for row in features:
        if row["fund_score"]:
            assert float(row["scenario_score"]) <= float(row["fund_score"]) + 1e-10


def llm_case():
    cards = [
        {
            "manager_id": "M1",
            "manager_name": "M1",
            "strategy": "buyout",
            "status": "RANKED_DEMO",
            "rank": "1",
            "score": "70",
            "avg_tvpi_percentile": "75",
            "avg_dpi_percentile": "62.5",
            "eligible_funds": "1",
            "total_funds": "1",
            "coverage": "1",
            "scenario_score": "65",
            "scenario_rank": "1",
            "score_change_nav_haircut": "-5",
            "as_of_date": "2026-06-30",
            "constituent_fund_ids": "[\"F1\"]",
        }
    ]
    features = [
        {
            "fund_id": "F1",
            "vintage_year": "2020",
            "currency": "USD",
            "dpi": "1",
            "rvpi": "1",
            "tvpi": "2",
            "nav_dependence": "0.5",
            "tvpi_percentile": "75",
            "dpi_percentile": "62.5",
            "fund_score": "70",
            "scenario_score": "65",
            "evidence_ids": "[\"E1\"]",
        }
    ]
    return cards, features


def llm_response():
    return {
        "summary": "The supplied record supports further diligence.",
        "summary_evidence_ids": ["E1"],
        "strengths": [{"text": "Cash realization is comparatively strong.", "evidence_ids": ["E1"]}],
        "risks": [{"text": "Remaining value still affects the assessment.", "evidence_ids": ["E1"]}],
        "questions": [{"text": "What supports the remaining marks?", "evidence_ids": []}],
    }


def test_t09_unknown_evidence_reference_is_rejected():
    value = llm_response()
    value["risks"][0]["evidence_ids"] = ["UNKNOWN"]
    with pytest.raises(briefing.BriefingError):
        briefing.validate_llm_response(value, {"E1"})


def test_t09_missing_openrouter_key_returns_template(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cards, features = llm_case()
    briefs, cache = briefing.generate_briefs(
        cards, features, compact_policy(), GP_ROOT / "brief-prompt.txt", "openrouter"
    )
    assert briefs[0]["mode"] == "template"
    assert briefs[0]["fallback_reason"] == "OPENROUTER_API_KEY_MISSING"
    assert briefs[0]["model"] == "google/gemini-3.8-flash"
    assert cache["status"] == "fallback"


def test_t09_dry_run_uses_gemini_default_without_network(monkeypatch):
    cards, features = llm_case()
    monkeypatch.setattr(
        briefing,
        "_openrouter_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network path called")),
    )
    briefs, cache = briefing.generate_briefs(
        cards,
        features,
        compact_policy(),
        GP_ROOT / "brief-prompt.txt",
        "openrouter",
        dry_run=True,
    )
    assert briefs[0]["mode"] == "dry_run"
    assert briefs[0]["provider"] == "openrouter"
    assert briefs[0]["model"] == "google/gemini-3.8-flash"
    assert cache["status"] == "dry_run"
    assert cache["responses"]


def test_t09_openrouter_and_anthropic_use_separate_adapters(monkeypatch):
    cards, features = llm_case()
    called = []

    def fake_openrouter(*args, **kwargs):
        called.append("openrouter")
        return llm_response(), {"input_tokens": 100, "output_tokens": 50}, "google/gemini-3.8-flash"

    def fake_anthropic(*args, **kwargs):
        called.append("anthropic")
        return llm_response(), {"input_tokens": 100, "output_tokens": 50}, "claude-sonnet-5"

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    monkeypatch.setattr(briefing, "_openrouter_request", fake_openrouter)
    monkeypatch.setattr(briefing, "_anthropic_request", fake_anthropic)

    gemini, _ = briefing.generate_briefs(
        cards, features, compact_policy(), GP_ROOT / "brief-prompt.txt", "openrouter"
    )
    claude, _ = briefing.generate_briefs(
        cards, features, compact_policy(), GP_ROOT / "brief-prompt.txt", "anthropic"
    )
    assert called == ["openrouter", "anthropic"]
    assert gemini[0]["provider"] == "openrouter"
    assert gemini[0]["model"] == "google/gemini-3.8-flash"
    assert claude[0]["provider"] == "anthropic"
    assert claude[0]["model"] == "claude-sonnet-5"


def test_t09_unknown_model_is_refused_until_price_is_declared():
    cards, features = llm_case()
    briefs, cache = briefing.generate_briefs(
        cards,
        features,
        compact_policy(),
        GP_ROOT / "brief-prompt.txt",
        "openrouter",
        model_override="some/new-model",
        dry_run=True,
    )
    assert briefs[0]["mode"] == "template"
    assert briefs[0]["fallback_reason"].startswith("MODEL_PRICE_UNKNOWN")
    assert cache["status"] == "fallback"


def test_t09_default_provider_budgets_fit_declared_cap():
    p = compact_policy()
    for provider in ("openrouter", "anthropic"):
        config = briefing.resolve_llm_config(p, provider)
        cost = briefing.maximum_run_cost(p, config, int(p["brief_manager_limit"]))
        assert cost <= float(p["llm"]["max_run_cost_usd"])


def test_t09_openrouter_request_has_structured_output_and_private_routing(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "google/gemini-3.8-flash",
                "choices": [{"message": {"content": json.dumps(llm_response())}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            }

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    config = briefing.resolve_llm_config(compact_policy(), "openrouter")
    parsed, usage, model = briefing._openrouter_request(
        "test-key",
        config,
        "prompt",
        {"evidence_ids": ["E1"]},
        briefing.response_schema(),
        2000,
    )
    body = captured["json"]
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert body["model"] == "google/gemini-3.8-flash"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {
        "zdr": True,
        "data_collection": "deny",
        "allow_fallbacks": False,
        "require_parameters": True,
    }
    assert "tools" not in body
    assert parsed["summary_evidence_ids"] == ["E1"]
    assert usage["total_tokens"] == 150
    assert model == "google/gemini-3.8-flash"


def test_t09_anthropic_request_uses_direct_messages_api(monkeypatch):
    captured = {}

    class Block:
        type = "text"
        text = json.dumps(llm_response())

    class Usage:
        input_tokens = 100
        output_tokens = 50

    class Message:
        content = [Block()]
        usage = Usage()
        model = "claude-sonnet-5"

    class Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return Message()

    class FakeAnthropicClient:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.messages = Messages()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    config = briefing.resolve_llm_config(compact_policy(), "anthropic")
    parsed, usage, model = briefing._anthropic_request(
        "test-key",
        config,
        "prompt",
        {"evidence_ids": ["E1"]},
        briefing.response_schema(),
        2000,
    )
    assert captured["model"] == "claude-sonnet-5"
    assert captured["output_config"]["effort"] == "low"
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert "tools" not in captured
    assert parsed["summary_evidence_ids"] == ["E1"]
    assert usage["input_tokens"] == 100
    assert model == "claude-sonnet-5"


def test_t09_report_id_changes_with_provider_variant():
    briefs = [{"manager_key": "M1|buyout", "summary": "x"}]
    openrouter = {
        "provider": "openrouter",
        "model_override": "",
        "dry_run": True,
        "cache_status": "dry_run",
        "resolved_model": "google/gemini-3.8-flash",
    }
    anthropic = {
        "provider": "anthropic",
        "model_override": "",
        "dry_run": True,
        "cache_status": "dry_run",
        "resolved_model": "claude-sonnet-5",
    }
    assert _report_id("DATA", openrouter, briefs) != _report_id("DATA", anthropic, briefs)


def test_t10_dashboard_is_self_contained_and_population_labeled():
    html = dashboard.render_dashboard(
        {
            "population": "fixture",
            "as_of_date": "2026-06-30",
            "build_id": "DATA",
            "report_id": "REPORT",
            "quality_run": {},
        },
        compact_policy(),
        [],
        [],
        [],
        [],
        [],
    )
    assert "fictional synthetic managers only" in html
    assert "Real records appear in a separate evidence section" in html
    assert "report REPORT | data DATA" in html
    assert "<script src=" not in html
    assert '<link rel="stylesheet"' not in html
    assert "http://" not in html and "https://" not in html


def test_current_fixture_census_and_real_evidence_boundary():
    p = policy()
    fixture = inputs.load_fixture(PARENT, p["default_as_of"], p)
    observed = inputs.build_observed_evidence(PARENT, p["real_evidence_cards"])
    assert len(fixture["fund_master"]) == 800
    assert len(fixture["manager_master"]) == 200
    assert len(fixture["selected_records"]) == 693
    assert fixture["quality_run"]["status"] == "COMPLETE"
    assert all(row["manager_id"].startswith("MANAGER_SYNTH_") for row in fixture["selected_records"])
    assert 1 <= len(observed["cards"]) <= 3
    assert all(card["status"] == "EVIDENCE_ONLY" for card in observed["cards"])
