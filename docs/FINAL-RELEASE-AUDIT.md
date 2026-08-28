# Release check

The release command validates source files, extraction finals, identity decisions, fund-model promotion, quality results, analytics, reviewer files, and both DuckDB databases.

## Review files

| File | Content |
|---|---|
| [`reviewer-observations.csv`](../data/extracted/review/reviewer-observations.csv) | 7,201 printed facts with source, A/B comparison, decision, and promotion status |
| [`document-summary.csv`](../data/extracted/review/document-summary.csv) | 29-document extraction rollup |
| [`reviewer-fund-periods.csv`](../data/extracted/review/reviewer-fund-periods.csv) | 1,312 periods with source class, quality, attributes, terms, holdings, and analytics |
| [`reviewer-cell-lineage.csv`](../data/extracted/review/reviewer-cell-lineage.csv) | generated and propagated cells with method and input record |
| [`reviewer-gap-ledger.csv`](../data/extracted/review/reviewer-gap-ledger.csv) | completed analytical inputs |
| [`reviewer-analytics-summary.csv`](../data/extracted/review/reviewer-analytics-summary.csv) | distributions, coverage, strategy exposure, and portfolio result |
| [`FINAL-RELEASE-AUDIT.csv`](FINAL-RELEASE-AUDIT.csv) | stage command, input, output, test, status, and handoff |

## Release results

| Measure | Result |
|---|---:|
| Published documents | 29 |
| Covered pages | 311 |
| Published observations | 7,201 |
| Observation-lineage rows | 7,201 |
| Cells found by both extractors | 6,111 |
| Printed value agreements | 5,661, or 92.6 percent |
| Source-only fund periods | 378 |
| Source-only metrics | 804 |
| Completed periods | 934 |
| Integrated metrics | 3,736 |
| PME results | 1,868 |
| Allocations | 934 |
| Release checks | 144 |

## Analytical results

| Population | Result |
|---|---|
| Source-only | 268 quality-approved periods support multiples; median DPI 0.51x, RVPI 0.62x, TVPI 1.21x |
| Integrated demonstration | 934 periods; median DPI 0.60x, RVPI 0.57x, TVPI 1.21x, XIRR 2.13 percent |
| PME demonstration | median KS-PME 0.41x and Direct Alpha -10.18 percent against the SPY demonstration proxy |
| Allocation demonstration | 934 bounded weights and 2.13 percent weighted expected return |

## Release limits

The published extraction contains 29 of 442 catalogued reports. All printed identity classifications are closed; 55 manager fields remain blank with a stated source-silent or no-public-match result. The promotion stage withholds 65 category/value combinations. The integrated population adds labelled source classes to supply dated cash flows and other analytical inputs. SPY is restricted to `DEMO_PROXY_ONLY` and `DEMONSTRATION_ONLY`. Source-only XIRR and PME coverage follows the dated cash flows printed by the source documents.

Rebuild command: `python -m src.pipeline.publish_review_release`.
