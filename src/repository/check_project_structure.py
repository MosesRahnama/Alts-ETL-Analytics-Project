"""Validate project documentation, manifest coverage, and source ownership."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from .build_project_manifest import OUTPUT, entries, gitignored_root_names, sha256
from .build_readmes import (
    PROJECT_ROOT,
    hand_written,
    project_directories,
    relative,
    render_readme,
)


# Bytecode and pytest caches are not listed: every Python invocation, this
# check included, creates them, so forbidding them made `python -m pytest`
# fail on its own footprint. They are excluded by .gitignore and skipped by
# the manifest instead.
SKIP_NAMES = {".git", ".pytest_cache", "__pycache__"}

FORBIDDEN_PARTS = {
    ".claude",
    ".codex",
    ".github",
    "alts-sample-project",
    "edge-temp-src060",
    "project-audits",
    "tmp",
}


def read_manifest() -> dict[str, dict[str, str]]:
    if not OUTPUT.is_file():
        return {}
    with OUTPUT.open(encoding="utf-8-sig", newline="") as handle:
        return {row["path"]: row for row in csv.DictReader(handle)}


MARKER = re.compile(r"<!--\s*(curated-manual|direct-inventory:(start|end))\s*-->")


def check_readmes(errors: list[str]) -> None:
    for directory in project_directories():
        readme = directory / "README.md"
        if not readme.is_file():
            errors.append(f"missing folder guide: {relative(directory)}/README.md")
            continue
        text = readme.read_text(encoding="utf-8-sig", errors="replace")
        # A folder guide is written for the reader who opens it. An instruction
        # addressed to a generator has no business in that file.
        if MARKER.search(text):
            errors.append(f"generator marker in a folder guide: {relative(readme)}")
        if (
            directory != PROJECT_ROOT
            and not hand_written(directory)
            and text != render_readme(directory)
        ):
            errors.append(f"folder guide drift: {relative(readme)}")


def check_numbering(errors: list[str]) -> None:
    """A number prefix promises a position in a sequence, so the sequence must
    be whole. Folders numbered 02, 04, 05, 07 tell a reader that 01, 03, and 06
    exist somewhere and were withheld. Duplicates are allowed because one step
    can own several files (a route's records and coverage share its number)."""
    for directory in project_directories():
        numbers = set()
        for path in directory.iterdir():
            if path.name in SKIP_NAMES:
                continue
            match = re.match(r"^(\d\d)-", path.name)
            if match:
                numbers.add(int(match.group(1)))
        if not numbers:
            continue
        first, last = min(numbers), max(numbers)
        if first > 1:
            errors.append(
                f"numbering starts at {first:02d}: {relative(directory)}"
            )
        missing = sorted(set(range(first, last + 1)) - numbers)
        if missing:
            gap = ", ".join(f"{value:02d}" for value in missing)
            errors.append(f"numbering gap ({gap}): {relative(directory)}")


def check_root_index(errors: list[str]) -> None:
    readme = PROJECT_ROOT / "README.md"
    if not readme.is_file():
        return
    text = readme.read_text(encoding="utf-8-sig", errors="replace")
    skipped = {".git", ".pytest_cache", "__pycache__"} | gitignored_root_names()
    for path in sorted(PROJECT_ROOT.iterdir(), key=lambda item: item.name.casefold()):
        if path.name in skipped:
            continue
        token = f"{path.name}/" if path.is_dir() else path.name
        if token not in text:
            errors.append(f"root landing page omits: {token}")


def check_manifest(errors: list[str], verify_hashes: bool) -> None:
    manifest = read_manifest()
    if not manifest:
        errors.append("missing or empty docs/PROJECT-MANIFEST.csv")
        return
    actual = {relative(path): path for path in entries()}
    missing = sorted(set(actual) - set(manifest), key=str.casefold)
    extra = sorted(set(manifest) - set(actual), key=str.casefold)
    errors.extend(f"manifest missing: {path}" for path in missing)
    errors.extend(f"manifest extra: {path}" for path in extra)
    for rel, path in actual.items():
        row = manifest.get(rel)
        if row is None:
            continue
        expected_type = "file" if path.is_file() else "directory"
        if row["entry_type"] != expected_type:
            errors.append(f"manifest type mismatch: {rel}")
        readme = PROJECT_ROOT / Path(row["local_readme"])
        if not readme.is_file():
            errors.append(f"manifest guide missing for {rel}: {row['local_readme']}")
        if not path.is_file() or path == OUTPUT or not row["size_bytes"]:
            continue
        if row["size_bytes"] != str(path.stat().st_size):
            errors.append(f"manifest size mismatch: {rel}")
        if verify_hashes and row["sha256"] != sha256(path):
            errors.append(f"manifest hash mismatch: {rel}")


def check_debris(errors: list[str]) -> None:
    for path in PROJECT_ROOT.rglob("*"):
        relative_parts = path.relative_to(PROJECT_ROOT).parts
        # Git's own directory is not project content. It carries a `tmp` folder
        # while Git LFS stages an object, which this check would otherwise read
        # as leftover working material.
        if relative_parts and relative_parts[0] in SKIP_NAMES:
            continue
        parts = {part.casefold() for part in relative_parts}
        if parts & FORBIDDEN_PARTS:
            errors.append(f"excluded debris present: {relative(path)}")


def check_source_contract(errors: list[str], verify_hashes: bool) -> None:
    ledger = PROJECT_ROOT / "data-gathering" / "source_ledger.csv"
    types_path = PROJECT_ROOT / "data-gathering" / "document-types.csv"
    pdf_root = PROJECT_ROOT / "data" / "documents" / "pdf"
    if not ledger.is_file() or not types_path.is_file():
        errors.append("source ledger or controlled document-type table is missing")
        return
    with ledger.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with types_path.open(encoding="utf-8-sig", newline="") as handle:
        types = {row["doc_type"] for row in csv.DictReader(handle) if row.get("doc_type")}
    if len(rows) != 442:
        errors.append(f"source ledger has {len(rows)} rows, expected 442")
    if len(types) != 17:
        errors.append(f"document-type table has {len(types)} values, expected 17")
    unknown = sorted({row["doc_type"] for row in rows} - types)
    if unknown:
        errors.append(f"source ledger uses unknown document types: {', '.join(unknown)}")
    local = {path.name: path for path in pdf_root.glob("*.pdf")}
    expected = {row["filename"]: row for row in rows}
    if local and set(local) != set(expected):
        errors.append("local PDF cache does not match the 442 ledger filenames")
    if local and verify_hashes:
        for name, path in local.items():
            if sha256(path) != expected[name]["sha256"]:
                errors.append(f"source SHA-256 mismatch: {name}")


def validate(verify_hashes: bool = False) -> list[str]:
    errors: list[str] = []
    check_readmes(errors)
    check_numbering(errors)
    check_root_index(errors)
    check_manifest(errors, verify_hashes)
    check_debris(errors)
    check_source_contract(errors, verify_hashes)
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-hashes", action="store_true")
    args = parser.parse_args()
    errors = validate(args.verify_hashes)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        raise SystemExit(1)
    file_count = sum(path.is_file() for path in entries())
    directory_count = sum(path.is_dir() for path in entries())
    mode = " and SHA-256" if args.verify_hashes else ""
    print(f"PASS: {file_count} files, {directory_count} directories, folder guides, manifest{mode}")


if __name__ == "__main__":
    main()
