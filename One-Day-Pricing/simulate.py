"""Generate deterministic seller positions, interim events, and forecast assumptions."""
from __future__ import annotations
import random
from datetime import date, timedelta
from typing import Any, Mapping, Sequence
from inputs import numeric_balances
from utils import DataError, fmt, hash_json, number, parse_date, stable_id

class SimulationError(DataError):
    """Raised when a synthetic transaction cannot be reconciled."""

def _rng(policy: Mapping[str, Any], population: str) -> random.Random:
    seed = int(policy['seed'])
    population_salt = sum((ord(ch) for ch in population))
    return random.Random(seed + population_salt)

def _between(start: date, end: date, fraction: float) -> date:
    days = (end - start).days
    if days <= 1:
        return end
    return start + timedelta(days=max(1, min(days - 1, round(days * fraction))))

def _ask_fraction(row: Mapping[str, Any], quote_date: date, policy: Mapping[str, Any], rng: random.Random) -> float:
    seller = policy['seller']
    base = float(seller['base_ask_nav_fraction'])
    try:
        age = quote_date.year - int(row.get('vintage_year') or quote_date.year)
    except ValueError:
        age = 8
    nav = max(number(row.get('nav'), 'nav'), 0.0)
    distributions = max(number(row.get('distributions_itd'), 'distributions_itd'), 0.0)
    nav_reliance = nav / (nav + distributions) if nav + distributions > 0 else 1.0
    if age >= 15:
        base -= 0.12
    elif age >= 10:
        base -= 0.06
    elif age <= 5:
        base += 0.03
    base -= 0.05 * max(nav_reliance - 0.55, 0.0)
    base += rng.uniform(-float(seller['ask_noise']), float(seller['ask_noise']))
    return max(float(seller['min_ask_nav_fraction']), min(float(seller['max_ask_nav_fraction']), base))

def _consent(index: int, population: str) -> str:
    if population == 'integrated_demo':
        return ['APPROVED', 'APPROVED', 'PENDING', 'APPROVED', 'UNKNOWN', 'APPROVED', 'DENIED'][(index - 1) % 7]
    if index % 23 == 0:
        return 'DENIED'
    if index % 17 == 0:
        return 'UNKNOWN'
    if index % 11 == 0:
        return 'PENDING'
    return 'APPROVED'

