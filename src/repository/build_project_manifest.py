"""Build the project manifest from the repository tree and Git policy."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "PROJECT-MANIFEST.csv"
# The structure check and its test import the manifest path under this name.
OUTPUT = DEFAULT_OUTPUT
EXCLUDED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
}
# Gitignored operator dumps. They stay on this machine and are not project paths.
LOCAL_TREE_PREFIXES = (
    "audit",
)
COLUMNS = (
    "path",
    "entry_type",
    "size_bytes",
    "sha256",
    "repository_policy",
    "local_readme",
    "role",
)
# Rebuilt on every read of the tree and rendered from this manifest; listed,
# never sized or hashed.
UNHASHED = frozenset({"dashboard.html"})
REJECT_ROLE = re.compile(
    r"\b(old|new|earlier|former|retired|working note|scratch|history|temporary)\b",
    re.I,
)
# A prior role is kept so a hand-written description survives a rebuild. These
# three were written by an early generator and say nothing, and keeping them was
# self-perpetuating: the manifest preserved them, so no regeneration could reach
# the real description. Naming them here lets the current generator answer.
STALE_ROLE = re.compile(
    r"^(This folder guide|Marks the folder as a Python package|Project artifact for )",
    re.I,
)
ROLE_OVERRIDES = {
    "data/extracted/tables/dim_metric.csv": (
        "Metric IDs observed in the published extraction, with value kind, row count, "
        "cross-document label, reported scope, and source note."
    ),
    "data/schemas": (
        "Document routing, 17 record families, 89 metric names, 30 term names, and "
        "the source surveys that define the field list."
    ),
    "data/schemas/EXTRACTION-METRIC-CATEGORIES.csv": (
        "The field vocabulary: 89 metric names and 30 term names with definitions, "
        "unit hints, and usual families."
    ),
    "data/schemas/METRIC-STANDARD-MEASURES.csv": (
        "Cross-document labels, reported scopes, and source notes for all published metric IDs."
    ),
    "data/schemas/RETURN-METHOD-BY-DOCUMENT.csv": (
        "Return methods, fee bases, and supporting source text by document, table, and column."
    ),
    "data/warehouse/extracted.duckdb": (
        "Document-level DuckDB star schema built from data/extracted/tables and "
        "data/extracted/wide."
    ),
    "src/catalog/simple_pdf_extraction/csv_wide_contract.py": (
        "The field list: 42 record columns, 17 record families, document-type routing, "
        "89 metric names, and 30 term names with definitions."
    ),
}


class ManifestError(RuntimeError):
    """Raised when the project manifest cannot be built."""


def relative(path: Path, root: Path) -> str:
    return "." if path == root else path.relative_to(root).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_existing(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return {row["path"]: row for row in reader if row.get("path")}


def git_paths(root: Path) -> tuple[set[str], set[str]]:
    tracked = set(
        subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=True,
        ).stdout.splitlines()
    )
    ignored = set(
        subprocess.run(
            ["git", "ls-files", "--others", "-i", "--exclude-standard"],
            cwd=root,
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=True,
        ).stdout.splitlines()
    )
    return tracked, ignored


def paths(root: Path) -> list[Path]:
    output: list[Path] = []
    ignored_root = gitignored_root_names()
    for current, directories, filenames in os.walk(root):
        directory = Path(current)
        rel_dir = relative(directory, root)
        if ".git" in directory.parts or skip_local_tree(rel_dir, ignored_root):
            directories[:] = []
            continue
        directories[:] = [
            name
            for name in directories
            if name not in EXCLUDED_DIRECTORIES
            and not skip_local_tree(relative(directory / name, root), ignored_root)
        ]
        output.append(directory)
        output.extend(
            directory / filename
            for filename in filenames
            if not filename.endswith(".part")
            and not skip_local_tree(relative(directory / filename, root), ignored_root)
        )
    return sorted(output, key=lambda path: (relative(path, root) != ".", relative(path, root).casefold()))


def entries(root: Path = PROJECT_ROOT) -> list[Path]:
    """Every path the manifest lists, root first, in manifest order."""

    return paths(root)


def gitignored_root_names() -> set[str]:
    """Root files named in .gitignore; they stay off the landing page."""

    ignore = PROJECT_ROOT / ".gitignore"
    if not ignore.is_file():
        return set()
    names = set()
    for line in ignore.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "/" not in line and "*" not in line:
            names.add(line)
    return names


def skip_local_tree(rel: str, ignored_root: set[str] | None = None) -> bool:
    """True for gitignored operator files and diagnostic dumps."""

    roots = gitignored_root_names() if ignored_root is None else ignored_root
    if rel in roots:
        return True
    return any(rel == prefix or rel.startswith(prefix + "/") for prefix in LOCAL_TREE_PREFIXES)


def python_role(path: Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        docstring = ast.get_docstring(tree)
        if docstring:
            return docstring.strip().splitlines()[0].rstrip(".") + "."
    except (OSError, SyntaxError, UnicodeDecodeError):
        pass
    return f"Python module for {path.stem.replace('_', ' ')}."


def markdown_role(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if line.startswith("#"):
                return line.lstrip("#").strip().rstrip(".") + " documentation."
    except OSError:
        pass
    return f"Documentation for {path.stem.replace('-', ' ').replace('_', ' ')}."


def generated_role(path: Path) -> str:
    if path.is_dir():
        return "Project root." if path == PROJECT_ROOT else f"Folder for {path.name.replace('-', ' ').replace('_', ' ')}."
    if path.name == "README.md":
        return "Folder guide and direct inventory."
    if path.name == "LICENSE":
        return "Repository licence."
    if path.name == "requirements.txt":
        return "Python dependency pins."
    known = {
        "pdf-wide-records.csv": "Published source observations.",
        "pdf-wide-coverage.csv": "Published physical-page coverage.",
        "document-summary.csv": "A/B, conflict, decision, and final counts by document.",
        "disagreement-fields.csv": "Disagreement counts by conflict type and field.",
        "observation-lineage.csv": "Observation links to candidate rows, pairs, decisions, final rows, and source hashes.",
        "trace-sample.csv": "Lineage samples with source evidence.",
        "reviewer-queries.sql": "DuckDB queries for extraction review.",
        "source_ledger.csv": "Source IDs, locations, page counts, document types, and hashes.",
        "PROJECT-MANIFEST.csv": "Project paths, sizes, hashes, policies, guides, and roles.",
        "CSV-LINEAGE.csv": "Every CSV with its origin CSV, transforming module, agent operation, and brief.",
    }
    if path.name in known:
        return known[path.name]
    suffix = path.suffix.casefold()
    stem = path.stem.replace("-", " ").replace("_", " ")
    if suffix == ".py":
        return python_role(path)
    if suffix == ".md":
        return markdown_role(path)
    if suffix == ".csv":
        if path.name.startswith("dim_"):
            return f"Dimension table for {stem[4:]}."
        if path.name.startswith("fact_"):
            return f"Fact table for {stem[5:]}."
        if path.name.startswith("wide_"):
            return f"Pivot table for {stem[5:]}."
        return f"CSV table for {stem}."
    if suffix == ".sql":
        return f"SQL definitions for {stem}."
    if suffix in {".yaml", ".yml", ".toml", ".ini", ".cfg"}:
        return f"Configuration for {stem}."
    if suffix == ".pdf":
        return "Source report registered in the source ledger."
    if suffix == ".txt":
        return "Page-aligned text or text evidence."
    if suffix == ".parquet":
        return f"Parquet data file for {stem}."
    if suffix == ".duckdb":
        return f"DuckDB database for {stem}."
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return "Image used by source review or the reviewer interface."
    if suffix in {".html", ".htm"}:
        return "HTML interface or report."
    if suffix == ".css":
        return "Interface style rules."
    if suffix == ".js":
        return "Interface script."
    return f"File for {path.name}."


def role(path: Path, root: Path, existing: Mapping[str, Mapping[str, str]]) -> str:
    key = relative(path, root)
    if key in ROLE_OVERRIDES:
        return ROLE_OVERRIDES[key]
    prior = existing.get(key, {}).get("role", "").strip()
    if (
        prior
        and not REJECT_ROLE.search(prior)
        and not STALE_ROLE.match(prior)
        and not prior.startswith(("File for ", "Folder for "))
    ):
        return prior.rstrip(".") + "."
    return generated_role(path)


def local_readme(path: Path, root: Path) -> str:
    if path == root:
        return "README.md"
    directory = path if path.is_dir() else path.parent
    return (directory / "README.md").relative_to(root).as_posix()


def build_rows(root: Path = PROJECT_ROOT, output: Path = DEFAULT_OUTPUT) -> list[dict[str, str]]:
    root = root.resolve()
    output = output.resolve()
    existing = read_existing(output)
    tracked, ignored = git_paths(root)
    rows: list[dict[str, str]] = []
    for path in paths(root):
        key = relative(path, root)
        is_file = path.is_file()
        if key in tracked or key not in ignored:
            policy = "TRACK"
        else:
            policy = "LOCAL_ONLY"
        # Two files describe the tree rather than belong to it: this manifest,
        # and the dashboard page, which renders the manifest. Recording their
        # bytes here would make each rebuild invalidate the other.
        unhashed = not is_file or path == output or key in UNHASHED
        rows.append(
            {
                "path": key,
                "entry_type": "file" if is_file else "directory",
                "size_bytes": "" if unhashed else str(path.stat().st_size),
                "sha256": "" if unhashed else sha256(path),
                "repository_policy": policy,
                "local_readme": local_readme(path, root),
                "role": role(path, root, existing),
            }
        )
    return rows


def render(rows: Sequence[Mapping[str, str]]) -> str:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def write(output: Path = DEFAULT_OUTPUT, root: Path = PROJECT_ROOT) -> int:
    text = render(build_rows(root, output))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")
    temporary.write_text(text, encoding="utf-8", newline="")
    temporary.replace(output)
    return text.count("\n") - 1


def check(output: Path = DEFAULT_OUTPUT, root: Path = PROJECT_ROOT) -> None:
    expected = render(build_rows(root, output))
    if not output.is_file():
        raise ManifestError(f"Missing manifest: {output}")
    actual = output.read_text(encoding="utf-8-sig")
    if actual != expected:
        raise ManifestError(f"Manifest differs from the project tree: {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            check(args.output.resolve(), args.root.resolve())
            print("PASS: project manifest matches the repository tree")
        else:
            count = write(args.output.resolve(), args.root.resolve())
            print(f"PASS: project manifest contains {count} path rows")
    except (ManifestError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
