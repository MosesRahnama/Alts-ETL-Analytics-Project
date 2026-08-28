"""Audit each project file with a type-specific check."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote

from src.repository.build_project_manifest import skip_local_tree

# The widest cell in the audited corpus is a receipt input list of about 26 KB.
# One megabyte leaves room for growth and still refuses a runaway field.
csv.field_size_limit(1024 * 1024)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "docs" / "PROJECT-MANIFEST.csv"
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
TEXT_NAMES = {".gitignore", ".gitattributes", "LICENSE"}
TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".cmd",
    ".css",
    ".gitignore",
    ".htm",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".rst",
    ".sql",
    ".svg",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
GENERATOR_MARKER = re.compile(r"<!--\s*(curated-manual|direct-inventory:(start|end))\s*-->")


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class FileResult:
    path: str
    file_type: str
    size_bytes: int
    check: str
    status: str
    detail: str


class AuditError(RuntimeError):
    """Raised when a release audit cannot run."""


def relative(path: Path, root: Path) -> str:
    return "." if path == root else path.relative_to(root).as_posix()


def files_and_directories(root: Path) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    directories: list[Path] = []
    for current, names, filenames in os.walk(root):
        directory = Path(current)
        rel_dir = relative(directory, root)
        if ".git" in directory.parts or skip_local_tree(rel_dir):
            names[:] = []
            continue
        names[:] = [
            name
            for name in names
            if name not in EXCLUDED_DIRECTORIES
            and not skip_local_tree(relative(directory / name, root))
        ]
        directories.append(directory)
        files.extend(
            directory / filename
            for filename in filenames
            if not filename.endswith(".part")
            and not skip_local_tree(relative(directory / filename, root))
        )
    return sorted(files), sorted(directories)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise AuditError(f"Manifest has no header: {path}")
        rows = list(reader)
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row.get("path", "")
        if not key:
            raise AuditError(f"Manifest contains a blank path: {path}")
        if key in output:
            raise AuditError(f"Manifest repeats {key}: {path}")
        output[key] = row
    return output


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def check_csv(path: Path) -> tuple[str, str]:
    widths: Counter[int] = Counter()
    rows = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise AuditError("CSV contains no header")
        if not header:
            raise AuditError("CSV header is blank")
        if any(name == "" for name in header):
            raise AuditError("CSV header contains a blank field")
        if len(header) != len(set(header)):
            raise AuditError("CSV header contains a duplicate field")
        width = len(header)
        for line_number, row in enumerate(reader, 2):
            rows += 1
            widths[len(row)] += 1
            if len(row) != width:
                raise AuditError(
                    f"line {line_number} has {len(row)} cells; header has {width}"
                )
    return "CSV header and row width", f"rows={rows}; columns={len(header)}"


def check_markdown(path: Path, root: Path) -> tuple[str, str]:
    text = read_text(path)
    broken: list[str] = []
    for target in LINK_PATTERN.findall(text):
        target_path = target.strip().split("#", 1)[0]
        if not target_path or target_path.startswith(("http://", "https://", "mailto:", "#")):
            continue
        candidate = (path.parent / unquote(target_path)).resolve()
        if not candidate.exists():
            broken.append(target)
    if broken:
        raise AuditError("broken links: " + ", ".join(broken[:10]))
    return "UTF-8 and local links", f"links={len(LINK_PATTERN.findall(text))}"


def check_python(path: Path) -> tuple[str, str]:
    text = read_text(path)
    tree = ast.parse(text, filename=str(path))
    return "UTF-8 and Python syntax", f"statements={len(tree.body)}"


def check_json(path: Path) -> tuple[str, str]:
    value = json.loads(read_text(path))
    return "UTF-8 and JSON parse", f"root_type={type(value).__name__}"


def check_yaml(path: Path) -> tuple[str, str]:
    import yaml

    value = yaml.safe_load(read_text(path))
    return "UTF-8 and YAML parse", f"root_type={type(value).__name__}"


def check_pdf(path: Path) -> tuple[str, str]:
    import fitz

    document = fitz.open(path)
    try:
        pages = document.page_count
        if pages < 1:
            raise AuditError("PDF has no pages")
    finally:
        document.close()
    return "PDF open and page count", f"pages={pages}"


def check_image(path: Path) -> tuple[str, str]:
    from PIL import Image

    with Image.open(path) as image:
        size = image.size
        image.verify()
    return "Image decode", f"width={size[0]}; height={size[1]}"


def check_parquet(path: Path) -> tuple[str, str]:
    import pyarrow.parquet as parquet

    file = parquet.ParquetFile(path)
    metadata = file.metadata
    return (
        "Parquet metadata",
        f"rows={metadata.num_rows}; row_groups={metadata.num_row_groups}; columns={len(file.schema.names)}",
    )


def check_duckdb(path: Path) -> tuple[str, str]:
    import duckdb

    connection = duckdb.connect(str(path), read_only=True)
    try:
        objects = connection.execute(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_name
            """
        ).fetchall()
        rows = 0
        for name, _kind in objects:
            rows += int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
    finally:
        connection.close()
    return "DuckDB open and object scan", f"objects={len(objects)}; aggregate_rows={rows}"


