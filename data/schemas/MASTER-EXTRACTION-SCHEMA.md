# Field list for printed cells

Field-list version: `2026-08-22.2`.

## Fixed rules

| Rule | Field list |
|---|---|
| Atomic row | One row is one source observation or one listed operative provision. |
| Table grain | One populated allowed value cell produces one row. A row with N populated allowed value columns produces N rows. |
| Nulls | Blank, dash, em dash, and N/A cells produce no record. |
| Identity | Pair on file, family, page, table, row, column, occurrence, and controlled metric/term category. |
| Coverage | Every physical page appears once in the companion coverage CSV. |
| Routing | `data/schemas/EXTRACTION-ROUTING.csv` is fixed; agents do not reclassify documents. |
| Templates | Template and illustrative documents are routed to the REFERENCE product, never mixed with actual fund observations. |
| Values | Copy printed values as printed. Do not calculate, normalize, convert, back-solve, or infer. |

## Record header

```csv
"contract_version","file_id","source_sha256","canonical_doc_type","route","product_tier","agent_role","record_family","source_page","source_structure_type","source_section","source_table","source_row_label","source_column_label","source_occurrence","subject_type","subject_name","asset_class","strategy","geography","manager_name","investor_name","portfolio_name","vintage_year","period_start","period_end","as_of_date","horizon","currency_scale","metric_category","metric_name","metric_value_raw","unit","term_category","text_raw","basis_raw","condition_raw","evidence_quote","evidence_class","notes","source_agents","adjudication_status"
```

## Coverage header

```csv
"contract_version","file_id","source_sha256","canonical_doc_type","route","product_tier","agent_role","source_page","page_status","layout_checked","source_structures","relevant_record_families","expected_observation_count","records_written","notes"
```

## Document type routes

| Ratified document type | Route | Default product | Allowed record families |
|---|---|---|---|
| `Financials` | `01-financials` | `CORE` | `document_context`, `financial_statement_observation`, `fund_economics_observation`, `position_observation`, `fee_observation`, `financing_observation` |
| `Performance` | `02-performance` | `CORE` | `document_context`, `performance_observation`, `fund_economics_observation`, `cash_flow_observation` |
| `Institutional_Report` | `03-institutional-report` | `CORE` | `document_context`, `performance_observation`, `fund_economics_observation`, `position_observation`, `allocation_observation` |
| `Quarterly_Report` | `04-quarterly-report` | `CORE` | `document_context`, `performance_observation`, `fund_economics_observation`, `allocation_observation`, `cash_flow_observation`, `position_observation` |
| `PPM` | `05-fund-legal-docs` | `CORE` | `document_context`, `legal_term` |
| `LPA` | `05-fund-legal-docs` | `CORE` | `document_context`, `legal_term`, `legal_clause` |
| `Subscription` | `05-fund-legal-docs` | `SECONDARY` | `document_context`, `subscription_reference` |
| `Side_Letter` | `05-fund-legal-docs` | `CORE` | `document_context`, `legal_term`, `legal_clause` |
| `DDQ` | `05-fund-legal-docs` | `CORE` | `document_context`, `ddq_quantitative_observation` |
| `Schedule_Inv` | `06-statements-and-economics` | `CORE` | `document_context`, `position_observation` |
| `Fee_Report` | `06-statements-and-economics` | `CORE` | `document_context`, `fee_observation`, `fund_economics_observation` |
| `Valuation` | `06-statements-and-economics` | `CORE` | `document_context`, `valuation_observation` |
| `NAV_Statement` | `06-statements-and-economics` | `CORE` | `document_context`, `nav_observation`, `valuation_observation` |
| `Cash_Flow_Notice` | `06-statements-and-economics` | `CORE` | `document_context`, `cash_flow_observation`, `fund_economics_observation` |
| `PCAP` | `06-statements-and-economics` | `CORE` | `document_context`, `fund_economics_observation`, `cash_flow_observation` |
| `Foundations_Annual` | `07-institutional-mission` | `SECONDARY` | `document_context` |
| `Stewardship_Proxy_Report` | `07-institutional-mission` | `SECONDARY` | `document_context`, `stewardship_observation`, `stewardship_policy` |

## Record-family grains

