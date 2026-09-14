"""Read parent data without importing or modifying the parent or GP-Scoring systems."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from utils import DataError, fingerprint, git_state, iter_csv, number, parse_date, read_csv

class InputError(DataError):
    """Raised when pricing inputs fail identity, scope, date, or quality gates."""

def _text(value: object) -> str:
    return str(value or '').strip()

def _active(row: Mapping[str, str]) -> bool:
    return _text(row.get('record_status')).upper() == 'ACTIVE'

def _whole_fund(row: Mapping[str, str]) -> bool:
    return row.get('perspective', '') == 'fund_total' and (not row.get('lp_id', '')) and (not row.get('share_class_name', ''))

def _timestamp(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise InputError('quality checked_at is blank')
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def _quality_rows(path: Path, period_ids: set[str]) -> list[dict[str, str]]:
    rows = []
    for row in iter_csv(path):
        if row.get('record_table') == 'fund_periods' and row.get('record_id') in period_ids:
            rows.append(row)
    return rows

def resolve_quality(path: Path, period_ids: set[str], required_rules: Iterable[str]) -> tuple[dict[str, tuple[bool, str]], dict[str, Any]]:
    """Use only the latest applicable coherent run and never inherit an older PASS."""
    required = set(required_rules)
    if not period_ids:
        return ({}, {'status': 'NO_PERIODS', 'run_id': '', 'checked_at': ''})
    rows = _quality_rows(path, period_ids)
    if not rows:
        return ({pid: (False, 'QUALITY_ROWS_MISSING') for pid in period_ids}, {'status': 'MISSING', 'run_id': '', 'checked_at': ''})
    by_run: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        run_id = _text(row.get('run_id'))
        checked_at = _text(row.get('checked_at'))
        if run_id and checked_at:
            by_run[run_id, checked_at].append(row)
    if not by_run:
        return ({pid: (False, 'QUALITY_RUN_MISSING') for pid in period_ids}, {'status': 'MISSING', 'run_id': '', 'checked_at': ''})
    latest_time = max((_timestamp(key[1]) for key in by_run))
    latest_groups = [(key, group) for key, group in by_run.items() if _timestamp(key[1]) == latest_time]
    complete = []
    for key, group in latest_groups:
        seen: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in group:
            seen[row.get('record_id', ''), row.get('rule_id', '')].append(row)
        if all((len(seen[pid, rule]) == 1 for pid in period_ids for rule in required)):
            complete.append((key, group, seen))
    if len(complete) != 1:
        reason = 'LATEST_QUALITY_RUN_INCOMPLETE' if not complete else 'LATEST_QUALITY_RUN_AMBIGUOUS'
        return ({pid: (False, reason) for pid in period_ids}, {'status': reason, 'run_id': '', 'checked_at': latest_time.isoformat()})
    (run_id, checked_at), group, seen = complete[0]
    approval: dict[str, tuple[bool, str]] = {}
    for pid in period_ids:
        reasons = []
        for rule in sorted(required):
            row = seen[pid, rule][0]
            status = _text(row.get('status')).upper()
            severity = _text(row.get('severity')).lower()
            if status not in {'PASS', 'FAIL', 'SKIP'}:
                reasons.append(f'INVALID_STATUS:{rule}')
            elif status == 'SKIP':
                reasons.append(f'REQUIRED_RULE_SKIPPED:{rule}')
            elif status == 'FAIL' and severity == 'error':
                reasons.append(f'ERROR_FAIL:{rule}')
        approval[pid] = (not reasons, 'QUALITY_APPROVED:' + run_id if not reasons else '|'.join(reasons))
    return (approval, {'status': 'COMPLETE', 'run_id': run_id, 'checked_at': checked_at, 'rows': len(group)})

def _lineage_for_ids(path: Path, record_ids: set[str]) -> list[dict[str, str]]:
    if not path.is_file() or not record_ids:
        return []
    keep_fields = {'canonical_asset_class', 'canonical_strategy', 'canonical_sub_strategy', 'base_currency', 'fund_size', 'vintage_year', 'strategy', 'sub_strategy'}
    rows = []
    for row in iter_csv(path):
        if row.get('target_record_id') in record_ids and row.get('target_field') in keep_fields:
            rows.append(row)
    return rows

def _candidate_records(parent: Path, population: str, policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[Path]]:
    if population == 'integrated_demo':
        base = parent / 'data' / 'csv'
        config = policy['integrated_demo']
        paths = {'fund_master': base / 'fund_master.csv', 'manager_master': base / 'manager_master.csv', 'periods': base / 'fund_periods.csv', 'quality': base / 'quality_results.csv', 'lineage': parent / 'data' / 'integrated' / 'cell-lineage.csv', 'gaps': parent / 'data' / 'integrated' / 'gap-ledger.csv'}
    elif population == 'fixture':
        base = parent / 'data' / 'synthetic' / 'clean'
        config = policy['fixture']
        paths = {'fund_master': base / 'fund_master.csv', 'manager_master': base / 'manager_master.csv', 'periods': base / 'fund_periods.csv', 'quality': base / 'quality_results.csv', 'lineage': None, 'gaps': None}
    elif population == 'observed':
        base = parent / 'data' / 'extracted' / 'fund-level'
        config = policy['observed']
        paths = {'fund_master': base / 'fund_master.csv', 'manager_master': base / 'manager_master.csv', 'periods': base / 'fund_periods.csv', 'quality': base / 'quality_results.csv', 'lineage': parent / 'data' / 'integrated' / 'cell-lineage.csv', 'gaps': parent / 'data' / 'integrated' / 'gap-ledger.csv'}
    else:
        raise InputError(f'unsupported population: {population}')
    fund_rows = read_csv(paths['fund_master'])
    manager_rows = read_csv(paths['manager_master'])
    periods = read_csv(paths['periods'])
    managers = {row['manager_id']: row for row in manager_rows if row.get('manager_id')}
    funds = {row['fund_id']: row for row in fund_rows if row.get('fund_id')}
    if len(funds) != len([row for row in fund_rows if row.get('fund_id')]):
        raise InputError('fund_master contains duplicate fund_id values')
    if population in {'integrated_demo', 'fixture'}:
        reference = config['reference_date']
        currency = config['currency']
        strategy = config['strategy']
        candidates = []
        for period in periods:
            fund = funds.get(period.get('fund_id', ''))
            if fund is None or not _active(period) or (not _whole_fund(period)):
                continue
            if period.get('as_of_date') != reference or period.get('currency') != currency:
                continue
            if population == 'fixture':
                strategy_value = _text(fund.get('strategy')).lower()
            else:
                strategy_value = _text(fund.get('canonical_strategy')).lower() or _text(period.get('strategy')).lower()
            if strategy_value != strategy:
                continue
            candidates.append((fund['fund_id'], fund, period))
        candidates.sort(key=lambda item: item[0])
        candidate_ids = {period['fund_period_id'] for _, _, period in candidates}
        approvals, quality_state = resolve_quality(paths['quality'], candidate_ids, policy['quality']['required_parent_rules'])
        selected = []
        rejected = []
        for fund_id, fund, period in candidates:
            manager_id = fund.get('fund_manager_id', '')
            reasons = []
            if not manager_id or manager_id not in managers:
                reasons.append('MANAGER_UNRESOLVED')
            approved, qreason = approvals.get(period['fund_period_id'], (False, 'QUALITY_MISSING'))
            if not approved:
                reasons.append(qreason)
            target = rejected if reasons else selected
            target.append({'fund': fund, 'period': period, 'manager': managers.get(manager_id, {}), 'input_reasons': reasons, 'quality_reason': qreason})
        max_positions = int(config['max_positions'])
        selected = selected[:max_positions]
        selected_period_ids = {item['period']['fund_period_id'] for item in selected}
        selected_fund_ids = {item['fund']['fund_id'] for item in selected}
        lineage = _lineage_for_ids(paths['lineage'], selected_fund_ids | selected_period_ids) if paths['lineage'] else []
        input_paths = [paths['fund_master'], paths['manager_master'], paths['periods'], paths['quality']]
        if paths['lineage']:
            input_paths.append(paths['lineage'])
        if paths['gaps']:
            input_paths.append(paths['gaps'])
        meta = {'quality_state': quality_state, 'candidate_count': len(candidates), 'quality_rejected_count': len(rejected), 'lineage_rows': lineage}
        return (selected, meta, input_paths)
    observed_candidates = []
    for period in periods:
        fund = funds.get(period.get('fund_id', ''))
        if fund is None or not _active(period):
            continue
        strategy_value = _text(period.get('canonical_strategy')).lower() or _text(fund.get('canonical_strategy')).lower() or _text(period.get('strategy')).lower()
        if strategy_value != 'buyout':
            continue
        try:
            as_of = parse_date(period.get('as_of_date'), 'as_of_date')
        except DataError:
            continue
        observed_candidates.append((fund['fund_id'], as_of, fund, period))
    latest: dict[str, tuple] = {}
    for item in observed_candidates:
        if item[0] not in latest or item[1] > latest[item[0]][1]:
            latest[item[0]] = item
    selected = []
    for fund_id, as_of, fund, period in sorted(latest.values(), key=lambda x: (x[1], x[0]), reverse=True)[:int(config['max_positions'])]:
        manager = managers.get(fund.get('fund_manager_id', ''), {})
        selected.append({'fund': fund, 'period': period, 'manager': manager, 'input_reasons': ['OBSERVED_EVIDENCE_ONLY'], 'quality_reason': 'NOT_PRICED'})
    lineage = _lineage_for_ids(paths['lineage'], {item['fund']['fund_id'] for item in selected}) if paths['lineage'] else []
    input_paths = [paths['fund_master'], paths['manager_master'], paths['periods'], paths['quality'], paths['lineage'], paths['gaps']]
    return (selected, {'quality_state': {'status': 'EVIDENCE_ONLY'}, 'candidate_count': len(observed_candidates), 'quality_rejected_count': 0, 'lineage_rows': lineage}, input_paths)

def build_context(parent: Path, population: str, policy: Mapping[str, Any]) -> dict[str, Any]:
    parent = parent.resolve()
    selected, metadata, input_paths = _candidate_records(parent, population, policy)
    prepared = []
    for index, item in enumerate(selected, start=1):
        fund, period, manager = (item['fund'], item['period'], item['manager'])
        prepared.append({'population': population, 'display_name': f'Demo Position {index:02d}' if population == 'integrated_demo' else fund.get('fund_name', '') if population == 'fixture' else f'Source Evidence {index:02d}', 'fund_id': fund.get('fund_id', ''), 'fund_name': fund.get('fund_name', ''), 'manager_id': fund.get('fund_manager_id', ''), 'manager_name': fund.get('fund_manager_name', '') or manager.get('manager_name', ''), 'fund_period_id': period.get('fund_period_id', ''), 'perspective': period.get('perspective', ''), 'lp_id': period.get('lp_id', ''), 'lp_name': period.get('lp_name', ''), 'share_class_name': period.get('share_class_name', ''), 'as_of_date': period.get('as_of_date', ''), 'report_date': period.get('report_date', ''), 'currency': period.get('currency', ''), 'strategy': fund.get('canonical_strategy', '') or fund.get('strategy', '') or period.get('strategy', ''), 'sub_strategy': fund.get('canonical_sub_strategy', '') or fund.get('sub_strategy', '') or period.get('sub_strategy', ''), 'vintage_year': fund.get('vintage_year', '') or period.get('vintage_year', ''), 'commitment': period.get('commitment', ''), 'paid_in_capital_itd': period.get('paid_in_capital_itd', ''), 'distributions_itd': period.get('distributions_itd', ''), 'nav': period.get('nav', ''), 'unfunded_commitment': period.get('unfunded_commitment', ''), 'recallable_distributions_itd': period.get('recallable_distributions_itd', ''), 'dpi': period.get('dpi', ''), 'rvpi': period.get('rvpi', ''), 'tvpi': period.get('tvpi', ''), 'historical_irr': period.get('calculated_irr', '') or period.get('reported_irr', ''), 'period_provenance_type': period.get('provenance_type', ''), 'fund_provenance_type': fund.get('provenance_type', ''), 'source_document_id': period.get('source_document_id', '') or fund.get('source_document_id', ''), 'source_page': period.get('source_page', '') or fund.get('source_page', ''), 'input_reasons': item['input_reasons'], 'quality_reason': item['quality_reason']})
    return {'population': population, 'selected': prepared, 'metadata': metadata, 'parent_state': git_state(parent), 'input_fingerprints': fingerprint(input_paths, parent), 'input_paths': [str(path.resolve()) for path in input_paths]}

def numeric_balances(row: Mapping[str, Any]) -> dict[str, float]:
    required = ['commitment', 'paid_in_capital_itd', 'distributions_itd', 'nav', 'unfunded_commitment', 'recallable_distributions_itd']
    return {field: number(row.get(field), field) for field in required}
