"""The dashboard shell: style, browser code, and the HTML wrapper.

The page holds its data inline and loads nothing over the network, so a
reviewer opens the file from disk and reads every panel offline. The block
kinds rendered here are the ones `build_dashboard` emits: kpi, note, heading,
steps, keyvalue, bars, formulas, table, and explorer.

Numbers are shown to two decimals at most. Every table carries a row
description, every column carries a definition in the column guide, and the
row detail retains every field omitted from the compact grid.
"""

from __future__ import annotations

import json


STYLE = r"""
:root {
  --ink: #142033;
  --ink-soft: #27374a;
  --ink-faint: #3b4a5d;
  --line: #c8d2df;
  --rule: #e2e7ee;
  --page: #eaf0f6;
  --paper: #ffffff;
  --panel: #f4f7fb;
  --accent: #174f7c;
  --accent-2: #246b9e;
  --accent-soft: #dceaf5;
  --nav: #102a43;
  --nav-soft: #dbe8f3;
  --nav-hover: #173b5c;
  --good: #1f6f45;
  --good-soft: #e6f3ec;
  --warn: #8a5b00;
  --warn-soft: #fbf1dc;
  --stop: #9b2226;
  --stop-soft: #f9e5e6;
  --mono: ui-monospace, "Cascadia Mono", "SF Mono", Menlo, Consolas, monospace;
  --sans: -apple-system, "Segoe UI", Inter, Roboto, Helvetica, Arial, sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--page);
  color: var(--ink);
  font: 15px/1.58 var(--sans);
  display: flex;
  align-items: flex-start;
}
a { color: #0f5688; }
a:focus-visible, button:focus-visible, input:focus-visible, summary:focus-visible {
  outline: 3px solid #f3b53f;
  outline-offset: 2px;
}

#nav {
  position: sticky;
  top: 0;
  flex: 0 0 256px;
  height: 100vh;
  overflow-y: auto;
  border-right: 1px solid #0b2136;
  background: var(--nav);
  color: #ffffff;
  padding: 22px 0 40px;
}
#nav h1 { font-size: 16px; margin: 0 20px 5px; line-height: 1.35; }
#nav .sub { margin: 0 20px 20px; font-size: 12px; color: var(--nav-soft); }
#nav a {
  display: flex; gap: 10px; align-items: baseline;
  padding: 7px 20px;
  font-size: 14px;
  color: #f6f9fc;
  text-decoration: none;
  border-left: 3px solid transparent;
}
#nav a .n { font-family: var(--mono); font-size: 11px; color: var(--nav-soft); min-width: 16px; }
#nav a:hover { background: var(--nav-hover); }
#nav a.on { border-left-color: #69b9ed; background: var(--nav-hover); font-weight: 650; }
#nav .foot { margin: 22px 20px 0; font-size: 11.5px; color: var(--nav-soft); line-height: 1.5; }

main { flex: 1 1 auto; min-width: 0; padding: 40px 44px 90px; max-width: 1560px; }
section { display: none; }
section.on { display: block; }
.eyebrow { font-family: var(--mono); font-size: 11.5px; letter-spacing: .08em; text-transform: uppercase; color: var(--accent); margin: 0 0 6px; font-weight: 650; }
h2 { font-size: 30px; margin: 0 0 9px; letter-spacing: -.025em; line-height: 1.2; }
.blurb { color: var(--ink-soft); margin: 0 0 30px; max-width: 82ch; font-size: 16px; }
h3 { font-size: 18px; margin: 38px 0 12px; letter-spacing: -.012em; }
p.note { max-width: 88ch; margin: 0 0 16px; color: #2b3038; }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 0 0 22px; }
.kpi { border: 1px solid var(--line); border-top: 4px solid var(--accent-2); border-radius: 9px; padding: 14px 16px 13px; background: var(--paper); box-shadow: 0 2px 8px rgba(20,32,51,.07); }
.kpi .v { font-size: 25px; font-weight: 650; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.kpi .l { font-size: 11.5px; color: var(--ink-soft); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
.kpi .n { font-size: 12.5px; color: var(--ink-soft); margin-top: 6px; line-height: 1.4; }

.steps { counter-reset: s; margin: 0 0 22px; padding: 0; list-style: none; }
.steps li { counter-increment: s; position: relative; padding: 0 0 14px 42px; border-left: 2px solid var(--rule); margin-left: 13px; }
.steps li:last-child { border-left-color: transparent; }
.steps li::before {
  content: counter(s);
  position: absolute; left: -14px; top: -2px;
  width: 26px; height: 26px; border-radius: 50%;
  background: var(--accent); color: #fff;
  font-size: 12px; font-weight: 700;
  display: grid; place-items: center;
}
.steps b { display: block; }
.steps span { color: var(--ink-soft); }
.steps li.stage-head {
  counter-increment: none;
  padding: 16px 0 10px 42px;
  font-size: 11px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase;
  color: var(--accent);
}
.steps li.stage-head:first-child { padding-top: 0; }
.steps li.stage-head::before { content: none; }

.kv { border: 1px solid var(--line); border-radius: 8px; overflow: hidden; margin: 0 0 22px; background: var(--paper); }
.kv div { display: flex; gap: 16px; padding: 8px 14px; border-bottom: 1px solid var(--rule); font-size: 14px; }
.kv div:last-child { border-bottom: 0; }
.kv dt { flex: 0 0 280px; color: var(--ink-soft); margin: 0; }
.kv dd { margin: 0; flex: 1 1 auto; }

.panel { border: 1px solid var(--line); border-radius: 9px; margin: 0 0 26px; overflow: hidden; background: var(--paper); box-shadow: 0 3px 12px rgba(20,32,51,.07); }
.panel > header { padding: 14px 17px 13px; border-bottom: 1px solid var(--line); border-left: 4px solid var(--accent-2); background: var(--panel); }
.panel h4 { margin: 0; font-size: 15.5px; }
.panel .about { margin: 5px 0 0; font-size: 13.5px; color: var(--ink-soft); max-width: 104ch; line-height: 1.5; }
.panel .src { font-family: var(--mono); font-size: 11.5px; color: var(--ink-faint); margin-top: 7px; overflow-wrap: anywhere; }
.panel details { border-bottom: 1px solid var(--rule); }
.panel summary { padding: 8px 16px; font-size: 12.5px; color: var(--accent); cursor: pointer; user-select: none; }
.panel summary:hover { background: var(--accent-soft); }
.panel .defs { padding: 4px 16px 12px; display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 3px 22px; font-size: 12.5px; }
.panel .defs div { display: flex; gap: 8px; align-items: baseline; }
.panel .defs code { flex: 0 0 auto; }
.panel .defs span { color: var(--ink-soft); }
.panel .bar-row { display: flex; gap: 10px; align-items: center; padding: 9px 16px; border-bottom: 1px solid var(--rule); }
.panel input[type=search] { flex: 1 1 auto; font: inherit; font-size: 13px; padding: 7px 10px; border: 1px solid #9dacbd; border-radius: 6px; min-width: 120px; background: #fff; color: var(--ink); }
.panel .count { font-size: 12px; color: var(--ink-soft); white-space: nowrap; }
.panel .pager { display: flex; gap: 8px; align-items: center; padding: 9px 16px; font-size: 13px; }
.panel button { font: inherit; font-size: 13px; padding: 4px 11px; border: 1px solid var(--line); background: #fff; border-radius: 6px; cursor: pointer; }
.panel button:hover:not(:disabled) { background: var(--accent-soft); }
.panel button:disabled { color: var(--ink-faint); background: #eef2f5; cursor: default; }
.scroll { overflow-x: auto; max-height: 640px; overflow-y: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--rule); vertical-align: top; }
th {
  position: sticky; top: 0; z-index: 1;
  background: #263b52; border-bottom: 1px solid #16283b;
  font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: #ffffff;
  cursor: pointer; white-space: nowrap;
}
th .type { display: block; font-weight: 400; text-transform: none; letter-spacing: 0; font-size: 10.5px; color: #c8d6e4; }
th.up .lbl::after { content: " \2191"; }
th.down .lbl::after { content: " \2193"; }
td { max-width: 38ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-variant-numeric: tabular-nums; }
td.technical { max-width: 24ch; font-family: var(--mono); font-size: 12px; }
td.narrative { max-width: 34ch; }
td.num { text-align: right; }
th.num { text-align: right; }
tbody tr:nth-child(4n+3) td { background: #f4f7fa; }
tbody tr.row:hover td { background: var(--accent-soft); cursor: pointer; }
tr.detail td { white-space: normal; max-width: none; background: #f6f8fb; padding: 12px 16px 14px; }
.detail .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px 26px; }
.detail .grid div { border-left: 2px solid var(--line); padding-left: 10px; }
.detail .grid .k { font-size: 12px; color: var(--ink); font-weight: 650; }
.detail .grid code.field { display: block; width: fit-content; margin-top: 2px; color: var(--ink-faint); background: transparent; padding: 0; }
.detail .grid .v { font-size: 13.5px; word-break: break-word; margin: 1px 0; }
.detail .grid .d { font-size: 12px; color: var(--ink-faint); line-height: 1.4; }
.hint { font-size: 12px; color: var(--ink-soft); padding: 9px 16px 11px; border-top: 1px solid var(--rule); background: var(--panel); }
.status-PASS, .status-DETECTED, .status-ACTIVE, .status-TRACK { color: var(--good); font-weight: 600; }
.status-WARN, .status-EXCLUDED_FROM_RELEASE, .status-WARNING, .status-SKIP, .status-DEMO_PROXY_ONLY, .status-DEMONSTRATION_ONLY { color: var(--warn); font-weight: 600; }
.status-FAIL, .status-MISSED, .status-REJECT { color: var(--stop); font-weight: 600; }
code { font-family: var(--mono); font-size: 12.5px; background: var(--panel); padding: 1px 4px; border-radius: 3px; }

.bars { padding: 12px 16px 14px; }
.bar { display: grid; grid-template-columns: 240px 1fr 140px; gap: 12px; align-items: center; padding: 3px 0; font-size: 13px; }
.bar .track { background: var(--rule); border-radius: 4px; height: 16px; }
.bar .fill { background: linear-gradient(90deg, var(--accent), var(--accent-2)); height: 16px; border-radius: 4px; min-width: 2px; }
.bar .num { text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-soft); white-space: pre; }
.bar .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.formulas { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 16px; margin: 0 0 24px; }
.formula { border: 1px solid var(--line); border-radius: 8px; background: var(--paper); box-shadow: 0 1px 2px rgba(23,26,33,.04); display: flex; flex-direction: column; }
.formula header { padding: 14px 18px 10px; }
.formula h4 { margin: 0; font-size: 17px; }
.formula .plain { margin: 4px 0 0; font-size: 13.5px; color: #3a404b; line-height: 1.5; }
.formula .math { padding: 14px 18px; background: var(--panel); border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); font-size: 15px; overflow-x: auto; }
.formula .math .eq { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; white-space: nowrap; }
.frac { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin: 0 4px; }
.frac > span { padding: 1px 8px; }
.frac > span:first-child { border-bottom: 1.5px solid var(--ink); }
.formula .math i { font-style: italic; color: var(--accent); }
.formula .math .sum { font-size: 20px; }
.formula .example { padding: 12px 18px 6px; }
.formula .example h5 { margin: 0 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-soft); }
.formula .example table { font-size: 13px; }
.formula .example th { position: static; }
.formula .example td, .formula .example th { padding: 4px 8px; }
.formula .example tr:last-child td { border-bottom: 0; }
.formula .example .result td { font-weight: 650; border-top: 1.5px solid var(--line); }
.formula footer { padding: 10px 18px 14px; margin-top: auto; font-size: 12px; color: var(--ink-soft); display: grid; grid-template-columns: 110px 1fr; gap: 3px 10px; }
.formula footer code { font-size: 11.5px; }

/* Box-and-whisker plots. The five printed numbers of a distribution drawn to
   one scale per unit, so multiples compare with multiples and rates with
   rates. Positions are percentages, so the plot reflows with the panel. */
.boxes { padding: 6px 16px 14px; }
.boxgroup { padding: 10px 0 4px; }
.boxgroup + .boxgroup { border-top: 1px solid var(--rule); margin-top: 8px; }
.boxscale { display: grid; grid-template-columns: 150px 56px 1fr 92px; gap: 12px; font-size: 11px; color: var(--ink-faint); text-transform: uppercase; letter-spacing: .05em; padding-bottom: 6px; }
.boxscale .ends { display: flex; justify-content: space-between; }
.boxrow { display: grid; grid-template-columns: 150px 56px 1fr 92px; gap: 12px; align-items: center; padding: 5px 0; font-size: 13px; }
.boxrow .name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.boxrow .n, .boxrow .mid { text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-soft); }
.boxrow .mid { color: var(--ink); font-weight: 650; }
.boxtrack { position: relative; height: 26px; }
.boxtrack .axis { position: absolute; left: 0; right: 0; top: 50%; height: 1px; background: var(--rule); }
.boxtrack .zero { position: absolute; top: 0; bottom: 0; width: 1px; background: #c9d1dc; }
.boxtrack .whisk { position: absolute; top: 50%; height: 1px; background: #97a1af; }
.boxtrack .cap { position: absolute; top: calc(50% - 5px); width: 1px; height: 11px; background: #97a1af; }
.boxtrack .box { position: absolute; top: 4px; height: 19px; border-radius: 4px; background: linear-gradient(180deg, var(--accent-2), var(--accent)); box-shadow: 0 1px 2px rgba(23,26,33,.18); min-width: 2px; }
.boxtrack .med { position: absolute; top: 2px; width: 2px; height: 23px; background: #fff; border-radius: 1px; }

/* Donuts, drawn with a conic gradient so they stay crisp at any size. */
.donutrow { display: flex; flex-wrap: wrap; gap: 22px; align-items: center; padding: 16px; }
.donut { position: relative; width: 148px; height: 148px; border-radius: 50%; flex: 0 0 auto; }
.donut::after { content: ""; position: absolute; inset: 24%; background: var(--paper); border-radius: 50%; }
.donut .mid { position: absolute; inset: 22%; display: grid; place-content: center; text-align: center; z-index: 1; }
.donut .mid b { display: block; font-size: 18px; letter-spacing: -.02em; font-variant-numeric: tabular-nums; line-height: 1.2; }
.donut .mid span { display: block; font-size: 10.5px; color: var(--ink-soft); text-transform: uppercase; letter-spacing: .03em; line-height: 1.25; }
.legend { flex: 1 1 260px; min-width: 240px; }
.legend div { display: grid; grid-template-columns: 12px 1fr auto auto; gap: 10px; align-items: center; padding: 3px 0; font-size: 13px; border-bottom: 1px solid var(--rule); }
.legend div:last-child { border-bottom: 0; }
.legend i { width: 12px; height: 12px; border-radius: 3px; display: block; }
.legend .k { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.legend .v { font-variant-numeric: tabular-nums; }
.legend .p { font-variant-numeric: tabular-nums; color: var(--ink-soft); min-width: 48px; text-align: right; }

/* Stacked composition bars: one row per thing, segments in proportion. */
.stacks { padding: 6px 16px 14px; }
.stackrow { display: grid; grid-template-columns: 190px 1fr 76px; gap: 12px; align-items: center; padding: 4px 0; font-size: 13px; }
.stackrow .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stackrow .tot { text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-soft); }
.stackhold { min-width: 0; }
.stackbar { display: flex; height: 20px; border-radius: 4px; overflow: hidden; background: var(--rule); }
.stackbar span { display: grid; place-content: center; font-size: 11px; color: #fff; font-variant-numeric: tabular-nums; overflow: hidden; white-space: nowrap; }
.keys { display: flex; flex-wrap: wrap; gap: 14px; padding: 12px 16px 4px; font-size: 12.5px; }
.keys div { display: flex; gap: 7px; align-items: center; }
.keys i { width: 12px; height: 12px; border-radius: 3px; display: block; }

.kpi .meter { margin-top: 9px; height: 4px; border-radius: 2px; background: var(--rule); overflow: hidden; }
.kpi .meter i { display: block; height: 100%; border-radius: 2px; background: linear-gradient(90deg, var(--accent-2), var(--accent)); }

.pills { display: flex; flex-wrap: wrap; gap: 8px; padding: 11px 16px; border-bottom: 1px solid var(--rule); }
.pill { font-family: var(--mono); font-size: 12.5px; padding: 5px 12px; border: 1px solid var(--line); background: #fff; border-radius: 999px; cursor: pointer; }
.pill.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.explorer { display: grid; grid-template-columns: 260px minmax(0, 1fr); }
.tablelist { border-right: 1px solid var(--line); max-height: 700px; overflow-y: auto; background: var(--panel); }
.tablelist button {
  display: flex; justify-content: space-between; gap: 8px; align-items: baseline;
  width: 100%; text-align: left; border: 0; border-bottom: 1px solid var(--rule);
  border-radius: 0; background: none; padding: 7px 14px; cursor: pointer; font-size: 13px;
}
.tablelist button:hover { background: var(--accent-soft); }
.tablelist button.on { background: var(--accent-soft); box-shadow: inset 3px 0 0 var(--accent); font-weight: 600; }
.tablelist button.view .n { font-style: italic; }
.tablelist .n { font-family: var(--mono); font-size: 12px; overflow: hidden; text-overflow: ellipsis; }
.tablelist .c { color: var(--ink-soft); font-variant-numeric: tabular-nums; font-size: 12px; }
.gridside { min-width: 0; }
.caption { padding: 14px 16px 2px; font-size: 13.5px; border-bottom: 1px solid var(--rule); background: #fbfcfe; }
.caption .shape { font-weight: 650; color: var(--ink); }
.caption .what { color: #3a404b; margin-top: 3px; line-height: 1.5; }

@media (max-width: 900px) {
  body { display: block; }
  #nav { position: static; height: auto; width: 100%; flex: none; }
  #nav a { display: inline-flex; width: 49%; vertical-align: top; }
  main { padding: 22px 16px 60px; }
  .bar { grid-template-columns: 130px 1fr 80px; }
  .explorer { grid-template-columns: minmax(0, 1fr); }
  .tablelist { border-right: 0; border-bottom: 1px solid var(--line); max-height: 220px; }
  .formulas { grid-template-columns: 1fr; }
  .kv div { display: block; }
  .kv dt { margin-bottom: 3px; }
}
@media (max-width: 560px) {
  #nav a { width: 100%; }
  h2 { font-size: 26px; }
  .kpis { grid-template-columns: 1fr; }
  .bar { grid-template-columns: 100px 1fr 70px; gap: 8px; }
}
@media print {
  #nav { display: none; }
  section { display: block !important; page-break-before: always; }
  .scroll { max-height: none; }
}
"""


