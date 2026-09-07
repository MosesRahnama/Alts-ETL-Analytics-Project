# Clean regression fixture

Standalone `FUND_SYNTH_` managers, funds, periods, cash flows, terms, holdings, benchmarks, parameters, allocations, and zero-failure quality results. The regression fixture remains separate from fund-model data.

| File | Contents |
|---|---|
| `fund_master.csv` | Synthetic fund identities and fixed attributes. |
| `manager_master.csv` | Synthetic manager identities. |
| `fund_periods.csv` | Reconciled fund-period values. |
| `fund_cashflows.csv` | Calls, distributions, fees, and terminal values. |
| `fund_terms.csv` | Synthetic economic terms. |
| `fund_term_clauses.csv` | Synthetic legal-clause records. |
| `fund_holdings.csv` | Synthetic portfolio holdings. |
| `fund_observations.csv` | Long-form synthetic observations. |
| `manager_observations.csv` | Long-form manager observations. |
| `benchmark_returns.csv` | Fixture benchmark returns. |
| `portfolio_allocations.csv` | Fixture portfolio weights. |
| `synthetic_parameters.csv` | Parameters used for generation. |
| `defect_injections.csv` | Header-only proof that the clean population has no planted defect. |
| `quality_results.csv` | Clean-population quality results. |
