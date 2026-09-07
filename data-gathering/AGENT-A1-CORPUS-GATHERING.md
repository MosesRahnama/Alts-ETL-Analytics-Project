# Agent A1: corpus gathering

## Goal

Reproduce the 442-PDF source library byte for byte, or prepare a reviewed addendum of openly served source documents.

## Read set

1. `data-gathering/README.md`
2. `data-gathering/source_ledger.csv`
3. `data-gathering/document-types.md`
4. `data-gathering/src/README.md`

## Source library

| Family | Files | Visible data |
|---|---:|---|
| Financial statements | 221 | balance sheet, capital, gains, fees, expenses, holdings |
| Institutional and quarterly reports | 107 | fund rows, commitments, NAV, allocations, performance |
| Performance reports | 46 | IRR, TVPI, DPI, RVPI, return series, benchmarks |
| Schedules and statements | 40 | holdings, fees, valuations, NAV, capital activity |
| Legal and diligence documents | 19 | strategy, fees, carry, hurdle, waterfall, term, LP clauses |
| Mission and stewardship reports | 9 | foundation allocations, governance, voting, ESG measures |

## Procedure

```mermaid
flowchart TD
    S["source_ledger.csv<br/>442 IDs, URLs, dates, hashes"] --> V["python -m src.repository.check_project_structure --verify-hashes"]
    V --> G{"442 local PDFs match<br/>ledger filename and SHA-256?"}
    G -- "fail" --> P["python data-gathering/src/fetch_corpus.py --dry-run --timeout 90"]
    P --> D{"ledger URL serves matching bytes?"}
    D -- "yes" --> F["python data-gathering/src/fetch_corpus.py --timeout 90"]
    D -- "changed or unavailable" --> H["hold the file ID<br/>record publisher drift for operator review"]
    F --> V
    G -- "pass" --> C["reconcile doc_type with document-types.csv<br/>and doc-type-audit.csv"]
    C --> CG{"442 file-by-file verdicts agree?"}
    CG -- "fail" --> H
    CG -- "pass" --> R["PASS: 442 PDFs, 17 types, 40,788 pages"]

    N["candidate direct public URL"] --> DL["_acquire_lib.py download<br/>to data/documents/pdf"]
    DL --> FP["_acquire_lib.py full<br/>signature, bytes, hash, page and layout probe"]
    FP --> O{"human review confirms<br/>scope, type, issuer, period, source class?"}
    O -- "fail" --> X["reject candidate before ledger merge"]
    O -- "pass" --> J["reviewed JSON row<br/>unused filename and stable metadata"]
    J --> M["_merge_rows.py reviewed-batch.json"]
    M --> MG{"hash, enum, date, duplicate,<br/>and live-file checks pass?"}
    MG -- "fail" --> J
    MG -- "pass" --> U["operator refreshes TXT, routing, worklists,<br/>repository manifest, and tests"]
```

## Addendum fields

Each accepted row carries `filename`, controlled `doc_type`, tier, issuer, issuer type, jurisdiction, period, direct source URL, retrieval date, SHA-256, layout features, redaction flag, expected field families, source class, wave, strategy, and a review note. Source class is one of `public_filing`, `freely_published`, `foia_release`, `public_domain`, or `model_template`.

## Acceptance gate

The task passes when local files and ledger rows pair 1:1, filenames and hashes are unique, every hash matches, all types use the 17-value enum, page and layout facts are populated, external drift is listed, and the repository hash check passes.

## Response cap

Return at most ten lines: accepted, rejected by reason, duplicate count, source classes, type counts, text-layer counts, pages, bytes, hash gate, and external drift.
