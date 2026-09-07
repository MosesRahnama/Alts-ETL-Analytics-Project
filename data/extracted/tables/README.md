# Tables

Relational dimensions and facts built from adjudicated observations.

| File | Role |
|---|---|
| `dim_document.csv` | One row per published source document with ratified type and source reference. |
| `dim_page.csv` | One row per reviewed physical PDF page. |
| `dim_entity.csv` | Standardized funds, managers, plans, LPs, benchmarks, and portfolio companies. |
| `entity_alias.csv` | Printed source names linked to standardized entities when a decision exists. |
| `dim_metric.csv` | One row per family and vocabulary name observed in the published slice, with its value kind, row count, standard measure, and measurement grain. |
| `fact_observation.csv` | One source observation with document, page, entity, metric, value, and evidence lineage. |
| `observation_lineage.csv` | Every published observation joined back to the pair it was settled under, the two candidate row numbers, and the adjudicator decision. |
| `fact_holding.csv` | One source-reported holding linked to document, page, and entity where resolved. |
| `unresolved_names.csv` | Header-only identity exception guard; the current release contains zero rows. Header-only. |
| `MANIFEST.csv` | Row counts and file membership for this generated stage. |
