from __future__ import annotations

import json
import sys
import copy
from datetime import date
from pathlib import Path

import pytest

GP_ROOT = Path(__file__).resolve().parents[1]
PARENT = GP_ROOT.parent
if str(GP_ROOT) not in sys.path:
    sys.path.insert(0, str(GP_ROOT))

import run_v2
import v2_diligence
import v2_features
import v2_inputs
import v2_stress
from v2_dashboard import render_dashboard


@pytest.fixture(scope="session")
def policy():
    return v2_inputs.read_json(GP_ROOT / "v2-policy.json")


@pytest.fixture(scope="session")
def context(policy):
    return v2_inputs.build_context(PARENT, GP_ROOT, policy)


@pytest.fixture(scope="session")
def core(context):
    return v2_features.build_core_features(context)


@pytest.fixture(scope="session")
def scenarios(context, core):
    return v2_stress.build_scenarios(context, core)


def test_v2_01_protected_baseline_is_unchanged():
    assert v2_inputs.verify_baseline(PARENT, GP_ROOT) == []


def test_v2_02_input_fingerprint_detects_drift(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    fingerprint = {str(path): v2_inputs.sha256_file(path)}
    assert v2_inputs.verify_fingerprints(fingerprint) == []
    path.write_text("a\n2\n", encoding="utf-8")
    assert v2_inputs.verify_fingerprints(fingerprint) == [f"input hash changed: {path}"]


def test_v2_03_whole_fund_flow_excludes_position_copies():
    base = {"record_status": "ACTIVE", "lp_id": "", "share_class_name": ""}
    assert v2_inputs._whole_fund_flow(base)
    assert not v2_inputs._whole_fund_flow({**base, "lp_id": "LP1"})
    assert not v2_inputs._whole_fund_flow({**base, "share_class_name": "Class A"})
    assert not v2_inputs._whole_fund_flow({**base, "record_status": "INACTIVE"})


def test_v2_04_context_census_and_no_population_mix(context):
    assert len(context["fund_master"]) == 800
    assert len(context["manager_master"]) == 200
    assert len(context["current_records"]) == 693
    assert len(context["whole_cashflows"]) == 17473
    assert all(row["fund_id"].startswith("FUND_SYNTH_") for row in context["current_records"])


def test_v2_05_strategy_pme_uses_declared_fixture_mapping(context, core):
    current = [row for row in core["fund_diagnostics"] if row["current_status"] == "AVAILABLE"]
    mapped = [row for row in current if row["ks_pme"] is not None]
    assert len(mapped) == 546
    for row in mapped:
        assert row["benchmark_id"] == context["strategy_benchmark"][row["strategy"]]
        assert context["benchmark_currency"][row["benchmark_id"]] == row["currency"]
    unsupported = [row for row in current if row["benchmark_status"] == "BENCHMARK_CURRENCY_UNSUPPORTED"]
    assert len(unsupported) == 147


def test_v2_06_realization_identity_and_missingness(core):
    for row in core["fund_diagnostics"]:
        if row["realized_share"] is None:
            assert row["nav_reliance"] is None
        else:
            assert row["realized_share"] + row["nav_reliance"] == pytest.approx(1.0)


def test_v2_07_age_snapshots_are_backward_only_and_expected_coverage(core):
    expected = {3: 657, 5: 549, 7: 438, 10: 255}
    for years, count in expected.items():
        available = [row for row in core["fund_diagnostics"] if row[f"age_{years}_status"] == "AVAILABLE"]
        assert len(available) == count
        for row in available:
            assert int(row[f"age_{years}_lag_days"]) >= 0
            assert int(row[f"age_{years}_lag_days"]) <= 100


def test_v2_08_trailing_returns_require_exact_opening_state(core):
    expected = {1: 663, 3: 550, 5: 442, 10: 148}
    for years, count in expected.items():
        assert sum(row[f"trailing_{years}y_status"] == "AVAILABLE" for row in core["fund_diagnostics"]) == count


def test_v2_09_reference_peer_membership_has_no_self_manager(context, core):
    fund_manager = {row["fund_id"]: row["fund_manager_id"] for row in context["fund_master"]}
    for row in core["cohort_membership"]:
        assert fund_manager[row["evaluated_fund_id"]] != fund_manager[row["peer_fund_id"]]


def test_v2_10_v1_reference_scores_are_exact(context, core):
    source = {
        (row["manager_id"], row["strategy"]): row
        for row in context["v1"]["scorecards"]
        if row["status"] == "RANKED_DEMO"
    }
    observed = {
        (row["manager_id"], row["strategy"]): row
        for row in core["manager_diagnostics"]
        if row["v1_status"] == "RANKED_DEMO"
    }
    assert len(source) == len(observed) == 38
    for key, expected in source.items():
        assert observed[key]["historical_score"] == pytest.approx(float(expected["score"]), abs=1e-12)
        assert str(observed[key]["historical_rank"]) == expected["rank"]


def test_v2_11_genealogy_does_not_invent_successor_when_vintage_tied(core):
    ambiguous = [row for row in core["genealogy"] if row["order_status"] == "AMBIGUOUS_SAME_VINTAGE"]
    assert ambiguous
    assert all(row["predecessor_fund_id"] == "" for row in ambiguous)


def test_v2_12_consistency_requires_real_sample_depth(core):
    rows = core["manager_diagnostics"]
    assert sum(row["consistency_status"] == "AVAILABLE" for row in rows) > 0
    for row in rows:
        if row["eligible_score_funds"] < 2:
            assert row["consistency_status"] == "CONSISTENCY_UNAVAILABLE"
        if row["score_trend_per_fund"] is not None:
            assert row["eligible_score_funds"] >= 3


def test_v2_13_holdings_reconcile_before_concentration(core):
    current = [row for row in core["fund_diagnostics"] if row["current_status"] == "AVAILABLE"]
    assert len(current) == 693
    assert all(row["holdings_status"] == "AVAILABLE" for row in current)
    for row in current:
        assert 0 < row["company_hhi"] <= 1
        assert 0 < row["top_company_share"] <= row["top3_company_share"] <= 1 + 1e-12
        assert 0 < row["sector_hhi"] <= 1


def test_v2_14_original_snapshot_cost_never_becomes_loss_metric(core):
    assert all(row["economic_loss_status"] == "UNSUPPORTED_DEFINITION" for row in core["fund_diagnostics"])


def test_v2_15_base_terms_are_scope_correct_and_uniform(context, core):
    current = [row for row in core["fund_diagnostics"] if row["current_status"] == "AVAILABLE"]
    fees = {row["management_fee_rate"] for row in current if row["management_fee_rate"] is not None}
    assert len(fees) == 1
    assert next(iter(fees)) == pytest.approx(0.018)
    assert all(row["term_status"] == "AVAILABLE" for row in current)
    # Confirm an LP override is applied only when explicitly requested.
    override = next(row for row in context["terms"] if row.get("term_scope") == "lp_override")
    base = v2_features.resolve_terms(context, override["fund_id"])
    lp = v2_features.resolve_terms(context, override["fund_id"], lp_id=override["lp_id"])
    assert base["fund_term_id"] != lp["applied_override_id"]
    assert float(lp["management_fee_rate"]) < float(base["management_fee_rate"])


def test_v2_16_geography_is_available_constant_not_missing(core):
    current = [row for row in core["fund_diagnostics"] if row["current_status"] == "AVAILABLE"]
    assert all(row["geography_status"] == "AVAILABLE_CONSTANT" for row in current)
    assert all(row["geography_hhi"] == pytest.approx(1.0) for row in current)


def test_v2_17_zero_and_nav_downside_scenarios_are_monotone(scenarios):
    zero = [row for row in scenarios["fund_scenarios"] if row["scenario_id"] == "nav_00"]
    downside = [row for row in scenarios["fund_scenarios"] if row["scenario_id"] == "nav_30"]
    assert zero
    assert downside
    assert max(abs(row["scenario_score"] - row["baseline_score"]) for row in zero) <= 1e-9
    assert all(row["scenario_score"] <= row["baseline_score"] + 1e-9 for row in downside)


def test_v2_18_weight_baseline_is_exact(scenarios):
    rows = [row for row in scenarios["fund_scenarios"] if row["scenario_id"] == "w60_40"]
    assert rows
    assert max(abs(row["scenario_score"] - row["baseline_score"]) for row in rows) <= 1e-9


def test_v2_19_leave_one_out_never_waives_history_rules(scenarios):
    best = [row for row in scenarios["manager_scenarios"] if row["scenario_id"] == "remove_best"]
    assert len(best) == 38
    assert sum(bool(row["official_eligible"]) for row in best) == 0
    assert all(row["scenario_rank"] is None for row in best)
    assert all(row["counterfactual_score"] is not None for row in best)


def test_v2_20_readiness_is_coverage_not_investment_score(core):
    assert core["readiness"]
    for row in core["readiness"]:
        if row["coverage"] is not None:
            assert 0 <= row["coverage"] <= 1
    manager_rows = [row for row in core["readiness"] if row["entity_level"] == "manager_strategy"]
    assert any(row["dimension"] == "team_strategy" and row["status"] == "UNKNOWN" for row in manager_rows)


def test_v2_21_named_real_evidence_is_evidence_only(core):
    assert len(core["real_evidence"]) == 12
    assert all(row["status"] == "EVIDENCE_ONLY" for row in core["real_evidence"])
    assert all("historical_score" not in row and "rank" not in row for row in core["real_evidence"])


def test_v2_22_dashboard_is_self_contained_and_has_eight_views(context, core, scenarios):
    html = render_dashboard(
        {"v2_data_id": "DATA", "v1_data_build_id": "V1"},
        core,
        scenarios,
        case_bundle={},
        briefs=[],
    )
    for label in (
        "Screener",
        "Manager Comparison",
        "Track Record & Peers",
        "Realization & Stress",
        "Holdings & Terms",
        "Team / Governance",
        "Evidence & Diligence",
        "RAG: Document Insights",
    ):
        assert label in html
    assert "Print IC one-pager" not in html
    assert "onepager" not in html
    assert "<script src=" not in html
    assert '<link rel="stylesheet"' not in html
    assert "http://127.0.0.1:8765" in html
    assert "https://" not in html
    assert "named real-source evidence" not in html.lower()
    assert "scored manager (fictional)" in html.lower()
    assert "/gp_manager_context" in html
    assert "/gp_search" in html
    assert "Search reviewed PDFs" in html
    assert "Reviewer session ID" not in html
    assert "research-session" not in html
    assert 'id="research-entity"' in html
    assert 'id="research-scope-type"' not in html
    assert 'id="research-manager"' not in html
    assert 'id="research-fund"' not in html
    assert "retrieval_methods:['keyword']" in html
    assert 'class="research-results-table"' in html
    assert 'class="evidence-values-table"' in html
    assert "function evidenceColumns(row)" in html
    assert "function sourceDetails(row)" in html
    assert "Source details" in html
    assert "Open source PDF" in html
    assert "Physical PDF page" not in html
    assert "tab-research" not in html
    assert "tab-scroller" not in html
    assert ".tabs{display:flex;flex-wrap:wrap" in html
    assert ".tab{flex:0 0 auto;cursor:pointer" in html
    assert ".kpi{display:flex;flex-direction:column;justify-content:space-between;" in html
    assert ".report-summary .kpis{margin:0;grid-template-columns:repeat(5,minmax(0,1fr))}" in html
    assert 'th scope="col">Printed evidence</th>' in html
    assert "window.open('about:blank','_blank')" in html
    assert "changing the manager opens its track record" in html.lower()
    for marker in (
        "--accent:#087e83",
        'class="hero"',
        'id="report-summary"',
        'aria-label="Dashboard views"',
        '<th scope="col">',
    ):
        assert marker in html


def test_v2_23_active_release_verifies_read_only():
    assert run_v2.check_only(PARENT) == 0


@pytest.fixture(scope="session")
def case_context(policy):
    return v2_inputs.build_context(PARENT, GP_ROOT, policy, include_cases=True)


@pytest.fixture(scope="session")
def case_bundle(case_context, core):
    return v2_diligence.build_case_bundle(case_context, core)


def test_v2_24_case_population_reuses_existing_manager_and_fund_ids(case_context, case_bundle):
    assert set(case_bundle["manager_cases"]) == {
        "MANAGER_SYNTH_00176",
        "MANAGER_SYNTH_00091",
        "MANAGER_SYNTH_00164",
    }
    for case in case_bundle["manager_cases"].values():
        assert case["population"] == "case_simulation"
        assert case["manager_id"] in case_context["manager_by_id"]
        assert case["fund_id"] in case_context["fund_by_id"]
        assert case_context["fund_by_id"][case["fund_id"]]["fund_manager_id"] == case["manager_id"]


def test_v2_25_case_document_registry_hashes_match(case_context):
    rows = case_context["overlay"]["document-registry.csv"]
    assert len(rows) == 18
    for row in rows:
        path = GP_ROOT / row["path"]
        assert path.is_file()
        assert v2_inputs.sha256_file(path) == row["sha256"]
        assert row["synthetic_flag"] == "true"


def test_v2_26_conflicting_ddq_and_lpa_fact_resolves_to_binding_lpa(case_bundle):
    assert len(case_bundle["conflict_resolutions"]) == 1
    resolution = case_bundle["conflict_resolutions"][0]
    assert resolution["conflict_group"] == "CONFLICT_CASE_001_GP_COMMITMENT"
    assert resolution["reviewer"] == "V2_DETERMINISTIC_CONFLICT_POLICY"
    assert resolution["rejected_fact_ids"]
    selected = next(row for row in case_bundle["resolved_facts"] if row["fact_id"] == resolution["selected_fact_id"])
    assert selected["document_family"] == "lpa_terms"
    assert float(selected["value_numeric"]) == pytest.approx(0.02)
    assert selected["resolution_status"] == "RESOLVED_TO_BINDING_LPA"


def test_v2_27_team_history_and_deal_attribution_are_temporally_valid(case_context, case_bundle):
    people = {row["person_id"]: row for row in case_context["overlay"]["team-history.csv"]}
    for row in case_context["overlay"]["deal-attribution.csv"]:
        person = people[row["person_id"]]
        assert row["action_date"] >= person["join_date"]
        if person["departure_date"]:
            assert row["action_date"] <= person["departure_date"]
    case = case_bundle["manager_cases"]["MANAGER_SYNTH_00091"]
    assert case["team_continuity"] == pytest.approx(2 / 3)
    assert case["attribution_continuity"] == pytest.approx(5 / 9)


def test_v2_28_case_loss_metrics_are_event_backed_and_separate_from_core(case_bundle, core):
    assert all(row["economic_loss_status"] == "UNSUPPORTED_DEFINITION" for row in core["fund_diagnostics"])
    for case in case_bundle["manager_cases"].values():
        assert 0 <= case["loss_ratio"] <= 1
        assert 0 <= case["writeoff_capital_ratio"] <= 1
        assert case["case_tvpi"] > 0
        assert case["evidence_ids"]


def test_v2_29_secondaries_case_financing_pair_and_unsupported_purchase_price(case_bundle):
    case = case_bundle["manager_cases"]["MANAGER_SYNTH_00164"]
    scenario = case["case_scenario"]
    assert case["strategy"] == "secondaries"
    assert scenario["facility_status"] == "AVAILABLE"
    assert scenario["xirr_with_facility"] is not None
    assert scenario["xirr_without_facility"] is not None
    assert scenario["facility_xirr_delta"] == pytest.approx(
        scenario["xirr_with_facility"] - scenario["xirr_without_facility"]
    )
    assert scenario["purchase_price_status"] == "UNAVAILABLE_NOT_IN_CASE"
    assert scenario["fx_status"] == "UNSUPPORTED_NO_CROSS_CURRENCY_CASE"


def test_v2_30_pure_distribution_delay_preserves_case_tvpi(case_bundle):
    for case in case_bundle["manager_cases"].values():
        scenario = case["case_scenario"]
        assert scenario["distribution_delay_tvpi"] == pytest.approx(case["case_tvpi"])
        if scenario["case_xirr"] is not None and scenario["distribution_delay_xirr"] is not None:
            assert scenario["distribution_delay_xirr"] <= scenario["case_xirr"] + 1e-12


def test_v2_31_case_geography_is_separate_and_varied(case_bundle, core):
    assert all(row["geography_status"] == "AVAILABLE_CONSTANT" for row in core["fund_diagnostics"] if row["current_status"] == "AVAILABLE")
    assert all(len(case["case_geographies"]) >= 2 for case in case_bundle["manager_cases"].values())
    assert all(0 < case["case_geography_hhi"] < 1 for case in case_bundle["manager_cases"].values())


def test_v2_32_model_preview_is_no_network_and_live_requires_explicit_authorization(case_bundle, core):
    manager = case_bundle["manager_cases"]["MANAGER_SYNTH_00176"]
    diagnostic = next(row for row in core["manager_diagnostics"] if row["manager_id"] == manager["manager_id"] and row["strategy"] == manager["strategy"])
    openrouter = v2_diligence.model_preview(manager, diagnostic, "openrouter")
    anthropic = v2_diligence.model_preview(manager, diagnostic, "anthropic")
    assert openrouter["model"] == "google/gemini-3.8-flash"
    assert anthropic["model"] == "claude-sonnet-5"
    assert openrouter["network"] is False and anthropic["network"] is False
    assert openrouter["live_status"] == anthropic["live_status"] == "NOT_RUN"
    assert "expected-facts" not in json.dumps(openrouter["packet"], sort_keys=True)
    with pytest.raises(v2_diligence.DiligenceError, match="LIVE_MODEL_REQUIRES_EXPLICIT_AUTHORIZATION"):
        v2_diligence.generate_model_brief(manager, diagnostic, live=True, authorized=False)


def test_v2_33_active_release_contains_cases_but_no_model_call():
    receipt = v2_inputs.read_json(GP_ROOT / "06-report/receipt.json")
    checks = v2_inputs.read_csv(GP_ROOT / "06-report/checks.csv")
    assert receipt["include_cases"] is True
    assert receipt["model_calls"] == "NOT_RUN"
    assert receipt["checks"] == {"passed": 27, "failed": 0}
    assert len(checks) == 27 and all(row["status"] == "PASS" for row in checks)
    previews = v2_inputs.read_json(GP_ROOT / "06-report/model-previews.json")
    assert len(previews) == 6
    assert all(row["network"] is False and row["live_status"] == "NOT_RUN" for row in previews.values())


def test_case_cash_and_debt_reconcile_by_date(case_context, case_bundle):
    for case in case_bundle["manager_cases"].values():
        events = [row for row in case_context["overlay"]["case-events.csv"] if row["case_id"] == case["case_id"]]
        daily = {}
        for row in events:
            def amount(key):
                return float(row.get(key) or 0)
            day = daily.setdefault(row["event_date"], [0.0, 0.0])
            if row["event_type"] == "lp_capital_call":
                day[0] += amount("invested_cost") + amount("fee") + amount("facility_interest")
                day[0] -= amount("fee")
            elif row["event_type"] == "investment":
                day[0] -= amount("invested_cost")
            else:
                day[0] += amount("facility_draw") + amount("proceeds") - amount("distribution") - amount("facility_repayment") - amount("facility_interest") - amount("carry")
                day[1] += amount("facility_draw") - amount("facility_repayment")
        cash = debt = 0
        for moment, values in sorted(daily.items()):
            cash += values[0]
            debt += values[1]
            assert cash >= -1e-6, moment
            assert debt >= -1e-6, moment
        assert cash == pytest.approx(0, abs=1e-6)
        assert debt == pytest.approx(0, abs=1e-6)
        scenario = case["case_scenario"]
        if scenario["facility_status"] == "AVAILABLE":
            actual = dict(scenario["investor_flows"])
            alternative = dict(scenario["investor_flows_without_facility"])
            draw = next(row for row in events if row["event_type"] == "facility_draw")
            repay = next(row for row in events if row["event_type"] == "facility_repayment")
            assert alternative[draw["event_date"]] - actual[draw["event_date"]] == pytest.approx(-float(draw["facility_draw"]))
            assert alternative.get(repay["event_date"], 0) - actual[repay["event_date"]] == pytest.approx(float(repay["facility_repayment"]) + float(repay["facility_interest"]))
            assert scenario["nav_age_days"] == 71
        assert scenario["timing_basis"] == "RETROSPECTIVE_HYPOTHETICAL"
        flows = scenario["delayed_investor_flows"]
        assert scenario["distribution_delay_tvpi"] == pytest.approx(sum(v for _, v in flows if v > 0) / -sum(v for _, v in flows if v < 0))


@pytest.mark.parametrize("field,value", [("manager_id", "WRONG"), ("fund_id", "WRONG"), ("review_status", "REJECTED"), ("locator", "#missing"), ("field_name", "unlisted"), ("unit", "USD"), ("document_family", "valuation_memo"), ("effective_date", "2030-01-01"), ("available_at", "2030-01-01"), ("value_text", "unsupported statement")])
def test_case_fact_refusal(case_context, core, field, value):
    overlay = dict(case_context["overlay"])
    facts = [dict(row) for row in overlay["diligence-facts.csv"]]
    facts[0][field] = value
    overlay["diligence-facts.csv"] = facts
    with pytest.raises(v2_diligence.DiligenceError):
        v2_diligence.build_case_bundle({**case_context, "overlay": overlay}, core)


def _small_return_context():
    opening = {"fund_id": "F", "fund_period_id": "O", "as_of_date": "2025-06-30", "report_date": "2025-08-15", "currency": "USD", "nav": "100", "quality_approved": True}
    closing = {**opening, "fund_period_id": "C", "as_of_date": "2026-06-30", "report_date": "2026-08-15", "nav": "110"}
    return {"policy": {"economic_as_of": "2026-06-30", "returns": {"trailing_years": [1]}}, "periods_by_fund": {"F": [opening, closing]}, "current_by_fund": {"F": closing}, "flows_by_fund": {}, "available_period": lambda row: v2_inputs._available_period(row, date(2026, 9, 9))}


@pytest.mark.parametrize("target,key,value,reason", [(1,"report_date","2027-01-01","CLOSING_REPORT_UNAVAILABLE_AT_CUTOFF"), (0,"currency","EUR","OPENING_CURRENCY_MISMATCH"), (0,"quality_approved",False,"OPENING_QUALITY_UNAVAILABLE"), (1,"quality_approved",False,"CLOSING_QUALITY_UNAVAILABLE"), (1,"input_reasons",["invalid"],"CLOSING_INPUT_CHECK_FAILED")])
def test_trailing_return_admission(target, key, value, reason):
    context = _small_return_context()
    assert v2_features.trailing_returns(context)["F"][1]["value"] == pytest.approx(0.1)
    context["periods_by_fund"]["F"][target][key] = value
    assert v2_features.trailing_returns(context)["F"][1]["status"] == reason


def test_duplicate_opening_date_is_a_conflict():
    context = _small_return_context()
    context["periods_by_fund"]["F"].append(dict(context["periods_by_fund"]["F"][0], fund_period_id="OTHER"))
    assert v2_features.trailing_returns(context)["F"][1]["status"] == "OPENING_PERIOD_CONFLICT"


def test_effective_term_intervals_and_linked_overrides():
    base = {"fund_id": "F", "fund_term_id": "T", "record_status": "ACTIVE", "perspective": "fund_total", "term_scope": "base_fund", "effective_date": "2020-01-01", "effective_end_date": "", "management_fee_rate": ".02", "carry_rate": ".2"}
    context = {"policy": {"economic_as_of": "2026-06-30"}, "terms": [base]}
    assert v2_features.resolve_terms(context, "F")["status"] == "AVAILABLE"
    for updates in ({"effective_date": "2030-01-01"}, {"effective_end_date": "2025-12-31"}):
        assert v2_features.resolve_terms({**context, "terms": [{**base, **updates}]}, "F")["status"] == "BASE_TERM_CONFLICT_OR_MISSING"
    expired = {**base, "fund_term_id": "OLD", "effective_end_date": "2025-12-31"}
    override = {**base, "fund_term_id": "OV", "lp_id": "LP", "term_scope": "lp_override", "overrides_fund_term_id": "WRONG", "management_fee_rate": ".01", "carry_rate": ""}
    context["terms"] += [expired, override]
    assert v2_features.resolve_terms(context, "F", lp_id="LP")["management_fee_rate"] == ".02"
    override["overrides_fund_term_id"] = "T"
    result = v2_features.resolve_terms(context, "F", lp_id="LP")
    assert result["management_fee_rate"] == ".01" and result["carry_rate"] == ".2"
    assert result["fund_term_id"] == "T" and result["applied_override_id"] == "OV"


def test_readiness_uses_field_counts():
    from v2_dashboard import _readiness_summary

    rows = [{"entity_level": "fund", "entity_id": "F", "supported_fields": 4, "required_fields": 5, "coverage": .8}, {"entity_level": "manager_strategy", "entity_id": "M|S", "supported_fields": 1, "required_fields": 1, "coverage": 1}]
    assert _readiness_summary(rows, "M", "S", ["F"]) == pytest.approx(5/6)


def test_comparison_policy_changes_membership(context):
    context = {**context, "policy": copy.deepcopy(context["policy"]), "fund_by_id": copy.deepcopy(context["fund_by_id"])}
    context["policy"]["cohorts"]["size_band_count"] = 1
    context["policy"]["cohorts"]["match_sub_strategy"] = False
    first, _ = v2_features.cohort_data(context)
    context["policy"]["cohorts"]["size_band_count"] = 5
    five, _ = v2_features.cohort_data(context)
    assert len(five) < len(first)
    context["policy"]["cohorts"]["match_sub_strategy"] = True
    for i, fund in enumerate(context["fund_by_id"].values()):
        fund["sub_strategy"] = str(i % 2)
    matched, _ = v2_features.cohort_data(context)
    assert len(matched) < len(five)


def test_v2_competition_ranks_and_saved_reference(context):
    rows = [{"strategy": "S", "manager_id": str(i), "score": v} for i,v in enumerate([90,90,80])]
    v2_stress._rank(rows, "score", "rank")
    assert [row["rank"] for row in rows] == [1,1,3]
    for row in context["v1"]["scorecards"]:
        assert row["rank"] == row["v1_reference_rank"]


def test_diagnostic_and_scenario_references_resolve(core, scenarios, case_bundle):
    by_id = {row["feature_id"]: row for row in core["evidence"] + scenarios["evidence"]}
    case_ids = {row["evidence_id"] for row in case_bundle["evidence"]}
    for row in core["manager_diagnostics"]:
        assert f"MANAGER:{row['manager_id']}:{row['strategy']}:V2" in by_id
    for row in by_id.values():
        if row.get("feature") in {"manager_diagnostics", "scenario"}:
            assert set(row["input_ids"]).issubset(by_id)
    for brief in run_v2._template_briefs(core, scenarios, case_bundle):
        assert set(brief["evidence_ids"]).issubset(set(by_id) | case_ids)
    for row in case_bundle["evidence"]:
        assert set(row.get("input_ids", [])).issubset(case_ids)


def test_dashboard_includes_all_groups_and_source_files(core, scenarios):
    from v2_dashboard import build_packets

    packets = build_packets(core, scenarios)
    assert len(packets) == len(core["manager_diagnostics"]) == 640
    assert {row["status"] for row in packets} == {"RANKED_DEMO", "PARTIAL_TRACK_RECORD", "INSUFFICIENT_DATA"}
    html = render_dashboard({}, core, scenarios)
    for text in ("Trailing returns", "Same-age comparisons", "Information cutoff", "../04-diagnostics/evidence.json", "../05-scenarios/manager-scenarios.csv"):
        assert text in html


def test_relative_fingerprints_use_selected_checkout(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    _, fingerprints = v2_inputs._fingerprint_entries([path], tmp_path)
    assert list(fingerprints) == ["data.csv"]
    assert v2_inputs.verify_fingerprints(fingerprints, tmp_path) == []
    other = tmp_path / "copy"
    other.mkdir()
    (other / "data.csv").write_text("a\n2\n", encoding="utf-8")
    assert v2_inputs.verify_fingerprints(fingerprints, other)


def test_empty_receipts_fail(tmp_path, monkeypatch):
    for stage in ("04-diagnostics", "06-report"):
        (tmp_path / stage).mkdir()
    (tmp_path / "04-diagnostics/manifest.json").write_text('{"v2_data_id":"X"}', encoding="utf-8")
    (tmp_path / "06-report/receipt.json").write_text('{"status":"PASS","v2_data_id":"X","output_hashes":{}}', encoding="utf-8")
    assert "required output inventory incomplete" in run_v2._bundle_errors(tmp_path)
    assert v2_inputs.verify_baseline(PARENT, GP_ROOT) == []


def test_invalid_active_bundle_keeps_successful_archive(tmp_path, monkeypatch):
    import shutil
    import zipfile

    for stage in run_v2.STAGES:
        shutil.copytree(GP_ROOT / stage, tmp_path / stage)
    monkeypatch.setattr(run_v2, "HERE", tmp_path)
    assert run_v2._bundle_errors(tmp_path) == []
    run_v2._archive_active()
    archive = tmp_path / "v2-archive/previous.zip"
    saved = archive.read_bytes()
    receipt_path = tmp_path / "06-report/receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["status"] = "INVALID_REPLACEMENT_IN_PROGRESS"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    (tmp_path / "04-diagnostics/fund-diagnostics.csv").write_text("PARTIAL", encoding="utf-8")
    run_v2._archive_active()
    assert archive.read_bytes() == saved
    with zipfile.ZipFile(archive) as handle:
        assert json.loads(handle.read("06-report/receipt.json"))["status"] == "PASS"


def test_optional_return_absence_stays_local(context, core, scenarios):
    changed = {**core, "fund_diagnostics": [dict(row) for row in core["fund_diagnostics"]]}
    row = next(row for row in changed["fund_diagnostics"] if row["current_status"] == "AVAILABLE")
    row.update(xirr=None, xirr_status="RETURN_UNAVAILABLE", company_hhi=None, holdings_status="HOLDINGS_UNAVAILABLE")
    checks = run_v2._checks(PARENT, context, changed, scenarios, {"fingerprints": context["fingerprints"]})
    assert all(row["status"] == "PASS" for row in checks)


def test_model_budget_fallback_and_cache(case_bundle, core, monkeypatch, tmp_path):
    manager = next(iter(case_bundle["manager_cases"].values()))
    diagnostic = next(row for row in core["manager_diagnostics"] if row["manager_id"] == manager["manager_id"] and row["strategy"] == manager["strategy"])
    policy = json.loads((GP_ROOT / "policy.json").read_text())
    policy_path = tmp_path / "policy.json"
    policy["llm"]["max_run_cost_usd"] = 0
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(v2_diligence, "HERE", tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    calls = []

    def fail(*args):
        calls.append(1)
        raise TimeoutError("test timeout")

    monkeypatch.setattr(v2_diligence, "_model_request", fail)
    with pytest.raises(v2_diligence.DiligenceError, match="BUDGET"):
        v2_diligence.generate_model_brief(manager, diagnostic, live=True, authorized=True)
    assert calls == []
    policy["llm"]["max_run_cost_usd"] = .2
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    result = v2_diligence.generate_model_brief(manager, diagnostic, live=True, authorized=True)
    assert result["review_status"] == "TEMPLATE_FALLBACK" and len(calls) == 1
    response = {"summary": "Reviewed case facts.", "summary_evidence_ids": [manager["evidence_ids"][0]], "strengths": [], "risks": [], "questions": []}
    monkeypatch.setattr(v2_diligence, "_model_request", lambda *args: (response, {"input_tokens": 10, "output_tokens": 10}, "test-model"))
    cache = tmp_path / "responses.json"
    assert v2_diligence.generate_model_brief(manager, diagnostic, live=True, authorized=True, cache_path=cache)["mode"] == "live"
    monkeypatch.setattr(v2_diligence, "_model_request", fail)
    assert v2_diligence.generate_model_brief(manager, diagnostic, live=True, authorized=True, cache_path=cache)["mode"] == "cache"
    assert len(calls) == 1


def test_truncated_provider_response_is_refused(monkeypatch):
    import requests
    from types import SimpleNamespace

    fake = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]})
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: fake)
    with pytest.raises(v2_diligence.DiligenceError, match="INCOMPLETE"):
        v2_diligence._model_request("openrouter", "test-only", {"endpoint": "https://example.invalid", "model": "test"}, "prompt", {}, {}, 10)


