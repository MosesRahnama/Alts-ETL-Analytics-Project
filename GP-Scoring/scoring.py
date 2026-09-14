from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping


class ScoringError(ValueError):
    pass


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoringError(f"{field} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise ScoringError(f"{field} is not finite")
    return result


def compute_multiples(period: Mapping[str, Any]) -> dict[str, float]:
    paid_in = _number(period.get("paid_in_capital_itd"), "paid_in_capital_itd")
    distributions = _number(period.get("distributions_itd"), "distributions_itd")
    nav = _number(period.get("nav"), "nav")
    if paid_in <= 0:
        raise ScoringError("paid_in_capital_itd must be positive")
    if distributions < 0 or nav < 0:
        raise ScoringError("distributions_itd and nav must be nonnegative")
    dpi = distributions / paid_in
    rvpi = nav / paid_in
    tvpi = dpi + rvpi
    total_value = distributions + nav
    nav_dependence = nav / total_value if total_value > 0 else math.nan
    return {
        "paid_in": paid_in,
        "distributions": distributions,
        "nav": nav,
        "dpi": dpi,
        "rvpi": rvpi,
        "tvpi": tvpi,
        "nav_dependence": nav_dependence,
    }


def midpoint_percentile(value: float, peers: Iterable[float]) -> float:
    values = [float(item) for item in peers]
    if not values:
        raise ScoringError("percentile requires at least one peer")
    below = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return 100.0 * (below + 0.5 * equal) / len(values)


def vintage_bucket(vintage_year: int, width: int) -> int:
    if width <= 0:
        raise ScoringError("vintage bucket width must be positive")
    return width * (int(vintage_year) // width)


def _partition(row: Mapping[str, Any]) -> tuple[str, str, str, str, int]:
    return (
        _text(row.get("strategy")),
        _text(row.get("currency")),
        _text(row.get("as_of_date")),
        _text(row.get("measurement_basis")),
        int(row["vintage_bucket"]),
    )


def _json_ids(values: Iterable[str]) -> str:
    return json.dumps(sorted(set(values)), separators=(",", ":"))


def _rank_rows(rows: list[dict[str, Any]], score_field: str, output_field: str) -> None:
    by_group: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if _text(row.get("status")) != "RANKED_DEMO":
            row[output_field] = ""
            continue
        by_group[
            (
                _text(row.get("strategy")),
                _text(row.get("as_of_date")),
                _text(row.get("measurement_basis")),
            )
        ].append(row)
    for group_rows in by_group.values():
        values = sorted({float(row[score_field]) for row in group_rows}, reverse=True)
        ranks = {value: 1 + sum(other > value for other in values) for value in values}
        for row in group_rows:
            row[output_field] = str(ranks[float(row[score_field])])


def score_fixture(
    selected_records: list[dict[str, Any]],
    fund_master: list[dict[str, str]],
    manager_master: list[dict[str, str]],
    policy: Mapping[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    bucket_width = int(policy["vintage_bucket_years"])
    min_maturity = int(policy["min_maturity_years"])
    peer_min_funds = int(policy["peer_min_funds"])
    peer_min_managers = int(policy["peer_min_managers"])
    w_tvpi = float(policy["weights"]["tvpi"])
    w_dpi = float(policy["weights"]["dpi"])
    if abs((w_tvpi + w_dpi) - 1.0) > 1e-12:
        raise ScoringError("baseline score weights must sum to one")
    nav_haircut = float(policy["nav_haircut"])
    if not 0 <= nav_haircut < 1:
        raise ScoringError("nav_haircut must be in [0, 1)")

    manager_names = {row["manager_id"]: row.get("manager_name", "") for row in manager_master}
    master_by_fund = {row["fund_id"]: row for row in fund_master}
    supplied_by_manager_strategy: Counter[tuple[str, str]] = Counter(
        (row.get("fund_manager_id", ""), row.get("strategy", ""))
        for row in fund_master
        if row.get("fund_manager_id", "")
    )

    base_rows: list[dict[str, Any]] = []
    input_decisions: dict[str, dict[str, str]] = {}
    for record in selected_records:
        fund_id = _text(record.get("fund_id"))
        manager_id = _text(record.get("manager_id"))
        strategy = _text(record.get("strategy"))
        decision = {
            "level": "fund",
            "record_id": fund_id,
            "status": "EXCLUDED",
            "primary_reason": "",
            "additional_reasons": "[]",
            "source_ids": _json_ids([_text(record.get("fund_period_id"))]),
            "evidence_ids": _json_ids([_text(record.get("evidence_id"))]),
        }
        reasons = list(record.get("input_reasons", []))
        if not bool(record.get("quality_approved")):
            reasons.append(_text(record.get("quality_reason")) or "QUALITY_NOT_APPROVED")
        try:
            vintage = int(_text(record.get("vintage_year")))
        except ValueError:
            vintage = 0
            reasons.append("VINTAGE_MISSING_OR_INVALID")
        try:
            as_of_year = int(_text(record.get("as_of_date"))[:4])
        except ValueError:
            as_of_year = 0
            reasons.append("AS_OF_DATE_INVALID")
        if vintage and as_of_year and as_of_year - vintage < min_maturity:
            reasons.append("MINIMUM_MATURITY_NOT_MET")
        if manager_id not in manager_names:
            reasons.append("MANAGER_UNRESOLVED")
        if fund_id not in master_by_fund:
            reasons.append("FUND_ID_UNRESOLVED")

        metrics: dict[str, float] | None = None
        if not reasons:
            try:
                metrics = compute_multiples(record)
            except ScoringError as exc:
                reasons.append(f"FINANCE_INVALID:{exc}")
        if reasons:
            decision["primary_reason"] = reasons[0]
            decision["additional_reasons"] = json.dumps(reasons[1:], separators=(",", ":"))
            input_decisions[fund_id] = decision
            continue

        assert metrics is not None
        row = dict(record)
        row.update(metrics)
        row["vintage_bucket"] = vintage_bucket(vintage, bucket_width)
        row["measurement_basis"] = _text(record.get("measurement_basis")) or "synthetic_basis_unspecified"
        row["baseline_peer_ids"] = []
        row["status"] = "BASE_ELIGIBLE"
        base_rows.append(row)
        decision["status"] = "SELECTED"
        decision["primary_reason"] = "BASE_ELIGIBLE"
        input_decisions[fund_id] = decision

    groups: dict[tuple[str, str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in base_rows:
        groups[_partition(row)].append(row)

    feature_rows: list[dict[str, str]] = []
    feature_by_fund: dict[str, dict[str, str]] = {}
    for row in sorted(base_rows, key=lambda item: item["fund_id"]):
        peers = [peer for peer in groups[_partition(row)] if peer["manager_id"] != row["manager_id"]]
        peer_managers = {peer["manager_id"] for peer in peers}
        fund_id = row["fund_id"]
        if len(peers) < peer_min_funds or len(peer_managers) < peer_min_managers:
            input_decisions[fund_id]["status"] = "EXCLUDED"
            input_decisions[fund_id]["primary_reason"] = "PEERS_INSUFFICIENT"
            input_decisions[fund_id]["additional_reasons"] = json.dumps(
                [f"peer_funds={len(peers)}", f"peer_managers={len(peer_managers)}"],
                separators=(",", ":"),
            )
            status = "PEERS_INSUFFICIENT"
            tvpi_pct = dpi_pct = fund_score = nav_score = math.nan
            peer_ids: list[str] = [peer["fund_id"] for peer in peers]
        else:
            peer_ids = [peer["fund_id"] for peer in peers]
            tvpi_pct = midpoint_percentile(row["tvpi"], [peer["tvpi"] for peer in peers])
            dpi_pct = midpoint_percentile(row["dpi"], [peer["dpi"] for peer in peers])
            fund_score = w_tvpi * tvpi_pct + w_dpi * dpi_pct
            scenario_tvpi = row["dpi"] + (1.0 - nav_haircut) * row["rvpi"]
            scenario_tvpi_pct = midpoint_percentile(scenario_tvpi, [peer["tvpi"] for peer in peers])
            nav_score = w_tvpi * scenario_tvpi_pct + w_dpi * dpi_pct
            status = "RANKABLE_FUND"
            input_decisions[fund_id]["primary_reason"] = "RANKABLE_FUND"
        scenario_tvpi = row["dpi"] + (1.0 - nav_haircut) * row["rvpi"]
        values = {
            "population": _text(row.get("population")),
            "fund_id": fund_id,
            "manager_id": _text(row.get("manager_id")),
            "manager_name": manager_names.get(_text(row.get("manager_id")), ""),
            "fund_period_id": _text(row.get("fund_period_id")),
            "strategy": _text(row.get("strategy")),
            "currency": _text(row.get("currency")),
            "vintage_year": _text(row.get("vintage_year")),
            "vintage_bucket": str(row["vintage_bucket"]),
            "as_of_date": _text(row.get("as_of_date")),
            "measurement_basis": _text(row.get("measurement_basis")),
            "paid_in": f"{row['paid_in']:.12g}",
            "distributions": f"{row['distributions']:.12g}",
            "nav": f"{row['nav']:.12g}",
            "dpi": f"{row['dpi']:.12g}",
            "rvpi": f"{row['rvpi']:.12g}",
            "tvpi": f"{row['tvpi']:.12g}",
            "nav_dependence": "" if math.isnan(row["nav_dependence"]) else f"{row['nav_dependence']:.12g}",
            "tvpi_percentile": "" if math.isnan(tvpi_pct) else f"{tvpi_pct:.12g}",
            "dpi_percentile": "" if math.isnan(dpi_pct) else f"{dpi_pct:.12g}",
            "peer_count": str(len(peers)),
            "peer_manager_count": str(len(peer_managers)),
            "peer_fund_ids": _json_ids(peer_ids),
            "fund_score": "" if math.isnan(fund_score) else f"{fund_score:.12g}",
            "nav_haircut": f"{nav_haircut:.12g}",
            "scenario_tvpi": f"{scenario_tvpi:.12g}",
            "scenario_score": "" if math.isnan(nav_score) else f"{nav_score:.12g}",
            "evidence_ids": _json_ids([_text(row.get("evidence_id"))]),
            "status": status,
        }
        for scenario in policy.get("weight_scenarios", []):
            name = _text(scenario.get("name"))
            wt = float(scenario["tvpi"])
            wd = float(scenario["dpi"])
            if abs((wt + wd) - 1.0) > 1e-12:
                raise ScoringError(f"weight scenario {name} does not sum to one")
            values[f"score_{name}"] = (
                "" if math.isnan(tvpi_pct) else f"{(wt * tvpi_pct + wd * dpi_pct):.12g}"
            )
        feature_rows.append(values)
        feature_by_fund[fund_id] = values

    current_by_manager_strategy: Counter[tuple[str, str]] = Counter(
        (_text(row.get("manager_id")), _text(row.get("strategy"))) for row in selected_records
    )
    eligible_by_manager_strategy: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in feature_rows:
        if row["status"] == "RANKABLE_FUND":
            eligible_by_manager_strategy[(row["manager_id"], row["strategy"])].append(row)

    manager_keys = sorted(
        key for key in supplied_by_manager_strategy if key[0] in manager_names
    )
    scorecards: list[dict[str, Any]] = []
    manager_decisions: list[dict[str, str]] = []
    for manager_id, strategy in manager_keys:
        total = supplied_by_manager_strategy[(manager_id, strategy)]
        current = current_by_manager_strategy[(manager_id, strategy)]
        eligible = eligible_by_manager_strategy.get((manager_id, strategy), [])
        eligible_count = len({row["fund_id"] for row in eligible})
        coverage = eligible_count / total if total else 0.0
        status = (
            "RANKED_DEMO"
            if eligible_count >= int(policy["manager_min_funds"])
            and coverage >= float(policy["manager_min_coverage"])
            else ("PARTIAL_TRACK_RECORD" if eligible_count else "INSUFFICIENT_DATA")
        )
        scores = [float(row["fund_score"]) for row in eligible]
        tvpi_pcts = [float(row["tvpi_percentile"]) for row in eligible]
        dpi_pcts = [float(row["dpi_percentile"]) for row in eligible]
        scenario_scores = [float(row["scenario_score"]) for row in eligible]
        raw_score = sum(scores) / eligible_count if eligible_count else math.nan
        raw_scenario_score = sum(scenario_scores) / eligible_count if eligible_count else math.nan
        score = raw_score if status == "RANKED_DEMO" else math.nan
        scenario_score = raw_scenario_score if status == "RANKED_DEMO" else math.nan
        as_of_values = sorted({_text(row.get("as_of_date")) for row in eligible})
        basis_values = sorted({_text(row.get("measurement_basis")) for row in eligible})
        row: dict[str, Any] = {
            "population": _text(eligible[0].get("population")) if eligible else "fixture",
            "manager_id": manager_id,
            "manager_name": manager_names.get(manager_id, ""),
            "strategy": strategy,
            "as_of_date": as_of_values[0] if len(as_of_values) == 1 else "",
            "measurement_basis": basis_values[0] if len(basis_values) == 1 else "synthetic_basis_unspecified",
            "total_funds": str(total),
            "current_date_funds": str(current),
            "eligible_funds": str(eligible_count),
            "stale_or_missing_date_funds": str(max(total - current, 0)),
            "excluded_current_funds": str(max(current - eligible_count, 0)),
            "coverage": f"{coverage:.12g}",
            "constituent_fund_ids": _json_ids([item["fund_id"] for item in eligible]),
            "avg_tvpi_percentile": "" if not eligible_count else f"{sum(tvpi_pcts) / eligible_count:.12g}",
            "avg_dpi_percentile": "" if not eligible_count else f"{sum(dpi_pcts) / eligible_count:.12g}",
            "score": "" if math.isnan(score) else f"{score:.12g}",
            "rank": "",
            "fund_score_min": "" if not scores else f"{min(scores):.12g}",
            "fund_score_max": "" if not scores else f"{max(scores):.12g}",
            "scenario_score": "" if math.isnan(scenario_score) else f"{scenario_score:.12g}",
            "scenario_rank": "",
            "score_change_nav_haircut": "" if math.isnan(score) else f"{scenario_score - score:.12g}",
            "status": status,
            "reasons": "[]",
        }
        reasons: list[str] = []
        if eligible_count < int(policy["manager_min_funds"]):
            reasons.append("MANAGER_MIN_FUNDS_NOT_MET")
        if coverage < float(policy["manager_min_coverage"]):
            reasons.append("MANAGER_COVERAGE_NOT_MET")
        row["reasons"] = json.dumps(reasons, separators=(",", ":"))
        for scenario in policy.get("weight_scenarios", []):
            name = _text(scenario.get("name"))
            values = [float(item[f"score_{name}"]) for item in eligible]
            row[f"score_{name}"] = (
                "" if status != "RANKED_DEMO" or not values else f"{sum(values) / len(values):.12g}"
            )
            row[f"rank_{name}"] = ""
        scorecards.append(row)
        manager_decisions.append(
            {
                "level": "manager_strategy",
                "record_id": f"{manager_id}|{strategy}",
                "status": status,
                "primary_reason": status,
                "additional_reasons": row["reasons"],
                "source_ids": row["constituent_fund_ids"],
                "evidence_ids": "[]",
            }
        )

    _rank_rows(scorecards, "score", "rank")
    _rank_rows(scorecards, "scenario_score", "scenario_rank")
    for scenario in policy.get("weight_scenarios", []):
        name = _text(scenario.get("name"))
        _rank_rows(scorecards, f"score_{name}", f"rank_{name}")

    fund_decisions = [input_decisions[key] for key in sorted(input_decisions)]
    all_decisions = fund_decisions + manager_decisions
    return feature_rows, [{k: str(v) for k, v in row.items()} for row in scorecards], all_decisions


def scorecard_reconciliation_errors(
    features: list[Mapping[str, str]], scorecards: list[Mapping[str, str]], policy: Mapping[str, Any]
) -> list[str]:
    by_fund = {row["fund_id"]: row for row in features}
    errors: list[str] = []
    for card in scorecards:
        if card.get("status") != "RANKED_DEMO":
            continue
        fund_ids = json.loads(card["constituent_fund_ids"])
        rows = [by_fund[fund_id] for fund_id in fund_ids]
        expected = sum(float(row["fund_score"]) for row in rows) / len(rows)
        if abs(expected - float(card["score"])) > 1e-9:
            errors.append(f"{card['manager_id']} score does not reconcile")
        expected_tvpi = sum(float(row["tvpi_percentile"]) for row in rows) / len(rows)
        expected_dpi = sum(float(row["dpi_percentile"]) for row in rows) / len(rows)
        if abs(expected_tvpi - float(card["avg_tvpi_percentile"])) > 1e-9:
            errors.append(f"{card['manager_id']} TVPI component does not reconcile")
        if abs(expected_dpi - float(card["avg_dpi_percentile"])) > 1e-9:
            errors.append(f"{card['manager_id']} DPI component does not reconcile")
        weighted = float(policy["weights"]["tvpi"]) * expected_tvpi + float(policy["weights"]["dpi"]) * expected_dpi
        if abs(weighted - float(card["score"])) > 1e-9:
            errors.append(f"{card['manager_id']} weighted components do not reconcile")
    return errors
