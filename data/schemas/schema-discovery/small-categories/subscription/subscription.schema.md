# Subscription

Sample: 4 / 4

## subscription: CORE

One row = one subscriber application or fund interest.

| Field | Definition | Document prevalence |
|---|---|---:|
| `fund_name` | Fund or partnership being subscribed to | 4/4 (100.0%) |
| `general_partner_name` | General partner or managing member | 4/4 (100.0%) |
| `subscriber_legal_name` | Applicant/subscriber legal name | 4/4 (100.0%) |
| `subscription_date` | Date investor executes or submits subscription | 4/4 (100.0%) |
| `requested_commitment_amount_raw` | Amount investor applies to subscribe/commit | 4/4 (100.0%) |
| `accepted_commitment_amount_raw` | Amount accepted by fund/GP when stated | 4/4 (100.0%) |
| `fund_jurisdiction` | Fund legal jurisdiction/formation context | 4/4 (100.0%) |
| `subscriber_entity_type` | Legal form/type of investor | 4/4 (100.0%) |
| `subscriber_jurisdiction` | Investor jurisdiction of formation/governance | 3/4 (75.0%) |
| `ownership_form` | Investor ownership form/capacity selected for the interest | 2/4 (50.0%) |

## qualification_response: CORE

One row = one printed qualification criterion and response.

| Field | Definition | Document prevalence |
|---|---|---:|
| `qualification_type` | Qualification/eligibility regime tested | 4/4 (100.0%) |
| `criterion_label` | Printed eligibility criterion or option | 4/4 (100.0%) |
| `response_raw` | Selected or stated response to criterion | 4/4 (100.0%) |
| `threshold_value_raw` | Printed quantitative eligibility threshold | 4/4 (100.0%) |
| `threshold_basis` | Basis/unit for quantitative threshold | 4/4 (100.0%) |
| `source_rule` | Printed legal/regulatory reference tied to qualification | 4/4 (100.0%) |

## representation: CORE

One row = one contractual representation or acknowledgement.

| Field | Definition | Document prevalence |
|---|---|---:|
| `representation_category` | Category of contractual representation/acknowledgement | 4/4 (100.0%) |
| `representation_text_raw` | Operative representation or acknowledgement text | 4/4 (100.0%) |
| `response_or_status` | Whether representation is affirmative/negative/conditional when structured | 4/4 (100.0%) |
| `update_obligation_flag` | Whether investor must update the information/representation after signing | 4/4 (100.0%) |

## execution: CORE

One row = one signature or acceptance party.

| Field | Definition | Document prevalence |
|---|---|---:|
| `party_role` | Role of executing/accepting party | 4/4 (100.0%) |
| `signatory_name` | Printed signatory name | 4/4 (100.0%) |
| `signatory_title` | Printed signatory title/capacity | 4/4 (100.0%) |
| `execution_date` | Execution/acceptance date associated with a signature | 4/4 (100.0%) |
| `acceptance_status` | Subscription acceptance/rejection status | 4/4 (100.0%) |

## payment_instruction: EXTENSION

One row = one subscription or distribution payment-instruction set.

| Field | Definition | Document prevalence |
|---|---|---:|
| `payment_direction` | Contribution/subscription or distribution direction | 4/4 (100.0%) |
| `bank_name` | Receiving bank when printed/provided | 3/4 (75.0%) |
| `routing_code` | Printed routing identifier when present | 3/4 (75.0%) |
| `account_identifier` | Printed receiving account identifier when present | 3/4 (75.0%) |
| `payment_reference` | Printed payment reference/memo requirement when present | 3/4 (75.0%) |
