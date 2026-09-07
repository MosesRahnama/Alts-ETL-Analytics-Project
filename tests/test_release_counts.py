"""Reviewer-facing prose may not state a count the release contradicts.

Audit finding A06. The landing page said 7,201 observations while the dashboard
cards read 7,284, and the prose said 42 record columns against a contract of 47.
Each number was typed into prose once and then left behind by a release.

This checks the numbers that actually drifted, in the files a reviewer reads.
A stale number here is a defect, not a style point: it tells a reviewer the
release is smaller or narrower than the data they are looking at.
"""
from __future__ import annotations

import re
import csv
import unittest
from unittest.mock import patch
from pathlib import Path

from src.repository import build_release_counts

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Files a reviewer reads directly. Working notes and audit ledgers are excluded:
# they record what was true when they were written.
#
# The four hand-written folder guides and the pipeline diagram were outside
# this list while carrying five superseded numbers apiece, which is how the
# release-count gate passed green over stale prose. A folder guide a generator
# rewrites is checked by that generator; these five are maintained by hand and
# nothing else reads them.
REVIEWER_TEXT = (
    "README.md",
    "docs/STATUS.md",
    "docs/ARCHITECTURE.md",
    "docs/FINAL-RELEASE-AUDIT.md",
    "docs/SYNTHETIC-DATA-AND-QUALITY.md",
    "docs/DATA-MODEL.md",
    "docs/EXTRACTED-DATA-MODEL.md",
    "data/csv/README.md",
    "data/extracted/README.md",
    "data/extracted/fund-level/README.md",
    "data/integrated/README.md",
    "data/warehouse/README.md",
    "instructions/PIPELINE-VISUAL-GUIDE.md",
    "src/dashboard/build_dashboard.py",
    "src/dashboard/teaching.py",
    "src/dashboard/glossary.py",
    "src/repository/build_readmes.py",
)

# One count, and the shapes of a claim about it. A number that is superseded
# names the count it belongs to, so the message can say what it should read.
#
# `quality_results` listed 35,118, a number no release ever published, while
# five reviewer files carried 35,160. A pattern that matches nothing passes in
# silence, so each entry below is checked against the tree it was written for.
# A count, and the phrase a reviewer file writes beside it. The number is read
# out of the prose and compared with the release, so nobody has to predict the
# value it will drift to. A phrase belongs here when it names one count and
# nothing else; `934` alone appears in a dozen unrelated sentences, so only the
# counts with a distinctive phrase are checked this way.
STATED_BESIDE = {
    "transformation_matrices": (r"(?P<count>[\d,]+) rule-family matrices",),
    "record_columns": (
        r"(?P<count>\d+)[- ](?:column|columns) (?:row format|field list|source observations|observations)",
    ),
    "published_observations": (
        r"(?P<count>[\d,]+) printed values",
        r"(?P<count>[\d,]+) printed facts",
        r"(?P<count>[\d,]+) records, 311 page rows",
        r"\| Published observations \| (?P<count>[\d,]+) \|",
        r"\| Observation origin rows \| (?P<count>[\d,]+) \|",
    ),
    # The release-check page states the extraction and analytics results in
    # one table apiece. Each row named one count and none was read back, so
    # the page kept a 144-check gate and 29 assigned documents after the
    # release had moved on from both.
    "published_documents": (
        r"(?P<count>\d+)-document extraction rollup",
        r"\| Published documents \| (?P<count>[\d,]+) \|",
    ),
    "published_pages": (r"\| Covered pages \| (?P<count>[\d,]+) \|",),
    "physical_ab_pairs": (r"\| Cells found by both extractors \| (?P<count>[\d,]+) \|",),
    "raw_value_agreements": (r"\| Printed value agreements \| (?P<count>[\d,]+),",),
    "source_only_fund_metrics": (r"\| Source-only metrics \| (?P<count>[\d,]+) \|",),
    "pme_results": (r"\| PME results \| (?P<count>[\d,]+) \|",),
    "fund_periods": (r"(?P<count>[\d,]+) periods with source class",),
    "fund_observations": (
        r"(?P<count>[\d,]+) fund observations",
        r"\| `fund_observations.csv` \| (?P<count>[\d,]+) \|",
    ),
    # Two quality populations print the same words, so each phrase carries the
    # label of the layer it belongs to.
    "quality_results": (
        r"(?P<count>[\d,]+) fund-model results",
        r"\| Integrated review \| (?P<count>[\d,]+) rule results",
    ),
    "source_only_quality_results": (
        r"\| Fund tables before fill \| (?P<count>[\d,]+) rule results",
        r"(?P<count>[\d,]+) rule results on these tables alone",
    ),
    "source_backed_fund_periods": (r"\| Source-only fund periods \| (?P<count>[\d,]+) \|",),
    "return_rows": (r"(?P<count>[\d,]+) published return rows",),
    "qualifier_backlog_rows": (
        r"(?P<count>[\d,]+) published rows in [\d,]+ documents leave a qualifier blank",
    ),
    "qualifier_backlog_documents": (
        r"[\d,]+ published rows in (?P<count>[\d,]+) documents leave a qualifier blank",
    ),
    "unfinished_documents": (
        r"(?P<count>\d+) documents in the active scope have no final",
        r"unfinished documents: (?P<count>\d+)",
    ),
}


