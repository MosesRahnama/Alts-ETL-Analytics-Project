"""Guards for the manager round: family grouping, auto-settlement, and merge
integrity in src.catalog.simple_pdf_extraction.name_normalization.

Every test points the module's path constants at a temporary directory so
nothing here touches the live matrices.
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.catalog.simple_pdf_extraction import name_normalization as nm


def write(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class ManagerWorkflowTestCase(unittest.TestCase):
    """Base class that redirects every module path constant into a tmp dir."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._originals = {
            name: getattr(nm, name)
            for name in (
                "FUND_MATRIX",
                "MANAGER_MATRIX",
                "LP_MATRIX",
                "PLAN_MATRIX",
                "COMPANY_MATRIX",
                "WEB_MANAGER_NAMES",
                "MANAGER_QUEUE",
                "WORKSHEET_DIR",
                "NEAR_DUPLICATES",
            )
        }
        nm.FUND_MATRIX = root / "fund-names-matrix.csv"
        nm.MANAGER_MATRIX = root / "manager-names-matrix.csv"
        nm.LP_MATRIX = root / "lp-names-matrix.csv"
        nm.PLAN_MATRIX = root / "plan-names-matrix.csv"
        nm.COMPANY_MATRIX = root / "company-names-matrix.csv"
        nm.WEB_MANAGER_NAMES = root / "web-manager-names.csv"
        nm.MANAGER_QUEUE = root / "manager-queue.csv"
        nm.WORKSHEET_DIR = root / "worksheets"
        nm.NEAR_DUPLICATES = root / "name-near-duplicates.csv"
        nm.KINDS = {
            "fund": (nm.FUND_MATRIX, "fund_name_raw", "standardized_fund_name", "fund_id"),
            "manager": (nm.MANAGER_MATRIX, "manager_name_raw", "standardized_manager_name", "manager_id"),
            "lp": (nm.LP_MATRIX, "lp_name_raw", "standardized_lp_name", "lp_id"),
            "plan": (nm.PLAN_MATRIX, "plan_name_raw", "standardized_plan_name", "plan_id"),
            "company": (nm.COMPANY_MATRIX, "company_name_raw", "standardized_company_name", "company_id"),
        }
        nm.MATRIX_HEADER = {
            kind: [raw, std, nm.FAMILY_COLUMN, entity_id, *nm.MATRIX_TAIL]
            if kind == "fund"
            else [raw, std, entity_id, *nm.MATRIX_TAIL]
            for kind, (_path, raw, std, entity_id) in nm.KINDS.items()
        }
        self.root = root
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        for name, value in self._originals.items():
            setattr(nm, name, value)

    def write_fund_matrix(self, rows: list[dict[str, str]]) -> None:
        write(nm.FUND_MATRIX, nm.MATRIX_HEADER["fund"], rows)

    def fund_row(
        self, raw: str, standard: str, family: str = "", fund_id: str = "", status: str = "decided"
    ) -> dict[str, str]:
        return {
            "fund_name_raw": raw,
            "standardized_fund_name": standard,
            "fund_family": family,
            "fund_id": fund_id,
            "decision_status": status,
            "seen_in_agents": "",
            "source_files": "",
            "a_count": "1",
            "b_count": "0",
            "merge_note": "",
        }


