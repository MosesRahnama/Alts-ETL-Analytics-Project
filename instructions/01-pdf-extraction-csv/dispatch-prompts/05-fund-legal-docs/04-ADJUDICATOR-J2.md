# Fund Legal Documents: ADJUDICATOR J2

> **Binding:** Do not dispatch sub-agents. Do not use Python, scripts, regex, or automated table parsing to read source content. The workflow may be used only to validate, pair, and build files mechanically. Append decisions to the resolution CSVs and save after each settled group, never in one batch at the end.

- **Project root:** the repository root, the folder holding `README.md`; every path below is relative to it
- **Worklist:** `instructions/01-pdf-extraction-csv/worklists/active/05-fund-legal-docs.csv`
- **Shard:** worklist rows with even `work_order` values.

For each assigned file, wait until both extractors have finished it: `coverage-a.csv` and `coverage-b.csv` each carry a row for every page. Read only this prompt, those candidates, the generated comparison files, the pre-computed table grid at the worklist's `grid_path`, and the source TXT/PDF/PNGs. **The page images at the worklist's `image_dir` are the adjudicator's to open and are expected to be used**; unlike the extractors, the adjudicator is never limited to linearised text.

## Clear the mechanical defects before anything else

`compare` and `build-final` both refuse to run while either candidate fails validation, so a mechanical defect is not a blemish on one row: it deadlocks the whole file before a pair-index exists, and the merge where it would be fixed is never reached. Two defects have deterministic repairs. **Run both, for both lanes, before `compare`. They need no operator approval; they are part of the adjudicator's job.**

```powershell
python instructions/01-pdf-extraction-csv/workflow.py repair-shifted --route 05-fund-legal-docs --file <file_id> --agent A
python instructions/01-pdf-extraction-csv/workflow.py repair-shifted --route 05-fund-legal-docs --file <file_id> --agent B
python instructions/01-pdf-extraction-csv/workflow.py repair-value-format --route 05-fund-legal-docs --file <file_id> --agent A
python instructions/01-pdf-extraction-csv/workflow.py repair-value-format --route 05-fund-legal-docs --file <file_id> --agent B
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 05-fund-legal-docs --file <file_id> --agent A
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 05-fund-legal-docs --file <file_id> --agent B
```

`repair-value-format` restores a printed `%` or `x` that a row's own `evidence_quote` proves the value dropped. It touches no digits, asserts the result equals the value plus that symbol before writing, and skips any row where the quote also prints the value bare, because a quote showing both a threshold like `<1%` and the cell's own bare figure is ambiguous and must not be rewritten. It reports how many repaired rows still leave `unit` blank: a printed `%` or `x` is a printed unit, so set it in the merged record when those rows are adjudicated.

Whatever either command leaves failing is a cell to correct from the page, not a reason to stop.

The repair restores the missing cell where the other lane's row for the same printed cell says it belongs, and it is allowed to do that only when one placement fits; the value put back is still the lane's own reading, so agreement afterwards is two-source confirmation. Repaired rows carry `REPAIRED_SHIFT` in `notes` and are adjudicated like any other row. Rows it refuses move to `malformed-a.csv` or `malformed-b.csv` in the file folder. **Those are unread cells, not deleted ones: open the page image, read what the row was meant to say, and put it back** by merging it into the pair it belongs to or by adding it with `ADD`. Leaving them in the quarantine file loses printed data that one lane did reach.

If a lane still fails `validate-candidate` after repair for a reason other than width, that is a cell to correct, not a lane to discard. Read the page, fix the cell in the merged record, and note the correction in `reason`. Do not fall back to the passing lane just because it passes: it may be the one that is wrong, and the final file has to satisfy `validate-final` either way.

## Declare the executing model, once

