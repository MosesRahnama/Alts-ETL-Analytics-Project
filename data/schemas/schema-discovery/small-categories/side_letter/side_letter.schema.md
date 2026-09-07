# Side_Letter

Sample: 2 / 2

## document: CORE

One row = one fund-investor side-letter agreement.

| Field | Definition | Document prevalence |
|---|---|---:|
| `letter_date` | Side-letter date | 2/2 (100.0%) |
| `fund_name` | Fund/partnership to which the side letter applies | 2/2 (100.0%) |
| `investor_lp` | Investor receiving the side-letter rights | 2/2 (100.0%) |
| `general_partner_name` | General partner party | 2/2 (100.0%) |
| `manager_name` | Investment manager party when distinct | 2/2 (100.0%) |
| `governing_document_reference` | Underlying agreement(s) supplemented or modified | 2/2 (100.0%) |
| `governing_law` | Law governing the side letter | 2/2 (100.0%) |
| `commitment_amount_raw` | Investor commitment/subscription amount referenced in side letter | 1/2 (50.0%) |

## clause: CORE

One row = one numbered or headed contractual clause.

| Field | Definition | Document prevalence |
|---|---|---:|
| `clause_id` | Printed clause/paragraph number | 2/2 (100.0%) |
| `clause_title` | Printed clause heading | 2/2 (100.0%) |
| `clause_category` | Standardized analytical category assigned to the clause | 2/2 (100.0%) |
| `text_raw` | Operative contractual right, restriction, waiver, representation, or obligation | 2/2 (100.0%) |
| `beneficiary_party` | Party receiving a right/benefit or protection | 2/2 (100.0%) |
| `obligated_party` | Party bearing the obligation/restriction | 2/2 (100.0%) |
| `effect_type` | Legal/economic effect of the clause | 2/2 (100.0%) |
| `base_term_reference` | Printed legal or governing-document reference tied to the clause | 2/2 (100.0%) |
| `condition_raw` | Printed condition or trigger limiting clause operation | 2/2 (100.0%) |

## clause_parameter: EXTENSION

One row = one structured quantitative, reporting, or economic parameter within a clause.

| Field | Definition | Document prevalence |
|---|---|---:|
| `parameter_name` | Type/name of a quantitative or timing parameter embedded in clause | 2/2 (100.0%) |
| `parameter_value_raw` | Printed numeric/rate/duration/threshold value | 2/2 (100.0%) |
| `parameter_basis` | Printed basis to which a parameter applies | 2/2 (100.0%) |
| `notice_timing` | Printed notice/reporting timing or cadence | 2/2 (100.0%) |
| `mfn_comparison_basis` | Printed investor-size/comparison basis for MFN eligibility | 2/2 (100.0%) |
| `reporting_item` | Specific information item contractually required or permitted to be reported/disclosed | 2/2 (100.0%) |
| `economic_term_name` | Named economic term affected, waived, disclosed or restricted by a clause | 1/2 (50.0%) |
| `economic_term_effect` | Contractual effect of clause on named economic term | 1/2 (50.0%) |

## execution: CORE

One row = one signature or countersignature party.

| Field | Definition | Document prevalence |
|---|---|---:|
| `party_role` | Role of execution/countersignature party | 2/2 (100.0%) |
| `signatory_name` | Printed signatory name where populated | 1/2 (50.0%) |
| `signatory_title` | Printed signatory title/capacity | 2/2 (100.0%) |
| `execution_date` | Execution/countersignature date | 2/2 (100.0%) |
