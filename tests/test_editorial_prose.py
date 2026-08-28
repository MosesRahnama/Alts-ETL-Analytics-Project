"""Editorial rules for every Markdown file a reviewer reads.

The repository follows the house editorial rulebook: declarative section heads,
affirmative phrasing, plain vocabulary, and no em dashes. Most Markdown here is
generated (folder guides, extraction prompts, the field guide), so a banned word
reaches the tree through a generator string rather than through an edited file.
Scanning the rendered Markdown catches both, and it fails at the point where a
new phrase is introduced instead of at the next manual read-through.

Fenced blocks and inline code spans are excluded: they carry column names,
enum values, and shell commands, which are data rather than prose.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}

FENCED = re.compile(r"```.*?```", re.S)
INLINE = re.compile(r"`[^`\n]*`")

# A controlled vocabulary printed as a bare comma list keeps its own spelling.
VOCABULARY_LINE = re.compile(r"may only be:|metric_category|term_category")

BANS = (
    # A question-framed head rarely carries a question mark. "What this section
    # is" and "How to use this repo" are the named patterns in the rulebook, so
    # the opening word is what has to be caught, not the punctuation.
    ("question-framed section head", re.compile(r"^#{1,6} .*\?\s*$", re.M)),
    (
        "interrogative section head",
        re.compile(
            r"^#{1,6}\s+(What|How|Why|When|Where|Who|Which|Whether|Is|Are|Was|Were"
            r"|Does|Do|Did|Can|Could|Should|Would|Will|Has|Have)\b",
            re.M | re.I,
        ),
    ),
    ("em dash", re.compile(r"—")),
    (
        "certainty vocabulary",
        re.compile(
            r"\b(exact|exactly|precise|precisely|sharp|sharpen|sharply|honest|honestly"
            r"|explicit|explicitly)\b",
            re.I,
        ),
    ),
    ("plain-English label", re.compile(r"(?i)plain[- ](english|language)")),
    ("provenance", re.compile(r"(?i)\bprovenance\b")),
    ("load-bearing", re.compile(r"(?i)\bload-bearing\b")),
    ("coarse", re.compile(r"(?i)\bcoarse\b")),
    (
        "negation template",
        re.compile(
            r"(?i)\bnot (only|just|merely)\b"
            r"|\bnot\s+[a-z-]+,\s+but\b"
            r"|\bit'?s not\b"
            r"|\bno\s+\w+\s+(needed|required)\b"
            r"|\bnot\s+(uncommon|insignificant|trivial)\b"
        ),
    ),
    (
        "hype vocabulary",
        re.compile(
            r"(?i)\b(comprehensive|robust|crucial|crucially|pivotal|delve\w*"
            r"|showcase\w*|holistic|streamline\w*|foster\w*|empower\w*|seamless|intricate"
            r"|nuanced|multifaceted|groundbreaking|cutting-edge|meticulous|noteworthy|realm"
            r"|tapestry|synergy|paramount|invaluable|unparalleled|utilize\w*"
            r"|testament to|vibrant|burgeoning)\b"
        ),
    ),
    # The rulebook bans these as stock verbs. `leverage` is also a real financial
    # ratio and a DDQ metric category, and `underscore` is also the `_` character
    # in an identifier format, so only the verb forms are caught here.
    (
        "stock verb",
        re.compile(
            r"\b(leverag(es|ing)|underscor(es|ing|ed))\b"
            r"|\b(leverage|underscore)\s+(the|a|an|our|its|their|this|that|how|why)\b",
            re.I,
        ),
    ),
    (
        "formulaic closer",
        re.compile(r"(?i)\b(in summary|to summarize|taken together|in conclusion)\b"),
    ),
    (
        "stock transition opener",
        re.compile(
            r"(?m)^\s*(Furthermore|Moreover|Additionally|Consequently|Nevertheless"
            r"|Notably|Crucially|That being said)\b"
        ),
    ),
    ("internal time word", re.compile(r"(?i)(?<![a-z-])now(?![a-z])")),
    ("throat-clearing", re.compile(r"(?i)it is important to note|it'?s worth noting|when it comes to|here'?s why")),
)

# Carve-outs, each with the reason it survives the ban. Empty while the stock-verb
# rule above handles the two words that double as terms of art.
ALLOWED: dict[tuple[str, str], str] = {}


# notes.md holds the operator's brief and verbatim review reports written by
# other agents. Editing those to the house rules would rewrite what the operator
# actually said, so they are read as inputs and not as repository prose.
# Audit records and the operator's own briefs are read as inputs, in the words
# their authors chose; the house rules govern the repository's own prose.
NOT_REPOSITORY_PROSE = {
    "notes.md",
    "diagnostics.md",
    "diagnostics_1.md",
    "audit/metric-vocabulary/AGENT-BRIEF-SIMPLIFY.md",
    "audit/language-rewrite.md",
    "audit/dashboard-explanation/language-rewrite.md",
    "audit/dashboard-explanation/README.md",
}


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in PROJECT_ROOT.rglob("*.md")
        if not (set(path.relative_to(PROJECT_ROOT).parts) & SKIP_DIRS)
        and path.relative_to(PROJECT_ROOT).as_posix() not in NOT_REPOSITORY_PROSE
        and not path.relative_to(PROJECT_ROOT).as_posix().startswith("audit/diagnostics/")
    )


def prose_of(path: Path) -> str:
    """The file with code spans blanked, keeping line numbers intact."""

    text = path.read_text(encoding="utf-8")
    text = FENCED.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return INLINE.sub("", text)


class EditorialProseTests(unittest.TestCase):
    def test_markdown_files_exist(self) -> None:
        self.assertGreater(len(markdown_files()), 100)

    def test_no_banned_prose_in_markdown(self) -> None:
        findings: list[str] = []
        for path in markdown_files():
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            prose = prose_of(path)
            lines = prose.splitlines()
            for label, pattern in BANS:
                allowed = ALLOWED.get((rel, label))
                for match in pattern.finditer(prose):
                    line_no = prose[: match.start()].count("\n")
                    line = lines[line_no] if line_no < len(lines) else ""
                    if allowed and match.group(0).lower().startswith(allowed):
                        continue
                    if label == "hype vocabulary" and VOCABULARY_LINE.search(line):
                        continue
                    findings.append(f"{rel}:{line_no + 1} [{label}] {match.group(0)!r} in {line.strip()[:90]!r}")
        self.assertEqual(findings, [], "\n" + "\n".join(findings[:40]))


if __name__ == "__main__":
    unittest.main()