class BuildManagerQueueTests(ManagerWorkflowTestCase):
    def test_a_named_family_becomes_one_lookup_covering_every_member(self) -> None:
        self.write_fund_matrix(
            [
                self.fund_row("Lone Star Fund VII", "Lone Star Fund VII, L.P.", family="Lone Star"),
                self.fund_row("Lone Star Fund VIII", "Lone Star Fund VIII, L.P.", family="Lone Star"),
                self.fund_row("Solo Fund", "Solo Fund, L.P.", family=""),
            ]
        )
        nm.build_manager_queue()
        queue = read(nm.MANAGER_QUEUE)
        self.assertEqual(len(queue), 2, "one family lookup + one standalone fund lookup")
        family_row = next(row for row in queue if row["lookup_kind"] == "family")
        self.assertEqual(family_row["lookup_key"], "Lone Star")
        self.assertEqual(int(family_row["member_count"]), 2)
        members = set(family_row["member_funds"].split(" | "))
        self.assertEqual(members, {"Lone Star Fund VII, L.P.", "Lone Star Fund VIII, L.P."})
        standalone_row = next(row for row in queue if row["lookup_kind"] == "fund")
        self.assertEqual(standalone_row["lookup_key"], "Solo Fund, L.P.")

    def test_a_prior_settlement_is_carried_forward_and_reported_as_covered(self) -> None:
        self.write_fund_matrix([self.fund_row("Acme Fund I", "Acme Fund I, L.P.", family="Acme")])
        write(
            nm.WEB_MANAGER_NAMES,
            nm.WEB_MANAGER_HEADER,
            [
                {
                    "standardized_fund_name": "Acme Fund I, L.P.",
                    "a_manager_name": "",
                    "a_source": "",
                    "b_manager_name": "",
                    "b_source": "",
                    "final_manager_name": "Acme Capital Partners LLC",
                    "final_source": "WEB_MANAGER: https://example.com | Acme runs Acme Fund I.",
                }
            ],
        )
        nm.build_manager_queue()
        queue = read(nm.MANAGER_QUEUE)
        self.assertEqual(queue[0]["final_manager_name"], "Acme Capital Partners LLC")

    def test_rerunning_the_queue_build_does_not_lose_in_progress_search_data(self) -> None:
        self.write_fund_matrix([self.fund_row("Beta Fund I", "Beta Fund I, L.P.", family="Beta")])
        nm.build_manager_queue()
        queue = read(nm.MANAGER_QUEUE)
        queue[0]["a_manager_name"] = "Beta Capital"
        queue[0]["a_source"] = "WEB_MANAGER: https://example.com | Beta Capital runs Beta funds."
        write(nm.MANAGER_QUEUE, nm.MANAGER_QUEUE_HEADER, queue)
        nm.build_manager_queue()
        queue_again = read(nm.MANAGER_QUEUE)
        self.assertEqual(queue_again[0]["a_manager_name"], "Beta Capital")


