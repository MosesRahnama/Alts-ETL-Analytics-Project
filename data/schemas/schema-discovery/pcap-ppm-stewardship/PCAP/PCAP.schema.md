# PCAP
Sample: 3 / 3

## statement_context: CORE
- `fund_name`
- `investor_lp`
- `period_start`
- `period_end`
- `as_of_date`
- `currency`
- `unit_scale`

## commitment_summary: CORE
- `commitment_amount`
- `paid_in_capital`
- `unfunded_commitment`
- `recallable_distributions`
- `ownership_pct`

## capital_account_summary: CORE
- `beginning_capital`
- `period_contributions`
- `period_distributions`
- `income_loss`
- `realized_gain_loss`
- `unrealized_gain_loss`
- `management_fees`
- `carry_accrual`
- `ending_capital`
- `ending_nav`

## capital_account_activity: EXTENSION
Recurring detailed rows across capital-account, commitment, call and distribution tables; retain printed row/column scopes instead of creating one schema field per accounting line.
- `line_group`
- `line_name`
- `event_date` (optional; only when printed)
- `period_scope`
- `account_scope`
- `amount_raw`
- `percentage_raw` (optional)

Second-pass challenger alignment retained the source-discovered row extension and standardized `investor_lp`, `line_group`, `line_name`, period fields and unit scale. It did not override the sample evidence: the one-document investment schedule, bridge-facility share, percent-called field and redundant total-value field remain dropped.