SCRIPT = r"""
const DATA = JSON.parse(document.getElementById('payload').textContent);
const nav = document.getElementById('nav');
const main = document.getElementById('main');

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function statusClass(value) {
  const key = String(value).trim();
  return /^(PASS|FAIL|WARN|WARNING|SKIP|DETECTED|MISSED|EXCLUDED_FROM_RELEASE|DEMO_PROXY_ONLY|DEMONSTRATION_ONLY|ACTIVE|TRACK|REJECT)$/.test(key)
    ? 'status-' + key : '';
}

// ---------------------------------------------------------------- numbers
//
// A cell that is a bare number is shown to two decimals at most, with
// thousands separators once it passes four digits. Identifiers, years, page
// numbers, and hashes are left as printed: the column name says which they
// are. The full value stays on the cell as its tooltip and in the row detail.
const PLAIN_NUMBER = /^-?\d+(\.\d+)?$/;
const REPO_PATH = /^(data|ledgers|instructions|docs|src|audit|config|sql|tests)\/[^\s]+\.[A-Za-z0-9]+$/;
const KEEP_AS_IS = /(^|_)(year|id|ids|page|pages|seed|order|version|number|line|precision|zip|phone)$|_id$|^id$|date|sha|hash|ticker|checked_at|created_at|retrieved_at/i;

function formatNumber(n, decimals) {
  return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function plural(n, word) {
  return n.toLocaleString() + ' ' + word + (n === 1 ? '' : 's');
}

function fmt(value, column, hint) {
  if (value === null || value === undefined) return '';
  const s = String(value).trim();
  if (s === '' || hint === 'raw' || !PLAIN_NUMBER.test(s)) return s;
  const n = Number(s);
  if (hint === 'pct') return formatNumber(n * 100, 2) + '%';
  if (hint === 'x') return formatNumber(n, 2) + 'x';
  if (hint === 'money' || hint === 'int') return formatNumber(n, 0);
  if (hint === 'num') return formatNumber(n, 2);
  if (KEEP_AS_IS.test(column)) return s;
  if (s.includes('.')) return formatNumber(n, 2);
  return Math.abs(n) >= 10000 ? formatNumber(n, 0) : s;
}

function isNumeric(value, column, hint) {
  const s = String(value === null || value === undefined ? '' : value).trim();
  return s !== '' && hint !== 'raw' && PLAIN_NUMBER.test(s) && !KEEP_AS_IS.test(column);
}

const COLUMN_TERMS = {
  id: 'ID', ids: 'IDs', irr: 'IRR', xirr: 'XIRR', pme: 'PME', dpi: 'DPI',
  rvpi: 'RVPI', tvpi: 'TVPI', nav: 'NAV', lp: 'LP', pdf: 'PDF', csv: 'CSV',
  url: 'URL', sha256: 'SHA-256', usd: 'USD', fx: 'FX', spv: 'SPV', sic: 'SIC',
};

function friendlyColumn(name) {
  const raw = String(name);
  if (/\s/.test(raw) || (/^[A-Z0-9-]+$/.test(raw) && !raw.includes('_'))) return raw;
  return raw.split('_').map((part, index) => {
    const word = part.toLowerCase();
    if (COLUMN_TERMS[word]) return COLUMN_TERMS[word];
    return index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word;
  }).join(' ');
}

function fieldClass(name) {
  const key = String(name).toLowerCase();
  if (/(^|_)(id|ids|sha256|hash|path|url|ticker|code|key)(_|$)/.test(key)) return 'technical';
  if (/(quote|notes?|reason|description|formula|command|contents|fields|anchor|basis)/.test(key)) return 'narrative';
  return '';
}

// ---------------------------------------------------------------- blocks

// Colours carry meaning wherever the data has an order to it: how printed a
// value is, and whether a rule passed. Everything else takes the categorical
// list in turn.
const PALETTE = ['#1e4d7b', '#2f6fae', '#4a9ac9', '#5aa9a0', '#b0894f', '#a35f68', '#7a6ea8', '#8a9199',
                 '#34779f', '#587847', '#c09a5e', '#b091a5'];
const NAMED = {
  EXTRACTED: '#1e4d7b', DERIVED: '#4a9ac9', IMPUTED: '#b0894f', SYNTHETIC: '#8a9199',
  PASS: '#1f6f45', FAIL: '#9b2226', SKIP: '#b0894f', WARNING: '#b0894f',
};

function colourFor(label, index) {
  return NAMED[String(label).toUpperCase()] || PALETTE[index % PALETTE.length];
}

function textColourFor(background) {
  const channels = [1, 3, 5].map((start) => parseInt(background.slice(start, start + 2), 16) / 255);
  const luminance = channels.map((channel) => channel <= 0.04045
    ? channel / 12.92
    : Math.pow((channel + 0.055) / 1.055, 2.4))
    .reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
  const whiteContrast = 1.05 / (luminance + 0.05);
  const darkLuminance = 0.021234698947365385; // #102a43
  const darkContrast = (luminance + 0.05) / (darkLuminance + 0.05);
  return whiteContrast >= darkContrast ? '#fff' : '#102a43';
}

function renderKpi(block) {
  const wrap = el('div', 'kpis');
  for (const item of block.items) {
    const card = el('div', 'kpi');
    card.appendChild(el('div', 'l', item.label));
    card.appendChild(el('div', 'v', item.value));
    if (item.note) card.appendChild(el('div', 'n', item.note));
    if (item.share !== undefined && item.share !== null) {
      const meter = el('div', 'meter');
      const fill = el('i');
      fill.style.width = Math.max(0, Math.min(100, item.share * 100)) + '%';
      meter.appendChild(fill);
      card.appendChild(meter);
    }
    wrap.appendChild(card);
  }
  return wrap;
}

function renderBoxes(block) {
  const panel = el('div', 'panel');
  panel.appendChild(panelHeader(block));
  const wrap = el('div', 'boxes');
  for (const group of block.groups) {
    const box = el('div', 'boxgroup');
    const scale = el('div', 'boxscale');
    scale.appendChild(el('div', null, group.title));
    scale.appendChild(el('div', null, 'rows'));
    const ends = el('div', 'ends');
    ends.appendChild(el('span', null, group.low_display));
    ends.appendChild(el('span', null, group.high_display));
    scale.appendChild(ends);
    scale.appendChild(el('div', null, 'median'));
    box.appendChild(scale);

    const span = group.high - group.low || 1;
    const at = (value) => ((value - group.low) / span) * 100;
    for (const item of group.items) {
      const row = el('div', 'boxrow');
      row.appendChild(el('div', 'name', item.label));
      row.appendChild(el('div', 'n', item.rows));
      const track = el('div', 'boxtrack');
      track.appendChild(el('div', 'axis'));
      if (group.low < 0 && group.high > 0) {
        const zero = el('div', 'zero');
        zero.style.left = at(0) + '%';
        track.appendChild(zero);
      }
      const whisk = el('div', 'whisk');
      whisk.style.left = at(item.min) + '%';
      whisk.style.width = Math.max(0, at(item.max) - at(item.min)) + '%';
      track.appendChild(whisk);
      for (const end of [item.min, item.max]) {
        const cap = el('div', 'cap');
        cap.style.left = at(end) + '%';
        track.appendChild(cap);
      }
      const body = el('div', 'box');
      body.style.left = at(item.p25) + '%';
      body.style.width = Math.max(0.4, at(item.p75) - at(item.p25)) + '%';
      track.appendChild(body);
      const median = el('div', 'med');
      median.style.left = at(item.median) + '%';
      track.appendChild(median);
      track.title =
        'minimum ' + item.display.min + ', 25th ' + item.display.p25 + ', median ' + item.display.median +
        ', 75th ' + item.display.p75 + ', maximum ' + item.display.max;
      row.appendChild(track);
      row.appendChild(el('div', 'mid', item.display.median));
      box.appendChild(row);
    }
    wrap.appendChild(box);
  }
  panel.appendChild(wrap);
  panel.appendChild(el('div', 'hint', 'The bar is the middle half of the values (25th to 75th). The white line is the median. The thin line is the low and the high. Rest on a row to see all five numbers.'));
  return panel;
}

function renderDonuts(block) {
  const panel = el('div', 'panel');
  panel.appendChild(panelHeader(block));
  for (const chart of block.charts) {
    const row = el('div', 'donutrow');
    const total = chart.items.reduce((sum, item) => sum + item.value, 0) || 1;
    let cursor = 0;
    const stops = [];
    chart.items.forEach((item, index) => {
      const start = (cursor / total) * 360;
      cursor += item.value;
      const end = (cursor / total) * 360;
      stops.push(colourFor(item.label, index) + ' ' + start.toFixed(2) + 'deg ' + end.toFixed(2) + 'deg');
    });
    const ring = el('div', 'donut');
    ring.style.background = 'conic-gradient(' + stops.join(', ') + ')';
    const mid = el('div', 'mid');
    mid.appendChild(el('b', null, chart.total_display));
    mid.appendChild(el('span', null, chart.total_label));
    ring.appendChild(mid);
    row.appendChild(ring);

    const legend = el('div', 'legend');
    chart.items.forEach((item, index) => {
      const line = el('div');
      const swatch = el('i');
      swatch.style.background = colourFor(item.label, index);
      line.appendChild(swatch);
      line.appendChild(el('div', 'k', item.label)).title = item.label;
      line.appendChild(el('div', 'v', item.display));
      line.appendChild(el('div', 'p', ((item.value / total) * 100).toFixed(1) + '%'));
      legend.appendChild(line);
    });
    row.appendChild(legend);
    panel.appendChild(row);
  }
  return panel;
}

function renderStacks(block) {
  const panel = el('div', 'panel');
  panel.appendChild(panelHeader(block));
  const keys = el('div', 'keys');
  block.keys.forEach((key, index) => {
    const item = el('div');
    const swatch = el('i');
    swatch.style.background = colourFor(key, index);
    item.appendChild(swatch);
    item.appendChild(el('span', null, key));
    keys.appendChild(item);
  });
  panel.appendChild(keys);

  const wrap = el('div', 'stacks');
  // A row with fewer cells gets a shorter bar, so the picture carries both the
  // mix inside a row and how that row compares with the fullest one.
  const widest = Math.max(...block.rows.map((row) => row.values.reduce((sum, value) => sum + value, 0)), 1);
  for (const row of block.rows) {
    const line = el('div', 'stackrow');
    line.appendChild(el('div', 'name', row.label)).title = row.label;
    const holder = el('div', 'stackhold');
    const bar = el('div', 'stackbar');
    const total = row.values.reduce((sum, value) => sum + value, 0) || 1;
    bar.style.width = (total / widest) * 100 + '%';
    row.values.forEach((value, index) => {
      if (!value) return;
      const share = (value / total) * 100;
      const segment = el('span', null, share >= 9 ? value.toLocaleString() : '');
      segment.style.width = share + '%';
      const background = colourFor(block.keys[index], index);
      segment.style.background = background;
      segment.style.color = textColourFor(background);
      segment.title = block.keys[index] + ': ' + value.toLocaleString() + ' (' + share.toFixed(1) + '%)';
      bar.appendChild(segment);
    });
    holder.appendChild(bar);
    line.appendChild(holder);
    line.appendChild(el('div', 'tot', row.total_display));
    wrap.appendChild(line);
  }
  panel.appendChild(wrap);
  return panel;
}

function renderNote(block) {
  return el('p', 'note', block.text);
}

function renderSteps(block) {
  const list = el('ol', 'steps');
  let stage = null;
  for (const item of block.items) {
    if (item.stage && item.stage !== stage) {
      stage = item.stage;
      list.appendChild(el('li', 'stage-head', stage));
    }
    const li = el('li');
    li.appendChild(el('b', null, item.title));
    li.appendChild(el('span', null, item.text));
    list.appendChild(li);
  }
  return list;
}

function renderKeyvalue(block) {
  const wrap = el('dl', 'kv');
  for (const [key, value] of block.items) {
    const row = el('div');
    row.appendChild(el('dt', null, key));
    row.appendChild(el('dd', null, value));
    wrap.appendChild(row);
  }
  return wrap;
}

function panelHeader(block) {
  const head = el('header');
  head.appendChild(el('h4', null, block.title));
  if (block.about) head.appendChild(el('p', 'about', block.about));
  if (block.source) head.appendChild(el('div', 'src', 'Source: ' + block.source));
  return head;
}

function renderBars(block) {
  const panel = el('div', 'panel');
  panel.appendChild(panelHeader(block));
  const wrap = el('div', 'bars');
  const top = Math.max(...block.items.map((item) => item.value), 1);
  const total = block.items.reduce((sum, item) => sum + item.value, 0);
  block.items.forEach((item, index) => {
    const row = el('div', 'bar');
    row.appendChild(el('div', 'name', item.label)).title = item.label;
    const track = el('div', 'track');
    const fill = el('div', 'fill');
    fill.style.width = Math.max(1, (item.value / top) * 100) + '%';
    if (NAMED[String(item.label).toUpperCase()]) fill.style.background = colourFor(item.label, index);
    track.appendChild(fill);
    row.appendChild(track);
    const shown = item.display !== undefined ? item.display : item.value;
    const share = total ? '  ' + ((item.value / total) * 100).toFixed(1) + '%' : '';
    row.appendChild(el('div', 'num', shown + share));
    wrap.appendChild(row);
  });
  panel.appendChild(wrap);
  return panel;
}

function renderFormulas(block) {
  const holder = el('div');
  if (block.title) holder.appendChild(el('h3', null, block.title));
  const wrap = el('div', 'formulas');
  for (const item of block.items) {
    const card = el('div', 'formula');
    const head = el('header');
    head.appendChild(el('h4', null, item.name));
    head.appendChild(el('p', 'plain', item.plain));
    card.appendChild(head);
    const math = el('div', 'math');
    const eq = el('div', 'eq');
    eq.innerHTML = item.html;   // authored in the builder, never from data
    math.appendChild(eq);
    card.appendChild(math);
    if (item.example && item.example.rows.length) {
      const ex = el('div', 'example');
      ex.appendChild(el('h5', null, item.example.title));
      const table = el('table');
      const tbody = el('tbody');
      item.example.rows.forEach((row, index) => {
        const tr = el('tr', index === item.example.rows.length - 1 && item.example.result ? 'result' : null);
        row.forEach((cell, c) => {
          const td = el('td', c > 0 ? 'num' : null, cell);
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      ex.appendChild(table);
      card.appendChild(ex);
    }
    const foot = el('footer');
    for (const [key, value] of item.lines) {
      foot.appendChild(el('span', null, key));
      const v = el('span');
      v.appendChild(el('code', null, value));
      foot.appendChild(v);
    }
    card.appendChild(foot);
    wrap.appendChild(card);
  }
  holder.appendChild(wrap);
  return holder;
}

// One grid, reused by the plain tables and by the database explorer, which
// re-points it at whatever table the reader selects.
function dataGrid(options) {
  const node = el('div');
  const defs = el('details');
  defs.appendChild(el('summary', null, 'Column meanings'));
  const defList = el('div', 'defs');
  defs.appendChild(defList);
  node.appendChild(defs);

  const controls = el('div', 'bar-row');
  const search = document.createElement('input');
  search.type = 'search';
  search.placeholder = 'Search table rows';
  search.setAttribute('aria-label', 'Search table rows');
  controls.appendChild(search);
  const count = el('div', 'count');
  controls.appendChild(count);
  node.appendChild(controls);

  const scroll = el('div', 'scroll');
  const table = el('table');
  const thead = el('thead');
  const headRow = el('tr');
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = el('tbody');
  table.appendChild(tbody);
  scroll.appendChild(table);
  node.appendChild(scroll);

  const pager = el('div', 'pager');
  const back = el('button', null, 'Previous');
  const next = el('button', null, 'Next');
  const place = el('div', 'count');
  pager.appendChild(back);
  pager.appendChild(next);
  pager.appendChild(place);
  node.appendChild(pager);
  node.appendChild(el('div', 'hint', 'Select a row to see every field and the page quote. Select a heading to sort. Rest on a heading to read its meaning.'));

  const size = (options && options.page) || 25;
  const held = (options && options.heldIn) || 'in the file';
  let columns = [];
  let hidden = [];
  let definitions = [];
  let formats = {};
  let rows = [];
  let total = 0;
  let page = 0;
  let sortIndex = -1;
  let ascending = true;

  function matches(row, needle) {
    return row.join('  |  ').toLowerCase().includes(needle);
  }

  function sortBy(index, th) {
    ascending = sortIndex === index ? !ascending : true;
    sortIndex = index;
    for (const other of headRow.children) other.classList.remove('up', 'down');
    th.classList.add(ascending ? 'up' : 'down');
    const sign = ascending ? 1 : -1;
    rows.sort((left, right) => {
      const a = left[index] === undefined ? '' : left[index];
      const b = right[index] === undefined ? '' : right[index];
      const na = parseFloat(String(a).replace(/[$,%x\s]/g, ''));
      const nb = parseFloat(String(b).replace(/[$,%x\s]/g, ''));
      if (!isNaN(na) && !isNaN(nb) && na !== nb) return (na - nb) * sign;
      return String(a).localeCompare(String(b)) * sign;
    });
    page = 0;
    draw();
  }

  function detailRow(row) {
    const tr = el('tr', 'detail');
    const td = el('td');
    td.colSpan = columns.length;
    const grid = el('div', 'grid');
    const all = columns.concat(hidden);
    all.forEach((name, index) => {
      const raw = row[index] === undefined ? '' : row[index];
      const shown = fmt(raw, name, formats[name]);
      const cell = el('div');
      cell.appendChild(el('div', 'k', friendlyColumn(name)));
      if (friendlyColumn(name) !== name) cell.appendChild(el('code', 'field', name));
      // The full value rides along only where rounding hid some of it.
      const scale = formats[name] === 'pct' ? 100 : 1;
      const shownNumber = Number(shown.replace(/[,%x]/g, '')) / scale;
      const lost = PLAIN_NUMBER.test(String(raw).trim()) && Math.abs(shownNumber - Number(raw)) > 1e-9;
      const value = el('div', 'v');
      if (REPO_PATH.test(String(raw).trim())) {
        // A repository path opens as a link, relative to this page at the
        // repository root, so a reviewer reaches the PDF, the page text, or
        // the extraction file behind a value in one click.
        const link = el('a', null, String(raw).trim());
        link.href = String(raw).trim();
        link.target = '_blank';
        link.rel = 'noopener';
        value.appendChild(link);
      } else {
        value.textContent = shown === '' ? '(blank)' : shown + (lost ? '  (' + raw + ')' : '');
      }
      cell.appendChild(value);
      if (definitions[index]) cell.appendChild(el('div', 'd', definitions[index]));
      grid.appendChild(cell);
    });
    td.appendChild(grid);
    tr.appendChild(td);
    return tr;
  }

  function draw() {
    const needle = search.value.trim().toLowerCase();
    const view = needle ? rows.filter((row) => matches(row, needle)) : rows;
    const pages = Math.max(1, Math.ceil(view.length / size));
    if (page >= pages) page = pages - 1;
    const start = page * size;
    const slice = view.slice(start, start + size);
    tbody.textContent = '';
    for (const row of slice) {
      const tr = el('tr', 'row');
      columns.forEach((name, index) => {
        const raw = row[index] === undefined ? '' : row[index];
        const shown = fmt(raw, name, formats[name]);
        const classes = [
          statusClass(raw),
          isNumeric(raw, name, formats[name]) ? 'num' : '',
          fieldClass(name),
        ].filter(Boolean).join(' ');
        const td = el('td', classes || null);
        if (REPO_PATH.test(String(raw).trim())) {
          const link = el('a', null, shown);
          link.href = String(raw).trim();
          link.target = '_blank';
          link.rel = 'noopener';
          td.appendChild(link);
        } else {
          td.textContent = shown;
        }
        td.title = String(raw);
        tr.appendChild(td);
      });
      let open = null;
      tr.addEventListener('click', () => {
        if (open) { open.remove(); open = null; return; }
        open = detailRow(row);
        tr.after(open);
      });
      tbody.appendChild(tr);
    }
    const withheld = rows.length < total ? ' of ' + total.toLocaleString() + ' ' + held : '';
    count.textContent = plural(view.length, 'row') + (needle ? ' matched' : '') + withheld;
    place.textContent = view.length
      ? 'Showing ' + (start + 1).toLocaleString() + ' to ' + Math.min(start + size, view.length).toLocaleString()
      : 'Matching rows: 0';
    back.disabled = page === 0;
    next.disabled = start + size >= view.length;
  }

  search.addEventListener('input', () => { page = 0; draw(); });
  back.addEventListener('click', () => { page -= 1; draw(); });
  next.addEventListener('click', () => { page += 1; draw(); });

  function set(spec) {
    columns = spec.columns;
    hidden = spec.hidden || [];
    definitions = spec.definitions || [];
    formats = spec.formats || {};
    headRow.textContent = '';
    columns.forEach((name, index) => {
      const th = el('th', formats[name] && formats[name] !== 'raw' ? 'num' : null);
      th.appendChild(el('span', 'lbl', friendlyColumn(name)));
      if (spec.types && spec.types[index]) th.appendChild(el('span', 'type', spec.types[index]));
      th.title = name + (definitions[index] ? ': ' + definitions[index] : '');
      th.addEventListener('click', () => sortBy(index, th));
      headRow.appendChild(th);
    });
    defList.textContent = '';
    columns.concat(hidden).forEach((name, index) => {
      const item = el('div');
      item.appendChild(el('code', null, name));
      item.appendChild(el('span', null, definitions[index] || ''));
      defList.appendChild(item);
    });
    defs.open = false;
    rows = spec.rows.slice();
    total = spec.total === undefined ? spec.rows.length : spec.total;
    page = 0;
    sortIndex = -1;
    ascending = true;
    search.value = '';
    draw();
  }

  return { node, set };
}

function renderTable(block) {
  const panel = el('div', 'panel');
  panel.appendChild(panelHeader(block));
  const grid = dataGrid({ page: block.page });
  panel.appendChild(grid.node);
  grid.set({
    columns: block.columns,
    hidden: block.hidden,
    definitions: block.definitions,
    formats: block.formats,
    rows: block.rows,
    total: block.rows_total,
  });
  return panel;
}

const EXPLORER_LONG_FIELD = /(sha|hash|path|quote|notes?|reason|description|formula|command|anchor|lineage|record_ids|row_ids|fields)/i;
const EXPLORER_PRIORITY = [
  /^(fund_name|manager_name|entity_name|document_id|source_document_id)$/i,
  /^(fund_id|fund_period_id|observation_id)$/i,
  /(^|_)date$/i,
  /^(metric_id|metric_name|metric_category)$/i,
  /^(value|value_raw|value_numeric|amount|status|provenance_type)$/i,
  /^(strategy|sub_strategy|currency|unit)$/i,
];

function compactExplorerEntry(entry) {
  const limit = 8;
  const all = entry.columns.map((_, index) => index);
  const visible = [];
  const add = (index) => {
    if (visible.length < limit && !visible.includes(index)) visible.push(index);
  };
  if (entry.columns.length <= limit) {
    all.forEach(add);
  } else {
    for (const pattern of EXPLORER_PRIORITY) {
      entry.columns.forEach((name, index) => { if (pattern.test(name)) add(index); });
    }
    entry.columns.forEach((name, index) => { if (!EXPLORER_LONG_FIELD.test(name)) add(index); });
    all.forEach(add);
  }
  visible.sort((left, right) => left - right);
  const hidden = all.filter((index) => !visible.includes(index));
  const order = visible.concat(hidden);
  return {
    columns: visible.map((index) => entry.columns[index]),
    hidden: hidden.map((index) => entry.columns[index]),
    definitions: order.map((index) => entry.definitions[index]),
    types: visible.map((index) => entry.types[index]),
    formats: entry.formats,
    rows: entry.preview.map((row) => order.map((index) => row[index])),
    total: entry.rows,
  };
}

function renderExplorer(block) {
  const panel = el('div', 'panel');
  panel.appendChild(panelHeader(block));

  const pills = el('div', 'pills');
  panel.appendChild(pills);
  const body = el('div', 'explorer');
  const list = el('div', 'tablelist');
  const right = el('div', 'gridside');
  const caption = el('div', 'caption');
  const shape = el('div', 'shape');
  const what = el('div', 'what');
  caption.appendChild(shape);
  caption.appendChild(what);
  right.appendChild(caption);
  const grid = dataGrid({ page: 25, heldIn: 'in the table' });
  right.appendChild(grid.node);
  body.appendChild(list);
  body.appendChild(right);
  panel.appendChild(body);

  let group = block.groups[0];

  function showTable(entry, button) {
    for (const other of list.children) other.classList.toggle('on', other === button);
    const preview = compactExplorerEntry(entry);
    shape.textContent =
      entry.name + ': ' + entry.kind + ', ' +
      plural(entry.columns.length, 'column') + ', ' +
      plural(entry.rows, 'row') +
      (entry.preview.length < entry.rows
        ? ', previewing ' + entry.preview.length.toLocaleString() + ' in sorted order'
        : '') + '.';
    what.textContent = (entry.about || '') + ' The grid presents ' + preview.columns.length.toLocaleString() +
      ' primary columns; the row detail retains all ' + entry.columns.length.toLocaleString() + ' fields.';
    grid.set(preview);
  }

  function showGroup(next) {
    group = next;
    for (const pill of pills.children) pill.classList.toggle('on', pill.dataset.name === group.name);
    list.textContent = '';
    group.tables.forEach((entry, index) => {
      const button = el('button', entry.kind === 'view' ? 'view' : null);
      button.appendChild(el('span', 'n', entry.name));
      button.appendChild(el('span', 'c', entry.rows.toLocaleString()));
      button.title = entry.about || '';
      button.addEventListener('click', () => showTable(entry, button));
      list.appendChild(button);
      if (index === 0) showTable(entry, button);
    });
  }

  for (const entry of block.groups) {
    const pill = el('button', 'pill', entry.name);
    pill.dataset.name = entry.name;
    pill.title = entry.note || '';
    pill.addEventListener('click', () => showGroup(entry));
    pills.appendChild(pill);
  }
  showGroup(group);
  return panel;
}

const RENDERERS = {
  kpi: renderKpi,
  note: renderNote,
  steps: renderSteps,
  keyvalue: renderKeyvalue,
  bars: renderBars,
  boxes: renderBoxes,
  donuts: renderDonuts,
  stacks: renderStacks,
  formulas: renderFormulas,
  table: renderTable,
  explorer: renderExplorer,
};

function build() {
  nav.appendChild(el('h1', null, DATA.title));
  nav.appendChild(el('p', 'sub', DATA.subtitle));
  DATA.sections.forEach((section, index) => {
    const link = el('a');
    link.href = '#' + section.id;
    link.dataset.id = section.id;
    link.appendChild(el('span', 'n', String(index + 1).padStart(2, '0')));
    link.appendChild(el('span', null, section.title));
    nav.appendChild(link);

    const node = el('section');
    node.id = section.id;
    node.appendChild(el('div', 'eyebrow', 'Section ' + (index + 1) + ' of ' + DATA.sections.length));
    node.appendChild(el('h2', null, section.title));
    node.appendChild(el('p', 'blurb', section.blurb));
    for (const block of section.blocks) {
      if (block.kind === 'heading') {
        node.appendChild(el('h3', null, block.text));
        continue;
      }
      const renderer = RENDERERS[block.kind];
      if (renderer) node.appendChild(renderer(block));
    }
    main.appendChild(node);
  });
  if (DATA.footer) nav.appendChild(el('p', 'foot', DATA.footer));
}

function show(id) {
  const known = DATA.sections.some((section) => section.id === id);
  const target = known ? id : DATA.sections[0].id;
  for (const section of main.children) section.classList.toggle('on', section.id === target);
  for (const link of nav.querySelectorAll('a')) link.classList.toggle('on', link.dataset.id === target);
  window.scrollTo(0, 0);
}

build();
window.addEventListener('hashchange', () => show(location.hash.slice(1)));
show(location.hash.slice(1));
"""


def render(payload: dict) -> str:
    """Return the whole page with the payload inlined."""

    body = json.dumps(payload, ensure_ascii=False, sort_keys=False)
    body = body.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{payload['title']}</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n"
        '<aside id="nav"></aside>\n<main id="main"></main>\n'
        f'<script id="payload" type="application/json">{body}</script>\n'
        f"<script>{SCRIPT}</script>\n</body>\n</html>\n"
    )
