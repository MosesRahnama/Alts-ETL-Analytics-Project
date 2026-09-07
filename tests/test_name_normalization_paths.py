"""Every identity command declares where it writes, and the runbook agrees.

An operator reading a runbook should never have to open the source to learn
where a command puts its output. That only holds while three things stay in
step: the commands the parser accepts, the `WRITES` registry, and the table in
the runbook. This test fails the moment any one of them moves.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.catalog.simple_pdf_extraction import name_normalization as nm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = PROJECT_ROOT / "instructions" / "02-fund-mapping" / "00-OPERATOR-RUNBOOK.md"
SOURCE = Path(nm.__file__)


def parser_commands() -> set[str]:
    """The verbs `main` registers, read from the source so importing is enough."""
    text = SOURCE.read_text(encoding="utf-8")
    return set(re.findall(r'sub\.add_parser\(\s*"([a-z-]+)"', text))


class WritesRegistryTests(unittest.TestCase):
    def test_every_command_declares_where_it_writes(self) -> None:
        commands = parser_commands()
        self.assertTrue(commands, "no subcommands found in the parser")
        self.assertEqual(
            commands - set(nm.WRITES),
            set(),
            "a command exists with no WRITES entry, so its output path is undocumented",
        )
        self.assertEqual(
            set(nm.WRITES) - commands,
            set(),
            "WRITES names a command the parser no longer accepts",
        )

    def test_declared_targets_are_repository_relative(self) -> None:
        for command, targets in nm.WRITES.items():
            for target in targets:
                self.assertFalse(
                    target.startswith("/") or ":" in target,
                    f"{command} declares an absolute path: {target}",
                )
                self.assertTrue(
                    target.startswith(("data/", "instructions/")),
                    f"{command} writes outside data/ and instructions/: {target}",
                )

    def test_the_matrices_land_in_the_normalization_folder(self) -> None:
        """The question this whole registry exists to answer."""
        for command in ("harvest", "merge", "propagate", "manager-queue"):
            for target in nm.WRITES[command]:
                self.assertTrue(
                    target.startswith("data/normalization/"),
                    f"{command} no longer writes into data/normalization/",
                )


class RunbookAgreementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runbook = RUNBOOK.read_text(encoding="utf-8")

    def test_the_runbook_lists_every_command(self) -> None:
        for command in nm.WRITES:
            self.assertIn(
                f"`{command}`",
                self.runbook,
                f"the runbook table omits {command}",
            )

    def test_the_runbook_names_each_declared_target(self) -> None:
        for command, targets in nm.WRITES.items():
            for target in targets:
                # `harvest` writes five matrices and the table names the first
                # and describes the rest, so one named target per command is the
                # contract; the registry and `paths` carry the full list.
                if command == "harvest" and target != nm.WRITES["harvest"][0]:
                    continue
                self.assertIn(
                    target,
                    self.runbook,
                    f"the runbook does not name where {command} writes: {target}",
                )

    def test_the_runbook_sends_the_reader_to_the_paths_command(self) -> None:
        self.assertIn("name_normalization paths", self.runbook)


class LiveDispatchTests(unittest.TestCase):
    def test_every_identity_worksheet_has_a_matching_prompt(self) -> None:
        self.assertEqual(nm.dispatch(check=True), 0)
        worksheets = (
            list(nm.WORKSHEET_DIR.glob("fund-part-*.csv"))
            + list(nm.WORKSHEET_DIR.glob("manager-*-a.csv"))
            + list(nm.WORKSHEET_DIR.glob("manager-*-b.csv"))
            + list(nm.WORKSHEET_DIR.glob("manager-*-j.csv"))
        )
        prompts: list[Path] = []
        for folder in ("normalize", "web-manager", "adjudicate"):
            root = nm.DISPATCH_DIR / folder
            if root.exists():
                prompts.extend(path for path in root.glob("*.md") if path.name != "README.md")
        self.assertEqual(len(worksheets), len(prompts))


if __name__ == "__main__":
    unittest.main()
