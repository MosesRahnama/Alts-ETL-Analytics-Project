# AI-Powered Alternative Investment ETL and Analytics

This repository is an end-to-end alternative-investment ETL and analytics project. Public and FOIA private-market PDF reports are collected from the web: 442 files, 40,788 pages, 17 document types. Each file is classified into one of those 17 categories by two independent agents, with disagreements resolved by an adjudicator. Every report has a page-aligned TXT. For extraction, each physical page is rendered at 300 DPI as a PNG, and page-aligned text and document grids sit next to those pictures so agents can locate table cells on the page image. Extraction is dual-blind (two independent agents); conflicts go to adjudicator agents. Extracted values are cleaned and normalized, and entities receive unique IDs. The printed-cell database (extracted.duckdb) is a 9-table star schema plus 18 reconstructed-source tables, 27 tables in the live file. The fund-model warehouse (alts.duckdb) has 18 tables. The pilot has extracted 29 of 442 documents (7,201 observations); more reports will be added in later updates. Public-market data (334 Parquet files, 58 benchmark series) supports benchmarking. Synthetic completion on the same fund IDs enables Direct Alpha, KS-PME, XIRR, and other performance metrics until vendor data and fuller extraction replace those cells. Every step is designed to be auditable.

## Dashboard

[`dashboard.html`](dashboard.html) lists the reports, 7,201 printed values, the reading checks, the three databases, the fund tables, quality results, performance measures, PME, allocations, benchmark rights, and fill records. Each table defines its row grain and columns; each panel cites its source file.

| Access mode | Artifact |
|---|---|
| Windows launcher | **`open-dashboard.cmd`** |
| Python build and local file | `python -m src.dashboard.build_dashboard --open` |
| Python build and loopback server | `python -m src.dashboard.build_dashboard --serve --open`; address `http://127.0.0.1:8000/` |
| Static snapshot | [`dashboard.html`](dashboard.html); hosted copy at https://mosesrahnama.github.io/Alts-ETL-Analytics-Project/dashboard.html |

`dashboard.html` embeds the published files present at build time. `python -m src.dashboard.build_dashboard` refreshes the snapshot after data changes. The build uses the Python standard library; identical input trees produce byte-identical output.

## Data groups

| Population | Where | Rows | Content |
|---|---|---:|---|
| Source observations | `data/extracted/tables/`, `extracted.duckdb` | 7,201 | one row per printed value, with page, quote, agents, and decision |
| Fund model | `data/csv/`, `alts.duckdb` | 1,312 periods | printed rows marked `EXTRACTED` (378 periods, 3,803 fund observations, 16 cash flows, 32 holdings) next to fill rows marked `SYNTHETIC` (934 periods, 6,538 cash flows, 2,802 holdings) on the same 934 fund IDs, with an origin mark on every row and a fill record for every added cell |
| Regression fixture | `data/synthetic/`, `alts_mock.duckdb` | 800 funds | 800 generated funds for rule and generator tests; they share only the table shapes |

Paid-in capital, distributions, and NAV appear together on 278 printed periods; 268 quality-approved periods produce 804 DPI, RVPI, and TVPI rows labelled `EXTRACTED` in [`data/extracted/fund-level/fund_metrics.csv`](data/extracted/fund-level/fund_metrics.csv). The corpus supplies 16 dated fee cash flows for one position. XIRR, KS-PME, and Direct Alpha run on the filled fund-date table and keep `SYNTHETIC`. Analytics reads `data/csv/`; fund-level promotion is the sole writer of printed rows into that model.

| Review area | Primary artifact |
|---|---|
| Dashboard | [`dashboard.html`](dashboard.html), **`open-dashboard.cmd`** |
| Review files | [`instructions/REVIEWER-GUIDE.md`](instructions/REVIEWER-GUIDE.md) |
| Stage order and checks | [`PROCESS.md`](PROCESS.md), [`instructions/PIPELINE-VISUAL-GUIDE.md`](instructions/PIPELINE-VISUAL-GUIDE.md) |
| Data model | [`docs/DATA-MODEL.md`](docs/DATA-MODEL.md), [`docs/EXTRACTED-DATA-MODEL.md`](docs/EXTRACTED-DATA-MODEL.md) |
| Release evidence | [`docs/FINAL-RELEASE-AUDIT.md`](docs/FINAL-RELEASE-AUDIT.md), [`docs/STATUS.md`](docs/STATUS.md) |
| Audits | [`costs/`](costs/) | Extraction cost measurement and the corpus estimate |

## Corpus