class AutoSettleTests(ManagerWorkflowTestCase):
    def _seed_queue(self, rows: list[dict[str, str]]) -> None:
        write(nm.MANAGER_QUEUE, nm.MANAGER_QUEUE_HEADER, rows)

    def _row(self, key: str, a_name: str, b_name: str, a_source: str = "s", b_source: str = "s") -> dict[str, str]:
        return {
            "lookup_key": key,
            "lookup_kind": "fund",
            "member_count": "1",
            "member_funds": key,
            "a_manager_name": a_name,
            "a_source": a_source,
            "b_manager_name": b_name,
            "b_source": b_source,
            "final_manager_name": "",
            "final_source": "",
        }

    def test_identical_names_settle_without_alteration(self) -> None:
        self._seed_queue([self._row("Fund A", "Acme Capital", "Acme Capital")])
        nm.auto_settle_manager_queue()
        row = read(nm.MANAGER_QUEUE)[0]
        self.assertEqual(row["final_manager_name"], "Acme Capital")
        self.assertIn("[AUTO: identical]", row["final_source"])

    def test_same_firm_spelled_differently_settles_on_the_fuller_form(self) -> None:
        self._seed_queue([self._row("Fund B", "Acme Capital", "Acme Capital, L.P.")])
        nm.auto_settle_manager_queue()
        row = read(nm.MANAGER_QUEUE)[0]
        self.assertEqual(row["final_manager_name"], "Acme Capital, L.P.")

    def test_one_sided_names_are_kept_per_the_adjudicator_rule(self) -> None:
        self._seed_queue([self._row("Fund C", "Acme Capital", "")])
        nm.auto_settle_manager_queue()
        row = read(nm.MANAGER_QUEUE)[0]
        self.assertEqual(row["final_manager_name"], "Acme Capital")
        self.assertIn("[AUTO: one-sided]", row["final_source"])

    def test_one_sided_settlement_uses_the_source_that_supports_the_name(self) -> None:
        self._seed_queue(
            [
                self._row(
                    "Fund Source",
                    "",
                    "Acme Capital",
                    a_source="WEB_MANAGER: no public manager match found",
                    b_source="WEB_MANAGER: https://example.com | Acme manages the fund",
                )
            ]
        )
        nm.auto_settle_manager_queue()
        row = read(nm.MANAGER_QUEUE)[0]
        self.assertEqual(row["final_manager_name"], "Acme Capital")
        self.assertTrue(row["final_source"].startswith("WEB_MANAGER: https://example.com"))
        self.assertNotIn("no public manager match found", row["final_source"])

    def test_a_stale_one_sided_source_is_repaired(self) -> None:
        row = self._row(
            "Fund Repair",
            "",
            "Acme Capital",
            a_source="WEB_MANAGER: no public manager match found",
            b_source="WEB_MANAGER: https://example.com | Acme manages the fund",
        )
        row["final_manager_name"] = "Acme Capital"
        row["final_source"] = (
            "WEB_MANAGER: no public manager match found  [AUTO: one-sided]"
        )
        self._seed_queue([row])
        nm.auto_settle_manager_queue()
        repaired = read(nm.MANAGER_QUEUE)[0]
        self.assertTrue(
            repaired["final_source"].startswith("WEB_MANAGER: https://example.com")
        )

    def test_a_genuine_disagreement_is_never_auto_settled(self) -> None:
        self._seed_queue([self._row("Fund D", "Acme Capital Group", "Zenith Partners")])
        nm.auto_settle_manager_queue()
        row = read(nm.MANAGER_QUEUE)[0]
        self.assertEqual(row["final_manager_name"], "", "a real disagreement needs a person")

    def test_a_row_with_neither_agent_naming_a_firm_is_left_for_review(self) -> None:
        self._seed_queue([self._row("Fund E", "", "")])
        nm.auto_settle_manager_queue()
        row = read(nm.MANAGER_QUEUE)[0]
        self.assertEqual(row["final_manager_name"], "")

    def test_an_already_settled_row_is_never_touched_again(self) -> None:
        row = self._row("Fund F", "Acme Capital", "Acme Capital")
        row["final_manager_name"] = "Hand-Adjudicated Name LLC"
        row["final_source"] = "WEB_MANAGER: https://example.com | adjudicated by a person"
        self._seed_queue([row])
        nm.auto_settle_manager_queue()
        result = read(nm.MANAGER_QUEUE)[0]
        self.assertEqual(result["final_manager_name"], "Hand-Adjudicated Name LLC")


