# Quarterly_Report
Sample: 10 / 36

## report_context: CORE

| Field | Definition |
|---|---|
| `report_title` | Printed title identifying the quarterly or periodic report. |
| `period_end` | Printed quarter-end or as-of date governing the reported data. |
| `reporting_entity` | Printed institution, plan, fund, or reporting organization. |
| `portfolio_name` | Printed portfolio, product, program, composite, or asset-class sleeve being reported. |

## portfolio_summary: CORE

| Field | Definition |
|---|---|
| `market_value` | Printed market value, NAV, fair value, or equivalent current portfolio value. |
| `allocation_pct` | Printed current portfolio allocation percentage. |
| `target_allocation_pct` | Printed policy or target allocation percentage. |
| `monetary_unit` | Printed currency and monetary scale applying to portfolio amounts. |

## performance_series: CORE

| Field | Definition |
|---|---|
| `performance_scope` | Printed portfolio, asset class, strategy, manager, or fund scope for the metric. |
| `period_label` | Printed performance horizon such as quarter, YTD, 1-year, 5-year, or inception. |
| `metric_name` | Printed performance or risk metric label, including return, IRR, TVPI, Sharpe, beta, or yield. |
| `metric_value` | Printed value corresponding to `metric_name`. |
| `benchmark_name` | Printed benchmark, policy index, or peer universe associated with the metric. |
| `benchmark_value` | Printed benchmark value for the same reported horizon or metric. |
| `performance_basis` | Printed gross/net or fee basis applying to the performance figure. |

## period_activity: CORE

| Field | Definition |
|---|---|
| `activity_scope` | Printed portfolio, program, asset-class, or manager scope for the activity row. |
| `activity_type` | Printed activity label such as capital call, contribution, distribution, NAV change, net cash flow, or commitment. |
| `activity_value` | Printed value corresponding to `activity_type`. |
| `activity_unit_context` | Printed currency, scale, or unit applying to `activity_value`. |

## fund_performance: EXTENSION

| Field | Definition |
|---|---|
| `fund_name` | Printed fund, partnership, or investment name. |
| `vintage_year` | Printed fund vintage year. |
| `investment_strategy` | Printed strategy, fund type, or asset-class label. |
| `fund_measure_name` | Printed recurring fund measure such as commitment, paid-in, distributions, unfunded, NAV, DPI, TVPI, or IRR. |
| `fund_measure_value` | Printed value corresponding to `fund_measure_name`. |
| `fund_unit_context` | Printed currency, scale, percent, or multiple unit applying to the fund measure. |

## exposure_breakdown: EXTENSION

| Field | Definition |
|---|---|
| `exposure_dimension` | Printed dimension used to segment the portfolio, such as asset class, strategy, geography, sector, vintage, or manager. |
| `exposure_bucket` | Printed category within `exposure_dimension`. |
| `exposure_measure` | Printed measure for the bucket, such as market value, NAV, unfunded, total exposure, portfolio weight, benchmark weight, or AUM. |
| `exposure_value` | Printed value corresponding to `exposure_measure`. |
| `exposure_unit_context` | Printed currency, scale, percent, or other unit applying to the exposure value. |
