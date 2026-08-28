"""Select market files and build reviewable PME candidate tables.

The retained store `data/public_markets/sources/` is the default input, so the
whole stage runs from a clone with nothing else present. Each retained file
keeps its original folders inside its name, joined by a double underscore, and
`source_index` reads those names back into the layout the acquiring corpus used,
which is the form the selection patterns and the inventory both speak.

Passing `--source-root` at a nested corpus reads that layout directly and copies
what the selections name into the retained store.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
import pyarrow.parquet as pq


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "public_markets"
DEFAULT_SOURCE_ROOT = DEFAULT_OUTPUT_ROOT / "sources"
MAX_TRANSFER_BYTES = 100 * 1024 * 1024

LEGACY_ADJUSTED_ETFS = (
    "DIA",
    "EFA",
    "GLD",
    "IEF",
    "IWM",
    "QQQ",
    "RSP",
    "SHY",
    "SPY",
    "TLT",
    "USO",
)

LONG_HISTORY_ETFS = (
    "AGG",
    "DBC",
    "DIA",
    "EEM",
    "EFA",
    "GLD",
    "HYG",
    "IEF",
    "IWM",
    "LQD",
    "QQQ",
    "SHY",
    "SLV",
    "SPY",
    "TLT",
    "UNG",
    "USO",
    "VTI",
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
)


@dataclass(frozen=True)
class Selection:
    name: str
    patterns: tuple[str, ...]
    expected_count: int
    tier: str
    family: str
    promotion_status: str
    pme_role: str
    return_basis: str
    source_system: str
    producer_script: str
    note: str


SELECTIONS = (
    Selection(
        "legacy_adjusted_etf_reference",
        tuple(f"raw/equity/{ticker}_1d.parquet" for ticker in LEGACY_ADJUSTED_ETFS),
        11,
        "PME_CORE",
        "ADJUSTED_ETF_REFERENCE",
        "REFERENCE",
        "VALIDATION_REFERENCE",
        "ADJ_CLOSE",
        "YAHOO_FINANCE_VIA_YFINANCE",
        "src/ingest/equity.py",
        "The adj_close field provides an independent comparison for selected ETF histories.",
    ),
    Selection(
        "long_history_adjusted_etfs",
        tuple(f"raw/equity/YF_{ticker}.parquet" for ticker in LONG_HISTORY_ETFS),
        29,
        "PME_CORE",
        "ADJUSTED_ETF_LONG_HISTORY",
        "CANDIDATE",
        "PRIMARY_OR_MATCHED_PROXY",
        "AUTO_ADJUSTED_CLOSE",
        "YAHOO_FINANCE_VIA_YFINANCE",
        "scripts/ingest_equities_yf.py",
        "The close field reflects the downloader's auto-adjusted setting.",
    ),
    Selection(
        "wide_adjusted_etf_panel",
        ("raw/wide_etf/wide_etf_adjclose.parquet",),
        1,
        "PME_CORE",
        "ADJUSTED_ETF_WIDE_PANEL",
        "CANDIDATE",
        "MATCHED_PROXY_SUPPLEMENT",
        "AUTO_ADJUSTED_CLOSE",
        "YAHOO_FINANCE_VIA_YFINANCE",
        "scripts/wide_etf_pointer_state.py",
        "The panel adds sector, geography, style, fixed-income, and real-asset proxies from 2012.",
    ),
    Selection(
        "fred_macro",
        ("raw/macro/FRED_*.parquet",),
        97,
        "MARKET_CONTEXT",
        "MACRO_FRED",
        "RESEARCH_ONLY",
        "REGIME_CONTEXT",
        "SOURCE_VALUE",
        "FRED_OR_ALFRED",
        "scripts/ingest_fred.py",
        "The realtime_start field supplies the recorded knowledge date when present.",
    ),
    Selection(
        "eia_macro",
        ("raw/macro/EIA_*.parquet",),
        8,
        "MARKET_CONTEXT",
        "ENERGY_FUNDAMENTALS",
        "RESEARCH_ONLY",
        "REAL_ASSET_CONTEXT",
        "SOURCE_VALUE",
        "US_EIA",
        "scripts/ingest_eia_live_fundamentals.py",
        "Energy production, demand, storage, and export series support real-asset research.",
    ),
    Selection(
        "macro_events",
        ("raw/events/macro_event_calendar.parquet",),
        1,
        "MARKET_CONTEXT",
        "MACRO_EVENTS",
        "RESEARCH_ONLY",
        "EVENT_CONTEXT",
        "SOURCE_VALUE",
        "MULTI_SOURCE_EVENT_CALENDAR",
        "scripts/build_event_calendar.py",
        "Knowledge timestamps support event-aligned analysis.",
    ),
    Selection(
        "commodity_surprises",
        ("raw/commodities/*.parquet",),
        2,
        "MARKET_CONTEXT",
        "COMMODITY_SURPRISES",
        "RESEARCH_ONLY",
        "REAL_ASSET_CONTEXT",
        "DERIVED_SOURCE_VALUE",
        "US_EIA",
        "scripts/ingest_term_structure_eia.py",
        "Storage surprise series support energy-fund sensitivity work.",
    ),
    Selection(
        "cot_positioning",
        ("raw/positioning/*.parquet",),
        46,
        "MARKET_CONTEXT",
        "COT_POSITIONING",
        "RESEARCH_ONLY",
        "POSITIONING_CONTEXT",
        "SOURCE_AND_DERIVED_FIELDS",
        "US_CFTC",
        "scripts/ingest_cot_positioning.py",
        "Weekly positioning supports regime and crowding analysis.",
    ),
    Selection(
        "rates_quarantine",
        ("raw/rates/*.parquet",),
        12,
        "MARKET_CONTEXT",
        "RATES",
        "QUARANTINE",
        "QUALITY_CONTROL_CASE",
        "FINAL_OR_FILLED_RATE",
        "THETADATA",
        "scripts/pull_thetadata_rates.py",
        "Vintage, weekend-fill, and pre-2018 SOFR treatment require adjudication.",
    ),
    Selection(
        "treasury_auctions",
        ("raw/treasury/treasury_auctions.parquet",),
        1,
        "MARKET_CONTEXT",
        "TREASURY_AUCTIONS",
        "RESEARCH_ONLY",
        "CAPITAL_MARKETS_CONTEXT",
        "SOURCE_VALUE",
        "US_TREASURY",
        "scripts/ingest_treasury_auctions.py",
        "Auction outcomes support rates and liquidity context.",
    ),
    Selection(
        "daily_vix_futures",
        ("raw/vix/xcbf_ohlcv1d_VX_v_*.parquet",),
        3,
        "MARKET_CONTEXT",
        "VIX_FUTURES_DAILY",
        "RESEARCH_ONLY",
        "VOLATILITY_CONTEXT",
        "FUTURES_PRICE",
        "DATABENTO",
        "scripts/pull_vix.py",
        "Daily VIX futures support volatility-regime research.",
    ),
    Selection(
        "daily_futures",
        ("raw/futures/*.parquet",),
        8,
        "MARKET_CONTEXT",
        "FUTURES_DAILY",
        "RESEARCH_ONLY",
        "MATCHED_OPPORTUNITY_COST",
        "FUTURES_PRICE_OR_TERM_STRUCTURE",
        "YAHOO_FINANCE_AND_EIA",
        "src/ingest/futures.py",
        "PME use requires a declared roll, collateral, exposure, and cost convention.",
    ),
    Selection(
        "crypto_daily",
        ("raw/crypto/**/*.parquet",),
        32,
        "MARKET_CONTEXT",
        "CRYPTO_DAILY",
        "RESEARCH_ONLY",
        "SPECIALIST_FUND_CONTEXT",
        "SPOT_OR_FUNDING_SOURCE_VALUE",
        "CRYPTO_EXCHANGE_AND_PROVIDER_SOURCES",
        "src/ingest/crypto.py",
        "A 24-hour cash-flow-date convention governs specialist PME use.",
    ),
    Selection(
        "enriched_price_features",
        ("features/enriched/*_px.parquet",),
        22,
        "ADVANCED_DAILY",
        "PRICE_FEATURES",
        "RESEARCH_ONLY",
        "RISK_AND_REGIME_FEATURE",
        "UNADJUSTED_CLOSE_DERIVATION",
        "DERIVED_FEATURE_BUILD",
        "scripts/build_price_features.py",
        "Momentum and volatility features support risk research; dividend-adjusted PME uses the core tier.",
    ),
    Selection(
        "enriched_cot_features",
        ("features/enriched/*_cot.parquet",),
        7,
        "ADVANCED_DAILY",
        "COT_FEATURES",
        "RESEARCH_ONLY",
        "POSITIONING_FEATURE",
        "CAUSAL_WEEKLY_FEATURE",
        "DERIVED_FEATURE_BUILD",
        "scripts/build_cot_features.py",
        "Friday knowledge dates govern weekly feature availability.",
    ),
    Selection(
        "enriched_macro_features",
        ("features/enriched/macro.parquet",),
        1,
        "ADVANCED_DAILY",
        "MACRO_FEATURES",
        "RESEARCH_ONLY",
        "REGIME_FEATURE",
        "CAUSAL_DAILY_FEATURE",
        "DERIVED_FEATURE_BUILD",
        "scripts/build_macro_features.py",
        "Release-lag rules govern daily feature availability.",
    ),
    Selection(
        "daily_options_aggregates",
        ("features/options_daily_*.parquet",),
        25,
        "ADVANCED_DAILY",
        "OPTIONS_DAILY",
        "RESEARCH_ONLY",
        "VOLATILITY_AND_LIQUIDITY_FEATURE",
        "DAILY_AGGREGATE",
        "DERIVED_FEATURE_BUILD",
        "scripts/build_options_features.py",
        "Daily aggregates retain the useful surface statistics at compact scale.",
    ),
    Selection(
        "daily_gex_aggregates",
        ("features/gex_daily_*.parquet",),
        25,
        "ADVANCED_DAILY",
        "GEX_DAILY",
        "RESEARCH_ONLY",
        "GAMMA_EXPOSURE_FEATURE",
        "DAILY_AGGREGATE",
        "DERIVED_FEATURE_BUILD",
        "scripts/build_gex_surface.py",
        "Daily gamma summaries support stress and market-structure research.",
    ),
    Selection(
        "natural_gas_aggregates",
        ("features/ng_*.parquet",),
        3,
        "ADVANCED_DAILY",
        "NATURAL_GAS_FEATURES",
        "RESEARCH_ONLY",
        "ALTERNATIVE_DATA_FEATURE",
        "DAILY_OR_WEEKLY_AGGREGATE",
        "DERIVED_FEATURE_BUILD",
        "scripts/ng_balance_model.py",
        "Weather, balance, and spread summaries support real-asset analysis.",
    ),
)

DATE_COLUMNS = (
    "timestamp_utc",
    "Date",
    "date",
    "knowledge_date",
    "release_timestamp_utc",
    "reference_date",
    "created",
    "ts_event",
    "auction_date",
    "friday",
    "window_start",
)

ASSET_CLASS_SETS = {
    "US_EQUITY_BROAD": {"DIA", "IJR", "IWM", "MDY", "QQQ", "RSP", "SPY", "VTI"},
    "US_EQUITY_SECTOR": {
        "IBB", "ITB", "IYT", "KRE", "SMH", "XBI", "XLB", "XLC", "XLE", "XLF",
        "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY", "XRT",
    },
    "INTERNATIONAL_EQUITY": {
        "EEM", "EFA", "EPI", "EWA", "EWC", "EWG", "EWH", "EWJ", "EWT", "EWU",
        "EWW", "EWZ", "FXI", "IEV", "INDA",
    },
    "FIXED_INCOME": {"AGG", "EMB", "HYG", "IEF", "LQD", "MUB", "SHY", "TIP", "TLT"},
    "REAL_ASSET": {"DBA", "DBC", "GLD", "IYR", "SLV", "UNG", "USO", "VNQ"},
}

GEOGRAPHY_SETS = {
    "DEVELOPED_EX_US": {"EFA", "EWA", "EWC", "EWG", "EWH", "EWJ", "EWU", "IEV"},
    "EMERGING_MARKETS": {"EEM", "EPI", "EWT", "EWW", "EWZ", "FXI", "INDA"},
}

PRIMARY_PROXY_TICKERS = {"AGG", "DBC", "EEM", "EFA", "HYG", "IWM", "LQD", "QQQ", "SPY", "VTI", "VNQ"}

STRATEGY_MAP = (
    ("BUYOUT", "DIVERSIFIED", "VTI", "PRIMARY", "Broad listed-equity opportunity-cost proxy."),
    ("BUYOUT", "SMALL_MIDDLE_MARKET", "IWM", "SENSITIVITY", "Small-cap listed-equity sensitivity."),
    ("VENTURE_CAPITAL", "GROWTH", "QQQ", "PRIMARY", "Listed growth-equity opportunity-cost proxy."),
    ("GROWTH_EQUITY", "DIVERSIFIED", "QQQ", "PRIMARY", "Listed growth-equity opportunity-cost proxy."),
    ("PRIVATE_CREDIT", "DIVERSIFIED", "AGG", "PRIMARY", "Diversified bond-market proxy."),
    ("PRIVATE_CREDIT", "INVESTMENT_GRADE", "LQD", "PRIMARY", "Investment-grade corporate-credit proxy."),
    ("PRIVATE_CREDIT", "HIGH_YIELD", "HYG", "PRIMARY", "High-yield corporate-credit proxy."),
    ("REAL_ESTATE", "DIVERSIFIED", "VNQ", "PRIMARY", "Listed real-estate sensitivity proxy."),
    ("REAL_ESTATE", "PROPERTY_SENSITIVITY", "IYR", "SENSITIVITY", "Alternative listed real-estate proxy."),
    ("INFRASTRUCTURE", "UTILITIES", "XLU", "SENSITIVITY", "Listed utilities sensitivity proxy."),
    ("INFRASTRUCTURE", "TRANSPORT", "IYT", "SENSITIVITY", "Listed transport sensitivity proxy."),
    ("NATURAL_RESOURCES", "DIVERSIFIED", "DBC", "PRIMARY", "Diversified commodity sensitivity proxy."),
    ("NATURAL_RESOURCES", "ENERGY", "XLE", "SENSITIVITY", "Listed energy-equity sensitivity proxy."),
    ("NATURAL_RESOURCES", "GOLD", "GLD", "SENSITIVITY", "Gold sensitivity proxy."),
    ("SECONDARIES", "DIVERSIFIED", "VTI", "PRIMARY", "Broad listed-equity opportunity-cost proxy."),
    ("INTERNATIONAL", "DEVELOPED", "EFA", "PRIMARY", "Developed-market equity proxy."),
    ("INTERNATIONAL", "EMERGING", "EEM", "PRIMARY", "Emerging-market equity proxy."),
    ("HEALTHCARE", "LIFE_SCIENCES", "IBB", "SENSITIVITY", "Listed biotechnology sensitivity proxy."),
    ("TECHNOLOGY", "DIVERSIFIED", "XLK", "SENSITIVITY", "Listed technology-sector sensitivity proxy."),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def flattened_name(relative_path: str) -> str:
    return relative_path.replace("/", "__")


def unflattened_name(stored_name: str) -> str:
    return stored_name.replace("__", "/")


def segments_match(parts: Sequence[str], wanted: Sequence[str]) -> bool:
    return all(fnmatch.fnmatchcase(part, want) for part, want in zip(parts, wanted))


def matches_pattern(relative_path: str, pattern: str) -> bool:
    """Glob one source path against one selection pattern, segment by segment.
    A `**` segment covers zero or more folders, the reading `Path.glob` gives it
    on a nested corpus."""
    parts = relative_path.split("/")
    wanted = pattern.split("/")
    if "**" in wanted:
        cut = wanted.index("**")
        head, tail = wanted[:cut], wanted[cut + 1 :]
        if len(parts) < len(head) + len(tail):
            return False
        return segments_match(parts[: len(head)], head) and segments_match(
            parts[len(parts) - len(tail) :], tail
        )
    return len(parts) == len(wanted) and segments_match(parts, wanted)


def source_index(source_root: Path) -> dict[str, Path]:
    """Map every source file to the path holding its bytes, keyed by the layout
    the acquiring corpus used. A file sitting flat in the retained store carries
    its folders in its name; a nested corpus states them directly. Folder guides
    stay out: they describe the store rather than supplying data."""
    index: dict[str, Path] = {}
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() == ".md":
            continue
        relative = path.relative_to(source_root).as_posix()
        key = relative if "/" in relative else unflattened_name(relative)
        if key in index:
            raise ValueError(f"Two files claim the same source path: {key}")
        index[key] = path
    return index


def asset_class_for(ticker: str) -> str:
    matches = [name for name, tickers in ASSET_CLASS_SETS.items() if ticker in tickers]
    if len(matches) != 1:
        raise ValueError(f"Asset-class mapping count for {ticker}: {len(matches)}")
    return matches[0]


def geography_for(ticker: str) -> str:
    for name, tickers in GEOGRAPHY_SETS.items():
        if ticker in tickers:
            return name
    if asset_class_for(ticker).startswith("US_EQUITY"):
        return "UNITED_STATES"
    return "MULTI_MARKET"


def select_files(index: dict[str, Path]) -> list[tuple[str, Path, Selection]]:
    selected: dict[str, tuple[str, Path, Selection]] = {}
    for selection in SELECTIONS:
        matches = sorted(
            (relative for relative in index if any(matches_pattern(relative, p) for p in selection.patterns)),
            key=str.lower,
        )
        if len(matches) != selection.expected_count:
            raise ValueError(
                f"Selection {selection.name} expected {selection.expected_count} files and found {len(matches)}"
            )
        for relative in matches:
            if relative in selected:
                raise ValueError(f"Duplicate selection route: {relative}")
            selected[relative] = (relative, index[relative], selection)
    total_bytes = sum(path.stat().st_size for _, path, _ in selected.values())
    if total_bytes > MAX_TRANSFER_BYTES:
        raise ValueError(f"Selected transfer size {total_bytes} exceeds safety bound {MAX_TRANSFER_BYTES}")
    return [selected[key] for key in sorted(selected, key=str.lower)]


def profile_parquet(path: Path) -> dict[str, object]:
    parquet_file = pq.ParquetFile(path)
    schema = parquet_file.schema_arrow
    schema_text = "; ".join(f"{field.name}:{field.type}" for field in schema)
    date_column = next((name for name in DATE_COLUMNS if name in schema.names), "")
    date_min = ""
    date_max = ""
    if date_column and parquet_file.metadata.num_rows:
        values = pq.read_table(path, columns=[date_column]).column(0).to_pandas()
        dates = pd.to_datetime(values, errors="coerce", utc=True).dropna()
        if len(dates):
            date_min = dates.min().isoformat()
            date_max = dates.max().isoformat()
    date_type = str(schema.field(date_column).type) if date_column else ""
    if date_column:
        timezone_status = "UTC_AWARE" if "tz=UTC" in date_type else "DATE_NAIVE"
    else:
        timezone_status = "DATE_FIELD_UNRESOLVED"
    return {
        "row_count": parquet_file.metadata.num_rows,
        "column_count": len(schema),
        "date_column": date_column,
        "date_min": date_min,
        "date_max": date_max,
        "timezone_status": timezone_status,
        "schema": schema_text,
        "schema_sha256": hashlib.sha256(schema_text.encode("utf-8")).hexdigest(),
    }


def portable_output_path(path: Path, output_root: Path) -> str:
    """Use a repository path in place and an output-root path in scratch."""
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.relative_to(output_root).as_posix()


def copy_and_inventory(
    output_root: Path,
    selected: list[tuple[str, Path, Selection]],
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    sources_dir = output_root / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    inventory: list[dict[str, object]] = []
    by_source_path: dict[str, dict[str, object]] = {}
    for source_relative, source_path, selection in selected:
        destination = sources_dir / flattened_name(source_relative)
        source_hash = sha256_file(source_path)
        if source_path == destination:
            copy_action = "RETAINED_IN_PLACE"
        elif destination.exists() and sha256_file(destination) == source_hash:
            copy_action = "REUSED_MATCHING_COPY"
        else:
            shutil.copy2(source_path, destination)
            copy_action = "COPIED"
        destination_hash = sha256_file(destination)
        if destination_hash != source_hash:
            raise ValueError(f"SHA-256 mismatch after transfer: {source_relative}")
        profile = profile_parquet(destination)
        file_id = "PMKT_" + hashlib.sha256(source_relative.encode("utf-8")).hexdigest()[:16].upper()
        row = {
            "file_id": file_id,
            "source_relative_path": source_relative,
            "destination_relative_path": portable_output_path(
                destination, output_root
            ),
            "analysis_tier": selection.tier,
            "source_family": selection.family,
            "promotion_status": selection.promotion_status,
            "pme_role": selection.pme_role,
            "return_basis": selection.return_basis,
            "source_system": selection.source_system,
            "producer_script": selection.producer_script,
            "rights_status": "DEMONSTRATION_ONLY",
            "copy_action": copy_action,
            "size_bytes": destination.stat().st_size,
            "row_count": profile["row_count"],
            "column_count": profile["column_count"],
            "date_column": profile["date_column"],
            "date_min": profile["date_min"],
            "date_max": profile["date_max"],
            "timezone_status": profile["timezone_status"],
            "schema_sha256": profile["schema_sha256"],
            "sha256": destination_hash,
            "schema": profile["schema"],
            "note": selection.note,
        }
        inventory.append(row)
        by_source_path[source_relative] = row
    return inventory, by_source_path


def load_benchmark_series(
    ticker: str,
    output_root: Path,
    inventory_by_source: dict[str, dict[str, object]],
) -> tuple[pd.DataFrame, dict[str, object], str]:
    if ticker in LONG_HISTORY_ETFS:
        source_relative = f"raw/equity/YF_{ticker}.parquet"
        source_priority = "YF_LONG_HISTORY"
        source_row = inventory_by_source[source_relative]
        source_path = output_root / "sources" / flattened_name(source_relative)
        frame = pd.read_parquet(source_path, columns=["timestamp_utc", "close"])
        frame = frame.rename(columns={"timestamp_utc": "date", "close": "level"})
        source_locator_column = "close"
    else:
        source_relative = "raw/wide_etf/wide_etf_adjclose.parquet"
        source_priority = "WIDE_PANEL_SUPPLEMENT"
        source_row = inventory_by_source[source_relative]
        source_path = output_root / "sources" / flattened_name(source_relative)
        frame = pd.read_parquet(source_path, columns=["Date", ticker])
        if "Date" not in frame.columns and frame.index.name == "Date":
            frame = frame.reset_index()
        frame = frame.rename(columns={"Date": "date", ticker: "level"})
        source_locator_column = ticker
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.date
    frame["level"] = pd.to_numeric(frame["level"], errors="coerce")
    frame = frame.dropna(subset=["date", "level"]).sort_values("date").reset_index(drop=True)
    if frame["date"].duplicated().any():
        raise ValueError(f"Duplicate benchmark dates: {ticker}")
    if (frame["level"] <= 0).any():
        raise ValueError(f"Nonpositive benchmark level: {ticker}")
    frame["source_row_index"] = range(len(frame))
    return frame, source_row, source_priority + ":" + source_locator_column


def build_benchmark_candidates(
    output_root: Path,
    inventory_by_source: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    wide_source = inventory_by_source["raw/wide_etf/wide_etf_adjclose.parquet"]
    wide_path = output_root / "sources" / flattened_name(
        "raw/wide_etf/wide_etf_adjclose.parquet"
    )
    wide_schema = pq.read_schema(wide_path)
    tickers = sorted({name for name in wide_schema.names if name != "Date"} | set(LONG_HISTORY_ETFS))
    mapped_tickers = set().union(*ASSET_CLASS_SETS.values())
    if set(tickers) != mapped_tickers:
        missing = sorted(set(tickers) - mapped_tickers)
        stale = sorted(mapped_tickers - set(tickers))
        raise ValueError(f"Benchmark metadata mismatch; missing={missing}; stale={stale}")

    masters: list[dict[str, object]] = []
    levels: list[dict[str, object]] = []
    returns: list[dict[str, object]] = []
    maximum_return_tieout = 0.0
    for ticker in tickers:
        frame, source_row, source_descriptor = load_benchmark_series(ticker, output_root, inventory_by_source)
        benchmark_id = f"BMK_ETF_{ticker}"
        source_priority, source_column = source_descriptor.split(":", maxsplit=1)
        pme_use_status = "PRIMARY_PROXY" if ticker in PRIMARY_PROXY_TICKERS else "SENSITIVITY_PROXY"
        masters.append(
            {
                "benchmark_id": benchmark_id,
                "benchmark_name": f"{ticker} adjusted ETF proxy",
                "ticker": ticker,
                "instrument_type": "EXCHANGE_TRADED_FUND",
                "asset_class": asset_class_for(ticker),
                "geography": geography_for(ticker),
                "currency": "USD",
                "source_provider": "YAHOO_FINANCE_VIA_YFINANCE",
                "return_basis": "ADJUSTED_ETF_PRICE_PROXY",
                "adjusted_flag": "TRUE",
                "calendar": "US_EXCHANGE_TRADING_DATES",
                "timezone": "DATE_ONLY_US_MARKET",
                "first_observation_date": frame["date"].iloc[0].isoformat(),
                "last_observation_date": frame["date"].iloc[-1].isoformat(),
                "observation_count": len(frame),
                "source_priority": source_priority,
                "source_file_id": source_row["file_id"],
                "source_column": source_column,
                "rights_status": "DEMONSTRATION_ONLY",
                "pme_use_status": pme_use_status,
                "record_status": "CANDIDATE",
                "note": "ETF expenses and tracking effects differ from institutional total-return indices.",
            }
        )
        level_ids: list[str] = []
        for row in frame.itertuples(index=False):
            date_text = row.date.isoformat()
            level_id = f"LVL_{ticker}_{date_text.replace('-', '')}"
            level_ids.append(level_id)
            levels.append(
                {
                    "benchmark_level_id": level_id,
                    "benchmark_id": benchmark_id,
                    "observation_date": date_text,
                    "level_value": format(float(row.level), ".12g"),
                    "currency": "USD",
                    "return_basis": "ADJUSTED_ETF_PRICE_PROXY",
                    "market_date_policy": "OBSERVED_TRADING_DATE",
                    "source_file_id": source_row["file_id"],
                    "source_locator": f"row_index={row.source_row_index};column={source_column}",
                    "market_data_provenance_type": "VENDOR_SOURCE",
                    "record_status": "CANDIDATE",
                }
            )
        simple_returns = frame["level"].pct_change(fill_method=None)
        for index in range(1, len(frame)):
            return_value = float(simple_returns.iloc[index])
            recomputed = float(frame["level"].iloc[index] / frame["level"].iloc[index - 1] - 1.0)
            maximum_return_tieout = max(maximum_return_tieout, abs(return_value - recomputed))
            date_text = frame["date"].iloc[index].isoformat()
            returns.append(
                {
                    "benchmark_return_id": f"RET_{ticker}_{date_text.replace('-', '')}",
                    "benchmark_id": benchmark_id,
                    "period_start": frame["date"].iloc[index - 1].isoformat(),
                    "return_date": date_text,
                    "periodicity": "DAILY",
                    "return_type": "SIMPLE",
                    "return_value": format(return_value, ".12g"),
                    "currency": "USD",
                    "return_basis": "ADJUSTED_ETF_PRICE_PROXY",
                    "formula_id": "FORMULA_SIMPLE_RETURN_V1",
                    "source_level_start_id": level_ids[index - 1],
                    "source_level_end_id": level_ids[index],
                    "market_date_policy": "OBSERVED_TRADING_DATES",
                    "market_data_provenance_type": "DERIVED_MARKET_DATA",
                    "record_status": "CANDIDATE",
                }
            )

    strategy_rows = [
        {
            "strategy_map_id": f"SMAP_{index:03d}",
            "strategy": strategy,
            "sub_strategy": sub_strategy,
            "benchmark_id": f"BMK_ETF_{ticker}",
            "benchmark_role": role,
            "selection_timing_rule": "PRECOMMIT_BEFORE_FUND_RESULT_REVIEW",
            "record_status": "CANDIDATE",
            "note": note,
        }
        for index, (strategy, sub_strategy, ticker, role, note) in enumerate(STRATEGY_MAP, start=1)
    ]
    metrics = {
        "benchmark_count": len(masters),
        "level_count": len(levels),
        "return_count": len(returns),
        "strategy_map_count": len(strategy_rows),
        "duplicate_level_keys": len(levels) - len({(row["benchmark_id"], row["observation_date"]) for row in levels}),
        "returns_at_or_below_minus_one": sum(float(row["return_value"]) <= -1 for row in returns),
        "maximum_return_tieout": maximum_return_tieout,
        "long_history_benchmark_count": sum(row["source_priority"] == "YF_LONG_HISTORY" for row in masters),
        "wide_panel_benchmark_count": sum(row["source_priority"] == "WIDE_PANEL_SUPPLEMENT" for row in masters),
    }
    return masters, levels, returns, strategy_rows, metrics


def build_family_summary(
    index: dict[str, Path],
    inventory_by_source: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """Summarise the retained store one row per series family: how many files it
    holds, how large they are, which analysis tiers and PME roles they carry, and
    the system each came from."""
    families: dict[str, list[str]] = {}
    for relative in inventory_by_source:
        families.setdefault(str(inventory_by_source[relative]["source_family"]), []).append(relative)
    rows: list[dict[str, object]] = []
    for family in sorted(families, key=str.lower):
        members = families[family]
        entries = [inventory_by_source[path] for path in members]

        def values(column: str) -> str:
            return ";".join(sorted({str(entry[column]) for entry in entries}))

        rows.append(
            {
                "source_family": family,
                "file_count": len(members),
                "total_bytes": sum(index[path].stat().st_size for path in members),
                "row_count": sum(int(entry["row_count"]) for entry in entries),
                "analysis_tiers": values("analysis_tier"),
                "pme_roles": values("pme_role"),
                "source_systems": values("source_system"),
                "rights_status": values("rights_status"),
                "note": entries[0]["note"],
            }
        )
    return rows


def build_quality_results(
    inventory: list[dict[str, object]],
    candidate_metrics: dict[str, object],
    selected_bytes: int,
) -> list[dict[str, object]]:
    checks = [
        ("PMQ01", "Selected file count", len(inventory), 334, len(inventory) == 334, "Every declared selection matched its expected count."),
        ("PMQ02", "Transferred bytes", selected_bytes, f"<= {MAX_TRANSFER_BYTES}", selected_bytes <= MAX_TRANSFER_BYTES, "The transfer stays inside the size safety bound."),
        ("PMQ03", "Source-copy hash matches", sum(row["copy_action"] in {"COPIED", "REUSED_MATCHING_COPY", "RETAINED_IN_PLACE"} for row in inventory), len(inventory), True, "Each retained file passed SHA-256 comparison."),
        ("PMQ04", "Positive source rows", sum(int(row["row_count"]) > 0 for row in inventory), len(inventory), all(int(row["row_count"]) > 0 for row in inventory), "Every selected Parquet carries at least one row."),
        ("PMQ05", "Benchmark master rows", candidate_metrics["benchmark_count"], 58, candidate_metrics["benchmark_count"] == 58, "The wide panel plus three longer-history additions define the adjusted ETF benchmark universe."),
        ("PMQ06", "Duplicate benchmark-date keys", candidate_metrics["duplicate_level_keys"], 0, candidate_metrics["duplicate_level_keys"] == 0, "Each benchmark has one level per observed trading date."),
        ("PMQ07", "Simple returns at or below minus one", candidate_metrics["returns_at_or_below_minus_one"], 0, candidate_metrics["returns_at_or_below_minus_one"] == 0, "Daily simple returns satisfy the economic floor."),
        ("PMQ08", "Return-level tie-out", candidate_metrics["maximum_return_tieout"], 0.0, candidate_metrics["maximum_return_tieout"] <= 1e-15, "Each return matches the two linked levels."),
        ("PMQ09", "Long-history source count", candidate_metrics["long_history_benchmark_count"], 29, candidate_metrics["long_history_benchmark_count"] == 29, "Available YF files receive source priority."),
        ("PMQ10", "Wide-panel supplement count", candidate_metrics["wide_panel_benchmark_count"], 29, candidate_metrics["wide_panel_benchmark_count"] == 29, "The wide panel supplies the remaining ETF candidates."),
    ]
    return [
        {
            "check_id": check_id,
            "scope": scope,
            "status": "PASS" if passed else "FAIL",
            "actual": actual,
            "expected": expected,
            "tolerance": "1e-15" if check_id == "PMQ08" else "",
            "note": note,
        }
        for check_id, scope, actual, expected, passed, note in checks
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-at", default="")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    if not source_root.exists():
        raise FileNotFoundError(source_root)
    for child in ("sources", "staging", "audit"):
        (output_root / child).mkdir(parents=True, exist_ok=True)

    index = source_index(source_root)
    selected = select_files(index)
    inventory, inventory_by_source = copy_and_inventory(output_root, selected)
    masters, levels, returns, strategy_rows, candidate_metrics = build_benchmark_candidates(
        output_root, inventory_by_source
    )
    family_rows = build_family_summary(index, inventory_by_source)
    selected_bytes = sum(int(row["size_bytes"]) for row in inventory)
    quality_rows = build_quality_results(inventory, candidate_metrics, selected_bytes)
    if any(row["status"] == "FAIL" for row in quality_rows):
        failed = [row["check_id"] for row in quality_rows if row["status"] == "FAIL"]
        raise ValueError(f"Public-market quality gate failed: {failed}")

    audit_dir = output_root / "audit"
    staging_dir = output_root / "staging"
    write_csv(audit_dir / "source_file_inventory.csv", list(inventory[0]), inventory)
    write_csv(audit_dir / "source_family_summary.csv", list(family_rows[0]), family_rows)
    write_csv(audit_dir / "quality_results.csv", list(quality_rows[0]), quality_rows)
    write_csv(staging_dir / "benchmark_master_candidates.csv", list(masters[0]), masters)
    write_csv(staging_dir / "benchmark_level_candidates.csv", list(levels[0]), levels)
    write_csv(staging_dir / "benchmark_return_candidates.csv", list(returns[0]), returns)
    write_csv(staging_dir / "benchmark_strategy_map_candidates.csv", list(strategy_rows[0]), strategy_rows)

    selection_digest = hashlib.sha256(
        "\n".join(f"{row['source_relative_path']}|{row['sha256']}" for row in inventory).encode("utf-8")
    ).hexdigest()
    run_at = args.run_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    in_place = source_root == (output_root / "sources").resolve()
    run_row = {
        "run_id": "PMRUN_" + selection_digest[:16].upper(),
        "executed_at_utc": run_at,
        # The receipt names folders, never a machine path: the output relative
        # to the repository, the source by its last two path parts.
        "source_root": "/".join(source_root.parts[-2:]),
        "output_root": portable_output_path(output_root, output_root),
        "transfer_mode": "RETAINED_STORE" if in_place else "COPY_PRESERVE_SOURCE",
        "source_corpus_file_count": len(index),
        "source_corpus_bytes": sum(path.stat().st_size for path in index.values()),
        "selected_file_count": len(inventory),
        "selected_bytes": selected_bytes,
        "benchmark_count": candidate_metrics["benchmark_count"],
        "benchmark_level_count": candidate_metrics["level_count"],
        "benchmark_return_count": candidate_metrics["return_count"],
        "strategy_map_count": candidate_metrics["strategy_map_count"],
        "selection_sha256": selection_digest,
        "quality_status": "PASS",
    }
    write_csv(audit_dir / "market_data_runs.csv", list(run_row), [run_row])
    print(json.dumps(run_row, indent=2))


if __name__ == "__main__":
    main()
