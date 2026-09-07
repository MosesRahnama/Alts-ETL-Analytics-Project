# AI-Powered Alternative Investment ETL and Analytics

Public investment reports become reviewed evidence, normalized fund records, and reproducible analytics. The corpus contains 442 PDFs across 17 document types; 36 documents have completed extraction, with 8,613 evidence records and 693 covered pages. The [dashboard](dashboard.html) presents the release and explains its data, controls, and analytical results.

## Data populations

| Population | Contents | Files |
|---|---|---|
| Extracted evidence | Printed values and clauses with document, physical page, table position, quote, and independent A/B proposals | [Evidence tables](data/extracted/tables/README.md) |
| Source-only fund data | Reviewed identities, investment positions, dated transactions, and source-supported attributes before generated completion | [Extracted fund tables](data/extracted/fund-level/README.md) |
| Integrated demonstration | Source rows retained alongside labelled generated periods, cash flows, terms, and holdings on the same real fund IDs | [Fund-model CSVs](data/csv/README.md) |
| Regression fixture | Separate generated funds and deliberately damaged copies for testing | [Synthetic fixture](data/synthetic/README.md) |
| Public-market benchmarks | 334 retained Parquet files and 58 benchmark series; published benchmark uses remain demonstration-only | [Market data](data/public_markets/README.md) |

## PDF extraction and review

[Category coverage](docs/EXTRACTION-CATEGORY-COVERAGE.md) lists all 17 report types and the 36 completed documents, including the Apollo prospectus (SRC421) and Packard Foundation tax return (SRC373). Every active assignment has completed extraction and review.

| Method | Control and evidence |
|---|---|
| Page images, text, and grids | Each assigned page has a 300 DPI image; aligned text and coordinate-derived grids identify row labels, stacked headers, values, and footnotes. The page image determines ambiguous layouts. |
| Independent extraction | Two agents produce separate records and page-coverage files; adjudicators resolve disagreements, sample agreements, and review each populated table's scope and governing notes. |
| Mechanical checks | Candidate and final checks reject incomplete page coverage, unsupported dates and accounting scopes, contradictory return headers, ambiguous definition references, and quotes containing only part of a number. |
| Definitions and omissions | Accounting policies, legends, and return-method notes remain extracted records. Grid counts flag empty or sparsely captured tables; exclusions require source-specific reasons. These checks do not replace page review. |
| Dates and accounting scope | Comparative dates retain their printed meaning; source-backed rules resolve slash-date order. Investor positions, whole funds, holdings, and statement lines remain distinct. |
| Entity names | Accounting labels such as Total assets remain statement items; they do not become institutions. A named fund partnership retains its fund identity. |
| Currency | Named currency headings resolve ambiguous dollar symbols. Fund periods retain the denomination; mixed currencies and unconverted foreign inputs are excluded from combined amounts. |
| Corrections | [Source-review decisions](data/normalization/source-review-corrections.csv) record old and new fields with page evidence. Original A/B candidates remain unchanged; source review produces corrected finals. |
| Publication | Current finals must match published records and pass the same completeness checks as candidates. Final construction checks records and coverage before replacing prior outputs. |

The field contract contains 47 columns; publication appends the extractor-model field as column 48. Eighteen record families share the accepted metric and term vocabularies. [Extraction instructions](instructions/01-pdf-extraction-csv/README.md) describe the formats and closing checks; [review records](data/extracted/review/README.md) connect each accepted record to its candidate rows and decision.

## Normalization and fund-level promotion

[Decision matrices](data/normalization/transformations/README.md) state classifications, aliases, scales, date rules, and defaults. Normalized fields sit beside printed strings. Stable entity IDs identify funds and investors; reviewed fund attributes propagate only where source evidence supports them. Promotion reconstructs source-only financial fields from evidence and excludes values retained from generated completion. [Change records](data/extracted/audit/README.md) and [cell origins](data/integrated/README.md) record the resulting changes.

CSV tables are the persisted stage outputs. DuckDB databases are query copies checked against those CSVs: [extracted.duckdb](data/warehouse/extracted.duckdb) contains evidence and reconstructed tables; [alts.duckdb](data/warehouse/alts.duckdb) contains the integrated fund model; [alts_mock.duckdb](data/warehouse/alts_mock.duckdb) contains the separate fixture.

