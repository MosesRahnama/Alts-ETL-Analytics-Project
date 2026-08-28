# Extracted fields, one by one

Field-list `2026-08-22.2`. Companion to `MASTER-EXTRACTION-SCHEMA.md`,
which states the same field list for code. This file is written for a
reader: every field appears on its own line with what it means, followed by
what each document type produces.

Generated from the field list. Edit `src/catalog/simple_pdf_extraction/field_guide.py`, then rebuild.

## The unit of one row

One row is one fact printed in one place: a single value cell in a table, or a
single whitelisted provision in a legal document. A table row with five
populated columns produces five rows, each carrying its own column label. A
blank, a dash, or an N/A produces no row at all.

Every value is copied verbatim as printed. Nothing is calculated, converted,
rounded, or inferred. If the page does not state it, the field stays blank.

There are 42 fields on every row. Most are blank on any given
row, because a field only applies where the page supports it.

## IDs the work fills

Written by the work from the worklist. An extractor copies these from that list.

- `contract_version`: Which release of this field list the row was written under. Filled by the workflow.
- `file_id`: The corpus identifier of the source document, such as SRC377.
- `source_sha256`: SHA-256 of the source PDF, binding the row to one binary. A mismatch means the document changed and the extraction is void.
- `canonical_doc_type`: The listed type, such as Financials or PPM. Readers keep the listed type.
- `route`: The reading group the document belongs to, derived from its type.
- `product_tier`: CORE, SECONDARY, or REFERENCE. Controls what evidence classes are acceptable and keeps template material out of the fund dataset.
- `agent_role`: Which blind extractor wrote the row, A or B. Becomes ADJUDICATED on a final row.

## Printed address of the value

The physical address of the fact inside the document. Two extractors reading the same cell must map to the same address, which is what makes their work comparable.

- `record_family`: What kind of fact this row is, chosen from the closed family list. Follows the table the value sits in, not the document type.
- `source_page`: The physical PDF page number the value is printed on.
- `source_structure_type`: The kind of layout the value came from: TABLE, FIGURE, NARRATIVE, FORM, FOOTNOTE, SCHEDULE, or DOCUMENT. Always uppercase.
- `source_section`: The printed section heading above the table, such as Statements of Financial Position.
- `source_table`: The printed table or figure title that names the whole table. Never a date and never a heading that covers only some columns.
- `source_row_label`: The printed row label the value sits on. The primary physical anchor for a value.
- `source_column_label`: The printed column header the value sits under, taken from the lowest header directly above the column. Kept unique within a row, so stacked headers such as 1-Yr Total Return are preserved whole.
- `source_occurrence`: Which instance this is when the same row and column labels repeat on one page, counted top to bottom then left to right. Normally 1.

## Subject of the value

The entity the number describes, and the analytical dimensions a reviewer filters on.

- `subject_type`: What kind of thing the row measures, in lowercase, from the closed list. Read from the row's own printed label, not decided once per document.
- `subject_name`: The printed name of the thing being measured: the fund, portfolio, position, asset class, or benchmark named on that row.
- `asset_class`: The printed asset class governing the row, such as Private Equity or Fixed Income. Taken from the group heading, table title, or document statement that covers the row. A core analytical dimension: fill it whenever the page states it, never infer it, and never restate the row label here.
- `strategy`: The printed strategy governing the row, such as Buyout, Venture, or Core Real Estate. Same sourcing rule as asset class.
- `geography`: The printed geographic scope governing the row, such as North America or Europe. Same sourcing rule as asset class.
- `manager_name`: The printed manager or general partner. Recorded once on the document row, not repeated on every observation.
- `investor_name`: The printed asset owner, verbatim as the page renders it. Recorded once on the document row.
- `portfolio_name`: The printed portfolio or programme the document reports on. Recorded once on the document row.
- `vintage_year`: The printed vintage year of the fund on that row.

## Dates, scale, and units

These fields place the number in time and make the number usable.

