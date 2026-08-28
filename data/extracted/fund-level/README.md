# Extracted fund-level snapshot

Source-backed fund tables frozen by stage 95 after promotion and before completion; the integration stage reads them and leaves them unchanged.

| File | Content |
|---|---|
| `fund_master.csv` | 934 source-backed fund identities referenced by the promoted tables |
| `manager_master.csv` | Managers printed in the promoted documents |
| `document_fund_map.csv` | Printed fund name per document and page |
| `document_manager_map.csv` | Printed manager name per document and page |
| `fund_observations.csv` | Promoted printed fund facts |
| `manager_observations.csv` | Promoted printed manager facts |
| `fund_periods.csv` | 378 printed periods from 6 documents; 314 carry a vintage and 138 a strategy from the attribute matrix |
| `fund_cashflows.csv` | 16 printed dated flows |
| `fund_holdings.csv` | 32 printed holdings |
| `fund_terms.csv` | Header-only: the published legal documents name the governed fund only as the Fund |
| `fund_term_clauses.csv` | Header-only for the same reason |
| `quality_results.csv` | 6,206 rule results on these tables alone; 2 `FAIL`, both negatives the page prints in parentheses; 312 multiple checks pass inside the printed precision of their inputs, tolerance on the row |
| `fund_metrics.csv` | 804 metrics from 268 quality-approved periods that print paid-in, distributions, and NAV, labelled `EXTRACTED` |

Next: [`../../integrated/README.md`](../../integrated/README.md).
