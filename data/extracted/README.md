# Extracted data

Publication files, route outputs, review tables, relational tables, family pivots, the promotion audit, and the frozen source-only fund snapshot.

| File | Role |
|---|---|
| `pdf-wide-records.csv` | published 42-column observations, plus `extractor_model` |
| `pdf-wide-coverage.csv` | one row per published page |

| Folder | Role |
|---|---|
| `rounds/` | route records and coverage written by `publish` |
| `raw/` | one final-record concatenation per route; a verification mirror, never a stage input |
| `review/` | A/B summaries, disagreement counts, observation lineage, trace samples, queries, and the flat reviewer files |
| `tables/` | dimensions, aliases, facts, holdings, the unstandardized-name ledger, and lineage |
| `wide/` | one pivot per record family and the observation bridge |
| `audit/` | source-lineage checks, withheld promotion cells, and inherited-attribute evidence |
| `fund-level/` | the source-only fund tables frozen before completion |

`combine_extracted_raw --check` verifies route concatenations. `build_extraction_review --check` verifies review tables. `build_extracted_database` rebuilds tables, pivots, and `extracted.duckdb`.

Next: [`../normalization/README.md`](../normalization/README.md).
