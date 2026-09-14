from __future__ import annotations
import ast
import copy
import sys
from datetime import date, timedelta
from pathlib import Path
import pytest
HERE = Path(__file__).resolve().parents[1]
PARENT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import briefing
import finance
import inputs
import market
import pricing
import qc
import report
import run
import simulate
from utils import DataError, number, read_json

@pytest.fixture(scope='module')
def policy():
    return read_json(HERE / 'policy.json')

@pytest.fixture(scope='module')
def integrated(policy):
    context = inputs.build_context(PARENT, 'integrated_demo', policy)
    positions = simulate.generate_positions(context, policy)
    events = simulate.generate_interim_events(positions, policy)
    results, cashflows, steps, sensitivities, exceptions = pricing.price_positions(positions, events, policy)
    portfolios = pricing.portfolio_results(results, cashflows, policy)
    return (context, positions, events, results, cashflows, steps, sensitivities, exceptions, portfolios)

def test_xnpv_golden_one_year():
    start = date(2026, 1, 1)
    assert finance.xnpv(0.1, [(start, 0.0), (start + timedelta(days=365), 110.0)]) == pytest.approx(100.0, abs=1e-10)

def test_xirr_golden_one_year():
    start = date(2026, 1, 1)
    rate = finance.xirr([(start, -100.0), (start + timedelta(days=365), 110.0)])
    assert rate == pytest.approx(0.1, abs=1e-08)
    assert finance.xnpv(rate, [(start, -100.0), (start + timedelta(days=365), 110.0)]) == pytest.approx(0.0, abs=1e-08)

def test_nonconventional_sign_changes_are_detected():
    start = date(2026, 1, 1)
    flows = [(start, -100.0), (start + timedelta(days=100), 150.0), (start + timedelta(days=200), -20.0)]
    assert finance.sign_changes(flows) == 2
    value, status = pricing._safe_xirr(flows)
    assert value is None
    assert status == 'NONCONVENTIONAL_MULTIPLE_SIGN_CHANGES'

def test_settlement_golden_and_recall():
    position = {'position_id': 'P', 'reference_date': '2026-01-01', 'quote_date': '2026-06-30', 'closing_date': '2026-12-31', 'reference_nav': '100', 'reference_unfunded': '20'}
    events = [{'event_id': 'C', 'event_date': '2026-03-01', 'settlement_eligible': 'TRUE', 'amount': '3', 'event_type': 'capital_call', 'actual_or_forecast': 'ACTUAL', 'capital_account_contribution': '3', 'fee_expense_amount': '0', 'commitment_reduction': '3', 'recallable_increase': '0'}, {'event_id': 'D', 'event_date': '2026-04-01', 'settlement_eligible': 'TRUE', 'amount': '5', 'event_type': 'distribution', 'actual_or_forecast': 'ACTUAL', 'capital_account_contribution': '0', 'fee_expense_amount': '0', 'commitment_reduction': '0', 'recallable_increase': '1'}]
    state = pricing.closing_state(position, events)
    assert number(state['settlement_adjustment']) == pytest.approx(-2.0)
    assert number(state['closing_unfunded']) == pytest.approx(18.0)
    assert number(state['closing_economic_nav']) == pytest.approx(98.0)

def test_fee_funded_call_changes_nav_once():
    position = {'position_id': 'P', 'reference_date': '2026-01-01', 'quote_date': '2026-06-30', 'closing_date': '2026-12-31', 'reference_nav': '100', 'reference_unfunded': '20'}
    event = {'event_id': 'C', 'event_date': '2026-03-01', 'settlement_eligible': 'TRUE', 'amount': '10', 'event_type': 'capital_call', 'actual_or_forecast': 'ACTUAL', 'capital_account_contribution': '10', 'fee_expense_amount': '2', 'commitment_reduction': '10', 'recallable_increase': '0'}
    state = pricing.closing_state(position, [event])
    assert number(state['settlement_adjustment']) == pytest.approx(10.0)
    assert number(state['closing_economic_nav']) == pytest.approx(108.0)
    assert number(state['closing_unfunded']) == pytest.approx(10.0)

def test_transaction_generation_is_deterministic(policy):
    context = inputs.build_context(PARENT, 'integrated_demo', policy)
    one = simulate.generate_positions(context, policy)
    two = simulate.generate_positions(context, policy)
    assert one == two
    assert len(one) == 7

def test_partial_sale_scales_once(integrated):
    _, positions, _, _, _, _, _, _, _ = integrated
    partial = next((row for row in positions if number(row['sale_fraction']) == pytest.approx(0.5)))
    source = next((row for row in integrated[0]['selected'] if row['fund_period_id'] == partial['fund_period_id']))
    expected = number(source['nav']) * number(partial['seller_fund_fraction']) * number(partial['sale_fraction'])
    assert number(partial['reference_nav']) == pytest.approx(expected, rel=1e-08)

def test_event_outside_transfer_interval_is_rejected(policy, integrated):
    _, positions, events, *_ = integrated
    damaged = copy.deepcopy(events)
    damaged[0]['event_date'] = positions[0]['reference_date']
    errors = simulate.validate_transaction_inputs(positions, damaged)
    assert any(('outside reference/close interval' in error for error in errors))