def check_text(path: Path) -> tuple[str, str]:
    text = read_text(path)
    nul = text.count("\x00")
    replacement = text.count("\ufffd")
    # The page-aligned text under data/documents/txt/ is what pdfplumber read
    # from each PDF's text layer, kept as read. A font with no Unicode map
    # yields U+FFFD and an odd text layer can yield NUL; both are facts about
    # the source and are counted, never corrected, so the file is reported
    # with its counts rather than failed.
    if "documents" in path.parts and "txt" in path.parts:
        return "UTF-8 decode of page text", f"characters={len(text)}; replacement_characters={replacement}; nul_characters={nul}"
    if nul:
        raise AuditError("text contains a NUL character")
    if replacement:
        raise AuditError("text contains a Unicode replacement character")
    return "UTF-8 decode", f"characters={len(text)}"


def check_binary(path: Path) -> tuple[str, str]:
    with path.open("rb") as handle:
        first = handle.read(16)
    return "Binary read", f"prefix_bytes={len(first)}"


def check_file(path: Path, root: Path) -> FileResult:
    suffix = path.suffix.casefold()
    try:
        if suffix == ".csv":
            check, detail = check_csv(path)
            kind = "csv"
        elif suffix == ".md":
            check, detail = check_markdown(path, root)
            kind = "markdown"
        elif suffix == ".py":
            check, detail = check_python(path)
            kind = "python"
        elif suffix == ".json":
            check, detail = check_json(path)
            kind = "json"
        elif suffix in {".yaml", ".yml"}:
            check, detail = check_yaml(path)
            kind = "yaml"
        elif suffix == ".pdf":
            check, detail = check_pdf(path)
            kind = "pdf"
        elif suffix in IMAGE_SUFFIXES:
            check, detail = check_image(path)
            kind = "image"
        elif suffix == ".parquet":
            check, detail = check_parquet(path)
            kind = "parquet"
        elif suffix == ".duckdb":
            check, detail = check_duckdb(path)
            kind = "duckdb"
        elif suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            check, detail = check_text(path)
            kind = "text"
        else:
            check, detail = check_binary(path)
            kind = suffix.lstrip(".") or "binary"
        return FileResult(relative(path, root), kind, path.stat().st_size, check, "PASS", detail)
    except Exception as exc:
        return FileResult(
            relative(path, root),
            suffix.lstrip(".") or "file",
            path.stat().st_size,
            "type-specific check",
            "FAIL",
            str(exc),
        )


