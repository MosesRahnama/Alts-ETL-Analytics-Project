# Financials: ADJUDICATOR J2

> **Binding:** Do not dispatch sub-agents. Do not use Python, scripts, regex, or automated table parsing to read source content. The workflow may be used only to validate, pair, and build files mechanically. Append decisions to the resolution CSVs and save after each settled group, never in one batch at the end.

- **Project root:** the repository root, the folder holding `README.md`; every path below is relative to it
- **Worklist:** `instructions/01-pdf-extraction-csv/worklists/active/01-financials.csv`
- **Shard:** worklist rows with even `work_order` values.

Existing `records-final.csv` or `coverage-final.csv` files require `validate-final` first. A passing final completes that document: preserve its candidates, comparisons, and decisions, then skip it. A failing or incomplete final requires a reported correction request before further work. Reordering the worklist does not reopen completed review.

For each assigned file, wait until both extractors have finished it: `coverage-a.csv` and `coverage-b.csv` each carry a row for every page. Read only this prompt, those candidates, the generated comparison files, the pre-computed table grid at the worklist's `grid_path`, and the source TXT/PDF/PNGs. **The page images at the worklist's `image_dir` are the adjudicator's to open and are expected to be used**; unlike the extractors, the adjudicator is never limited to linearised text.

## Check both lanes before opening a single file

An extractor that stopped early reports itself finished, because every per-file check it runs can only judge a document it chose to name. Run both of these first:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py lane-check --route 01-financials --agent A
python instructions/01-pdf-extraction-csv/workflow.py lane-check --route 01-financials --agent B
```

Each prints every worklist document with that lane's state and fails while any is unstarted or unfinished. **A document either lane has not finished cannot be adjudicated**: one side of the comparison does not exist, and `compare` and `build-final` refuse anyway. Adjudicate a document marked `DONE` by both commands only when it has no existing final; preserve completed review and report unfinished extraction by file ID. Do not extract the missing work yourself: a third reader who writes one lane's rows is no longer independent of them.

## Candidate validation and ownership

Both candidates must pass the current candidate and page-completeness checks before a fresh comparison. A failing candidate returns to its original extractor with the reported file, row and error. The adjudicator does not rewrite either blind file or copy a passing lane over a failing lane.

```powershell
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 01-financials --file <file_id> --agent A
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route 01-financials --file <file_id> --agent A
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 01-financials --file <file_id> --agent B
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route 01-financials --file <file_id> --agent B
```

Historical reconstruction reads the original candidates under their recorded contract and uses the existing pair-index and adjudication decisions. It does not certify an old candidate under the current rules. Every constructed final must pass the current semantic and completeness checks before either final output is replaced.

## Declare the executing model, once

Before the first file, run this once. It is never repeated and costs no per-row effort:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py claim --route 01-financials --agent J2 --model "<model name>"
```

Added or resolved rows are stamped with it mechanically at publish time, so **never add a model column** and never name the model in a row.

## Build the deterministic comparison

```powershell
python instructions/01-pdf-extraction-csv/workflow.py compare --route 01-financials --file <file_id>
```

The command writes `pair-index.csv`, `coverage-diff.csv`, an empty `resolution.csv`, and an empty `coverage-resolution.csv` in the file folder.

A/B records align on the **physical cell**, nothing else:

```text
file_id + source_page + source_row_label + source_column_label + source_occurrence
```

Family, category and table title are deliberately **not** part of identity. They are read decisions, and two careful readers disagree about them on the same printed cell. Pairing on them turned one observation into two unrelated rows and made whole documents unadjudicatable. They are compared instead, so a disagreement arrives as one row with two readings, which is what it always was.

Extractor-created labels and row counts do not establish agreement.

Each conflict is typed so its nature is known before the page is opened:

- `VALUE_CONFLICT`: different readings of a printed cell; resolve against the image.
- `CLASSIFICATION_CONFLICT`: different family, category or subject; review the image and the route vocabulary. A component assigned to a fund total changes the analysis even when the number agrees.
- `CONTEXT_CONFLICT`: different date, unit, scale, horizon or qualifier; review the governing header and notes. A populated field is not automatically correct.

### Source interpretation and completion

