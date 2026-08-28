# Quarterly Report: EXTRACTOR A

> **Binding:** Do not dispatch sub-agents. Do not use Python, scripts, regex, or automated table parsing to read or extract source content. The extractor reads the source and writes the candidate rows directly into the output CSV. Do not write a generator, builder, emitter, or intermediate data file that expands into rows: the only Python permitted is the validator and audit commands named below, verbatim except for `<file_id>`, which names the document in progress. Append rows to the output CSVs and save after each table, section, and page, never in one batch at the end of a file. Run `validate-candidate` after the first page and `audit-file` after each finished document; both must report PASS before the next document is opened. Never delete, empty, overwrite, or reset a candidate file: rows already on disk are finished work, including rows written by an earlier session, and the only permitted write is an append.

- **Project root:** the repository root, the folder holding `README.md`; every path below is relative to it
- **Worklist:** `instructions/01-pdf-extraction-csv/worklists/active/04-quarterly-report.csv`
- **Record output:** `ledgers/working/pdf-extraction-csv/04-quarterly-report/<file_id>/records-a.csv`
- **Coverage output:** `ledgers/working/pdf-extraction-csv/04-quarterly-report/<file_id>/coverage-a.csv`

Read only this prompt, the assigned worklist, and the listed TXT/PDF/PNG source files. Never open another extractor's candidate (B), a comparison file, a resolution, or a final file.

## Deterministic unit

**One CSV row is one source observation.** For a table, one populated allowed value cell is one observation. A printed source row with N populated allowed value columns produces N CSV rows. Never combine several values into one row and never split one value into field-name/value EAV rows.

**Outside a table the same rule is counted differently, and this is where two lanes drift furthest apart.** A table supplies a bounded set of cells, so the row count is not a judgement. Running prose does not: every figure in a sentence is a candidate, and "how many rows does this page yield" has no obvious answer. Measured across one round, extraction volume between the two lanes tracked almost nothing except how much of the document was narrative: on tabular routes the lanes landed within 4% of each other, on a 41%-narrative route one lane wrote 1.9x the other, and on a 68%-narrative route 3.0x. They were not reading different numbers, one lane simply stopped earlier: of 32 values one lane took from a stewardship report, all 32 were in the other lane's set, which held 41 more.

Narrative is counted the same way as a table:

- **Every printed figure in the running text that states a fact about the reporting entity is one row.** `carried out 543 engagement activities, covering 352 companies in 34 countries` is three rows, not one and not a summary. Take them all, including the ones that arrive late in a sentence or in a parenthesis.
- **A figure describing someone else is not allowed**: a market total, a peer or index statistic, a counterparty's own scale, or an external framework's own numbers, unless the page states it as a measure of this entity.
- **A figure repeated from a table already extracted on that page is not a second row.** Prose restating a table cell is the same observation.
- **A provision row (`text_raw`) is one operative statement**: one rule, commitment, threshold, or duty that binds the entity. A sentence carrying two distinct duties is two rows; a paragraph of background around one duty is one row, quoted at the duty.
- If a page is genuinely all background, `NO_ELIGIBLE_DATA` with a category reason is right. This rule invents no rows; it forbids stopping early on a page that keeps printing facts.

Correct:

```text
Fund A | Commitment 100 | Paid-In 80 | Unfunded 20
=> three rows with source_column_label Commitment, Paid-In, and Unfunded.
```

Wrong:

```text
one row containing "Commitment | Paid-In | Unfunded" or one row that keeps only 100.
```

A dash, em dash, blank cell, `$ -`, `N/A`, or `not applicable` produces **no record**. A redacted printed value may be recorded as `REDACTED` with `evidence_class=redacted`.

Performance and benchmark rows remain separate source observations. Example:

```text
Endowment          4.3   7.3
Policy Benchmark   4.4   6.4
```

This produces four rows: two with `subject_type=portfolio` and two with `subject_type=benchmark`.

## Frozen routing

Use `canonical_doc_type`, `route`, and `product_tier` verbatim from the worklist. The TXT header may contain a stale earlier classification; do not reclassify the document.

## Source method

Each worklist row supplies four views of the same document:

| Column | What it is |
|---|---|
| `txt_path` | Page-aligned text. Good for finding content and copying `evidence_quote`. Loses column alignment. |
| `grid_path` | **Pre-computed table grid.** Every numeric cell with its row label, column number and column header, taken from the PDF's own coordinates. |
| `image_dir` | One PNG per page. The authority on layout. |
| `pdf_path` | The original. |

1. Read the TXT header and every physical page in order.
2. Use TXT to locate content and copy `evidence_quote`.
3. **For any table, read `grid_path` for that page before assigning a value to a column.** It lists `source_page, source_row_label, column_index, source_column_label, value_raw`, so which column a number belongs to is already decided. Reading a wide table off linearised text and counting columns by eye is the single largest source of wrong values in this work.
4. Open the corresponding PNG whenever layout, rows, columns, merged headers, chart labels, checkboxes, footnotes, indentation, wide page orientation, OCR, or redaction affects meaning. The PNG decides layout.
5. Finish and save both CSVs for one file before opening the next file.

### Scope and limits of the grid

The grid is a **word map**. The page picture is the source. The grid is not an extraction. It reports what is printed and where. The extractor still decides the record family, the category, the scope, and whether a value is allowed at all.

It is deliberately incomplete, and that is not an error:

- **A page absent from the grid has no detected numeric table.** Narrative pages produce nothing. Scanned pages produce nothing because there is no text layer to measure. Check `data/documents/grids/MANIFEST.csv`: a `text_layer` of `ocr` means that document must be read from its PNGs.
- **Column headers are best-effort.** Some PDFs draw their header text twice, so a header can arrive garbled. `column_index` and `column_x` are always reliable, so when a header is unreadable, name the column once from the PNG and apply it to every row in that column.
- **The grid never decides eligibility.** It lists every number on the page, including totals, subtotals and figures outside this document type's allowed categories. Extract only what the route's scope permits.

If the grid and the PNG disagree, the PNG wins.

## Save progressively (hard requirement)

**Append to the record CSV during reading, never at the end.** Save after every finished table, section, or page. Never hold a document's rows in memory and write them once at the end.

The loop for every document is:

1. Read the next table, section, or page.
2. Extract the observations it supports.
3. **Append those rows to the record CSV and save.**
4. Append that page's row to the page-coverage CSV once the page is finished, and save.
5. Only then move to the next table, section, or page.

Rules:

- Write the header once, then append. Never rewrite the file from scratch and never lose rows already saved.
- Keep the sort order correct in the finished file; sorting at the end is fine, but the rows must already be on disk before that.
- A page is complete only when its coverage row is saved, so records and coverage stay consistent at every point.
- If the session stops mid-document, everything already read is on disk and the next session resumes at the first page with no coverage row.

Long documents are where extractions get lost. Saving per section instead of per file is what makes an interrupted run recoverable and progress visible during the run.

## Allowed scope

| Document type | Product | Allowed record family | Grain | Usual categories (any name of the family's kind is valid) |
|---|---|---|---|---|
| `Quarterly_Report` | `CORE` | `document_context` | one row per document | none |
| `Quarterly_Report` | `CORE` | `performance_observation` | one populated allowed source value cell | `return`, `irr`, `alpha`, `pme`, `direct_alpha`, `sharpe_ratio`, `tracking_error`, `yield`, `aum` |
| `Quarterly_Report` | `CORE` | `fund_economics_observation` | one populated allowed source value cell | `commitment`, `paid_in_capital`, `contribution`, `distribution`, `nav`, `unfunded_commitment`, `recallable_distribution`, `tvpi`, `dpi`, `rvpi`, `moic`, `ownership_percentage`, `income`, `fee`, `carried_interest` |
| `Quarterly_Report` | `CORE` | `allocation_observation` | one populated allowed source value cell for one allocation bucket | `actual_allocation`, `target_allocation` |
| `Quarterly_Report` | `CORE` | `cash_flow_observation` | one populated allowed source value cell or one notice component the page states in words | `capital_call`, `return_of_capital`, `preferred_return`, `expense`, `interest`, `net_cash_flow` |
| `Quarterly_Report` | `CORE` | `position_observation` | one populated allowed source value cell for one named position | `quantity`, `cost`, `fair_value`, `market_value`, `notional`, `portfolio_weight`, `interest_rate`, `maturity_date` |

### Vocabulary

Pick the family from the table shape and the name from the printed meaning. A family takes any name of its kind below; the usual family is guidance for a mixed table, never a rule.

| `metric_category` | Means | Unit | Usual family |
|---|---|---|---|
| `commitment` | Capital committed to the fund by the investor or in total. | currency | `fund_economics_observation` |
| `paid_in_capital` | Capital contributed to date (PIC, paid-in, contributed capital). | currency | `fund_economics_observation` |
| `contribution` | One contribution or a period's contributions, as a flow. | currency | `fund_economics_observation` |
| `distribution` | Capital distributed to date or in a period, including a printed component such as preferred return when the page lists it inside distributions. | currency | `fund_economics_observation` |
| `nav` | Residual value of one fund, LP position, or share class at a date, printed as NAV, remaining value, reported value, or ending market value at that grain. | currency | `fund_economics_observation` |
| `unfunded_commitment` | Commitment not yet called (unfunded, remaining, uncalled). | currency | `fund_economics_observation` |
| `recallable_distribution` | Distributed capital the fund may call again. | currency | `fund_economics_observation` |
| `tvpi` | Total value to paid-in: (distributions + NAV) / paid-in. | x | `fund_economics_observation` |
| `dpi` | Distributions to paid-in. | x | `fund_economics_observation` |
| `rvpi` | Residual value to paid-in: NAV / paid-in. | x | `fund_economics_observation` |
| `moic` | Multiple of invested capital: total value / invested cost, gross or as printed. | x | `fund_economics_observation` |
| `ownership_percentage` | Share of a vehicle, firm, or partnership held by the subject. | % | `fund_economics_observation` |
| `income` | Investment, dividend, interest, or net income of a fund or capital account for a period, recorded as a currency amount; percent-based distribution and investment yields use yield. | currency | `fund_economics_observation` |
| `fee` | A fee amount charged to a fund or account when the page states no finer kind (management fees, commissions, advisor fees). | currency | `fund_economics_observation` |
| `carried_interest` | Carried interest accrued, realized, or unrealized, as an amount. | currency | `fund_economics_observation` |
| `beginning_capital` | Opening balance of a capital account, partners' capital, or net assets for a period, at the entity or partner grain printed by the statement. | currency | `financial_statement_observation` |
| `ending_capital` | Closing balance of a capital account, partners' capital, or net assets for a period, at the entity or partner grain printed by the statement. A residual closing balance may also represent NAV. | currency | `financial_statement_observation` |
| `return` | The return printed for a period or horizon, as a percent, under the method, fee basis, and hedge treatment stated by the report. Methods include time-weighted, Modified Dietz, holding-period, annualized, and money-weighted. Data/schemas/RETURN-METHOD-BY-DOCUMENT.csv records the applicable basis. A figure labelled IRR uses irr. | % | `performance_observation` |
| `irr` | Internal rate of return, net or gross, since inception or for a horizon, where the page labels it IRR. A money-weighted return printed under another label stays return, with its method recorded. | % | `performance_observation` |
| `alpha` | Return minus the stated benchmark's return (value added, excess return). | % | `performance_observation` |
| `pme` | Public market equivalent ratio (Kaplan-Schoar or as printed). | x | `performance_observation` |
| `direct_alpha` | Direct alpha against a stated public index. | % | `performance_observation` |
| `sharpe_ratio` | Sharpe ratio as printed. | ratio | `performance_observation` |
| `tracking_error` | Tracking error against the stated benchmark. | % | `performance_observation` |
| `yield` | A rate of income as a percent: distribution rate, income yield, or investment yield. Total-period performance uses return. | % | `performance_observation` |
| `aum` | Assets under management or total assets at manager, plan, endowment, pool, fund, or asset-class scope. | currency | `performance_observation` |
| `cash` | Cash and cash equivalents at a date or a period's opening or closing balance. | currency | `financial_statement_observation` |
| `total_assets` | Total assets. | currency | `financial_statement_observation` |
| `total_liabilities` | Total liabilities. | currency | `financial_statement_observation` |
| `net_assets` | Net assets of the reporting entity as printed, restricted or unrestricted: total assets less total liabilities at statement grain. | currency | `financial_statement_observation` |
| `partners_capital` | Partners' capital by partner class or in total, and its change from operations, at the entity grain of the statement. Position-level closing capital uses ending_capital. | currency | `financial_statement_observation` |
| `net_investment_income` | Net investment income or loss for a period. | currency | `financial_statement_observation` |
| `investment_fair_value` | Investments at fair value as a line of a financial statement or note, including the Level 1, 2, and 3 hierarchy lines. The amount precedes the entity's other assets and liabilities in the NAV build-up. | currency | `financial_statement_observation` |
| `investment_cost` | Cost basis of investments on a statement. | currency | `financial_statement_observation` |
| `fund_expense` | An expense line or an expense ratio of the fund (professional fees, organizational expenses, total expenses). | currency or % | `financial_statement_observation` |
| `interest_expense` | Interest expense for a period. | currency | `financial_statement_observation` |
| `realized_gain_loss` | Realized gain or loss on investments for a period. | currency | `financial_statement_observation` |
| `unrealized_gain_loss` | Change in unrealized gain or loss for a period. | currency | `financial_statement_observation` |
| `quantity` | Shares, units, or par held. | count | `position_observation` |
| `cost` | Cost of a holding. | currency | `position_observation` |
| `fair_value` | Fair or market value of one named holding on a schedule of investments. Fund residual value uses nav; statement investment lines use investment_fair_value. | currency | `position_observation` |
| `market_value` | Market value under that printed heading for one holding or one allocation bucket. The same measure as fair_value at holding grain; at fund grain the residual value is nav. | currency | `position_observation` |
| `notional` | Notional, par, purchase, or sale amount of a contract or security. | currency | `position_observation` |
| `portfolio_weight` | A holding's share of the portfolio or of partners' capital. | % | `position_observation` |
| `interest_rate` | Coupon or yield printed on a holding. | % | `position_observation` |
| `maturity_date` | Maturity or settlement date printed on a holding. | date | `position_observation` |
| `actual_allocation` | Actual share of a portfolio in an asset class, strategy, vintage, geography, or industry bucket. | % | `allocation_observation` |
| `target_allocation` | Target or policy weight of a bucket or benchmark component. | % | `allocation_observation` |
| `management_fee` | Management fee as an amount or as a rate; the unit column says which. The contractual clause is the term-vocabulary management_fee. | currency or % | `fee_observation` |
| `performance_fee` | Incentive or performance fee rate or amount. | % or currency | `fee_observation` |
| `cost_bps` | Fee or cost expressed in basis points. | bps | `fee_observation` |
| `offset` | A fee offset, adjustment, or rebate amount. | currency | `fee_observation` |
| `fee_benchmark` | A peer or benchmark fee level the report compares against. | bps or currency | `fee_observation` |
| `nav_aum_denominator` | The asset base a fee is measured on. | currency | `fee_observation` |
| `capital_call` | A dated capital call amount. | currency | `cash_flow_observation` |
| `return_of_capital` | The return-of-capital component of a distribution. | currency | `cash_flow_observation` |
| `preferred_return` | The preferred-return component of a distribution. | currency | `cash_flow_observation` |
| `expense` | An expense or tax charge in a capital-account or cash-flow statement. | currency | `cash_flow_observation` |
| `interest` | Interest paid or charged in a capital-account statement. | currency | `cash_flow_observation` |
| `net_cash_flow` | Net cash movement after the page combines cash inflows and outflows. | currency | `cash_flow_observation` |
| `nav_per_share` | NAV per share or unit by class. | currency | `nav_observation` |
| `shares_units` | Shares or units outstanding, issued, or sold. | count | `nav_observation` |
| `transaction_price` | Transaction price per share by class. | currency | `nav_observation` |
| `nav_component` | A line of the NAV build-up: investments, cash, debt, other assets and liabilities. | currency | `nav_observation` |
| `repurchase_limit` | A repurchase or redemption limit as a share of NAV or an amount. | % or currency | `nav_observation` |
| `request_satisfaction` | Share or amount of repurchase requests satisfied. | % or currency | `nav_observation` |
| `valuation_assumption` | A discount rate, exit capitalization rate, or other valuation input. | % | `nav_observation` |
| `valuation_sensitivity` | Change in value for a stated change in an assumption. | % | `nav_observation` |
| `method` | The valuation method or principle stated. | text | `valuation_observation` |
| `frequency` | How often NAV or appraisals are produced. | text | `valuation_observation` |
| `valuer` | Who values or calculates NAV. | text | `valuation_observation` |
| `oversight` | Who approves or oversees valuations. | text | `valuation_observation` |
| `independent_review` | Independent review or appraisal of valuations. | text | `valuation_observation` |
| `enterprise_value` | Enterprise value of a company or portfolio company. | currency | `valuation_observation` |
| `outstanding_balance` | Balance drawn on a credit facility or loan. | currency | `financing_observation` |
| `staff_count` | Employees or investment professionals at the firm. | count | `ddq_quantitative_observation` |
| `lockup` | Lock-up period. | years or months | `ddq_quantitative_observation` |
| `redemption_notice` | Redemption notice period or fee. | days or % | `ddq_quantitative_observation` |
| `position_limit` | Position or exposure limit. | % | `ddq_quantitative_observation` |
| `leverage` | Leverage ratio or policy limit. | x | `ddq_quantitative_observation` |
| `liquidity` | Redemption proceeds timing in days, or a withdrawal size as a percent of proceeds or of NAV; the unit column says which. | % or days | `ddq_quantitative_observation` |
| `minimum_investment` | Minimum initial investment. | currency | `ddq_quantitative_observation` |
| `service_provider_count` | Number of service providers or counterparties stated. | count | `ddq_quantitative_observation` |
| `meeting_count` | Meetings held or voted at. | count | `stewardship_observation` |
| `vote_count` | Proposals, directors, or votes counted. | count | `stewardship_observation` |
| `engagement_count` | Engagements, milestones, or companies engaged. | count | `stewardship_observation` |
| `coverage` | Share or count of a universe covered, held, or voted. | % or count | `stewardship_observation` |
| `score` | Support percentage or assessment score. | % | `stewardship_observation` |
| `target` | A stated target year or level. | year | `stewardship_observation` |

### Excluded scope

- **Quarterly_Report:** Unapproved exposure charts and generic breakdowns; use position or allocation only when the printed structure matches.

Only the vocabulary names above are permitted. Do not use `other`, generic dimensions, invented categories, or `SCHEMA_GAP` rows. Put a genuinely useful excluded concept in `notes` of the page-coverage row; do not extract it.

## Record CSV field list

Header, verbatim:

```csv
"contract_version","file_id","source_sha256","canonical_doc_type","route","product_tier","agent_role","record_family","source_page","source_structure_type","source_section","source_table","source_row_label","source_column_label","source_occurrence","subject_type","subject_name","asset_class","strategy","geography","manager_name","investor_name","portfolio_name","vintage_year","period_start","period_end","as_of_date","horizon","currency_scale","metric_category","metric_name","metric_value_raw","unit","term_category","text_raw","basis_raw","condition_raw","evidence_quote","evidence_class","notes","source_agents","adjudication_status"
```

Rules:

- UTF-8 CSV; quote every cell; **42 cells on every single row**, header and data alike.
- **Never omit a column, and never add one.** A column with no value is written as an empty pair of quotes `""`, in its own position. Omitting it shifts every later value one column left, so the row silently reports the wrong field. Count the cells before saving: a correct row contains 41 commas outside quotes.
- **Extra cells come from unescaped punctuation.** A value containing a comma, a quote, or a line break splits into two cells unless it is quoted correctly. Wrap every cell in double quotes and double any quote inside a value: a printed `Smith, Jones "A" LP` is written as `"Smith, Jones ""A"" LP"`. If a row has too many cells, an unescaped comma or quote inside one of its values is the cause.
- `record_family` is a closed vocabulary. Use only the families listed for this document type in **Allowed scope** below. Never invent one: `holding_position`, `allocation_bucket`, and similar are rejected. If no listed family fits the table, the table is out of scope, so record it in the page-coverage `notes` and extract nothing from it.
- `contract_version` is `2026-08-22.2`.
- `agent_role` is `A`; `source_agents` and `adjudication_status` are blank.
- `source_page` is the physical page number.
- `source_structure_type` is one of **DOCUMENT, TABLE, FIGURE, NARRATIVE, FORM, FOOTNOTE, SCHEDULE** and is **UPPERCASE**. A `document_context` row is always `DOCUMENT`; a row read out of a ruled table is `TABLE`.
- `subject_type` is one of document, reporting_entity, fund, portfolio, investment, manager, investor, asset_class, benchmark, peer_group, market_series, fee_scope, cash_flow, valuation_subject, foundation, program_related_investment, service_provider, clause_party, subscription, other_printed_scope and is **lowercase**. It classifies **what `subject_name` names on the page**, so read the row label and pick from that, never once per document. `Domestic common and preferred stock` is `asset_class`; `Blackstone Capital Partners VII` is `investment`; `Total net assets` on a statement is `reporting_entity`; a named sleeve or pool is `portfolio`. A whole table of `investment` is a sign the label was not read: an aggregated line is not an ownable investment.
- Controlled values are matched character for character. `table` is rejected where `TABLE` is required, and `Fund` is rejected where `fund` is required. Copy the spellings above; do not type them from memory.
- `source_table` is the printed table/figure title, verbatim, the caption that names the whole table. If none exists, use the nearest printed section heading. If neither exists, use `UNTITLED_TABLE_1`, `UNTITLED_TABLE_2`, etc., top-to-bottom on that page. **Never a date, and never a header that sits over only some of the columns.** `December 31, 2015` is a column-group heading, not a table name; the table there is `(3) Investments`. The whole table gets one `source_table`, identical on every row taken from it.
- `source_row_label` is the printed row/entity/metric label, verbatim. Use `DOCUMENT` only for the single document-context row.
- `source_column_label` is the printed **leaf** header for the value cell: the lowest header directly above the column, not the banner spanning several columns. Blank only when the source has no column. Where a table prints `Fair Value Measurements Using` across four columns and `Level 1 | Level 2 | Level 3 | Total` beneath it, the leaf headers are `Level 1`, `Level 2`, `Level 3`, `Total`, and the same rule fixes `metric_name`.
- **The column label must identify the column uniquely within its row.** When the leaf alone repeats across columns, keep the stacked header that separates them, top line first. A table printing `1-Yr 3-Yr 5-Yr 10-Yr` over four columns all headed `Total Return` gives `1-Yr Total Return`, `3-Yr Total Return`, `5-Yr Total Return`, `10-Yr Total Return`. Writing `Total Return` four times collides four values onto one record key and the file is rejected.
- `source_occurrence` is the **Nth time this page prints this row label under this column label**, counted top to bottom then left to right. Normally `1`. It is decided by position on the page and nothing else, so both extractors reach the same number without agreeing on anything interpretive. **A page carrying two tables with the same row labels is the case this exists for**: a page printing `Forward contracts` under `Derivative assets` in one table and again in a second table gives the first `1` and the second `2`. **Count every printing of the label, including ones whose cell under this column is a dash or blank and so produces no row.** A page with eight `Value Added` rows whose first three print `-` under `10 Year` gives the five extracted rows occurrences `4` through `8`, not `1` through `5`: whether a cell is populated is a judgement, where the label sits is not, and one round mis-paired 72 correctly-read cells because the two lanes counted these two ways. Two rows that share a page, row label, column label and occurrence are the same cell by definition, so two different values written there mean that one of them needs the next occurrence number. The single `document_context` row is always `1`.
- **No cell may contain a line break.** Where the source wraps across lines, join it with single spaces so the value stays on one CSV row.
- `evidence_quote` is required on every row and must be **500 characters or fewer**. One short printed line, not a paragraph.
- **`metric_category` and `metric_name` are different columns and must not be swapped.** `metric_category` is a controlled value chosen from the list for that record family in **Allowed scope**. `metric_name` is the label printed on the page, verbatim. They are usually different text, and putting the printed label in `metric_category` is rejected.

  ```text
  printed column header:  Fair Value Rate of Return
  metric_category = return                       (controlled value)
  metric_name     = Fair Value Rate of Return    (printed label, verbatim)
  ```


  **`metric_name` is the leaf column header, never the banner above it.** If `metric_name` comes out identical on every row of a wide table, the spanning header has been copied and it names the table, not the metric. `Fair Value Measurements Using` spans four columns; the metric names are `Level 1`, `Level 2`, `Level 3`, `Total`.

  Which label names the measure depends on the table's shape, so read the shape first and apply the matching line. Both reading groups reading the same table must map to the same answer, and a run where they did not produced 455 paired rows and **zero** matching pairs.

  | The table's rows are | The table's columns are | `metric_name` is | Example |
  |---|---|---|---|
  | measures (`Total Return`, `Value Added`, `Net Assets`) | periods or dates | the **row label** | `Value Added` over `1 Year / 3 Year` gives `Value Added`, with `3 Year` in `horizon` |
  | entities, funds, or securities | measures (`Level 1`, `Fair Value`, `Cost`) | the **leaf column header** | `Fair Value Measurements Using` spanning `Level 1 / Level 2` gives `Level 1` |
  | entities, funds, or securities | periods or dates | the **measure the table itself names**, from its title or banner, **in its printed wording** | a table titled `Annualized Returns` listing funds by `1 Year / 3 Year` gives `Annualized Returns`, not `Return` |

  Only the third shape may take the name from a banner or title, and only because neither axis names a measure there. Never take a section heading, and never trim, singularise, or paraphrase the printed words. **A period is never a metric name:** if `metric_name` and `horizon` come out identical, the wrong axis has been used.
- `metric_value_raw` and `text_raw` are copied verbatim as printed. Do not calculate or normalize. **A printed `%`, `x`, or currency symbol stays in the value** (`(51.90%)`, `1.4x`, `$61.4`) **and is also recorded in `unit` or `currency_scale`**; the one thing closed is whitespace, so `$ 4,858.5` is written `$4,858.5`. Recording the symbol in `unit` does not license removing it from the value: both carry it. Where the page spells the word instead (`3.6 percent`) there is no symbol to copy and `unit` alone carries it.

  **This is enforced.** `validate-candidate` rejects any row whose own `evidence_quote` shows a `%` or `x` printed against the value while the value has dropped it, and names the row. It is checked on the candidate, not on the adjudicator's desk, because caught here it is one row to retype and caught there it is a conflict on every affected cell: one run split 549 otherwise identical values on this, and a later one shipped 61 of 73 rows in the stripped form.
- `evidence_quote` is a short one-line excerpt, verbatim from the cited page.
- One `document_context` row per document, not one per page or table. **Its `source_page` is always `1`**, whatever page supplied the document's identity. It describes the whole document, so the page number is a constant and not a reading: two lanes that file it on different pages produce a row that cannot pair, and the document's own context row then reaches the adjudicator as two one-sided rows. Six documents of one round split this way, on pages as far apart as 1 and 29.
- Populate only business columns allowed for the selected record family. Every other column is still present on the row as `""`; "blank" means an empty cell, never a missing cell.

Sort records by:

```text
source_page, record_family, source_table, source_row_label,
source_column_label, source_occurrence, metric_category
```

## Field discipline

These rules exist because two independent extractors must produce the same row from the same cell. Every one of them settles a real disagreement seen in practice.

### Only the printed page is a source

Every value must be **visible on the cited physical page**. Never take a value from:

- the TXT header block (`# issuer:`, `# doc_type:`, `# filename:`, `# sha256:`);
- the PDF filename;
- the worklist;
- prior knowledge of the institution.

The header block identifies the document; it is not content. If a page prints `Public Employees' Retirement Fund (PERF)`, that is the value, even when the header names the parent institution. Copy what the page prints, not the organisation's known name.

### Entity fields

| Column | What goes in it |
|---|---|
| `subject_type` | Decided by the row's own printed label, the same way on every row. A label naming a vehicle (`... Fund V, L.P.`, `... LLC`, `... Trust`, a named fund) is `fund`. A label naming the owner's aggregate (`Total Plan`, `Endowment`, `Alternatives Portfolio`, a pool) is `portfolio`. A single holding, security, or property inside a vehicle is `investment`. An index or policy benchmark is `benchmark`; a peer universe, median, or percentile line (`NACUBO`, a Cambridge Associates universe, `Peer Median`) is `peer_group`. A period label (`Q2 2009`, `1-Yr`) is never a subject of any kind; it is `horizon`. One round split `fund` against `investment` on 465 of 466 rows of one document. |
| `subject_name` | The thing this row measures: the printed fund, portfolio, position, or benchmark row label. **Where the page prints both a full name and a ticker or abbreviation for the same subject, take the full name.** A page carrying `Antares Private Credit Fund (ABDC)` gives `Antares Private Credit Fund`, never `ABDC`: two lanes that split on this produce rows naming the same fund two ways, and nothing downstream can join them. |
| `asset_class`, `strategy`, `geography` | **Core analytical dimensions. Fill them whenever the page states them**, because the delivered database is filtered on these. Take the value from the printed grouping that governs the row, in this order: the row's own group heading inside the table (`Private Equity`, `Real Estate`, `Fixed income:`), then the table title, then a document-level statement of what the table covers. Copy it verbatim, colon dropped, and apply the same value to every row under that grouping. Two limits bound it: **never infer a value the page does not state**, and **never copy `subject_name` into these fields**, so a row already labelled `Domestic common and preferred stock` leaves `asset_class` blank because the row label already is the grouping. To spot a group heading mechanically: **a row that prints a label but no values in its value columns is a heading, and it governs every row beneath it until the next such heading.** A returns table printing a bare `Private Assets` line above `Private Equity`, `Absolute Return`, `Real Estate`, `Real Assets`, `Private Credit`, and `Cash` gives all six rows `asset_class` `Private Assets`. Leaving these blank on a page that states them is the single most damaging defect here: the delivered database is filtered on these three columns, so an unlabelled row is invisible to every query that matters. |
| `source_section` | The printed section heading above the table, verbatim. Blank only when the page prints no heading. A financial statement's own title (`Statements of Financial Position`, `Statements of Operations`) is a heading: record it. **The reporting entity's name is never a section heading**: on a page headed `Oregon Public Employees Retirement Fund` over `Alternatives Portfolio`, the section is `Alternatives Portfolio` and the entity belongs on the single `document_context` row, not here. Blank here while the page prints a title is a defect, not a judgement call. |

**When more than one printed name could fill a column, take the nearest and most specific one to the row.**

`manager_name`, `investor_name` and `portfolio_name` are **document-level facts and belong only on the single `document_context` row**. They name the manager, the asset owner, and the portfolio the whole document reports on, so repeating them on every observation adds nothing and the validator rejects them there. Record each once, on the context row, verbatim as the page prints it.

A document title, cover heading, or report name is not a portfolio. If the only candidate for `portfolio_name` is the document title, leave it blank on the context row too.

Worked example. A page titled `University Endowment Fund Profile` prints a table whose rows include `University Long Term Portfolio`:

```text
document_context row: portfolio_name = University Long Term Portfolio
NOT                                     University Endowment Fund   (that is the document title)
observation rows:     portfolio_name = ""                          (document-level, never repeated)
```

### Dates, scale, and units

| Column | Rule |
|---|---|
| `as_of_date`, `period_start`, `period_end` | Copy the printed date **verbatim**, as rendered: `September 30, 2022` stays `September 30, 2022`. Never reformat to ISO or any other form. **Take the fullest printed form that governs the value.** A statement whose columns are headed `2016  2015` prints its real date once, in the title line `December 31, 2016 and 2015`, so `as_of_date` is `December 31, 2016`, not `2016`. A bare year is only correct where the page prints nothing more specific. |
| `currency_scale` | Copy the printed currency/scale statement verbatim, **parentheses included**: a page printing `($ in millions)` is recorded as `($ in millions)`, not `$ in millions`. Blank only when the page prints no scale. **A magnitude word printed inline with the number belongs here, not in the value.** Prose reading `stood at $52 billion` gives `metric_value_raw` `$52` and `currency_scale` `billion`. The value column holds the numeral, its currency symbol, separators, decimals, sign, and parentheses, and nothing else, so that two rows measuring the same thing stay comparable. |
| `horizon` | The printed measurement period for that value, copied from the header as rendered: `1-Yr`, `3 Year`, `10-Yr`, `Fiscal YTD 9 Months`, `ITD`, `Since Inception`. **Whenever the column header carries a period qualifier, `horizon` is required.** Where the stacked header reads `1-Yr` over `Total Return`, the qualifier goes in `horizon` and `metric_name` is the metric without it (`Total Return`), while `source_column_label` keeps the full `1-Yr Total Return`. Blank only for a value the page attaches to no period. |
| `unit` | The unit of measure printed for that value, and nothing else: `%`, `x`, `bps`, `years`, `shares`. **A currency or a scale is never a unit.** `USD`, `$`, `USD millions`, and `$ in thousands` belong in `currency_scale`, never here. If the page prints no unit of measure, leave `unit` blank; do not infer one. **A `%` or `x` printed in the cell or in the column header is a printed unit and `unit` is required**: `(51.90%)` gives `unit` `%` **and `metric_value_raw` `(51.90%)`**, `1.4x` gives `x` **and `1.4x`**. Filling `unit` never means emptying the symbol out of the value; the two are recorded together and `validate-candidate` rejects a value that dropped one. One round left `unit` blank on 1,007 percentage values, and another stripped the symbol from 61 of 73. |
| `metric_value_raw` | Copy the printed value verbatim, including its currency symbol, thousands separators, decimals, sign, and any parentheses. Two normalisations only: trim leading and trailing spaces, and close the gap between a currency symbol and its digits, so `$ 61.4` is recorded as `$61.4`. Nothing else changes: never round, rescale, strip a symbol, or convert `(1,234)` to `-1234`. |

#### A label printed once still applies to every value under it

**"Printed" means printed anywhere that governs the value, not printed in the same cell.** A table states its unit and its scale once, in a column header, a row label, a table title, or a banner line above the table, and every value underneath inherits it. Reading "printed" as "printed in this cell" leaves whole tables of numbers with no unit and no scale, which is the single most common defect in this work: it strips the meaning from the value and nothing downstream can put it back. `4.3` is not data. `4.3` `%` is.

Apply the nearest governing label, and apply it no wider than it governs:

| The page prints | Applies to | Example |
|---|---|---|
| A unit in the column header (`Return (%)`, `Multiple (x)`) | Every value in **that column** | `unit` = `%` |
| A unit in the row label (`Net IRR (%)`, `TVPI (x)`) | Every value in **that row** | `unit` = `%` |
| A unit or scale in the table title or a banner above it | Every value in **that table** | `$ in thousands` |
| A scale over one column only (`Market Value in Millions ($)`) | **That column only** | leave the percent columns' `currency_scale` blank |

A performance table headed `1 Year | 3 Year | 5 Year` whose body reads `11.48`, `10.28` is a table of percentages: `unit` is `%` on every one of those values. Do not leave it blank because no `%` sign is printed beside each number.

The limit is unchanged: infer nothing the page does not state somewhere. If no header, label, title, or banner gives a unit, leave `unit` blank.

#### Three more fields that carry the value's meaning

| Column | Rule |
|---|---|
| `as_of_date` | The date the value is stated as of, taken from the page or from the report's own cover or banner date. Blank only when no date governs the value anywhere on the page. A number with no date cannot be placed in time and is not deliverable. |
| `source_column_label` | On any `TABLE` row, the printed header of the column the value sits in, copied verbatim. Never blank on a `TABLE` row: if the column has no printed header, write `UNLABELED_COLUMN_<n>` using its position from the left, counting the label column as 0. |
| `metric_value_raw` | Never substitute a character to avoid a CSV problem. A thousands comma stays a comma: quote the field. Writing `8,312,575` as `8.312.575` or `8312575` changes the number and no later step can detect it. |

### `evidence_quote`

One short line copied verbatim from the cited TXT page that contains the value. Use the printed source line the value sits on. It must appear on that page verbatim, and **it must contain `metric_value_raw` itself**: the quote proves this number itself, and a page alone proves nothing. A quote naming the table or the row without the figure is rejected. Do not paraphrase, join two lines, or summarise. On a scanned page where the TXT cannot supply the line, start `notes` with `IMAGE_ONLY:`.

### Choosing the record family

**The family follows the table, not the document type and not the route name.** A document routed to one lane still yields whichever of its permitted families the table at hand calls for: a performance report containing a partnership capital schedule yields capital-account rows, not return rows. Decide per table, never once per document, and only from the families listed below.

Read the table's column headers and pick the first rule that matches. Only families this document type permits are listed:

| The table's columns include | Family | Applies to |
|---|---|---|
| Period or annualised returns (1-Yr, 3-Yr, 5-Yr, ITD), benchmark rows, or risk statistics, with no capital-account columns | `performance_observation` | every column in that table |
| Commitment, contributed/paid-in, distributed, remaining or ending value, and the multiples or IRR reported beside them | `fund_economics_observation` | every column in that table |
| Target and actual allocation by bucket, with the market value or weight reported against each | `allocation_observation` | every column in that table |
| A dated call or distribution and its components: capital call, contribution, distribution, recallable amount, expense | `cash_flow_observation` | every column in that table |
| One row per **named individual** security, holding, or position, with cost, quantity, or market value | `position_observation` | every column in that table |

### Cells that must be extracted

The scope tables above say what is *allowed* once a cell is picked. This says which cells must be picked, and it is not a matter of judgement. Two readers choosing different subsets of the same page is the largest single source of unusable output in this work: thousands of rows where one extractor recorded a cell the other never looked at, which no third reader can resolve because only one side ever saw it.

For every printed table, in order:

1. Read the table title, every row label, and every column label.
2. Map each value-bearing row or column to one allowed category for the chosen family.
3. **Where a row or column maps to an allowed category, extract every populated cell governed by that mapping.** All of them. A table with 30 rows and 6 mapped columns yields up to 180 rows.
4. Never extract a selection. Take every mapped cell: the small values, the later rows, every row inside a group, and the lines beside the totals. "I captured the important ones" is a failed extraction.
5. Blank, dash, em dash and N/A cells produce nothing. They are not skipped cells; there is no value there to record.
6. A total or subtotal row is extracted only when its own label maps to an allowed category and its grain is clear. `Total Fund` on a returns table is a real observation; a column sum with no printed label is not.
7. Before leaving the page, count the mapped populated cells and put that number in `expected_observation_count`. It must equal the rows written.

If a mapped column is too dense or too wide to resolve from the TXT, open the page image and read it there. Extracting fewer rows is never the answer to a hard table.

**One table produces one family.** Do not split a single printed table across two families because one of its columns looks like a return. A partnership table showing `Capital Commitment | Total Capital Contributed | Total Capital Distributed | Ending Market Value | IRR (%) | TVPI` is entirely `fund_economics_observation`: the IRR and TVPI columns belong to that family too, because they are reported as attributes of the capital account.

The family says what shape of table the cell came from; the category says what the cell means. The two are chosen separately: a TVPI printed in a capital-account table is `fund_economics_observation` with `tvpi`, and the same TVPI in a returns table is `performance_observation` with `tvpi`. Never invent a family to fit a name, and never change a name to fit a family.

### Category disambiguation

When the printed label is ambiguous, use this mapping so both extractors map to the same category:

| Printed label | Category |
|---|---|
| Capital Contributed, Contributed Capital, Paid-In Capital, PIC, Paid-In, Total Contributions | `paid_in_capital`, never `moic` (PIC is an amount, not a multiple) |
| Contributions for a single period or transaction row | `contribution` |
| Capital Commitment, Commitment | `commitment` |
| Distributions, Total Distributed, Capital Distributed | `distribution` |
| Ending Market Value, Market Value, Net Asset Value, NAV, Remaining Value, Reported Value | `nav` in a `fund_economics_observation` table; `market_value` in a `position_observation` table |
| Fair Value, Estimated Fair Value | `fair_value` in `position_observation`; `nav` in `fund_economics_observation` |
| Cost, Cost Basis | `cost` |
| Net IRR, IRR, Since-Inception IRR | `irr` |
| TVPI, Total Value to Paid-In, Investment Multiple | `tvpi` |
| DPI, Distributions to Paid-In, Realization Multiple | `dpi` |
| Unfunded, Remaining Commitment, Uncalled Capital | `unfunded_commitment` |
| Value Added, Excess Return, Difference, Relative Return, Over/Under Benchmark: a row that is the portfolio's return minus its benchmark's | `alpha`, never `return` |

## Page-coverage CSV field list

Header, verbatim:

```csv
"contract_version","file_id","source_sha256","canonical_doc_type","route","product_tier","agent_role","source_page","page_status","layout_checked","source_structures","relevant_record_families","expected_observation_count","records_written","notes"
```

Write one row for every physical page, including pages with no allowed data. `page_status` is one of: NO_ELIGIBLE_DATA, ELIGIBLE_DATA_EXTRACTED, DEFERRED_BY_SCOPE, REFERENCE_ONLY, UNREADABLE. `layout_checked` is `YES` or `NO` and must be `YES` for any page with an extracted observation.

For each page:

- `expected_observation_count` is the count of populated allowed value cells plus bounded narrative provisions.
- `records_written` must equal the actual number of record rows citing that page.
- `ELIGIBLE_DATA_EXTRACTED` requires a positive count.
- Every other status requires zero record rows.
- `REFERENCE_ONLY` is for a page whose content is reference or boilerplate: glossary, definitions, footnotes, disclosures, disclaimers, risk factors, contact or office directory, cover, table of contents, blank. `NO_ELIGIBLE_DATA` is for a page that prints substantive figures or tables, every one of which falls outside this document type's allowed categories. Two lanes split these labels on seven pages of one document; both counted zero rows, and only one label was right.
- **A `NO_ELIGIBLE_DATA` page that still prints monetary amounts, percentages, or multiples must justify itself: start `notes` with `NO_ELIGIBLE_REASON:` followed by why those figures fall outside this document type's allowed categories.** The validator scans the page for those signals and rejects the row without that prefix, so a page is never silently skipped.

#### `NO_ELIGIBLE_DATA` means the page prints nothing allowed, never that it was hard to read

The most valuable pages in this corpus are usually the hardest: a fund-by-fund or holding-by-holding schedule of ten or more columns, running across several pages. **Difficulty is not ineligibility.** The reason must be about *category*, not about *legibility*.

| Not a reason | Why |
|---|---|
| `column assignment not reliable` | The page still prints the data. Resolve the columns from the PNG. |
| `grid and TXT drop columns` | The grid is an aid, not the source. It drops columns on dense tables; that is a known limit of the tool, not a property of the page. |
| `values are not recoverable` | They are printed. They are recoverable from the image. |
| `labels are merged in TXT` | Read the PNG, where they are not merged. |

A valid reason names the category test: `NO_ELIGIBLE_REASON: glossary definitions, no populated values in an allowed category`, or `NO_ELIGIBLE_REASON: office contact details, outside the allowed financial categories`.

**When a table is too dense to resolve from the TXT, open the page image and read it there.** That is the escalation, and it is required, not optional. A validator rejects a readability complaint on a page that prints allowed figures. Skipping a partnership schedule because it is wide loses more value than every other defect in this work combined.
- Coverage rows are sorted by `source_page`, one row per page, no page repeated and no page missing.
- `source_structures` lists table/figure/section titles verbatim separated by ` | `.
- `relevant_record_families` lists controlled family names separated by ` | `.

This coverage file is the machine-checkable omission check. Do not mark a page complete until the populated allowed cells have been counted against the PNG.

## Evidence and product rules

Allowed evidence classes: actual, illustrative, template, requirement, definition, redacted, unknown.

- `CORE` candidates may contain only `actual` or `redacted` evidence.
- Template and illustrative documents belong in the `reference` worklist, never the active worklist.
- No personal identifiers, signature images, or personal/operational bank and wire details.

## Declare the executing model, once

Before the first document, run this once. It takes no per-row effort and is never repeated:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py claim --route 04-quarterly-report --agent A --model "<model name>"
```

Name the model actually executing this run, as specifically as it can be identified (for example `claude-opus-5`, `gpt-5.5-xhigh`, `gemini-3-pro`). Rows are stamped with it mechanically at publish time, so **never add a model column to the CSV** and never mention the model in any row. If the model cannot be identified, say so in `--model` instead of guessing a different one.

## Validate each file

```powershell
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 04-quarterly-report --file <file_id> --agent A
```

Repair until the command passes, then continue to the next worklist row. A valid no-data document has a header-only record CSV and complete page coverage.

**Run it once on the very first page, before extracting anything else**, adding `--through-page 1`:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 04-quarterly-report --file <file_id> --agent A --through-page 1
```

`--through-page N` checks everything written up to page N and does not ask for pages not yet reached. Without it the command requires coverage for the whole document, which page 1 can never satisfy. A row-shape mistake repeats on every row written, so catching it on page 1 costs a minute and catching it at the end costs the whole document. Do not extract a second page until the first one validates. Run the command without `--through-page` when the document is finished.

## Audit each finished document

Validation proves the file is well formed. It cannot prove the file is finished, because a page declared empty and a page that is empty look identical in the CSV. Before moving to the next worklist row, run:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route 04-quarterly-report --file <file_id> --agent A
```

It compares the written rows against what the document actually prints, and reports two things:

| Finding | Meaning | Action |
|---|---|---|
| Pages with no coverage row | The run stopped before the end of the document | Cover every remaining page |
| Pages declared empty that the grid resolved into a table | A printed table may have been skipped | Open that page image. Extract it, or replace the note with a reason naming the category test it fails |

**This command must pass before the next document is opened.** It is not advisory and it does not need anyone's approval: run it, act on what it says, run it again.

A flagged page is a category call. Some pages hold no allowed values: an office directory of addresses and phone numbers, a glossary, a page of statutory text. Write a category reason and the flag is decided. A legibility reason is rejected, because being hard to read is not a reason a page holds no data.

## Working memory

This prompt is the spec; the block below is the working memory, and `audit-file` reprints it every time it passes so it stays fresh. When output drifts from it mid-file, stop and re-read the relevant section above before writing another row.

```text
RE-READ BEFORE THE NEXT DOCUMENT, the fifteen rules that decay:
 1. Family follows the table, not the document type. One table, one
    family. This route may only use: performance_observation, fund_economics_observation, allocation_observation, cash_flow_observation, position_observation.
 2. metric_name and source_column_label take the LEAF header under a banner,
    never the banner (`Level 1`, not `Fair Value Measurements Using`).
 3. Drop trailing colons AND footnote markers from labels: `Fixed income:` ->
    `Fixed income`; `IRR2` -> `IRR`; `Total Fund***` -> `Total Fund`.
    Spaced name parts stay: `Fund II`, `DT 2020`.
 4. subject_type classifies that row's printed label, row by row, lowercase.
    manager_name, investor_name and portfolio_name go ONLY on the single
    document_context row, never on an observation row.
 5. asset_class, strategy and geography come from the printed grouping that
    governs the row. Fill them whenever the page states them; never infer
    them; never copy subject_name into them.
 6. unit and currency_scale: a label printed once (column header, row label,
    table title, banner) applies to every value under it. A scale over one
    column covers only that column.
 7. metric_value_raw verbatim: commas stay commas (quote the field), `$` only
    if printed, `(1,234)` never becomes -1234. A printed `%` or `x` STAYS in
    the value AND goes in unit: `4.8%` -> value `4.8%`, unit `%`. Never `4.8`.
 8. as_of_date takes the fullest printed form (`December 31, 2015`, not
    `2015`) and stays verbatim: never reformat to ISO.
 9. In a fund_economics table, Ending/Fair Market Value -> nav, never
    fair_value. Entity names come off the page, never the filename.
10. A TABLE row always has source_column_label; use UNLABELED_COLUMN_<n> when
    the column prints no header. A currency (USD, $) is never a unit.
11. A period qualifier in the header fills horizon (`1-Yr`, `Fiscal YTD`).
    metric_name drops it; source_column_label keeps the full stack so four
    `Total Return` columns stay distinct.
12. source_occurrence = the Nth time THIS PAGE prints this row label under
    this column label. Two tables with the same row labels -> 1 and 2.
13. Extract EVERY populated cell under a mapped row or column, never a
    selection. expected_observation_count must equal the rows written.
14. NO_ELIGIBLE_DATA is about category, never difficulty. A table unresolved
    from TXT or grid is read from the page image, never skipped.
15. Save after every table and section. Every physical page gets a coverage
    row, and audit-file must pass before the next document is opened.
```
