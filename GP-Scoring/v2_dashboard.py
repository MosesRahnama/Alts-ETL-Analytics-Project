from __future__ import annotations

import html
import json
from collections import defaultdict
from typing import Any, Mapping, Sequence


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _num(value: Any, digits: int = 1) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return _e(value)


def _pct(value: Any, digits: int = 0) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{100 * float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return _e(value)


def _multiple(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return _e(value)


def _rate(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{100 * float(value):.1f}%"
    except (TypeError, ValueError):
        return _e(value)


def _safe_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")


def _risk_label(value: Any, medium: float, high: float) -> str:
    if value is None or value == "":
        return "Unknown"
    number = float(value)
    if number >= high:
        return "Elevated"
    if number >= medium:
        return "Moderate"
    return "Lower"


def _readiness_summary(readiness: Sequence[Mapping[str, Any]], manager_id: str, strategy: str, fund_ids: Sequence[str]) -> float | None:
    selected = [row for row in readiness if
                (row.get("entity_level") == "manager_strategy" and row.get("entity_id") == f"{manager_id}|{strategy}") or
                (row.get("entity_level") == "fund" and row.get("entity_id") in set(fund_ids))]
    required = sum(int(row["required_fields"]) for row in selected)
    return sum(int(row["supported_fields"]) for row in selected) / required if required else None


def build_packets(core: Mapping[str, Any], scenarios: Mapping[str, Any], case_bundle: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    fund_by_id = {row["fund_id"]: row for row in core["fund_diagnostics"]}
    scenario_by_manager: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scenarios["manager_scenarios"]:
        scenario_by_manager[f"{row['manager_id']}|{row['strategy']}"] .append(dict(row))
    peers: dict[str, list[str]] = defaultdict(list)
    for row in core["cohort_membership"]:
        if row.get("policy_id") == "reference_v1_10_5":
            peers[row["evaluated_fund_id"]].append(row["peer_fund_id"])
    packets = []
    for manager in core["manager_diagnostics"]:
        fund_ids = [row["fund_id"] for row in core["fund_diagnostics"] if row["manager_id"] == manager["manager_id"] and row["strategy"] == manager["strategy"]]
        funds = [fund_by_id[fund_id] for fund_id in fund_ids if fund_id in fund_by_id]
        funds.sort(key=lambda row: (int(row.get("vintage_year") or 0), row["fund_id"]))
        key = f"{manager['manager_id']}|{manager['strategy']}"
        readiness = _readiness_summary(core["readiness"], manager["manager_id"], manager["strategy"], fund_ids)
        case = (case_bundle or {}).get("manager_cases", {}).get(manager["manager_id"], {})
        if case.get("strategy") != manager["strategy"]:
            case = {}
        packet = {
            "key": key,
            "manager_id": manager["manager_id"],
            "manager_name": manager["manager_name"],
            "strategy": manager["strategy"],
            "sub_strategy": manager.get("sub_strategy", ""),
            "status": manager.get("v1_status", ""),
            "reason": "Requires two scored funds and 75% of supplied same-strategy funds." if manager.get("v1_status") == "PARTIAL_TRACK_RECORD" else ("Comparable fund history missing." if manager.get("v1_status") == "INSUFFICIENT_DATA" else ""),
            "score": manager.get("historical_score"),
            "rank": manager.get("historical_rank"),
            "fund_count": manager.get("eligible_score_funds"),
            "supplied_funds": manager.get("supplied_funds"),
            "realized_share": manager.get("avg_realized_share"),
            "nav_reliance": manager.get("avg_nav_reliance"),
            "ks_pme": manager.get("avg_ks_pme"),
            "direct_alpha": manager.get("avg_direct_alpha"),
            "company_hhi": manager.get("avg_company_hhi"),
            "sector_hhi": manager.get("avg_sector_hhi"),
            "worst_fund": manager.get("worst_fund_score"),
            "iqr": manager.get("fund_score_iqr"),
            "score_above_50_rate": manager.get("score_above_50_rate"),
            "trend": manager.get("score_trend_per_fund"),
            "two_point_change": manager.get("two_point_change"),
            "size_step_up": manager.get("latest_size_step_up"),
            "readiness": readiness,
            "score_tvpi_points": manager.get("score_tvpi_points"),
            "score_dpi_points": manager.get("score_dpi_points"),
            "score_contributions": manager.get("score_contributions", []),
            "benchmark_fund_count": manager.get("benchmark_fund_count", 0),
            "benchmark_beating_count": manager.get("benchmark_beating_count", 0),
            "capital_returned_fund_count": manager.get("capital_returned_fund_count", 0),
            "currencies": manager.get("scored_fund_currencies", []),
            "funds": funds,
            "scenarios": scenario_by_manager.get(key, []),
            "peers": {fund_id: sorted(peers.get(fund_id, [])) for fund_id in fund_ids},
            "case": case,
        }
        packets.append(packet)
    packets.sort(key=lambda row: (row["strategy"], int(row["rank"] or 10**9), row["manager_id"]))
    return packets


def render_dashboard(metadata: Mapping[str, Any], core: Mapping[str, Any], scenarios: Mapping[str, Any], case_bundle: Mapping[str, Any] | None = None, briefs: Sequence[Mapping[str, Any]] | None = None) -> str:
    data = _safe_json({"packets": build_packets(core, scenarios, case_bundle), "metadata": dict(metadata),
                      "definitions": scenarios["definitions"],
                      "briefs": {str(row.get("manager_key", "")): dict(row) for row in (briefs or [])}})
    css = """
    :root{--ink:#173344;--ink-2:#214b60;--muted:#526b79;--accent:#087e83;--accent-dark:#06696d;--accent-soft:#edf7f7;--bg:#f1f5f6;--panel:#fff;--line:#d3e0e4;--line-strong:#b8cbd2;--good:#0a6e56;--warn:#8b4513;--bad:#9d2020;--shadow:0 10px 28px rgba(23,51,68,.07)}
    *{box-sizing:border-box}html{scroll-behavior:smooth;color-scheme:light}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}button,select{font:inherit}button,select,summary,[tabindex]{outline-offset:3px}:focus-visible{outline:3px solid #8fd1d3}
    a{color:var(--accent-dark);font-weight:650;text-underline-offset:2px}a:hover{color:#034e52}.hero{background:var(--ink);color:#fff;padding:40px 24px 30px}    .hero-inner,.tabs,main,footer{max-width:none;width:100%}.hero-inner{padding:0 28px}.hero h1{font-size:clamp(32px,4vw,46px);line-height:1.08;margin:8px 0 14px;letter-spacing:-.025em}.eyebrow,.manager-kicker,.summary-label{font-size:11px;font-weight:750;letter-spacing:.14em;text-transform:uppercase}.eyebrow{color:#9ad4d5}.lede{max-width:930px;margin:0 0 12px;color:#e5eef1;font-size:17px}.release-meta{display:flex;gap:8px;flex-wrap:wrap;color:#d5e3e8;font-size:13px}.release-meta span{border:1px solid rgba(211,224,228,.25);border-radius:999px;padding:5px 10px;background:rgba(255,255,255,.04)}
    .definitions{max-width:930px;margin:16px 0 0;border-top:1px solid rgba(211,224,228,.24);padding-top:12px}.definitions summary{cursor:pointer;color:#9ad4d5;font-weight:700}.definitions p{color:#d9e6eb;margin:10px 0}.toolbar{display:grid;grid-template-columns:minmax(150px,.65fr) minmax(180px,.75fr) minmax(260px,1.55fr) auto;gap:12px;align-items:end;margin-top:20px;max-width:none;width:100%}.toolbar label{display:grid;gap:6px;color:#eef5f7;font-size:12px;font-weight:700}.toolbar select{width:100%;min-height:42px;background:#fff;color:var(--ink);border:1px solid #a9c0ca;border-radius:7px;padding:9px 34px 9px 11px}.primary-action{min-height:42px;cursor:pointer;border:0;border-radius:7px;padding:9px 16px;background:var(--accent);color:#fff;font-weight:750}.primary-action:hover{background:#0a9298}#selection-count{margin:12px 0 0;color:#d5e3e8;font-size:13px}
    .tab-shell{position:sticky;top:0;z-index:20;background:rgba(241,245,246,.96);border-bottom:1px solid var(--line);backdrop-filter:blur(8px)}.tabs{display:flex;flex-wrap:wrap;align-items:center;gap:8px;overflow:visible;padding:12px 28px 14px}.tab{flex:0 0 auto;cursor:pointer;background:#fff;color:var(--accent-dark);border:1px solid var(--line);border-radius:999px;padding:9px 14px;font-size:14px;font-weight:700;white-space:nowrap}.tab:hover{border-color:#91babe;background:#f8fbfb}.tab.active{background:var(--accent);border-color:var(--accent);color:#fff;box-shadow:0 4px 12px rgba(8,126,131,.2)}
    main{padding:22px 28px 60px}.report-summary{display:grid;grid-template-columns:minmax(190px,.7fr) minmax(0,2.3fr);gap:20px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:0 0 22px;box-shadow:var(--shadow)}.summary-label{color:var(--accent)}.summary-copy{margin:5px 0 0;color:var(--muted);font-size:13px}.view{display:none}.view.active{display:block}.view-head,.manager-heading{margin:0 0 16px}.view-head h2,.manager-heading h2{font-size:clamp(25px,3vw,34px);line-height:1.15;margin:4px 0 6px;letter-spacing:-.02em}.view-head p,.manager-heading p{max-width:900px;margin:0;color:var(--muted)}.manager-kicker{color:var(--accent)}.manager-meta{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.status-badge{display:inline-block;border-radius:999px;padding:4px 9px;background:#e5f3ee;color:var(--good);font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}.status-badge.partial{background:#fff3de;color:var(--warn)}.status-badge.insufficient{background:#fde9e9;color:var(--bad)}
    .panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:22px;margin:0 0 18px;box-shadow:var(--shadow)}.panel h3{font-size:19px;line-height:1.25;margin:0 0 8px}.panel>p:first-of-type{color:var(--muted);max-width:940px}.callout{border-left:4px solid var(--accent);padding:13px 16px;background:var(--accent-soft);border-radius:6px;margin:12px 0}.warning{border-left-color:#d4a333;background:#fff9e9}.danger{border-left-color:var(--bad);background:#fff0f0}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0 20px;align-items:stretch}.report-summary .kpis{margin:0;grid-template-columns:repeat(5,minmax(0,1fr))}.kpi{display:flex;flex-direction:column;justify-content:space-between;background:var(--accent-soft);border-left:4px solid var(--accent);border-radius:6px;padding:13px 14px;min-width:0}.kpi span{display:block;color:var(--muted);font-size:11px;font-weight:750;letter-spacing:.06em;line-height:1.3;text-transform:uppercase}.kpi strong{display:block;margin-top:auto;padding-top:8px;color:var(--ink);font-size:25px;line-height:1.2;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
    .table-wrap{max-height:600px;overflow:auto;border:1px solid var(--line);border-radius:8px;background:#fff;scrollbar-color:#9bb4bf #eef3f4}.panel .table-wrap+ p{margin-top:14px}table{width:100%;min-width:850px;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}th,td{padding:10px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{position:sticky;top:0;z-index:2;background:var(--ink);color:#fff;font-size:11px;letter-spacing:.035em;text-transform:uppercase}tbody tr:nth-child(even){background:#f7fafa}tbody tr:hover{background:#eaf5f5}tbody tr:focus{background:#e0f1f1}tr:last-child td{border-bottom:0}.manager-link{background:none;border:0;color:var(--accent);padding:0;cursor:pointer;text-align:left}.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:4px 8px;margin:2px 4px 2px 0;font-size:11px}.bar{height:8px;background:#deeaed;border-radius:99px;overflow:hidden}.bar>span{display:block;height:100%;background:var(--accent)}.muted{color:var(--muted)}.quote{max-width:440px}.section-title{display:flex;align-items:flex-end;justify-content:space-between;gap:15px;margin-bottom:12px}.section-title h2{margin:0}.scorebox{font-size:46px;color:var(--good);font-weight:750;line-height:1}.scorebox small{font-size:12px;color:var(--muted);display:block}.flag{padding:10px 12px;border-radius:7px;background:#fff9e9;border:1px solid #ecd49c;color:var(--warn)}.good{color:var(--good)}.bad{color:var(--bad)}code{color:#0b6570}footer{padding:0 28px 40px;color:var(--muted);font-size:12px}
    @media(max-width:900px){.toolbar{grid-template-columns:repeat(2,minmax(0,1fr))}.grid2,.grid3,.report-summary{grid-template-columns:1fr}.tab-shell{position:static}.report-summary .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
    @media(max-width:560px){.hero{padding:28px 18px 24px}.hero-inner{padding:0}.hero h1{font-size:32px}.lede{font-size:15px}.toolbar{grid-template-columns:1fr}.tabs{padding:12px 16px}.tab{font-size:14px;padding:8px 13px}main{padding:16px 12px 44px}.report-summary,.panel{padding:17px}.report-summary .kpis{grid-template-columns:1fr 1fr}.kpi{padding:11px}.kpi strong{font-size:22px}.manager-meta{align-items:flex-start;flex-direction:column}th,td{padding:9px}}
    """
    css = css.rstrip() + """
    .comparison-controls{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0 20px}.comparison-controls label{display:grid;gap:5px;font-size:12px;font-weight:700;flex:1;min-width:180px}.comparison-controls select{width:100%;padding:10px;border:1px solid var(--line-strong);border-radius:6px;background:white;color:var(--ink)}.score-parts{display:flex;height:24px;background:#edf1f3;border-radius:5px;overflow:hidden;margin:12px 0}.score-parts .value{background:#087e83}.score-parts .cash{background:#2f536e}.legend{display:flex;gap:20px;font-size:13px;color:var(--ink)}.legend span:before{content:'';display:inline-block;width:10px;height:10px;background:#087e83;margin-right:6px}.legend span+span:before{background:#2f536e}.selected-row{background:#dff1f1!important;box-shadow:inset 4px 0 var(--accent)}
    .research-grid{display:grid;grid-template-columns:repeat(2,minmax(220px,1fr));gap:14px}.research-grid label{display:grid;gap:6px;color:var(--ink);font-size:12px;font-weight:750}.research-grid input,.research-grid select,.research-grid textarea{width:100%;border:1px solid var(--line-strong);border-radius:7px;background:#fff;color:var(--ink);padding:10px 11px;font:inherit}.research-grid textarea{min-height:94px;resize:vertical}.research-span{grid-column:1/-1}.research-actions,.research-presets{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.secondary-action,.preset,.source-button{cursor:pointer;border:1px solid var(--accent);border-radius:6px;padding:8px 11px;background:#fff;color:var(--accent-dark);font-weight:700}.secondary-action:hover,.preset:hover,.source-button:hover{background:var(--accent-soft)}.research-state{margin:12px 0 0;color:var(--ink);font-weight:650}.research-state.error{color:var(--bad)}.research-table-wrap,.evidence-values-wrap{overflow-x:auto}.research-results-table,.evidence-values-table{width:100%;border-collapse:collapse;background:#fff}.research-results-table{min-width:0;table-layout:fixed;border:1px solid var(--line)}.research-results-table th,.research-results-table td,.evidence-values-table th,.evidence-values-table td{border:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}.research-results-table>thead>tr>th{background:var(--accent-dark);color:#fff;font-size:12px}.research-results-table>tbody>tr:nth-child(even){background:#f5f9fa}.research-results-table th:first-child,.research-results-table td:first-child{width:52px}.research-results-table th:last-child,.research-results-table td:last-child{width:230px}.research-evidence-cell{min-width:0;max-width:none}.research-evidence-text{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.research-source summary{cursor:pointer;color:var(--accent-dark);font-weight:700}.research-source dl{margin:8px 0 10px;display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 10px;font-size:12px}.research-source dt{color:var(--muted);font-weight:700}.research-source dd{margin:0;overflow-wrap:anywhere}.research-source .source-button{margin:0 0 8px;width:100%}.research-source details{margin-top:6px}.evidence-values-table{min-width:0;font-size:12px}.evidence-values-table th{background:var(--accent-soft);color:var(--ink);white-space:nowrap}.evidence-values-table td{color:var(--ink);overflow-wrap:anywhere}.research-scope{margin:12px 0;color:var(--ink)}.research-scope strong{color:var(--ink)}.research-hidden{display:none!important}.mode-note{border-left:4px solid var(--accent);padding:10px 13px;background:var(--accent-soft);color:var(--ink)}
    @media(max-width:720px){.research-grid{grid-template-columns:1fr}.research-span{grid-column:auto}}
    """
    script = r"""
    const {packets,metadata,definitions,briefs}=JSON.parse(document.getElementById('report-data').textContent);
    const q=s=>document.querySelector(s), qa=s=>[...document.querySelectorAll(s)];
    const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const fmt=(v,d=1)=>v===null||v===undefined||v===''?'—':Number(v).toFixed(d);
    const pct=(v,d=1)=>v===null||v===undefined||v===''?'—':(100*Number(v)).toFixed(d)+'%';
    const mult=v=>v===null||v===undefined||v===''?'—':Number(v).toFixed(2)+'x';
    const money=v=>v===null||v===undefined||v===''?'—':Number(v).toLocaleString('en-US',{maximumFractionDigits:2});
    const table=(heads,rows)=>'<div class="table-wrap"><table><thead><tr>'+heads.map(x=>'<th scope="col">'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
    const box=(label,value)=>'<div class="kpi"><span>'+esc(label)+'</span><strong>'+esc(value)+'</strong></div>';
    const panel=(heading,body)=>'<section class="panel"><h3>'+esc(heading)+'</h3>'+body+'</section>';
    const statusLabel=value=>({'RANKED_DEMO':'Ranked','PARTIAL_TRACK_RECORD':'Partial track record','INSUFFICIENT_DATA':'Insufficient data'}[value]||value);
    const statusClass=value=>value==='PARTIAL_TRACK_RECORD'?'partial':value==='INSUFFICIENT_DATA'?'insufficient':'';
    const title=p=>'<div class="manager-heading"><div class="manager-kicker">'+esc(p.strategy.replaceAll('_',' '))+' manager</div><h2>'+esc(p.manager_name)+'</h2><p class="manager-meta"><span class="status-badge '+statusClass(p.status)+'">'+esc(statusLabel(p.status))+'</span><span>'+esc(p.reason)+'</span></p></div>';
    const description=id=>Object.entries(definitions).find(([key])=>key.split('/').includes(id))?.[1]||id;
    const sourceFiles='<p><a href="../04-diagnostics/fund-diagnostics.csv">Fund results (CSV)</a> · <a href="../04-diagnostics/manager-diagnostics.csv">Manager results (CSV)</a> · <a href="../04-diagnostics/evidence.json">Calculation inputs and source references</a> · <a href="../04-diagnostics/evidence-readiness.csv">Field coverage counts</a></p>';
    function currentPacket(){return packets.find(p=>p.key===q('#manager').value);}
    function rankRange(p){const rows=p.scenarios.filter(r=>['nav_00','nav_10','nav_20','nav_30','w50_50','w60_40','w70_30'].includes(r.scenario_id)&&r.scenario_rank!==null&&r.scenario_rank!==undefined);return rows.length?Math.min(...rows.map(r=>r.scenario_rank))+'–'+Math.max(...rows.map(r=>r.scenario_rank)):'—';}
    function scoreParts(p){return '<div class="score-parts" aria-label="Score contributions"><span class="value" style="width:'+Math.min(100,Math.max(0,Number(p.score_tvpi_points)||0))+'%"></span><span class="cash" style="width:'+Math.min(100,Math.max(0,Number(p.score_dpi_points)||0))+'%"></span></div><div class="legend"><span>Total-value comparison: '+fmt(p.score_tvpi_points)+' points</span><span>Cash-return comparison: '+fmt(p.score_dpi_points)+' points</span></div>';}
    let compareKeys=[];
    function renderCompare(){
      const options=packets.filter(p=>p.strategy===q('#strategy').value&&p.status==='RANKED_DEMO');
      const prior=compareKeys.filter(key=>options.some(p=>p.key===key));
      compareKeys=[...prior,...options.map(p=>p.key).filter(key=>!prior.includes(key))].slice(0,3);
      q('#compare-content').innerHTML='<div class="view-head"><h2>Manager comparison</h2><p>Same-strategy managers compared on the stated economic date. The performance score, cash returned, benchmark results and evidence requirements remain distinct measures.</p></div><div class="comparison-controls" id="comparison-controls"></div><div id="comparison-results"></div>';
      compareKeys.forEach((key,index)=>{const label=document.createElement('label');label.textContent='Manager '+(index+1);const select=document.createElement('select');select.setAttribute('aria-label','Comparison manager '+(index+1));options.forEach(p=>{const option=document.createElement('option');option.value=p.key;option.textContent=p.manager_name;select.append(option);});select.value=key;select.addEventListener('change',()=>{compareKeys[index]=select.value;comparisonResults();});label.append(select);q('#comparison-controls').append(label);});
      comparisonResults();
    }
    function comparisonResults(){
      const selected=[...new Set(compareKeys)].map(key=>packets.find(p=>p.key===key)).filter(Boolean);
      if(!selected.length){q('#comparison-results').textContent='This strategy has zero ranked manager groups.';return;}
      const rows=[['Historical score',p=>fmt(p.score)],['Total-value score points',p=>fmt(p.score_tvpi_points)],['Cash-return score points',p=>fmt(p.score_dpi_points)],['Baseline rank',p=>p.rank],['Rank range under value and weight changes',p=>rankRange(p)],['Scored / supplied funds',p=>p.fund_count+'/'+p.supplied_funds],['Fund currencies',p=>p.currencies.join(', ')],['Mean realized share',p=>pct(p.realized_share)],['Funds with capital returned in cash',p=>p.capital_returned_fund_count+'/'+p.fund_count],['Funds beating the benchmark',p=>p.benchmark_beating_count+'/'+p.benchmark_fund_count],['Mean KS-PME',p=>mult(p.ks_pme)],['Worst fund score',p=>fmt(p.worst_fund)],['Scored funds above 50',p=>pct(p.score_above_50_rate)],['Score after removing best fund',p=>fmt(p.scenarios.find(r=>r.scenario_id==='remove_best')?.counterfactual_score)],['Field coverage',p=>pct(p.readiness)],['Case governance finding',p=>p.case?.governance_flag||'Evidence unavailable']];
      q('#comparison-results').innerHTML=panel('Comparable results',table(['Measure',...selected.map(p=>p.manager_name)],rows.map(([name,value])=>[name,...selected.map(value)]))+'<p>Rank ranges cover the four remaining-value reductions and three score-weight choices, using the same manager population. These are assumption tests. The best-fund removal is a diagnostic score; the original history requirement still applies. Benchmark counts include funds with a supported currency and benchmark.</p>')+selected.map(p=>panel(p.manager_name,scoreParts(p)+'<p>'+esc(p.fund_count)+' scored funds; '+esc(p.currencies.join(', '))+'; historical score '+fmt(p.score)+'.</p>')).join('');
    }
    function selection(){return packets.filter(p=>p.strategy===q('#strategy').value && (q('#status').value==='ALL'||p.status===q('#status').value));}
    function fillManagers(){
      const prior=q('#manager').value, rows=selection();
      q('#manager').replaceChildren(...rows.map(p=>{const o=document.createElement('option');o.value=p.key;o.textContent=(p.rank?'#'+p.rank+' ':'')+p.manager_name;return o;}));
      if(rows.some(p=>p.key===prior))q('#manager').value=prior;
      q('#screener-content').innerHTML='<div class="view-head"><div class="manager-kicker">Historical comparison</div><h2>Manager screener</h2><p>Scores compare fictional fund histories within the same strategy, currency and vintage range. The selected row opens its detailed track record.</p><p id="screener-selected" class="mode-note"></p></div>'+panel('Manager rankings',table(['Manager','Status','Rank','Score','Scored / supplied funds','Mean KS-PME','Mean realized share','Field coverage'],rows.map(p=>[p.manager_name,statusLabel(p.status),p.rank,fmt(p.score),p.fund_count+'/'+p.supplied_funds,mult(p.ks_pme),pct(p.realized_share),pct(p.readiness)])));
      qa('#screener-content tbody tr').forEach((tr,i)=>{tr.style.cursor='pointer';tr.tabIndex=0;tr.dataset.managerKey=rows[i].key;const open=()=>{q('#manager').value=rows[i].key;activate('track');};tr.addEventListener('click',open);tr.addEventListener('keydown',event=>{if(event.key==='Enter')open();});});
      q('#selection-count').textContent=rows.length+' manager-strategy groups selected; '+packets.length+' groups in the report.';
      render();
    }
    function markSelectedManager(){
      const key=q('#manager').value, p=currentPacket();
      qa('#screener-content tbody tr').forEach(tr=>tr.classList.toggle('selected-row',tr.dataset.managerKey===key));
      const selected=q('#screener-selected');
      if(selected)selected.textContent=p?'Selected fictional manager: '+p.manager_name+'. Changing the manager opens its track record.':'No fictional manager matches the filters.';
    }
    function renderTrack(p){
      let value=title(p)+'<div class="kpis">'+box('Historical score',fmt(p.score))+box('Rank',p.rank||'—')+box('Worst fund score',fmt(p.worst_fund))+box('Scored funds above 50',pct(p.score_above_50_rate))+box('Middle-half score spread',fmt(p.iqr))+'</div>';
      value+=panel('Score contributions',scoreParts(p)+'<p>Each scored fund has equal weight. Total-value points use the 60% weight; cash-return points use 40%. The rows sum to the manager score when the history requirement is met. Other groups retain these fund comparisons without a published manager score.</p>'+table(['Fund','Total-value points','Cash-return points','Combined points'],p.score_contributions.map(r=>[r.fund_id,fmt(r.tvpi_points,2),fmt(r.dpi_points,2),fmt(r.tvpi_points+r.dpi_points,2)])));
      value+=panel('Fund results','<p>Annualized returns use dated investor payments and remaining fund value. Fee basis appears beside each result.</p>'+table(['Fund','Current status','Vintage','Currency','As of','Fee basis','TVPI','DPI','Score','KS-PME','Annualized return'],p.funds.map(f=>[f.fund_id,f.current_status,f.vintage_year,f.currency,f.as_of_date,f.xirr_basis,mult(f.tvpi),mult(f.dpi),fmt(f.v1_fund_score),mult(f.ks_pme),pct(f.xirr)])));
      value+=panel('Trailing returns','<p>Each interval starts with the opening fund value, includes payments during the interval, and ends with the closing value.</p>'+table(['Fund','1-year','Status','3-year','Status','5-year','Status','10-year','Status'],p.funds.map(f=>[f.fund_id,...[1,3,5,10].flatMap(y=>[pct(f['trailing_'+y+'y_xirr']),f['trailing_'+y+'y_status']])])));
      value+=panel('Same-age comparisons','<p>Age starts at the first investor call. The chosen report falls on or before each age target, up to 100 days earlier.</p>'+table(['Fund','Target age','Report date','Days before target','Status','TVPI','DPI','TVPI percentile'],p.funds.flatMap(f=>[3,5,7,10].map(y=>[f.fund_id,y,f['age_'+y+'_date'],f['age_'+y+'_lag_days'],f['age_'+y+'_status'],mult(f['age_'+y+'_tvpi']),mult(f['age_'+y+'_dpi']),fmt(f['age_'+y+'_tvpi_percentile'])]))));
      value+=panel('Comparison funds',table(['Fund','Reference peers','20 funds / 10 managers','Peer identifiers'],p.funds.map(f=>[f.fund_id,f.reference_peer_count,f.strict_20_10_eligible?'Meets minimum':'Below minimum',(p.peers[f.fund_id]||[]).join(', ')]))+'<p><a href="../04-diagnostics/cohort-membership.csv">Comparison membership</a> · <a href="../04-diagnostics/genealogy.csv">Fund series ordering</a></p>');
      q('#track-content').innerHTML=value;
    }
    function renderStress(p){
      const rows=p.scenarios.map(x=>[x.scenario_id,description(x.scenario_id),fmt(x.scenario_score),x.scenario_rank??'—',x.official_eligible===false?'History requirement unmet':'Reference rules',fmt(x.counterfactual_score),x.removed_fund_id||'']);
      const c=p.case||{}, t=c.case_scenario||{};
      let value=title(p)+'<div class="kpis">'+box('Mean realized share',pct(p.realized_share))+box('Mean remaining-value share',pct(p.nav_reliance))+box('Mean KS-PME',mult(p.ks_pme))+box('Mean Direct Alpha',pct(p.direct_alpha))+'</div>';
      value+=panel('Capital recovery','<p>Capital still to return is investor contributions less cash distributions, floored at zero. The remaining-value reduction is the largest fall in the current mark consistent with returning that capital. A negative percentage means current remaining value is already below the capital gap.</p>'+table(['Fund','Currency','Cash paid in','Cash returned','Remaining value','Capital still to return','Value reduction to capital break-even','Status'],p.funds.map(f=>[f.fund_id,f.currency,money(f.paid_in),money(f.distributions),money(f.remaining_nav),money(f.capital_still_to_return),pct(f.nav_haircut_to_capital),f.capital_recovery_status])));
      value+=panel('Public-market wealth comparison','<p>Each contribution and distribution grows at its matched benchmark return to the economic date. Excess value equals remaining fund value plus benchmark-grown distributions, less benchmark-grown contributions. A positive amount favors the fund. The break-even reduction measures the change in remaining value that would remove this advantage; a negative result means a value increase is required.</p>'+table(['Fund','Currency','Benchmark','Benchmark-grown contributions','Benchmark-grown distributions','Excess value','Value reduction to match benchmark','Direct Alpha: effective','Direct Alpha: continuous','Status'],p.funds.map(f=>[f.fund_id,f.currency,f.benchmark_id,money(f.benchmark_capital),money(f.benchmark_distributions),money(f.benchmark_excess_value),pct(f.nav_haircut_to_match_benchmark),pct(f.direct_alpha),pct(f.direct_alpha_continuous),f.benchmark_status]))+'<p>The effective annualized rate uses benchmark-adjusted payment dates. The continuous rate is the natural logarithm of one plus the effective rate. Benchmark wealth measures timing-adjusted value; it remains separate from market-risk attribution.</p>');
      value+=panel('Sensitivity results','<p>Manager measures are equal-fund averages of available scored-fund results. Each scenario changes its named input while peer values stay fixed.</p>'+table(['Scenario','Assumption','Score','Rank','Rank status','Diagnostic score','Removed fund'],rows)+'<p><a href="../05-scenarios/fund-scenarios.csv">Fund sensitivity results</a> · <a href="../05-scenarios/manager-scenarios.csv">Manager sensitivity results</a> · <a href="../05-scenarios/scenario-definitions.json">Scenario definitions</a></p>');
      if(c.status==='AVAILABLE')value+=panel('Retrospective payment-timing example','<p>The hypothetical delays historical distributions by '+esc(t.timing_delay_days)+' days. Investment amounts and terminal remaining value stay fixed.</p><div class="kpis">'+box('Case annualized return',pct(t.case_xirr))+box('Delayed annualized return',pct(t.distribution_delay_xirr))+box('Delayed total-value multiple',mult(t.distribution_delay_tvpi))+'</div>');
      q('#stress-content').innerHTML=value;
    }
    function renderHoldings(p){
      let value=title(p)+panel('Holdings and effective terms','<p>Concentration sums squared investment shares; a value near one means most value sits in a small number of investments. Fees use terms effective on the economic date.</p>'+table(['Fund','Company concentration','Largest company','Largest three','Sector concentration','Top sector','Management fee','Waterfall','Term status'],p.funds.map(f=>[f.fund_id,fmt(f.company_hhi,3),pct(f.top_company_share),pct(f.top3_company_share),fmt(f.sector_hhi,3),f.top_sector,pct(f.management_fee_rate),f.waterfall_type,f.term_status]))+'<p>The parent fixture records current holdings. Realized losses require the dated investment costs supplied by the case examples. Parent geography is North America.</p>');
      const c=p.case||{};
      if(c.status==='AVAILABLE')value+=panel('Generated investment events: '+c.case_id,'<div class="kpis">'+box('Realized cost in loss-making deals',pct(c.loss_ratio))+box('Invested cost written off',pct(c.writeoff_capital_ratio))+box('Case total-value multiple',mult(c.case_tvpi))+box('Mean exit vs prior mark difference',pct(c.mark_to_exit_bias))+box('Case region concentration',fmt(c.case_geography_hhi,3))+'</div><p>Case amounts form a separate fictional accounting example. Historical scores retain the parent fixture values.</p><p><a href="../data/case-events.csv">Dated case events</a> · <a href="../data/case-valuations.csv">Case valuations</a></p>');
      if(c.investment_analysis){const a=c.investment_analysis;
        value+=panel('Investment gains and winner dependence','<p>Amounts are illustrative US dollars. Deal value equals realized proceeds plus the remaining mark. Gain subtracts original invested cost. Realized loss is the cash shortfall on a closed investment; an active mark stays separate.</p><div class="kpis">'+box('Largest deal / positive gains',pct(a.positive_gain_top_deal_share))+box('Gross multiple excluding best deal',mult(a.gross_multiple_ex_best_deal))+box('Realized loss amount',money(a.realized_loss_amount))+'</div>'+table(['Company','Status','Invested cost','Proceeds','Remaining value','Gain','Gross multiple','Realized loss'],a.deals.map(r=>[r.company_id,r.status,money(r.cost),money(r.proceeds),money(r.remaining_value),money(r.gain),mult(r.gross_multiple),money(r.realized_loss)]))+'<p>Gross deal results precede fund fees. Removing the best deal removes its invested cost and its value; retained deals form the comparison.</p>');
        const assumption=a.operating_results[0]?.assumptions;
        value+=panel('Company operating downside','<p>Business value equals revenue × operating profit margin × valuation multiple, the factor applied to profit. Equity value subtracts net debt, which is borrowing less cash, then applies the ownership share and currency conversion. Revenue changes '+pct(assumption?.revenue_change)+', margin changes '+fmt(100*(assumption?.margin_change||0))+' percentage points, and the valuation multiple changes '+fmt(assumption?.multiple_change)+' turns. Debt, ownership and currency stay fixed. Effects are applied in that stated order, with equity floored at zero.</p><div class="kpis">'+box('Baseline case multiple',mult(c.case_tvpi))+box('Operating-downside case multiple',mult(a.operating_case_tvpi))+box('Remaining-value change',money(a.operating_value_change))+'</div>'+table(['Company','Baseline value','Revenue effect','Margin effect','Multiple effect','Stressed value'],a.operating_results.map(r=>[r.company_id,money(r.baseline_value),money(r.revenue_effect),money(r.margin_effect),money(r.multiple_effect),money(r.scenario_value)]))+'<p>These hypothetical operating changes apply to current fictional company records. Fund scores stay unchanged. Calculation reference '+esc('CASEMETRIC:'+c.case_id+':INVESTMENTS')+'. <a href="../data/documents/valuation-memo.html#'+encodeURIComponent(c.case_id.toLowerCase())+'">Company inputs and valuation dates</a>.</p>');
      }
      q('#holdings-content').innerHTML=value;
    }
    function renderTeam(p){
      const c=p.case||{}, t=c.case_scenario||{};
      let value=title(p);
      if(c.status==='AVAILABLE'){
        value+=panel('Team and governance','<div class="kpis">'+box('Senior team retained',pct(c.team_continuity))+box('Positive-gain attribution retained',pct(c.attribution_continuity))+box('Manager commitment',pct(c.gp_commitment_pct))+box('Succession evidence',c.succession_status)+'</div><p>'+esc(c.team_summary)+'</p><p>'+esc(c.governance_flag)+': '+esc(c.governance_summary)+'</p><p><a href="../data/team-history.csv">Employment dates</a> · <a href="../data/deal-attribution.csv">Investment attribution</a></p>');
        if(t.facility_status==='AVAILABLE')value+=panel('Short-term borrowing example','<p>The comparison replaces each debt draw with an investor contribution on that date and removes its later principal and interest payment.</p><div class="kpis">'+box('Return with borrowing',pct(t.xirr_with_facility,3))+box('Return funded by investors',pct(t.xirr_without_facility,3))+box('Difference (percentage points)',fmt(100*t.facility_xirr_delta,3))+box('Valuation age at information cutoff',t.nav_age_days+' days')+'</div><p>Valuation date '+esc(t.nav_mark_date)+'; age reference '+esc(t.nav_age_reference_date)+'. Purchase-price and currency scenarios require further case inputs.</p>'+table(['Date','Cash change','Closing cash','Debt change','Closing debt'],(t.cash_reconciliation||[]).map(r=>[r.date,fmt(r.cash_change,6),fmt(r.closing_cash,6),fmt(r.debt_change,6),fmt(r.closing_debt,6)])));
      }else value+=panel('Missing diligence','<p>Team history, manager commitments and governance events are missing from this group’s fixture records. Those fields remain empty.</p>');
      q('#team-content').innerHTML=value;
    }
    function renderEvidence(p){
      const c=p.case||{}, b=briefs[p.key];
      let value=title(p)+panel('Field coverage','<div class="kpis">'+box('Supported / required fields',pct(p.readiness))+'</div><p>Coverage divides summed supported field counts by summed required counts for this manager group and its funds. It measures available information.</p>'+sourceFiles+'<p>Manager calculation reference: '+esc('MANAGER:'+p.manager_id+':'+p.strategy+':V2')+'</p>');
      if(c.status==='AVAILABLE')value+=panel('Case facts and review decisions',table(['Field','Value','Unit','Effective','Available','Source family','Review decision','Evidence reference'],(c.fact_records||[]).map(r=>[r.field_name,r.value_text||r.value_numeric,r.unit,r.effective_date,r.available_at,r.document_family,r.resolution_status,r.evidence_id]))+'<p><a href="../data/diligence-facts.csv">All facts, including competing statements</a> · <a href="../data/document-registry.csv">Document filenames and case locations</a></p>'+table(['Field','Selected fact','Rejected facts','Decision'],(c.conflict_resolutions||[]).map(r=>[r.field_name,r.selected_fact_id,r.rejected_fact_ids.join(', '),r.reason])));
      if(c.status==='AVAILABLE')value+=panel('Case source documents','<p>'+[['ddq','Diligence questionnaire'],['lpa-terms','Partnership terms'],['track-record','Investment record'],['team-roster','Team roster'],['portfolio-investments','Portfolio investments'],['valuation-memo','Valuation memo']].map(([file,label])=>'<a href="../data/documents/'+file+'.html#'+encodeURIComponent(c.case_id.toLowerCase())+'">'+esc(label)+'</a>').join(' · ')+'</p>');
      if(b)value+=panel('Brief ('+(b.mode||'template')+')','<p>'+esc(b.summary)+'</p><p>'+esc((b.evidence_ids||[]).join(', '))+'</p>');
      q('#evidence-content').innerHTML=value;
    }
    const research={context:null,controller:null,request:0};
    const localResearchBase=location.protocol==='http:'&&['localhost','127.0.0.1'].includes(location.hostname)
      ? ''
      : (location.protocol==='file:'?'http://127.0.0.1:8765':null);
    function fragmentValue(name){return new URLSearchParams(location.hash.replace(/^#/, '')).get(name)||'';}
    async function researchPost(path,payload,signal){
      const response=await fetch(localResearchBase+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal});
      const result=await response.json();
      if(!response.ok)throw new Error(result.error||result.execution_state||'Local service request failed.');
      return result;
    }
    function researchStatus(text,error=false){const node=q('#research-state');if(node){node.textContent=text;node.classList.toggle('error',error);}}
    function cancelResearch(){research.request+=1;if(research.controller)research.controller.abort();research.controller=null;q('#research-results').replaceChildren();}
    function selectedResearchScope(){
      if(!research.context)return null;
      const option=q('#research-entity').selectedOptions[0];
      if(!option)return null;
      if(option.dataset.scopeType==='fund')return research.context.funds.find(row=>row.fund_id===option.value)||null;
      return research.context.managers.find(row=>row.manager_key===option.value)||null;
    }
    function renderResearchScope(){
      const selected=selectedResearchScope(), option=q('#research-entity').selectedOptions[0], mode=option?.dataset.scopeType||'';
      cancelResearch();
      if(!selected){q('#research-scope-summary').textContent='Select a real manager or fund.';return;}
      const docs=selected.documents||[];
      const funds=mode==='manager'?(selected.funds||[]):[selected];
      const names=funds.slice(0,12).map(row=>row.fund_name).join('; ')+(funds.length>12?'; '+(funds.length-12)+' more':'');
      q('#research-scope-summary').innerHTML='<strong>'+esc(mode==='manager'?selected.manager_name:selected.fund_name)+'</strong><br>'+esc(docs.map(row=>row.file_id+' '+row.doc_type).join('; '))+'<br>'+esc(funds.length+' fund'+(funds.length===1?'':'s')+': '+names);
      researchStatus('Source scope ready. '+docs.length+' reviewed document'+(docs.length===1?'':'s')+' will be searched.');
    }
    function fillResearchSelectors(){
      const managers=research.context?.managers||[], funds=research.context?.funds||[];
      const select=q('#research-entity'), managerGroup=document.createElement('optgroup'), fundGroup=document.createElement('optgroup');
      managerGroup.label='Managers';fundGroup.label='Funds';
      managers.forEach(row=>{const option=document.createElement('option');option.value=row.manager_key;option.dataset.scopeType='manager';option.textContent=row.manager_name+' ('+row.fund_count+' fund'+(row.fund_count===1?'':'s')+', '+row.document_count+' document'+(row.document_count===1?'':'s')+')';managerGroup.appendChild(option);});
      funds.forEach(row=>{const option=document.createElement('option');option.value=row.fund_id;option.dataset.scopeType='fund';option.textContent=row.fund_name+(row.manager_name?' ('+row.manager_name+')':' (manager not named)');fundGroup.appendChild(option);});
      select.replaceChildren(managerGroup,fundGroup);select.disabled=!(managers.length||funds.length);q('#research-search').disabled=select.disabled;
      q('#research-counts').innerHTML=box('Exact manager names',research.context.manager_count)+box('Real funds',research.context.fund_count)+box('Fund source documents',research.context.fund_document_count)+box('Reviewed documents',research.context.permitted_document_count);
      renderResearchScope();
    }
    async function connectResearch(){
      cancelResearch();
      if(localResearchBase===null){researchStatus('Interactive document search is available in the local project copy.',true);return;}
      researchStatus('Loading real managers and funds from reviewed extraction records.');
      try{
        const result=await researchPost('/gp_manager_context',{});
        if(result.execution_state!=='OK')throw new Error('The reviewed manager and fund list is unavailable.');
        research.context=result;fillResearchSelectors();
      }catch(error){research.context=null;researchStatus('The local RAG service is not running. Start RAG/start-local.ps1, then reload this page.',true);}
    }
    async function openResearchDocument(blockId,page){
      const sourceWindow=window.open('about:blank','_blank');
      if(!sourceWindow){researchStatus('The browser blocked the PDF tab. Permit pop-ups for this local page and try again.',true);return;}
      sourceWindow.opener=null;
      try{
        const response=await fetch(localResearchBase+'/document',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({block_id:blockId})});
        if(!response.ok)throw new Error('The cited source PDF is unavailable.');
        const url=URL.createObjectURL(await response.blob())+(page?'#page='+page:'');
        sourceWindow.location.replace(url);setTimeout(()=>URL.revokeObjectURL(url.split('#')[0]),60000);
      }catch(error){sourceWindow.close();researchStatus(error.message||String(error),true);}
    }
    function evidenceColumns(row){
      if(row.block_kind!=='table_row')return [];
      const parts=String(row.original_text||'').split('|').map(value=>value.trim()).filter(Boolean);
      if(parts.length<2)return [];
      const used={};
      return parts.map((part,index)=>{
        const split=part.indexOf(':'), labelled=split>0&&split<80;
        let label=labelled?part.slice(0,split).trim():(index===0?'Row label':'Value '+(index+1));
        const value=labelled?part.slice(split+1).trim():part;
        used[label]=(used[label]||0)+1;if(used[label]>1)label+=' '+used[label];
        return {label,value};
      });
    }
    function renderedEvidence(row){
      const full=String(row.original_text||''), columns=evidenceColumns(row);
      if(columns.length){
        return '<div class="evidence-values-wrap"><table class="evidence-values-table"><thead><tr>'+columns.map(item=>'<th scope="col">'+esc(item.label)+'</th>').join('')+'</tr></thead><tbody><tr>'+columns.map(item=>'<td>'+esc(item.value)+'</td>').join('')+'</tr></tbody></table></div>';
      }
      return '<p class="research-evidence-text">'+esc(full)+'</p>';
    }
    function sourceDetails(row){
      const page=row.physical_page||row.printed_page||'';
      const facts=[['PDF',row.filename||''],['Report',row.file_id||''],['Page',page],['Document',row.doc_type||''],['Block',row.block_kind||'']].filter(item=>String(item[1]).trim());
      const related=(row.context||[]).slice(0,4);
      let body='<dl>'+facts.map(([label,value])=>'<dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd>').join('')+'</dl>';
      if(row.block_id)body+='<button class="source-button" type="button" data-block="'+esc(row.block_id)+'" data-page="'+esc(page)+'">Open source PDF</button>';
      if(related.length)body+='<details><summary>Related notes</summary><ul>'+related.map(item=>'<li>'+esc(item.original_text||'')+'</li>').join('')+'</ul></details>';
      return '<details class="research-source"><summary>Source details</summary>'+body+'</details>';
    }
    function renderResearchResults(payload){
      const rows=payload.results||[], scope=payload.gp_scope||{};
      if(!rows.length){q('#research-results').innerHTML=panel('Search results','<p>No indexed passage matched this wording inside the selected source documents. This result does not prove that the documents omit the subject.</p>');return;}
      const methods=(payload.methods_used||[]).join(' + ')||'keyword';
      q('#research-results').innerHTML='<div class="view-head"><h2>Source evidence</h2><p>'+esc(rows.length+' cited passages for '+scope.scope_name+'. Retrieval: '+methods+'.')+'</p></div><div class="research-table-wrap"><table class="research-results-table"><thead><tr><th scope="col">#</th><th scope="col">Printed evidence</th><th scope="col">Source</th></tr></thead><tbody>'+rows.map((row,index)=>'<tr><td>'+(index+1)+'</td><td class="research-evidence-cell">'+renderedEvidence(row)+'</td><td>'+sourceDetails(row)+'</td></tr>').join('')+'</tbody></table></div>';
      qa('#research-results .source-button').forEach(button=>button.addEventListener('click',()=>openResearchDocument(button.dataset.block,button.dataset.page)));
    }
    async function searchResearch(){
      const selected=selectedResearchScope(), query=q('#research-query').value.trim();
      if(!research.context||!selected){researchStatus('Select a real manager or fund.',true);return;}
      if(!query){researchStatus('Enter search words or a question.',true);return;}
      cancelResearch();const request=++research.request;research.controller=new AbortController();
      const payload={query,result_limit:10,retrieval_methods:['keyword']};
      if(q('#research-entity').selectedOptions[0]?.dataset.scopeType==='fund')payload.fund_id=selected.fund_id;else payload.manager_key=selected.manager_key;
      researchStatus('Searching the selected real source documents.');
      try{
        const result=await researchPost('/gp_search',payload,research.controller.signal);
        if(request!==research.request)return;
        if(!['OK','EMPTY_RESULTS'].includes(result.execution_state))throw new Error(result.execution_state||'Search failed.');
        renderResearchResults(result);researchStatus((result.results||[]).length+' cited passage'+((result.results||[]).length===1?'':'s')+' returned.');
      }catch(error){if(error.name!=='AbortError'&&request===research.request)researchStatus(error.message||String(error),true);}
    }
    function initResearch(){
      q('#research-content').innerHTML=
        '<div class="view-head"><div class="manager-kicker">Reviewed source documents</div><h2>RAG: Document Insights</h2><p>Fictional managers supply quantitative scoring examples. Real managers and funds come from the reviewed PDF extractions and remain a separate population.</p></div>'+panel('Search reviewed fund documents',
        '<p class="mode-note">Select a real manager or fund from the list, then search its reviewed PDFs by keyword. Results retain the report ID, physical PDF page, printed text, and related table or footnote context. No provider model is called.</p><div class="research-grid"><label class="research-span">Manager or fund<select id="research-entity" disabled></select></label><label class="research-span">Search words or a plain-language question<textarea id="research-query">management fees and fund expenses</textarea></label><div class="research-presets research-span"><button class="preset" data-query="management fees carried interest expenses and fee basis">Fees and expenses</button><button class="preset" data-query="fund performance distributions paid in capital NAV IRR TVPI DPI RVPI">Performance and cash</button><button class="preset" data-query="valuation method valuation date fair value and net asset value">Valuation and NAV</button><button class="preset" data-query="commitment term extension key person removal and investment period">Fund terms</button><button class="preset" data-query="investment team governance succession and key person">Team and governance</button><button class="preset" data-query="definitions methodology notes and footnotes">Definitions and footnotes</button></div><div class="research-actions research-span"><button class="primary-action" id="research-search" disabled>Search reviewed PDFs</button></div></div><p id="research-state" class="research-state" aria-live="polite">Loading real managers and funds.</p><div class="kpis" id="research-counts"></div><p class="research-scope" id="research-scope-summary">Select a real manager or fund.</p>')+'<div id="research-results"></div>';
      q('#research-search').addEventListener('click',searchResearch);q('#research-entity').addEventListener('change',renderResearchScope);qa('.preset').forEach(button=>button.addEventListener('click',()=>{q('#research-query').value=button.dataset.query;}));
      connectResearch();
    }
    function render(){
      const p=currentPacket();
      if(!p){['track','stress','holdings','team','evidence'].forEach(id=>q('#'+id+'-content').textContent='Selection contains zero manager groups.');renderCompare();return;}
      renderTrack(p);renderStress(p);renderHoldings(p);renderTeam(p);renderEvidence(p);renderCompare();
      qa('main a[href]').forEach(a=>{a.target='_blank';a.rel='noopener';});
      markSelectedManager();
    }
    function renderReportSummary(){
      const funds=new Set(packets.flatMap(p=>p.funds.map(f=>f.fund_id))).size;
      const strategies=new Set(packets.map(p=>p.strategy)).size;
      const ranked=packets.filter(p=>p.status==='RANKED_DEMO').length;
      const cases=packets.filter(p=>p.case?.status==='AVAILABLE').length;
      q('#report-summary').innerHTML=box('Manager-strategy groups',packets.length)+box('Fund records',funds)+box('Ranked groups',ranked)+box('Reviewed case examples',cases)+box('Strategies',strategies);
    }
    function activate(id){qa('.tab').forEach(x=>x.classList.toggle('active',x.dataset.view===id));qa('.view').forEach(x=>x.classList.toggle('active',x.id===id));q('.toolbar').classList.toggle('research-hidden',id==='research');q('#selection-count').classList.toggle('research-hidden',id==='research');render();}
    [...new Set(packets.map(p=>p.strategy))].sort().forEach(value=>{const o=document.createElement('option');o.value=value;o.textContent=value.replaceAll('_',' ');q('#strategy').append(o);});
    if(packets.some(p=>p.strategy==='buyout'))q('#strategy').value='buyout';
    q('#strategy').addEventListener('change',fillManagers);q('#status').addEventListener('change',fillManagers);q('#manager').addEventListener('change',()=>{if(q('#screener').classList.contains('active'))activate('track');else render();});
    qa('.tab').forEach(btn=>btn.addEventListener('click',()=>activate(btn.dataset.view)));renderReportSummary();initResearch();fillManagers();if(fragmentValue('view')==='research')activate('research');
    """
    tabs = [("screener", "Screener"), ("compare", "Manager Comparison"), ("track", "Track Record & Peers"), ("stress", "Realization & Stress"),
            ("holdings", "Holdings & Terms"), ("team", "Team / Governance"), ("evidence", "Evidence & Diligence"),
            ("research", "RAG: Document Insights")]
    navigation = "".join(
        f"<button class='tab{' active' if key == 'screener' else ''}' data-view='{key}'>{label}</button>"
        for key, label in tabs
    )
    views = "".join(f"<section id='{key}' class='view{' active' if key == 'screener' else ''}'><div id='{key}-content'></div></section>" for key, _ in tabs)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>GP Scoring</title><style>{css}</style></head><body>
    <header class="hero"><div class="hero-inner"><div class="eyebrow">Alternative investment manager diligence</div><h1>GP Scoring</h1><p class="lede">Fictional manager records support quantitative scoring and scenario analysis. A separate document search uses real managers, real funds, and reviewed source PDFs.</p>
    <div class="release-meta"><span>Economic date: {_e(metadata.get('economic_as_of', ''))}</span><span>Information cutoff: {_e(metadata.get('information_cutoff', ''))}</span><span>Equal fund weights for manager summaries</span></div>
    <details class="definitions"><summary>Measure definitions</summary><p>Total value to paid-in capital (TVPI) divides distributions plus remaining fund value by investor contributions. Distributions to paid-in capital (DPI) counts cash returned. Net asset value (NAV) is the remaining fund value.</p><p>The historical score is 60% TVPI percentile and 40% DPI percentile. A percentile compares a fund with same-strategy, currency and vintage peers, excluding the same manager. Ranked groups require two scored funds and 75% coverage of their supplied same-strategy history. Tied scores use competition ranks: 1, 1, 3.</p><p>Annualized return (XIRR) uses payment dates. Kaplan–Schoar public market equivalent (KS-PME) compares fund value with placing the same dated payments in a benchmark; values above one favor the fund. Direct Alpha expresses this comparison as an annualized excess return. Concentration uses squared value shares, often called HHI.</p><p>Scores describe fictional histories. Three case examples use generated documents and separate investment events.</p></details>
    <div class="toolbar" aria-label="Dashboard filters"><label>Strategy<select id="strategy"></select></label><label>Status<select id="status"><option value="RANKED_DEMO">Ranked</option><option value="PARTIAL_TRACK_RECORD">Partial history</option><option value="INSUFFICIENT_DATA">Insufficient data</option><option value="ALL">All groups</option></select></label><label>Scored manager (fictional)<select id="manager"></select></label></div><p id="selection-count" aria-live="polite"></p></div></header>
    <div class="tab-shell"><nav class="tabs" aria-label="Dashboard views">{navigation}</nav></div><main><section class="report-summary" aria-label="Report coverage"><div><div class="summary-label">Current report</div><p class="summary-copy">Fictional histories supply the scoring analyses. Real names appear only in the separate source-document search.</p></div><div class="kpis" id="report-summary"></div></section>{views}</main>
    <footer>Fictional scoring records and real source-document evidence remain separate populations.</footer>
    <script id="report-data" type="application/json">{data}</script><script>{script}</script></body></html>"""