| Family | Grain | Required business fields |
|---|---|---|
| `document_context` | one row per document | `subject_name`, `subject_type` |
| `financial_statement_observation` | one populated allowed source value cell | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `performance_observation` | one populated allowed source value cell | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`, `subject_type` |
| `fund_economics_observation` | one populated allowed source value cell | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `position_observation` | one populated allowed source value cell for one named position | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `allocation_observation` | one populated allowed source value cell for one allocation bucket | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `fee_observation` | one populated allowed source value cell | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `cash_flow_observation` | one populated allowed source value cell or one notice component the page states in words | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `nav_observation` | one populated allowed source value cell | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `valuation_observation` | one printed valuation fact or one populated value cell | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `financing_observation` | one populated allowed source value cell | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `legal_term` | one printed term or one numbered provision whose primary meaning matches the whitelist | `term_category`, `text_raw` |
| `legal_clause` | one numbered or separately headed operative provision whose primary meaning matches the whitelist | `term_category`, `text_raw` |
| `ddq_quantitative_observation` | one printed quantitative answer or table value | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `stewardship_observation` | one populated allowed source value cell | `metric_category`, `metric_name`, `metric_value_raw`, `subject_name` |
| `stewardship_policy` | one separately headed operative policy statement | `term_category`, `text_raw` |
| `subscription_reference` | one whitelisted subscription reference fact | `term_category`, `text_raw` |

## Controlled categories

One vocabulary, one row per name: 89 metric names and 30 term names in `EXTRACTION-METRIC-CATEGORIES.csv`, each with a definition, a unit hint, and a preferred family. A metric family fills `metric_category` from the whole metric vocabulary and a term family fills `term_category` from the whole term vocabulary; the family is the table grain and owns no private list. The preferred family is guidance for a mixed table. The document-type to family matrix used by every prompt is `instructions/01-pdf-extraction-csv/FIELD-SELECTION.csv`.

| Family | Kind | Preferred names |
|---|---|---|
| `financial_statement_observation` | metric | `beginning_capital`, `ending_capital`, `cash`, `total_assets`, `total_liabilities`, `net_assets`, `partners_capital`, `net_investment_income`, `investment_fair_value`, `investment_cost`, `fund_expense`, `interest_expense`, `realized_gain_loss`, `unrealized_gain_loss` |
| `performance_observation` | metric | `return`, `irr`, `alpha`, `pme`, `direct_alpha`, `sharpe_ratio`, `tracking_error`, `yield`, `aum` |
| `fund_economics_observation` | metric | `commitment`, `paid_in_capital`, `contribution`, `distribution`, `nav`, `unfunded_commitment`, `recallable_distribution`, `tvpi`, `dpi`, `rvpi`, `moic`, `ownership_percentage`, `income`, `fee`, `carried_interest` |
| `position_observation` | metric | `quantity`, `cost`, `fair_value`, `market_value`, `notional`, `portfolio_weight`, `interest_rate`, `maturity_date` |
| `allocation_observation` | metric | `actual_allocation`, `target_allocation` |
| `fee_observation` | metric | `management_fee`, `performance_fee`, `cost_bps`, `offset`, `fee_benchmark`, `nav_aum_denominator` |
| `cash_flow_observation` | metric | `capital_call`, `return_of_capital`, `preferred_return`, `expense`, `interest`, `net_cash_flow` |
| `nav_observation` | metric | `nav_per_share`, `shares_units`, `transaction_price`, `nav_component`, `repurchase_limit`, `request_satisfaction`, `valuation_assumption`, `valuation_sensitivity` |
| `valuation_observation` | metric | `method`, `frequency`, `valuer`, `oversight`, `independent_review`, `enterprise_value` |
| `financing_observation` | metric | `outstanding_balance` |
| `legal_term` | term | `management_fee`, `carried_interest`, `catch_up`, `waterfall`, `clawback`, `fee_offset`, `organizational_expense`, `recycling`, `fund_term`, `term_extension`, `commitment_period`, `investment_period` |
| `legal_clause` | term | `key_person`, `gp_removal`, `no_fault_termination`, `mfn`, `reporting`, `transfer`, `tax`, `governing_law`, `confidentiality`, `notice` |
| `ddq_quantitative_observation` | metric | `staff_count`, `lockup`, `redemption_notice`, `position_limit`, `leverage`, `liquidity`, `minimum_investment`, `service_provider_count` |
| `stewardship_observation` | metric | `meeting_count`, `vote_count`, `engagement_count`, `coverage`, `score`, `target` |
| `stewardship_policy` | term | `stewardship_policy` |
| `subscription_reference` | term | `subscription_fund`, `general_partner`, `requested_commitment`, `accepted_commitment`, `subscriber_entity_type`, `fund_jurisdiction`, `execution_date` |

## Exclusions

No SSNs/TINs, dates of birth, passport or government-ID numbers, personal bank/wire/routing/account information, signature images, blank form fields, unsupported calculations, generic document transcription, or fields outside the closed contract.
