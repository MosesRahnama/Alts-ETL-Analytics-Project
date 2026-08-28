# Stewardship_Proxy_Report
Sample: 5 / 5

## document_context: CORE
- `issuer_name`
- `report_name`
- `reporting_period_start`
- `reporting_period_end`
- `publication_date`

## stewardship_policy: CORE
- `policy_topic`
- `policy_or_guideline_name`
- `policy_text`
- `applicability`
- `governance_body`
- `effective_period`

## metric: CORE
Generic quantitative row for stewardship, governance, climate and responsible-investment measures; metric names remain row values, not schema fields.
- `metric_name`
- `dimension`
- `value_raw`
- `unit`
- `target_raw`
- `baseline_raw`
- `coverage_raw`

## engagement: EXTENSION
Recurring company/manager/stakeholder engagement activity, supported across multiple independent reports.
- `related_entity`
- `topic`
- `engagement_date`
- `action_raw`
- `objective_raw`
- `outcome_raw`
- `status_raw`

## proxy_stat: EXTENSION
Recurring aggregate voting/proxy statistics and breakdowns; one row per printed category/metric/dimension.
- `category`
- `metric_name`
- `count_raw`
- `percent_raw`
- `vote_stance`
- `comparison_raw`
- `proposal_topic`

Final consolidation: vote/voting/proxy and engagement/dialogue synonyms were standardized at record-group level while preserving printed labels as row dimensions. Individual vote cases, named initiatives and narrative case studies were not promoted because they were less recurrent or narrative-heavy.
