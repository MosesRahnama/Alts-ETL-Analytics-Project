"""The closing gate passes on the published tree and states the boundary.

The boundary a reviewer has to see is between printed rows and generated
rows inside one fund model: both populations are present, both are counted,
and every row says which it is. A gate that asserted the fund tables were
empty, or that the fund-model warehouse was absent, would fail on disk, so
those are the claims this file refuses to let back in.

The three grouping and qualifier checks are pinned twice: once against the
published tree, and once against fixtures that fail each of them by name, so
renaming or deleting one fails here instead of quietly leaving the corpus
unread.
"""

from __future__ import annotations

import csv

import pytest

from src.pipeline import reviewer_check


LOCAL_SOURCES = any(
    (reviewer_check.PROJECT_ROOT / "data" / "documents" / "pdf").glob("*.pdf")
)

# What the gate discloses on every run. These are boundaries the release
# declares and the gate returns 0 with, so requiring the list to be empty made
# the test fail on a disclosure instead of on a defect. A boundary of a kind
# nobody declared still fails.
DECLARED_BOUNDARIES = (
    "published rows awaiting a qualifier reading",
    "assigned documents with no final",
    "unmapped measures by disposition",
    "open gaps",
    "manager identities with no fund, observation, or document link",
)

GROUPING_MATRIX = [
    {"context": "asset_class", "input_value": "Private Equity"},
    {"context": "strategy", "input_value": "Buyout"},
    {"context": "sector", "input_value": "Retail"},
]


def _published_row(**overrides: str) -> dict[str, str]:
    row = {
        "asset_class": "Private Equity",
        "strategy": "Buyout",
        "sector": "",
        "metric_category": "return",
        "method": "time_weighted",
        "fee_basis": "net",
        "definition_keys": "1",
        "basis_raw": "",
    }
    row.update(overrides)
    return row


def _by_name(checks: list[reviewer_check.Check]) -> dict[str, reviewer_check.Check]:
    return {check.name: check for check in checks}


def test_a_clean_row_passes_all_three_grouping_and_qualifier_checks() -> None:
    checks = _by_name(
        reviewer_check.grouping_and_qualifier_checks([_published_row()], GROUPING_MATRIX)
    )

    assert sorted(checks) == [
        "industries filed under asset_class",
        "printed groupings the grouping matrix reads",
        "return rows without a stated method and fee basis",
    ]
    assert all(check.passed for check in checks.values())


def test_an_industry_under_asset_class_fails_its_own_check() -> None:
    checks = _by_name(
        reviewer_check.grouping_and_qualifier_checks(
            [_published_row(asset_class="Retail")], GROUPING_MATRIX
        )
    )

    check = checks["industries filed under asset_class"]
    assert check.actual == 1
    assert check.expected == 0
    assert not check.passed


def test_a_benchmark_name_under_asset_class_fails_the_grouping_check() -> None:
    checks = _by_name(
        reviewer_check.grouping_and_qualifier_checks(
            [_published_row(asset_class="S&P 500 Index")], GROUPING_MATRIX
        )
    )

    check = checks["printed groupings the grouping matrix reads"]
    assert check.actual == {("asset_class", "S&P 500 Index")}
    assert check.expected == set()
    assert not check.passed
    # A benchmark name is nobody's industry, so the sector check stays clean and
    # the two failures cannot be confused for one another.
    assert checks["industries filed under asset_class"].passed


def test_a_return_row_blank_on_method_fails_the_qualifier_check() -> None:
    checks = _by_name(
        reviewer_check.grouping_and_qualifier_checks(
            [_published_row(method="")], GROUPING_MATRIX
        )
    )

    check = checks["return rows without a stated method and fee basis"]
    assert check.actual == 1
    assert check.expected == 0
    assert not check.passed


def test_a_stated_qualifier_citing_neither_definition_nor_basis_fails_the_same_check() -> None:
    """R2's second clause: a value other than `unstated` was read off the page,
    so the row cites `definition_keys` or `basis_raw`; an unstated pair needs
    no citation."""

    stated = _by_name(
        reviewer_check.grouping_and_qualifier_checks(
            [_published_row(definition_keys="", basis_raw="")], GROUPING_MATRIX
        )
    )["return rows without a stated method and fee basis"]
    assert stated.actual == 1
    assert not stated.passed

    cited_by_basis = _by_name(
        reviewer_check.grouping_and_qualifier_checks(
            [_published_row(definition_keys="", basis_raw="net of fees")], GROUPING_MATRIX
        )
    )["return rows without a stated method and fee basis"]
    assert cited_by_basis.passed

    unstated = _by_name(
        reviewer_check.grouping_and_qualifier_checks(
            [_published_row(method="unstated", fee_basis="unstated", definition_keys="", basis_raw="")],
            GROUPING_MATRIX,
        )
    )["return rows without a stated method and fee basis"]
    assert unstated.passed


def _write_csv(path, header: str, *rows: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join((header, *rows)) + "\n", encoding="utf-8", newline="\n")


def test_dispatch_checks_follow_changed_assignments_without_count_pins(tmp_path) -> None:
    worklist = tmp_path / "instructions/01-pdf-extraction-csv/worklists/active/route.csv"
    _write_csv(worklist, "file_id", "SRC001")
    rows = [{"file_id": "SRC001", "dispatch_scope": "ACTIVE"},
            {"file_id": "SRC002", "dispatch_scope": "UNSCHEDULED"}]
    sources = {"SRC001", "SRC002"}
    assert all(c.passed for c in reviewer_check.dispatch_assignment_checks(tmp_path, rows, sources))
    _write_csv(worklist, "file_id", "SRC001", "SRC002")
    rows[1]["dispatch_scope"] = "ACTIVE"
    assert all(c.passed for c in reviewer_check.dispatch_assignment_checks(tmp_path, rows, sources))


