# Standalone regression fixture

The 800 `FUND_SYNTH_` funds test generator scale and rule coverage. They do not feed `data/csv/`, reviewer outputs, or `alts.duckdb`.

| Path | Content |
|---|---|
| `clean/` | Reconciled standalone population |
| `defects/` | Matched damaged population and scorecard |
| `analytics/` | Fixture metrics, PME, and allocations |
| `fixture-parameters.csv` | Header-only input that makes the fixture emit its own declared assumptions |
| `MANIFEST.csv` | File and row inventory |

The primary demonstration instead augments the 934 real extracted fund IDs through `src/pipeline/build_integrated_universe.py`.