def test_integrated_quality_uses_coherent_latest_run(policy):
    context = inputs.build_context(PARENT, 'integrated_demo', policy)
    state = context['metadata']['quality_state']
    assert state['status'] == 'COMPLETE'
    assert state['run_id'] == 'INTEGRATED_QC_V1'
    assert len(context['selected']) == 7

def test_observed_mode_is_evidence_only(policy):
    context = inputs.build_context(PARENT, 'observed', policy)
    assert context['selected']
    assert context['metadata']['quality_state']['status'] == 'EVIDENCE_ONLY'
    assert simulate.generate_positions(context, policy) == []

def test_forecast_rollforward_and_terminal_zero(integrated):
    _, _, _, _, _, steps, _, _, _ = integrated
    for row in steps:
        expected = number(row['opening_nav']) + number(row['growth_amount']) + number(row['capitalized_call']) - number(row['distribution'])
        assert number(row['ending_nav']) == pytest.approx(expected, abs=max(1e-05, abs(expected) * 1e-08))
        assert number(row['ending_unfunded']) >= -1e-08
    final = [row for row in steps if row['quarter'] == '20']
    assert final and all((abs(number(row['ending_nav'])) < 1e-06 for row in final))

def test_future_calls_not_double_subtracted(integrated):
    _, _, _, results, _, _, _, _, _ = integrated
    for row in results:
        assert number(row['future_cashflow_pv_at_hurdle']) - number(row['buyer_transaction_cost']) == pytest.approx(number(row['max_closing_seller_payment']), abs=1e-05)

def test_price_ceiling_satisfies_hurdle_identity(integrated):
    _, _, _, results, _, _, _, _, _ = integrated
    for row in results:
        expected = number(row['future_cashflow_pv_at_hurdle']) - number(row['buyer_initial_outflow_at_ask'])
        assert number(row['ask_npv_at_hurdle']) == pytest.approx(expected, abs=max(1e-05, abs(expected) * 1e-08))

def test_higher_hurdle_lowers_ceiling(integrated):
    _, _, _, _, _, _, sensitivities, _, _ = integrated
    grouped = {}
    for row in sensitivities:
        grouped.setdefault((row['position_id'], row['scenario_id']), []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda x: number(x['hurdle_rate']))
        ceilings = [number(row['max_reference_price']) for row in rows]
        assert all((right <= left + 1e-07 for left, right in zip(ceilings, ceilings[1:])))

def test_price_is_not_capped_at_nav(policy):
    position = {'deal_id': 'D', 'position_id': 'P', 'population': 'fixture', 'display_name': 'P', 'fund_id': 'F', 'manager_id': 'M', 'source_record_ids': 'FP', 'currency': 'USD', 'reference_date': '2026-01-01', 'quote_date': '2026-01-02', 'closing_date': '2026-01-03', 'reference_nav': '100', 'reference_unfunded': '0', 'ask_nav_fraction': '1.0', 'ask_reference_price': '100', 'buyer_transaction_cost': '0', 'consent_status': 'APPROVED'}
    state = {'closing_economic_nav': 300.0, 'closing_unfunded': 0.0, 'settlement_adjustment': 0.0, 'actual_settlement_adjustment': 0.0, 'forecast_settlement_adjustment': 0.0}
    changed = copy.deepcopy(policy)
    changed['forecast']['scenarios'] = {'base': {'opening_nav_multiplier': 1.0, 'annual_growth': 0.0, 'distribution_delay_quarters': 0, 'distribution_fraction_multiplier': 1.0}}
    changed['forecast']['distribution_start_quarter'] = 1
    future, _ = pricing.forecast_position(position, state, changed)
    pv = finance.xnpv(changed['buyer']['hurdle_rate'], [(date.fromisoformat(position['closing_date']), 0.0), *[(date.fromisoformat(x['cashflow_date']), number(x['amount'])) for x in future]])
    assert pv / 100.0 > 1.0

def test_denied_consent_is_no_quote(integrated):
    _, positions, _, results, _, _, _, _, _ = integrated
    denied = next((p for p in positions if p['consent_status'] == 'DENIED'))
    rows = [r for r in results if r['position_id'] == denied['position_id']]
    assert rows and all((r['status'] == 'NO_QUOTE' for r in rows))

def test_portfolio_reconciles_without_averaging_irrs(integrated):
    _, _, _, results, _, _, _, _, portfolios = integrated
    base = next((row for row in portfolios if row['scenario_id'] == 'base'))
    ids = set(base['included_position_ids'].split('|'))
    members = [row for row in results if row['scenario_id'] == 'base' and row['position_id'] in ids]
    assert number(base['reference_nav']) == pytest.approx(sum((number(r['reference_nav']) for r in members)), abs=1e-05)
    constituent_irrs = [number(r['ask_irr']) for r in members if r.get('ask_irr')]
    assert number(base['ask_irr']) != pytest.approx(sum(constituent_irrs) / len(constituent_irrs), abs=1e-05)