def test_cases_belong_to_their_own_strategy(core, scenarios, case_bundle):
    from v2_dashboard import build_packets

    packets = build_packets(core, scenarios, case_bundle)
    with_cases = [row for row in packets if row["case"]]
    assert len(with_cases) == 3
    assert all(row["strategy"] == row["case"]["strategy"] for row in with_cases)


def test_zero_scenario_score_is_not_replaced(core, scenarios):
    modified = copy.deepcopy(scenarios)
    for row in modified["manager_scenarios"]:
        if row["scenario_id"] == "nav_20":
            row["scenario_score"] = 0
    assert all("NAV -20% score 0.0." in row["summary"] for row in run_v2._template_briefs(core, modified))


def test_interrupted_publication_retries_from_complete_candidate(tmp_path, monkeypatch):
    import shutil

    for stage in run_v2.STAGES:
        shutil.copytree(GP_ROOT / stage, tmp_path / stage)
    monkeypatch.setattr(run_v2, "HERE", tmp_path)
    candidate = tmp_path / ".v2-candidate"

    def prepare():
        shutil.rmtree(candidate, ignore_errors=True)
        for stage in run_v2.STAGES:
            shutil.copytree(GP_ROOT / stage, candidate / stage)
        receipt = candidate / "pending-receipt.json"
        (candidate / "06-report/receipt.json").replace(receipt)
        return receipt

    original_move = shutil.move
    calls = []

    def interrupted_move(source, target):
        calls.append(source)
        if len(calls) == 2:
            raise OSError("simulated interrupted replacement")
        return original_move(source, target)

    receipt = prepare()
    monkeypatch.setattr(shutil, "move", interrupted_move)
    with pytest.raises(OSError, match="interrupted"):
        run_v2._publish(candidate, receipt)
    assert run_v2._bundle_errors(tmp_path)
    archive = (tmp_path / "v2-archive/previous.zip").read_bytes()
    monkeypatch.setattr(shutil, "move", original_move)
    run_v2._publish(candidate, prepare())
    assert run_v2._bundle_errors(tmp_path) == []
    assert (tmp_path / "v2-archive/previous.zip").read_bytes() == archive


