"""Validate Round 02 hash lineage and block unpromoted extracted facts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKING_DIR = PROJECT_ROOT / "ledgers" / "promotion-gate"
DEFAULT_CSV_DIR = PROJECT_ROOT / "data" / "csv"
DEFAULT_PUBLIC_MARKET_AUDIT_DIR = PROJECT_ROOT / "data" / "public_markets" / "audit"
DEFAULT_PUBLIC_MARKET_STAGING_DIR = PROJECT_ROOT / "data" / "public_markets" / "staging"
DEFAULT_BENCHMARK_POLICY = PROJECT_ROOT / "data" / "integrated" / "benchmark-policy.csv"
TEMPLATE_ROOT = PROJECT_ROOT / "ledgers" / "promotion-gate"

# Round 01 owns document-to-fund mapping. Round 02 source facts, including
# fund-master enrichment, require dual-audit Round 02 lineage. Parameter rows
# use Round 03 adjudication. Real benchmark histories use the separate
# public-market rights, audit, selection, and promotion path; synthetic
# benchmark histories use Round 03 adjudication.
GATED_TABLES = {
    "fund_observations": ("fund_observations.csv", "observation_id"),
    "manager_observations": ("manager_observations.csv", "manager_observation_id"),
    "fund_cashflows": ("fund_cashflows.csv", "cashflow_id"),
    "fund_periods": ("fund_periods.csv", "fund_period_id"),
    "fund_terms": ("fund_terms.csv", "fund_term_id"),
    "fund_term_clauses": ("fund_term_clauses.csv", "fund_term_clause_id"),
    "fund_holdings": ("fund_holdings.csv", "holding_id"),
    "benchmark_returns": ("benchmark_returns.csv", "benchmark_return_id"),
}

TABLE_SOURCE_FIELDS = {
    "fund_observations": "file_id",
    "manager_observations": "file_id",
    "fund_cashflows": "file_id",
    "fund_periods": "source_document_id",
    "fund_terms": "source_document_id",
    "fund_term_clauses": "source_document_id",
    "fund_holdings": "source_document_id",
    "benchmark_returns": "source_document_id",
}

WIDE_FUND_MODEL_TABLES = {
    "fund_master",
    "fund_cashflows",
    "fund_periods",
    "fund_terms",
    "fund_holdings",
}

PUBLIC_MARKET_PROMOTION_STATUSES = {"PROMOTED", "CANONICAL"}
PUBLIC_MARKET_RIGHTS_STATUSES = {
    "APPROVED",
    "CLEARED",
    "CANONICAL_USE_APPROVED",
    "APPROVED_FOR_CANONICAL",
}
DEMO_PARAMETER_SET_ID = "PUBLIC_PROXY_DEMONSTRATION_ONLY_V1"
DEMO_PROMOTION_STATUS = "CANDIDATE"
DEMO_RIGHTS_STATUS = "DEMONSTRATION_ONLY"
DEMO_USE_STATUS = "DEMO_PROXY_ONLY"


class PromotionGateError(ValueError):
    """Raised when audit lineage or fund-model promotion coverage is invalid."""


@dataclass(frozen=True)
class CsvRecord:
    row: dict[str, str]
    path: Path
    file_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _template_header(name: str, template_root: Path = TEMPLATE_ROOT) -> list[str]:
    with (template_root / name).open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def _read_records(
    paths: list[Path], template_name: str, template_root: Path = TEMPLATE_ROOT
) -> list[CsvRecord]:
    records: list[CsvRecord] = []
    if not paths:
        return records
    expected_header = _template_header(template_name, template_root)
    for path in sorted(paths):
        digest = _sha256(path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise PromotionGateError(f"Missing CSV header: {path}")
            if reader.fieldnames != expected_header:
                raise PromotionGateError(f"Header differs from {template_name}: {path}")
            records.extend(CsvRecord(dict(row), path, digest) for row in reader)
    return records


def _unique_index(records: list[CsvRecord], key: str) -> dict[str, CsvRecord]:
    result: dict[str, CsvRecord] = {}
    for record in records:
        value = record.row.get(key, "")
        if not value:
            raise PromotionGateError(f"Blank {key}: {record.path}")
        if value in result:
            raise PromotionGateError(f"Duplicate {key}={value}: {record.path}")
        result[value] = record
    return result


def _integer(row: dict[str, str], field: str, errors: list[str], row_id: str) -> int:
    try:
        return int(row[field])
    except (KeyError, TypeError, ValueError):
        errors.append(f"{row_id}: invalid integer {field}={row.get(field)!r}")
        return -1


def validate_round02_lineage(
    working_dir: Path, template_root: Path = TEMPLATE_ROOT
) -> set[tuple[str, str]]:
    """Return promoted fund-model keys after validating every completed batch."""
    promotion_paths = list(working_dir.glob("round-02-*-audit-adjudicated.csv"))
    promotion_records = _read_records(
        promotion_paths, "audit_adjudication_template.csv", template_root
    )
    if not promotion_records:
        return set()

    adjudication_paths = [
        path
        for path in working_dir.glob("round-02-*-adjudicated.csv")
        if not path.name.endswith("-audit-adjudicated.csv")
    ]
    audit_paths = list(working_dir.glob("round-02-*-audit-dates.csv"))
    audit_paths.extend(working_dir.glob("round-02-*-audit-schema.csv"))

    promotions = _unique_index(promotion_records, "audit_adjudication_id")
    adjudications = _unique_index(
        _read_records(adjudication_paths, "adjudication_template.csv", template_root),
        "adjudication_id",
    )
    audit_records = _read_records(audit_paths, "audit_template.csv", template_root)
    audits = _unique_index(audit_records, "audit_id")
    errors: list[str] = []
    promoted: set[tuple[str, str]] = set()
    decided_adjudications: set[str] = set()
    completed_batches: set[tuple[str, str, str]] = set()

    for promotion in promotions.values():
        row = promotion.row
        promotion_id = row["audit_adjudication_id"]
        adjudication = adjudications.get(row.get("adjudication_id", ""))
        dates_audit = audits.get(row.get("dates_audit_id", ""))
        schema_audit = audits.get(row.get("schema_audit_id", ""))
        if adjudication is None:
            errors.append(f"{promotion_id}: missing adjudication")
            continue
        if dates_audit is None or schema_audit is None:
            errors.append(f"{promotion_id}: missing one or both summary audits")
            continue

        decided_adjudications.add(adjudication.row["adjudication_id"])
        scope = (row["round_id"], row["module_id"], row["batch_id"])
        completed_batches.add(scope)
        if row.get("dates_audit_id") == row.get("schema_audit_id"):
            errors.append(f"{promotion_id}: dates audit ID duplicates the schema audit ID")
        decision_status = {
            "PROMOTE": "PROMOTED",
            "CLOSE_NO_CANONICAL_ROW": "CLOSED_NO_CANONICAL_ROW",
            "RETURN_FOR_READJUDICATION": "RETURNED_FOR_READJUDICATION",
            "BLOCK": "BLOCKED",
        }
        if decision_status.get(row.get("final_decision", "")) != row.get("promotion_status"):
            errors.append(f"{promotion_id}: final decision and status disagree")

        expected_scope = {
            "round_id": row["round_id"],
            "module_id": row["module_id"],
            "batch_id": row["batch_id"],
            "file_id": row["file_id"],
        }
        for label, record in (
            ("adjudication", adjudication),
            ("dates audit", dates_audit),
            ("schema audit", schema_audit),
        ):
            for field, expected in expected_scope.items():
                if record.row.get(field) != expected:
                    errors.append(f"{promotion_id}: {label} {field} mismatch")

        if adjudication.file_sha256.lower() != row.get("staging_sha256", "").lower():
            errors.append(f"{promotion_id}: staged-file SHA-256 mismatch")
        if dates_audit.file_sha256.lower() != row.get("dates_audit_file_sha256", "").lower():
            errors.append(f"{promotion_id}: dates-audit-file SHA-256 mismatch")
        if schema_audit.file_sha256.lower() != row.get("schema_audit_file_sha256", "").lower():
            errors.append(f"{promotion_id}: schema-audit-file SHA-256 mismatch")

        for label, record, family, result_field in (
            ("dates", dates_audit, "dates_provenance", "dates_result"),
            ("schema", schema_audit, "schema_grain_math", "schema_result"),
        ):
            audit = record.row
            if audit.get("audit_family") != family:
                errors.append(f"{promotion_id}: {label} audit family mismatch")
            if audit.get("check_family") != "ROW_SUMMARY" or audit.get("check_id") != "SUMMARY":
                errors.append(f"{promotion_id}: {label} audit lacks the ROW_SUMMARY SUMMARY check identity")
            if audit.get("adjudication_id") != adjudication.row["adjudication_id"]:
                errors.append(f"{promotion_id}: {label} adjudication mismatch")
            if audit.get("staging_sha256", "").lower() != adjudication.file_sha256.lower():
                errors.append(f"{promotion_id}: {label} staging hash mismatch")
            if audit.get("source_sha256", "").lower() != adjudication.row.get("source_sha256", "").lower():
                errors.append(f"{promotion_id}: {label} source hash mismatch")
            if audit.get("result") != row.get(result_field):
                errors.append(f"{promotion_id}: {label} result mismatch")

        children = [
            record.row
            for record in audit_records
            if record.row.get("adjudication_id") == adjudication.row["adjudication_id"]
            and record.row.get("check_family") != "ROW_SUMMARY"
        ]
        for summary, family in (
            (dates_audit.row, "dates_provenance"),
            (schema_audit.row, "schema_grain_math"),
        ):
            family_children = [
                child for child in children if child.get("audit_family") == family
            ]
            if summary.get("result") not in {"PASS", "NOT_APPLICABLE"} and not family_children:
                errors.append(
                    f"{promotion_id}: {family} summary with a FAIL or UNRESOLVED result lacks a finding row"
                )
        derived_counts = {
            "error_count": sum(child.get("severity") == "ERROR" for child in children),
            "unresolved_count": sum(child.get("result") == "UNRESOLVED" for child in children),
            "warning_count": sum(child.get("severity") == "WARNING" for child in children),
        }
        for field, expected in derived_counts.items():
            if _integer(row, field, errors, promotion_id) != expected:
                errors.append(f"{promotion_id}: {field} disagrees with the audit findings")

        terminal = row.get("promotion_status") in {"PROMOTED", "CLOSED_NO_CANONICAL_ROW"}
        if terminal and adjudication.row.get("audit_ready_status") != "READY_FOR_BOTH_AUDITS":
            errors.append(f"{promotion_id}: adjudication lacks READY_FOR_BOTH_AUDITS")
        if terminal:
            for field in ("dates_coverage_pct", "schema_coverage_pct"):
                if row.get(field) not in {"100", "100.0", "100.00"}:
                    errors.append(f"{promotion_id}: {field} differs from 100")
            if any(
                _integer(row, field, errors, promotion_id) != 0
                for field in ("error_count", "unresolved_count", "warning_count", "waived_warning_count")
            ):
                errors.append(f"{promotion_id}: terminal decision has blocking findings")
            if row.get("waiver_id"):
                errors.append(f"{promotion_id}: Round 02 warning waivers are disabled")

        if row.get("promotion_status") == "PROMOTED":
            if row.get("dates_result") != "PASS" or row.get("schema_result") != "PASS":
                errors.append(f"{promotion_id}: promoted row lacks two PASS summaries")
            if row.get("quality_gate_result") not in {"PASS", "NOT_APPLICABLE"}:
                errors.append(f"{promotion_id}: quality gate result falls outside PASS and NOT_APPLICABLE")
            if row.get("key_gate_result") != "PASS" or row.get("duplicate_gate_result") != "PASS":
                errors.append(f"{promotion_id}: key gate or duplicate gate result differs from PASS")
            promotion_key = (row.get("canonical_table", ""), row.get("canonical_row_id", ""))
            if not all(promotion_key):
                errors.append(f"{promotion_id}: promoted row lacks fund-model key")
            elif (
                promotion_key in promoted
                and promotion_key[0] not in WIDE_FUND_MODEL_TABLES
            ):
                errors.append(f"{promotion_id}: duplicate fund-model promotion {promotion_key}")
            else:
                promoted.add(promotion_key)
        elif row.get("promotion_status") == "CLOSED_NO_CANONICAL_ROW":
            if row.get("canonical_row_id"):
                errors.append(f"{promotion_id}: CLOSED_NO_CANONICAL_ROW carries a fund-model row ID")

    for adjudication in adjudications.values():
        row = adjudication.row
        if (row["round_id"], row["module_id"], row["batch_id"]) in completed_batches:
            if row["adjudication_id"] not in decided_adjudications:
                errors.append(f"{row['adjudication_id']}: completed batch lacks final decision")

    if errors:
        raise PromotionGateError("Round 02 promotion gate failed:\n- " + "\n- ".join(errors))
    return promoted


def _read_dict_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PromotionGateError(f"Missing public-market gate file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise PromotionGateError(f"Missing CSV header: {path}")
        return [dict(row) for row in reader]


def _lean_round02_sources(working_dir: Path) -> set[str] | None:
    """Return source IDs from accepted lean batches, or None for the legacy route."""

    root = working_dir / "round02"
    progress_path = root / "progress.csv"
    if not progress_path.is_file():
        return None
    with progress_path.open("r", encoding="utf-8-sig", newline="") as handle:
        progress_rows = list(csv.DictReader(handle))
    batch_ids = [row.get("batch_id", "").strip() for row in progress_rows]
    if any(not batch_id for batch_id in batch_ids) or len(batch_ids) != len(set(batch_ids)):
        raise PromotionGateError("Lean Round 02 progress has blank or duplicate batch IDs")

    accepted_sources: set[str] = set()
    for batch_id in batch_ids:
        batch_root = root / batch_id
        assignment_path = batch_root / "assignment.json"
        worksheet_path = batch_root / "worksheet.csv"
        if not assignment_path.is_file() or not worksheet_path.is_file():
            raise PromotionGateError(f"Accepted lean batch {batch_id} lacks assignment or worksheet")
        try:
            assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise PromotionGateError(f"Invalid lean assignment for {batch_id}: {exc}") from exc
        if assignment.get("batch_id") != batch_id:
            raise PromotionGateError(f"Lean assignment batch ID differs for {batch_id}")
        assigned = {
            str(item.get("file_id", "")).strip()
            for item in assignment.get("files", [])
            if str(item.get("file_id", "")).strip()
        }
        if not assigned:
            raise PromotionGateError(f"Lean assignment {batch_id} has zero source files")
        with worksheet_path.open("r", encoding="utf-8-sig", newline="") as handle:
            worksheet = list(csv.DictReader(handle))
        accepted_by_file: set[str] = set()
        for row in worksheet:
            decision = row.get("decision", "").strip()
            if decision not in {"ACCEPT", "REJECT"}:
                raise PromotionGateError(f"Lean worksheet {batch_id} has an undecided row")
            file_id = row.get("file_id", "").strip()
            if file_id not in assigned:
                raise PromotionGateError(f"Lean worksheet {batch_id} cites an unassigned source")
            if decision == "ACCEPT":
                accepted_by_file.add(file_id)
        missing = assigned - accepted_by_file
        if missing:
            raise PromotionGateError(
                f"Lean worksheet {batch_id} lacks an accepted outcome for: {', '.join(sorted(missing))}"
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
    inventory = {row.get("file_id", ""): row for row in inventory_rows}
    decisions = {row.get("benchmark_id", ""): row for row in decision_rows}
    demo_rows = [
        row
        for row in rows
        if row.get("synthetic_parameter_set_id", "") == DEMO_PARAMETER_SET_ID
    ]
    policies = {
        row.get("benchmark_id", ""): row
        for row in (_read_dict_rows(benchmark_policy_path) if demo_rows else [])
    }
    failed_quality = [
        row.get("check_id", "<blank>")
        for row in quality_rows
        if row.get("status", "").upper() != "PASS"
    ]
    errors: list[str] = []
    if not quality_rows:
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
    template_root: Path = TEMPLATE_ROOT,
    benchmark_policy_path: Path = DEFAULT_BENCHMARK_POLICY,
) -> int:
    """Require a valid Round 02 promotion for every extracted analytical row."""
    lean_sources = _lean_round02_sources(working_dir)
    promoted = set() if lean_sources is not None else validate_round02_lineage(
        working_dir, template_root
    )
    missing: list[str] = []
    public_market_benchmarks: list[dict[str, str]] = []
    checked = 0
    for table, (filename, primary_key) in GATED_TABLES.items():
        path = csv_dir / filename
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if table == "benchmark_returns" and row.get(
                    "source_document_id", ""
                ).upper().startswith("PMKT_"):
                    public_market_benchmarks.append(row)
                    continue
                if row.get("provenance_type", "").upper() != "EXTRACTED":
                    continue
                checked += 1
                key = row.get(primary_key, "")
                if lean_sources is not None:
                    source_id = row.get(TABLE_SOURCE_FIELDS[table], "")
                    if source_id not in lean_sources:
                        missing.append(f"{table}.{key or '<blank>'}")
                elif (table, key) not in promoted:
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
        "--lineage-only",
        action="store_true",
        help="validate working-file lineage without checking fund-model CSV coverage",
    )
    args = parser.parse_args()
    try:
        promoted = validate_round02_lineage(args.working_dir.resolve())
        checked = len(promoted)
        if args.lineage_only is False:
            checked = validate_fund_model_extracted_rows(
                args.csv_dir.resolve(),
                args.working_dir.resolve(),
                args.public_market_audit_dir.resolve(),
                args.public_market_staging_dir.resolve(),
                benchmark_policy_path=args.benchmark_policy.resolve(),
            )
    except PromotionGateError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: Round 02 promotion lineage is valid; promoted rows={checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