- `period_start`: The printed start of the period the value covers.
- `period_end`: The printed end of the period the value covers.
- `as_of_date`: The printed date the value is stated as of, in the fullest printed form. December 31, 2015, not 2015, and never reformatted to ISO.
- `horizon`: The printed measurement period for a return or risk figure, such as 1-Yr, 5 Year, ITD, or Fiscal YTD 9 Months. Required whenever the column header carries a period qualifier.

## The measurement itself

The fact being captured, and everything needed to read it correctly.

- `currency_scale`: The printed currency and scale statement that makes the number readable, such as $ in millions, copied verbatim including any parentheses.
- `metric_category`: What the value measures, chosen from the one metric vocabulary by the printed meaning; the family says where the cell sat, the category says what it is. This is the field the database joins on.
- `metric_name`: The printed label for the measure, taken from whichever axis names it: the row label where rows are measures and columns are periods, the leaf column header where rows are entities and columns are measures, and the table's own title only where neither axis names a measure. Never a section heading, and never identical to horizon. The page's own wording, not a controlled value.
- `metric_value_raw`: The printed value, copied verbatim: currency symbol, thousands separators, decimals, sign, and parentheses all preserved. Never calculated, rounded, rescaled, or repunctuated.
- `unit`: The unit of measure printed for the value: %, x, bps, years, shares. A currency is never a unit; it belongs in currency_scale.

## Legal and narrative provisions

Used by the legal families only, where the fact is printed wording, not a number.

- `term_category`: For provisions only: which term of the one term vocabulary the clause states, such as management_fee or key_person.
- `text_raw`: For legal provisions and qualitative facts: the printed wording of the provision.
- `basis_raw`: For legal provisions: the printed basis a rate or amount is calculated on, such as committed capital.
- `condition_raw`: For legal provisions: the printed condition or qualification attached to the term.

## Proof and lineage

How the row can be checked against the page, and how it was settled between the two extractors.

- `evidence_quote`: One short line copied verbatim from the cited page that contains the value. Checked against the page, so it cannot be paraphrased.
- `evidence_class`: Whether the value is an actual reported figure, an illustrative or template figure, a stated requirement, a definition, or redacted.
- `notes`: Free-text remarks. Also carries the NO_ELIGIBLE_REASON and IMAGE_ONLY prefixes where the field list requires them.
- `source_agents`: On a final adjudicated row, which extractors the fact came from: A, B, A+B, or ADJUDICATOR.
- `adjudication_status`: On a final adjudicated row, how it was settled: AGREED, VERIFIED_ONE_SIDED, RESOLVED, or ADDED.

## Controlled vocabularies

Three fields accept only listed values, matched character for character.

- `source_structure_type`: DOCUMENT, TABLE, FIGURE, NARRATIVE, FORM, FOOTNOTE, SCHEDULE
- `subject_type`: document, reporting_entity, fund, portfolio, investment, manager, investor, asset_class, benchmark, peer_group, market_series, fee_scope, cash_flow, valuation_subject, foundation, program_related_investment, service_provider, clause_party, subscription, other_printed_scope
- `metric_category`: any name in the metric vocabulary of `EXTRACTION-METRIC-CATEGORIES.csv`,
  89 names, each with a definition and unit hint; `term_category`: any of its
  30 term names. A family fills one of the two by its kind; the preferred
  family listed for a name is guidance for a mixed table, never a rule.

## Output by document type

A document's type fixes which kinds of row it can yield. Within a document,
the family follows the table the value sits in, not the document type: a
financial statement can still yield a holdings row where it prints a holdings
schedule.

### Cash_Flow_Notice

Capital call or distribution notice stating the amounts due or paid and their components.

Extracted in route `06-statements-and-economics`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`cash_flow_observation`**: A printed call, contribution, distribution, fee, expense, or other investor cash-flow value.

- Grain: one populated allowed source value cell or one notice component the page states in words
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: capital_call, return_of_capital, preferred_return, expense, interest, net_cash_flow

**`fund_economics_observation`**: A printed commitment, paid-in, distribution, NAV, unfunded, multiple, or capital-account value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: commitment, paid_in_capital, contribution, distribution, nav, unfunded_commitment, recallable_distribution, tvpi, dpi, rvpi, moic, ownership_percentage, income, fee, carried_interest

