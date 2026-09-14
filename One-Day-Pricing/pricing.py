"""Calculate settlement, future cash flows, price ceilings, and portfolio economics."""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from typing import Any, Mapping, Sequence
from finance import sign_changes, xirr, xnpv
from utils import DataError, add_months, fmt, number, parse_date, stable_id

class PricingError(DataError):
    """Raised when a transaction or scenario violates the pricing contract."""

def events_by_position(events: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[str(event['position_id'])].append(event)
    for rows in grouped.values():
        rows.sort(key=lambda row: (row['event_date'], row['event_id']))
    return grouped

def closing_state(position: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    r = parse_date(position['reference_date'])
    q = parse_date(position['quote_date'])
    s = parse_date(position['closing_date'])
    nav = number(position['reference_nav'], 'reference_nav')
    unfunded = number(position['reference_unfunded'], 'reference_unfunded')
    actual_adjustment = 0.0
    forecast_adjustment = 0.0
    actual_event_ids: list[str] = []
    forecast_event_ids: list[str] = []
    for event in sorted(events, key=lambda row: (row['event_date'], row['event_id'])):
        day = parse_date(event['event_date'], 'event_date')
        if not r < day <= s:
            continue
        if str(event.get('settlement_eligible', '')).upper() != 'TRUE':
            continue
        amount = number(event['amount'], 'event amount')
        kind = str(event['event_type'])
        status = str(event['actual_or_forecast']).upper()
        if kind == 'capital_call':
            delta = amount
            nav += number(event['capital_account_contribution']) - number(event['fee_expense_amount'])
        elif kind == 'distribution':
            delta = -amount
            nav -= amount
        else:
            raise PricingError(f'unsupported interim event type: {kind}')
        unfunded = unfunded - number(event['commitment_reduction']) + number(event['recallable_increase'])
        if status == 'ACTUAL' and day <= q:
            actual_adjustment += delta
            actual_event_ids.append(str(event['event_id']))
        else:
            forecast_adjustment += delta
            forecast_event_ids.append(str(event['event_id']))
    if nav < -1e-06:
        raise PricingError(f'closing NAV became negative for {position['position_id']}')
    if unfunded < -1e-06:
        raise PricingError(f'closing unfunded became negative for {position['position_id']}')
    return {'position_id': position['position_id'], 'closing_date': position['closing_date'], 'closing_economic_nav': max(0.0, nav), 'closing_unfunded': max(0.0, unfunded), 'actual_settlement_adjustment': actual_adjustment, 'forecast_settlement_adjustment': forecast_adjustment, 'settlement_adjustment': actual_adjustment + forecast_adjustment, 'actual_event_ids': actual_event_ids, 'forecast_event_ids': forecast_event_ids}

def forecast_position(position: Mapping[str, Any], state: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cfg = policy['forecast']
    closing = parse_date(position['closing_date'])
    total_quarters = int(cfg['quarters'])
    funding_quarters = int(cfg['funding_quarters'])
    base_distribution_start = int(cfg['distribution_start_quarter'])
    base_distribution_fraction = float(cfg['distribution_fraction'])
    draw_fraction = float(cfg['draw_fraction'])
    fee_fraction = float(cfg['call_fee_fraction'])
    if not 0 <= draw_fraction <= 1 or not 0 <= fee_fraction < 1:
        raise PricingError('forecast draw and fee fractions are invalid')
    cashflows: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for scenario_id, sc in cfg['scenarios'].items():
        nav = number(state['closing_economic_nav']) * float(sc['opening_nav_multiplier'])
        unfunded = number(state['closing_unfunded'])
        draw_remaining = unfunded * draw_fraction
        growth = float(sc['annual_growth'])
        distribution_start = base_distribution_start + int(sc['distribution_delay_quarters'])
        distribution_fraction = min(1.0, base_distribution_fraction * float(sc['distribution_fraction_multiplier']))
        previous = closing
        for quarter in range(1, total_quarters + 1):
            day = add_months(closing, 3 * quarter)
            elapsed = (day - previous).days / 365.0
            opening_nav = nav
            growth_amount = nav * ((1.0 + growth) ** elapsed - 1.0) if growth > -1.0 else 0.0
            nav += growth_amount
            call = 0.0
            capitalized = 0.0
            fee_expense = 0.0
            if quarter <= funding_quarters and draw_remaining > 1e-12:
                remaining_slots = funding_quarters - quarter + 1
                call = draw_remaining / remaining_slots
                draw_remaining -= call
                unfunded -= call
                capitalized = call * (1.0 - fee_fraction)
                fee_expense = call * fee_fraction
                nav += capitalized
                cashflows.append({'cashflow_id': stable_id('PCF', position['position_id'], scenario_id, quarter, 'call'), 'position_id': position['position_id'], 'deal_id': position['deal_id'], 'scenario_id': scenario_id, 'cashflow_date': day.isoformat(), 'cashflow_type': 'future_capital_call', 'amount': fmt(-call, 8), 'currency': position['currency'], 'origin_type': 'FORECAST', 'assumption_id': f'FORECAST_{scenario_id.upper()}_V1'})
            distribution = 0.0
            if quarter >= distribution_start and nav > 1e-12:
                distribution = nav if quarter == total_quarters else nav * distribution_fraction
                nav -= distribution
                cashflows.append({'cashflow_id': stable_id('PCF', position['position_id'], scenario_id, quarter, 'distribution'), 'position_id': position['position_id'], 'deal_id': position['deal_id'], 'scenario_id': scenario_id, 'cashflow_date': day.isoformat(), 'cashflow_type': 'future_distribution', 'amount': fmt(distribution, 8), 'currency': position['currency'], 'origin_type': 'FORECAST', 'assumption_id': f'FORECAST_{scenario_id.upper()}_V1'})
            if quarter == total_quarters and nav > 1e-10:
                distribution += nav
                cashflows.append({'cashflow_id': stable_id('PCF', position['position_id'], scenario_id, quarter, 'final_distribution'), 'position_id': position['position_id'], 'deal_id': position['deal_id'], 'scenario_id': scenario_id, 'cashflow_date': day.isoformat(), 'cashflow_type': 'future_distribution', 'amount': fmt(nav, 8), 'currency': position['currency'], 'origin_type': 'FORECAST', 'assumption_id': f'FORECAST_{scenario_id.upper()}_V1'})
                nav = 0.0
            steps.append({'position_id': position['position_id'], 'deal_id': position['deal_id'], 'scenario_id': scenario_id, 'quarter': str(quarter), 'step_date': day.isoformat(), 'opening_nav': fmt(opening_nav, 8), 'growth_amount': fmt(growth_amount, 8), 'capital_call': fmt(call, 8), 'capitalized_call': fmt(capitalized, 8), 'fee_expense': fmt(fee_expense, 8), 'distribution': fmt(distribution, 8), 'ending_nav': fmt(nav, 8), 'ending_unfunded': fmt(max(0.0, unfunded), 8), 'currency': position['currency'], 'origin_type': 'DERIVED'})
            previous = day
        if draw_remaining > 1e-06:
            raise PricingError(f'forecast draw schedule did not allocate target calls: {position['position_id']} {scenario_id}')
        if nav > 1e-06:
            raise PricingError(f'forecast failed to liquidate terminal NAV: {position['position_id']} {scenario_id}')
    return (cashflows, steps)

def _future_series(rows: Sequence[Mapping[str, Any]]) -> list[tuple[date, float]]:
    return [(parse_date(row['cashflow_date']), number(row['amount'])) for row in rows]

def _safe_xirr(cashflows: Sequence[tuple[date, float]]) -> tuple[float | None, str]:
    if sign_changes(cashflows) > 1:
        return (None, 'NONCONVENTIONAL_MULTIPLE_SIGN_CHANGES')
    try:
        value = xirr(cashflows)
    except ValueError as exc:
        return (None, 'XIRR_UNAVAILABLE:' + str(exc))
    residual = xnpv(value, cashflows)
    if abs(residual) > max(1e-06, sum((abs(amount) for _, amount in cashflows)) * 1e-08):
        return (None, 'XIRR_RESIDUAL_FAIL')
    return (value, 'OK')

def price_positions(positions: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    event_map = events_by_position(events)
    results: list[dict[str, Any]] = []
    cashflows: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    sensitivities: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    hurdle = float(policy['buyer']['hurdle_rate'])
    for position in positions:
        pid = str(position['position_id'])
        try:
            state = closing_state(position, event_map.get(pid, []))
            future, forecast_steps = forecast_position(position, state, policy)
        except (DataError, ValueError) as exc:
            exceptions.append({'position_id': pid, 'scenario_id': '', 'severity': 'ERROR', 'reason': 'PRICING_INPUT_ERROR', 'detail': str(exc)})
            continue
        cashflows.extend(future)
        steps.extend(forecast_steps)
        for scenario_id in policy['forecast']['scenarios']:
            scenario_rows = [row for row in future if row['scenario_id'] == scenario_id]
            series = _future_series(scenario_rows)
            closing = parse_date(position['closing_date'])
            anchored = [(closing, 0.0), *series]
            future_pv = xnpv(hurdle, anchored)
            transaction_cost = number(position['buyer_transaction_cost'])
            settlement_adjustment = number(state['settlement_adjustment'])
            max_closing_seller_payment = future_pv - transaction_cost
            max_reference_price = max_closing_seller_payment - settlement_adjustment
            reference_nav = number(position['reference_nav'])
            max_nav_fraction = max_reference_price / reference_nav if reference_nav != 0 else None
            ask_reference = number(position['ask_reference_price'])
            ask_closing_seller = ask_reference + settlement_adjustment
            ask_initial_outflow = ask_closing_seller + transaction_cost
            ask_series = [(closing, -ask_initial_outflow), *series]
            ask_npv = xnpv(hurdle, ask_series)
            ask_irr, irr_status = _safe_xirr(ask_series)
            total_calls = sum((-amount for _, amount in series if amount < 0))
            total_distributions = sum((amount for _, amount in series if amount > 0))
            denominator = ask_initial_outflow + total_calls
            money_multiple = total_distributions / denominator if denominator > 0 else None
            consent = str(position['consent_status'])
            if consent == 'DENIED':
                status, status_reason = ('NO_QUOTE', 'TRANSFER_CONSENT_DENIED')
            elif consent in {'PENDING', 'UNKNOWN'}:
                status, status_reason = ('DEMO_REVIEW', f'TRANSFER_CONSENT_{consent}')
            elif max_reference_price <= 0:
                status, status_reason = ('DEMO_DECLINE', 'NEGATIVE_BUYER_PRICE_CEILING')
            elif ask_reference <= max_reference_price:
                status, status_reason = ('DEMO_PURSUABLE', 'ASK_MEETS_BUYER_HURDLE')
            else:
                status, status_reason = ('DEMO_DECLINE', 'ASK_EXCEEDS_BUYER_CEILING')
            row = {'result_id': stable_id('PRICE', pid, scenario_id, hurdle), 'deal_id': position['deal_id'], 'position_id': pid, 'population': position['population'], 'display_name': position['display_name'], 'fund_id': position['fund_id'], 'manager_id': position['manager_id'], 'scenario_id': scenario_id, 'currency': position['currency'], 'reference_date': position['reference_date'], 'quote_date': position['quote_date'], 'closing_date': position['closing_date'], 'reference_nav': fmt(reference_nav, 8), 'reference_unfunded': position['reference_unfunded'], 'closing_economic_nav': fmt(number(state['closing_economic_nav']), 8), 'closing_unfunded': fmt(number(state['closing_unfunded']), 8), 'actual_settlement_adjustment': fmt(number(state['actual_settlement_adjustment']), 8), 'forecast_settlement_adjustment': fmt(number(state['forecast_settlement_adjustment']), 8), 'settlement_adjustment': fmt(settlement_adjustment, 8), 'ask_nav_fraction': position['ask_nav_fraction'], 'ask_reference_price': fmt(ask_reference, 8), 'ask_closing_seller_payment': fmt(ask_closing_seller, 8), 'buyer_transaction_cost': fmt(transaction_cost, 8), 'buyer_initial_outflow_at_ask': fmt(ask_initial_outflow, 8), 'buyer_hurdle_rate': fmt(hurdle, 10), 'future_cashflow_pv_at_hurdle': fmt(future_pv, 8), 'max_closing_seller_payment': fmt(max_closing_seller_payment, 8), 'max_reference_price': fmt(max_reference_price, 8), 'max_nav_fraction': fmt(max_nav_fraction, 10) if max_nav_fraction is not None else '', 'ask_npv_at_hurdle': fmt(ask_npv, 8), 'ask_irr': fmt(ask_irr, 10) if ask_irr is not None else '', 'ask_irr_status': irr_status, 'buyer_money_multiple': fmt(money_multiple, 10) if money_multiple is not None else '', 'future_calls': fmt(total_calls, 8), 'future_distributions': fmt(total_distributions, 8), 'consent_status': consent, 'status': status, 'status_reason': status_reason, 'origin_type': 'DERIVED', 'source_record_ids': position['source_record_ids']}
            results.append(row)
            if irr_status != 'OK':
                exceptions.append({'position_id': pid, 'scenario_id': scenario_id, 'severity': 'WARNING', 'reason': irr_status.split(':', 1)[0], 'detail': irr_status})
            for sensitivity in policy['buyer']['hurdle_sensitivities']:
                sensitivity = float(sensitivity)
                pv = xnpv(sensitivity, anchored)
                close_max = pv - transaction_cost
                ref_max = close_max - settlement_adjustment
                sensitivities.append({'position_id': pid, 'scenario_id': scenario_id, 'hurdle_rate': fmt(sensitivity, 10), 'future_cashflow_pv': fmt(pv, 8), 'max_reference_price': fmt(ref_max, 8), 'max_nav_fraction': fmt(ref_max / reference_nav, 10) if reference_nav else '', 'currency': position['currency'], 'origin_type': 'DERIVED'})
    return (results, cashflows, steps, sensitivities, exceptions)

def portfolio_results(position_results: Sequence[Mapping[str, Any]], cashflows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_scenario: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in position_results:
        by_scenario[str(row['scenario_id'])].append(row)
    flows_by_scenario_position: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for flow in cashflows:
        flows_by_scenario_position[str(flow['scenario_id']), str(flow['position_id'])].append(flow)
    output = []
    for scenario_id, rows in sorted(by_scenario.items()):
        currencies = {row['currency'] for row in rows if row['status'] != 'NO_QUOTE'}
        included = [row for row in rows if row['status'] != 'NO_QUOTE']
        excluded = [row for row in rows if row['status'] == 'NO_QUOTE']
        if len(currencies) > 1:
            raise PricingError(f'portfolio currency mix in {scenario_id}')
        if not included:
            continue
        closing = parse_date(included[0]['closing_date'])
        aggregate_flows: dict[date, float] = defaultdict(float)
        for row in included:
            aggregate_flows[closing] -= number(row['buyer_initial_outflow_at_ask'])
            for flow in flows_by_scenario_position[scenario_id, str(row['position_id'])]:
                aggregate_flows[parse_date(flow['cashflow_date'])] += number(flow['amount'])
        portfolio_series = sorted(aggregate_flows.items())
        irr, irr_status = _safe_xirr(portfolio_series)
        hurdle = float(policy['buyer']['hurdle_rate'])
        ask_npv = xnpv(hurdle, portfolio_series)
        ref_nav = sum((number(row['reference_nav']) for row in included))
        ask_ref = sum((number(row['ask_reference_price']) for row in included))
        max_ref = sum((number(row['max_reference_price']) for row in included))
        closing_cash = sum((number(row['buyer_initial_outflow_at_ask']) for row in included))
        unfunded = sum((number(row['closing_unfunded']) for row in included))
        future_calls = sum((number(row['future_calls']) for row in included))
        future_dist = sum((number(row['future_distributions']) for row in included))
        review_count = sum((row['status'] == 'DEMO_REVIEW' for row in included))
        if review_count:
            status, reason = ('DEMO_REVIEW', 'POSITION_REVIEW_REQUIRED')
        elif closing_cash > float(policy['buyer']['max_total_closing_cash']):
            status, reason = ('DEMO_REVIEW', 'CLOSING_CASH_LIMIT_EXCEEDED')
        elif unfunded > float(policy['buyer']['max_total_unfunded']):
            status, reason = ('DEMO_REVIEW', 'UNFUNDED_LIMIT_EXCEEDED')
        elif ask_ref <= max_ref:
            status, reason = ('DEMO_PURSUABLE', 'PORTFOLIO_ASK_MEETS_HURDLE')
        else:
            status, reason = ('DEMO_DECLINE', 'PORTFOLIO_ASK_EXCEEDS_CEILING')
        output.append({'portfolio_result_id': stable_id('PORT', scenario_id, *(row['position_id'] for row in included)), 'deal_id': included[0]['deal_id'], 'scenario_id': scenario_id, 'currency': next(iter(currencies)) if currencies else '', 'included_position_ids': '|'.join((row['position_id'] for row in included)), 'excluded_position_ids': '|'.join((row['position_id'] for row in excluded)), 'included_count': str(len(included)), 'excluded_count': str(len(excluded)), 'reference_nav': fmt(ref_nav, 8), 'portfolio_ask_reference_price': fmt(ask_ref, 8), 'portfolio_ask_nav_fraction': fmt(ask_ref / ref_nav, 10) if ref_nav else '', 'portfolio_max_reference_price': fmt(max_ref, 8), 'portfolio_max_nav_fraction': fmt(max_ref / ref_nav, 10) if ref_nav else '', 'buyer_initial_outflow_at_ask': fmt(closing_cash, 8), 'closing_unfunded': fmt(unfunded, 8), 'future_calls': fmt(future_calls, 8), 'future_distributions': fmt(future_dist, 8), 'ask_npv_at_hurdle': fmt(ask_npv, 8), 'ask_irr': fmt(irr, 10) if irr is not None else '', 'ask_irr_status': irr_status, 'buyer_hurdle_rate': fmt(hurdle, 10), 'status': status, 'status_reason': reason, 'origin_type': 'DERIVED'})
    return output
