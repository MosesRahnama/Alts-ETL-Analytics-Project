"""Capital recovery, benchmark wealth and company operating scenarios."""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping

from src.analytics.run_round04_analytics import _build_benchmark_series


class InvestmentAnalysisError(ValueError):
    pass


def number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise InvestmentAnalysisError("finite amount required")
    return result


def agrees(left: float, right: float, policy: Mapping[str, Any]) -> bool:
    return math.isclose(left, right, rel_tol=policy["reconciliation_relative_tolerance"],
                        abs_tol=policy["reconciliation_absolute_tolerance"])


def capital_recovery(paid: float, distributions: float, nav: float) -> dict[str, Any]:
    paid, distributions, nav = map(number, (paid, distributions, nav))
    if paid <= 0 or min(distributions, nav) < 0:
        raise InvestmentAnalysisError("positive paid-in and nonnegative value required")
    gap = max(paid - distributions, 0.0)
    return {
        "paid_in": paid, "distributions": distributions, "remaining_nav": nav,
        "capital_still_to_return": gap,
        "nav_needed_for_capital_multiple": gap / nav if nav else None,
        "nav_haircut_to_capital": 1 - gap / nav if nav else None,
        "capital_recovery_status": ("RETURNED_IN_CASH" if gap == 0 else
                                    "NAV_BELOW_CAPITAL_GAP" if gap > nav else "DEPENDS_ON_REMAINING_VALUE"),
    }


def benchmark_wealth(period: Mapping[str, Any], flows: list[Mapping[str, Any]], series: Any) -> dict[str, Any]:
    terminal = date.fromisoformat(period["as_of_date"])
    nav = number(period["nav"])
    end = series.as_of(terminal)
    calls = distributions = 0.0
    inputs = []
    for flow in flows:
        moment = date.fromisoformat(flow["cashflow_date"])
        if moment > terminal:
            continue
        if flow.get("base_currency") != period["currency"]:
            raise InvestmentAnalysisError("benchmark cash-flow currency mismatch")
        amount = number(flow["amount_base_currency"])
        point = series.as_of(moment)
        future_value = amount * end.level / point.level
        calls += max(-future_value, 0.0)
        distributions += max(future_value, 0.0)
        inputs.append({"cashflow_id": flow["cashflow_id"], "date": moment.isoformat(),
                       "amount": amount, "benchmark_return_id": point.record_id,
                       "benchmark_date": point.return_date.isoformat(), "terminal_value": future_value})
    if calls <= 0 or nav < 0:
        raise InvestmentAnalysisError("benchmark comparison requires contributions and nonnegative NAV")
    needed = max(calls - distributions, 0.0)
    return {"benchmark_capital": calls, "benchmark_distributions": distributions,
            "benchmark_excess_value": distributions + nav - calls,
            "nav_needed_to_match_benchmark": needed,
            "nav_haircut_to_match_benchmark": 1 - needed / nav if nav else None,
            "benchmark_recomputed_pme": (distributions + nav) / calls,
            "benchmark_terminal_id": end.record_id, "benchmark_terminal_date": end.return_date.isoformat(),
            "benchmark_cashflows": inputs}


