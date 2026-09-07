"""The migration gate on a scratch repository: every rule refuses what it exists to refuse."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import unittest
from pathlib import Path
from tempfile import mkdtemp

from src.common import matrices
from src.pipeline import migration_gate as gate

LIVE_ROOT = gate.root_dir()
HEADER = "input_value,output_value,decided_by,evidence,note\n"
INVENTORY_HEADER = "id,source,line,symbol,kind,proposed_matrix\n"
MASTER_HEADER = """# Master transformation inventory

## 8. Union inventory

| id | Site | Symbol | Kind | Severity | Matrix | Found by | Decides |
|---|---|---|---|---|---|---|---|
"""


def _remove_readonly(function, path, _excinfo) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(mkdtemp(prefix="gate-"))
        self.roadmap = Path(mkdtemp(prefix="roadmap-"))
        self.git("init", "-q")
        self.git("config", "user.email", "gate@test")
        self.git("config", "user.name", "gate")
        self.git("config", "core.autocrlf", "false")
        self.write("data/csv/a.csv", "h1,h2\n1,2\n2,3\n")
        self.write("data/normalization/README.md", "# Hand-written guide\n")
        self.write("src/common/README.md", "# Generated guide\n")
        self.write("src/x.py", "X = 1\n")
        self.write("ledgers/pipeline/transformation-receipts.csv", "receipt_id,output_path,output_sha256,status\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("tag", "v2")
        for name in gate.INVENTORIES:
            self.write_roadmap(name, INVENTORY_HEADER)
        self.write_roadmap(gate.MASTER_INVENTORY, MASTER_HEADER)
        gate.configure(self.root)
        matrices.clear_cache()

    def tearDown(self) -> None:
        gate.configure(LIVE_ROOT)
        matrices.clear_cache()
        shutil.rmtree(self.root, onexc=_remove_readonly)
        shutil.rmtree(self.roadmap, onexc=_remove_readonly)

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, text=True, capture_output=True, check=True).stdout

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def write_roadmap(self, name: str, text: str) -> None:
        (self.roadmap / name).write_text(text, encoding="utf-8", newline="\n")

    def write_master(self, *rows: str) -> None:
        self.write_roadmap(gate.MASTER_INVENTORY, MASTER_HEADER + "".join(rows))

    def refresh_snapshot(self) -> None:
        gate.write_site_snapshot(self.roadmap, self.root / gate.SITE_SNAPSHOT_REL)

    def write_scope(self, *rows: str) -> None:
        self.write(gate.BATCH_SCOPE_REL, "batch,source,expected_sites\n" + "".join(rows))

    def test_r01_reports_a_missing_published_path(self) -> None:
        self.assertTrue(gate.rule_r01("v2").passed)
        result = gate.rule_r01("migration-batch-0")
        self.assertFalse(result.passed)
        self.assertIn("previous-batch ref absent", result.detail)
        (self.root / "data" / "csv" / "a.csv").unlink()
        result = gate.rule_r01("v2")
        self.assertFalse(result.passed)
        self.assertIn("data/csv/a.csv", result.detail)

    def test_r02_and_r03_catch_header_and_row_count_changes(self) -> None:
        self.write("data/csv/a.csv", "h1,h3\n1,2\n2,3\n")
        changed, _ = gate.porcelain()
        r02, r03 = gate.rule_r02_r03("v2", changed, [])
        self.assertFalse(r02.passed)
        self.assertTrue(r03.passed)
        self.write("data/csv/a.csv", "h1,h2\n1,2\n")
        changed, _ = gate.porcelain()
        r02, r03 = gate.rule_r02_r03("v2", changed, [])
        self.assertTrue(r02.passed)
        self.assertFalse(r03.passed)
        self.assertIn("(2 -> 1)", r03.detail)

    def test_r04_catches_a_value_change_unless_the_path_is_allowed(self) -> None:
        self.write("data/csv/a.csv", "h1,h2\n1,2\n2,4\n")
        changed, _ = gate.porcelain()
        self.assertFalse(gate.rule_r04(changed, []).passed)
        self.assertTrue(gate.rule_r04(changed, ["data/csv/a.csv"]).passed)

    def test_r05_refuses_new_paths_outside_the_set_and_ignores_caches(self) -> None:
        self.write("data/csv/new.csv", "h\n")
        self.write("src/__pycache__/x.cpython-313.pyc", "")
        changed, untracked = gate.porcelain()
        self.assertNotIn("src/__pycache__/x.cpython-313.pyc", untracked)
        self.assertFalse(gate.rule_r05(changed, untracked, []).passed)
        self.assertTrue(gate.rule_r05(changed, untracked, ["data/csv/"]).passed)

    def test_committed_changes_remain_visible_against_the_batch_base(self) -> None:
        self.write("src/committed.py", "VALUE = 1\n")
        self.git("add", "src/committed.py")
        self.git("commit", "-q", "-m", "batch change")
        self.assertEqual(gate.porcelain(), (set(), set()))
        changed, untracked = gate.porcelain("v2")
        self.assertEqual(changed, {"src/committed.py"})
        self.assertEqual(untracked, set())
        self.assertFalse(gate.rule_r05(changed, untracked, []).passed)

    def test_r06_checks_committed_folders_against_the_batch_base(self) -> None:
        self.write("data/newfolder/x.csv", "h\n")
        self.git("add", "data/newfolder/x.csv")
        self.git("commit", "-q", "-m", "new folder")
        changed, untracked = gate.porcelain("v2")
        result = gate.rule_r06(changed | untracked, "v2")
        self.assertFalse(result.passed)
        self.assertIn("data/newfolder", result.detail)

    def test_only_the_two_rebuilt_databases_are_exempt(self) -> None:
        self.write("data/warehouse/alts.duckdb", "bytes")
        changed, untracked = gate.porcelain()
        self.assertTrue(gate.rule_r05(changed, untracked, []).passed)
        self.write("data/warehouse/alts_mock.duckdb", "bytes")
        changed, untracked = gate.porcelain()
        result = gate.rule_r05(changed, untracked, [])
        self.assertFalse(result.passed)
        self.assertIn("alts_mock.duckdb", result.detail)

    def test_r06_refuses_a_new_folder_except_the_matrix_root(self) -> None:
        self.write("data/newfolder/x.csv", "h\n")
        _, untracked = gate.porcelain()
        result = gate.rule_r06(untracked)
        self.assertFalse(result.passed)
        self.assertIn("data/newfolder", result.detail)
        (self.root / "data" / "newfolder" / "x.csv").unlink()
        (self.root / "data" / "newfolder").rmdir()
        self.write(gate.MATRIX_ROOT_REL + "/m.csv", HEADER + "a,x,literal,src/x.py:1,\n")
        _, untracked = gate.porcelain()
        self.assertTrue(gate.rule_r06(untracked).passed)

    def test_hand_written_guides_need_an_allowance_and_generated_ones_do_not(self) -> None:
        self.write("data/normalization/README.md", "# Hand-written guide, edited\n")
        changed, untracked = gate.porcelain()
        self.assertFalse(gate.rule_r05(changed, untracked, []).passed)
        self.assertTrue(gate.rule_r05(changed, untracked, ["data/normalization/README.md"]).passed)
        self.git("checkout", "--", "data/normalization/README.md")
        self.write("src/common/README.md", "# Generated guide, regenerated\n")
        changed, untracked = gate.porcelain()
        self.assertTrue(gate.rule_r05(changed, untracked, []).passed)

    def test_r07_reports_an_invalid_matrix(self) -> None:
        self.assertTrue(gate.rule_r07().passed)
        self.write(gate.MATRIX_ROOT_REL + "/bad.csv", HEADER + "a,x,,src/x.py:1,\n")
        result = gate.rule_r07()
        self.assertFalse(result.passed)
        self.assertIn("blank decided_by", result.detail)

    def test_r09_finds_prior_unversioned_and_current_closeout_legacy_symbols(self) -> None:
        self.write("src/x.py", "_LEGACY_B1_X = {'a': 'b'}\n")
        self.assertTrue(gate.rule_r09(1).passed)
        result = gate.rule_r09(2)
        self.assertFalse(result.passed)
        self.assertIn("src/x.py:1:_LEGACY_B1_X", result.detail)
        self.assertFalse(gate.rule_r09(1, retire_current=True).passed)
        self.write("src/x.py", "_LEGACY_X = {'a': 'b'}\n")
        self.assertFalse(gate.rule_r09(1).passed)
        self.write("src/x.py", '"""Documentation may name _LEGACY_BN_ without defining it."""\n')
        self.assertTrue(gate.rule_r09(1).passed)

    def test_r10_needs_a_row_bearing_matrix_or_a_disposition_across_all_inventories(self) -> None:
        target = gate.MATRIX_ROOT_REL + "/foo.csv"
        self.write_roadmap("transformation-inventory.csv", INVENTORY_HEADER + f"T001,src/x.py,5,FOO,classify,{target}\n")
        self.write_roadmap("transformation-inventory-b.csv", INVENTORY_HEADER + f"T009,src/x.py,6,FOO,classify,{gate.MATRIX_ROOT_REL}/bar.csv\n")
        self.write_roadmap("transformation-inventory-c.csv", INVENTORY_HEADER + "T004,src/y.py,7,OTHER,filter,\n")
        self.write_master(
            "| M001 | src/x.py:5 | FOO | classify | major | no | A:T001; B:T009 | maps x |\n",
            "| M002 | src/y.py:7 | OTHER | filter | minor | no | C:T004 | filters y |\n",
        )
        self.refresh_snapshot()
        self.write_scope("1,src/x.py,1\n1,src/y.py,1\n")
        self.write(
            gate.DISPOSITIONS_REL,
            "id,disposition,reason\nM002,structure,test-only non-data site\n",
        )
        result = gate.rule_r10(1)
        self.assertFalse(result.passed)
        self.assertIn("M001", result.detail)
        self.write(target, HEADER)
        result = gate.rule_r10(1)
        self.assertFalse(result.passed, "a header-only matrix must not count as coverage")
        matrices.clear_cache()
        self.write(target, HEADER + "a,x,literal,src/x.py:7,\n")
        self.assertFalse(
            gate.rule_r10(1).passed,
            "an unrelated row in the proposed matrix must not count as site coverage",
        )
        matrices.clear_cache()
        self.write(target, HEADER + "a,x,literal,src/x.py:5,\n")
        self.assertFalse(gate.rule_r10(1).passed, "every source line in a merged site must be covered")
        matrices.clear_cache()
        self.write(gate.MATRIX_ROOT_REL + "/bar.csv", HEADER + "b,y,literal,src/x.py:6,\n")
        self.assertTrue(gate.rule_r10(1).passed)
        (self.root / target).unlink()
        (self.root / gate.MATRIX_ROOT_REL / "bar.csv").unlink()
        matrices.clear_cache()
        self.write(
            gate.DISPOSITIONS_REL,
            "id,disposition,reason\nM001,structure,column order only\nM002,structure,test-only non-data site\n",
        )
        self.assertTrue(gate.rule_r10(1).passed)
        self.write(
            gate.DISPOSITIONS_REL,
            "id,disposition,reason\nM001,deferred,later\nM002,structure,test-only non-data site\n",
        )
        result = gate.rule_r10(1)
        self.assertFalse(result.passed)
        self.assertIn("disposition must be", result.detail)
        self.write(
            gate.DISPOSITIONS_REL,
            "id,disposition,reason\nM002,structure,test-only non-data site\nM999,structure,not in snapshot\n",
        )
        result = gate.rule_r10(1)
        self.assertFalse(result.passed)
        self.assertIn("unknown disposition", result.detail)
        (self.root / gate.SITE_SNAPSHOT_REL).unlink()
        result = gate.rule_r10(1)
        self.assertFalse(result.passed)
        self.assertIn("migration site snapshot absent", result.detail)
        (self.roadmap / "transformation-inventory-c.csv").unlink()
        with self.assertRaisesRegex(ValueError, "unknown inventory reference"):
            gate.write_site_snapshot(self.roadmap, self.root / gate.SITE_SNAPSHOT_REL)

    def test_r10_ignores_sites_outside_the_batches_done(self) -> None:
        self.write_roadmap("transformation-inventory.csv", INVENTORY_HEADER + f"T001,src/z.py,5,FOO,classify,{gate.MATRIX_ROOT_REL}/foo.csv\n")
        self.write_master("| M001 | src/z.py:5 | FOO | classify | major | no | A:T001 | maps z |\n")
        self.refresh_snapshot()
        self.write_scope("2,src/z.py,2\n")
        result = gate.rule_r10(1)
        self.assertFalse(result.passed)
        self.assertIn("count mismatch", result.detail)
        self.write_scope("2,src/z.py,1\n")
        self.assertTrue(gate.rule_r10(1).passed)
        self.assertFalse(gate.rule_r10(2).passed)
        self.assertEqual(gate.main(["--batch", "2", "--base", "v2"]), 1)

    def test_r10_requires_a_disposition_when_the_inventory_proposes_no_matrix(self) -> None:
        self.write_roadmap(
            "transformation-inventory.csv",
            INVENTORY_HEADER + "T001,src/x.py,5,ORDER,default,\n",
        )
        self.write_master(
            "| M001 | src/x.py:5 | ORDER | default | minor | no | A:T001 | fixes output order |\n"
        )
        self.refresh_snapshot()
        self.write_scope("1,src/x.py,1\n")
        result = gate.rule_r10(1)
        self.assertFalse(result.passed)
        self.assertIn("no proposed matrix and no structure disposition", result.detail)
        self.write(
            gate.DISPOSITIONS_REL,
            "id,disposition,reason\nM001,structure,output order only\n",
        )
        self.assertTrue(gate.rule_r10(1).passed)

    def test_master_sites_requires_every_inventory_row_exactly_once(self) -> None:
        self.write_roadmap("transformation-inventory.csv", INVENTORY_HEADER + "T001,src/x.py,5,FOO,classify,\n")
        self.write_master("| M001 | src/x.py:5 | FOO | classify | major | no | A:T001 | maps x |\n")
        sites = gate.master_sites(self.roadmap)
        self.assertEqual([(site["id"], site["source"]) for site in sites], [("M001", "src/x.py")])
        self.write_master(
            "| M001 | src/x.py:5 | FOO | classify | major | no | A:T001 | maps x |\n",
            "| M002 | src/x.py:5 | FOO | classify | major | no | A:T001 | duplicate |\n",
        )
        with self.assertRaisesRegex(ValueError, "duplicate references"):
            gate.master_sites(self.roadmap)

    def test_allowances_are_narrow(self) -> None:
        self.assertTrue(gate.allowed("docs/PROJECT-MANIFEST.csv", []))
        self.assertTrue(gate.allowed(gate.MATRIX_ROOT_REL + "/x.csv", []))
        self.assertFalse(gate.allowed("ledgers/promotion-gate/round02/x/worksheet.csv", []))
        self.assertFalse(gate.allowed("data/warehouse/alts_mock.duckdb", []))
        self.assertFalse(gate.allowed("data/normalization/README.md", []))
        self.assertTrue(gate.allowed("src/common/README.md", []))


if __name__ == "__main__":
    unittest.main()