class MergeManagerSlicesTests(ManagerWorkflowTestCase):
    def test_merge_refuses_a_slice_naming_an_unknown_lookup(self) -> None:
        write(
            nm.MANAGER_QUEUE,
            nm.MANAGER_QUEUE_HEADER,
            [
                {
                    "lookup_key": "Real Fund",
                    "lookup_kind": "fund",
                    "member_count": "1",
                    "member_funds": "Real Fund",
                    "a_manager_name": "",
                    "a_source": "",
                    "b_manager_name": "",
                    "b_source": "",
                    "final_manager_name": "",
                    "final_source": "",
                }
            ],
        )
        nm.WORKSHEET_DIR.mkdir(parents=True, exist_ok=True)
        write(
            nm.WORKSHEET_DIR / "manager-01-a.csv",
            ["lookup_key", "lookup_kind", "member_count", "member_funds", "a_manager_name", "a_source"],
            [
                {
                    "lookup_key": "Invented Fund Nobody Asked For",
                    "lookup_kind": "fund",
                    "member_count": "1",
                    "member_funds": "Invented Fund Nobody Asked For",
                    "a_manager_name": "Made Up Capital",
                    "a_source": "WEB_MANAGER: https://example.com | fabricated",
                }
            ],
        )
        result = nm.merge_manager_slices()
        self.assertEqual(result, 1, "a slice inventing a lookup must fail closed")

    def test_merge_folds_a_valid_slice_back_into_the_queue(self) -> None:
        write(
            nm.MANAGER_QUEUE,
            nm.MANAGER_QUEUE_HEADER,
            [
                {
                    "lookup_key": "Real Fund",
                    "lookup_kind": "fund",
                    "member_count": "1",
                    "member_funds": "Real Fund",
                    "a_manager_name": "",
                    "a_source": "",
                    "b_manager_name": "",
                    "b_source": "",
                    "final_manager_name": "",
                    "final_source": "",
                }
            ],
        )
        nm.WORKSHEET_DIR.mkdir(parents=True, exist_ok=True)
        write(
            nm.WORKSHEET_DIR / "manager-01-a.csv",
            ["lookup_key", "lookup_kind", "member_count", "member_funds", "a_manager_name", "a_source"],
            [
                {
                    "lookup_key": "Real Fund",
                    "lookup_kind": "fund",
                    "member_count": "1",
                    "member_funds": "Real Fund",
                    "a_manager_name": "Acme Capital",
                    "a_source": "WEB_MANAGER: https://example.com | Acme runs Real Fund.",
                }
            ],
        )
        result = nm.merge_manager_slices()
        self.assertEqual(result, 0)
        self.assertEqual(read(nm.MANAGER_QUEUE)[0]["a_manager_name"], "Acme Capital")


class PropagateManagersTests(ManagerWorkflowTestCase):
    def test_a_settled_family_lookup_is_written_onto_every_member_fund(self) -> None:
        write(
            nm.MANAGER_QUEUE,
            nm.MANAGER_QUEUE_HEADER,
            [
                {
                    "lookup_key": "Lone Star",
                    "lookup_kind": "family",
                    "member_count": "2",
                    "member_funds": "Lone Star Fund VII, L.P. | Lone Star Fund VIII, L.P.",
                    "a_manager_name": "",
                    "a_source": "",
                    "b_manager_name": "",
                    "b_source": "",
                    "final_manager_name": "Lone Star Global Acquisitions, Ltd.",
                    "final_source": "WEB_MANAGER: https://example.com | Lone Star manages the series.",
                }
            ],
        )
        nm.propagate_managers()
        rows = {row["standardized_fund_name"]: row for row in read(nm.WEB_MANAGER_NAMES)}
        self.assertEqual(len(rows), 2)
        for fund in ("Lone Star Fund VII, L.P.", "Lone Star Fund VIII, L.P."):
            self.assertEqual(
                rows[fund]["final_manager_name"], "Lone Star Global Acquisitions, Ltd."
            )
            self.assertTrue(rows[fund]["final_source"].startswith("FAMILY Lone Star:"))

    def test_propagate_never_overwrites_an_existing_manager(self) -> None:
        write(
            nm.WEB_MANAGER_NAMES,
            nm.WEB_MANAGER_HEADER,
            [
                {
                    "standardized_fund_name": "Solo Fund, L.P.",
                    "a_manager_name": "",
                    "a_source": "",
                    "b_manager_name": "",
                    "b_source": "",
                    "final_manager_name": "Original Manager LLC",
                    "final_source": "WEB_MANAGER: https://example.com | hand adjudicated",
                }
            ],
        )
        write(
            nm.MANAGER_QUEUE,
            nm.MANAGER_QUEUE_HEADER,
            [
                {
                    "lookup_key": "Solo Fund, L.P.",
                    "lookup_kind": "fund",
                    "member_count": "1",
                    "member_funds": "Solo Fund, L.P.",
                    "a_manager_name": "",
                    "a_source": "",
                    "b_manager_name": "",
                    "b_source": "",
                    "final_manager_name": "Different Manager Corp",
                    "final_source": "WEB_MANAGER: https://example.com | should not win",
                }
            ],
        )
        nm.propagate_managers()
        rows = {row["standardized_fund_name"]: row for row in read(nm.WEB_MANAGER_NAMES)}
        self.assertEqual(rows["Solo Fund, L.P."]["final_manager_name"], "Original Manager LLC")


