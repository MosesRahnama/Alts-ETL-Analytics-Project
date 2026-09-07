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

from src.common import matrices


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "public_markets"
DEFAULT_SOURCE_ROOT = DEFAULT_OUTPUT_ROOT / "sources"


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


# Every constant above has moved into a matrix under
SOURCE_SELECTION = "public-market-source-selection"
QUALITY_RULES = "public-market-quality-rules"
SOURCE_LISTS = "public-market-source-priority"
SERIES_SOURCES = "benchmark-source-priority"
COLUMN_MAP = "public-market-column-map"
DATE_COLUMN_ORDER = "public-market-date-columns"
TICKER_CLASSES = "ticker-classification"
PME_ROLES = "ticker-pme-role"
STRATEGY_BENCHMARKS = "strategy-benchmark-map"
PATH_RULES = "path-normalization"
FILE_FILTERS = "public-market-file-filters"
PARSING_RULES = "public-market-parsing-rules"
TIMEZONE_STATUS = "public-market-timezone-status"
COPY_ACTIONS = "public-market-copy-action"
IDENTIFIERS = "public-market-identifiers"
RIGHTS_POLICY = "public-market-rights-policy"
ROW_FILTERS = "public-market-row-filters"
BENCHMARK_DEFAULTS = "public-market-benchmark-defaults"
RETURN_RULES = "return-construction"
SUMMARY_RULES = "public-market-summary-rules"
STATUS_MAP = "public-market-status-map"
RUNTIME_DEFAULTS = "pipeline-runtime-defaults"

MAX_TRANSFER_BYTES = int(matrices.resolve(QUALITY_RULES, "transfer_bound_bytes"))
LEGACY_ADJUSTED_ETFS = tuple(matrices.resolve(SOURCE_LISTS, "legacy_adjusted_etfs").split("|"))
LONG_HISTORY_ETFS = tuple(matrices.resolve(SOURCE_LISTS, "long_history_etfs").split("|"))
SELECTIONS = tuple(
    Selection(
        row["input_value"],
        tuple(row["output_value"].split("|")),
        int(row["expected_count"]),
        row["tier"],
        row["family"],
        row["promotion_status"],
        row["pme_role"],
        row["return_basis"],
        row["source_system"],
        row["producer_script"],
        row["selection_note"],
    )
    for row in matrices.load(SOURCE_SELECTION)
)
DATE_COLUMNS = tuple(
    row["output_value"]
    for row in sorted(matrices.rows_in(DATE_COLUMN_ORDER), key=lambda item: int(item["input_value"]))
)
ASSET_CLASS_SETS: dict[str, set[str]] = {}
for _row in matrices.rows_in(TICKER_CLASSES, "asset_class"):
    ASSET_CLASS_SETS.setdefault(_row["output_value"], set()).add(_row["input_value"])
GEOGRAPHY_SETS: dict[str, set[str]] = {}
for _row in matrices.rows_in(TICKER_CLASSES, "geography"):
    GEOGRAPHY_SETS.setdefault(_row["output_value"], set()).add(_row["input_value"])
