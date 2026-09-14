"""SQLite store for documents, page blocks, sessions, and FTS."""

from __future__ import annotations

import sqlite3
import struct
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    file_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    source_version TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    txt_path TEXT,
    pdf_path TEXT,
    grid_path TEXT,
    image_dir TEXT,
    text_state TEXT NOT NULL,
    index_state TEXT NOT NULL,
    routing_status TEXT,
    disagreement TEXT,
    product_tier TEXT,
    content_hash TEXT,
    layout_features TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS blocks (
    block_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    physical_page INTEGER NOT NULL,
    printed_page TEXT,
    block_kind TEXT NOT NULL,
    original_text TEXT NOT NULL,
    search_text TEXT NOT NULL,
    parent_id TEXT,
    layout_uncertain INTEGER NOT NULL DEFAULT 0,
    source_representation TEXT NOT NULL,
    text_start INTEGER,
    text_end INTEGER
);
CREATE TABLE IF NOT EXISTS relations (
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    kind TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS blocks_file_page_kind_idx
    ON blocks(file_id, physical_page, block_kind, block_id);
CREATE INDEX IF NOT EXISTS relations_from_id_idx
    ON relations(from_id);
CREATE INDEX IF NOT EXISTS relations_to_id_idx
    ON relations(to_id);
CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5(
    block_id UNINDEXED,
    file_id UNINDEXED,
    search_text,
    tokenize = 'unicode61'
);
CREATE TABLE IF NOT EXISTS vectors (
    block_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    model_key TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS vectors_model_file_idx
    ON vectors(model_key, file_id, block_id);
CREATE TABLE IF NOT EXISTS embedding_cache (
    model_key TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY(model_key, text_hash)
);
CREATE TABLE IF NOT EXISTS vector_staging (
    build_id TEXT NOT NULL,
    block_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    model_key TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY(build_id, block_id)
);
"""

ACCESS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    purpose TEXT NOT NULL,
    document_ids TEXT NOT NULL,
    data_groups TEXT NOT NULL,
    issued_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    provider TEXT,
    model_id TEXT,
    reasoning_setting TEXT,
    documents TEXT,
    fields TEXT,
    request_limit INTEGER,
    spending_cap TEXT,
    expires_at TEXT,
    granted_by TEXT NOT NULL,
    authorization_reference TEXT NOT NULL DEFAULT '',
    provider_contract_hash TEXT NOT NULL DEFAULT '',
    max_input_tokens INTEGER NOT NULL DEFAULT 0,
    max_output_tokens INTEGER NOT NULL DEFAULT 0,
    input_usd_per_m TEXT NOT NULL DEFAULT '',
    output_usd_per_m TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS usage (
    request_id TEXT PRIMARY KEY,
    approval_id TEXT,
    provider TEXT,
    model_id TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost TEXT,
    outcome TEXT,
    recorded_at TEXT NOT NULL,
    reasoning_setting TEXT NOT NULL DEFAULT '',
    reserved_cost TEXT NOT NULL DEFAULT '',
    provider_request_id TEXT NOT NULL DEFAULT '',
    cost_status TEXT NOT NULL DEFAULT ''
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout = 15000")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(documents)")}
        if "layout_features" not in columns:
            self.conn.execute(
                "ALTER TABLE documents ADD COLUMN layout_features TEXT NOT NULL DEFAULT ''"
            )
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def replace_documents(self, rows: Iterable[dict[str, Any]]) -> None:
        self.conn.execute("DELETE FROM documents")
        self.conn.executemany(
            """
            INSERT INTO documents(
                file_id, filename, doc_type, source_version, page_count, txt_path, pdf_path,
                grid_path, image_dir, text_state, index_state, routing_status, disagreement, product_tier,
                content_hash, layout_features
            ) VALUES (
                :file_id, :filename, :doc_type, :source_version, :page_count, :txt_path, :pdf_path,
                :grid_path, :image_dir, :text_state, :index_state, :routing_status, :disagreement, :product_tier,
                :content_hash, :layout_features
            )
            """,
            list(rows),
        )
        self.conn.commit()

    def upsert_documents(self, rows: Iterable[dict[str, Any]]) -> None:
        self.conn.executemany(
            """
            INSERT INTO documents(
                file_id, filename, doc_type, source_version, page_count, txt_path, pdf_path,
                grid_path, image_dir, text_state, index_state, routing_status, disagreement, product_tier,
                content_hash, layout_features
            ) VALUES (
                :file_id, :filename, :doc_type, :source_version, :page_count, :txt_path, :pdf_path,
                :grid_path, :image_dir, :text_state, :index_state, :routing_status, :disagreement, :product_tier,
                :content_hash, :layout_features
            )
            ON CONFLICT(file_id) DO UPDATE SET
                filename=excluded.filename, doc_type=excluded.doc_type,
                source_version=excluded.source_version, page_count=excluded.page_count,
                txt_path=excluded.txt_path, pdf_path=excluded.pdf_path,
                grid_path=excluded.grid_path, image_dir=excluded.image_dir,
                text_state=excluded.text_state, index_state=excluded.index_state,
                routing_status=excluded.routing_status, disagreement=excluded.disagreement,
                product_tier=excluded.product_tier, content_hash=excluded.content_hash,
                layout_features=excluded.layout_features
            """,
            list(rows),
        )
        self.conn.commit()

    def replace_blocks(self, blocks: list[dict[str, Any]], relations: list[tuple[str, str, str]]) -> None:
        self.conn.execute("DELETE FROM vectors")
        self.conn.execute("DELETE FROM vector_staging")
        self.conn.execute("DELETE FROM blocks")
        self.conn.execute("DELETE FROM relations")
        self.conn.execute("DELETE FROM blocks_fts")
        self.conn.executemany(
            """
            INSERT INTO blocks(
                block_id, file_id, source_version, physical_page, printed_page, block_kind,
                original_text, search_text, parent_id, layout_uncertain, source_representation,
                text_start, text_end
            ) VALUES (
                :block_id, :file_id, :source_version, :physical_page, :printed_page, :block_kind,
                :original_text, :search_text, :parent_id, :layout_uncertain, :source_representation,
                :text_start, :text_end
            )
            """,
            blocks,
        )
        self.conn.executemany(
            "INSERT INTO relations(from_id, to_id, kind) VALUES(?,?,?)",
            relations,
        )
        searchable = [block for block in blocks if block["block_kind"] != "page"]
        self.conn.executemany(
            "INSERT INTO blocks_fts(block_id, file_id, search_text) VALUES(:block_id, :file_id, :search_text)",
            searchable,
        )
        self.conn.commit()

    def replace_blocks_for(
        self,
        file_ids: Iterable[str],
        blocks: list[dict[str, Any]],
        relations: list[tuple[str, str, str]],
    ) -> None:
        selected = tuple(dict.fromkeys(file_ids))
        if not selected:
            return
        placeholders = ",".join("?" for _ in selected)
        old_ids = [
            str(row["block_id"])
            for row in self.conn.execute(
                f"SELECT block_id FROM blocks WHERE file_id IN ({placeholders})", selected
            )
        ]
        if old_ids:
            old_placeholders = ",".join("?" for _ in old_ids)
            self.conn.execute(
                f"DELETE FROM relations WHERE from_id IN ({old_placeholders}) OR to_id IN ({old_placeholders})",
                (*old_ids, *old_ids),
            )
        self.conn.execute(f"DELETE FROM vectors WHERE file_id IN ({placeholders})", selected)
        self.conn.execute(f"DELETE FROM vector_staging WHERE file_id IN ({placeholders})", selected)
        self.conn.execute(f"DELETE FROM blocks WHERE file_id IN ({placeholders})", selected)
        self.conn.execute(f"DELETE FROM blocks_fts WHERE file_id IN ({placeholders})", selected)
        self.conn.executemany(
            """
            INSERT INTO blocks(
                block_id, file_id, source_version, physical_page, printed_page, block_kind,
                original_text, search_text, parent_id, layout_uncertain, source_representation,
                text_start, text_end
            ) VALUES (
                :block_id, :file_id, :source_version, :physical_page, :printed_page, :block_kind,
                :original_text, :search_text, :parent_id, :layout_uncertain, :source_representation,
                :text_start, :text_end
            )
            """,
            blocks,
        )
        self.conn.executemany("INSERT INTO relations(from_id, to_id, kind) VALUES(?,?,?)", relations)
        searchable = [block for block in blocks if block["block_kind"] != "page"]
        self.conn.executemany(
            "INSERT INTO blocks_fts(block_id, file_id, search_text) VALUES(:block_id, :file_id, :search_text)",
            searchable,
        )
        self.conn.commit()

    def document(self, file_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM documents WHERE file_id=?", (file_id,)).fetchone()

    def documents(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM documents ORDER BY file_id"))

    def block(self, block_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM blocks WHERE block_id=?", (block_id,)).fetchone()

    def blocks_for(self, file_id: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM blocks WHERE file_id=? ORDER BY physical_page, block_kind, block_id",
                (file_id,),
            )
        )

    def related(self, block_id: str) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT to_id, kind FROM relations WHERE from_id=?",
            (block_id,),
        ).fetchall()
        return [(str(row["to_id"]), str(row["kind"])) for row in rows]

    @staticmethod
    def encode_vector(values: Iterable[float]) -> bytes:
        vector = tuple(float(value) for value in values)
        return struct.pack(f"<{len(vector)}f", *vector)

    @staticmethod
    def decode_vector(blob: bytes, dimension: int) -> list[float]:
        if dimension <= 0 or len(blob) != dimension * 4:
            raise ValueError("stored vector has the wrong byte length")
        return list(struct.unpack(f"<{dimension}f", blob))

    def vector_count(self, model_key: str | None = None) -> int:
        base = """
            SELECT COUNT(*) AS n
            FROM vectors
            JOIN blocks USING(block_id)
            JOIN documents ON documents.file_id=vectors.file_id
            WHERE vectors.source_version=blocks.source_version
              AND documents.index_state IN ('indexed','restricted')
        """
        if model_key:
            row = self.conn.execute(
                base + " AND vectors.model_key=?", (model_key,)
            ).fetchone()
        else:
            row = self.conn.execute(base).fetchone()
        return int(row["n"])

    def vector_coverage(self, model_key: str | None = None) -> dict[str, int]:
        model_filter = " AND vectors.model_key=?" if model_key else ""
        params = (model_key,) if model_key else ()
        row = self.conn.execute(
            f"""
            SELECT COUNT(*) AS blocks, COUNT(DISTINCT vectors.file_id) AS documents
            FROM vectors
            JOIN blocks USING(block_id)
            JOIN documents ON documents.file_id=vectors.file_id
            WHERE vectors.source_version=blocks.source_version
              AND documents.index_state IN ('indexed','restricted')
              {model_filter}
            """,
            params,
        ).fetchone()
        return {"vector_blocks": int(row["blocks"]), "vector_documents": int(row["documents"])}

    def coverage(self) -> dict[str, int]:
        docs = self.documents()
        pages = int(
            self.conn.execute(
                """
                SELECT COUNT(*) AS n FROM (
                    SELECT DISTINCT blocks.file_id, blocks.physical_page
                    FROM blocks JOIN documents USING(file_id)
                    WHERE documents.index_state IN ('indexed', 'restricted')
                )
                """
            ).fetchone()["n"]
        )
        vector = self.vector_coverage(self.meta("embedding_model_key") or None)
        return {
            "catalogued_documents": len(docs),
            "indexed_documents": sum(1 for row in docs if row["index_state"] == "indexed"),
            "restricted_documents": sum(1 for row in docs if row["index_state"] == "restricted"),
            "textless_documents": sum(1 for row in docs if row["text_state"] == "missing"),
            "stale_documents": sum(1 for row in docs if row["index_state"] == "stale"),
            "failed_documents": sum(1 for row in docs if row["index_state"] == "failed"),
            "indexed_pages": pages,
            "block_count": int(self.conn.execute("SELECT COUNT(*) AS n FROM blocks").fetchone()["n"]),
            **vector,
        }


class AccessStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(ACCESS_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        additions = {
            "approvals": {
                "authorization_reference": "TEXT NOT NULL DEFAULT ''",
                "provider_contract_hash": "TEXT NOT NULL DEFAULT ''",
                "max_input_tokens": "INTEGER NOT NULL DEFAULT 0",
                "max_output_tokens": "INTEGER NOT NULL DEFAULT 0",
                "input_usd_per_m": "TEXT NOT NULL DEFAULT ''",
                "output_usd_per_m": "TEXT NOT NULL DEFAULT ''",
            },
            "usage": {
                "reasoning_setting": "TEXT NOT NULL DEFAULT ''",
                "reserved_cost": "TEXT NOT NULL DEFAULT ''",
                "provider_request_id": "TEXT NOT NULL DEFAULT ''",
                "cost_status": "TEXT NOT NULL DEFAULT ''",
            },
        }
        for table, columns in additions.items():
            present = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, declaration in columns.items():
                if name not in present:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