442 public PDFs, 40,788 pages, 17 document types: Financials, Institutional_Report, Performance, Quarterly_Report, Fee_Report, Schedule_Inv, PPM, NAV_Statement, Valuation, Stewardship_Proxy_Report, Cash_Flow_Notice, Foundations_Annual, Subscription, DDQ, LPA, PCAP, Side_Letter. Counts and pages per type: [`data-gathering/document-types.md`](data-gathering/document-types.md). Each file carries a SHA-256, URL, licence note, and page count in [`data-gathering/source_ledger.csv`](data-gathering/source_ledger.csv); two agents typed every file, each on its own file, and [`ledgers/doc-type/doc-type-audit.csv`](ledgers/doc-type/doc-type-audit.csv) holds both verdicts and the final type.

| Page text, pictures, and document grids | Method | Result |
|---|---|---|
| Page-aligned TXT | pdfplumber per page, RapidOCR on image-only pages | 40,566 native pages, 111 OCR pages; [`data/documents/txt/MANIFEST.csv`](data/documents/txt/MANIFEST.csv) |
| Page images | 300 DPI PNG per physical page, written by `data-gathering/src/render_image_corpus.py` | required for extraction; Git tracks the manifest and leaves the PNG files on the local machine because a 300 DPI page is a large file |
| Document grids | document grids for identifying items in the tables with ease in the page image files; `page_grid.py` builds one grid per page | 36 documents; [`data/documents/grids/MANIFEST.csv`](data/documents/grids/MANIFEST.csv) |
| Split-number repair | numbers broken across lines rejoined and audited | [`ledgers/analysis/split_number_audit.csv`](ledgers/analysis/split_number_audit.csv) |

Extraction requires the page pictures. A report is read after every physical page has a PNG. Both reading groups and the third reader open those pictures. Git tracks [`data/documents/images/MANIFEST.csv`](data/documents/images/MANIFEST.csv). The PNG files stay on the local machine because 300 DPI pages are large.

| Job | Command |
|---|---|
| Full corpus | `python data-gathering/src/render_image_corpus.py` |
| The 29 reports already read | `python data-gathering/src/render_image_corpus.py --published-slice` |
| One future PDF | `python data-gathering/src/render_image_corpus.py --pdf Fee_Report_PSERS_Aon_Base_Management_Fees_FY2017.pdf` |

Existing `page-001.png` files are skipped. One PDF goes to `data/documents/images/<stem>/page-001.png` and the later pages. `workflow.py require-images` refuses a file whose picture folder is short. Commands: [`data/documents/images/README.md`](data/documents/images/README.md).

Document grids identify items in the tables with ease in the page image files. Each page image gets a grid that names the printed row and column of every table item, so a reader can open the picture and find the cell. `page_grid.py` writes those grids; the 36-report set is in [`data/documents/grids/MANIFEST.csv`](data/documents/grids/MANIFEST.csv).

## Schema

| Step | Input | Output |
|---|---|---|
| Label census | the text of all 442 documents | 52 recurring value labels with corpus share, [`field_label_census.csv`](ledgers/analysis/field_label_census.csv) |
| Family surveys | sample documents per family, read by hand | file ledger, field ledger, and sample rows per family under [`data/schemas/schema-discovery/`](data/schemas/schema-discovery/) |
| Document inventory | every document typed and its expected fields listed | [`document_field_inventory.csv`](ledgers/analysis/document_field_inventory.csv) |
| Row format | the surveys written into code | [`MASTER-EXTRACTION-SCHEMA.md`](data/schemas/MASTER-EXTRACTION-SCHEMA.md): 42 columns per record (the published rounds append `extractor_model` as a 43rd), 17 record families, 7 routes, one field-selection row per document type |
| Vocabulary | one list, one row per name | 89 metric and 30 term names, each with a definition, unit hint, and usual family, [`EXTRACTION-METRIC-CATEGORIES.csv`](data/schemas/EXTRACTION-METRIC-CATEGORIES.csv); a name outside the list fails validation |

The record family is the table grain (statement, holdings, capital account, allocation) and shares the one list: a metric family accepts any metric name, a term family any term name. The vocabulary audit holds zero open rows: the 452 SRC457 time-weighted return rows once filed as `irr` were re-adjudicated under the banner rule, and SRC457 carries 130 `irr` and 409 `return` rows.

## Extraction

Extraction starts after the assigned PDF has a 300 DPI PNG for every physical page. Two machines type each report, each on its own file (A: claude-sonnet-5; B: gpt-5), each producing a records file and a coverage file. Checks run before a person judges; two third readers (claude-opus-5) pick every pair from the page picture, J1 on odd work orders and J2 on even. Model claims per route: [`ledgers/working/pdf-extraction-csv/<route>/RUN-CLAIM.csv`](ledgers/working/pdf-extraction-csv/).