def stated_beside() -> dict[str, tuple[str, ...]]:
    """The phrases above, plus one per row of the two lists a release splits.

    The return split and the per-document backlog carry one count each and both
    lists move with the corpus, so their phrases are derived from the same
    functions that write the counts instead of being retyped here.
    """

    patterns = dict(STATED_BESIDE)
    for method, fee_basis, _count in build_release_counts.return_qualifier_counts():
        patterns[build_release_counts.return_count_name(method, fee_basis)] = (
            rf"\| `{re.escape(method)}` \| `{re.escape(fee_basis)}` \| (?P<count>[\d,]+) \|",
        )
    for _route, file_id, _count in build_release_counts.qualifier_backlog():
        patterns[build_release_counts.backlog_count_name(file_id)] = (
            rf"\| {re.escape(file_id)} \| (?P<count>[\d,]+) \|",
        )
    return patterns

SUPERSEDED = {
    "published_observations": (r"7,201", r"\b7201\b"),
    "record_columns": (r"\b42[- ](?:columns?|fields?)\b", r"\b42 (?:columns|fields)\b"),
    "fund_periods": (r"1,312\b", r"\b378 periods\b"),
    "source_backed_fund_periods": (r"\b378\b",),
    "quality_results": (r"35,160\b", r"\b35160\b", r"35,118\b"),
    "transformation_matrices": (r"\b32[12] (?:matrices|rule-family matrices)\b",),
    "metric_categories": (r"\b8[89] metric (?:names|categories)\b",),
    "reconstructed_wide_tables": (r"\b17 (?:reconstructed|wide|evidence-wide)\b",),
}


