"""Build the local source index from catalogue TXT and grid files."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .catalog import load_catalogue, resolve_document_path
from .pages import is_note_passage, numbered_footnotes, parse_pages, printed_page_label, split_paragraphs
from .policy import access_policy
from .store import Store
from .tables import row_blocks


def _search_text(original: str) -> str:
    return " ".join(original.lower().replace("%", " percent ").split())


def _content_hash(document: dict, project_root: Path | None = None) -> str:
    digest = hashlib.sha256()
    for key in ("pdf_path", "txt_path", "grid_path"):
        path = (
            resolve_document_path(document, key, project_root)
            if project_root is not None
            else Path(document.get(key) or "")
        )
        if path is None or not path.is_file():
            continue
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _index_version(store: Store) -> str:
    digest = hashlib.sha256()
    for row in store.documents():
        digest.update(
            "\0".join(
                str(row[key] or "")
                for key in (
                    "file_id",
                    "source_version",
                    "content_hash",
                    "page_count",
                    "text_state",
                    "index_state",
                    "routing_status",
                    "disagreement",
                    "product_tier",
                    "layout_features",
                )
            ).encode("utf-8")
        )
        digest.update(b"\n")
    for row in store.conn.execute(
        """
        SELECT block_id, file_id, source_version, physical_page, printed_page,
               block_kind, original_text, search_text, parent_id, layout_uncertain,
               source_representation, text_start, text_end
        FROM blocks ORDER BY block_id
        """
    ):
        digest.update(
            "\0".join(str(row[key] or "") for key in row.keys()).encode("utf-8")
        )
        digest.update(b"\n")
    for row in store.conn.execute(
        "SELECT from_id, to_id, kind FROM relations ORDER BY from_id, to_id, kind"
    ):
        digest.update(
            "\0".join(str(row[key] or "") for key in row.keys()).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()[:16]


def _page_blocks(
    file_id: str,
    source_version: str,
    page: int,
    text: str,
    representation: str,
    *,
    layout_uncertain: bool,
) -> list[dict]:
    parent_id = f"{file_id}:p{page}:page:0"
    printed = printed_page_label(text)
    blocks = [
        {
            "block_id": parent_id,
            "file_id": file_id,
            "source_version": source_version,
            "physical_page": page,
            "printed_page": printed,
            "block_kind": "page",
            "original_text": text,
            "search_text": _search_text(text),
            "parent_id": None,
            "layout_uncertain": int(layout_uncertain),
            "source_representation": representation,
            "text_start": 0,
            "text_end": len(text),
        }
    ]
    cursor = 0
    for index, paragraph in enumerate(split_paragraphs(text), start=1):
        start = text.find(paragraph, cursor)
        end = start + len(paragraph) if start >= 0 else None
        cursor = end or cursor
        kind = "note" if is_note_passage(paragraph) else "paragraph"
        blocks.append(
            {
                "block_id": f"{file_id}:p{page}:{kind}:{index}",
                "file_id": file_id,
                "source_version": source_version,
                "physical_page": page,
                "printed_page": printed,
                "block_kind": kind,
                "original_text": paragraph,
                "search_text": _search_text(paragraph),
                "parent_id": parent_id,
                "layout_uncertain": int(layout_uncertain),
                "source_representation": representation,
                "text_start": start if start >= 0 else None,
                "text_end": end,
            }
        )
    for number, note, start, end in numbered_footnotes(text):
        blocks.append(
            {
                "block_id": f"{file_id}:p{page}:footnote:{number}",
                "file_id": file_id,
                "source_version": source_version,
                "physical_page": page,
                "printed_page": printed,
                "block_kind": "footnote",
                "original_text": note,
                "search_text": _search_text(note),
                "parent_id": parent_id,
                "layout_uncertain": int(layout_uncertain),
                "source_representation": representation,
                "text_start": start,
                "text_end": end,
            }
        )
    return blocks


def build_index(store: Store, project_root: Path, *, file_ids: tuple[str, ...] | None = None) -> dict:
    documents, warnings = load_catalogue(project_root)
    partial = file_ids is not None
    if file_ids is not None:
        allowed = set(file_ids)
        known = {row["file_id"] for row in documents}
        missing = sorted(allowed - known)
        if missing:
            raise ValueError(f"unknown file_id: {', '.join(missing)}")
        documents = [row for row in documents if row["file_id"] in allowed]
    blocks: list[dict] = []
    relations: list[tuple[str, str, str]] = []
    for document in documents:
        file_id = document["file_id"]
        if document["disagreement"]:
            document["index_state"] = "failed"
            continue
        txt = Path(document["txt_path"]) if document["txt_path"] else None
        if txt is None or not txt.is_file():
            document["text_state"] = "missing"
            document["index_state"] = "textless"
            continue
        pages, declared, state = parse_pages(txt)
        document["text_state"] = state
        if declared and pages and sorted(pages) != list(range(1, declared + 1)):
            warnings.append(f"{file_id}: TXT page sequence disagrees with declared count {declared}")
        if not pages:
            document["index_state"] = "textless"
            continue
        version = document["source_version"] or hashlib.sha256(txt.read_bytes()).hexdigest()
        document["source_version"] = version
        document["content_hash"] = _content_hash(document, project_root)
        document_blocks: list[dict] = []
        for page, text in pages.items():
            page_blocks = _page_blocks(
                file_id,
                version,
                page,
                text,
                state,
                layout_uncertain="multi_column" in document.get("layout_features", ""),
            )
            blocks.extend(page_blocks)
            document_blocks.extend(page_blocks)
            parent_id = page_blocks[0]["block_id"]
            for child in page_blocks[1:]:
                relations.append((child["block_id"], parent_id, "child_of"))
                if child["block_kind"] in {"note", "footnote"}:
                    relations.append((child["block_id"], parent_id, "note_on_page"))
        if document["grid_path"]:
            grid_blocks, grid_relations = row_blocks(Path(document["grid_path"]), file_id, version)
            blocks.extend(grid_blocks)
            document_blocks.extend(grid_blocks)
            relations.extend(grid_relations)
        footnotes: dict[str, list[tuple[int, str]]] = {}
        for block in document_blocks:
            if block["block_kind"] == "footnote":
                number = block["block_id"].rsplit(":", 1)[-1]
                footnotes.setdefault(number, []).append(
                    (int(block["physical_page"]), block["block_id"])
                )
        for block in document_blocks:
            if block["block_kind"] in {"page", "footnote"}:
                continue
            for number in set(re.findall(r"\((\d{1,2})\)", block["original_text"])):
                candidates = footnotes.get(number) or []
                if candidates:
                    page = int(block["physical_page"])
                    _target_page, target = min(
                        candidates,
                        key=lambda item: (0 if item[0] >= page else 1, abs(item[0] - page)),
                    )
                    relations.append((block["block_id"], target, "defined_by_footnote"))
        restricted = set(access_policy().get("restricted_file_ids") or [])
        document["index_state"] = "restricted" if file_id in restricted else "indexed"
    stored = [{key: document.get(key, "" if key != "page_count" else 0) for key in (
        "file_id", "filename", "doc_type", "source_version", "page_count", "txt_path",
        "pdf_path", "grid_path", "image_dir", "text_state", "index_state", "routing_status",
        "disagreement", "product_tier", "content_hash", "layout_features",
    )} for document in documents]
    if partial:
        store.upsert_documents(stored)
        store.replace_blocks_for((row["file_id"] for row in stored), blocks, relations)
    else:
        store.replace_documents(stored)
        store.replace_blocks(blocks, relations)
    version = _index_version(store)
    store.set_meta("index_version", version)
    store.set_meta("keyword_enabled", "1")
    active_model = store.meta("embedding_model_key")
    store.set_meta(
        "vector_enabled",
        "1" if active_model and store.vector_count(active_model) else "0",
    )
    return {"warnings": warnings, "coverage": store.coverage(), "index_version": version}


def refresh_staleness(
    store: Store,
    file_ids: tuple[str, ...] | None = None,
    *,
    project_root: Path | None = None,
) -> int:
    marked = 0
    selected = set(file_ids) if file_ids is not None else None
    for document in store.documents():
        if selected is not None and document["file_id"] not in selected:
            continue
        if document["index_state"] in {"textless", "failed"}:
            continue
        current = _content_hash(dict(document), project_root)
        if current != (document["content_hash"] or ""):
            store.conn.execute("UPDATE documents SET index_state='stale' WHERE file_id=?", (document["file_id"],))
            marked += 1
        elif document["index_state"] == "stale":
            restricted = set(access_policy().get("restricted_file_ids") or [])
            restored = "restricted" if document["file_id"] in restricted else "indexed"
            store.conn.execute("UPDATE documents SET index_state=? WHERE file_id=?", (restored, document["file_id"]))
            marked += 1
    if marked:
        store.conn.commit()
    return marked
