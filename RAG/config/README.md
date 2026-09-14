# RAG configuration

Local retrieval, source-use, embedding, and named-query settings.

| File | Role |
|---|---|
| `retrieval.json` | Keyword, context, local-vector, ranking, and disabled reasoning-model settings. |
| `access.json` | Restricted source IDs for search and public export. |
| `queries.json` | Named analytical lookups. |

Keyword search remains the default because hybrid retrieval did not improve the held-out cases. The reasoning model stays disabled while its provider contract is unverified or the job lacks approval.