class PropagateNegativeResultTests(ManagerWorkflowTestCase):
    """A lookup that found nothing is a result, and has to reach the fund row.

    Without it, a fund searched by both lanes with nothing published looks
    just like a fund nobody has opened yet, and coverage cannot separate the
    backlog from the genuinely unfindable.
    """

    def queue_row(self, **overrides: str) -> dict[str, str]:
        row = {column: "" for column in nm.MANAGER_QUEUE_HEADER}
        row.update(overrides)
        return row

    def test_a_searched_lookup_with_no_firm_carries_its_evidence_to_each_member(self) -> None:
        write(
            nm.MANAGER_QUEUE,
            nm.MANAGER_QUEUE_HEADER,
            [
                self.queue_row(
                    lookup_key="Obscure Sponsor",
                    lookup_kind="family",
                    member_count="2",
                    member_funds="Obscure Fund I, L.P. | Obscure Fund II, L.P.",
                    a_source="WEB_MANAGER: no public manager match found",
                    b_source="WEB_MANAGER: no public manager match found",
                )
            ],
        )
        write(nm.WEB_MANAGER_NAMES, nm.WEB_MANAGER_HEADER, [])
        nm.propagate_managers()
        rows = {row["standardized_fund_name"]: row for row in read(nm.WEB_MANAGER_NAMES)}
        self.assertEqual(len(rows), 2)
        for fund in ("Obscure Fund I, L.P.", "Obscure Fund II, L.P."):
            self.assertEqual(rows[fund]["final_manager_name"], "", "no firm may be invented")
            self.assertIn("no public manager match found", rows[fund]["a_source"])
            self.assertTrue(
                rows[fund]["a_source"].startswith("FAMILY Obscure Sponsor:"),
                "an inherited negative says which lookup produced it",
            )

    def test_a_lookup_nobody_has_searched_propagates_nothing(self) -> None:
        write(
            nm.MANAGER_QUEUE,
            nm.MANAGER_QUEUE_HEADER,
            [
                self.queue_row(
                    lookup_key="Untouched Fund, L.P.",
                    lookup_kind="fund",
                    member_count="1",
                    member_funds="Untouched Fund, L.P.",
                )
            ],
        )
        write(nm.WEB_MANAGER_NAMES, nm.WEB_MANAGER_HEADER, [])
        nm.propagate_managers()
        self.assertEqual(read(nm.WEB_MANAGER_NAMES), [], "an unsearched lookup is not a result")

    def test_a_found_manager_still_wins_over_an_earlier_negative(self) -> None:
        write(
            nm.MANAGER_QUEUE,
            nm.MANAGER_QUEUE_HEADER,
            [
                self.queue_row(
                    lookup_key="Solo Fund, L.P.",
                    lookup_kind="fund",
                    member_count="1",
                    member_funds="Solo Fund, L.P.",
                    a_manager_name="Real Capital LLC",
                    a_source="WEB_MANAGER: https://example.com | names the GP",
                    final_manager_name="Real Capital LLC",
                    final_source="WEB_MANAGER: https://example.com | names the GP",
                )
            ],
        )
        write(
            nm.WEB_MANAGER_NAMES,
            nm.WEB_MANAGER_HEADER,
            [
                {
                    "standardized_fund_name": "Solo Fund, L.P.",
                    "a_manager_name": "",
                    "a_source": "WEB_MANAGER: no public manager match found",
                    "b_manager_name": "",
                    "b_source": "",
                    "final_manager_name": "",
                    "final_source": "",
                }
            ],
        )
        nm.propagate_managers()
        row = read(nm.WEB_MANAGER_NAMES)[0]
        self.assertEqual(row["final_manager_name"], "Real Capital LLC")


