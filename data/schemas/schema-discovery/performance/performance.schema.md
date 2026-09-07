# Performance

Sample: 30 / 46

## performance_metric: CORE
One row = one printed performance, risk, benchmark, valuation, or attribution metric for one entity and reporting horizon.

| Field | Definition | Document prevalence |
|---|---|---:|
| `as_of_date` | Printed reporting or measurement date applying to the metric. | 28/30 (93.3%) |
| `entity_name` | Printed fund, portfolio, manager/composite, share class, asset class, benchmark, investment, or other measured entity. | 29/30 (96.7%) |
| `horizon` | Printed measurement horizon or period label such as quarter, YTD, 1 year, or since inception. | 21/30 (70.0%) |
| `metric_name` | Printed label of an analytically material return, multiple, risk, benchmark-relative, valuation, distribution, exposure, or attribution metric. | 30/30 (100.0%) |
| `metric_value` | Verbatim printed value for `metric_name`; do not calculate or replace it. | 30/30 (100.0%) |
| `unit` | Printed unit, currency, or scale applying to the value, including %, x, bps, currency, millions, or billions. | 30/30 (100.0%) |
| `return_method` | Printed methodology or return type such as TWR, IRR, modified Dietz, money-weighted, or total return. | 28/30 (93.3%) |
| `gross_net_basis` | Printed indication that a reported result is gross, net, or otherwise fee-adjusted. | 24/30 (80.0%) |
| `annualization_basis` | Printed annualized or non-annualized treatment when stated. | 13/30 (43.3%) |
| `benchmark_name` | Printed benchmark, policy index, PME benchmark, peer universe, or comparison series. | 17/30 (56.7%) |

## fund_snapshot: CORE
One row = one private-market fund or partnership snapshot at one as-of date.

| Field | Definition | Document prevalence |
|---|---|---:|
| `as_of_date` | Printed date applying to the fund snapshot. | 28/30 (93.3%) |
| `fund_name` | Printed private-market fund, partnership, or investment name. | 18/30 (60.0%) |
| `manager_name` | Printed manager, sponsor, GP, adviser, or PE house attached to the fund. | 2/30 (6.7%) |
| `vintage_year` | Printed fund vintage year. | 16/30 (53.3%) |
| `strategy` | Printed strategy classification. | 20/30 (66.7%) |
| `commitment` | Printed committed-capital amount. | 18/30 (60.0%) |
| `contributed_capital` | Printed contributed, paid-in, called, or funded capital amount. | 19/30 (63.3%) |
| `distributions` | Printed cumulative distributed-capital amount. | 17/30 (56.7%) |
| `unfunded_capital` | Printed remaining unfunded commitment. | 9/30 (30.0%) |
| `remaining_value` | Printed remaining, fair, reported, current market, or NAV value for the fund. | 25/30 (83.3%) |
| `unit` | Printed currency or scale applying to monetary fields. | 30/30 (100.0%) |

## allocation: CORE
One row = one printed allocation bucket and basis for one entity at one as-of date.

| Field | Definition | Document prevalence |
|---|---|---:|
| `as_of_date` | Printed date applying to the allocation. | 28/30 (93.3%) |
| `entity_name` | Printed portfolio, program, fund, or other entity whose allocation is reported. | 29/30 (96.7%) |
| `allocation_dimension` | Printed allocation dimension such as asset class, strategy, geography, or sector. | 11/30 (36.7%) |
| `allocation_label` | Printed category within the allocation dimension. | 11/30 (36.7%) |
| `allocation_basis` | Printed role of the allocation, such as actual, target, policy, adjusted policy, benchmark, or permitted range. | 8/30 (26.7%) |
| `allocation_value` | Verbatim printed allocation percentage or printed target/policy range. | 11/30 (36.7%) |
| `unit` | Printed unit applying to the allocation value. | 30/30 (100.0%) |

## cash_flow: EXTENSION
One row = one printed cash-flow category for one entity and reported period.

| Field | Definition | Document prevalence |
|---|---|---:|
| `as_of_date` | Printed period-end or reporting date applying to the cash flow. | 28/30 (93.3%) |
| `entity_name` | Printed fund, portfolio, program, strategy, or other entity receiving or generating the cash flow. | 29/30 (96.7%) |
| `horizon` | Printed period label for the cash-flow observation when stated. | 21/30 (70.0%) |
| `cash_flow_type` | Printed category such as contribution, capital call, distribution, withdrawal, fee, transfer, drawdown, realization, or net cash flow. | 14/30 (46.7%) |
| `cash_flow_value` | Verbatim printed amount for the cash-flow category and period. | 14/30 (46.7%) |
| `unit` | Printed currency or scale applying to the cash-flow value. | 30/30 (100.0%) |

## investment_observation: EXTENSION
One row = one underlying holding, deal, realization, drawdown, or case-study investment at one as-of date.

| Field | Definition | Document prevalence |
|---|---|---:|
| `as_of_date` | Printed date applying to the investment observation. | 28/30 (93.3%) |
| `entity_name` | Printed parent fund, portfolio, or program containing the investment observation. | 29/30 (96.7%) |
| `investment_name` | Printed underlying security, portfolio company, property/project, or deal name. | 3/30 (10.0%) |
| `manager_name` | Printed manager, sponsor, GP, adviser, or PE house attached to the investment when stated. | 2/30 (6.7%) |
| `geography` | Printed geography or country for the investment. | 11/30 (36.7%) |
| `investment_value` | Verbatim printed value, proceeds, exposure amount, or other reported monetary value for the investment. | 2/30 (6.7%) |
| `portfolio_weight_pct` | Printed share of portfolio, NAV, exposure, or total fund represented by the investment. | 6/30 (20.0%) |
| `unit` | Printed unit, currency, or scale applying to investment values. | 30/30 (100.0%) |
