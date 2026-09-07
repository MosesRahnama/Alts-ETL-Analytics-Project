# Damaged regression fixture

The clean standalone fixture with declared errors, rule results, and `detection_scorecard.csv`. It never feeds fund-model data.

| File | Contents |
|---|---|
| `fund_master.csv` | Synthetic fund identities and fixed attributes. |
| `manager_master.csv` | Synthetic manager identities. |
| `fund_periods.csv` | Fund periods carrying declared test defects. |
| `fund_cashflows.csv` | Calls, distributions, fees, and terminal values. |
| `fund_terms.csv` | Synthetic economic terms. |
| `fund_term_clauses.csv` | Synthetic legal-clause records. |
| `fund_holdings.csv` | Synthetic portfolio holdings. |
| `fund_observations.csv` | Long-form synthetic observations. |
| `manager_observations.csv` | Long-form manager observations. |
| `benchmark_returns.csv` | Fixture benchmark returns. |
| `portfolio_allocations.csv` | Fixture portfolio weights. |
| `synthetic_parameters.csv` | Parameters used for generation. |
| `defect_injections.csv` | Each planted defect, target field, clean value, damaged value, and expected rule. |
| `quality_results.csv` | Quality results for the damaged population. |
| `detection_scorecard.csv` | Detection counts by planted defect family. |
