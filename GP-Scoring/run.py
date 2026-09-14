from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from briefing import generate_briefs  # noqa: E402
from dashboard import render_dashboard  # noqa: E402
from inputs import (  # noqa: E402
    InputError,
    build_manifest,
    build_observed_evidence,
    load_fixture,
    read_json,
    sha256_file,
    verify_fingerprints,
)
from scoring import score_fixture, scorecard_reconciliation_errors  # noqa: E402


STAGES = ("01-inputs", "02-scoring", "03-report")


class RunError(RuntimeError):
    pass


def _report_id(data_build_id: str, llm_receipt: Mapping[str, Any], briefs: list[Mapping[str, Any]]) -> str:
    material = {
        "data_build_id": data_build_id,
        "llm": dict(llm_receipt),
        "briefs": briefs,
    }
    payload = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _fieldnames(rows: list[Mapping[str, Any]], fallback: list[str]) -> list[str]:
    if not rows:
        return fallback
    result: list[str] = []
    for row in rows:
        for key in row:
            if key not in result:
                result.append(key)
    return result


def _write_csv(path: Path, rows: list[Mapping[str, Any]], fallback: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = _fieldnames(rows, fallback)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _append_missing_fixture_decisions(
    decisions: list[dict[str, str]], preliminary: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, str]]:
    represented = {row["record_id"] for row in decisions if row.get("level") == "fund"}
    output = list(decisions)
    for fund_id in sorted(preliminary):
        if fund_id in represented:
            continue
        reasons = list(preliminary[fund_id].get("reasons", []))
        if not reasons:
            reasons = ["NOT_SELECTED"]
        output.append(
            {
                "level": "fund",
                "record_id": fund_id,
                "status": "EXCLUDED",
                "primary_reason": reasons[0],
                "additional_reasons": json.dumps(reasons[1:], separators=(",", ":")),
                "source_ids": "[]",
                "evidence_ids": "[]",
            }
        )
    return sorted(output, key=lambda row: (row.get("level", ""), row.get("record_id", "")))


def _checks(
    population: str,
    policy: Mapping[str, Any],
    features: list[dict[str, str]],
    scorecards: list[dict[str, str]],
    decisions: list[dict[str, str]],
    expected_fund_count: int,
    fingerprints: Mapping[str, str],
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, actual: Any, expected: Any, source: str, reason: str = "") -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else "FAIL",
                "actual": str(actual),
                "expected": str(expected),
                "source": source,
                "reason": reason,
            }
        )

    weight_sum = float(policy["weights"]["tvpi"]) + float(policy["weights"]["dpi"])
    add("C01_WEIGHT_SUM", abs(weight_sum - 1.0) <= 1e-12, weight_sum, 1.0, "policy.json")
    errors = scorecard_reconciliation_errors(features, scorecards, policy)
    add("C02_SCORE_RECONCILIATION", not errors, len(errors), 0, "scoring.py", "; ".join(errors[:5]))
    out_of_bounds = [
        row["fund_id"]
        for row in features
        if row.get("fund_score") and not 0.0 <= float(row["fund_score"]) <= 100.0
    ]
    add("C03_FUND_SCORE_BOUNDS", not out_of_bounds, len(out_of_bounds), 0, "fund-features.csv")
    nav_increases = [
        row["fund_id"]
        for row in features
        if row.get("fund_score") and row.get("scenario_score") and float(row["scenario_score"]) > float(row["fund_score"]) + 1e-10
    ]
    add("C04_NAV_HAIRCUT_MONOTONIC", not nav_increases, len(nav_increases), 0, "fund-features.csv")
    ranked_real = [row for row in scorecards if row.get("status") == "RANKED_DEMO" and not row.get("manager_id", "").startswith("MANAGER_SYNTH_")]
    add("C05_SYNTHETIC_RANK_BOUNDARY", not ranked_real, len(ranked_real), 0, "gp-scorecards.csv")
    fund_decision_count = len({row["record_id"] for row in decisions if row.get("level") == "fund"})
    add(
        "C06_FUND_DISPOSITION_COVERAGE",
        population != "fixture" or fund_decision_count == expected_fund_count,
        fund_decision_count,
        expected_fund_count if population == "fixture" else fund_decision_count,
        "decisions.csv",
    )
    duplicate_funds = len(features) - len({row["fund_id"] for row in features})
    add("C07_ONE_FEATURE_ROW_PER_FUND", duplicate_funds == 0, duplicate_funds, 0, "fund-features.csv")
    drift = verify_fingerprints(fingerprints)
    add("C08_INPUT_HASH_STABILITY", not drift, len(drift), 0, "manifest.json", "; ".join(drift[:3]))
    ranked_blanks = [row["manager_id"] for row in scorecards if row.get("status") == "RANKED_DEMO" and (not row.get("score") or not row.get("rank"))]
    add("C09_RANKED_ROWS_COMPLETE", not ranked_blanks, len(ranked_blanks), 0, "gp-scorecards.csv")
    nonranked_with_rank = [row["manager_id"] for row in scorecards if row.get("status") != "RANKED_DEMO" and (row.get("score") or row.get("rank"))]
    add("C10_NONRANKED_ROWS_BLANK", not nonranked_with_rank, len(nonranked_with_rank), 0, "gp-scorecards.csv")
    return checks


