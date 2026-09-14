"""Context-review suggestions written only to RAG runtime output."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from .citations import rounding_note
from .paths import review_csv_path
from .store import Store
from .types import QueryScope

COLUMNS = [
    "suggestion_id",
    "request_id",
    "file_id",
    "observation_id",
    "field",
    "claimed_value",
    "proposed_value",
    "assessment",
    "evidence_ids",
    "source_version",
    "reason",
    "method",
    "review_state",
]

NOTE_FIELDS = ("definition", "condition", "fee_basis", "method")


def _existing_quotes(project_root: Path, file_id: str) -> set[str]:
    path = project_root / "data" / "extracted" / "tables" / "fact_observation.csv"
    quotes: set[str] = set()
    if not path.is_file():
        return quotes
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("document_id") != file_id:
                continue
            quotes.add((row.get("evidence_quote") or "").strip().lower())
            quotes.add((row.get("text_raw") or "").strip().lower())
    return quotes


def context_suggestions(
    store: Store,
    scope: QueryScope,
    file_id: str,
    request_id: str,
    project_root: Path,
    runtime: Path,
) -> list[dict]:
    if scope.role != "reviewer" or file_id not in scope.permitted_document_ids:
        raise PermissionError("ACCESS_DENIED")
    document = store.document(file_id)
    if document is None:
        return []
    quotes = _existing_quotes(project_root, file_id)
    rows = []
    for block in store.blocks_for(file_id):
        if block["block_kind"] not in {"note", "footnote", "paragraph"}:
            continue
        text = block["original_text"].strip()
        if len(text) < (8 if block["block_kind"] == "footnote" else 40):
            continue
        lowered = text.lower()
        if block["block_kind"] != "footnote" and not any(token in lowered for token in ("note", "definition", "provided that", "subject to", "round", "fee", "net of", "gross of", "dietz")):
            continue
        duplicate = any(lowered[:80] in quote or quote[:80] in lowered for quote in quotes if quote)
        field = "fee_basis" if "fee" in lowered or "net of" in lowered else "method" if "dietz" in lowered or "irr" in lowered else "definition"
        if rounding_note(text) or (block["block_kind"] == "footnote" and "as of" in lowered):
            field = "condition"
        suggestion_id = hashlib.sha256(
            f"{file_id}:{document['source_version']}:{block['block_id']}:{field}".encode()
        ).hexdigest()[:16]
        rows.append(
            {
                "suggestion_id": suggestion_id,
                "request_id": request_id,
                "file_id": file_id,
                "observation_id": "",
                "field": field,
                "claimed_value": "",
                "proposed_value": text[:400],
                "assessment": "INSUFFICIENT_EVIDENCE",
                "evidence_ids": block["block_id"],
                "source_version": document["source_version"],
                "reason": "duplicate candidate under different wording" if duplicate else "Indexed note or condition may be absent from recorded passages.",
                "method": "context-review:v1",
                "review_state": "duplicate_candidate" if duplicate else "proposed",
            }
        )
    path = review_csv_path(runtime)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file()
    existing_ids: set[str] = set()
    if not new_file:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            existing_ids = {row.get("suggestion_id", "") for row in csv.DictReader(handle)}
    pending = [row for row in rows if row["suggestion_id"] not in existing_ids]
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerows(pending)
    return rows
