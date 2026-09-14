from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Mapping, Sequence

from scoring import midpoint_percentile


class V2StressError(ValueError):
    pass


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rank(rows: list[dict[str, Any]], score_field: str, rank_field: str) -> None:
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get(score_field) is not None:
            by_strategy[str(row.get("strategy", ""))].append(row)
    for group in by_strategy.values():
        ordered = sorted(group, key=lambda row: (-float(row[score_field]), str(row.get("manager_id", ""))))
        prior_score = None
        prior_rank = 0
        for position, row in enumerate(ordered, 1):
            score = float(row[score_field])
            if prior_score is None or abs(score - prior_score) > 1e-12:
                prior_rank = position
                prior_score = score
            row[rank_field] = prior_rank


def _fund_score_for_tvpi(v1: Mapping[str, str], peer_rows: Sequence[Mapping[str, str]], stressed_tvpi: float, tvpi_weight: float = 0.6, dpi_weight: float = 0.4) -> float:
    peer_values = [float(row["tvpi"]) for row in peer_rows]
    tvpi_pct = midpoint_percentile(stressed_tvpi, peer_values)
    dpi_pct = float(v1["dpi_percentile"])
    return tvpi_weight * tvpi_pct + dpi_weight * dpi_pct


def build_scenarios(context: Mapping[str, Any], core: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = {row["fund_id"]: row for row in core["fund_diagnostics"]}
    v1_features = {row["fund_id"]: row for row in context["v1"]["features"]}
    v1_scorecards = context["v1"]["scorecards"]
    peer_rows_by_fund: dict[str, list[Mapping[str, str]]] = {}
    for fund_id, row in v1_features.items():
        peers = json.loads(row.get("peer_fund_ids", "[]"))
        peer_rows_by_fund[fund_id] = [v1_features[peer] for peer in peers if peer in v1_features]

    fund_rows: list[dict[str, Any]] = []
    manager_rows: list[dict[str, Any]] = []
    nav_haircuts = [float(value) for value in context["policy"]["stress"]["nav_haircuts"]]
    fund_scenario_score: dict[tuple[str, str], float] = {}
    for fund_id, v1 in v1_features.items():
        if not v1.get("fund_score"):
            continue
        dpi = float(v1["dpi"])
        rvpi = float(v1["rvpi"])
        peers = peer_rows_by_fund[fund_id]
        for haircut in nav_haircuts:
            stressed_tvpi = dpi + (1.0 - haircut) * rvpi
            score = _fund_score_for_tvpi(v1, peers, stressed_tvpi)
            scenario_id = f"nav_{int(round(haircut * 100)):02d}"
            fund_scenario_score[(fund_id, scenario_id)] = score
            fund_rows.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_type": "nav_haircut",
                    "fund_id": fund_id,
                    "manager_id": v1["manager_id"],
                    "strategy": v1["strategy"],
                    "baseline_score": float(v1["fund_score"]),
                    "scenario_score": score,
                    "baseline_tvpi": float(v1["tvpi"]),
                    "scenario_tvpi": stressed_tvpi,
                    "haircut": haircut,
                    "official_eligibility": "same_as_baseline",
                    "affected_ids": "[]",
                }
            )

    ranked_cards = [row for row in v1_scorecards if row.get("status") == "RANKED_DEMO"]
    for haircut in nav_haircuts:
        scenario_id = f"nav_{int(round(haircut * 100)):02d}"
        scenario_managers: list[dict[str, Any]] = []
        for card in ranked_cards:
            fund_ids = list(json.loads(card["constituent_fund_ids"]))
            scores = [fund_scenario_score[(fund_id, scenario_id)] for fund_id in fund_ids if (fund_id, scenario_id) in fund_scenario_score]
            if len(scores) != len(fund_ids):
                continue
            scenario_managers.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_type": "nav_haircut",
                    "manager_id": card["manager_id"],
                    "manager_name": card["manager_name"],
                    "strategy": card["strategy"],
                    "baseline_score": float(card["score"]),
                    "baseline_rank": int(card["rank"]),
                    "scenario_score": sum(scores) / len(scores),
                    "scenario_rank": None,
                    "official_eligible": True,
                    "removed_fund_id": "",
                }
            )
        _rank(scenario_managers, "scenario_score", "scenario_rank")
        manager_rows.extend(scenario_managers)

    weight_scenarios = context["policy"]["stress"]["weight_scenarios"]
    for spec in weight_scenarios:
        scenario_id = str(spec["id"])
        tw = float(spec["tvpi"])
        dw = float(spec["dpi"])
        weighted_funds: dict[str, float] = {}
        for fund_id, v1 in v1_features.items():
            if not v1.get("fund_score"):
                continue
            score = tw * float(v1["tvpi_percentile"]) + dw * float(v1["dpi_percentile"])
            weighted_funds[fund_id] = score
            fund_rows.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_type": "weight_policy",
                    "fund_id": fund_id,
                    "manager_id": v1["manager_id"],
                    "strategy": v1["strategy"],
                    "baseline_score": float(v1["fund_score"]),
                    "scenario_score": score,
                    "baseline_tvpi": float(v1["tvpi"]),
                    "scenario_tvpi": float(v1["tvpi"]),
                    "haircut": 0.0,
                    "official_eligibility": "same_as_baseline",
                    "affected_ids": "[]",
                }
            )
        scenario_managers = []
        for card in ranked_cards:
            fund_ids = list(json.loads(card["constituent_fund_ids"]))
            scores = [weighted_funds[fund_id] for fund_id in fund_ids if fund_id in weighted_funds]
            if len(scores) != len(fund_ids):
                continue
            scenario_managers.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_type": "weight_policy",
                    "manager_id": card["manager_id"],
                    "manager_name": card["manager_name"],
                    "strategy": card["strategy"],
                    "baseline_score": float(card["score"]),
                    "baseline_rank": int(card["rank"]),
                    "scenario_score": sum(scores) / len(scores),
                    "scenario_rank": None,
                    "official_eligible": True,
                    "removed_fund_id": "",
                }
            )
        _rank(scenario_managers, "scenario_score", "scenario_rank")
        manager_rows.extend(scenario_managers)

    membership: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in core["cohort_membership"]:
        membership[(row["evaluated_fund_id"], row["policy_id"])].append(row["peer_fund_id"])
    for policy_id, min_funds, min_managers in (
        ("strict_20_10", int(context["policy"]["cohorts"]["strict_min_funds"]), int(context["policy"]["cohorts"]["strict_min_managers"])),
        ("size_bands", int(context["policy"]["cohorts"]["reference_min_funds"]), int(context["policy"]["cohorts"]["reference_min_managers"])),
    ):
        policy_fund_scores: dict[str, float] = {}
        for fund_id, v1 in v1_features.items():
            peers = json.loads(v1.get("peer_fund_ids", "[]")) if policy_id == "strict_20_10" else membership.get((fund_id, "size_bands"), [])
            if context["policy"]["cohorts"]["match_sub_strategy"]:
                peers = [peer for peer in peers if context["fund_by_id"][peer].get("sub_strategy") == context["fund_by_id"][fund_id].get("sub_strategy")]
            peer_managers = {v1_features[p]["manager_id"] for p in peers if p in v1_features}
            if len(peers) < min_funds or len(peer_managers) < min_managers:
                continue
            tvpi_pct = midpoint_percentile(float(v1["tvpi"]), [float(v1_features[p]["tvpi"]) for p in peers])
            dpi_pct = midpoint_percentile(float(v1["dpi"]), [float(v1_features[p]["dpi"]) for p in peers])
            score = 0.6 * tvpi_pct + 0.4 * dpi_pct
            policy_fund_scores[fund_id] = score
            fund_rows.append(
                {
                    "scenario_id": policy_id,
                    "scenario_type": "peer_policy",
                    "fund_id": fund_id,
                    "manager_id": v1["manager_id"],
                    "strategy": v1["strategy"],
                    "baseline_score": float(v1["fund_score"]),
                    "scenario_score": score,
                    "baseline_tvpi": float(v1["tvpi"]),
                    "scenario_tvpi": float(v1["tvpi"]),
                    "haircut": 0.0,
                    "official_eligibility": "alternative_policy",
                    "affected_ids": json.dumps(peers, separators=(",", ":")),
                }
            )
        scenario_managers = []
        for card in ranked_cards:
            fund_ids = list(json.loads(card["constituent_fund_ids"]))
            scores = [policy_fund_scores[fund_id] for fund_id in fund_ids if fund_id in policy_fund_scores]
            coverage = len(scores) / int(card["total_funds"]) if int(card["total_funds"]) else 0.0
            eligible = len(scores) >= 2 and coverage >= 0.75
            scenario_managers.append(
                {
                    "scenario_id": policy_id,
                    "scenario_type": "peer_policy",
                    "manager_id": card["manager_id"],
                    "manager_name": card["manager_name"],
                    "strategy": card["strategy"],
                    "baseline_score": float(card["score"]),
                    "baseline_rank": int(card["rank"]),
                    "scenario_score": (sum(scores) / len(scores)) if eligible else None,
                    "scenario_rank": None,
                    "official_eligible": eligible,
                    "removed_fund_id": "",
                }
            )
        _rank(scenario_managers, "scenario_score", "scenario_rank")
        manager_rows.extend(scenario_managers)

    for removal in ("best", "worst"):
        scenario_id = f"remove_{removal}"
        scenario_managers = []
        for card in ranked_cards:
            fund_ids = list(json.loads(card["constituent_fund_ids"]))
            scores = [(fund_id, float(v1_features[fund_id]["fund_score"])) for fund_id in fund_ids if fund_id in v1_features and v1_features[fund_id].get("fund_score")]
            if len(scores) < 2:
                continue
            removed = max(scores, key=lambda item: (item[1], item[0])) if removal == "best" else min(scores, key=lambda item: (item[1], item[0]))
            remaining = [score for fund_id, score in scores if fund_id != removed[0]]
            coverage = len(remaining) / int(card["total_funds"]) if int(card["total_funds"]) else 0.0
            eligible = len(remaining) >= 2 and coverage >= 0.75
            scenario_managers.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_type": "leave_one_out",
                    "manager_id": card["manager_id"],
                    "manager_name": card["manager_name"],
                    "strategy": card["strategy"],
                    "baseline_score": float(card["score"]),
                    "baseline_rank": int(card["rank"]),
                    "scenario_score": (sum(remaining) / len(remaining)) if remaining else None,
                    "scenario_rank": None,
                    "official_eligible": eligible,
                    "removed_fund_id": removed[0],
                    "counterfactual_score": (sum(remaining) / len(remaining)) if remaining else None,
                }
            )
        eligible_rows = [row for row in scenario_managers if row["official_eligible"]]
        _rank(eligible_rows, "scenario_score", "scenario_rank")
        manager_rows.extend(scenario_managers)

    for scenario_id, mode in (("top3_20", "top3"), ("largest_sector_20", "sector")):
        haircut = float(context["policy"]["stress"]["top3_haircut"] if mode == "top3" else context["policy"]["stress"]["sector_haircut"])
        scores_by_fund: dict[str, float] = {}
        for fund_id, v1 in v1_features.items():
            current = context["current_by_fund"].get(fund_id)
            holdings = context["holdings_by_fund"].get(fund_id, [])
            if not current or not holdings or not v1.get("fund_score") or diagnostics.get(fund_id, {}).get("holdings_status") != "AVAILABLE":
                continue
            nav = float(current["nav"])
            paid = float(current["paid_in_capital_itd"])
            distributions = float(current["distributions_itd"])
            company: dict[str, float] = defaultdict(float)
            sector: dict[str, float] = defaultdict(float)
            ids_by_company: dict[str, list[str]] = defaultdict(list)
            ids_by_sector: dict[str, list[str]] = defaultdict(list)
            for holding in holdings:
                value = float(holding["fair_value"])
                company_id = holding.get("portfolio_company_id", "") or holding["holding_id"]
                sector_id = holding.get("sector", "") or "UNKNOWN"
                company[company_id] += value
                sector[sector_id] += value
                ids_by_company[company_id].append(holding["holding_id"])
                ids_by_sector[sector_id].append(holding["holding_id"])
            if mode == "top3":
                selected = [key for key, _ in sorted(company.items(), key=lambda item: (-item[1], item[0]))[:3]]
                affected = sum(company[key] for key in selected)
                affected_ids = sorted({hold for key in selected for hold in ids_by_company[key]})
            else:
                selected_sector = max(sector, key=lambda key: (sector[key], key))
                affected = sector[selected_sector]
                affected_ids = sorted(ids_by_sector[selected_sector])
            stressed_nav = nav - haircut * affected
            if stressed_nav < -1e-8:
                raise V2StressError(f"portfolio shock creates negative NAV for {fund_id}")
            stressed_tvpi = (distributions + max(stressed_nav, 0.0)) / paid
            score = _fund_score_for_tvpi(v1, peer_rows_by_fund[fund_id], stressed_tvpi)
            scores_by_fund[fund_id] = score
            fund_rows.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_type": "portfolio_haircut",
                    "fund_id": fund_id,
                    "manager_id": v1["manager_id"],
                    "strategy": v1["strategy"],
                    "baseline_score": float(v1["fund_score"]),
                    "scenario_score": score,
                    "baseline_tvpi": float(v1["tvpi"]),
                    "scenario_tvpi": stressed_tvpi,
                    "haircut": haircut,
                    "official_eligibility": "same_as_baseline",
                    "affected_ids": json.dumps(affected_ids, separators=(",", ":")),
                }
            )
        scenario_managers = []
        for card in ranked_cards:
            fund_ids = list(json.loads(card["constituent_fund_ids"]))
            scores = [scores_by_fund[fund_id] for fund_id in fund_ids if fund_id in scores_by_fund]
            if len(scores) != len(fund_ids):
                continue
            scenario_managers.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_type": "portfolio_haircut",
                    "manager_id": card["manager_id"],
                    "manager_name": card["manager_name"],
                    "strategy": card["strategy"],
                    "baseline_score": float(card["score"]),
                    "baseline_rank": int(card["rank"]),
                    "scenario_score": sum(scores) / len(scores),
                    "scenario_rank": None,
                    "official_eligible": True,
                    "removed_fund_id": "",
                }
            )
        _rank(scenario_managers, "scenario_score", "scenario_rank")
        manager_rows.extend(scenario_managers)

    definitions = {
        "nav_00/nav_10/nav_20/nav_30": "Reduce remaining NAV by the named percentage; distributions and paid-in stay fixed; baseline peer distributions stay fixed.",
        "w50_50/w60_40/w70_30": "Reweight existing TVPI/DPI percentiles only.",
        "strict_20_10": "Use the V1 peer definition but require at least 20 peer funds and 10 other managers.",
        "size_bands": f"Comparison uses {context['policy']['cohorts']['size_band_count']} fund-size groups within the reference currency and vintage groups; minimum {context['policy']['cohorts']['reference_min_funds']} funds and {context['policy']['cohorts']['reference_min_managers']} other managers; sub-strategy match {context['policy']['cohorts']['match_sub_strategy']}.",
        "remove_best/remove_worst": "Remove one constituent fund and retain the original manager-series denominator and eligibility rules.",
        "top3_20": "Reduce the three largest current company exposures by 20 percent and reconcile the change to NAV.",
        "largest_sector_20": "Reduce the largest current sector exposure by 20 percent and reconcile the change to NAV.",
    }
    evidence = []
    for level, rows in (("fund", fund_rows), ("manager", manager_rows)):
        for row in rows:
            identity = row.get("fund_id") if level == "fund" else f"{row['manager_id']}:{row['strategy']}"
            row["evidence_id"] = f"SCENARIO:{level}:{identity}:{row['scenario_id']}"
            evidence.append({"feature_id": row["evidence_id"], "feature": "scenario", "values": dict(row),
                             "input_ids": [f"F:{identity}:DIAGNOSTICS"] if level == "fund" else [f"MANAGER:{identity}:V2"],
                             "formula_id": "v2_stress.build_scenarios", "assumptions": context["policy"]["stress"],
                             "cohort_policy": context["policy"]["cohorts"], "population": "fixture"})
    return {"fund_scenarios": fund_rows, "manager_scenarios": manager_rows, "definitions": definitions, "evidence": evidence}
