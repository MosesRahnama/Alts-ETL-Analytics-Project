# Dashboard

`dashboard.html` is a static rendering of the published files. It displays the release without recalculating data.

| Command | Result |
|---|---|
| `python -m src.dashboard.build_dashboard` | Writes `dashboard.html` using the Python standard library |
| `python -m src.dashboard.build_dashboard --open` | Builds and opens the local file |
| `python -m src.dashboard.build_dashboard --serve --open` | Builds and serves the page on a loopback address |
| `open-dashboard.cmd` | Runs the same build through the Windows launcher; the committed snapshot remains available without Python |
| `python -m pytest tests/test_dashboard.py -q` | Runs the dashboard tests |

| File | Role |
|---|---|
| `build_dashboard.py` | reads the files, builds the eleven sections, writes the page, serves it on request |
| `page.py` | the shell: style, browser code, and the block kinds the builder emits |
| `glossary.py` | what each table is and what each column means; a test fails the build if any column on the page is undefined |

| Section | Reads |
|---|---|
| Overview | source ledger, document summary, release audit, fact observations, entity dimension, receipts |
| Corpus | source ledger, text manifest, grid manifest |
| Extraction and adjudication | document summary, observation lineage, fact observations |
| Evidence browser | `fact_observation.csv`, every row and every column |
| Schema and vocabulary | the contract code and the generated schema CSVs |
| Databases | the three DuckDB files, table by table, 200 rows each in sorted order |
| Analytics | source-only metrics, completed metrics and PME, the reviewer analytics summary |
| Public markets and benchmarks | market audit files, benchmark policy, benchmark rows |
| Quality controls | rule configuration, both quality-result files, the defect scorecard |
| Generated data | cell lineage, gap ledger, completion settings, parameters |
| Reproduction | release audit, receipts, project manifest |

The snapshot reflects the tree at build time. Identical inputs produce byte-identical output. The database explorer uses the `duckdb` package and reports unread files when that package is unavailable. The generated file embeds every observation and the database previews.
