"""The optional local field guide uses current release data and explains each step."""

from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.dashboard import build_field_guide

pytestmark = pytest.mark.skipif(
    not build_field_guide.TEMPLATE.is_file(),
    reason="The field-guide template is local-only and absent from public clones.",
)

PAYLOAD = re.compile(r'<script id="payload" type="application/json">(.*?)</script>', re.S)


def built_guide() -> tuple[str, dict]:
    text = build_field_guide.render()
    match = PAYLOAD.search(text)
    assert match is not None
    return text, json.loads(match.group(1))


def test_local_field_guide_matches_the_builder() -> None:
    expected, _ = built_guide()
    actual = build_field_guide.OUTPUT.read_text(encoding="utf-8")
    assert actual == expected


def test_field_guide_uses_current_counts_and_defines_the_evidence_chain() -> None:
    _, payload = built_guide()
    help_text = json.dumps(payload["help"])
    overview = next(section for section in payload["sections"] if section["id"] == "overview")
    extraction = next(section for section in payload["sections"] if section["id"] == "extraction")
    documents = len(extraction["blocks"][2]["items"])
    assert "36 of the 452 listed reports" in help_text
    assert "693 reviewed pages" in help_text
    assert "records-a.csv" in help_text
    assert "records-final.csv" in help_text
    assert "fact_observation.csv" in help_text
    assert "reviewer-cell-lineage.csv" in help_text
    assert documents > 0
    assert "Twenty-nine" not in help_text
    assert not [
        block
        for block in overview["blocks"]
        if block.get("href") == "dashboard.html#overview"
    ]


def test_release_explanations_cover_the_current_29_steps() -> None:
    text, payload = built_guide()
    section = next(item for item in payload["sections"] if item["id"] == "overview")
    table = next(item for item in section["blocks"] if item.get("source") == "docs/FINAL-RELEASE-AUDIT.csv")
    stage_index = table["columns"].index("stage")
    assert len(table["rows"]) == 29
    assert [row[stage_index] for row in table["rows"][:4]] == [
        "Source collection and classification",
        "Document preparation",
        "Independent extraction",
        "Adjudication and source review",
    ]
    shell = PAYLOAD.sub("<payload>", text)
    ids = [entry["id"] for entry in table["explanations"]]
    stage_id_index = table["columns"].index("stage_id") if "stage_id" in table["columns"] else len(table["columns"]) + table["hidden"].index("stage_id")
    assert ids == [row[stage_id_index] for row in table["rows"]]
    # The guide reads the dashboard's explanations and keeps no copy of its own.
    assert "RELEASE_EXPLANATIONS" not in shell
    assert "if (id === 'dash-overview') id = 'overview';" in shell


def test_field_guide_build_can_write_an_independent_file() -> None:
    with TemporaryDirectory() as directory:
        output = Path(directory) / "guide.html"
        path, size = build_field_guide.build(output)
        assert path == output
        assert size == output.stat().st_size
        assert output.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_the_guide_is_written_only_inside_the_ignored_audit_tree() -> None:
    relative = build_field_guide.OUTPUT.relative_to(build_field_guide.PROJECT_ROOT)
    assert relative.parts[0] == "audit"
    assert not (build_field_guide.PROJECT_ROOT / "dashboard-field-guide.html").exists()


def test_the_build_writes_the_guide_and_nothing_beside_it(tmp_path, monkeypatch) -> None:
    output = tmp_path / "project-outline" / "guide.html"
    monkeypatch.setattr(build_field_guide, "OUTPUT", output)
    monkeypatch.setattr(build_field_guide, "render", lambda: "<!doctype html>\nCurrent guide\n")
    build_field_guide.build()
    assert output.read_text(encoding="utf-8") == "<!doctype html>\nCurrent guide\n"
    assert [path.name for path in sorted(tmp_path.rglob("*")) if path.is_file()] == ["guide.html"]


def test_custom_output_does_not_overwrite_the_project_guide(tmp_path, monkeypatch) -> None:
    project_guide = tmp_path / "guide.html"
    project_guide.write_text("Existing guide", encoding="utf-8")
    monkeypatch.setattr(build_field_guide, "OUTPUT", project_guide)
    monkeypatch.setattr(build_field_guide, "render", lambda: "<!doctype html>Custom guide")
    build_field_guide.build(tmp_path / "custom.html")
    assert project_guide.read_text(encoding="utf-8") == "Existing guide"


def test_guide_uses_dashboard_layout_and_current_sequence() -> None:
    text, payload = built_guide()
    assert re.search(r"<style>(.*?)</style>", text, re.S).group(1) == build_field_guide.STYLE
    shell = PAYLOAD.sub("<payload>", text)
    assert "panel.classList.add('release-audit')" in shell
    assert "The work before this table" not in shell
    assert "157 checks" not in shell
    copy = json.dumps(payload["sections"], ensure_ascii=False)
    assert "Process step 3, after document preparation and before any proposal becomes accepted evidence." in copy
    assert "The final row keeps the printed value, normalized field name, evidence location, decision, and links to both proposals." in copy
    dashboard = PAYLOAD.search(build_field_guide.build_dashboard.OUTPUT.read_text(encoding="utf-8"))
    assert dashboard is not None
    original = json.loads(dashboard.group(1))
    def audit_table(data):
        overview = next(section for section in data["sections"] if section["id"] == "overview")
        return next(block for block in overview["blocks"] if block.get("source") == "docs/FINAL-RELEASE-AUDIT.csv")
    assert audit_table(payload) == audit_table(original)