def test_v2_refuses_failed_empty_and_changed_v1_references(tmp_path):
    import shutil

    for stage in ("01-inputs", "02-scoring", "03-report"):
        shutil.copytree(GP_ROOT / stage, tmp_path / stage)
    receipt_path = tmp_path / "03-report/receipt.json"
    original = json.loads(receipt_path.read_text())
    assert v2_inputs._v1_reference(tmp_path)["receipt"]["status"] == "PASS"
    for path in tmp_path.rglob("*"):
        if path.is_file():
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    assert v2_inputs._v1_reference(tmp_path)["receipt"]["status"] == "PASS"
    for receipt, reason in (({**original, "status": "FAIL"}, "not PASS"), ({**original, "output_hashes": {}}, "inventory incomplete")):
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with pytest.raises(v2_inputs.V2InputError, match=reason):
            v2_inputs._v1_reference(tmp_path)
    receipt_path.write_text(json.dumps(original), encoding="utf-8")
    (tmp_path / "02-scoring/fund-features.csv").write_text("changed", encoding="utf-8")
    with pytest.raises(v2_inputs.V2InputError, match="output differs"):
        v2_inputs._v1_reference(tmp_path)


def test_v2_writers_use_git_line_endings(tmp_path):
    for writer in (run_v2._write_json, v2_diligence._write_cache):
        path = tmp_path / "output.json"
        writer(path, {"sample": [1, 2]})
        assert b"\r\n" not in path.read_bytes()


