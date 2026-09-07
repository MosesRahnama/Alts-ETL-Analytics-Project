# Schedule_Inv
Sample: 9 / 9

## holding: CORE
One row = one printed investment/security/private-fund position at one holdings date, inheriting the verbatim printed parent portfolio/account context.

| Field | Definition | Document prevalence |
|---|---|---:|
| `parent_entity` | Verbatim printed fund, trust, account, pool, series, reporting manager, or portfolio whose holding belongs to; inherit without normalizing. | 100.0% |
| `as_of_date` | Printed schedule valuation or holdings date applying to the row. | 100.0% |
| `investment_name` | Verbatim printed name or description identifying the investment, security, private fund, currency position, or derivative holding. | 100.0% |
| `asset_type` | Printed high-level asset, security, or instrument class; preserve source wording and section inheritance. | 100.0% |
| `investment_type` | Printed lower-level investment category, strategy, or schedule subgroup. | 66.7% |
| `quantity_raw` | Verbatim printed position quantity, share count, contract count, par/principal amount, or other unit amount. | 66.7% |
| `quantity_type` | Verbatim printed unit type qualifying `quantity_raw`, such as shares, contracts, or principal/par amount. | 66.7% |
| `cost_raw` | Verbatim printed accounting cost, allocated acquisition cost, or source cost for the holding. | 33.3% |
| `fair_value_raw` | Verbatim printed fair value, market value, or reported current value at the as-of date. | 100.0% |
| `currency` | Printed currency or printed source currency context for monetary values. | 55.6% |
| `position_weight_raw` | Verbatim printed holding/pool weight relative to the source-defined fund, portfolio, asset-class, or net-assets denominator. | 44.4% |
| `geography` | Verbatim printed geographic region/country classification; preserve source granularity. | 44.4% |
| `maturity_date` | Printed maturity date for a debt security, TBA, future, swap, or other dated instrument. | 55.6% |
| `interest_rate_raw` | Verbatim printed coupon, stated rate, or variable-rate label; do not back-solve or normalize a missing rate. | 55.6% |
| `restricted_security_flag` | Printed indication that the holding is restricted, a private placement, or designated 144A or restricted in print. | 44.4% |

## position_identifier: EXTENSION
One row = one printed identifier attached to a holding.

| Field | Definition | Document prevalence |
|---|---|---:|
| `identifier_type` | Printed identifier namespace/type, e.g. CUSIP, FIGI, LEI, ISIN, ticker, or other. | 22.2% |
| `identifier_value` | Verbatim printed identifier value paired with `identifier_type`. | 22.2% |

This extension is structurally present in the Form 13F and N-PORT documents in the fixed sample; both are blank templates, so the current sample contains no populated identifier values. It is retained because it clears the 20% extension threshold and provides high-value deterministic linkage.

## derivative_position: EXTENSION
One row = one derivative position child attached to a holding; core holding fields such as `parent_entity`, `as_of_date`, `investment_name`, `asset_type`, and `fair_value_raw` remain on the parent holding row.

| Field | Definition | Document prevalence |
|---|---|---:|
| `derivative_type` | Printed derivative family/type: forward, option, future, swap/swaption, warrant, or other. | 66.7% |
| `derivative_date` | Verbatim printed settlement, expiration, maturity, or termination date. | 66.7% |
| `derivative_date_role` | Printed role of `derivative_date`, so settlement, expiration, and maturity are not conflated. | 66.7% |
| `contract_type` | Verbatim printed option/warrant direction/type such as CALL or PUT. | 55.6% |
| `counterparty` | Verbatim printed derivative counterparty name. | 22.2% |
| `receive_amount_raw` | Verbatim printed amount to be bought/received under an FX or similar derivative contract. | 33.3% |
| `pay_amount_raw` | Verbatim printed amount to be sold/paid under an FX or similar derivative contract. | 33.3% |
| `notional_raw` | Verbatim printed derivative notional amount when separately reported. | 22.2% |

## Discovery decisions

- Final schema: **25 unique fields / 3 record groups / 2 extensions**. No computed or inferred fields are included.
- `cost_raw`, `currency`, position weight, geography, maturity/rate, and restriction status remain in the core despite sub-60% prevalence because they are generic, high-value position context, not publisher-specific structures.
- Private-fund commitment/performance fields from SRC065 and the rich period-activity roll-forward fields from SRC477 were dropped because those structures did not recur independently enough to justify separate record groups.
- N-PORT-only default, arrears, PIK, and liquidity fields were dropped because they occur only as blank template fields in the fixed sample.
- The second-pass dictionary/audit/routes were used only to challenge terminology and gaps. The prior Round-02 25-group holdings schema was not imported; current source evidence controls. `SRC065` remains in this sample because the current `source_ledger.csv` classifies it as `Schedule_Inv`, even though an older routing artifact classified it as `Performance`.
