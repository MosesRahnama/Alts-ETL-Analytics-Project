# Work stages

Stages run in this order. The first block covers operator and review work. `python -m src.pipeline.publish_review_release` runs the 19 data-changing stages in the second block and writes one receipt per command to `ledgers/pipeline/transformation-receipts.csv`. Four upstream controls and two closing checks bring `docs/FINAL-RELEASE-AUDIT.csv` to 25 entries. CSV stage files name each stage; every DuckDB file is derived from its CSVs and checked for parity.

## From source files to names

| Stage | Command or role | Output | Check |
|---|---|---|---|
| Acquire | `data-gathering/src/fetch_corpus.py` | `data/documents/pdf/`, `data-gathering/source_ledger.csv` | SHA-256 per file; 442 rows |
| Type | two typing agents, each on its own file, then audit | `ledgers/doc-type/doc-type-audit.csv`, `data-gathering/document-types.csv` | ledger and audit agree on every file; 17 types |
| Page text | `python -m src.catalog.build_txt_corpus` | `data/documents/txt/` | one TXT page per PDF page |
| Page pictures | `data-gathering/src/render_image_corpus.py` | local `data/documents/images/<stem>/page-001.png` | extraction requires one 300 DPI PNG per physical page; Git tracks the manifest; PNG files stay local because they are large |
| Document grids | `python -m src.catalog.simple_pdf_extraction.build_page_grids` | `data/documents/grids/` | grid manifest names every empty result |
| Survey | `python -m src.catalog.census_field_labels`; family surveys | `ledgers/analysis/`, `data/schemas/schema-discovery/` | field ledgers back every schema column |
| Row format | `python -m src.catalog.simple_pdf_extraction.build_csv_pipeline build`, then `verify` | `data/schemas/`, `instructions/01-pdf-extraction-csv/` worklists and four briefs per route | `workflow.py verify-contract` |
| Extract | briefs `01-EXTRACTOR-A.md`, `02-EXTRACTOR-B.md` | `records-a.csv`, `records-b.csv`, `coverage-a.csv`, `coverage-b.csv` per document | `require-images`, `validate-candidate`, `audit-file` |
| Compare | `workflow.py compare` | `pair-index.csv`, `coverage-diff.csv` | every pair typed VALUE, CLASSIFICATION, CONTEXT, A_ONLY, or B_ONLY |
| Third reader | briefs `03-ADJUDICATOR-J1.md` (odd), `04-ADJUDICATOR-J2.md` (even) | `resolution.csv`, `coverage-resolution.csv`, `records-final.csv`, `coverage-final.csv` | `validate-final`; one decision and reason per pair |
| Publish | `workflow.py publish` | `data/extracted/rounds/`, `pdf-wide-records.csv`, `pdf-wide-coverage.csv` | route drift and round drift refused |
| Identity | `name_normalization` collect, autofill, export, dispatch, merge, conflicts; `entity_ids.py`; manager queue, search each on its own file, auto-decide, third reader, propagate | `data/normalization/` | `conflicts --strict`; `managers` coverage report |
| Attributes | `fund_attributes` collect printed names, autofill, export, dispatch, merge, conflicts | `fund-attributes-matrix.csv` | `conflicts --strict` |

Extraction requires the page pictures. Render the assigned PDF. Then dispatch. Commands: [`data/documents/images/README.md`](data/documents/images/README.md).

Runbooks: [`instructions/01-pdf-extraction-csv/00-OPERATOR-RUNBOOK.md`](instructions/01-pdf-extraction-csv/00-OPERATOR-RUNBOOK.md), [`instructions/02-fund-mapping/00-OPERATOR-RUNBOOK.md`](instructions/02-fund-mapping/00-OPERATOR-RUNBOOK.md).

## Rebuild stages

