from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DOC_DIR = DATA_DIR / "documents"
GENERATOR_VERSION = "gp_v2_cases_3"
SEED = 20260909


class CaseGenerationError(ValueError):
    pass


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_int(*parts: str) -> int:
    text = "|".join(parts).encode("utf-8")
    return int(hashlib.sha256(text).hexdigest()[:16], 16)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    temporary.replace(path)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def _selected_managers(parent: Path) -> list[dict[str, str]]:
    rows = read_csv(HERE / "04-diagnostics/manager-diagnostics.csv")
    ranked = [row for row in rows if row.get("v1_status") == "RANKED_DEMO"]
    buyout = sorted(
        [row for row in ranked if row.get("strategy") == "buyout"],
        key=lambda row: (int(row["historical_rank"]), row["manager_id"]),
    )[:2]
    secondaries = [row for row in ranked if row.get("strategy") == "secondaries"]
    secondaries.sort(
        key=lambda row: (
            -float(row.get("avg_nav_reliance") or -1),
            int(row.get("historical_rank") or 10**9),
            row["manager_id"],
        )
    )
    selected = [*buyout, *(secondaries[:1])]
    if len(selected) != 3:
        raise CaseGenerationError("case selection requires two ranked buyout managers and one ranked secondaries manager")
    if len({row["manager_id"] for row in selected}) != 3:
        raise CaseGenerationError("case manager selection is not unique")
    return selected


