# DDQ

Sample: 3 / 3

## document: CORE

One row = one DDQ response package.

| Field | Definition | Document prevalence |
|---|---|---:|
| `manager_name` | Investment manager/adviser name | 3/3 (100.0%) |
| `fund_name` | Fund/product subject to DDQ | 3/3 (100.0%) |
| `as_of_date` | DDQ response or data as-of date | 3/3 (100.0%) |
| `ddq_type` | DDQ/template or diligence package type | 3/3 (100.0%) |
| `fund_structure` | Legal/product structure of fund | 2/3 (66.7%) |
| `fund_domicile` | Fund legal domicile(s) | 2/3 (66.7%) |
| `regulatory_file_number` | Manager regulatory registration identifier | 3/3 (100.0%) |
| `strategy_summary` | Short strategy/product summary | 3/3 (100.0%) |
| `preparer_name` | Named DDQ preparer/reviewer when stated | 2/3 (66.7%) |
| `preparer_title` | Preparer/reviewer title | 2/3 (66.7%) |
| `certification_date` | Date of preparation/review/signature | 2/3 (66.7%) |

## question_response: CORE

One row = one printed question or subquestion and response.

| Field | Definition | Document prevalence |
|---|---|---:|
| `section` | Printed DDQ section/subsection | 3/3 (100.0%) |
| `question_id` | Printed question identifier when present; blank if none | 2/3 (66.7%) |
| `question_text` | Verbatim printed question or prompt | 3/3 (100.0%) |
| `answer_raw` | Manager/fund response to the question | 3/3 (100.0%) |
| `answer_state` | Structured response status where discernible | 3/3 (100.0%) |
| `response_type` | Structural type of response | 3/3 (100.0%) |
| `source_reference` | Printed reference to supporting document/source | 3/3 (100.0%) |
| `subquestion_label` | Printed nested prompt/subsection label when present and useful for preserving question structure | 3/3 (100.0%) |

## quantitative_fact: CORE

One row = one printed quantitative fact or repeating-table measure.

| Field | Definition | Document prevalence |
|---|---|---:|
| `metric_label` | Printed metric/row label within DDQ response | 3/3 (100.0%) |
| `value_raw` | One printed quantitative value verbatim as stated | 3/3 (100.0%) |
| `unit_or_basis` | Printed unit or basis for quantitative value | 3/3 (100.0%) |
| `as_of_date` | As-of date tied to metric if printed | 3/3 (100.0%) |
| `period` | Printed period/horizon tied to metric | 3/3 (100.0%) |
| `programme_or_scope` | Entity/programme scope for metric | 3/3 (100.0%) |
| `row_label` | Verbatim printed row label for repeating table/time-series metric | 2/3 (66.7%) |
| `period_end_or_year` | Printed year/period endpoint for repeated metric row | 2/3 (66.7%) |
| `lower_bound_raw` | Printed lower bound for metric bucket/range when table defines one | 2/3 (66.7%) |
| `upper_bound_raw` | Printed upper bound for metric bucket/range when table defines one | 2/3 (66.7%) |
| `fact_status` | Whether printed metric is an actual, target, minimum, limit, or historical observation | 3/3 (100.0%) |
| `share_class_or_structure` | Printed share class, feeder, structure, or product variant to which metric applies | 2/3 (66.7%) |

## service_provider: EXTENSION

One row = one service-provider relationship.

| Field | Definition | Document prevalence |
|---|---|---:|
| `provider_role` | Service-provider role | 3/3 (100.0%) |
| `provider_name` | Service-provider organization name | 3/3 (100.0%) |
| `provider_location` | Printed provider location when relevant | 3/3 (100.0%) |
| `relationship_duration` | Printed relationship tenure/duration | 2/3 (66.7%) |

## personnel: EXTENSION

One row = one named key-person role.

| Field | Definition | Document prevalence |
|---|---|---:|
| `person_name` | Named key personnel/contact | 3/3 (100.0%) |
| `title_or_role` | Printed title/role | 3/3 (100.0%) |
| `function` | Function tied to named person | 3/3 (100.0%) |