| Order | Command or function | Result |
|---:|---|---|
| 10 | `python -m src.pipeline.combine_extracted_raw --check` | Verifies adjudicated extraction files; `data/extracted/raw/` is a verification mirror and stays outside stage inputs |
| 15 | `publish_review_release.verify_raw_round_relation` | Matches raw rows to published rounds |
| 20 | `name_normalization check`; `fund_attributes conflicts --strict` | Stops the release on identity or attribute conflicts |
| 30 | `python -m src.flatten.flatten_extracted` | Builds the nine evidence tables |
| 40 | `python -m src.pipeline.build_extraction_review` | Rebuilds the database origin-record table and writes the document summary, reviewer origin records, disagreement fields, trace sample, and reviewer queries under `data/extracted/review/` |
| 50 | `python -m src.flatten.pivot_wide` | Builds the 17 wide tables |
| 60 | `python -m src.flatten.load_star` | Rebuilds `extracted.duckdb` |
| 70 | `python -m src.catalog.simple_pdf_extraction.fund_attributes apply` | Records inherited-attribute evidence; promotion remains the sole writer of fund rows |
| 80 | `python -m src.load.promote_extracted_to_fund_level` | Writes the source-backed fund tables |
| 90 | `python -m src.load.validate_round02_promotion` | Validates promotion origin records |
| 95 | `python -m src.pipeline.build_integrated_universe --snapshot-only` | Writes the copy taken before fill to `data/extracted/fund-level/` |
| 100 | `python -m src.pipeline.build_integrated_universe` | Adds labelled facts on the same fund IDs |
| 105 | `python -m src.load.validate_round02_promotion` | Enforces benchmark rights and demonstration disclosure |
| 110 | `python -m src.quality.run_fund_checks --run-id INTEGRATED_QC_V1` | Runs the 23 rules on the fund-model tables |
| 112 | `python -m src.quality.run_fund_checks --run-id EXTRACTED_QC_V1` | Runs the same rules on the copy taken before fill |
| 115 | `python -m src.analytics.run_extracted_analytics` | Publishes source-only metrics |
| 120 | `python -m src.analytics.run_integrated_analytics` | Publishes metrics, PME, and allocations on the filled fund-date table |
| 130 | `python -m src.pipeline.build_reviewer_publication` | Builds the flat reviewer files |
| 140 | `python -m src.load.load_csv_to_duckdb --rebuild` | Rebuilds `alts.duckdb` and verifies CSV parity |
| Close | `python -m src.pipeline.reviewer_check` | The release checks |
| Dashboard | `python -m src.dashboard.build_dashboard`, or `open-dashboard.cmd` | Builds `dashboard.html` from the published artifacts; `--serve` uses a loopback address |

Precedence is extracted, then derived propagation, then labelled generation; the origin column copies the input period into every metric and PME row, so source-only results have `EXTRACTED` and filled-table results have `SYNTHETIC`. The analytics path reads `data/csv/` alone. The public-market package is a retained input; the closing check ties its 279,211 returns to 279,269 staged levels ([`docs/PUBLIC-MARKET-DATA.md`](docs/PUBLIC-MARKET-DATA.md)). `python -m src.pipeline.transformation_lineage` verifies the optional external archive.

## Folder and file checks

| Command | Checks |
|---|---|
| `python -m src.repository.build_readmes` | writes every generated folder guide; the hand-written ones are listed in the generator |
| `python -m src.repository.build_project_manifest` | records path, size, SHA-256, policy, guide, and role for every file |
| `python -m src.repository.build_csv_lineage` | writes `docs/CSV-LINEAGE.csv`: every CSV with its origin CSV, its module, its agent operation, and that operation's brief |
| `python -m src.repository.check_project_structure --verify-hashes` | guides, manifest, hashes, source ledger |
| `python -m src.repository.release_audit` | a type-specific check on every file, the databases, and the dashboard |

Extraction procedures: [`instructions/01-pdf-extraction-csv/README.md`](instructions/01-pdf-extraction-csv/README.md).
