from __future__ import annotations

import csv
import os
from pathlib import Path

from src.repository import build_csv_lineage
from src.repository.build_project_manifest import OUTPUT, ROLE_OVERRIDES, role
from src.repository.build_readmes import (
    PROJECT_ROOT,
    hand_written,
    project_directories,
    render_readme,
)
from src.repository.check_project_structure import validate


def test_every_directory_guide_is_current() -> None:
    for directory in project_directories():
        readme = directory / "README.md"
        assert readme.is_file()
        text = readme.read_text(encoding="utf-8-sig")
        if directory != PROJECT_ROOT and not hand_written(directory):
            assert text == render_readme(directory)


def test_csv_lineage_matches_the_public_project_tree() -> None:
    current = build_csv_lineage.OUTPUT.read_text(encoding="utf-8-sig")
    assert current == build_csv_lineage.render()


def test_no_folder_guide_carries_a_generator_marker() -> None:
    """A folder guide is read by people. An HTML comment addressed to a
    generator is a note to a machine sitting in front of every reader, and a
    fork shows it in the raw file."""

    for directory in project_directories():
        text = (directory / "README.md").read_text(encoding="utf-8-sig")
        assert "curated-manual" not in text
        assert "direct-inventory" not in text


def test_manifest_has_one_self_row_without_recursive_hash() -> None:
    with OUTPUT.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    self_rows = [row for row in rows if row["path"] == "docs/PROJECT-MANIFEST.csv"]
    assert len(self_rows) == 1
    assert self_rows[0]["entry_type"] == "file"
    assert self_rows[0]["sha256"] == ""
    # The dashboard renders the manifest, so the manifest lists it unhashed;
    # otherwise each rebuild would invalidate the other.
    page_rows = [row for row in rows if row["path"] == "dashboard.html"]
    assert len(page_rows) == 1
    assert page_rows[0]["sha256"] == ""
    assert page_rows[0]["size_bytes"] == ""


def test_live_project_structure() -> None:
    assert validate(verify_hashes=False) == []


def test_extracted_database_manifest_role_is_count_independent() -> None:
    path = PROJECT_ROOT / "data" / "warehouse" / "extracted.duckdb"
    existing = {
        "data/warehouse/extracted.duckdb": {
            "role": "Stale numeric description that should not survive."
        }
    }
    assert role(path, PROJECT_ROOT, existing) == ROLE_OVERRIDES[
        "data/warehouse/extracted.duckdb"
    ]


def test_core_readmes_form_a_navigable_handoff_chain() -> None:
    chain = (
        "README.md",
        "PROCESS.md",
        "instructions/01-pdf-extraction-csv/README.md",
        "instructions/02-fund-mapping/README.md",
        "instructions/03-synthetic-qc/README.md",
        "instructions/04-analytics/README.md",
        "instructions/REVIEWER-GUIDE.md",
        "data/extracted/review/README.md",
        "data/warehouse/README.md",
        "docs/FINAL-RELEASE-AUDIT.md",
    )
    for source_name, target_name in zip(chain, chain[1:]):
        source = PROJECT_ROOT / source_name
        target = PROJECT_ROOT / target_name
        relative_target = Path(os.path.relpath(target, source.parent)).as_posix()
        assert source.is_file()
        assert target.is_file()
        assert f"]({relative_target})" in source.read_text(encoding="utf-8-sig")


def test_data_readmes_trace_source_to_review_database() -> None:
    chain = (
        "data/documents/README.md",
        "data/extracted/README.md",
        "data/normalization/README.md",
        "data/extracted/fund-level/README.md",
        "data/integrated/README.md",
        "data/csv/README.md",
        "data/extracted/review/README.md",
        "data/warehouse/README.md",
        "docs/FINAL-RELEASE-AUDIT.md",
    )
    for source_name, target_name in zip(chain, chain[1:]):
        source = PROJECT_ROOT / source_name
        target = PROJECT_ROOT / target_name
        relative_target = Path(os.path.relpath(target, source.parent)).as_posix()
        assert f"]({relative_target})" in source.read_text(encoding="utf-8-sig")
