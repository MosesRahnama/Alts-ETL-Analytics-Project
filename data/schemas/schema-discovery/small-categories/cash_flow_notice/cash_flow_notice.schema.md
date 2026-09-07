# Cash_Flow_Notice

Sample: 4 / 4

## notice: CORE

One row = one cash-flow notice or event.

| Field | Definition | Document prevalence |
|---|---|---:|
| `event_type` | Type of cash-flow event | 4/4 (100.0%) |
| `fund_name` | Fund or vehicle issuing the notice | 3/4 (75.0%) |
| `investor_lp` | Investor or recipient named on the notice | 2/4 (50.0%) |
| `notice_date` | Date the notice was issued | 4/4 (100.0%) |
| `due_date` | Date by which a call must be funded | 2/4 (50.0%) |
| `event_total_amount_raw` | Total amount due or distributed for the event | 3/4 (75.0%) |

## cash_flow_component: CORE

One row = one printed amount or purpose component within a notice.

| Field | Definition | Document prevalence |
|---|---|---:|
| `component_type` | Printed component or purpose label | 3/4 (75.0%) |
| `amount_raw` | Printed amount for the component | 3/4 (75.0%) |
| `percentage_raw` | Printed percentage when supplied for the component | 3/4 (75.0%) |
| `commitment_impact_flag` | Whether printed text says the component affects commitment | 2/4 (50.0%) |
| `description_raw` | Printed narrative detail supporting a cash-flow component | 3/4 (75.0%) |
| `recipient` | Printed recipient of a cash-flow component | 2/4 (50.0%) |
| `basis_raw` | Printed basis or explanatory qualifier for a component amount | 2/4 (50.0%) |

## capital_account: CORE

One row = one investor/fund capital-account snapshot associated with the event.

| Field | Definition | Document prevalence |
|---|---|---:|
| `commitment_amount_raw` | Investor commitment stated on the notice | 3/4 (75.0%) |
| `prior_funded_amount_raw` | Funded capital before the current notice | 1/4 (25.0%) |
| `prior_unfunded_amount_raw` | Unfunded capital before the current notice | 2/4 (50.0%) |
| `current_call_affecting_commitment_raw` | Current call amount reducing unfunded commitment | 2/4 (50.0%) |
| `post_event_funded_amount_raw` | Funded capital after the current event | 1/4 (25.0%) |
| `post_event_unfunded_amount_raw` | Unfunded commitment after the current event | 2/4 (50.0%) |
| `reinvested_amount_raw` | Amount of otherwise-distributable proceeds reinvested | 1/4 (25.0%) |
| `recallable_distribution_amount_raw` | Previously distributed amount subject to recall | 2/4 (50.0%) |
| `clawback_exposure_amount_raw` | Amount potentially subject to LP recontribution/clawback | 2/4 (50.0%) |

## payment_instruction: EXTENSION

One row = one payment or wire instruction set.

| Field | Definition | Document prevalence |
|---|---|---:|
| `payee_name` | Named wire beneficiary | 2/4 (50.0%) |
| `bank_name` | Receiving bank name | 2/4 (50.0%) |
| `routing_code` | Printed routing or transfer code | 2/4 (50.0%) |
| `account_number` | Receiving account identifier | 2/4 (50.0%) |
| `payment_reference` | Reference/memo text required on payment | 2/4 (50.0%) |
