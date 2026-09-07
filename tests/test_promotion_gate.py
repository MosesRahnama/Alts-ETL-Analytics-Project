from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.load import validate_round02_promotion
from src.load.load_csv_to_duckdb import load
from src.load.validate_round02_promotion import (
    GATED_TABLES,
    PromotionGateError,
    validate_fund_model_extracted_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def write_marker(working: Path, batches: dict[str, list[str]] | None = None) -> None:
    """Write the batch marker the promotion stage writes, one row per batch.

    Each batch gets the assignment and the worksheet the gate reads, with every
    assigned source accepted. A marker with no batch accepts no source, which is
    what a working folder looks like before the first batch closes.
    """

    root = working / "round02"
    root.mkdir(parents=True, exist_ok=True)
    batches = batches or {}
    write_rows(
        root / "progress.csv",
        ["batch_id", "accepted_at", "observations", "periods", "cashflows", "terms", "no_data_files"],
        [{"batch_id": batch_id} for batch_id in batches],
    )
    for batch_id, file_ids in batches.items():
        batch = root / batch_id
        batch.mkdir(parents=True, exist_ok=True)
        (batch / "assignment.json").write_text(
            json.dumps({"batch_id": batch_id, "files": [{"file_id": file_id} for file_id in file_ids]}),
            encoding="utf-8",
        )
        write_rows(
            batch / "worksheet.csv",
            ["file_id", "decision"],
            [{"file_id": file_id, "decision": "ACCEPT"} for file_id in file_ids],
        )


class PromotionGateTests(unittest.TestCase):
    def test_separately_owned_tables_are_outside_round_02_gate(self) -> None:
        self.assertNotIn("synthetic_parameters", GATED_TABLES)
        self.assertNotIn("fund_master", GATED_TABLES)
        self.assertIn("benchmark_returns", GATED_TABLES)

    def test_a_missing_batch_marker_names_the_stage_that_writes_it(self) -> None:
        """The gate has one route. A working folder with no marker is refused
        with the writer named, never answered from a second reader that finds
        no promotion and refuses every row for a reason the message hides."""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            working.mkdir()
            fund_model.mkdir()
            with self.assertRaises(PromotionGateError) as raised:
                validate_fund_model_extracted_rows(fund_model, working)
            message = str(raised.exception)
            self.assertIn("batch marker is absent", message)
            self.assertIn("progress.csv", message)
            self.assertIn("promote_extracted_to_fund_level", message)

    def test_the_retired_lineage_readers_are_gone(self) -> None:
        for name in (
            "validate_round02_lineage",
            "TEMPLATE_ROOT",
            "WIDE_FUND_MODEL_TABLES",
            "wide_tables",
        ):
            self.assertFalse(
                hasattr(validate_round02_promotion, name),
                f"{name} survives the retirement of the round-02 lineage branch",
            )

    def test_src_benchmark_requires_round_02_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            working.mkdir()
            fund_model.mkdir()
            write_marker(working, {"02A-PERF-001": ["SRC999"]})
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
            write_marker(working)
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
            write_marker(working)
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

    def test_a_refused_row_leaves_an_existing_database_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            working.mkdir()
            fund_model.mkdir()
            write_marker(working, {"02A-PERF-001": ["SRC021"]})
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
            self.assertEqual(validate_fund_model_extracted_rows(fund_model, working), 1)

            observation["file_id"] = "SRC404"
            write_rows(
                fund_model / "fund_observations.csv",
                fund_model_header("fund_observations.csv"),
                [observation],
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

    def test_unaccepted_extracted_row_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            working.mkdir()
            fund_model.mkdir()
            write_marker(working)
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
            with self.assertRaisesRegex(PromotionGateError, "fund_observations.OBS_UNPROMOTED"):
                validate_fund_model_extracted_rows(fund_model, working)

    def test_round01_identity_rows_are_outside_round02_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            working.mkdir()
            fund_model.mkdir()
            write_marker(working)
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

    def test_accepted_batches_gate_extracted_rows_by_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            fund_model = root / "csv"
            working.mkdir()
            fund_model.mkdir()
            write_marker(working, {"02A-PERF-001": ["SRC001"]})
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
