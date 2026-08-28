# Source acquisition

The source ledger, acquisition contract, and corpus recovery tools.

| File | Role |
|---|---|
| `source_ledger.csv` | Authoritative source ID, URL, report type, page count, and acquisition metadata. |
| `document-types.csv` | Controlled 17-value document-type list. |
| `document-types.md` | Document-family counts and visible field summary. |
| `AGENT-A1-CORPUS-GATHERING.md` | Guide for agent a1 corpus gathering. |

| Folder | Role |
|---|---|
| `src/` | Download, hash, PDF-probe, merge, and page-render utilities. |

```mermaid
flowchart TD
    U["Public source URLs"] --> A["data-gathering/src/_acquire_lib.py"]
    A --> G{"PDF signature, size, and page probe pass?"}
    G -- "review" --> U
    G -- "accepted" --> L["source_ledger.csv"]
    L --> F["fetch_corpus.py"]
    F --> P["data/documents/pdf"]
    P --> T["text, image, and grid preparation"]
```
