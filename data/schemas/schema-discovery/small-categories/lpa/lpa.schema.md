# LPA

Sample: 3 / 3

## document: CORE

One row = one agreement and governed fund.

| Field | Definition | Document prevalence |
|---|---|---:|
| `fund_name` | Fund/vehicle governed or referenced by agreement | 3/3 (100.0%) |
| `general_partner_name` | General partner or equivalent investment manager party | 3/3 (100.0%) |
| `agreement_date` | Agreement date/effective date as printed | 3/3 (100.0%) |
| `governing_law` | Governing law/jurisdiction | 3/3 (100.0%) |
| `partnership_jurisdiction` | Fund/partnership legal jurisdiction and form | 2/3 (66.7%) |
| `term_years` | Initial stated agreement/fund term | 3/3 (100.0%) |
| `extension_terms` | Printed fund-term extension structure | 2/3 (66.7%) |

## economic_term: CORE

One row = one recurring fund-economic term.

| Field | Definition | Document prevalence |
|---|---|---:|
| `term_name` | Standardized name of recurring economic term | 2/3 (66.7%) |
| `value_raw` | Printed economic term value | 2/3 (66.7%) |
| `unit_or_type` | Printed unit/type of economic term | 2/3 (66.7%) |
| `basis` | Printed denominator/basis for economic term | 2/3 (66.7%) |
| `phase_or_period` | Period or phase in which economic term applies | 2/3 (66.7%) |
| `accrual_or_compounding` | Printed accrual/compounding convention for preferred return or similar economic term | 1/3 (33.3%) |
| `offset_or_adjustment` | Printed offset, step-down, reduction, or adjustment mechanism affecting an economic term | 2/3 (66.7%) |

## capital_term: CORE

One row = one capital or commitment mechanic.

| Field | Definition | Document prevalence |
|---|---|---:|
| `capital_term_type` | Standardized capital/commitment mechanic | 2/3 (66.7%) |
| `value_raw` | Printed value for capital mechanic | 2/3 (66.7%) |
| `basis_or_scope` | Printed basis/entity scope of capital mechanic | 2/3 (66.7%) |
| `timing_or_notice` | Printed timing/notice term for capital mechanic | 2/3 (66.7%) |
| `consequence_or_effect` | Printed consequence/effect of capital mechanic | 2/3 (66.7%) |
| `recycling_or_recallability` | Printed rule allowing distributed/unused capital to be recycled or recalled | 2/3 (66.7%) |

## clause: CORE

One row = one governing clause or provision.

| Field | Definition | Document prevalence |
|---|---|---:|
| `section_number` | Printed article/section number | 3/3 (100.0%) |
| `section_heading` | Printed article/section heading | 3/3 (100.0%) |
| `clause_category` | Standardized analytical category for legal provision | 3/3 (100.0%) |
| `operative_text` | Operative legal right, obligation, restriction, representation, or procedure | 3/3 (100.0%) |
| `beneficiary_party` | Party benefiting from the right/protection | 3/3 (100.0%) |
| `obligated_party` | Party bearing the obligation/restriction | 3/3 (100.0%) |
| `effect_type` | Legal/economic effect type | 3/3 (100.0%) |
| `condition_or_trigger` | Printed condition/trigger for provision | 3/3 (100.0%) |
| `parameter_name` | Named quantitative/timing parameter embedded in legal clause | 3/3 (100.0%) |
| `parameter_value_raw` | Printed value verbatim as stated | 3/3 (100.0%) |

## waterfall_tier: EXTENSION

One row = one printed distribution or allocation waterfall tier.

| Field | Definition | Document prevalence |
|---|---|---:|
| `waterfall_context` | Printed waterfall/allocation context | 2/3 (66.7%) |
| `tier_order` | Printed tier sequence/order | 2/3 (66.7%) |
| `tier_recipient` | Printed recipient(s) of tier | 2/3 (66.7%) |
| `allocation_percent_raw` | Printed allocation percentage for tier | 2/3 (66.7%) |
| `threshold_or_condition` | Printed condition for moving through waterfall tier | 2/3 (66.7%) |
| `reference_basis` | Named economic basis referenced by tier | 2/3 (66.7%) |

## execution: CORE

One row = one signature or approval party.

| Field | Definition | Document prevalence |
|---|---|---:|
| `party_role` | Role of executing/approving party | 3/3 (100.0%) |
| `signatory_name` | Printed signatory name when populated | 2/3 (66.7%) |
| `signatory_title` | Printed signatory title/capacity | 3/3 (100.0%) |
| `execution_date` | Execution/approval date | 3/3 (100.0%) |
