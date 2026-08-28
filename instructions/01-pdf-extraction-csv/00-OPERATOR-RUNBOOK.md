# Wide-Row PDF Extraction: Operator Runbook

## Contract

- Version: `2026-08-22.2`.
- One record row = one source observation or one whitelisted provision.
- One coverage row = one physical page.
- A and B use identical schemas, routing, grain, categories, and validators.
- J1 handles odd work orders; J2 handles even work orders.

## Current scope

| Scope | Documents |
|---|---:|
| Active core | 29 |
| Deferred secondary | 61 |
| Reference/template | 8 |
| Unscheduled full corpus | 344 |

| Route | Document types | Full corpus | Active | Sessions |
|---|---|---:|---:|---:|
| `01-financials` | Financials | 221 | 5 | 4 |
| `02-performance` | Performance | 46 | 5 | 4 |
| `03-institutional-report` | Institutional_Report | 71 | 5 | 4 |
| `04-quarterly-report` | Quarterly_Report | 36 | 3 | 4 |
| `05-fund-legal-docs` | PPM, LPA, Subscription, Side_Letter, DDQ | 19 | 3 | 4 |
| `06-statements-and-economics` | Schedule_Inv, Fee_Report, Valuation, NAV_Statement, Cash_Flow_Notice, PCAP | 40 | 5 | 4 |
| `07-institutional-mission` | Foundations_Annual, Stewardship_Proxy_Report | 9 | 3 | 4 |

## Rebuild and verify the contract

```powershell
python -m src.catalog.simple_pdf_extraction.build_csv_pipeline build
python -m src.catalog.simple_pdf_extraction.build_csv_pipeline verify
python instructions/01-pdf-extraction-csv/workflow.py verify-contract
```

## Build the page grids

Every worklist row points at a pre-computed table grid in `grid_path`. Build them before dispatching, and rebuild whenever the corpus changes:

```powershell
python -m src.catalog.simple_pdf_extraction.build_page_grids --scope active
```

About 1.5 seconds per document. See `data/documents/grids/README.md` for what the grid does and does not cover; `data/documents/grids/MANIFEST.csv` records which documents produced one and why any did not.

Routing comes from `data-gathering/source_ledger.csv` and is frozen in `data/schemas/EXTRACTION-ROUTING.csv`. `169` corpus documents and `51` currently scheduled documents have stale TXT-header classifications marked `RATIFIED_HEADER_OVERRIDE`; agents never reclassify documents.

To change scope, edit only `data/schemas/EXTRACTION-DISPATCH-SCOPE.csv` and rerun the builder. Valid scope values are `ACTIVE`, `DEFERRED`, `REFERENCE`, and `UNSCHEDULED`.

## Dispatch

For each route, launch:

1. `01-EXTRACTOR-A.md`
2. `02-EXTRACTOR-B.md`
3. `03-ADJUDICATOR-J1.md`
4. `04-ADJUDICATOR-J2.md`

Prompts are under `dispatch-prompts/<route>/`. Each is self-contained.

## Per-file lifecycle

```powershell
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 02-performance --file SRC060 --agent A
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 02-performance --file SRC060 --agent B
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route 02-performance --file SRC060 --agent A
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route 02-performance --file SRC060 --agent B
python instructions/01-pdf-extraction-csv/workflow.py compare --route 02-performance --file SRC060
python instructions/01-pdf-extraction-csv/workflow.py build-final --route 02-performance --file SRC060
python instructions/01-pdf-extraction-csv/workflow.py validate-final --route 02-performance --file SRC060
```

`validate-candidate` proves the file is well formed. `audit-file` proves it is finished: it reports pages with no coverage row, and pages declared empty that the grid resolved into a printed table. Extractors run it themselves after each document; it needs no operator decision.

## Monitor and publish

```powershell
python instructions/01-pdf-extraction-csv/workflow.py status --scope active
```

Consolidation runs in two stages, each checked on its own, so a failure is located before it can spread.

**Stage 1, one round.** Validates every adjudicated document in that round and writes the round's own pair of files. Run it as soon as a round is adjudicated; it never waits for another route and rewrites nothing but its own two files.

```powershell
python instructions/01-pdf-extraction-csv/workflow.py publish --scope active --route 04-quarterly-report
```

- `data/extracted/rounds/<route>-records.csv` (the 42 contract columns plus `extractor_model`)
- `data/extracted/rounds/<route>-coverage.csv`

**Stage 2, the corpus.** Concatenates the published rounds. It reads the round files, not the documents, so what ships is what stage 1 checked.

```powershell
python instructions/01-pdf-extraction-csv/workflow.py publish --scope active
```

- `data/extracted/pdf-wide-records.csv`
- `data/extracted/pdf-wide-coverage.csv`

Both stages block instead of shipping a partial result. Stage 1 fails if any document in the round is missing or fails `validate-final`, naming every bad document at once. Stage 2 fails if a round in scope was never consolidated, and re-derives each round from its documents to compare against the published file, so a round edited or re-adjudicated since it was published is named and blocked instead of leaving stale rows in the corpus.
