from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

import v2_features  # noqa: E402
import v2_inputs  # noqa: E402
import v2_stress  # noqa: E402
from v2_dashboard import render_dashboard  # noqa: E402


STAGES = ("04-diagnostics", "05-scenarios", "06-report")


class V2RunError(RuntimeError):
    pass


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(_jsonable(value), separators=(",", ":"), sort_keys=isinstance(value, dict))
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fallback_fields: Sequence[str] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = list(fallback_fields)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(value) for key, value in row.items()})
    os.replace(temporary, path)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _hash_files(paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for path in sorted({p.resolve() for p in paths}, key=str):
        if not path.is_file():
            raise V2RunError(f"implementation file missing: {path}")
        output[path.relative_to(HERE).as_posix()] = {"sha256": v2_inputs.sha256_file(path), "bytes": path.stat().st_size}
    return output


def _implementation_files(include_cases: bool) -> list[Path]:
    paths = [HERE / name for name in ("v2-policy.json", "v2_inputs.py", "v2_features.py", "v2_analysis.py", "v2_stress.py", "v2_dashboard.py", "run_v2.py")]
    if include_cases:
        for name in ("generate_v2_cases.py", "v2_diligence.py"):
            path = HERE / name
            if path.is_file():
                paths.append(path)
    return paths


def _finalize_manifest(context: Mapping[str, Any], include_cases: bool) -> dict[str, Any]:
    manifest = v2_inputs.manifest_for_context(context)
    implementation = _hash_files(_implementation_files(include_cases))
    material = {
        "base_data_id": manifest["v2_data_id"],
        "implementation": implementation,
        "include_cases": include_cases,
    }
    manifest["base_data_id"] = manifest["v2_data_id"]
    manifest["implementation"] = implementation
    manifest["include_cases"] = include_cases
    manifest["v2_data_id"] = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    return manifest


def _template_briefs(
    core: Mapping[str, Any],
    scenarios: Mapping[str, Any],
    case_bundle: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    scenario_index = {
        (row["manager_id"], row["strategy"], row["scenario_id"]): row
        for row in scenarios["manager_scenarios"]
    }
    ranked = [
        row for row in core["manager_diagnostics"] if row.get("v1_status") == "RANKED_DEMO"
    ]
    case_map = (case_bundle or {}).get("manager_cases", {})
    if case_map:
        selected_ids = set(case_map)
        ranked = [row for row in ranked if row.get("manager_id") in selected_ids]
        ranked.sort(key=lambda row: case_map[row["manager_id"]].get("case_id", ""))
    else:
        ranked.sort(
            key=lambda row: (
                row.get("strategy") != "buyout",
                int(row.get("historical_rank") or 10**9),
                row.get("manager_id", ""),
            )
        )
        ranked = ranked[:3]
    output: list[dict[str, Any]] = []
    for row in ranked:
        nav20 = scenario_index.get((row["manager_id"], row["strategy"], "nav_20"), {})
        nav_score = nav20.get("scenario_score")
        nav_text = "unavailable" if nav_score is None else f"{float(nav_score):.1f}"
        realized = row.get("avg_realized_share")
        realized_text = "unavailable" if realized is None else f"{100 * float(realized):.0f}%"
        questions = [
            "Accounting and fee basis of the supplied track record.",
            "Current valuations of the largest remaining positions.",
            "Senior-team roster, departures, attribution and manager commitment evidence.",
        ]
        case = case_map.get(row["manager_id"], {})
        if case.get("strategy") != row["strategy"]:
            case = {}
        case_text = ""
        evidence_ids = [f"MANAGER:{row['manager_id']}:{row['strategy']}:V2"]
        if case:
            case_text = (
                f" Bounded case evidence reports senior-team continuity "
                f"{100 * float(case.get('team_continuity') or 0):.0f}%, GP commitment "
                f"{100 * float(case.get('gp_commitment_pct') or 0):.1f}%, and governance status "
                f"{case.get('governance_flag')}."
            )
            evidence_ids.extend(case.get("evidence_ids", []))
        output.append(
            {
                "manager_key": f"{row['manager_id']}|{row['strategy']}",
                "manager_id": row["manager_id"],
                "manager_name": row["manager_name"],
                "strategy": row["strategy"],
                "mode": "template",
                "provider": "",
                "model": "",
                "review_status": "DETERMINISTIC_TEMPLATE",
                "summary": (
                    f"Historical score {float(row['historical_score']):.1f}, rank {row['historical_rank']}; "
                    f"average realized share {realized_text}; "
                    f"NAV -20% score {nav_text}."
                    + case_text
                ),
                "questions": questions,
                "evidence_ids": sorted(set(evidence_ids)),
            }
        )
    return output


def _checks(
    parent: Path,
    context: Mapping[str, Any],
    core: Mapping[str, Any],
    scenarios: Mapping[str, Any],
    manifest: Mapping[str, Any],
    case_bundle: Mapping[str, Any] | None = None,
    model_previews: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def add(check_id: str, ok: bool, actual: Any, expected: Any, source: str, reason: str = "") -> None:
        checks.append({"check_id": check_id, "status": "PASS" if ok else "FAIL", "actual": str(actual), "expected": str(expected), "source": source, "reason": reason})

    baseline = v2_inputs.verify_baseline(parent, HERE)
    add("V2C01_PROTECTED_BASELINE", not baseline, len(baseline), 0, "v2-baseline.json", "; ".join(baseline[:3]))
    decisions = core["decisions"]
    unique_funds = {row["entity_id"] for row in decisions if row.get("level") == "fund"}
    expected_funds = {row["fund_id"] for row in context["fund_master"]}
    add("V2C02_FUND_DISPOSITIONS", unique_funds == expected_funds and len(decisions) == len(expected_funds), len(decisions), len(expected_funds), "decisions.csv")
    current = [row for row in core["fund_diagnostics"] if row.get("current_status") == "AVAILABLE"]
    expected_current = {row["fund_id"] for row in context["current_records"] if not v2_features.period_reason(context, row)}
    add("V2C03_CURRENT_PERIODS", {row['fund_id'] for row in current} == expected_current and len(core['fund_diagnostics']) == len(expected_funds), len(current), len(expected_current), "fund-diagnostics.csv")
    xirr_count = sum(row.get("xirr") is not None for row in current)
    xirr_bad = [row for row in current if (row.get('xirr') is not None) != (row.get('xirr_status') == 'AVAILABLE')]
    add("V2C04_XIRR_COVERAGE", not xirr_bad, f"{xirr_count} available; {len(xirr_bad)} unexplained", "each return or missing reason", "fund-diagnostics.csv")
    pme_rows = [row for row in current if row.get("ks_pme") is not None]
    bad_pme = [row["fund_id"] for row in pme_rows if row.get("benchmark_id") != context["strategy_benchmark"].get(row.get("strategy", "")) or context["benchmark_currency"].get(row.get("benchmark_id", "")) != row.get("currency")]
    add("V2C05_PME_MAPPING_AND_CURRENCY", not bad_pme, f"{len(pme_rows)} rows; {len(bad_pme)} bad", "0 bad", "fund-diagnostics.csv")
    bad_realization = [row["fund_id"] for row in current if row.get("realized_share") is not None and abs(float(row["realized_share"]) + float(row["nav_reliance"]) - 1.0) > 1e-9]
    add("V2C06_REALIZATION_IDENTITY", not bad_realization, len(bad_realization), 0, "fund-diagnostics.csv")
    bad_holdings = [row["fund_id"] for row in current if not row.get("holdings_status") or (row.get("holdings_status") != "AVAILABLE" and row.get("company_hhi") is not None)]
    add("V2C07_HOLDINGS_RECONCILIATION", not bad_holdings, len(bad_holdings), 0, "fund-diagnostics.csv")
    bad_loss = [row["fund_id"] for row in core["fund_diagnostics"] if row.get("economic_loss_status") != "UNSUPPORTED_DEFINITION"]
    add("V2C08_LOSS_DEFINITION_BOUNDARY", not bad_loss, len(bad_loss), 0, "fund-diagnostics.csv")
    nav0 = [row for row in scenarios["fund_scenarios"] if row.get("scenario_id") == "nav_00"]
    nav0_diff = max((abs(float(row["scenario_score"]) - float(row["baseline_score"])) for row in nav0), default=0.0)
    add("V2C09_ZERO_NAV_STRESS", nav0_diff <= 1e-9, nav0_diff, "<=1e-9", "fund-scenarios.csv")
    nav30_bad = [row["fund_id"] for row in scenarios["fund_scenarios"] if row.get("scenario_id") == "nav_30" and float(row["scenario_score"]) > float(row["baseline_score"]) + 1e-9]
    add("V2C10_NAV_MONOTONICITY", not nav30_bad, len(nav30_bad), 0, "fund-scenarios.csv")
    w60 = [row for row in scenarios["fund_scenarios"] if row.get("scenario_id") == "w60_40"]
    w60_diff = max((abs(float(row["scenario_score"]) - float(row["baseline_score"])) for row in w60), default=0.0)
    add("V2C11_WEIGHT_BASELINE", w60_diff <= 1e-9, w60_diff, "<=1e-9", "fund-scenarios.csv")
    bad_remove = [row for row in scenarios["manager_scenarios"] if row.get("scenario_id") in {"remove_best", "remove_worst"} and not row.get("official_eligible") and row.get("scenario_rank") not in (None, "")]
    add("V2C12_LEAVE_ONE_OUT_ELIGIBILITY", not bad_remove, len(bad_remove), 0, "manager-scenarios.csv")
    readiness_bad = [row for row in core["readiness"] if row.get("coverage") is not None and not 0 <= float(row["coverage"]) <= 1]
    add("V2C13_READINESS_BOUNDS", not readiness_bad, len(readiness_bad), 0, "evidence-readiness.csv")
    named_score = [row for row in core["real_evidence"] if row.get("historical_score") or row.get("rank")]
    add("V2C14_REAL_EVIDENCE_NOT_RANKED", not named_score, len(named_score), 0, "evidence.json")
    bad_self = []
    fund_manager = {row["fund_id"]: row["fund_manager_id"] for row in context["fund_master"]}
    for row in core["cohort_membership"]:
        if fund_manager.get(row["evaluated_fund_id"]) == fund_manager.get(row["peer_fund_id"]):
            bad_self.append(row)
    add("V2C15_PEER_SELF_EXCLUSION", not bad_self, len(bad_self), 0, "cohort-membership.csv")
    baseline_card = {(row["manager_id"], row["strategy"]): row for row in context["v1"]["scorecards"] if row.get("status") == "RANKED_DEMO"}
    core_card = {(row["manager_id"], row["strategy"]): row for row in core["manager_diagnostics"] if row.get("v1_status") == "RANKED_DEMO"}
    drift = [key for key, source in baseline_card.items() if key not in core_card or abs(float(source["score"]) - float(core_card[key]["historical_score"])) > 1e-12]
    add("V2C16_V1_SCORE_REFERENCE", not drift and set(core_card) == set(baseline_card), f"{len(core_card)} rows; {len(drift)} drift", f"{len(baseline_card)} rows; 0 drift", "manager-diagnostics.csv")
    fingerprint_drift = v2_inputs.verify_fingerprints(manifest["fingerprints"], parent)
    add("V2C17_INPUT_HASH_STABILITY", not fingerprint_drift, len(fingerprint_drift), 0, "manifest.json", "; ".join(fingerprint_drift[:3]))
    analysis_policy = context["policy"]["investment_analysis"]
    def same(left: Any, right: Any) -> bool:
        return (isinstance(left, (int, float)) and isinstance(right, (int, float))
                and math.isfinite(left) and math.isfinite(right)
                and math.isclose(left, right, rel_tol=analysis_policy["reconciliation_relative_tolerance"],
                                 abs_tol=analysis_policy["reconciliation_absolute_tolerance"]))
    capital_bad = [r["fund_id"] for r in current if not same(r["capital_still_to_return"], max(r["paid_in"] - r["distributions"], 0)) or (r.get("benchmark_capital") is not None and not same(r["benchmark_excess_value"], (r["ks_pme"] - 1) * r["benchmark_capital"]))]
    add("V2C25_CAPITAL_AND_BENCHMARK", not capital_bad, len(capital_bad), 0, "fund-diagnostics.csv")
    points_bad = [r["manager_id"] for r in core_card.values() if not same(r["score_tvpi_points"] + r["score_dpi_points"], r["historical_score"]) or not same(sum(c["tvpi_points"] + c["dpi_points"] for c in r["score_contributions"]), r["historical_score"])]
    add("V2C26_SCORE_CONTRIBUTIONS", not points_bad, len(points_bad), 0, "manager-diagnostics.csv")
    if case_bundle:
        cases = list(case_bundle.get("manager_cases", {}).values())
        add("V2C18_CASE_MANAGER_COUNT", len(cases) == 3, len(cases), 3, "case-manifest.json")
        bad_population = [row.get("manager_id", "") for row in cases if row.get("population") != "case_simulation"]
        add("V2C19_CASE_POPULATION", not bad_population, len(bad_population), 0, "case bundle")
        resolutions = list(case_bundle.get("conflict_resolutions", []))
        resolved_ok = bool(resolutions) and all(row.get("selected_fact_id") and row.get("rejected_fact_ids") and row.get("reviewer") for row in resolutions)
        add("V2C20_CASE_CONFLICT_RESOLUTION", resolved_ok, len(resolutions), ">=1 complete", "conflict resolutions")
        evidence_missing = [row.get("manager_id", "") for row in cases if not row.get("evidence_ids")]
        add("V2C21_CASE_EVIDENCE", not evidence_missing, len(evidence_missing), 0, "case evidence")
        timing_bad = [
            row.get("manager_id", "")
            for row in cases
            if row.get("case_scenario", {}).get("distribution_delay_tvpi") is not None
            and abs(float(row["case_scenario"]["distribution_delay_tvpi"]) - float(row.get("case_tvpi") or 0.0)) > 1e-12
        ]
        add("V2C22_CASE_TIMING_TVPI", not timing_bad, len(timing_bad), 0, "case scenarios")
        facility = [row for row in cases if row.get("case_scenario", {}).get("facility_status") == "AVAILABLE"]
        add("V2C23_CASE_FACILITY_PAIR", len(facility) == 1 and facility[0]["case_scenario"].get("xirr_with_facility") is not None and facility[0]["case_scenario"].get("xirr_without_facility") is not None, len(facility), 1, "case scenarios")
        previews = list((model_previews or {}).values())
        preview_ok = bool(previews) and all(row.get("network") is False and row.get("live_status") == "NOT_RUN" for row in previews)
        add("V2C24_MODEL_PREVIEW_NO_NETWORK", preview_ok, len(previews), ">=2 no-network previews", "model-previews.json")
        operating = [r for case in cases for r in case["investment_analysis"]["operating_results"]]
        bad_operating = [r for r in operating if not same(r["baseline_value"] + r["rounding_adjustment"] + r["revenue_effect"] + r["margin_effect"] + r["multiple_effect"], r["scenario_value"]) or r["scenario_value"] < 0 or r["scenario_value"] > r["baseline_value"] + analysis_policy["reconciliation_absolute_tolerance"]]
        add("V2C27_OPERATING_RECONCILIATION", bool(operating) and not bad_operating, f"{len(operating)} companies; {len(bad_operating)} failed", "positive count; 0 failed", "evidence.json")
    return checks


def _write_stage_guides(candidate: Path, include_cases: bool) -> None:
    guides = {
        "04-diagnostics": (
            "# V2 diagnostics\n\n"
            "| File | Content |\n|---|---|\n"
            "| fund-diagnostics.csv | One row per supplied fund: returns, capital recovery, benchmark wealth, concentrations, terms and missing-value reasons. |\n"
            "| manager-diagnostics.csv | One row per manager and strategy: score contributions, benchmark counts, history status and averages. |\n"
            "| cohort-membership.csv | The funds used in each comparison. |\n"
            "| genealogy.csv | Fund ordering within each manager and strategy. |\n"
            "| coverage.csv | Availability decisions by fund and measure. |\n"
            "| evidence-readiness.csv | Supported and required field counts by review dimension. |\n"
            "| decisions.csv | Input exclusions and their reasons. |\n"
            "| evidence.json | Calculation inputs and dates, benchmark cash flows, case investment gains, operating scenarios and source references. |\n"
            "| manifest.json | Input files, policy and implementation used by this build. |\n\n"
            "[Sensitivity results](../05-scenarios/README.md)\n"
        ),
        "05-scenarios": (
            "# V2 scenarios\n\n"
            "| File | Content |\n|---|---|\n"
            "| fund-scenarios.csv | Fund results under each named change in assumptions. |\n"
            "| manager-scenarios.csv | Manager scores and eligibility after those changes. |\n"
            "| scenario-definitions.json | The assumption changed by each scenario. |\n\n"
            "[Report](../06-report/README.md)\n"
        ),
        "06-report": (
            "# V2 report\n\n"
            "| File | Content |\n|---|---|\n"
            "| [dashboard.html](dashboard.html) | Eight report views, including RAG: Document Insights for reviewed source PDFs. |\n"
            "| briefs.json | Calculation-based manager summaries. |\n"
            "| checks.csv | Input, calculation and publication checks; 19 core checks or 27 with cases. |\n"
            "| receipt.json | Build identifiers, check totals and output verification. |\n"
            + ("| model-previews.json | Six proposed provider requests; no network calls. |\n" if include_cases else "")
            + "\n[Implementation](../V2-IMPLEMENTATION-REPORT.md)\n"
        ),
    }
    for stage, text in guides.items():
        (candidate / stage / "README.md").write_text(text, encoding="utf-8", newline="\n")


def _output_hashes(candidate: Path) -> dict[str, str]:
    result = {}
    for stage in STAGES:
        for path in sorted((candidate / stage).rglob("*")):
            if path.is_file() and path.name != "receipt.json":
                result[str(path.relative_to(candidate)).replace("\\", "/")] = v2_inputs.sha256_file(path)
    return result


def _archive_active() -> None:
    active = [HERE / stage for stage in STAGES if (HERE / stage).exists()]
    if not active:
        return
    if _bundle_errors(HERE):
        return
    archive = HERE / "v2-archive"
    archive.mkdir(parents=True, exist_ok=True)
    temporary = archive / "previous.zip.tmp"
    target = archive / "previous.zip"
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for stage_dir in active:
            for path in stage_dir.rglob("*"):
                if path.is_file():
                    bundle.write(path, path.relative_to(HERE))
    os.replace(temporary, target)
    (archive / "README.md").write_text("# V2 recovery\n\n| File | Content |\n|---|---|\n| previous.zip | Most recent complete V2 bundle replaced by a build; an incomplete retry does not replace it. |\n", encoding="utf-8", newline="\n")


def _publish(candidate: Path, receipt_path: Path) -> None:
    _archive_active()
    active_receipt = HERE / "06-report/receipt.json"
    if active_receipt.is_file():
        prior = v2_inputs.read_json(active_receipt)
        prior["status"] = "INVALID_REPLACEMENT_IN_PROGRESS"
        _write_json(active_receipt, prior)
    for stage in STAGES:
        target = HERE / stage
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(candidate / stage), str(target))
    final_receipt = HERE / "06-report/receipt.json"
    os.replace(receipt_path, final_receipt)
    shutil.rmtree(candidate, ignore_errors=True)


def build(parent: Path, include_cases: bool = False) -> int:
    policy = v2_inputs.read_json(HERE / "v2-policy.json")
    candidate = HERE / ".v2-candidate"
    shutil.rmtree(candidate, ignore_errors=True)
    for stage in STAGES:
        (candidate / stage).mkdir(parents=True, exist_ok=True)
    context = v2_inputs.build_context(parent, HERE, policy, include_cases=include_cases)
    manifest = _finalize_manifest(context, include_cases)
    core = v2_features.build_core_features(context)
    scenarios = v2_stress.build_scenarios(context, core)
    case_bundle: dict[str, Any] = {}
    model_previews: dict[str, Any] = {}
    if include_cases and (HERE / "v2_diligence.py").is_file():
        import v2_diligence

        case_bundle = v2_diligence.build_case_bundle(context, core)
        diagnostic_by_manager = {
            (row["manager_id"], row["strategy"]): row
            for row in core["manager_diagnostics"]
            if row.get("v1_status") == "RANKED_DEMO"
        }
        for manager_id, case in sorted(case_bundle.get("manager_cases", {}).items()):
            diagnostic = diagnostic_by_manager.get((manager_id, case["strategy"]))
            if diagnostic is None:
                raise V2RunError(f"case manager lacks ranked diagnostic: {manager_id}")
            for provider in ("openrouter", "anthropic"):
                model_previews[f"{manager_id}|{provider}"] = v2_diligence.model_preview(
                    case,
                    diagnostic,
                    provider=provider,
                )
    briefs = _template_briefs(core, scenarios, case_bundle)
    _write_json(candidate / "04-diagnostics/manifest.json", manifest)
    _write_csv(candidate / "04-diagnostics/coverage.csv", core["coverage"])
    _write_csv(candidate / "04-diagnostics/fund-diagnostics.csv", core["fund_diagnostics"])
    _write_csv(candidate / "04-diagnostics/manager-diagnostics.csv", core["manager_diagnostics"])
    _write_csv(candidate / "04-diagnostics/cohort-membership.csv", core["cohort_membership"])
    _write_csv(candidate / "04-diagnostics/genealogy.csv", core["genealogy"])
    _write_csv(candidate / "04-diagnostics/evidence-readiness.csv", core["readiness"])
    _write_csv(candidate / "04-diagnostics/decisions.csv", core["decisions"])
    _write_json(
        candidate / "04-diagnostics/evidence.json",
        {
            "feature_evidence": core["evidence"] + scenarios.get("evidence", []),
            "real_source_evidence": core["real_evidence"],
            "case_evidence": case_bundle.get("evidence", []),
            "case_manager_summary": case_bundle.get("manager_cases", {}),
            "case_conflict_resolutions": case_bundle.get("conflict_resolutions", []),
            "case_resolved_facts": case_bundle.get("resolved_facts", []),
        },
    )
    _write_csv(candidate / "05-scenarios/fund-scenarios.csv", scenarios["fund_scenarios"])
    _write_csv(candidate / "05-scenarios/manager-scenarios.csv", scenarios["manager_scenarios"])
    _write_json(candidate / "05-scenarios/scenario-definitions.json", scenarios["definitions"])
    _write_json(candidate / "06-report/briefs.json", briefs)
    if model_previews:
        _write_json(candidate / "06-report/model-previews.json", model_previews)
    _write_stage_guides(candidate, include_cases)
    dashboard = render_dashboard(manifest, core, scenarios, case_bundle=case_bundle, briefs=briefs)
    (candidate / "06-report/dashboard.html").write_text(dashboard, encoding="utf-8", newline="\n")
    checks = _checks(
        parent,
        context,
        core,
        scenarios,
        manifest,
        case_bundle=case_bundle,
        model_previews=model_previews,
    )
    _write_csv(candidate / "06-report/checks.csv", checks)
    failures = [row for row in checks if row["status"] == "FAIL"]
    if failures:
        raise V2RunError("V2 checks failed: " + ",".join(row["check_id"] for row in failures))
    output_hashes = _output_hashes(candidate)
    report_material = {"v2_data_id": manifest["v2_data_id"], "dashboard": output_hashes.get("06-report/dashboard.html", ""), "briefs": output_hashes.get("06-report/briefs.json", ""), "include_cases": include_cases}
    report_id = hashlib.sha256(json.dumps(report_material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    receipt = {
        "status": "PASS",
        "v2_data_id": manifest["v2_data_id"],
        "v2_report_id": report_id,
        "v1_data_build_id": manifest["v1_data_build_id"],
        "v1_report_id": manifest["v1_report_id"],
        "policy_version": policy["version"],
        "include_cases": include_cases,
        "model_calls": "NOT_RUN",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checks": {"passed": len(checks), "failed": 0},
        "output_hashes": output_hashes,
        "limitations": [
            "Historical ranks are the unchanged V1 synthetic-manager performance screen.",
            "Named real-source evidence receives no numerical GP rank.",
            "Original fixture holding cost does not support realized-loss conclusions.",
            "Synthetic public benchmarks are USD; non-USD strategy PME is unavailable without a supported conversion or matched benchmark.",
            "Evidence readiness measures field support and is not investment quality.",
        ],
    }
    receipt_candidate = candidate / "receipt.json"
    _write_json(receipt_candidate, receipt)
    if v2_inputs.verify_fingerprints(manifest["fingerprints"], parent):
        raise V2RunError("input drift detected before publication")
    if v2_inputs.verify_baseline(parent, HERE):
        raise V2RunError("protected V1 or parent file changed before publication")
    _publish(candidate, receipt_candidate)
    print(f"PASS GP Scoring V2 data={manifest['v2_data_id']} report={report_id} funds={len(core['fund_diagnostics'])} ranked={sum(row.get('v1_status')=='RANKED_DEMO' for row in core['manager_diagnostics'])} cases={include_cases}")
    print(HERE / "06-report/dashboard.html")
    return 0


def _bundle_errors(root: Path) -> list[str]:
    errors: list[str] = []
    required = {
        "04-diagnostics/manifest.json", "04-diagnostics/coverage.csv", "04-diagnostics/fund-diagnostics.csv",
        "04-diagnostics/manager-diagnostics.csv", "04-diagnostics/cohort-membership.csv", "04-diagnostics/genealogy.csv",
        "04-diagnostics/evidence-readiness.csv", "04-diagnostics/decisions.csv", "04-diagnostics/evidence.json",
        "05-scenarios/fund-scenarios.csv", "05-scenarios/manager-scenarios.csv", "05-scenarios/scenario-definitions.json",
        "06-report/briefs.json", "06-report/dashboard.html", "06-report/checks.csv",
        *(f"{stage}/README.md" for stage in STAGES),
    }
    try:
        receipt = v2_inputs.read_json(root / "06-report/receipt.json")
        manifest = v2_inputs.read_json(root / "04-diagnostics/manifest.json")
        if receipt.get("include_cases"):
            required.add("06-report/model-previews.json")
        if receipt.get("status") != "PASS" or not receipt.get("v2_data_id") or receipt.get("v2_data_id") != manifest.get("v2_data_id"):
            errors.append("successful matching receipt required")
        hashes = receipt.get("output_hashes", {})
        if not required.issubset(hashes):
            errors.append("required output inventory incomplete")
        for relative, expected in hashes.items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file() or v2_inputs.sha256_file(path) != expected:
                errors.append(f"output differs: {relative}")
        checks = _read_csv(root / "06-report/checks.csv")
        count = 24 if receipt.get("include_cases") else 17
        if receipt.get("policy_version", "").startswith("2.2."):
            count += 3 if receipt.get("include_cases") else 2
        if len(checks) != count or len({row['check_id'] for row in checks}) != count or any(row.get("status") != "PASS" for row in checks) or receipt.get("checks") != {"passed": count, "failed": 0}:
            errors.append("release check record incomplete or failed")
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return errors + ["active bundle unreadable or incomplete"]


def check_only(parent: Path) -> int:
    receipt_path = HERE / "06-report/receipt.json"
    manifest_path = HERE / "04-diagnostics/manifest.json"
    errors: list[str] = _bundle_errors(HERE)
    if not receipt_path.is_file() or not manifest_path.is_file():
        print("FAIL V2 active receipt or manifest missing")
        return 1
    receipt = v2_inputs.read_json(receipt_path)
    manifest = v2_inputs.read_json(manifest_path)
    if receipt.get("status") != "PASS":
        errors.append(f"receipt status is {receipt.get('status')}")
    if receipt.get("v2_data_id") != manifest.get("v2_data_id"):
        errors.append("receipt/manifest data ID mismatch")
    errors.extend(v2_inputs.verify_baseline(parent, HERE))
    fingerprints = manifest.get("fingerprints", {})
    if not fingerprints or set(fingerprints) != {row['path'] for row in manifest.get('inputs', [])}:
        errors.append("input inventory missing or inconsistent")
    errors.extend(v2_inputs.verify_fingerprints(fingerprints, parent))
    expected_implementation = {path.relative_to(HERE).as_posix() for path in _implementation_files(bool(receipt.get('include_cases')))}
    if set(manifest.get('implementation', {})) != expected_implementation:
        errors.append("implementation inventory incomplete")
    for raw_path, expected in manifest.get("implementation", {}).items():
        path = HERE / raw_path
        if not path.is_file() or v2_inputs.sha256_file(path) != expected.get("sha256"):
            errors.append(f"implementation changed: {path}")
    for relative, expected in receipt.get("output_hashes", {}).items():
        path = HERE / relative
        if not path.is_file():
            errors.append(f"output missing: {relative}")
        elif v2_inputs.sha256_file(path) != expected:
            errors.append(f"output hash changed: {relative}")
    if errors:
        for error in errors[:20]:
            print("FAIL", error)
        return 1
    print(f"PASS GP Scoring V2 data={receipt['v2_data_id']} report={receipt['v2_report_id']} verified")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify the downstream GP Scoring V2 demonstration")
    parser.add_argument("--parent", default=".")
    parser.add_argument("--include-cases", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    parent = Path(args.parent).resolve()
    try:
        return check_only(parent) if args.check_only else build(parent, include_cases=args.include_cases)
    except (V2RunError, v2_inputs.V2InputError, v2_features.V2FeatureError, v2_stress.V2StressError, ValueError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
