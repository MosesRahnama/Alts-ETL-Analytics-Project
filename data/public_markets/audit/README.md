# Audit

Run receipts, the file inventory, the series-family summary, and market-data quality results.

| File | Role |
|---|---|
| `market_data_runs.csv` | Curation receipt with source and destination paths and SHA-256. |
| `source_file_inventory.csv` | 334 retained Parquet files with tier, family, PME role, rights status, and producer. |
| `source_family_summary.csv` | 19 series families in the retained store with file, byte, and row counts, analysis tier, PME role, source system, and rights status. |
| `quality_results.csv` | PMQ01 to PMQ10: population, keys, dates, levels, bounds, and return reconciliation, all PASS. |