@pytest.mark.parametrize("paid,cash,nav,gap,cut", [(100,20,100,80,.2), (100,20,40,80,-1), (100,120,50,0,1), (100,100,0,0,None)])
def test_capital_recovery_examples(paid, cash, nav, gap, cut):
    from v2_analysis import capital_recovery
    row = capital_recovery(paid, cash, nav)
    assert row["capital_still_to_return"] == gap
    if cut is None:
        assert row["nav_haircut_to_capital"] is None
    else:
        assert row["nav_haircut_to_capital"] == pytest.approx(cut)
        assert cash + nav * (1-cut) >= paid


@pytest.mark.parametrize("paid,cash,nav", [(0,0,1), (100,-1,1), (100,1,-1), (float('nan'),1,1), (100,1,float('inf'))])
def test_capital_recovery_refuses_invalid_values(paid, cash, nav):
    from v2_analysis import capital_recovery
    with pytest.raises(ValueError):
        capital_recovery(paid, cash, nav)


def test_benchmark_wealth_hand_calculation():
    from src.analytics.run_round04_analytics import _BenchmarkPoint, _BenchmarkSeries
    from v2_analysis import benchmark_wealth
    series = _BenchmarkSeries([_BenchmarkPoint(date(2010,1,1),100,'B0'), _BenchmarkPoint(date(2011,1,1),110,'B1')])
    period = {"as_of_date":"2011-01-01", "currency":"USD", "nav":"90"}
    flows = [{"cashflow_id":"C", "cashflow_date":"2010-01-01", "base_currency":"USD", "amount_base_currency":"-100"},
             {"cashflow_id":"D", "cashflow_date":"2011-01-01", "base_currency":"USD", "amount_base_currency":"20"}]
    result = benchmark_wealth(period, flows, series)
    assert result["benchmark_capital"] == pytest.approx(110)
    assert result["benchmark_excess_value"] == pytest.approx(0)
    assert result["benchmark_recomputed_pme"] == pytest.approx(1)
    assert result["nav_haircut_to_match_benchmark"] == pytest.approx(0)
    assert benchmark_wealth(period, list(reversed(flows)), series)["benchmark_excess_value"] == result["benchmark_excess_value"]
    flows[0]["base_currency"] = "EUR"
    with pytest.raises(ValueError, match="currency"):
        benchmark_wealth(period, flows, series)


