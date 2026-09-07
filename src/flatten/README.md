# Flatten

Wide extraction records converted into relational facts and dimensions.

| File | Role |
|---|---|
| `flatten_extracted.py` | Convert published wide observations into relational tables. |
| `pivot_wide.py` | Pivot fact_observation into one wide table per record family, with the bridge back to every observation and the DDL it loads under. |
| `load_star.py` | Build the document DuckDB under a temporary name and publish it after full CSV parity. |
| `__init__.py` | Package marker so Python can import the modules in this folder. |
