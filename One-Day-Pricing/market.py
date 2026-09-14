"""Synthetic comparable-transaction simulation and simple out-of-sample market-price evaluation."""
from __future__ import annotations
import hashlib
import math
import random
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence
import numpy as np
from utils import DataError, fmt, number, optional_number, parse_date, read_csv, stable_id

class MarketError(DataError):
    """Raised when the synthetic market experiment is not valid."""

def _manager_bucket(manager_id: str, modulus: int) -> int:
    return int(hashlib.sha256(manager_id.encode('utf-8')).hexdigest()[:8], 16) % modulus

def _latest_on_or_before(rows: Sequence[Mapping[str, str]], cutoff: str) -> Mapping[str, str] | None:
    target = parse_date(cutoff)
    eligible = []
    for row in rows:
        text = row.get('as_of_date', '')
        if not text:
            continue
        day = parse_date(text)
        if day <= target and row.get('perspective') == 'fund_total' and (not row.get('lp_id')) and (not row.get('share_class_name')) and (row.get('record_status', '').upper() == 'ACTIVE'):
            eligible.append((day, row))
    return max(eligible, key=lambda item: item[0])[1] if eligible else None

def generate_trades(parent: Path, policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    base = parent / 'data' / 'synthetic' / 'clean'
    funds = {row['fund_id']: row for row in read_csv(base / 'fund_master.csv') if row.get('strategy') == policy['market']['strategy'] and row.get('base_currency') == 'USD'}
    periods_by_fund: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(base / 'fund_periods.csv'):
        if row.get('fund_id') in funds:
            periods_by_fund[row['fund_id']].append(row)
    rng = random.Random(int(policy['market']['seed']))
    snapshots = ['2023-12-31', '2024-12-31', '2025-12-31', '2026-06-30']
    regime = {2023: -0.04, 2024: -0.01, 2025: 0.01, 2026: 0.02}
    sub_offset = {'middle_market': 0.01, 'large_market': 0.02, 'small_market': -0.01}
    trades: list[dict[str, Any]] = []
    for fund_id, fund in sorted(funds.items()):
        for cutoff in snapshots:
            period = _latest_on_or_before(periods_by_fund[fund_id], cutoff)
            if period is None:
                continue
            nav = optional_number(period.get('nav'))
            distributions = optional_number(period.get('distributions_itd'))
            commitment = optional_number(period.get('commitment'))
            unfunded = optional_number(period.get('unfunded_commitment'))
            tvpi = optional_number(period.get('tvpi'))
            dpi = optional_number(period.get('dpi'))
            fund_size = optional_number(period.get('fund_size')) or optional_number(fund.get('fund_size'))
            if None in (nav, distributions, commitment, unfunded, tvpi, dpi) or commitment <= 0 or nav < 0 or (distributions < 0):
                continue
            report_date = period.get('report_date') or period.get('as_of_date')
            deal_date = parse_date(report_date) + timedelta(days=14)
            vintage = int(fund.get('vintage_year') or deal_date.year)
            age = max(0, deal_date.year - vintage)
            nav_reliance = nav / (nav + distributions) if nav + distributions > 0 else 1.0
            unfunded_ratio = unfunded / commitment
            size_feature = math.log1p(max(fund_size or commitment, 0.0))
            price = 0.9 + 0.025 * (tvpi - 1.4) + 0.035 * (dpi - 0.8) - 0.06 * nav_reliance - 0.05 * unfunded_ratio
            price += -0.012 * max(age - 10, 0) + (0.01 if 4 <= age <= 8 else 0.0)
            price += sub_offset.get(fund.get('sub_strategy', ''), 0.0) + regime.get(deal_date.year, 0.0) + rng.normalvariate(0.0, 0.025)
            clearing = max(0.5, min(1.1, price))
            draw = rng.random()
            status = 'SOLD' if draw < 0.86 else 'WITHDRAWN' if draw < 0.94 else 'UNSOLD'
            ask = max(0.45, min(1.2, clearing + rng.uniform(0.015, 0.065)))
            bid = max(0.4, min(1.15, clearing + rng.uniform(-0.045, 0.018)))
            trade_id = stable_id('TRADE', fund_id, period['as_of_date'], deal_date)
            trades.append({'trade_id': trade_id, 'fund_id': fund_id, 'manager_id': fund.get('fund_manager_id', ''), 'strategy': fund.get('strategy', ''), 'sub_strategy': fund.get('sub_strategy', ''), 'vintage_year': str(vintage), 'reference_date': period['as_of_date'], 'available_at': report_date, 'deal_date': deal_date.isoformat(), 'currency': period['currency'], 'reference_nav': fmt(nav, 8), 'commitment': fmt(commitment, 8), 'unfunded': fmt(unfunded, 8), 'tvpi': fmt(tvpi, 10), 'dpi': fmt(dpi, 10), 'age_years': fmt(float(age), 4), 'nav_reliance': fmt(nav_reliance, 10), 'unfunded_ratio': fmt(unfunded_ratio, 10), 'log_fund_size': fmt(size_feature, 10), 'ask_nav_fraction': fmt(ask, 10), 'bid_nav_fraction': fmt(bid, 10), 'clearing_nav_fraction': fmt(clearing, 10) if status == 'SOLD' else '', 'status': status, 'origin_type': 'NEW_SYNTHETIC', 'generator_version': 'MARKET_SIM_V1', 'assumption_id': 'MARKET_SIMULATION_V1'})
    return trades

def _features(row: Mapping[str, Any], categories: Sequence[str]) -> list[float]:
    numeric = [number(row['age_years']), number(row['tvpi']), number(row['dpi']), number(row['nav_reliance']), number(row['unfunded_ratio']), number(row['log_fund_size'])]
    return numeric + [1.0 if row.get('sub_strategy') == category else 0.0 for category in categories]

def evaluate(trades: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    cfg = policy['market']
    cutoff = parse_date(cfg['train_cutoff'])
    modulus = int(cfg['manager_holdout_modulus'])
    sold = [row for row in trades if row.get('status') == 'SOLD' and row.get('clearing_nav_fraction')]
    train = [row for row in sold if parse_date(row['deal_date']) <= cutoff and _manager_bucket(str(row['manager_id']), modulus) != 0]
    temporal = [row for row in sold if parse_date(row['deal_date']) > cutoff]
    manager_holdout = [row for row in sold if parse_date(row['deal_date']) <= cutoff and _manager_bucket(str(row['manager_id']), modulus) == 0]
    if len(train) < int(cfg['minimum_train_rows']):
        raise MarketError(f'synthetic market training rows {len(train)} below minimum')
    categories = sorted({str(row.get('sub_strategy', '')) for row in train})
    X = np.asarray([_features(row, categories) for row in train], dtype=float)
    y = np.asarray([number(row['clearing_nav_fraction']) for row in train], dtype=float)
    mean = X[:, :6].mean(axis=0)
    std = X[:, :6].std(axis=0)
    std[std == 0] = 1.0
    Xs = X.copy()
    Xs[:, :6] = (Xs[:, :6] - mean) / std
    Xdesign = np.column_stack([np.ones(len(Xs)), Xs])
    alpha = float(cfg['ridge_alpha'])
    penalty = np.eye(Xdesign.shape[1]) * alpha
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(Xdesign.T @ Xdesign + penalty, Xdesign.T @ y)
    overall_median = median(y.tolist())
    medians = {cat: median([number(row['clearing_nav_fraction']) for row in train if row.get('sub_strategy', '') == cat]) for cat in categories}
    comparisons: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    for split_name, test_rows in [('temporal_test', temporal), ('manager_holdout_test', manager_holdout)]:
        if not test_rows:
            evaluations.append({'split': split_name, 'count': '0', 'baseline_mae': '', 'model_mae': '', 'baseline_nav_weighted_mae': '', 'model_nav_weighted_mae': '', 'model_bias': '', 'model_beats_baseline': '', 'status': 'SKIP', 'origin_type': 'DERIVED'})
            continue
        actuals = []
        baseline_preds = []
        model_preds = []
        weights = []
        for row in test_rows:
            x = np.asarray(_features(row, categories), dtype=float)
            x[:6] = (x[:6] - mean) / std
            model = float(np.concatenate([[1.0], x]) @ beta)
            model = max(0.35, min(1.25, model))
            baseline = float(medians.get(str(row.get('sub_strategy', '')), overall_median))
            actual = number(row['clearing_nav_fraction'])
            weight = max(number(row['reference_nav']), 0.0)
            actuals.append(actual)
            baseline_preds.append(baseline)
            model_preds.append(model)
            weights.append(weight)
            comparisons.append({'trade_id': row['trade_id'], 'split': split_name, 'fund_id': row['fund_id'], 'manager_id': row['manager_id'], 'deal_date': row['deal_date'], 'sub_strategy': row['sub_strategy'], 'actual_clearing_nav_fraction': fmt(actual, 10), 'baseline_prediction': fmt(baseline, 10), 'model_prediction': fmt(model, 10), 'baseline_abs_error': fmt(abs(baseline - actual), 10), 'model_abs_error': fmt(abs(model - actual), 10), 'reference_nav': row['reference_nav'], 'origin_type': 'DERIVED'})
        baseline_errors = np.abs(np.asarray(baseline_preds) - np.asarray(actuals))
        model_errors = np.abs(np.asarray(model_preds) - np.asarray(actuals))
        weight_arr = np.asarray(weights, dtype=float)
        weight_total = float(weight_arr.sum())
        b_w = float((baseline_errors * weight_arr).sum() / weight_total) if weight_total > 0 else float(baseline_errors.mean())
        m_w = float((model_errors * weight_arr).sum() / weight_total) if weight_total > 0 else float(model_errors.mean())
        bias = float((np.asarray(model_preds) - np.asarray(actuals)).mean())
        b_mae = float(baseline_errors.mean())
        m_mae = float(model_errors.mean())
        evaluations.append({'split': split_name, 'count': str(len(test_rows)), 'baseline_mae': fmt(b_mae, 10), 'model_mae': fmt(m_mae, 10), 'baseline_nav_weighted_mae': fmt(b_w, 10), 'model_nav_weighted_mae': fmt(m_w, 10), 'model_bias': fmt(bias, 10), 'model_beats_baseline': 'TRUE' if m_mae < b_mae else 'FALSE', 'status': 'PASS', 'origin_type': 'DERIVED'})
    metadata = {'train_count': len(train), 'temporal_test_count': len(temporal), 'manager_holdout_count': len(manager_holdout), 'categories': categories, 'feature_names': ['age_years', 'tvpi', 'dpi', 'nav_reliance', 'unfunded_ratio', 'log_fund_size', *[f'sub_strategy={c}' for c in categories]], 'coefficients': [float(v) for v in beta], 'simulation_only': True}
    return (comparisons, evaluations, metadata)
