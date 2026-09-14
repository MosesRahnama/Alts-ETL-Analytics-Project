"""Explanations of the release-audit steps.

The dashboard lists each step's work above the release audit table and opens the
full explanation under a row when the row is selected. The local field guide
reads the same entries from the dashboard payload, so both pages show one text.
Entries follow the rows of docs/FINAL-RELEASE-AUDIT.csv in order.
"""

from __future__ import annotations

import copy

RELEASE_EXPLANATIONS: list[dict] = [
    {
        "id": "source-catalog",
        "title": "Collect and classify each source report",
        "position": "Process step 1, before any report is prepared for reading.",
        "before": (
            "A public body, fund manager, regulator, or other publisher has made a report "
            "available as a PDF file."
        ),
        "purpose": (
            "We download public investment reports and write down, for each one, where it "
            "came from, who published it, what kind of report it is, and how many pages it "
            "has."
        ),
        "work": (
            "The collection process saves the PDF and records its project identifier, "
            "filename, source address, publisher, report type, reporting period, page "
            "count, and reuse note. The report type selects the extraction workflow "
            "because a financial statement, cash-flow notice, annual report, and "
            "partnership agreement disclose different fields."
        ),
        "inputs": "Public report addresses, downloaded PDF files, and document classifications.",
        "outputs": (
            "The saved PDF reports and the source ledger. Its rows describe the reports; "
            "the financial information remains inside the PDFs until step 3."
        ),
        "check": (
            "The check opens all 452 files and recounts their pages against that record. "
            "It would catch a file that was listed but never downloaded, one that was "
            "replaced by a different document, or one that arrived truncated."
        ),
        "example": (
            "The Gates Foundation financial statements are recorded in the catalogue as a "
            "20-page report. The check opens the file and counts the pages: 20. It did "
            "this for all 452 reports and every count matched."
        ),
        "after": (
            "Process step 2 creates the page-level reading materials used by the two "
            "independent extractors and the reviewer."
        ),
        "files": [
            ["Source ledger", "data-gathering/source_ledger.csv"],
            ["Saved PDF reports", "data/documents/pdf/"],
            ["Collection program", "data-gathering/src/fetch_corpus.py"],
            ["Source documentation", "data-gathering/README.md"],
        ],
    },
    {
        "id": "document-preparation",
        "title": "Prepare every assigned PDF page for review",
        "position": (
            "Process step 2, after source collection and before either extractor reads the "
            "report."
        ),
        "before": (
            "Step 1 saved the original report and recorded its filename, source address, "
            "and page count in the source ledger."
        ),
        "purpose": (
            "For every report we intend to read, we prepare three aids: a photograph of "
            "each page, the text of each page, and a map of where the numbers sit in "
            "tables on each page. That third aid finds the table columns by looking at "
            "where numbers line up vertically, then records each value with the row label "
            "to its left and the heading above it. Numbers loose in a sentence, in an "
            "address, or in a page footer are not recorded, because they do not line up in "
            "a column."
        ),
        "work": (
            "The text file keeps physical page boundaries. A 300 dots-per-inch image "
            "records the visible page, including spacing, column headings, footnotes, and "
            "scanned text. The document grid lists possible table values with their page "
            "position. The image controls when text order or grid coordinates disagree "
            "with the printed page."
        ),
        "inputs": (
            "An assigned PDF and the approved list of fields that the readers may record "
            "for that report type."
        ),
        "outputs": (
            "Page-aligned text, one page image per physical PDF page, and a document grid "
            "for each assigned report."
        ),
        "check": (
            "The check confirms all three exist for every page of every assigned document. "
            "Without it a model could be sent to read a report whose page photographs were "
            "never made, and it would be guessing from text alone on tables the text does "
            "not lay out correctly."
        ),
        "example": (
            "For that same 20-page report we produced 20 photographs, the text of each "
            "page, and a map of its tables holding 358 values. It placed 27 on page 4 and "
            "32 on page 6. Page 4 actually prints 48 numbers, so 21 of them are not in the "
            "map: they are in sentences and footnotes, not in a column. Page 2 is the "
            "auditors' letter, whose only numbers are the firm's street address and the "
            "statement dates, and the map holds nothing at all for it. That selectivity is "
            "the point, because a later check compares what a reader typed against this "
            "map, and it would be useless if it counted street numbers."
        ),
        "after": "Process step 3 sends the same prepared pages to two independent extractors.",
        "files": [
            ["Operator runbook", "instructions/01-pdf-extraction-csv/00-OPERATOR-RUNBOOK.md"],
            ["Extraction instructions", "instructions/01-pdf-extraction-csv/README.md"],
            ["Page-aligned text", "data/documents/txt/"],
            ["Page images", "data/documents/images/"],
            ["Document grids", "data/documents/grids/"],
        ],
    },
    {
        "id": "blind-extraction",
        "title": "Record two independent readings of the same pages",
        "position": (
            "Process step 3, after document preparation and before any proposal becomes "
            "accepted evidence."
        ),
        "before": (
            "Both extractors receive the same assigned PDF, page text, page images, "
            "document grid, and report-specific field rules. Neither receives the other "
            "extractor's work."
        ),
        "purpose": (
            "Two language models read the same pages at the same time, each on its own. "
            "Neither can see the other's work. Each produces its own file of typed-out "
            "values and its own page-by-page record of what it found."
        ),
        "work": (
            "Each extractor writes one row for one printed value or statement. The row "
            "records the printed label and value, the fund or other subject, date, unit, "
            "page number, table position, quotation, and reading method. A page-coverage "
            "file lists every assigned page and the number of rows copied from it, "
            "including zero when no in-scope information appears."
        ),
        "inputs": (
            "The prepared page materials, assigned pages, and rules for the 47 columns "
            "that describe each copied value or statement."
        ),
        "outputs": (
            "Separate A and B proposal tables and page-coverage tables. A proposal is a "
            "reader's copied information before the third reader decides which rows to "
            "keep. The files use CSV, a text-table format that a spreadsheet can open."
        ),
        "check": (
            "The check confirms both covered every assigned page and that their row counts "
            "add up. It deliberately does not compare their values, because deciding who "
            "is right is the next step's job. What it catches is a model that stopped "
            "halfway and called it done."
        ),
        "example": (
            "On that report the first model typed 111 rows and the second typed 88. "
            "Neither is right or wrong yet. The next step exists to resolve that gap of 23 "
            "rows."
        ),
        "after": (
            "Process step 4 pairs the proposals and resolves each disagreement or "
            "one-extractor finding against the page image."
        ),
        "files": [
            ["Working extraction folders", "ledgers/working/pdf-extraction-csv/"],
            ["Candidate and coverage workflow", "src/catalog/simple_pdf_extraction/csv_workflow.py"],
            ["Allowed fields by row type", "data/schemas/EXTRACTION-RECORD-FAMILIES.csv"],
            ["Working-file guide", "ledgers/working/pdf-extraction-csv/README.md"],
        ],
    },
    {
        "id": "adjudication",
        "title": "Decide the retained evidence against the source page",
        "position": (
            "Process step 4, after both proposal sets and before reviewed values enter the "
            "shared evidence tables."
        ),
        "before": (
            "The report has two independent proposal files, two page-coverage files, and a "
            "comparison that pairs rows by source location and meaning."
        ),
        "purpose": (
            "A third model compares the two readings. Wherever they disagree it opens the "
            "photograph of the page, decides which is right, and records why. The result "
            "is one agreed version of the document."
        ),
        "work": (
            "The reviewer opens the cited page image for every disagreement and every "
            "field found by only one extractor. Matching proposals also receive a fixed "
            "sample check because two readers can copy the same mistake. The final row "
            "keeps the printed value, normalized field name, evidence location, decision, "
            "and links to both proposals."
        ),
        "inputs": (
            "Extractor A and B proposals, their page coverage, the pair comparison, the "
            "PDF page image, and any recorded correction decision."
        ),
        "outputs": (
            "The reviewed fields for one report are saved in records-final.csv, a "
            "text-table file that a spreadsheet can open. A second file, "
            "coverage-final.csv, records the final review state of every page. Supporting "
            "decision files keep corrections and review reasons."
        ),
        "check": (
            "The check runs the full set of rules over that agreed version: is every field "
            "filled correctly, is every page accounted for, does every number that needs "
            "context have it. It catches a disagreement decided without looking at the "
            "page, and any shortcut taken while merging the two readings."
        ),
        "example": (
            "From those two sets the third model produced 135 final rows. It took the "
            "first model's version 67 times, the second model's 28 times, combined them 26 "
            "times, kept 14 where both matched exactly, and threw out 5."
        ),
        "after": (
            "Process step 5 publishes every completed document's reviewed rows into the "
            "shared evidence files without changing the accepted source values."
        ),
        "files": [
            ["Review instructions", "instructions/01-pdf-extraction-csv/README.md"],
            ["Working extraction folders", "ledgers/working/pdf-extraction-csv/"],
            ["Final validation workflow", "src/catalog/simple_pdf_extraction/csv_workflow.py"],
            ["Review-file guide", "data/extracted/review/README.md"],
        ],
    },
    {
        "id": "corpus-publication",
        "title": "Put the checked report values in one table",
        "position": (
            "Process step 5, after the four source-reading and review steps. This is the "
            "first automated publication operation."
        ),
        "before": (
            "Each completed report already has reviewed final records whose values and "
            "locations were checked against its pages."
        ),
        "purpose": (
            "Every agreed document is gathered into one combined set of records, along "
            "with the page-by-page reading record for each."
        ),
        "work": (
            "The checked tables have already been grouped by report type. This program "
            "checks those group files against the individual reports’ checked tables, then "
            "copies the groups’ rows into one shared file. It also combines the records of "
            "pages inspected."
        ),
        "inputs": (
            "Tables of checked numbers and text, already grouped by report type; the "
            "individual reports’ checked tables; and the lists of assigned reports and "
            "pages inspected."
        ),
        "outputs": (
            "A shared table of copied information, a shared table of inspected pages, and "
            "a list of context still requiring review, such as whether a return includes "
            "fees."
        ),
        "check": (
            "The check confirms the combined set matches the agreed documents exactly. It "
            "catches publishing anything that differs from what was actually reviewed."
        ),
        "example": (
            "8,613 values from 36 reports across 693 pages are gathered here. The "
            "comparison covers every field of every reviewed row, not only the numbers, so "
            "a corrected footnote reference beside an unchanged number is caught."
        ),
        "after": (
            "The next row counts the assigned reports and records which have completed the "
            "earlier reading and review."
        ),
        "files": [
            ["Earlier work and release sequence", "PROCESS.md"],
            ["PDF reading and review instructions", "instructions/01-pdf-extraction-csv/00-OPERATOR-RUNBOOK.md"],
            ["Shared table of copied information", "data/extracted/pdf-wide-records.csv"],
            ["Pages inspected", "data/extracted/pdf-wide-coverage.csv"],
            ["Context awaiting review", "ledgers/pipeline/qualifier-backlog.csv"],
            ["Program", "src/catalog/simple_pdf_extraction/csv_workflow.py"],
        ],
    },
    {
        "id": "extraction-scope",
        "title": "Account for every assigned report",
        "position": "After the combined extraction files, before the detailed data tables.",
        "before": (
            "Step 5 assembled the checked rows from completed reports. The assignment "
            "lists identify all reports assigned for extraction, including any still in "
            "progress."
        ),
        "purpose": (
            "Counts what was assigned to be read, what was finished, and what was "
            "deliberately put off, and writes those counts down."
        ),
        "work": (
            "The program examines the assignment lists and final files for every report "
            "group. It also recounts outstanding context decisions and compares that count "
            "with the saved list."
        ),
        "inputs": (
            "The active assignment lists, each report’s checked table, and outstanding "
            "context decisions."
        ),
        "outputs": (
            "A completion table with assigned, finished, and unfinished report counts for "
            "each group."
        ),
        "check": (
            "The check makes those three numbers reconcile against the assignment lists. "
            "It catches a document that was assigned to somebody and then quietly never "
            "done, which is the one failure no per-document check can see."
        ),
        "example": (
            "For the financials route it records 6 documents assigned and 6 finished. If "
            "somebody had been assigned a seventh and quietly never done it, those two "
            "numbers would differ and the run would stop here."
        ),
        "after": "The next operation prepares separate combined files for the report groups.",
        "files": [
            ["Completion table", "ledgers/pipeline/extraction-scope.csv"],
            ["Program", "src/pipeline/publish_review_release.py"],
        ],
    },
    {
        "id": "raw-combination",
        "title": "Prepare the report-group files",
        "position": "After completion is counted, before published copies are compared.",
        "before": (
            "Reviewed extraction files exist for individual reports. The previous two "
            "steps have combined their overall records and counted completion."
        ),
        "purpose": "Groups the published records into one file per kind of report.",
        "work": (
            "The program appends each finished report’s rows in report-identifier order. "
            "The source values, columns, and row order inside each report remain "
            "unchanged. Here, “raw” names this pre-reformatting copy of reviewed data."
        ),
        "inputs": (
            "The reviewed final extraction file for each finished report on an active "
            "assignment list."
        ),
        "outputs": "Seven combined files under data/extracted/raw/, one for each report group.",
        "check": (
            "The check confirms the values and the record of which model produced them are "
            "unchanged by the regrouping. It catches a value altered while files were "
            "being rearranged."
        ),
        "example": (
            "The financials route becomes one file of 903 rows, performance 2,127 rows, "
            "institutional reports 753."
        ),
        "after": "The next check compares these files with the copies published for those groups.",
        "files": [
            ["Combined group files", "data/extracted/raw/"],
            ["Program", "src/pipeline/combine_extracted_raw.py"],
        ],
    },
    {
        "id": "round-publication-verification",
        "title": "Check the published extraction copies",
        "position": "After the report-group files, before any reformatting of their values.",
        "before": (
            "Each report group has a combined reviewed file and a published copy. The "
            "published copy also names the language model credited with the extraction."
        ),
        "purpose": (
            "Reads the regrouped files back and compares them with the published ones. "
            "This step writes nothing at all."
        ),
        "work": (
            "The program compares the corresponding rows field by field and checks that "
            "the published rows name their extracting model. Where an earlier publication "
            "exists, it also checks the model credit for unchanged cells that can be "
            "matched uniquely."
        ),
        "inputs": "The seven combined group files and the corresponding published group files.",
        "outputs": "A check result in the command output. This operation writes no new data file.",
        "check": (
            "It catches any difference between the two copies, and it catches a row losing "
            "the note of which model typed it, which is how we can always say who produced "
            "any given number."
        ),
        "example": (
            "Every row records which model typed it. 1,831 rows say claude-fable-5 plus "
            "claude-opus-5. This step confirms that record survived the regrouping, so we "
            "can always say which model produced any given number."
        ),
        "after": (
            "The next checks examine the approved corrections, fund-name decisions, and "
            "written conversion rules."
        ),
        "files": [
            ["Combined copies", "data/extracted/raw/"],
            ["Published copies", "data/extracted/rounds/"],
            ["Program", "src/pipeline/publish_review_release.py"],
        ],
    },
    {
        "id": "normalization-gates",
        "title": "Check the decisions used to standardize data",
        "position": "Before printed text is organized into the main evidence tables.",
        "before": (
            "The reviewed and published copies have been compared. Separate decision files "
            "state approved corrections, names, fund details, and conversion rules."
        ),
        "purpose": (
            "Checks the decision tables. These are the lists that say things like which "
            "printed fund names refer to the same fund, and which printed words map to "
            "which standard category."
        ),
        "work": (
            "The checks examine page-backed corrections, approved name mappings, reviewed "
            "fund details, and CSV rule tables. A CSV is a text table that a spreadsheet "
            "can open. The project calls these rule tables matrices."
        ),
        "inputs": (
            "The correction records, name mappings, reviewed fund-detail table, and "
            "transformation rule tables."
        ),
        "outputs": (
            "A table of conflicting fund details and a table recording the rule-table "
            "checks."
        ),
        "check": (
            "The check confirms each of those tables satisfies its own stated rules. It "
            "catches a list that contradicts itself, has a gap, or has been edited into an "
            "inconsistent state."
        ),
        "example": (
            "There are 334 of these decision tables. One says the printed words Absolute "
            "Return mean hedge funds, and Common and preferred stock means public equity. "
            "The check confirms each table obeys its own stated rules."
        ),
        "after": (
            "The next operation organizes the reviewed values, names, dates, and page "
            "references into related tables."
        ),
        "files": [
            ["Conflicting details", "data/normalization/attribute-conflicts.csv"],
            ["Rule checks", "ledgers/pipeline/matrix-check.csv"],
            ["Written rules", "data/normalization/transformations/"],
            ["Correction checks", "src/catalog/simple_pdf_extraction/source_review.py"],
            ["Name checks", "src/catalog/simple_pdf_extraction/name_normalization.py"],
            ["Fund-detail checks", "src/catalog/simple_pdf_extraction/fund_attributes.py"],
            ["Rule-table reader", "src/common/matrices.py"],
        ],
    },
    {
        "id": "flatten",
        "title": "Organize the printed facts and their sources",
        "position": "After decision checks, before the evidence database and fund calculations.",
        "before": "Reviewed extraction rows and checked name and field definitions are available.",
        "purpose": (
            "Writes the standard version of each value beside the printed version. The "
            "printed one is never overwritten; the standard one sits next to it."
        ),
        "work": (
            "A number or statement from one location becomes one observation, meaning one "
            "recorded fact. The program keeps the printed text beside the number or date "
            "read from it. A unit factor, such as thousands, stays in a separate field at "
            "this step."
        ),
        "inputs": (
            "Published extraction rows, the report list, field definitions, and approved "
            "name mappings."
        ),
        "outputs": (
            "Nine files, including the printed-fact table, report and page tables, name "
            "tables, and a file list."
        ),
        "check": (
            "The check confirms every standardized field still names the exact printed "
            "cell it came from. It catches a standardized value that no longer names its "
            "source, which is the point at which data stops being traceable."
        ),
        "example": (
            "Page 2 of one report prints the words Fixed income. We write the standard "
            "code fixed_income in a separate column beside it. The printed words are never "
            "overwritten, so both are visible forever."
        ),
        "after": (
            "The next operation connects these facts to the two readers’ proposals and the "
            "review decisions."
        ),
        "files": [
            ["Printed facts", "data/extracted/tables/fact_observation.csv"],
            ["Report table", "data/extracted/tables/dim_document.csv"],
            ["Files produced", "data/extracted/tables/MANIFEST.csv"],
            ["Program", "src/flatten/flatten_extracted.py"],
        ],
    },
    {
        "id": "extraction-review",
        "title": "Connect each fact to its reading and review records",
        "position": (
            "After the printed-fact table, before reconstructed tables and the evidence "
            "database."
        ),
        "before": (
            "The project has the accepted printed facts, each reader’s proposed values, "
            "the comparison between those proposals, and the decisions made during review."
        ),
        "purpose": (
            "Builds the record that keeps, next to every published number, what each of "
            "the two models originally typed for it. On page 12 of one report the row "
            "labelled Beginning balance shows 75,225,846: the first model typed it without "
            "the dollar sign, the second typed it with, the third looked at the page and "
            "kept the version with the sign. All three of those are stored, so a year from "
            "now anyone can ask what each model said and who decided. It also summarises "
            "each document: how many rows each model typed and how often they matched."
        ),
        "work": (
            "The program builds per-report review summaries and links each fact to its "
            "earlier reading and decision records. It refreshes the file list for existing "
            "page pictures. This command assembles the review history; the language models "
            "performed the review before the release rebuild."
        ),
        "inputs": (
            "Accepted facts, both readers’ files, their comparisons, review decisions, and "
            "saved page pictures."
        ),
        "outputs": (
            "Review summaries, fact-to-decision links, sample traces, and updated file "
            "lists."
        ),
        "check": (
            "The check confirms every published number has both models' original answers "
            "still attached to it. It catches a number with no origin, meaning one that "
            "cannot be shown to have come from anybody reading anything."
        ),
        "example": (
            "Illustrative example: reader A proposed 15 and reader B proposed 75. The "
            "record connects the accepted 75 to the reviewer’s decision and the cited page."
        ),
        "after": (
            "The next operation places related printed cells together in rows resembling "
            "the original tables."
        ),
        "files": [
            ["Fact-to-review links", "data/extracted/tables/observation_lineage.csv"],
            ["Report summaries", "data/extracted/review/document-summary.csv"],
            ["Page-picture list", "data/documents/images/MANIFEST.csv"],
            ["Program", "src/pipeline/build_extraction_review.py"],
            ["Picture-list program", "data-gathering/src/render_image_corpus.py"],
        ],
    },
    {
        "id": "wide",
        "title": "Put related PDF cells together in table rows",
        "position": (
            "After fact-level review links, immediately before the evidence database is "
            "built."
        ),
        "before": (
            "The evidence tables store individual printed facts. Several facts can come "
            "from different columns of the same printed table row."
        ),
        "purpose": (
            "Rebuilds each printed table, row by row, so that one row of our output "
            "corresponds to one row a person would see on the page."
        ),
        "work": (
            "The program groups cells using their report, page, printed row, date, and "
            "relevant column context. It keeps different reporting periods and different "
            "investor positions separate. Each reconstructed cell retains a reference to "
            "the individual fact it came from."
        ),
        "inputs": (
            "The printed-fact tables, tables of investments owned, name mappings, and "
            "written grouping rules."
        ),
        "outputs": (
            "Eighteen reconstructed table files, a file connecting their cells to the "
            "original facts, a file list, and database table definitions."
        ),
        "check": (
            "The check confirms every rebuilt cell still names the individual values it "
            "was assembled from. It catches a rebuilt row that has quietly mixed together "
            "cells from different printed rows."
        ),
        "example": (
            "Page 1 of the Oregon Growth Account report has a line for Adventure Fund I, "
            "L.P. reading: Committed $3,000,000, Contributed $2,558,543, Distributed "
            "$4,987,944, Remaining Value $0, IRR 11.97, TVPI 1.95, Unfunded $0. In the "
            "evidence table those are seven separate rows, one per cell. This step puts "
            "them back together into one row, exactly as a person reading the page sees it."
        ),
        "after": (
            "The next operation stores both the individual-fact tables and these "
            "reconstructed tables in the evidence database."
        ),
        "files": [
            ["Reconstructed tables", "data/extracted/wide/"],
            ["Links to printed facts", "data/extracted/wide/bridge_pivot_observation.csv"],
            ["File and conflict counts", "data/extracted/wide/MANIFEST.csv"],
            ["Program", "src/flatten/pivot_wide.py"],
        ],
    },
    {
        "id": "extracted-database",
        "title": "Store the evidence tables in one database file",
        "position": (
            "After evidence tables are prepared, before the analytical fund tables are "
            "built."
        ),
        "before": (
            "The project has spreadsheet-readable CSV files for individual facts, their "
            "sources, and reconstructed printed rows."
        ),
        "purpose": "Loads all the evidence into a database so it can be queried quickly.",
        "work": (
            "The program builds a replacement database from the CSV files. It then reads "
            "the stored tables back and compares them with the inputs before replacing the "
            "previous database."
        ),
        "inputs": (
            "The individual-fact tables, reconstructed tables, and definitions of their "
            "database columns."
        ),
        "outputs": "The evidence database, data/warehouse/extracted.duckdb.",
        "check": (
            "The check compares the database with the spreadsheets it was built from, "
            "value for value. The database is only a convenient copy, never a second "
            "version of the truth, and this is what enforces that."
        ),
        "example": (
            "All 8,613 values are loaded, then every cell is compared with the spreadsheet "
            "it came from. A single mismatched cell stops the run."
        ),
        "after": (
            "The next operation records which source-backed fund details can be reused. "
            "Later fund-table construction reads the evidence CSV files; this database is "
            "an additional form of those tables."
        ),
        "files": [
            ["Evidence database", "data/warehouse/extracted.duckdb"],
            ["Program", "src/flatten/load_star.py"],
            ["Shared comparison code", "src/load/load_csv_to_duckdb.py"],
        ],
    },
    {
        "id": "attribute-audit",
        "title": "Record the source of reusable fund details",
        "position": "Immediately before the analytical fund tables are built.",
        "before": (
            "Reviewed facts identify some lasting fund details, such as its start year and "
            "investment strategy. A strategy describes the kinds of investments a fund "
            "pursues."
        ),
        "purpose": (
            "Where one document states a fund's vintage year or strategy and another does "
            "not, the known value is copied to the fund's other records."
        ),
        "work": (
            "The program reads the reviewed fund-detail decisions and writes their source "
            "references. Although its command is named apply, this step writes the audit "
            "record. The next operation performs the changes to the fund tables."
        ),
        "inputs": "The printed facts and the reviewed table of fund details and their sources.",
        "outputs": "An audit file naming the source of reusable details.",
        "check": (
            "The check confirms every copied value names the document and page it came "
            "from. It catches an attribute appearing on a fund with no evidence for it."
        ),
        "example": (
            "One fund's asset class is printed as Short term on page 2 of one report and "
            "nowhere else. That value is copied to the fund's other records, and the "
            "record of the copy names the report and the page, so its source is always "
            "known."
        ),
        "after": "The next operation builds the fund tables and applies these approved details.",
        "files": [
            ["Detail-source audit", "data/extracted/audit/attribute-inherit.csv"],
            ["Reviewed decisions", "data/normalization/fund-attributes-matrix.csv"],
            ["Program", "src/catalog/simple_pdf_extraction/fund_attributes.py"],
        ],
    },
    {
        "id": "fund-model-promotion",
        "title": "Build comparable fund records for analysis",
        "position": (
            "After evidence and fund-detail checks, before generated example data are "
            "added."
        ),
        "before": (
            "The project has printed facts with page references, approved fund names, "
            "written conversion rules, and reusable fund details."
        ),
        "purpose": (
            "Turns the printed evidence into fund records: positions, dated transactions, "
            "terms and holdings, built only from what pages actually say."
        ),
        "work": (
            "The program reads the evidence CSV files, applies the approved field and unit "
            "rules, and fills supported lasting details within the same fund. It keeps "
            "whole-fund figures separate from one investor’s share of the fund. Unmapped "
            "facts remain in the evidence tables."
        ),
        "inputs": (
            "Printed facts, investments owned, fund identifiers, field-conversion rules, "
            "and approved fund details."
        ),
        "outputs": (
            "The source-based fund tables, records of attribute changes and rejected field "
            "mappings, and document-acceptance records for the next check."
        ),
        "check": (
            "The check confirms these tables contain nothing invented. It catches a "
            "generated value in the set that must hold only printed values."
        ),
        "example": (
            "451 fund periods are built, every one of them marked as read from a page. "
            "Nothing in this set is generated."
        ),
        "after": (
            "The next check confirms that source-marked fund rows refer to documents "
            "accepted by the extraction review."
        ),
        "files": [
            ["Fund list", "data/csv/fund_master.csv"],
            ["Fund-and-date records", "data/csv/fund_periods.csv"],
            ["Copied-detail changes", "data/extracted/audit/attribute-changes.csv"],
            ["Document-acceptance records", "ledgers/promotion-gate/round02/"],
            ["Program", "src/load/promote_extracted_to_fund_level.py"],
        ],
    },
    {
        "id": "normalized-holdings",
        "title": "Separate holding owners, targets, instruments, and positions",
        "position": "After source-only fund tables are built, before their acceptance check.",
        "before": (
            "The evidence tables can describe a reporting owner and a held fund or company in "
            "the same row. The older compatibility table cannot represent those roles cleanly."
        ),
        "purpose": (
            "Builds a second, owner-aware representation of every source holding without "
            "changing the printed evidence or the compatibility holdings table."
        ),
        "work": (
            "The program joins each reconstructed holding to its accepted source cells and a "
            "reviewed reporting-owner decision. It creates separate owner, target, instrument, "
            "position, and field-origin records. Portfolio totals and asset-class totals receive "
            "an explicit refusal instead of being treated as investments."
        ),
        "inputs": (
            "Reconstructed source holdings, their source-cell links, source identities, and the "
            "reviewed holding-owner map."
        ),
        "outputs": (
            "Six normalized source tables plus a refusal file for source rows that are aggregates "
            "rather than investee positions."
        ),
        "check": (
            "The output must not turn market value into fair value, portfolio weight into "
            "ownership, or a held fund into its own reporting owner."
        ),
        "example": (
            "The current source set contains 487 reconstructed holdings. This step publishes 454 "
            "normalized positions and keeps 33 aggregate or summary rows as stated refusals."
        ),
        "after": "The next step proves that every source holding was handled exactly once.",
        "files": [
            ["Owners", "data/csv/investment_owner.csv"],
            ["Positions", "data/csv/fund_position.csv"],
            ["Field origins", "data/csv/holding_field_lineage.csv"],
            ["Refusals", "data/extracted/audit/normalized-holdings-refusals.csv"],
            ["Program", "src/load/build_normalized_holdings.py"],
        ],
    },
    {
        "id": "normalized-holdings-check",
        "title": "Prove complete source-holding coverage",
        "position": "Immediately after the owner-aware holding tables are built.",
        "before": (
            "The normalized tables and refusal file now state the disposition of the current "
            "source holdings."
        ),
        "purpose": (
            "Blocks publication unless every source holding has exactly one disposition and the "
            "normalized database rules find no error."
        ),
        "work": (
            "The checker loads the six CSV files into a temporary DuckDB under their real keys "
            "and checks. It compares source holding IDs with normalized position IDs and refusal "
            "IDs, then runs the normalized holdings QA view."
        ),
        "inputs": "The six normalized CSV files, the refusal file, fund identities, and source holdings.",
        "outputs": "A check result in the command output; this step writes no data file.",
        "check": (
            "It catches dropped source holdings, duplicate dispositions, missing owners, invalid "
            "fund-interest links, range errors, and unsupported look-through relationships."
        ),
        "example": (
            "The current run proves 454 normalized positions plus 33 refusals equals all 487 "
            "source holdings, with zero ERROR findings."
        ),
        "after": "The ordinary promotion check then continues with the accepted fund records.",
        "files": [
            ["Normalized holdings QA", "Expansion/holdings/normalized_holdings_qa.sql"],
            ["Program", "src/load/validate_normalized_holdings.py"],
        ],
    },
    {
        "id": "promotion-gate",
        "title": "Check the accepted source behind each fund row",
        "position": (
            "Immediately after source-based fund tables are built, before their "
            "preservation and completion."
        ),
        "before": (
            "At this point, fund-table rows contain reported values and a reference to the "
            "report they came from."
        ),
        "purpose": (
            "Re-reads the promoted fund rows and confirms each one has the evidence behind "
            "it and the permission to be used. Writes nothing."
        ),
        "work": (
            "The program examines the source references on the relevant fund-table rows "
            "and compares them with the document-acceptance records. It also applies its "
            "public-market checks to any market-source rows already present."
        ),
        "inputs": (
            "The fund tables and accepted-document records, plus market approval records "
            "where applicable."
        ),
        "outputs": "A check result in the command output; the check writes no new data file.",
        "check": (
            "It catches a row promoted into the fund model without the source reference "
            "that justifies it."
        ),
        "example": (
            "It re-reads those 451 and confirms each one names the evidence row behind it. "
            "A promoted row with no source reference stops the run."
        ),
        "after": (
            "The next operation keeps a copy of the source-based fund tables before adding "
            "generated values."
        ),
        "files": [
            ["Document-acceptance progress", "ledgers/promotion-gate/round02/progress.csv"],
            ["Program", "src/load/validate_round02_promotion.py"],
        ],
    },
    {
        "id": "extracted-fund-level-snapshot",
        "title": "Keep a copy of the fund tables before generated additions",
        "position": "Between the source-acceptance check and the generated-data operation.",
        "before": (
            "The fund tables contain source-based values, standardized units, and "
            "supported details copied within the same fund."
        ),
        "purpose": (
            "Takes a copy of the fund tables at this exact moment, before anything is "
            "filled in."
        ),
        "work": (
            "The program copies the eleven designated fund-table files to "
            "data/extracted/fund-level/. These are the standardized fund tables at this "
            "point; the earlier evidence tables retain the literal PDF text."
        ),
        "inputs": "The eleven source-based fund-table files selected by the release program.",
        "outputs": "Eleven saved copies under data/extracted/fund-level/.",
        "check": (
            "This is what makes the next step provable. Because an untouched copy exists, "
            "we can always show that filling gaps changed nothing that was printed."
        ),
        "example": (
            "A copy of those 451 fund periods is taken here, before anything is filled in. "
            "That copy is what makes the next step provable."
        ),
        "after": (
            "The next operation adds labeled example data and verifies that the "
            "source-based records remain intact."
        ),
        "files": [
            ["Saved source-based tables", "data/extracted/fund-level/"],
            ["Program", "src/pipeline/build_integrated_universe.py"],
        ],
    },
    {
        "id": "integrated-completion",
        "title": "Add labeled data for the analysis examples",
        "position": (
            "After the source-based copies are saved, before financial checks and "
            "calculations."
        ),
        "before": (
            "Real reports supply some balances and returns but often omit the complete "
            "sequence of payments required for further calculations."
        ),
        "purpose": (
            "Fills in the analytical inputs the source documents do not provide, so the "
            "calculations have complete data to run against. Every filled value is "
            "labelled as generated."
        ),
        "work": (
            "The program adds fund-date records, payments into and out of funds, "
            "contractual details, and investments owned under stated settings. Repeatable "
            "generation settings produce the same example values on repeated builds. It "
            "also selects the public-market comparison data prepared earlier."
        ),
        "inputs": (
            "The saved source-based fund tables, approved fund details, prepared market "
            "data, and generation settings."
        ),
        "outputs": (
            "Updated working fund tables, cell-by-cell origin records, remaining-gap "
            "records, comparisons with the source-based copies, and deliberate-error test "
            "results."
        ),
        "check": (
            "The check confirms two things: every added value has its label and the method "
            "that produced it, and not one printed value was altered. It catches generated "
            "numbers presented as observed ones."
        ),
        "example": (
            "Four funds report in Canadian dollars and euros. No report prints an exchange "
            "rate for them, so the step invents none: it writes no money rows for those "
            "funds and records four currency gaps. A further 944 gaps stay open because no "
            "report states a sub-strategy, and inventing one would be a guess presented as "
            "a fact."
        ),
        "after": (
            "The next check verifies the source and permitted use of the market data "
            "selected for the comparisons."
        ),
        "files": [
            ["Working fund tables", "data/csv/"],
            ["Origin of added cells", "data/integrated/cell-lineage.csv"],
            ["Remaining gaps", "data/integrated/gap-ledger.csv"],
            ["Source-retention comparisons", "data/integrated/reconciliation-results.csv"],
            ["Deliberate-error results", "data/integrated/detection-scorecard.csv"],
            ["Program", "src/pipeline/build_integrated_universe.py"],
        ],
    },
    {
        "id": "benchmark-rights-gate",
        "title": "Check permission to use the market comparison data",
        "position": (
            "After market rows are selected, before investment comparisons are calculated."
        ),
        "before": (
            "The completed tables include dated public-market returns. A benchmark is the "
            "market investment or index used as a comparison for a fund."
        ),
        "purpose": (
            "Checks the market index data used for comparison against the licence "
            "conditions attached to it."
        ),
        "work": (
            "The program runs the source-acceptance checker again because the completion "
            "operation has just written market rows. It checks their source and policy "
            "records, including the conditions for demonstration-only use."
        ),
        "inputs": (
            "The market return rows, retained-source list, selection decisions, quality "
            "results, and use-policy records."
        ),
        "outputs": "A check result in the command output; this step creates no new data file.",
        "check": (
            "It catches a benchmark licensed for demonstration only being used as though "
            "it were licensed for production. That misuse is a legal exposure, not a data "
            "error."
        ),
        "example": (
            "All seven market series in the comparison data are marked DEMONSTRATION_ONLY, "
            "each with a note saying it is not approved for production use or "
            "redistribution. Together they hold 42,876 dated observations, and every one "
            "of them keeps that restriction."
        ),
        "after": (
            "The next operation checks the financial relationships in the completed fund "
            "data."
        ),
        "files": [
            ["Market return rows", "data/csv/benchmark_returns.csv"],
            ["Use policy", "data/integrated/benchmark-policy.csv"],
            ["Program", "src/load/validate_round02_promotion.py"],
        ],
    },
    {
        "id": "quality",
        "title": "Test the financial relationships after data completion",
        "position": (
            "After generated additions and market permission checks, before performance "
            "calculations."
        ),
        "before": (
            "The working fund tables contain source-based records and labeled generated "
            "records, with payments, balances, and reported returns."
        ),
        "purpose": "Runs the 23 accounting rules over the completed fund data.",
        "work": (
            "The rules examine balances, dates, payment signs, and relationships between "
            "amounts and performance figures. Checks on source-based rows use the "
            "source-based fund details so that generated additions do not conceal missing "
            "source information."
        ),
        "inputs": (
            "The working fund records and payments, the financial rules, source-based "
            "details, and information about printed rounding."
        ),
        "outputs": "The financial-check results file for the completed data.",
        "check": (
            "The check confirms each rule was applied to the right population. It catches "
            "a rule meant for printed rows being run against generated ones, which would "
            "make the result meaningless."
        ),
        "example": (
            "36,585 checks ran here: 30,364 passed, 6,219 did not apply, 2 failed. A "
            "passing example, using the same Adventure Fund I line from step 12: the "
            "report prints a total value multiple of 1.95. We ignore that and recompute it "
            "ourselves from the printed inputs, 4,987,944 plus 0 divided by 2,558,543, "
            "which gives 1.9495 and rounds to 1.95. The report and our arithmetic agree."
        ),
        "after": "The next operation applies financial checks to the source-based copies alone.",
        "files": [
            ["Completed-data checks", "data/csv/quality_results.csv"],
            ["Source-value exceptions", "data/normalization/transformations/quality-source-exceptions.csv"],
            ["Program", "src/quality/run_fund_checks.py"],
        ],
    },
    {
        "id": "extracted-only-quality",
        "title": "Test the source-based fund data on their own",
        "position": "After the completed-data checks, before source-based return calculations.",
        "before": (
            "The source-based copies saved at process step 17, internal execution order "
            "95, remain available alongside the working tables containing generated "
            "additions."
        ),
        "purpose": (
            "Runs the same 23 rules again over the printed-only data, before any "
            "gap-filling."
        ),
        "work": (
            "The program applies the financial rules to the saved source-based tables and "
            "writes their results in a different file from the completed-data results."
        ),
        "inputs": (
            "The saved source-based fund records and payments, financial rules, and "
            "printed-rounding information."
        ),
        "outputs": "The source-based financial-check results under data/extracted/fund-level/.",
        "check": (
            "This exists so a problem in a source document is visible on its own and is "
            "not hidden once generated values are mixed in. It is how we can say the two "
            "negative balances come from the page and not from us."
        ),
        "example": (
            "7,414 checks over the printed data alone, with 2 failures. Both are the same "
            "report: a holding value of minus 1,500,000 and a distribution of minus "
            "100,000, printed on the page in parentheses, which is how accountants write a "
            "negative. We keep them as printed and the rule keeps objecting."
        ),
        "after": (
            "The next operation calculates the performance measures supported by these "
            "source-based inputs."
        ),
        "files": [
            ["Source-based checks", "data/extracted/fund-level/quality_results.csv"],
            ["Program", "src/quality/run_fund_checks.py"],
        ],
    },
    {
        "id": "extracted-only-analytics",
        "title": "Calculate returns supported by the reported data",
        "position": (
            "After source-based financial checks, before calculations using generated "
            "additions."
        ),
        "before": (
            "The project has checked the source-based records for each fund and reporting "
            "date, apart from the generated additions."
        ),
        "purpose": (
            "Calculates the performance multiples from printed values alone, and only for "
            "the periods where the required inputs are actually printed and the accounting "
            "rules passed."
        ),
        "work": (
            "The three ratios are called DPI, RVPI, and TVPI, respectively. Each compares "
            "an amount with the cash paid into the fund. A return rate that uses "
            "individual payment dates is calculated only when the required dated payments "
            "exist."
        ),
        "inputs": "Source-based fund-date records, payments, and financial-check results.",
        "outputs": (
            "A separate source-based performance file, labeled to distinguish it from "
            "calculations using generated inputs."
        ),
        "check": (
            "The check enforces that restriction. It catches a multiple being calculated "
            "for a period missing an input, which would produce a precise-looking number "
            "with no printed input for it."
        ),
        "example": (
            "804 measures. Adventure Fund I again: cash returned divided by cash put in, "
            "4,987,944 divided by 2,558,543, giving 1.9495. The row stores the name of the "
            "formula used and the exact record it read, so anybody can repeat it by hand."
        ),
        "after": (
            "The next operation calculates the demonstration results using the completed "
            "data and public-market comparisons."
        ),
        "files": [
            ["Source-based performance", "data/extracted/fund-level/fund_metrics.csv"],
            ["Program", "src/analytics/run_extracted_analytics.py"],
        ],
    },
    {
        "id": "analytics",
        "title": "Calculate fund and market-comparison results",
        "position": (
            "After financial and market-use checks, before the reviewer’s combined tables."
        ),
        "before": (
            "The working tables contain labeled data additions and checked public-market "
            "comparison series. Source-based performance already has its own published "
            "file."
        ),
        "purpose": (
            "Calculates the multiples, the public-market comparisons and the demonstration "
            "portfolio weights over the completed data."
        ),
        "work": (
            "A payment-date return rate, called XIRR, uses the amounts and dates of money "
            "paid in and received. A public-market equivalent, called PME, compares those "
            "same payments with investment in the chosen market series. The portfolio "
            "weights state the fraction assigned to each included fund."
        ),
        "inputs": (
            "Completed fund records, dated payments, market returns, financial-check "
            "results, and portfolio settings."
        ),
        "outputs": (
            "Fund performance figures, public-market comparison results, and portfolio "
            "allocations. Calculations retain the labels identifying their generated "
            "inputs."
        ),
        "check": (
            "The check confirms each result records whether its inputs were printed or "
            "generated. It catches a headline figure whose origin can no longer be "
            "established."
        ),
        "example": (
            "3,764 measures over the completed data, plus 1,882 comparisons against the "
            "market index. Each row records whether its inputs were read off a page or "
            "generated."
        ),
        "after": (
            "The next operation places fund results, source references, and added-value "
            "explanations in the reviewer’s tables."
        ),
        "files": [
            ["Fund performance", "data/csv/fund_metrics.csv"],
            ["Market comparisons", "data/csv/pme_results.csv"],
            ["Portfolio allocations", "data/csv/portfolio_allocations.csv"],
            ["Program", "src/analytics/run_integrated_analytics.py"],
            ["Calculation code", "src/analytics/run_round04_analytics.py"],
        ],
    },
    {
        "id": "reviewer-publication",
        "title": "Assemble the tables presented for review",
        "position": (
            "After performance calculations, before the completed fund database and "
            "closing checks."
        ),
        "before": (
            "The project has separate files for printed facts, fund details, additions, "
            "financial checks, and calculated results."
        ),
        "purpose": (
            "Flattens everything into wide review files a person can open and read: one "
            "row per printed fact, one row per fund and date, with the origin of every "
            "field beside it."
        ),
        "work": (
            "The program connects the fund records with the evidence and review records. "
            "It also publishes the origin of added cells, remaining gaps, and a summary of "
            "the calculated results."
        ),
        "inputs": (
            "Printed facts and review links, source-based and completed fund records, "
            "fund-detail decisions, financial checks, and performance results."
        ),
        "outputs": (
            "Five reviewer files: printed observations, fund-and-date records, cell "
            "origins, remaining gaps, and an analytics summary."
        ),
        "check": (
            "The check reconciles those files against the tables underneath them. It "
            "catches a reviewer file that no longer matches the data it claims to show."
        ),
        "example": (
            "8,613 rows with 109 columns each. One row shows the printed value, what each "
            "model typed, the decision that resolved it, the fund it was matched to, and "
            "the result of every accounting check that touched it."
        ),
        "after": "The next operation stores the completed fund tables in a database file.",
        "files": [
            ["Printed observations", "data/extracted/review/reviewer-observations.csv"],
            ["Fund-and-date records", "data/extracted/review/reviewer-fund-periods.csv"],
            ["Cell origins", "data/extracted/review/reviewer-cell-lineage.csv"],
            ["Remaining gaps", "data/extracted/review/reviewer-gap-ledger.csv"],
            ["Results summary", "data/extracted/review/reviewer-analytics-summary.csv"],
            ["Program", "src/pipeline/build_reviewer_publication.py"],
        ],
    },
    {
        "id": "fund-model-database",
        "title": "Store the completed fund tables in a database",
        "position": "Last data-writing operation, before the release’s closing review.",
        "before": (
            "The fund data, added records, financial checks, and performance calculations "
            "have been written as CSV files, which are text tables a spreadsheet can open."
        ),
        "purpose": "Loads the completed fund model into its own database.",
        "work": (
            "The program builds a replacement database from the completed CSV files, reads "
            "its tables back, and compares them with those files. The database is another "
            "stored form of the published tables."
        ),
        "inputs": (
            "The completed fund-model CSV tables, database column definitions, and "
            "source-acceptance records."
        ),
        "outputs": "The completed-data database, data/warehouse/alts.duckdb.",
        "check": (
            "As with the evidence database, the check compares it with the spreadsheets "
            "value for value."
        ),
        "example": (
            "The completed fund model is loaded and then compared with its spreadsheets "
            "cell by cell, the same way the evidence database was at step 13."
        ),
        "after": "The closing review checks the current outputs and assignments together.",
        "files": [
            ["Completed-data database", "data/warehouse/alts.duckdb"],
            ["Program", "src/load/load_csv_to_duckdb.py"],
        ],
    },
    {
        "id": "reviewer-check",
        "title": "Check the prepared release as a whole",
        "position": "After all 21 data operations, at the end of the main release command.",
        "before": (
            "The release has produced evidence tables, source-based copies, completed fund "
            "tables, reviewer files, calculations, and databases."
        ),
        "purpose": "One pass over everything published at once.",
        "work": (
            "The checks cover assigned-report completion, required context, evidence and "
            "review links, preservation of source records, calculation populations, and "
            "agreement between databases and their source tables."
        ),
        "inputs": (
            "The prepared release files, current extraction assignments, and saved records "
            "for generated outputs."
        ),
        "outputs": (
            "A closing check report printed by the command and a saved result in the "
            "release-check table. The recorded result below states the outcome of the "
            "latest saved check."
        ),
        "check": (
            "It confirms the counts tie out between files, no identifier is duplicated or "
            "orphaned, every row states whether it was read or generated, each database "
            "matches its spreadsheets, and every file the release must produce has a "
            "current receipt. It also reports what is still owed, so every open item is "
            "stated in the report."
        ),
        "example": (
            "169 checks over everything at once, all passing, with 2 observations "
            "disclosed in the result."
        ),
        "after": (
            "The documented closeout also rebuilds the presentation and runs repository "
            "checks and automated tests, summarized by the next row."
        ),
        "files": [
            ["Closing checks", "src/pipeline/reviewer_check.py"],
            ["Main release program", "src/pipeline/publish_review_release.py"],
            ["Release status document", "docs/STATUS.md"],
        ],
    },
    {
        "id": "repository-and-tests",
        "title": "Check the project files, presentation, and tested behavior",
        "position": "Final listed closeout, after the data release and presentation rebuild.",
        "before": (
            "The main release command has finished. The documented closeout also refreshes "
            "the project’s guides, file lists, and dashboard."
        ),
        "purpose": (
            "The last pass covers the repository itself, not the data: the folder guides, "
            "the file manifest, a check on every file by type, and the full test suite."
        ),
        "work": (
            "Repository checks examine file structure and release artifacts. The test "
            "suite runs programmed cases, including cases designed to trigger refusals. "
            "Dashboard rebuilding and these commands are separate from the 23 publication "
            "operations above."
        ),
        "inputs": (
            "The current project files, rebuilt dashboard, documentation, and automated "
            "tests."
        ),
        "outputs": (
            "Recorded results from repository checks and the full automated test suite. "
            "The current test count and result appear in the recorded result detail below."
        ),
        "check": (
            "It catches documentation that no longer describes the tree, a file present "
            "that nothing accounts for, and any code change that broke a behaviour a test "
            "protects."
        ),
        "example": (
            "The final result reports the current file, folder, and test counts after every check passes."
        ),
        "after": (
            "This is the last listed row. The prepared dashboard displays the saved data "
            "and check assessments from its build."
        ),
        "files": [
            ["Tests", "tests/"],
            ["Release audit document", "docs/FINAL-RELEASE-AUDIT.md"],
            ["Closeout commands", "PROCESS.md"],
        ],
    },
]


def explanations_for(stage_ids: list[str]) -> list[dict]:
    """The explanations in audit-table order; refuses a missing, new, or moved step."""

    ids = [entry["id"] for entry in RELEASE_EXPLANATIONS]
    if ids != list(stage_ids):
        raise ValueError("Release explanations must match every current audit stage in order")
    return copy.deepcopy(RELEASE_EXPLANATIONS)
