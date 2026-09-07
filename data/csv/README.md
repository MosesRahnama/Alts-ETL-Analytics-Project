# Fund-model CSV tables

The CSVs define the contents of alts.duckdb; source rows, generated rows, and imputed cells retain distinct source classification.

| File | Content |
|---|---|
| `entity_registry.csv` | Standardized entities from document context |
| `manager_master.csv` | Manager identities with EXTRACTED or DERIVED source classification |
| `fund_master.csv` | Source fund identities with completion attributes; each imputed cell recorded in `data/integrated/cell-lineage.csv` |
| `document_fund_map.csv` | Printed fund identity per document and native location |
| `document_manager_map.csv` | Manager identity per document and native location |
| `document_entity_context.csv` | Fund, manager, investor, share-class, and perspective context |
| `fund_observations.csv` | Promoted source facts with page references and defined metric meanings |
| `manager_observations.csv` | Promoted manager-level facts |
| `fund_periods.csv` | Reported periods and generated periods; source class, investor, share class, and currency remain recorded |
| `fund_cashflows.csv` | Source and generated dated economic flows, with separate accounting scope |
| `fund_terms.csv` | Term sets with source classification |
| `fund_term_clauses.csv` | Clauses linked to term sets |
| `fund_holdings.csv` | Source holdings and labelled generated holdings |
| `synthetic_parameters.csv` | qualifying source statistics and declared assumptions, each with its origin class |
| `quality_results.csv` | Accounting and consistency checks; source rows use source-only master attributes |
| `defect_injections.csv` | Planted defect specifications for the isolated overlay |
| `benchmark_returns.csv` | Daily benchmark returns with series IDs and row-level permitted-use disclosures |
| `fund_metrics.csv` | Completed-period multiples and dated returns with formula, input IDs, and SYNTHETIC labels |
| `pme_results.csv` | Public-market equivalent and Direct Alpha comparisons with benchmark and source classification |
| `portfolio_allocations.csv` | Constrained portfolio weights on qualifying funds |

[Source-only tables](../extracted/fund-level/README.md) · [Completion records](../integrated/README.md) · [Reviewer files](../extracted/review/README.md) · [Counts](../../docs/RELEASE-COUNTS.csv)
