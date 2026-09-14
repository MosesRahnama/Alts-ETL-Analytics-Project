"""Retrieval, access, and query policy loaded from RAG/config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import CONFIG_DIR

DEFAULTS = {
    "candidate_limit": 40,
    "result_limit": 10,
    "rrf_k": 60,
    "context_char_budget": 12000,
    "keyword_enabled": True,
    "vector_enabled": False,
    "hybrid_default": False,
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "embedding_revision": "52398278842ec682c6f32300af41344b1c0b0bb2",
    "embedding_dimension": 384,
    "embedding_block_kinds": ["paragraph", "note", "footnote", "table_row"],
    "embedding_scope": "extracted_documents",
    "embedding_batch_size": 64,
    "keyword_weight": 1.0,
    "vector_weight": 0.7,
    "reasoning_model_name": "GPT-5.6 Luna",
    "reasoning_model": "",
    "reasoning_setting": "max",
    "provider": "openrouter",
    "identifier_status": "unverified",
    "reasoning_request": {},
}


def load_json(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.is_file():
        return dict(fallback or {})
    return json.loads(path.read_text(encoding="utf-8"))


def retrieval_policy(config_dir: Path | None = None) -> dict[str, Any]:
    data = dict(DEFAULTS)
    data.update(load_json((config_dir or CONFIG_DIR) / "retrieval.json"))
    return data


def access_policy(config_dir: Path | None = None) -> dict[str, Any]:
    return load_json(
        (config_dir or CONFIG_DIR) / "access.json",
        {
            "extractor_roles": ["extractor_a", "extractor_b"],
            "reviewer_role": "reviewer",
            "public_role": "public_demo",
            "data_groups": ["extracted"],
        },
    )


def query_definitions(config_dir: Path | None = None) -> dict[str, Any]:
    return load_json((config_dir or CONFIG_DIR) / "queries.json", {})
