from __future__ import annotations

import re

from src.dashboard.build_dashboard import evidence_review_section
from src.dashboard.page import SCRIPT, render


def test_evidence_section_contains_the_local_console() -> None:
    section = evidence_review_section()
    consoles = [block for block in section["blocks"] if block.get("kind") == "rag_console"]
    assert len(consoles) == 1
    assert consoles[0]["source"] == "RAG/src/alts_rag/service.py"


def test_dashboard_makes_no_automatic_loopback_probe() -> None:
    assert "fetch('/status'" not in SCRIPT
    assert "127.0.0.1" not in SCRIPT
    endpoints = re.findall(r"fetch\((['\"])(.*?)\1", SCRIPT)
    assert all(endpoint.startswith("/") for _quote, endpoint in endpoints)


def test_dashboard_renders_the_console_without_the_engine() -> None:
    page = render(
        {
            "title": "Fixture",
            "subtitle": "Fixture",
            "footer": "",
            "sections": [
                {
                    "id": "evidence-review",
                    "title": "Evidence",
                    "blurb": "Fixture",
                    "blocks": [
                        {
                            "kind": "rag_console",
                            "title": "Local evidence console",
                            "about": "Fixture",
                            "source": "RAG/src/alts_rag/service.py",
                            "hybrid_default": False,
                        }
                    ],
                }
            ],
        }
    )
    assert "Local evidence console" in page
    assert "Run local review" in page
    assert "/document" in page
