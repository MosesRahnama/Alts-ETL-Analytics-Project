# Public market files

Public benchmarks compare the same dated calls and distributions with what the same money would have earned in public markets. The retained market package also supports regime, volatility, positioning, liquidity, and real-asset research.

| Stage | Artifact |
|---|---|
| Retain and hash | 334 Parquet files in `data/public_markets/sources/` plus `audit/source_file_inventory.csv` |
| Stage | 58 masters, 279,269 levels, 279,211 tied-out returns, and 19 strategy mappings |
| Promote | `data/csv/benchmark_returns.csv`; level candidates remain in staging |
| Analyze | KS-PME and Direct Alpha in `data/csv/pme_results.csv` |

| Tier | Retained data | Analytical use |
|---|---|---|
| PME core | Adjusted broad-market, sector, geography, credit, rates, and real-asset ETFs | Primary and sensitivity benchmarks |
| Market context | FRED, EIA, CFTC positioning, Treasury auctions, futures, volatility, and crypto | Regime and opportunity-cost research |
| Advanced daily | Options, gamma, macro, weather, natural-gas, and price aggregates | Liquidity and other-data examples |

The package contains 334 Parquet inputs and 58 benchmark series. Twenty-nine benchmark proxies use longer-history Yahoo Finance sources; twenty-nine use an adjusted wide panel beginning in 2012. Ten recorded quality checks pass.

The alignment rule uses the latest available market date at or before each fund cash-flow date. This prevents future benchmark values from entering weekend or holiday cash flows. Each PME result records the benchmark ID, formula ID, input records, terminal date, and quality population.

ETF proxies are demonstration series, not licensed institutional indices. All retained market sources carry `DEMONSTRATION_ONLY`, which excludes production use and external redistribution.

`python -m src.market_data.curate_public_markets` reads `data/public_markets/sources/` and rebuilds the staging and audit files from it, so the stage runs on a clone with nothing else present. Each retained file keeps the folders of the acquiring corpus inside its name, joined by a double underscore, and `audit/source_file_inventory.csv` records that path, the SHA-256, the schema, and the date range of every file. `audit/source_family_summary.csv` groups the store into 19 series families, and `audit/market_data_runs.csv` carries the run receipt.

Next: [`../instructions/04-analytics/README.md`](../instructions/04-analytics/README.md).