class ManagerCoverageScopeTests(ManagerWorkflowTestCase):
    """Coverage is a claim about the fund universe, so the file cannot set it."""

    def coverage(self) -> str:
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            nm.managers()
        return buffer.getvalue()

    def test_a_name_no_longer_in_the_universe_is_removed(self) -> None:
        self.write_fund_matrix([self.fund_row("Live Fund", "Live Fund, L.P.")])
        write(
            nm.WEB_MANAGER_NAMES,
            nm.WEB_MANAGER_HEADER,
            [
                {
                    "standardized_fund_name": "Live Fund, L.P.",
                    "a_manager_name": "", "a_source": "",
                    "b_manager_name": "", "b_source": "",
                    "final_manager_name": "", "final_source": "",
                },
                {
                    # Settled once, since merged away. Counting it would report
                    # 2 of 1 funds covered.
                    "standardized_fund_name": "Retired Fund, L.P.",
                    "a_manager_name": "", "a_source": "",
                    "b_manager_name": "", "b_source": "",
                    "final_manager_name": "Ghost Capital LLC",
                    "final_source": "WEB_MANAGER: https://example.com | stale",
                },
            ],
        )
        report = self.coverage()
        self.assertIn("with a general partner    : 0 (0.0%)", report)
        self.assertIn("obsolete rows removed     : 1", report)
        self.assertEqual(
            [row["standardized_fund_name"] for row in read(nm.WEB_MANAGER_NAMES)],
            ["Live Fund, L.P."],
        )

    def test_searched_and_unsearched_funds_are_reported_apart(self) -> None:
        self.write_fund_matrix(
            [
                self.fund_row("Tried Fund", "Tried Fund, L.P."),
                self.fund_row("Queued Fund", "Queued Fund, L.P."),
            ]
        )
        write(
            nm.WEB_MANAGER_NAMES,
            nm.WEB_MANAGER_HEADER,
            [
                {
                    "standardized_fund_name": "Tried Fund, L.P.",
                    "a_manager_name": "", "a_source": "WEB_MANAGER: no public manager match found",
                    "b_manager_name": "", "b_source": "WEB_MANAGER: no public manager match found",
                    "final_manager_name": "", "final_source": "",
                },
                {
                    "standardized_fund_name": "Queued Fund, L.P.",
                    "a_manager_name": "", "a_source": "",
                    "b_manager_name": "", "b_source": "",
                    "final_manager_name": "", "final_source": "",
                },
            ],
        )
        report = self.coverage()
        self.assertIn("searched, no firm found   : 1", report)
        self.assertIn("waiting for the web round : 1", report)


class ManagerRetryExportTests(ManagerWorkflowTestCase):
    """Re-opening a lookup is deliberate, and never destroys the first answer."""

    def _queue(self) -> None:
        write(
            nm.MANAGER_QUEUE,
            nm.MANAGER_QUEUE_HEADER,
            [
                {
                    "lookup_key": "Obscure Fund, L.P.",
                    "lookup_kind": "fund",
                    "member_count": "1",
                    "member_funds": "Obscure Fund, L.P.",
                    "a_manager_name": "",
                    "a_source": "WEB_MANAGER: no public manager match found",
                    "b_manager_name": "",
                    "b_source": "WEB_MANAGER: no public manager match found",
                    "final_manager_name": "",
                    "final_source": "",
                }
            ],
        )

    def test_a_plain_export_carries_the_previous_answer_into_the_slice(self) -> None:
        self._queue()
        nm.export_manager_slices(24)
        row = read(nm.WORKSHEET_DIR / "manager-01-a.csv")[0]
        self.assertEqual(row["a_source"], "WEB_MANAGER: no public manager match found")

    def test_retry_empties_the_answer_cells_but_leaves_the_queue_intact(self) -> None:
        self._queue()
        nm.export_manager_slices(24, retry=True)
        row = read(nm.WORKSHEET_DIR / "manager-01-a.csv")[0]
        self.assertEqual(row["a_source"], "", "a second pass must not read the first verdict")
        self.assertEqual(row["lookup_key"], "Obscure Fund, L.P.", "context still travels")
        queued = read(nm.MANAGER_QUEUE)[0]
        self.assertEqual(
            queued["a_source"], "WEB_MANAGER: no public manager match found", "the queue keeps the first answer"
        )


