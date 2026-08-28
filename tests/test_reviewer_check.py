"""The closing gate passes on the published tree and states the boundary.

The boundary a reviewer has to see is between printed rows and generated
rows inside one fund model: both populations are present, both are counted,
and every row says which it is. A gate that asserted the fund tables were
empty, or that the fund-model warehouse was absent, would fail on disk, so
those are the claims this file refuses to let back in.
"""

from __future__ import annotations

import pytest

from src.pipeline import reviewer_check


LOCAL_SOURCES = any(
    (reviewer_check.PROJECT_ROOT / "data" / "documents" / "pdf").glob("*.pdf")
)


@pytest.mark.skipif(not LOCAL_SOURCES, reason="local source files are absent")
def test_reviewer_baseline_passes() -> None:
    checks, open_items = reviewer_check.run_checks(reviewer_check.PROJECT_ROOT)
    failures = [check for check in checks if not check.passed]

    assert failures == []
    assert len(checks) >= 100
    assert open_items == []


@pytest.mark.skipif(not LOCAL_SOURCES, reason="local source files are absent")
def test_reviewer_baseline_states_the_printed_and_generated_boundary() -> None:
    checks, _ = reviewer_check.run_checks(reviewer_check.PROJECT_ROOT)
    by_name = {check.name: check for check in checks}

    assert by_name["review physical pairs"].actual == 6_111
    assert by_name["review value agreements"].actual == 5_661
    assert by_name["review value conflicts"].actual == 450
    assert by_name["fund-model fund_periods printed rows"].actual == 378
    assert by_name["fund-model fund_periods generated rows"].actual == 934
    assert by_name["fund-model fund_observations printed rows"].actual == 3_803
    assert by_name["fund-model warehouse present"].actual is True
    assert by_name["extracted-only metric rows"].actual == 804
    assert by_name["extracted-only metric provenance"].actual == {"EXTRACTED"}
    assert by_name["integrated metric provenance"].actual == {"SYNTHETIC"}
    assert by_name["integrated PME provenance"].actual == {"SYNTHETIC"}