def _operating_example():
    return {"valuation_id":"V", "portfolio_company_id":"C", "revenue":100, "ebitda_margin":.2,
            "ev_ebitda_multiple":10, "net_debt":50, "ownership_pct":.5, "fx_to_usd":1,
            "fair_value":75, "evidence_id":"E"}


def test_operating_downside_hand_calculation_and_zero(policy):
    from v2_analysis import operating_downside
    analysis = policy["investment_analysis"]
    result = operating_downside(_operating_example(), analysis)
    assert result["revenue_effect"] == pytest.approx(-10)
    assert result["margin_effect"] == pytest.approx(-9)
    assert result["multiple_effect"] == pytest.approx(-8.1)
    assert result["scenario_value"] == pytest.approx(47.9)
    zero = copy.deepcopy(analysis)
    zero["operating_downside"].update(revenue_change=0, margin_change=0, multiple_change=0)
    assert operating_downside(_operating_example(), zero)["scenario_value"] == 75
    row = {**_operating_example(), "net_debt":190, "fair_value":5}
    assert operating_downside(row, analysis)["scenario_value"] == 0


@pytest.mark.parametrize("field,value", [("fair_value",76), ("ownership_pct",1.1), ("fx_to_usd",0), ("revenue",float('nan'))])
def test_operating_inputs_must_match_value(policy, field, value):
    from v2_analysis import operating_downside
    row = {**_operating_example(), field:value}
    with pytest.raises(ValueError):
        operating_downside(row, policy["investment_analysis"])


