"""The matrix reader: validation, lookups, contexts, the legacy asserts, and the check record."""

from __future__ import annotations

import ast
import csv
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from src.common import matrices

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HEADER = "input_value,output_value,decided_by,evidence,note\n"
CONTEXT_HEADER = "input_value,output_value,decided_by,evidence,note,context\n"


def write(root: Path, name: str, body: str, header: str = HEADER) -> None:
    (root / f"{name}.csv").write_text(header + body, encoding="utf-8", newline="\n")


def _loaded_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {
        item.id
        for item in ast.walk(node)
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
    }


def _contains_matrix_assert(node: ast.AST) -> bool:
    for item in ast.walk(node):
        if isinstance(item, ast.Assert):
            return True
        if not isinstance(item, ast.Call) or not isinstance(item.func, ast.Attribute):
            continue
        if (
            isinstance(item.func.value, ast.Name)
            and item.func.value.id == "matrices"
            and item.func.attr in {"assert_legacy", "assert_legacy_rows"}
        ):
            return True
    return False


def uncovered_legacy_literals(source: str) -> list[str]:
    tree = ast.parse(source)
    legacy: set[str] = set()
    dependencies: dict[str, set[str]] = {}
    for item in ast.walk(tree):
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            value = item.value
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                dependencies.setdefault(target.id, set()).update(_loaded_names(value))
                if target.id.startswith("_LEGACY_"):
                    legacy.add(target.id)

    covered: set[str] = set()
    for item in ast.walk(tree):
        if isinstance(item, ast.Assert):
            covered.update(_loaded_names(item.test))
        elif isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute):
            if (
                isinstance(item.func.value, ast.Name)
                and item.func.value.id == "matrices"
                and item.func.attr in {"assert_legacy", "assert_legacy_rows"}
            ):
                covered.update(_loaded_names(item))
        elif isinstance(item, ast.For) and _contains_matrix_assert(ast.Module(body=item.body)):
            covered.update(_loaded_names(item.iter))

    changed = True
    while changed:
        changed = False
        for name in tuple(covered):
            for dependency in dependencies.get(name, set()):
                if dependency not in covered:
                    covered.add(dependency)
                    changed = True
    return sorted(legacy - covered)


def matrix_constants_without_runtime_use(source: str, matrix_names: set[str]) -> list[str]:
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for item in ast.walk(tree):
        for child in ast.iter_child_nodes(item):
            parents[child] = item
    constants: dict[str, str] = {}
    for item in tree.body:
        if not isinstance(item, ast.Assign) or not isinstance(item.value, ast.Constant):
            continue
        if not isinstance(item.value.value, str) or item.value.value not in matrix_names:
            continue
        for target in item.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = item.value.value

    unused: list[str] = []
    for name in constants:
        runtime_use = False
        for item in ast.walk(tree):
            if not isinstance(item, ast.Name) or item.id != name or not isinstance(item.ctx, ast.Load):
                continue
            ancestor = parents.get(item)
            assertion_only = False
            while ancestor is not None:
                if isinstance(ancestor, ast.Assert):
                    assertion_only = True
                    break
                if isinstance(ancestor, ast.Call) and isinstance(ancestor.func, ast.Attribute):
                    if (
                        isinstance(ancestor.func.value, ast.Name)
                        and ancestor.func.value.id == "matrices"
                        and ancestor.func.attr in {"assert_legacy", "assert_legacy_rows"}
                    ):
                        assertion_only = True
                        break
                ancestor = parents.get(ancestor)
            if not assertion_only:
                runtime_use = True
                break
        if not runtime_use:
            unused.append(name)
    return sorted(unused)


class MatrixReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = TemporaryDirectory()
        self.root = Path(self._directory.name)
        matrices.clear_cache()

    def tearDown(self) -> None:
        self._directory.cleanup()
        matrices.clear_cache()

    def test_live_root_validates(self) -> None:
        self.assertEqual(matrices.check(), [])

    def test_every_legacy_literal_has_an_assert(self) -> None:
        findings: list[str] = []
        for path in sorted((PROJECT_ROOT / "src").rglob("*.py")):
            if "dashboard" in path.parts or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            findings.extend(
                f"{path.relative_to(PROJECT_ROOT).as_posix()}: {name}"
                for name in uncovered_legacy_literals(text)
            )
        self.assertEqual(findings, [])

    def test_legacy_scan_requires_a_real_syntax_link(self) -> None:
        unlinked = "_LEGACY_B1_VALUE = 'x'\nmatrices.assert_legacy(MATRIX, OTHER)\n"
        self.assertEqual(uncovered_legacy_literals(unlinked), ["_LEGACY_B1_VALUE"])
        linked = "_LEGACY_B1_VALUE = 'x'\nmatrices.assert_legacy(MATRIX, {'k': _LEGACY_B1_VALUE})\n"
        self.assertEqual(uncovered_legacy_literals(linked), [])

    def test_every_matrix_constant_has_a_non_assertion_consumer(self) -> None:
        matrix_names = {
            path.stem for path in matrices.matrix_files(PROJECT_ROOT / "data" / "normalization" / "transformations")
        }
        findings: list[str] = []
        for path in sorted((PROJECT_ROOT / "src").rglob("*.py")):
            if "dashboard" in path.parts or "__pycache__" in path.parts:
                continue
            findings.extend(
                f"{path.relative_to(PROJECT_ROOT).as_posix()}: {name}"
                for name in matrix_constants_without_runtime_use(
                    path.read_text(encoding="utf-8"), matrix_names
                )
            )
        self.assertEqual(findings, [])

    def test_lookup_and_star(self) -> None:
        write(self.root, "m", "a,x,literal,src/x.py:1,\n*,other,literal,src/x.py:2,\n")
        self.assertEqual(matrices.mapping("m", root=self.root), {"a": "x"})
        self.assertEqual(matrices.resolve("m", "a", root=self.root), "x")
        with self.assertRaises(matrices.MatrixError):
            matrices.resolve("m", "b", root=self.root)
        self.assertEqual(matrices.resolve_or_star("m", "b", root=self.root), "other")
        write(self.root, "nostar", "a,x,literal,src/x.py:1,\n")
        with self.assertRaises(matrices.MatrixError):
            matrices.resolve_or_star("nostar", "b", root=self.root)

    def test_members_uses_the_output_disposition(self) -> None:
        write(
            self.root,
            "members",
            "a,included,literal,src/x.py:1,\nb,excluded,literal,src/x.py:2,\n",
        )
        self.assertEqual(matrices.members("members", "included", root=self.root), frozenset({"a"}))
        self.assertEqual(matrices.members("members", "excluded", root=self.root), frozenset({"b"}))

    def test_blank_cells_are_refused_and_the_token_means_empty(self) -> None:
        write(self.root, "blank_in", ",x,literal,src/x.py:1,\n")
        errors = matrices.validate("blank_in", self.root)
        self.assertTrue(any("blank input_value" in error and "<blank>" in error for error in errors), errors)
        write(self.root, "blank_out", "a,,literal,src/x.py:1,\n")
        errors = matrices.validate("blank_out", self.root)
        self.assertTrue(any("blank output_value" in error for error in errors), errors)
        with self.assertRaises(matrices.MatrixError):
            matrices.load("blank_out", self.root)
        write(self.root, "token", "<blank>,absolute,literal,src/x.py:1,\nmillion,<blank>,literal,src/x.py:2,\n")
        self.assertEqual(matrices.mapping("token", root=self.root), {"": "absolute", "million": ""})
        self.assertEqual(matrices.resolve("token", "", root=self.root), "absolute")
        self.assertEqual(matrices.encode(""), "<blank>")
        self.assertEqual(matrices.decode("<blank>"), "")

    def test_contexts_keep_one_input_distinct_under_two_conditions(self) -> None:
        write(
            self.root,
            "ctx",
            "irr,rate,literal,src/x.py:1,,percent\nirr,ratio,literal,src/x.py:2,,number\nnav,money,literal,src/x.py:3,,\n",
            header=CONTEXT_HEADER,
        )
        self.assertEqual(matrices.validate("ctx", self.root), [])
        self.assertEqual(matrices.contexts("ctx", self.root), ["", "number", "percent"])
        self.assertEqual(matrices.resolve("ctx", "irr", context="percent", root=self.root), "rate")
        self.assertEqual(matrices.resolve("ctx", "irr", context="number", root=self.root), "ratio")
        self.assertEqual(matrices.mapping("ctx", root=self.root), {"nav": "money"})
        with self.assertRaises(matrices.MatrixError):
            matrices.resolve("ctx", "irr", root=self.root)
        write(
            self.root,
            "ctx_dup",
            "irr,rate,literal,src/x.py:1,,percent\nirr,ratio,literal,src/x.py:2,,percent\n",
            header=CONTEXT_HEADER,
        )
        errors = matrices.validate("ctx_dup", self.root)
        self.assertTrue(any("duplicate context 'percent', input_value 'irr'" in error for error in errors), errors)
        matrices.assert_legacy("ctx", {"irr": "rate"}, context="percent", root=self.root)
        with self.assertRaises(matrices.MatrixError):
            matrices.assert_legacy("ctx", {"irr": "rate"}, context="number", root=self.root)

    def test_validation_refuses_duplicates_and_bad_headers(self) -> None:
        write(self.root, "dup", "a,x,literal,src/x.py:1,\na,y,literal,src/x.py:2,\n")
        self.assertTrue(any("duplicate" in error for error in matrices.validate("dup", self.root)))
        write(self.root, "evidence", "a,x,,src/x.py:1,\nb,y,literal,,\n")
        errors = matrices.validate("evidence", self.root)
        self.assertTrue(any("blank decided_by" in error for error in errors))
        self.assertTrue(any("blank evidence" in error for error in errors))
        write(self.root, "head", "1,2\n", header="x,y\n")
        self.assertTrue(any("header" in error for error in matrices.validate("head", self.root)))
        write(self.root, "wide", "a,x,literal,src/x.py:1,,extra\n")
        self.assertTrue(any("more cells" in error for error in matrices.validate("wide", self.root)))
        self.assertEqual(matrices.validate("absent", self.root), [f"{(self.root / 'absent.csv').as_posix()}: missing"])
        with self.assertRaises(matrices.MatrixError):
            matrices.load("dup", self.root)
        self.assertGreaterEqual(len(matrices.check(self.root)), 4)

    def test_assert_legacy_mapping_and_membership(self) -> None:
        write(self.root, "map", "a,x,literal,src/x.py:1,\nb,y,literal,src/x.py:1,\n")
        matrices.assert_legacy("map", {"a": "x", "b": "y"}, root=self.root)
        with self.assertRaises(matrices.MatrixError):
            matrices.assert_legacy("map", {"a": "x", "b": "z"}, root=self.root)
        with self.assertRaises(matrices.MatrixError):
            matrices.assert_legacy("map", {"a": "x"}, root=self.root)
        write(self.root, "members", "a,member,literal,src/x.py:1,\nb,member,literal,src/x.py:1,\n")
        matrices.assert_legacy("members", {"a", "b"}, output_value="member", root=self.root)
        matrices.assert_legacy("members", ("b", "a"), output_value="member", root=self.root)
        with self.assertRaises(matrices.MatrixError):
            matrices.assert_legacy("members", {"a"}, output_value="member", root=self.root)
        with self.assertRaises(matrices.MatrixError):
            matrices.assert_legacy("members", {"a", "b"}, root=self.root)

    def test_assert_legacy_rows(self) -> None:
        write(
            self.root,
            "scale",
            "million,millions,literal,src/x.py:1,,1000000\nmm,millions,literal,src/x.py:1,,1000000\n<blank>,absolute,literal,src/x.py:2,,1\n",
            header="input_value,output_value,decided_by,evidence,note,multiplier\n",
        )
        expected = [
            {"input_value": "million", "output_value": "millions", "multiplier": 1000000},
            {"input_value": "mm", "output_value": "millions", "multiplier": 1000000},
            {"input_value": "", "output_value": "absolute", "multiplier": 1},
        ]
        matrices.assert_legacy_rows("scale", expected, root=self.root)
        with self.assertRaises(matrices.MatrixError):
            matrices.assert_legacy_rows("scale", [dict(expected[0], multiplier=1000), *expected[1:]], root=self.root)
        with self.assertRaises(matrices.MatrixError):
            matrices.assert_legacy_rows("scale", expected[:2], root=self.root)
        with self.assertRaises(matrices.MatrixError):
            matrices.assert_legacy_rows("scale", [*expected, {"input_value": "bn"}], root=self.root)

    def test_check_record(self) -> None:
        write(self.root, "ok", "a,x,literal,src/x.py:1,\n")
        write(self.root, "bad", "a,x,,src/x.py:1,\n")
        record = self.root / "record.csv"
        self.assertEqual(matrices.write_check(record, self.root), 1)
        with record.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["matrix"] for row in rows], ["bad", "ok"])
        self.assertEqual([row["status"] for row in rows], ["FAIL", "PASS"])
        self.assertEqual((rows[1]["rows"], rows[1]["contexts"]), ("1", "1"))
        with TemporaryDirectory() as empty:
            empty_record = Path(empty) / "record.csv"
            self.assertEqual(matrices.write_check(empty_record, Path(empty)), 0)
            self.assertEqual(
                empty_record.read_text(encoding="utf-8"), ",".join(matrices.CHECK_COLUMNS) + "\n"
            )

    def test_command_line_check(self) -> None:
        write(self.root, "ok", "a,x,literal,src/x.py:1,\n")
        record = self.root / "record.csv"
        self.assertEqual(matrices.main(["--check", "--root", str(self.root), "--record", str(record)]), 0)
        write(self.root, "bad", "a,x,,src/x.py:1,\n")
        self.assertEqual(matrices.main(["--check", "--root", str(self.root), "--record", str(record)]), 1)

    def test_module_command_has_no_import_warning(self) -> None:
        write(self.root, "ok", "a,x,literal,src/x.py:1,\n")
        record = self.root / "module-record.csv"
        completed = subprocess.run(
            [
                sys.executable,
                "-W",
                "error",
                "-m",
                "src.common.matrices",
                "--check",
                "--root",
                str(self.root),
                "--record",
                str(record),
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
