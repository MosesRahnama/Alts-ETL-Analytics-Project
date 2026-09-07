"""Validate Round 02 batch acceptance and block unpromoted extracted facts."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from src.common import matrices

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKING_DIR = PROJECT_ROOT / "ledgers" / "promotion-gate"
DEFAULT_CSV_DIR = PROJECT_ROOT / "data" / "csv"
DEFAULT_PUBLIC_MARKET_AUDIT_DIR = PROJECT_ROOT / "data" / "public_markets" / "audit"
DEFAULT_PUBLIC_MARKET_STAGING_DIR = PROJECT_ROOT / "data" / "public_markets" / "staging"
DEFAULT_BENCHMARK_POLICY = PROJECT_ROOT / "data" / "integrated" / "benchmark-policy.csv"

# Round 01 owns document-to-fund mapping. A Round 02 source fact reaches the
# fund model only from a batch whose worksheet accepted its source document,
# which the batch marker under the working folder records. Parameter rows use
# Round 03 adjudication. Real benchmark histories use the separate
# public-market rights, audit, selection, and promotion path; synthetic
# benchmark histories use Round 03 adjudication. Every decision the gate makes
# is a row in a matrix under data/normalization/transformations.
GATED = "promotion-gated-tables"
SOURCE_FIELD = "table-source-field"
MARKET_STATUSES = "market-promotion-statuses"
RIGHTS_STATUSES = "public-market-rights-status"
USE_POLICY = "benchmark-use-policy"
GATE_ROUTE = "promotion-gate-route"
SOURCE_DECISIONS = "round02-source-decision"
MARKET_KEYS = "public-market-duplicate-policy"
QUALITY_STATUS = "public-market-quality-status"
MISSING_TABLE = "promotion-missing-table-policy"
PREFIX_ROUTING = "source-prefix-gate-routing"
PROVENANCE_SCOPE = "provenance-gate-scope"

# The stage that writes the batch marker. The gate names it when the marker is
# absent, because the marker is written, never authored by hand.
MARKER_WRITER = "stage 080 fund-model-promotion (python -m src.load.promote_extracted_to_fund_level)"


def _split_rule(name: str, question: str) -> set[str]:
    return set(matrices.resolve(name, question).split("|"))


def gated_tables() -> dict[str, tuple[str, str]]:
    return {
        row["input_value"]: (row["output_value"], row["primary_key"])
        for row in matrices.load(GATED)
        if row["output_value"] != "wide_only"
    }


GATED_TABLES = gated_tables()
TABLE_SOURCE_FIELDS = matrices.mapping(SOURCE_FIELD)
PUBLIC_MARKET_PROMOTION_STATUSES = set(matrices.members(MARKET_STATUSES, "promotable"))
PUBLIC_MARKET_RIGHTS_STATUSES = set(matrices.members(RIGHTS_STATUSES, "approved"))
DEMO_PARAMETER_SET_ID = matrices.resolve(USE_POLICY, "demo_parameter_set_id")
DEMO_PROMOTION_STATUS = matrices.resolve(USE_POLICY, "demo_promotion_status")
DEMO_RIGHTS_STATUS = matrices.resolve(USE_POLICY, "demo_rights_status")
DEMO_USE_STATUS = matrices.resolve(USE_POLICY, "demo_use_status")


class PromotionGateError(ValueError):
    """Raised when batch acceptance or fund-model promotion coverage is invalid."""


def _index_rows(
    rows: list[dict[str, str]], key_field: str, repeated_key_policy: str
) -> dict[str, dict[str, str]]:
    if repeated_key_policy != "last_row_wins":
        raise matrices.MatrixError(
            f"{MARKET_KEYS}: unsupported repeated_key policy {repeated_key_policy!r}"
        )
    return {row.get(key_field, ""): row for row in rows}


def _read_dict_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PromotionGateError(f"Missing public-market gate file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise PromotionGateError(f"Missing CSV header: {path}")
        return [dict(row) for row in reader]


def accepted_round02_sources(working_dir: Path) -> set[str]:
    """Return the source IDs every accepted Round 02 batch names.

    The batch marker is the only route into the fund model. A working folder
    without one is refused here and names the stage that writes it, because the
    gate has nothing to read and a gate that reads nothing promotes nothing.
    """

    marker = matrices.resolve(GATE_ROUTE, "lean_marker")
    progress_path = working_dir / Path(marker)
    root = progress_path.parent
    if not progress_path.is_file():
        raise PromotionGateError(
            f"Round 02 batch marker is absent: {progress_path}; {MARKER_WRITER} writes it"
        )
    with progress_path.open("r", encoding="utf-8-sig", newline="") as handle:
        progress_rows = list(csv.DictReader(handle))
    batch_ids = [row.get("batch_id", "").strip() for row in progress_rows]
    if any(not batch_id for batch_id in batch_ids) or len(batch_ids) != len(set(batch_ids)):
        raise PromotionGateError("Round 02 batch marker has blank or duplicate batch IDs")

    accepted_sources: set[str] = set()
    for batch_id in batch_ids:
        batch_root = root / batch_id
        assignment_path = batch_root / "assignment.json"
        worksheet_path = batch_root / "worksheet.csv"
        if not assignment_path.is_file() or not worksheet_path.is_file():
            raise PromotionGateError(f"Accepted Round 02 batch {batch_id} lacks assignment or worksheet")
        try:
            assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise PromotionGateError(f"Invalid Round 02 assignment for {batch_id}: {exc}") from exc
        if assignment.get("batch_id") != batch_id:
            raise PromotionGateError(f"Round 02 assignment batch ID differs for {batch_id}")
        assigned = {
            str(item.get("file_id", "")).strip()
            for item in assignment.get("files", [])
            if str(item.get("file_id", "")).strip()
        }
        if not assigned:
            raise PromotionGateError(f"Round 02 assignment {batch_id} has zero source files")
        with worksheet_path.open("r", encoding="utf-8-sig", newline="") as handle:
            worksheet = list(csv.DictReader(handle))
        accepted_by_file: set[str] = set()
        legal_decisions = _split_rule(SOURCE_DECISIONS, "decisions")
        accepted_decision = matrices.resolve(SOURCE_DECISIONS, "accepted_decision")
        for row in worksheet:
            decision = row.get("decision", "").strip()
            if decision not in legal_decisions:
                raise PromotionGateError(f"Round 02 worksheet {batch_id} has an undecided row")
            file_id = row.get("file_id", "").strip()
            if file_id not in assigned:
                raise PromotionGateError(f"Round 02 worksheet {batch_id} cites an unassigned source")
            if decision == accepted_decision:
                accepted_by_file.add(file_id)
        missing = assigned - accepted_by_file
        if missing:
            raise PromotionGateError(
                f"Round 02 worksheet {batch_id} lacks an accepted outcome for: {', '.join(sorted(missing))}"
            )
        accepted_sources.update(assigned)

    return accepted_sources


def _validate_public_market_benchmarks(
    rows: list[dict[str, str]],
    audit_dir: Path,
    staging_dir: Path,
    benchmark_policy_path: Path = DEFAULT_BENCHMARK_POLICY,
) -> None:
    if not rows:
        return
    inventory_rows = _read_dict_rows(audit_dir / "source_file_inventory.csv")
    decision_rows = _read_dict_rows(staging_dir / "benchmark_master_candidates.csv")
    quality_rows = _read_dict_rows(audit_dir / "quality_results.csv")
    inventory_key = matrices.resolve(MARKET_KEYS, "inventory_key")
    decision_key = matrices.resolve(MARKET_KEYS, "decision_key")
    repeated_key_policy = matrices.resolve(MARKET_KEYS, "repeated_key")
    inventory = _index_rows(inventory_rows, inventory_key, repeated_key_policy)
    decisions = _index_rows(decision_rows, decision_key, repeated_key_policy)
    demo_rows = [
        row
        for row in rows
        if row.get("synthetic_parameter_set_id", "") == DEMO_PARAMETER_SET_ID
    ]
    policies = {
        row.get("benchmark_id", ""): row
        for row in (_read_dict_rows(benchmark_policy_path) if demo_rows else [])
    }
    quality_pass = matrices.resolve(QUALITY_STATUS, "passing_status")
    failed_quality = [
        row.get("check_id", "<blank>")
        for row in quality_rows
        if row.get("status", "").upper() != quality_pass
    ]
    errors: list[str] = []
    if not quality_rows and matrices.resolve(QUALITY_STATUS, "zero_checks") == "refused":
        errors.append("public-market quality audit has zero checks")
    if failed_quality:
        errors.append(
            "public-market quality audit has non-PASS checks: "
            + ", ".join(sorted(failed_quality))
        )
    for row in rows:
        row_id = row.get("benchmark_return_id", "<blank>")
        source_id = row.get("source_document_id", "")
        benchmark_id = row.get("benchmark_id", "")
        source = inventory.get(source_id)
        decision = decisions.get(benchmark_id)
        if source is None:
            errors.append(f"{row_id}: PMKT source {source_id} is absent from audit inventory")
            continue
        is_demo = row.get("synthetic_parameter_set_id", "") == DEMO_PARAMETER_SET_ID
        if is_demo:
            policy = policies.get(benchmark_id)
            anchor = row.get("source_anchor", "")
            if policy is None:
                errors.append(f"{row_id}: demonstration benchmark lacks a policy row")
                continue
            if policy.get("source_file_id", "") != source_id:
                errors.append(f"{row_id}: demonstration policy source_file_id mismatch")
            if policy.get("rights_status", "").upper() != DEMO_RIGHTS_STATUS:
                errors.append(f"{row_id}: demonstration policy rights status is not disclosed")
            if policy.get("use_status", "").upper() != DEMO_USE_STATUS:
                errors.append(f"{row_id}: demonstration policy use status is not disclosed")
            if f"rights_status={DEMO_RIGHTS_STATUS}" not in anchor:
                errors.append(f"{row_id}: row anchor lacks demonstration rights disclosure")
            if f"use_status={DEMO_USE_STATUS}" not in anchor:
                errors.append(f"{row_id}: row anchor lacks demonstration-use disclosure")
            if source.get("promotion_status", "").upper() != DEMO_PROMOTION_STATUS:
                errors.append(f"{row_id}: demonstration source is not recorded as CANDIDATE")
            if source.get("rights_status", "").upper() != DEMO_RIGHTS_STATUS:
                errors.append(f"{row_id}: demonstration source is not restricted to demonstration use")
            if decision is None:
                errors.append(f"{row_id}: benchmark {benchmark_id} lacks a selection decision")
                continue
            if decision.get("source_file_id", "") != source_id:
                errors.append(f"{row_id}: benchmark decision source_file_id mismatch")
            if decision.get("record_status", "").upper() != DEMO_PROMOTION_STATUS:
                errors.append(f"{row_id}: demonstration decision is not recorded as CANDIDATE")
            if decision.get("rights_status", "").upper() != DEMO_RIGHTS_STATUS:
                errors.append(f"{row_id}: demonstration decision is not restricted to demonstration use")
            continue
        if source.get("promotion_status", "").upper() not in PUBLIC_MARKET_PROMOTION_STATUSES:
            errors.append(
                f"{row_id}: PMKT source promotion_status "
                f"{source.get('promotion_status', '')!r} blocks fund-model use"
            )
        if source.get("rights_status", "").upper() not in PUBLIC_MARKET_RIGHTS_STATUSES:
            errors.append(
                f"{row_id}: PMKT source rights_status "
                f"{source.get('rights_status', '')!r} blocks fund-model use"
            )
        if decision is None:
            errors.append(f"{row_id}: benchmark {benchmark_id} lacks a selection decision")
            continue
        if decision.get("source_file_id", "") != source_id:
            errors.append(f"{row_id}: benchmark decision source_file_id mismatch")
        if decision.get("record_status", "").upper() not in PUBLIC_MARKET_PROMOTION_STATUSES:
            errors.append(
                f"{row_id}: benchmark decision record_status "
                f"{decision.get('record_status', '')!r} blocks fund-model use"
            )
        if decision.get("rights_status", "").upper() not in PUBLIC_MARKET_RIGHTS_STATUSES:
            errors.append(
                f"{row_id}: benchmark decision rights_status "
                f"{decision.get('rights_status', '')!r} blocks fund-model use"
            )
    if errors:
        raise PromotionGateError("Public-market benchmark gate failed:\n- " + "\n- ".join(errors))


def validate_fund_model_extracted_rows(
    csv_dir: Path,
    working_dir: Path = DEFAULT_WORKING_DIR,
    public_market_audit_dir: Path = DEFAULT_PUBLIC_MARKET_AUDIT_DIR,
    public_market_staging_dir: Path = DEFAULT_PUBLIC_MARKET_STAGING_DIR,
    benchmark_policy_path: Path = DEFAULT_BENCHMARK_POLICY,
) -> int:
    """Require a valid Round 02 promotion for every extracted analytical row."""
    accepted_sources = accepted_round02_sources(working_dir)
    missing: list[str] = []
    public_market_benchmarks: list[dict[str, str]] = []
    checked = 0
    for table, (filename, primary_key) in GATED_TABLES.items():
        path = csv_dir / filename
        if not path.exists():
            missing_policy = matrices.resolve(MISSING_TABLE, "missing_input")
            if missing_policy == "skipped":
                continue
            raise matrices.MatrixError(
                f"{MISSING_TABLE}: unsupported missing_input policy {missing_policy!r}"
            )
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if table == "benchmark_returns" and row.get(
                    "source_document_id", ""
                ).upper().startswith(matrices.resolve(PREFIX_ROUTING, "public_market_prefix")):
                    public_market_benchmarks.append(row)
                    continue
                if row.get("provenance_type", "").upper() != matrices.resolve(PROVENANCE_SCOPE, "gated_provenance"):
                    continue
                checked += 1
                key = row.get(primary_key, "")
                source_id = row.get(TABLE_SOURCE_FIELDS[table], "")
                if source_id not in accepted_sources:
                    missing.append(f"{table}.{key or '<blank>'}")
    if missing:
        raise PromotionGateError(
            "Fund-model EXTRACTED rows lack valid Round 02 promotion lineage: "
            + ", ".join(sorted(missing))
        )
    _validate_public_market_benchmarks(
        public_market_benchmarks,
        public_market_audit_dir,
        public_market_staging_dir,
        benchmark_policy_path,
    )
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--working-dir", type=Path, default=DEFAULT_WORKING_DIR)
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_CSV_DIR)
    parser.add_argument(
        "--public-market-audit-dir",
        type=Path,
        default=DEFAULT_PUBLIC_MARKET_AUDIT_DIR,
    )
    parser.add_argument(
        "--public-market-staging-dir",
        type=Path,
        default=DEFAULT_PUBLIC_MARKET_STAGING_DIR,
    )
    parser.add_argument(
        "--benchmark-policy",
        type=Path,
        default=DEFAULT_BENCHMARK_POLICY,
    )
    parser.add_argument(
        "--batches-only",
        action="store_true",
        help="validate the accepted batches without checking fund-model CSV coverage",
    )
    args = parser.parse_args()
    try:
        sources = accepted_round02_sources(args.working_dir.resolve())
        checked = len(sources)
        subject = "accepted sources"
        if args.batches_only is False:
            checked = validate_fund_model_extracted_rows(
                args.csv_dir.resolve(),
                args.working_dir.resolve(),
                args.public_market_audit_dir.resolve(),
                args.public_market_staging_dir.resolve(),
                benchmark_policy_path=args.benchmark_policy.resolve(),
            )
            subject = "gated rows"
    except PromotionGateError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: every Round 02 source is accepted; {subject}={checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
