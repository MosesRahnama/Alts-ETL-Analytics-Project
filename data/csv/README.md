# Fund-model CSV tables

The CSV files a reviewer can open, and the owner of `alts.duckdb`. Printed rows come from `data/extracted/fund-level/` through the promotion check; the completion stage adds labelled rows and cells on the same fund IDs and explains each one in `data/integrated/`. Every row has `provenance_type`, so a query can keep the two apart.

| File | Rows | Grain and source |
|---|---:|---|
| `entity_registry.csv` | 243 | Standardized entities named in document context |
| `manager_master.csv` | 119 | One manager: 40 `EXTRACTED`, 79 `DERIVED` from the manager round |
| `fund_master.csv` | 934 | One fund per extracted fund ID; `vintage_year` is `IMPUTED` on 623 rows, `strategy` on 419, and `fund_size`, `base_currency`, `fund_size_currency`, and `fund_status` on all 934, each recorded in `data/integrated/cell-lineage.csv` |
| `document_fund_map.csv` | 156 | Printed fund name per document and page |
| `document_manager_map.csv` | 30 | Printed manager name per document and page |
| `document_entity_context.csv` | 238 | Fund, manager, LP, share class, and perspective per document |
| `fund_observations.csv` | 3,803 | Promoted printed facts with page and observation lineage, all `EXTRACTED` |
| `manager_observations.csv` | 55 | Promoted manager-level facts |
| `fund_periods.csv` | 1,312 | 378 `EXTRACTED` printed periods and 934 `SYNTHETIC` completed periods |
| `fund_cashflows.csv` | 6,554 | 16 `EXTRACTED` and 6,538 `SYNTHETIC` dated flows |
| `fund_terms.csv` | 934 | One `SYNTHETIC` term set per fund |
| `fund_term_clauses.csv` | 934 | One `SYNTHETIC` clause per term set |
| `fund_holdings.csv` | 2,834 | 32 `EXTRACTED` and 2,802 `SYNTHETIC` holdings |
| `synthetic_parameters.csv` | 10 | Completion parameters: three `DERIVED` medians from extracted periods and seven `ASSUMED` settings |
| `quality_results.csv` | 35,160 | 23 rules on every fund-model row; 2 `FAIL`, both negatives printed on the page; all 934 completed XIRRs pass |
| `defect_injections.csv` | 12 | Planted defects, one per row, kept in the isolated overlay |
| `benchmark_returns.csv` | 8,394 | SPY daily returns, `DEMO_PROXY_ONLY` |
| `fund_metrics.csv` | 3,736 | DPI, RVPI, TVPI, and XIRR per completed period with formula and input IDs, all `SYNTHETIC`; the source-only multiples are in `data/extracted/fund-level/fund_metrics.csv` |
| `pme_results.csv` | 1,868 | KS-PME and Direct Alpha per completed period against SPY, all `SYNTHETIC` |
| `portfolio_allocations.csv` | 934 | Bounded equal-weight allocation per fund |

Next: [`../extracted/review/README.md`](../extracted/review/README.md).