Before the first file, run this once. It is never repeated and costs no per-row effort:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py claim --route 05-fund-legal-docs --agent J2 --model "<model name>"
```

Added or resolved rows are stamped with it mechanically at publish time, so **never add a model column** and never name the model in a row.

## Build the deterministic comparison

```powershell
python instructions/01-pdf-extraction-csv/workflow.py compare --route 05-fund-legal-docs --file <file_id>
```

The command writes `pair-index.csv`, `coverage-diff.csv`, an empty `resolution.csv`, and an empty `coverage-resolution.csv` in the file folder.

A/B records align on the **physical cell**, nothing else:

```text
file_id + source_page + source_row_label + source_column_label + source_occurrence
```

Family, category and table title are deliberately **not** part of identity. They are read decisions, and two careful readers disagree about them on the same printed cell. Pairing on them turned one observation into two unrelated rows and made whole documents unadjudicatable. They are compared instead, so a disagreement arrives as one row with two readings, which is what it always was.

Extractor-created labels and row counts do not establish agreement.

Each conflict is typed so its nature is known before the page is opened:

- `VALUE_CONFLICT` : same cell, different printed value. One of them misread the page. Settle it against the image; this is the only kind that can put a wrong number in the dataset.
- `CLASSIFICATION_CONFLICT` : same cell, same value, different family, category or subject. Nobody misread anything; they mapped it differently. Settle it with the category rules, not the page.
- `CONTEXT_CONFLICT` : same cell, same value, same mapping, different date, unit, scale or horizon. Usually one side left a field blank that the page states.

## The adjudicator is the resolving authority

The third reader is the only reader that sees the printed page with both candidates in front of it. The extractors work on their own files and single-pass; the third reader does not. **Nothing leaves this stage unresolved.** Every conflict, every one-sided row, every quarantined row, and every page-coverage disagreement is decided here, from the source, and the final file is the answer.

Three things follow from that, and they override any instinct to be conservative:

**Open the page image. It is the authority, not a last resort.** The worklist row for this file gives `image_dir`; the pages are `page-001.png`, `page-002.png`, and so on, one per printed page. On a value conflict, a column-assignment question, a header the grid rendered blank or as prose, or any row the TXT leaves unsettled, **read the image before deciding**. The TXT is linearised and loses columns; the grid drops columns on dense tables and is about 86% right; the image is what the document actually prints. One adjudicator recovered 260 real cells from a page image that both extractors had skipped, and they verified against the printed arithmetic.

**Repair what is mechanically repairable; do not pass it through.** A shifted row, a value missing its printed symbol, a stripped currency, a reformatted date, a row on the wrong family, a `document_context` row on the wrong page: these are the adjudicator's to fix in the final via `MERGE`, not to accept from whichever lane happens to be closer. A lane that fails `validate-candidate` for a content reason is not disqualified; read the page, correct the cell, and merge. The final file must pass `validate-final`, which enforces the value-format rule, so a defect passed through will simply fail there.

**Read the cells both reading groups missed.** `ADD` exists for this. If the page prints an allowed cell neither candidate holds, write it: `pair_id` blank, `agent_role=ADJUDICATED`, `source_agents=ADJUDICATOR`, status `ADDED`, with a real `evidence_quote` from the page. Rows quarantined into `malformed-a.csv` or `malformed-b.csv` are not lost data, they are unread cells: read them off the image and either merge them into the pair or add them.

## Rows requiring source review

Review every conflict, `A_ONLY`, and `B_ONLY` pair and every `EXACT` pair marked `requires_review=YES`. Work `VALUE_CONFLICT` first. The `EXACT` sample is deterministic and includes at least one pair from each populated page. Review every row in `coverage-diff.csv`.

The source rule is fixed: one populated allowed value cell is one row. A printed row with N populated allowed value columns requires N rows; blanks and dash/N/A cells require zero rows.

**A one-sided row is a claim to check against the page picture.** `A_ONLY` and `B_ONLY` mean one reading group saw a cell the other did not. Read the page: if the cell is printed and allowed, the row is right and the other reading group missed it; if it is not, reject it. Read the page picture. Do not take the one-sided row as proved.

**A document where nothing pairs is expected on prose families, not a failure.** Provisions (`legal_term`, `legal_clause`, `subscription_reference`, `ddq_quantitative_observation`, `stewardship_policy`) are keyed on `source_row_label`, which for prose is whichever fragment each reading group chose, so two reading groups rarely map to the same key. One legal document paired 0 of 88 rows with both reading groups valid. Expect to work those documents row by row against the page instead of by rule, and expect the row count to be the sum of both reading groups minus the merged duplicates.

## Deciding a disagreement

Judge against the printed page, never by which candidate has more rows. The recurring disagreements have fixed answers:

**Consult the grid on a value or column disagreement, then confirm on the page.** The worklist's `grid_path` lists every printed numeric cell for that page with its row label, `column_index` and column header, taken from the PDF's own coordinates. It is a strong witness on column membership, which is where linearised text fails.

It is not an authority. Measured against the extractions on disk it agrees with the agents on **86% of the values it can be checked against**, and where it disagrees it is usually the grid that is wrong: on a dense table it can drop a column, and on a page with narrative text above the table it can take a fragment of a sentence as a column header. So:

- A grid column header that reads as prose (`as of`, `billion`, `2025, up from`) means the grid failed on that page. Ignore its headers there and read them off the PNG.
- A value the grid does not list is not thereby wrong. The grid omits columns it failed to resolve. Check the PNG before deleting a row.
- **When the grid and the page image disagree, the image wins.** Always.

A page is absent from the grid when it is scanned or holds no numeric table; `data/documents/grids/MANIFEST.csv` says which.

Most conflicts are not two readings of a number. Measured across one full round, **not one paired cell in 1,707 had the two lanes reading the same printed line and extracting different numbers**; every conflict was a convention, and the same dozen conventions recur on every route. They are resolved here by rule, once per pattern, and the rule is recorded in `reason` so the ledger shows it was applied, not judged. A convention row resolves to `ACCEPT_A` or `ACCEPT_B` when one candidate already has the right form, and to `MERGE` when neither does.

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
| One reading group extracts prose sentences as provisions (`stewardship_policy`, `legal_clause`, `legal_term`) from a page the other declared `NO_ELIGIBLE_DATA` as narrative | Decide it **once for the document and apply it to every page**, and record that ruling in `reason`. A sentence is a provision when it states an operative rule, commitment, threshold, or duty that binds the reporting entity. Background, history, mission language, a description of what a policy document contains, and the names of an external framework's principles are narrative. This split ran to 197 rows against 12 on one document, so deciding it per row wastes the round; deciding it per document costs one decision. |
| A lane declares a page `NO_ELIGIBLE_DATA` with a reasoned `NO_ELIGIBLE_REASON:` note naming a category test, and the other extracted from it | The note is evidence of judgement, not of abandonment, so read the page before overriding it. If the page prints something in an allowed category the extracting lane is right; if the note correctly identifies it as out of category, the zero is right and the other lane's rows are rejected. Do not resolve it by preferring the larger lane. |

Record the reason applied alongside the decision.

## Resolution CSV

Header, verbatim:

```csv
"pair_id","decision","reason","contract_version","file_id","source_sha256","canonical_doc_type","route","product_tier","agent_role","record_family","source_page","source_structure_type","source_section","source_table","source_row_label","source_column_label","source_occurrence","subject_type","subject_name","asset_class","strategy","geography","manager_name","investor_name","portfolio_name","vintage_year","period_start","period_end","as_of_date","horizon","currency_scale","metric_category","metric_name","metric_value_raw","unit","term_category","text_raw","basis_raw","condition_raw","evidence_quote","evidence_class","notes","source_agents","adjudication_status"
```

Allowed decisions:

- `CONFIRM` : the sampled `EXACT` pair is source-correct.
- `ACCEPT_A` : A is source-correct.
- `ACCEPT_B` : B is source-correct.
- `MERGE` : neither candidate is complete; provide one corrected full record in the appended record columns.
- `REJECT` : neither candidate is publishable.

Only `MERGE` fills the appended record columns; every other decision leaves them blank. In a `MERGE` record, `contract_version` is `2026-08-22.2`.
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
| Both lanes report zero rows, one says `NO_ELIGIBLE_DATA` and the other `REFERENCE_ONLY` | `REFERENCE_ONLY` for a page whose content is reference or boilerplate: glossary, definitions, footnotes, disclosures, disclaimers, risk factors, contact or office directory, cover, table of contents, blank. `NO_ELIGIBLE_DATA` for a page that prints substantive figures or tables, every one of which falls outside this document type's allowed categories. One lane labelled seven footnote and glossary pages `NO_ELIGIBLE_DATA`; the label was wrong, the zero count was right. |
| `expected_observation_count` differs with both reading groups `ELIGIBLE_DATA_EXTRACTED` | Neither reading group's count: each reading group counted what it extracted. Count the allowed cells on the PNG directly; the answer is usually the larger of the two plus whatever both missed, and is never decided by averaging. |
| One reading group `NO_ELIGIBLE_DATA`, the other extracted rows | Read the page. A case study, sidebar, or marketing panel that prints real fund figures (`Fund Commitment $25.7M`, a loss rate, a count of deals) is allowed and its `evidence_class` is `actual` if the figures are stated as fact; the reading group that skipped it was wrong. A panel of hypothetical or illustrative figures is `REFERENCE_ONLY` and the rows are rejected. |

## Save progressively (hard requirement)

**Append each decision when made and save, never in one batch at the end.** Save `resolution.csv` after each settled group of pairs, and `coverage-resolution.csv` after each settled page. Write the header once, then append; never rewrite a file from scratch and lose decisions already recorded. If the session stops, every decision already made is on disk and the next session resumes at the first unresolved pair.

## Allowed scope

| Document type | Product | Allowed record family | Grain | Usual categories (any name of the family's kind is valid) |
|---|---|---|---|---|
| `PPM` | `CORE` | `document_context` | one row per document | none |
| `PPM` | `CORE` | `legal_term` | one printed term or one numbered provision whose primary meaning matches the whitelist | `management_fee`, `carried_interest`, `catch_up`, `waterfall`, `clawback`, `fee_offset`, `organizational_expense`, `recycling`, `fund_term`, `term_extension`, `commitment_period`, `investment_period` |
| `LPA` | `CORE` | `document_context` | one row per document | none |
| `LPA` | `CORE` | `legal_term` | one printed term or one numbered provision whose primary meaning matches the whitelist | `management_fee`, `carried_interest`, `catch_up`, `waterfall`, `clawback`, `fee_offset`, `organizational_expense`, `recycling`, `fund_term`, `term_extension`, `commitment_period`, `investment_period` |
| `LPA` | `CORE` | `legal_clause` | one numbered or separately headed operative provision whose primary meaning matches the whitelist | `key_person`, `gp_removal`, `no_fault_termination`, `mfn`, `reporting`, `transfer`, `tax`, `governing_law`, `confidentiality`, `notice` |
| `Subscription` | `SECONDARY` | `document_context` | one row per document | none |
| `Subscription` | `SECONDARY` | `subscription_reference` | one whitelisted subscription reference fact | `subscription_fund`, `general_partner`, `requested_commitment`, `accepted_commitment`, `subscriber_entity_type`, `fund_jurisdiction`, `execution_date` |
| `Side_Letter` | `CORE` | `document_context` | one row per document | none |
| `Side_Letter` | `CORE` | `legal_term` | one printed term or one numbered provision whose primary meaning matches the whitelist | `management_fee`, `carried_interest`, `catch_up`, `waterfall`, `clawback`, `fee_offset`, `organizational_expense`, `recycling`, `fund_term`, `term_extension`, `commitment_period`, `investment_period` |
| `Side_Letter` | `CORE` | `legal_clause` | one numbered or separately headed operative provision whose primary meaning matches the whitelist | `key_person`, `gp_removal`, `no_fault_termination`, `mfn`, `reporting`, `transfer`, `tax`, `governing_law`, `confidentiality`, `notice` |
| `DDQ` | `CORE` | `document_context` | one row per document | none |
| `DDQ` | `CORE` | `ddq_quantitative_observation` | one printed quantitative answer or table value | `staff_count`, `lockup`, `redemption_notice`, `position_limit`, `leverage`, `liquidity`, `minimum_investment`, `service_provider_count` |

### Excluded scope

- **PPM:** Risk-factor transcription and clauses outside the term whitelist.
- **LPA:** Clauses outside the term whitelist and generic document transcription.
- **Subscription:** Qualification questionnaires; representations; personal identifiers; bank/wire data; signatures.
- **Side_Letter:** Clauses outside the term whitelist and generic document transcription.
- **DDQ:** Exhaustive question-and-answer transcription; personal names; broker lists; narrative answers without a selected quantitative fact.

## Build and validate the final files

```powershell
python instructions/01-pdf-extraction-csv/workflow.py build-final --route 05-fund-legal-docs --file <file_id>
python instructions/01-pdf-extraction-csv/workflow.py validate-final --route 05-fund-legal-docs --file <file_id>
```

The workflow publishes agreed unsampled records mechanically and applies the adjudicator's decisions to reviewed pairs. Final rows receive `agent_role=ADJUDICATED`, populated `source_agents`, and an adjudication status of `AGREED`, `VERIFIED_ONE_SIDED`, `RESOLVED`, or `ADDED`.

Finish one file and save its final records and final coverage before opening the next worklist row.
