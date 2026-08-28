from __future__ import annotations

import csv
import math
import tempfile
import unittest
from pathlib import Path

from src.pipeline.build_calibration_candidates import (
    CalibrationCandidateError,
    build_candidates,
    write_candidates,
)


HEADER = [
    "parameter_id",
    "parameter_set_id",
    "strategy",
    "sub_strategy",
    "parameter_name",
    "value_numeric",
    "value_text",
    "unit",
    "provenance_type",
    "source_document_id",
    "source_page",
    "source_anchor",
    "formula_id",
    "input_record_ids",
    "assumption_basis",
    "adjudication_status",
    "active",
]


def fact(observation_id: str, fund: str, metric: str, value: float) -> dict[str, str]:
    return {
        "observation_id": observation_id,
        "document_id": "SRC457",
        "source_page": "9",
        "source_table": "Investment Detail",
        "subject_type": "fund",
        "subject_name": fund,
        "strategy": "Value Add",
        "metric_id": f"fund_economics_observation.{metric}",
        "value_numeric": str(value),
        "evidence_quote": f"{fund} {metric.upper()} {value}",
        "adjudication_status": "RESOLVED",
    }


class CalibrationCandidateTests(unittest.TestCase):
    def test_builds_four_inactive_source_backed_statistics(self) -> None:
        rows = [
            fact("D1", "Fund One, L.P.", "dpi", 1.0),
            fact("R1", "Fund One, L.P.", "rvpi", 0.2),
            fact("D2", "Fund Two, L.P.", "dpi", 1.4),
            fact("R2", "Fund Two, L.P.", "rvpi", 0.6),
        ]
        candidates = build_candidates(rows, expected_fund_count=2)
        by_name = {row["parameter_name"]: row for row in candidates}
        self.assertEqual(set(by_name), {"dpi_mean", "dpi_sd", "rvpi_mean", "rvpi_sd"})
        self.assertEqual(by_name["dpi_mean"]["value_numeric"], "1.2")
        self.assertTrue(
            math.isclose(float(by_name["dpi_sd"]["value_numeric"]), math.sqrt(0.08))
        )
        self.assertEqual(by_name["rvpi_mean"]["value_numeric"], "0.4")
        self.assertEqual(by_name["dpi_mean"]["provenance_type"], "DERIVED")
        self.assertEqual(
            by_name["dpi_mean"]["adjudication_status"], "EXCLUDED_FROM_RELEASE"
        )
        self.assertEqual(by_name["dpi_mean"]["active"], "false")
        self.assertIn("one LP schedule", by_name["dpi_mean"]["assumption_basis"])
        self.assertEqual(by_name["dpi_mean"]["input_record_ids"], "D1|D2")

    def test_rejects_unpaired_metric_panels(self) -> None:
        rows = [
            fact("D1", "Fund One, L.P.", "dpi", 1.0),
            fact("R1", "Fund Two, L.P.", "rvpi", 0.2),
        ]
        with self.assertRaisesRegex(CalibrationCandidateError, "panels differ"):
            build_candidates(rows, expected_fund_count=1)

    def test_writes_the_fixed_header_verbatim(self) -> None:
        rows = [
            fact("D1", "Fund One, L.P.", "dpi", 1.0),
            fact("R1", "Fund One, L.P.", "rvpi", 0.2),
            fact("D2", "Fund Two, L.P.", "dpi", 1.4),
            fact("R2", "Fund Two, L.P.", "rvpi", 0.6),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "facts.csv"
            contract = root / "contract.csv"
            output = root / "candidates.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            with contract.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerow(HEADER)
            count, funds = write_candidates(
                source, output, contract, expected_fund_count=2
            )
            with output.open("r", encoding="utf-8", newline="") as handle:
                actual_header = next(csv.reader(handle))
            self.assertEqual((count, funds), (4, 2))
            self.assertEqual(actual_header, HEADER)


if __name__ == "__main__":
    unittest.main()
