# Dashboard

`dashboard.html` presents the release with definitions, source links, controls, and analytical results.

| Command | Result |
|---|---|
| `python -m src.dashboard.build_dashboard` | Writes `dashboard.html` using the Python standard library |
| `python -m src.repository.build_release_audit --check` | Verifies the complete process table against release definitions and recorded results before dashboard publication |
| `python -m src.dashboard.build_dashboard --open` | Builds and opens the local file |
| `python -m src.dashboard.build_dashboard --serve --open` | Builds and serves the page on a loopback address |
| `open-dashboard.cmd` | Runs the same build through the Windows launcher; the committed snapshot remains available without Python |
| `python -m pytest tests/test_dashboard.py tests/test_dashboard_field_guide.py -q` | Runs both reviewer-page test sets |
| `python -m src.dashboard.publish_dashboard` | Prepares the dashboard, referenced data, completed extraction files, and compressed database downloads |
| `python -m src.dashboard.publish_dashboard --publish` | Updates the public dashboard and `dashboard-data/`; existing public code and source datasets remain unchanged |

| File | Role |
|---|---|
| `__init__.py` | Dashboard package marker. |
| `build_dashboard.py` | reads the files, builds the twelve sections, writes the page, serves it on request |
| `page.py` | the shell: style, browser code, and the block kinds the builder emits |
| `glossary.py` | what each table is and what each column means; a test fails the build if any column on the page is undefined |
| `teaching.py` | Page guide copy, word list, and the teaching box at the top of each section |
| `publish_dashboard.py` | Selects public download files, checks both reviewer pages, and publishes a commit whose parent belongs to the public repository |

| Section | Reads |
|---|---|
| Overview | source ledger, document summary, complete process table with dated check results, fact observations, entity dimension, receipts |
| Corpus | source ledger, text manifest, grid manifest |
| Extraction review | document summary, observation origin records, fact observations |
| Evidence browser | `fact_observation.csv`, every row and every column |
| Schema and vocabulary | the validation code and the generated schema CSVs |
| Databases | the three DuckDB files, table by table, 200 rows each in sorted order |
| Analytics | source-only metrics, completed metrics and PME, the reviewer analytics summary |
| Public markets and benchmarks | market audit files, benchmark policy, benchmark rows |
| Quality controls | rule configuration, both quality-result files, the defect scorecard |
| Generated data | cell origin records, gap ledger, completion settings, parameters |
| Reproduction | release audit, receipts, project manifest |

The snapshot reflects the tree at build time. Identical inputs produce byte-identical output. The database explorer uses the `duckdb` package and reports unread files when that package is unavailable. The generated file embeds every observation and the database previews.
