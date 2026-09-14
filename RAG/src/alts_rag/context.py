"""Assemble parent, table, and note context around ranked blocks."""

from __future__ import annotations

from .policy import retrieval_policy
from .retrieval import passage_is_instruction
from .store import Store
from .types import EvidenceBlock, Location, QueryScope


def row_to_block(row, store: Store, *, truncated: bool = False, continuation_ids: tuple[str, ...] = ()) -> EvidenceBlock:
    document = store.document(row["file_id"])
    relations = tuple(item[0] for item in store.related(row["block_id"]))
    return EvidenceBlock(
        block_id=row["block_id"],
        file_id=row["file_id"],
        source_version=row["source_version"],
        physical_page=int(row["physical_page"]),
        printed_page=row["printed_page"],
        block_kind=row["block_kind"],
        original_text=row["original_text"],
        source_representation=row["source_representation"],
        location=Location(
            physical_page=int(row["physical_page"]),
            printed_page=row["printed_page"],
            text_start=row["text_start"],
            text_end=row["text_end"],
            bbox=None,
            page_width=None,
            page_height=None,
            coordinate_convention=None,
            layout_uncertain=bool(row["layout_uncertain"]),
        ),
        parent_id=row["parent_id"],
        relation_ids=relations,
        layout_uncertainty=bool(row["layout_uncertain"]),
        filename=document["filename"] if document else "",
        doc_type=document["doc_type"] if document else "",
        truncated=truncated,
        continuation_ids=continuation_ids,
    )


def block_dict(block: EvidenceBlock, score: float | None = None, methods: tuple[str, ...] = ()) -> dict:
    payload = {
        "block_id": block.block_id,
        "file_id": block.file_id,
        "filename": block.filename,
        "doc_type": block.doc_type,
        "source_version": block.source_version,
        "physical_page": block.physical_page,
        "printed_page": block.printed_page,
        "block_kind": block.block_kind,
        "original_text": block.original_text,
        "source_representation": block.source_representation,
        "parent_id": block.parent_id,
        "relation_ids": list(block.relation_ids),
        "layout_uncertainty": block.layout_uncertainty,
        "truncated": block.truncated,
        "continuation_ids": list(block.continuation_ids),
        "location": {
            "physical_page": block.location.physical_page,
            "printed_page": block.location.printed_page,
            "text_start": block.location.text_start,
            "text_end": block.location.text_end,
            "layout_uncertain": block.location.layout_uncertain,
        },
        "instruction_like": passage_is_instruction(block.original_text),
    }
    if score is not None:
        payload["score"] = score
        payload["methods"] = list(methods)
    return payload


def load_permitted_block(store: Store, block_id: str, scope: QueryScope) -> EvidenceBlock | None:
    row = store.block(block_id)
    if row is None or row["file_id"] not in scope.permitted_document_ids:
        return None
    return row_to_block(row, store)


def assemble(store: Store, ranked: list[tuple[str, float, tuple[str, ...]]], scope: QueryScope) -> list[dict]:
    settings = retrieval_policy()
    budget = max(1, int(settings["context_char_budget"]))
    used = 0
    results: list[dict] = []
    for block_id, score, methods in ranked:
        primary = load_permitted_block(store, block_id, scope)
        if primary is None:
            continue
        available = budget - used
        if available <= 0:
            break
        primary_text = primary.original_text[:available]
        primary_was_truncated = len(primary_text) < len(primary.original_text)
        if passage_is_instruction(primary.original_text):
            context_ids: list[str] = []
        else:
            context_ids = list(primary.relation_ids)
            page_notes = store.conn.execute(
                """
                SELECT block_id FROM blocks
                WHERE file_id=? AND physical_page=? AND block_kind IN ('note', 'footnote')
                """,
                (primary.file_id, primary.physical_page),
            ).fetchall()
            context_ids.extend(row["block_id"] for row in page_notes)
        unique_ids = []
        seen = {primary.block_id}
        for item in context_ids:
            if item in seen:
                continue
            seen.add(item)
            unique_ids.append(item)
        remaining = max(0, available - len(primary_text))
        context_blocks = []
        continuation = [primary.block_id] if primary_was_truncated else []
        for related_id in unique_ids:
            related = load_permitted_block(store, related_id, scope)
            if related is None:
                continue
            if related.block_kind == "page":
                continue
            if remaining < len(related.original_text):
                continuation.append(related.block_id)
                continue
            context_blocks.append(block_dict(related))
            remaining -= len(related.original_text)
        truncated = bool(continuation)
        used += len(primary_text) + sum(len(item["original_text"]) for item in context_blocks)
        payload = block_dict(primary, score, methods)
        payload["original_text"] = primary_text
        payload["truncated"] = truncated
        payload["continuation_ids"] = continuation
        payload["context"] = context_blocks
        results.append(payload)
        if used >= budget:
            break
    return results
