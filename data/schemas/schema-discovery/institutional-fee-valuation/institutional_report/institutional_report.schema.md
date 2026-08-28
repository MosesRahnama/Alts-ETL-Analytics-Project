# Institutional_Report
Sample: 10 / 71

## document_context: CORE
Grain: `document`
Fields: `institution_name | report_period | as_of_date | currency_or_scale`

## portfolio_snapshot: CORE
Grain: `institution/portfolio-as_of`
Fields: `portfolio_name | portfolio_value | net_assets`

## allocation_record: CORE
Grain: `portfolio-allocation-row-as_of`
Fields: `allocation_name | market_value | actual_allocation_pct | target_allocation_pct`

## performance_record: CORE
Grain: `portfolio/scope-period`
Fields: `scope_name | period_label | return_pct | benchmark_name | benchmark_return_pct | excess_return_pct | inception_date`

## private_market_position: EXTENSION
Grain: `institution-private-investment-as_of`
Fields: `investment_name | manager_name | commitment | contributions | distributions | reported_value | unfunded_commitment | irr | multiple`