- Each table is reviewed by column and row: date, unit, scale, subject, method, fee treatment and value scope. A comparative column keeps its own date; a component remains separate from the total.
- A named currency heading remains in `currency_scale` beside every governed monetary cell. A bare `$` does not mean US dollars when the heading states Canadian or Australian dollars. Normalization retains that denomination; unconverted currencies remain separate in fund periods and generated amount inputs.
- A statement label such as Total assets is not an institution name. A row that retains that label as its subject uses `other_printed_scope`; the document context identifies the reporting institution or combined group. A single named fund partnership remains a `fund`, not a pension or institutional reporting entity.
- Definitions, legends, accounting policies and performance-method notes are `definition_context` records, including on pages with no numbers. A mixed disclaimer page still yields its methodology records. Illustrative amounts inside a definition remain text, not actual fund observations.
- Definition markers resolve within the same table and page before a unique document-wide definition. A reused marker with different meanings requires a table-specific reference. A Modified Dietz method under a time-weighted heading requires that refinement in the cited definition.
- Text evidence contains the complete printed number, not a substring of another number. Printed number words remain words in `metric_value_raw`; normalization reads the number-word matrix. A TXT conversion defect uses `IMAGE_ONLY:` with the physical page image and a specific explanation; the adjudicator reviews every image-only row.
- Page counts include definitions and all populated allowed comparative cells. The count comes from the page image before reconciliation with the record CSV. Every zero-observation page with numeric signals needs a `NO_ELIGIBLE_REASON:` explanation; thin pages need `PARTIAL_BY_SCOPE:`. Each explanation names excluded rows or columns and the category test, not reading difficulty.
- `UNREADABLE` and `DEFERRED_BY_SCOPE` are unfinished CORE work. A settled exclusion uses `NO_ELIGIBLE_DATA` or `REFERENCE_ONLY` with source-backed reasons. Candidate handoff and final publication share the grid-completeness check; final construction validates before replacing outputs.
- Gates test recorded evidence and consistency. They do not establish that every permitted source fact was found. Both extractors inspect every page, and the adjudicator reviews every populated table's scope and governing notes, including agreements.
- `lane-check` validates existing finals before marking historical work `DONE`; `REVIEW_REQUIRED` goes to the adjudicator, never to an extractor rewriting original candidates.


