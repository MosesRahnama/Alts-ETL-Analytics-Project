"""Local embeddings and vector-index construction with no network access."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import threading
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Protocol

from .policy import retrieval_policy
from .store import Store

REQUIRED_MODEL_FILES = (
    "config.json",
    "model_optimized.onnx",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "tokenizer.json",
)
TOKEN = re.compile(r"[A-Za-z0-9%$.]+")
_MODEL_LOCK = threading.Lock()


class EmbeddingUnavailable(RuntimeError):
    """The configured local model or its Python runtime is unavailable."""


class Embedder(Protocol):
    model_key: str
    dimension: int

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def embedding_settings() -> dict:
    settings = retrieval_policy()
    return {
        "name": str(settings.get("embedding_model") or "").strip(),
        "revision": str(settings.get("embedding_revision") or "").strip(),
        "dimension": int(settings.get("embedding_dimension") or 0),
        "block_kinds": tuple(str(item) for item in settings.get("embedding_block_kinds") or ()),
        "scope": str(settings.get("embedding_scope") or "extracted_documents"),
        "batch_size": int(settings.get("embedding_batch_size") or 64),
    }


def model_key(name: str, revision: str, dimension: int) -> str:
    return f"{name}@{revision}:{dimension}"


def model_directory(runtime: Path, settings: dict | None = None) -> Path:
    selected = settings or embedding_settings()
    safe_name = selected["name"].replace("/", "--")
    return runtime / "models" / safe_name / selected["revision"]


def _default_source(settings: dict) -> Path | None:
    explicit = os.environ.get("ALTS_RAG_MODEL_SOURCE")
    if explicit:
        return Path(explicit)
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    root = (
        Path(local)
        / "rag-engine"
        / "data"
        / "models"
        / "models--qdrant--bge-small-en-v1.5-onnx-q"
        / "snapshots"
    )
    exact = root / settings["revision"]
    if exact.is_dir():
        return exact
    candidates = sorted(path for path in root.glob("*") if path.is_dir())
    return candidates[-1] if candidates else None


def _resolved_file(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise EmbeddingUnavailable(f"model file cannot be resolved: {path.name}") from exc


def validate_model_directory(path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in REQUIRED_MODEL_FILES:
        source = path / name
        resolved = _resolved_file(source)
        if not resolved.is_file() or resolved.stat().st_size == 0:
            raise EmbeddingUnavailable(f"local model file is absent or empty: {name}")
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        hashes[name] = digest.hexdigest()
    return hashes


def prepare_local_model(runtime: Path, source: Path | None = None) -> dict:
    """Copy the existing ONNX snapshot into this engine's private runtime."""

    settings = embedding_settings()
    if not settings["name"] or not settings["revision"] or settings["dimension"] <= 0:
        raise EmbeddingUnavailable("embedding settings are incomplete")
    selected_source = source or _default_source(settings)
    if selected_source is None or not selected_source.is_dir():
        raise EmbeddingUnavailable("approved local embedding-model snapshot was not found")
    source_hashes = validate_model_directory(selected_source)
    destination = model_directory(runtime, settings)
    if destination.is_dir():
        destination_hashes = validate_model_directory(destination)
        if destination_hashes == source_hashes:
            return {
                "model": settings["name"],
                "revision": settings["revision"],
                "dimension": settings["dimension"],
                "path": str(destination),
                "copied": False,
            }
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        for name in REQUIRED_MODEL_FILES:
            shutil.copy2(_resolved_file(selected_source / name), staging / name)
        manifest = {
            "model": settings["name"],
            "revision": settings["revision"],
            "dimension": settings["dimension"],
            "files": source_hashes,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validate_model_directory(staging)
        if destination.exists():
            shutil.rmtree(destination)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {
        "model": settings["name"],
        "revision": settings["revision"],
        "dimension": settings["dimension"],
        "path": str(destination),
        "copied": True,
    }


def _normalize(values: Iterable[float], dimension: int) -> list[float]:
    vector = [float(value) for value in values]
    if len(vector) != dimension or any(not math.isfinite(value) for value in vector):
        raise EmbeddingUnavailable("embedding has the wrong dimension or a non-finite value")
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise EmbeddingUnavailable("embedding has zero magnitude")
    return [value / norm for value in vector]


@lru_cache(maxsize=2)
def _fastembed_model(name: str, model_path: str, threads: int):
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise EmbeddingUnavailable("fastembed is not installed in this Python environment") from exc
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    try:
        return TextEmbedding(
            model_name=name,
            specific_model_path=model_path,
            local_files_only=True,
            cache_dir=str(Path(model_path).parent),
            threads=threads,
        )
    except Exception as exc:
        raise EmbeddingUnavailable("the approved local embedding model failed to load") from exc


class LocalEmbedder:
    def __init__(self, runtime: Path) -> None:
        settings = embedding_settings()
        path = model_directory(runtime, settings)
        validate_model_directory(path)
        self.name = settings["name"]
        self.revision = settings["revision"]
        self.dimension = settings["dimension"]
        self.model_key = model_key(self.name, self.revision, self.dimension)
        self.path = path
        self.batch_size = max(1, settings["batch_size"])
        self.threads = max(1, int(os.environ.get("ALTS_RAG_EMBED_THREADS") or max(1, (os.cpu_count() or 4) // 2)))

    @property
    def _model(self):
        return _fastembed_model(self.name, str(self.path), self.threads)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with _MODEL_LOCK:
            rows = list(self._model.embed(texts, batch_size=self.batch_size))
        return [_normalize(row, self.dimension) for row in rows]

    def embed_query(self, text: str) -> list[float]:
        with _MODEL_LOCK:
            row = next(iter(self._model.query_embed([text])))
        return _normalize(row, self.dimension)


class FakeEmbedder:
    """Deterministic local vectors for tests; never used as measured model evidence."""

    def __init__(self, dimension: int = 64, key: str = "fake:v1") -> None:
        self.dimension = dimension
        self.model_key = key

    def _one(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        for token in TOKEN.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            values[index] += -1.0 if digest[4] & 1 else 1.0
        if not any(values):
            values[0] = 1.0
        return _normalize(values, self.dimension)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._one(text)


def load_embedder(runtime: Path) -> Embedder:
    if os.environ.get("ALTS_RAG_FAKE_EMBEDDER") == "1":
        return FakeEmbedder()
    return LocalEmbedder(runtime)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def default_vector_file_ids(
    store: Store,
    project_root: Path,
    *,
    all_documents: bool = False,
) -> tuple[str, ...]:
    available = {
        str(row["file_id"])
        for row in store.documents()
        if row["index_state"] in {"indexed", "restricted"}
    }
    if all_documents:
        return tuple(sorted(available))
    summary = project_root / "data" / "extracted" / "review" / "document-summary.csv"
    if not summary.is_file():
        return tuple(sorted(available))
    with summary.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = {
        (row.get("file_id") or row.get("document_id") or "").strip()
        for row in rows
    }
    return tuple(sorted((selected - {""}) & available))


def _vector_version(store: Store, active_model_key: str) -> str:
    digest = hashlib.sha256(active_model_key.encode("utf-8"))
    for row in store.conn.execute(
        "SELECT block_id, text_hash FROM vectors WHERE model_key=? ORDER BY block_id",
        (active_model_key,),
    ):
        digest.update(str(row["block_id"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["text_hash"]).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()[:16]


def build_vectors(
    store: Store,
    project_root: Path,
    runtime: Path,
    *,
    file_ids: tuple[str, ...] | None = None,
    all_documents: bool = False,
    block_kinds: tuple[str, ...] | None = None,
    embedder: Embedder | None = None,
) -> dict:
    """Build vectors in a shadow table and activate them only after validation."""

    selected = tuple(
        dict.fromkeys(
            file_ids
            or default_vector_file_ids(
                store,
                project_root,
                all_documents=all_documents,
            )
        )
    )
    if not selected:
        raise ValueError("no indexed documents were selected for vectorization")
    known = {str(row["file_id"]) for row in store.documents()}
    unknown = sorted(set(selected) - known)
    if unknown:
        raise ValueError(f"unknown file_id: {', '.join(unknown)}")
    settings = embedding_settings()
    kinds = tuple(dict.fromkeys(block_kinds or settings["block_kinds"]))
    if not kinds or "page" in kinds:
        raise ValueError("vector block kinds must be non-page evidence types")
    active = embedder or load_embedder(runtime)
    build_id = uuid.uuid4().hex
    placeholders = ",".join("?" for _ in selected)
    kind_marks = ",".join("?" for _ in kinds)
    rows = list(
        store.conn.execute(
            f"""
            SELECT block_id, file_id, source_version, search_text
            FROM blocks
            WHERE file_id IN ({placeholders}) AND block_kind IN ({kind_marks})
            ORDER BY file_id, physical_page, block_kind, block_id
            """,
            (*selected, *kinds),
        )
    )
    if not rows:
        raise ValueError("selected documents have no eligible evidence blocks")
    store.conn.execute("DELETE FROM vector_staging WHERE build_id=?", (build_id,))
    store.conn.commit()
    cache_hits = 0
    embedded = 0
    batch_size = max(1, settings["batch_size"])
    try:
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            vectors: list[list[float] | None] = [None] * len(batch)
            missing_by_hash: dict[str, list[int]] = {}
            text_by_hash: dict[str, str] = {}
            for index, row in enumerate(batch):
                digest = _text_hash(str(row["search_text"]))
                cached = store.conn.execute(
                    "SELECT dim, vector FROM embedding_cache WHERE model_key=? AND text_hash=?",
                    (active.model_key, digest),
                ).fetchone()
                if cached is not None and int(cached["dim"]) == active.dimension:
                    vector = store.decode_vector(cached["vector"], active.dimension)
                    vectors[index] = vector
                    cache_hits += 1
                else:
                    missing_by_hash.setdefault(digest, []).append(index)
                    text_by_hash[digest] = str(row["search_text"])
            if missing_by_hash:
                missing_hashes = list(missing_by_hash)
                made = active.embed_passages([text_by_hash[digest] for digest in missing_hashes])
                if len(made) != len(missing_hashes):
                    raise EmbeddingUnavailable("embedder returned the wrong row count")
                cache_rows = []
                for digest, vector in zip(missing_hashes, made):
                    normalized = _normalize(vector, active.dimension)
                    cache_rows.append((active.model_key, digest, active.dimension, store.encode_vector(normalized)))
                    for index in missing_by_hash[digest]:
                        vectors[index] = normalized
                        embedded += 1
                store.conn.executemany(
                    """
                    INSERT INTO embedding_cache(model_key, text_hash, dim, vector)
                    VALUES(?,?,?,?)
                    ON CONFLICT(model_key,text_hash) DO UPDATE SET dim=excluded.dim, vector=excluded.vector
                    """,
                    cache_rows,
                )
            staged = []
            for row, vector in zip(batch, vectors):
                if vector is None:
                    raise EmbeddingUnavailable("vector build left an empty result")
                staged.append(
                    (
                        build_id,
                        row["block_id"],
                        row["file_id"],
                        row["source_version"],
                        active.model_key,
                        _text_hash(str(row["search_text"])),
                        active.dimension,
                        store.encode_vector(vector),
                    )
                )
            store.conn.executemany(
                """
                INSERT INTO vector_staging(
                    build_id, block_id, file_id, source_version, model_key, text_hash, dim, vector
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                staged,
            )
            store.conn.commit()
        staged_count = int(
            store.conn.execute(
                "SELECT COUNT(*) AS n FROM vector_staging WHERE build_id=?", (build_id,)
            ).fetchone()["n"]
        )
        if staged_count != len(rows):
            raise EmbeddingUnavailable("staged vector count does not match eligible block count")
        store.conn.execute("BEGIN IMMEDIATE")
        store.conn.execute(f"DELETE FROM vectors WHERE file_id IN ({placeholders})", selected)
        store.conn.execute(
            """
            INSERT INTO vectors(block_id,file_id,source_version,model_key,text_hash,dim,vector)
            SELECT block_id,file_id,source_version,model_key,text_hash,dim,vector
            FROM vector_staging WHERE build_id=?
            """,
            (build_id,),
        )
        store.conn.execute("DELETE FROM vector_staging WHERE build_id=?", (build_id,))
        store.conn.execute(
            "DELETE FROM vectors WHERE block_id NOT IN (SELECT block_id FROM blocks)"
        )
        store.conn.commit()
    except Exception:
        store.conn.rollback()
        store.conn.execute("DELETE FROM vector_staging WHERE build_id=?", (build_id,))
        store.conn.commit()
        raise
    store.set_meta("embedding_model_key", active.model_key)
    store.set_meta("embedding_dimension", str(active.dimension))
    store.set_meta("embedding_block_kinds", "|".join(kinds))
    vector_version = _vector_version(store, active.model_key)
    store.set_meta("vector_version", vector_version)
    active_count = store.vector_count(active.model_key)
    store.set_meta("vector_enabled", "1" if active_count else "0")
    return {
        "execution_state": "OK",
        "model_key": active.model_key,
        "dimension": active.dimension,
        "documents_selected": len(selected),
        "eligible_blocks": len(rows),
        "active_vectors": active_count,
        "cache_hits": cache_hits,
        "embedded_blocks": embedded,
        "block_kinds": list(kinds),
        "vector_version": vector_version,
    }