## Quality and analytics

| Area | Method |
|---|---|
| Financial identities | Checks reconcile paid-in capital, distributions, net asset value, commitment, unfunded amounts, multiples, and balance rollforwards. Tolerances reflect printed precision. |
| Dated cash flows | Capital calls have investor-economic signs; component columns and cumulative totals do not become duplicate transactions. Calculations separate funds, investors, classes, and currencies. |
| Source-only metrics | Distribution and residual-value multiples are computed only for source periods with the required inputs and passing quality checks. |
| Generated completion | Missing analytical inputs receive declared assumptions and field-level origin records; generated values are not presented as observed performance. |
| Benchmark comparisons | KS-PME compares contributions and distributions with public-market index growth; Direct Alpha expresses relative performance as an annualized rate. XIRR uses actual cash-flow dates and terminal value. |
| Allocation | A bounded near-equal-weight demonstration, not an estimated risk-optimal portfolio. |
| Error detection | Isolated copies contain planted defects; scorecards identify detected and missed errors without changing the analytical population. |

The negative NAV and distribution printed in SRC060 remain source facts and quality exceptions. Benchmark rights remain restricted to the demonstration. [Quality methods](docs/SYNTHETIC-DATA-AND-QUALITY.md), [release results](docs/FINAL-RELEASE-AUDIT.md), and [current counts](docs/RELEASE-COUNTS.csv) state the measured results and limits.

The [release audit table](docs/FINAL-RELEASE-AUDIT.csv) covers source collection, document preparation, independent extraction, third-reader review, automated publication, and closing checks; each result cites an executed check and its time.

## Reproduction

| Command | Output or check |
|---|---|
| `python -m src.repository.build_release_audit --verify-inputs` | Checks source files, reading aids, retained A/B proposals, and reviewed finals; refreshes the complete process table. |
| `python -m src.pipeline.publish_review_release` | Ordered publication, normalization, fund-model, quality, analytics, reviewer-export, and database stages; receipts record each output. |
| `python -m src.pipeline.reviewer_check` | Source coverage, preservation, source classification, arithmetic, and database checks. |
| `python -m pytest -q` | Regression suite. |
| `python -m src.repository.build_release_audit --verify-repository` | Records structure, release-audit, and regression results; the manifest and dashboard rebuild follow. |
| `python -m src.dashboard.build_dashboard` | Rebuilds the dashboard from the published files. |
| `open-dashboard.cmd` | Rebuilds and opens the local dashboard. |

[PROCESS.md](PROCESS.md) contains the complete command sequence and documentation checks.

## Project folders

| Folder | Contents |
|---|---|
| [data-gathering](data-gathering/README.md) | Acquisition scripts, source ledger, and document classification. |
| [data](data/README.md) | Source files, extracted tables, normalization matrices, completion, benchmarks, and databases. |
| [instructions](instructions/README.md) | Operator procedures, assignments, extraction and review briefs. |
| [ledgers](ledgers/README.md) | Candidate files, decisions, coverage, promotion records, and transformation receipts. |
| [src](src/README.md) | Extraction infrastructure, normalization, data processing, quality, analytics, and dashboard code. |
| [sql](sql/README.md) | Database table and view definitions. |
| [tests](tests/README.md) | Data, finance, workflow, regression, presentation, and repository tests. |
| [config](config/README.md) | Schemas, tolerances, and generation settings. |
| [docs](docs/README.md) | Methods, current results, file manifest, and CSV origin records. |
| [costs](costs/README.md) | Extraction-cost measurements and estimates. |

| Root files | Role |
|---|---|
| `README.md`, `PROCESS.md` | Project summary and reproducible stage order. |
| `dashboard.html` | Current reviewer dashboard. |
| `open-dashboard.cmd`, `open-dashboard.ps1` | Local dashboard launchers. |
| `requirements.txt`, `pytest.ini`, `ruff.toml` | Environment, test, and lint configuration. |
| `.gitignore`, `.gitattributes`, `LICENSE` | Repository policy, large-file tracking, and licence. |

The analytics path reads source-only tables for printed-data metrics and completed tables for generated cash-flow analyses.
