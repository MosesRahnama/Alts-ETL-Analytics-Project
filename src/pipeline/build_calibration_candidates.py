"""Build an inactive, source-backed calibration audit exhibit.

The first pilot uses the fund-level real-estate schedule on SRC457 page 9.
It derives sample means and sample standard deviations for DPI and RVPI. The
rows remain inactive and are excluded from released parameters because one LP
schedule is not a general calibration basis.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "extracted" / "tables" / "fact_observation.csv"
DEFAULT_CONTRACT = PROJECT_ROOT / "data" / "csv" / "synthetic_parameters.csv"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "ledgers" / "analysis" / "synthetic_parameter_candidates.csv"
)

PARAMETER_SET_ID = "SOURCE_CALIBRATION_REAL_ESTATE_V1"
SOURCE_DOCUMENT_ID = "SRC457"
SOURCE_PAGE = "9"
SOURCE_TABLE = "Investment Detail"
SOURCE_STRATEGIES = {"Core", "Opportunistic", "Value Add"}
EXPECTED_FUND_COUNT = 33
METRICS = {
    "fund_economics_observation.dpi": "dpi",
    "fund_economics_observation.rvpi": "rvpi",
}


class CalibrationCandidateError(ValueError):
    """Raised when the source panel cannot support a deterministic queue."""


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise CalibrationCandidateError(f"missing CSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CalibrationCandidateError(f"CSV has no header: {path}")
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in reader
        ]


def _header(path: Path) -> list[str]:
    if not path.is_file():
        raise CalibrationCandidateError(f"missing contract CSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        try:
            return next(csv.reader(handle))
        except StopIteration as exc:
            raise CalibrationCandidateError(f"CSV has no header: {path}") from exc


def _plain_number(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _source_panel(
    rows: Iterable[Mapping[str, str]], expected_fund_count: int
) -> dict[str, list[Mapping[str, str]]]:
    selected = [
        row
        for row in rows
        if row.get("document_id") == SOURCE_DOCUMENT_ID
        and row.get("source_page") == SOURCE_PAGE
        and row.get("source_table") == SOURCE_TABLE
        and row.get("subject_type") == "fund"
        and row.get("strategy") in SOURCE_STRATEGIES
        and row.get("metric_id") in METRICS
    ]
    if not selected:
        raise CalibrationCandidateError("source panel has zero eligible observations")

    ids = [row.get("observation_id", "") for row in selected]
    if any(not value for value in ids):
        raise CalibrationCandidateError("source panel contains a blank observation_id")
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise CalibrationCandidateError(
            "source panel repeats observation IDs: " + ", ".join(duplicates)
        )

    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in selected:
        if row.get("adjudication_status") != "RESOLVED":
            raise CalibrationCandidateError(
                f"{row['observation_id']} is not adjudicated RESOLVED"
            )
        if not row.get("evidence_quote"):
            raise CalibrationCandidateError(
                f"{row['observation_id']} lacks an evidence quote"
            )
        try:
            value = float(row.get("value_numeric", ""))
        except ValueError as exc:
            raise CalibrationCandidateError(
                f"{row['observation_id']} lacks a numeric value"
            ) from exc
        if not math.isfinite(value) or value < 0:
            raise CalibrationCandidateError(
                f"{row['observation_id']} has an invalid multiple: {value}"
            )
        grouped[row["metric_id"]].append(row)

    if set(grouped) != set(METRICS):
        raise CalibrationCandidateError(
            f"source panel metrics differ: {sorted(grouped)}"
        )
    subject_sets: dict[str, set[str]] = {}
    for metric_id, metric_rows in grouped.items():
        names = [row.get("subject_name", "") for row in metric_rows]
        if any(not name for name in names):
            raise CalibrationCandidateError(f"{metric_id} contains a blank fund name")
        repeated = sorted(name for name, count in Counter(names).items() if count > 1)
        if repeated:
            raise CalibrationCandidateError(
                f"{metric_id} repeats fund rows: " + ", ".join(repeated)
            )
        subject_sets[metric_id] = set(names)
    if len({frozenset(names) for names in subject_sets.values()}) != 1:
        raise CalibrationCandidateError("DPI and RVPI fund panels differ")
    fund_count = len(next(iter(subject_sets.values())))
    if expected_fund_count and fund_count != expected_fund_count:
        raise CalibrationCandidateError(
            f"source panel has {fund_count} funds; expected {expected_fund_count}"
        )
    return dict(grouped)


def build_candidates(
    source_rows: Sequence[Mapping[str, str]], expected_fund_count: int = EXPECTED_FUND_COUNT
) -> list[dict[str, str]]:
    """Return four inactive candidate rows with full observation lineage."""

    grouped = _source_panel(source_rows, expected_fund_count)
    candidates: list[dict[str, str]] = []
    for metric_id, short_name in METRICS.items():
        metric_rows = sorted(grouped[metric_id], key=lambda row: row["observation_id"])
        values = [float(row["value_numeric"]) for row in metric_rows]
        formulas = (
            (f"{short_name}_mean", statistics.fmean(values), "ARITHMETIC_MEAN_V1"),
            (f"{short_name}_sd", statistics.stdev(values), "SAMPLE_STANDARD_DEVIATION_V1"),
        )
        for parameter_name, value, formula_id in formulas:
            candidates.append(
                {
                    "parameter_id": (
                        "PARAM_CAL_SRC457_REAL_ESTATE_" + parameter_name.upper()
                    ),
                    "parameter_set_id": PARAMETER_SET_ID,
                    "strategy": "real_estate",
                    "sub_strategy": "",
                    "parameter_name": parameter_name,
                    "value_numeric": _plain_number(value),
                    "value_text": "",
                    "unit": "decimal",
                    "provenance_type": "DERIVED",
                    "source_document_id": SOURCE_DOCUMENT_ID,
                    "source_page": SOURCE_PAGE,
                    "source_anchor": (
                        f"{SOURCE_TABLE} | fund rows | {short_name.upper()} column"
                    ),
                    "formula_id": formula_id,
                    "input_record_ids": "|".join(
                        row["observation_id"] for row in metric_rows
                    ),
                    "assumption_basis": (
                        "Pooled fund rows labelled Core, Opportunistic, or Value Add; "
                        "portfolio totals and Public Real Estate rows excluded. "
                        "The panel comes from one LP schedule, so the statistic is "
                        "retained for audit and excluded from released parameters."
                    ),
                    "adjudication_status": "EXCLUDED_FROM_RELEASE",
                    "active": "false",
                }
            )
    return sorted(candidates, key=lambda row: row["parameter_name"])


def write_candidates(
    input_path: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
    contract_path: Path = DEFAULT_CONTRACT,
    expected_fund_count: int = EXPECTED_FUND_COUNT,
) -> tuple[int, int]:
    rows = _read_rows(input_path)
    candidates = build_candidates(rows, expected_fund_count)
    header = _header(contract_path)
    unexpected = sorted(set().union(*(row.keys() for row in candidates)) - set(header))
    missing = sorted(set(header) - set(candidates[0]))
    if unexpected or missing:
        raise CalibrationCandidateError(
            f"candidate contract differs; missing={missing}, unexpected={unexpected}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(candidates)
    temporary.replace(output_path)
    input_count = len(candidates[0]["input_record_ids"].split("|"))
    return len(candidates), input_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--expected-funds", type=int, default=EXPECTED_FUND_COUNT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        candidate_count, fund_count = write_candidates(
            args.input.resolve(),
            args.output.resolve(),
            args.contract.resolve(),
            args.expected_funds,
        )
    except (CalibrationCandidateError, OSError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(
        f"PASS: {candidate_count} inactive calibration audit rows from "
        f"{fund_count} paired fund observations; output={args.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