class ReleaseCountTests(unittest.TestCase):
    def test_category_register_matches_published_and_assigned_documents(self) -> None:
        documents = build_release_counts.category_documents()
        with (PROJECT_ROOT / build_release_counts.CATEGORY_CSV).open(encoding="utf-8", newline="") as handle:
            self.assertEqual(list(csv.DictReader(handle)), documents)
        rendered = (PROJECT_ROOT / build_release_counts.CATEGORY_MD).read_text(encoding="utf-8")
        self.assertEqual(rendered, build_release_counts.category_markdown(documents))
        for category in build_release_counts.CANONICAL_DOC_TYPES:
            self.assertIn(f"| {category} |", rendered)
        self.assertEqual(len({row["file_id"] for row in documents}), len(documents))
        self.assertEqual(
            sum(int(row["published_pages"]) for row in documents),
            build_release_counts.rows_in("data/extracted/pdf-wide-coverage.csv"),
        )

    def test_category_register_refuses_assignment_category_drift(self) -> None:
        read_rows = build_release_counts.read_rows
        def changed(relative: str) -> list[dict[str, str]]:
            rows = read_rows(relative)
            if relative == "data/schemas/EXTRACTION-ROUTING.csv":
                for row in rows:
                    row["canonical_doc_type"] = "invented_category"
            return rows
        with patch.object(build_release_counts, "read_rows", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "categories disagree"):
                build_release_counts.category_documents()

    def test_the_counts_file_matches_the_release(self) -> None:
        """The artifact is derived, so regenerating it must change nothing."""
        stored = build_release_counts.read()
        self.assertTrue(stored, "docs/RELEASE-COUNTS.csv is missing")
        fresh = {row["name"]: row["value"] for row in build_release_counts.counts()}
        self.assertEqual(stored, fresh)

    def test_a_stated_count_beside_its_own_phrase_is_the_current_one(self) -> None:
        """The number a reviewer file states next to a phrase naming a count.

        The list of superseded numbers above only catches a value somebody
        remembered to add: correcting 321 to 328 passed this file green while
        a new matrix made the release 329. This reads the number out of the
        prose and compares it with the release, so a count is checked without
        anyone predicting what it will drift to."""

        current = build_release_counts.read()
        findings: list[str] = []
        for relative in REVIEWER_TEXT:
            path = PROJECT_ROOT / relative
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for name, patterns in stated_beside().items():
                for pattern in patterns:
                    for match in re.finditer(pattern, text):
                        stated = match.group("count").replace(",", "")
                        if stated != current.get(name, ""):
                            line = text[: match.start()].count("\n") + 1
                            findings.append(
                                f"{relative}:{line} states {match.group(0)!r}; "
                                f"{name} is {current.get(name, '?')}"
                            )
        self.assertEqual(findings, [], "\n" + "\n".join(findings))

    def test_no_superseded_pattern_matches_a_current_count(self) -> None:
        """A pattern must reject the old number and accept the current one.

        `\\b378\\b` reads as a stale period count only while the release has a
        different one. Were a count to return to a value this list forbids,
        every correct statement of it would be reported as a defect, so the
        two are compared here."""

        current = build_release_counts.read()
        for name, patterns in SUPERSEDED.items():
            value = current.get(name, "")
            self.assertTrue(value, f"{name} is not a released count")
            for rendered in (value, f"{int(value):,}" if value.isdigit() else value):
                for pattern in patterns:
                    self.assertIsNone(
                        re.fullmatch(pattern, rendered),
                        f"{name}: pattern {pattern!r} forbids its own current value {rendered!r}",
                    )

    def test_the_reviewer_prose_states_the_return_split_and_the_backlog(self) -> None:
        """A phrase pattern that matches nothing passes in silence.

        The return split, the per-document backlog and the unfinished documents
        are stated in one reviewer file, so the pattern for each is required to
        find its sentence there. No surface presents `return` as one measure."""

        text = (PROJECT_ROOT / "docs" / "EXTRACTED-DATA-MODEL.md").read_text(encoding="utf-8")
        prefixes = ("return_rows", "qualifier_backlog", "unfinished_documents")
        missing = [
            name
            for name, patterns in stated_beside().items()
            if name.startswith(prefixes)
            and not any(re.search(pattern, text) for pattern in patterns)
        ]
        self.assertEqual(missing, [])
        for file_id in build_release_counts.unfinished_documents():
            self.assertIn(file_id, text)

    def test_every_governed_count_is_a_number_a_reviewer_can_check(self) -> None:
        """Each count names the file it was read from, and that file exists."""

        for row in build_release_counts.counts():
            source = row["source"]
            self.assertTrue(row["value"], row["name"])
            self.assertTrue(row["note"].endswith("."), row["name"])
            if "/" in source:
                self.assertTrue((PROJECT_ROOT / source).exists(), f"{row['name']}: {source}")

    def test_reviewer_text_states_no_superseded_count(self) -> None:
        current = build_release_counts.read()
        self.assertTrue(current, "docs/RELEASE-COUNTS.csv is missing")
        findings: list[str] = []
        for relative in REVIEWER_TEXT:
            path = PROJECT_ROOT / relative
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for name, patterns in SUPERSEDED.items():
                for pattern in patterns:
                    for match in re.finditer(pattern, text):
                        line = text[: match.start()].count("\n") + 1
                        findings.append(
                            f"{relative}:{line} states {match.group(0)!r}; "
                            f"{name} is {current.get(name, '?')}"
                        )
        self.assertEqual(findings, [], "\n" + "\n".join(findings))


if __name__ == "__main__":
    unittest.main()
