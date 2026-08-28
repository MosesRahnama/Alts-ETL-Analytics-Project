# Runtime and field-list tests

Tests over acquisition, extraction, identity, promotion, fill, quality, analytics, origin records, parity, editorial prose, the reviewer dashboard, and repository structure; run with python -m pytest -q.

| File | Role |
|---|---|
| `test_acquisition_contract.py` | Acquisition routes share one PDF cache, the document-type list derives from the ledger, and a dry run never touches the network. |
| `test_analytics.py` | Fund metrics recompute their components, PME uses the latest prior benchmark date and rejects a missing one, and allocations stay bounded. |
| `test_calibration_candidates.py` | The calibration builder yields four inactive source-backed statistics and rejects unpaired metric panels. |
| `test_csv_wide_contract.py` | The generated field list verifies, routing is complete and unique, dispatch scopes never overlap, every route has its prompts, and one vocabulary serves every family of its kind. |
| `test_csv_wide_workflow.py` | Validator refusals (null values, bad quotes, shifted widths, drifted occurrences) and the matching-pair path to a final file. |
| `test_dashboard.py` | The dashboard opens with no network, renders the same bytes from the same tree, carries the counts its source files carry, and cites a path a reader can open. |
| `test_database_parity.py` | Full-content CSV-to-DuckDB comparison and header drift detection. |
| `test_editorial_prose.py` | Every Markdown file follows the house editorial rules: declarative heads, affirmative phrasing, plain vocabulary, no em dashes. |
| `test_extraction_review.py` | Every published observation appears once in the lineage table, and the agreement layers of document-summary.csv add up. |
| `test_flatten_extracted.py` | Printed numbers keep their magnitude, percents stay percents, parentheses mean negative, ambiguous dates stay unparsed, and nothing is dropped. |
| `test_fund_attributes.py` | Fund-attribute conflicts, audit-only apply behavior, evidence lookup, and changed-cell records. |
| `test_generator.py` | Generation gates, a clean universe with no quality failures, and every injected defect detected. |
| `test_integrated_universe.py` | The integrated fund ID list, extracted-row keep, financial identities, analytics, and defect detection. |
| `test_mock_universe_pipeline.py` | Stage order and checks of the mock build, including its refusal to write the fund-model database. |
| `test_name_normalization_managers.py` | Family grouping, auto-settlement, merge integrity, negative-result propagation, coverage scope, and dispatch-prompt generation. |
| `test_name_normalization_paths.py` | The identity commands, the WRITES registry, and the runbook output table name the same files. |
| `test_pivot_wide.py` | Every observation maps to one wide row, every usual and observed vocabulary name of a family is a column, the wide DDL is the one the module renders, and the set loads under its foreign keys. |
| `test_project_structure.py` | Every folder guide is current, the manifest has one hashless self row, and the live structure validates. |
| `test_promotion_gate.py` | Extracted rows need hash-linked dual-audit origin records to load; public-market rows follow their own rights check. |
| `test_promotion_to_fund_level.py` | Every promoted row names a fund and an accepted document, money reaches one scale, and the gate refuses a missing document. |
| `test_prompt_contract_agreement.py` | Every generated prompt names only real columns, the families its route permits, and vocabulary names of the kinds those families fill. |
| `test_public_markets.py` | The copied source inventory matches disk, levels and returns reconcile, and the strategy map passes its gate. |
| `test_quality.py` | XIRR on dated flows, sign requirements, clean periods passing every applicable rule, and injected errors caught. |
| `test_release_presentation.py` | Every folder has a guide, the landing documents state the data boundary in timeless words, the review tables cover every fact, and the manifest covers every tracked file. |
| `test_reviewer_check.py` | The live reviewer baseline passes. |
| `test_reviewer_publication.py` | Reviewer row coverage, enrichment evidence, and current transformation receipts. |
| `test_transformation_lineage.py` | Content-addressed archives, receipt deduplication, and distinct failed and passing attempts. |