PRIMARY_PROXY_TICKERS = {
    row["input_value"]
    for row in matrices.load(PME_ROLES)
    if row["output_value"] == "PRIMARY_PROXY" and row["input_value"] != "*"
}
STRATEGY_MAP = tuple(
    (row["input_value"], "", row["output_value"], row["benchmark_role"], row["note"])
    for row in matrices.rows_in(STRATEGY_BENCHMARKS, "canonical_strategy")
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
    return relative_path.replace("/", matrices.resolve(PATH_RULES, "flattened_separator"))


def unflattened_name(stored_name: str) -> str:
    return stored_name.replace(matrices.resolve(PATH_RULES, "flattened_separator"), "/")


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
        if not path.is_file() or path.suffix.lower() == matrices.resolve(FILE_FILTERS, "excluded_suffix"):
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
        return matrices.resolve(TICKER_CLASSES, "us_equity_prefix", context="geography_default")
    return matrices.resolve_or_star(TICKER_CLASSES, "", context="geography_default")


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
        dates = pd.to_datetime(
            values,
            errors=matrices.resolve(PARSING_RULES, "date_parse_errors", context="profile"),
            utc=matrices.resolve(PARSING_RULES, "date_parse_utc", context="profile") == "true",
        ).dropna()
        if len(dates):
            date_min = dates.min().isoformat()
            date_max = dates.max().isoformat()
    date_type = str(schema.field(date_column).type) if date_column else ""
    if date_column:
        timezone_status = (
            matrices.resolve(TIMEZONE_STATUS, "aware_status")
            if matrices.resolve(TIMEZONE_STATUS, "utc_marker") in date_type
            else matrices.resolve(TIMEZONE_STATUS, "naive_status")
        )
    else:
        timezone_status = matrices.resolve(TIMEZONE_STATUS, "missing_status")
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
            copy_action = matrices.resolve(COPY_ACTIONS, "same_path")
        elif destination.exists() and sha256_file(destination) == source_hash:
            copy_action = matrices.resolve(COPY_ACTIONS, "matching_existing_copy")
        else:
            shutil.copy2(source_path, destination)
            copy_action = matrices.resolve(COPY_ACTIONS, "otherwise")
        destination_hash = sha256_file(destination)
        if destination_hash != source_hash:
            raise ValueError(f"SHA-256 mismatch after transfer: {source_relative}")
        profile = profile_parquet(destination)
        file_id = matrices.resolve(IDENTIFIERS, "prefix", context="file") + hashlib.sha256(
            source_relative.encode("utf-8")
        ).hexdigest()[: int(matrices.resolve(IDENTIFIERS, "digest_length", context="file"))].upper()
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
            "rights_status": matrices.resolve(RIGHTS_POLICY, "rights_status"),
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
        source_relative = matrices.resolve(SERIES_SOURCES, "source_pattern", context="long_history").format(ticker=ticker)
        source_priority = matrices.resolve(SERIES_SOURCES, "source_priority", context="long_history")
        source_row = inventory_by_source[source_relative]
        source_path = output_root / "sources" / flattened_name(source_relative)
        renames = matrices.mapping(COLUMN_MAP, context="long_history")
        frame = pd.read_parquet(source_path, columns=list(renames))
        frame = frame.rename(columns=renames)
        source_locator_column = next(name for name, target in renames.items() if target == "level")
    else:
        source_relative = matrices.resolve(SERIES_SOURCES, "source_pattern", context="wide_panel")
        source_priority = matrices.resolve(SERIES_SOURCES, "source_priority", context="wide_panel")
        source_row = inventory_by_source[source_relative]
        source_path = output_root / "sources" / flattened_name(source_relative)
        renames = {
            (ticker if name == "{ticker}" else name): target
            for name, target in matrices.mapping(COLUMN_MAP, context="wide_panel").items()
        }
        date_source = next(name for name, target in renames.items() if target == "date")
        frame = pd.read_parquet(source_path, columns=list(renames))
        if date_source not in frame.columns and frame.index.name == date_source:
            frame = frame.reset_index()
        frame = frame.rename(columns=renames)
        source_locator_column = ticker
    frame["date"] = pd.to_datetime(
        frame["date"], errors=matrices.resolve(PARSING_RULES, "date_parse_errors", context="benchmark")
    ).dt.date
    frame["level"] = pd.to_numeric(
        frame["level"], errors=matrices.resolve(PARSING_RULES, "level_parse_errors", context="benchmark")
    )
    if matrices.resolve(ROW_FILTERS, "missing_date_or_level") == "dropped":
        frame = frame.dropna(subset=["date", "level"])
    frame = frame.sort_values("date").reset_index(drop=True)
    if matrices.resolve(ROW_FILTERS, "duplicate_dates") == "refused" and frame["date"].duplicated().any():
        raise ValueError(f"Duplicate benchmark dates: {ticker}")
    if matrices.resolve(ROW_FILTERS, "nonpositive_level") == "refused" and (frame["level"] <= 0).any():
        raise ValueError(f"Nonpositive benchmark level: {ticker}")
    frame["source_row_index"] = range(len(frame))
    return frame, source_row, source_priority + ":" + source_locator_column


def build_benchmark_candidates(
    output_root: Path,
    inventory_by_source: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    # The lookup is the assertion: a benchmark built from a wide file the
    # inventory never recorded would carry no provenance, so the missing key
    # stops the build here instead of producing an unsourced series.
    if "raw/wide_etf/wide_etf_adjclose.parquet" not in inventory_by_source:
        raise KeyError("inventory has no row for raw/wide_etf/wide_etf_adjclose.parquet")
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
        benchmark_id = matrices.resolve(IDENTIFIERS, "benchmark_format", context="benchmark").format(ticker=ticker)
        source_priority, source_column = source_descriptor.split(":", maxsplit=1)
        pme_use_status = matrices.resolve_or_star(PME_ROLES, ticker)
        masters.append(
            {
                "benchmark_id": benchmark_id,
                "benchmark_name": matrices.resolve(BENCHMARK_DEFAULTS, "benchmark_name_format").format(ticker=ticker),
                "ticker": ticker,
                "instrument_type": matrices.resolve(BENCHMARK_DEFAULTS, "instrument_type"),
                "asset_class": asset_class_for(ticker),
                "geography": geography_for(ticker),
                "currency": matrices.resolve(BENCHMARK_DEFAULTS, "currency"),
                "source_provider": matrices.resolve(BENCHMARK_DEFAULTS, "source_provider"),
                "return_basis": matrices.resolve(BENCHMARK_DEFAULTS, "return_basis"),
                "adjusted_flag": matrices.resolve(BENCHMARK_DEFAULTS, "adjusted_flag"),
                "calendar": matrices.resolve(BENCHMARK_DEFAULTS, "calendar"),
                "timezone": matrices.resolve(BENCHMARK_DEFAULTS, "timezone"),
                "first_observation_date": frame["date"].iloc[0].isoformat(),
                "last_observation_date": frame["date"].iloc[-1].isoformat(),
                "observation_count": len(frame),
                "source_priority": source_priority,
                "source_file_id": source_row["file_id"],
                "source_column": source_column,
                "rights_status": matrices.resolve(RIGHTS_POLICY, "rights_status"),
                "pme_use_status": pme_use_status,
                "record_status": matrices.resolve(BENCHMARK_DEFAULTS, "record_status"),
                "note": matrices.resolve(BENCHMARK_DEFAULTS, "master_note"),
            }
        )
        level_ids: list[str] = []
        for row in frame.itertuples(index=False):
            date_text = row.date.isoformat()
            level_id = matrices.resolve(IDENTIFIERS, "level_format", context="level").format(
                ticker=ticker, date=date_text.replace("-", "")
            )
            level_ids.append(level_id)
            levels.append(
                {
                    "benchmark_level_id": level_id,
                    "benchmark_id": benchmark_id,
                    "observation_date": date_text,
                    "level_value": format(float(row.level), matrices.resolve(RETURN_RULES, "value_format")),
                    "currency": matrices.resolve(BENCHMARK_DEFAULTS, "currency"),
                    "return_basis": matrices.resolve(BENCHMARK_DEFAULTS, "return_basis"),
                    "market_date_policy": matrices.resolve(RETURN_RULES, "level_date_policy"),
                    "source_file_id": source_row["file_id"],
                    "source_locator": f"row_index={row.source_row_index};column={source_column}",
                    "market_data_provenance_type": matrices.resolve(RETURN_RULES, "level_provenance"),
                    "record_status": matrices.resolve(BENCHMARK_DEFAULTS, "record_status"),
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
                    "benchmark_return_id": matrices.resolve(IDENTIFIERS, "return_format", context="return").format(
                        ticker=ticker, date=date_text.replace("-", "")
                    ),
                    "benchmark_id": benchmark_id,
                    "period_start": frame["date"].iloc[index - 1].isoformat(),
                    "return_date": date_text,
                    "periodicity": matrices.resolve(RETURN_RULES, "periodicity"),
                    "return_type": matrices.resolve(RETURN_RULES, "return_type"),
                    "return_value": format(return_value, matrices.resolve(RETURN_RULES, "value_format")),
                    "currency": matrices.resolve(BENCHMARK_DEFAULTS, "currency"),
                    "return_basis": matrices.resolve(BENCHMARK_DEFAULTS, "return_basis"),
                    "formula_id": matrices.resolve(RETURN_RULES, "formula_id"),
                    "source_level_start_id": level_ids[index - 1],
                    "source_level_end_id": level_ids[index],
                    "market_date_policy": matrices.resolve(RETURN_RULES, "return_date_policy"),
                    "market_data_provenance_type": matrices.resolve(RETURN_RULES, "return_provenance"),
                    "record_status": matrices.resolve(BENCHMARK_DEFAULTS, "record_status"),
                }
            )

    strategy_rows = [
        {
            "strategy_map_id": matrices.resolve(IDENTIFIERS, "strategy_format", context="strategy").format(index=index),
            "strategy": strategy,
            "sub_strategy": sub_strategy,
            "benchmark_id": matrices.resolve(IDENTIFIERS, "benchmark_format", context="benchmark").format(ticker=ticker),
            "benchmark_role": role,
            "selection_timing_rule": matrices.resolve(RETURN_RULES, "selection_timing_rule"),
            "record_status": matrices.resolve(BENCHMARK_DEFAULTS, "record_status"),
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
            return matrices.resolve(SUMMARY_RULES, "value_join").join(
                sorted({str(entry[column]) for entry in entries})
            )

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
    expected_files = int(matrices.resolve(QUALITY_RULES, "selected_file_count"))
    expected_benchmarks = int(matrices.resolve(QUALITY_RULES, "benchmark_count"))
    expected_long = int(matrices.resolve(QUALITY_RULES, "long_history_count"))
    expected_wide = int(matrices.resolve(QUALITY_RULES, "wide_panel_count"))
    tieout = float(matrices.resolve(QUALITY_RULES, "return_tieout_tolerance"))
    checks = [
        ("PMQ01", "Selected file count", len(inventory), expected_files, len(inventory) == expected_files, "Every declared selection matched its expected count."),
        ("PMQ02", "Transferred bytes", selected_bytes, f"<= {MAX_TRANSFER_BYTES}", selected_bytes <= MAX_TRANSFER_BYTES, "The transfer stays inside the size safety bound."),
        ("PMQ03", "Source-copy hash matches", sum(row["copy_action"] in {"COPIED", "REUSED_MATCHING_COPY", "RETAINED_IN_PLACE"} for row in inventory), len(inventory), True, "Each retained file passed SHA-256 comparison."),
        ("PMQ04", "Positive source rows", sum(int(row["row_count"]) > 0 for row in inventory), len(inventory), all(int(row["row_count"]) > 0 for row in inventory), "Every selected Parquet carries at least one row."),
        ("PMQ05", "Benchmark master rows", candidate_metrics["benchmark_count"], expected_benchmarks, candidate_metrics["benchmark_count"] == expected_benchmarks, "The wide panel plus three longer-history additions define the adjusted ETF benchmark universe."),
        ("PMQ06", "Duplicate benchmark-date keys", candidate_metrics["duplicate_level_keys"], 0, candidate_metrics["duplicate_level_keys"] == 0, "Each benchmark has one level per observed trading date."),
        ("PMQ07", "Simple returns at or below minus one", candidate_metrics["returns_at_or_below_minus_one"], 0, candidate_metrics["returns_at_or_below_minus_one"] == 0, "Daily simple returns satisfy the economic floor."),
        ("PMQ08", "Return-level tie-out", candidate_metrics["maximum_return_tieout"], 0.0, candidate_metrics["maximum_return_tieout"] <= tieout, "Each return matches the two linked levels."),
        ("PMQ09", "Long-history source count", candidate_metrics["long_history_benchmark_count"], expected_long, candidate_metrics["long_history_benchmark_count"] == expected_long, "Available YF files receive source priority."),
        ("PMQ10", "Wide-panel supplement count", candidate_metrics["wide_panel_benchmark_count"], expected_wide, candidate_metrics["wide_panel_benchmark_count"] == expected_wide, "The wide panel supplies the remaining ETF candidates."),
    ]
    return [
        {
            "check_id": check_id,
            "scope": scope,
            "status": matrices.resolve(STATUS_MAP, "pass_status" if passed else "fail_status"),
            "actual": actual,
            "expected": expected,
            "tolerance": matrices.resolve(QUALITY_RULES, "return_tieout_tolerance") if check_id == "PMQ08" else "",
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
    assert matrices.resolve(RUNTIME_DEFAULTS, "run_at_source") == "utc_now_seconds"
    run_at = args.run_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    in_place = source_root == (output_root / "sources").resolve()
    display_rule = matrices.resolve(RUNTIME_DEFAULTS, "source_root_display")
    assert display_rule == "last_two_parts"
    run_row = {
        "run_id": matrices.resolve(IDENTIFIERS, "run_prefix", context="run")
        + selection_digest[: int(matrices.resolve(IDENTIFIERS, "run_digest_length", context="run"))].upper(),
        "executed_at_utc": run_at,
        # The receipt names folders, never a machine path: the output relative
        # to the repository, the source by its last two path parts.
        "source_root": "/".join(source_root.parts[-2:]),
        "output_root": portable_output_path(output_root, output_root),
        "transfer_mode": matrices.resolve(RUNTIME_DEFAULTS, "in_place_mode")
        if in_place
        else matrices.resolve(RUNTIME_DEFAULTS, "copy_mode"),
        "source_corpus_file_count": len(index),
        "source_corpus_bytes": sum(path.stat().st_size for path in index.values()),
        "selected_file_count": len(inventory),
        "selected_bytes": selected_bytes,
        "benchmark_count": candidate_metrics["benchmark_count"],
        "benchmark_level_count": candidate_metrics["level_count"],
        "benchmark_return_count": candidate_metrics["return_count"],
        "strategy_map_count": candidate_metrics["strategy_map_count"],
        "selection_sha256": selection_digest,
        "quality_status": matrices.resolve(STATUS_MAP, "pass_status"),
    }
    write_csv(audit_dir / "market_data_runs.csv", list(run_row), [run_row])
    print(json.dumps(run_row, indent=2))


if __name__ == "__main__":
    main()