def test_dispatch_checks_reject_wrong_ids_with_unchanged_counts(tmp_path) -> None:
    worklist = tmp_path / "instructions/01-pdf-extraction-csv/worklists/active/route.csv"
    _write_csv(worklist, "file_id", "SRC001")
    rows = [{"file_id": "SRC002", "dispatch_scope": "ACTIVE"},
            {"file_id": "SRC001", "dispatch_scope": "UNSCHEDULED"}]
    checks = _by_name(reviewer_check.dispatch_assignment_checks(tmp_path, rows, {"SRC001", "SRC002"}))
    assert not checks["active dispatch rows"].passed
    assert not checks["unscheduled dispatch rows"].passed


def _transport_fixture(tmp_path, wide_method: str, wide_fee_basis: str):
    """One wide row built from an irr stating `unstated` and a net return."""

    _write_csv(
        tmp_path / "data" / "extracted" / "tables" / "fact_observation.csv",
        "observation_id,metric_category,method,fee_basis",
        "OBS_IRR,irr,,unstated",
        "OBS_RET,return,time_weighted,net",
        "OBS_NAV,nav,,",
    )
    _write_csv(
        tmp_path / "data" / "extracted" / "wide" / "bridge_pivot_observation.csv",
        "pivot_table,pivot_row_id,observation_id",
        "wide_performance_observation,ROW_1,OBS_IRR",
        "wide_performance_observation,ROW_1,OBS_RET",
        "wide_performance_observation,ROW_1,OBS_NAV",
    )
    _write_csv(
        tmp_path / "data" / "extracted" / "wide" / "wide_performance_observation.csv",
        "wide_row_id,method_qualifier,fee_basis",
        f"ROW_1,{wide_method},{wide_fee_basis}",
    )
    return tmp_path


def test_a_wide_row_carrying_its_return_cell_pair_passes_the_transport_check(tmp_path) -> None:
    check = reviewer_check.qualifier_transport_check(
        _transport_fixture(tmp_path, "time_weighted", "net")
    )
    assert check.passed


def test_a_pair_assembled_from_two_cells_fails_the_transport_check(tmp_path) -> None:
    """The SRC457 pattern: the return's method beside the irr's fee basis."""

    check = reviewer_check.qualifier_transport_check(
        _transport_fixture(tmp_path, "time_weighted", "unstated")
    )
    assert not check.passed
    assert check.actual == 1


@pytest.mark.skipif(not LOCAL_SOURCES, reason="local source files are absent")
def test_reviewer_baseline_passes() -> None:
    checks, open_items = reviewer_check.run_checks(reviewer_check.PROJECT_ROOT)
    failures = [check for check in checks if not check.passed]

    assert failures == []
    assert len(checks) >= 100
    assert [item for item in open_items if not item.startswith(DECLARED_BOUNDARIES)] == []


@pytest.mark.skipif(not LOCAL_SOURCES, reason="local source files are absent")
def test_reviewer_baseline_states_the_printed_and_generated_boundary() -> None:
    checks, _ = reviewer_check.run_checks(reviewer_check.PROJECT_ROOT)
    by_name = {check.name: check for check in checks}

    def read(relative):
        with (reviewer_check.PROJECT_ROOT / relative).open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    pairs = read("data/extracted/review/document-summary.csv")
    for name, field in [("review physical pairs", "physical_pairs"),
                        ("review value agreements", "raw_value_agreements"),
                        ("review value conflicts", "value_conflicts")]:
        assert by_name[name].actual == sum(int(row[field]) for row in pairs)
    periods = read("data/csv/fund_periods.csv")
    assert by_name["fund-model fund_periods printed rows"].actual == sum(r["provenance_type"] == "EXTRACTED" for r in periods)
    assert by_name["fund-model fund_periods generated rows"].actual == sum(r["provenance_type"] == "SYNTHETIC" for r in periods)
    assert by_name["fund-model fund_observations printed rows"].actual == len(read("data/extracted/fund-level/fund_observations.csv"))
    assert by_name["fund-model warehouse present"].actual is True
    assert by_name["extracted-only metric rows"].actual == len(read("data/extracted/fund-level/fund_metrics.csv"))
    assert by_name["extracted-only metric provenance"].actual == {"EXTRACTED"}
    assert by_name["integrated metric provenance"].actual == {"SYNTHETIC"}
    assert by_name["integrated PME provenance"].actual == {"SYNTHETIC"}


@pytest.mark.skipif(not LOCAL_SOURCES, reason="local source files are absent")
def test_the_published_corpus_is_read_in_full() -> None:
    """The strict expected value of each reading the corpus owes a reviewer."""

    checks, _ = reviewer_check.run_checks(reviewer_check.PROJECT_ROOT)
    by_name = {check.name: check for check in checks}

    assert by_name["printed groupings the grouping matrix reads"].expected == set()
    assert by_name["industries filed under asset_class"].expected == 0
    assert by_name["return rows without a stated method and fee basis"].expected == 0
    assert by_name["qualifier backlog rows"].actual == 0
    assert by_name["qualifier backlog rows"].passed
