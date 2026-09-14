from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from scoring import midpoint_percentile  # noqa: E402
from src.analytics.run_round04_analytics import calculate_pme_results  # noqa: E402
from src.common.finance import xirr  # noqa: E402
from v2_inputs import quality_approval_for_ids, read_csv, term_applies  # noqa: E402


class V2FeatureError(ValueError):
    pass


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> float | None:
    text = _text(value)
    if not text:
        return None
    try:
        value_float = float(text)
    except ValueError:
        return None
    return value_float if math.isfinite(value_float) else None


def _date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _add_years(moment: date, years: int) -> date:
    try:
        return moment.replace(year=moment.year + years)
    except ValueError:
        return moment.replace(year=moment.year + years, day=28)


def _q(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return ordered[lo]
    weight = position - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _mean(values: Iterable[float | None]) -> float | None:
    selected = [value for value in values if value is not None and math.isfinite(value)]
    return statistics.fmean(selected) if selected else None


def _fmt(value: float | None) -> str:
    return "" if value is None or not math.isfinite(value) else format(value, ".12g")


def _json(values: Iterable[str]) -> str:
    return json.dumps(list(values), separators=(",", ":"))


def _vintage_bucket(vintage: int, years: int) -> int:
    return years * (vintage // years)


def period_reason(context: Mapping[str, Any], row: Mapping[str, Any] | None, approval: Mapping[str, tuple[bool, str]] | None = None) -> str:
    if row is None:
        return "NO_COMMON_DATE_RECORD"
    if not context["available_period"](row):
        return "REPORT_UNAVAILABLE_AT_CUTOFF"
    if row.get("input_reasons"):
        return "INPUT_CHECK_FAILED"
    approved = row.get("quality_approved")
    if approved is None:
        approved = (approval or {}).get(row.get("fund_period_id", ""), (False, ""))[0]
    if approved is not True:
        return "QUALITY_UNAVAILABLE"
    if not row.get("currency"):
        return "CURRENCY_UNAVAILABLE"
    return ""


def build_initial_coverage(context: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    coverage: list[dict[str, str]] = []
    decisions: list[dict[str, str]] = []
    current = context["current_by_fund"]
    metric_index = context["metric_index"]
    benchmark_currency = context["benchmark_currency"]
    mapped = context["strategy_benchmark"]
    for fund in sorted(context["fund_master"], key=lambda row: row["fund_id"]):
        fund_id = fund["fund_id"]
        period = current.get(fund_id)
        reasons: list[str] = []
        if period is None:
            status = "EXCLUDED"
            reasons.append("NO_COMMON_DATE_RECORD")
        elif period_reason(context, period):
            status = "EXCLUDED"
            reasons.append(period_reason(context, period))
        else:
            status = "AVAILABLE"
        decisions.append(
            {
                "level": "fund",
                "entity_id": fund_id,
                "status": status,
                "primary_reason": reasons[0] if reasons else "CURRENT_RECORD_AVAILABLE",
                "additional_reasons": _json(reasons[1:]),
                "population": "fixture",
            }
        )
        fields = {
            "current_period": (status, reasons[0] if reasons else ""),
            "xirr": (
                "AVAILABLE" if period and "xirr" in metric_index.get(period["fund_period_id"], {}) else "UNKNOWN",
                "" if period else "NO_CURRENT_PERIOD",
            ),
            "holdings": (
                "AVAILABLE" if context["holdings_by_fund"].get(fund_id) else "UNKNOWN",
                "",
            ),
            "base_terms": (
                "AVAILABLE" if fund_id in context["base_term_by_fund"] else "UNKNOWN",
                "",
            ),
            "economic_loss": ("UNSUPPORTED_DEFINITION", "SNAPSHOT_COST_IS_NOT_INVESTED_COST_LEDGER"),
            "geography_concentration": ("AVAILABLE_CONSTANT", "PARENT_FIXTURE_GEOGRAPHY_IS_NORTH_AMERICA"),
        }
        benchmark_id = mapped.get(fund.get("strategy", ""), "")
        if period and benchmark_id:
            if benchmark_currency.get(benchmark_id) == period.get("currency"):
                fields["strategy_pme"] = ("AVAILABLE", "")
            else:
                fields["strategy_pme"] = ("UNSUPPORTED_DEFINITION", "BENCHMARK_CURRENCY_UNSUPPORTED")
        else:
            fields["strategy_pme"] = ("UNKNOWN", "BENCHMARK_MAPPING_MISSING")
        for field_name, (field_status, reason) in fields.items():
            coverage.append(
                {
                    "entity_level": "fund",
                    "entity_id": fund_id,
                    "strategy": fund.get("strategy", ""),
                    "sub_strategy": fund.get("sub_strategy", ""),
                    "field_name": field_name,
                    "status": field_status,
                    "reason": reason,
                    "population": "fixture",
                }
            )
    for manager in sorted(context["manager_master"], key=lambda row: row["manager_id"]):
        for field_name in ("team_continuity", "gp_commitment_pct", "governance_event"):
            coverage.append(
                {
                    "entity_level": "manager",
                    "entity_id": manager["manager_id"],
                    "strategy": "",
                    "sub_strategy": "",
                    "field_name": field_name,
                    "status": "UNKNOWN",
                    "reason": "CORE_FIXTURE_HAS_NO_EVENT_LEVEL_SUPPORT",
                    "population": "fixture",
                }
            )
    return coverage, decisions


def strategy_pme(context: Mapping[str, Any]) -> tuple[dict[str, dict[str, dict[str, str]]], list[dict[str, str]]]:
    mapped = context["strategy_benchmark"]
    benchmark_currency = context["benchmark_currency"]
    current = [row for row in context["current_records"] if not period_reason(context, row)]
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    unsupported: list[dict[str, str]] = []
    for period in current:
        fund = context["fund_by_id"][period["fund_id"]]
        benchmark_id = mapped.get(fund.get("strategy", ""), "")
        if not benchmark_id:
            unsupported.append({"fund_id": period["fund_id"], "status": "BENCHMARK_MAPPING_MISSING"})
            continue
        if benchmark_currency.get(benchmark_id) != period.get("currency"):
            unsupported.append({"fund_id": period["fund_id"], "status": "BENCHMARK_CURRENCY_UNSUPPORTED"})
            continue
        groups[benchmark_id].append(period)

    output: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for benchmark_id, periods in sorted(groups.items()):
        fund_ids = {row["fund_id"] for row in periods}
        period_ids = {row["fund_period_id"] for row in periods}
        flows = [row for row in context["whole_cashflows"] if row.get("fund_id") in fund_ids]
        quality = [row for row in context["quality_subset"] if row.get("record_id") in period_ids]
        rows = calculate_pme_results(
            periods,
            flows,
            context["benchmarks"],
            quality,
            benchmark_id=benchmark_id,
            strict_quality=True,
            canonical_strategy_by_fund=None,
        )
        for row in rows:
            fund_id = row["entity_id"]
            row = dict(row)
            row["benchmark_selection"] = "v2_explicit_fixture_strategy_mapping"
            output[fund_id][row["metric_id"]] = row
    return output, unsupported


def trailing_returns(context: Mapping[str, Any]) -> dict[str, dict[int, dict[str, Any]]]:
    years_list = [int(value) for value in context["policy"]["returns"]["trailing_years"]]
    current_date = _date(context["policy"]["economic_as_of"])
    assert current_date is not None
    opening_dates = {_add_years(current_date, -years).isoformat() for years in years_list}
    approval_ids = {row["fund_period_id"] for rows in context["periods_by_fund"].values() for row in rows if row.get("as_of_date") in opening_dates and row.get("quality_approved") is None}
    approval = quality_approval_for_ids(context, approval_ids)
    output: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for fund_id, current in context["current_by_fund"].items():
        closing_nav = _number(current.get("nav"))
        currency = current.get("currency", "")
        period_by_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for period in context["periods_by_fund"].get(fund_id, []):
            period_by_date[period.get("as_of_date", "")].append(period)
        for years in years_list:
            reason = period_reason(context, current)
            if reason or closing_nav is None or closing_nav < 0 or current.get("as_of_date") != current_date.isoformat():
                output[fund_id][years] = {"status": "CLOSING_" + (reason or "NAV_OR_DATE_INVALID")}
                continue
            if len(period_by_date.get(current_date.isoformat(), [])) > 1:
                output[fund_id][years] = {"status": "CLOSING_PERIOD_CONFLICT"}
                continue
            opening_date = _add_years(current_date, -years)
            candidates = period_by_date.get(opening_date.isoformat(), [])
            if len(candidates) != 1:
                output[fund_id][years] = {"status": "OPENING_PERIOD_CONFLICT" if candidates else "OPENING_NAV_UNAVAILABLE"}
                continue
            opening = candidates[0]
            reason = period_reason(context, opening, approval)
            if reason:
                output[fund_id][years] = {"status": "OPENING_" + reason}
                continue
            if opening.get("currency") != currency:
                output[fund_id][years] = {"status": "OPENING_CURRENCY_MISMATCH"}
                continue
            opening_nav = _number(opening.get("nav"))
            if opening_nav is None or opening_nav < 0:
                output[fund_id][years] = {"status": "OPENING_NAV_INVALID"}
                continue
            selected_flows: list[tuple[date, float]] = [(opening_date, -opening_nav)]
            flow_ids: list[str] = []
            mismatch = False
            for flow in context["flows_by_fund"].get(fund_id, []):
                moment = _date(flow.get("cashflow_date"))
                if moment is None or not (opening_date < moment <= current_date):
                    continue
                if flow.get("base_currency") != currency:
                    mismatch = True
                    break
                amount = _number(flow.get("amount_base_currency"))
                if amount is None:
                    mismatch = True
                    break
                selected_flows.append((moment, amount))
                flow_ids.append(flow["cashflow_id"])
            if mismatch:
                output[fund_id][years] = {"status": "CURRENCY_OR_AMOUNT_INVALID"}
                continue
            selected_flows.append((current_date, closing_nav))
            try:
                value = xirr(selected_flows)
                status = "AVAILABLE"
            except ValueError as exc:
                value = None
                status = f"XIRR_UNAVAILABLE:{type(exc).__name__}"
            output[fund_id][years] = {
                "status": status,
                "value": value,
                "opening_period_id": opening["fund_period_id"],
                "closing_period_id": current["fund_period_id"],
                "cashflow_ids": flow_ids,
                "opening_date": opening_date.isoformat(),
                "closing_date": current_date.isoformat(),
            }
    return output


def age_snapshots(context: Mapping[str, Any]) -> dict[str, dict[int, dict[str, Any]]]:
    age_years = [int(value) for value in context["policy"]["returns"]["age_years"]]
    max_lag = int(context["policy"]["returns"]["age_max_lag_days"])
    current_date = _date(context["policy"]["economic_as_of"])
    assert current_date is not None
    first_calls: dict[str, date] = {}
    for fund_id, flows in context["flows_by_fund"].items():
        dates = [
            _date(row.get("cashflow_date"))
            for row in flows
            if row.get("cashflow_type") == "capital_call" and (_number(row.get("amount_base_currency")) or 0.0) < 0
        ]
        selected = [moment for moment in dates if moment is not None]
        if selected:
            first_calls[fund_id] = min(selected)

    candidate_ids: set[str] = set()
    output: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for fund in context["fund_master"]:
        fund_id = fund["fund_id"]
        first_call = first_calls.get(fund_id)
        if first_call is None:
            for years in age_years:
                output[fund_id][years] = {"status": "FIRST_CALL_UNAVAILABLE"}
            continue
        rows = context["periods_by_fund"].get(fund_id, [])
        for years in age_years:
            target = _add_years(first_call, years)
            if target > current_date:
                output[fund_id][years] = {"status": "FUND_TOO_YOUNG", "target_date": target.isoformat()}
                continue
            candidates = []
            for row in rows:
                moment = _date(row.get("as_of_date"))
                if moment is None or moment > target:
                    continue
                lag = (target - moment).days
                if lag <= max_lag and context["available_period"](row):
                    candidates.append((moment, row))
            if not candidates:
                output[fund_id][years] = {"status": "AGE_REPORT_UNAVAILABLE", "target_date": target.isoformat()}
                continue
            moment = max(item[0] for item in candidates)
            latest = [row for at, row in candidates if at == moment]
            if len(latest) != 1:
                output[fund_id][years] = {"status": "AGE_PERIOD_CONFLICT", "target_date": target.isoformat()}
                continue
            selected = latest[0]
            if selected.get("currency") != fund.get("base_currency") or selected.get("input_reasons"):
                output[fund_id][years] = {"status": "AGE_INPUT_INVALID", "target_date": target.isoformat()}
                continue
            candidate_ids.add(selected["fund_period_id"])
            output[fund_id][years] = {
                "status": "PENDING_QUALITY",
                "target_date": target.isoformat(),
                "actual_date": moment.isoformat(),
                "lag_days": (target - moment).days,
                "actual_age_years": (moment - first_call).days / 365.25,
                "period_id": selected["fund_period_id"],
                "dpi": _number(selected.get("dpi")),
                "rvpi": _number(selected.get("rvpi")),
                "tvpi": _number(selected.get("tvpi")),
                "xirr": _number(selected.get("calculated_irr")),
            }
    approval = quality_approval_for_ids(context, candidate_ids)
    for fund_id, ages in output.items():
        for years, record in ages.items():
            if record.get("status") != "PENDING_QUALITY":
                continue
            ok, reason = approval.get(record["period_id"], (False, "QUALITY_RESULT_MISSING"))
            record["status"] = "AVAILABLE" if ok else "QUALITY_UNAVAILABLE"
            record["quality_reason"] = reason
            if not ok:
                for key in ("dpi", "rvpi", "tvpi", "xirr"):
                    record[key] = None
    _add_age_percentiles(context, output)
    return output


def _add_age_percentiles(context: Mapping[str, Any], snapshots: dict[str, dict[int, dict[str, Any]]]) -> None:
    vintage_years = int(context["policy"]["cohorts"]["vintage_bucket_years"])
    min_funds = int(context["policy"]["cohorts"]["reference_min_funds"])
    min_managers = int(context["policy"]["cohorts"]["reference_min_managers"])
    for fund in context["fund_master"]:
        fund_id = fund["fund_id"]
        for years, record in snapshots.get(fund_id, {}).items():
            if record.get("status") != "AVAILABLE":
                continue
            for metric in ("tvpi", "dpi"):
                value = record.get(metric)
                if value is None:
                    continue
                peers: list[tuple[float, str]] = []
                for other in context["fund_master"]:
                    if other["fund_manager_id"] == fund["fund_manager_id"]:
                        continue
                    if other.get("strategy") != fund.get("strategy") or (context["policy"]["cohorts"]["match_sub_strategy"] and other.get("sub_strategy") != fund.get("sub_strategy")):
                        continue
                    if other.get("base_currency") != fund.get("base_currency"):
                        continue
                    if _vintage_bucket(int(other["vintage_year"]), vintage_years) != _vintage_bucket(int(fund["vintage_year"]), vintage_years):
                        continue
                    other_rec = snapshots.get(other["fund_id"], {}).get(years, {})
                    other_value = other_rec.get(metric) if other_rec.get("status") == "AVAILABLE" else None
                    if other_value is not None:
                        peers.append((float(other_value), other["fund_manager_id"]))
                managers = {manager for _, manager in peers}
                record[f"{metric}_peer_count"] = len(peers)
                record[f"{metric}_peer_manager_count"] = len(managers)
                if len(peers) >= min_funds and len(managers) >= min_managers:
                    record[f"{metric}_percentile"] = midpoint_percentile(float(value), [peer for peer, _ in peers])
                else:
                    record[f"{metric}_percentile"] = None


def cash_conversion(context: Mapping[str, Any], trailing: Mapping[str, Mapping[int, Mapping[str, Any]]]) -> dict[str, dict[str, Any]]:
    current_date = _date(context["policy"]["economic_as_of"])
    assert current_date is not None
    fraction = float(context["policy"]["returns"]["material_distribution_paid_in_fraction"])
    output: dict[str, dict[str, Any]] = {}
    for fund_id, current in context["current_by_fund"].items():
        paid_in = _number(current.get("paid_in_capital_itd"))
        if period_reason(context, current):
            output[fund_id] = {"status": period_reason(context, current)}
            continue
        if paid_in is None or paid_in <= 0:
            output[fund_id] = {"status": "PAID_IN_UNAVAILABLE"}
            continue
        threshold = paid_in * fraction
        material = []
        calls = []
        invalid_flow = False
        for flow in context["flows_by_fund"].get(fund_id, []):
            moment = _date(flow.get("cashflow_date"))
            amount = _number(flow.get("amount_base_currency"))
            if moment is None or amount is None:
                invalid_flow = True
                break
            if moment > current_date:
                continue
            if flow.get("base_currency") != current.get("currency"):
                invalid_flow = True
                break
            if flow.get("cashflow_type") == "distribution" and amount >= threshold:
                material.append((moment, flow["cashflow_id"], amount))
            if flow.get("cashflow_type") == "capital_call" and amount < 0:
                calls.append((moment, flow["cashflow_id"], -amount))
        if invalid_flow:
            output[fund_id] = {"status": "CASHFLOW_CURRENCY_OR_VALUE_INVALID"}
            continue
        last = max(material, default=None, key=lambda item: item[0])
        months = None if last is None else (current_date - last[0]).days / 30.4375
        calls.sort()
        total_calls = sum(amount for _, _, amount in calls)
        milestones: dict[str, Any] = {}
        first_call = calls[0][0] if calls else None
        for target_fraction in (0.5, 0.75):
            cumulative = 0.0
            reached = None
            reached_id = ""
            for moment, flow_id, amount in calls:
                cumulative += amount
                if total_calls > 0 and cumulative / total_calls >= target_fraction:
                    reached = moment
                    reached_id = flow_id
                    break
            key = f"call_{int(target_fraction * 100)}"
            milestones[f"{key}_date"] = reached.isoformat() if reached else ""
            milestones[f"{key}_months"] = ((reached - first_call).days / 30.4375) if reached and first_call else None
            milestones[f"{key}_cashflow_id"] = reached_id
        one_year = trailing.get(fund_id, {}).get(1, {})
        opening_nav = None
        if one_year.get("status") == "AVAILABLE" and one_year.get("opening_period_id"):
            period_map = {row["fund_period_id"]: row for row in context["periods_by_fund"].get(fund_id, [])}
            opening_nav = _number(period_map.get(one_year["opening_period_id"], {}).get("nav"))
        one_year_distributions = 0.0
        if one_year.get("opening_date"):
            start = _date(one_year["opening_date"])
            if start:
                one_year_distributions = sum(
                    _number(row.get("amount_base_currency")) or 0.0
                    for row in context["flows_by_fund"].get(fund_id, [])
                    if row.get("cashflow_type") == "distribution"
                    and (_date(row.get("cashflow_date")) or date.min) > start
                    and (_date(row.get("cashflow_date")) or date.max) <= current_date
                )
        velocity = one_year_distributions / opening_nav if opening_nav and opening_nav > 0 else None
        output[fund_id] = {
            "status": "AVAILABLE",
            "distribution_recency_months": months,
            "last_material_distribution_id": last[1] if last else "",
            "materiality_threshold": threshold,
            "distribution_velocity_1y": velocity,
            "called_capital_total": total_calls,
            **milestones,
        }
    return output


def cohort_data(context: Mapping[str, Any]) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]]]:
    v1_features = context["v1"]["features"]
    fund_master = context["fund_by_id"]
    reference: dict[str, dict[str, Any]] = {}
    membership: list[dict[str, str]] = []
    for row in v1_features:
        peers = list(json.loads(row.get("peer_fund_ids", "[]")))
        managers = {fund_master[peer]["fund_manager_id"] for peer in peers if peer in fund_master}
        reference[row["fund_id"]] = {"peer_ids": peers, "peer_managers": managers}
        for peer in peers:
            membership.append(
                {
                    "evaluated_fund_id": row["fund_id"],
                    "policy_id": "reference_v1_10_5",
                    "peer_fund_id": peer,
                    "included": "true",
                    "reason": "V1_EXPLICIT_PEER",
                }
            )
    strict_min_funds = int(context["policy"]["cohorts"]["strict_min_funds"])
    strict_min_managers = int(context["policy"]["cohorts"]["strict_min_managers"])
    for fund_id, data in reference.items():
        strict_peers = [peer for peer in data["peer_ids"] if not context["policy"]["cohorts"]["match_sub_strategy"] or fund_master[peer].get("sub_strategy") == fund_master[fund_id].get("sub_strategy")]
        strict_managers = {fund_master[peer]["fund_manager_id"] for peer in strict_peers}
        data["strict_eligible"] = len(strict_peers) >= strict_min_funds and len(strict_managers) >= strict_min_managers

    groups: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in v1_features:
        groups[(row["strategy"], row["currency"], row["vintage_bucket"], row["measurement_basis"], row["as_of_date"])].append(row)
    size_band: dict[str, int] = {}
    band_count = int(context["policy"]["cohorts"]["size_band_count"])
    if band_count < 1:
        raise V2FeatureError("size_band_count must be positive")
    for rows in groups.values():
        values = sorted((_number(fund_master[row["fund_id"]].get("fund_size")) or 0.0, row["fund_id"]) for row in rows)
        positive = [value for value, _ in values if value > 0]
        if not positive:
            continue
        breaks = [_q(positive, index / band_count) for index in range(1, band_count)]
        for value, fund_id in values:
            if value > 0:
                size_band[fund_id] = sum(value > boundary for boundary in breaks)
    for row in v1_features:
        fund_id = row["fund_id"]
        if fund_id not in size_band:
            continue
        same = [
            other
            for other in groups[(row["strategy"], row["currency"], row["vintage_bucket"], row["measurement_basis"], row["as_of_date"])]
            if other["manager_id"] != row["manager_id"] and size_band.get(other["fund_id"]) == size_band[fund_id]
            and (not context["policy"]["cohorts"]["match_sub_strategy"] or fund_master[other["fund_id"]].get("sub_strategy") == fund_master[fund_id].get("sub_strategy"))
        ]
        peer_ids = sorted(other["fund_id"] for other in same)
        managers = {other["manager_id"] for other in same}
        reference[fund_id]["size_peer_ids"] = peer_ids
        reference[fund_id]["size_peer_managers"] = managers
        for peer in peer_ids:
            membership.append(
                {
                    "evaluated_fund_id": fund_id,
                    "policy_id": "size_bands",
                    "peer_fund_id": peer,
                    "included": "true",
                    "reason": f"SIZE_BAND_{size_band[fund_id]}",
                }
            )
    return membership, reference


