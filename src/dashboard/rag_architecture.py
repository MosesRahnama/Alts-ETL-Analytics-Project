"""RAG engine explanation used by the main dashboard and RAG/architecture.html."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = PROJECT_ROOT / "RAG" / "architecture.html"
DEMO = PROJECT_ROOT / "RAG" / "evaluation" / "public-demo.json"
RETRIEVAL = PROJECT_ROOT / "RAG" / "config" / "retrieval.json"


def _json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def architecture_svg() -> str:
    text = OUTPUT.read_text(encoding="utf-8")
    start = text.index("<svg")
    end = text.index("</svg>") + 6
    svg = text[start:end]
    svg = svg.replace("Access Interfaces (Front Doors)", "Access Interfaces")
    svg = svg.replace("Enforces Chinese wall between roles", "Keeps extractor sessions isolated")
    return svg


def _counts() -> dict[str, str]:
    index = _json(DEMO).get("index_summary") or {}
    evaluation = _json(DEMO).get("evaluation_summary") or {}
    return {
        "catalogued": f"{int(index.get('catalogued_documents') or 0):,}",
        "searchable": f"{int(index.get('indexed_documents') or 0):,}",
        "pages": f"{int(index.get('indexed_pages') or 0):,}",
        "blocks": f"{int(index.get('block_count') or 0):,}",
        "vectors": f"{int(index.get('vector_blocks') or 0):,}",
        "vector_docs": f"{int(index.get('vector_documents') or 0):,}",
        "cases": f"{int(evaluation.get('case_count') or 0):,}",
        "model": str(index.get("embedding_model") or "BAAI/bge-small-en-v1.5"),
        "revision": str(index.get("embedding_revision") or ""),
    }


def architecture_html() -> str:
    counts = _counts()
    policy = _json(RETRIEVAL)
    svg = architecture_svg()
    dimension = int(policy.get("embedding_dimension") or 384)
    kinds = ", ".join(str(item) for item in (policy.get("embedding_block_kinds") or ()))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RAG engine</title>
<style>
:root {{
  --ink: #173344; --ink-soft: #214b60; --ink-faint: #3d5663; --line: #d3e0e4;
  --page: #f1f5f6; --paper: #ffffff; --panel: #edf7f7; --accent: #087e83;
  --accent-2: #06696d; --good: #0a6e56; --good-soft: #e5f3ee; --warn: #8b4513;
  --warn-soft: #fff9e9; --stop: #9d2020; --stop-soft: #fff0f0;
  --sans: -apple-system, "Segoe UI", Inter, Roboto, Helvetica, Arial, sans-serif;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{ background: var(--page); color: var(--ink); font: 15px/1.5 var(--sans); }}
main {{ max-width: 1100px; margin: 0 auto; padding: 28px 32px 72px; }}
h1 {{ font-size: 28px; margin: 8px 0 8px; letter-spacing: -.02em; }}
h2 {{ font-size: 20px; margin: 32px 0 8px; }}
p.lead {{ color: var(--ink-faint); max-width: 76ch; margin: 0 0 16px; }}
.muted {{ color: var(--ink-faint); font-size: 13px; }}
.kpis {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 18px 0 8px; align-items: stretch; }}
.kpi {{ display: flex; flex-direction: column; justify-content: space-between; background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-width: 0; }}
.kpi b {{ display: block; margin-top: auto; padding-top: 8px; font-size: 20px; color: var(--accent-2); }}
.kpi span {{ font-size: 12px; color: var(--ink-faint); line-height: 1.3; }}
.flow {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin: 16px 0; }}
.step {{ background: var(--paper); border: 1px solid var(--line); border-top: 3px solid var(--accent); border-radius: 8px; padding: 10px 12px; min-height: 110px; }}
.step strong {{ display: block; font-size: 13px; margin-bottom: 4px; }}
.step span {{ display: block; font-size: 12px; color: var(--ink-faint); line-height: 1.4; }}
svg.arch {{ width: 100%; height: auto; background: var(--paper); border: 1px solid var(--line); border-radius: 8px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; background: var(--paper); }}
th, td {{ text-align: left; vertical-align: top; padding: 8px 10px; border-bottom: 1px solid var(--line); }}
th {{ color: var(--ink-faint); font-size: 12px; font-weight: 700; }}
.card {{ background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; margin: 12px 0; overflow-x: auto; }}
code {{ font-size: 12.5px; }}
@media (max-width: 980px) {{
  main {{ padding: 18px 16px; }}
  .kpis, .flow {{ grid-template-columns: 1fr 1fr; }}
}}
</style>
</head>
<body>
<main>
<p class="muted">Local retrieval engine. This page describes the system. It does not run a search.</p>
<h1>RAG engine</h1>
<p class="lead">The engine finds passages in source fund reports and tests extracted fields against that printed text. It does not change source PDFs, extraction files, or financial databases. Keyword search is the default. A local embedding model is optional. Provider language-model calls stay off.</p>
<div class="kpis">
<div class="kpi"><span>Catalogued reports</span><b>{counts['catalogued']}</b></div>
<div class="kpi"><span>Searchable reports</span><b>{counts['searchable']}</b></div>
<div class="kpi"><span>Indexed pages</span><b>{counts['pages']}</b></div>
<div class="kpi"><span>Evidence blocks</span><b>{counts['blocks']}</b></div>
<div class="kpi"><span>Local vectors</span><b>{counts['vectors']}</b></div>
</div>
<p class="muted">Counts from the measured index. One report, SRC132, is restricted and stays out of the public export. Vectors cover {counts['vector_docs']} reviewed reports. {counts['cases']} source-verified cases passed under keyword, keyword plus context, and hybrid retrieval. Hybrid added no held-out accuracy, so keyword remains the default.</p>

<h2>System map</h2>
<p class="lead">Read-only project files feed a local SQLite index. The engine applies role checks, then returns passages or field verdicts through four access interfaces.</p>
{svg}

<h2>Indexing path</h2>
<div class="flow">
<div class="step"><strong>1. Inputs</strong><span>Source ledger, routing CSV, page text, table grids, and original PDFs. The engine never writes these files.</span></div>
<div class="step"><strong>2. Indexer</strong><span>Splits each page into paragraphs, table rows, notes, and footnotes. Original wording is stored unchanged.</span></div>
<div class="step"><strong>3. Search store</strong><span>SQLite holds document metadata, block text, FTS5 word index, table and footnote links, and optional vectors.</span></div>
<div class="step"><strong>4. Sessions</strong><span>Each request carries a server-issued role and a fixed document set. Extractor sessions cannot see each other.</span></div>
<div class="step"><strong>5. Context</strong><span>A hit receives parent table headers, row labels, and footnotes, up to 12,000 characters.</span></div>
<div class="step"><strong>6. Field checks</strong><span>Value, date, unit, fee basis, and method are scored separately as SUPPORTED, CONTRADICTED, or INSUFFICIENT_EVIDENCE.</span></div>
</div>

<h2>Embedding model</h2>
<div class="card">
<table>
<thead><tr><th>Setting</th><th>Value</th></tr></thead>
<tbody>
<tr><td>Model</td><td><code>{counts['model']}</code></td></tr>
<tr><td>Runtime</td><td>Local ONNX snapshot. Copied into <code>%LOCALAPPDATA%\\MinaAnalytics\\AltsRAG</code>. No download at query time.</td></tr>
<tr><td>Revision</td><td><code>{counts['revision']}</code></td></tr>
<tr><td>Vector size</td><td>{dimension} numbers per passage</td></tr>
<tr><td>Embedded block types</td><td>{kinds}</td></tr>
<tr><td>Scope</td><td>Reviewed extracted documents ({counts['vector_docs']} reports, {counts['vectors']} vectors)</td></tr>
<tr><td>Batch size</td><td>{int(policy.get('embedding_batch_size') or 64)}</td></tr>
<tr><td>Keyword weight / vector weight</td><td>{policy.get('keyword_weight')} / {policy.get('vector_weight')}</td></tr>
<tr><td>Hybrid default</td><td>Off. Reciprocal rank fusion uses k = {policy.get('rrf_k')} when hybrid is requested.</td></tr>
<tr><td>Candidate / result limits</td><td>{policy.get('candidate_limit')} ranked candidates, {policy.get('result_limit')} returned hits</td></tr>
<tr><td>Reasoning model</td><td>GPT-5.6 Luna through OpenRouter is named in config. The provider identifier and job approval are unset, so the adapter refuses execution.</td></tr>
</tbody>
</table>
</div>

<h2>Operations</h2>
<div class="card">
<table>
<thead><tr><th>Operation</th><th>Role</th><th>Return</th></tr></thead>
<tbody>
<tr><td><code>search_sources</code></td><td>Assigned documents for the session</td><td>Ranked blocks with original text, physical PDF page, block type, and attached table or footnote context</td></tr>
<tr><td><code>get_evidence</code></td><td>Same session</td><td>Stored quotation for a known block ID, without a new search</td></tr>
<tr><td><code>verify_claim</code></td><td>reviewer</td><td>Per-field verdicts. A matching number does not prove a date or a net-of-fees label</td></tr>
<tr><td><code>context_review</code></td><td>reviewer</td><td>Footnotes and conditions that extracted records may have missed, written to a review CSV</td></tr>
<tr><td><code>explain_analytics</code></td><td>reviewer</td><td>Named DuckDB reads. Free-form SQL is blocked</td></tr>
</tbody>
</table>
</div>

<h2>Roles</h2>
<div class="card">
<table>
<thead><tr><th>Role</th><th>Search scope</th><th>Field checks</th><th>Footnote scan</th><th>Analytics</th><th>Other extractors</th></tr></thead>
<tbody>
<tr><td><code>extractor_a</code></td><td>Assigned report only</td><td>No</td><td>No</td><td>No</td><td>No</td></tr>
<tr><td><code>extractor_b</code></td><td>Assigned report only</td><td>No</td><td>No</td><td>No</td><td>No</td></tr>
<tr><td><code>reviewer</code></td><td>Active audit reports</td><td>Yes</td><td>Yes</td><td>Yes</td><td>Compares A and B</td></tr>
<tr><td><code>public_demo</code></td><td>Static export only</td><td>Precomputed</td><td>No</td><td>No</td><td>No</td></tr>
</tbody>
</table>
</div>

<h2>Storage</h2>
<p class="lead">Runtime files sit outside Git. Source PDFs, page text, grids, and DuckDB warehouses remain read-only.</p>
<div class="card">
<table>
<thead><tr><th>Store</th><th>Contents</th></tr></thead>
<tbody>
<tr><td><code>index.sqlite</code></td><td>Document records, evidence blocks, FTS5 word index, block relations, optional vectors</td></tr>
<tr><td><code>access.sqlite</code></td><td>Sessions, roles, permitted document lists, query audit log</td></tr>
<tr><td>Review suggestions CSV</td><td>Proposed footnote attachments. Not written into extracted facts</td></tr>
<tr><td>DuckDB warehouses</td><td>Published metrics on demand. A missing or locked file returns DATABASE_UNAVAILABLE; text search still runs</td></tr>
</tbody>
</table>
</div>

<h2>Response envelope</h2>
<div class="card">
<table>
<thead><tr><th>Field or state</th><th>Meaning</th></tr></thead>
<tbody>
<tr><td><code>request_id</code>, <code>operation</code>, <code>scope</code></td><td>Tracking id, function name, role and permitted documents</td></tr>
<tr><td><code>source_version</code></td><td>Hash of the indexed files. A later disk change yields STALE_SOURCE</td></tr>
<tr><td><code>results</code> / <code>assessments</code></td><td>Hits or field verdicts</td></tr>
<tr><td>OK</td><td>The request finished. Read results and assessments</td></tr>
<tr><td>EMPTY_RESULTS</td><td>Search ran. No permitted text matched</td></tr>
<tr><td>ACCESS_DENIED</td><td>The role cannot see the report or operation</td></tr>
<tr><td>STALE_SOURCE</td><td>A source file changed after the index was built</td></tr>
<tr><td>QUERY_UNSUPPORTED</td><td>A required parameter is missing</td></tr>
<tr><td>DATABASE_UNAVAILABLE</td><td>The analytics file is locked or absent</td></tr>
<tr><td>MODEL_DISABLED</td><td>External language-model calls are off</td></tr>
</tbody>
</table>
</div>

<h2>Access interfaces</h2>
<div class="card">
<table>
<thead><tr><th>Interface</th><th>Entry</th></tr></thead>
<tbody>
<tr><td>Command line</td><td><code>python -B -m alts_rag</code> with a subcommand such as status, index, or evaluate</td></tr>
<tr><td>MCP</td><td>Standard-input JSON tools for coding agents</td></tr>
<tr><td>Loopback server</td><td><code>127.0.0.1:8765</code> from <code>RAG/start-local.ps1</code>. Interactive search lives there and on GP Scoring, RAG: Document Insights</td></tr>
<tr><td>Static export</td><td><code>RAG/evaluation/public-demo.json</code>, shown on <a href="../rag.html">rag.html</a></td></tr>
</tbody>
</table>
</div>
<p class="muted">The four interfaces call the same service methods. Transport code contains no fund-math. Live search is not on this page.</p>
</main>
</body>
</html>
"""