def source_pdf_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    ledger_path = root / "data-gathering" / "source_ledger.csv"
    routing_path = root / "data" / "schemas" / "EXTRACTION-ROUTING.csv"
    pdf_root = root / "data" / "documents" / "pdf"
    with ledger_path.open("r", encoding="utf-8-sig", newline="") as handle:
        ledger = list(csv.DictReader(handle))
    with routing_path.open("r", encoding="utf-8-sig", newline="") as handle:
        routing = {row.get("file_id", ""): row for row in csv.DictReader(handle)}
    pdfs = {path.name: path for path in pdf_root.glob("*.pdf")}
    matched: set[str] = set()
    for row in ledger:
        file_id = row.get("file_id", "<blank>")
        route_row = routing.get(file_id, {})
        candidates = [
            Path(str(value).split("?", 1)[0]).name
            for value in [*row.values(), *route_row.values()]
            if value and str(value).split("?", 1)[0].casefold().endswith(".pdf")
        ]
        candidate_names = sorted({name for name in candidates if name in pdfs})
        if len(candidate_names) != 1:
            findings.append(
                Finding(
                    "ERROR",
                    "SOURCE_PDF_MATCH",
                    "data-gathering/source_ledger.csv",
                    f"{file_id} maps to {len(candidate_names)} local PDFs",
                )
            )
            continue
        name = candidate_names[0]
        matched.add(name)
        path = pdfs[name]
        expected_hash = (
            row.get("sha256")
            or row.get("source_sha256")
            or route_row.get("source_sha256")
            or route_row.get("sha256")
            or ""
        )
        if expected_hash and sha256(path).casefold() != expected_hash.casefold():
            findings.append(
                Finding("ERROR", "SOURCE_PDF_HASH", relative(path, root), f"{file_id} hash mismatch")
            )
        expected_pages = row.get("page_count", "") or route_row.get("page_count", "")
        if expected_pages:
            try:
                import fitz

                document = fitz.open(path)
                pages = document.page_count
                document.close()
                if pages != int(float(expected_pages)):
                    findings.append(
                        Finding(
                            "ERROR",
                            "SOURCE_PDF_PAGES",
                            relative(path, root),
                            f"{file_id}: ledger={expected_pages}; pdf={pages}",
                        )
                    )
            except Exception as exc:
                findings.append(
                    Finding("ERROR", "SOURCE_PDF_OPEN", relative(path, root), f"{file_id}: {exc}")
                )
    extra = sorted(set(pdfs) - matched)
    if extra:
        findings.append(
            Finding(
                "ERROR",
                "SOURCE_PDF_EXTRA",
                "data/documents/pdf",
                f"{len(extra)} PDFs lack a source-ledger match",
            )
        )
    if len(ledger) != 442:
        findings.append(
            Finding("ERROR", "SOURCE_LEDGER_COUNT", relative(ledger_path, root), f"rows={len(ledger)}")
        )
    if len(pdfs) != 442:
        findings.append(
            Finding("ERROR", "SOURCE_PDF_COUNT", relative(pdf_root, root), f"files={len(pdfs)}")
        )
    return findings


