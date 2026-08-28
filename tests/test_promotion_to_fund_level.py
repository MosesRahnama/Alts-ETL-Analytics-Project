"""The promotion from extraction into the fund-level tables, and its gate.

Three things have to hold. Every promoted row names a fund and traces to a
document the gate accepted. Money reaches the analytical grain on one scale, so
a ratio built from two differently scaled cells cannot be a million times wrong.
And the gate refuses a row whose document is missing, which is the property that
makes the promotion evidence worth writing at all.
"""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from src.load import promote_extracted_to_fund_level as promote
from src.load.validate_round02_promotion import (
    PromotionGateError,
    validate_fund_model_extracted_rows,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSV_DIR = PROJECT_ROOT / "data" / "csv"
GATE_DIR = PROJECT_ROOT / "ledgers" / "promotion-gate" / "round02"


def read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


class MoneyScaleTests(unittest.TestCase):
    def test_a_currency_cell_carries_its_scale_into_the_analytical_grain(self) -> None:
        row = {
            "value_numeric": "1586.4", "value_kind": "currency",
            "currency": "USD", "unit_scale_multiplier": "1000000",
        }
        self.assertEqual(promote.scaled_amount(row), "1586400000")

    def test_a_dollar_sign_in_the_heading_still_counts_as_money(self) -> None:
        """A schedule that prints `$` once above the column and bare numbers
        under it yields value_kind `number`, and the currency code is what
        settles it. Reading value_kind alone dropped 213 real amounts."""
        row = {
            "value_numeric": "50000000", "value_kind": "number",
            "currency": "USD", "unit_scale_multiplier": "1",
        }
        self.assertTrue(promote.is_money(row))
        self.assertEqual(promote.period_cell("commitment", row), "50000000")

    def test_a_multiple_never_lands_in_a_money_column(self) -> None:
        """A page printing `1.73` under a paid-in heading is a multiple, and
        placing it in paid_in_capital_itd made one fund's RVPI 18 million."""
        row = {"value_numeric": "1.73", "value_kind": "number", "currency": ""}
        self.assertIsNone(promote.period_cell("paid_in_capital_itd", row))

    def test_a_printed_percent_becomes_a_decimal_rate(self) -> None:
        row = {"value_numeric": "9", "value_kind": "percent", "currency": ""}
        self.assertEqual(promote.period_cell("reported_irr", row), "0.09")


class PromotedTableTests(unittest.TestCase):
    def test_every_observed_fund_has_a_source_master_row(self) -> None:
        observed = {
            row["fund_id"] for row in read(CSV_DIR / "fund_observations.csv")
        }
        mastered = {row["fund_id"] for row in read(CSV_DIR / "fund_master.csv")}
        self.assertEqual(observed - mastered, set())

    def test_every_promoted_row_names_a_fund_and_a_document(self) -> None:
        for name, key in (
            ("fund_observations.csv", "file_id"),
            ("fund_periods.csv", "source_document_id"),
            ("fund_cashflows.csv", "file_id"),
            ("fund_holdings.csv", "source_document_id"),
        ):
            rows = read(CSV_DIR / name)
            self.assertTrue(rows, f"{name} holds no promoted rows")
            for row in rows:
                self.assertTrue(row["fund_id"].startswith("FUND_"), f"{name}: {row}")
                if row["provenance_type"] != "EXTRACTED":
                    self.assertTrue(row.get("synthetic_parameter_set_id"))
                    continue
                self.assertTrue(row[key], f"{name} row without a source document")

    def test_every_period_traces_to_the_observations_it_was_built_from(self) -> None:
        observations = {
            row["observation_id"] for row in read(CSV_DIR / "fund_observations.csv")
        }
        for row in read(CSV_DIR / "fund_periods.csv"):
            if row["provenance_type"] != "EXTRACTED":
                self.assertEqual(
                    row["synthetic_parameter_set_id"], "INTEGRATED_COMPLETION_V1"
                )
                continue
            cited = [part for part in row["input_observation_ids"].split(" | ") if part]
            self.assertTrue(cited, f"period {row['fund_period_id']} cites no observation")
            for observation_id in cited:
                self.assertIn(observation_id, observations)

    def test_manager_observations_resolve_to_the_manager_master(self) -> None:
        known = {row["manager_id"] for row in read(CSV_DIR / "manager_master.csv")}
        for row in read(CSV_DIR / "manager_observations.csv"):
            self.assertIn(row["manager_id"], known)


class GateTests(unittest.TestCase):
    def test_the_accepted_batches_cover_every_promoted_document(self) -> None:
        accepted = set()
        for assignment in GATE_DIR.glob("*/assignment.json"):
            payload = json.loads(assignment.read_text(encoding="utf-8"))
            accepted.update(item["file_id"] for item in payload["files"])
        for name, key in (
            ("fund_observations.csv", "file_id"),
            ("fund_periods.csv", "source_document_id"),
        ):
            for row in read(CSV_DIR / name):
                if row.get("provenance_type") != "EXTRACTED":
                    continue
                self.assertIn(row[key], accepted)

    def test_the_gate_refuses_a_row_whose_document_was_not_accepted(self) -> None:
        """The gate has to bite, or the acceptance evidence proves nothing."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            working = Path(raw) / "promotion-gate"
            shutil.copytree(GATE_DIR.parent, working)
            # Drop a document that actually produced promoted rows; a document
            # whose extraction found nothing eligible would leave the gate with
            # nothing to reject and the test would pass for the wrong reason.
            promoted = {row["file_id"] for row in read(CSV_DIR / "fund_observations.csv")}
            for batch in sorted((working / "round02").glob("*/assignment.json")):
                payload = json.loads(batch.read_text(encoding="utf-8"))
                keep = [item for item in payload["files"] if item["file_id"] not in promoted]
                if len(keep) == len(payload["files"]):
                    continue
                dropped = next(
                    item["file_id"] for item in payload["files"] if item["file_id"] in promoted
                )
                payload["files"] = [
                    item for item in payload["files"] if item["file_id"] != dropped
                ]
                batch.write_text(json.dumps(payload), encoding="utf-8")
                break
            else:
                self.fail("no accepted batch carries a document with promoted rows")
            worksheet = batch.parent / "worksheet.csv"
            kept = [row for row in read(worksheet) if row["file_id"] != dropped]
            with worksheet.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(kept[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows(kept)
            with self.assertRaises(PromotionGateError):
                validate_fund_model_extracted_rows(CSV_DIR, working)


if __name__ == "__main__":
    unittest.main()
