from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from scoring import ScoringError, compute_multiples


class InputError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def csv_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _split_ids(value: str, separator: str = "|") -> list[str]:
    return [part.strip() for part in _text(value).split(separator) if part.strip()]


def _metric_period_id(row: Mapping[str, str]) -> str:
    return _text(row.get("input_record_ids")).split(";", 1)[0].strip()


def git_state(parent: Path) -> dict[str, Any]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=parent, text=True, stderr=subprocess.DEVNULL
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=parent, text=True, stderr=subprocess.DEVNULL
        ).splitlines()
        return {"commit": commit, "dirty": bool(status), "status_lines": status}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": "UNKNOWN", "dirty": True, "status_lines": ["git state unavailable"]}


def fingerprint_paths(paths: Iterable[Path]) -> dict[str, str]:
    return {str(path.resolve()): sha256_file(path) for path in paths}


def verify_fingerprints(fingerprints: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    for raw_path, expected in fingerprints.items():
        path = Path(raw_path)
        if not path.is_file():
            errors.append(f"missing input: {path}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            errors.append(f"input hash changed: {path}")
    return errors


def _load_selected_quality_rows(path: Path, selected_ids: set[str]) -> tuple[list[dict[str, str]], int]:
    rows: list[dict[str, str]] = []
    total = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            total += 1
            if row.get("record_table", "").lower() == "fund_periods" and row.get("record_id", "") in selected_ids:
                rows.append(row)
    return rows, total


def resolve_quality_approval(
    rows: list[Mapping[str, str]], selected_ids: set[str], required_rules: Iterable[str]
) -> tuple[dict[str, tuple[bool, str]], dict[str, str]]:
    required = set(required_rules)
    if not selected_ids:
        return {}, {"run_id": "", "checked_at": "", "status": "NO_SELECTED_PERIODS"}
    by_run: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        run_id = _text(row.get("run_id"))
        checked_at = _text(row.get("checked_at"))
        if run_id and checked_at:
            by_run[(run_id, checked_at)].append(row)
    if not by_run:
        return {record_id: (False, "QUALITY_RUN_MISSING") for record_id in selected_ids}, {
            "run_id": "",
            "checked_at": "",
            "status": "MISSING",
        }
    latest_checked_at = max(checked_at for _, checked_at in by_run)
    latest = [(key, value) for key, value in by_run.items() if key[1] == latest_checked_at]
    complete: list[tuple[tuple[str, str], list[Mapping[str, str]]]] = []
    for key, run_rows in latest:
        rule_map: dict[str, set[str]] = defaultdict(set)
        for row in run_rows:
            if row.get("record_id", "") in selected_ids:
                rule_map[row["record_id"]].add(row.get("rule_id", ""))
        if all(required.issubset(rule_map.get(record_id, set())) for record_id in selected_ids):
            complete.append((key, run_rows))
    if len(complete) != 1:
        reason = "LATEST_QUALITY_RUN_INCOMPLETE" if not complete else "LATEST_QUALITY_RUN_AMBIGUOUS"
        return {record_id: (False, reason) for record_id in selected_ids}, {
            "run_id": "",
            "checked_at": latest_checked_at,
            "status": reason,
        }
    (run_id, checked_at), run_rows = complete[0]
    by_record: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in run_rows:
        if row.get("record_id", "") in selected_ids:
            by_record[row["record_id"]].append(row)
    result: dict[str, tuple[bool, str]] = {}
    for record_id in selected_ids:
        record_rows = by_record[record_id]
        invalid_status = [row for row in record_rows if _text(row.get("status")).upper() not in {"PASS", "FAIL", "SKIP"}]
        if invalid_status:
            result[record_id] = (False, "QUALITY_STATUS_INVALID")
            continue
        blocking = [
            row
            for row in record_rows
            if _text(row.get("severity")).lower() == "error" and _text(row.get("status")).upper() == "FAIL"
        ]
        if blocking:
            result[record_id] = (False, "QUALITY_ERROR_FAIL:" + ",".join(sorted({row["rule_id"] for row in blocking})))
        else:
            result[record_id] = (True, f"QUALITY_APPROVED:{run_id}")
    return result, {"run_id": run_id, "checked_at": checked_at, "status": "COMPLETE"}


def _load_metric_subset(path: Path, period_ids: set[str]) -> tuple[dict[str, dict[str, str]], int]:
    metrics: dict[str, dict[str, str]] = defaultdict(dict)
    total = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            total += 1
            period_id = _metric_period_id(row)
            if period_id in period_ids and row.get("metric_id") in {"dpi", "rvpi", "tvpi"}:
                metrics[period_id][row["metric_id"]] = row.get("value_numeric", "")
    return metrics, total


def load_fixture(parent: Path, as_of_date: str, policy: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "fund_master": parent / "data/synthetic/clean/fund_master.csv",
        "manager_master": parent / "data/synthetic/clean/manager_master.csv",
        "fund_periods": parent / "data/synthetic/clean/fund_periods.csv",
        "quality_results": parent / "data/synthetic/clean/quality_results.csv",
        "fund_metrics": parent / "data/synthetic/analytics/fund_metrics.csv",
    }
    for path in paths.values():
        if not path.is_file():
            raise InputError(f"required fixture input is missing: {path}")
    fund_master = read_csv(paths["fund_master"])
    manager_master = read_csv(paths["manager_master"])
    period_rows = read_csv(paths["fund_periods"])
    manager_ids = {row["manager_id"] for row in manager_master}
    master_by_fund = {row["fund_id"]: row for row in fund_master}
    if len(master_by_fund) != len(fund_master):
        raise InputError("fixture fund_master contains duplicate fund_id values")

    candidate_by_fund: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in period_rows:
        if (
            row.get("record_status", "").upper() == "ACTIVE"
            and row.get("perspective", "") == "fund_total"
            and row.get("as_of_date", "") == as_of_date
            and not row.get("lp_id", "")
            and not row.get("share_class_name", "")
        ):
            candidate_by_fund[row["fund_id"]].append(row)

    provisional: list[dict[str, Any]] = []
    preliminary_decisions: dict[str, dict[str, Any]] = {}
    for fund in fund_master:
        fund_id = fund["fund_id"]
        candidates = candidate_by_fund.get(fund_id, [])
        reasons: list[str] = []
        selected: dict[str, str] | None = None
        if not candidates:
            reasons.append("STALE_OR_NO_COMMON_DATE")
        elif len(candidates) > 1:
            serialized = {json.dumps(row, sort_keys=True) for row in candidates}
            if len(serialized) == 1:
                selected = candidates[0]
            else:
                reasons.append("CONFLICTING_FUND_PERIOD_DUPLICATES")
        else:
            selected = candidates[0]
        manager_id = fund.get("fund_manager_id", "")
        if not manager_id:
            reasons.append("MANAGER_MISSING")
        elif manager_id not in manager_ids:
            reasons.append("MANAGER_UNRESOLVED")
        if selected is not None:
            if selected.get("fund_id") != fund_id:
                reasons.append("FUND_PERIOD_IDENTITY_MISMATCH")
            if selected.get("strategy") != fund.get("strategy"):
                reasons.append("STRATEGY_MISMATCH")
            provisional.append(
                {
                    **selected,
                    "population": "fixture",
                    "manager_id": manager_id,
                    "manager_name": fund.get("fund_manager_name", ""),
                    "strategy": fund.get("strategy", ""),
                    "vintage_year": fund.get("vintage_year", ""),
                    "measurement_basis": "synthetic_basis_unspecified",
                    "evidence_id": f"SYNTH:{fund_id}:{selected.get('fund_period_id', '')}",
                    "input_reasons": reasons,
                }
            )
        preliminary_decisions[fund_id] = {"reasons": reasons, "has_current_period": selected is not None}

    selected_ids = {row["fund_period_id"] for row in provisional}
    quality_rows, quality_total = _load_selected_quality_rows(paths["quality_results"], selected_ids)
    approvals, quality_run = resolve_quality_approval(
        quality_rows, selected_ids, policy["required_quality_rules"]
    )
    metric_values, metric_total = _load_metric_subset(paths["fund_metrics"], selected_ids)
    tolerance = float(policy.get("metric_tolerance", 1e-5))
    for row in provisional:
        period_id = row["fund_period_id"]
        approved, reason = approvals.get(period_id, (False, "QUALITY_RESULT_MISSING"))
        row["quality_approved"] = approved
        row["quality_reason"] = reason
        try:
            calculated = compute_multiples(row)
        except ScoringError as exc:
            row["input_reasons"].append(f"FINANCE_INVALID:{exc}")
            continue
        stored = metric_values.get(period_id, {})
        missing = [metric for metric in ("dpi", "rvpi", "tvpi") if metric not in stored]
        if missing:
            row["input_reasons"].append("STORED_METRICS_MISSING:" + ",".join(missing))
            continue
        for metric in ("dpi", "rvpi", "tvpi"):
            try:
                difference = abs(float(stored[metric]) - calculated[metric])
            except ValueError:
                row["input_reasons"].append(f"STORED_METRIC_INVALID:{metric}")
                continue
            if not math.isfinite(difference) or difference > tolerance:
                row["input_reasons"].append(f"STORED_METRIC_MISMATCH:{metric}")

    row_counts = {
        str(paths["fund_master"].resolve()): len(fund_master),
        str(paths["manager_master"].resolve()): len(manager_master),
        str(paths["fund_periods"].resolve()): len(period_rows),
        str(paths["quality_results"].resolve()): quality_total,
        str(paths["fund_metrics"].resolve()): metric_total,
    }
    synthetic_evidence = [
        {
            "evidence_id": row["evidence_id"],
            "fund_id": row["fund_id"],
            "manager_id": row["manager_id"],
            "fund_period_id": row["fund_period_id"],
            "source_class": "SYNTHETIC",
            "parameter_set_id": row.get("synthetic_parameter_set_id", ""),
            "as_of_date": row.get("as_of_date", ""),
        }
        for row in provisional
    ]
    return {
        "fund_master": fund_master,
        "manager_master": manager_master,
        "selected_records": provisional,
        "preliminary_decisions": preliminary_decisions,
        "quality_run": quality_run,
        "synthetic_evidence": synthetic_evidence,
        "consumed_paths": list(paths.values()),
        "row_counts": row_counts,
    }


def _observed_metric_map(metrics: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for row in metrics:
        period_id = _metric_period_id(row)
        if period_id and row.get("metric_id") in {"dpi", "rvpi", "tvpi"}:
            result[period_id][row["metric_id"]] = row.get("value_numeric", "")
    return result


def build_observed_evidence(parent: Path, card_limit: int = 3) -> dict[str, Any]:
    paths = {
        "fund_master": parent / "data/extracted/fund-level/fund_master.csv",
        "manager_master": parent / "data/extracted/fund-level/manager_master.csv",
        "fund_periods": parent / "data/extracted/fund-level/fund_periods.csv",
        "fund_metrics": parent / "data/extracted/fund-level/fund_metrics.csv",
        "quality_results": parent / "data/extracted/fund-level/quality_results.csv",
        "fund_observations": parent / "data/extracted/fund-level/fund_observations.csv",
        "fact_observation": parent / "data/extracted/tables/fact_observation.csv",
        "observation_lineage": parent / "data/extracted/tables/observation_lineage.csv",
    }
    for path in paths.values():
        if not path.is_file():
            raise InputError(f"required observed input is missing: {path}")
    fund_master = read_csv(paths["fund_master"])
    manager_master = read_csv(paths["manager_master"])
    periods = read_csv(paths["fund_periods"])
    metrics = read_csv(paths["fund_metrics"])
    quality = read_csv(paths["quality_results"])
    fund_by_id = {row["fund_id"]: row for row in fund_master}
    manager_by_id = {row["manager_id"]: row for row in manager_master}
    period_by_id = {row["fund_period_id"]: row for row in periods}
    metric_map = _observed_metric_map(metrics)
    quality_by_period: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in quality:
        if row.get("record_table", "").lower() == "fund_periods":
            quality_by_period[row.get("record_id", "")].append(row)

    chosen: list[tuple[str, str]] = []
    supported = [
        period_id
        for period_id in sorted(metric_map)
        if period_id in period_by_id
        and fund_by_id.get(period_by_id[period_id]["fund_id"], {}).get("fund_manager_id", "")
    ]
    if supported:
        chosen.append(("supported_multiple", supported[0]))
    failures = sorted(
        {
            row.get("record_id", "")
            for row in quality
            if row.get("record_table", "").lower() == "fund_periods"
            and row.get("severity", "").lower() == "error"
            and row.get("status", "").upper() == "FAIL"
            and row.get("record_id", "") in period_by_id
        }
    )
    if failures:
        chosen.append(("quality_exception", failures[0]))
    missing_manager = [
        period_id
        for period_id in sorted(metric_map)
        if period_id in period_by_id
        and not fund_by_id.get(period_by_id[period_id]["fund_id"], {}).get("fund_manager_id", "")
    ]
    if missing_manager:
        chosen.append(("missing_manager", missing_manager[0]))
    deduped: list[tuple[str, str]] = []
    seen_periods: set[str] = set()
    for card_type, period_id in chosen:
        if period_id not in seen_periods:
            deduped.append((card_type, period_id))
            seen_periods.add(period_id)
        if len(deduped) >= card_limit:
            break

    observation_ids: set[str] = set()
    for _, period_id in deduped:
        observation_ids.update(_split_ids(period_by_id[period_id].get("input_observation_ids", "")))
    observation_map: dict[str, dict[str, str]] = {}
    with paths["fund_observations"].open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("observation_id", "") in observation_ids:
                observation_map[row["observation_id"]] = row
    fact_map: dict[str, dict[str, str]] = {}
    lineage_map: dict[str, dict[str, str]] = {}
    with paths["fact_observation"].open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("observation_id", "") in observation_ids:
                fact_map[row["observation_id"]] = row
    with paths["observation_lineage"].open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("observation_id", "") in observation_ids:
                lineage_map[row["observation_id"]] = row

    cards: list[dict[str, Any]] = []
    for card_type, period_id in deduped:
        period = period_by_id[period_id]
        fund = fund_by_id.get(period["fund_id"], {})
        manager_id = fund.get("fund_manager_id", "")
        manager = manager_by_id.get(manager_id, {})
        evidence: list[dict[str, str]] = []
        for observation_id in _split_ids(period.get("input_observation_ids", ""))[:10]:
            observation = observation_map.get(observation_id, {})
            fact = fact_map.get(observation_id, {})
            lineage = lineage_map.get(observation_id, {})
            evidence.append(
                {
                    "evidence_id": f"OBS:{observation_id}",
                    "observation_id": observation_id,
                    "metric_id": observation.get("metric_id", fact.get("metric_id", "")),
                    "value": observation.get("value_raw", fact.get("value_raw", "")),
                    "unit": observation.get("unit", fact.get("unit", "")),
                    "document_id": observation.get("file_id", fact.get("document_id", "")),
                    "source_page": observation.get("source_page", fact.get("source_page", "")),
                    "source_anchor": observation.get("source_anchor", ""),
                    "evidence_quote": fact.get("evidence_quote", ""),
                    "adjudication_status": fact.get("adjudication_status", ""),
                    "source_agents": fact.get("source_agents", ""),
                    "source_sha256": lineage.get("source_sha256", ""),
                }
            )
        failed_rules = [
            row.get("rule_id", "")
            for row in quality_by_period.get(period_id, [])
            if row.get("severity", "").lower() == "error" and row.get("status", "").upper() == "FAIL"
        ]
        cards.append(
            {
                "card_type": card_type,
                "status": "EVIDENCE_ONLY",
                "fund_period_id": period_id,
                "fund_id": period.get("fund_id", ""),
                "fund_name": fund.get("fund_name", ""),
                "manager_id": manager_id,
                "manager_name": manager.get("manager_name", fund.get("fund_manager_name", "")),
                "as_of_date": period.get("as_of_date", ""),
                "perspective": period.get("perspective", ""),
                "currency": period.get("currency", ""),
                "vintage_year": period.get("vintage_year", ""),
                "printed_strategy": period.get("strategy", ""),
                "metrics": metric_map.get(period_id, {}),
                "quality_error_failures": failed_rules,
                "evidence": evidence,
                "limitation": (
                    "This is an LP-position source record and does not establish a complete GP track record."
                    if period.get("perspective") == "lp_position"
                    else "This source record is shown for evidence review and is not assigned a GP rank in version 1."
                ),
            }
        )

    row_counts = {
        str(paths["fund_master"].resolve()): len(fund_master),
        str(paths["manager_master"].resolve()): len(manager_master),
        str(paths["fund_periods"].resolve()): len(periods),
        str(paths["fund_metrics"].resolve()): len(metrics),
        str(paths["quality_results"].resolve()): len(quality),
    }
    return {"cards": cards, "consumed_paths": list(paths.values()), "row_counts": row_counts}


def build_manifest(
    parent: Path,
    gp_root: Path,
    population: str,
    as_of_date: str,
    policy: Mapping[str, Any],
    consumed_paths: Iterable[Path],
    row_counts: Mapping[str, int],
) -> dict[str, Any]:
    dependency_paths = [
        gp_root / "policy.json",
        gp_root / "inputs.py",
        gp_root / "scoring.py",
        gp_root / "briefing.py",
        gp_root / "dashboard.py",
        gp_root / "run.py",
        parent / "src/analytics/run_round04_analytics.py",
        parent / "src/quality/run_fund_checks.py",
        parent / "config/quality_rules.yml",
    ]
    all_paths: list[Path] = []
    seen: set[str] = set()
    for path in list(consumed_paths) + dependency_paths:
        resolved = str(path.resolve())
        if resolved not in seen:
            if not path.is_file():
                raise InputError(f"manifest dependency is missing: {path}")
            all_paths.append(path)
            seen.add(resolved)
    entries = []
    for path in all_paths:
        resolved = str(path.resolve())
        entry: dict[str, Any] = {
            "path": resolved,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        if path.suffix.lower() == ".csv":
            entry["header"] = csv_header(path)
            if resolved in row_counts:
                entry["rows"] = int(row_counts[resolved])
        entries.append(entry)
    fingerprints = {entry["path"]: entry["sha256"] for entry in entries}
    policy_hash = sha256_file(gp_root / "policy.json")
    build_material = {
        "population": population,
        "as_of_date": as_of_date,
        "policy_version": policy["version"],
        "policy_hash": policy_hash,
        "fingerprints": fingerprints,
    }
    build_id = hashlib.sha256(
        json.dumps(build_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "build_id": build_id,
        "population": population,
        "as_of_date": as_of_date,
        "policy_version": policy["version"],
        "policy_sha256": policy_hash,
        "parent_git": git_state(parent),
        "inputs": entries,
        "fingerprints": fingerprints,
    }
