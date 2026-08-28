# Valuation
Sample: 6 / 6

## document_context: CORE
Grain: `document`
Fields: `issuing_body | report_or_valuation_date | valuation_scope`

## valuation_result: CORE
Grain: `subject-valuation-as_of`
Fields: `subject_name | valuation_date | value_type | fair_value | currency`

## valuation_method: CORE
Grain: `subject-method-as_of`
Fields: `method_name | method_scope | valuation_basis | calibration_reference`

## valuation_input: CORE
Grain: `subject-method-input-as_of`
Fields: `input_name | input_value_raw | unit_or_currency | input_source | reference_date`

## valuation_adjustment: CORE
Grain: `subject-adjustment-as_of`
Fields: `adjustment_type | adjustment_value_raw | adjustment_reference`

## valuation_governance: CORE
Grain: `policy/control`
Fields: `valuer_role | policy_document_name | valuation_frequency | oversight_body | independent_review_party`