def test_age_duplicate_reports_are_withheld(monkeypatch):
    fund = {"fund_id":"F", "fund_manager_id":"M", "base_currency":"USD", "vintage_year":"2010", "strategy":"buyout", "sub_strategy":"mid_market"}
    row = {"fund_period_id":"P1", "as_of_date":"2011-01-01", "currency":"USD", "tvpi":"1", "dpi":"0"}
    ctx = {"policy":{"economic_as_of":"2012-01-01", "returns":{"age_years":[1],"age_max_lag_days":100},
                     "cohorts":{"vintage_bucket_years":5,"reference_min_funds":10,"reference_min_managers":5,"match_sub_strategy":True}},
           "fund_master":[fund], "flows_by_fund":{"F":[{"cashflow_date":"2010-01-01","cashflow_type":"capital_call","amount_base_currency":"-100"}]},
           "periods_by_fund":{"F":[row,dict(row,fund_period_id="P2")]}, "available_period":lambda r:True}
    monkeypatch.setattr(v2_features,"quality_approval_for_ids",lambda *args:{"P1":(True,"")})
    assert v2_features.age_snapshots(ctx)["F"][1]["status"] == "AGE_PERIOD_CONFLICT"


def test_cash_conversion_currency_failure_stays_empty():
    ctx = _small_return_context()
    ctx["policy"]["returns"]["material_distribution_paid_in_fraction"] = .01
    ctx["current_by_fund"]["F"]["paid_in_capital_itd"] = "100"
    ctx["flows_by_fund"] = {"F":[{"cashflow_id":"X","cashflow_date":"2026-06-01","cashflow_type":"distribution","base_currency":"EUR","amount_base_currency":"20"}]}
    result = v2_features.cash_conversion(ctx, {})["F"]
    assert result == {"status":"CASHFLOW_CURRENCY_OR_VALUE_INVALID"}