| Document type | Product | Allowed record family | Grain | Usual categories (any name of the family's kind is valid) |
|---|---|---|---|---|
| `Financials` | `CORE` | `document_context` | one row per document | none |
| `Financials` | `CORE` | `financial_statement_observation` | one populated allowed source value cell | `beginning_capital`, `ending_capital`, `cash`, `total_assets`, `total_liabilities`, `net_assets`, `partners_capital`, `net_investment_income`, `investment_fair_value`, `investment_cost`, `fund_expense`, `interest_expense`, `realized_gain_loss`, `unrealized_gain_loss` |
| `Financials` | `CORE` | `fund_economics_observation` | one populated allowed source value cell | `commitment`, `paid_in_capital`, `paid_in_capital_multiple`, `contribution`, `distribution`, `nav`, `unfunded_commitment`, `recallable_distribution`, `tvpi`, `dpi`, `rvpi`, `moic`, `ownership_percentage`, `income`, `fee`, `carried_interest` |
| `Financials` | `CORE` | `position_observation` | one populated allowed source value cell for one named position | `quantity`, `cost`, `fair_value`, `market_value`, `notional`, `portfolio_weight`, `interest_rate`, `maturity_date` |
| `Financials` | `CORE` | `fee_observation` | one populated allowed source value cell | `management_fee`, `performance_fee`, `cost_bps`, `offset`, `fee_benchmark`, `nav_aum_denominator` |
| `Financials` | `CORE` | `financing_observation` | one populated allowed source value cell | `outstanding_balance` |
| `Financials` | `CORE` | `definition_context` | one printed footnote, definition, methodology note, or legend entry | none |

Pick the family from the table shape and the name from the printed meaning. A family takes any name of its kind below; the usual family is guidance for a mixed table, never a rule.

| `metric_category` | Means | Unit | Usual family |
|---|---|---|---|
| `commitment` | Capital committed to the fund by the investor or in total. | currency | `fund_economics_observation` |
| `paid_in_capital` | Capital contributed to date (PIC, paid-in, contributed capital). | currency | `fund_economics_observation` |
| `paid_in_capital_multiple` | Paid-in capital as a multiple of commitment, printed in the multiples block beside TVPI, RVPI, and DPI. The value exceeds 1.00 where the fund recycles capital or contributes outside commitment. The contributed amount uses paid_in_capital. | x | `fund_economics_observation` |
| `contribution` | One contribution or a period's contributions, as a flow. | currency | `fund_economics_observation` |
| `distribution` | Capital distributed to date or in a period, including a printed component such as preferred return when the page lists it inside distributions. | currency | `fund_economics_observation` |
| `nav` | Residual value of one fund, LP position, or share class at a date, printed as NAV, remaining value, reported value, or ending market value at that grain. **Qualified: fill `value_scope`** from what the page states (a footnote key cited in `definition_keys`, or a printed phrase copied into `basis_raw`); write `unstated` when the page states nothing. | currency | `fund_economics_observation` |
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
| `beginning_capital` | Opening balance of a capital account, partners' capital, or net assets for a period, at the entity or partner grain printed by the statement. **Qualified: fill `value_scope`** from what the page states (a footnote key cited in `definition_keys`, or a printed phrase copied into `basis_raw`); write `unstated` when the page states nothing. | currency | `financial_statement_observation` |
| `ending_capital` | Closing balance of a capital account, partners' capital, or net assets for a period, at the entity or partner grain printed by the statement. A residual closing balance may also represent NAV. **Qualified: fill `value_scope`** from what the page states (a footnote key cited in `definition_keys`, or a printed phrase copied into `basis_raw`); write `unstated` when the page states nothing. | currency | `financial_statement_observation` |
| `return` | The return printed for a period or horizon, as a percent, under the method, fee basis, and hedge treatment stated by the report. Methods include time-weighted, Modified Dietz, holding-period, annualized, and money-weighted. Every return row states its own method and fee_basis, read from the footnote or header it cites, or unstated. A figure labelled IRR uses irr. **Qualified: fill `method` and `fee_basis`** from what the page states (a footnote key cited in `definition_keys`, or a printed phrase copied into `basis_raw`); write `unstated` when the page states nothing. | % | `performance_observation` |
| `irr` | Internal rate of return, net or gross, since inception or for a horizon, where the page labels it IRR. A money-weighted return printed under another label stays return, with its method recorded. **Qualified: fill `fee_basis`** from what the page states (a footnote key cited in `definition_keys`, or a printed phrase copied into `basis_raw`); write `unstated` when the page states nothing. | % | `performance_observation` |
| `alpha` | Return minus the stated benchmark's return (value added, excess return). | % | `performance_observation` |
| `pme` | Public market equivalent ratio (Kaplan-Schoar or as printed). | x | `performance_observation` |
| `direct_alpha` | Direct alpha against a stated public index. | % | `performance_observation` |
| `sharpe_ratio` | Sharpe ratio as printed. | ratio | `performance_observation` |
| `tracking_error` | Tracking error against the stated benchmark. | % | `performance_observation` |
| `yield` | A rate of income as a percent: distribution rate, income yield, or investment yield. Total-period performance uses return. | % | `performance_observation` |
| `aum` | Assets under management or total assets at manager, plan, endowment, pool, fund, or asset-class scope. **Qualified: fill `value_scope`** from what the page states (a footnote key cited in `definition_keys`, or a printed phrase copied into `basis_raw`); write `unstated` when the page states nothing. | currency | `performance_observation` |
| `cash` | Cash and cash equivalents at a date or a period's opening or closing balance. | currency | `financial_statement_observation` |
| `total_assets` | Total assets. | currency | `financial_statement_observation` |
| `total_liabilities` | Total liabilities. | currency | `financial_statement_observation` |
| `net_assets` | Net assets of the reporting entity as printed, restricted or unrestricted: total assets less total liabilities at statement grain. | currency | `financial_statement_observation` |
| `partners_capital` | Partners' capital by partner class or in total, and its change from operations, at the entity grain of the statement. Position-level closing capital uses ending_capital. | currency | `financial_statement_observation` |
| `net_investment_income` | Net investment income or loss for a period. | currency | `financial_statement_observation` |
| `investment_fair_value` | Investments at fair value as a line of a financial statement or note, including the Level 1, 2, and 3 hierarchy lines. The amount precedes the entity's other assets and liabilities in the NAV build-up. **Qualified: fill `value_scope`** from what the page states (a footnote key cited in `definition_keys`, or a printed phrase copied into `basis_raw`); write `unstated` when the page states nothing. | currency | `financial_statement_observation` |
| `investment_cost` | Cost basis of investments on a statement. | currency | `financial_statement_observation` |
| `fund_expense` | An expense line or an expense ratio of the fund (professional fees, organizational expenses, total expenses). | currency or % | `financial_statement_observation` |
| `interest_expense` | Interest expense for a period. | currency | `financial_statement_observation` |
| `realized_gain_loss` | Realized gain or loss on investments for a period. | currency | `financial_statement_observation` |
| `unrealized_gain_loss` | Change in unrealized gain or loss for a period. | currency | `financial_statement_observation` |
| `quantity` | Shares, units, or par held. | count | `position_observation` |
| `cost` | Cost of a holding. | currency | `position_observation` |
| `fair_value` | Fair or market value of one named holding on a schedule of investments. Fund residual value uses nav; statement investment lines use investment_fair_value. **Qualified: fill `value_scope`** from what the page states (a footnote key cited in `definition_keys`, or a printed phrase copied into `basis_raw`); write `unstated` when the page states nothing. | currency | `position_observation` |
| `market_value` | Market value under that printed heading for one holding or one allocation bucket. The same measure as fair_value at holding grain; at fund grain the residual value is nav. **Qualified: fill `value_scope`** from what the page states (a footnote key cited in `definition_keys`, or a printed phrase copied into `basis_raw`); write `unstated` when the page states nothing. | currency | `position_observation` |
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

| Printed label | Category |
|---|---|
| Capital Contributed, Contributed Capital, Paid-In Capital, PIC, Paid-In, Total Contributions | `paid_in_capital`, never `moic` (PIC is an amount, not a multiple) |
| Contributions for a single period or transaction row | `contribution` |
| Capital Commitment, Commitment | `commitment` |
| Distributions, Total Distributed, Capital Distributed | `distribution` |
| Ending Market Value, Market Value, Net Asset Value, NAV, Remaining Value, Reported Value | `nav` in a `fund_economics_observation` table; `market_value` in a `position_observation` table |
| Fair Value, Estimated Fair Value | `fair_value` in `position_observation`; `investment_fair_value` in `financial_statement_observation`; `nav` in `fund_economics_observation` |
| Cost, Cost Basis | `cost` |
| Net IRR, IRR, Since-Inception IRR | `irr` |
| TVPI, Total Value to Paid-In, Investment Multiple | `tvpi` |
| DPI, Distributions to Paid-In, Realization Multiple | `dpi` |
| Unfunded, Remaining Commitment, Uncalled Capital | `unfunded_commitment` |
| Value Added, Excess Return, Difference, Relative Return, Over/Under Benchmark: a row that is the portfolio's return minus its benchmark's | `alpha`, never `return` |

## The adjudicator is the resolving authority

The adjudicator compares both candidates with the source. Unsupported readings remain blocked; no value, identity or qualifier is guessed to obtain a PASS. Every conflict, one-sided record and coverage difference requires a source-backed decision.

Three things follow from that, and they override any instinct to be conservative:

**Open the page image. It is the authority, not a last resort.** The worklist row for this file gives `image_dir`; the pages are `page-001.png`, `page-002.png`, and so on, one per printed page. On a value conflict, a column-assignment question, a header the grid rendered blank or as prose, or any row the TXT leaves unsettled, **read the image before deciding**. The TXT is linearised and loses columns. On the 29 reviewed documents, the corrected grid found 5,509 of 6,577 in-scope printed cells and retained a source header on 92.9% of its matches. The image is what the document actually prints. One adjudicator recovered 260 real cells from a page image that both extractors had skipped, and they verified against the printed arithmetic.

**Correct source readings through adjudication.** After valid candidates have been compared, a source-backed correction uses `MERGE`; a missed definition or value uses `ADD`. Failing candidate validation returns to its owner before comparison. A missing source fact remains blocked pending source review.

**Read the cells both reading groups missed.** `ADD` exists for this. If the page prints an allowed cell neither candidate holds, write it: `pair_id` blank, `agent_role=ADJUDICATED`, `source_agents=ADJUDICATOR`, status `ADDED`, with a real `evidence_quote` from the page. Rows quarantined into `malformed-a.csv` or `malformed-b.csv` are not lost data, they are unread cells: read them off the image and either merge them into the pair or add them.

## Rows requiring source review

Review every conflict, every one-sided pair, every image-only record, and each sampled agreement. Inspect every populated table's date columns, account owner, units and governing footnotes. A defect found in an agreed row requires `MERGE` or `REJECT` even when `requires_review=NO`; review every affected row in that source block.

The source rule is fixed: one populated allowed value cell is one row. A printed row with N populated allowed value columns requires N rows; blanks and dash/N/A cells require zero rows.

**A one-sided row is a claim to check against the page picture.** `A_ONLY` and `B_ONLY` mean one reading group saw a cell the other did not. Read the page: if the cell is printed and allowed, the row is right and the other reading group missed it; if it is not, reject it. Read the page picture. Do not take the one-sided row as proved.

**A document where nothing pairs is expected on prose families, not a failure.** Provisions (`legal_term`, `legal_clause`, `subscription_reference`, `ddq_quantitative_observation`, `stewardship_policy`) are keyed on `source_row_label`, which for prose is whichever fragment each reading group chose, so two reading groups rarely map to the same key. One legal document paired 0 of 88 rows with both reading groups valid. Expect to work those documents row by row against the page instead of by rule, and expect the row count to be the sum of both reading groups minus the merged duplicates.

## Deciding a disagreement

Judge against the printed page, never by which candidate has more rows. The recurring disagreements have fixed answers:

**Consult the grid on a value or column disagreement, then confirm on the page.** The worklist's `grid_path` lists every printed numeric cell for that page with its row label, `column_index` and column header, taken from the PDF's own coordinates. It is a strong witness on column membership, which is where linearised text fails.

It is not an authority. On the 29 reviewed documents, it found **5,509 of 6,577 in-scope printed cells (83.8% recall)**, and 5,509 of its 6,398 rows matched a reviewed cell (86.1% precision). On a dense table it can drop a column, and on a page with narrative text above the table it can take a fragment of a sentence as a column header. So:

- A grid column header that reads as prose (`as of`, `billion`, `2025, up from`) means the grid failed on that page. Ignore its headers there and read them off the PNG.
- A value the grid does not list is not thereby wrong. The grid omits columns it failed to resolve. Check the PNG before deleting a row.
- **When the grid and the page image disagree, the image wins.** Always.

A page is absent from the grid when it is scanned or holds no numeric table; `data/documents/grids/MANIFEST.csv` says which.

A convention applies only within the source block that supports it. Every value, classification and context decision retains its source rationale; agreement between the lanes does not establish correctness.

| Disagreement | Correct answer |
|---|---|
| Same row and column, different numbers | The value printed on the page. Use the grid to locate it, the PNG to confirm it. |
| Same number, different column | The `column_index` the grid assigns it, once the grid's header for that column is confirmed as a real header and not a prose fragment. This is the commonest wrong-value defect: a wide table read from linearised text shifts a column, and the numbers stay plausible. |
| Same number, one side keeps the printed `%`, `x`, or currency symbol and the other strips it (`0.52` vs `0.52%`, `(51.90)` vs `(51.90%)`) | **The printed form, symbol included,** with `unit` set to `%` or `x` and `currency_scale` to the currency. The value column is raw; stripping is a normalisation and is wrong. This single convention was 549 of the 551 value conflicts on one document. **`validate-final` enforces it**: any row whose own `evidence_quote` prints a `%` or `x` attached to the value while the value drops it is rejected, naming the row. Apply it to every row of every document, including the ones where the conflict stays invisible: one shard applied it on two documents and not the third, leaving 61 of 73 rows in the other format, and the same metric reads two ways. Where the page spells the word (`3.6 percent`) there is no symbol to keep, and `unit` alone carries it. |
| Value differs only by spacing | `$61.4` and `$4,858.5`, with no gap between symbol and digits; whitespace is the one thing closed. |
| Same cell, one lane cites the full printed line and the other cites only the value (`(51.90%)`) | The rows are otherwise equal; accept the lane with the full line, because its quote proves the value and the short one proves only that the digits occur somewhere on the page. |
| One side gives `unit` or `currency_scale`, the other blanks it | The populated side, if the page prints that unit or scale in the cell, the column header, the row label, the table title, or a banner above the table. A label printed once governs every value under it. A `%` printed in the cell or column header is a printed unit, so a blank `unit` beside a percentage is wrong. |
| One side blanks any context field: `source_section`, `source_table`, `asset_class`, `strategy`, `geography`, `horizon`, `as_of_date`, `period_start`, `period_end`, `vintage_year`, `currency_scale` | If the page prints it, the populated candidate is right. If the page does not print it, the blank is right. These are per-page facts, so check the page once and apply the answer to every row on it: one lane left `source_section` blank on 1,600 rows whose pages all printed the heading. |
| `source_section` vs `asset_class` for the same heading (`Real Assets`, `Private Assets`, `Fixed income:`) | A heading **inside** the table that governs the rows beneath it is the rows' `asset_class` (or `strategy` or `geography`, by what it names), never `source_section`. `source_section` is the page's section heading **above** the table. Both can be populated on one row; they are different headings. |
| One lane puts a two-level grouping in `asset_class` alone (`Opportunistic`) and leaves `strategy` blank; the other splits it (`Real Estate` / `Opportunistic`) | The split. The broader printed grouping is `asset_class`, the narrower is `strategy`. |
| `subject_type` `fund` vs `investment` vs `portfolio`, or `benchmark` vs `peer_group` | By the row's own label: a vehicle (`... Fund V, L.P.`, `... LLC`, a named fund) is `fund`; the owner's aggregate (`Total Plan`, `Endowment`, `Alternatives Portfolio`) is `portfolio`; a holding, security, or property inside a vehicle is `investment`; an index or policy line is `benchmark`; a peer universe, median, or percentile line (`NACUBO`, a Cambridge universe, `Peer Median`) is `peer_group`. One document split `fund` against `investment` on 465 of 466 rows. |
| Entity name differs | The name **printed on the cited page**, at the most specific level, **in full**: `Antares Private Credit Fund`, never its ticker `ABDC`. A value taken from the TXT header block, the filename, or general knowledge of the institution is wrong even when it names the same organisation. A period label (`Q2 2009`, `1-Yr`) is never a `subject_name`; it belongs in `horizon`. |
| `metric_name` differs only by trimming, singularising, or dropping a qualifier (`Return` vs `Annualized Returns`, `Distribution Rate` vs `Annualized Distribution Rate`) | The printed wording, in full. |
| `metric_name` taken from different axes (`3 Year` vs `Annualized Returns` for the same cell) | Apply the table-shape rule in the extractor prompts: rows that are measures name the metric; rows that are entities under measure columns take the leaf column header; only a table whose rows are entities and whose columns are periods takes its own title. A period is never a metric name. |
| `alpha` vs `return` on a `Value Added`, `Excess Return`, or `Difference` row | `alpha`: the row is the portfolio's return minus its benchmark's. |
| Date format differs | The date **printed verbatim**. `September 30, 2022` is correct; `2022-09-30` is a reformat and is wrong. Where both are verbatim and one is fuller (`March 31, 2026` vs `March 2026`), the fuller printed form. |
| `source_table` is the short heading on one side and the full printed title on the other | The full printed title that names the whole table. |
| Category or family differs | Apply the disambiguation table in the extractor prompts; the family follows the table shape and the category follows the printed meaning, each judged on its own. |
| Family differs on a fund-by-fund table that prints capital-account columns (Commitment, Unfunded, PIC, Market Value) beside multiples and IRRs | `fund_economics_observation`, **every column in that table**, per the extractor chooser. A lane that typed it `performance_observation` also tends to have skipped the capital columns, so its rows are wrong on family and its gaps are filled from the other lane one-sided. On one such table this was 676 paired rows and 126 rows only one lane extracted. |
| Period columns (`Qtr`, `1 Year`, `3 Year`) read as `return` by one lane and `irr` by the other | **The banner over the column block decides, in either family.** A banner reading `IRR`, `Net IRR`, or `Since Inception IRR` makes the columns `irr`; a banner reading `Time Weighted Return`, `TWR`, `Net Time Weighted Returns`, or `Modified Dietz` makes them `return`, and `fund_economics_observation` permits `return` for this case. Name the banner in `reason`. One schedule printed both blocks side by side, `Net Time Weighted Returns (1)` and `Inception IRR (4)`, and 452 rows of the first block were settled as `irr` because the family was thought to forbid `return`; that reading is wrong and is the case this rule exists for. |
| A rate the page labels assumed, expected, target, or actuarial (`Actuarial Assumed Interest Rate`, `Smooth Expected Rate of Return`) | Not `return` and not `irr`. It is an assumption; reject it unless the family has a category for it. |
| A balance-sheet line (`Collective trust funds`, `Investments, at fair value`) read as `nav` | `investment_fair_value` in a `financial_statement_observation` table. `nav` is a fund's or share class's net asset value on a performance, capital-account, or NAV page. |
| A plan's or endowment's total value (`market value of the PUF was $39.5 billion`) read as `nav` | `aum`. |
| A waterfall component (`Preferred return`, `Return of capital`) read as `distribution` | The narrower name when the vocabulary has one: `preferred_return`, `return_of_capital`. A total distribution line stays `distribution`. |
| An expense ratio (`Total Annual Expenses 9.89%`) read as `fee` | `fund_expense` with `unit` `%`. |
| A portfolio share of an asset class (`34%` beside `Natural Resources (Net)`) read as `ownership_percentage` | `actual_allocation`. `ownership_percentage` is a stake in a vehicle or a firm. |
| `Market Value` read as `aum` vs `nav` | `nav` in a `fund_economics_observation` table; `market_value` in a `position_observation` table; `aum` only for a manager's or plan's stated total assets under management. |
| `PIC` or `Paid-In` read as `moic` | `paid_in_capital`. PIC is an amount; `moic` is a multiple. |
| A row carries `REPAIRED_SHIFT` in `notes` | Adjudicate it like any other row. The note records that its cells were realigned; its value is that lane's own reading. |
| The two lanes file the `document_context` row on different pages | `source_page` `1`. The row describes the whole document, so its page is a constant. Merge the two one-sided rows into one. |
| An `A_ONLY` row and a `B_ONLY` row on the same page describe the same printed thing, and differ only in a key column: one lane blank where the other carries a printed heading, most often `source_table` | They are one cell, not two. **Publish one row, not both.** Take the side that carries the printed value, since a heading printed on the page is never correctly blank, and reject the other. Twelve glossary definitions arrived this way on one document, identical in wording, and publishing both sides would have doubled every one of them. Before ruling a page's one-sided rows genuine, sort them by `source_row_label` and check whether an unpaired row on the other side carries the same label. |
| A cover page carries the `document_context` row and one lane marked it `ELIGIBLE_DATA_EXTRACTED` while the other marked it `REFERENCE_ONLY` | `REFERENCE_ONLY`, or whatever the page's printed content deserves. The identity row is bookkeeping and never makes a page eligible, and it stays on page 1 regardless. |
| One lane's `text_raw` repeats the term that names the row and the other's starts after it: `Clawback - GP carried interest that must be returned` against `GP carried interest that must be returned` | The shorter one. The term is already in `source_row_label`, so repeating it stores the same fact twice. **Rule the document once and apply it to every row**: this split arrives on every provision and every definition a lane wrote, never on one of them, and one round produced nineteen of these across two documents. |
| Two one-sided provision rows on the same page carry the same operative wording under different `source_row_label` values, one the section heading above the passage and one the clause's opening words | The printed defined term or clause heading (`Investment Period`, `Recall of Distributions`), and one row, not two. A section heading repeated across several provisions is the giveaway: three clauses filed as `Interim Distributions` are three rows that each belong under their own printed name. Read the page before merging, then reject the duplicate. |
| Prose or provisions on a mixed page | Review the individual clause against its permitted family. Binding rules and definitions are records; historical narrative and unrelated boilerplate are excluded. A document-wide narrative label never overrides a qualifying clause or methodology note. |
| A lane declares a page `NO_ELIGIBLE_DATA` with a reasoned `NO_ELIGIBLE_REASON:` note naming a category test, and the other extracted from it | The note is evidence of judgement, not of abandonment, so read the page before overriding it. If the page prints something in an allowed category the extracting lane is right; if the note correctly identifies it as out of category, the zero is right and the other lane's rows are rejected. Do not resolve it by preferring the larger lane. |

Record the reason applied alongside the decision.

## Resolution CSV

Header, verbatim:

```csv
"pair_id","decision","reason","contract_version","file_id","source_sha256","canonical_doc_type","route","product_tier","agent_role","record_family","source_page","source_structure_type","source_section","source_table","source_row_label","source_column_label","source_occurrence","subject_type","subject_name","asset_class","strategy","geography","manager_name","investor_name","portfolio_name","vintage_year","period_start","period_end","as_of_date","horizon","currency_scale","metric_category","metric_name","metric_value_raw","unit","term_category","text_raw","basis_raw","condition_raw","evidence_quote","evidence_class","notes","source_agents","adjudication_status","definition_keys","method","fee_basis","value_scope","sector"
```

Allowed decisions:

- `CONFIRM` : the sampled `EXACT` pair is source-correct.
- `ACCEPT_A` : A is source-correct.
- `ACCEPT_B` : B is source-correct.
- `MERGE` : neither candidate is complete; provide one corrected full record in the appended record columns.
- `REJECT` : neither candidate is publishable.

`MERGE` and `ADD` fill the appended record columns; other decisions leave them blank. New or corrected records use contract_version `2026-09-01.2`.
- `ADD` : both missed an allowed observation; leave `pair_id` blank and provide the full record.

Every required pair carries one decision. For `MERGE` and `ADD`, use `agent_role=ADJUDICATED`; provide direct source evidence and controlled family/category values. Do not edit A or B.

## Coverage resolution

Header, verbatim:

```csv
"source_page","final_page_status","final_expected_observation_count","reason"
```

Write one row for every page in `coverage-diff.csv`, after counting allowed source observations from the PNG. The final expected count must equal the final record count on that page. Do not resolve a coverage conflict by choosing the larger candidate automatically.

Three coverage disagreements recur on every document and have fixed answers:

| Disagreement | Correct answer |
|---|---|
| Both lanes report zero rows | Check the page for missing definitions and permitted values before deciding its status. Add in-scope footnotes, legends, accounting policies and methodology with `ADD`; a disclaimer heading does not exclude them. Only then settle `REFERENCE_ONLY` or `NO_ELIGIBLE_DATA`. |
| `expected_observation_count` differs with both reading groups `ELIGIBLE_DATA_EXTRACTED` | Neither reading group's count: each reading group counted what it extracted. Count the allowed cells on the PNG directly; the answer is usually the larger of the two plus whatever both missed, and is never decided by averaging. |
| One reading group `NO_ELIGIBLE_DATA`, the other extracted rows | Read the page. A case study, sidebar, or marketing panel that prints real fund figures (`Fund Commitment $25.7M`, a loss rate, a count of deals) is allowed and its `evidence_class` is `actual` if the figures are stated as fact; the reading group that skipped it was wrong. A panel of hypothetical or illustrative figures is `REFERENCE_ONLY` and the rows are rejected. |

## Save progressively (hard requirement)

**Append each decision when made and save, never in one batch at the end.** Save `resolution.csv` after each settled group of pairs, and `coverage-resolution.csv` after each settled page. Write the header once, then append; never rewrite a file from scratch and lose decisions already recorded. If the session stops, every decision already made is on disk and the next session resumes at the first unresolved pair.

## Allowed scope

| Document type | Product | Allowed record family | Grain | Usual categories (any name of the family's kind is valid) |
|---|---|---|---|---|
| `Financials` | `CORE` | `document_context` | one row per document | none |
| `Financials` | `CORE` | `financial_statement_observation` | one populated allowed source value cell | `beginning_capital`, `ending_capital`, `cash`, `total_assets`, `total_liabilities`, `net_assets`, `partners_capital`, `net_investment_income`, `investment_fair_value`, `investment_cost`, `fund_expense`, `interest_expense`, `realized_gain_loss`, `unrealized_gain_loss` |
| `Financials` | `CORE` | `fund_economics_observation` | one populated allowed source value cell | `commitment`, `paid_in_capital`, `paid_in_capital_multiple`, `contribution`, `distribution`, `nav`, `unfunded_commitment`, `recallable_distribution`, `tvpi`, `dpi`, `rvpi`, `moic`, `ownership_percentage`, `income`, `fee`, `carried_interest` |
| `Financials` | `CORE` | `position_observation` | one populated allowed source value cell for one named position | `quantity`, `cost`, `fair_value`, `market_value`, `notional`, `portfolio_weight`, `interest_rate`, `maturity_date` |
| `Financials` | `CORE` | `fee_observation` | one populated allowed source value cell | `management_fee`, `performance_fee`, `cost_bps`, `offset`, `fee_benchmark`, `nav_aum_denominator` |
| `Financials` | `CORE` | `financing_observation` | one populated allowed source value cell | `outstanding_balance` |
| `Financials` | `CORE` | `definition_context` | one printed footnote, definition, methodology note, or legend entry | none |

### Excluded scope

- **Financials:** Generic statement transcription; non-investment operating lines; null cells; hypothetical values.

## Build and validate the final files

```powershell
python instructions/01-pdf-extraction-csv/workflow.py build-final --route 01-financials --file <file_id>
python instructions/01-pdf-extraction-csv/workflow.py validate-final --route 01-financials --file <file_id>
```

The workflow publishes agreed unsampled records mechanically and applies the adjudicator's decisions to reviewed pairs. Final rows receive `agent_role=ADJUDICATED`, populated `source_agents`, and an adjudication status of `AGREED`, `VERIFIED_ONE_SIDED`, `RESOLVED`, or `ADDED`.

Finish one file and save its final records and final coverage before opening the next worklist row.
