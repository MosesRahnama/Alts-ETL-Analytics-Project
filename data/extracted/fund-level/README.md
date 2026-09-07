# Source-only fund snapshot

Stage 95 writes promoted source tables before completion; stages 112 and 115 add source-only quality results and metrics.

| File | Content |
|---|---|
| `fund_master.csv` | Source identities and supported attributes; generated size, currency, and status excluded |
| `manager_master.csv` | Promoted manager identities with their source class |
| `document_fund_map.csv` | Printed fund names by document and page |
| `document_manager_map.csv` | Manager links by document and page |
| `fund_observations.csv` | Source facts with metric meaning, date, scope, and native location |
| `manager_observations.csv` | Manager-level source facts |
| `fund_periods.csv` | Reported periods, including separately identified investor positions |
| `fund_cashflows.csv` | Dated source events; totals counted once with economic signs |
| `fund_holdings.csv` | Promoted source holdings |
| `fund_terms.csv` | Source term sets where the fund identity and terms support promotion |
| `fund_term_clauses.csv` | Source clauses linked to term sets |
| `quality_results.csv` | Source-only accounting and consistency checks |
| `fund_metrics.csv` | Multiples computed from qualifying source periods, labelled EXTRACTED |

Next: [integrated completion](../../integrated/README.md). Counts: [RELEASE-COUNTS.csv](../../../docs/RELEASE-COUNTS.csv).
