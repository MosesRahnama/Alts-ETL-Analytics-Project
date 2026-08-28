# Fee_Report
Sample: 8 / 12

## document_context: CORE
Grain: `document`
Fields: `reporting_entity | report_period | as_of_date | currency_or_scale`

## fee_line_item: CORE
Grain: `investment/manager-period-fee`
Fields: `investment_name | manager_name | asset_class | vintage_year | fee_type | fee_amount | fee_rate | fee_basis`

## fund_economics: CORE
Grain: `investment-period`
Fields: `commitment | contributions | distributions | remaining_value | investment_multiple | net_irr | gross_irr`

## cost_summary: CORE
Grain: `portfolio/asset-class-period`
Fields: `scope_name | total_cost_amount | management_fee_amount | fund_expense_amount | carried_interest_amount | cost_bps | nav_or_aum`

## fee_benchmark: EXTENSION
Grain: `peer-bucket-statistic`
Fields: `strategy_or_vehicle_type | statistic_name | statistic_value_raw | basis`