def write_architecture_html(path: Path = OUTPUT) -> Path:
    path.write_text(architecture_html(), encoding="utf-8", newline="\n")
    return path


def rag_engine_section() -> dict:
    from src.dashboard.build_dashboard import heading, keyvalue, kpi, note, steps, thousands
    from src.dashboard.teaching import primers_for

    demo = _json(DEMO)
    index = demo.get("index_summary") or {}
    evaluation = demo.get("evaluation_summary") or {}
    policy = _json(RETRIEVAL)
    catalogued = int(index.get("catalogued_documents") or 0)
    searchable = int(index.get("indexed_documents") or 0)
    pages = int(index.get("indexed_pages") or 0)
    blocks = int(index.get("block_count") or 0)
    vectors = int(index.get("vector_blocks") or 0)
    vector_docs = int(index.get("vector_documents") or 0)
    cases = int(evaluation.get("case_count") or 0)
    model = str(index.get("embedding_model") or policy.get("embedding_model") or "")
    revision = str(index.get("embedding_revision") or policy.get("embedding_revision") or "")
    dimension = int(policy.get("embedding_dimension") or 384)
    kinds = ", ".join(str(item) for item in (policy.get("embedding_block_kinds") or ()))
    return {
        "id": "rag-engine",
        "title": "RAG engine",
        "blurb": (
            "Local source search and field checks for fund reports. This section describes "
            "the engine, the index, and the embedding model. It does not run a query. "
            "Interactive search is GP Scoring, RAG: Document Insights, or the local RAG service."
        ),
        "blocks": [
            *primers_for("rag-engine"),
            kpi(
                ("Catalogued reports", thousands(catalogued), "source ledger documents known to the engine"),
                ("Searchable reports", thousands(searchable), "indexed for keyword search; SRC132 stays restricted"),
                ("Indexed pages", thousands(pages), "physical PDF pages in the text index"),
                ("Evidence blocks", thousands(blocks), "paragraphs, table rows, notes, and footnotes"),
                ("Local vectors", thousands(vectors), f"{thousands(vector_docs)} reviewed reports, {dimension}-number embeddings"),
            ),
            heading("System map"),
            {
                "kind": "figure",
                "title": "Stores, engine, and access interfaces",
                "about": (
                    "Read-only inputs on the left. Local SQLite stores next. Engine operations in "
                    "the third column. Command line, MCP, loopback server, and static export on the right."
                ),
                "source": "RAG/architecture.html",
                "svg": architecture_svg(),
            },
            heading("Indexing path"),
            steps(
                [
                    ("Inputs", "Source ledger, routing CSV, page text, table grids, and original PDFs. The engine never writes these files."),
                    ("Indexer", "Splits each page into paragraphs, table rows, notes, and footnotes. Original wording is stored unchanged."),
                    ("Search store", "SQLite holds metadata, block text, the FTS5 word index, table and footnote links, and optional vectors."),
                    ("Sessions", "Each request carries a server-issued role and a fixed document set. Extractor sessions cannot see each other."),
                    ("Context", "A hit receives parent table headers, row labels, and footnotes, up to 12,000 characters."),
                    ("Field checks", "Value, date, unit, fee basis, and method are scored separately as SUPPORTED, CONTRADICTED, or INSUFFICIENT_EVIDENCE."),
                ]
            ),
            heading("Embedding model"),
            keyvalue(
                [
                    ("Model", model),
                    ("Runtime", "Local ONNX snapshot under %LOCALAPPDATA%\\MinaAnalytics\\AltsRAG. No download at query time."),
                    ("Revision", revision),
                    ("Vector size", f"{dimension} numbers per passage"),
                    ("Embedded block types", kinds),
                    ("Scope", f"Reviewed extracted documents ({thousands(vector_docs)} reports)"),
                    ("Keyword default", "On. Hybrid search is optional and added no held-out accuracy on the measured cases."),
                    (
                        "Hybrid fusion",
                        f"Reciprocal rank fusion k = {policy.get('rrf_k')}; keyword weight {policy.get('keyword_weight')}; vector weight {policy.get('vector_weight')}.",
                    ),
                    (
                        "Search limits",
                        f"{policy.get('candidate_limit')} candidates, {policy.get('result_limit')} returned hits, 12,000-character context budget.",
                    ),
                    (
                        "Reasoning model",
                        "GPT-5.6 Luna through OpenRouter is named in config. The provider identifier and job approval are unset, so the adapter refuses execution.",
                    ),
                    (
                        "Measured cases",
                        f"{thousands(cases)} source-verified cases passed under keyword, keyword plus context, and hybrid retrieval.",
                    ),
                ]
            ),
            heading("Operations"),
            steps(
                [
                    ("search_sources", "Ranks permitted blocks. Returns original text, physical PDF page, block type, and attached table or footnote context."),
                    ("get_evidence", "Returns the stored quotation for a known block ID without a new search."),
                    ("verify_claim", "Reviewer only. Scores each claimed field on its own. A matching number does not prove a date or a net-of-fees label."),
                    ("context_review", "Reviewer only. Lists footnotes and conditions that extracted records may have missed."),
                    ("explain_analytics", "Reviewer only. Runs named DuckDB reads. Free-form SQL is blocked."),
                ]
            ),
            heading("Roles"),
            keyvalue(
                [
                    ("extractor_a / extractor_b", "Search the assigned report only. No field checks, footnote scan, analytics, or view of the other extractor."),
                    ("reviewer", "Search active audit reports. Run field checks, footnote scan, and named analytics. Compare extractor A and B."),
                    ("public_demo", "Read the static export only. No live index and no model call."),
                ]
            ),
            heading("Storage"),
            keyvalue(
                [
                    ("index.sqlite", "Document records, evidence blocks, FTS5 word index, block relations, optional vectors."),
                    ("access.sqlite", "Sessions, roles, permitted document lists, query audit log."),
                    ("Review suggestions CSV", "Proposed footnote attachments. Not written into extracted facts."),
                    ("DuckDB warehouses", "Published metrics on demand. A missing file returns DATABASE_UNAVAILABLE; text search still runs."),
                ]
            ),
            heading("Response states"),
            keyvalue(
                [
                    ("OK", "The request finished. Read results and assessments."),
                    ("EMPTY_RESULTS", "Search ran. No permitted text matched."),
                    ("ACCESS_DENIED", "The role cannot see the report or operation."),
                    ("STALE_SOURCE", "A source file changed after the index was built."),
                    ("QUERY_UNSUPPORTED", "A required parameter is missing."),
                    ("DATABASE_UNAVAILABLE", "The analytics file is locked or absent."),
                    ("MODEL_DISABLED", "External language-model calls are off."),
                ]
            ),
            note(
                "Live document search uses real manager and fund names on GP Scoring, RAG: Document Insights. "
                "This section does not embed that search."
            ),
        ],
    }
