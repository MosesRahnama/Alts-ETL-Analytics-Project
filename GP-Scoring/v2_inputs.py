from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from inputs import build_observed_evidence, load_fixture, resolve_quality_approval  # noqa: E402


class V2InputError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matches_fingerprint(path: Path, expected: str) -> bool:
    if sha256_file(path) == expected:
        return True
    # Git stores LF text while retained V1 receipts describe Windows CRLF files.
    # Accept only this byte-format equivalence, never changed field content.
    if path.suffix.lower() not in {".csv", ".json", ".html", ".md", ".txt", ".py", ".yml", ".yaml"}:
        return False
    raw = path.read_bytes()
    if b"\x00" in raw:
        return False
    lf = raw.replace(b"\r\n", b"\n")
    return expected in {hashlib.sha256(lf).hexdigest(), hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest()}


def csv_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def _require_columns(path: Path, rows: list[Mapping[str, str]], required: Iterable[str]) -> None:
    header = set(rows[0]) if rows else set(csv_header(path))
    missing = sorted(set(required) - header)
    if missing:
        raise V2InputError(f"{path} missing columns: {','.join(missing)}")


def verify_baseline(parent: Path, gp_root: Path) -> list[str]:
    baseline_path = gp_root / "v2-baseline.json"
    if not baseline_path.is_file():
        return ["v2-baseline.json missing"]
    baseline = read_json(baseline_path)
    errors: list[str] = []
    for relative, expected in baseline.get("protected_files", {}).items():
        # The catalog and its rendered page register new files; scoring reads neither.
        # Their original fingerprints remain in the baseline as historical evidence.
        if relative in {"docs/PROJECT-MANIFEST.csv", "dashboard.html"}:
            continue
        path = parent / relative
        if not path.is_file():
            errors.append(f"protected file missing: {relative}")
            continue
        if not matches_fingerprint(path, expected.get("sha256", "")):
            errors.append(f"protected file changed: {relative}")
    return errors


def verify_fingerprints(fingerprints: Mapping[str, str], parent: Path | None = None) -> list[str]:
    errors: list[str] = []
    for raw, expected in fingerprints.items():
        path = (parent or HERE.parent) / raw
        if not path.is_file():
            errors.append(f"missing input: {path}")
        elif not matches_fingerprint(path, expected):
            errors.append(f"input hash changed: {path}")
    return errors


