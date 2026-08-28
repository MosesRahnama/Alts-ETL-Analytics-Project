"""Keep every stage file and record each input-to-output edge.

Live outputs keep stable names. Before a stage replaces one, the prior bytes are
copied into the content-addressed archive. The receipt ledger is append-only by
receipt ID: rerunning the same inputs into the same output adds no duplicate,
while any changed input or output creates a new row.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, TypeVar


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = Path(
    os.environ.get(
        "ALTS_ARTIFACT_ARCHIVE",
        str(PROJECT_ROOT.parent / "Alts-ETL-Analytics-Project-Artifact-Archive"),
    )
)
RECEIPT_PATH = PROJECT_ROOT / "ledgers" / "pipeline" / "transformation-receipts.csv"
PIPELINE_CONTRACT_VERSION = "2026-08-26.1"
# A stage failure carries its whole error text. One gate that reports a message
# per benchmark row produced a three-million-character cell, repeated on every
# receipt that shared the failure, and the ledger grew to 32 MB of which 91 per
# cent was that one string. The cell now keeps a readable head and the full text
# goes to the content-addressed archive the ledger already uses, so the record
# survives at its own address and the ledger stays readable.
NOTE_LIMIT = 2000

RECEIPT_COLUMNS = (
    "receipt_id",
    "stage_order",
    "stage_id",
    "command",
    "contract_version",
    "input_artifacts",
    "predecessor_receipt_ids",
    "output_path",
    "prior_output_sha256",
    "prior_output_object_path",
    "output_sha256",
    "output_object_path",
    "output_rows",
    "status",
    "recorded_at_utc",
    "notes",
)


class LineageError(RuntimeError):
    """Raised when an artifact or receipt violates the lineage contract."""


@dataclass(frozen=True)
class ArtifactState:
    path: Path
    display_path: str
    sha256: str
    object_path: str
    rows: str


T = TypeVar("T")


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def display_path(path: Path, root: Path = PROJECT_ROOT) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def object_locator(path: Path, root: Path = PROJECT_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return f"external-artifact://{path.name}"


def csv_rows(path: Path) -> str:
    if path.suffix.casefold() != ".csv":
        return ""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        if next(reader, None) is None:
            raise LineageError(f"CSV has no header: {path}")
        return str(sum(1 for _ in reader))


def snapshot(
    path: Path,
    *,
    archive_dir: Path = ARCHIVE_DIR,
    root: Path = PROJECT_ROOT,
) -> ArtifactState:
    path = path.resolve()
    if not path.is_file():
        raise LineageError(f"artifact is missing: {path}")
    sha = digest(path)
    suffix = path.suffix.casefold() or ".bin"
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / f"sha256-{sha}{suffix}"
    if target.exists():
        if digest(target) != sha:
            raise LineageError(f"content-addressed object is corrupt: {target}")
    else:
        shutil.copyfile(path, target)
        if digest(target) != sha:
            target.unlink(missing_ok=True)
            raise LineageError(f"archived copy failed its hash check: {target}")
    return ArtifactState(
        path=path,
        display_path=display_path(path, root),
        sha256=sha,
        object_path=object_locator(target, root),
        rows=csv_rows(path),
    )


def _read_receipts(path: Path = RECEIPT_PATH) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    # A ledger written before the note limit can still carry a multi-megabyte
    # cell, so the reader stays wide enough to compact one.
    csv.field_size_limit(64 * 1024 * 1024)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RECEIPT_COLUMNS:
            raise LineageError(f"receipt header drift at {path}")
        return [dict(row) for row in reader]


def _write_receipts(rows: list[dict[str, str]], path: Path = RECEIPT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECEIPT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in RECEIPT_COLUMNS} for row in rows)


def store_note(
    text: str,
    *,
    archive_dir: Path = ARCHIVE_DIR,
    root: Path = PROJECT_ROOT,
    limit: int = NOTE_LIMIT,
) -> str:
    """Keep a short note as written. Send a long one to the archive and leave a
    head plus its object address, so the receipt stays readable and the full
    text keeps a permanent home."""

    if len(text) <= limit:
        return text
    payload = text.encode("utf-8")
    sha = hashlib.sha256(payload).hexdigest()
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / f"sha256-{sha}.txt"
    if not target.exists():
        target.write_bytes(payload)
    locator = object_locator(target, root)
    head = text[:limit].rstrip()
    return f"{head} [truncated at {limit} characters; full text {len(text)} characters at {locator}]"


def compact_notes(
    *,
    receipt_path: Path = RECEIPT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    root: Path = PROJECT_ROOT,
    limit: int = NOTE_LIMIT,
) -> dict[str, int]:
    """Apply the note limit to receipts already written. Receipt IDs, hashes,
    and row order are untouched; only oversized note text moves to the archive."""

    rows = _read_receipts(receipt_path)
    moved = 0
    freed = 0
    for row in rows:
        note = row.get("notes", "")
        if len(note) > limit:
            replacement = store_note(note, archive_dir=archive_dir, root=root, limit=limit)
            freed += len(note) - len(replacement)
            row["notes"] = replacement
            moved += 1
    if moved:
        _write_receipts(rows, receipt_path)
    return {"receipts": len(rows), "notes_archived": moved, "characters_freed": freed}


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _receipt_id(
    stage_id: str,
    command: str,
    contract_version: str,
    input_artifacts: str,
    output_path: str,
    output_sha256: str,
    status: str,
) -> str:
    payload = "|".join(
        (
            stage_id,
            command,
            contract_version,
            input_artifacts,
            output_path,
            output_sha256,
            status,
        )
    )
    return "TR_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _append_stage_receipts(
    *,
    stage_id: str,
    stage_order: int,
    command: str,
    inputs: list[ArtifactState],
    prior_outputs: dict[str, ArtifactState],
    outputs: list[ArtifactState],
    contract_version: str,
    status: str,
    recorded_at_utc: str,
    notes: str,
    receipt_path: Path,
) -> list[dict[str, str]]:
    existing = _read_receipts(receipt_path)
    existing_ids = {row["receipt_id"] for row in existing}
    output_index = {
        (row["output_path"], row["output_sha256"]): row["receipt_id"]
        for row in existing
        if row.get("status") == "PASS"
    }
    input_artifacts = " | ".join(
        f"{state.display_path}#{state.sha256}" for state in sorted(inputs, key=lambda item: item.display_path)
    )
    predecessors = " | ".join(
        sorted(
            receipt_id
            for state in inputs
            if (receipt_id := output_index.get((state.display_path, state.sha256)))
        )
    )
    added: list[dict[str, str]] = []
    for state in sorted(outputs, key=lambda item: item.display_path):
        receipt_id = _receipt_id(
            stage_id,
            command,
            contract_version,
            input_artifacts,
            state.display_path,
            state.sha256,
            status,
        )
        if receipt_id in existing_ids:
            continue
        prior = prior_outputs.get(state.display_path)
        row = {
            "receipt_id": receipt_id,
            "stage_order": str(stage_order),
            "stage_id": stage_id,
            "command": command,
            "contract_version": contract_version,
            "input_artifacts": input_artifacts,
            "predecessor_receipt_ids": predecessors,
            "output_path": state.display_path,
            "prior_output_sha256": prior.sha256 if prior else "",
            "prior_output_object_path": prior.object_path if prior else "",
            "output_sha256": state.sha256,
            "output_object_path": state.object_path,
            "output_rows": state.rows,
            "status": status,
            "recorded_at_utc": recorded_at_utc,
            "notes": store_note(notes),
        }
        existing.append(row)
        existing_ids.add(receipt_id)
        added.append(row)
    if added:
        _write_receipts(existing, receipt_path)
    return added


def run_stage(
    *,
    stage_id: str,
    stage_order: int,
    command: str,
    inputs: Iterable[Path],
    outputs: Iterable[Path],
    action: Callable[[], T],
    contract_version: str = PIPELINE_CONTRACT_VERSION,
    recorded_at_utc: str | None = None,
    receipt_path: Path = RECEIPT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    root: Path = PROJECT_ROOT,
) -> tuple[T, list[dict[str, str]]]:
    """Run one stage, preserving inputs and both versions of each output."""

    input_paths = [Path(path) for path in inputs]
    output_paths = [Path(path) for path in outputs]
    input_states = [snapshot(path, archive_dir=archive_dir, root=root) for path in input_paths]
    prior_outputs = {
        display_path(path, root): snapshot(path, archive_dir=archive_dir, root=root)
        for path in output_paths
        if path.is_file()
    }
    stamp = recorded_at_utc or _timestamp()
    try:
        result = action()
    except Exception as exc:
        failed_outputs = [
            snapshot(path, archive_dir=archive_dir, root=root)
            for path in output_paths
            if path.is_file()
        ]
        _append_stage_receipts(
            stage_id=stage_id,
            stage_order=stage_order,
            command=command,
            inputs=input_states,
            prior_outputs=prior_outputs,
            outputs=failed_outputs,
            contract_version=contract_version,
            status="FAIL",
            recorded_at_utc=stamp,
            notes=f"{type(exc).__name__}: {exc}",
            receipt_path=receipt_path,
        )
        raise
    missing = [path for path in output_paths if not path.is_file()]
    if missing:
        raise LineageError(
            f"{stage_id} did not write declared output(s): "
            + ", ".join(str(path) for path in missing)
        )
    output_states = [snapshot(path, archive_dir=archive_dir, root=root) for path in output_paths]
    receipts = _append_stage_receipts(
        stage_id=stage_id,
        stage_order=stage_order,
        command=command,
        inputs=input_states,
        prior_outputs=prior_outputs,
        outputs=output_states,
        contract_version=contract_version,
        status="PASS",
        recorded_at_utc=stamp,
        notes="",
        receipt_path=receipt_path,
    )
    return result, receipts


def missing_current_receipts(
    paths: Iterable[Path],
    *,
    receipt_path: Path = RECEIPT_PATH,
    root: Path = PROJECT_ROOT,
) -> list[str]:
    """Current outputs with no matching PASS receipt."""

    indexed = {
        (row["output_path"], row["output_sha256"])
        for row in _read_receipts(receipt_path)
        if row.get("status") == "PASS"
    }
    missing = []
    for path in paths:
        if not path.is_file():
            missing.append(f"{display_path(path, root)}:missing")
            continue
        key = (display_path(path, root), digest(path))
        if key not in indexed:
            missing.append(key[0])
    return missing


def receipt_errors(
    *,
    receipt_path: Path = RECEIPT_PATH,
    root: Path = PROJECT_ROOT,
    archive_dir: Path = ARCHIVE_DIR,
    require_objects: bool = True,
) -> list[str]:
    """Validate receipt structure and, when requested, external artifact bytes."""

    rows = _read_receipts(receipt_path)
    errors: list[str] = []
    seen: set[str] = set()
    pass_ids = {row["receipt_id"] for row in rows if row.get("status") == "PASS"}
    for row in rows:
        receipt_id = row.get("receipt_id", "")
        if not receipt_id or receipt_id in seen:
            errors.append(f"duplicate or blank receipt_id: {receipt_id or '<blank>'}")
        seen.add(receipt_id)
        predecessors = [
            value.strip()
            for value in row.get("predecessor_receipt_ids", "").split("|")
            if value.strip()
        ]
        missing_predecessors = sorted(set(predecessors) - pass_ids)
        if missing_predecessors:
            errors.append(f"{receipt_id}: missing PASS predecessor {missing_predecessors[0]}")
        input_items = [
            value.strip()
            for value in row.get("input_artifacts", "").split("|")
            if value.strip()
        ]
        for item in input_items:
            if "#" not in item:
                errors.append(f"{receipt_id}: malformed input artifact")
                continue
            input_path, expected = item.rsplit("#", 1)
            if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
                errors.append(f"{receipt_id}: malformed input hash")
                continue
            if not require_objects:
                continue
            suffix = Path(input_path).suffix.casefold() or ".bin"
            target = archive_dir / f"sha256-{expected}{suffix}"
            if not target.is_file():
                errors.append(f"{receipt_id}: archived input is missing: {input_path}")
            elif digest(target) != expected:
                errors.append(f"{receipt_id}: archived input hash differs: {input_path}")
        for hash_field, path_field in (
            ("prior_output_sha256", "prior_output_object_path"),
            ("output_sha256", "output_object_path"),
        ):
            expected = row.get(hash_field, "")
            object_path = row.get(path_field, "")
            if not expected:
                if object_path:
                    errors.append(f"{receipt_id}: object path without {hash_field}")
                continue
            if not object_path:
                errors.append(f"{receipt_id}: {path_field} is blank")
                continue
            if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
                errors.append(f"{receipt_id}: malformed {hash_field}")
                continue
            if not require_objects:
                continue
            if object_path.startswith("external-artifact://"):
                target = archive_dir / object_path.removeprefix("external-artifact://")
            else:
                target = root / Path(object_path)
                if not target.is_file():
                    target = archive_dir / Path(object_path).name
            if not target.is_file():
                errors.append(f"{receipt_id}: archived object is missing: {object_path}")
            elif digest(target) != expected:
                errors.append(f"{receipt_id}: archived object hash differs: {object_path}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-path", type=Path, default=RECEIPT_PATH)
    parser.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR)
    parser.add_argument("--structure-only", action="store_true")
    parser.add_argument(
        "--compact-notes",
        action="store_true",
        help="Move oversized receipt notes into the archive and leave a head plus its address.",
    )
    args = parser.parse_args(argv)
    if args.compact_notes:
        result = compact_notes(receipt_path=args.receipt_path, archive_dir=args.archive_dir)
        print(
            f"COMPACTED: {result['notes_archived']} of {result['receipts']} receipts, "
            f"{result['characters_freed']} characters archived"
        )
        return 0
    errors = receipt_errors(
        receipt_path=args.receipt_path,
        archive_dir=args.archive_dir,
        require_objects=not args.structure_only,
    )
    if errors:
        print("FAIL: " + "; ".join(errors[:10]))
        return 1
    mode = "receipt structure" if args.structure_only else "external artifact archive"
    print(f"PASS: {mode} is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
