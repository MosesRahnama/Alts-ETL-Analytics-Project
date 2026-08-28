# Runtime code

| Folder | Role |
|---|---|
| `catalog/` | Source preparation, extraction field lists, validation, and identity support |
| `flatten/` | Relational and wide tables that keep the printed cell |
| `load/` | Promotion and DuckDB parity loading |
| `pipeline/` | Extraction, fill, release, and review stages |
| `quality/` | Financial, identity, date, currency, and grain checks |
| `analytics/` | Performance, PME, and allocation |
| `market_data/` | Public market curation |
| `generate/` | Standalone regression-fixture generation |
| `common/` | Shared financial mathematics |
| `repository/` | Folder guides, manifest, and structure checks |
| `dashboard/` | The reviewer dashboard rendered from the published files |

`__init__.py` marks the package.
