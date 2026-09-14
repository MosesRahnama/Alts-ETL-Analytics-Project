"""Focused quality controls for One-Day Pricing inputs, arithmetic, and persisted outputs."""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Mapping, Sequence
from finance import xnpv
from pricing import closing_state
from simulate import validate_transaction_inputs
from utils import fmt, number, parse_date

def _check(rows: list[dict[str, str]], check_id: str, ok: bool, actual: object, expected: object, source: str, reason: str='') -> None:
    rows.append({'check_id': check_id, 'status': 'PASS' if ok else 'FAIL', 'actual': str(actual), 'expected': str(expected), 'source': source, 'reason': reason})

def run_checks(positions: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]], cashflows: Sequence[Mapping[str, Any]], steps: Sequence[Mapping[str, Any]], portfolios: Sequence[Mapping[str, Any]], sensitivities: Sequence[Mapping[str, Any]], policy: Mapping[str, Any], *, population: str) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    input_errors = validate_transaction_inputs(positions, events)
    _check(checks, 'T1_INPUT_CONTRACT', not input_errors, len(input_errors), 0, 'simulate.validate_transaction_inputs', '|'.join(input_errors))
    if population == 'observed':
        _check(checks, 'T1_OBSERVED_NO_PRICING', not positions and (not results), f'positions={len(positions)} results={len(results)}', '0 priced rows', 'run observed mode')
        return checks
    expected_results = len(positions) * len(policy['forecast']['scenarios'])
    _check(checks, 'T2_SCENARIO_COVERAGE', len(results) == expected_results, len(results), expected_results, 'pricing.price_positions')
    bad_scale = []
    for pos in positions:
        seller = number(pos['seller_fund_fraction'])
        sale = number(pos['sale_fraction'])
        transfer = number(pos['transferred_fraction_of_fund'])
        if abs(seller * sale - transfer) > 1e-09:
            bad_scale.append(pos['position_id'])
    _check(checks, 'T3_POSITION_SCALING', not bad_scale, len(bad_scale), 0, 'simulate.generate_positions', '|'.join(bad_scale))
    golden_position = {'position_id': 'GOLD', 'reference_date': '2026-01-01', 'quote_date': '2026-06-30', 'closing_date': '2026-12-31', 'reference_nav': '100', 'reference_unfunded': '20'}
    golden_events = [{'event_id': 'C', 'event_date': '2026-03-01', 'settlement_eligible': 'TRUE', 'amount': '3', 'event_type': 'capital_call', 'actual_or_forecast': 'ACTUAL', 'capital_account_contribution': '3', 'fee_expense_amount': '0', 'commitment_reduction': '3', 'recallable_increase': '0'}, {'event_id': 'D', 'event_date': '2026-04-01', 'settlement_eligible': 'TRUE', 'amount': '5', 'event_type': 'distribution', 'actual_or_forecast': 'ACTUAL', 'capital_account_contribution': '0', 'fee_expense_amount': '0', 'commitment_reduction': '0', 'recallable_increase': '0'}]
    state = closing_state(golden_position, golden_events)
    _check(checks, 'T4_SETTLEMENT_GOLDEN', abs(number(state['settlement_adjustment']) + 2.0) < 1e-12 and abs(number(state['closing_unfunded']) - 17.0) < 1e-12, f'adjustment={state['settlement_adjustment']};unfunded={state['closing_unfunded']}', '-2;17', 'independent hand example')
    bad_steps = []
    for row in steps:
        expected_nav = number(row['opening_nav']) + number(row['growth_amount']) + number(row['capitalized_call']) - number(row['distribution'])
        if abs(expected_nav - number(row['ending_nav'])) > max(1e-05, abs(expected_nav) * 1e-09) or number(row['ending_unfunded']) < -1e-07:
            bad_steps.append(f'{row['position_id']}:{row['scenario_id']}:{row['quarter']}')
    _check(checks, 'T5_T8_FORECAST_RECONCILIATION', not bad_steps, len(bad_steps), 0, 'pricing.forecast_position', '|'.join(bad_steps[:10]))
    time_errors = []
    pos_by_id = {row['position_id']: row for row in positions}
    for event in events:
        pos = pos_by_id[event['position_id']]
        q = parse_date(pos['quote_date'])
        e = parse_date(event['event_date'])
        a = parse_date(event['available_at'])
        status = event['actual_or_forecast']
        if status == 'ACTUAL' and (e > q or a > q):
            time_errors.append(event['event_id'])
        if e > q and status != 'FORECAST':
            time_errors.append(event['event_id'])
    _check(checks, 'T6_INFORMATION_CUTOFF', not time_errors, len(time_errors), 0, 'interim event dates', '|'.join(time_errors))
    close = date(2026, 1, 1)
    future = close + timedelta(days=365)
    pv = xnpv(0.1, [(close, 0.0), (future, 110.0)])
    _check(checks, 'T7_XNPV_GOLDEN', abs(pv - 100.0) < 1e-09, fmt(pv, 10), '100', 'finance.xnpv')
    _check(checks, 'T7_COST_GOLDEN', abs(pv - 1.0 - 99.0) < 1e-09, fmt(pv - 1.0, 10), '99', 'buyer ceiling identity')
    price_errors = []
    for row in results:
        future_pv = number(row['future_cashflow_pv_at_hurdle'])
        cost = number(row['buyer_transaction_cost'])
        close_max = number(row['max_closing_seller_payment'])
        if abs(future_pv - cost - close_max) > max(1e-05, abs(future_pv) * 1e-09):
            price_errors.append(row['result_id'] + ':ceiling')
        expected_npv = future_pv - number(row['buyer_initial_outflow_at_ask'])
        if abs(expected_npv - number(row['ask_npv_at_hurdle'])) > max(1e-05, abs(expected_npv) * 1e-09):
            price_errors.append(row['result_id'] + ':npv')
    _check(checks, 'T7_T9_PRICE_IDENTITIES', not price_errors, len(price_errors), 0, 'pricing.price_positions', '|'.join(price_errors[:10]))
    by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in sensitivities:
        by_key[row['position_id'], row['scenario_id']].append(row)
    sensitivity_errors = []
    for key, rows in by_key.items():
        ordered = sorted(rows, key=lambda x: number(x['hurdle_rate']))
        values = [number(x['max_reference_price']) for x in ordered]
        if any((b > a + 1e-07 for a, b in zip(values, values[1:]))):
            sensitivity_errors.append(':'.join(key))
    _check(checks, 'T7_HURDLE_MONOTONICITY', not sensitivity_errors, len(sensitivity_errors), 0, '02-pricing/sensitivities.csv', '|'.join(sensitivity_errors))
    result_map = {(row['position_id'], row['scenario_id']): row for row in results}
    portfolio_errors = []
    for port in portfolios:
        ids = [x for x in str(port['included_position_ids']).split('|') if x]
        members = [result_map[pid, port['scenario_id']] for pid in ids]
        nav = sum((number(x['reference_nav']) for x in members))
        ask = sum((number(x['ask_reference_price']) for x in members))
        ceiling = sum((number(x['max_reference_price']) for x in members))
        if abs(nav - number(port['reference_nav'])) > 1e-05 or abs(ask - number(port['portfolio_ask_reference_price'])) > 1e-05 or abs(ceiling - number(port['portfolio_max_reference_price'])) > 1e-05:
            portfolio_errors.append(port['portfolio_result_id'])
    _check(checks, 'T10_PORTFOLIO_RECONCILIATION', not portfolio_errors, len(portfolio_errors), 0, 'pricing.portfolio_results', '|'.join(portfolio_errors))
    unlabeled = [row['result_id'] for row in results if row.get('origin_type') != 'DERIVED' or not row.get('source_record_ids')]
    _check(checks, 'T12_ORIGIN_AND_SOURCE', not unlabeled, len(unlabeled), 0, '02-pricing/positions.csv', '|'.join(unlabeled[:10]))
    return checks

def failed(checks: Sequence[Mapping[str, str]]) -> list[Mapping[str, str]]:
    return [row for row in checks if row.get('status') == 'FAIL']