def test_holdings_currency_refused_before_concentration():
    ctx = _small_return_context()
    ctx["holdings_by_fund"] = {"F":[{"holding_id":"H","fair_value":"110","currency":"EUR"}]}
    result = v2_features.holdings_features(ctx)["F"]
    assert result["status"] == "HOLDING_VALUE_INVALID"
    assert "company_hhi" not in result


def test_stress_uses_reconciled_holdings_only(context, core):
    fund = next(row for row in core["fund_diagnostics"] if row.get("v1_fund_score") is not None)
    changed = {**core,"fund_diagnostics":[{**row,"holdings_status":"FAILED"} if row["fund_id"]==fund["fund_id"] else row for row in core["fund_diagnostics"]]}
    result = v2_stress.build_scenarios(context, changed)
    assert not [row for row in result["fund_scenarios"] if row["fund_id"]==fund["fund_id"] and row["scenario_type"]=="portfolio_haircut"]


@pytest.mark.parametrize("target,field,value", [("case-events.csv","event_date","2027-01-01"), ("case-events.csv","currency","EUR"),
                                                ("case-valuations.csv","valuation_date","2027-01-01"), ("deal-attribution.csv","attribution_weight","0.5")])
def test_case_dates_currencies_and_attribution_refused(case_context, target, field, value):
    ctx = {**case_context,"overlay":copy.deepcopy(case_context["overlay"])}
    ctx["overlay"][target][0][field] = value
    with pytest.raises(v2_diligence.DiligenceError):
        v2_diligence._validate_dates(ctx)


