# NAV_Statement
Sample: 6 / 6

Current population note: all six current `NAV_Statement` documents are Starwood Real Estate Income Trust NAV supplements. The schema therefore standardizes the structures that recur across this population. A 54-page 2025 supplement also contains performance, portfolio/exposure, indebtedness, distribution, financial-statement, and prospectus material; those structures occur in only 1/6 current documents and are deliberately excluded, not imported from older schemas.

Extraction rule: transcribe printed values only. Preserve signs, dollar/percent symbols, wording, dates, units, and table scale; do not calculate, normalize, convert, or back-solve values. Repeating rows are records keyed by their printed dimensions and dates.

## statement_context: CORE
Grain: one record per NAV supplement. Structural context is retained even where it is not itself an investment metric.

| Field | Source labels / examples | Definition |
|---|---|---|
| `issuer_name` | STARWOOD REAL ESTATE INCOME TRUST, INC. | Printed issuer/fund name. |
| `supplement_date` | SUPPLEMENT NO. ... DATED ... | Printed supplement/report date. |
| `transaction_price_effective_date` | July 1, 2024 Transaction Price | Printed effective date attached to the transaction price. |
| `amount_unit_context` | dollars in thousands; shares/units in thousands except per-share/unit data | Printed table-level currency/scale context for raw amounts and share/unit counts. |

## nav_component: CORE
Grain: one printed Components of NAV row per `as_of_date`. Do not create a separate column for every component label.

| Field | Source labels / examples | Definition |
|---|---|---|
| `as_of_date` | May 31, 2024; April 30, 2024 | Printed date for the NAV table column. |
| `component_name` | Investments in real estate; Debt obligations; Net asset value; Non-controlling interests in consolidated entities | Printed NAV component row label, verbatim. |
| `amount_raw` | Components of NAV amounts | Printed amount for the component under that date; no conversion. |

## share_class_nav: CORE
Grain: one printed share class or operating-partnership unit category per `as_of_date`; transaction-price records use the separately printed effective date.

| Field | Source labels / examples | Definition |
|---|---|---|
| `as_of_date` | May 31, 2024; April 30, 2024 | Printed measurement date for class/unit NAV data. |
| `share_class` | Class S; Class T; Class D; Class I; Operating Partnership Units | Printed share class or unit category. |
| `nav_raw` | Net asset value | Printed NAV attributable to the class/unit category. |
| `shares_units_raw` | Number of outstanding shares/units | Printed outstanding share/unit count. |
| `nav_per_share_raw` | NAV Per Share/Unit | Printed NAV per share or unit. |
| `transaction_price_raw` | Transaction Price (per share) | Printed transaction/subscription price per share for the stated effective date. |

## valuation_assumption: CORE
Grain: one property type per valuation `as_of_date`. This is the recurring numeric assumption table, not a narrative valuation-policy record.

| Field | Source labels / examples | Definition |
|---|---|---|
| `as_of_date` | May 31, 2024 | Printed valuation measurement date. |
| `property_type` | Multifamily; Industrial; Office; Other | Printed property-type row/column label. |
| `discount_rate_raw` | Discount Rate | Printed weighted-average DCF discount rate. |
| `exit_cap_rate_raw` | Exit Capitalization Rate | Printed weighted-average exit capitalization rate. |

## valuation_sensitivity: EXTENSION
Why extension: high-value coherent sensitivity matrix recurring in 6/6 current documents, but structurally optional for other NAV-statement families.
Grain: one `property_type` × `assumption_name` × `assumption_change_raw` row per `as_of_date`.

| Field | Source labels / examples | Definition |
|---|---|---|
| `as_of_date` | May 31, 2024 | Printed measurement date. |
| `property_type` | Multifamily; Industrial; Office; Other | Printed property-type dimension. |
| `assumption_name` | Discount Rate; Exit Capitalization Rate | Printed valuation assumption being shocked. |
| `assumption_change_raw` | 0.25% decrease; 0.25% increase | Printed assumption shock. |
| `investment_value_change_raw` | Hypothetical Investment Values | Printed resulting change in investment value. |

## repurchase_liquidity: EXTENSION
Why extension: material semi-liquid vehicle mechanics recurring throughout the current population, but not inherent to every possible NAV statement.
Grain: one printed governing limit/term or one request-period outcome. Keep policy terms and actual request outcomes as source-aligned rows; do not infer unprinted percentages.

| Field | Source labels / examples | Definition |
|---|---|---|
| `request_period` | May 2024; June 2024; May 2025 | Printed period to which an actual repurchase outcome relates. |
| `limit_raw` | 0.33% of NAV per month; 1% of NAV per quarter; 2% of NAV per month | Printed repurchase cap, preserving basis. |
| `frequency_raw` | monthly; quarterly | Printed cadence of the governing limit. |
| `limit_status_raw` | received repurchase requests in excess of the ... limit | Printed status language relative to the cap; blank, never inferred, when absent. |
| `proration_rule_raw` | pro rata basis up to the ... limitation | Printed proration rule or outcome language. |
| `request_satisfaction_raw` | approximately 3%; approximately 4%; all timely submitted repurchase requests ... were satisfied | Printed satisfaction result, preserving percentage or categorical wording. |
| `excess_repurchase_amount_raw` | exceeded the ... limitation by $90,630; $8,820 | Printed exception amount above the stated cap, when present. |

Second-pass challenge result: the prior audit/runtime taxonomy suggested generic performance, exposure, valuation-method, and liquidity groups. Current-source evidence supports NAV/share-class, numeric valuation assumptions/sensitivities, and repurchase mechanics; performance/exposure and broader balance-sheet/prospectus structures remain sparse at 1/6 and are not admitted. Final schema contains 25 unique field names, 6 record groups, and 2 extensions.