def _archive_active(gp_root: Path) -> None:
    active = [gp_root / stage for stage in STAGES if (gp_root / stage).exists()]
    if not active:
        return
    archive_dir = gp_root / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / "previous.zip"
    temporary = archive_dir / "previous.zip.tmp"
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for stage_dir in active:
            for path in stage_dir.rglob("*"):
                if path.is_file():
                    bundle.write(path, path.relative_to(gp_root))
    os.replace(temporary, archive_path)
    (archive_dir / "README.md").write_text(
        "# Previous bundle\n\n`previous.zip` is the immediately preceding successful GP scoring bundle, retained before replacement.\n",
        encoding="utf-8",
    )


def _publish_candidate(gp_root: Path, candidate: Path) -> None:
    _archive_active(gp_root)
    for stage in STAGES:
        target = gp_root / stage
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(candidate / stage), str(target))
    shutil.rmtree(candidate, ignore_errors=True)


def _output_hashes(candidate: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for stage in STAGES:
        for path in sorted((candidate / stage).rglob("*")):
            if path.is_file() and path.name != "receipt.json":
                hashes[str(path.relative_to(candidate)).replace("\\", "/")] = sha256_file(path)
    return hashes


def check_only(gp_root: Path) -> int:
    receipt_path = gp_root / "03-report/receipt.json"
    manifest_path = gp_root / "01-inputs/manifest.json"
    if not receipt_path.is_file() or not manifest_path.is_file():
        print("GP scoring output is missing receipt.json or manifest.json")
        return 1
    receipt = read_json(receipt_path)
    manifest = read_json(manifest_path)
    errors = verify_fingerprints(manifest.get("fingerprints", {}))
    for relative, expected in receipt.get("output_hashes", {}).items():
        path = gp_root / relative
        if not path.is_file():
            errors.append(f"missing output: {relative}")
        elif sha256_file(path) != expected:
            errors.append(f"output hash changed: {relative}")
    if receipt.get("build_id") != manifest.get("build_id"):
        errors.append("receipt build_id does not match manifest build_id")
    briefs_path = gp_root / "03-report/briefs.json"
    if briefs_path.is_file() and isinstance(receipt.get("llm"), dict):
        expected_report_id = _report_id(
            str(manifest.get("build_id", "")),
            receipt["llm"],
            read_json(briefs_path),
        )
        if receipt.get("report_id") != expected_report_id:
            errors.append("receipt report_id does not match briefs/provider variant")
    if errors:
        for error in errors:
            print("FAIL", error)
        return 1
    print(
        f"PASS GP scoring data {receipt.get('build_id')} | "
        f"report={receipt.get('report_id')} verified"
    )
    return 0


def run(
    parent: Path,
    population: str,
    as_of_date: str,
    llm_provider: str,
    llm_model: str = "",
    llm_dry_run: bool = False,
) -> int:
    gp_root = HERE
    policy = read_json(gp_root / "policy.json")
    candidate = gp_root / ".candidate"
    shutil.rmtree(candidate, ignore_errors=True)
    for stage in STAGES:
        (candidate / stage).mkdir(parents=True, exist_ok=True)

    observed = build_observed_evidence(parent, int(policy.get("real_evidence_cards", 3)))
    row_counts = dict(observed["row_counts"])
    consumed_paths = list(observed["consumed_paths"])
    quality_run: dict[str, str] = {"run_id": "", "checked_at": "", "status": "NOT_APPLICABLE"}
    expected_fund_count = 0

    if population == "fixture":
        fixture = load_fixture(parent, as_of_date, policy)
        expected_fund_count = len(fixture["fund_master"])
        quality_run = fixture["quality_run"]
        features, scorecards, decisions = score_fixture(
            fixture["selected_records"], fixture["fund_master"], fixture["manager_master"], policy
        )
        decisions = _append_missing_fixture_decisions(decisions, fixture["preliminary_decisions"])
        synthetic_evidence = fixture["synthetic_evidence"]
        consumed_paths.extend(fixture["consumed_paths"])
        row_counts.update(fixture["row_counts"])
    elif population == "observed":
        features = []
        scorecards = []
        synthetic_evidence = []
        decisions = [
            {
                "level": "fund_period",
                "record_id": card["fund_period_id"],
                "status": "EVIDENCE_ONLY",
                "primary_reason": "REAL_SOURCE_NOT_RANKED_V1",
                "additional_reasons": "[]",
                "source_ids": json.dumps([card["fund_id"]], separators=(",", ":")),
                "evidence_ids": json.dumps(
                    [item["evidence_id"] for item in card.get("evidence", [])], separators=(",", ":")
                ),
            }
            for card in observed["cards"]
        ]
    else:
        raise RunError(f"unknown population: {population}")

    manifest = build_manifest(
        parent, gp_root, population, as_of_date, policy, consumed_paths, row_counts
    )
    manifest["quality_run"] = quality_run
    evidence = {
        "build_id": manifest["build_id"],
        "population": population,
        "as_of_date": as_of_date,
        "separation_rule": "Synthetic manager scores and named real-source evidence are separate populations.",
        "synthetic_evidence": synthetic_evidence,
        "real_source_cards": observed["cards"],
    }
    _write_json(candidate / "01-inputs/manifest.json", manifest)
    _write_json(candidate / "01-inputs/evidence.json", evidence)
    (candidate / "01-inputs/README.md").write_text(
        "# GP scoring inputs\n\n| File | Content |\n|---|---|\n| `manifest.json` | Input and code hashes, local commit, policy, population, and quality run |\n| `evidence.json` | Synthetic scoring evidence IDs and separate real-source evidence cards |\n",
        encoding="utf-8",
    )

    feature_fields = [
        "population","fund_id","manager_id","manager_name","fund_period_id","strategy","currency","vintage_year","vintage_bucket","as_of_date","measurement_basis","paid_in","distributions","nav","dpi","rvpi","tvpi","nav_dependence","tvpi_percentile","dpi_percentile","peer_count","peer_manager_count","peer_fund_ids","fund_score","nav_haircut","scenario_tvpi","scenario_score","evidence_ids","status",
    ]
    scorecard_fields = [
        "population","manager_id","manager_name","strategy","as_of_date","measurement_basis","total_funds","current_date_funds","eligible_funds","stale_or_missing_date_funds","excluded_current_funds","coverage","constituent_fund_ids","avg_tvpi_percentile","avg_dpi_percentile","score","rank","fund_score_min","fund_score_max","scenario_score","scenario_rank","score_change_nav_haircut","status","reasons",
    ]
    decision_fields = ["level","record_id","status","primary_reason","additional_reasons","source_ids","evidence_ids"]
    _write_csv(candidate / "02-scoring/fund-features.csv", features, feature_fields)
    _write_csv(candidate / "02-scoring/gp-scorecards.csv", scorecards, scorecard_fields)
    _write_csv(candidate / "02-scoring/decisions.csv", decisions, decision_fields)
    (candidate / "02-scoring/README.md").write_text(
        "# GP scoring results\n\n| File | Content |\n|---|---|\n| `fund-features.csv` | Fund multiples, peers, percentiles, scores, and NAV sensitivity |\n| `gp-scorecards.csv` | Manager-strategy aggregation, coverage, rank, and sensitivity |\n| `decisions.csv` | Selected and excluded fund and manager records with reasons |\n",
        encoding="utf-8",
    )

    briefs, llm_cache = generate_briefs(
        scorecards,
        features,
        policy,
        gp_root / "brief-prompt.txt",
        llm_provider,
        model_override=llm_model,
        dry_run=llm_dry_run,
        existing_cache_path=gp_root / "03-report/llm-cache.json",
    )
    _write_json(candidate / "03-report/briefs.json", briefs)
    if llm_cache:
        _write_json(candidate / "03-report/llm-cache.json", llm_cache)
    llm_receipt = {
        "provider": llm_provider,
        "model_override": llm_model,
        "dry_run": llm_dry_run,
        "cache_status": llm_cache.get("status", "off") if llm_cache else "off",
        "resolved_model": llm_cache.get("model", "") if llm_cache else "",
    }
    report_id = _report_id(manifest["build_id"], llm_receipt, briefs)
    dashboard = render_dashboard(
        {**manifest, "report_id": report_id, "quality_run": quality_run},
        policy,
        scorecards,
        features,
        decisions,
        observed["cards"],
        briefs,
    )
    (candidate / "03-report/dashboard.html").write_text(dashboard, encoding="utf-8")
    (candidate / "03-report/README.md").write_text(
        "# GP scoring report\n\n| File | Content |\n|---|---|\n| `dashboard.html` | Static investment comparison, manager detail, sensitivity, controls, and real evidence |\n| `briefs.json` | Deterministic or provider-generated diligence briefs |\n| `llm-cache.json` | Optional validated provider responses, usage, and request metadata; no credentials |\n| `checks.csv` | Executed downstream build checks |\n| `receipt.json` | Matching build ID, hashes, status, and limitations |\n",
        encoding="utf-8",
    )

    checks = _checks(
        population, policy, features, scorecards, decisions, expected_fund_count, manifest["fingerprints"]
    )
    _write_csv(
        candidate / "03-report/checks.csv",
        checks,
        ["check_id", "status", "actual", "expected", "source", "reason"],
    )
    failures = [row for row in checks if row["status"] == "FAIL"]
    if failures:
        raise RunError("numerical publication checks failed: " + "; ".join(row["check_id"] for row in failures))

    receipt = {
        "status": "PASS",
        "build_id": manifest["build_id"],
        "report_id": report_id,
        "population": population,
        "as_of_date": as_of_date,
        "policy_version": policy["version"],
        "quality_run": quality_run,
        "llm": llm_receipt,
        "checks": {"passed": len(checks), "failed": 0},
        "output_hashes": _output_hashes(candidate),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "Numerical rankings use fictional synthetic managers only.",
            "The score summarizes historical supplied records and is not a forecast.",
            "The NAV haircut is a sensitivity assumption and is not an LP-interest price.",
            "Named real-source records remain evidence-only until complete comparable GP histories are supported.",
        ],
    }
    _write_json(candidate / "03-report/receipt.json", receipt)
    if verify_fingerprints(manifest["fingerprints"]):
        raise RunError("an input changed after calculation and before publication")
    _publish_candidate(gp_root, candidate)
    print(
        f"PASS GP scoring data {manifest['build_id']} | report={report_id} | population={population} | "
        f"fund_features={len(features)} | ranked_gp_rows={sum(row.get('status') == 'RANKED_DEMO' for row in scorecards)}"
    )
    print(gp_root / "03-report/dashboard.html")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the downstream GP scoring demonstration")
    parser.add_argument("--parent", default=".", help="parent Alts-ETL-Analytics-Project directory")
    parser.add_argument("--population", choices=("fixture", "observed"), default=None)
    parser.add_argument("--as-of", dest="as_of_date", default=None)
    parser.add_argument(
        "--llm",
        choices=("off", "openrouter", "anthropic"),
        default="off",
        help="optional commentary provider; off is the safe default and makes no network request",
    )
    parser.add_argument(
        "--model",
        default="",
        help="provider model ID; blank uses that provider's policy default",
    )
    parser.add_argument(
        "--llm-dry-run",
        action="store_true",
        help="resolve provider/model, packet limits and budget without making a model request",
    )
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    parent = Path(args.parent).resolve()
    gp_root = HERE
    if args.check_only:
        return check_only(gp_root)
    policy = read_json(gp_root / "policy.json")
    population = args.population or str(policy["default_population"])
    as_of_date = args.as_of_date or str(policy["default_as_of"])
    try:
        return run(
            parent,
            population,
            as_of_date,
            args.llm,
            llm_model=args.model,
            llm_dry_run=args.llm_dry_run,
        )
    except (InputError, RunError, ValueError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
