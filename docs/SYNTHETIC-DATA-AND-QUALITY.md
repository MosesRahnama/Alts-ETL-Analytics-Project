# Quality rules and planted-error tests

## Extraction checks

| Check | Failure it blocks | Saved evidence |
|---|---|---|
| Assignment | Wrong file, route, schema, enum, or assignment | Worklist and candidate CSV |
| `validate-candidate` | Malformed records, missing source anchors, or invalid values | Reading-group validator result |
| `audit-file` | Missing physical pages or a page called empty despite grid evidence | Reading-group coverage and audit result |
| `compare` | Unreported disagreement between A and B | `pair-index.csv`, `coverage-diff.csv` |
| Third reader | Unsupported merge or one-sided candidate | `resolution.csv`, `coverage-resolution.csv` |
| `validate-final` and `publish` | Partial files, routes, or corpus output | Final records, final coverage, published rounds |

The 29-document extraction retained 7,369 comparison pairs, 6,111 of them cells both extractors reached. They include 450 value conflicts and 1,258 one-sided candidates; third readers rejected 493 candidates before publishing 7,201 source-backed rows.

## Financial results

| Population | Current result |
|---|---|
| Fund tables before fill | 6,206 rule results; 2 discrepancies, both negatives the page prints in parentheses (SRC060: a fund at inception with NAV of ($1.5) million, and a distribution of ($0.1) million) |
| Integrated review | 35,160 rule results; the same 2 discrepancies |
| Completed periods | 934 periods; zero failed rules and 934 passing XIRR recomputations |
| Integrated defect overlay | 12 isolated errors across six families; 12 detected and zero missed |
| Standalone regression fixture | 800 separate `FUND_SYNTH_` IDs for generator and rule-scale testing |

Two rule behaviours decide those counts. The multiple rules (R02 to R05) read the printed rounding of each input from the evidence cell behind it: a page that prints $90.5 million has stated the value to the nearest hundred thousand, and a page that prints 0.47x has stated it to the nearest hundredth. The tolerance widens by the rounding those printed digits allow, the widened tolerance is written on the result row, and the note says by how much. 312 source-only checks pass inside that widening; a break larger than the page's own rounding still fails. R08 compares a printed IRR only with printed cash flows; the completed periods recompute XIRR from their labelled synthetic cash flows.

| Population | Purpose | Identity |
|---|---|---|
| Extracted snapshot | Keep source-backed fund facts | Real `FUND_` IDs |
| Integrated completion | Add missing attributes, one analytical period, and dated cash flows | The same real `FUND_` IDs |
| Integrated defect overlay | Prove rule detection on a copy that does not mix into the fund-model data | Twelve selected real IDs in an isolated copy |
| Standalone regression fixture | Test generation and rules at 800 funds | Separate `FUND_SYNTH_` IDs |

`build_integrated_universe.py` applies extracted-first precedence, writes every resolution to `gap-ledger.csv`, writes every added cell or row to `cell-lineage.csv`, and refuses publication when identity or financial reconciliation fails. The completed period supplies commitment, paid-in capital, distributions, NAV, unfunded, DPI, RVPI, TVPI, XIRR inputs, NAV rollforward, strategy, vintage, and size. Master attributes the sources leave blank are imputed and labelled `IMPUTED` in the cell fill record: 623 of 934 vintages (seeded draw), 419 of 934 strategies (name keywords), and all 934 fund sizes, currencies, and statuses (declared fallbacks). The isolated overlay plants six error families and requires 100 percent detection.

The 800-fund files under `data/synthetic/` remain a regression fixture and stay out of the final reviewer data and `alts.duckdb`.

## Evidence files

| Evidence | Location |
|---|---|
| A/B candidates, differences, coverage, and third-reader decisions | `ledgers/working/pdf-extraction-csv/` |
| Extraction rollup | `data/extracted/review/document-summary.csv` |
| Source-only quality results | `data/extracted/fund-level/quality_results.csv` |
| Integrated quality results | `data/csv/quality_results.csv` |
| Withheld promotion cells and inherited-attribute changes | `data/extracted/audit/` |
| Planted errors and detection score | `data/integrated/defect-*.csv`, `data/integrated/detection-scorecard.csv` |
| Vocabulary and misfiled-row audit | `audit/metric-vocabulary/` |

The release check keeps source rows, reconciles 279,211 benchmark returns to their source levels, checks reviewer enrichment fill records, and verifies both DuckDB files against their CSV owners.

Next: [`FINAL-RELEASE-AUDIT.md`](FINAL-RELEASE-AUDIT.md).
