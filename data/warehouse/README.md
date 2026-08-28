# Warehouse

Three DuckDB files, each rebuilt from its CSV owner under a temporary name, compared with the CSVs in full both ways, and published only on parity. All three are tracked through Git LFS.

| File | Owner | Content |
|---|---|---|
| `extracted.duckdb` | `data/extracted/tables/`, `data/extracted/wide/` | 9 star tables with foreign keys, 17 wide tables, `bridge_pivot_observation`, 4 views (`sql/duckdb/03`, `04`): 7,201 printed values |
| `alts.duckdb` | `data/csv/` | 18 fund-model tables and 3 views (`sql/duckdb/02`): printed rows labelled `EXTRACTED` beside completion rows labelled `SYNTHETIC` |
| `alts_mock.duckdb` | `data/synthetic/` | The standalone 800-fund regression fixture; shares the schema and no row |

Next: [`../../docs/FINAL-RELEASE-AUDIT.md`](../../docs/FINAL-RELEASE-AUDIT.md).
