"""Read the decision matrices under data/normalization/transformations.

Each matrix is one CSV. A row names the input the pipeline saw, the output it
wrote, who decided that, and the file and line where the decision lived before
it moved here. A lookup with no row raises. The reader has no silent default,
because a silent default is the pattern this folder exists to replace.

Cell rules. A blank cell in input_value or output_value is an error, because a
blank cannot be told from a forgotten one; the empty string is written as the
token <blank>. A matrix may carry a context column after the five shared
columns; rows are then unique per (context, input_value) and every lookup names
its context, which is how one printed value can map differently under two
conditions the code once tested in sequence.
"""

from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable, Mapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT = PROJECT_ROOT / "data" / "normalization" / "transformations"
CHECK_PATH = PROJECT_ROOT / "ledgers" / "pipeline" / "matrix-check.csv"
COLUMNS = ("input_value", "output_value", "decided_by", "evidence", "note")
CONTEXT = "context"
CHECK_COLUMNS = ("matrix", "rows", "columns", "contexts", "status", "detail")
REQUIRED = ("input_value", "output_value", "decided_by", "evidence")
STAR = "*"
BLANK = "<blank>"

_CACHE: dict[tuple[str, str], list[dict[str, str]]] = {}


class MatrixError(RuntimeError):
    """A matrix is missing, malformed, or has no row for a value."""


def encode(value: object) -> str:
    """The cell text for a literal value: the empty string becomes <blank>."""

    text = str(value)
    return BLANK if text == "" else text


def decode(cell: str) -> str:
    """The literal value for a cell text: <blank> becomes the empty string."""

    return "" if cell == BLANK else cell


def matrix_path(name: str, root: Path = ROOT) -> Path:
    return root / f"{name}.csv"


def matrix_files(root: Path = ROOT) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*.csv") if path.is_file())


def matrix_names(root: Path = ROOT) -> list[str]:
    return [path.stem for path in matrix_files(root)]


