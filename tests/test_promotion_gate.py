from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.load.load_csv_to_duckdb import load
from src.load.validate_round02_promotion import (
    GATED_TABLES,
    PromotionGateError,
    validate_fund_model_extracted_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def template_header(name: str) -> list[str]:
    with (PROJECT_ROOT / "ledgers" / "promotion-gate" / name).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        return next(csv.reader(handle))


def fund_model_header(name: str) -> list[str]:
    with (PROJECT_ROOT / "data" / "csv" / name).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        return next(csv.reader(handle))


def write_rows(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in header})


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PromotionGateTests(unittest.TestCase):
    def test_separately_owned_tables_are_outside_round_02_gate(self) -> None:
        self.assertNotIn("synthetic_parameters", GATED_TABLES)
        self.assertNotIn("fund_master", GATED_TABLES)
        self.assertIn("benchmark_returns", GATED_TABLES)

    def test_src_benchmark_requires_round_02_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            working.mkdir()
            fund_model.mkdir()
            write_rows(
                fund_model / "benchmark_returns.csv",
                fund_model_header("benchmark_returns.csv"),
                [
                    {
                        "benchmark_return_id": "BENCH_SRC_001",
                        "benchmark_id": "BENCH_REPORTED",
                        "return_date": "2025-12-31",
                        "return_value": "0.10",
                        "provenance_type": "EXTRACTED",
                        "source_document_id": "SRC001",
                        "record_status": "PROMOTED",
                    }
                ],
            )
            with self.assertRaisesRegex(PromotionGateError, "benchmark_returns.BENCH_SRC_001"):
                validate_fund_model_extracted_rows(fund_model, working)

    def test_pmkt_benchmark_uses_separate_rights_and_promotion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            audit = root / "audit"
            staging = root / "staging"
            for folder in (working, fund_model, audit, staging):
                folder.mkdir()
            write_rows(
                fund_model / "benchmark_returns.csv",
                fund_model_header("benchmark_returns.csv"),
                [
                    {
                        "benchmark_return_id": "BENCH_PMKT_001",
                        "benchmark_id": "BMK_ETF_SPY",
                        "return_date": "2025-12-31",
                        "return_value": "0.10",
                        "provenance_type": "EXTRACTED",
                        "source_document_id": "PMKT_SOURCE_001",
                        "record_status": "PROMOTED",
                    }
                ],
            )
            inventory_header = ["file_id", "promotion_status", "rights_status"]
            decision_header = [
                "benchmark_id",
                "source_file_id",
                "rights_status",
                "record_status",
            ]
            write_rows(
                audit / "source_file_inventory.csv",
                inventory_header,
                [
                    {
                        "file_id": "PMKT_SOURCE_001",
                        "promotion_status": "CANDIDATE",
                        "rights_status": "REVIEW_REQUIRED",
                    }
                ],
            )
            write_rows(
                staging / "benchmark_master_candidates.csv",
                decision_header,
                [
                    {
                        "benchmark_id": "BMK_ETF_SPY",
                        "source_file_id": "PMKT_SOURCE_001",
                        "rights_status": "REVIEW_REQUIRED",
                        "record_status": "CANDIDATE",
                    }
                ],
            )
            write_rows(
                audit / "quality_results.csv",
                ["check_id", "status"],
                [{"check_id": "PMQ01", "status": "PASS"}],
            )
            with self.assertRaisesRegex(PromotionGateError, "Public-market benchmark gate"):
                validate_fund_model_extracted_rows(fund_model, working, audit, staging)

            write_rows(
                audit / "source_file_inventory.csv",
                inventory_header,
                [
                    {
                        "file_id": "PMKT_SOURCE_001",
                        "promotion_status": "PROMOTED",
                        "rights_status": "APPROVED_FOR_CANONICAL",
                    }
                ],
            )
            write_rows(
                staging / "benchmark_master_candidates.csv",
                decision_header,
                [
                    {
                        "benchmark_id": "BMK_ETF_SPY",
                        "source_file_id": "PMKT_SOURCE_001",
                        "rights_status": "APPROVED_FOR_CANONICAL",
                        "record_status": "PROMOTED",
                    }
                ],
            )
            validate_fund_model_extracted_rows(fund_model, working, audit, staging)

    def test_derived_demo_benchmark_requires_complete_rights_disclosure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            audit = root / "audit"
            staging = root / "staging"
            policy = root / "benchmark-policy.csv"
            for folder in (working, fund_model, audit, staging):
                folder.mkdir()
            write_rows(
                fund_model / "benchmark_returns.csv",
                fund_model_header("benchmark_returns.csv"),
                [
                    {
                        "benchmark_return_id": "BENCH_PMKT_DEMO",
                        "benchmark_id": "BMK_ETF_SPY",
                        "return_date": "2025-12-31",
                        "return_value": "0.10",
                        "provenance_type": "DERIVED",
                        "source_document_id": "PMKT_SOURCE_001",
                        "source_anchor": "rights_status=DEMONSTRATION_ONLY; use_status=DEMO_PROXY_ONLY",
                        "synthetic_parameter_set_id": "PUBLIC_PROXY_DEMONSTRATION_ONLY_V1",
                        "record_status": "ACTIVE",
                    }
                ],
            )
            write_rows(
                audit / "source_file_inventory.csv",
                ["file_id", "promotion_status", "rights_status"],
                [
                    {
                        "file_id": "PMKT_SOURCE_001",
                        "promotion_status": "CANDIDATE",
                        "rights_status": "DEMONSTRATION_ONLY",
                    }
                ],
            )
            write_rows(
                staging / "benchmark_master_candidates.csv",
                ["benchmark_id", "source_file_id", "rights_status", "record_status"],
                [
                    {
                        "benchmark_id": "BMK_ETF_SPY",
                        "source_file_id": "PMKT_SOURCE_001",
                        "rights_status": "DEMONSTRATION_ONLY",
                        "record_status": "CANDIDATE",
                    }
                ],
            )
            write_rows(
                audit / "quality_results.csv",
                ["check_id", "status"],
                [{"check_id": "PMQ01", "status": "PASS"}],
            )
            policy_header = ["benchmark_id", "source_file_id", "rights_status", "use_status"]
            policy_row = {
                "benchmark_id": "BMK_ETF_SPY",
                "source_file_id": "PMKT_SOURCE_001",
                "rights_status": "DEMONSTRATION_ONLY",
                "use_status": "DEMO_PROXY_ONLY",
            }
            write_rows(policy, policy_header, [policy_row])
            self.assertEqual(
                validate_fund_model_extracted_rows(
                    fund_model,
                    working,
                    audit,
                    staging,
                    benchmark_policy_path=policy,
                ),
                0,
            )
            write_rows(policy, policy_header, [{**policy_row, "use_status": ""}])
            with self.assertRaisesRegex(PromotionGateError, "use status is not disclosed"):
                validate_fund_model_extracted_rows(
                    fund_model,
                    working,
                    audit,
                    staging,
                    benchmark_policy_path=policy,
                )

    def test_valid_hash_linked_dual_audit_promotion_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            working.mkdir()
            fund_model.mkdir()
            prefix = "round-02-02a-performance-02A-PERF-001"
            source_hash = "b" * 64

            staging_path = working / f"{prefix}-adjudicated.csv"
            staging_row = {
                "round_id": "02",
                "module_id": "02A",
                "batch_id": "02A-PERF-001",
                "adjudication_id": "ADJ001",
                "file_id": "SRC021",
                "source_sha256": source_hash,
                "doc_type": "Performance",
                "canonical_table": "fund_observations",
                "record_kind": "OBSERVATION",
                "canonical_row_key": "OBS001",
                "agreement_class": "EXACT",
                "canonical_fund_id": "FUND_REAL_001",
                "date_role": "as_of",
                "date_raw": "2025-12-31",
                "date_precision": "day",
                "as_of_date": "2025-12-31",
                "metric_id": "perf.tvpi",
                "canonical_value_raw": "1.50x",
                "canonical_value_numeric": "1.5",
                "unit": "ratio_x",
                "perspective": "lp_position",
                "measure_basis": "ratio",
                "source_page": "1",
                "pdf_page_number": "1",
                "source_anchor": "table 1 row 1",
                "provenance_type": "EXTRACTED",
                "extraction_method": "manual",
                "extractor_version": "TEST",
                "extracted_at": "2026-08-02 00:00:00",
                "decision": "ACCEPT_EXACT",
                "status": "ADJUDICATED_COMPLETE",
                "audit_ready_status": "READY_FOR_BOTH_AUDITS",
            }
            write_rows(
                staging_path,
                template_header("adjudication_template.csv"),
                [staging_row],
            )
            staging_hash = digest(staging_path)

            def audit_row(audit_id: str, agent: str, family: str) -> dict[str, str]:
                return {
                    "round_id": "02",
                    "module_id": "02A",
                    "batch_id": "02A-PERF-001",
                    "audit_agent_id": agent,
                    "audit_family": family,
                    "audit_id": audit_id,
                    "staging_sha256": staging_hash,
                    "adjudication_id": "ADJ001",
                    "file_id": "SRC021",
                    "source_sha256": source_hash,
                    "doc_type": "Performance",
                    "canonical_table": "fund_observations",
                    "canonical_row_key": "OBS001",
                    "check_family": "ROW_SUMMARY",
                    "check_id": "SUMMARY",
                    "severity": "INFO",
                    "result": "PASS",
                }

            dates_path = working / f"{prefix}-audit-dates.csv"
            schema_path = working / f"{prefix}-audit-schema.csv"
            write_rows(
                dates_path,
                template_header("audit_template.csv"),
                [audit_row("AUD_DATES", "DATES_AGENT", "dates_provenance")],
            )
            write_rows(
                schema_path,
                template_header("audit_template.csv"),
                [audit_row("AUD_SCHEMA", "SCHEMA_AGENT", "schema_grain_math")],
            )

            promotion_path = working / f"{prefix}-audit-adjudicated.csv"
            promotion_row = {
                "round_id": "02",
                "module_id": "02A",
                "batch_id": "02A-PERF-001",
                "audit_adjudication_id": "PROMO001",
                "staging_sha256": staging_hash,
                "dates_audit_file_sha256": digest(dates_path),
                "schema_audit_file_sha256": digest(schema_path),
                "adjudication_id": "ADJ001",
                "file_id": "SRC021",
                "dates_audit_id": "AUD_DATES",
                "schema_audit_id": "AUD_SCHEMA",
                "dates_result": "PASS",
                "schema_result": "PASS",
                "dates_coverage_pct": "100",
                "schema_coverage_pct": "100",
                "error_count": "0",
                "unresolved_count": "0",
                "warning_count": "0",
                "waived_warning_count": "0",
                "quality_gate_result": "PASS",
                "key_gate_result": "PASS",
                "duplicate_gate_result": "PASS",
                "final_decision": "PROMOTE",
                "canonical_table": "fund_observations",
                "canonical_row_id": "OBS001",
                "promotion_status": "PROMOTED",
                "promotion_run_id": "RUN001",
            }
            write_rows(
                promotion_path,
                template_header("audit_adjudication_template.csv"),
                [promotion_row],
            )

            observation = {
                "observation_id": "OBS001",
                "fund_id": "FUND_REAL_001",
                "file_id": "SRC021",
                "metric_id": "perf.tvpi",
                "perspective": "lp_position",
                "measure_basis": "ratio",
                "provenance_type": "EXTRACTED",
                "record_status": "PROMOTED",
            }
            write_rows(
                fund_model / "fund_observations.csv",
                fund_model_header("fund_observations.csv"),
                [observation],
            )
            validate_fund_model_extracted_rows(fund_model, working)

            wrong_schema = audit_row("AUD_SCHEMA", "SCHEMA_AGENT", "dates_provenance")
            write_rows(
                schema_path,
                template_header("audit_template.csv"),
                [wrong_schema],
            )
            promotion_row["schema_audit_file_sha256"] = digest(schema_path)
            write_rows(
                promotion_path,
                template_header("audit_adjudication_template.csv"),
                [promotion_row],
            )
            with self.assertRaises(PromotionGateError):
                validate_fund_model_extracted_rows(fund_model, working)
            existing_database = root / "existing.duckdb"
            existing_database.write_text("preserve me", encoding="utf-8")
            with self.assertRaises(PromotionGateError):
                load(
                    fund_model,
                    existing_database,
                    rebuild=True,
                    working_dir=working,
                )
            self.assertEqual(
                existing_database.read_text(encoding="utf-8"),
                "preserve me",
            )

    def test_unpromoted_extracted_row_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            working.mkdir()
            fund_model.mkdir()
            write_rows(
                fund_model / "fund_observations.csv",
                fund_model_header("fund_observations.csv"),
                [
                    {
                        "observation_id": "OBS_UNPROMOTED",
                        "fund_id": "FUND_REAL_001",
                        "metric_id": "perf.tvpi",
                        "perspective": "lp_position",
                        "measure_basis": "ratio",
                        "provenance_type": "EXTRACTED",
                        "record_status": "PENDING",
                    }
                ],
            )
            with self.assertRaises(PromotionGateError):
                validate_fund_model_extracted_rows(fund_model, working)

    def test_round01_identity_rows_are_outside_round02_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            working.mkdir()
            fund_model.mkdir()
            write_rows(
                fund_model / "fund_master.csv",
                fund_model_header("fund_master.csv"),
                [
                    {
                        "fund_id": "FUND_REAL_UNPROMOTED",
                        "fund_name": "Unpromoted Fund",
                        "fund_manager_name": "Unpromoted Manager",
                        "strategy": "buyout",
                        "provenance_type": "EXTRACTED",
                        "record_status": "PENDING",
                    }
                ],
            )
            validate_fund_model_extracted_rows(fund_model, working)

    def test_lean_progress_gates_extracted_rows_by_accepted_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            batch = working / "round02" / "02A-PERF-001"
            batch.mkdir(parents=True)
            fund_model.mkdir()
            write_rows(
                working / "round02" / "progress.csv",
                ["batch_id", "accepted_at", "observations", "periods", "cashflows", "terms", "no_data_files"],
                [{"batch_id": "02A-PERF-001"}],
            )
            (batch / "assignment.json").write_text(
                json.dumps(
                    {
                        "batch_id": "02A-PERF-001",
                        "files": [{"file_id": "SRC001"}],
                    }
                ),
                encoding="utf-8",
            )
            write_rows(
                batch / "worksheet.csv",
                ["file_id", "decision"],
                [{"file_id": "SRC001", "decision": "ACCEPT"}],
            )
            observation = {
                "observation_id": "OBS001",
                "fund_id": "FUND_0001",
                "file_id": "SRC001",
                "metric_id": "perf.tvpi",
                "perspective": "fund_total",
                "measure_basis": "ratio",
                "provenance_type": "EXTRACTED",
                "record_status": "ACTIVE",
            }
            write_rows(
                fund_model / "fund_observations.csv",
                fund_model_header("fund_observations.csv"),
                [observation],
            )
            validate_fund_model_extracted_rows(fund_model, working)
            observation["file_id"] = "SRC002"
            write_rows(
                fund_model / "fund_observations.csv",
                fund_model_header("fund_observations.csv"),
                [observation],
            )
            with self.assertRaises(PromotionGateError):
                validate_fund_model_extracted_rows(fund_model, working)


if __name__ == "__main__":
    unittest.main()
