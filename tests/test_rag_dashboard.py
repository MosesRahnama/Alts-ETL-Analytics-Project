"""The standalone RAG page stays current, static, and linked to the main dashboard."""

from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from src.dashboard import build_dashboard, build_rag_dashboard
from src.dashboard.page import SCRIPT
from src.dashboard.publish_dashboard import allowed_path, source_files


PROJECT_ROOT = build_rag_dashboard.PROJECT_ROOT
PAYLOAD = re.compile(
    r'<script id="payload" type="application/json">(.*?)</script>', re.S
)
REMOTE = re.compile(r'(?:src|href)\s*=\s*["\']\s*(?:https?:)?//', re.I)


def build_to(directory: str) -> tuple[Path, str, dict]:
    output = Path(directory) / "rag.html"
    build_rag_dashboard.build(output)
    text = output.read_text(encoding="utf-8")
    match = PAYLOAD.search(text)
    assert match is not None
    return output, text, json.loads(match.group(1))


def test_rag_page_is_self_contained_and_deterministic() -> None:
    with TemporaryDirectory() as first_directory, TemporaryDirectory() as second_directory:
        _, first, _ = build_to(first_directory)
        _, second, _ = build_to(second_directory)
    assert first == second
    assert first.startswith("<!doctype html>")
    assert not REMOTE.search(first)
    assert "<link" not in first
    assert "<script src" not in first


def test_checked_in_rag_page_matches_the_builder() -> None:
    with TemporaryDirectory() as directory:
        _, rendered, _ = build_to(directory)
    assert (PROJECT_ROOT / "rag.html").read_text(encoding="utf-8") == rendered


def test_rag_page_covers_the_complete_reviewer_story() -> None:
    with TemporaryDirectory() as directory:
        _, text, document = build_to(directory)
    assert [section["id"] for section in document["sections"]] == [
        "overview",
        "architecture",
        "evidence-model",
        "retrieval",
        "verification",
        "use-cases",
        "evaluation",
        "controls",
        "console",
        "operations",
    ]
    copy = json.dumps(document)
    for phrase in (
        "physical PDF page",
        "table row",
        "footnote",
        "SUPPORTED",
        "CONTRADICTED",
        "INSUFFICIENT_EVIDENCE",
        "Extraction evidence lookup",
        "Adjudication and audit",
        "Analytical explanation",
        "zero model requests",
    ):
        assert phrase in copy
    assert "Interactive review is available only from the loopback service" in SCRIPT
    assert "[127, 0, 0, 1].join('.')" in SCRIPT


def test_rag_page_titles_are_declarative() -> None:
    document = build_rag_dashboard.payload()
    question_opening = re.compile(
        r"^(what|how|why|when|where|who|which|whether|is|are|do|does|can|could|should|would)\b",
        re.I,
    )
    titles = [section["title"] for section in document["sections"]]
    titles.extend(
        block.get("text") or block.get("title", "")
        for section in document["sections"]
        for block in section["blocks"]
        if block.get("kind") in {"heading", "table", "guide"}
    )
    for title in titles:
        assert not question_opening.search(title), title
        assert "?" not in title


def test_rag_page_counts_come_from_the_public_export() -> None:
    demo = json.loads(build_rag_dashboard.DEMO.read_text(encoding="utf-8"))
    document = build_rag_dashboard.payload()
    copy = json.dumps(document)
    index = demo["index_summary"]
    evaluation = demo["evaluation_summary"]
    for value in (
        index["indexed_documents"],
        index["indexed_pages"],
        index["block_count"],
        index["vector_blocks"],
        evaluation["case_count"],
    ):
        assert f"{value:,}" in copy


def test_main_dashboard_links_to_the_rag_page() -> None:
    section = next(
        item for item in build_dashboard.payload()["sections"]
        if item["id"] == "evidence-review"
    )
    links = [block for block in section["blocks"] if block.get("kind") == "link"]
    assert any(block.get("href") == "rag.html#overview" for block in links)


def test_publication_includes_only_the_rag_page_and_static_export() -> None:
    completed: set[str] = set()
    assert allowed_path("rag.html", completed)
    assert allowed_path("RAG/evaluation/public-demo.json", completed)
    assert allowed_path("RAG/architecture.html", completed)
    for path in (
        "RAG/src/alts_rag/service.py",
        "RAG/evaluation/results.csv",
        "RAG/Plan.md",
        "dashboard-field-guide.html",
    ):
        assert not allowed_path(path, completed)
    files, _ = source_files(build_dashboard.payload(), PROJECT_ROOT)
    assert "rag.html" in files
    assert "RAG/evaluation/public-demo.json" in files
    assert "RAG/architecture.html" in files


def test_architecture_page_is_an_explanation_not_a_console() -> None:
    from src.dashboard.rag_architecture import architecture_html

    html = architecture_html()
    assert "<svg" in html
    assert "BAAI/bge-small-en-v1.5" in html
    assert "plain english" not in html.lower()
    assert "What the Engine" not in html
    assert "in Plain English" not in html
    assert "rag-console" not in html
    assert "This page describes the system. It does not run a search." in html