def test_case_model_packet_keeps_manager_strategy(case_bundle, core):
    case = next(iter(case_bundle["manager_cases"].values()))
    wrong = next(row for row in core["manager_diagnostics"] if row["manager_id"] != case["manager_id"])
    with pytest.raises(v2_diligence.DiligenceError, match="manager-strategy"):
        v2_diligence.model_packet(case, wrong)


def test_investment_analytics_reconcile_current_output(context, core, case_bundle):
    import math
    for row in core["fund_diagnostics"]:
        if row["current_status"] != "AVAILABLE":
            continue
        assert row["capital_still_to_return"] == pytest.approx(max(row["paid_in"] - row["distributions"],0))
        if row.get("benchmark_capital") is not None:
            assert row["benchmark_excess_value"] == pytest.approx((row["ks_pme"] - 1) * row["benchmark_capital"], abs=1e-5)
        if row["direct_alpha"] is not None:
            assert math.expm1(row["direct_alpha_continuous"]) == pytest.approx(row["direct_alpha"])
    for row in core["manager_diagnostics"]:
        if row["historical_score"] is not None:
            assert row["score_tvpi_points"] + row["score_dpi_points"] == pytest.approx(row["historical_score"])
            assert sum(r["tvpi_points"]+r["dpi_points"] for r in row["score_contributions"]) == pytest.approx(row["historical_score"])
    for case in case_bundle["manager_cases"].values():
        analysis = case["investment_analysis"]
        assert analysis["operating_case_tvpi"] <= case["case_tvpi"]
        for r in analysis["operating_results"]:
            assert r["baseline_value"] + r["rounding_adjustment"] + r["revenue_effect"] + r["margin_effect"] + r["multiple_effect"] == pytest.approx(r["scenario_value"])
        assert sum(r["gain"] for r in analysis["deals"]) == pytest.approx(sum(r["proceeds"]+r["remaining_value"]-r["cost"] for r in analysis["deals"]))


def test_published_checks_refuse_analytics_tampering(context, core, scenarios):
    changed = {**core, "fund_diagnostics":copy.deepcopy(core["fund_diagnostics"])}
    next(r for r in changed["fund_diagnostics"] if r["current_status"]=="AVAILABLE")["capital_still_to_return"] += 1
    checks = run_v2._checks(PARENT,context,changed,scenarios,{"fingerprints":context["fingerprints"]})
    assert next(r for r in checks if r["check_id"]=="V2C25_CAPITAL_AND_BENCHMARK")["status"] == "FAIL"


def test_manager_trend_refuses_mixed_series():
    funds = [{"fund_id":"F1","fund_manager_id":"M","strategy":"buyout","sub_strategy":"a","vintage_year":"2020"},
             {"fund_id":"F2","fund_manager_id":"M","strategy":"buyout","sub_strategy":"b","vintage_year":"2010"}]
    ctx = {"fund_master":funds,"v1":{"features":[{"fund_id":"F1","fund_score":"20"},{"fund_id":"F2","fund_score":"80"}],
                                   "scorecards":[{"manager_id":"M","strategy":"buyout","status":"RANKED_DEMO","score":"50"}]}}
    ordering = {r["fund_id"]:{"order_status":"ORDERED","display_order":1} for r in funds}
    first = v2_features.consistency_features(ctx,ordering)[0]
    ctx["fund_master"] = list(reversed(funds))
    assert v2_features.consistency_features(ctx,ordering)[0] == first
    assert first["two_point_change"] is None and first["score_trend_per_fund"] is None
    assert first["trend_status"] == "SERIES_ORDER_OR_DEPTH_UNSUPPORTED"


def test_case_duplicate_event_refused(case_context):
    ctx = {**case_context,"overlay":copy.deepcopy(case_context["overlay"])}
    ctx["overlay"]["case-events.csv"].append(dict(ctx["overlay"]["case-events.csv"][0]))
    with pytest.raises(v2_diligence.DiligenceError, match="identifiers"):
        v2_diligence._validate_dates(ctx)


def test_fixture_holding_availability_assumption_is_explicit(policy):
    ctx = _small_return_context()
    ctx["policy"]["investment_analysis"] = policy["investment_analysis"]
    row = {"holding_id":"H","fair_value":"110","currency":"USD","as_of_date":"2026-06-30","provenance_type":"SYNTHETIC"}
    ctx["holdings_by_fund"] = {"F":[row]}
    result = v2_features.holdings_features(ctx)["F"]
    assert result["report_date_basis"] == "MATCHING_FIXTURE_FUND_REPORT"
    row["report_date"] = "2027-01-01"
    assert v2_features.holdings_features(ctx)["F"]["status"] == "HOLDING_VALUE_INVALID"


@pytest.mark.parametrize("target", ["capital", "score"])
def test_new_reconciliation_checks_refuse_nonfinite_values(context, core, scenarios, target):
    changed = copy.deepcopy(core)
    if target == "capital":
        next(r for r in changed["fund_diagnostics"] if r["current_status"] == "AVAILABLE")["capital_still_to_return"] = float("nan")
        check_id = "V2C25_CAPITAL_AND_BENCHMARK"
    else:
        next(r for r in changed["manager_diagnostics"] if r["v1_status"] == "RANKED_DEMO")["score_tvpi_points"] = float("inf")
        check_id = "V2C26_SCORE_CONTRIBUTIONS"
    checks = run_v2._checks(PARENT, context, changed, scenarios, {"fingerprints": context["fingerprints"]})
    assert next(r for r in checks if r["check_id"] == check_id)["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["duplicate_investment", "zero_cost", "negative_proceeds"])
def test_case_investment_grain_and_values(case_context, mutation):
    from v2_analysis import case_investments
    ctx = {**case_context, "overlay": copy.deepcopy(case_context["overlay"])}
    events = ctx["overlay"]["case-events.csv"]
    investment = next(r for r in events if r["event_type"] == "investment")
    if mutation == "duplicate_investment":
        events.append({**investment, "event_id": "NEW_ID"})
    elif mutation == "zero_cost":
        investment["invested_cost"] = "0"
    else:
        next(r for r in events if r["case_id"] == investment["case_id"] and r.get("proceeds"))["proceeds"] = "-1"
    with pytest.raises(ValueError):
        case_investments(ctx, investment["case_id"])