class DispatchPromptTests(ManagerWorkflowTestCase):
    """The prompts are generated, so a stale one is a bug the check must catch."""

    def setUp(self) -> None:
        super().setUp()
        self._dispatch_originals = {
            name: getattr(nm, name) for name in ("INSTRUCTIONS_DIR", "DISPATCH_DIR")
        }
        nm.INSTRUCTIONS_DIR = self.root / "instructions"
        nm.DISPATCH_DIR = nm.INSTRUCTIONS_DIR / "dispatch-prompts"
        nm.INSTRUCTIONS_DIR.mkdir(parents=True, exist_ok=True)
        for role in nm.DISPATCH_ROLES:
            brief = nm.INSTRUCTIONS_DIR / role["brief"]
            brief.write_text(f"# {role['title']}\n\nBody for {role['brief']}.\n", encoding="utf-8")
        nm.WORKSHEET_DIR.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._restore_dispatch)

    def _restore_dispatch(self) -> None:
        for name, value in self._dispatch_originals.items():
            setattr(nm, name, value)

    def write_manager_slice(self, name: str, header: list[str], rows: list[dict[str, str]]) -> None:
        write(nm.WORKSHEET_DIR / name, header, rows)

    def test_one_prompt_per_slice_naming_that_slice_and_its_size(self) -> None:
        header = ["lookup_key", "lookup_kind", "member_count", "member_funds",
                  "a_manager_name", "a_source"]
        self.write_manager_slice(
            "manager-01-a.csv",
            header,
            [
                {"lookup_key": "Alpha", "lookup_kind": "family", "member_count": "3",
                 "member_funds": "A | B | C", "a_manager_name": "", "a_source": ""},
                {"lookup_key": "Beta", "lookup_kind": "fund", "member_count": "1",
                 "member_funds": "Beta", "a_manager_name": "", "a_source": ""},
            ],
        )
        nm.dispatch()
        prompt = nm.DISPATCH_DIR / "web-manager" / "WEB-MANAGER-01-A.md"
        self.assertTrue(prompt.exists())
        text = prompt.read_text(encoding="utf-8")
        self.assertIn("manager-01-a.csv", text)
        self.assertIn("2 GP lookups, covering 4 funds", text)
        self.assertIn("Body for 02-WEB-MANAGER-A.md.", text, "the brief travels with the prompt")

    def test_finished_rows_are_reported_so_a_relaunch_resumes(self) -> None:
        header = ["lookup_key", "lookup_kind", "member_count", "member_funds",
                  "a_manager_name", "a_source"]
        self.write_manager_slice(
            "manager-01-a.csv",
            header,
            [
                {"lookup_key": "Alpha", "lookup_kind": "fund", "member_count": "1",
                 "member_funds": "Alpha", "a_manager_name": "Found LLC",
                 "a_source": "WEB_MANAGER: https://example.com | x"},
                {"lookup_key": "Beta", "lookup_kind": "fund", "member_count": "1",
                 "member_funds": "Beta", "a_manager_name": "", "a_source": ""},
            ],
        )
        nm.dispatch()
        text = (nm.DISPATCH_DIR / "web-manager" / "WEB-MANAGER-01-A.md").read_text(encoding="utf-8")
        self.assertIn("1 already finished in an earlier session", text)
        self.assertIn("never clear or rewrite a filled cell", text)

    def test_check_fails_on_a_prompt_that_no_longer_matches_its_brief(self) -> None:
        write(
            nm.WORKSHEET_DIR / "fund-part-01.csv",
            nm.MATRIX_HEADER["fund"],
            [self.fund_row("Raw", "Standard, L.P.", status="auto")],
        )
        self.assertEqual(nm.dispatch(), 0)
        self.assertEqual(nm.dispatch(check=True), 0)
        brief = nm.INSTRUCTIONS_DIR / "01-NAME-NORMALIZER.md"
        brief.write_text(brief.read_text(encoding="utf-8") + "\nA new binding rule.\n", encoding="utf-8")
        self.assertEqual(nm.dispatch(check=True), 1, "an edited brief makes every prompt stale")
        self.assertEqual(nm.dispatch(), 0)
        self.assertEqual(nm.dispatch(check=True), 0)

    def test_a_finished_slice_keeps_the_prompt_as_a_standing_brief(self) -> None:
        write(
            nm.WORKSHEET_DIR / "fund-part-01.csv",
            nm.MATRIX_HEADER["fund"],
            [self.fund_row("Raw", "Standard, L.P.", status="decided")],
        )
        nm.dispatch()
        prompt = nm.DISPATCH_DIR / "normalize" / "NORMALIZER-01.md"
        self.assertTrue(prompt.exists(), "a settled slice still has a standing brief")
        self.assertIn("Every row is finished", prompt.read_text(encoding="utf-8"))

    def test_an_autofilled_name_is_not_a_decision_and_still_needs_a_normalizer(self) -> None:
        write(
            nm.WORKSHEET_DIR / "fund-part-01.csv",
            nm.MATRIX_HEADER["fund"],
            [self.fund_row("Raw", "Standard, L.P.", status="auto")],
        )
        nm.dispatch()
        self.assertTrue(
            (nm.DISPATCH_DIR / "normalize" / "NORMALIZER-01.md").exists(),
            "`auto` is a machine proposal, so the row has not been read by anyone",
        )

    def test_a_searched_slice_that_found_nothing_counts_as_finished(self) -> None:
        header = ["lookup_key", "lookup_kind", "member_count", "member_funds",
                  "a_manager_name", "a_source"]
        self.write_manager_slice(
            "manager-01-a.csv",
            header,
            [
                {"lookup_key": "Obscure", "lookup_kind": "fund", "member_count": "1",
                 "member_funds": "Obscure", "a_manager_name": "",
                 "a_source": "WEB_MANAGER: no public manager match found"},
            ],
        )
        nm.dispatch()
        prompt = nm.DISPATCH_DIR / "web-manager" / "WEB-MANAGER-01-A.md"
        self.assertTrue(prompt.exists(), "a searched slice still has a standing brief")
        self.assertIn("Every row is finished", prompt.read_text(encoding="utf-8"))

    def test_a_prompt_whose_slice_is_gone_is_removed(self) -> None:
        write(
            nm.WORKSHEET_DIR / "fund-part-01.csv",
            nm.MATRIX_HEADER["fund"],
            [self.fund_row("Raw", "Standard, L.P.", status="auto")],
        )
        write(
            nm.WORKSHEET_DIR / "fund-part-02.csv",
            nm.MATRIX_HEADER["fund"],
            [self.fund_row("Other", "Other, L.P.", status="auto")],
        )
        nm.dispatch()
        self.assertTrue((nm.DISPATCH_DIR / "normalize" / "NORMALIZER-02.md").exists())
        (nm.WORKSHEET_DIR / "fund-part-02.csv").unlink()
        nm.dispatch()
        self.assertFalse(
            (nm.DISPATCH_DIR / "normalize" / "NORMALIZER-02.md").exists(),
            "a prompt naming a slice that no longer exists is worse than no prompt",
        )
        self.assertEqual(nm.dispatch(check=True), 0)


if __name__ == "__main__":
    unittest.main()