def _case_profiles(selected: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    profiles = (
        {
            "profile_id": "GP_COMMITMENT_CONTRADICTION",
            "purpose": "A high-ranked buyout manager with a deliberate DDQ/LPA contradiction and an LPAC review event.",
        },
        {
            "profile_id": "TEAM_ATTRIBUTION_BREAK",
            "purpose": "A high-ranked buyout manager with a senior departure after valid historical deal work.",
        },
        {
            "profile_id": "SECONDARIES_FINANCING",
            "purpose": "A secondaries manager with explicit fund-financing terms, incomplete succession evidence, and a higher NAV-reliance profile.",
        },
    )
    result = []
    for index, (manager, profile) in enumerate(zip(selected, profiles), 1):
        result.append(
            {
                "case_id": f"CASE_{index:03d}",
                "profile_id": profile["profile_id"],
                "purpose": profile["purpose"],
                "manager_id": manager["manager_id"],
                "manager_name": manager["manager_name"],
                "strategy": manager["strategy"],
                "sub_strategy": manager.get("sub_strategy", ""),
                "fund_id": manager["latest_fund_id"],
                "historical_score": manager["historical_score"],
                "historical_rank": manager["historical_rank"],
                "avg_nav_reliance": manager.get("avg_nav_reliance", ""),
            }
        )
    return result


def _team_rows(cases: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    roles = ("Managing Partner", "Partner", "Partner", "Principal")
    rows: list[dict[str, Any]] = []
    for case in cases:
        rng = random.Random(_stable_int(str(SEED), case["manager_id"], "TEAM"))
        base_year = 2012 + rng.randrange(0, 4)
        for order, role in enumerate(roles, 1):
            join_year = base_year + order * 2
            join_date = date(join_year, 1 + (order * 2) % 10, 1 + order * 3)
            departure = ""
            if case["profile_id"] == "TEAM_ATTRIBUTION_BREAK" and order == 2:
                departure = "2025-03-31"
            rows.append(
                {
                    "person_id": f"PERSON_{case['manager_id'][-5:]}_{order:02d}",
                    "case_id": case["case_id"],
                    "manager_id": case["manager_id"],
                    "person_name": f"Synthetic Investment Professional {case['manager_id'][-3:]}-{order}",
                    "role": role,
                    "seniority": "senior" if order <= 3 else "mid_level",
                    "join_date": join_date.isoformat(),
                    "departure_date": departure,
                    "ownership_pct": f"{max(0.02, 0.22 - order * 0.035):.4f}",
                    "carry_participation": "true",
                    "source_kind": "SYNTHETIC_CASE",
                    "evidence_id": f"EV_TEAM_{case['case_id']}_{order:02d}",
                    "synthetic_flag": "true",
                    "generator_version": GENERATOR_VERSION,
                }
            )
    return rows


def _selected_companies(parent: Path, cases: Sequence[Mapping[str, str]]) -> dict[str, list[dict[str, str]]]:
    holdings = read_csv(parent / "data/synthetic/clean/fund_holdings.csv")
    by_case: dict[str, list[dict[str, str]]] = {}
    for case in cases:
        rows = [
            row
            for row in holdings
            if row.get("fund_id") == case["fund_id"] and row.get("as_of_date") == "2026-06-30" and row.get("record_status") == "ACTIVE"
        ]
        by_company: dict[str, dict[str, str]] = {}
        for row in sorted(rows, key=lambda value: (value.get("portfolio_company_id", ""), value.get("instrument_id", ""))):
            by_company.setdefault(row["portfolio_company_id"], row)
        companies = list(by_company.values())
        if len(companies) < 3:
            raise CaseGenerationError(f"case {case['case_id']} requires at least three current company identities")
        by_case[case["case_id"]] = companies[: min(4, len(companies))]
    return by_case


def _attribution_rows(cases: Sequence[Mapping[str, str]], teams: Sequence[Mapping[str, Any]], companies: Mapping[str, Sequence[Mapping[str, str]]]) -> list[dict[str, Any]]:
    people_by_case: dict[str, list[Mapping[str, Any]]] = {}
    for case in cases:
        people_by_case[case["case_id"]] = [row for row in teams if row["case_id"] == case["case_id"]]
    rows: list[dict[str, Any]] = []
    for case in cases:
        people = people_by_case[case["case_id"]]
        for order, company in enumerate(companies[case["case_id"]], 1):
            # The team-break case assigns one historical deal to the person who later departed.
            if case["profile_id"] == "TEAM_ATTRIBUTION_BREAK" and order == 1:
                person = people[1]
            else:
                person = people[(order - 1) % min(3, len(people))]
            action = date(2021 + (order % 3), 2 + order, 10 + order)
            if action < date.fromisoformat(str(person["join_date"])):
                action = date.fromisoformat(str(person["join_date"])) + timedelta(days=90)
            rows.append(
                {
                    "attribution_id": f"ATTR_{case['case_id']}_{order:02d}",
                    "case_id": case["case_id"],
                    "manager_id": case["manager_id"],
                    "fund_id": case["fund_id"],
                    "portfolio_company_id": company["portfolio_company_id"],
                    "person_id": person["person_id"],
                    "action_date": action.isoformat(),
                    "role": "lead",
                    "attribution_weight": "1.000000",
                    "source_kind": "SYNTHETIC_CASE",
                    "evidence_id": f"EV_ATTR_{case['case_id']}_{order:02d}",
                    "synthetic_flag": "true",
                    "generator_version": GENERATOR_VERSION,
                }
            )
    return rows


def _fact_rows(cases: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(case: Mapping[str, str], family: str, field: str, *, value_numeric: str = "", value_text: str = "", unit: str = "", effective: str = "2026-06-30", available: str = "2026-07-15", conflict: str = "", review: str = "ACCEPTED") -> None:
        sequence = 1 + sum(1 for row in rows if row["case_id"] == case["case_id"])
        fact_id = f"FACT_{case['case_id']}_{sequence:03d}"
        rows.append(
            {
                "fact_id": fact_id,
                "case_id": case["case_id"],
                "manager_id": case["manager_id"],
                "fund_id": case["fund_id"],
                "document_family": family,
                "field_name": field,
                "value_numeric": value_numeric,
                "value_text": value_text,
                "unit": unit,
                "effective_date": effective,
                "available_at": available,
                "locator": f"#{fact_id.lower()}",
                "review_status": review,
                "conflict_group": conflict,
                "source_kind": "SYNTHETIC_CASE_DOCUMENT",
                "synthetic_flag": "true",
                "generator_version": GENERATOR_VERSION,
            }
        )

    for case in cases:
        add(case, "ddq", "current_strategy", value_text=f"{case['strategy']} / {case['sub_strategy']}")
        add(case, "ddq", "valuation_policy", value_text="Quarterly marks are reviewed by the valuation committee; material overrides require documented rationale.")
        add(case, "lpa_terms", "key_person_provision", value_text="Departure of two named senior professionals suspends the investment period pending LPAC review.")
        add(case, "lpa_terms", "management_fee_rate", value_numeric="0.018", unit="decimal_rate")
        add(case, "lpa_terms", "carry_rate", value_numeric="0.20", unit="decimal_rate")
        add(case, "lpa_terms", "hurdle_rate", value_numeric="0.08", unit="decimal_rate")
        if case["profile_id"] == "GP_COMMITMENT_CONTRADICTION":
            group = f"CONFLICT_{case['case_id']}_GP_COMMITMENT"
            add(case, "ddq", "gp_commitment_pct", value_numeric="0.025", unit="decimal_rate", conflict=group, review="REVIEW_REQUIRED")
            add(case, "lpa_terms", "gp_commitment_pct", value_numeric="0.020", unit="decimal_rate", conflict=group, review="REVIEW_REQUIRED")
            add(case, "ddq", "governance_event", value_text="LPAC review opened for a proposed related-party continuation process.", effective="2026-04-15")
            add(case, "ddq", "succession_plan", value_text="Documented internal succession plan names two potential successors.")
        elif case["profile_id"] == "TEAM_ATTRIBUTION_BREAK":
            add(case, "lpa_terms", "gp_commitment_pct", value_numeric="0.030", unit="decimal_rate")
            add(case, "team_roster", "senior_departure", value_text="One senior partner departed on 2025-03-31 after leading a case investment before departure.", effective="2025-03-31", available="2025-04-15")
            add(case, "ddq", "succession_plan", value_text="Internal successor was appointed to the departed partner's portfolio coverage.")
            add(case, "ddq", "governance_event", value_text="none_observed_in_case_material")
        else:
            add(case, "lpa_terms", "gp_commitment_pct", value_numeric="0.015", unit="decimal_rate")
            add(case, "lpa_terms", "subscription_facility_limit_pct", value_numeric="0.15", unit="decimal_rate")
            add(case, "lpa_terms", "subscription_facility_cost_rate", value_numeric="0.055", unit="decimal_rate")
            add(case, "lpa_terms", "subscription_facility_max_days", value_numeric="180", unit="days")
            add(case, "lpa_terms", "nav_facility_flag", value_text="false")
            add(case, "ddq", "governance_event", value_text="none_observed_in_case_material")
            # Succession is deliberately omitted to demonstrate unknown evidence.
    return rows


def _economic_rows(cases: Sequence[Mapping[str, str]], companies: Mapping[str, Sequence[Mapping[str, str]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    event_rows: list[dict[str, Any]] = []
    valuation_rows: list[dict[str, Any]] = []
    profiles = (
        ("realized_winner", 25.0, 45.0, 0.0, "2025-12-31", "2026-03-31", 35.0),
        ("realized_loss", 20.0, 12.0, 0.0, "2025-12-31", "2026-04-15", 15.0),
        ("writeoff", 10.0, 0.0, 0.0, "2025-09-30", "2026-02-28", 4.0),
        ("active_partial", 45.0, 10.0, 60.0, "2026-06-30", "", 60.0),
    )
    regions = ("North America", "Europe", "North America", "Asia Pacific")
    for case in cases:
        available_companies = list(companies[case["case_id"]])
        if len(available_companies) == 3:
            use_profiles = (profiles[0], profiles[1], profiles[3])
        else:
            use_profiles = profiles[: len(available_companies)]
        for order, (company, spec) in enumerate(zip(available_companies, use_profiles), 1):
            status, cost, proceeds, remaining, mark_date, exit_date, mark = spec
            invest_date = date(2021 + order % 2, 3 + order, 10)
            event_rows.append(
                {
                    "event_id": f"CASEEV_{case['case_id']}_{order:02d}_INVEST",
                    "case_id": case["case_id"],
                    "manager_id": case["manager_id"],
                    "fund_id": case["fund_id"],
                    "portfolio_company_id": company["portfolio_company_id"],
                    "instrument_id": company["instrument_id"],
                    "event_date": invest_date.isoformat(),
                    "event_type": "investment",
                    "invested_cost": f"{cost:.6f}",
                    "proceeds": "",
                    "distribution": "",
                    "fee": "",
                    "carry": "",
                    "facility_draw": "",
                    "facility_repayment": "",
                    "facility_interest": "",
                    "currency": "USD",
                    "status_after_event": "active",
                    "evidence_id": f"EV_CASE_{case['case_id']}_{order:02d}_INVEST",
                    "synthetic_flag": "true",
                    "generator_version": GENERATOR_VERSION,
                }
            )
            if status in {"realized_loss", "writeoff", "realized_winner"}:
                realized_date = date.fromisoformat(exit_date)
                event_rows.append(
                    {
                        "event_id": f"CASEEV_{case['case_id']}_{order:02d}_EXIT",
                        "case_id": case["case_id"],
                        "manager_id": case["manager_id"],
                        "fund_id": case["fund_id"],
                        "portfolio_company_id": company["portfolio_company_id"],
                        "instrument_id": company["instrument_id"],
                        "event_date": realized_date.isoformat(),
                        "event_type": "realization",
                        "invested_cost": "",
                        "proceeds": f"{proceeds:.6f}",
                        "distribution": f"{proceeds:.6f}",
                        "fee": "",
                        "carry": "",
                        "facility_draw": "",
                        "facility_repayment": "",
                        "facility_interest": "",
                        "currency": "USD",
                        "status_after_event": "writeoff" if status == "writeoff" else "realized",
                        "evidence_id": f"EV_CASE_{case['case_id']}_{order:02d}_EXIT",
                        "synthetic_flag": "true",
                        "generator_version": GENERATOR_VERSION,
                    }
                )
            elif proceeds > 0:
                event_rows.append(
                    {
                        "event_id": f"CASEEV_{case['case_id']}_{order:02d}_PARTIAL",
                        "case_id": case["case_id"], "manager_id": case["manager_id"], "fund_id": case["fund_id"],
                        "portfolio_company_id": company["portfolio_company_id"], "instrument_id": company["instrument_id"],
                        "event_date": "2026-03-15", "event_type": "partial_realization", "invested_cost": "", "proceeds": f"{proceeds:.6f}",
                        "distribution": f"{proceeds:.6f}", "fee": "", "carry": "", "facility_draw": "", "facility_repayment": "", "facility_interest": "",
                        "currency": "USD", "status_after_event": "active", "evidence_id": f"EV_CASE_{case['case_id']}_{order:02d}_PARTIAL", "synthetic_flag": "true", "generator_version": GENERATOR_VERSION,
                    }
                )
            valuation_rows.append(
                {
                    "valuation_id": f"CASEVAL_{case['case_id']}_{order:02d}",
                    "case_id": case["case_id"],
                    "manager_id": case["manager_id"],
                    "fund_id": case["fund_id"],
                    "portfolio_company_id": company["portfolio_company_id"],
                    "instrument_id": company["instrument_id"],
                    "valuation_date": mark_date,
                    "fair_value": f"{mark:.6f}",
                    "remaining_value": f"{remaining:.6f}",
                    "invested_cost": f"{cost:.6f}",
                    "status": "active" if status == "active_partial" else "pre_exit_mark",
                    "sector": company.get("sector", ""),
                    "geography": regions[(order - 1) % len(regions)],
                    "ownership_pct": f"{mark / ((40 + 5 * order) * (0.16 + 0.015 * order) * (9.0 + 0.7 * order) - (18 - 2 * order)):.12f}",
                    "revenue": f"{(40 + 5 * order):.6f}",
                    "ebitda_margin": f"{(0.16 + 0.015 * order):.6f}",
                    "ev_ebitda_multiple": f"{(9.0 + 0.7 * order):.6f}",
                    "net_debt": f"{(18 - 2 * order):.6f}",
                    "fx_to_usd": "1.000000",
                    "evidence_id": f"EV_CASE_{case['case_id']}_{order:02d}_VAL",
                    "synthetic_flag": "true",
                    "generator_version": GENERATOR_VERSION,
                }
            )
        investments = [row for row in event_rows if row["case_id"] == case["case_id"] and row["event_type"] == "investment"]
        financed = max(investments, key=lambda row: float(row["invested_cost"])) if case["profile_id"] == "SECONDARIES_FINANCING" else None

        def funding(suffix: str, moment: str, kind: str, **amounts: float) -> None:
            row = {key: "" for key in investments[0]}
            row.update(case_id=case["case_id"], manager_id=case["manager_id"], fund_id=case["fund_id"],
                       event_id=f"CASEEV_{case['case_id']}_{suffix}", evidence_id=f"EV_CASE_{case['case_id']}_{suffix}",
                       event_date=moment, event_type=kind, currency="USD", status_after_event="funded",
                       synthetic_flag="true", generator_version=GENERATOR_VERSION)
            row.update({key: f"{value:.6f}" for key, value in amounts.items()})
            event_rows.append(row)

        for order, investment in enumerate(investments, 1):
            cost = float(investment["invested_cost"])
            borrowed = 30.0 if investment is financed else 0.0
            moment = investment["event_date"]
            funding(f"LP_CALL_{order}", moment, "lp_capital_call", invested_cost=cost-borrowed, fee=cost*0.018)
            if borrowed:
                repayment = (date.fromisoformat(moment) + timedelta(days=90)).isoformat()
                interest = round(borrowed * 0.055 * 90 / 365, 6)
                funding("FACILITY_DRAW", moment, "facility_draw", facility_draw=borrowed)
                funding("LP_REPAY_CALL", repayment, "lp_capital_call", invested_cost=borrowed, facility_interest=interest)
                funding("FACILITY_REPAY", repayment, "facility_repayment", facility_repayment=borrowed, facility_interest=interest)
    return event_rows, valuation_rows


def _render_document(family: str, cases: Sequence[Mapping[str, str]], facts: Sequence[Mapping[str, Any]], teams: Sequence[Mapping[str, Any]], attributions: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]], valuations: Sequence[Mapping[str, Any]]) -> str:
    blocks = []
    for case in cases:
        case_facts = [row for row in facts if row["case_id"] == case["case_id"] and row["document_family"] == family]
        if family == "team_roster":
            rows = [row for row in teams if row["case_id"] == case["case_id"]]
            table = "".join(f"<tr id='{html.escape(str(row['evidence_id']).lower())}'><td>{html.escape(str(row['person_name']))}</td><td>{html.escape(str(row['role']))}</td><td>{row['join_date']}</td><td>{row['departure_date'] or 'Active'}</td></tr>" for row in rows)
            body = f"<table><tr><th>Professional</th><th>Role</th><th>Joined</th><th>Departure</th></tr>{table}</table>"
        elif family == "portfolio_investments":
            rows = [row for row in valuations if row["case_id"] == case["case_id"]]
            table = "".join(f"<tr id='{html.escape(str(row['evidence_id']).lower())}'><td>{row['portfolio_company_id']}</td><td>{row['sector']}</td><td>{row['geography']}</td><td>{row['invested_cost']}</td><td>{row['fair_value']}</td><td>{row['status']}</td></tr>" for row in rows)
            body = f"<table><tr><th>Company</th><th>Sector</th><th>Region</th><th>Case cost</th><th>Mark</th><th>Status</th></tr>{table}</table>"
        elif family == "track_record":
            body = f"<p>Controlled fixture reference. Historical score: {html.escape(case['historical_score'])}. Historical rank within {html.escape(case['strategy'])}: {html.escape(case['historical_rank'])}. These values are inherited from the V1 synthetic scorecard and are not generated by this case document.</p>"
        elif family == "valuation_memo":
            rows = [row for row in valuations if row["case_id"] == case["case_id"]]
            body = "".join(f"<section id='{html.escape(str(row['evidence_id']).lower())}'><h3>{row['portfolio_company_id']}</h3><p>Case valuation date {row['valuation_date']}; fair value {row['fair_value']} USD; status {row['status']}.</p><p>Revenue {row['revenue']}; operating profit margin {row['ebitda_margin']}; business value divided by operating profit {row['ev_ebitda_multiple']}; net debt {row['net_debt']}; fund ownership fraction {row['ownership_pct']}; dollar conversion {row['fx_to_usd']}. The fictional ownership fraction reconciles the declared company economics with its fund value.</p></section>" for row in rows)
        else:
            body = ""
        body += "".join(
                f"<section id='{html.escape(str(row['fact_id']).lower())}'><h3>{html.escape(str(row['field_name']).replace('_',' ').title())}</h3><p>{html.escape(str(row['value_text'] or row['value_numeric']))}{(' ' + html.escape(str(row['unit']))) if row['unit'] else ''}</p><small>Effective {row['effective_date']}; available {row['available_at']}; review {row['review_status']}</small></section>"
                for row in case_facts
            )
        blocks.append(f"<article id='{case['case_id'].lower()}'><h2>{html.escape(case['manager_name'])} | {html.escape(case['case_id'])}</h2><p><strong>Synthetic case material.</strong> {html.escape(case['purpose'])}</p>{body}</article>")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>GP V2 {html.escape(family)}</title><style>body{{font-family:Arial,sans-serif;max-width:1000px;margin:30px auto;line-height:1.45}}article{{border-top:2px solid #333;padding:20px 0}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #bbb;padding:7px;text-align:left}}small{{color:#555}}</style></head><body><h1>{html.escape(family.replace('_',' ').title())}</h1><p>Fictional material generated for the GP Scoring V2 diligence demonstration. It is not a real manager document.</p>{''.join(blocks)}</body></html>"


def generate(parent: Path) -> dict[str, Any]:
    selected = _selected_managers(parent)
    cases = _case_profiles(selected)
    companies = _selected_companies(parent, cases)
    teams = _team_rows(cases)
    attributions = _attribution_rows(cases, teams, companies)
    facts = _fact_rows(cases)
    events, valuations = _economic_rows(cases, companies)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(DATA_DIR / "team-history.csv", teams)
    _write_csv(DATA_DIR / "deal-attribution.csv", attributions)
    _write_csv(DATA_DIR / "diligence-facts.csv", facts)
    _write_csv(DATA_DIR / "case-events.csv", events)
    _write_csv(DATA_DIR / "case-valuations.csv", valuations)

    families = ("ddq", "lpa_terms", "track_record", "team_roster", "portfolio_investments", "valuation_memo")
    registry: list[dict[str, Any]] = []
    for family in families:
        filename = f"{family.replace('_', '-')}.html"
        path = DOC_DIR / filename
        text = _render_document(family, cases, facts, teams, attributions, events, valuations)
        path.write_text(text, encoding="utf-8", newline="\n")
        for case in cases:
            registry.append(
                {
                    "document_id": f"DOC_{family.upper()}_{case['case_id']}",
                    "case_id": case["case_id"],
                    "manager_id": case["manager_id"],
                    "fund_id": case["fund_id"],
                    "document_family": family,
                    "path": str(path.relative_to(HERE)).replace("\\", "/"),
                    "sha256": sha256_file(path),
                    "effective_date": "2026-06-30",
                    "available_at": "2026-07-15",
                    "case_locator": f"#{case['case_id'].lower()}",
                    "source_kind": "SYNTHETIC_CASE_DOCUMENT",
                    "synthetic_flag": "true",
                    "generator_version": GENERATOR_VERSION,
                }
            )
    _write_csv(DATA_DIR / "document-registry.csv", registry)

    expected = {
        "generator_version": GENERATOR_VERSION,
        "cases": {case["case_id"]: case for case in cases},
        "facts": {row["fact_id"]: row for row in facts},
        "required_case_properties": {
            "deliberate_contradiction": "CONFLICT_CASE_001_GP_COMMITMENT",
            "senior_departure_case": "CASE_002",
            "secondaries_financing_case": "CASE_003",
        },
    }
    _write_json(DATA_DIR / "expected-facts.json", expected)

    input_paths = [
        HERE / "04-diagnostics/manager-diagnostics.csv",
        HERE / "04-diagnostics/fund-diagnostics.csv",
        parent / "data/synthetic/clean/fund_holdings.csv",
        parent / "data/synthetic/clean/fund_master.csv",
        parent / "data/synthetic/clean/fund_terms.csv",
    ]
    outputs = [
        DATA_DIR / "team-history.csv",
        DATA_DIR / "deal-attribution.csv",
        DATA_DIR / "diligence-facts.csv",
        DATA_DIR / "case-events.csv",
        DATA_DIR / "case-valuations.csv",
        DATA_DIR / "document-registry.csv",
        DATA_DIR / "expected-facts.json",
        *[DOC_DIR / f"{family.replace('_', '-')}.html" for family in families],
    ]
    manifest = {
        "status": "PASS",
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "population": "case_simulation",
        "selection_policy": "top two ranked buyout managers plus the ranked secondaries manager with highest average NAV reliance",
        "cases": cases,
        "input_hashes": {str(path.resolve().relative_to(parent.resolve())).replace("\\", "/"): sha256_file(path) for path in input_paths},
        "output_hashes": {str(path.relative_to(HERE)).replace("\\", "/"): sha256_file(path) for path in outputs},
        "row_counts": {
            "team_history": len(teams),
            "deal_attribution": len(attributions),
            "diligence_facts": len(facts),
            "case_events": len(events),
            "case_valuations": len(valuations),
            "document_registry": len(registry),
        },
        "limitations": [
            "Case economics are independent synthetic scenarios and do not reconstruct the parent fixture's historical deal economics.",
            "Selected company IDs are reused only as stable fictional identities; case investment dates, costs, proceeds and marks are new declared assumptions.",
            "Case documents are generated HTML and never claim to be PDFs or real manager diligence materials.",
            "No case value enters the fixture leaderboard or V1 historical score.",
        ],
    }
    _write_json(DATA_DIR / "case-manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate bounded synthetic diligence cases for GP Scoring V2")
    parser.add_argument("--parent", default=".")
    args = parser.parse_args()
    manifest = generate(Path(args.parent).resolve())
    print(
        f"PASS cases={len(manifest['cases'])} facts={manifest['row_counts']['diligence_facts']} "
        f"events={manifest['row_counts']['case_events']} documents={manifest['row_counts']['document_registry']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