| Check | Mechanism | Blocks |
|---|---|---|
| Page pictures | `render_image_corpus.py` writes one 300 DPI PNG per physical page; `workflow.py require-images` and `validate-candidate` demand every page | a report whose picture folder is short |
| Assignment | worklist fixes file ID, route, page count, page-text and picture paths, and schema version | a reading group using the wrong file, route, or field list |
| `validate-candidate` | evidence quote must contain the value and appear on the cited TXT page; null-like values, dropped `%` and `x` suffixes, and out-of-vocabulary categories fail | values with no quote, and units dropped from the printed text |
| `audit-file` | one coverage row per physical page; a page called empty is compared with its grid cell count | skipped tables and thin pages |
| `compare` | pairs A and B on a physical five-part key (file, page, row label, column label, occurrence), realigns cited lines and renamed columns, types each conflict as VALUE, CLASSIFICATION, or CONTEXT, and draws a deterministic 10 percent sample of agreements for spot review | unreported disagreement |
| Third reader | `repair-shifted` and `repair-value-format` fix pairing and number-format errors; the third reader writes MERGE, ACCEPT_A, ACCEPT_B, ADD, or REJECT with a reason and the page it looked at | an unsupported merge or a one-sided guess |
| `validate-final` and `publish` | route files, then corpus files, with round-drift detection | partial routes and stale rounds |

| Measure | Count |
|---|---|
| Documents extracted | 29 reports, 311 pages; every assigned report finished both reading groups, page coverage, comparison, the third reader, and final checks |
| Candidate rows A, B | 6,321, 7,159 |
| Physical pairs, value agreements | 6,111, 5,661 (92.6 percent) |
| Conflicts: value, classification, context | 450, 2,318, 3,342 |
| One-sided candidates | 1,258 (210 A only, 1,048 B only) |
| Decisions: merge, accept B, accept A, addition, reject | 5,752, 981, 143, 325, 493 |
| Published observations | 7,201 (249 from image-only evidence) |
| Value kinds | 2,455 number, 2,153 percent, 1,952 currency, 458 multiple, 159 text, 24 none |

Rollup per document: [`data/extracted/review/document-summary.csv`](data/extracted/review/document-summary.csv). Disagreements by field: [`disagreement-fields.csv`](data/extracted/review/disagreement-fields.csv). Every published row back to its A row, B row, pair, decision, and final row: [`observation-lineage.csv`](data/extracted/review/observation-lineage.csv). Every pair and decision: [`ledgers/working/pdf-extraction-csv/`](ledgers/working/pdf-extraction-csv/).

## Identity and manager names

| Step | Method | Result |
|---|---|---|
| Collect printed names | every printed fund, manager, LP, plan, and company name from the published rounds | 1,055 fund-name rows |
| Autofill and worksheets | rows with one spelling are filled by the script; nine normalizers decide the rest by hand | all 1,055 decided; 1,011 standards in 186 sponsor families |
| `conflicts --strict` | one normalization key must map to one standard | 0 conflicts |
| `entity_ids.py` | append-only IDs | 1,213 IDs; 1,008 entities in the evidence tables, 1,454 printed spellings |
| Manager queue | 535 lookups; two web searchers per lookup, each on its own file, each with a public source | 956 of 1,011 standards have a general partner; 55 have a stated source-silent or no-public-match result; none remain open |
| Fund-constant attributes | vintage, strategy, asset class, and geography copied at fund grain from printed context | 853 funds, 0 conflicts, 330 inherited cells, 1,278 recorded changes |

Files: [`data/normalization/`](data/normalization/). Runbook: [`instructions/02-fund-mapping/00-OPERATOR-RUNBOOK.md`](instructions/02-fund-mapping/00-OPERATOR-RUNBOOK.md).

## Promotion and the databases

Promotion wrote 4,284 source rows into the fund tables and withheld 65 cells whose metric category and printed value kind disagree ([`data/extracted/audit/`](data/extracted/audit/)). The copy taken before fill holds 934 fund masters, 378 periods, 3,803 fund observations, 16 cash flows, and 32 holdings ([`data/extracted/fund-level/`](data/extracted/fund-level/)).

| Database | Tables | Content |
|---|---|---|
| [`extracted.duckdb`](data/warehouse/extracted.duckdb) | 9 star tables with foreign keys, 17 wide tables, 1 bridge, 4 views | one row per printed value with page, grid position, quote, agents, and decision |
| [`alts.duckdb`](data/warehouse/alts.duckdb) | 18 fund-model tables, 3 views | fund master, periods, cash flows, terms, holdings, quality results, metrics, PME, allocations, printed and completed rows side by side |
| [`alts_mock.duckdb`](data/warehouse/alts_mock.duckdb) | 18 tables, 3 views | the 800-fund regression fixture |

