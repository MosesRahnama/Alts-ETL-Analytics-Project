# Fund data model

| Table group | Tables | Key boundary |
|---|---|---|
| Identity | `fund_master`, `manager_master`, `entity_registry`, document maps and context | Fund, manager, and investor identities remain distinct |
| Reported facts | `fund_observations`, `manager_observations`, `fund_periods`, `fund_cashflows`, `fund_holdings`, fund terms | Date, currency, investor or share class, and source location accompany each fact |
| Completion | `synthetic_parameters`, integrated gap and cell-origin records | Generated and imputed values remain labelled |
| Quality | `quality_results`, `defect_injections` | Reported discrepancies differ from planted test defects |
| Analytics | `fund_metrics`, `pme_results`, `portfolio_allocations`, `benchmark_returns` | Formula, input IDs, source class, and benchmark policy accompany results |

| Financial measure | Definition |
|---|---|
| Distributions to paid-in capital (DPI) | Cumulative distributions divided by cumulative paid-in capital |
| Residual value to paid-in capital (RVPI) | Net asset value divided by cumulative paid-in capital |
| Total value to paid-in capital (TVPI) | DPI plus RVPI |
| Commitment reconciliation | Paid-in capital plus unfunded commitment minus recallable distributions |
| Net asset value reconciliation | Opening value plus contributions, gains, and income minus distributions, fees, and expenses |
| Dated internal rate of return (XIRR) | Rate that discounts dated cash flows and terminal value to zero |

Investor positions never share cash flows with whole-fund periods; incompatible currencies require a recorded conversion. Printed zero, blank, dash, and inapplicable values remain distinct.

Field lists: [data/csv/README.md](../data/csv/README.md). Extraction model: [EXTRACTED-DATA-MODEL.md](EXTRACTED-DATA-MODEL.md). Completion: [data/integrated/README.md](../data/integrated/README.md).