def test_core_qc_passes(integrated, policy):
    _, positions, events, results, cashflows, steps, sensitivities, _, portfolios = integrated
    checks = qc.run_checks(positions, events, results, cashflows, steps, portfolios, sensitivities, policy, population='integrated_demo')
    assert not qc.failed(checks)

def test_brief_preview_never_calls_network(monkeypatch, integrated, policy):
    _, positions, _, results, *_ = integrated
    monkeypatch.setattr(briefing, '_openrouter', lambda *a, **k: (_ for _ in ()).throw(AssertionError('network called')))
    briefs, previews = briefing.generate_briefs(positions, results, policy, mode='preview', provider='openrouter')
    assert len(briefs) == len(positions)
    assert len(previews) == len(positions)
    assert all((row['review_status'] == 'NO_MODEL_CALL' for row in briefs))

def test_brief_rejects_unknown_evidence():
    bad = {'summary': 'x', 'summary_evidence_ids': ['BOGUS'], 'strengths': [], 'risks': [], 'questions': []}
    with pytest.raises(briefing.BriefingError):
        briefing.validate_response(bad, {'GOOD'})

def test_report_escapes_user_text(policy):
    metadata = {'population': 'fixture', 'policy_version': '1', 'input_fingerprints': []}
    pos = {'position_id': 'P', 'display_name': '<script>alert(1)</script>'}
    row = {'position_id': 'P', 'scenario_id': 'base', 'display_name': '<script>alert(1)</script>', 'status': 'DEMO_DECLINE', 'ask_nav_fraction': '0.9', 'max_nav_fraction': '0.8', 'ask_closing_seller_payment': '90', 'closing_unfunded': '0', 'ask_irr': '0.1', 'buyer_money_multiple': '1.2', 'status_reason': 'X', 'currency': 'USD', 'reference_date': '2026-01-01', 'quote_date': '2026-01-02', 'closing_date': '2026-01-03', 'actual_settlement_adjustment': '0', 'forecast_settlement_adjustment': '0', 'reference_nav': '100', 'closing_economic_nav': '100', 'future_calls': '0', 'future_distributions': '120'}
    html = report.render_dashboard(metadata, [pos], [row], [], [], [], [], {}, [], [])
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html

def test_market_simulation_is_deterministic_and_split(policy):
    a = market.generate_trades(PARENT, policy)
    b = market.generate_trades(PARENT, policy)
    assert a == b
    comparisons, evaluations, metadata = market.evaluate(a, policy)
    assert metadata['simulation_only'] is True
    assert metadata['train_count'] >= policy['market']['minimum_train_rows']
    temporal = {row['trade_id'] for row in comparisons if row['split'] == 'temporal_test'}
    holdout = {row['trade_id'] for row in comparisons if row['split'] == 'manager_holdout_test'}
    assert temporal.isdisjoint(holdout)
    assert evaluations and all((row['status'] == 'PASS' for row in evaluations))

def test_market_model_beats_declared_synthetic_baseline(policy):
    trades = market.generate_trades(PARENT, policy)
    _, evaluations, _ = market.evaluate(trades, policy)
    assert all((row['model_beats_baseline'] == 'TRUE' for row in evaluations if row['status'] == 'PASS'))

def test_runtime_modules_have_no_gp_scoring_import():
    for path in HERE.glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(('GP-Scoring' not in alias.name and 'gp_scoring' not in alias.name.lower() for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                assert 'GP-Scoring' not in (node.module or '') and 'gp_scoring' not in (node.module or '').lower()

def test_anthropic_preview_never_calls_network(monkeypatch, integrated, policy):
    _, positions, _, results, *_ = integrated
    monkeypatch.setattr(briefing, '_anthropic', lambda *a, **k: (_ for _ in ()).throw(AssertionError('network called')))
    briefs, previews = briefing.generate_briefs(positions, results, policy, mode='preview', provider='anthropic')
    assert len(briefs) == len(positions)
    assert len(previews) == len(positions)
    assert all((row['review_status'] == 'NO_MODEL_CALL' for row in briefs))

def test_failed_build_does_not_replace_active_receipt(monkeypatch, policy):
    receipt_path = HERE / '03-report' / 'receipt.json'
    if not receipt_path.is_file():
        pytest.skip('active release not built')
    before = receipt_path.read_bytes()
    monkeypatch.setattr(qc, 'run_checks', lambda *a, **k: [{'check_id': 'FORCED', 'status': 'FAIL', 'actual': '1', 'expected': '0', 'source': 'test', 'reason': 'forced'}])
    with pytest.raises(DataError):
        run.build(PARENT, 'integrated_demo', llm_mode='off', provider='openrouter', model='', authorize_live_model=False, run_market=False)
    assert receipt_path.read_bytes() == before
    assert not run.CANDIDATE.exists()
    if run.FAILURE.exists():
        run.FAILURE.unlink()

def test_active_receipt_verifies():
    if not (HERE / '03-report' / 'receipt.json').is_file():
        pytest.skip('active release not built')
    assert run.check_only(PARENT) == []
