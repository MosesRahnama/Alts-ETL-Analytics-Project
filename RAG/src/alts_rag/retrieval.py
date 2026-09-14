"""Keyword retrieval with reciprocal-rank fusion."""

from __future__ import annotations

import math
import re
import heapq
from pathlib import Path

from .embed import Embedder, EmbeddingUnavailable, load_embedder
from .policy import retrieval_policy
from .store import Store
from .types import QueryScope

TOKEN = re.compile(r"[A-Za-z0-9%$.]+")
STOPWORDS = frozenset({"and", "or", "not", "near", "the", "a", "an", "of", "on", "for", "to", "in", "as"})
INJECTION = re.compile(
    r"(ignore (previous|all) instructions|system:|you are now|/etc/passwd|drop table)",
    re.I,
)


def sanitize_query(text: str) -> str:
    return " ".join(TOKEN.findall(text))


def _match_query(text: str) -> str:
    text = text.lower().replace("%", " percent ")
    tokens = TOKEN.findall(text)
    cleaned = []
    for token in tokens:
        if token in STOPWORDS:
            continue
        cleaned.append('"' + token.replace('"', "") + '"')
    return " AND ".join(cleaned[:24])


def _fts_rows(store: Store, match: str, limit: int, file_ids: tuple[str, ...]):
    if not file_ids:
        return []
    placeholders = ",".join("?" for _ in file_ids)
    sql = f"""
        SELECT block_id, file_id
        FROM blocks_fts
        WHERE blocks_fts MATCH ?
          AND file_id IN ({placeholders})
        ORDER BY bm25(blocks_fts), block_id
        LIMIT ?
    """
    return store.conn.execute(sql, (match, *file_ids, limit)).fetchall()


def keyword_search(store: Store, query: str, scope: QueryScope, limit: int) -> list[tuple[str, float]]:
    match = _match_query(query)
    if not match:
        return []
    allowed = tuple(scope.permitted_document_ids)
    rows = _fts_rows(store, match, limit * 4, allowed)
    if not rows:
        tokens = [
            f'"{token}"'
            for token in TOKEN.findall(query.lower().replace("%", " percent "))
            if token not in STOPWORDS
        ]
        if tokens:
            rows = _fts_rows(store, " OR ".join(tokens[:24]), limit * 4, allowed)
    ranked: list[tuple[str, float]] = []
    for index, row in enumerate(rows):
        if row["file_id"] not in allowed:
            continue
        ranked.append((row["block_id"], 1.0 / (index + 1)))
        if len(ranked) >= limit:
            break
    return ranked


def vector_search(
    store: Store,
    query: str,
    scope: QueryScope,
    limit: int,
    *,
    runtime: Path,
    embedder: Embedder | None = None,
) -> list[tuple[str, float]]:
    """Score only vectors inside the session's permitted document set."""
    if store.meta("vector_enabled") != "1":
        return []
    active_model = store.meta("embedding_model_key")
    dimension = int(store.meta("embedding_dimension") or 0)
    allowed = tuple(dict.fromkeys(scope.permitted_document_ids))
    if not active_model or dimension <= 0 or not allowed:
        return []
    try:
        active = embedder or load_embedder(runtime)
        if active.model_key != active_model or active.dimension != dimension:
            return []
        import numpy as np

        query_vector = np.asarray(active.embed_query(query), dtype=np.float32)
        norm = float(np.linalg.norm(query_vector))
        if query_vector.shape != (dimension,) or not np.isfinite(query_vector).all() or norm == 0:
            return []
        query_vector /= norm
    except (EmbeddingUnavailable, ImportError, ValueError):
        return []
    placeholders = ",".join("?" for _ in allowed)
    cursor = store.conn.execute(
        f"""
        SELECT vectors.block_id, vectors.dim, vectors.vector
        FROM vectors
        JOIN blocks USING(block_id)
        JOIN documents ON documents.file_id=vectors.file_id
        WHERE vectors.model_key=?
          AND vectors.file_id IN ({placeholders})
          AND vectors.source_version=blocks.source_version
          AND documents.index_state IN ('indexed','restricted')
        ORDER BY vectors.block_id
        """,
        (active_model, *allowed),
    )
    best: list[tuple[float, str]] = []
    while True:
        rows = cursor.fetchmany(2048)
        if not rows:
            break
        usable = [row for row in rows if int(row["dim"]) == dimension and len(row["vector"]) == dimension * 4]
        if not usable:
            continue
        matrix = np.frombuffer(b"".join(row["vector"] for row in usable), dtype="<f4").reshape(len(usable), dimension)
        scores = matrix @ query_vector
        take = min(limit, len(usable))
        indices = np.argpartition(-scores, take - 1)[:take] if take < len(usable) else range(len(usable))
        for index in indices:
            item = (float(scores[index]), str(usable[index]["block_id"]))
            if len(best) < limit:
                heapq.heappush(best, item)
            elif item > best[0]:
                heapq.heapreplace(best, item)
    return [(block_id, score) for score, block_id in sorted(best, key=lambda item: (-item[0], item[1]))]


def reciprocal_rank_fusion(
    rankings: dict[str, list[tuple[str, float]]],
    k: int,
    limit: int,
    weights: dict[str, float] | None = None,
) -> list[tuple[str, float, tuple[str, ...]]]:
    scores: dict[str, float] = {}
    methods: dict[str, list[str]] = {}
    for method, ranked in rankings.items():
        weight = float((weights or {}).get(method, 1.0))
        for index, (block_id, _score) in enumerate(ranked, start=1):
            scores[block_id] = scores.get(block_id, 0.0) + weight / (k + index)
            methods.setdefault(block_id, []).append(method)
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [(block_id, score, tuple(methods[block_id])) for block_id, score in ordered[:limit]]


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    na = math.sqrt(sum(a * a for a in left))
    nb = math.sqrt(sum(b * b for b in right))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def retrieve(
    store: Store,
    query: str,
    scope: QueryScope,
    result_limit: int | None = None,
    *,
    runtime: Path,
    embedder: Embedder | None = None,
    active_methods: tuple[str, ...] | None = None,
) -> tuple[list[tuple[str, float, tuple[str, ...]]], tuple[str, ...]]:
    settings = retrieval_policy()
    candidate_limit = max(1, min(int(settings["candidate_limit"]), 200))
    requested_limit = int(result_limit) if result_limit is not None else int(settings["result_limit"])
    limit = max(1, min(requested_limit, min(candidate_limit, 50)))
    rankings: dict[str, list[tuple[str, float]]] = {}
    methods: list[str] = []
    if active_methods is None:
        selected = {"keyword"}
        if settings.get("hybrid_default"):
            selected.add("vector")
    else:
        selected = set(active_methods)
    if settings.get("keyword_enabled", True) and "keyword" in selected:
        keyword = keyword_search(store, query, scope, candidate_limit)
        rankings["keyword"] = keyword
        if keyword:
            methods.append("keyword")
    if settings.get("vector_enabled") and store.meta("vector_enabled") == "1" and "vector" in selected:
        vector = vector_search(
            store,
            query,
            scope,
            candidate_limit,
            runtime=runtime,
            embedder=embedder,
        )
        if vector:
            rankings["vector"] = vector
            methods.append("vector")
    fused = reciprocal_rank_fusion(
        rankings,
        int(settings["rrf_k"]),
        limit,
        {
            "keyword": float(settings.get("keyword_weight", 1.0)),
            "vector": float(settings.get("vector_weight", 1.0)),
        },
    )
    return fused, tuple(methods)


def passage_is_instruction(text: str) -> bool:
    return bool(INJECTION.search(text))
