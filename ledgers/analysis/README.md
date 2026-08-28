# Analysis

Field inventories, schema surveys, manager evidence, and calibration candidates.

| File | Role |
|---|---|
| `field_label_census.csv` | 52 recurring printed field labels with corpus share, occurrence count, and top document types, used to choose extraction fields. |
| `round1_family_survey_fields.csv` | 392 field observations by document family: where printed, best channel, grain, prevalence, and TXT readability. |
| `document_field_inventory.csv` | One row per catalogued file (537) with routing, parser route, type, tier, issuer, default perspective, and multi-fund flag from the schema survey. |
| `document_type_field_schema.csv` | One row per document type of the pre-ratification survey taxonomy (18) stating typical grain, default perspective, fund-name rule, provided fields, and downstream use; the ratified 17-value list is data-gathering/document-types.csv. |
| `report_subtype_schema.csv` | 26 report subtypes with typical grain and extraction contract from the earlier survey. |
| `split_number_audit.csv` | 57 documents whose TXT rendering split numbers across tokens, with damaged and repaired page counts. |
| `manager_locus_sweep.csv` | 276 candidate manager mentions found by pattern in source text, with page and quote, gathered to seed manager mapping. |
| `derived_manager_ledger.csv` | 109 funds whose manager was derived from the fund-name brand; the origin of the DERIVED rows in manager_master.csv. |
| `model-ledger.csv` | Append-only model claims used to preserve extraction-lane attribution. |
| `synthetic_parameter_candidates.csv` | Four inactive statistics from one LP schedule, retained as audit evidence and excluded from released parameters. |
