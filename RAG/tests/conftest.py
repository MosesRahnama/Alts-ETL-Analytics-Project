from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

RAG_SRC = Path(__file__).resolve().parents[1] / "src"
PROJECT = Path(__file__).resolve().parents[2]
if str(RAG_SRC) not in sys.path:
    sys.path.insert(0, str(RAG_SRC))
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "corpus"
WORKLIST = Path(__file__).resolve().parent / "fixtures" / "worklist.csv"


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    path = tmp_path / "runtime"
    monkeypatch.setenv("ALTS_RAG_RUNTIME", str(path))
    return path


@pytest.fixture
def engine(runtime):
    from alts_rag.network import install_socket_guard
    from alts_rag.service import Engine

    socket_connect = socket.socket.connect
    create_connection = socket.create_connection
    install_socket_guard()
    item = Engine(project_root=FIXTURE_ROOT, runtime=runtime)
    item.index()
    try:
        yield item
    finally:
        item.close()
        socket.socket.connect = socket_connect  # type: ignore[method-assign]
        socket.create_connection = create_connection
