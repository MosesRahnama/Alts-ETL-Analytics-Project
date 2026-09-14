# Alts RAG engine

Written for a reviewer or engineer who has not used this engine.

Retrieval-augmented generation (RAG) combines source search with evidence review. This engine finds report passages, attaches table rows, notes, and footnotes, checks each claimed field separately, and reads approved analytical tables without changing source PDFs or financial data.

The [RAG reviewer page](../rag.html) holds evaluation cases and the local evidence console. The [main dashboard RAG engine section](../dashboard.html#rag-engine) and [architecture.html](architecture.html) describe the stores, operations, roles, and embedding model. An explanation of information flow and dual-extractor integration is [HOW-RAG-WORKS.md](HOW-RAG-WORKS.md).

| Capability | Verified state |
|---|---|
| Source index | 441 searchable reports, one restricted report, 40,788 pages, and 494,838 page, paragraph, table-row, note, and footnote blocks |
| Retrieval | Keyword search is the default; optional hybrid search adds 4,399 local vectors across the 36 reviewed documents |
| Evaluation | All 35 source-verified cases passed under keyword, keyword plus context, and hybrid retrieval; hybrid produced no held-out gain, so the cheaper keyword method remains the default |
| Field review | Deterministic checks return `SUPPORTED`, `CONTRADICTED`, or `INSUFFICIENT_EVIDENCE` for each claimed value, date, unit, fee basis, or method |
| Extraction use | All 14 A/B route prompts permit the two named source-search tools while retaining full TXT, grid, PNG, and manual CSV rules |
| Access | Every request uses a server-issued role and fixed document set; stale, restricted, and unassigned evidence stays out |
| Interfaces | Command line, Model Context Protocol (MCP), loopback web service, local dashboard controls, and a static public export |
| Provider use | Disabled; historical DeepSeek rows remain labeled and stay outside current metrics |

Runtime files use `%LOCALAPPDATA%\MinaAnalytics\AltsRAG` unless `ALTS_RAG_RUNTIME` names another local directory.

| Command | Result |
|---|---|
| `python -B -m alts_rag status` | Reports index, vector, coverage, and model state without a network request |
| `python -B -m alts_rag index` | Rebuilds the local text index and keeps a failed build from replacing the current index |
| `python -B -m alts_rag prepare-model --source PATH` | Copies and validates an approved local embedding snapshot |
| `python -B -m alts_rag embed` | Builds vectors for the reviewed documents; `--all-documents` expands the scope |
| `python -B -m alts_rag issue-session --role reviewer --purpose review --reviewed-corpus` | Creates a reviewer session over the 36 reviewed documents |
| `python -B -m alts_rag evaluate --offline` | Writes comparable keyword, context, and hybrid measurements |
| `python -B -m alts_rag export-demo` | Writes the permitted static dashboard data |
| `powershell -File RAG/start-local.ps1` | Serves the RAG page and evidence operations on `127.0.0.1:8765`; the main dashboard remains at `/dashboard.html` |
| `python -B -m alts_rag mcp` | Runs the four local agent tools over standard input and output |

The selected reasoning configuration is GPT-5.6 Luna through OpenRouter with Max reasoning. The provider identifier, request contract, pricing, and job approval remain unset, so the adapter refuses execution. `record-approval` records an authorized job but sends no request.

[Implementation status](IMPLEMENTATION.md) records the checks. [Evaluation data](evaluation/README.md) records the cases and results. [Plan](Plan.md) retains the original build contract. [Main dashboard](../dashboard.html) presents the extraction, fund data, quality, and analytics release.
