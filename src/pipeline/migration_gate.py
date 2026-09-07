"""Prove a transformation-migration batch changed no published byte.

Twelve rules, R01 to R12, read from ledgers/pipeline/migration-requirements.csv.
Rules R01 to R06 compare the working tree against the previous batch tag and
stop the gate on the first failure. R07 to R11 check the matrices, the legacy
asserts, and the receipts. R12 runs the release gates that already exist.
One line per rule, exit 1 on any FAIL.

Allowances are narrow on purpose. A batch may change the matrices, the records
every publish rewrites (receipts, the matrix check, the manifest, the lineage
file, the dashboard page), the two DuckDB files the publish rebuilds, and any
folder guide the generator writes and the structure check proves current. A
hand-written guide, any other database, and every other path must be named in
the batch's allowed-edit set.
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from src.common import matrices
from src.pipeline.transformation_lineage import missing_current_receipts
from src.repository.build_readmes import HAND_WRITTEN

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STATE = {"root": PROJECT_ROOT}

REQUIREMENTS_REL = "ledgers/pipeline/migration-requirements.csv"
DISPOSITIONS_REL = "ledgers/pipeline/migration-dispositions.csv"
RECEIPTS_REL = "ledgers/pipeline/transformation-receipts.csv"
CHECK_REL = "ledgers/pipeline/matrix-check.csv"
SITE_SNAPSHOT_REL = "ledgers/pipeline/migration-sites.csv"
BATCH_SCOPE_REL = "ledgers/pipeline/migration-batch-scope.csv"
MATRIX_ROOT_REL = "data/normalization/transformations"
PUBLISHED_ROOTS = ("data", "docs", "ledgers", "sql")
DIRECTORY_ROOTS = ("data", "docs", "ledgers", "instructions")
INVENTORIES = (
    "transformation-inventory.csv",
    "transformation-inventory-b.csv",
    "transformation-inventory-c.csv",
)
MASTER_INVENTORY = "master-transformation-inventory.md"
INVENTORY_TAGS = ("A", "B", "C")
LEGACY = re.compile(r"\b_LEGACY_(?:B(?P<batch>[1-4])_)?[A-Z0-9_]+\b")
CACHE_PARTS = {"__pycache__", ".pytest_cache"}
MASTER_ROW = re.compile(r"^\| (M\d{3}) \|")
INVENTORY_REFERENCE = re.compile(r"\b([ABC]):(T\d{3})\b")
EVIDENCE_LOCATION = re.compile(r"\b(src/[A-Za-z0-9_./-]+\.py):(\d+)\b")
SITE_COLUMNS = ("master_id", "source", "inventory_ids", "proposed_matrices", "evidence_locations")
BATCH_SCOPE_COLUMNS = ("batch", "source", "expected_sites")
DISPOSITION_COLUMNS = ("id", "disposition", "reason")
ALLOWED_DISPOSITIONS = {"structure"}

# The publish rebuilds these two databases on every run and their bytes are
# not stable; their content is proven by the parity checks in reviewer_check.
REBUILT_DATABASES = ("data/warehouse/extracted.duckdb", "data/warehouse/alts.duckdb")

# Paths every batch may change: the matrices and the records the release and
# the folder checks rewrite on every run.
ALWAYS_ALLOWED = (
    MATRIX_ROOT_REL + "/",
    RECEIPTS_REL,
    CHECK_REL,
    DISPOSITIONS_REL,
    "docs/PROJECT-MANIFEST.csv",
    "docs/CSV-LINEAGE.csv",
    "dashboard.html",
)

# Batch 0: the scaffold files, and the four hand-written guides that gained a
# row naming them.
BATCH_ZERO_ALLOWED = (
    "src/common/matrices.py",
    "src/pipeline/migration_gate.py",
    "src/pipeline/publish_review_release.py",
    "src/repository/build_readmes.py",
    "tests/test_transformation_matrices.py",
    "tests/test_migration_gate.py",
    REQUIREMENTS_REL,
    SITE_SNAPSHOT_REL,
    BATCH_SCOPE_REL,
    "data/normalization/README.md",
    "ledgers/pipeline/README.md",
    "src/README.md",
    "src/pipeline/README.md",
)


def configure(root: Path) -> None:
    """Point the gate at another checkout; the tests use a scratch repository."""

    _STATE["root"] = Path(root)


def root_dir() -> Path:
    return _STATE["root"]


@dataclass
class Result:
    rule: str
    passed: bool
    detail: str

    def line(self) -> str:
        return f"{self.rule} {'PASS' if self.passed else 'FAIL'}: {self.detail}"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def git(*args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root_dir(), text=True, capture_output=True, encoding="utf-8", errors="replace"
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def run(command: Sequence[str]) -> tuple[int, str]:
    completed = subprocess.run(
        list(command), cwd=root_dir(), text=True, capture_output=True, encoding="utf-8", errors="replace", env=_env()
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def read_requirements(path: Path | None = None) -> list[dict[str, str]]:
    with (path or root_dir() / REQUIREMENTS_REL).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def is_cache(path: str) -> bool:
    return any(part in CACHE_PARTS for part in path.split("/"))


def porcelain(base: str = "HEAD") -> tuple[set[str], set[str]]:
    """Tracked paths changed from ``base``, and untracked paths, repo-relative.

    ``git diff base`` compares the base tree with the working tree. It therefore
    covers committed batch changes and later working-tree corrections in one
    set. Git applies commit-time end-of-line normalization, so CRLF-only status
    entries remain outside the set. Interpreter and pytest caches are tool
    footprints and never project content.
    """

    changed: set[str] = set()
    untracked: set[str] = set()
    for line in git("status", "--porcelain=v1", "--untracked-files=all").splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if status == "??" and not is_cache(path):
            untracked.add(path)
    for line in git("diff", "--name-only", base).splitlines():
        path = line.strip()
        if path and not is_cache(path):
            changed.add(path)
    return changed, untracked


def is_generated_guide(path: str) -> bool:
    """A README.md the generator writes; the structure check proves it current."""

    if path != "README.md" and not path.endswith("/README.md"):
        return False
    folder = path[: -len("/README.md")] if "/" in path else "."
    return folder not in HAND_WRITTEN


def allowed(path: str, prefixes: Sequence[str]) -> bool:
    if is_generated_guide(path):
        return True
    for prefix in (*ALWAYS_ALLOWED, *prefixes):
        if path == prefix or (prefix.endswith("/") and path.startswith(prefix)) or path.startswith(prefix + "/"):
            return True
    return False


def under_published(path: str) -> bool:
    return any(path == root or path.startswith(root + "/") for root in PUBLISHED_ROOTS)


def tracked_at(ref: str) -> set[str]:
    return set(git("ls-tree", "-r", "--name-only", ref, "--", *PUBLISHED_ROOTS).splitlines())


def show(ref: str, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=root_dir(), text=True, capture_output=True, encoding="utf-8", errors="replace"
    )
    return completed.stdout if completed.returncode == 0 else None


def csv_shape(text: str) -> tuple[str, int]:
    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    return ",".join(header), sum(1 for _ in reader)


def rule_r01(base: str) -> Result:
    if not git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=False).strip():
        return Result("R01", False, f"previous-batch ref absent: {base}")
    tracked = tracked_at(base)
    missing = [path for path in sorted(tracked) if not (root_dir() / path).exists()]
    if missing:
        return Result("R01", False, f"{len(missing)} published path(s) missing: " + "; ".join(missing[:10]))
    return Result("R01", True, f"all {len(tracked)} published paths tracked at {base} exist")


def rule_r02_r03(base: str, changed: set[str], prefixes: Sequence[str]) -> tuple[Result, Result]:
    header_diffs: list[str] = []
    count_diffs: list[str] = []
    for path in sorted(changed):
        if not under_published(path) or not path.endswith(".csv") or allowed(path, prefixes):
            continue
        before = show(base, path)
        if before is None or not (root_dir() / path).is_file():
            continue
        after = (root_dir() / path).read_text(encoding="utf-8-sig")
        header_before, rows_before = csv_shape(before)
        header_after, rows_after = csv_shape(after)
        if header_before != header_after:
            header_diffs.append(path)
        if rows_before != rows_after:
            count_diffs.append(f"{path} ({rows_before} -> {rows_after})")
    r02 = Result("R02", not header_diffs, "every published CSV keeps its header" if not header_diffs else "header changed: " + "; ".join(header_diffs[:10]))
    r03 = Result("R03", not count_diffs, "every published CSV keeps its row count" if not count_diffs else "row count changed: " + "; ".join(count_diffs[:10]))
    return r02, r03


def rule_r04(changed: set[str], prefixes: Sequence[str]) -> Result:
    offenders = sorted(
        path
        for path in changed
        if under_published(path) and not allowed(path, prefixes) and path not in REBUILT_DATABASES
    )
    exempt = sorted(path for path in changed if path in REBUILT_DATABASES)
    if offenders:
        return Result("R04", False, f"{len(offenders)} published file(s) changed: " + "; ".join(offenders[:10]))
    note = f"; {len(exempt)} rebuilt DuckDB file(s) deferred to the parity checks in R12" if exempt else ""
    return Result("R04", True, "every published file outside the allowed set is byte-identical" + note)


def rule_r05(changed: set[str], untracked: set[str], prefixes: Sequence[str]) -> Result:
    offenders = sorted(
        path
        for path in changed | untracked
        if not allowed(path, prefixes) and path not in REBUILT_DATABASES
    )
    if offenders:
        return Result("R05", False, f"{len(offenders)} path(s) outside the allowed set: " + "; ".join(offenders[:10]))
    return Result("R05", True, f"{len(changed | untracked)} changed or new path(s), all inside the allowed set")


def rule_r06(paths: set[str], base: str = "HEAD") -> Result:
    new_dirs: set[str] = set()
    for path in paths:
        parts = path.split("/")
        if parts[0] not in DIRECTORY_ROOTS:
            continue
        for depth in range(1, len(parts)):
            folder = "/".join(parts[:depth])
            if folder == MATRIX_ROOT_REL or folder.startswith(MATRIX_ROOT_REL + "/"):
                continue
            if not git("ls-tree", "-d", base, "--", folder).strip():
                new_dirs.add(folder)
    if new_dirs:
        return Result("R06", False, "new folder(s): " + "; ".join(sorted(new_dirs)))
    return Result("R06", True, "no folder created outside the matrix root")


def matrix_root() -> Path:
    return root_dir() / MATRIX_ROOT_REL


def rule_r07() -> Result:
    errors = matrices.check(matrix_root())
    if errors:
        return Result("R07", False, "; ".join(errors[:10]))
    return Result("R07", True, f"{len(matrices.matrix_names(matrix_root()))} matrices parse with the shared columns")


def rule_r08() -> Result:
    code, output = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_transformation_matrices.py"])
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    return Result("R08", code == 0, tail)


def rule_r09(batch: int, retire_current: bool = False) -> Result:
    """Reject unversioned, prior-batch, and future-batch legacy literals.

    A batch may retain only its own ``_LEGACY_BN_`` symbols while shadow mode
    is active. This remains true when the current and prior batches edit the
    same module, so an allowed source path never hides an undeleted literal.
    ``retire_current`` is the final close gate and permits no current-batch
    symbols either.
    """

    hits: list[str] = []
    for path in sorted((root_dir() / "src").rglob("*.py")):
        rel = path.relative_to(root_dir()).as_posix()
        if "dashboard" in path.parts or is_cache(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            hits.append(f"{rel}:{exc.lineno}:syntax-error")
            continue
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                names = [part.id for part in ast.walk(target) if isinstance(part, ast.Name)]
                for name in names:
                    match = LEGACY.fullmatch(name)
                    if not match:
                        continue
                    owner = match.group("batch")
                    invalid = owner is None or int(owner) != batch or retire_current
                    if invalid:
                        hits.append(f"{rel}:{node.lineno}:{name}")
    if hits:
        allowed_state = "none" if retire_current else f"_LEGACY_B{batch}_* only"
        return Result(
            "R09",
            False,
            f"{len(hits)} invalid _LEGACY_ hit(s); allowed state is {allowed_state}: "
            + "; ".join(hits[:10]),
        )
    detail = "no _LEGACY_ symbol survives" if retire_current else f"only _LEGACY_B{batch}_* symbols may remain"
    return Result("R09", True, detail)


def inventory_rows(roadmap: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for tag, name in zip(INVENTORY_TAGS, INVENTORIES):
        path = roadmap / name
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                match = re.search(r"\d+", row.get("line", "") or "")
                rows.append(
                    {
                        "id": f"{tag}:{row.get('id', '')}",
                        "source": row.get("source", ""),
                        "line": int(match.group()) if match else -1,
                        "symbol": row.get("symbol", ""),
                        "proposed_matrix": (row.get("proposed_matrix", "") or "").strip(),
                    }
                )
    return rows


def master_sites(roadmap: Path) -> list[dict[str, object]]:
    """Read the verified 424-site merge and prove it covers A, B, and C once."""

    rows = inventory_rows(roadmap)
    by_id = {row["id"]: row for row in rows}
    master_path = roadmap / MASTER_INVENTORY
    if not master_path.is_file():
        raise ValueError(f"master inventory absent: {master_path}")
    in_union = False
    seen_refs: list[str] = []
    sites: list[dict[str, object]] = []
    for line in master_path.read_text(encoding="utf-8-sig").splitlines():
        if line == "## 8. Union inventory":
            in_union = True
            continue
        if in_union and line.startswith("## "):
            break
        match = MASTER_ROW.match(line) if in_union else None
        if not match:
            continue
        master_id = match.group(1)
        refs = [f"{tag}:{row_id}" for tag, row_id in INVENTORY_REFERENCE.findall(line)]
        if not refs:
            raise ValueError(f"{master_id}: no A/B/C inventory references")
        unknown = [ref for ref in refs if ref not in by_id]
        if unknown:
            raise ValueError(f"{master_id}: unknown inventory reference(s): {', '.join(unknown)}")
        group = [by_id[ref] for ref in refs]
        sources = {str(row["source"]) for row in group}
        if len(sources) != 1:
            raise ValueError(f"{master_id}: merged references disagree on source: {', '.join(sorted(sources))}")
        sites.append(
            {
                "id": master_id,
                "source": next(iter(sources)),
                "rows": group,
                "proposals": sorted(
                    {
                        str(row["proposed_matrix"])
                        for row in group
                        if str(row["proposed_matrix"]).startswith(MATRIX_ROOT_REL + "/")
                    }
                ),
                "evidence": {
                    (str(row["source"]), int(row["line"]))
                    for row in group
                    if int(row["line"]) >= 0
                },
            }
        )
        seen_refs.extend(refs)
    if not sites:
        raise ValueError(f"{master_path}: section 8 has no master rows")
    duplicates = sorted(ref for ref, count in Counter(seen_refs).items() if count != 1)
    missing = sorted(set(by_id) - set(seen_refs))
    if duplicates or missing:
        detail = []
        if duplicates:
            detail.append("duplicate references " + ", ".join(duplicates[:10]))
        if missing:
            detail.append("missing references " + ", ".join(missing[:10]))
        raise ValueError(f"{master_path}: " + "; ".join(detail))
    return sites


def write_site_snapshot(roadmap: Path, path: Path | None = None) -> int:
    """Freeze the verified master merge into the tracked migration input."""

    sites = master_sites(roadmap)
    target = path or root_dir() / SITE_SNAPSHOT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SITE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for site in sites:
            writer.writerow(
                {
                    "master_id": site["id"],
                    "source": site["source"],
                    "inventory_ids": "|".join(str(row["id"]) for row in site["rows"]),
                    "proposed_matrices": "|".join(str(value) for value in site["proposals"]),
                    "evidence_locations": "|".join(
                        f"{source}:{line}" for source, line in sorted(site["evidence"])
                    ),
                }
            )
    return len(sites)


def read_site_snapshot(path: Path | None = None) -> list[dict[str, object]]:
    """Read the tracked site list and reject omissions, duplicate ids, and malformed rows."""

    target = path or root_dir() / SITE_SNAPSHOT_REL
    if not target.is_file():
        raise ValueError(f"migration site snapshot absent: {target}")
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != SITE_COLUMNS:
            raise ValueError(f"{target}: header must be {','.join(SITE_COLUMNS)}")
        raw_rows = list(reader)
    if not raw_rows:
        raise ValueError(f"{target}: no master sites")
    sites: list[dict[str, object]] = []
    seen_master: set[str] = set()
    seen_inventory: set[str] = set()
    for number, row in enumerate(raw_rows, 2):
        master_id = (row.get("master_id") or "").strip()
        source = (row.get("source") or "").strip()
        inventory_ids = [value for value in (row.get("inventory_ids") or "").split("|") if value]
        proposals = [value for value in (row.get("proposed_matrices") or "").split("|") if value]
        evidence = evidence_locations(row.get("evidence_locations") or "")
        if not re.fullmatch(r"M\d{3}", master_id):
            raise ValueError(f"{target}:{number}: invalid master_id {master_id!r}")
        if master_id in seen_master:
            raise ValueError(f"{target}:{number}: duplicate master_id {master_id}")
        if not source.startswith("src/") or not source.endswith(".py"):
            raise ValueError(f"{target}:{number}: invalid source {source!r}")
        if not inventory_ids or any(not re.fullmatch(r"[ABC]:T\d{3}", value) for value in inventory_ids):
            raise ValueError(f"{target}:{number}: invalid inventory_ids")
        duplicate_inventory = sorted(set(inventory_ids) & seen_inventory)
        if duplicate_inventory:
            raise ValueError(f"{target}:{number}: repeated inventory id(s): {', '.join(duplicate_inventory)}")
        if any(not value.startswith(MATRIX_ROOT_REL + "/") for value in proposals):
            raise ValueError(f"{target}:{number}: proposed matrix outside {MATRIX_ROOT_REL}")
        if not evidence or any(location[0] != source for location in evidence):
            raise ValueError(f"{target}:{number}: evidence_locations must cite {source}")
        seen_master.add(master_id)
        seen_inventory.update(inventory_ids)
        sites.append(
            {
                "id": master_id,
                "source": source,
                "inventory_ids": inventory_ids,
                "proposals": proposals,
                "evidence": evidence,
            }
        )
    return sites


def read_batch_scope(
    sites: Sequence[dict[str, object]] | None = None, path: Path | None = None
) -> dict[str, int]:
    """Read the tracked source-to-batch assignment and reconcile every count."""

    target = path or root_dir() / BATCH_SCOPE_REL
    if not target.is_file():
        raise ValueError(f"migration batch scope absent: {target}")
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != BATCH_SCOPE_COLUMNS:
            raise ValueError(f"{target}: header must be {','.join(BATCH_SCOPE_COLUMNS)}")
        rows = list(reader)
    assignments: dict[str, int] = {}
    expected: dict[str, int] = {}
    for number, row in enumerate(rows, 2):
        source = (row.get("source") or "").strip()
        try:
            batch = int((row.get("batch") or "").strip())
            count = int((row.get("expected_sites") or "").strip())
        except ValueError as exc:
            raise ValueError(f"{target}:{number}: batch and expected_sites must be integers") from exc
        if batch not in {1, 2, 3, 4}:
            raise ValueError(f"{target}:{number}: batch must be 1, 2, 3, or 4")
        if not source.startswith("src/") or not source.endswith(".py"):
            raise ValueError(f"{target}:{number}: invalid source {source!r}")
        if source in assignments:
            raise ValueError(f"{target}:{number}: duplicate source {source}")
        if count < 1:
            raise ValueError(f"{target}:{number}: expected_sites must be positive")
        assignments[source] = batch
        expected[source] = count
    actual = Counter(
        str(site["source"])
        for site in (sites if sites is not None else read_site_snapshot())
    )
    missing = sorted(set(actual) - set(assignments))
    extra = sorted(set(assignments) - set(actual))
    wrong = sorted(
        source for source in set(actual) & set(expected) if actual[source] != expected[source]
    )
    if missing or extra or wrong:
        detail: list[str] = []
        if missing:
            detail.append("unassigned " + ", ".join(missing[:8]))
        if extra:
            detail.append("unknown " + ", ".join(extra[:8]))
        if wrong:
            detail.append(
                "count mismatch "
                + ", ".join(f"{source} ({expected[source]} != {actual[source]})" for source in wrong[:8])
            )
        raise ValueError(f"{target}: " + "; ".join(detail))
    return assignments


def evidence_locations(text: str) -> set[tuple[str, int]]:
    return {(source, int(line)) for source, line in EVIDENCE_LOCATION.findall(text.replace("\\", "/"))}


def matrix_evidence(target: str) -> set[tuple[str, int]]:
    """Every Python location cited by the rows of one valid matrix."""

    path = root_dir() / target
    if not path.is_file():
        return set()
    try:
        rows = matrices.load(path.stem, path.parent)
    except matrices.MatrixError:
        return set()
    return set().union(*(evidence_locations(row.get("evidence", "")) for row in rows))


def read_dispositions() -> set[str]:
    path = root_dir() / DISPOSITIONS_REL
    if not path.is_file():
        return set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != DISPOSITION_COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(DISPOSITION_COLUMNS)}")
        rows = list(reader)
    dispositions: set[str] = set()
    for number, row in enumerate(rows, 2):
        master_id = (row.get("id") or "").strip()
        disposition = (row.get("disposition") or "").strip()
        reason = (row.get("reason") or "").strip()
        if not re.fullmatch(r"M\d{3}", master_id):
            raise ValueError(f"{path}:{number}: invalid id {master_id!r}")
        if master_id in dispositions:
            raise ValueError(f"{path}:{number}: duplicate id {master_id}")
        if disposition not in ALLOWED_DISPOSITIONS:
            raise ValueError(
                f"{path}:{number}: disposition must be one of {', '.join(sorted(ALLOWED_DISPOSITIONS))}"
            )
        if not reason:
            raise ValueError(f"{path}:{number}: blank reason")
        dispositions.add(master_id)
    return dispositions


def rule_r10(batch: int) -> Result:
    uncovered: list[str] = []
    counted = 0
    try:
        sites = read_site_snapshot()
        assignments = read_batch_scope(sites)
        dispositions = read_dispositions()
    except ValueError as exc:
        return Result("R10", False, str(exc))
    known_ids = {str(site["id"]) for site in sites}
    unknown_dispositions = sorted(dispositions - known_ids)
    if unknown_dispositions:
        return Result("R10", False, "unknown disposition id(s): " + ", ".join(unknown_dispositions))
    for site in sites:
        source = str(site["source"])
        if assignments[source] > batch:
            continue
        counted += 1
        master_id = str(site["id"])
        proposals = list(site["proposals"])
        if not proposals:
            if master_id not in dispositions:
                uncovered.append(f"{master_id} has no proposed matrix and no structure disposition")
            continue
        evidence = set(site["evidence"])
        cited = set().union(*(matrix_evidence(target) for target in proposals))
        if evidence <= cited:
            continue
        if master_id in dispositions:
            continue
        missing = sorted(evidence - cited)
        locations = "|".join(f"{source}:{line}" for source, line in missing)
        uncovered.append(f"{master_id} missing {locations} -> {', '.join(proposals)}")
    if uncovered:
        return Result("R10", False, f"{len(uncovered)} of {counted} site(s) without a source-citing matrix row or a disposition: " + "; ".join(uncovered[:8]))
    return Result(
        "R10",
        True,
        f"{counted} of {len(sites)} master sites assigned through batch {batch} carry all source lines or a structure disposition",
    )


def rule_r11() -> Result:
    missing = missing_current_receipts([root_dir() / CHECK_REL], receipt_path=root_dir() / RECEIPTS_REL, root=root_dir())
    if missing:
        return Result("R11", False, "matrix check record without a current receipt: " + ", ".join(missing))
    return Result("R11", True, f"{CHECK_REL} carries a current PASS receipt")


def rule_r12(test_floor: int, reviewer_floor: int) -> Result:
    parts: list[str] = []
    ok = True
    code, output = run([sys.executable, "-m", "src.pipeline.reviewer_check"])
    match = re.search(r"PASS: (\d+) reviewer baseline checks", output)
    count = int(match.group(1)) if match else 0
    if code != 0 or count < reviewer_floor:
        ok = False
        parts.append(f"reviewer_check {count} checks (floor {reviewer_floor}) exit {code}")
    else:
        parts.append(f"reviewer_check {count} PASS")
    code, output = run([sys.executable, "-m", "src.repository.release_audit"])
    if code != 0 or "PASS:" not in output:
        ok = False
        tail = output.strip().splitlines()[-1][:160] if output.strip() else ""
        parts.append(f"release_audit FAIL: {tail}")
    else:
        parts.append("release_audit PASS")
    code, output = run([sys.executable, "-m", "src.repository.check_project_structure", "--verify-hashes"])
    if code != 0:
        ok = False
        parts.append("check_project_structure FAIL: " + "; ".join(line for line in output.splitlines() if line.startswith("FAIL"))[:300])
    else:
        parts.append("check_project_structure PASS")
    code, output = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    summary = output.strip().splitlines()[-1] if output.strip() else ""
    passed = int(match.group(1)) if (match := re.search(r"(\d+) passed", summary)) else 0
    failed = int(match.group(1)) if (match := re.search(r"(\d+) failed", summary)) else 0
    if code != 0 or failed or passed < test_floor:
        ok = False
        parts.append(f"pytest {summary} (floor {test_floor} passed, 0 failed)")
    else:
        parts.append(f"pytest {summary}")
    return Result("R12", ok, "; ".join(parts))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, required=True, help="batch number; rules with batch_from above it are skipped")
    parser.add_argument("--base", default=None, help="git ref of the previous batch; default migration-batch-(N-1), or v2 for batch 0")
    parser.add_argument("--allowed", action="append", default=[], help="repo-relative file or folder prefix the batch may change; repeat per entry")
    parser.add_argument("--done", action="append", default=[], help="deprecated compatibility option; R10 reads the tracked batch scope")
    parser.add_argument("--retire-current", action="store_true", help="final close: R09 permits no current-batch _LEGACY_ symbols")
    parser.add_argument("--test-floor", type=int, default=265)
    parser.add_argument("--reviewer-floor", type=int, default=144)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base = args.base or (f"migration-batch-{args.batch - 1}" if args.batch > 0 else "v2")
    prefixes = list(args.allowed) + (list(BATCH_ZERO_ALLOWED) if args.batch == 0 else [])
    if args.batch > 0:
        try:
            sites = read_site_snapshot()
            assignments = read_batch_scope(sites)
        except ValueError as exc:
            print(f"R10 FAIL: {exc}")
            return 1
        required = sorted(source for source, owner in assignments.items() if owner == args.batch)
        missing = [source for source in required if source not in args.allowed]
        if missing:
            print(
                f"FAIL: --allowed must name all {len(required)} batch {args.batch} source files; "
                f"missing: " + "; ".join(missing)
            )
            return 1
    requirements = {row["id"]: row for row in read_requirements()}
    active = {rule_id for rule_id, row in requirements.items() if int(row["batch_from"]) <= args.batch}
    results: list[Result] = [rule_r01(base)]
    if not results[0].passed:
        print(results[0].line())
        print("FAIL: an output-destination rule failed; the remaining rules did not run")
        return 1
    changed, untracked = porcelain(base)

    r02, r03 = rule_r02_r03(base, changed, prefixes)
    results.extend(
        [
            r02,
            r03,
            rule_r04(changed, prefixes),
            rule_r05(changed, untracked, prefixes),
            rule_r06(changed | untracked, base),
        ]
    )
    for result in results:
        print(result.line())
    if any(not result.passed for result in results):
        print("FAIL: an output-destination rule failed; the remaining rules did not run")
        return 1

    later = [
        ("R07", rule_r07),
        ("R08", rule_r08),
        ("R09", lambda: rule_r09(args.batch, args.retire_current)),
        ("R10", lambda: rule_r10(args.batch)),
        ("R11", rule_r11),
        ("R12", lambda: rule_r12(args.test_floor, args.reviewer_floor)),
    ]
    for rule_id, action in later:
        if rule_id not in active:
            print(f"{rule_id} SKIP: batch_from {requirements[rule_id]['batch_from']} is after batch {args.batch}")
            continue
        result = action()
        results.append(result)
        print(result.line())
    failed = [result.rule for result in results if not result.passed]
    if failed:
        print(f"FAIL: {', '.join(failed)}")
        return 1
    print(f"PASS: batch {args.batch} against {base}; {len(results)} rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
