"""Build, publish, and verify the self-contained One-Day Pricing demonstration."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence
import briefing
import inputs
import market
import pricing
import qc
import report
import simulate
from utils import DataError, fingerprint, hash_json, read_json, sha256_file, utc_now, verify_fingerprints, write_csv, write_json
HERE = Path(__file__).resolve().parent
ACTIVE_DIRS = ('01-inputs', '02-pricing', '03-report')
CANDIDATE = HERE / '_candidate'
FAILURE = HERE / 'last-failure.json'
POSITION_FIELDS = ['deal_id', 'position_id', 'population', 'display_name', 'fund_id', 'manager_id', 'fund_period_id', 'seller_id', 'currency', 'strategy', 'sub_strategy', 'vintage_year', 'reference_date', 'quote_date', 'closing_date', 'available_at', 'availability_origin', 'seller_fund_fraction', 'sale_fraction', 'transferred_fraction_of_fund', 'reference_commitment', 'reference_paid_in', 'reference_distributions', 'reference_nav', 'reference_unfunded', 'reference_recallable', 'ask_nav_fraction', 'ask_reference_price', 'buyer_transaction_cost', 'consent_status', 'proportional_transfer_supported', 'all_or_nothing', 'settlement_convention', 'origin_type', 'source_record_ids', 'quality_reason']
EVENT_FIELDS = ['event_id', 'deal_id', 'position_id', 'event_date', 'available_at', 'event_type', 'amount', 'currency', 'actual_or_forecast', 'settlement_eligible', 'commitment_reduction', 'recallable_increase', 'capital_account_contribution', 'fee_expense_amount', 'origin_type', 'assumption_id', 'source_record_ids']
ASSUMPTION_FIELDS = ['assumption_id', 'category', 'name', 'value', 'unit', 'description', 'origin_type']
PRICE_FIELDS = ['result_id', 'deal_id', 'position_id', 'population', 'display_name', 'fund_id', 'manager_id', 'scenario_id', 'currency', 'reference_date', 'quote_date', 'closing_date', 'reference_nav', 'reference_unfunded', 'closing_economic_nav', 'closing_unfunded', 'actual_settlement_adjustment', 'forecast_settlement_adjustment', 'settlement_adjustment', 'ask_nav_fraction', 'ask_reference_price', 'ask_closing_seller_payment', 'buyer_transaction_cost', 'buyer_initial_outflow_at_ask', 'buyer_hurdle_rate', 'future_cashflow_pv_at_hurdle', 'max_closing_seller_payment', 'max_reference_price', 'max_nav_fraction', 'ask_npv_at_hurdle', 'ask_irr', 'ask_irr_status', 'buyer_money_multiple', 'future_calls', 'future_distributions', 'consent_status', 'status', 'status_reason', 'origin_type', 'source_record_ids']
CASHFLOW_FIELDS = ['cashflow_id', 'position_id', 'deal_id', 'scenario_id', 'cashflow_date', 'cashflow_type', 'amount', 'currency', 'origin_type', 'assumption_id']
STEP_FIELDS = ['position_id', 'deal_id', 'scenario_id', 'quarter', 'step_date', 'opening_nav', 'growth_amount', 'capital_call', 'capitalized_call', 'fee_expense', 'distribution', 'ending_nav', 'ending_unfunded', 'currency', 'origin_type']
SENSITIVITY_FIELDS = ['position_id', 'scenario_id', 'hurdle_rate', 'future_cashflow_pv', 'max_reference_price', 'max_nav_fraction', 'currency', 'origin_type']
EXCEPTION_FIELDS = ['position_id', 'scenario_id', 'severity', 'reason', 'detail']
PORTFOLIO_FIELDS = ['portfolio_result_id', 'deal_id', 'scenario_id', 'currency', 'included_position_ids', 'excluded_position_ids', 'included_count', 'excluded_count', 'reference_nav', 'portfolio_ask_reference_price', 'portfolio_ask_nav_fraction', 'portfolio_max_reference_price', 'portfolio_max_nav_fraction', 'buyer_initial_outflow_at_ask', 'closing_unfunded', 'future_calls', 'future_distributions', 'ask_npv_at_hurdle', 'ask_irr', 'ask_irr_status', 'buyer_hurdle_rate', 'status', 'status_reason', 'origin_type']
DECISION_FIELDS = ['position_id', 'display_name', 'scenario_id', 'status', 'reason', 'ask_nav_fraction', 'max_nav_fraction', 'consent_status', 'source_record_ids']
CHECK_FIELDS = ['check_id', 'status', 'actual', 'expected', 'source', 'reason']

def _local_code_files() -> list[Path]:
    names = ['utils.py', 'finance.py', 'inputs.py', 'simulate.py', 'pricing.py', 'qc.py', 'market.py', 'briefing.py', 'report.py', 'ledger.py', 'run.py', 'policy.json', 'open-dashboard.cmd', 'open-dashboard.ps1']
    return [HERE / name for name in names]

def _ensure_clean_candidate() -> None:
    if CANDIDATE.exists():
        shutil.rmtree(CANDIDATE)
    for dirname in ACTIVE_DIRS:
        (CANDIDATE / dirname).mkdir(parents=True, exist_ok=True)

def _guide(stage: str) -> str:
    if stage == '01-inputs':
        return '# Pricing inputs\n\n| File | Content |\n|---|---|\n| `positions.csv` | Selected hypothetical seller positions and transferred balances. |\n| `interim-events.csv` | Reference-to-closing calls and distributions, with actual or forecast status. |\n| `assumptions.csv` | Declared transaction and forecast settings. |\n| `evidence.json` | Parent records, field origins, synthetic events, and evidence references. |\n| `manifest.json` | Input, code, policy, population, and parent-state fingerprints. |\n| `trades.csv` | Separate fictional secondary transactions used only by the market-model experiment. |\n'
    if stage == '02-pricing':
        return '# Pricing outputs\n\n| File | Content |\n|---|---|\n| `positions.csv` | Ask economics, buyer ceilings, returns, funding, and decision states by scenario. |\n| `cashflows.csv` | Future buyer cash flows used by the pricing calculations. |\n| `forecast-steps.csv` | Quarterly NAV, funding, growth, and distribution reconciliation. |\n| `sensitivities.csv` | Buyer-ceiling sensitivity to the required annual return. |\n| `portfolios.csv` | Portfolio economics recomputed from dated position cash flows. |\n| `decisions.csv` | One disposition per position and scenario. |\n| `exceptions.csv` | Calculation warnings and blocked positions. |\n| `market-comparison.csv` | Held-out predictions for the separate fictional-market experiment. |\n'
    return '# Reviewer report\n\n| File | Content |\n|---|---|\n| `dashboard.html` | Self-contained reviewer interface. |\n| `checks.csv` | Executed One-Day-Pricing checks. |\n| `briefs.json` | Deterministic or optional model-generated draft commentary. |\n| `model-previews.json` | No-network request metadata when model preview is selected. |\n| `evaluation.csv` | Synthetic market-model evaluation against the median baseline. |\n| `market-model.json` | Synthetic-model coefficients, split counts, and simulation label. |\n| `receipt.json` | Published output hashes and binding input metadata; written last. |\n'

def _write_candidate_csv(stage: str, name: str, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> Path:
    path = CANDIDATE / stage / name
    write_csv(path, rows, fields)
    return path

def _archive_active() -> None:
    existing = [HERE / name for name in ACTIVE_DIRS if (HERE / name).exists()]
    if not existing:
        return
    archive = HERE / 'archive'
    archive.mkdir(exist_ok=True)
    (archive / 'README.md').write_text('# Recovery archive\n\n| File | Content |\n|---|---|\n| `previous.zip` | Previous successful active pricing bundle, replaced on the next successful build. |\n', encoding='utf-8', newline='\n')
    target = archive / 'previous.zip'
    temp = target.with_name(target.name + '.part')
    with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for directory in existing:
            for path in sorted(directory.rglob('*')):
                if path.is_file():
                    zipped.write(path, path.relative_to(HERE).as_posix())
    temp.replace(target)

def _publish(receipt: Mapping[str, Any]) -> None:
    _archive_active()
    for dirname in ACTIVE_DIRS:
        active = HERE / dirname
        if active.exists():
            shutil.rmtree(active)
        shutil.move(str(CANDIDATE / dirname), str(active))
    if CANDIDATE.exists():
        shutil.rmtree(CANDIDATE)
    write_json(HERE / '03-report' / 'receipt.json', receipt)
    if FAILURE.exists():
        FAILURE.unlink()

def _output_hashes(root: Path) -> list[dict[str, Any]]:
    rows = []
    for dirname in ACTIVE_DIRS:
        stage = root / dirname
        if not stage.is_dir():
            continue
        for path in sorted(stage.rglob('*')):
            if path.is_file() and path.name != 'receipt.json':
                rows.append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha256_file(path)})
    return rows

def _market_bundle(parent: Path, policy: Mapping[str, Any], enabled: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[Path]]:
    if not enabled:
        return ([], [], [], {'status': 'DISABLED', 'simulation_only': True}, [])
    trades = market.generate_trades(parent, policy)
    comparisons, evaluations, metadata = market.evaluate(trades, policy)
    metadata = {'status': 'PASS', **metadata}
    paths = [parent / 'data' / 'synthetic' / 'clean' / 'fund_master.csv', parent / 'data' / 'synthetic' / 'clean' / 'fund_periods.csv']
    return (trades, comparisons, evaluations, metadata, paths)

def _market_checks(evaluations: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any], enabled: bool) -> list[dict[str, str]]:
    if not enabled:
        return [{'check_id': 'M01_MARKET_EXPERIMENT', 'status': 'SKIP', 'actual': 'disabled', 'expected': 'optional', 'source': 'market.py', 'reason': ''}]
    rows = []
    ok = int(metadata.get('train_count', 0)) > 0 and all((row.get('status') == 'PASS' and int(row.get('count', 0)) > 0 for row in evaluations))
    rows.append({'check_id': 'M01_MARKET_SPLITS', 'status': 'PASS' if ok else 'FAIL', 'actual': f'train={metadata.get('train_count', 0)};tests={sum((int(r.get('count', 0)) for r in evaluations))}', 'expected': 'nonempty separated train and test populations', 'source': 'market.evaluate', 'reason': 'simulation only'})
    baseline = {row['split']: row.get('model_beats_baseline') for row in evaluations if row.get('status') == 'PASS'}
    rows.append({'check_id': 'M02_MARKET_BASELINE', 'status': 'PASS' if baseline and all((v == 'TRUE' for v in baseline.values())) else 'FAIL', 'actual': json.dumps(baseline, sort_keys=True), 'expected': 'ridge beats median on each declared synthetic holdout', 'source': '03-report/evaluation.csv', 'reason': 'failure does not imply core pricing failure; it blocks the P7 model claim'})
    return rows

def build(parent: Path, population: str, *, llm_mode: str, provider: str, model: str, authorize_live_model: bool, run_market: bool) -> dict[str, Any]:
    started = utc_now()
    timer = time.perf_counter()
    parent = parent.resolve()
    policy = read_json(HERE / 'policy.json')
    _ensure_clean_candidate()
    try:
        context = inputs.build_context(parent, population, policy)
        positions = simulate.generate_positions(context, policy)
        events = simulate.generate_interim_events(positions, policy)
        assumptions = simulate.assumption_rows(policy)
        evidence = simulate.evidence_packet(context, positions, events, policy)
        if population == 'observed':
            results = []
            cashflows = []
            steps = []
            sensitivities = []
            exceptions = []
            portfolios = []
        else:
            results, cashflows, steps, sensitivities, exceptions = pricing.price_positions(positions, events, policy)
            portfolios = pricing.portfolio_results(results, cashflows, policy)
        numerical_hash_before_ai = hash_json({'results': results, 'cashflows': cashflows, 'steps': steps, 'sensitivities': sensitivities, 'portfolios': portfolios})
        trades, comparisons, evaluations, market_metadata, market_paths = _market_bundle(parent, policy, run_market)
        briefs, previews = briefing.generate_briefs(positions, results, policy, mode=llm_mode, provider=provider, model_override=model, live_authorized=authorize_live_model)
        numerical_hash_after_ai = hash_json({'results': results, 'cashflows': cashflows, 'steps': steps, 'sensitivities': sensitivities, 'portfolios': portfolios})
        checks = qc.run_checks(positions, events, results, cashflows, steps, portfolios, sensitivities, policy, population=population)
        checks.extend(_market_checks(evaluations, market_metadata, run_market))
        checks.append({'check_id': 'T12_MODEL_NUMERIC_ISOLATION', 'status': 'PASS' if numerical_hash_before_ai == numerical_hash_after_ai else 'FAIL', 'actual': numerical_hash_after_ai, 'expected': numerical_hash_before_ai, 'source': 'briefing.generate_briefs', 'reason': 'provider text cannot mutate numerical objects'})
        blocking = [row for row in checks if row['status'] == 'FAIL']
        if blocking:
            raise DataError('blocking One-Day-Pricing checks failed: ' + ','.join((row['check_id'] for row in blocking)))
        input_records = list(context['input_fingerprints'])
        if market_paths:
            existing = {row['path'] for row in input_records}
            for row in fingerprint(market_paths, parent):
                if row['path'] not in existing:
                    input_records.append(row)
                    existing.add(row['path'])
        local_code = fingerprint(_local_code_files(), parent)
        manifest = {'status': 'BOUND', 'population': population, 'policy_version': policy['version'], 'policy_hash': sha256_file(HERE / 'policy.json'), 'parent_root': str(parent), 'parent_state': context['parent_state'], 'input_fingerprints': sorted(input_records, key=lambda x: x['path']), 'local_code_fingerprints': local_code, 'gp_scoring_runtime_dependency': False, 'selection': {'candidate_count': context['metadata'].get('candidate_count', 0), 'selected_count': len(context['selected']), 'priced_position_count': len(positions), 'quality_state': context['metadata'].get('quality_state', {})}, 'market': {'enabled': run_market, 'simulation_only': True, 'metadata': market_metadata}, 'llm': {'mode': llm_mode, 'provider': provider if llm_mode != 'off' else 'off', 'model_override': model, 'live_authorized': authorize_live_model}}
        manifest['data_id'] = hash_json({'population': population, 'policy_hash': manifest['policy_hash'], 'inputs': manifest['input_fingerprints'], 'code': manifest['local_code_fingerprints']})[:16]
        evidence['manifest_data_id'] = manifest['data_id']
        for dirname in ACTIVE_DIRS:
            (CANDIDATE / dirname / 'README.md').write_text(_guide(dirname), encoding='utf-8', newline='\n')
        _write_candidate_csv('01-inputs', 'positions.csv', positions, POSITION_FIELDS)
        _write_candidate_csv('01-inputs', 'interim-events.csv', events, EVENT_FIELDS)
        _write_candidate_csv('01-inputs', 'assumptions.csv', assumptions, ASSUMPTION_FIELDS)
        _write_candidate_csv('01-inputs', 'trades.csv', trades, list(trades[0].keys()) if trades else ['trade_id'])
        write_json(CANDIDATE / '01-inputs' / 'evidence.json', evidence)
        write_json(CANDIDATE / '01-inputs' / 'manifest.json', manifest)
        _write_candidate_csv('02-pricing', 'positions.csv', results, PRICE_FIELDS)
        _write_candidate_csv('02-pricing', 'cashflows.csv', cashflows, CASHFLOW_FIELDS)
        _write_candidate_csv('02-pricing', 'forecast-steps.csv', steps, STEP_FIELDS)
        _write_candidate_csv('02-pricing', 'sensitivities.csv', sensitivities, SENSITIVITY_FIELDS)
        _write_candidate_csv('02-pricing', 'portfolios.csv', portfolios, PORTFOLIO_FIELDS)
        decisions = [{'position_id': r['position_id'], 'display_name': r['display_name'], 'scenario_id': r['scenario_id'], 'status': r['status'], 'reason': r['status_reason'], 'ask_nav_fraction': r['ask_nav_fraction'], 'max_nav_fraction': r['max_nav_fraction'], 'consent_status': r['consent_status'], 'source_record_ids': r['source_record_ids']} for r in results]
        if population == 'observed':
            decisions = [{'position_id': r['fund_period_id'], 'display_name': r['display_name'], 'scenario_id': '', 'status': 'EVIDENCE_ONLY', 'reason': 'NO_SYNTHETIC_PRICE_IN_OBSERVED_MODE', 'ask_nav_fraction': '', 'max_nav_fraction': '', 'consent_status': '', 'source_record_ids': r['fund_period_id']} for r in context['selected']]
        _write_candidate_csv('02-pricing', 'decisions.csv', decisions, DECISION_FIELDS)
        _write_candidate_csv('02-pricing', 'exceptions.csv', exceptions, EXCEPTION_FIELDS)
        _write_candidate_csv('02-pricing', 'market-comparison.csv', comparisons, list(comparisons[0].keys()) if comparisons else ['trade_id'])
        _write_candidate_csv('03-report', 'checks.csv', checks, CHECK_FIELDS)
        _write_candidate_csv('03-report', 'evaluation.csv', evaluations, list(evaluations[0].keys()) if evaluations else ['split'])
        write_json(CANDIDATE / '03-report' / 'market-model.json', market_metadata)
        write_json(CANDIDATE / '03-report' / 'briefs.json', briefs)
        write_json(CANDIDATE / '03-report' / 'model-previews.json', previews)
        dash_meta = {**manifest, 'input_fingerprints': manifest['input_fingerprints']}
        dashboard = report.render_dashboard(dash_meta, positions, results, portfolios, sensitivities, exceptions, checks, evidence, evaluations, briefs)
        (CANDIDATE / '03-report' / 'dashboard.html').write_text(dashboard, encoding='utf-8', newline='\n')
        drift = verify_fingerprints(manifest['input_fingerprints'], parent)
        code_drift = verify_fingerprints(manifest['local_code_fingerprints'], parent)
        if drift or code_drift:
            raise DataError('inputs changed during build: ' + '|'.join(drift + code_drift))
        candidate_hashes = _output_hashes(CANDIDATE)
        finished = utc_now()
        elapsed = time.perf_counter() - timer
        receipt = {'status': 'PASS', 'build_id': hash_json({'manifest': manifest, 'outputs': candidate_hashes})[:16], 'report_id': hashlib.sha256(dashboard.encode('utf-8')).hexdigest()[:16], 'data_id': manifest['data_id'], 'parent_root': str(parent), 'population': population, 'policy_version': policy['version'], 'started_at': started, 'finished_at': finished, 'elapsed_seconds': round(elapsed, 6), 'input_fingerprints': manifest['input_fingerprints'], 'local_code_fingerprints': manifest['local_code_fingerprints'], 'output_hashes': candidate_hashes, 'counts': {'selected_parent_records': len(context['selected']), 'positions': len(positions), 'interim_events': len(events), 'pricing_results': len(results), 'future_cashflows': len(cashflows), 'forecast_steps': len(steps), 'portfolio_results': len(portfolios), 'synthetic_trades': len(trades), 'market_test_predictions': len(comparisons), 'briefs': len(briefs), 'checks': len(checks)}, 'checks': {'passed': sum((row['status'] == 'PASS' for row in checks)), 'skipped': sum((row['status'] == 'SKIP' for row in checks)), 'failed': sum((row['status'] == 'FAIL' for row in checks))}, 'boundaries': ['Synthetic positions and comparable trades are demonstrations.', 'Buyer ceilings are return-based outputs, not observed market-clearing prices.', 'No runtime dependency on GP-Scoring.', 'No real-market predictive-accuracy claim.', 'No parent data were written by this command.']}
        _publish(receipt)
        return receipt
    except Exception as exc:
        failure = {'status': 'FAIL', 'failed_at': utc_now(), 'population': population, 'reason': str(exc)}
        write_json(FAILURE, failure)
        if CANDIDATE.exists():
            shutil.rmtree(CANDIDATE)
        raise

def check_only(parent: Path | None=None) -> list[str]:
    receipt_path = HERE / '03-report' / 'receipt.json'
    if not receipt_path.is_file():
        return ['missing 03-report/receipt.json']
    receipt = read_json(receipt_path)
    errors = []
    parent = Path(parent or receipt.get('parent_root') or HERE.parent).resolve()
    errors.extend(verify_fingerprints(receipt.get('input_fingerprints', []), parent))
    errors.extend(verify_fingerprints(receipt.get('local_code_fingerprints', []), parent))
    for row in receipt.get('output_hashes', []):
        path = HERE / row['path']
        if not path.is_file():
            errors.append(f'missing output: {row['path']}')
            continue
        if path.stat().st_size != int(row['bytes']):
            errors.append(f'output size changed: {row['path']}')
            continue
        if sha256_file(path) != row['sha256']:
            errors.append(f'output hash changed: {row['path']}')
    if receipt.get('status') != 'PASS':
        errors.append('receipt status is not PASS')
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, default=HERE.parent)
    parser.add_argument('--population', choices=['integrated_demo', 'fixture', 'observed'], default='integrated_demo')
    parser.add_argument('--llm', choices=['off', 'preview', 'live'], default='off')
    parser.add_argument('--provider', choices=['openrouter', 'anthropic'], default='openrouter')
    parser.add_argument('--model', default='')
    parser.add_argument('--authorize-live-model', action='store_true')
    parser.add_argument('--skip-market', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if args.check_only:
        errors = check_only(args.parent)
        if errors:
            for error in errors:
                print('FAIL:', error)
            return 1
        receipt = read_json(HERE / '03-report' / 'receipt.json')
        print(f'PASS: One-Day-Pricing {receipt['build_id']} ({receipt['population']})')
        return 0
    if args.llm == 'live' and (not args.authorize_live_model):
        print('FAIL: --llm live requires --authorize-live-model')
        return 2
    try:
        receipt = build(args.parent, args.population, llm_mode=args.llm, provider=args.provider, model=args.model, authorize_live_model=args.authorize_live_model, run_market=not args.skip_market)
    except Exception as exc:
        print('FAIL:', exc)
        return 1
    print(f'PASS: One-Day-Pricing build {receipt['build_id']} | population={receipt['population']} | checks={receipt['checks']['passed']} pass/{receipt['checks']['failed']} fail | {receipt['elapsed_seconds']:.3f}s')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
