"""Build the standalone RAG reviewer page from checked-in evidence results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.dashboard.build_dashboard import (
    PROJECT_ROOT,
    heading,
    keyvalue,
    kpi,
    link,
    note,
    steps,
    table,
    thousands,
)
from src.dashboard.page import render
from src.dashboard.teaching import guide


OUTPUT = PROJECT_ROOT / "rag.html"
DEMO = PROJECT_ROOT / "RAG" / "evaluation" / "public-demo.json"
TITLE = "Alternative Investment Evidence RAG"
SUBTITLE = "Local source retrieval and field-level verification for private-fund reports"
FOOTER = "The page reports checked-in measurements. Provider requests remain disabled."

TERMS = [
    {
        "word": "retrieval-augmented generation (RAG)",
        "meaning": "A process that finds source passages before a language model or rule evaluates a question.",
    },
    {
        "word": "evidence block",
        "meaning": "One indexed paragraph, table row, note, footnote, or page fallback with a document and physical PDF page.",
    },
    {
        "word": "keyword retrieval",
        "meaning": "Local search that ranks passages using the words in the question.",
    },
    {
        "word": "vector retrieval",
        "meaning": "Local search that compares numeric representations of meaning instead of exact wording.",
    },
    {
        "word": "context assembly",
        "meaning": "The addition of the governing table row, parent passage, nearby note, or footnote to a search result.",
    },
    {
        "word": "field assessment",
        "meaning": "A separate evidence decision for a value, date, unit, fee basis, method, or entity name.",
    },
    {
        "word": "physical PDF page",
        "meaning": "Page count from the start of the PDF file. It can differ from a page number printed in the footer.",
    },
    {
        "word": "reviewer session",
        "meaning": "A local identifier that fixes the role, permitted reports, purpose, and permitted data groups before search.",
    },
]

HELP = {
    "title": "RAG page guide",
    "intro": (
        "Written for a reviewer who has not seen this project and knows no retrieval terminology. "
        "The sections describe the engine, its data boundaries, its measured results, and its local controls."
    ),
    "sections": [
        {
            "title": "Evidence and decisions",
            "paragraphs": [
                "A search result is evidence, not a final extraction decision. Each result retains the source report and physical PDF page.",
                "A field assessment states whether retrieved text supports, contradicts, or fails to establish one claimed field. A person retains the final review decision.",
            ],
        },
        {
            "title": "Static and local modes",
            "paragraphs": [
                "The checked-in page contains saved questions, approved excerpts, and measured offline results. It sends no request to a model provider.",
                "The local loopback service activates the evidence console and source-PDF opener for a reviewer session on this computer.",
            ],
        },
    ],
}


def _demo() -> dict:
    if not DEMO.is_file():
        return {}
    payload = json.loads(DEMO.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("RAG/evaluation/public-demo.json must contain an object")
    return payload


def _index_values(demo: dict) -> tuple[dict, dict, dict]:
    return (
        demo.get("index_summary") or {},
        demo.get("evaluation_summary") or {},
        demo.get("limits") or {},
    )


def overview_section(demo: dict) -> dict:
    index, evaluation, limits = _index_values(demo)
    return {
        "id": "overview",
        "title": "Purpose and current state",
        "blurb": (
            "The engine searches the report corpus, attaches the context that gives a printed value its meaning, "
            "and checks each claimed field against cited source text. It supplements the extraction and review process; "
            "it does not replace full-page reading, adjudication, or the financial-data pipeline."
        ),
        "blocks": [
            guide(
                "The problem it addresses",
                [
                    "A private-fund fact often depends on text outside its table cell. A return can require a fee-basis note on another page, a date can refer to a report rather than a measurement, and the same number can appear under several funds.",
                    "The engine retrieves the printed value together with nearby table, note, and footnote evidence. Every returned passage names its report and physical page, so a reviewer can reopen the source.",
                    "The engine reports insufficient evidence when the retrieved text does not establish a qualifier. It does not convert search failure into a factual claim that the document is silent.",
                ],
            ),
            kpi(
                ("Catalogued reports", thousands(index.get("catalogued_documents") or 0), "reports recorded in the source ledger"),
                ("Searchable reports", thousands(index.get("indexed_documents") or 0), "locally indexed reports"),
                ("Indexed pages", thousands(index.get("indexed_pages") or 0), "physical PDF pages represented in the index"),
                ("Evidence blocks", thousands(index.get("block_count") or 0), "paragraphs, rows, notes, footnotes, and page fallbacks"),
                ("Local vectors", thousands(index.get("vector_blocks") or 0), "meaning-based representations for the reviewed documents"),
                ("Evaluation cases", thousands(evaluation.get("case_count") or 0), "source-checked retrieval questions"),
                ("Provider requests", str(limits.get("model_requests") or "disabled"), "the checked-in page and offline engine use none"),
            ),
            link("dashboard.html#evidence-review", "Project dashboard", "Related project data:"),
        ],
    }


def architecture_section(demo: dict) -> dict:
    del demo
    return {
        "id": "architecture",
        "title": "Architecture and data boundaries",
        "blurb": (
            "One service controls source search, context assembly, field checks, analytical reads, access rules, and citations. "
            "The index and reviewer sessions remain outside the repository; the source PDFs and published financial tables remain unchanged."
        ),
        "blocks": [
            steps([
                ("Scope", "Select permitted reports", "data-gathering/source_ledger.csv supplies report identity and source paths. A reviewer session fixes the permitted report IDs before retrieval."),
                ("Prepare", "Split source material into evidence blocks", "RAG/src/alts_rag/indexer.py records pages, paragraphs, table rows, notes, and footnotes without changing their original text."),
                ("Store", "Write the local evidence index", "SQLite stores documents, evidence blocks, relationships, full-text search data, and optional local vectors under %LOCALAPPDATA%/MinaAnalytics/AltsRAG."),
                ("Retrieve", "Rank evidence inside the permitted set", "RAG/src/alts_rag/retrieval.py runs keyword search and, when requested, local vector search. Permission filtering occurs before ranking."),
                ("Context", "Attach meaning-bearing passages", "RAG/src/alts_rag/context.py adds linked parents, table rows, notes, and footnotes within a fixed text budget."),
                ("Assess", "Check each claimed field", "RAG/src/alts_rag/assessment.py evaluates the value, date, unit, fee basis, method, and entity separately and cites the supporting or conflicting blocks."),
                ("Return", "Provide source-backed results", "RAG/src/alts_rag/service.py returns evidence, proposed context-review items, or named analytical records through the command line, local web service, and agent tools."),
            ]),
            heading("Separation from the financial pipeline"),
            keyvalue([
                ("Read-only source inputs", "PDF, TXT, page-grid, extraction, reviewer, CSV, and DuckDB files"),
                ("Private runtime state", "text index, vectors, sessions, approvals, usage records, and review suggestions"),
                ("Checked-in RAG outputs", "configuration, tests, evaluation cases, measured offline results, and this static page"),
                ("Excluded behavior", "automatic changes to extracted facts, fund identities, financial calculations, or reviewer decisions"),
            ]),
        ],
    }


def evidence_model_section(demo: dict) -> dict:
    index, _, _ = _index_values(demo)
    return {
        "id": "evidence-model",
        "title": "Evidence model",
        "blurb": (
            "The index preserves the source location and the surrounding structure required to interpret a passage. "
            "Original quotations stay separate from normalized search text and generated explanations."
        ),
        "blocks": [
            keyvalue([
                ("Document", "Source-ledger ID, filename, report type, page count, source version, text state, and access state"),
                ("Evidence block", "Original text, searchable text, block type, physical page, printed page when available, and text offsets"),
                ("Relationship", "Links from a result to its parent passage, table context, nearby note, footnote, or continuation"),
                ("Citation", "Block ID, report ID, source version, physical PDF page, printed page, and layout-uncertainty flag"),
                ("Local vector", f"A {index.get('embedding_model') or 'configured local model'} representation tied to one block ID, text hash, and model revision"),
                ("Session", "Role, purpose, permitted report IDs, permitted data groups, and issue time"),
            ]),
            guide(
                "Tables, notes, and page layout",
                [
                    "Table rows are indexed as individual blocks where the existing page-grid material supplies a row. Parent and relation IDs retain the wider section and note context.",
                    "Physical pages remain the primary location because printed footer numbers can restart or differ from the PDF file count. Missing coordinates and uncertain layouts remain explicit limits.",
                    "Text that resembles an instruction inside a report is labeled as source content. It is never executed as a command and receives no automatic context expansion.",
                ],
            ),
        ],
    }


def retrieval_section(demo: dict) -> dict:
    _, evaluation, limits = _index_values(demo)
    metrics = (evaluation.get("metrics") or {}).get("all") or {}
    return {
        "id": "retrieval",
        "title": "Retrieval and context assembly",
        "blurb": (
            "Keyword retrieval is the measured default. Optional local vectors cover the reviewed documents, and reciprocal-rank fusion combines the two rankings when a reviewer selects hybrid search."
        ),
        "blocks": [
            keyvalue([
                ("Candidate passages per method", "40"),
                ("Returned primary passages", "10"),
                ("Combined context budget", "12,000 characters"),
                ("Keyword status", "enabled and selected by default"),
                ("Vector status", str(limits.get("vector_retrieval") or "disabled")),
                ("Default-selection rule", "Hybrid becomes the default only after a held-out improvement without an exact-match or safety regression"),
            ]),
            guide(
                "Question-to-evidence method",
                [
                    "The query is reduced to searchable words and matched only against reports in the active session. Keyword search uses the local full-text index; vector search uses locally stored representations when selected.",
                    "The engine combines result positions rather than treating unlike keyword and vector scores as directly comparable. The top passages then receive permitted parent, row, note, and footnote context.",
                    "A fixed context budget bounds the returned text. Truncated material carries continuation IDs instead of an invented summary.",
                ],
                [
                    ("Keyword", f"{(metrics.get('keyword') or {}).get('passed', 0)} of {(metrics.get('keyword') or {}).get('run', 0)} evaluation cases passed"),
                    ("Keyword plus context", f"{(metrics.get('keyword_context') or {}).get('passed', 0)} of {(metrics.get('keyword_context') or {}).get('run', 0)} evaluation cases passed"),
                    ("Hybrid plus context", f"{(metrics.get('keyword_vector_context') or {}).get('passed', 0)} of {(metrics.get('keyword_vector_context') or {}).get('run', 0)} evaluation cases passed"),
                ],
            ),
            note("Hybrid tied keyword retrieval on the held-out cases. The measured rule therefore retains keyword search as the cheaper default; the local vectors remain available for reviewer-selected semantic queries."),
        ],
    }


def verification_section(demo: dict) -> dict:
    del demo
    return {
        "id": "verification",
        "title": "Field verification and review",
        "blurb": (
            "A single row can contain a correct number and an unsupported date, unit, fee basis, method, or entity assignment. "
            "The engine records a separate decision and evidence list for every claimed field."
        ),
        "blocks": [
            keyvalue([
                ("SUPPORTED", "Retrieved source text contains evidence for the claimed field in the value's context"),
                ("CONTRADICTED", "Retrieved source text prints an incompatible qualifier, such as gross wording for a net claim"),
                ("INSUFFICIENT_EVIDENCE", "The available passages do not establish the claimed field"),
                ("ACCESS_DENIED", "The request includes a report or data group outside the session"),
                ("STALE_SOURCE", "The indexed source version no longer matches the current source"),
                ("MODEL_DISABLED", "A provider assessment was requested without a verified model contract and matching approval"),
            ]),
            guide(
                "Field-check boundaries",
                [
                    "Number matching uses numeric boundaries, so the value 18 does not pass because the source prints 18.2. A blank claimed value has no fact to verify.",
                    "Fee-basis checks require net or gross wording in the matching value context. A rounding note beside the same number supplies no fee-basis evidence.",
                    "Method checks require the printed method name. Date, unit, and entity checks require their wording in the matching value context when a value is also claimed.",
                    "Every assessment is proposed review evidence. The extraction agents and adjudicator retain responsibility for reading the assigned pages and writing or approving the final record.",
                ],
            ),
        ],
    }


def use_cases_section(demo: dict) -> dict:
    del demo
    return {
        "id": "use-cases",
        "title": "Operational use cases",
        "blurb": (
            "The engine serves extraction, adjudication, audit, and analysis through the same permission and citation rules. "
            "Each use returns evidence or existing records; none writes a canonical financial fact."
        ),
        "blocks": [
            guide(
                "Extraction evidence lookup",
                ["An extractor searches an assigned report for a printed label, fund, date, method, or note. The result supplies page-cited passages; the extractor still reviews every assigned page and writes the extraction CSV manually."],
            ),
            guide(
                "Adjudication and audit",
                ["A reviewer searches the disputed value and its qualifiers, opens the cited PDF page, and compares each field. A prior decision never replaces the current source."],
            ),
            guide(
                "Missing-context review",
                ["The engine compares indexed definitions, conditions, fee-basis text, and methods with recorded evidence and proposes items for review. Duplicate, irrelevant, and unsupported suggestions remain outside published data."],
            ),
            guide(
                "Analytical explanation",
                ["Five named, parameter-bound queries return existing extracted or integrated analytical records with origin labels and source references. Arbitrary SQL and an undeclared data group are refused."],
            ),
            guide(
                "Reviewer questions",
                ["A reviewer can ask where a value appears, which note defines it, or which stored result uses it. The response retains the permitted source IDs and physical pages needed for independent inspection."],
            ),
        ],
    }


def evaluation_section(demo: dict) -> dict:
    _, evaluation, _ = _index_values(demo)
    measured = [row for row in (demo.get("measured") or []) if row.get("result") != "unrun"]
    public_cases = len(demo.get("examples") or [])
    total_cases = int(evaluation.get("case_count") or 0)
    rows = [
        [
            str(row.get("case_id") or ""),
            str(row.get("configuration") or ""),
            str(row.get("execution_state") or ""),
            str(row.get("result") or ""),
            str(row.get("label") or ""),
        ]
        for row in measured
    ]
    return {
        "id": "evaluation",
        "title": "Measured evaluation",
        "blurb": (
            "The checked-in evaluation contains exact-wording and meaning-based questions verified against native source pages. "
            "Development and held-out cases remain separated by document."
        ),
        "blocks": [
            keyvalue([
                ("Total cases", thousands(evaluation.get("case_count") or 0)),
                ("Meaning-based paraphrases", thousands(evaluation.get("semantic_case_count") or 0)),
                ("Cases in the static result table", f"{public_cases} of {total_cases}"),
                ("Held-out exact cases", thousands((((evaluation.get("metrics") or {}).get("exact_held_out") or {}).get("keyword") or {}).get("cases") or 0)),
                ("Held-out semantic cases", thousands((((evaluation.get("metrics") or {}).get("semantic_held_out") or {}).get("keyword") or {}).get("cases") or 0)),
                ("Measured conclusion", "Keyword, context, and hybrid passed the current cases; hybrid produced no held-out gain"),
                ("Claim boundary", "These results measure evidence retrieval on the authored cases, not unattended extraction accuracy"),
            ]),
            table(
                "Per-case retrieval results",
                "RAG/evaluation/public-demo.json",
                ["case_id", "configuration", "execution_state", "result", "label"],
                rows,
                about=(
                    "One completed row per source-use-permitted case and retrieval configuration. "
                    f"The static table contains {public_cases} of {total_cases} cases; the others remain in the local evaluation. "
                    "Unrun provider rows stay outside the table and every accuracy denominator."
                ),
                key="evidence-review",
            ),
        ],
    }


def controls_section(demo: dict) -> dict:
    index, _, limits = _index_values(demo)
    return {
        "id": "controls",
        "title": "Access, cost, and failure controls",
        "blurb": (
            "Local operations run on loopback and require a server-issued session. Provider execution remains disabled until a verified model contract and a job-specific approval cover the request."
        ),
        "blocks": [
            keyvalue([
                ("Network address", "127.0.0.1:8765 on this computer only"),
                ("Indexed access", f"{thousands(index.get('indexed_documents') or 0)} searchable reports; {thousands(index.get('restricted_documents') or 0)} restricted report"),
                ("Permission order", "Filter permitted report IDs before keyword search, vector ranking, context expansion, cache access, and analytical reads"),
                ("Source freshness", "Changed source versions are marked stale and withheld from evidence assessment"),
                ("Request size", "HTTP request bodies are limited to 1,000,000 bytes"),
                ("Provider state", str(limits.get("model_requests") or "disabled")),
                ("Public page", "Static data only; zero model requests and zero local-service probes"),
            ]),
            guide(
                "Provider approval boundary",
                [
                    "GPT-5.6 Luna through OpenRouter with Max reasoning is the selected future field-assessment configuration. Its provider identifier, price contract, and job approval remain unset, so the adapter refuses execution.",
                    "A valid approval fixes the operation, provider, model, reasoning setting, report and field scope, request limit, token limits, prices, spending cap, expiration, and authorization reference. Usage and reserved cost are recorded per request.",
                    "The current page, index, keyword search, local vectors, deterministic field checks, and named analytical reads require no provider request.",
                ],
                tone="warn",
            ),
        ],
    }


def console_section(demo: dict) -> dict:
    _, _, limits = _index_values(demo)
    examples = demo.get("examples") or []
    evidence = [
        row for row in (demo.get("evidence") or [])
        if row.get("file_id") not in {"SRC132", "FIX007"}
    ]
    return {
        "id": "console",
        "title": "Evidence console and saved examples",
        "featured": True,
        "blurb": (
            "The local service activates search, field checks, context review, analytical reads, and source-PDF opening. "
            "The static page retains approved questions and excerpts without calling the local service."
        ),
        "blocks": [
            {
                "kind": "rag_console",
                "title": "Local evidence console",
                "about": (
                    "Each request stays inside the reports and data groups fixed by the reviewer session. "
                    "Returned passages retain the report ID, source version, and physical PDF page."
                ),
                "source": "RAG/src/alts_rag/service.py",
                "hybrid_default": bool(limits.get("hybrid_default")),
                "idle_text": "Enter the reviewer session issued when RAG/start-local.ps1 started the service.",
            },
            table(
                "Saved source questions",
                "RAG/evaluation/public-demo.json",
                ["case_id", "split", "query", "file_ids", "expected_pages", "reference_label"],
                [
                    [
                        str(row.get("case_id") or ""),
                        str(row.get("split") or ""),
                        str(row.get("query") or ""),
                        "|".join(row.get("file_ids") or []) if isinstance(row.get("file_ids"), list) else str(row.get("file_ids") or ""),
                        str(row.get("expected_pages") or ""),
                        str(row.get("reference_label") or ""),
                    ]
                    for row in examples
                ],
                about="One authored question per row with its permitted report set and required physical pages.",
                key="evidence-review",
            ),
            table(
                "Approved evidence excerpts",
                "RAG/evaluation/public-demo.json",
                ["file_id", "physical_page", "block_kind", "original_text"],
                [
                    [
                        str(row.get("file_id") or ""),
                        str(row.get("physical_page") or ""),
                        str(row.get("block_kind") or ""),
                        str(row.get("original_text") or "")[:400],
                    ]
                    for row in evidence
                ],
                about="Source-use-checked excerpts embedded in the static page; export-restricted reports are omitted.",
                key="evidence-review",
            ),
        ],
    }


def operations_section(demo: dict) -> dict:
    del demo
    return {
        "id": "operations",
        "title": "Interfaces and reproducibility",
        "blurb": (
            "The command line, local web page, and four agent tools call the same service methods and enforce the same session scope. "
            "The static page is regenerated from the checked-in evaluation export."
        ),
        "blocks": [
            keyvalue([
                ("Start local page", "powershell -File RAG/start-local.ps1"),
                ("Engine status", "python -B -m alts_rag status"),
                ("Build or refresh text index", "python -B -m alts_rag index"),
                ("Build approved local vectors", "python -B -m alts_rag embed"),
                ("Run offline evaluation", "python -B -m alts_rag evaluate --offline"),
                ("Refresh static evidence export", "python -B -m alts_rag export-demo"),
                ("Rebuild this page", "python -B -m src.dashboard.build_rag_dashboard"),
                ("Run RAG tests", "python -B -m pytest -q RAG/tests -p no:cacheprovider"),
            ]),
            heading("Agent tools"),
            keyvalue([
                ("search_sources", "Ranks permitted source passages for a question"),
                ("get_evidence", "Returns full cited blocks already identified by search or assessment"),
                ("verify_claim", "Checks supplied fields or proposes missing-context items for one permitted report"),
                ("explain_analytics", "Runs one named, parameter-bound read over the permitted extracted or integrated data group"),
            ]),
            link("RAG/README.md", "Operating guide", "Repository documentation:"),
            link("RAG/IMPLEMENTATION.md", "Implementation status", "Validation record:"),
        ],
    }


def payload() -> dict:
    demo = _demo()
    builders = (
        overview_section,
        architecture_section,
        evidence_model_section,
        retrieval_section,
        verification_section,
        use_cases_section,
        evaluation_section,
        controls_section,
        console_section,
        operations_section,
    )
    return {
        "title": TITLE,
        "subtitle": SUBTITLE,
        "footer": FOOTER,
        "terms": TERMS,
        "help": HELP,
        "sections": [builder(demo) for builder in builders],
    }


def build(output: Path = OUTPUT) -> tuple[Path, int, int]:
    document = payload()
    output.write_text(render(document), encoding="utf-8", newline="\n")
    return output, len(document["sections"]), sum(len(section["blocks"]) for section in document["sections"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    try:
        output, sections, blocks = build(args.output)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"PASS: {output.name}, {sections} sections, {blocks} panels, {output.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
