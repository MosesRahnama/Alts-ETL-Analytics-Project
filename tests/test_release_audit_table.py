"""The release table includes extraction and records only executed check results."""

import csv
from types import SimpleNamespace

import pytest

from src.pipeline import release_checks
from src.repository import build_release_audit as audit


def test_complete_process_matches_the_release():
    rows = audit.report_rows()
    assert [row["order"] for row in rows] == [str(n) for n in range(1, len(rows) + 1)]
    assert [row["stage_id"] for row in rows[:4]] == list(audit.PREPARATION_IDS)
    assert all(not row["execution_order"] for row in rows[:4])
    assert rows[4]["execution_order"] == "3"
    assert rows[4]["stage_id"] == "corpus-publication"
    audit.build(check=True)


@pytest.mark.parametrize("change", ["omit-preparation", "omit-stage", "duplicate", "wrong-order"])
def test_description_registry_rejects_incomplete_or_wrong_sequence(tmp_path, change):
    with audit.CATALOG.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header, rows = reader.fieldnames, list(reader)
    if change == "omit-preparation":
        rows.pop(0)
    elif change == "omit-stage":
        rows.pop(5)
    elif change == "duplicate":
        rows.insert(0, rows[0])
    else:
        rows[4]["execution_order"] = "99"
    path = tmp_path / "steps.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError):
        audit.stage_catalog(path)


def test_new_execution_stage_requires_a_description():
    from src.pipeline.publish_review_release import stages
    items = list(stages())
    items.insert(1, SimpleNamespace(stage_id="new-stage", order=4, command="check"))
    with pytest.raises(ValueError, match="every execution stage"):
        audit.stage_catalog(release_stages=items)


def test_unrecorded_results_never_become_pass():
    rows = audit.report_rows(results=[])
    assert all(row["status"] == "NOT_RUN" and not row["evidence"] for row in rows)


def test_latest_failure_replaces_an_earlier_pass(tmp_path):
    path = tmp_path / "checks.csv"
    release_checks.run_check("check", "command", lambda: "passed", path=path)
    with pytest.raises(ValueError):
        release_checks.run_check("check", "command", lambda: (_ for _ in ()).throw(ValueError("refused")), path=path)
    results = release_checks.read_results(path)
    assert [row["status"] for row in results] == ["PASS", "FAIL"]
    row = audit.report_rows(catalog=[{"stage_id": "check", "test": "command"}], results=results)[0]
    assert row["status"] == "FAIL"
    assert "refused" in row["result_detail"]
    assert results[-1]["check_id"] in row["evidence"]


def test_zero_output_check_has_a_record(tmp_path):
    path = tmp_path / "checks.csv"
    release_checks.run_check("verification", "check-only", lambda: None, path=path)
    assert release_checks.read_results(path)[0]["status"] == "PASS"
    assert list(tmp_path.iterdir()) == [path]


def test_changed_command_does_not_inherit_pass(tmp_path):
    path = tmp_path / "checks.csv"
    release_checks.run_check("check", "old-command", lambda: None, path=path)
    row = audit.report_rows(catalog=[{"stage_id": "check", "test": "new-command"}],
                            results=release_checks.read_results(path))[0]
    assert row["status"] == "STALE"


def test_edited_pass_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "audit.csv"
    path.write_text(audit.render().replace("NOT_RUN", "PASS"), encoding="utf-8")
    # A forged row is refused even when every current result already passes.
    path.write_text(path.read_text(encoding="utf-8") + "1,forged,PASS\n", encoding="utf-8")
    monkeypatch.setattr(audit, "OUTPUT", path)
    with pytest.raises(ValueError, match="stale"):
        audit.build(check=True)


def test_failure_during_publish_is_recorded(tmp_path, monkeypatch):
    from src.pipeline import publish_review_release as release
    monkeypatch.setattr(release_checks, "OUTPUT", tmp_path / "checks.csv")
    monkeypatch.setattr(release, "working_final_files", lambda: ["final"])
    monkeypatch.setattr(release, "round_files", lambda: ["round"])
    item = SimpleNamespace(order=15, stage_id="verification", command="check", action=lambda: None,
                           declared_inputs=lambda: [], declared_outputs=lambda: [])
    monkeypatch.setattr(release, "stages", lambda: [item])
    monkeypatch.setattr(release, "stage", lambda *args: (_ for _ in ()).throw(release.ReleaseError("refused")))
    rebuilt = []
    monkeypatch.setattr(audit, "build", lambda: rebuilt.append(True))
    with pytest.raises(release.ReleaseError, match="refused"):
        release.publish()
    assert release_checks.read_results()[0]["status"] == "FAIL"
    assert rebuilt == [True]
