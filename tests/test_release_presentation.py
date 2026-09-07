from __future__ import annotations

import csv
import re
import subprocess
from pathlib import Path

import pytest

from src.common import matrices
from src.pipeline import publish_review_release as release
from src.repository import release_audit
from src.repository import build_readmes
from src.repository.build_readmes import project_directories

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_prepared_extraction_guides_describe_pending_work(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(build_readmes, "PROJECT_ROOT", tmp_path)
    relative = "ledgers/working/pdf-extraction-csv/05-fund-legal-docs/SRC001"
    assert "pending" in build_readmes.empty_reason(f"{relative}/records-a.csv")
    assert build_readmes.diagram_for(relative, [], []) == ""
    assert "300 DPI" in build_readmes.purpose_for("data/documents/images/example")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def repository_directories() -> list[Path]:
    """The folders this test expects a guide for.

    A fourth private walker with a three-name skip list demanded a folder
    guide inside `.ruff_cache` as soon as the project's own lint command ran.
    The manifest, the structure gate, the folder-guide generator, and this test
    now agree on which folders a released tree carries."""

    return project_directories()


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
    """The patterns and the files are rows of presentation-patterns.csv, the
    matrix the release audit reads, so this test and the audit refuse the
    same words in the same files."""

    files = release_audit.presentation_targets(PROJECT_ROOT, "timeline_target")
    assert {
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "PROCESS.md",
        PROJECT_ROOT / "instructions" / "REVIEWER-GUIDE.md",
        PROJECT_ROOT / "docs" / "STATUS.md",
        PROJECT_ROOT / "docs" / "ARCHITECTURE.md",
        PROJECT_ROOT / "docs" / "REPOSITORY-BOUNDARY.md",
    } <= files
    patterns = [
        row["input_value"]
        for context in ("timeline", "presentation")
        for row in matrices.rows_in(release_audit.PRESENTATION_PATTERNS, context)
    ]
    assert r"\bnow\b" in patterns and r"\bweeks went\b" in patterns
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        for pattern in patterns:
            assert re.search(pattern, text, flags=re.I) is None, f"{pattern} in {path}"


def test_the_presentation_audit_reads_the_matrix_and_passes_on_the_tree() -> None:
    assert release_audit.presentation_findings(PROJECT_ROOT) == []
    assert not hasattr(release_audit, "_legacy_patterns")
    for context in ("presentation", "timeline", "presentation_target", "timeline_target"):
        assert matrices.rows_in(release_audit.PRESENTATION_PATTERNS, context), context


def test_a_pattern_that_does_not_compile_is_an_audit_error_naming_the_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An edited matrix used to abort with a bare AssertionError; a bad row is
    now the audit's own error, which main prints as one FAIL line."""

    bad = [{"input_value": r"\bnow(", "output_value": "timeline word now"}]
    monkeypatch.setattr(matrices, "rows_in", lambda name, context="", root=None: bad)
    with pytest.raises(release_audit.AuditError) as error:
        release_audit.presentation_patterns("timeline")
    assert "timeline" in str(error.value)
    assert r"\bnow(" in str(error.value)


def test_main_reports_a_bad_matrix_as_one_fail_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(root: Path) -> None:
        raise matrices.MatrixError("presentation-patterns: duplicate input_value")

    monkeypatch.setattr(release_audit, "audit", refuse)
    monkeypatch.setattr("sys.argv", ["release_audit"])
    assert release_audit.main() == 1
    printed = capsys.readouterr().out
    assert printed.startswith("FAIL: presentation-patterns")
    assert "Traceback" not in printed


def test_review_tables_cover_every_fact() -> None:
    review = PROJECT_ROOT / "data" / "extracted" / "review"
    facts = read_rows(PROJECT_ROOT / "data" / "extracted" / "tables" / "fact_observation.csv")
    lineage = read_rows(review / "observation-lineage.csv")
    documents = read_rows(review / "document-summary.csv")

    published = len(facts)
    assert published > 7_000
    assert len(lineage) == published
    assert len({row["observation_id"] for row in lineage}) == published
    # The document count is the adjudicated finals, not a literal. A worklist
    # assigns more documents than the tree has finished, and a fixed number
    # here read as full coverage of the assignment.
    assigned = sum(len(release.csv_rows(path)) for path in release.active_worklists())
    assert len(documents) == len(release.working_final_files())
    assert len(documents) <= assigned
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
