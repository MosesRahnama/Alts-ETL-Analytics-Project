# Processing sequence

Each stage preserves its output; transformation receipts record data changes, and [release checks](ledgers/pipeline/release-checks.csv) record executed checks, including those that write no data.

## Source preparation and review

The [category register](docs/EXTRACTION-CATEGORY-COVERAGE.md) separates published documents from additional assignments; source preparation uses the existing document folders and role briefs.

| Operation | Command or role | Output |
|---|---|---|
| Acquire and classify | Acquisition scripts, independent type reviewers | [Source ledger](data-gathering/README.md) |
| Prepare source pages | `python -m src.catalog.build_txt_corpus`; `python data-gathering/src/render_image_corpus.py --published-slice`; `python -m src.catalog.simple_pdf_extraction.build_page_grids` | Text, required page images, and grids |
| Generate instructions | `python -m src.catalog.simple_pdf_extraction.build_csv_pipeline build` | Schema, worklists, and route briefs |
| Prepare additional assignments | Scope changes in `data/schemas/EXTRACTION-DISPATCH-SCOPE.csv`; instruction rebuild; `workflow.py prepare --scope active`; renderer `--pdf`; grid builder `--file-id`; `require-images` | Separate header-only A/B records and coverage files, with every assigned page rendered |
| Extract and review | A/B extraction; `validate-candidate`, `audit-file`, `compare`, source review, `validate-final`, route publication | [Working records](ledgers/working/pdf-extraction-csv/README.md) |
| Prevent repeated source errors | Shared candidate/final checks; table-context review; definition and page-omission checks | Date, owner, fee, method, scope and number-boundary errors refused; currency retained; original proposals retained |
| Apply source corrections | `python -m src.catalog.simple_pdf_extraction.source_review --apply` | Page-backed source review corrections and change log; original A/B files retained |
| Normalize identities and attributes | Name and attribute review commands in the [mapping runbook](instructions/02-fund-mapping/00-OPERATOR-RUNBOOK.md) | Reviewed matrices and stable entity IDs |
| Refresh fund attributes | After publication and initial flatten: `fund_attributes harvest`, `autofill`, `conflicts --strict`, `export`, reviewed `merge`, and `dispatch` | Every observed fund appears in the attribute matrix; portfolio-component labels remain separate |
| Curate benchmarks | `python -m src.market_data.curate_public_markets` | Benchmark candidates rebuilt from retained Parquet files |

## Release command

`python -m src.pipeline.publish_review_release` executes the following stages and then runs the closing reviewer checks.

Publication of an expanded assignment requires completed extraction and review for each added document; prior published data remain available during preparation.

The dashboard's [complete process table](docs/FINAL-RELEASE-AUDIT.csv) starts with source collection, document preparation, independent extraction, and third-reader review. Its consecutive row numbers differ from the internal execution IDs below. [Stage descriptions](docs/RELEASE-STEPS.csv) must match the release script; results come from executed checks. Retained proposal checks verify files and page counts; final validation checks reviewed source fields. A recorded PASS applies to the named check at its stated time, not every financial value or subsequent edit.

| Execution ID | Stage | Main output or refusal |
|---:|---|---|
| 3 | Corpus publication | Published records and coverage must match accepted route files |
| 5 | Extraction scope | Assigned, finished, and unfinished document counts |
| 10 | Raw combination | Per-route raw mirrors |
| 15 | Publication verification | Raw values and model attribution agree with published rounds |
| 20 | Normalization checks | Source corrections, identities, attributes, and decision matrices validate |
| 30 | Flatten | Evidence tables with printed strings and normalized fields |
| 40 | Extraction review | Candidate-to-final origin records and current image index |
| 50 | Wide tables | Reconstructed source rows and observation links |
| 60 | Evidence database | `extracted.duckdb`, checked against CSVs |
| 70 | Attribute audit | Recorded source evidence for inherited attributes |
| 80 | Fund-model promotion | Source-only fund tables; unsupported completion values cannot enter the source master |
| 90 | Promotion check | Source rows have accepted extraction evidence |
| 95 | Source snapshot | `data/extracted/fund-level/`, before generated completion |
| 100 | Integrated completion | Labelled generated data, cell origins, gaps, and reconciliation results |
| 105 | Benchmark rights | Demonstration use and source restrictions enforced |
| 110 | Integrated quality | Source rows checked against source masters; generated rows against completed masters |
| 112 | Source-only quality | Checks before generated completion |
| 115 | Source-only analytics | Metrics supported by quality-approved source inputs |
| 120 | Integrated analytics | Multiples, dated returns, benchmark comparisons, and allocation |
| 130 | Reviewer publication | Flat observations, periods, analytics, gaps, and cell origins |
| 140 | Fund-model database | `alts.duckdb`, checked against CSVs |

The [extraction guide](instructions/01-pdf-extraction-csv/README.md) precedes [identity normalization](data/normalization/README.md), [source-only fund data](data/extracted/fund-level/README.md), [completion](data/integrated/README.md), and [reviewer exports](data/extracted/review/README.md).

## Repository and presentation checks

| Order | Command |
|---:|---|
| 1 | `python -m src.repository.build_release_audit --verify-inputs` |
| 2 | `python -m src.repository.build_release_counts` |
| 3 | `python -m src.repository.build_readmes` |
| 4 | `python -m src.repository.build_csv_lineage` |
| 5 | `python -m src.repository.build_project_manifest` |
| 6 | `python -m src.dashboard.build_dashboard` |
| 7 | `python -m src.repository.build_release_audit --verify-repository` |
| 8 | `python -m src.repository.build_project_manifest` |
| 9 | `python -m src.dashboard.build_dashboard` |
| 10 | `python -m src.repository.build_release_audit --check`; `python -m src.repository.check_project_structure --verify-hashes`; `python -m pytest -q tests/test_release_audit_table.py tests/test_dashboard.py -p no:cacheprovider` |

Step 7 records the structure check, file audit, and full regression suite. Steps 8 and 9 refresh the reviewer dashboard after that record changes; step 10 checks the resulting table and page without rewriting it. These checks test existing files; they do not repeat agent extraction or third-reader decisions.

The separate fixture uses `python -m src.pipeline.build_mock_universe`; it does not supply the integrated reviewer population.
