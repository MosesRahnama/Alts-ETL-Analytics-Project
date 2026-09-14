"""Project and runtime locations."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
RAG_ROOT = PACKAGE_ROOT.parents[1]
PROJECT_ROOT = RAG_ROOT.parent
CONFIG_DIR = RAG_ROOT / "config"
EVALUATION_DIR = RAG_ROOT / "evaluation"


def runtime_dir(override: Path | None = None) -> Path:
    if override is not None:
        return override
    env = os.environ.get("ALTS_RAG_RUNTIME")
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "MinaAnalytics" / "AltsRAG"
    return Path.home() / "MinaAnalytics" / "AltsRAG"


def index_path(runtime: Path) -> Path:
    return runtime / "index" / "current" / "index.sqlite"


def review_csv_path(runtime: Path) -> Path:
    return runtime / "review" / "review-suggestions.csv"


def access_path(runtime: Path) -> Path:
    return runtime / "access.sqlite"
