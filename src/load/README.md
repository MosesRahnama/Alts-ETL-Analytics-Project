# Load

CSV-to-DuckDB loading.

| File | Role |
|---|---|
| `promote_extracted_to_fund_level.py` | Map adjudicated observations into the fund-level tables and write the acceptance evidence the promotion gate reads. |
| `validate_round02_promotion.py` | Block fund-model loading when extracted or market rows lack governed promotion lineage. |
| `load_csv_to_duckdb.py` | Build the fund-model DuckDB under a temporary name and publish it after full CSV parity. |
| `__init__.py` | Package marker so Python can import the modules in this folder. |
| `build_normalized_holdings.py` | Build owner-aware normalized holdings without changing source evidence. |
| `validate_normalized_holdings.py` | Validate normalized holdings tables, source coverage, and DuckDB constraints. |
