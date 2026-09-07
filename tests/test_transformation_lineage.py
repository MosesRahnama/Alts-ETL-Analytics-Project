from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.pipeline.transformation_lineage import digest, receipt_errors, run_stage


def receipts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class TransformationLineageTests(unittest.TestCase):
    def test_stage_archives_both_versions_and_deduplicates_an_exact_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "archive"
            ledger = root / "receipts.csv"
            source = root / "source.csv"
            output = root / "output.csv"
            source.write_text("id,value\n1,A\n", encoding="utf-8")
            output.write_text("id,value\n1,OLD\n", encoding="utf-8")
            old_hash = digest(output)

            def build() -> int:
                output.write_text("id,value\n1,NEW\n", encoding="utf-8")
                return 1

            _, first = run_stage(
                stage_id="test",
                stage_order=1,
                command="build",
                inputs=(source,),
                outputs=(output,),
                action=build,
                recorded_at_utc="2026-01-01T00:00:00Z",
                receipt_path=ledger,
                archive_dir=archive,
                root=root,
            )
            self.assertEqual(len(first), 1)
            row = receipts(ledger)[0]
            self.assertEqual(row["prior_output_sha256"], old_hash)
            self.assertTrue((root / row["prior_output_object_path"]).is_file())
            self.assertTrue((root / row["output_object_path"]).is_file())
            self.assertEqual(
                receipt_errors(receipt_path=ledger, root=root, archive_dir=archive), []
            )

            _, second = run_stage(
                stage_id="test",
                stage_order=1,
                command="build",
                inputs=(source,),
                outputs=(output,),
                action=build,
                recorded_at_utc="2026-01-02T00:00:00Z",
                receipt_path=ledger,
                archive_dir=archive,
                root=root,
            )
            self.assertEqual(second, [])
            self.assertEqual(len(receipts(ledger)), 1)

    def test_failed_and_passing_attempts_have_distinct_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "archive"
            ledger = root / "receipts.csv"
            source = root / "source.csv"
            output = root / "output.csv"
            source.write_text("id\n1\n", encoding="utf-8")
            output.write_text("id\n0\n", encoding="utf-8")

            def fail() -> None:
                output.write_text("id\n1\n", encoding="utf-8")
                raise ValueError("planted failure")

            with self.assertRaisesRegex(ValueError, "planted failure"):
                run_stage(
                    stage_id="test",
                    stage_order=1,
                    command="build",
                    inputs=(source,),
                    outputs=(output,),
                    action=fail,
                    receipt_path=ledger,
                    archive_dir=archive,
                    root=root,
                )
            run_stage(
                stage_id="test",
                stage_order=1,
                command="build",
                inputs=(source,),
                outputs=(output,),
                action=lambda: output.write_text("id\n1\n", encoding="utf-8"),
                receipt_path=ledger,
                archive_dir=archive,
                root=root,
            )
            self.assertEqual({row["status"] for row in receipts(ledger)}, {"FAIL", "PASS"})

    def test_a_changed_archive_object_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "archive"
            ledger = root / "receipts.csv"
            source = root / "source.csv"
            output = root / "output.csv"
            source.write_text("id\n1\n", encoding="utf-8")
            output.write_text("id\n0\n", encoding="utf-8")
            run_stage(
                stage_id="test",
                stage_order=1,
                command="build",
                inputs=(source,),
                outputs=(output,),
                action=lambda: output.write_text("id\n1\n", encoding="utf-8"),
                receipt_path=ledger,
                archive_dir=archive,
                root=root,
            )
            row = receipts(ledger)[0]
            (root / row["output_object_path"]).write_text("changed", encoding="utf-8")
            self.assertTrue(
                receipt_errors(receipt_path=ledger, root=root, archive_dir=archive)
            )
            self.assertEqual(
                receipt_errors(
                    receipt_path=ledger,
                    root=root,
                    archive_dir=archive,
                    require_objects=False,
                ),
                [],
            )


if __name__ == "__main__":
    unittest.main()
