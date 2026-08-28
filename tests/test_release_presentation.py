from __future__ import annotations

import csv
import os
import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".pytest_cache", "__pycache__"}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def repository_directories() -> list[Path]:
    output: list[Path] = []
    for current, directories, _files in os.walk(PROJECT_ROOT):
        directories[:] = [name for name in directories if name not in EXCLUDED]
        path = Path(current)
        if ".git" not in path.parts:
            output.append(path)
    return output


def test_every_directory_has_a_folder_guide() -> None:
    """Every folder explains itself. What each file is stays in the guide's own
    prose and in docs/PROJECT-MANIFEST.csv, which carries every path with its
    size, hash, policy, and role."""

    for directory in repository_directories():
        readme = directory / "README.md"
        assert readme.is_file(), f"missing {readme}"
        text = readme.read_text(encoding="utf-8-sig").strip()
        assert text.startswith("#"), f"{readme} opens with something other than a heading"
        assert len(text) > 80, f"{readme} is too short to describe the folder"


def test_reviewer_documents_state_the_data_boundary() -> None:
    files = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "PROCESS.md",
        PROJECT_ROOT / "instructions" / "REVIEWER-GUIDE.md",
        PROJECT_ROOT / "docs" / "STATUS.md",
        PROJECT_ROOT / "docs" / "ARCHITECTURE.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8-sig") for path in files)
    folded = combined.casefold()

    assert "source-to-analysis path proven end to end" not in folded
    assert "eight-part physical key" not in folded
    assert "no git repository has been created" not in folded
    assert "c:\\users\\moses" not in folded
    assert "alts-sample-project" not in folded
    assert "fund-level promotion" in folded
    assert "analytics path does not read" in folded or "analytics path reads" in folded
    # The tables are populated on disk, so the landing documents may not say
    # they are empty, and the fund-model warehouse is tracked, so they may not
    # say it is absent.
    assert "headers only" not in folded
    assert "alts.duckdb is absent" not in folded
    assert "promotion step between those paths is not present" not in folded


def test_reviewer_documents_avoid_internal_timeline_language() -> None:
    files = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "PROCESS.md",
        PROJECT_ROOT / "instructions" / "REVIEWER-GUIDE.md",
        PROJECT_ROOT / "docs" / "STATUS.md",
        PROJECT_ROOT / "docs" / "ARCHITECTURE.md",
        PROJECT_ROOT / "docs" / "REPOSITORY-BOUNDARY.md",
    ]
    patterns = [
        r"\bnow\b",
        r"\btoday\b",
        r"\bcurrently\b",
        r"\bearlier\b",
        r"\bprevious(?:ly)?\b",
        r"\bretired\b",
        r"\bhistorical\b",
        r"\bweeks went\b",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        for pattern in patterns:
            assert re.search(pattern, text, flags=re.I) is None, f"{pattern} in {path}"


def test_review_tables_cover_every_fact() -> None:
    review = PROJECT_ROOT / "data" / "extracted" / "review"
    facts = read_rows(PROJECT_ROOT / "data" / "extracted" / "tables" / "fact_observation.csv")
    lineage = read_rows(review / "observation-lineage.csv")
    documents = read_rows(review / "document-summary.csv")

    published = len(facts)
    assert published > 7_000
    assert len(lineage) == published
    assert len({row["observation_id"] for row in lineage}) == published
    assert len(documents) == 29
    assert sum(int(row["final_rows"]) for row in documents) == published


def test_project_manifest_covers_tracked_files() -> None:
    tracked = set(
        subprocess.run(
            ["git", "ls-files"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=True,
        ).stdout.splitlines()
    )
    manifest = {row["path"]: row for row in read_rows(PROJECT_ROOT / "docs" / "PROJECT-MANIFEST.csv")}
    missing = sorted(path for path in tracked if path not in manifest)
    assert missing == []
    wrong_policy = sorted(
        path for path in tracked if manifest[path].get("repository_policy") != "TRACK"
    )
    assert wrong_policy == []


def test_internal_landing_note_is_absent() -> None:
    assert not (PROJECT_ROOT / "notes.md").exists()
