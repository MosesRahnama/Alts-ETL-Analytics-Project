# Fee_Report field survey

Field survey of the Fee_Report family: file ledger, field ledger, source-backed sample, and schema note.

| File | Role |
|---|---|
| `fee_report.file-ledger.csv` | One row per reviewed source document with the pages read, the fields found, and the disposition. |
| `fee_report.field-ledger.csv` | One row per visible source field with grain, location, prevalence, and mapping decision. |
| `fee_report.sample.csv` | Source-backed sample rows that tested the field contract before it was frozen. |
| `fee_report.schema.md` | Schema note for the family: record grains, fields, and document prevalence from the ledger. |
