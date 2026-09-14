# alts_rag package

Shared engine used by the CLI, MCP adapter, and local HTTP handler.

| File | Role |
|---|---|
| `types.py` | Request and result records. |
| `paths.py` | Runtime and evaluation locations. |
| `policy.py` | Retrieval and source-use settings. |
| `network.py` | Outbound socket refusal. |
| `store.py` | SQLite index and access records. |
| `catalog.py` | Ledger and routing readers. |
| `pages.py` | Physical-page TXT parsing. |
| `tables.py` | Grid row blocks. |
| `permissions.py` | Session issuance and access checks. |
| `approvals.py` | Model-approval records. |
| `indexer.py` | Atomic full and partial text-index builds. |
| `embed.py` | Local embedding-model validation, cache reuse, and atomic vector builds. |
| `retrieval.py` | Permission-first keyword and vector ranking with reciprocal-rank fusion. |
| `citations.py` | Number-boundary quote checks. |
| `context.py` | Result assembly. |
| `assessment.py` | Field assessments. |
| `review.py` | Context-review suggestions. |
| `analytics.py` | Named warehouse lookups. |
| `models.py` | Approval-, token-, and spending-bound OpenRouter adapter. |
| `service.py` | Shared operations. |
| `evaluate.py` | Offline keyword, context, and hybrid case measurements plus the activation decision. |
| `export.py` | Static dashboard export. |
| `cli.py` | Command interface, including approval recording. |
| `serve.py` | Loopback dashboard, JSON operations, and permission-checked PDF handler. |
| `mcp.py` | Model Context Protocol tool adapter over standard input and output. |
