"""The dashboard shell: style, browser code, and the HTML wrapper.

The page holds its data inline and loads nothing over the network, so a
reviewer opens the file from disk and reads every panel offline. The block
kinds rendered here are the ones `build_dashboard` emits: kpi, note, heading,
steps, keyvalue, figure, bars, formulas, table, explorer, guide, and terms.

Numbers are shown to two decimals at most. Every table carries a row
description, every column carries a definition in the column guide, and the
row detail retains every field omitted from the compact grid.
"""

from __future__ import annotations

import json


STYLE = r"""
:root {
  --ink: #173344;
  --ink-soft: #214b60;
  --ink-faint: #3d5663;
  --line: #d3e0e4;
  --line-strong: #b8cbd2;
  --rule: #b8cbd2;
  --page: #f1f5f6;
  --paper: #ffffff;
  --panel: #edf7f7;
  --accent: #087e83;
  --accent-2: #06696d;
  --accent-soft: #edf7f7;
  --nav: #173344;
  --nav-soft: #9ad4d5;
  --nav-hover: #214b60;
  --gold: #c4a035;
  --gold-deep: #8b4513;
  --good: #0a6e56;
  --good-soft: #e5f3ee;
  --warn: #8b4513;
  --warn-soft: #fff9e9;
  --stop: #9d2020;
  --stop-soft: #fff0f0;
  --shadow: 0 10px 28px rgba(23, 51, 68, .07);
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
a { color: #06696d; font-weight: 650; }
a:hover { color: #034e52; }
a:focus-visible, button:focus-visible, input:focus-visible, summary:focus-visible {
  outline: 3px solid #8fd1d3;
  outline-offset: 2px;
}

#nav {
  position: sticky;
  top: 0;
  z-index: 40;
  flex: 0 0 360px;
  height: 100vh;
  overflow-y: auto;
  border-right: 1px solid #0f2430;
  background: var(--nav);
  color: #ffffff;
  padding: 22px 0 40px;
  box-shadow: inset 0 3px 0 var(--accent);
}
#nav h1 { font-size: 16px; margin: 0 22px 6px; line-height: 1.3; font-weight: 750; }
#nav .sub { margin: 0 22px 22px; font-size: 12px; color: var(--nav-soft); line-height: 1.45; }
#nav a {
  display: flex; gap: 12px; align-items: baseline;
  padding: 9px 22px;
  font-size: 15px;
  font-weight: 400;
  color: #e5eef1;
  text-decoration: none;
  border-left: 3px solid transparent;
}
#nav a .n { font-family: var(--mono); font-size: 11.5px; color: var(--nav-soft); min-width: 22px; font-weight: 400; }
#nav a:hover { background: var(--nav-hover); color: #ffffff; }
#nav a.on { border-left-color: #9ad4d5; background: var(--nav-hover); font-weight: 400; color: #ffffff; }
#nav .foot { margin: 22px 22px 0; font-size: 11.5px; color: var(--nav-soft); line-height: 1.5; }
#nav .help-btn {
  display: block;
  margin: 0 22px 18px;
  width: calc(100% - 44px);
  padding: 9px 12px;
  background: var(--accent);
  color: #ffffff;
  border: 0;
  border-radius: 8px;
  cursor: pointer;
  font: inherit;
  font-size: 13.5px;
  font-weight: 700;
}
#nav .help-btn:hover { background: #0a9298; }
#nav a.featured {
  margin: 6px 14px 10px;
  padding: 11px 14px;
  border-left: 0;
  border-radius: 9px;
  background: var(--accent);
  color: #ffffff;
  box-shadow: 0 6px 16px rgba(0, 0, 0, .22);
}
#nav a.featured .n { color: #ffffff; }
#nav a.featured:hover { background: #0a9298; }
#nav a.featured.on { background: #0a9298; box-shadow: inset 0 0 0 2px #9ad4d5, 0 6px 16px rgba(0, 0, 0, .22); }
.report-open {
  display: inline-block;
  margin: 2px 0 14px;
  padding: 10px 16px;
  border-radius: 8px;
  background: var(--accent);
  color: #ffffff;
  text-decoration: none;
  font-weight: 750;
}
.report-open:hover { background: #0a9298; color: #ffffff; }
.report-frame {
  display: block;
  width: 100%;
  height: 86vh;
  min-height: 720px;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  background: #ffffff;
}
main:has(section.fill-embed.on) {
  padding: 0;
  max-width: none;
}
section.fill-embed.on {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}
.report-frame-fill {
  flex: 1 1 auto;
  width: 100%;
  height: 100vh;
  min-height: 100vh;
  border: 0;
  border-radius: 0;
}

#page-guide { display: none; padding: 0 0 56px; }
#page-guide.on { display: block; }
.help-card {
  width: min(1280px, 100%);
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  border-radius: 9px;
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
}
.help-card header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding: 16px 22px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
  border-radius: 9px 9px 0 0;
}
.help-card header h2 { margin: 0; font-size: 22px; letter-spacing: -.02em; }
.help-card header button {
  font: inherit;
  font-size: 13px;
  padding: 5px 12px;
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 6px;
  cursor: pointer;
}
.help-body { padding: 12px 22px 24px; }
.help-body .intro { font-size: 15px; color: var(--ink-soft); max-width: none; }
.help-body h3 { font-size: 16px; margin: 22px 0 8px; }
.help-body p { margin: 0 0 10px; max-width: 92ch; }
.help-words {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 18px;
  margin-top: 8px;
}
.help-words div {
  border: 1px solid var(--rule);
  border-radius: 8px;
  padding: 8px 12px;
  background: var(--panel);
}
.help-words b { display: block; font-size: 13px; margin-bottom: 3px; }
.help-words span { font-size: 13.5px; color: var(--ink-soft); }

.guide {
  border: 1px solid var(--line);
  border-left: 5px solid var(--accent);
  border-radius: 9px;
  padding: 14px 18px 12px;
  margin: 0 0 22px;
  background: var(--accent-soft);
}
.guide.tone-warn { border-left-color: var(--warn); background: var(--warn-soft); }
.guide.tone-fact { border-left-color: var(--good); background: var(--good-soft); }
.guide h4 { margin: 0 0 6px; font-size: 16px; }
.guide .lead { margin: 0 0 10px; font-size: 13px; color: var(--accent); font-weight: 650; }
.guide p { margin: 0 0 10px; max-width: 88ch; color: var(--ink); }
.guide p:last-child { margin-bottom: 0; }
.guide dl {
  display: grid;
  grid-template-columns: minmax(120px, 220px) 1fr;
  gap: 6px 14px;
  margin: 12px 0 0;
  font-size: 13.5px;
}
.guide dt { font-weight: 650; color: var(--ink); }
.guide dd { margin: 0; color: var(--ink-soft); }

.terms {
  border: 1px solid var(--line);
  border-radius: 9px;
  margin: 0 0 22px;
  background: var(--paper);
  overflow: hidden;
}
.terms h4 {
  margin: 0;
  padding: 10px 16px;
  font-size: 13px;
  letter-spacing: .04em;
  text-transform: uppercase;
  background: var(--ink);
  color: #ffffff;
  border-bottom: 1px solid var(--accent);
}
.terms dl { margin: 0; }
.terms div {
  display: grid;
  grid-template-columns: minmax(140px, 240px) 1fr;
  gap: 8px 14px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--rule);
  font-size: 13.5px;
}
.terms div:last-child { border-bottom: 0; }
.terms dt { font-weight: 650; }
.terms dd { margin: 0; color: var(--ink-soft); }

main { flex: 1 1 auto; min-width: 0; padding: 40px 44px 90px; max-width: 1560px; }
section { display: none; }
section.on { display: block; }
.eyebrow { font-family: var(--mono); font-size: 11.5px; letter-spacing: .08em; text-transform: uppercase; color: var(--accent); margin: 0 0 6px; font-weight: 650; }
h2 { font-size: 30px; margin: 0 0 9px; letter-spacing: -.025em; line-height: 1.2; }
.blurb { color: var(--ink-soft); margin: 0 0 30px; max-width: 82ch; font-size: 16px; }
#overview .blurb { margin-bottom: 8px; }
.repo-line { max-width: 88ch; margin: 0 0 22px; font-size: 17.5px; line-height: 1.5; }
.repo-line strong { font-weight: 700; color: var(--ink); }
.repo-line a { font-weight: 650; text-decoration: underline; text-underline-offset: 3px; }
h3 { font-size: 18px; margin: 38px 0 12px; letter-spacing: -.012em; }
p.note { max-width: 88ch; margin: 0 0 16px; color: var(--ink); }

.figure-svg { margin: 0 0 22px; overflow-x: auto; }
.figure-svg svg { width: 100%; height: auto; background: var(--paper); border: 1px solid var(--line); border-radius: 8px; display: block; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 0 0 22px; }
.kpi { border: 1px solid var(--line); border-top: 4px solid var(--accent); border-radius: 9px; padding: 14px 16px 13px; background: var(--paper); box-shadow: var(--shadow); }
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
.steps.fold { counter-reset: none; }
.steps.fold li { counter-increment: none; }
.steps.fold li.stage-head {
  padding: 8px 10px 8px 28px;
  margin: 0 0 4px 13px;
  border-left: 0;
  border-radius: 6px;
}
.steps.fold li.stage-head:first-child { padding-top: 8px; }
.steps.fold li.stage-head:hover, .steps.fold li.stage-head:focus-within { background: var(--accent-soft); }
.steps.fold .stage-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  margin: 0;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  letter-spacing: inherit;
  text-transform: inherit;
  text-align: left;
  cursor: pointer;
}
.steps.fold .stage-toggle::before {
  content: "";
  width: 0;
  height: 0;
  border-top: 5px solid transparent;
  border-bottom: 5px solid transparent;
  border-left: 7px solid var(--accent);
  flex: 0 0 auto;
}
.steps.fold li.stage-head.open .stage-toggle::before {
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 7px solid var(--accent);
  border-bottom: 0;
}
.steps.fold > li:not(.stage-head) { display: none; }
.steps.fold > li.open-step { display: block; }
.steps.fold > li.open-step::before { content: attr(data-n); }

.kv { border: 1px solid var(--line); border-radius: 8px; overflow: hidden; margin: 0 0 22px; background: var(--paper); }
.kv div { display: flex; gap: 16px; padding: 8px 14px; border-bottom: 1px solid var(--rule); font-size: 14px; }
.kv div:last-child { border-bottom: 0; }
.kv dt { flex: 0 0 280px; color: var(--ink-soft); margin: 0; }
.kv dd { margin: 0; flex: 1 1 auto; }
.rag-console { padding: 16px; }
.rag-form { display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 12px 16px; }
.rag-field { display: grid; gap: 5px; font-size: 12.5px; color: var(--ink-soft); }
.rag-field.wide { grid-column: 1 / -1; }
.rag-field input, .rag-field select, .rag-field textarea {
  width: 100%; box-sizing: border-box; border: 1px solid #5ab1e8; border-radius: 6px;
  padding: 8px 10px; background: #fff; color: var(--ink); font: inherit;
}
.rag-field textarea { min-height: 70px; resize: vertical; }
.rag-options { grid-column: 1 / -1; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
.rag-options label { font-size: 13px; color: var(--ink); }
.rag-run { padding: 8px 14px !important; border-color: var(--accent) !important; color: var(--accent); font-weight: 700; }
.rag-output { margin-top: 16px; border-top: 1px solid var(--rule); padding-top: 14px; }
.rag-state { font-weight: 700; margin-bottom: 10px; color: var(--ink); }
.rag-error { color: var(--warn); }
.rag-result { border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 6px; padding: 11px 13px; margin: 9px 0; background: var(--panel); }
.rag-result-head { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font: 650 12px var(--mono); color: var(--ink-soft); }
.rag-result p { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.rag-context { margin: 8px 0 0 18px; color: var(--ink-soft); font-size: 12.5px; }
.rag-source { margin-left: auto; padding: 3px 8px !important; }
.rag-json { max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.45 var(--mono); background: var(--panel); padding: 10px; border-radius: 6px; }

.panel { border: 1px solid var(--line); border-radius: 9px; margin: 0 0 26px; overflow: hidden; background: var(--paper); box-shadow: var(--shadow); }
.panel > header { padding: 14px 17px 13px; border-bottom: 1px solid var(--line); border-left: 4px solid var(--accent); background: var(--panel); }
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
.panel input[type=search] { flex: 1 1 auto; font: inherit; font-size: 13px; padding: 7px 10px; border: 1px solid var(--line-strong); border-radius: 6px; min-width: 120px; background: #fff; color: var(--ink); }
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
  background: var(--ink); border-bottom: 1px solid var(--accent);
  font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: #ffffff;
  cursor: pointer; white-space: nowrap;
}
th .type { display: block; font-weight: 400; text-transform: none; letter-spacing: 0; font-size: 10.5px; color: #9ad4d5; }
th.up .lbl::after { content: " \2191"; }
th.down .lbl::after { content: " \2193"; }
td { max-width: 38ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-variant-numeric: tabular-nums; }
td.technical { max-width: 24ch; font-family: var(--mono); font-size: 12px; }
td.narrative { max-width: 34ch; }
.release-audit table { table-layout: fixed; min-width: 860px; }
.release-audit th, .release-audit td { white-space: normal; overflow-wrap: break-word; max-width: none; }
.release-audit th:nth-child(1) { width: 6%; }
.release-audit th:nth-child(2) { width: 12%; }
.release-audit th:nth-child(3) { width: 18%; }
.release-audit th:nth-child(4) { width: 24%; }
.release-audit th:nth-child(5) { width: 32%; }
.release-audit th:nth-child(6) { width: 8%; }
.release-audit tr.row { cursor: pointer; }
.release-audit tr.row:focus-visible { outline: 3px solid var(--gold); outline-offset: -3px; }
.release-audit tr.row[aria-expanded="true"] > td { background: var(--accent-soft); font-weight: 600; }
.release-audit .scroll:has(tr.release-detail) { max-height: none; overflow-y: visible; }
.release-audit .scroll:has(tr.release-detail) thead th { position: static; }
tr.release-detail > td { white-space: normal; max-width: none; background: var(--accent-soft);
  padding: 20px 26px 24px; border-left: 4px solid var(--accent); }
.release-explain { max-width: 104ch; }
.release-explain .release-step { font-size: 13px; color: var(--ink-soft); font-weight: 650; }
.release-explain h4 { margin: 4px 0 3px; font-size: 21px; line-height: 1.25; letter-spacing: -.02em; }
.release-explain .release-code { margin: 0 0 13px; font: 12px/1.5 var(--mono); color: var(--ink-soft);
  overflow-wrap: anywhere; }
.release-explain .release-reader { font-size: 13px; color: var(--ink-soft); margin: 0 0 11px; }
.release-explain p { margin: 0 0 14px; }
.release-explain h3 { font-size: 16px; margin: 20px 0 6px; }
.release-explain .release-position { background: var(--panel); border: 1px solid var(--rule);
  border-left: 4px solid var(--accent); padding: 13px 17px; margin: 0 0 16px; }
.release-position dl { margin: 0; display: grid; grid-template-columns: 68px minmax(0, 1fr); gap: 8px 14px; }
.release-position dt { font-weight: 650; }
.release-position dd { margin: 0; }
.release-example { background: var(--warn-soft); border-left: 3px solid var(--gold-deep); padding: 13px 17px; }
.release-status-note { font-size: 14px; border-top: 1px solid var(--rule); padding-top: 14px;
  margin-top: 20px !important; }
.release-files { margin-top: 18px; border-top: 1px solid var(--rule); padding-top: 13px; }
.release-files summary { cursor: pointer; color: var(--ink-soft); font-weight: 650; }
.release-files dl { margin: 14px 0; }
.release-files dt { font-size: 14px; font-weight: 650; margin-top: 15px; }
.release-files dd { margin: 4px 0; font-size: 14px; overflow-wrap: anywhere; }
.release-files a { text-decoration: underline; text-underline-offset: 2px; }
.release-files code { font-size: 12px; white-space: normal; overflow-wrap: anywhere; }
#release-work { margin-bottom: 18px; }
#release-work .steps span { max-width: 100ch; }
@media (max-width: 720px) {
  tr.release-detail > td { padding: 15px 14px 18px; }
  .release-explain h4 { font-size: 19px; }
}
td.num { text-align: right; }
th.num { text-align: right; }
tbody tr:nth-child(4n+3) td { background: #f7fafa; }
tbody tr.row:hover td { background: var(--accent-soft); cursor: pointer; }
tr.detail td { white-space: normal; max-width: none; overflow: visible; background: var(--accent-soft); padding: 14px 18px 16px; }
/* Row detail: one field per line. Name and column name on the left, value and
   meaning on the right, so every field lines up with the one above it. */
.detail .grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(520px, 1fr)); gap: 0 32px;
  background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 2px 18px; overflow: hidden;
  position: sticky; left: 18px;
}
.detail .grid > div {
  display: grid; grid-template-columns: minmax(150px, 30%) minmax(0, 1fr); column-gap: 18px; row-gap: 2px;
  align-items: start; align-content: start; padding: 10px 0; margin-bottom: -1px; border-bottom: 1px solid var(--line);
}
.detail .grid .kk { grid-column: 1; grid-row: 1 / span 2; min-width: 0; }
.detail .grid .k { font-size: 13px; font-weight: 650; color: var(--ink); line-height: 1.35; }
.detail .grid code.field { display: block; margin-top: 3px; font-size: 11.5px; color: var(--ink-faint); background: transparent; padding: 0; overflow-wrap: anywhere; }
.detail .grid .v { grid-column: 2; grid-row: 1; font-size: 13.5px; color: var(--ink); line-height: 1.4; overflow-wrap: anywhere; }
.detail .grid .v.blank { color: var(--ink-faint); font-style: italic; }
.detail .grid .d { grid-column: 2; grid-row: 2; font-size: 12px; color: var(--ink-faint); line-height: 1.45; }
@media (max-width: 560px) {
  .detail .grid { grid-template-columns: minmax(0, 1fr); padding: 2px 12px; }
  .detail .grid > div { grid-template-columns: minmax(0, 1fr); }
  .detail .grid .kk, .detail .grid .v, .detail .grid .d { grid-column: 1; grid-row: auto; }
}
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

.formulas { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 16px; margin: 0 0 24px; min-width: 0; }
.formula { border: 1px solid var(--line); border-radius: 8px; background: var(--paper); box-shadow: 0 1px 2px rgba(23,26,33,.04); display: flex; flex-direction: column; min-width: 0; overflow-wrap: anywhere; }
.formula header { padding: 14px 18px 10px; }
.formula h4 { margin: 0; font-size: 17px; }
.formula .plain { margin: 4px 0 0; font-size: 13.5px; color: var(--ink-soft); line-height: 1.5; }
.formula .math { padding: 14px 18px; background: var(--panel); border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); font-size: 15px; overflow-x: auto; }
.formula .math .eq { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.formula .math .eq > * { white-space: nowrap; flex-shrink: 0; }
.frac { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin: 0 4px; }
.frac > span { padding: 1px 8px; }
.frac > span:first-child { border-bottom: 1.5px solid var(--ink); }
.formula .math i { font-style: italic; color: var(--accent); }
.formula .math .sum { font-size: 20px; }
.formula .example { padding: 12px 18px 6px; min-width: 0; overflow-x: auto; }
.formula .example h5 { margin: 0 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-soft); }
.formula .example table { font-size: 13px; }
.formula .example th { position: static; }
.formula .example td, .formula .example th { padding: 4px 8px; }
.formula .example tr:last-child td { border-bottom: 0; }
.formula .example .result td { font-weight: 650; border-top: 1.5px solid var(--line); }
.formula footer { padding: 10px 18px 14px; margin-top: auto; font-size: 12px; color: var(--ink-soft); display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 3px 10px; }
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
.boxtrack .zero { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--rule); }
.boxtrack .whisk { position: absolute; top: 50%; height: 1px; background: var(--ink); }
.boxtrack .cap { position: absolute; top: calc(50% - 5px); width: 1px; height: 11px; background: var(--ink); }
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
.caption { padding: 14px 16px 2px; font-size: 13.5px; border-bottom: 1px solid var(--rule); background: var(--accent-soft); }
.caption .shape { font-weight: 650; color: var(--ink); }
.caption .what { color: var(--ink-soft); margin-top: 3px; line-height: 1.5; }

.warehouse-dbs-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
  margin: 0 16px 8px;
}
.warehouse-db-summary-card {
  background: var(--accent-soft);
  border: 1px solid var(--line);
  border-left: 4px solid var(--accent);
  border-radius: 8px;
  padding: 14px 16px;
}
.warehouse-db-summary-card .head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.warehouse-db-summary-card .db-name {
  font-family: var(--mono);
  font-weight: 700;
  font-size: 14px;
  color: var(--accent-2);
}
.warehouse-db-summary-card .desc {
  margin: 0 0 8px;
  font-size: 13.5px;
  line-height: 1.5;
}
.warehouse-db-summary-card .meta {
  font-size: 12px;
  color: var(--ink-soft);
  font-weight: 650;
}

/* Warehouse Index and Everything in one list */
.warehouse-db-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
  margin: 14px 0 20px;
}
.warehouse-db-card {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px 16px;
  box-shadow: var(--shadow);
}
.warehouse-db-card .db-title {
  font-family: var(--mono);
  font-weight: 700;
  font-size: 14px;
  color: var(--accent);
  margin-bottom: 6px;
}
.warehouse-db-card .db-purpose {
  font-size: 13px;
  color: var(--ink);
  line-height: 1.5;
  margin: 0;
}
.warehouse-search-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.warehouse-search-input {
  flex: 0 0 340px;
  max-width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--paper);
  color: var(--ink);
  font: inherit;
  font-size: 13.5px;
}
.warehouse-search-count {
  font-size: 13px;
  color: var(--ink-soft);
  font-weight: 600;
}
.warehouse-index-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.warehouse-index-table th {
  background: var(--panel);
  color: var(--ink-soft);
  font-weight: 650;
  padding: 10px 12px;
  text-align: left;
  border-bottom: 2px solid var(--line);
  user-select: none;
  cursor: pointer;
  white-space: nowrap;
}
.warehouse-index-table th:hover {
  background: var(--rule);
}
.warehouse-index-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}
.warehouse-index-table td.contents {
  white-space: pre-line;
  min-width: 440px;
  max-width: 820px;
  line-height: 1.55;
  font-size: 13.5px;
}
.warehouse-index-table td.contents strong {
  color: var(--ink-soft);
  font-weight: 650;
}
.table-jump-btn {
  background: none;
  border: none;
  padding: 0;
  color: var(--accent);
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 650;
  text-align: left;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.table-jump-btn:hover {
  color: var(--ink-soft);
}
.pill.db-pill {
  background: var(--panel);
  color: var(--ink-soft);
  font-family: var(--mono);
}
.pill.view-pill {
  background: var(--warn-soft);
  color: var(--warn);
  font-style: italic;
}
.pill.table-pill {
  background: var(--accent-soft);
  color: var(--accent-2);
}

/* Dedicated Table View in Explorer */
.table-detail-card {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px 20px;
  margin: 14px 16px 14px;
  box-shadow: var(--shadow);
}
.table-detail-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.table-detail-head h3 {
  margin: 0;
  font-size: 20px;
  font-family: var(--mono);
  color: var(--ink);
}
.table-detail-meta {
  font-size: 12.5px;
  color: var(--ink-soft);
  margin-bottom: 14px;
}
.explanation-card {
  display: block;
  background: var(--panel);
  border-left: 4px solid var(--accent);
  border-radius: 0 6px 6px 0;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.explanation-card .plain-title {
  font-weight: 700;
  font-size: 15px;
  color: var(--ink);
  margin-bottom: 6px;
}
.explanation-card .plain-contents {
  font-size: 14px;
  color: var(--ink);
  line-height: 1.55;
  margin: 0 0 10px;
}
.explanation-card .plain-sub {
  font-size: 13.5px;
  line-height: 1.55;
  margin-top: 8px;
  padding: 8px 10px;
  background: var(--paper);
  border-radius: 4px;
  border: 1px solid var(--line);
}
.explanation-card .plain-sub strong {
  color: var(--ink-soft);
}
.warnbox {
  background: var(--warn-soft);
  color: var(--warn);
  border: 1px solid var(--gold);
  border-left: 4px solid var(--gold);
  padding: 10px 14px;
  border-radius: 4px;
  font-size: 13px;
  margin-bottom: 14px;
}
.explorer-accordions {
  margin: 0 16px 16px;
}
.explorer-details {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 6px;
  margin-bottom: 10px;
  overflow: hidden;
}
.explorer-details summary {
  padding: 10px 14px;
  font-weight: 650;
  font-size: 13.5px;
  cursor: pointer;
  background: var(--panel);
  user-select: none;
}
.explorer-details summary:hover {
  background: var(--rule);
}
.explorer-details-body {
  padding: 14px;
  border-top: 1px solid var(--line);
}
.derivation-chain {
  list-style: none;
  padding: 0;
  margin: 0;
}
.derivation-chain li {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
}
.derivation-chain li:last-child {
  border-bottom: none;
}
.derivation-chain .d-label {
  color: var(--ink-soft);
  font-weight: 600;
}
.derivation-chain .d-value code {
  font-family: var(--mono);
  background: var(--panel);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.derivation-chain .d-note {
  font-size: 12px;
  color: var(--ink-soft);
  margin-top: 3px;
}
pre.sql-box {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px 14px;
  font-family: var(--mono);
  font-size: 12.5px;
  line-height: 1.5;
  overflow-x: auto;
  margin: 0;
  white-space: pre-wrap;
}
.col-filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.col-filter-input {
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: 4px;
  font: inherit;
  font-size: 12.5px;
  width: 240px;
}
.col-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.col-table th {
  text-align: left;
  padding: 8px 10px;
  background: var(--panel);
  border-bottom: 2px solid var(--line);
  color: var(--ink-soft);
}
.col-table td {
  padding: 7px 10px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}
.col-table td.col-name {
  font-family: var(--mono);
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
}
.col-table td.col-type {
  font-family: var(--mono);
  color: var(--accent);
  white-space: nowrap;
}
.explorer-preview-head {
  padding: 0 16px 8px;
}
.explorer-preview-head h4 {
  margin: 0 0 4px;
  font-size: 15px;
  color: var(--ink);
}
.explorer-preview-head .hint {
  margin: 0;
}

@media (max-width: 900px) {
  body { display: block; }
  #nav { position: static; height: auto; width: 100%; flex: none; }
  #nav a { display: inline-flex; width: 49%; vertical-align: top; }
  #nav a.featured { margin: 0; border-radius: 0; box-shadow: none; }
  .help-words { grid-template-columns: 1fr; }
  main { padding: 22px 16px 60px; }
  .report-frame { height: 78vh; min-height: 540px; }
  .report-frame-fill { height: 100vh; min-height: 100vh; }
  .bar { grid-template-columns: 130px 1fr 80px; }
  .explorer { grid-template-columns: minmax(0, 1fr); }
  .tablelist { border-right: 0; border-bottom: 1px solid var(--line); max-height: 220px; }
  .formulas { grid-template-columns: 1fr; }
  .kv div { display: block; }
  .kv dt { margin-bottom: 3px; }
  .guide dl, .terms div { display: block; }
  .guide dt, .terms dt { margin-bottom: 2px; }
}
@media (max-width: 560px) {
  #nav a { width: 100%; }
  h2 { font-size: 26px; }
  .kpis { grid-template-columns: 1fr; }
  .bar { grid-template-columns: 100px 1fr 70px; gap: 8px; }
}
@media print {
  #nav { display: none; }
  #page-guide { display: none !important; }
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

function esc(s) {
  return String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function fmtContents(s) {
  return esc(s).replace(/^([^:\n]{1,40}):/gm, '<strong>$1:</strong>');
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
const REPO_PATH = /^(data|ledgers|instructions|docs|src|audit|config|sql|tests|GP-Scoring|RAG)\/[^\s]+\.[A-Za-z0-9]+$/;
// The Git LFS paths named in .gitattributes. GitHub Pages serves their pointer
// files, so the page on github.io links them to GitHub's LFS media host.
const LFS_PATH = /\.(pdf|duckdb|parquet|png)$|^data\/documents\/txt\/[^\/]+\.txt$|^data\/synthetic\/(clean|defects)\/(quality_results|fund_observations)\.csv$|^data\/synthetic\/analytics\/(pme_results|fund_metrics)\.csv$|^data\/public_markets\/staging\/benchmark_(level|return)_candidates\.csv$/;
const LFS_MEDIA = 'https://media.githubusercontent.com/media/MosesRahnama/Alts-ETL-Analytics-Project/main/';
function downloadHref(path) {
  const value = String(path).trim();
  if (DATA.downloads) return DATA.downloads[value] || '';
  if (!REPO_PATH.test(value)) return '';
  return location.hostname.endsWith('github.io') && LFS_PATH.test(value) ? LFS_MEDIA + value : value;
}

function downloadLabel(path, label) {
  return downloadHref(path).endsWith('.zip') ? label + ' (ZIP)' : label;
}
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
const PALETTE = ['#087e83', '#173344', '#214b60', '#06696d', '#0a6e56', '#8b4513', '#9d2020', '#3d7a7d',
                 '#4a6b75', '#c4a035'];
const NAMED = {
  EXTRACTED: '#087e83', DERIVED: '#3d7a7d', IMPUTED: '#c4a035', SYNTHETIC: '#8b4513',
  PASS: '#0a6e56', FAIL: '#9d2020', SKIP: '#c4a035', WARNING: '#8b4513',
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
  const darkLuminance = 0.029671664617693577; // #173344
  const darkContrast = (luminance + 0.05) / (darkLuminance + 0.05);
  return whiteContrast >= darkContrast ? '#fff' : '#173344';
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

function renderGuide(block) {
  const node = el('aside', 'guide tone-' + (block.tone || 'teach'));
  node.setAttribute('aria-label', block.title || 'Guide');
  node.appendChild(el('h4', null, block.title));
  if (block.lead) node.appendChild(el('p', 'lead', block.lead));
  for (const paragraph of (block.paragraphs || [])) {
    node.appendChild(el('p', null, paragraph));
  }
  if (block.items && block.items.length) {
    const list = el('dl');
    for (const item of block.items) {
      list.appendChild(el('dt', null, item[0]));
      list.appendChild(el('dd', null, item[1]));
    }
    node.appendChild(list);
  }
  return node;
}

function renderTerms(block) {
  const node = el('aside', 'terms');
  node.appendChild(el('h4', null, block.title || 'Words on this page'));
  const list = el('dl');
  for (const item of (block.items || [])) {
    const row = el('div');
    row.appendChild(el('dt', null, item[0]));
    row.appendChild(el('dd', null, item[1]));
    list.appendChild(row);
  }
  node.appendChild(list);
  return node;
}

function renderLink(block) {
  const p = el('p', 'repo-line');
  if (block.prefix) {
    p.appendChild(el('strong', null, block.prefix));
    p.appendChild(document.createTextNode(' '));
  }
  const a = el('a', null, block.label || block.href);
  a.href = block.href;
  a.target = '_blank';
  a.rel = 'noopener';
  p.appendChild(a);
  return p;
}

function renderSteps(block) {
  const list = el('ol', 'steps');
  if (block.fold) list.classList.add('fold');
  let stage = null;
  let n = 0;
  for (const item of block.items) {
    if (item.stage && item.stage !== stage) {
      stage = item.stage;
      const stageKey = 'stage-' + stage.toLowerCase().replace(/[^a-z0-9]+/g, '-');
      const head = el('li', 'stage-head');
      if (block.fold) {
        const button = el('button', 'stage-toggle', stage);
        button.type = 'button';
        button.setAttribute('aria-expanded', 'false');
        button.addEventListener('click', () => toggleStepStage(head, stageKey));
        head.appendChild(button);
      } else {
        head.textContent = stage;
      }
      list.appendChild(head);
    }
    const li = el('li');
    n += 1;
    if (block.fold) {
      li.dataset.stage = 'stage-' + stage.toLowerCase().replace(/[^a-z0-9]+/g, '-');
      li.dataset.n = String(n);
    }
    li.appendChild(el('b', null, item.title));
    li.appendChild(el('span', null, item.text));
    list.appendChild(li);
  }
  return list;
}

function toggleStepStage(head, stageKey) {
  const open = !head.classList.contains('open');
  head.classList.toggle('open', open);
  const button = head.querySelector('.stage-toggle');
  if (button) button.setAttribute('aria-expanded', open ? 'true' : 'false');
  for (const li of head.parentNode.children) {
    if (li.dataset.stage === stageKey) li.classList.toggle('open-step', open);
  }
}

function renderFigure(block) {
  const panel = el('div', 'panel');
  panel.appendChild(panelHeader(block));
  const wrap = el('div', 'figure-svg');
  wrap.setAttribute('role', 'img');
  if (block.title) wrap.setAttribute('aria-label', block.title);
  wrap.innerHTML = block.svg || '';
  panel.appendChild(wrap);
  return panel;
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

function renderRagConsole(block) {
  const panel = el('div', 'panel');
  panel.appendChild(panelHeader(block));
  const body = el('div', 'rag-console');
  const form = el('form', 'rag-form');
  const localService = window.location.protocol === 'http:'
    && ['localhost', [127, 0, 0, 1].join('.')].includes(window.location.hostname);

  function field(label, node, wide) {
    const wrap = el('label', 'rag-field' + (wide ? ' wide' : ''));
    wrap.appendChild(el('span', null, label));
    wrap.appendChild(node);
    form.appendChild(wrap);
    return node;
  }

  const session = field('Reviewer session ID', document.createElement('input'));
  session.autocomplete = 'off';
  session.spellcheck = false;
  session.placeholder = 'Created by alts_rag issue-session';

  const operation = document.createElement('select');
  for (const [value, label] of [
    ['search_sources', 'Search report evidence'],
    ['verify_claim', 'Check recorded fields'],
    ['context_review', 'Find missing context'],
    ['explain_analytics', 'Read analytical records'],
  ]) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    operation.appendChild(option);
  }
  field('Operation', operation);

  const files = field('Document IDs', document.createElement('input'));
  files.placeholder = 'SRC421, SRC606';
  files.spellcheck = false;

  const dataGroup = document.createElement('select');
  for (const value of ['extracted', 'integrated']) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    dataGroup.appendChild(option);
  }
  field('Analytical data group', dataGroup);

  const query = field('Question, claim subject, or analytical query ID', document.createElement('textarea'), true);
  query.placeholder = 'What annual performance remained after fees since inception?';

  const fields = field('Claim fields or analytical parameters (JSON)', document.createElement('textarea'), true);
  fields.placeholder = '{"value":"9.43%","fee_basis":"net"}';
  fields.spellcheck = false;

  const options = el('div', 'rag-options');
  const hybridLabel = el('label');
  const hybrid = document.createElement('input');
  hybrid.type = 'checkbox';
  hybrid.checked = Boolean(block.hybrid_default);
  hybridLabel.appendChild(hybrid);
  hybridLabel.appendChild(document.createTextNode(' Combine keyword and local vector retrieval'));
  options.appendChild(hybridLabel);
  const run = el('button', 'rag-run', 'Run local review');
  run.type = 'submit';
  options.appendChild(run);
  form.appendChild(options);

  const output = el('div', 'rag-output');
  output.appendChild(el(
    'p',
    'rag-state',
    localService
      ? (block.idle_text || 'The local service runs only after a reviewer submits this form.')
      : 'Interactive review is available only from the loopback service on the project computer. The saved examples below remain available on this static page.',
  ));

  if (!localService) {
    for (const control of form.querySelectorAll('input, select, textarea, button')) control.disabled = true;
  }

  function parseObject(raw) {
    if (!raw.trim()) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('The JSON field must contain an object.');
    return parsed;
  }

  async function openDocument(blockId, page) {
    const response = await fetch('/document', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: session.value.trim(), block_id: blockId}),
    });
    if (!response.ok) throw new Error('The source PDF is unavailable for this session.');
    const blob = await response.blob();
    const href = URL.createObjectURL(blob) + (page ? '#page=' + page : '');
    window.open(href, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(href.split('#')[0]), 60000);
  }

  function showResponse(payload) {
    output.replaceChildren();
    const methods = (payload.methods_used || []).join(' + ');
    output.appendChild(el('div', 'rag-state', payload.execution_state + (methods ? ' · ' + methods : '')));
    for (const warning of (payload.warnings || [])) output.appendChild(el('p', 'rag-error', warning));
    for (const item of (payload.results || [])) {
      if (!item.original_text) continue;
      const card = el('article', 'rag-result');
      const head = el('div', 'rag-result-head');
      head.appendChild(el('span', null, [item.file_id, item.physical_page ? 'physical page ' + item.physical_page : '', item.block_kind].filter(Boolean).join(' · ')));
      if (item.block_id) {
        const source = el('button', 'rag-source', 'Open source PDF');
        source.type = 'button';
        source.addEventListener('click', () => openDocument(item.block_id, item.physical_page).catch(error => {
          output.prepend(el('p', 'rag-error', error.message));
        }));
        head.appendChild(source);
      }
      card.appendChild(head);
      card.appendChild(el('p', null, item.original_text));
      const context = (item.context || []).slice(0, 3);
      if (context.length) {
        const list = el('ul', 'rag-context');
        for (const related of context) list.appendChild(el('li', null, related.original_text || related.block_id));
        card.appendChild(list);
      }
      output.appendChild(card);
    }
    if (payload.assessments && payload.assessments.length) {
      const pre = el('pre', 'rag-json');
      pre.textContent = JSON.stringify(payload.assessments, null, 2);
      output.appendChild(pre);
    }
    if (!(payload.results || []).some(item => item.original_text) && !(payload.assessments || []).length) {
      const pre = el('pre', 'rag-json');
      pre.textContent = JSON.stringify(payload.results || payload, null, 2);
      output.appendChild(pre);
    }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!localService) return;
    run.disabled = true;
    output.replaceChildren(el('p', 'rag-state', 'Running local review…'));
    try {
      const fileIds = files.value.split(/[\s,|]+/).filter(Boolean);
      const values = parseObject(fields.value);
      const methods = hybrid.checked ? ['keyword', 'vector'] : ['keyword'];
      let endpoint = '/' + operation.value;
      let payload = {session_id: session.value.trim()};
      if (!payload.session_id) throw new Error('A reviewer session ID is required.');
      if (operation.value === 'search_sources') {
        payload = {...payload, query: query.value.trim(), file_ids: fileIds, retrieval_methods: methods};
      } else if (operation.value === 'verify_claim') {
        payload = {...payload, subject: query.value.trim(), field_values: values, file_ids: fileIds, retrieval_methods: methods};
      } else if (operation.value === 'context_review') {
        endpoint = '/verify_claim';
        if (fileIds.length !== 1) throw new Error('Context review requires one document ID.');
        payload = {...payload, subject: '', field_values: {}, file_ids: fileIds, context_review: true};
      } else {
        payload = {...payload, query_id: query.value.trim(), parameters: values, data_group: dataGroup.value};
      }
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const responseBody = await response.json();
      if (!response.ok) throw new Error(responseBody.error || responseBody.execution_state || 'Local request failed.');
      showResponse(responseBody);
    } catch (error) {
      output.replaceChildren(el('p', 'rag-error', error.message + ' The interactive controls require the local RAG server.'));
    } finally {
      run.disabled = false;
    }
  });

  body.appendChild(form);
  body.appendChild(output);
  panel.appendChild(body);
  return panel;
}

function panelHeader(block) {
  const head = el('header');
  head.appendChild(el('h4', null, block.title));
  if (block.about) head.appendChild(el('p', 'about', block.about));
  if (block.source) {
    const source = el('div', 'src', 'Source: ' + block.source);
    const href = downloadHref(block.source);
    if (href) {
      source.appendChild(document.createTextNode(' · '));
      const link = el('a', null, downloadLabel(block.source, 'Download source file'));
      link.href = href;
      link.target = '_blank';
      link.rel = 'noopener';
      source.appendChild(link);
    }
    head.appendChild(source);
  }
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
// re-points it at whatever table the checker selects.
function dataGrid(options) {
  const node = el('div');
  const defs = el('details');
  defs.appendChild(el('summary', null, 'Meanings of every column, including hidden fields'));
  const defList = el('div', 'defs');
  defs.appendChild(defList);
  node.appendChild(defs);

  const controls = el('div', 'bar-row');
  const search = document.createElement('input');
  search.type = 'search';
  search.placeholder = 'Search every field in the row';
  search.setAttribute('aria-label', 'Search every field in the row');
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
  node.appendChild(el('div', 'hint', 'Select a row to see every field and the page quote. Select a heading to sort. Rest on a heading to read its meaning. Open Meanings of every column for the one-line definition of each field.'));

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
      // The label and its column name stay together on the left, so a value
      // that wraps onto several lines cannot pull them apart.
      const head = el('div', 'kk');
      head.appendChild(el('div', 'k', friendlyColumn(name)));
      if (friendlyColumn(name) !== name) head.appendChild(el('code', 'field', name));
      cell.appendChild(head);
      // The full value rides along only where rounding hid some of it.
      const scale = formats[name] === 'pct' ? 100 : 1;
      const shownNumber = Number(shown.replace(/[,%x]/g, '')) / scale;
      const lost = PLAIN_NUMBER.test(String(raw).trim()) && Math.abs(shownNumber - Number(raw)) > 1e-9;
      const value = el('div', 'v');
      if (downloadHref(raw)) {
        // A repository path opens as a link, relative to this page at the
        // repository root, so a reviewer reaches the PDF, the page text, or
        // the extraction file behind a value in one click.
        const link = el('a', null, downloadLabel(raw, String(raw).trim()));
        link.href = downloadHref(raw);
        link.target = '_blank';
        link.rel = 'noopener';
        value.appendChild(link);
      } else {
        value.textContent = shown === '' ? '(blank)' : shown + (lost ? '  (' + raw + ')' : '');
        if (shown === '') value.classList.add('blank');
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
        if (downloadHref(raw)) {
          const link = el('a', null, downloadLabel(raw, shown));
          link.href = downloadHref(raw);
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
      if (options && options.onSelect) {
        tr.tabIndex = 0;
        tr.setAttribute('aria-expanded', 'false');
        tr.setAttribute('aria-label', 'Show the explanation of ' + (options.rowLabel ? options.rowLabel(row) : row[1]));
        tr.addEventListener('keydown', (event) => {
          if (event.target === tr && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            options.onSelect(row, tr);
          }
        });
      }
      tr.addEventListener('click', (event) => {
        if (options && options.onSelect) {
          if (!event.target.closest('a')) options.onSelect(row, tr);
          return;
        }
        if (open) { open.remove(); open = null; return; }
        open = detailRow(row);
        tr.after(open);
        // A wide table scrolls sideways, so the detail takes the visible width
        // of its box and stays in view while the table scrolls.
        const box = tr.closest('.scroll');
        const sheet = open.querySelector('.grid');
        if (box && sheet) sheet.style.width = Math.max(260, box.clientWidth - 38) + 'px';
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
  if (block.source.endsWith('docs/FINAL-RELEASE-AUDIT.csv')) panel.classList.add('release-audit');
  panel.appendChild(panelHeader(block));
  // A table that carries step explanations opens one under the selected row in
  // place of the field list every other table shows.
  const explained = Array.isArray(block.explanations);
  const grid = dataGrid({
    page: block.page,
    onSelect: explained ? (row, tr) => toggleReleaseDetail(block, row, tr) : null,
    rowLabel: explained ? row => row[block.columns.indexOf('stage')] : null,
  });
  if (explained) grid.node.querySelector('.hint').textContent = 'Select any row to open an explanation beneath it, covering its inputs, work, output, check, limits, worked example, and related files. Select it again to close.';
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

function renderWarehouseIndex(block) {
  const panel = el('div', 'panel');
  panel.id = 'warehouse-index-block';
  panel.appendChild(panelHeader(block));

  const dbsHeader = el('h3', null, 'Database contents');
  dbsHeader.style.margin = '16px 20px 12px';
  panel.appendChild(dbsHeader);

  const summaryGrid = el('div', 'warehouse-dbs-summary');
  (block.databases || []).forEach((db) => {
    const card = el('div', 'warehouse-db-summary-card');
    const titleRow = el('div', 'head');
    const nameSpan = el('span', 'db-name', db.name);
    const countBadge = el('span', 'pill db-pill', db.tables_count + ' tables, ' + db.views_count + ' views');
    titleRow.appendChild(nameSpan);
    titleRow.appendChild(countBadge);
    card.appendChild(titleRow);

    const desc = el('p', 'desc', db.summary);
    card.appendChild(desc);

    const meta = el('div', 'meta', db.total_rows.toLocaleString() + ' source & calculated records');
    card.appendChild(meta);
    summaryGrid.appendChild(card);
  });
  panel.appendChild(summaryGrid);

  const listHeader = el('h3', null, 'Everything, in one list');
  listHeader.style.margin = '24px 20px 8px';
  panel.appendChild(listHeader);

  const searchBar = el('div', 'warehouse-search-bar');
  const searchInput = el('input', 'warehouse-search-input');
  searchInput.type = 'search';
  searchInput.placeholder = 'Filter this index';
  searchInput.setAttribute('aria-label', 'Filter warehouse table index');
  searchBar.appendChild(searchInput);

  const searchCount = el('span', 'warehouse-search-count');
  searchBar.appendChild(searchCount);
  panel.appendChild(searchBar);

  const tableWrap = el('div', 'scroll');
  tableWrap.style.margin = '0 16px 20px';
  const table = el('table', 'warehouse-index-table');
  const thead = el('thead');
  const trH = el('tr');
  const columns = [
    { label: 'Database', key: 'db', sort: true },
    { label: 'Kind', key: 'kind', sort: true },
    { label: 'Name', key: 'name', sort: true },
    { label: 'Rows', key: 'rows', sort: true },
    { label: 'Columns', key: 'columns', sort: true },
    { label: 'Contents', key: 'contents', sort: false },
  ];

  let sortKey = null;
  let sortAsc = true;

  columns.forEach((col) => {
    const th = el('th', null, col.label);
    if (col.sort) {
      th.title = 'Click to sort by ' + col.label;
      th.addEventListener('click', () => {
        if (sortKey === col.key) {
          sortAsc = !sortAsc;
        } else {
          sortKey = col.key;
          sortAsc = true;
        }
        drawRows();
      });
    }
    trH.appendChild(th);
  });
  thead.appendChild(trH);
  table.appendChild(thead);

  const tbody = el('tbody');
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  panel.appendChild(tableWrap);

  const allItems = (block.items || []).slice();

  function drawRows() {
    let list = allItems.slice();
    if (sortKey) {
      list.sort((a, b) => {
        const valA = a[sortKey];
        const valB = b[sortKey];
        if (typeof valA === 'number' && typeof valB === 'number') {
          return (valA - valB) * (sortAsc ? 1 : -1);
        }
        return String(valA || '').localeCompare(String(valB || '')) * (sortAsc ? 1 : -1);
      });
    }

    const q = searchInput.value.toLowerCase().trim();
    tbody.textContent = '';
    let matches = 0;

    list.forEach((item) => {
      const searchTarget = (
        item.db + ' ' + item.kind + ' ' + item.name + ' ' +
        (item.row_is || '') + ' ' + (item.it_holds || '') + ' ' +
        (item.example || '') + ' ' + (item.why_separated || '')
      ).toLowerCase();
      if (q && !searchTarget.includes(q)) return;
      matches++;

      const tr = el('tr');

      const tdDb = el('td');
      tdDb.appendChild(el('span', 'pill db-pill', item.db));
      tr.appendChild(tdDb);

      const tdKind = el('td');
      tdKind.appendChild(el('span', 'pill ' + (item.kind === 'view' ? 'view-pill' : 'table-pill'), item.kind));
      tr.appendChild(tdKind);

      const tdName = el('td');
      const jumpBtn = el('button', 'table-jump-btn', item.name);
      jumpBtn.type = 'button';
      jumpBtn.title = 'Open ' + item.name + ' in the interactive explorer below';
      jumpBtn.addEventListener('click', () => {
        if (window.openWarehouseTable) {
          window.openWarehouseTable(item.db_file, item.name);
        }
      });
      tdName.appendChild(jumpBtn);
      tr.appendChild(tdName);

      const tdRows = el('td');
      tdRows.style.textAlign = 'right';
      tdRows.style.fontVariantNumeric = 'tabular-nums';
      tdRows.textContent = item.rows.toLocaleString();
      tr.appendChild(tdRows);

      const tdCols = el('td');
      tdCols.style.textAlign = 'right';
      tdCols.style.fontVariantNumeric = 'tabular-nums';
      tdCols.textContent = String(item.columns);
      tr.appendChild(tdCols);

      const tdContents = el('td', 'contents');
      tdContents.innerHTML = fmtContents(item.contents || '');
      tr.appendChild(tdContents);

      tbody.appendChild(tr);
    });

    if (q) {
      searchCount.textContent = 'Showing ' + matches + ' of ' + allItems.length + ' tables and views';
    } else {
      searchCount.textContent = allItems.length + ' tables and views total';
    }
  }

  searchInput.addEventListener('input', drawRows);
  drawRows();

  return panel;
}

function renderExplorer(block) {
  const panel = el('div', 'panel');
  panel.id = 'database-explorer-panel';
  panel.appendChild(panelHeader(block));

  const pills = el('div', 'pills');
  panel.appendChild(pills);
  const body = el('div', 'explorer');

  const listCol = el('div');
  listCol.style.borderRight = '1px solid var(--line)';
  listCol.style.display = 'flex';
  listCol.style.flexDirection = 'column';

  const filterWrap = el('div', 'tablelist-filter');
  const filterInput = el('input');
  filterInput.type = 'search';
  filterInput.placeholder = 'Filter tables...';
  filterWrap.appendChild(filterInput);
  listCol.appendChild(filterWrap);

  const list = el('div', 'tablelist');
  list.style.borderRight = 'none';
  listCol.appendChild(list);

  filterInput.addEventListener('input', () => {
    const q = filterInput.value.toLowerCase().trim();
    for (const btn of list.children) {
      const match = !q || btn.textContent.toLowerCase().includes(q);
      btn.style.display = match ? '' : 'none';
    }
  });

  const right = el('div', 'gridside');

  const dedicatedContainer = el('div');
  right.appendChild(dedicatedContainer);

  const previewHead = el('div', 'explorer-preview-head');
  const previewTitle = el('h4', null, 'Example entries and live data grid');
  const shape = el('p', 'hint');
  previewHead.appendChild(previewTitle);
  previewHead.appendChild(shape);
  right.appendChild(previewHead);

  const grid = dataGrid({ page: 25, heldIn: 'in the table' });
  right.appendChild(grid.node);

  body.appendChild(listCol);
  body.appendChild(right);
  panel.appendChild(body);

  let group = block.groups[0];

  function renderDedicatedCard(entry) {
    dedicatedContainer.textContent = '';
    const card = el('div', 'table-detail-card');

    const head = el('div', 'table-detail-head');
    const titleEl = el('h3', null, entry.name);
    const kindBadge = el('span', 'pill ' + (entry.kind === 'view' ? 'view-pill' : 'table-pill'), entry.kind.toUpperCase());
    const dbTag = el('span', 'pill db-pill', group.name);
    head.appendChild(titleEl);
    head.appendChild(kindBadge);
    head.appendChild(dbTag);
    card.appendChild(head);

    const meta = el('div', 'table-detail-meta');
    meta.textContent = group.name + ', ' + entry.rows.toLocaleString() + ' rows, ' +
      entry.columns.length + ' columns' +
      (entry.preview.length < entry.rows
        ? ', previewing ' + entry.preview.length.toLocaleString() + ' sorted sample rows'
        : ', showing all ' + entry.preview.length.toLocaleString() + ' rows');
    card.appendChild(meta);

    if (group.name.includes('mock')) {
      const mockBox = el('div', 'warnbox');
      mockBox.appendChild(el('strong', null, 'Test fixture data. '));
      mockBox.appendChild(document.createTextNode('These records describe made-up funds used to test data structure and calculation logic. Source-backed fund records reside in alts.duckdb and extracted.duckdb.'));
      card.appendChild(mockBox);
    }

    const explCard = el('div', 'explanation-card');
    explCard.setAttribute('aria-label', (entry.kind === 'view' ? 'View' : 'Table') + ' explanation');

    if (entry.plain_title) {
      explCard.appendChild(el('div', 'plain-title', entry.plain_title));
    }
    if (entry.row_is || entry.contents) {
      explCard.appendChild(el('p', 'plain-contents', entry.row_is || entry.contents));
    }
    if (entry.it_holds) {
      const p = el('p', 'plain-sub');
      p.appendChild(el('strong', null, 'What it holds: '));
      p.appendChild(document.createTextNode(entry.it_holds));
      explCard.appendChild(p);
    }
    if (entry.why_separated) {
      const p = el('p', 'plain-sub');
      const label = entry.kind === 'view' ? 'Reason for a view: ' : 'Reason for a separate table: ';
      p.appendChild(el('strong', null, label));
      p.appendChild(document.createTextNode(entry.why_separated));
      explCard.appendChild(p);
    }
    if (entry.example) {
      const p = el('p', 'plain-sub');
      p.appendChild(el('strong', null, 'Example: '));
      p.appendChild(document.createTextNode(entry.example));
      explCard.appendChild(p);
    }
    card.appendChild(explCard);

    const accordions = el('div', 'explorer-accordions');

    const colDetails = el('details', 'explorer-details');
    colDetails.appendChild(el('summary', null, 'Column dictionary & types (' + entry.columns.length + ' fields)'));
    const colBody = el('div', 'explorer-details-body');

    const colFilterBar = el('div', 'col-filter-bar');
    const colInput = el('input', 'col-filter-input');
    colInput.placeholder = 'Filter columns...';
    colFilterBar.appendChild(colInput);
    colBody.appendChild(colFilterBar);

    const colTable = el('table', 'col-table');
    const colThead = el('thead');
    const colTrH = el('tr');
    ['Column', 'Type', 'What it holds'].forEach((h) => {
      colTrH.appendChild(el('th', null, h));
    });
    colThead.appendChild(colTrH);
    colTable.appendChild(colThead);

    const colTbody = el('tbody');
    (entry.columns_meta || []).forEach((c) => {
      const tr = el('tr');
      tr.appendChild(el('td', 'col-name', c.name));
      tr.appendChild(el('td', 'col-type', c.type));
      tr.appendChild(el('td', null, c.note || ''));
      colTbody.appendChild(tr);
    });
    colTable.appendChild(colTbody);
    colBody.appendChild(colTable);
    colDetails.appendChild(colBody);
    accordions.appendChild(colDetails);

    colInput.addEventListener('input', () => {
      const q = colInput.value.toLowerCase().trim();
      for (const tr of colTbody.children) {
        const match = !q || tr.textContent.toLowerCase().includes(q);
        tr.style.display = match ? '' : 'none';
      }
    });

    if (entry.derivation && entry.derivation.length) {
      const dDetails = el('details', 'explorer-details');
      dDetails.appendChild(el('summary', null, 'Source files & pipeline processing (' + entry.derivation.length + ' steps)'));
      const dBody = el('div', 'explorer-details-body');
      const dList = el('ul', 'derivation-chain');
      entry.derivation.forEach((step) => {
        const li = el('li');
        li.appendChild(el('div', 'd-label', step.label));
        const valDiv = el('div', 'd-value');
        valDiv.appendChild(el('code', null, step.value));
        if (step.note) {
          valDiv.appendChild(el('div', 'd-note', step.note));
        }
        li.appendChild(valDiv);
        dList.appendChild(li);
      });
      dBody.appendChild(dList);
      dDetails.appendChild(dBody);
      accordions.appendChild(dDetails);
    }

    const activeConstraints = (entry.constraints || []).filter((c) => c.kind !== 'NOT NULL');
    if (activeConstraints.length) {
      const cDetails = el('details', 'explorer-details');
      cDetails.appendChild(el('summary', null, 'Keys & constraints (' + activeConstraints.length + ')'));
      const cBody = el('div', 'explorer-details-body');
      const cTable = el('table', 'col-table');
      const cThead = el('thead');
      const cTrH = el('tr');
      cTrH.appendChild(el('th', null, 'Kind'));
      cTrH.appendChild(el('th', null, 'Constraint'));
      cThead.appendChild(cTrH);
      cTable.appendChild(cThead);
      const cTbody = el('tbody');
      activeConstraints.forEach((c) => {
        const tr = el('tr');
        tr.appendChild(el('td', null, c.kind));
        tr.appendChild(el('td', 'col-name', c.text));
        cTbody.appendChild(tr);
      });
      cTable.appendChild(cTbody);
      cBody.appendChild(cTable);
      cDetails.appendChild(cBody);
      accordions.appendChild(cDetails);
    }

    if (entry.sql) {
      const sDetails = el('details', 'explorer-details');
      sDetails.appendChild(el('summary', null, 'View SQL definition'));
      const sBody = el('div', 'explorer-details-body');
      sBody.appendChild(el('pre', 'sql-box', entry.sql));
      sDetails.appendChild(sBody);
      accordions.appendChild(sDetails);
    }

    card.appendChild(accordions);
    dedicatedContainer.appendChild(card);
  }

  function showTable(entry, button) {
    for (const other of list.children) other.classList.toggle('on', other === button);
    renderDedicatedCard(entry);
    const preview = compactExplorerEntry(entry);
    shape.textContent = 'Sorted sample of ' + preview.rows.length.toLocaleString() + ' of ' +
      plural(entry.rows, 'row') + '. The interactive grid below presents ' + preview.columns.length.toLocaleString() +
      ' primary columns; click any row to inspect all ' + entry.columns.length.toLocaleString() + ' fields.';
    grid.set(preview);
  }

  function showGroup(next, targetTableName) {
    group = next;
    for (const pill of pills.children) pill.classList.toggle('on', pill.dataset.name === group.name);
    list.textContent = '';
    filterInput.value = '';
    let selectedBtn = null;
    let selectedEntry = null;
    group.tables.forEach((entry, index) => {
      const button = el('button', entry.kind === 'view' ? 'view' : null);
      button.dataset.table = entry.name;
      button.dataset.kind = entry.kind;
      button.appendChild(el('span', 'n', entry.name));
      button.appendChild(el('span', 'c', entry.rows.toLocaleString()));
      button.title = entry.about || entry.plain_title || '';
      button.addEventListener('click', () => showTable(entry, button));
      list.appendChild(button);
      if (targetTableName ? entry.name === targetTableName : index === 0) {
        selectedBtn = button;
        selectedEntry = entry;
      }
    });
    if (selectedBtn && selectedEntry) {
      showTable(selectedEntry, selectedBtn);
    }
  }

  for (const entry of block.groups) {
    const pill = el('button', 'pill', entry.name);
    pill.dataset.name = entry.name;
    pill.title = entry.note || '';
    pill.addEventListener('click', () => showGroup(entry));
    pills.appendChild(pill);
  }
  showGroup(group);

  window.openWarehouseTable = function(dbFile, tableName) {
    const cleanDb = (dbFile || '').replace(/\.duckdb$/i, '').trim();
    const targetGroup = block.groups.find((g) => g.name === dbFile || g.name.replace(/\.duckdb$/i, '') === cleanDb);
    if (targetGroup) {
      showGroup(targetGroup, tableName);
      panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return panel;
}

// The release audit carries one explanation per step. Each step's work is listed
// above the table, and the full explanation opens under a row when it is selected.
function renderReleaseWork(block) {
  const node = el('aside', 'guide tone-teach');
  node.id = 'release-work';
  node.setAttribute('aria-label', 'Work performed at each step');
  node.appendChild(el('h4', null, 'Work performed at each step'));
  node.appendChild(el('p', 'lead', 'This list gives the work performed at each of the ' + block.rows.length +
    ' steps in the release audit table below, in the same order. Open a heading such as Preparation or Publication to read those steps. Select a row in the table to read the inputs, result, check, and worked example of that step.'));
  const items = block.rows.map(row => {
    const stageId = releaseValue(block, row, 'stage_id');
    const item = block.explanations.find(entry => entry.id === stageId);
    if (!item) throw new Error('Release explanation missing for ' + stageId);
    return {
      stage: String(releaseValue(block, row, 'phase')),
      title: String(releaseValue(block, row, 'stage')),
      text: item.work,
    };
  });
  node.appendChild(renderSteps({ items, fold: true }));
  return node;
}

function releaseParagraph(parent, title, text, cls) {
  parent.appendChild(el('h3', null, title));
  parent.appendChild(el('p', cls || null, text));
}

function releaseColumns(block) {
  return block.columns.concat(block.hidden || []);
}

function releaseValue(block, row, name) {
  const index = releaseColumns(block).indexOf(name);
  return index < 0 ? '' : row[index];
}

// The explanation opens under its own row, so the table stays on screen while
// it is read.
function toggleReleaseDetail(block, row, tr) {
  const table = tr.closest('table');
  const already = tr.nextElementSibling;
  const wasOpen = already && already.classList.contains('release-detail');
  table.querySelectorAll('tr.release-detail').forEach(node => node.remove());
  table.querySelectorAll('tr.row[aria-expanded="true"]').forEach(node =>
    node.setAttribute('aria-expanded', 'false'));
  const scroll = tr.closest('.scroll');
  if (scroll) { scroll.style.maxHeight = ''; scroll.style.overflowY = ''; }
  if (wasOpen) return;
  tr.after(buildReleaseDetail(block, row, tr.children.length));
  tr.setAttribute('aria-expanded', 'true');
  // The explanation is taller than the grid's scroll box, so the box is opened
  // out while one is showing; otherwise the row being explained scrolls away.
  if (scroll) { scroll.style.maxHeight = 'none'; scroll.style.overflowY = 'visible'; }
  tr.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function buildReleaseDetail(block, raw, span) {
  const stageId = releaseValue(block, raw, 'stage_id');
  const item = block.explanations.find(entry => entry.id === stageId);
  if (!item) throw new Error('Release explanation missing for ' + stageId);
  const processOrder = String(releaseValue(block, raw, 'order'));
  const stageName = String(releaseValue(block, raw, 'stage'));
  const status = String(releaseValue(block, raw, 'status'));
  const checkedAt = String(releaseValue(block, raw, 'checked_at_utc'));
  const resultDetail = String(releaseValue(block, raw, 'result_detail'));

  const tr = el('tr', 'detail release-detail');
  tr.dataset.stageId = stageId;
  const td = el('td');
  td.colSpan = span;
  const body = el('div', 'release-explain');

  body.appendChild(el('p', 'release-step',
    'Process step ' + processOrder + ' of ' + block.explanations.length));
  body.appendChild(el('h4', null, item.title));
  body.appendChild(el('p', 'release-code', 'Recorded stage: ' + stageName + ' (' + item.id + ')'));
  body.appendChild(el('p', 'release-reader', 'Written for a reader who has not seen this project and does not know private-fund accounting or data-engineering terms.'));
  body.appendChild(el('p', null, item.purpose));

  const place = el('div', 'release-position');
  const positions = el('dl');
  for (const [label, text] of [['Position', item.position], ['Before', item.before], ['After', item.after]]) {
    positions.appendChild(el('dt', null, label));
    positions.appendChild(el('dd', null, text));
  }
  place.appendChild(positions);
  body.appendChild(place);

  releaseParagraph(body, 'Work performed', item.work);
  releaseParagraph(body, 'Information used', item.inputs);
  releaseParagraph(body, 'Result produced', item.outputs);
  releaseParagraph(body, 'Checks and their limits', item.check);
  releaseParagraph(body, 'Example', item.example, 'release-example');
  body.appendChild(el('p', 'release-status-note',
    'Recorded result: ' + status + ' at ' + checkedAt + ' UTC. ' + resultDetail));

  // A path opens as a link where the page can reach it: a repository file on
  // the local copy, a published download on the public one. Otherwise it is
  // shown as text, so the public page carries no dead links.
  const details = el('details', 'release-files');
  details.appendChild(el('summary', null, 'Related files and the saved table fields'));
  const files = el('dl');
  item.files.forEach(([label, path]) => {
    files.appendChild(el('dt', null, label));
    const dd = el('dd');
    const href = downloadHref(path);
    if (href) {
      const link = el('a', null, path);
      link.href = href;
      link.target = '_blank';
      link.rel = 'noopener';
      dd.appendChild(link);
    } else {
      dd.appendChild(el('code', null, path));
    }
    files.appendChild(dd);
  });
  details.appendChild(files);
  const definitions = block.definitions || [];
  const fields = el('dl');
  releaseColumns(block).forEach((name, index) => {
    fields.appendChild(el('dt', null, name));
    const value = el('dd');
    value.appendChild(el('code', null, raw[index] === '' ? '(blank in the saved table)' : raw[index]));
    fields.appendChild(value);
    fields.appendChild(el('dd', null, definitions[index] || ''));
  });
  details.appendChild(fields);
  body.appendChild(details);

  td.appendChild(body);
  tr.appendChild(td);
  return tr;
}

// ---------------------------------------------------------------- report
//
// A separate report shown inside the page. Its frame loads when the section
// opens. An embedded report fills the section. Other reports keep a new-tab link.
function renderReport(block) {
  const embedded = Boolean(block.embed);
  const panel = el('div', embedded ? 'report-embed' : 'panel');
  if (!embedded) {
    const head = el('header');
    head.appendChild(el('h4', null, block.title));
    if (block.about) head.appendChild(el('p', 'about', block.about));
    panel.appendChild(head);
  }
  let href = downloadHref(block.source);
  if (!href) {
    panel.appendChild(el('p', 'note', 'The report file is missing from this copy of the page.'));
    return panel;
  }
  if (block.fragment) href += '#' + String(block.fragment).replace(/^#/, '');
  if (!embedded) {
    const open = el('a', 'report-open', 'Open the full report in a new tab');
    open.href = href;
    open.target = '_blank';
    open.rel = 'noopener';
    panel.appendChild(open);
  }
  const frame = el('iframe', embedded ? 'report-frame report-frame-fill' : 'report-frame');
  frame.title = block.title;
  frame.dataset.src = href;
  panel.appendChild(frame);
  return panel;
}

const RENDERERS = {
  kpi: renderKpi,
  report: renderReport,
  note: renderNote,
  guide: renderGuide,
  terms: renderTerms,
  link: renderLink,
  steps: renderSteps,
  keyvalue: renderKeyvalue,
  figure: renderFigure,
  rag_console: renderRagConsole,
  bars: renderBars,
  boxes: renderBoxes,
  donuts: renderDonuts,
  stacks: renderStacks,
  formulas: renderFormulas,
  table: renderTable,
  explorer: renderExplorer,
  warehouse_index: renderWarehouseIndex,
};

let helpButton = null;
let lastSection = '';

function renderHelpOverlay() {
  const help = DATA.help || {};
  const overlay = el('div');
  overlay.id = 'page-guide';
  overlay.setAttribute('role', 'region');
  overlay.setAttribute('aria-labelledby', 'page-guide-title');

  const card = el('div', 'help-card');
  const head = el('header');
  const title = el('h2', null, help.title || 'Page guide');
  title.id = 'page-guide-title';
  head.appendChild(title);
  const close = el('button', null, 'Close');
  close.type = 'button';
  close.addEventListener('click', () => {
    location.hash = lastSection || DATA.sections[0].id;
  });
  head.appendChild(close);
  card.appendChild(head);

  const body = el('div', 'help-body');
  if (help.intro) body.appendChild(el('p', 'intro', help.intro));
  for (const section of (help.sections || [])) {
    body.appendChild(el('h3', null, section.title));
    for (const paragraph of (section.paragraphs || [])) {
      body.appendChild(el('p', null, paragraph));
    }
  }
  if (DATA.terms && DATA.terms.length) {
    body.appendChild(el('h3', null, 'Words used on this page'));
    const words = el('div', 'help-words');
    for (const row of DATA.terms) {
      const item = el('div');
      item.appendChild(el('b', null, row.word));
      item.appendChild(el('span', null, row.meaning));
      words.appendChild(item);
    }
    body.appendChild(words);
  }
  card.appendChild(body);
  overlay.appendChild(card);
  main.appendChild(overlay);

  helpButton = el('button', 'help-btn', 'Page guide');
  helpButton.type = 'button';
  helpButton.setAttribute('aria-expanded', 'false');
  helpButton.setAttribute('aria-controls', 'page-guide');
  helpButton.addEventListener('click', () => {
    if (location.hash.slice(1) === 'page-guide') {
      location.hash = lastSection || DATA.sections[0].id;
    } else {
      location.hash = 'page-guide';
    }
  });
  nav.appendChild(helpButton);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && location.hash.slice(1) === 'page-guide') {
      location.hash = lastSection || DATA.sections[0].id;
    }
  });
}

function build() {
  lastSection = DATA.sections[0].id;
  nav.appendChild(el('h1', null, DATA.title));
  nav.appendChild(el('p', 'sub', DATA.subtitle));
  renderHelpOverlay();
  DATA.sections.forEach((section, index) => {
    const link = el('a');
    link.href = '#' + section.id;
    link.dataset.id = section.id;
    link.appendChild(el('span', 'n', String(index + 1).padStart(2, '0')));
    link.appendChild(el('span', null, section.title));
    if (section.featured) link.classList.add('featured');
    nav.appendChild(link);

    const node = el('section');
    node.id = section.id;
    const fill = section.blocks.some((block) => block.kind === 'report' && block.embed);
    if (fill) node.classList.add('fill-embed');
    if (!fill) {
      node.appendChild(el('div', 'eyebrow', 'Section ' + (index + 1) + ' of ' + DATA.sections.length));
      node.appendChild(el('h2', null, section.title));
      node.appendChild(el('p', 'blurb', section.blurb));
    }
    for (const block of section.blocks) {
      if (fill && !(block.kind === 'report' && block.embed)) continue;
      if (block.kind === 'heading') {
        node.appendChild(el('h3', null, block.text));
        continue;
      }
      if (Array.isArray(block.explanations)) node.appendChild(renderReleaseWork(block));
      const renderer = RENDERERS[block.kind];
      if (renderer) node.appendChild(renderer(block));
    }
    main.appendChild(node);
  });
  if (DATA.footer) nav.appendChild(el('p', 'foot', DATA.footer));
}

function show(id) {
  if (id === 'page-guide') {
    for (const node of main.children) node.classList.toggle('on', node.id === 'page-guide');
    for (const link of nav.querySelectorAll('a')) link.classList.remove('on');
    if (helpButton) helpButton.setAttribute('aria-expanded', 'true');
    window.scrollTo(0, 0);
    return;
  }
  const parts = id ? id.split('/') : [];
  const sectionId = parts[0] || '';
  const known = DATA.sections.some((section) => section.id === sectionId);
  const target = known ? sectionId : DATA.sections[0].id;
  lastSection = target;
  for (const node of main.children) node.classList.toggle('on', node.id === target);
  for (const link of nav.querySelectorAll('a')) link.classList.toggle('on', link.dataset.id === target);
  if (helpButton) helpButton.setAttribute('aria-expanded', 'false');
  // An embedded report loads the first time its section opens, so the page
  // opens at its usual speed.
  const opened = document.getElementById(target);
  if (opened) {
    for (const frame of opened.querySelectorAll('iframe[data-src]')) {
      if (!frame.getAttribute('src')) frame.src = frame.dataset.src;
    }
  }

  if (target === 'warehouse' && parts.length >= 3) {
    const db = parts[1];
    const table = parts[2];
    setTimeout(() => {
      if (window.openWarehouseTable) window.openWarehouseTable(db, table);
    }, 40);
  } else {
    window.scrollTo(0, 0);
  }
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
