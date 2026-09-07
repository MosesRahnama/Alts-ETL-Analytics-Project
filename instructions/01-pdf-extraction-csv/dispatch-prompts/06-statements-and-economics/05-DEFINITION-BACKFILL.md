# Statements and Economics: DEFINITION BACKFILL (lane A or B)

> **Binding:** Do not dispatch sub-agents. Do not use Python, scripts, regex, or automated table parsing to read source content; the only Python permitted is the workflow commands named below. Work one lane (`--agent A` or `--agent B`) named by your dispatch, and never open the other lane's files.

The original extraction read the footnotes that define the numbers and discarded them. This pass goes back to the pages of one already-extracted document and captures them as data. It changes no existing value.

- **Worklist:** `instructions/01-pdf-extraction-csv/worklists/active/06-statements-and-economics.csv`
- **Files:** `ledgers/working/pdf-extraction-csv/06-statements-and-economics/<file_id>/records-<lane>.csv` (rewrite in place; the header is the current 47-column contract)

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


What this pass writes, and nothing else:

1. **New `definition_context` rows**, one per printed footnote, definition, methodology note, or legend entry, per the Definitions section of this route's extractor prompt: `definition_keys` = the printed marker, `text_raw` = the full printed wording verbatim, `condition_raw` = what it governs when stated, `source_structure_type` = `FOOTNOTE` or what it physically is, `evidence_class` = `actual`, `evidence_quote` = a line of the note. `contract_version` on a new row is `2026-09-01.2`; `agent_role` is your lane.
2. **The new columns on existing rows**: `definition_keys` (the printed markers attached to that row or its column, pipe-joined), and for a qualified category `method`, `fee_basis`, `value_scope`, from what the page states through a cited key or a `basis_raw` phrase, else `unstated`.

The atomic unit is unchanged: one populated allowed value cell is one row. This pass adds definition rows beside the value rows and fills their new columns; it never merges, splits, or re-derives a value row.

What never changes, on any existing row: every pre-existing cell. The row's `contract_version`, its value, its labels, its dates, its quotes all stay byte-for-byte. Rows are identified by the physical cell (`source_page`, `source_row_label`, `source_column_label`, `source_occurrence`); never renumber, resort, or delete.

Keep the file sorted by the contract sort order (new definition rows land in position). After each finished document, run and pass both:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 06-statements-and-economics --file <file_id> --agent <lane>
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route 06-statements-and-economics --file <file_id> --agent <lane>
```

The dispatching agent reruns both commands independently before the document is called done, then `compare` pairs the two lanes and an adjudicator settles the definition rows like any others.
