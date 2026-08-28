# Live counts

| Layer | Release result | Scope |
|---|---|---|
| Source catalog | 442 PDFs, 17 types, 40,788 pages | 29 documents are the reports that were read |
| Published extraction | 29 documents, 311 pages, 7,201 observations | all 29 finished both reading groups, page coverage, comparison, the third reader, and final checks |
| A/B review | 6,111 physical pairs; 5,661 value agreements (92.6 percent) | 450 value conflicts, 2,318 classification conflicts, 3,342 context conflicts, 1,258 one-sided candidates, 493 rejections |
| Vocabulary audit | zero open rows | the 452 SRC457 time-weighted rows once filed as `irr` are re-adjudicated: 130 `irr`, 409 `return` |
| Identity | 1,055 fund-name rows, all decided; 1,008 evidence entities; 956 of 1,011 standards have a general partner | 55 manager fields have a stated source-silent or no-public-match result; no identity classifications remain open |
| Fund-level promotion | 4,284 source rows promoted; snapshot of 934 fund masters, 378 periods, 3,803 fund observations, 16 cash flows, 32 holdings | 65 category/value combinations withheld |
| Filled fund-date table | 934 `SYNTHETIC` periods, 6,538 cash flows, term sets, and 2,802 holdings on the same fund IDs, with gap and cell fill records | `IMPUTED` and labelled: 623 vintages, 419 strategies, all 934 fund sizes, currencies, and statuses |
| Financial quality | 6,206 source-only results with 2 discrepancies, both negatives the page prints; 312 multiple checks pass inside the printed rounding; 934 completed periods pass XIRR recomputation | 35,160 fund-model results with the same 2 discrepancies |
| Analytics | 804 source-only multiples on 268 quality-approved printed periods; 3,736 completed metrics; 1,868 PME rows; 934 allocations | source-only rows have `EXTRACTED`; filled-table rows have `SYNTHETIC`; SPY is restricted to `DEMO_PROXY_ONLY` use |
| Defect test | 12 isolated defects; six of six families detected | the overlay stays outside the fund-model periods |
| Reviewer files | 7,201 observations, 1,312 periods, 36 summary rows, gap and cell fill records | each printed fact links to source and A/B evidence |
| Databases | `extracted.duckdb`, `alts.duckdb`, `alts_mock.duckdb` | each loads from its CSV files and passes content parity checks |
| Dashboard | `dashboard.html`, 11 sections, built from the files above | a static snapshot; rebuild after any data change |

Release reproduction: `python -m src.pipeline.publish_review_release`.

Release audit: [`FINAL-RELEASE-AUDIT.md`](FINAL-RELEASE-AUDIT.md).