Each database is rebuilt from its CSVs and checked so each database matches its CSV files both ways. All three are tracked through Git LFS, as are the PDFs, the page text, and the market Parquet files.

## Completion and analytics

The completion stage adds, on the same 934 extracted fund IDs, one `SYNTHETIC` period, seven dated cash flows, a term set, and three holdings per fund, and writes each added cell to [`cell-lineage.csv`](data/integrated/cell-lineage.csv) (49,598 rows) and each filled gap to [`gap-ledger.csv`](data/integrated/gap-ledger.csv) (34,666 rows). Source-backed masters supply 311 vintages and 515 strategies. Where the corpus is silent, the completed row is labelled `IMPUTED`: 623 vintages, 419 strategies, and all 934 fund sizes, currencies, and statuses.

| Population | Result |
|---|---|
| Source only | 268 of 378 periods pass the inputs and quality checks for multiples; median DPI 0.51x, RVPI 0.62x, TVPI 1.21x |
| Filled fund-date table | 934 periods; median TVPI 1.21x, XIRR 2.13 percent |
| PME | KS-PME median 0.41x, Direct Alpha median -10.18 percent against SPY, a proxy restricted to this demonstration |
| Allocation | 934 bounded near-equal weights; volatility and liquidity blank by design |

Quality: 23 rules with tolerances. The multiple rules read the printed rounding of each input from its evidence cell and widen their allowed difference only by that rounding; 312 source-only checks pass inside it, and a larger break fails. The source-only layer records 6,206 results and the integrated layer 35,160. Both retain the same two failures: negative balances printed in parentheses by SRC060. All 934 completed periods pass XIRR recomputation. An isolated copy plants 12 defects across six rule families; all 12 are detected. Method: [`docs/SYNTHETIC-DATA-AND-QUALITY.md`](docs/SYNTHETIC-DATA-AND-QUALITY.md).

## Reproduction

| Command | Result |
|---|---|
| `python -m src.pipeline.publish_review_release` | 19 data-changing rebuild stages with one receipt each; the release audit adds four upstream controls and two closing checks, for 25 entries |
| `python -m src.pipeline.reviewer_check` | the release checks against the published files |
| `python -m pytest -q` | the test suite |
| `python -m src.repository.check_project_structure --verify-hashes` | every folder guide, the manifest, and source hashes |
| `python -m src.repository.release_audit` | a type-specific check on every file, the source ledger, the databases, and the dashboard |
| `python -m src.dashboard.build_dashboard` | `dashboard.html`, rendered from the files above; `open-dashboard.cmd` runs the same build |

## Release limits

All fund, company, and LP identity rows in the published extraction have final classifications. The 29 extracted reports are the reports that were read from the 442-report source ledger. SPY carries `DEMO_PROXY_ONLY` and `DEMONSTRATION_ONLY`, which excludes production use and redistribution. Four statistics derived from one 33-fund real-estate schedule are retained as inactive audit evidence and excluded from released synthetic parameters because a single LP schedule is not a general calibration basis.

## Folders

| Folder | Contents |
|---|---|
| [`data-gathering/`](data-gathering/) | Source ledger, document types, acquisition brief and scripts |
| [`data/`](data/) | PDFs, page text, pictures, and document grids, schemas, extracted evidence, identity matrices, integrated CSVs, market inputs, fixtures, DuckDB files |
| [`instructions/`](instructions/) | Operator runbooks, role briefs, worklists, reviewer guide |
| [`ledgers/`](ledgers/) | Document typing, schema analysis, extraction working files, promotion check, transformation receipts |
| [`src/`](src/) | Acquisition, TXT and grid builders, extraction workflow, normalization, promotion, integration, quality, analytics, release, dashboard |
| [`sql/`](sql/) | DuckDB table definitions |
| [`tests/`](tests/) | Schema, finance, origin records, parity, editorial, dashboard, and structure tests |
| [`config/`](config/) | Schema, financial tolerances, completion settings |
| [`docs/`](docs/) | Status, architecture, data models, market data, quality method, release audit, repository boundary, manifest |
| [`archive/`](archive/) | Pointer to the local artifact backup outside the repository |

| Root file | Role |
|---|---|
| `README.md`, `PROCESS.md` | Landing page and stage order |
| `dashboard.html`, `open-dashboard.cmd`, `open-dashboard.ps1` | The exploration dashboard as last built, and the launcher that rebuilds and opens it |
| `requirements.txt`, `pytest.ini` | Python environment and test settings |
| `.gitignore`, `.gitattributes` | Repository and Git LFS policy |
| `LICENSE` | License |