def _label(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        rows = []
        for raw in reader:
            row = {key: (value if value is not None else "") for key, value in raw.items() if key is not None}
            if raw.get(None):
                row["__extra__"] = "|".join(str(cell) for cell in raw[None])
            rows.append(row)
    return header, rows


def validate(name: str, root: Path = ROOT) -> list[str]:
    """Every defect in one matrix, as messages a reader can act on."""

    path = matrix_path(name, root)
    label = _label(path)
    if not path.is_file():
        return [f"{label}: missing"]
    header, rows = _read(path)
    if tuple(header[: len(COLUMNS)]) != COLUMNS:
        return [f"{label}: header must start with {','.join(COLUMNS)}; found {','.join(header)}"]
    errors: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    for number, row in enumerate(rows, 2):
        for column in REQUIRED:
            if not row.get(column, "").strip():
                hint = f"; write {BLANK} for the empty string" if column in ("input_value", "output_value") else ""
                errors.append(f"{label}:{number}: blank {column}{hint}")
        key = (row.get(CONTEXT, ""), row.get("input_value", ""))
        if key in seen:
            where = f"context {key[0]!r}, " if key[0] else ""
            errors.append(f"{label}:{number}: duplicate {where}input_value {key[1]!r} (first at line {seen[key]})")
        else:
            seen[key] = number
        if "__extra__" in row:
            errors.append(f"{label}:{number}: more cells than header columns")
    return errors


def load(name: str, root: Path = ROOT) -> list[dict[str, str]]:
    key = (str(root), name)
    if key not in _CACHE:
        errors = validate(name, root)
        if errors:
            raise MatrixError("; ".join(errors))
        _CACHE[key] = _read(matrix_path(name, root))[1]
    return _CACHE[key]


def clear_cache() -> None:
    _CACHE.clear()


def contexts(name: str, root: Path = ROOT) -> list[str]:
    return sorted({row.get(CONTEXT, "") for row in load(name, root)})


def rows_in(name: str, context: str = "", root: Path = ROOT) -> list[dict[str, str]]:
    return [row for row in load(name, root) if row.get(CONTEXT, "") == context]


def mapping(name: str, context: str = "", root: Path = ROOT) -> dict[str, str]:
    return {
        decode(row["input_value"]): decode(row["output_value"])
        for row in rows_in(name, context, root)
        if row["input_value"] != STAR
    }


def members(
    name: str, output_value: str, context: str = "", root: Path = ROOT
) -> frozenset[str]:
    return frozenset(
        input_value
        for input_value, disposition in mapping(name, context, root).items()
        if disposition == output_value
    )


def resolve(name: str, input_value: str, context: str = "", root: Path = ROOT) -> str:
    table = mapping(name, context, root)
    if input_value in table:
        return table[input_value]
    where = f" under context {context!r}" if context else ""
    raise MatrixError(f"{name}: no row for input_value {input_value!r}{where}")


def resolve_or_star(name: str, input_value: str, context: str = "", root: Path = ROOT) -> str:
    table = mapping(name, context, root)
    if input_value in table:
        return table[input_value]
    for row in rows_in(name, context, root):
        if row["input_value"] == STAR:
            return decode(row["output_value"])
    where = f" under context {context!r}" if context else ""
    raise MatrixError(f"{name}: no row for input_value {input_value!r}{where} and no {STAR} row")


def assert_legacy(
    name: str,
    legacy: Mapping[object, object] | Iterable[object],
    output_value: str | None = None,
    context: str = "",
    root: Path = ROOT,
) -> None:
    """Fail at import when the matrix and the literal it replaces disagree.

    A mapping literal is compared key by key. A set, tuple, or list literal is
    compared as a membership: every member must appear as an input_value and
    every row must carry the given output_value.
    """

    actual = mapping(name, context, root)
    if isinstance(legacy, Mapping):
        expected = {str(key): str(value) for key, value in legacy.items()}
    else:
        if output_value is None:
            raise MatrixError(f"{name}: assert_legacy on a membership literal needs output_value")
        expected = {str(item): output_value for item in legacy}
    if actual == expected:
        return
    where = f" under context {context!r}" if context else ""
    for key in sorted(set(actual) | set(expected)):
        if actual.get(key) != expected.get(key):
            raise MatrixError(
                f"{name}: matrix and _LEGACY literal differ at input_value {key!r}{where}: "
                f"matrix={actual.get(key)!r} literal={expected.get(key)!r}"
            )


def assert_legacy_rows(
    name: str, expected: Iterable[Mapping[str, object]], root: Path = ROOT
) -> None:
    """Fail at import when a multi-column matrix disagrees with the literal.

    Each expected item names an input_value (and a context when the matrix has
    one) and the columns to compare; rows are matched by that key, so order
    does not matter. Completeness is per context: within every context the
    expected items touch, every row of the matrix must be named, while rows
    under other contexts belong to other callers' asserts.
    """

    rows = {(row.get(CONTEXT, ""), row["input_value"]): row for row in load(name, root)}
    wanted = [{key: encode(value) for key, value in item.items()} for item in expected]
    named: set[tuple[str, str]] = set()
    for item in wanted:
        key = (item.get(CONTEXT, ""), item.get("input_value", ""))
        named.add(key)
        row = rows.get(key)
        if row is None:
            raise MatrixError(f"{name}: no row for input_value {key[1]!r} named by the _LEGACY literal")
        for column, value in item.items():
            if row.get(column, "") != value:
                raise MatrixError(
                    f"{name}: matrix and _LEGACY literal differ at input_value {key[1]!r}, column "
                    f"{column}: matrix={row.get(column, '')!r} literal={value!r}"
                )
    covered_contexts = {key[0] for key in named}
    extra = sorted(
        key for key in rows
        if key not in named and key[1] != STAR and key[0] in covered_contexts
    )
    if extra:
        raise MatrixError(
            f"{name}: rows absent from the _LEGACY literal: " + ", ".join(key[1] for key in extra)
        )


def check(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for path in matrix_files(root):
        errors.extend(validate(path.stem, root))
    return errors


def check_record(root: Path = ROOT) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for path in matrix_files(root):
        errors = validate(path.stem, root)
        header, rows = _read(path)
        records.append(
            {
                "matrix": path.stem,
                "rows": str(len(rows)),
                "columns": str(len(header)),
                "contexts": str(len({row.get(CONTEXT, "") for row in rows})) if rows else "0",
                "status": "FAIL" if errors else "PASS",
                "detail": "; ".join(errors),
            }
        )
    return records


def write_check(path: Path = CHECK_PATH, root: Path = ROOT) -> int:
    """Write the check record and return the number of failing matrices."""

    records = check_record(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CHECK_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    return sum(1 for record in records if record["status"] == "FAIL")


def check_and_record() -> int:
    """The release-stage action: the record is written, the failure count returned."""

    return write_check()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate every matrix and write the check record")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--record", type=Path, default=CHECK_PATH)
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 0
    failing = write_check(args.record, args.root)
    for error in check(args.root):
        print(f"FAIL: {error}")
    names = matrix_names(args.root)
    if failing:
        print(f"FAIL: {failing} of {len(names)} matrices")
        return 1
    print(f"PASS: {len(names)} matrices under {_label(args.root)}; record -> {_label(args.record)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