def generate_positions(context: Mapping[str, Any], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    population = str(context['population'])
    if population == 'observed':
        return []
    config = policy[population]
    reference_date = parse_date(config['reference_date'], 'reference_date')
    quote_date = parse_date(config['quote_date'], 'quote_date')
    closing_date = parse_date(config['closing_date'], 'closing_date')
    if not reference_date <= quote_date <= closing_date:
        raise SimulationError('reference_date <= quote_date <= closing_date is required')
    seller_policy = policy['seller']
    rng = _rng(policy, population)
    sale_fractions = [float(value) for value in seller_policy['sale_fractions']]
    positions = []
    for index, source in enumerate(context['selected'], start=1):
        balances = numeric_balances(source)
        seller_ownership = rng.uniform(float(seller_policy['ownership_min']), float(seller_policy['ownership_max']))
        sale_fraction = sale_fractions[(index - 1) % len(sale_fractions)]
        scale = seller_ownership * sale_fraction
        if not (0 < seller_ownership <= 1 and 0 < sale_fraction <= 1 and (0 < scale <= 1)):
            raise SimulationError('invalid seller ownership or sale fraction')
        transferred = {key: value * scale for key, value in balances.items()}
        ask_fraction = _ask_fraction(source, quote_date, policy, rng)
        reference_nav = transferred['nav']
        transaction_cost = reference_nav * float(seller_policy['transaction_cost_nav_fraction'])
        report_date = str(source.get('report_date') or '')
        if report_date:
            available_at = report_date
            availability_origin = 'PARENT_SYNTHETIC' if source.get('period_provenance_type') == 'SYNTHETIC' else 'PARENT_SOURCE'
        else:
            assumed = quote_date - timedelta(days=42)
            available_at = assumed.isoformat()
            availability_origin = 'ASSUMPTION'
        position_id = stable_id('POS', population, source['fund_period_id'], index)
        deal_id = 'DEAL_INTEGRATED_DEMO' if population == 'integrated_demo' else 'DEAL_FIXTURE_DEMO'
        positions.append({'deal_id': deal_id, 'position_id': position_id, 'population': population, 'display_name': source['display_name'], 'fund_id': source['fund_id'], 'manager_id': source['manager_id'], 'fund_period_id': source['fund_period_id'], 'seller_id': 'SELLER_DEMO_001', 'currency': source['currency'], 'strategy': source['strategy'], 'sub_strategy': source['sub_strategy'], 'vintage_year': source['vintage_year'], 'reference_date': reference_date.isoformat(), 'quote_date': quote_date.isoformat(), 'closing_date': closing_date.isoformat(), 'available_at': available_at, 'availability_origin': availability_origin, 'seller_fund_fraction': fmt(seller_ownership, 10), 'sale_fraction': fmt(sale_fraction, 10), 'transferred_fraction_of_fund': fmt(scale, 10), 'reference_commitment': fmt(transferred['commitment'], 6), 'reference_paid_in': fmt(transferred['paid_in_capital_itd'], 6), 'reference_distributions': fmt(transferred['distributions_itd'], 6), 'reference_nav': fmt(reference_nav, 6), 'reference_unfunded': fmt(transferred['unfunded_commitment'], 6), 'reference_recallable': fmt(transferred['recallable_distributions_itd'], 6), 'ask_nav_fraction': fmt(ask_fraction, 10), 'ask_reference_price': fmt(ask_fraction * reference_nav, 6), 'buyer_transaction_cost': fmt(transaction_cost, 6), 'consent_status': _consent(index, population), 'proportional_transfer_supported': 'TRUE', 'all_or_nothing': 'FALSE', 'settlement_convention': 'REFERENCE_NAV_PLUS_ELIGIBLE_CALLS_MINUS_DISTRIBUTIONS', 'origin_type': 'NEW_SYNTHETIC', 'source_record_ids': source['fund_period_id'], 'quality_reason': source['quality_reason']})
    return positions

def generate_interim_events(positions: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    cfg = policy['interim']
    events: list[dict[str, Any]] = []
    for index, pos in enumerate(positions, start=1):
        r = parse_date(pos['reference_date'])
        q = parse_date(pos['quote_date'])
        s = parse_date(pos['closing_date'])
        nav = number(pos['reference_nav'])
        unfunded = number(pos['reference_unfunded'])
        fee_fraction = float(cfg['call_fee_fraction'])
        actual_call = min(unfunded, unfunded * float(cfg['actual_call_unfunded_fraction']))
        actual_dist = min(max(nav, 0.0), max(nav, 0.0) * float(cfg['actual_distribution_nav_fraction']))
        remaining_after_actual = max(0.0, unfunded - actual_call)
        forecast_call = min(remaining_after_actual, remaining_after_actual * float(cfg['forecast_call_unfunded_fraction']))
        forecast_dist = min(max(nav - actual_dist, 0.0), max(nav, 0.0) * float(cfg['forecast_distribution_nav_fraction']))
        specs = [('capital_call', actual_call, _between(r, q, 0.38), 'ACTUAL'), ('distribution', actual_dist, _between(r, q, 0.72), 'ACTUAL'), ('capital_call', forecast_call, _between(q, s, 0.35), 'FORECAST'), ('distribution', forecast_dist, _between(q, s, 0.7), 'FORECAST')]
        for event_index, (kind, amount, event_date, status) in enumerate(specs, start=1):
            if amount <= 0:
                continue
            recall = 0.0
            if kind == 'distribution' and index == int(cfg['recallable_case_index']) and (status == 'ACTUAL'):
                recall = amount * float(cfg['recallable_distribution_fraction'])
            if kind == 'capital_call':
                contribution = amount
                fee_expense = amount * fee_fraction
                commitment_reduction = amount
            else:
                contribution = 0.0
                fee_expense = 0.0
                commitment_reduction = 0.0
            available_at = (event_date + timedelta(days=1)).isoformat() if status == 'ACTUAL' else q.isoformat()
            events.append({'event_id': stable_id('EVT', pos['position_id'], event_index, kind, event_date), 'deal_id': pos['deal_id'], 'position_id': pos['position_id'], 'event_date': event_date.isoformat(), 'available_at': available_at, 'event_type': kind, 'amount': fmt(amount, 6), 'currency': pos['currency'], 'actual_or_forecast': status, 'settlement_eligible': 'TRUE', 'commitment_reduction': fmt(commitment_reduction, 6), 'recallable_increase': fmt(recall, 6), 'capital_account_contribution': fmt(contribution, 6), 'fee_expense_amount': fmt(fee_expense, 6), 'origin_type': 'NEW_SYNTHETIC' if status == 'ACTUAL' else 'FORECAST', 'assumption_id': 'INTERIM_DEMO_V1', 'source_record_ids': pos['fund_period_id']})
    return events

def assumption_rows(policy: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for category in ['seller', 'interim', 'buyer']:
        for name, value in policy[category].items():
            if isinstance(value, (dict, list)):
                continue
            rows.append({'assumption_id': stable_id('ASM', category, name), 'category': category, 'name': name, 'value': str(value), 'unit': '', 'description': 'Demonstration policy setting', 'origin_type': 'ASSUMPTION'})
    for scenario_id, values in policy['forecast']['scenarios'].items():
        for name, value in values.items():
            rows.append({'assumption_id': stable_id('ASM', 'forecast', scenario_id, name), 'category': f'forecast:{scenario_id}', 'name': name, 'value': str(value), 'unit': '', 'description': 'Scenario assumption', 'origin_type': 'ASSUMPTION'})
    for name in ['quarters', 'funding_quarters', 'distribution_start_quarter', 'distribution_fraction', 'call_fee_fraction', 'draw_fraction']:
        rows.append({'assumption_id': stable_id('ASM', 'forecast', name), 'category': 'forecast', 'name': name, 'value': str(policy['forecast'][name]), 'unit': '', 'description': 'Forecast engine setting', 'origin_type': 'ASSUMPTION'})
    return rows

def evidence_packet(context: Mapping[str, Any], positions: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    return {'population': context['population'], 'policy_version': policy['version'], 'selected_parent_records': list(context['selected']), 'selected_parent_lineage': context['metadata'].get('lineage_rows', []), 'positions': list(positions), 'interim_events': list(events), 'origin_contract': {'PARENT_SOURCE': 'Printed or reviewed parent record', 'PARENT_SYNTHETIC': 'Parent completion or standalone fixture record', 'NEW_SYNTHETIC': 'New fictional transaction fact generated for this product', 'ASSUMPTION': 'Declared pricing or simulation policy', 'FORECAST': 'Future event or value generated from declared assumptions', 'DERIVED': 'Calculated from referenced inputs'}, 'packet_hash': hash_json({'positions': list(positions), 'events': list(events), 'policy_version': policy['version']})}

def validate_transaction_inputs(positions: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_positions: set[str] = set()
    seen_events: set[str] = set()
    by_position: dict[str, list[Mapping[str, Any]]] = {}
    for pos in positions:
        pid = str(pos['position_id'])
        if pid in seen_positions:
            errors.append(f'duplicate position_id: {pid}')
        seen_positions.add(pid)
        by_position[pid] = []
        try:
            r, q, s = (parse_date(pos['reference_date']), parse_date(pos['quote_date']), parse_date(pos['closing_date']))
            if not r <= q <= s:
                errors.append(f'date order: {pid}')
            if not 0 < number(pos['sale_fraction']) <= 1:
                errors.append(f'sale fraction: {pid}')
            if number(pos['reference_nav']) <= 0:
                errors.append(f'nonpositive reference NAV: {pid}')
            if number(pos['reference_unfunded']) < 0:
                errors.append(f'negative unfunded: {pid}')
        except DataError as exc:
            errors.append(f'{pid}: {exc}')
    for event in events:
        eid = str(event['event_id'])
        pid = str(event['position_id'])
        if eid in seen_events:
            errors.append(f'duplicate event_id: {eid}')
        seen_events.add(eid)
        if pid not in by_position:
            errors.append(f'event position missing: {eid}')
            continue
        by_position[pid].append(event)
    for pos in positions:
        pid = str(pos['position_id'])
        r, s = (parse_date(pos['reference_date']), parse_date(pos['closing_date']))
        capacity = number(pos['reference_unfunded'])
        for event in sorted(by_position.get(pid, []), key=lambda row: (row['event_date'], row['event_id'])):
            day = parse_date(event['event_date'])
            if not r < day <= s:
                errors.append(f'interim event outside reference/close interval: {event['event_id']}')
            if event['currency'] != pos['currency']:
                errors.append(f'event currency mismatch: {event['event_id']}')
            reduction = number(event['commitment_reduction'])
            increase = number(event['recallable_increase'])
            if reduction > capacity + 1e-07:
                errors.append(f'call exceeds capacity: {event['event_id']}')
            capacity = capacity - reduction + increase
            if capacity < -1e-07:
                errors.append(f'negative capacity: {event['event_id']}')
    return errors
