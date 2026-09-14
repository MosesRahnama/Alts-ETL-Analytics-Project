"""Build the reviewer field guide from the current dashboard data."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.dashboard import build_dashboard
from src.dashboard.page import STYLE


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).with_name("field_guide_template.html")
# The guide is local-only under repository policy, so it is written inside the
# ignored audit tree and never at the repository root.
OUTPUT = PROJECT_ROOT / "audit" / "project-outline" / "claude-alts-dashboard-field-guide.html"
PAYLOAD_MARKER = "__DASHBOARD_PAYLOAD__"
STYLE_MARKER = "__DASHBOARD_STYLE__"

SOURCE_LEDGER = PROJECT_ROOT / "data-gathering" / "source_ledger.csv"

# Who originates each kind of document, how often it appears, and what it is,
# in ordinary words. The repository records the counts, the pages and the
# publisher of each copy; it records none of these three, so they are authored
# here and checked against the ledger's own type list at build time.
DOCUMENT_TYPE_FACTS = {
    "Financials": (
        "GP", "Once a year, audited",
        "The fund's audited accounts: what it owns, what it owes, what it earned and "
        "spent, and the partners' capital. An independent auditor signs them.",
    ),
    "Institutional_Report": (
        "LP", "Once a year, with board packets in between",
        "An asset owner's own report on its whole investment programme: what it holds by "
        "asset class, what it has committed, its policy targets, and its manager list.",
    ),
    "Performance": (
        "LP", "Every quarter",
        "Return tables: the percentage each fund, asset class, or the whole portfolio "
        "made over named periods, usually beside the benchmark it is measured against.",
    ),
    "Quarterly_Report": (
        "GP", "Every quarter",
        "The GP's periodic report to its investors: fund value, what was called and "
        "distributed in the quarter, performance to date, and portfolio commentary.",
    ),
    "Fee_Report": (
        "LP", "Once a year",
        "What the investor actually paid: management fees, carried interest, offsets "
        "against them, and fund expenses, often compared with a peer level.",
    ),
    "Schedule_Inv": (
        "GP", "Every quarter",
        "A line for every holding the fund owns, with what it cost and what it is now "
        "worth. Regulatory holdings filings take the same shape.",
    ),
    "PPM": (
        "GP", "Once, when the fund raises money",
        "The offering document: the strategy the fund will follow, the terms it is sold "
        "on, the fees and carried interest it will charge, and its risks.",
    ),
    "NAV_Statement": (
        "GP", "Monthly or quarterly",
        "The net asset value of a fund or share class at a date, the units outstanding, "
        "and the value per unit.",
    ),
    "Valuation": (
        "GP", "Every quarter, under a policy set once a year",
        "How a holding's value was arrived at: the method used, the inputs, and which "
        "level of the fair-value hierarchy it falls in.",
    ),
    "Stewardship_Proxy_Report": (
        "LP", "Once a year",
        "How the owner voted its shares and engaged with the companies it holds, with "
        "counts of meetings, votes, and engagements.",
    ),
    "Subscription": (
        "GP", "Once, when the investor commits",
        "The agreement by which an investor commits money to the fund: the amount, the "
        "share class, and the terms accepted.",
    ),
    "Cash_Flow_Notice": (
        "GP", "Whenever money moves, on short notice",
        "A demand for money or a payment of it: the amount, the date it is due or paid, "
        "what it is for, and how much of it may be called again.",
    ),
    "Foundations_Annual": (
        "LP", "Once a year",
        "A foundation's annual return to the tax authority, which lists its investments "
        "at fair value and its unfunded commitments.",
    ),
    "LPA": (
        "GP", "Once, at closing, amended only by consent",
        "The partnership agreement itself: the fee, the carried interest, the hurdle the "
        "GP must clear, the order profits are split in, and how long the fund lasts.",
    ),
    "PCAP": (
        "GP", "Every quarter",
        "One investor's account in the fund: opening balance, money in, money out, gains "
        "and losses, and closing balance.",
    ),
    "DDQ": (
        "GP", "At diligence, refreshed yearly",
        "The manager's answers to a standard question set before an investor commits: "
        "assets managed, strategy, operations, controls, and terms.",
    ),
    "Side_Letter": (
        "GP", "Once, at closing, for one investor",
        "Terms one investor negotiates for itself alongside the partnership agreement, "
        "such as a different fee, extra reporting, or earlier liquidity.",
    ),
    "Secondary_Pricing": (
        "LP", "Once or twice a year",
        "A bank or adviser's report on the secondaries market: volume, pricing versus NAV, "
        "who is buying and selling, and how continuation vehicles are being used.",
    ),
    "Continuation_Fund": (
        "GP", "When a continuation vehicle is proposed, plus standing industry guidance",
        "Papers for a continuation fund: whether an investor rolls or sells, the price to NAV, "
        "conflicts, fees, and carried interest.",
    ),
}

# Kinds of document that exist in this market and are absent from the corpus.
# Each says why, because for most of them the reason is that they are never
# published rather than that they were overlooked.
ABSENT_DOCUMENT_TYPES = [
    ("Tax reporting to investors",
     "A Schedule K-1 is issued to every investor once a year and is the document their "
     "own tax return is built from. It names the taxpayer, so no copy is public. The "
     "same holds for the related foreign-holding and withholding statements."),
    ("Portfolio company operating reports",
     "Revenue, earnings, debt and headcount for each company a fund owns, reported "
     "quarterly to investors on an industry template. Commercially sensitive, and "
     "published by nobody."),
    ("Manager regulatory filings",
     "A US manager files a registration form describing its business, and a confidential "
     "return of fund-level risk data. The registration form is public and could be "
     "acquired; the risk return is seen only by the regulator."),
    ("Service-provider control reports",
     "An independent audit of the administrator that strikes the fund's books. Issued "
     "once a year to the manager and its investors under a restricted-use notice."),
    ("Governance papers between the GP and its investors",
     "Advisory-committee packs and minutes, consents, amendments, and requests to extend "
     "a fund's life. All are sent to investors and none are published."),
    ("Fund borrowing reports",
     "Reporting on the credit line a fund draws against before it calls money. The "
     "extraction contract already carries a record kind for it, and almost nothing in "
     "the corpus fills it."),
]

# The dashboard reports what extraction produced. This guide-only section
# reports what extraction refuses, because the checks are the part a reviewer
# asks about and no published table shows them. Every number and command below
# is read from the runbook, the dispatch prompts, the workflow code, and
# data/normalization/transformations/grid-thresholds.csv.
EXTRACTION_GATES_SECTION = {
    "id": "extraction-gates",
    "title": "Extraction gates",
    "blurb": (
        "What happens while a document is being read, and every check that can "
        "stop it. Read this beside the release audit on the overview page."
    ),
    "blocks": [
        {
            "kind": "guide",
            "tone": "teach",
            "title": "What extraction is, and what a gate is",
            "lead": (
                "Extraction is the step where a number printed on a PDF page becomes a row "
                "in a table. Two readers do it separately on the same document, and a third "
                "settles what they disagree about."
            ),
            "paragraphs": [
                "A gate here is a command that refuses. It either prints PASS or it prints "
                "the file, the line, and what is wrong, and the work does not move on until "
                "the reader fixes it. Nothing on this page is advice and nothing waits for "
                "anyone's approval: a reader runs the command, acts on what it says, and runs "
                "it again.",
                "That matters because the two readers must be independent for the third to "
                "have anything to compare. Most of the checks below exist to catch one reader "
                "quietly recording less than the other, which is the failure that produces "
                "rows nobody can adjudicate: only one side ever saw the cell.",
                "Six commands carry the whole extraction. They are named in the operator "
                "runbook at instructions/01-pdf-extraction-csv/00-OPERATOR-RUNBOOK.md and run "
                "in the order below.",
            ],
        },
        {
            "kind": "steps",
            "items": [
                {
                    "stage": "Before a page is read",
                    "title": "Build the page pictures, the page text, and the page grid",
                    "text": (
                        "Extraction refuses to start on a document missing any of the three. "
                        "The grid is rebuilt whenever the corpus changes, at about 1.5 seconds "
                        "per document."
                    ),
                },
                {
                    "stage": "Before a page is read",
                    "title": "Declare the model doing the reading",
                    "text": (
                        "One command, once per run. The first validation of the first document "
                        "fails while it has not been run, so a document is never written by "
                        "something nothing can name afterwards."
                    ),
                },
                {
                    "stage": "Before a page is read",
                    "title": "lane-check, to read the assignment",
                    "text": (
                        "It prints every document on the worklist and its state. The reader "
                        "takes the assignment from this, never from the message that dispatched "
                        "it: an operator's message can name fewer documents than the worklist "
                        "holds, and the worklist wins."
                    ),
                },
                {
                    "stage": "While reading",
                    "title": "Append rows to the two files after every table, section, and page",
                    "text": (
                        "Never in one batch at the end. Rows already on disk are finished work "
                        "and the only permitted write is an append, so an interrupted session "
                        "resumes at the first page with no coverage row."
                    ),
                },
                {
                    "stage": "While reading",
                    "title": "validate-candidate --through-page 3, after the first three pages",
                    "text": (
                        "Before a fourth page is opened. A row-shape mistake repeats on every "
                        "row written, so catching it here costs a minute and catching it at the "
                        "end costs the document."
                    ),
                },
                {
                    "stage": "When the document is finished",
                    "title": "validate-candidate, on the whole document",
                    "text": (
                        "Proves the file is well formed: every row, every controlled value, "
                        "every quote against the page it cites."
                    ),
                },
                {
                    "stage": "When the document is finished",
                    "title": "audit-file, before the next document is opened",
                    "text": (
                        "Proves the file is finished, which validation cannot: a page declared "
                        "empty and a page that is empty look identical in the file. This is the "
                        "check that compares what was written against what the page prints."
                    ),
                },
                {
                    "stage": "When both readings exist",
                    "title": "compare, then the third reader's decisions, then build-final",
                    "text": (
                        "The two readings are paired cell by cell. The third reader decides "
                        "every pair that does not match, and the agreed document is constructed "
                        "from those decisions rather than typed."
                    ),
                },
                {
                    "stage": "When both readings exist",
                    "title": "validate-final",
                    "text": (
                        "The constructed document is checked again, under stricter rules than a "
                        "reading is: what passes as a warning during reading is a refusal here."
                    ),
                },
                {
                    "stage": "When the lane is finished",
                    "title": "lane-check, as the last action",
                    "text": (
                        "It re-derives every assigned document's state from the files on disk "
                        "and fails while any is unstarted or unfinished. The run is over when "
                        "this prints PASS and at no earlier point."
                    ),
                },
            ],
        },
        {
            "kind": "guide",
            "tone": "teach",
            "title": "Three things must exist before anyone reads a page",
            "lead": (
                "A reader is never given only the PDF. The document is prepared into three "
                "views first, and extraction refuses to run while any of them is missing."
            ),
            "items": [
                [
                    "A photograph of every page",
                    "One PNG image per physical page at 300 dots per inch. The check names "
                    "every absent page image and the command that renders them. The picture is "
                    "the authority on layout: where the grid and the picture disagree, the "
                    "picture wins.",
                ],
                [
                    "The text of every page",
                    "The document's own text, kept aligned to physical pages. Every recorded "
                    "value must quote a line that appears on the page it cites, and this is "
                    "the file that proves it. Where a page has no text layer, the row must say "
                    "IMAGE_ONLY, name the page image, and explain the defect.",
                ],
                [
                    "The page grid",
                    "A map of the numbers printed in tables, taken from the PDF's own "
                    "coordinates. Without it, the completeness audit fails outright and says "
                    "so: no page grid, build the source grids first.",
                ],
            ],
        },
        {
            "kind": "guide",
            "tone": "warn",
            "title": "The page grid, and what it is not",
            "lead": (
                "The grid lists every numeric cell it can resolve on a page with its row label, "
                "its column number, and its column header. It is how a reader knows which "
                "column a number belongs to without counting columns by eye, which is the "
                "single largest source of wrong values in this work."
            ),
            "paragraphs": [
                "It is a word map, not an extraction and not a count of every number printed. "
                "It reports what is printed and where. The reader still decides what kind of "
                "record it is, what it measures, and whether it is allowed at all.",
                "It is deliberately incomplete, and that is not a fault. A page with no "
                "detected table produces nothing. A narrative page produces nothing. A scanned "
                "page produces nothing, because there is no text layer to measure, and such a "
                "document must be read from its pictures.",
                "Column headers are best effort, because some PDFs draw their header text "
                "twice. The column number and its position are always reliable, so where a "
                "header arrives garbled the reader names that column once from the picture and "
                "applies it down the column.",
            ],
        },
        {
            "kind": "guide",
            "tone": "teach",
            "title": "The three-page check",
            "lead": (
                "After the first three pages, and before a fourth page is opened, the reader "
                "runs the validator with --through-page 3."
            ),
            "paragraphs": [
                "It checks everything written so far and does not ask for pages nobody has "
                "reached yet. On a one-page or two-page document it simply checks the whole "
                "thing. Without it the command would demand coverage for the entire document, "
                "which the opening pages can never satisfy.",
                "It runs after page three rather than page one because page one is a cover, a "
                "letter, or a contents page on eleven of the twenty-nine documents published "
                "at the time the rule was set. A coverage row for a cover says nothing about "
                "the shape of a row carrying a value. Through page three the check reaches "
                "printed values on twenty-five of those documents, where page one alone reaches "
                "eighteen.",
                "This is a rule the reader follows, not a receipt the pipeline stores: nothing "
                "records that it ran. Its value is timing, not proof. The backstop that cannot "
                "be skipped is the completeness audit at the end of the document, which no "
                "later step will pass without.",
            ],
        },
        {
            "kind": "guide",
            "tone": "warn",
            "title": "The four numbers that decide whether a page was skimmed",
            "lead": (
                "The completeness audit compares the rows a reader wrote on a page against the "
                "cells the grid resolved on it. Four thresholds decide when it objects. They "
                "are configuration, not code: they live in "
                "data/normalization/transformations/grid-thresholds.csv."
            ),
            "items": [
                [
                    "12 cells",
                    "At or above twelve resolved cells, the page carries a table. This is the "
                    "trigger for both questions below.",
                ],
                [
                    "4 rows",
                    "A table must also span at least four rows before a page declared empty is "
                    "challenged, so a stray line of figures is not treated as a schedule.",
                ],
                [
                    "60 cells",
                    "Above sixty resolved cells across four or more rows, no honest narrative "
                    "page has ever landed. Declaring such a page empty without a stated reason "
                    "is a hard failure and the message says so: that is a printed table, so the "
                    "page is not empty.",
                ],
                [
                    "A quarter",
                    "On a page of twelve or more cells, writing fewer rows than a quarter of "
                    "them is a thin page. The reader must start the note with PARTIAL_BY_SCOPE: "
                    "and name the rows or columns left out and the test they fail. A cash-flow "
                    "statement with only its opening and closing cash lines in scope is a "
                    "legitimate thin page, and the note is what says so.",
                ],
            ],
        },
        {
            "kind": "guide",
            "tone": "warn",
            "title": "A reason must be about category, never about difficulty",
            "lead": (
                "A page holding nothing this document type collects is a normal outcome. A page "
                "that was hard to read is not the same thing, and the checks refuse to let the "
                "two collapse into each other."
            ),
            "paragraphs": [
                "The audit scans the note for phrases that describe reading difficulty and "
                "rejects them by name: column assignment not reliable, the grid dropped "
                "columns, values not recoverable, labels merged in the text. Every one of those "
                "describes the tool, not the page. The data is printed, and the escalation is "
                "required rather than optional: open the page picture and read it there.",
                "A valid reason names the category test the page fails, in at least six words. "
                "Office contact details, outside the allowed financial categories, is a reason. "
                "The most valuable pages in this corpus are usually the hardest, and skipping a "
                "wide partnership schedule because it is wide loses more than every other "
                "defect in this work combined.",
                "Printed footnotes, glossaries, and accounting or performance-method notes are "
                "records in their own right. A page carrying them cannot be filed as reference "
                "material with nothing extracted, and the audit raises that separately.",
            ],
        },
        {
            "kind": "guide",
            "tone": "teach",
            "title": "What the row check refuses",
            "lead": (
                "Every row is checked on its own, against the document it claims to come from. "
                "These are the refusals a reader meets most often."
            ),
            "items": [
                [
                    "A row of the wrong width",
                    "Every row carries all 47 columns, header and data alike, with an empty "
                    "column written as an empty pair of quotes in its own position. Omitting "
                    "one shifts every later value one column left, so the row silently reports "
                    "the wrong field.",
                ],
                [
                    "A quote that does not contain its own value",
                    "The quote must be the printed line the value sits on, so it proves that "
                    "number and not merely that the page exists. It must also actually appear "
                    "on the page it cites, and it is capped at 500 characters.",
                ],
                [
                    "A value that dropped its printed symbol",
                    "A printed per-cent sign or multiple sign stays in the value and is also "
                    "recorded in the unit column. Stripping it makes the same measure read two "
                    "ways across one document. This is checked while reading rather than at "
                    "adjudication because 549 of one document's 551 value disagreements were "
                    "this alone.",
                ],
                [
                    "Two rows at one printed cell",
                    "A page, a row label, a column label, and an occurrence number identify one "
                    "physical cell. Two rows there are the same observation, and if the page "
                    "really prints that label twice, the second one takes the next occurrence "
                    "number.",
                ],
                [
                    "A word where a measurement belongs",
                    "A measured value carries digits. Without this check a lost number leaves a "
                    "bare unit behind, and prose lands in the value column: both validate clean "
                    "and both read as real data.",
                ],
                [
                    "An empty cell recorded as data",
                    "A dash, a blank, a nil marker, or not applicable produces no record at all. "
                    "There is no value there to record.",
                ],
                [
                    "A footnote key pointing at nothing",
                    "A marker cited on a value row must have its definition recorded in the same "
                    "document, and it must resolve to one meaning. A marker reused with two "
                    "meanings is refused until the row cites the one governing its own table.",
                ],
                [
                    "A claim the page does not make",
                    "Categories whose meaning depends on the report's own words, such as a "
                    "return or a fund value, must state their method, fee treatment, or scope, "
                    "and must back it with a cited footnote or the printed phrase itself. Where "
                    "the page says nothing, the row says unstated. Guessing is refused; saying "
                    "nothing is not.",
                ],
                [
                    "A currency in the unit column",
                    "Dollars are the money, not the thing measured. Per cent, multiple, basis "
                    "points, years, and shares are units; a currency and a scale belong in the "
                    "currency column.",
                ],
                [
                    "A document identity row in the wrong place",
                    "One row per document describes the document itself, and it sits on page 1 "
                    "whatever page supplied the identity. Two readers who file it on different "
                    "pages produce a row that cannot be paired, and six documents of one round "
                    "split exactly that way.",
                ],
                [
                    "A value taken from anywhere but the page",
                    "Not from the file's header block, not from the filename, not from the "
                    "worklist, and not from knowing the institution. If the page prints the "
                    "fund's own shorter name, that is the value.",
                ],
            ],
        },
        {
            "kind": "guide",
            "tone": "teach",
            "title": "What the page accounting refuses",
            "lead": (
                "Alongside the values, every reader writes one row per physical page saying "
                "what that page held and how many records were taken from it. This is the "
                "machine-checkable omission check."
            ),
            "items": [
                [
                    "A missing or repeated page",
                    "One row per page, in page order, no page absent and none twice. A document "
                    "with a page unaccounted for is unfinished.",
                ],
                [
                    "Counts that do not reconcile",
                    "The number of records the page row claims must equal the records actually "
                    "citing that page, and must equal the count the reader made from the page "
                    "picture before writing anything.",
                ],
                [
                    "A populated page filed as empty",
                    "A page with records must carry the extracted status and must record that "
                    "its layout was checked.",
                ],
                [
                    "An empty page claiming extraction",
                    "The extracted status requires at least one observation. The document "
                    "identity row does not count, so a page cannot describe its data in the "
                    "note, extract none of it, and still pass.",
                ],
                [
                    "A skipped page and a deferred page",
                    "Unreadable and deferred are unfinished work, not outcomes. On the finished "
                    "corpus they block the document until source review settles what the page "
                    "holds.",
                ],
            ],
        },
        {
            "kind": "guide",
            "tone": "warn",
            "title": "The checks on meaning, not on shape",
            "lead": (
                "A row can be perfectly formed and still say something the page contradicts. A "
                "separate set of checks reads the row against the headings and footnotes around "
                "it."
            ),
            "items": [
                [
                    "A header that states the answer",
                    "Where the printed header or row label states net of fees, or names the "
                    "return method, the row must agree with it or cite the footnote that refines "
                    "it.",
                ],
                [
                    "A basis that is really a name",
                    "The measurement basis column takes what the page says a number is measured "
                    "on. An entity name, a table title, or a column heading placed there is "
                    "refused: those belong in the label columns.",
                ],
                [
                    "A comparative column with the wrong date",
                    "Where a column is headed by a year, the date on the row has to be that "
                    "year's. Under one heading covering two years, each column keeps its own "
                    "date.",
                ],
                [
                    "An accounting label read as an institution",
                    "Total net assets on a statement is a line of that statement, not the name "
                    "of an organisation, and a named fund partnership stays a fund.",
                ],
                [
                    "A part of a fund reported as the whole fund",
                    "Where a column is the fund and the rows are its strategy components, each "
                    "row must say it is a component. Only the fund's own total row may claim to "
                    "be the fund total.",
                ],
                [
                    "An investor's account credited to the fund",
                    "A capital-account statement naming both the investor and the fund it "
                    "invested in records the investor's account as the subject.",
                ],
            ],
        },
        {
            "kind": "guide",
            "tone": "warn",
            "title": "The gates that keep the two readings independent",
            "lead": (
                "Two readings are only worth having if they were made twice. Four rules protect "
                "that, and each of them exists because it failed once."
            ),
            "items": [
                [
                    "No program may write the rows",
                    "The validator refuses to run while any script capable of writing candidate "
                    "rows exists anywhere in the repository, and it names the file. A generated "
                    "reading is the first reading retyped by a program, so the third reader ends "
                    "up comparing a document with itself. One 149-page document was filed this "
                    "way: a single loop stamped one identical judgement across 104 pages, and "
                    "both the validator and the audit passed it, because a file written by a "
                    "loop and a file read off the pages are the same file.",
                ],
                [
                    "Neither reader may open the other's work",
                    "A reader opens this brief, its own worklist, and the document. Never the "
                    "other reading, the comparison, the decisions, or the agreed file.",
                ],
                [
                    "The run declares which model read the document",
                    "Once per run, before the first document. The rows are stamped with it "
                    "mechanically at publication, never typed into a row.",
                ],
                [
                    "The lane, not the reader, decides the run is over",
                    "A per-document command can only judge a document somebody chose to name, so "
                    "a document nobody opened produces no failing check anywhere. One round lost "
                    "three documents that way, one of them never opened at all, while all three "
                    "readers reported themselves finished.",
                ],
            ],
        },
        {
            "kind": "guide",
            "tone": "teach",
            "title": "What the third reader is given",
            "lead": (
                "The comparison pairs the two readings by physical cell: the document, the page, "
                "the row label, the column label, and which time that label appears on the page."
            ),
            "paragraphs": [
                "Each pair comes out as agreed, as a disagreement about the value, about the "
                "classification, or about the surrounding context, or as a cell only one reader "
                "recorded. Every pair that is not an exact agreement goes to the third reader, "
                "who opens the picture of the cited page and decides it.",
                "Agreement is not taken on trust. A fixed one-in-ten sample of the agreeing "
                "pairs is checked against the page as well, and at least one pair from every "
                "page is always checked, because two readers can copy the same mistake.",
                "The page accounting is compared too, on the page status, the layout check, the "
                "expected count, the structures named, and the record kinds. The first and last "
                "page of every document are always reviewed, and other agreeing pages by the "
                "same fixed sample.",
                "The agreed document is then constructed from those decisions rather than "
                "typed, and it is refused if the comparison it was built on is out of date. It "
                "is checked again before it is written, under the stricter rules: an unreadable "
                "character must be resolved against the page picture, and a category whose "
                "meaning depends on the report's wording must carry a reviewed answer even on "
                "rows extracted under an older version of the contract.",
            ],
        },
        {
            "kind": "guide",
            "tone": "fact",
            "title": "What these gates do not prove",
            "lead": (
                "The checks test recorded evidence and internal consistency. They do not "
                "establish that every permitted fact in a document was found."
            ),
            "paragraphs": [
                "No check can read a page and know what a careful person would have taken from "
                "it. What they can do is refuse a page that was declared empty while printing a "
                "table, refuse a page extracted far below what it prints without a stated "
                "reason, refuse a reason that describes difficulty, and refuse a lane that "
                "stopped early. That is why both readers inspect every page, and why the third "
                "reader reviews every populated table's scope and governing notes.",
                "The thresholds are also honest about their own reach. The thin-page test was "
                "set at three times the current table threshold when it was first written, and "
                "at that setting it fired on no page of the corpus, which is recorded in the "
                "threshold file itself.",
            ],
        },
        {
            "kind": "terms",
            "title": "Words on this page",
            "items": [
                [
                    "Candidate",
                    "One reader's file for one document, before anything is compared. There are "
                    "two per document.",
                ],
                [
                    "Coverage",
                    "The page-by-page record: one row per physical page saying what it held and "
                    "how many records came off it.",
                ],
                [
                    "Lane",
                    "One reader working through one route's whole worklist. A route is a group "
                    "of documents of similar kinds read under one brief.",
                ],
                [
                    "Final",
                    "The agreed version of one document, constructed from the third reader's "
                    "decisions.",
                ],
                [
                    "Grid",
                    "The map of numbers printed in tables on a page, with their row and column "
                    "labels, taken from the PDF's coordinates.",
                ],
                [
                    "Occurrence",
                    "Which time a page prints the same row label under the same column, counted "
                    "top to bottom. It settles which cell a row means when a page repeats a "
                    "label.",
                ],
            ],
        },
    ],
}


def extraction_contract_block() -> dict:
    """The 47 columns a reader writes, read from the contract module itself.

    The dashboard prose says every printed value becomes a row of 47 columns and
    then shows the warehouse tables, whose column lists are wider. No panel
    anywhere held the 47, so a reader who counted found the sentence untrue of
    the table beneath it.
    """

    from src.catalog.simple_pdf_extraction.csv_wide_contract import (
        CONTRACT_VERSION, PAIR_KEY, RECORD_COLUMNS,
    )
    from src.common import matrices

    described = matrices.mapping("field-descriptions")
    key_fields = [
        row["output_value"]
        for row in sorted(
            (r for r in matrices.load(PAIR_KEY) if r["input_value"] != "pair_id_format"),
            key=lambda item: int(item["input_value"]),
        )
    ]
    items = []
    for position, name in enumerate(RECORD_COLUMNS, 1):
        note = described.get(name, "")
        if name in key_fields:
            note = f"{note} One of the five columns that identify the printed cell."
        items.append([f"{position}. {name}", note])
    return {
        "kind": "guide",
        "tone": "fact",
        "title": f"The {len(RECORD_COLUMNS)} columns a reader writes",
        "lead": (
            f"Field list {CONTRACT_VERSION}. This is the row itself, before anything is "
            "loaded into a database. It is kept in data/extracted/pdf-wide-records.csv, "
            "where publication adds one further column recording which model produced the "
            "row. The evidence tables further down this page hold the same values under a "
            "wider column list built for querying, so their headings will not match these."
        ),
        "items": items,
    }


ISSUER_WORDS = {
    "gp": "the fund manager",
    "lp": "an investor",
    "pension": "a pension plan",
    "auditor": "an auditor",
    "administrator": "a fund administrator",
    "regulator": "a regulator",
    "standards_body": "an industry body",
    "law_firm": "a law firm",
    "other": "another publisher",
}


def document_type_rows() -> list[dict]:
    """Counts, pages and publishers per type, read from the source ledger."""

    counts: dict[str, dict] = {}
    with SOURCE_LEDGER.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            entry = counts.setdefault(
                row["doc_type"], {"files": 0, "pages": 0, "issuers": Counter()}
            )
            entry["files"] += 1
            entry["pages"] += int(float(row["page_count"]))
            entry["issuers"][row["issuer_type"]] += 1
    if set(counts) != set(DOCUMENT_TYPE_FACTS):
        raise ValueError(
            "every ledger document type needs an authored description: "
            f"missing {sorted(set(counts) - set(DOCUMENT_TYPE_FACTS))}, "
            f"unknown {sorted(set(DOCUMENT_TYPE_FACTS) - set(counts))}"
        )
    rows = []
    for name, entry in counts.items():
        side, frequency, description = DOCUMENT_TYPE_FACTS[name]
        publisher, published = entry["issuers"].most_common(1)[0]
        rows.append({
            "name": name, "side": side, "frequency": frequency,
            "description": description, "files": entry["files"], "pages": entry["pages"],
            "publisher": ISSUER_WORDS.get(publisher, publisher), "published": published,
            "issuers_pension": entry["issuers"]["pension"],
        })
    rows.sort(key=lambda row: -row["files"])
    return rows


def document_types_section() -> dict:
    """A guide-only page naming every source document type and who issues it."""

    rows = document_type_rows()
    total_files = sum(row["files"] for row in rows)
    total_pages = sum(row["pages"] for row in rows)

    def entries(side: str) -> list[list[str]]:
        result = []
        for row in rows:
            if row["side"] != side:
                continue
            # A mode of one or two copies is not a publisher pattern, so the
            # publisher is named only where it carries more than half the type.
            if row["published"] * 2 > row["files"]:
                who = f"published mostly by {row['publisher']}"
            else:
                who = "published by no one source in particular"
            result.append([
                row["name"].replace("_", " "),
                f"{row['description']} How often: {row['frequency'].lower()}. "
                f"In the corpus: {row['files']} document"
                f"{'s' if row['files'] != 1 else ''}, {row['pages']:,} pages, {who}.",
            ])
        return result

    manager = entries("GP")
    owner = entries("LP")
    quarterly = next(row for row in rows if row["name"] == "Quarterly_Report")
    reprinted = quarterly["issuers_pension"]
    return {
        "id": "document-types",
        "title": "Document types",
        "blurb": (
            f"The {len(rows)} kinds of document this corpus is built from: what each one "
            "contains, how often it appears, and which side of the market issues it."
        ),
        "blocks": [
            {
                "kind": "guide",
                "tone": "teach",
                "title": "Two sides publish everything here",
                "lead": (
                    "A private investment fund has two sides. The manager that runs it, "
                    "called the general partner or GP, and the investors that put money "
                    "into it, each called a limited partner or LP. A pension plan, an "
                    "endowment, and a foundation are all LPs."
                ),
                "paragraphs": [
                    "The manager writes most of the documents, because it is the one that "
                    "knows what the fund owns and what it earned. The investor writes the "
                    "rest, reporting on its whole programme across every manager it uses.",
                    "Who wrote a document and who published the copy we hold are different "
                    "questions, and the difference is why this corpus exists at all. Most "
                    "of what a manager sends its investors is private. Large public "
                    "investors, and pension plans above all, are required to publish, so a "
                    "manager's numbers become readable once an investor reprints them. "
                    f"That is why the quarterly report is a manager's document and yet {reprinted} "
                    f"of the {quarterly['files']} copies here were published by a pension plan.",
                    f"The corpus holds {total_files} documents across {total_pages:,} pages. "
                    "Each entry below gives what the document contains, how often it comes "
                    "out, and who published the copies we have.",
                ],
            },
            {
                "kind": "guide",
                "tone": "fact",
                "title": f"Written by the manager ({len(manager)} types)",
                "lead": (
                    "These describe one fund: what it owns, what it is worth, what it "
                    "charges, and what it agreed to."
                ),
                "items": manager,
            },
            {
                "kind": "guide",
                "tone": "fact",
                "title": f"Written by the investor ({len(owner)} types)",
                "lead": (
                    "These describe one investor's whole programme across every manager it "
                    "uses, which is why they carry allocations and policy targets that no "
                    "single fund's document can."
                ),
                "items": owner,
            },
            {
                "kind": "guide",
                "tone": "warn",
                "title": "What this market produces that is not here, and why",
                "lead": (
                    "The types above are the ones that reach the public. Six more exist "
                    "and are absent, and for five of them the reason is that they are "
                    "never published rather than that they were missed."
                ),
                "items": [[label, text] for label, text in ABSENT_DOCUMENT_TYPES],
            },
            {
                "kind": "guide",
                "tone": "warn",
                "title": "Three names cover more than they say",
                "lead": (
                    "Some documents were filed under the closest of these names rather "
                    "than getting one of their own, so the list of types is shorter than "
                    "the list of things in it."
                ),
                "items": [
                    [
                        "Regulatory holdings filings",
                        "The quarterly holdings return a large US manager files, and a "
                        "fund's monthly portfolio filing, are both held as schedules of "
                        "investments. They print the same thing: a line per holding with "
                        "its value.",
                    ],
                    [
                        "A foundation's tax return",
                        "Filed as the foundation's annual report, because the investment "
                        "schedules inside it are what the extraction reads.",
                    ],
                    [
                        "Calls and distributions",
                        "A demand for money and a payment of money are one type here, "
                        "because they are the same document shape pointing in opposite "
                        "directions.",
                    ],
                ],
            },
        ],
    }


def guide_payload() -> dict:
    """Return the dashboard payload with a novice-reader title."""

    document = build_dashboard.payload()
    document["title"] = "Alternative Investment ETL and Analytics: Field Guide"
    document["subtitle"] = (
        "Written for a reader who has not seen this repository and does not know "
        "private-fund accounting or data-engineering terms."
    )
    document["footer"] = (
        "Every displayed figure comes from the named project file. Page guide defines "
        "the repeated terms and table controls."
    )
    overview = next(section for section in document["sections"] if section["id"] == "overview")
    overview["blocks"] = [
        block
        for block in overview["blocks"]
        if not (
            block.get("kind") == "link"
            and block.get("href", "").startswith("dashboard-field-guide.html")
        )
    ]
    sections = document["sections"]
    if any(section["id"] == EXTRACTION_GATES_SECTION["id"] for section in sections):
        raise ValueError(
            f"the dashboard already publishes a {EXTRACTION_GATES_SECTION['id']!r} section"
        )
    after = next(index for index, section in enumerate(sections) if section["id"] == "extraction")
    # The 47-column row goes above the first evidence table, because that table
    # is the warehouse form and the reader needs the contract to compare it with.
    extraction = sections[after]
    blocks = extraction["blocks"]
    first_table = next(
        (index for index, block in enumerate(blocks) if block.get("kind") == "table"),
        len(blocks),
    )
    blocks.insert(first_table, extraction_contract_block())
    sections.insert(after + 1, json.loads(json.dumps(EXTRACTION_GATES_SECTION)))
    types = document_types_section()
    if any(section["id"] == types["id"] for section in sections):
        raise ValueError(f"the dashboard already publishes a {types['id']!r} section")
    corpus = next(index for index, section in enumerate(sections) if section["id"] == "corpus")
    sections.insert(corpus + 1, types)
    return document


def render(document: dict | None = None) -> str:
    """Insert current project data into the maintained field-guide shell."""

    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(PAYLOAD_MARKER) != 1:
        raise ValueError(f"{TEMPLATE} must contain one {PAYLOAD_MARKER} marker")
    if template.count(STYLE_MARKER) != 1:
        raise ValueError(f"{TEMPLATE} must contain one {STYLE_MARKER} marker")
    document = document if document is not None else guide_payload()
    body = json.dumps(document, ensure_ascii=False, sort_keys=False)
    body = body.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return template.replace(STYLE_MARKER, STYLE).replace(PAYLOAD_MARKER, body)


def build(output: Path | None = None) -> tuple[Path, int]:
    """Write the guide to one path; a custom output leaves the project guide alone."""

    output = OUTPUT if output is None else output
    text = render()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    return output, len(text.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    output, size = build(args.output)
    print(f"PASS: {output}, {size / (1024 * 1024):.1f} MB, current dashboard payload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