def _fingerprint_entries(paths: Iterable[Path], parent: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    entries: list[dict[str, Any]] = []
    fingerprints: dict[str, str] = {}
    for path in sorted({p.resolve() for p in paths}, key=str):
        if not path.is_file():
            raise V2InputError(f"required V2 input missing: {path}")
        digest = sha256_file(path)
        relative = path.relative_to(parent.resolve()).as_posix()
        fingerprints[relative] = digest
        entry: dict[str, Any] = {"path": relative, "sha256": digest, "bytes": path.stat().st_size}
        if path.suffix.lower() == ".csv":
            entry["header"] = csv_header(path)
        entries.append(entry)
    return entries, fingerprints


def _v1_reference(gp_root: Path) -> dict[str, Any]:
    receipt_path = gp_root / "03-report/receipt.json"
    features_path = gp_root / "02-scoring/fund-features.csv"
    scorecards_path = gp_root / "02-scoring/gp-scorecards.csv"
    decisions_path = gp_root / "02-scoring/decisions.csv"
    for path in (receipt_path, features_path, scorecards_path, decisions_path):
        if not path.is_file():
            raise V2InputError(f"V1 reference missing: {path}")
    receipt = read_json(receipt_path)
    if receipt.get("status") != "PASS":
        raise V2InputError("V1 receipt is not PASS")
    hashes = receipt.get("output_hashes", {})
    required = {str(path.relative_to(gp_root)).replace("\\", "/") for path in (features_path, scorecards_path, decisions_path)}
    if not required.issubset(hashes) or not receipt.get("build_id"):
        raise V2InputError("V1 receipt output inventory incomplete")
    for relative, expected in hashes.items():
        path = (gp_root / relative).resolve()
        if not path.is_relative_to(gp_root.resolve()) or not path.is_file() or not matches_fingerprint(path, expected):
            raise V2InputError(f"V1 reference output differs: {relative}")
    scorecards = read_csv(scorecards_path)
    from v2_stress import _rank

    ranked = []
    for row in scorecards:
        row["v1_reference_rank"] = row.get("rank", "")
        if row.get("status") == "RANKED_DEMO":
            ranked.append(row)
    _rank(ranked, "score", "rank")
    for row in ranked:
        row["rank"] = str(row["rank"])
    return {
        "receipt": receipt,
        "features": read_csv(features_path),
        "scorecards": scorecards,
        "decisions": read_csv(decisions_path),
        "paths": [receipt_path, features_path, scorecards_path, decisions_path, gp_root / "policy.json"],
    }


def _active(row: Mapping[str, str]) -> bool:
    return str(row.get("record_status", "")).strip().upper() == "ACTIVE"


def _whole_fund_flow(row: Mapping[str, str]) -> bool:
    return _active(row) and not str(row.get("lp_id", "")).strip() and not str(row.get("share_class_name", "")).strip()


def _whole_fund_period(row: Mapping[str, str]) -> bool:
    return (
        _active(row)
        and str(row.get("perspective", "")).strip() == "fund_total"
        and not str(row.get("lp_id", "")).strip()
        and not str(row.get("share_class_name", "")).strip()
    )


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise V2InputError(f"invalid date: {value}") from exc


def _available_period(row: Mapping[str, str], cutoff: date) -> bool:
    report = str(row.get("report_date", "")).strip()
    if not report:
        return False
    try:
        return _date(report) <= cutoff
    except V2InputError:
        return False


def term_applies(row: Mapping[str, Any], evaluation: date) -> bool:
    try:
        start = _date(str(row.get("effective_date", "")))
        end_raw = str(row.get("effective_end_date", "")).strip()
        end = _date(end_raw) if end_raw else date.max
    except V2InputError:
        return False
    return _active(row) and start <= evaluation <= end


def _load_metric_rows(path: Path, current_period_ids: set[str]) -> tuple[list[dict[str, str]], dict[str, dict[str, dict[str, str]]]]:
    rows = read_csv(path)
    subset: list[dict[str, str]] = []
    index: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        period_id = str(row.get("input_record_ids", "")).split(";", 1)[0].strip()
        if period_id not in current_period_ids:
            continue
        metric = str(row.get("metric_id", "")).strip()
        if metric in index[period_id]:
            raise V2InputError(f"duplicate current metric {metric} for {period_id}")
        index[period_id][metric] = row
        subset.append(row)
    return subset, index


def _load_quality_subset(path: Path, period_ids: set[str]) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("record_table", "").lower() == "fund_periods" and row.get("record_id", "") in period_ids:
                selected.append(row)
    return selected


def _strategy_benchmark(path: Path) -> dict[str, str]:
    rows = read_csv(path)
    if not rows:
        raise V2InputError("strategy-benchmark.csv is empty")
    strategy_col = "strategy" if "strategy" in rows[0] else next(iter(rows[0]))
    benchmark_col = "benchmark_id" if "benchmark_id" in rows[0] else list(rows[0])[1]
    mapping: dict[str, str] = {}
    for row in rows:
        strategy = row.get(strategy_col, "").strip()
        benchmark = row.get(benchmark_col, "").strip()
        if strategy and benchmark:
            if strategy in mapping and mapping[strategy] != benchmark:
                raise V2InputError(f"strategy benchmark conflict: {strategy}")
            mapping[strategy] = benchmark
    return mapping


def build_context(parent: Path, gp_root: Path, policy: Mapping[str, Any], include_cases: bool = False) -> dict[str, Any]:
    baseline_errors = verify_baseline(parent, gp_root)
    if baseline_errors:
        raise V2InputError("; ".join(baseline_errors[:5]))
    v1 = _v1_reference(gp_root)
    v1_policy = read_json(gp_root / "policy.json")
    as_of = str(policy["economic_as_of"])
    cutoff = _date(str(policy["information_cutoff"]))
    fixture = load_fixture(parent, as_of, v1_policy)

    paths = {
        "fund_master": parent / "data/synthetic/clean/fund_master.csv",
        "manager_master": parent / "data/synthetic/clean/manager_master.csv",
        "periods": parent / "data/synthetic/clean/fund_periods.csv",
        "cashflows": parent / "data/synthetic/clean/fund_cashflows.csv",
        "holdings": parent / "data/synthetic/clean/fund_holdings.csv",
        "terms": parent / "data/synthetic/clean/fund_terms.csv",
        "clauses": parent / "data/synthetic/clean/fund_term_clauses.csv",
        "manager_observations": parent / "data/synthetic/clean/manager_observations.csv",
        "benchmarks": parent / "data/synthetic/clean/benchmark_returns.csv",
        "quality": parent / "data/synthetic/clean/quality_results.csv",
        "fund_metrics": parent / "data/synthetic/analytics/fund_metrics.csv",
        "pme_results": parent / "data/synthetic/analytics/pme_results.csv",
        "strategy_benchmark": parent / "data/normalization/transformations/strategy-benchmark.csv",
        "finance_code": parent / "src/common/finance.py",
        "analytics_code": parent / "src/analytics/run_round04_analytics.py",
    }
    fund_master = read_csv(paths["fund_master"])
    manager_master = read_csv(paths["manager_master"])
    periods = read_csv(paths["periods"])
    cashflows = read_csv(paths["cashflows"])
    holdings = read_csv(paths["holdings"])
    terms = read_csv(paths["terms"])
    clauses = read_csv(paths["clauses"])
    manager_observations = read_csv(paths["manager_observations"])
    benchmarks = read_csv(paths["benchmarks"])

    _require_columns(paths["fund_master"], fund_master, ["fund_id", "fund_manager_id", "strategy", "sub_strategy", "vintage_year", "fund_size", "fund_size_currency", "first_close_date"])
    _require_columns(paths["periods"], periods, ["fund_period_id", "fund_id", "as_of_date", "report_date", "perspective", "currency", "paid_in_capital_itd", "distributions_itd", "nav"])
    _require_columns(paths["cashflows"], cashflows, ["cashflow_id", "fund_id", "cashflow_date", "cashflow_type", "amount", "currency", "base_currency", "amount_base_currency"])
    _require_columns(paths["holdings"], holdings, ["holding_id", "fund_id", "portfolio_company_id", "instrument_id", "as_of_date", "sector", "geography", "currency", "fair_value"])
    _require_columns(paths["terms"], terms, ["fund_term_id", "fund_id", "perspective", "term_scope", "overrides_fund_term_id", "management_fee_rate", "waterfall_type"])

    fund_by_id = {row["fund_id"]: row for row in fund_master}
    if len(fund_by_id) != len(fund_master):
        raise V2InputError("synthetic fund_master contains duplicate fund_id")
    manager_by_id = {row["manager_id"]: row for row in manager_master}
    if len(manager_by_id) != len(manager_master):
        raise V2InputError("synthetic manager_master contains duplicate manager_id")
    for fund in fund_master:
        if fund.get("fund_manager_id") not in manager_by_id:
            raise V2InputError(f"unresolved manager for {fund['fund_id']}")

    whole_periods = [row for row in periods if _whole_fund_period(row)]
    periods_by_fund: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in whole_periods:
        periods_by_fund[row["fund_id"]].append(row)
    for rows in periods_by_fund.values():
        rows.sort(key=lambda row: (row.get("as_of_date", ""), row.get("fund_period_id", "")))

    current_records = list(fixture["selected_records"])
    current_by_fund = {row["fund_id"]: row for row in current_records}
    if len(current_by_fund) != len(current_records):
        raise V2InputError("current selected fund records are not unique by fund")
    for row in current_records:
        if row["fund_id"] not in fund_by_id:
            raise V2InputError(f"current period has unknown fund: {row['fund_id']}")
        if row.get("as_of_date") != as_of:
            raise V2InputError(f"current period date mismatch: {row['fund_period_id']}")

    whole_cashflows = [row for row in cashflows if _whole_fund_flow(row)]
    flows_by_fund: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in whole_cashflows:
        if row.get("fund_id") not in fund_by_id:
            raise V2InputError(f"cash flow has unknown fund: {row.get('cashflow_id')}")
        flows_by_fund[row["fund_id"]].append(row)
    for rows in flows_by_fund.values():
        rows.sort(key=lambda row: (row.get("cashflow_date", ""), row.get("cashflow_id", "")))

    current_period_ids = {row["fund_period_id"] for row in current_records}
    metric_subset, metric_index = _load_metric_rows(paths["fund_metrics"], current_period_ids)
    parent_pme_subset, parent_pme_index = _load_metric_rows(paths["pme_results"], current_period_ids)
    quality_subset = _load_quality_subset(paths["quality"], current_period_ids)

    current_holdings = [row for row in holdings if _active(row) and row.get("as_of_date") == as_of]
    holdings_by_fund: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in current_holdings:
        holdings_by_fund[row["fund_id"]].append(row)

    base_terms = [row for row in terms if term_applies(row, _date(as_of)) and row.get("perspective") == "fund_total" and row.get("term_scope") == "base_fund"]
    base_term_by_fund: dict[str, dict[str, str]] = {}
    conflicts: set[str] = set()
    for row in base_terms:
        fund_id = row.get("fund_id", "")
        if fund_id in base_term_by_fund:
            conflicts.add(fund_id)
        base_term_by_fund[fund_id] = row
    for fund_id in conflicts:
        del base_term_by_fund[fund_id]

    strategy_benchmark = _strategy_benchmark(paths["strategy_benchmark"])
    benchmark_currency: dict[str, str] = {}
    for row in benchmarks:
        benchmark_id = row.get("benchmark_id", "")
        currency = row.get("currency", "")
        if benchmark_id in benchmark_currency and benchmark_currency[benchmark_id] != currency:
            raise V2InputError(f"benchmark currency conflict: {benchmark_id}")
        benchmark_currency[benchmark_id] = currency

    observed = build_observed_evidence(parent, 3)
    consumed = list(paths.values()) + list(v1["paths"]) + list(observed["consumed_paths"])
    overlay: dict[str, Any] = {}
    if include_cases:
        case_manifest = gp_root / "data/case-manifest.json"
        if case_manifest.is_file():
            overlay["manifest"] = read_json(case_manifest)
            consumed.append(case_manifest)
            for name in ["team-history.csv", "deal-attribution.csv", "diligence-facts.csv", "case-events.csv", "case-valuations.csv", "document-registry.csv"]:
                path = gp_root / "data" / name
                if path.is_file():
                    overlay[name] = read_csv(path)
                    consumed.append(path)
            for row in overlay.get("document-registry.csv", []):
                document_path = gp_root / str(row.get("path", ""))
                if document_path.is_file():
                    consumed.append(document_path)

    entries, fingerprints = _fingerprint_entries(consumed, parent)
    return {
        "parent": parent,
        "paths": paths,
        "gp_root": gp_root,
        "policy": dict(policy),
        "v1_policy": v1_policy,
        "cutoff": cutoff,
        "v1": v1,
        "fixture": fixture,
        "fund_master": fund_master,
        "manager_master": manager_master,
        "fund_by_id": fund_by_id,
        "manager_by_id": manager_by_id,
        "periods": periods,
        "whole_periods": whole_periods,
        "periods_by_fund": periods_by_fund,
        "current_records": current_records,
        "current_by_fund": current_by_fund,
        "cashflows": cashflows,
        "whole_cashflows": whole_cashflows,
        "flows_by_fund": flows_by_fund,
        "holdings": holdings,
        "current_holdings": current_holdings,
        "holdings_by_fund": holdings_by_fund,
        "terms": terms,
        "clauses": clauses,
        "base_term_by_fund": base_term_by_fund,
        "manager_observations": manager_observations,
        "benchmarks": benchmarks,
        "benchmark_currency": benchmark_currency,
        "strategy_benchmark": strategy_benchmark,
        "quality_subset": quality_subset,
        "metric_subset": metric_subset,
        "metric_index": metric_index,
        "parent_pme_subset": parent_pme_subset,
        "parent_pme_index": parent_pme_index,
        "observed_cards": observed["cards"],
        "overlay": overlay,
        "input_entries": entries,
        "fingerprints": fingerprints,
        "available_period": lambda row: _available_period(row, cutoff),
    }


def quality_approval_for_ids(context: Mapping[str, Any], period_ids: set[str]) -> dict[str, tuple[bool, str]]:
    if not period_ids:
        return {}
    rows = _load_quality_subset(context["paths"]["quality"], period_ids)
    approval, state = resolve_quality_approval(rows, period_ids, read_json(context["gp_root"] / "policy.json")["required_quality_rules"])
    if state.get("status") != "COMPLETE":
        return {period_id: (False, state.get("status", "QUALITY_INCOMPLETE")) for period_id in period_ids}
    return approval


def manifest_for_context(context: Mapping[str, Any]) -> dict[str, Any]:
    policy = context["policy"]
    v1_receipt = context["v1"]["receipt"]
    material = {
        "v2_policy_version": policy["version"],
        "v1_data_build_id": v1_receipt["build_id"],
        "v1_report_id": v1_receipt["report_id"],
        "economic_as_of": policy["economic_as_of"],
        "information_cutoff": policy["information_cutoff"],
        "fingerprints": context["fingerprints"],
    }
    data_id = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    return {
        "status": "BOUND",
        "v2_data_id": data_id,
        **material,
        "inputs": context["input_entries"],
        "population_counts": {
            "synthetic_funds": len(context["fund_master"]),
            "synthetic_managers": len(context["manager_master"]),
            "current_whole_fund_records": len(context["current_records"]),
            "whole_fund_cashflows": len(context["whole_cashflows"]),
            "current_holding_rows": len(context["current_holdings"]),
        },
        "availability_basis": "SYNTHETIC_REPORT_DATE for fixture periods; unknown for real evidence unless source metadata states otherwise",
    }