def enrich_core(context: Mapping[str, Any], funds: list[dict[str, Any]], managers: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> None:
    policy = context["policy"]["investment_analysis"]
    weights = context["v1_policy"]["weights"]
    series = {}
    for fund in funds:
        fund["capital_recovery_status"] = "CURRENT_DATA_UNAVAILABLE"
        if fund["current_status"] != "AVAILABLE":
            continue
        current = context["current_by_fund"][fund["fund_id"]]
        fund.update(capital_recovery(current["paid_in_capital_itd"], current["distributions_itd"], current["nav"]))
        result: dict[str, Any] = {}
        if fund["benchmark_status"] == "AVAILABLE":
            benchmark = fund["benchmark_id"]
            if benchmark not in series:
                series[benchmark] = _build_benchmark_series(context["benchmarks"], benchmark, None)
            series[benchmark].refuse_if_past_end(date.fromisoformat(current["as_of_date"]), benchmark)
            result = benchmark_wealth(current, context["flows_by_fund"].get(fund["fund_id"], []), series[benchmark])
            if not agrees(result["benchmark_recomputed_pme"], fund["ks_pme"], policy):
                raise InvestmentAnalysisError("benchmark wealth differs from published PME")
            fund.update({key: value for key, value in result.items() if key != "benchmark_cashflows"})
        alpha = fund.get("direct_alpha")
        fund["direct_alpha_continuous"] = math.log1p(alpha) if alpha is not None and alpha > -1 else None
        evidence.append({"feature_id": f"F:{fund['fund_id']}:CAPITAL", "feature": "capital_and_benchmark_wealth",
                         "entity_id": fund["fund_id"], "population": "fixture", "currency": fund["currency"],
                         "as_of_date": current["as_of_date"], "formula_id": "v2_analysis.capital_recovery_and_benchmark_wealth",
                         "input_ids": [current["fund_period_id"], *[row["cashflow_id"] for row in result.get("benchmark_cashflows", [])]],
                         "values": {key: fund.get(key) for key in ("capital_still_to_return", "nav_haircut_to_capital", "benchmark_excess_value", "nav_haircut_to_match_benchmark")},
                         "benchmark_detail": result})
    by_fund = {row["fund_id"]: row for row in funds}
    for manager in managers:
        selected = [by_fund[fid] for fid in manager["eligible_fund_ids"]]
        count = len(selected)
        manager["score_tvpi_points"] = sum(row["v1_tvpi_percentile"] * weights["tvpi"] for row in selected) / count if count else None
        manager["score_dpi_points"] = sum(row["v1_dpi_percentile"] * weights["dpi"] for row in selected) / count if count else None
        manager["benchmark_fund_count"] = sum(row.get("ks_pme") is not None for row in selected)
        manager["benchmark_beating_count"] = sum(row.get("ks_pme") is not None and row["ks_pme"] > 1 for row in selected)
        manager["capital_returned_fund_count"] = sum(row.get("capital_recovery_status") == "RETURNED_IN_CASH" for row in selected)
        manager["scored_fund_currencies"] = sorted({row["currency"] for row in selected})
        manager["score_contributions"] = [{"fund_id": row["fund_id"],
                                           "tvpi_points": row["v1_tvpi_percentile"] * weights["tvpi"] / count,
                                           "dpi_points": row["v1_dpi_percentile"] * weights["dpi"] / count} for row in selected]


def operating_downside(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    spec = policy["operating_downside"]
    if spec["order"] != ["revenue", "margin", "multiple"] or spec["fixed"] != ["net_debt", "ownership_pct", "fx_to_usd"]:
        raise InvestmentAnalysisError("unsupported operating scenario order or fixed inputs")
    revenue, margin, multiple, debt, ownership, fx, fair = [number(row[field]) for field in
        ("revenue", "ebitda_margin", "ev_ebitda_multiple", "net_debt", "ownership_pct", "fx_to_usd", "fair_value")]
    if revenue < 0 or not 0 <= margin <= 1 or multiple <= 0 or not 0 < ownership <= 1 or fx <= 0 or fair < 0:
        raise InvestmentAnalysisError("operating inputs outside bounds")
    def equity(r: float, m: float, v: float) -> float:
        return max(r * m * v - debt, 0.0) * ownership * fx
    baseline = equity(revenue, margin, multiple)
    if not agrees(baseline, fair, policy):
        raise InvestmentAnalysisError(f"operating inputs differ from case mark: {row.get('valuation_id')}")
    r2, m2, v2 = revenue * (1 + spec["revenue_change"]), margin + spec["margin_change"], multiple + spec["multiple_change"]
    if r2 < 0 or not 0 <= m2 <= 1 or v2 <= 0:
        raise InvestmentAnalysisError("operating scenario outside bounds")
    first, second, last = equity(r2, margin, multiple), equity(r2, m2, multiple), equity(r2, m2, v2)
    return {"valuation_id": row["valuation_id"], "company_id": row["portfolio_company_id"],
            "baseline_value": fair, "formula_value": baseline, "rounding_adjustment": baseline - fair,
            "revenue_effect": first - baseline, "margin_effect": second - first,
            "multiple_effect": last - second, "scenario_value": last,
            "value_change": last - fair, "scenario_id": "operating_downside",
            "source_id": row["evidence_id"], "assumptions": dict(spec)}


def case_investments(context: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    events = [r for r in context["overlay"]["case-events.csv"] if r["case_id"] == case_id]
    marks = [r for r in context["overlay"]["case-valuations.csv"] if r["case_id"] == case_id]
    rows, operating = [], []
    policy = context["policy"]["investment_analysis"]
    investments = sorted((r for r in events if r["event_type"] == "investment"), key=lambda r: r["portfolio_company_id"])
    companies = [r["portfolio_company_id"] for r in investments]
    if not companies or len(companies) != len(set(companies)) or set(companies) != {r["portfolio_company_id"] for r in marks}:
        raise InvestmentAnalysisError("case requires one investment and one valuation per company")
    for investment in investments:
        company = investment["portfolio_company_id"]
        company_events = [r for r in events if r.get("portfolio_company_id") == company]
        company_marks = [r for r in marks if r["portfolio_company_id"] == company]
        if len(company_marks) != 1:
            raise InvestmentAnalysisError("case deal requires one declared valuation record")
        mark = company_marks[0]
        cost = number(investment["invested_cost"])
        cash = [number(r["proceeds"]) for r in company_events if r.get("proceeds")]
        proceeds = sum(cash)
        remaining = number(mark["remaining_value"])
        if cost <= 0 or remaining < 0 or any(value < 0 for value in cash):
            raise InvestmentAnalysisError("case requires positive cost and nonnegative investment value")
        gain = proceeds + remaining - cost
        realized = any(r["event_type"] == "realization" for r in company_events)
        rows.append({"company_id": company, "cost": cost, "proceeds": proceeds, "remaining_value": remaining,
                     "gain": gain, "gross_multiple": (proceeds + remaining) / cost,
                     "realized_loss": max(cost - proceeds, 0.0) if realized else None,
                     "status": "REALIZED" if realized else "ACTIVE", "source_ids": [r["evidence_id"] for r in company_events] + [mark["evidence_id"]]})
        calculation = operating_downside(mark, policy)
        if mark["status"] == "active":
            if not agrees(remaining, number(mark["fair_value"]), policy):
                raise InvestmentAnalysisError("active case remaining value differs from mark")
            operating.append(calculation)
    total_cost = sum(row["cost"] for row in rows)
    positive = sum(max(row["gain"], 0) for row in rows)
    winner = max(rows, key=lambda row: (row["gain"], row["company_id"]))
    remaining_cost = total_cost - winner["cost"]
    return {"deals": rows, "operating_results": operating,
            "positive_gain_top_deal_share": max(winner["gain"], 0) / positive if positive > 0 else None,
            "best_deal_id": winner["company_id"],
            "gross_multiple_ex_best_deal": sum(row["proceeds"] + row["remaining_value"] for row in rows if row is not winner) / remaining_cost if remaining_cost > 0 else None,
            "realized_loss_amount": sum(row["realized_loss"] or 0 for row in rows),
            "operating_value_change": sum(row["value_change"] for row in operating)}