def readme_findings(root: Path, directories: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for directory in directories:
        readme = directory / "README.md"
        if not readme.is_file():
            findings.append(
                Finding("ERROR", "README_MISSING", relative(directory, root), "README.md is absent")
            )
            continue
        text = readme.read_text(encoding="utf-8-sig", errors="replace")
        # A folder guide is written for a reader. An HTML comment addressed to
        # a generator sits in front of that reader in every fork, so it fails
        # here. What each file is stays in the guide's prose and in
        # docs/PROJECT-MANIFEST.csv, which the manifest checks cover.
        if GENERATOR_MARKER.search(text):
            findings.append(
                Finding(
                    "ERROR",
                    "README_MARKER",
                    relative(readme, root),
                    "a generator marker is in a file a reader opens",
                )
            )
        if len(text.strip()) < 80 or not text.lstrip().startswith("#"):
            findings.append(
                Finding(
                    "ERROR",
                    "README_THIN",
                    relative(readme, root),
                    "the guide opens with no heading or says too little to describe the folder",
                )
            )
    return findings


def manifest_findings(
    root: Path,
    files: Sequence[Path],
    directories: Sequence[Path],
    manifest: dict[str, dict[str, str]],
) -> list[Finding]:
    findings: list[Finding] = []
    actual = {relative(path, root): path for path in [*files, *directories]}
    for key, path in actual.items():
        row = manifest.get(key)
        if row is None:
            findings.append(Finding("ERROR", "MANIFEST_MISSING", key, "path is absent from manifest"))
            continue
        expected_type = "file" if path.is_file() else "directory"
        if row.get("entry_type") != expected_type:
            findings.append(
                Finding("ERROR", "MANIFEST_TYPE", key, f"manifest={row.get('entry_type')}; actual={expected_type}")
            )
        if path.is_file() and key != "docs/PROJECT-MANIFEST.csv":
            if row.get("size_bytes") and int(row["size_bytes"]) != path.stat().st_size:
                findings.append(
                    Finding(
                        "ERROR",
                        "MANIFEST_SIZE",
                        key,
                        f"manifest={row['size_bytes']}; actual={path.stat().st_size}",
                    )
                )
            if row.get("sha256") and row["sha256"].casefold() != sha256(path).casefold():
                findings.append(Finding("ERROR", "MANIFEST_HASH", key, "SHA-256 mismatch"))
    for key in sorted(set(manifest) - set(actual)):
        findings.append(Finding("ERROR", "MANIFEST_ORPHAN", key, "manifest path is absent"))
    return findings


def git_findings(root: Path, manifest: dict[str, dict[str, str]]) -> list[Finding]:
    findings: list[Finding] = []
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
    for path in tracked:
        row = manifest.get(path)
        if row is None:
            findings.append(Finding("ERROR", "TRACKED_MANIFEST", path, "tracked file is absent from manifest"))
        elif row.get("repository_policy") != "TRACK":
            findings.append(
                Finding(
                    "ERROR",
                    "TRACKED_POLICY",
                    path,
                    f"repository_policy={row.get('repository_policy')}",
                )
            )
    return findings


def presentation_findings(root: Path) -> list[Finding]:
    """Reject stale claims and internal release text."""
    findings: list[Finding] = []
    targets = {
        root / "README.md",
        root / "PROCESS.md",
        root / "instructions" / "REVIEWER-GUIDE.md",
        *root.glob("docs/*.md"),
        *root.rglob("README.md"),
    }
    patterns = {
        r"C:\\Users\\Moses": "private machine path",
        r"Alts-Sample-Project": "source repository path",
        r"source-to-analysis path proven end to end": "false extracted-analytics completion claim",
        r"eight-part physical key": "superseded comparison-key claim",
        r"No Git repository has been created": "superseded repository-state claim",
        r"\b43[- ](?:column|field)s?\b": "superseded extraction width",
        r"\b2026-08-22\.1\b": "superseded extraction contract",
        r"\bweeks went\b": "work-history statement",
        r"\bcareless agent\b": "internal agent note",
        r"\bI am lost\b": "internal author note",
        r"\bmust be recovered\b": "internal repair note",
        r"\bthis was done twice\b": "work-history statement",
        r"\bTODO\b": "unfinished marker",
        r"\bFIXME\b": "unfinished marker",
        r"\bTBD\b": "unfinished marker",
    }
    timeline_targets = {
        root / "README.md",
        root / "PROCESS.md",
        root / "instructions" / "REVIEWER-GUIDE.md",
        root / "docs" / "STATUS.md",
        root / "docs" / "ARCHITECTURE.md",
        root / "docs" / "REPOSITORY-BOUNDARY.md",
    }
    timeline_patterns = {
        r"\bnow\b": "timeline word now",
        r"\btoday\b": "timeline word today",
        r"\bcurrently\b": "timeline word currently",
        r"\bearlier\b": "work-history word earlier",
        r"\bprevious(?:ly)?\b": "work-history word previous",
        r"\bretired\b": "work-history word retired",
        r"\bhistorical\b": "work-history word historical",
    }
    for path in sorted(targets):
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8-sig", errors="replace")
        for pattern, label in patterns.items():
            if re.search(pattern, source, flags=re.I):
                findings.append(
                    Finding("ERROR", "PRESENTATION_TEXT", relative(path, root), label)
                )
        if path in timeline_targets:
            for pattern, label in timeline_patterns.items():
                if re.search(pattern, source, flags=re.I):
                    findings.append(
                        Finding("ERROR", "PRESENTATION_TIMELINE", relative(path, root), label)
                    )
    return findings


def dashboard_findings(root: Path) -> list[Finding]:
    """The committed page is the reviewer's copy. It must exist and be one
    complete HTML document. The audit reads the tree and leaves it as it found
    it, so it never rebuilds the page here."""
    page = root / "dashboard.html"
    if not page.is_file():
        return [
            Finding(
                "ERROR",
                "DASHBOARD_PAGE",
                "dashboard.html",
                "the reviewer page is absent; run python -m src.dashboard.build_dashboard",
            )
        ]
    text = page.read_text(encoding="utf-8", errors="replace")
    low = text.casefold()
    findings: list[Finding] = []
    if "<html" not in low[:4000] or "</html>" not in low[-4000:]:
        findings.append(
            Finding("ERROR", "DASHBOARD_PAGE", "dashboard.html", "the page is not a complete HTML document")
        )
    for token in ("<title", "<style", "<script"):
        if token not in low:
            findings.append(
                Finding("ERROR", "DASHBOARD_PAGE", "dashboard.html", f"the page carries no {token}> element")
            )
    return findings

def audit(root: Path = PROJECT_ROOT) -> tuple[list[FileResult], list[Finding], Counter[str]]:
    root = root.resolve()
    files, directories = files_and_directories(root)
    if not MANIFEST_PATH.is_file():
        raise AuditError(f"Missing manifest: {MANIFEST_PATH}")
    manifest = read_manifest(MANIFEST_PATH)
    results = [check_file(path, root) for path in files]
    findings = [
        Finding("ERROR", "FILE_CHECK", result.path, result.detail)
        for result in results
        if result.status != "PASS"
    ]
    findings.extend(manifest_findings(root, files, directories, manifest))
    findings.extend(readme_findings(root, directories))
    findings.extend(git_findings(root, manifest))
    findings.extend(source_pdf_findings(root))
    findings.extend(presentation_findings(root))
    findings.extend(dashboard_findings(root))
    counts: Counter[str] = Counter(result.file_type for result in results)
    counts["files"] = len(files)
    counts["directories"] = len(directories)
    counts["bytes"] = sum(result.size_bytes for result in results)
    return results, sorted(findings, key=lambda item: (item.severity, item.code, item.path)), counts


def write_csv(path: Path, columns: Sequence[str], rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--results-csv", type=Path)
    args = parser.parse_args()
    try:
        results, findings, counts = audit(args.root)
    except (AuditError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}")
        return 1
    if args.results_csv:
        write_csv(
            args.results_csv.resolve(),
            ("path", "file_type", "size_bytes", "check", "status", "detail"),
            [result.__dict__ for result in results],
        )
    for finding in findings:
        print(f"{finding.severity}: {finding.code}: {finding.path}: {finding.message}")
    print(
        "CHECKED: "
        + "; ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    )
    if findings:
        print(f"FAIL: release audit found {len(findings)} issue(s)")
        return 1
    print("PASS: every project path passed its file, manifest, README, Git-policy, and source-ledger checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