### DDQ

Due diligence questionnaire. Structured answers about the manager, including quantitative firm and fund figures.

Extracted in route `05-fund-legal-docs`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`ddq_quantitative_observation`**: A selected quantitative due-diligence fact; narrative question-and-answer transcription is excluded.

- Grain: one printed quantitative answer or table value
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: staff_count, lockup, redemption_notice, position_limit, leverage, liquidity, minimum_investment, service_provider_count

### Fee_Report

Fee transparency reporting: management fees, carried interest, partnership expenses and the basis they are charged on.

Extracted in route `06-statements-and-economics`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`fee_observation`**: A printed fee, carry, expense, offset, cost, rate, or benchmark value.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: management_fee, performance_fee, cost_bps, offset, fee_benchmark, nav_aum_denominator

**`fund_economics_observation`**: A printed commitment, paid-in, distribution, NAV, unfunded, multiple, or capital-account value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: commitment, paid_in_capital, contribution, distribution, nav, unfunded_commitment, recallable_distribution, tvpi, dpi, rvpi, moic, ownership_percentage, income, fee, carried_interest

### Financials

Audited or unaudited fund financial statements: statements of assets and liabilities, operations, changes in partners' capital, and the investment schedules and fair-value notes behind them.

Extracted in route `01-financials`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`financial_statement_observation`**: A whitelisted alternative-investment financial-statement value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: beginning_capital, ending_capital, cash, total_assets, total_liabilities, net_assets, partners_capital, net_investment_income, investment_fair_value, investment_cost, fund_expense, interest_expense, realized_gain_loss, unrealized_gain_loss

**`fund_economics_observation`**: A printed commitment, paid-in, distribution, NAV, unfunded, multiple, or capital-account value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: commitment, paid_in_capital, contribution, distribution, nav, unfunded_commitment, recallable_distribution, tvpi, dpi, rvpi, moic, ownership_percentage, income, fee, carried_interest

**`position_observation`**: A printed holding or private-market position measure.

- Grain: one populated allowed source value cell for one named position
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: quantity, cost, fair_value, market_value, notional, portfolio_weight, interest_rate, maturity_date

**`fee_observation`**: A printed fee, carry, expense, offset, cost, rate, or benchmark value.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: management_fee, performance_fee, cost_bps, offset, fee_benchmark, nav_aum_denominator

**`financing_observation`**: A printed borrowing, facility, balance, rate, availability, or maturity value.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: outstanding_balance

### Foundations_Annual

A foundation's annual return or report, including investment holdings and programme-related investments.

Extracted in route `07-institutional-mission`, default product tier `SECONDARY`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

### Institutional_Report

An asset owner's periodic report on its whole portfolio: allocations, returns by asset class, and manager-level detail.

