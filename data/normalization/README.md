# Identity normalization

Printed names, accepted standardized identities, stable entity IDs, manager-research evidence, and closed classifications remain together here.

`src/catalog/simple_pdf_extraction/name_normalization.py` writes each identity matrix except `entity-ids.csv`. `src/catalog/simple_pdf_extraction/fund_attributes.py` writes fund-constant attributes. The commands in the third column regenerate the files; `name_normalization paths` and `fund_attributes paths` report the code-owned maps. The operator sequence is [`instructions/02-fund-mapping/00-OPERATOR-RUNBOOK.md`](../../instructions/02-fund-mapping/00-OPERATOR-RUNBOOK.md).

| File | Role | Written by |
|---|---|---|
| `fund-names-matrix.csv` | Printed fund names, fund families, stable IDs, decisions, counts, and source files | `harvest`, then `autofill` and `merge` |
| `manager-names-matrix.csv` | Managers printed directly in the extracted sources | `harvest`, `autofill`, `merge` |
| `lp-names-matrix.csv` | Limited-partner name standards | `harvest`, `autofill`, `merge` |
| `plan-names-matrix.csv` | Pension and institutional-plan name standards | `harvest`, `autofill`, `merge` |
| `company-names-matrix.csv` | Portfolio-company name standards | `harvest`, `autofill`, `merge` |
| `entity-ids.csv` | Append-only registry for fund, manager, LP, plan, and company IDs | `instructions/02-fund-mapping/entity_ids.py` |
| `manager-queue.csv` | Independent manager-search work and final decisions by sponsor family | `manager-queue`, then `manager-merge` and `manager-autosettle` |
| `web-manager-names.csv` | Fund-to-manager research result and supporting public sources | `propagate`, reported by `managers` |
| `web-manager-names-matrix.csv` | Standardized manager names derived from the web research round | `harvest`, `merge` |
| `fund-attributes-matrix.csv` | One row per fund with printed vintage, strategy, asset class, and geography, plus unique, spelling-collapsed, conflict, and decided statuses | `python -m src.catalog.simple_pdf_extraction.fund_attributes harvest`, then `autofill`, `merge`, and `apply` |
| `attribute-conflicts.csv` | Funds whose remaining printed labels still disagree after hyphen and `Investments`-suffix collapse. Header-only is the passing result of `fund_attributes conflicts --strict` | `conflicts` |
| `name-near-duplicates.csv` | Similar spellings presented for review without automatic merging | `check` |
| `standard-conflicts.csv` | Cases where one normalization key points to more than one standard. Header-only, and that is the passing result of `conflicts --strict` | `conflicts` |
| `source-review-corrections.csv` | Page-backed field corrections with expected old values; source_review applies them to resolution records and checks drift | `python -m src.catalog.simple_pdf_extraction.source_review --apply` |
| `worksheets/` | Human normalization, two-agent manager research, third-reader decisions, and attribute-conflict rows | `export`, `manager-export`, and `fund_attributes export` |
| `transformations/` | CSV decision matrices: each row names the input, output, context, decision owner, and evidence; `src/common/matrices.py` reads them and stage 20 checks them | 420 data-decision sites cite one or more rows; four non-data sites are recorded in [`migration-dispositions.csv`](../../ledgers/pipeline/migration-dispositions.csv) |

Only settled identities receive entity links. Fund attributes copy supported values for the same fund; missing source attributes remain blank.

[Source-only tables](../extracted/fund-level/README.md) · [Process](../../PROCESS.md)
