# PPM
Sample: 5 / 7

## document_context: CORE
- `fund_name`
- `issuer_name`
- `manager_name`
- `general_partner`
- `offering_date`
- `jurisdiction`
- `currency`

## investment_mandate: CORE
- `investment_objective`
- `strategy`
- `asset_focus`
- `geography_focus`
- `leverage_borrowing_term`
- `investment_restriction`

## fund_terms: CORE
- `minimum_initial_investment`
- `investor_eligibility`
- `subscription_term`
- `withdrawal_repurchase_term`
- `withdrawal_repurchase_limit`
- `transfer_restriction`
- `distribution_policy`
- `management_fee_rate`
- `performance_fee_or_carry_rate`
- `preferred_return_or_hurdle`
- `expense_cap_or_waiver`
- `valuation_frequency`
- `valuation_method`
- `nav_or_offering_price_basis`

## service_provider: EXTENSION
Recurring role/name relationships across managers, administrators, custodians, distributors, dealer managers and transfer agents.
- `provider_role`
- `provider_name`
- `relationship_scope`

## security_class_terms: EXTENSION
One row per printed share class, series or security type when terms differ. This absorbs class-specific pricing and fees without creating subtype schemas.
- `share_class`
- `security_type`
- `minimum_initial_investment`
- `offering_price_or_basis`
- `upfront_sales_charge`
- `ongoing_distribution_servicing_fee`
- `management_fee_rate`
- `performance_fee_or_carry_rate`
- `withdrawal_repurchase_term`

Final consolidation: minimum investment/subscription synonyms were standardized; redemption, withdrawal, tender and repurchase language maps to the neutral `withdrawal_repurchase_*` family while preserving source wording. Risk/tax prose, person biographies and nonrecurring deal criteria were dropped from the capped schema.