Extracted in route `03-institutional-report`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`performance_observation`**: A printed return, multiple, risk, valuation, or benchmark value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`, `subject_type`
- `metric_category`: any metric name; usual here: return, irr, alpha, pme, direct_alpha, sharpe_ratio, tracking_error, yield, aum

**`fund_economics_observation`**: A printed commitment, paid-in, distribution, NAV, unfunded, multiple, or capital-account value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: commitment, paid_in_capital, contribution, distribution, nav, unfunded_commitment, recallable_distribution, tvpi, dpi, rvpi, moic, ownership_percentage, income, fee, carried_interest

**`position_observation`**: A printed holding or private-market position measure.

- Grain: one populated allowed source value cell for one named position
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: quantity, cost, fair_value, market_value, notional, portfolio_weight, interest_rate, maturity_date

**`allocation_observation`**: A printed portfolio allocation amount or percentage.

- Grain: one populated allowed source value cell for one allocation bucket
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: actual_allocation, target_allocation

### LPA

Limited partnership agreement. The operative contract governing the fund.

Extracted in route `05-fund-legal-docs`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`legal_term`**: A whitelisted fund, economic, liquidity, governance, or investor-protection term.

- Grain: one printed term or one numbered provision whose primary meaning matches the whitelist
- Always filled: `term_category`, `text_raw`
- `term_category`: any term name; usual here: management_fee, carried_interest, catch_up, waterfall, clawback, fee_offset, organizational_expense, recycling, fund_term, term_extension, commitment_period, investment_period

**`legal_clause`**: A listed operative right, duty, restriction, waiver, or trigger.

- Grain: one numbered or separately headed operative provision whose primary meaning matches the whitelist
- Always filled: `term_category`, `text_raw`
- `term_category`: any term name; usual here: key_person, gp_removal, no_fault_termination, mfn, reporting, transfer, tax, governing_law, confidentiality, notice

### NAV_Statement

Net asset value statement, including per-share values and any repurchase or liquidity limits.

Extracted in route `06-statements-and-economics`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`nav_observation`**: A printed NAV, share-class, transaction-price, component, repurchase, assumption, or sensitivity value.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: nav_per_share, shares_units, transaction_price, nav_component, repurchase_limit, request_satisfaction, valuation_assumption, valuation_sensitivity

**`valuation_observation`**: A printed valuation result, method, input, adjustment, frequency, or governance fact.

- Grain: one printed valuation fact or one populated value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: method, frequency, valuer, oversight, independent_review, enterprise_value

### PCAP

Partners' capital account statement: an investor's beginning balance, contributions, distributions, allocations and ending balance.

Extracted in route `06-statements-and-economics`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`fund_economics_observation`**: A printed commitment, paid-in, distribution, NAV, unfunded, multiple, or capital-account value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: commitment, paid_in_capital, contribution, distribution, nav, unfunded_commitment, recallable_distribution, tvpi, dpi, rvpi, moic, ownership_percentage, income, fee, carried_interest

**`cash_flow_observation`**: A printed call, contribution, distribution, fee, expense, or other investor cash-flow value.

- Grain: one populated allowed source value cell or one notice component the page states in words
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: capital_call, return_of_capital, preferred_return, expense, interest, net_cash_flow

### PPM

Private placement memorandum. The offering document stating fund terms, fees and structure.

Extracted in route `05-fund-legal-docs`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`legal_term`**: A whitelisted fund, economic, liquidity, governance, or investor-protection term.

- Grain: one printed term or one numbered provision whose primary meaning matches the whitelist
- Always filled: `term_category`, `text_raw`
- `term_category`: any term name; usual here: management_fee, carried_interest, catch_up, waterfall, clawback, fee_offset, organizational_expense, recycling, fund_term, term_extension, commitment_period, investment_period

### Performance

Performance schedules reporting returns, multiples and IRRs, usually by partnership or by asset class, often against benchmarks.

Extracted in route `02-performance`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`performance_observation`**: A printed return, multiple, risk, valuation, or benchmark value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`, `subject_type`
- `metric_category`: any metric name; usual here: return, irr, alpha, pme, direct_alpha, sharpe_ratio, tracking_error, yield, aum

**`fund_economics_observation`**: A printed commitment, paid-in, distribution, NAV, unfunded, multiple, or capital-account value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: commitment, paid_in_capital, contribution, distribution, nav, unfunded_commitment, recallable_distribution, tvpi, dpi, rvpi, moic, ownership_percentage, income, fee, carried_interest

**`cash_flow_observation`**: A printed call, contribution, distribution, fee, expense, or other investor cash-flow value.

- Grain: one populated allowed source value cell or one notice component the page states in words
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: capital_call, return_of_capital, preferred_return, expense, interest, net_cash_flow

### Quarterly_Report

A quarterly report to investors combining commentary with performance, capital account and partnership-level schedules.