def peer_statistics(context: Mapping[str, Any], cohort: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_fund = {row["fund_id"]: row for row in context["v1"]["features"]}
    result: dict[str, dict[str, Any]] = {}
    for fund_id, data in cohort.items():
        row = by_fund[fund_id]
        stats: dict[str, Any] = {
            "strict_20_10_eligible": bool(data.get("strict_eligible")),
            "reference_peer_count": len(data.get("peer_ids", [])),
            "reference_peer_manager_count": len(data.get("peer_managers", [])),
            "size_peer_count": len(data.get("size_peer_ids", [])),
            "size_peer_manager_count": len(data.get("size_peer_managers", [])),
        }
        for metric, field in (("tvpi", "tvpi"), ("dpi", "dpi")):
            value = _number(row.get(field))
            peers = [_number(by_fund[peer].get(field)) for peer in data.get("peer_ids", []) if peer in by_fund]
            values = [x for x in peers if x is not None]
            stats[f"{metric}_peer_median"] = _q(values, 0.5)
            stats[f"{metric}_peer_q25"] = _q(values, 0.25)
            stats[f"{metric}_peer_q75"] = _q(values, 0.75)
            med = stats[f"{metric}_peer_median"]
            mad = _q([abs(x - med) for x in values], 0.5) if med is not None else None
            stats[f"{metric}_robust_z"] = ((value - med) / (1.4826 * mad)) if value is not None and med is not None and mad and mad > 0 else None
            size_values = [_number(by_fund[peer].get(field)) for peer in data.get("size_peer_ids", []) if peer in by_fund]
            size_values = [x for x in size_values if x is not None]
            managers = data.get("size_peer_managers", set())
            if value is not None and len(size_values) >= int(context["policy"]["cohorts"]["reference_min_funds"]) and len(managers) >= int(context["policy"]["cohorts"]["reference_min_managers"]):
                stats[f"{metric}_size_percentile"] = midpoint_percentile(value, size_values)
            else:
                stats[f"{metric}_size_percentile"] = None
        result[fund_id] = stats
    return result


def genealogy(context: Mapping[str, Any]) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for fund in context["fund_master"]:
        groups[(fund["fund_manager_id"], fund.get("strategy", ""), fund.get("sub_strategy", ""))].append(fund)
    rows: list[dict[str, str]] = []
    index: dict[str, dict[str, Any]] = {}
    for (manager_id, strategy, sub_strategy), funds in sorted(groups.items()):
        vintages = [fund.get("vintage_year", "") for fund in funds]
        ambiguous = len(vintages) != len(set(vintages))
        ordered = sorted(funds, key=lambda fund: (int(fund.get("vintage_year") or 0), fund.get("first_close_date", ""), fund["fund_id"]))
        previous = ""
        for order, fund in enumerate(ordered, 1):
            predecessor = "" if ambiguous or order == 1 else previous
            record = {
                "manager_id": manager_id,
                "strategy": strategy,
                "sub_strategy": sub_strategy,
                "fund_id": fund["fund_id"],
                "display_order": str(order),
                "vintage_year": fund.get("vintage_year", ""),
                "first_close_date": fund.get("first_close_date", ""),
                "predecessor_fund_id": predecessor,
                "order_status": "AMBIGUOUS_SAME_VINTAGE" if ambiguous else "ORDERED",
            }
            rows.append(record)
            index[fund["fund_id"]] = record
            previous = fund["fund_id"]
    return rows, index


def holdings_features(context: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for fund_id, current in context["current_by_fund"].items():
        rows = context["holdings_by_fund"].get(fund_id, [])
        nav = _number(current.get("nav"))
        if period_reason(context, current) or not rows or nav is None or nav < 0:
            output[fund_id] = {"status": "HOLDINGS_UNAVAILABLE"}
            continue
        company: dict[str, float] = defaultdict(float)
        sector: dict[str, float] = defaultdict(float)
        geography: dict[str, float] = defaultdict(float)
        holding_ids: list[str] = []
        invalid = False
        for row in rows:
            fair = _number(row.get("fair_value"))
            dated = bool(row.get("report_date"))
            inherited_date = (context["policy"].get("investment_analysis", {}).get("undated_fixture_holding_availability") == "matching_fund_report"
                              and row.get("provenance_type") == "SYNTHETIC" and row.get("as_of_date") == current.get("as_of_date"))
            if fair is None or fair < 0 or row.get("currency") != current.get("currency") or (dated and not context["available_period"](row)) or (not dated and not inherited_date):
                invalid = True
                break
            company[row.get("portfolio_company_id", "") or row["holding_id"]] += fair
            sector[row.get("sector", "") or "UNKNOWN"] += fair
            geography[row.get("geography", "") or "UNKNOWN"] += fair
            holding_ids.append(row["holding_id"])
        if invalid:
            output[fund_id] = {"status": "HOLDING_VALUE_INVALID"}
            continue
        total = sum(company.values())
        tolerance = max(1e-6, abs(nav) * 1e-9)
        if abs(total - nav) > tolerance:
            output[fund_id] = {"status": "HOLDINGS_NAV_RECONCILIATION_FAIL", "holding_total": total, "nav": nav}
            continue
        if total <= 0:
            output[fund_id] = {"status": "ZERO_HOLDING_DENOMINATOR"}
            continue
        company_weights = sorted((value / total, key) for key, value in company.items())
        sector_weights = sorted((value / total, key) for key, value in sector.items())
        geo_weights = sorted((value / total, key) for key, value in geography.items())
        output[fund_id] = {
            "status": "AVAILABLE",
            "holding_total": total,
            "report_date_basis": "HOLDING_REPORT_DATES" if all(row.get("report_date") for row in rows) else "MATCHING_FIXTURE_FUND_REPORT",
            "holding_ids": sorted(holding_ids),
            "company_count": len(company),
            "company_hhi": sum(weight * weight for weight, _ in company_weights),
            "top_company_share": max(weight for weight, _ in company_weights),
            "top3_company_share": sum(weight for weight, _ in sorted(company_weights, reverse=True)[:3]),
            "sector_hhi": sum(weight * weight for weight, _ in sector_weights),
            "top_sector_share": max(weight for weight, _ in sector_weights),
            "top_sector": max(sector_weights)[1],
            "geography_hhi": sum(weight * weight for weight, _ in geo_weights),
            "top_geography": max(geo_weights)[1],
            "geography_status": "AVAILABLE_CONSTANT" if len(geography) == 1 else "AVAILABLE",
        }
    return output


def resolve_terms(context: Mapping[str, Any], fund_id: str, lp_id: str = "", share_class_name: str = "") -> dict[str, Any]:
    evaluation = _date(context["policy"]["economic_as_of"])
    active = [row for row in context["terms"] if row.get("fund_id") == fund_id and term_applies(row, evaluation)]
    base = [row for row in active if row.get("term_scope") == "base_fund" and row.get("perspective") == "fund_total"]
    if len(base) != 1:
        return {"status": "BASE_TERM_CONFLICT_OR_MISSING"}
    selected = base[0]
    override = []
    if lp_id:
        override.extend(row for row in active if row.get("term_scope") == "lp_override" and row.get("lp_id") == lp_id and row.get("overrides_fund_term_id") == selected["fund_term_id"])
    if share_class_name:
        override.extend(row for row in active if row.get("term_scope") == "share_class_override" and row.get("share_class_name") == share_class_name and row.get("overrides_fund_term_id") == selected["fund_term_id"])
    if len(override) > 1:
        return {"status": "TERM_OVERRIDE_CONFLICT"}
    effective = dict(selected)
    inherited: list[str] = []
    if override:
        item = override[0]
        term_fields = {"management_fee_rate", "management_fee_basis", "carry_rate", "hurdle_rate", "catch_up_rate", "catch_up_present", "waterfall_type", "fund_term_years", "extension_years", "preferred_return_compounding", "expense_cap_rate", "maximum_offering", "currency"}
        for key, value in item.items():
            if key not in term_fields:
                continue
            if key in effective and _text(value):
                effective[key] = value
            elif key in effective and not _text(value):
                inherited.append(key)
        effective["applied_override_id"] = item["fund_term_id"]
    else:
        effective["applied_override_id"] = ""
    effective["status"] = "AVAILABLE"
    effective["inherited_fields"] = inherited
    return effective


def consistency_features(context: Mapping[str, Any], genealogy_index: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    feature_by_fund = {row["fund_id"]: row for row in context["v1"]["features"]}
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in context["v1"]["scorecards"]:
        groups[(row["manager_id"], row["strategy"])].append(row)
    output: list[dict[str, Any]] = []
    for card in context["v1"]["scorecards"]:
        manager_id = card["manager_id"]
        strategy = card["strategy"]
        all_funds = [
            fund
            for fund in context["fund_master"]
            if fund["fund_manager_id"] == manager_id and fund.get("strategy") == strategy
        ]
        sub_strategies = sorted({fund.get("sub_strategy", "") for fund in all_funds})
        supplied = sorted(all_funds, key=lambda fund: (int(fund.get("vintage_year") or 0), fund.get("first_close_date", ""), fund["fund_id"]))
        score_rows = [feature_by_fund[fund["fund_id"]] for fund in supplied if fund["fund_id"] in feature_by_fund and feature_by_fund[fund["fund_id"]].get("fund_score")]
        scores = [float(row["fund_score"]) for row in score_rows]
        comparable_series = len(sub_strategies) == 1 and all(genealogy_index.get(fund["fund_id"], {}).get("order_status") == "ORDERED" for fund in supplied)
        ordered_scores = [float(row["fund_score"]) for row in score_rows] if comparable_series else []
        trend = None
        two_point = None
        if len(ordered_scores) >= 3:
            xs = list(range(len(ordered_scores)))
            xm = statistics.fmean(xs)
            ym = statistics.fmean(ordered_scores)
            denom = sum((x - xm) ** 2 for x in xs)
            trend = sum((x - xm) * (y - ym) for x, y in zip(xs, ordered_scores)) / denom if denom else None
        elif len(ordered_scores) == 2:
            two_point = ordered_scores[1] - ordered_scores[0]
        output.append(
            {
                "manager_id": manager_id,
                "manager_name": card.get("manager_name", ""),
                "strategy": strategy,
                "sub_strategy": sub_strategies[0] if len(sub_strategies) == 1 else "",
                "v1_status": card.get("status", ""),
                "historical_score": _number(card.get("score")),
                "historical_rank": card.get("rank", ""),
                "supplied_funds": len(supplied),
                "eligible_score_funds": len(scores),
                "eligible_fund_ids": [row["fund_id"] for row in score_rows],
                "score_above_50_rate": sum(value > 50 for value in scores) / len(scores) if scores else None,
                "score_at_least_75_rate": sum(value >= 75 for value in scores) / len(scores) if scores else None,
                "score_at_most_25_rate": sum(value <= 25 for value in scores) / len(scores) if scores else None,
                "worst_fund_score": min(scores) if scores else None,
                "fund_score_iqr": ((_q(scores, 0.75) or 0) - (_q(scores, 0.25) or 0)) if scores else None,
                "score_trend_per_fund": trend,
                "two_point_change": two_point,
                "trend_status": "AVAILABLE" if comparable_series and len(ordered_scores) >= 2 else "SERIES_ORDER_OR_DEPTH_UNSUPPORTED",
                "consistency_status": "AVAILABLE" if len(scores) >= 2 else "CONSISTENCY_UNAVAILABLE",
            }
        )
    return output


def _size_progression(context: Mapping[str, Any], genealogy_index: Mapping[str, Mapping[str, Any]], fund_id: str) -> dict[str, Any]:
    node = genealogy_index.get(fund_id, {})
    predecessor = node.get("predecessor_fund_id", "")
    if not predecessor:
        return {"status": "PREDECESSOR_UNAVAILABLE"}
    current = context["fund_by_id"][fund_id]
    prior = context["fund_by_id"].get(predecessor)
    if prior is None:
        return {"status": "PREDECESSOR_UNRESOLVED"}
    if current.get("fund_size_currency") != prior.get("fund_size_currency"):
        return {"status": "FUND_SIZE_CURRENCY_MISMATCH", "predecessor_fund_id": predecessor}
    now = _number(current.get("fund_size"))
    before = _number(prior.get("fund_size"))
    if now is None or before is None or before <= 0:
        return {"status": "FUND_SIZE_INVALID", "predecessor_fund_id": predecessor}
    return {"status": "AVAILABLE", "step_up": now / before, "predecessor_fund_id": predecessor}


def build_core_features(context: Mapping[str, Any]) -> dict[str, Any]:
    coverage, decisions = build_initial_coverage(context)
    pme_map, pme_unsupported = strategy_pme(context)
    trailing = trailing_returns(context)
    ages = age_snapshots(context)
    cash = cash_conversion(context, trailing)
    cohort_rows, cohort = cohort_data(context)
    peer_stats = peer_statistics(context, cohort)
    genealogy_rows, genealogy_index = genealogy(context)
    holding = holdings_features(context)
    v1_by_fund = {row["fund_id"]: row for row in context["v1"]["features"]}
    fund_rows: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    pme_unsupported_by_fund = {row["fund_id"]: row["status"] for row in pme_unsupported}
    for fund in sorted(context["fund_master"], key=lambda row: row["fund_id"]):
        fund_id = fund["fund_id"]
        current = context["current_by_fund"].get(fund_id)
        current_status = period_reason(context, current) or "AVAILABLE"
        current = current if current_status == "AVAILABLE" else None
        v1 = v1_by_fund.get(fund_id, {})
        pme = pme_map.get(fund_id, {})
        hold = holding.get(fund_id, {"status": "HOLDINGS_UNAVAILABLE"})
        term = resolve_terms(context, fund_id)
        distributions = _number(current.get("distributions_itd")) if current else None
        nav = _number(current.get("nav")) if current else None
        total_value = (distributions + nav) if distributions is not None and nav is not None else None
        realized_share = distributions / total_value if total_value and total_value > 0 else None
        nav_reliance = nav / total_value if total_value and total_value > 0 else None
        metric = context["metric_index"].get(current["fund_period_id"], {}) if current else {}
        xirr_row = metric.get("xirr", {})
        size = _size_progression(context, genealogy_index, fund_id)
        row: dict[str, Any] = {
            "population": "fixture",
            "fund_id": fund_id,
            "manager_id": fund["fund_manager_id"],
            "manager_name": fund.get("fund_manager_name", ""),
            "strategy": fund.get("strategy", ""),
            "sub_strategy": fund.get("sub_strategy", ""),
            "vintage_year": fund.get("vintage_year", ""),
            "currency": current.get("currency", fund.get("base_currency", "")) if current else fund.get("base_currency", ""),
            "as_of_date": current.get("as_of_date", "") if current else "",
            "current_status": current_status,
            "v1_status": v1.get("status", ""),
            "v1_fund_score": _number(v1.get("fund_score")),
            "v1_tvpi_percentile": _number(v1.get("tvpi_percentile")),
            "v1_dpi_percentile": _number(v1.get("dpi_percentile")),
            "dpi": _number(current.get("dpi")) if current else None,
            "rvpi": _number(current.get("rvpi")) if current else None,
            "tvpi": _number(current.get("tvpi")) if current else None,
            "xirr": _number(xirr_row.get("value_numeric")),
            "xirr_status": "AVAILABLE" if _number(xirr_row.get("value_numeric")) is not None else "RETURN_UNAVAILABLE",
            "xirr_basis": xirr_row.get("input_fee_basis", "") or "unstated",
            "realized_share": realized_share,
            "nav_reliance": nav_reliance,
            "ks_pme": _number(pme.get("ks_pme", {}).get("value_numeric")),
            "direct_alpha": _number(pme.get("direct_alpha", {}).get("value_numeric")),
            "benchmark_id": pme.get("ks_pme", {}).get("benchmark_id", ""),
            "benchmark_status": "AVAILABLE" if pme else pme_unsupported_by_fund.get(fund_id, "NO_CURRENT_PERIOD"),
            "distribution_recency_months": cash.get(fund_id, {}).get("distribution_recency_months"),
            "distribution_velocity_1y": cash.get(fund_id, {}).get("distribution_velocity_1y"),
            "cash_conversion_status": cash.get(fund_id, {}).get("status", "NO_CURRENT_PERIOD"),
            "call_50_months": cash.get(fund_id, {}).get("call_50_months"),
            "call_75_months": cash.get(fund_id, {}).get("call_75_months"),
            "company_hhi": hold.get("company_hhi"),
            "top_company_share": hold.get("top_company_share"),
            "top3_company_share": hold.get("top3_company_share"),
            "sector_hhi": hold.get("sector_hhi"),
            "top_sector_share": hold.get("top_sector_share"),
            "top_sector": hold.get("top_sector", ""),
            "geography_hhi": hold.get("geography_hhi"),
            "geography_status": hold.get("geography_status", "UNKNOWN"),
            "holdings_status": hold.get("status", "HOLDINGS_UNAVAILABLE"),
            "holdings_report_date_basis": hold.get("report_date_basis", ""),
            "economic_loss_status": "UNSUPPORTED_DEFINITION",
            "management_fee_rate": _number(term.get("management_fee_rate")) if term.get("status") == "AVAILABLE" else None,
            "waterfall_type": term.get("waterfall_type", "") if term.get("status") == "AVAILABLE" else "",
            "term_status": term.get("status", "UNKNOWN"),
            "size_step_up": size.get("step_up"),
            "size_predecessor_fund_id": size.get("predecessor_fund_id", ""),
            "size_step_status": size.get("status", "PREDECESSOR_UNAVAILABLE"),
        }
        row.update(peer_stats.get(fund_id, {}))
        for years in context["policy"]["returns"]["trailing_years"]:
            rec = trailing.get(fund_id, {}).get(int(years), {})
            row[f"trailing_{years}y_xirr"] = rec.get("value") if rec.get("status") == "AVAILABLE" else None
            row[f"trailing_{years}y_status"] = rec.get("status", "UNAVAILABLE")
        for years in context["policy"]["returns"]["age_years"]:
            rec = ages.get(fund_id, {}).get(int(years), {})
            row[f"age_{years}_status"] = rec.get("status", "UNAVAILABLE")
            row[f"age_{years}_date"] = rec.get("actual_date", "")
            row[f"age_{years}_lag_days"] = rec.get("lag_days", "")
            row[f"age_{years}_tvpi"] = rec.get("tvpi") if rec.get("status") == "AVAILABLE" else None
            row[f"age_{years}_dpi"] = rec.get("dpi") if rec.get("status") == "AVAILABLE" else None
            row[f"age_{years}_tvpi_percentile"] = rec.get("tvpi_percentile") if rec.get("status") == "AVAILABLE" else None
            row[f"age_{years}_dpi_percentile"] = rec.get("dpi_percentile") if rec.get("status") == "AVAILABLE" else None
        fund_rows.append(row)
        evidence.append({
            "feature_id": f"F:{fund_id}:DIAGNOSTICS", "entity_id": fund_id, "feature": "fund_diagnostics",
            "values": dict(row), "date_meaning": "economic_as_of", "as_of_date": context["policy"]["economic_as_of"],
            "information_cutoff": context["policy"]["information_cutoff"], "currency": row["currency"],
            "units": "multiples and concentration are ratios; returns and shares are decimals; elapsed time is months",
            "inputs": {"fund_master": [fund_id, *([size['predecessor_fund_id']] if size.get('predecessor_fund_id') else [])],
                       "fund_periods": [period["fund_period_id"] for period in context["periods_by_fund"].get(fund_id, [])],
                       "fund_cashflows": [flow["cashflow_id"] for flow in context["flows_by_fund"].get(fund_id, [])],
                       "fund_holdings": hold.get("holding_ids", []), "peer_fund_ids": cohort.get(fund_id, {}).get("peer_ids", [])},
            "cash_timing": cash.get(fund_id, {}), "series": genealogy_index.get(fund_id, {}),
            "trailing_returns": trailing.get(fund_id, {}), "age_snapshots": ages.get(fund_id, {}),
            "terms": term, "formula_id": "v2_features.build_core_features", "population": "fixture"})
        if current:
            evidence.append({"feature_id": f"F:{fund_id}:CURRENT_MULTIPLES", "entity_id": fund_id, "feature": "dpi_rvpi_tvpi", "source_table": "fund_periods", "record_ids": [current["fund_period_id"]], "formula_id": "PARENT_PERIOD_COMPONENTS", "population": "fixture"})
        if xirr_row:
            evidence.append({"feature_id": f"F:{fund_id}:XIRR", "entity_id": fund_id, "feature": "xirr", "source_table": "fund_metrics", "record_ids": [xirr_row.get("analysis_result_id", "")], "input_ids": xirr_row.get("input_record_ids", "").split(";"), "formula_id": xirr_row.get("formula_id", ""), "population": "fixture"})
        if pme:
            for metric_name in ("ks_pme", "direct_alpha"):
                item = pme.get(metric_name)
                if item:
                    evidence.append({"feature_id": f"F:{fund_id}:{metric_name.upper()}", "entity_id": fund_id, "feature": metric_name, "source_table": "V2_RECOMPUTED", "record_ids": [item.get("analysis_result_id", "")], "input_ids": item.get("input_record_ids", "").split(";"), "formula_id": item.get("formula_id", ""), "benchmark_id": item.get("benchmark_id", ""), "population": "fixture"})
        if hold.get("status") == "AVAILABLE":
            evidence.append({"feature_id": f"F:{fund_id}:HOLDINGS", "entity_id": fund_id, "feature": "concentration", "source_table": "fund_holdings", "record_ids": hold.get("holding_ids", []), "formula_id": "V2_HHI_TOP_SHARES", "population": "fixture"})
        if term.get("status") == "AVAILABLE":
            ids = [term.get("fund_term_id", "")]
            if term.get("applied_override_id"):
                ids.append(term["applied_override_id"])
            evidence.append({"feature_id": f"F:{fund_id}:TERMS", "entity_id": fund_id, "feature": "terms", "source_table": "fund_terms", "record_ids": ids, "formula_id": "V2_SCOPED_TERM_RESOLUTION", "population": "fixture"})

    consistency = consistency_features(context, genealogy_index)
    fund_by_id = {row["fund_id"]: row for row in fund_rows}
    manager_rows: list[dict[str, Any]] = []
    for item in consistency:
        fund_ids = item["eligible_fund_ids"]
        selected = [fund_by_id[fund_id] for fund_id in fund_ids if fund_id in fund_by_id]
        latest_group_funds = [
            fund for fund in context["fund_master"]
            if fund["fund_manager_id"] == item["manager_id"] and fund.get("strategy") == item["strategy"]
        ]
        latest_group_funds.sort(key=lambda fund: (int(fund.get("vintage_year") or 0), fund.get("first_close_date", ""), fund["fund_id"]))
        latest_id = latest_group_funds[-1]["fund_id"] if latest_group_funds else ""
        latest_diag = fund_by_id.get(latest_id, {})
        manager_rows.append(
            {
                **item,
                "avg_realized_share": _mean(_number(row.get("realized_share")) for row in selected),
                "avg_nav_reliance": _mean(_number(row.get("nav_reliance")) for row in selected),
                "avg_ks_pme": _mean(_number(row.get("ks_pme")) for row in selected),
                "avg_direct_alpha": _mean(_number(row.get("direct_alpha")) for row in selected),
                "avg_company_hhi": _mean(_number(row.get("company_hhi")) for row in selected),
                "avg_sector_hhi": _mean(_number(row.get("sector_hhi")) for row in selected),
                "latest_fund_id": latest_id,
                "latest_size_step_up": latest_diag.get("size_step_up"),
                "latest_size_step_status": latest_diag.get("size_step_status", ""),
                "team_continuity": None,
                "strategy_flag": "NO_CASE_EVIDENCE",
                "gp_commitment_pct": None,
                "governance_flag": "NO_CASE_EVIDENCE",
            }
        )
    from v2_analysis import enrich_core
    enrich_core(context, fund_rows, manager_rows, evidence)
    for item in evidence:
        if item.get("feature") == "fund_diagnostics":
            item["values"] = dict(fund_by_id[item["entity_id"]])
    readiness = build_readiness(context, fund_rows, manager_rows)
    for manager in manager_rows:
        evidence.append({"feature_id": f"MANAGER:{manager['manager_id']}:{manager['strategy']}:V2",
                         "entity_id": manager["manager_id"], "feature": "manager_diagnostics", "values": dict(manager),
                         "input_ids": [f"F:{fund_id}:DIAGNOSTICS" for fund_id in manager["eligible_fund_ids"]],
                         "source_table": "02-scoring/gp-scorecards.csv", "record_ids": [f"{manager['manager_id']}|{manager['strategy']}"],
                         "formula_id": "equal_fund_mean_and_score_cutoffs", "population": "fixture",
                         "as_of_date": context["policy"]["economic_as_of"], "information_cutoff": context["policy"]["information_cutoff"]})
    for coverage_row in coverage:
        diagnostic = fund_by_id.get(coverage_row["entity_id"])
        if diagnostic:
            field_status = {"current_period": diagnostic["current_status"], "xirr": diagnostic["xirr_status"], "strategy_pme": diagnostic["benchmark_status"], "holdings": diagnostic["holdings_status"], "base_terms": diagnostic["term_status"]}.get(coverage_row["field_name"])
            if field_status:
                coverage_row["status"] = "AVAILABLE" if field_status == "AVAILABLE" else "UNKNOWN"
                coverage_row["reason"] = "" if field_status == "AVAILABLE" else field_status
    real_evidence = selected_real_evidence(context)
    return {
        "coverage": coverage,
        "decisions": decisions,
        "pme": pme_map,
        "fund_diagnostics": fund_rows,
        "manager_diagnostics": manager_rows,
        "cohort_membership": cohort_rows,
        "genealogy": genealogy_rows,
        "readiness": readiness,
        "evidence": evidence,
        "real_evidence": real_evidence,
    }


def build_readiness(context: Mapping[str, Any], fund_rows: Sequence[Mapping[str, Any]], manager_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    required = context["policy"]["readiness"]
    rows: list[dict[str, Any]] = []
    for fund in fund_rows:
        for dimension, fields in required["fund"].items():
            supported = []
            missing = []
            for field in fields:
                value = fund.get(field)
                if value is None or value == "":
                    missing.append(field)
                else:
                    supported.append(field)
            rows.append(
                {
                    "entity_level": "fund",
                    "entity_id": fund["fund_id"],
                    "strategy": fund.get("strategy", ""),
                    "dimension": dimension,
                    "supported_fields": len(supported),
                    "required_fields": len(fields),
                    "coverage": len(supported) / len(fields) if fields else None,
                    "supported_field_names": supported,
                    "missing_field_names": missing,
                    "status": "READY" if len(supported) == len(fields) else ("PARTIAL" if supported else "UNKNOWN"),
                    "population": "fixture",
                }
            )
    for manager in manager_rows:
        for dimension, fields in required["manager"].items():
            supported = []
            missing = []
            for field in fields:
                value = manager.get(field)
                if value is None or value == "" or value == "NO_CASE_EVIDENCE":
                    missing.append(field)
                else:
                    supported.append(field)
            rows.append(
                {
                    "entity_level": "manager_strategy",
                    "entity_id": f"{manager['manager_id']}|{manager['strategy']}",
                    "strategy": manager.get("strategy", ""),
                    "dimension": dimension,
                    "supported_fields": len(supported),
                    "required_fields": len(fields),
                    "coverage": len(supported) / len(fields) if fields else None,
                    "supported_field_names": supported,
                    "missing_field_names": missing,
                    "status": "READY" if len(supported) == len(fields) else ("PARTIAL" if supported else "UNKNOWN"),
                    "population": "fixture",
                }
            )
    return rows


def selected_real_evidence(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    path = context["parent"] / "data/extracted/tables/fact_observation.csv"
    facts = read_csv(path)
    families = ("ddq_quantitative_observation", "fee_observation", "legal_term", "legal_clause", "valuation_observation", "performance_observation")
    selected: list[dict[str, Any]] = []
    for family in families:
        candidates = [row for row in facts if row.get("record_family") == family]
        candidates.sort(key=lambda row: (row.get("document_id", ""), int(row.get("source_page") or 0), row.get("observation_id", "")))
        for row in candidates[:2]:
            selected.append(
                {
                    "status": "EVIDENCE_ONLY",
                    "record_family": family,
                    "observation_id": row.get("observation_id", ""),
                    "document_id": row.get("document_id", ""),
                    "source_page": row.get("source_page", ""),
                    "subject_name": row.get("subject_name", ""),
                    "subject_manager_name": row.get("subject_manager_name", ""),
                    "metric_id": row.get("metric_id", ""),
                    "value_raw": row.get("value_raw", ""),
                    "unit": row.get("unit", ""),
                    "as_of_date": row.get("as_of_date", ""),
                    "evidence_quote": row.get("evidence_quote", ""),
                    "adjudication_status": row.get("adjudication_status", ""),
                    "limitation": "Reviewed source fact shown for evidence; it is not a complete GP track record or a numerical GP rating.",
                }
            )
    return selected
