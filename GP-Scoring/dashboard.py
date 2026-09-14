from __future__ import annotations

import base64
import csv
import html
import io
import json
from collections import Counter
from typing import Any, Iterable, Mapping


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _pct(value: str) -> str:
    return "" if value == "" else f"{100.0 * float(value):.0f}%"


def _num(value: str, digits: int = 1) -> str:
    return "" if value == "" else f"{float(value):.{digits}f}"


def _multiple(value: str) -> str:
    return "" if value == "" else f"{float(value):.2f}x"


def _claim_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("text", ""))
    return str(value)


def csv_text(rows: list[Mapping[str, Any]], fieldnames: Iterable[str] | None = None) -> str:
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(fieldnames), extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def _download(label: str, filename: str, content: str) -> str:
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return f'<a class="download" download="{_e(filename)}" href="data:text/csv;base64,{encoded}">{_e(label)}</a>'


def _table(headers: list[tuple[str, str]], rows: list[Mapping[str, Any]]) -> str:
    head = "".join(f"<th>{_e(label)}</th>" for _, label in headers)
    body: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{_e(row.get(field, ''))}</td>" for field, _ in headers)
        body.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def render_dashboard(
    metadata: Mapping[str, Any],
    policy: Mapping[str, Any],
    scorecards: list[dict[str, str]],
    features: list[dict[str, str]],
    decisions: list[dict[str, str]],
    observed_cards: list[dict[str, Any]],
    briefs: list[dict[str, Any]],
) -> str:
    as_of = str(metadata.get("as_of_date", ""))
    build_id = str(metadata.get("build_id", ""))
    report_id = str(metadata.get("report_id", ""))
    initial_strategy = str(policy.get("initial_strategy", "buyout"))
    ranked = [row for row in scorecards if row.get("status") == "RANKED_DEMO"]
    ranked_initial = [row for row in ranked if row.get("strategy") == initial_strategy]
    ranked_initial.sort(key=lambda row: (int(row.get("rank") or 10**9), row.get("manager_id", "")))
    partial_initial = [
        row for row in scorecards if row.get("strategy") == initial_strategy and row.get("status") != "RANKED_DEMO"
    ]
    feature_by_fund = {row["fund_id"]: row for row in features}
    brief_by_key = {row["manager_key"]: row for row in briefs}

    comparison_rows = []
    for row in ranked_initial[:25]:
        comparison_rows.append(
            {
                "rank": row["rank"],
                "manager": row["manager_name"],
                "score": _num(row["score"]),
                "TVPI peer %ile": _num(row["avg_tvpi_percentile"]),
                "DPI peer %ile": _num(row["avg_dpi_percentile"]),
                "funds": f"{row['eligible_funds']}/{row['total_funds']}",
                "coverage": _pct(row["coverage"]),
                "NAV -20% score": _num(row["scenario_score"]),
                "NAV -20% rank": row["scenario_rank"],
                "change": _num(row["score_change_nav_haircut"]),
            }
        )
    partial_rows = [
        {
            "manager": row["manager_name"],
            "status": row["status"],
            "current": row["current_date_funds"],
            "qualifying": row["eligible_funds"],
            "total": row["total_funds"],
            "coverage": _pct(row["coverage"]),
            "reason": ", ".join(json.loads(row["reasons"])),
        }
        for row in partial_initial[:20]
    ]

    detail_sections: list[str] = []
    detail_cards = ranked_initial[:2]
    if len(ranked_initial) > 2:
        most_sensitive = min(
            ranked_initial,
            key=lambda row: float(row["score_change_nav_haircut"] or 0.0),
        )
        if most_sensitive not in detail_cards:
            detail_cards.append(most_sensitive)
    for card in detail_cards:
        fund_ids = json.loads(card["constituent_fund_ids"])
        rows = [feature_by_fund[fund_id] for fund_id in fund_ids if fund_id in feature_by_fund]
        rows.sort(key=lambda row: (int(row["vintage_year"]), row["fund_id"]))
        fund_rows = [
            {
                "fund": row["fund_id"],
                "vintage": row["vintage_year"],
                "currency": row["currency"],
                "DPI": _multiple(row["dpi"]),
                "RVPI": _multiple(row["rvpi"]),
                "TVPI": _multiple(row["tvpi"]),
                "NAV share": _pct(row["nav_dependence"]),
                "TVPI %ile": _num(row["tvpi_percentile"]),
                "DPI %ile": _num(row["dpi_percentile"]),
                "score": _num(row["fund_score"]),
                "NAV -20%": _num(row["scenario_score"]),
            }
            for row in rows
        ]
        brief = brief_by_key.get(f"{card['manager_id']}|{card['strategy']}", {})
        brief_html = ""
        if brief:
            strengths = "".join(f"<li>{_e(_claim_text(item))}</li>" for item in brief.get("strengths", []))
            risks = "".join(f"<li>{_e(_claim_text(item))}</li>" for item in brief.get("risks", []))
            questions = "".join(f"<li>{_e(_claim_text(item))}</li>" for item in brief.get("questions", []))
            provider_label = " / ".join(
                part for part in (str(brief.get("provider", "")), str(brief.get("model", ""))) if part
            )
            brief_html = f"""
            <div class="brief">
              <div class="eyebrow">Diligence brief: {_e(brief.get('mode', 'template'))}{' | ' + _e(provider_label) if provider_label else ''}</div>
              <p>{_e(brief.get('summary', ''))}</p>
              <div class="three-col"><div><h4>Strengths</h4><ul>{strengths or '<li>None stated.</li>'}</ul></div>
              <div><h4>Risks</h4><ul>{risks or '<li>None stated.</li>'}</ul></div>
              <div><h4>Questions</h4><ul>{questions}</ul></div></div>
              <p class="muted">Review status: {_e(brief.get('review_status', ''))}. {_e(brief.get('fallback_reason', ''))}</p>
            </div>"""
        detail_sections.append(
            f"""
            <article class="manager-card">
              <div class="manager-head"><div><div class="eyebrow">Fictional manager</div><h3>{_e(card['manager_name'])}</h3></div>
              <div class="score-box"><span>GP score</span><strong>{_num(card['score'])}</strong><small>rank {_e(card['rank'])}</small></div></div>
              <div class="metrics">
                <div><span>TVPI peer percentile</span><strong>{_num(card['avg_tvpi_percentile'])}</strong></div>
                <div><span>DPI peer percentile</span><strong>{_num(card['avg_dpi_percentile'])}</strong></div>
                <div><span>Series coverage</span><strong>{_pct(card['coverage'])}</strong></div>
                <div><span>NAV -20% score</span><strong>{_num(card['scenario_score'])}</strong></div>
              </div>
              {_table([('fund','Fund'),('vintage','Vintage'),('currency','CCY'),('DPI','DPI'),('RVPI','RVPI'),('TVPI','TVPI'),('NAV share','NAV share'),('TVPI %ile','TVPI %ile'),('DPI %ile','DPI %ile'),('score','Score'),('NAV -20%','NAV -20%')], fund_rows)}
              {brief_html}
            </article>"""
        )

    evidence_html: list[str] = []
    for card in observed_cards:
        metric_bits = " ".join(
            f"<span class='pill'>{_e(name.upper())}: {_multiple(value)}</span>"
            for name, value in sorted(card.get("metrics", {}).items())
        )
        evidence_rows = [
            {
                "metric": item.get("metric_id", ""),
                "value": item.get("value", ""),
                "document": item.get("document_id", ""),
                "page": item.get("source_page", ""),
                "quote": item.get("evidence_quote", "") or item.get("source_anchor", ""),
                "review": item.get("adjudication_status", ""),
            }
            for item in card.get("evidence", [])
        ]
        failures = card.get("quality_error_failures", [])
        failure_text = ", ".join(failures) if failures else "No error-severity failure on this selected period."
        evidence_html.append(
            f"""
            <article class="evidence-card">
              <div class="eyebrow">Real source evidence: {_e(card.get('card_type',''))}</div>
              <h3>{_e(card.get('fund_name') or card.get('fund_id'))}</h3>
              <p><strong>Manager:</strong> {_e(card.get('manager_name') or 'Not resolved')} &nbsp; <strong>Scope:</strong> {_e(card.get('perspective'))} &nbsp; <strong>Date:</strong> {_e(card.get('as_of_date'))}</p>
              <div>{metric_bits}</div>
              <p><strong>Quality:</strong> {_e(failure_text)}</p>
              <p class="warning">{_e(card.get('limitation',''))}</p>
              {_table([('metric','Metric'),('value','Printed value'),('document','Document'),('page','Page'),('quote','Evidence quote'),('review','Review')], evidence_rows)}
            </article>"""
        )

    fund_decisions = [row for row in decisions if row.get("level") == "fund"]
    reasons = Counter(row.get("primary_reason", "") for row in fund_decisions)
    exclusion_rows = [
        {"reason": reason, "records": count}
        for reason, count in reasons.most_common()
        if reason and reason not in {"RANKABLE_FUND", "BASE_ELIGIBLE"}
    ]
    ranked_count = len(ranked)
    fund_rankable = sum(row.get("status") == "RANKABLE_FUND" for row in features)
    quality_run = metadata.get("quality_run", {})

    scorecard_csv = csv_text(scorecards)
    feature_csv = csv_text(features)
    decision_csv = csv_text(decisions)

    style = """
    :root{--bg:#07111f;--panel:#0d1b2c;--panel2:#12243a;--text:#edf4fb;--muted:#9fb0c4;--line:#263a51;--accent:#8fd3ff;--good:#9de2b2;--warn:#ffd28a}*{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.45}a{color:var(--accent)}
    header{padding:42px max(28px,6vw) 28px;border-bottom:1px solid var(--line);background:linear-gradient(135deg,#09182a,#0d2138)}
    header h1{font-size:34px;margin:8px 0}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:12px;color:var(--accent);font-weight:700}.lede{max-width:1050px;color:#c7d5e5;font-size:17px}
    nav{display:flex;gap:16px;flex-wrap:wrap;margin-top:22px}nav a,.download{border:1px solid var(--line);border-radius:8px;padding:8px 11px;text-decoration:none;background:#0b1929}
    main{padding:28px max(28px,6vw) 60px}section{margin:0 0 42px}.panel,.manager-card,.evidence-card,.brief{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px;margin:14px 0}
    h2{font-size:25px;margin:0 0 12px}h3{margin:5px 0 14px}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}.metrics>div{background:var(--panel2);padding:14px;border-radius:10px}.metrics span,.score-box span{display:block;color:var(--muted);font-size:12px}.metrics strong{font-size:24px}
    .manager-head{display:flex;justify-content:space-between;gap:20px}.score-box{min-width:115px;text-align:right}.score-box strong{display:block;font-size:36px;color:var(--good)}.score-box small{color:var(--muted)}
    .table-wrap{overflow:auto;border:1px solid var(--line);border-radius:10px;margin-top:12px}table{width:100%;border-collapse:collapse;min-width:760px}th,td{padding:10px 11px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top;font-size:13px}th{background:#10243a;color:#bcd2e8;position:sticky;top:0}tr:last-child td{border-bottom:0}
    .three-col{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.muted{color:var(--muted)}.warning{border-left:3px solid var(--warn);padding-left:12px;color:#f7dfb5}.pill{display:inline-block;padding:5px 8px;margin:2px 5px 2px 0;border:1px solid var(--line);border-radius:999px;background:#10243a;font-size:12px}.downloads{display:flex;gap:10px;flex-wrap:wrap}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.kpi{background:var(--panel2);padding:16px;border-radius:10px}.kpi strong{display:block;font-size:28px}.kpi span{color:var(--muted);font-size:12px}.callout{border:1px solid #39627c;background:#0c2639;padding:18px;border-radius:12px;font-size:16px}
    @media(max-width:800px){.three-col{grid-template-columns:1fr}.manager-head{display:block}.score-box{text-align:left;margin-top:10px}}
    """

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>GP Scoring Demonstration</title><style>{style}</style></head>
    <body><header><div class="eyebrow">Downstream investment analytics | report {_e(report_id or build_id)} | data {_e(build_id)}</div><h1>GP Scoring Demonstration</h1>
    <p class="lede">A transparent manager screen built from the project's existing controlled fund data. Numerical rankings below use fictional synthetic managers only. Real records appear in a separate evidence section and receive no GP rank.</p>
    <nav><a href="#decision">Decision screen</a><a href="#detail">Manager detail</a><a href="#evidence">Real evidence</a><a href="#controls">Controls</a><a href="#method">Method</a></nav></header>
    <main>
    <section id="decision"><div class="eyebrow">Investment question</div><h2>Which managers merit closer diligence within {_e(initial_strategy)}?</h2>
    <div class="callout">The score is a relative historical screen, not a forecast. It weights peer-relative total value at 60% and peer-relative cash returned at 40%, then shows what happens after a stated 20% reduction in remaining NAV.</div>
    <div class="kpis"><div class="kpi"><strong>{ranked_count}</strong><span>ranked fictional manager-strategy rows across all strategies</span></div><div class="kpi"><strong>{len(ranked_initial)}</strong><span>ranked {_e(initial_strategy)} managers</span></div><div class="kpi"><strong>{fund_rankable}</strong><span>funds with sufficient comparable peers</span></div><div class="kpi"><strong>{_e(as_of)}</strong><span>fixture comparison date</span></div></div>
    <div class="panel"><h3>{_e(initial_strategy.title())} comparison</h3>{_table([('rank','Rank'),('manager','Manager'),('score','Score'),('TVPI peer %ile','TVPI %ile'),('DPI peer %ile','DPI %ile'),('funds','Funds'),('coverage','Coverage'),('NAV -20% score','NAV -20% score'),('NAV -20% rank','NAV -20% rank'),('change','Change')], comparison_rows)}</div>
    <div class="panel"><h3>Insufficient or partial track records</h3><p class="muted">These rows stay visible but receive no numerical GP rank.</p>{_table([('manager','Manager'),('status','Status'),('current','Current-date funds'),('qualifying','Qualifying funds'),('total','Total supplied funds'),('coverage','Coverage'),('reason','Reason')], partial_rows)}</div></section>

    <section id="detail"><div class="eyebrow">Drill-down</div><h2>What is driving the score?</h2>{''.join(detail_sections) or '<div class="panel">No ranked managers met the selected strategy conditions.</div>'}</section>

    <section id="evidence"><div class="eyebrow">Source discipline</div><h2>What does the real evidence actually support?</h2>
    <p class="lede">These cards come from the source-only fund model. They show the reported accounting scope, page evidence, and quality findings. They are not mixed into the fictional-manager ranking.</p>{''.join(evidence_html)}</section>

    <section id="controls"><div class="eyebrow">Quality and release controls</div><h2>Why should an investment user trust the numbers enough to inspect them?</h2>
    <div class="panel"><div class="kpis"><div class="kpi"><strong>{_e(quality_run.get('run_id',''))}</strong><span>quality run used for fixture periods</span></div><div class="kpi"><strong>{_e(quality_run.get('status',''))}</strong><span>quality-run completeness</span></div><div class="kpi"><strong>{len(features)}</strong><span>current-date fund feature rows after base checks</span></div><div class="kpi"><strong>{len(decisions)}</strong><span>recorded fund and manager dispositions</span></div></div>
    <h3>Exclusion reasons</h3>{_table([('reason','Reason'),('records','Records')], exclusion_rows)}
    <p class="muted">The build recomputes DPI, RVPI, and TVPI from the accounting components and compares them with the stored analytics. Existing quality results remain the financial gate. New checks cover identity, peer construction, aggregation, scenario behavior, and publication consistency.</p></div></section>

    <section id="method"><div class="eyebrow">Method</div><h2>Calculation and limitations</h2><div class="panel">
    <p><strong>Fund score:</strong> 60% × TVPI peer percentile + 40% × DPI peer percentile. Peers share strategy, currency, date, measurement basis, and five-year vintage group. Every evaluated fund excludes all funds managed by the same fictional GP from its reference set.</p>
    <p><strong>Manager score:</strong> arithmetic mean of qualifying distinct fund scores. A manager-strategy row needs at least {_e(policy.get('manager_min_funds'))} qualifying funds and {_e(float(policy.get('manager_min_coverage',0))*100)}% supplied-series coverage.</p>
    <p><strong>Valuation sensitivity:</strong> reduce NAV by {_e(float(policy.get('nav_haircut',0))*100)}%, keep cash returned and paid-in unchanged, and compare the stressed TVPI with the original peer distribution. This is a sensitivity assumption, not an LP-interest price.</p>
    <p><strong>Limits:</strong> synthetic data establish calculation behavior, not manager skill or predictive accuracy. Real GP scoring remains blocked until manager identity, complete fund series, strategy ownership, metric basis, and information dates support comparable histories.</p>
    <div class="downloads">{_download('Download GP scorecards','gp-scorecards.csv',scorecard_csv)}{_download('Download fund features','fund-features.csv',feature_csv)}{_download('Download decisions','decisions.csv',decision_csv)}</div></div></section>
    </main></body></html>"""