Extracted in route `04-quarterly-report`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`performance_observation`**: A printed return, multiple, risk, valuation, or benchmark value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`, `subject_type`
- `metric_category`: any metric name; usual here: return, irr, alpha, pme, direct_alpha, sharpe_ratio, tracking_error, yield, aum

**`fund_economics_observation`**: A printed commitment, paid-in, distribution, NAV, unfunded, multiple, or capital-account value cell.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: commitment, paid_in_capital, contribution, distribution, nav, unfunded_commitment, recallable_distribution, tvpi, dpi, rvpi, moic, ownership_percentage, income, fee, carried_interest

**`allocation_observation`**: A printed portfolio allocation amount or percentage.

- Grain: one populated allowed source value cell for one allocation bucket
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: actual_allocation, target_allocation

**`cash_flow_observation`**: A printed call, contribution, distribution, fee, expense, or other investor cash-flow value.

- Grain: one populated allowed source value cell or one notice component the page states in words
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: capital_call, return_of_capital, preferred_return, expense, interest, net_cash_flow

**`position_observation`**: A printed holding or private-market position measure.

- Grain: one populated allowed source value cell for one named position
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: quantity, cost, fair_value, market_value, notional, portfolio_weight, interest_rate, maturity_date

### Schedule_Inv

Schedule of investments: the holdings list, one row per position, with cost and fair value.

Extracted in route `06-statements-and-economics`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`position_observation`**: A printed holding or private-market position measure.

- Grain: one populated allowed source value cell for one named position
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: quantity, cost, fair_value, market_value, notional, portfolio_weight, interest_rate, maturity_date

### Side_Letter

Negotiated terms granted to a specific investor, amending or supplementing the LPA.

Extracted in route `05-fund-legal-docs`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`legal_term`**: A whitelisted fund, economic, liquidity, governance, or investor-protection term.

- Grain: one printed term or one numbered provision whose primary meaning matches the whitelist
- Always filled: `term_category`, `text_raw`
- `term_category`: any term name; usual here: management_fee, carried_interest, catch_up, waterfall, clawback, fee_offset, organizational_expense, recycling, fund_term, term_extension, commitment_period, investment_period

**`legal_clause`**: A listed operative right, duty, restriction, waiver, or trigger.

- Grain: one numbered or separately headed operative provision whose primary meaning matches the whitelist
- Always filled: `term_category`, `text_raw`
- `term_category`: any term name; usual here: key_person, gp_removal, no_fault_termination, mfn, reporting, transfer, tax, governing_law, confidentiality, notice

### Stewardship_Proxy_Report

Stewardship and proxy voting reporting: engagement and voting activity and the policies behind them.

Extracted in route `07-institutional-mission`, default product tier `SECONDARY`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`stewardship_observation`**: A printed stewardship, voting, engagement, climate, or governance metric.

- Grain: one populated allowed source value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: meeting_count, vote_count, engagement_count, coverage, score, target

**`stewardship_policy`**: A concise operative stewardship policy from a named framework or policy section.

- Grain: one separately headed operative policy statement
- Always filled: `term_category`, `text_raw`
- `term_category`: any term name; usual here: stewardship_policy

### Subscription

Subscription agreement recording an investor's commitment and eligibility representations.

Extracted in route `05-fund-legal-docs`, default product tier `SECONDARY`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`subscription_reference`**: A non-sensitive subscription-document reference fact; qualification narratives and personal identifiers are excluded.

- Grain: one whitelisted subscription reference fact
- Always filled: `term_category`, `text_raw`
- `term_category`: any term name; usual here: subscription_fund, general_partner, requested_commitment, accepted_commitment, subscriber_entity_type, fund_jurisdiction, execution_date

### Valuation

Valuation policy and results: methods, frequency, who values, what oversight applies, and resulting marks.

Extracted in route `06-statements-and-economics`, default product tier `CORE`.

**`document_context`**: One source-backed document identity and reporting context row.

- Grain: one row per document
- Always filled: `subject_name`, `subject_type`

**`valuation_observation`**: A printed valuation result, method, input, adjustment, frequency, or governance fact.

- Grain: one printed valuation fact or one populated value cell
- Always filled: `metric_category`, `metric_name`, `metric_value_raw`, `subject_name`
- `metric_category`: any metric name; usual here: method, frequency, valuer, oversight, independent_review, enterprise_value
