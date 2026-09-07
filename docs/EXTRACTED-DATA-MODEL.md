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

## Published returns

1,305 published return rows retain their method and fee treatment; different methods remain separate.

| Method | Fee basis | Rows |
|---|---|---:|
| `modified_dietz` | `net` | 446 |
| `annualized` | `unstated` | 279 |
| `unstated` | `unstated` | 272 |
| `time_weighted` | `net` | 168 |
| `time_weighted` | `unstated` | 46 |
| `unstated` | `gross` | 18 |
| `money_weighted` | `net` | 13 |
| `unstated` | `net` | 13 |
| `simple_period` | `net` | 12 |
| `annualized` | `net` | 11 |
| `simple_period` | `unstated` | 10 |
| `time_weighted` | `gross` | 8 |
| `annualized` | `partial` | 4 |
| `time_weighted` | `partial` | 4 |
| `unstated` | `partial` | 1 |

## Publication controls

0 published rows in 0 documents leave a qualifier blank; required qualifiers are reviewed against headers and footnotes, with source silence recorded as `unstated`. Optional and inapplicable fields remain blank.

All 36 active documents have validated finals and published evidence, including SRC421 and SRC373; unfinished documents: 0.

| Transformation | Evidence and control |
|---|---|
| Field correction | Source-review matrix records old/new values and the native page; original A/B proposals remain unchanged |
| Date parsing | Printed date retained beside parsed fields; footnote dates and comparative columns retain their own meaning |
| Identity normalization | Authored name matrices preserve aliases and assign stable entity IDs |
| Fund attributes | Settled source evidence supplies the same fund's vintage, strategy, asset class, and geography |
| Unit conversion | Currency and scale remain recorded; transformation matrices define conversion rules |
| Analytical promotion | Measure, date, investor scope, and currency determine admission; conflicts stop publication |
| Cash-flow schedules | Dated totals replace their components; cumulative totals are not duplicate events |
| Source-only snapshot | Generated fund size, currency, and status cannot appear as source-backed values |

[Source-only fund tables](../data/extracted/fund-level/README.md) · [Complete process](../PROCESS.md)
