# Review

Flattened reviewer observations, final fund periods, gap ledger, cell lineage, and document summaries.

| File | Role |
|---|---|
| `disagreement-fields.csv` | How often the two extractors differed on each field, by conflict kind, with the number of documents the difference appeared in. |
| `document-summary.csv` | One row per published document: what each extractor found, how the two compared, what the adjudicator decided, and how many rows were published. |
| `observation-lineage.csv` | One row per published observation naming the A row, B row, pair, decision, and final row it came from, with the file paths and row numbers a reviewer opens. |
| `reviewer-analytics-summary.csv` | Reviewer-ready distributions, analytical coverage, portfolio result, and strategy exposure. |
| `reviewer-cell-lineage.csv` | Every cell the completion wrote, with its label, source, formula, or parameter, flattened for review. |
| `reviewer-fund-periods.csv` | One flattened row per fund period with attribute sources, QC, and recomputed metrics. |
| `reviewer-gap-ledger.csv` | Every blank the completion filled, with the value before, the value after, and how the fill was decided. |
| `reviewer-observations.csv` | One flattened row per printed fact with enrichment, lineage, QC, and analysis links. |
| `reviewer-queries.sql` | DuckDB queries for the extracted database: inventory, observations by document, entity coverage, metric coverage, observation lookup, and pivot-to-observation tracing. |
| `trace-sample.csv` | A sample of observation trails carrying subject, dates, value, unit, source coordinates, quote, and A/B and adjudication lineage. |

Next: [Warehouse](../../warehouse/README.md).
