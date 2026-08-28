# Printed-cell tables

Reviewers open CSV files. `extracted.duckdb` is the query copy and must match those files table for table and value for value.

## Tables that keep the printed cell

| Table | Grain | Key links |
|---|---|---|
| `dim_document` | One published source document | Source hash and route |
| `dim_page` | One reviewed physical page | Document |
| `dim_entity` | One decided fund, manager, LP, plan, or company | Stable entity ID |
| `entity_alias` | One printed name | Decided entity when available |
| `dim_metric` | One family and category | Metric ID |
| `fact_observation` | One printed cell or clause | Document, page, metric, aliases, entities |
| `observation_lineage` | One published observation | A/B pair, candidate rows, resolution, source reference |
| `fact_holding` | One printed holding row | Document, page, entity, source observation IDs |
| `unresolved_names` | Zero-row identity exception guard | Entity kind and normalized text |

`fact_observation` keeps the printed value, date text, scale heading, physical location, quote, source agents, model, and schema version. Parsed dates and numbers sit beside the printed strings; scaling occurs in a view or during fund-level promotion.

## Wide tables

`data/extracted/wide/` contains one table per record family. One row is one printed table row, one column is one vocabulary name (the family's usual names, then any other name the facts carry in it), and `bridge_pivot_observation` links each pivot row back to every source observation. The current build has zero pivot collisions.

## Fund-level tables

`data/csv/` uses stable entity IDs and analytical grains: one observation, period, cash flow, holding, term, or manager fact per row. Promotion writes these tables; quality and analytics add `quality_results.csv` and `fund_metrics.csv`.

## Reviewer tables

| File | Grain | Added context |
|---|---|---|
| `reviewer-observations.csv` | One printed fact | A/B origin records, effective attributes and their sources, promotion, QC, analysis links |
| `reviewer-fund-periods.csv` | One fund/date/document position | Fund name, inherited-cell sources, QC summary, recomputed metrics |

## Publication

`python -m src.pipeline.publish_review_release` rebuilds the release. The loader creates each DuckDB file under a hidden temporary name, compares every CSV value, archives the replaced file, and publishes the passing database.

## Reviewer origin records

Two files carry observation origin records at two widths. `data/extracted/tables/observation_lineage.csv` is the evidence table, loaded into `extracted.duckdb` under its constraints: one row per `fact_observation`, with the pair, resolution, and final-row references. `data/extracted/review/observation-lineage.csv` is the reviewer file over the same rows, adding source and process paths, A and B row numbers, pair state, resolution reason, source agents, adjudication status, and source hash; it stays a CSV beside `trace-sample.csv`, which supplies review rows.
