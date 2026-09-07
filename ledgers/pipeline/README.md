# Rebuild receipts

| File | Contents |
|---|---|
| `transformation-receipts.csv` | Append-only commands, input hashes, predecessor receipts, output hashes, row counts, and external backup locators. |
| `release-checks.csv` | Append-only executed check results, commands, times, and errors; includes checks that write no data. [Release audit](../../docs/FINAL-RELEASE-AUDIT.csv) cites these records. |
| `matrix-check.csv` | One PASS or FAIL row per decision matrix with its row, column, and context counts; stage 20 writes the current matrix record. |
| `migration-requirements.csv` | The twelve rules `python -m src.pipeline.migration_gate` runs after a migration batch, with the check behind each and the batch it starts at. |
| `migration-batch-scope.csv` | Each source file's assigned batch and expected site count; R10 refuses omissions or count drift. |
| `migration-sites.csv` | The tracked 424-site merge of the three inventories: 420 sites name implementing matrices and four pair with the structure-disposition ledger. |
| `migration-dispositions.csv` | The four inventoried presentation or ordering sites that do not transform data, each with a required reason. |

Matrices: [`../../data/normalization/transformations/`](../../data/normalization/transformations/).
