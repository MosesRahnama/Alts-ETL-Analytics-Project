"""Write consistent folder guides for the curated project tree."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".pytest_cache", "__pycache__"}
# Folders whose guide is written by hand. The generator leaves these files
# alone and the structure check compares nothing against them. This list is
# the record; a marker inside the file would put a note to the generator in
# front of every reader of the repository.
HAND_WRITTEN = frozenset({
    ".",
    "archive",
    "audit",
    "audit/dashboard-explanation",
    "config",
    "data",
    "data/csv",
    "data/documents/images",
    "data/demo",
    "data/extracted",
    "data/extracted/audit",
    "data/extracted/fund-level",
    "data/integrated",
    "data/normalization",
    "data/public_markets",
    "data/synthetic",
    "data/synthetic/analytics",
    "data/synthetic/clean",
    "data/synthetic/defects",
    "data/warehouse",
    "instructions",
    "instructions/02-fund-mapping",
    "instructions/03-synthetic-qc",
    "instructions/04-analytics",
    "ledgers/pipeline",
    "src",
    "src/analytics",
    "src/dashboard",
    "src/pipeline",
})


def hand_written(directory: Path) -> bool:
    return relative(directory) in HAND_WRITTEN
BULK_DIRS = {
    "data/documents/pdf",
    "data/documents/txt",
    "data/public_markets/sources",
}
NEXT_READMES = {
    "data/documents": ("../extracted/README.md", "Published extraction"),
    "data/public_markets": ("../../docs/PUBLIC-MARKET-DATA.md", "Benchmark methods and rights"),
    "docs": ("FINAL-RELEASE-AUDIT.md", "Release check"),
    "data/extracted/review": ("../../warehouse/README.md", "Warehouse"),
    "instructions/01-pdf-extraction-csv": ("../02-fund-mapping/README.md", "Fund identity and manager mapping"),
}

# Files listed in the order a reader meets them in the process. A folder absent
# here lists its files alphabetically; a file absent from its folder's tuple is
# appended alphabetically after the ordered ones.
FOLDER_ORDER: dict[str, tuple[str, ...]] = {
    "data-gathering": ("source_ledger.csv", "document-types.csv", "document-types.md", "AGENT-A1-CORPUS-GATHERING.md"),
    "data-gathering/src": ("_acquire_lib.py", "_merge_rows.py", "fetch_corpus.py", "render_image_corpus.py"),
    "data/documents/grids": ("MANIFEST.csv",),
    "data/documents/images": ("MANIFEST.csv",),
    "data/schemas": (
        "EXTRACTION-ROUTING.csv", "EXTRACTION-DISPATCH-SCOPE.csv", "EXTRACTION-DOC-TYPE-MAP.csv",
        "EXTRACTION-RECORD-FAMILIES.csv", "EXTRACTION-METRIC-CATEGORIES.csv",
        "MASTER-EXTRACTION-SCHEMA.md", "EXTRACTED-FIELDS.md",
    ),
    "instructions/01-pdf-extraction-csv": (
        "00-OPERATOR-RUNBOOK.md", "FIELD-SELECTION.csv", "CSV-TEMPLATE.csv", "COVERAGE-TEMPLATE.csv",
        "RESOLUTION-TEMPLATE.csv", "COVERAGE-RESOLUTION-TEMPLATE.csv", "BATCH-WORKLIST-TEMPLATE.csv", "workflow.py",
    ),
    "ledgers/analysis": (
        "field_label_census.csv", "round1_family_survey_fields.csv", "document_field_inventory.csv",
        "document_type_field_schema.csv", "report_subtype_schema.csv", "split_number_audit.csv",
        "manager_locus_sweep.csv", "derived_manager_ledger.csv", "model-ledger.csv",
        "synthetic_parameter_candidates.csv",
    ),
    "ledgers/doc-type": (
        "a-batch1.csv", "a-batch2.csv", "a-batch3.csv", "a-batch4.csv",
        "b-batch1.csv", "b-batch2.csv", "b-batch3.csv", "b-batch4.csv", "doc-type-audit.csv",
    ),
    "ledgers/promotion-gate": ("adjudication_template.csv", "audit_template.csv", "audit_adjudication_template.csv"),
    "data/extracted/tables": (
        "dim_document.csv", "dim_page.csv", "dim_entity.csv", "entity_alias.csv", "dim_metric.csv",
        "fact_observation.csv", "observation_lineage.csv", "fact_holding.csv", "unresolved_names.csv", "MANIFEST.csv",
    ),
    "data/extracted/wide": ("MANIFEST.csv", "bridge_pivot_observation.csv"),
    "data/normalization/worksheets": tuple(f"fund-part-{n:02d}.csv" for n in range(1, 10)),
    "data/public_markets/audit": ("market_data_runs.csv", "source_file_inventory.csv", "source_family_summary.csv", "quality_results.csv"),
    "data/public_markets/staging": (
        "benchmark_master_candidates.csv", "benchmark_level_candidates.csv",
        "benchmark_return_candidates.csv", "benchmark_strategy_map_candidates.csv",
    ),
    "docs": (
        "STATUS.md", "ARCHITECTURE.md", "DATA-MODEL.md", "EXTRACTED-DATA-MODEL.md", "PUBLIC-MARKET-DATA.md",
        "SYNTHETIC-DATA-AND-QUALITY.md", "FINAL-RELEASE-AUDIT.md", "FINAL-RELEASE-AUDIT.csv",
        "PROJECT-MANIFEST.csv", "CSV-LINEAGE.csv",
    ),
    "src/catalog": ("build_txt_corpus.py", "repair_split_numbers.py", "census_field_labels.py", "sweep_manager_loci.py"),
    "src/catalog/simple_pdf_extraction": (
        "csv_wide_contract.py", "field_guide.py", "build_csv_pipeline.py", "page_grid.py", "build_page_grids.py",
        "csv_workflow.py", "name_normalization.py", "fund_attributes.py",
    ),
    "src/dashboard": ("build_dashboard.py", "page.py"),
    "src/flatten": ("flatten_extracted.py", "pivot_wide.py", "load_star.py"),
    "src/load": ("promote_extracted_to_fund_level.py", "validate_round02_promotion.py", "load_csv_to_duckdb.py"),
    "src/repository": ("build_readmes.py", "build_project_manifest.py", "check_project_structure.py"),
    "sql/duckdb": ("03_extracted_star_ddl.sql", "04_extracted_wide_ddl.sql", "02_fund_level_ddl.sql"),
}
WORKING_DOCUMENT_ORDER = (
    "records-a.csv", "records-b.csv", "coverage-a.csv", "coverage-b.csv",
    "pair-index.csv", "coverage-diff.csv", "resolution.csv", "coverage-resolution.csv",
    "records-final.csv", "coverage-final.csv",
)
SCHEMA_DISCOVERY_ORDER = (".file-ledger.csv", ".field-ledger.csv", ".sample.csv", ".schema.md")


def python_docstring(path: Path) -> str:
    """The module's first docstring line, or an empty string when it has none."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ""
    text = ast.get_docstring(tree)
    return text.strip().splitlines()[0].rstrip(".") + "." if text else ""

# Document-family folder names under schema-discovery, mapped to the ratified
# document type they surveyed.
FAMILY_FOLDERS = {
    "financials": "Financials", "performance": "Performance", "schedule-inv": "Schedule_Inv",
    "quarterly-report": "Quarterly_Report", "nav-statement": "NAV_Statement",
    "fee_report": "Fee_Report", "institutional_report": "Institutional_Report", "valuation": "Valuation",
    "PCAP": "PCAP", "PPM": "PPM", "Stewardship_Proxy_Report": "Stewardship_Proxy_Report",
    "cash_flow_notice": "Cash_Flow_Notice", "ddq": "DDQ", "foundations_annual": "Foundations_Annual",
    "lpa": "LPA", "side_letter": "Side_Letter", "subscription": "Subscription",
}

PURPOSES = {
    "archive": "Content-addressed copies of governed pipeline inputs and replaced outputs.",
    "config": "Versioned schemas, completion settings, fixture settings, and quality tolerances.",
    "data": "Source material, extracted facts, integrated outputs, market inputs, fixtures, and databases.",
    "data/csv": "Final fund tables a reviewer can open, financial checks, and analytical results.",
    "data/demo": "A two-fund walkthrough with one clean record and one planted-error record.",
    "data/documents": "Local PDF sources plus page text, 300 DPI pictures required for extraction, and document grids.",
    "data/documents/pdf": "The 442 public and FOIA source PDFs listed in data-gathering/source_ledger.csv.",
    "data/documents/txt": "Page-aligned text derived from the source PDFs for search and quotation.",
    "data/documents/images": "300 DPI page pictures required for extraction. Git tracks the manifest. PNG files stay local because they are large.",
    "data/documents/grids": "Word-position grids for the reports that were read.",
    "data/extracted": "Published source observations, page coverage, route consolidations, and relational tables.",
    "data/extracted/fund-level": "Immutable source-backed fund tables frozen before augmentation.",
    "data/integrated": "Gap, cell-lineage, reconciliation, benchmark-policy, and defect evidence for same-fund completion.",
    "data/extracted/audit": "Source checks, withheld cells, inheritance candidates, and changed fund-model cells.",
    "data/normalization": "Fund, manager, LP, plan, and company name decisions, fund-constant attributes, and open review queues retained.",
    "data/normalization/worksheets": "Human review slices used to reach fund and manager identity decisions and remaining attribute spelling splits.",
    "data/extracted/review": "Flattened reviewer observations, final fund periods, gap ledger, cell lineage, and document summaries.",
    "data/extracted/raw": "Byte-preserving route mirrors used to verify adjudicated finals.",
    "data/extracted/rounds": "Route records and physical-page coverage produced by publication gates.",
    "data/extracted/tables": "Relational dimensions and facts built from adjudicated observations.",
    "data/extracted/wide": "One modelling table per record family: a printed table row per row, a vocabulary name per column (the family's usual names, then any other name the facts carry in it), every cell traceable to fact_observation.",
    "data/public_markets": "Market and macro data selected for PME benchmarks and research extensions.",
    "data/public_markets/audit": "Run receipts, the file inventory, the series-family summary, and market-data quality results.",
    "data/public_markets/sources": "The retained Parquet inputs, hash-checked and read by curate_public_markets as the stage's source.",
    "data/public_markets/staging": "Candidate benchmark levels, returns, identifiers, and strategy mappings.",
    "data/schemas": "Document routing, the 17 record families, the vocabulary of 89 metric and 30 term names, and the family surveys that define the field list.",
    "data/schemas/schema-discovery": "Per-document-family evidence for extraction fields; one folder per family surveyed.",
    "data/schemas/schema-discovery/financials": "Field survey of the Financials family: audited statements of assets, liabilities, operations, and partners' capital.",
    "data/schemas/schema-discovery/performance": "Field survey of the Performance family: fund-by-fund return and multiple tables published by pensions and general partners.",
    "data/schemas/schema-discovery/schedule-inv": "Field survey of the Schedule_Inv family: schedules of investments listing each portfolio holding with cost and fair value.",
    "data/schemas/schema-discovery/quarterly-report": "Field survey of the Quarterly_Report family: periodic partner reports carrying performance, economics, and portfolio sections.",
    "data/schemas/schema-discovery/nav-statement": "Field survey of the NAV_Statement family: net asset value statements and their roll-forward lines.",
    "data/schemas/schema-discovery/institutional-fee-valuation": "Field survey of three families read together: Institutional_Report, Fee_Report, and Valuation.",
    "data/schemas/schema-discovery/pcap-ppm-stewardship": "Field survey of three families read together: PCAP capital accounts, PPM offering terms, and Stewardship_Proxy_Report.",
    "data/schemas/schema-discovery/small-categories": "Field survey of the six low-population families: Cash_Flow_Notice, DDQ, Foundations_Annual, LPA, Side_Letter, and Subscription.",
    "data/synthetic": "Standalone generated regression fixtures that stay out of fund-model data.",
    "data/synthetic/clean": "Financially reconciled mock funds and their quality results.",
    "data/synthetic/defects": "A matched mock population carrying declared errors for detection tests.",
    "data/synthetic/analytics": "Fund metrics, PME results, and bounded portfolio allocations from the mock population.",
    "data/warehouse": "Document evidence, final integrated fund-model data, and standalone fixture DuckDB files.",
    "data-gathering": "The source ledger, acquisition contract, and corpus recovery tools.",
    "data-gathering/src": "Download, hash, PDF-probe, merge, and page-render utilities.",
    "docs": "Architecture, data model, status, and analytical method guides.",
    "instructions": "Operator runbooks for extraction, identity, same-fund completion, quality, analytics, and review.",
    "instructions/02-fund-mapping": "Fund-name normalization, independent manager-research, and fund-constant attribute copy.",
    "instructions/03-synthetic-qc": "Same-fund completion and financial-quality operating guide.",
    "instructions/04-analytics": "Performance, PME, and portfolio-analysis operating guide.",
    "instructions/01-pdf-extraction-csv": "Page pictures first. Then two machines type each page, comparison, the third reader, and publication. Field list below.",
    "instructions/01-pdf-extraction-csv/dispatch-prompts": "Generated role briefs grouped by source-report route.",
    "instructions/02-fund-mapping/dispatch-prompts": "Generated identity and fund-constant-attribute prompts, one per worksheet; kept after the slice is settled.",
    "instructions/02-fund-mapping/dispatch-prompts/attributes": "Standing generated brief for fund-constant attribute spelling splits; kept after the worksheet is header-only.",
    "instructions/02-fund-mapping/dispatch-prompts/normalize": "Standing generated briefs for fund-name worksheets; kept after each slice is settled.",
    "instructions/02-fund-mapping/dispatch-prompts/web-manager": "Standing generated briefs for blind manager-search worksheets; kept after each slice is settled.",
    "instructions/02-fund-mapping/dispatch-prompts/adjudicate": "Standing generated briefs for manager-adjudication worksheets; kept after each slice is settled.",
    "instructions/01-pdf-extraction-csv/worklists": "Source assignments split into active, deferred, and reference scopes.",
    "instructions/01-pdf-extraction-csv/worklists/active": "The documents carried through the published extraction rounds.",
    "instructions/01-pdf-extraction-csv/worklists/deferred": "Catalogued documents selected for later extraction.",
    "instructions/01-pdf-extraction-csv/worklists/reference": "Documents used as field or method references.",
    "ledgers": "Classification decisions, schema evidence, promotion contracts, and extraction audit trails. Folders here carry no number because they are not a sequence: each holds the evidence of one workflow.",
    "ledgers/doc-type": "Blind document-type classifications and their adjudicated result.",
    "ledgers/promotion-gate": "The header contracts validate_round02_promotion.py enforces and the acceptance evidence it reads, one batch per extraction route.",
    "costs": "Extraction cost measurement and the corpus estimate derived from it.",
    "audit": "The closed metric and term vocabulary notes, and published rows whose category disagrees with the printed label.",
    "audit/metric-vocabulary": "The closed metric and term vocabulary notes, and published rows whose category disagrees with the printed label.",
    "ledgers/promotion-gate/round02": "Which documents were accepted for promotion into the fund-level tables, written from the published extraction ledger by promote_extracted_to_fund_level; one batch folder per extraction route.",
    "ledgers/analysis": "Field inventories, schema surveys, manager evidence, and calibration candidates.",
    "ledgers/pipeline": "Append-only transformation receipts linking every governed input and output hash.",
    "ledgers/working": "Document-level evidence produced by the active CSV extraction runtime.",
    "ledgers/working/pdf-extraction-csv": "Blind A and B records, comparison files, resolutions, and finals, one folder per published source.",
    "sql": "Database definitions used by local analytical stores.",
    "sql/duckdb": "Table definitions for extracted.duckdb (03 star, 04 wide) and alts.duckdb (02 fund model).",
    "src": "Python code for acquisition support, extraction controls, identity, loading, checks, and analysis.",
    "src/analytics": "Private-market performance, PME, and portfolio calculations.",
    "src/catalog": "Corpus text preparation, field census, repair, and extraction routing support.",
    "src/catalog/simple_pdf_extraction": "The active 42-column field list, prompt builder, validator, and publisher.",
    "src/common": "Shared financial mathematics.",
    "src/dashboard": "The reviewer dashboard: one HTML file rendered from the published artifacts.",
    "src/flatten": "Wide extraction records converted into relational facts and dimensions.",
    "src/generate": "Seeded synthetic fund generation with declared assumptions and planted errors.",
    "src/load": "CSV-to-DuckDB loading.",
    "src/market_data": "Public-market source curation and benchmark construction.",
    "src/pipeline": "End-to-end extraction, completion, release, and reviewer gates.",
    "src/quality": "Financial identity, cash-flow, multiple, NAV, IRR, and date checks.",
    "src/repository": "Folder-guide, project-manifest, and structure-verification tools.",
    "tests": "Tests over acquisition, extraction, identity, promotion, fill, quality, analytics, origin records, parity, editorial prose, the reviewer dashboard, and repository structure; run with python -m pytest -q.",
}

TITLES = {
    "data": "Data layers",
    "data/documents/txt": "Page-aligned text",
    "data/documents/pdf": "Source PDFs",
    "data/documents/grids": "Positional grids",
    "data/documents/images": "Page images",
    "data/schemas/schema-discovery": "Schema discovery",
    "data/schemas/schema-discovery/small-categories": "Small families",
    "data/schemas/schema-discovery/institutional-fee-valuation": "Institutional, fee, and valuation families",
    "data/schemas/schema-discovery/pcap-ppm-stewardship": "PCAP, PPM, and stewardship families",
    "data/csv": "Fund-model CSV tables",
    "data/schemas": "Extraction schemas",
    "data-gathering": "Source acquisition",
    "docs": "Project documentation",
    "instructions": "Operator instructions",
    "instructions/01-pdf-extraction-csv": "PDF reading and page-picture decisions",
    "ledgers": "Decision and evidence ledgers",
    "ledgers/doc-type": "Document-type classification",
    "ledgers/promotion-gate": "Promotion gate contracts",
    "ledgers/working/pdf-extraction-csv": "Document extraction evidence",
    "instructions/02-fund-mapping": "Identity, manager research, and fund-constant attributes",
    "instructions/03-synthetic-qc": "Completion and quality",
    "instructions/04-analytics": "Performance and portfolio analytics",
    "sql/duckdb": "DuckDB schemas",
    "src": "Runtime code",
    "src/catalog/simple_pdf_extraction": "PDF reading code",
    "tests": "Runtime and field-list tests",
}

PYTHON_ROLES = {
    "build_txt_corpus.py": "Build page-aligned text from every ledgered PDF.",
    "census_field_labels.py": "Count recurring source labels used during schema design.",
    "repair_split_numbers.py": "Repair source-text numbers split across extraction tokens.",
    "sweep_manager_loci.py": "Collect manager-name evidence from source text.",
    "build_csv_pipeline.py": "Generate worklists, role briefs, and route field lists from schema inputs.",
    "build_page_grids.py": "Build positional word grids for selected source documents.",
    "csv_wide_contract.py": "The field list: 42 record columns, 17 record families with their grain and kind, document-type routing, and the one vocabulary of 89 metric and 30 term names with definitions.",
    "csv_workflow.py": "Validate candidates, compare reading groups, build finals, and publish routes.",
    "field_guide.py": "Render allowed field guidance from the route field list.",
    "name_normalization.py": "Collect and standardize fund and manager identities.",
    "fund_attributes.py": "Collect fund constants, decide printed values, and write inheritance and changed-cell evidence for promotion.",
    "page_grid.py": "Convert PDF word coordinates into row and column word maps.",
    "finance.py": "Calculate XNPV and XIRR with dated cash flows.",
    "flatten_extracted.py": "Convert published wide observations into relational tables.",
    "pivot_wide.py": "Pivot fact_observation into one wide table per record family, with the bridge back to every observation and the DDL it loads under.",
    "load_star.py": "Build the document DuckDB under a temporary name and publish it after full CSV parity.",
    "generate_synthetic_funds.py": "Generate seeded fund data and declared defect variants.",
    "load_csv_to_duckdb.py": "Build the fund-model DuckDB under a temporary name and publish it after full CSV parity.",
    "promote_extracted_to_fund_level.py": "Map adjudicated observations into the fund-level tables and write the acceptance evidence the promotion gate reads.",
    "run_extracted_analytics.py": "Publish DPI, RVPI, and TVPI for the extracted periods that print paid-in, distributions, and NAV.",
    "run_integrated_analytics.py": "Run metrics, PME, and allocation on the filled fund-date table.",
    "validate_round02_promotion.py": "Block fund-model loading when extracted or market rows lack governed promotion lineage.",
    "curate_public_markets.py": "Select, hash, validate, and stage public-market benchmark data.",
    "build_calibration_candidates.py": "Derive inactive source-backed calibration candidates.",
    "build_extracted_database.py": "Build extracted relational CSVs and DuckDB.",
    "build_mock_universe.py": "Run mock generation, checks, analytics, warehouse loading, and manifests.",
    "combine_extracted_raw.py": "Tie route outputs to the published observation file.",
    "build_extraction_review.py": "Join every observation to A/B pairing and adjudication evidence.",
    "build_integrated_universe.py": "Freeze extracted fund tables, complete gaps on the same fund IDs, and write lineage and defect evidence.",
    "build_reviewer_publication.py": "Build flattened reviewer observations, fund periods, analytics summary, gaps, and cell lineage.",
    "publish_review_release.py": "Run the governed review release in order and receipt every output.",
    "transformation_lineage.py": "Archive artifact bytes and append input-to-output transformation receipts.",
    "reviewer_check.py": "Verify reviewer counts, row preservation, analytical lineage, closed identity classifications, and benchmark restrictions.",
    "run_fund_checks.py": "Apply financial, identity, date, and lineage rules.",
    "run_round04_analytics.py": "Calculate performance multiples, IRR, PME, and allocations.",
    "build_readmes.py": "Write this project-wide set of folder guides.",
    "release_audit.py": "Open every project file with a check for its type, then verify the manifest, folder guides, Git policy, source ledger, landing-page text, and the committed dashboard page.",
    "test_release_presentation.py": "Every folder has a guide, the landing documents state the data boundary in timeless words, the review tables cover every fact, and the manifest covers every tracked file.",
    "build_dashboard.py": "Read the published files and write dashboard.html, one page a reviewer opens from disk.",
    "page.py": "The dashboard shell: style, browser code, and the block kinds the builder emits.",
    # tests, one line each on what the file actually guards
    "test_acquisition_contract.py": "Acquisition routes share one PDF cache, the document-type list derives from the ledger, and a dry run never touches the network.",
    "test_analytics.py": "Fund metrics recompute their components, PME uses the latest prior benchmark date and rejects a missing one, and allocations stay bounded.",
    "test_integrated_universe.py": "The integrated fund ID list, extracted-row keep, financial identities, analytics, and defect detection.",
    "test_calibration_candidates.py": "The calibration builder yields four inactive source-backed statistics and rejects unpaired metric panels.",
    "test_csv_wide_contract.py": "The generated field list verifies, routing is complete and unique, dispatch scopes never overlap, every route has its prompts, and one vocabulary serves every family of its kind.",
    "test_editorial_prose.py": "Every Markdown file follows the house editorial rules: declarative heads, affirmative phrasing, plain vocabulary, no em dashes.",
    "test_dashboard.py": "The dashboard opens with no network, renders the same bytes from the same tree, carries the counts its source files carry, and cites a path a reader can open.",
    "test_csv_wide_workflow.py": "Validator refusals (null values, bad quotes, shifted widths, drifted occurrences) and the matching-pair path to a final file.",
    "test_flatten_extracted.py": "Printed numbers keep their magnitude, percents stay percents, parentheses mean negative, ambiguous dates stay unparsed, and nothing is dropped.",
    "test_pivot_wide.py": "Every observation maps to one wide row, every usual and observed vocabulary name of a family is a column, the wide DDL is the one the module renders, and the set loads under its foreign keys.",
    "test_generator.py": "Generation gates, a clean universe with no quality failures, and every injected defect detected.",
    "test_mock_universe_pipeline.py": "Stage order and checks of the mock build, including its refusal to write the fund-model database.",
    "test_name_normalization_managers.py": "Family grouping, auto-settlement, merge integrity, negative-result propagation, coverage scope, and dispatch-prompt generation.",
    "test_fund_attributes.py": "Fund-attribute conflicts, audit-only apply behavior, evidence lookup, and changed-cell records.",
    "test_transformation_lineage.py": "Content-addressed archives, receipt deduplication, and distinct failed and passing attempts.",
    "test_database_parity.py": "Full-content CSV-to-DuckDB comparison and header drift detection.",
    "test_reviewer_publication.py": "Reviewer row coverage, enrichment evidence, and current transformation receipts.",
    "test_project_structure.py": "Every folder guide is current, the manifest has one hashless self row, and the live structure validates.",
    "test_promotion_gate.py": "Extracted rows need hash-linked dual-audit origin records to load; public-market rows follow their own rights check.",
    "test_prompt_contract_agreement.py": "Every generated prompt names only real columns, the families its route permits, and vocabulary names of the kinds those families fill.",
    "test_public_markets.py": "The copied source inventory matches disk, levels and returns reconcile, and the strategy map passes its gate.",
    "test_quality.py": "XIRR on dated flows, sign requirements, clean periods passing every applicable rule, and injected errors caught.",
    "test_reviewer_check.py": "The live reviewer baseline passes.",
    "test_extraction_review.py": "Every published observation appears once in the lineage table, and the agreement layers of document-summary.csv add up.",
    "test_promotion_to_fund_level.py": "Every promoted row names a fund and an accepted document, money reaches one scale, and the gate refuses a missing document.",
    "test_name_normalization_paths.py": "The identity commands, the WRITES registry, and the runbook output table name the same files.",
    "build_project_manifest.py": "Record each project file, folder, role, size, and repository policy.",
    "check_project_structure.py": "Verify folder guides, manifest coverage, hashes, and source ownership.",
    "_acquire_lib.py": "Download, identify, hash, and probe source PDFs.",
    "_merge_rows.py": "Validate reviewed acquisitions before extending the source ledger.",
    "fetch_corpus.py": "Restore ledgered PDFs and reject changed bytes.",
    "render_image_corpus.py": "Write one 300 DPI PNG per physical page. Extraction requires those files.",
    "workflow.py": "Command-line entry to csv_workflow: require-images, claim, validate-candidate, audit-file, compare, build-final, validate-final, status, and publish.",
    "entity_ids.py": "Mint one append-only ID per settled fund, manager, LP, plan, and company standard.",
    "__init__.py": "Package marker so Python can import the modules in this folder.",
}

FILE_ROLES = {
    "LICENSE": "Source-available licence: inspection and evaluation are free, commercial use of the work or any part of it requires a paid licence.",
    ".gitignore": "Future Git exclusions for local source caches, generated populations, databases, archives, and debris.",
    "requirements.txt": "Fully pinned Python environment for the retained pipeline.",
    "pytest.ini": "Test discovery and cache-exclusion settings.",
    "integrated_completion.yml": "Deterministic same-fund completion, benchmark, allocation, and rights-policy settings.",
    "gap-ledger.csv": "Every analytical gap filled by the completion stage and its resolution.",
    "cell-lineage.csv": "Source, formula, parameter, and precedence for every added fund-model cell or row.",
    "reconciliation-results.csv": "Identity, source-preservation, and financial-math checks for the integrated build.",
    "benchmark-policy.csv": "Benchmark identity, source span, demonstration limit, and production rights status.",
    "fixture-parameters.csv": "Header-only fixture input that triggers standalone assumed parameters.",
    "defect-periods.csv": "Isolated copies carrying declared errors; never loaded into the fund-model period table.",
    "defect-quality-results.csv": "Quality-rule results for the isolated damaged periods.",
    "source_ledger.csv": "Authoritative source ID, URL, report type, page count, and acquisition metadata.",
    "document-types.csv": "Controlled 17-value document-type list.",
    "document-types.md": "Document-family counts and visible field summary.",
    "01-NAME-NORMALIZER.md": "Copy-ready brief for one fund-name worksheet.",
    "05-ATTRIBUTE-NORMALIZER.md": "Copy-ready brief for remaining fund-constant attribute spelling splits.",
    "FIELD-SELECTION.csv": "One row per document type and record family: grain, category kind, required and allowed fields, and the family's usual vocabulary names.",
    "EXTRACTION-ROUTING.csv": "Document type to extraction route mapping.",
    "EXTRACTION-DISPATCH-SCOPE.csv": "Active, deferred, reference, and unscheduled source scope.",
    "EXTRACTION-DOC-TYPE-MAP.csv": "Ratified source-type crosswalk.",
    "EXTRACTION-METRIC-CATEGORIES.csv": "The vocabulary, one row per name: 89 metric and 30 term names with definition, unit hint, and usual family.",
    "METRIC-STANDARD-MEASURES.csv": "One row per published metric ID with a cross-document label, reported scope, and source note; joined into dim_metric.csv.",
    "RETURN-METHOD-BY-DOCUMENT.csv": "Method, fee basis, and supporting source text for each published return group, keyed by document, table, and column.",
    "EXTRACTION-RECORD-FAMILIES.csv": "The 17 record families: grain, category kind (metric, term, or context), fields, and usual vocabulary names.",
    "MASTER-EXTRACTION-SCHEMA.md": "Human field list for source observations.",
    "EXTRACTED-FIELDS.md": "Readable field-selection guide by source type.",
    "pdf-wide-records.csv": "Published 42-column source observations.",
    "pdf-wide-coverage.csv": "One record per covered physical PDF page.",
    "MANIFEST.csv": "Row counts and file membership for this generated stage.",
    "RUN-CLAIM.csv": "Model attribution for the route's two extractors and two adjudicators.",
    "records-a.csv": "Blind Extractor A observations.",
    "records-b.csv": "Blind Extractor B observations.",
    "coverage-a.csv": "Physical pages reviewed by Extractor A.",
    "coverage-b.csv": "Physical pages reviewed by Extractor B.",
    "pair-index.csv": "Paired agreements, disagreements, and one-sided candidate rows.",
    "coverage-diff.csv": "Page-level differences between the two extraction lanes.",
    "resolution.csv": "Adjudicator decisions for candidate pairs.",
    "coverage-resolution.csv": "Adjudicator decisions for page-coverage differences.",
    "records-final.csv": "Source-backed final observations for one document.",
    "coverage-final.csv": "Final physical-page coverage for one document.",
    "synthetic_parameter_candidates.csv": "Four inactive statistics from one LP schedule, retained as audit evidence and excluded from released parameters.",
    "quality_results.csv": "Rule-by-rule quality results.",
    "attribute-changes.csv": "Fund-model attribute cells with old value, new value, source observation, page, quote, and rule.",
    "reviewer-observations.csv": "One flattened row per printed fact with enrichment, lineage, QC, and analysis links.",
    "reviewer-fund-periods.csv": "One flattened row per fund period with attribute sources, QC, and recomputed metrics.",
    "reviewer-analytics-summary.csv": "Reviewer-ready distributions, analytical coverage, portfolio result, and strategy exposure.",
    "transformation-receipts.csv": "Append-only stage, command, input hash, predecessor, output hash, archive object, row count, and status records.",
    "detection_scorecard.csv": "Planted-error detection totals by defect family.",
    "defect_injections.csv": "Declared changes applied to the damaged mock population.",
    "fund_metrics.csv": "Calculated multiples and IRR, each carrying the source class of its input period.",
    "pme_results.csv": "PME results with benchmark, cash-flow, and input-period lineage.",
    "portfolio_allocations.csv": "Bounded portfolio weights and constraint results.",
    "source-lineage-audit.csv": "Machine-readable source hash and extraction-lineage findings.",
    "source-lineage-audit.md": "Readable source-lineage finding and repair record.",
    "model-ledger.csv": "Append-only model claims used to preserve extraction-lane attribution.",
    "model-scorecard.csv": "Regenerated candidate validity and coverage results grouped by model claim.",
    "market_data_runs.csv": "Curation receipt with source and destination paths and SHA-256.",
    "misfiled-rows.csv": "Published rows whose category disagrees with the printed label, with the adjudicator rule in the briefs.",
    "dim_document.csv": "One row per published source document with ratified type and source reference.",
    "dim_page.csv": "One row per reviewed physical PDF page.",
    "dim_entity.csv": "Standardized funds, managers, plans, LPs, benchmarks, and portfolio companies.",
    "entity_alias.csv": "Printed source names linked to standardized entities when a decision exists.",
    "dim_metric.csv": "One row per family and vocabulary name observed in the published slice, with its value kind, row count, standard measure, and measurement grain.",
    "fact_observation.csv": "One source observation with document, page, entity, metric, value, and evidence lineage.",
    "fact_holding.csv": "One source-reported holding linked to document, page, and entity where resolved.",
    "unresolved_names.csv": "Header-only identity exception guard; the current release contains zero rows.",
    "fund_master.csv": "Fund-level identity, manager, strategy, vintage, size, currency, and whether the row was extracted or generated.",
    "manager_master.csv": "Manager-level identity, and whether the row was extracted, derived, or generated.",
    "document_fund_map.csv": "Source-backed links between each document and every named fund.",
    "document-summary.csv": "One row per published document: what each extractor found, how the two compared, what the adjudicator decided, and how many rows were published.",
    "observation_lineage.csv": "Every published observation joined back to the pair it was settled under, the two candidate row numbers, and the adjudicator decision.",
    "build_extraction_review.py": "Report the layered A/B agreement per document and join every observation back to its adjudication.",
    "promotion-category-mismatches.csv": "Cells the promotion left out because the printed value and its category disagree; the handoff for an adjudicator-instruction fix, never a licence to edit an adjudicated file.",
    "progress.csv": "One row per accepted promotion batch, naming the extraction route and how many documents it carries.",
    "assignment.json": "The batch ID and the documents the gate accepted, each with its file ID and source hash.",
    "worksheet.csv": "The accept decision for each document in the batch, with the hash and row count of its adjudicated final file.",
    "document_manager_map.csv": "Source-backed links between each document and every named manager.",
    "document_entity_context.csv": "Fund, manager, LP, share-class, and perspective context used during extraction.",
    "entity_registry.csv": "Stable standardized entity identifiers by entity kind.",
    "fund_observations.csv": "Long-form fund facts preserving metric, date role, grain, value, and evidence.",
    "manager_observations.csv": "Long-form manager facts kept separate from fund facts.",
    "fund_cashflows.csv": "Dated calls, distributions, fees, subscriptions, and other cash-flow events.",
    "fund_periods.csv": "Fund or position snapshots for capital, NAV, multiples, IRR, and NAV rollforward.",
    "fund_terms.csv": "Numeric fund, LP, and share-class economic terms with effective dates.",
    "fund_term_clauses.csv": "Source wording for governance, risk, transfer, and other nonnumeric provisions.",
    "fund_holdings.csv": "Portfolio-company and instrument positions with date, cost, value, and source of the row.",
    "benchmark_returns.csv": "Dated benchmark returns, each naming its source file and parameter set.",
    "fund-names-matrix.csv": "Printed fund names, standardized names, fund families, stable IDs, and decisions.",
    "manager-names-matrix.csv": "Printed manager names, standards, stable IDs, and decisions.",
    "lp-names-matrix.csv": "Printed LP names, standards, stable IDs, and decisions.",
    "plan-names-matrix.csv": "Printed institutional-plan names, standards, stable IDs, and decisions.",
    "company-names-matrix.csv": "Printed portfolio-company names, standards, stable IDs, and decisions.",
    "entity-ids.csv": "Append-only standardized identity registry.",
    "manager-queue.csv": "Blind manager-research work and final decisions by sponsor family.",
    "web-manager-names.csv": "Final fund-to-manager research result with cited public sources.",
    "web-manager-names-matrix.csv": "Standardized manager identities derived from the research round.",
    "attribute-conflicts.csv": "Funds whose remaining printed labels still disagree after hyphen and Investments-suffix collapse.",
    "attribute-inherit.csv": "Observation cells whose printed context is blank and whose fund has a settled attribute the inherit log would copy.",
    "name-near-duplicates.csv": "Similar printed identities retained for human review.",
    "standard-conflicts.csv": "Normalization keys that map to more than one proposed standard.",
    "synthetic_parameters.csv": "Completion parameters: three medians derived from extracted periods and the declared configuration values, each with its origin class.",
    # data/warehouse
    "extracted.duckdb": "The document-level star schema from data/extracted/tables: 29 documents, 998 entities, 7,201 observations.",
    "alts_mock.duckdb": "The 800-fund synthetic population, its quality results, and its analytics; every row SYNTHETIC.",
    # ledgers/analysis
    "derived_manager_ledger.csv": "109 funds whose manager was derived from the fund-name brand; the origin of the DERIVED rows in manager_master.csv.",
    "document_field_inventory.csv": "One row per catalogued file (537) with routing, parser route, type, tier, issuer, default perspective, and multi-fund flag from the schema survey.",
    "document_type_field_schema.csv": "One row per document type of the pre-ratification survey taxonomy (18) stating typical grain, default perspective, fund-name rule, provided fields, and downstream use; the ratified 17-value list is data-gathering/document-types.csv.",
    "field_label_census.csv": "52 recurring printed field labels with corpus share, occurrence count, and top document types, used to choose extraction fields.",
    "manager_locus_sweep.csv": "276 candidate manager mentions found by pattern in source text, with page and quote, gathered to seed manager mapping.",
    "report_subtype_schema.csv": "26 report subtypes with typical grain and extraction contract from the earlier survey.",
    "round1_family_survey_fields.csv": "392 field observations by document family: where printed, best channel, grain, prevalence, and TXT readability.",
    "split_number_audit.csv": "57 documents whose TXT rendering split numbers across tokens, with damaged and repaired page counts.",
    # ledgers/doc-type
    "doc-type-audit.csv": "442 documents with both agents' type and reason and the adjudicated final type.",
    # data/public_markets/audit and staging
    "source_family_summary.csv": "19 series families in the retained store with file, byte, and row counts, analysis tier, PME role, source system, and rights status.",
    "source_file_inventory.csv": "334 retained Parquet files with tier, family, PME role, rights status, and producer.",
    "benchmark_level_candidates.csv": "279,269 daily adjusted-price levels for the 58 candidate benchmarks, each naming its source file and record status.",
    "benchmark_master_candidates.csv": "58 candidate benchmarks: ticker, instrument, asset class, geography, currency, provider, and date range.",
    "benchmark_return_candidates.csv": "279,211 daily simple returns derived from the levels, each naming its start and end level IDs and formula.",
    "benchmark_strategy_map_candidates.csv": "19 pre-committed strategy-to-benchmark assignments with primary or sensitivity role.",
    # instructions/01-pdf-extraction-csv: header-only by design, one per file the
    # workflow writes. build_csv_pipeline.py generates them from the contract and
    # tests/test_csv_wide_contract.py fails if a header drifts from it.
    "CSV-TEMPLATE.csv": "The 42 record columns, in order: the header every records-a, records-b, and records-final file must carry.",
    "COVERAGE-TEMPLATE.csv": "The 15 coverage columns: the header every coverage-a, coverage-b, and coverage-final file must carry.",
    "RESOLUTION-TEMPLATE.csv": "The 45 third-reader columns: a decision and reason ahead of the 42 record columns the third reader picks.",
    "COVERAGE-RESOLUTION-TEMPLATE.csv": "The four columns a third reader writes to decide a page whose two coverage rows disagree.",
    "BATCH-WORKLIST-TEMPLATE.csv": "The 16 worklist columns: what a route assignment names about each source and its page text, pictures, and word maps.",
    # ledgers/promotion-gate: the three headers the promotion gate enforces
    "adjudication_template.csv": "Header validate_round02_promotion.py requires of every round-02 adjudicated file before a row may enter the fund-level tables.",
    "INITIAL-COST-ESTIMATE.md": "Corpus extraction estimate, the two-term cost law, the per-document-type matrix, and the batch condition.",
    "audit_template.csv": "Header the gate requires of the date and schema audit files that must accompany an adjudication.",
    "audit_adjudication_template.csv": "Header the gate requires of the audit adjudication that settles the two audits and carries the promotion decision.",
    # docs
    "ARCHITECTURE.md": "How source evidence, decisions, data products, and analysis are kept apart, with the ownership rule for each layer.",
    "DATA-MODEL.md": "The fund-level entity-relationship model and the financial identities the checks enforce.",
    "STATUS.md": "Live check table: what passes, what is open, and what awaits operator review.",
    "PUBLIC-MARKET-DATA.md": "Benchmark selection, the prior-close alignment rule, the PME method, and the rights boundary.",
    "SYNTHETIC-DATA-AND-QUALITY.md": "Extraction checks, financial checks, retained discrepancies, and planted-error results.",
    "PROJECT-MANIFEST.csv": "Every local file and folder with size, repository policy, owning guide, and role; regenerated by build_project_manifest.",
    "CSV-LINEAGE.csv": "Every CSV with the CSV it was built from, the Python module that built it, the agent operation where a model wrote the rows, and that operation's brief.",
    "PROCESS.md": "The whole pipeline in numbered steps, one or two sentences each, every location named.",
    "FINAL-RELEASE-AUDIT.md": "Current release result, reviewer path, analytical findings, and disclosed boundaries.",
    "FINAL-RELEASE-AUDIT.csv": "One reproducible audit row per stage or closing check.",
    "disagreement-fields.csv": "How often the two extractors differed on each field, by conflict kind, with the number of documents the difference appeared in.",
    "observation-lineage.csv": "One row per published observation naming the A row, B row, pair, decision, and final row it came from, with the file paths and row numbers a reviewer opens.",
    "trace-sample.csv": "A sample of observation trails carrying subject, dates, value, unit, source coordinates, quote, and A/B and adjudication lineage.",
    "reviewer-queries.sql": "DuckDB queries for the extracted database: inventory, observations by document, entity coverage, metric coverage, observation lookup, and pivot-to-observation tracing.",
    "reviewer-cell-lineage.csv": "Every cell the completion wrote, with its label, source, formula, or parameter, flattened for review.",
    "reviewer-gap-ledger.csv": "Every blank the completion filled, with the value before, the value after, and how the fill was decided.",
    "dashboard.html": "The reviewer dashboard as last built: a static picture of the data, opened from disk with no server. Rebuild with open-dashboard.cmd after any data change.",
    "open-dashboard.cmd": "Double-click to build the dashboard and open it; falls back to the last built page where no Python is found.",
    "open-dashboard.ps1": "The PowerShell behind open-dashboard.cmd.",
    # instructions
    "REVIEWER-GUIDE.md": "Review files by area, the observation origin-record layers, and the release checks with their results.",
    "PIPELINE-VISUAL-GUIDE.md": "Execution flowchart of the live stages and the relational model of both databases.",
    "00-OPERATOR-RUNBOOK.md": "The operator's command sequence for this stage, with its checks and rerun rules.",
    "02-WEB-MANAGER-A.md": "Blind web-search brief A: name each fund's general partner from a public source.",
    "03-WEB-MANAGER-B.md": "Blind web-search brief B, independent of A.",
    "04-WEB-MANAGER-ADJUDICATOR.md": "Adjudicator brief: settle A and B manager disagreements from sources.",
    # config
    "fund_level_schema.yml": "The fund and manager database contract with its identity, grain, and source-tracking rules.",
    "quality_rules.yml": "The 23 recomputed financial checks with their tolerances: money 1.00, multiple 0.005, rate 0.0005.",
    "synthetic_generation.yml": "Seed, gates, fund target, and the identity and defect rules the mock generator runs under.",
    # sql/duckdb
    "02_fund_level_ddl.sql": "The 18 fund-model tables and three views of alts.duckdb, loaded by load_csv_to_duckdb.",
    "03_extracted_star_ddl.sql": "The star schema for data/extracted/tables, with CHECK constraints from the field-list enums, every join declared as a foreign key, and the scaled, resolved, and coverage views; loads extracted.duckdb.",
    "04_extracted_wide_ddl.sql": "Generated by pivot_wide from the field list: one wide table per record family plus bridge_pivot_observation; loads after 03.",
    "bridge_pivot_observation.csv": "One row per (pivot row, observation) for the wide tables and fact_holding, with a foreign key to fact_observation.",
    "EXTRACTED-DATA-MODEL.md": "The tables, grains, and keys of extracted.duckdb, the wide layer, the fund tables, and the reviewer files.",
    "REPOSITORY-BOUNDARY.md": "Files Git tracks.",
    "fund-attributes-matrix.csv": "One row per extracted fund with printed vintage, strategy, asset class, and geography, and whether each value is unique, spelling-collapsed, conflicting, decided, or unprinted.",
}

# Names inside a generated prompt folder, mapped to the role that file plays.
PROMPT_ROLES = {
    "01-EXTRACTOR-A.md": "Extractor A, on its own file: reads the route's documents through TXT, grid, and page image, writes records-a.csv and coverage-a.csv, and runs validate-candidate and audit-file per document.",
    "02-EXTRACTOR-B.md": "Extractor B: the same brief as A, differing in reading-group name and output paths only, so the two reading groups are comparable.",
    "03-ADJUDICATOR-J1.md": "Third reader for odd work orders: repairs pairing and number-format errors, runs compare, picks every pair against the page image, and builds the final file.",
    "04-ADJUDICATOR-J2.md": "Third reader for even work orders: the same brief as J1 on the other half of the route.",
}


def relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix() or "."


def project_directories() -> list[Path]:
    directories = [PROJECT_ROOT]
    directories.extend(
        path
        for path in PROJECT_ROOT.rglob("*")
        if path.is_dir()
        and not any(part in SKIP_DIRS for part in path.relative_to(PROJECT_ROOT).parts)
        and not relative(path).startswith("audit/diagnostics")
    )
    return sorted(directories, key=lambda path: relative(path).casefold())


def humanize(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def purpose_for(rel: str) -> str:
    if rel in PURPOSES:
        return PURPOSES[rel]
    parts = rel.split("/")
    if "schema-discovery" in parts:
        directory = PROJECT_ROOT / rel
        if any(directory.glob("*.field-ledger.csv")):
            family = FAMILY_FOLDERS.get(parts[-1], humanize(parts[-1]))
            return f"Field survey of the {family} family: file ledger, field ledger, source-backed sample, and schema note."
        families = ", ".join(
            FAMILY_FOLDERS.get(child.name, humanize(child.name))
            for child in sorted(directory.iterdir(), key=lambda item: item.name.casefold())
            if child.is_dir()
        )
        return f"One survey folder per family: {families}."
    if "dispatch-prompts" in parts and len(parts) >= 4:
        return f"Generated extractor and adjudicator briefs for route {parts[-1]}, one file per role; rebuilt by build_csv_pipeline."
    if rel.startswith("ledgers/working/pdf-extraction-csv/"):
        if parts[-1].startswith("SRC"):
            return f"Blind candidates, coverage, comparison, decisions, and final records for {parts[-1]}."
        return f"Extraction evidence for route {parts[-1]}: the model claim and one folder per document."
    if rel.startswith("ledgers/promotion-gate/round02/"):
        return f"Acceptance evidence for route {parts[-1]}: the documents the promotion gate admits, with source and final-file hashes."
    return f"Project files for {humanize(parts[-1])}."


# A CSV that carries a header and no rows is a claim about the pipeline, so the
# guide states which claim. Keys are matched as a path prefix, longest first.
EMPTY_REASONS = {
    "data/extracted/fund-level/fund_terms.csv": (
        "Header-only: the published legal documents name the governed fund only as the Fund, "
        "so a printed term attaches to no fund identity."
    ),
    "data/extracted/fund-level/fund_term_clauses.csv": (
        "Header-only for the same reason as fund_terms.csv: the clauses are extracted "
        "and readable, and the fund they govern is unnamed."
    ),
    "data/normalization/attribute-conflicts.csv": (
        "Header-only is the passing result of fund_attributes conflicts --strict."
    ),
    "data/normalization/worksheets/attribute-conflicts.csv": (
        "Header-only: every printed split is settled, and the standing brief stays."
    ),
    "data/synthetic/fixture-parameters.csv": (
        "Header-only by design: an empty parameter file makes the generator emit its 152 declared assumptions as rows."
    ),
    "data/documents/grids/": (
        "Header-only: MANIFEST.csv records why, either a scan with no text layer "
        "or a native-text document printing no numeric table."
    ),
    "data/extracted/wide/": (
        "Header-only: columns come from the contract, so the table exists on every "
        "corpus; the published rounds printed no row of this family."
    ),
    "data/normalization/standard-conflicts.csv": (
        "Header-only, and that is the passing result: a row would name a fund "
        "carrying two standardized names."
    ),
    "data/synthetic/clean/defect_injections.csv": (
        "Header-only by definition: the clean population carries no planted "
        "errors, and the 144 injections are in data/synthetic/defects/."
    ),
    "instructions/01-pdf-extraction-csv/worklists/reference/": (
        "Header-only: this route has no reference document."
    ),
    "instructions/01-pdf-extraction-csv/": (
        "Header-only by design: a template is its header."
    ),
    "ledgers/promotion-gate/": (
        "Header-only by design: the gate compares a working file's header against this one."
    ),
    "ledgers/working/pdf-extraction-csv/": (
        "Header-only: coverage-final.csv carries the adjudicated status of every page."
    ),
}


def empty_reason(rel: str) -> str:
    for prefix in sorted(EMPTY_REASONS, key=len, reverse=True):
        if rel == prefix or rel.startswith(prefix):
            return EMPTY_REASONS[prefix]
    return "Header-only."


def is_header_only(path: Path) -> bool:
    if path.suffix.lower() != ".csv":
        return False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            if not handle.readline():
                return False
            for line in handle:
                if line.strip():
                    return False
    except OSError:
        return False
    return True


def describe_file(path: Path) -> str:
    role = _describe_file(path)
    if is_header_only(path):
        return f"{role} {empty_reason(relative(path))}"
    return role


def _describe_file(path: Path) -> str:
    name = path.name
    if name == "README.md":
        return "Folder inventory: the files and subfolders in this directory, each with its role."
    rel = relative(path)
    suffix = path.suffix.lower()
    if rel.startswith("data/documents/pdf/") and suffix == ".pdf":
        return "Ledgered source report; source_ledger.csv supplies its file ID, type, URL, and page count."
    if rel.startswith("data/documents/txt/") and suffix == ".txt":
        return "Page-aligned text derived from the same-named source PDF."
    if rel == "data/documents/txt/MANIFEST.csv":
        return "One row per source PDF: pages read by pdfplumber, pages read by RapidOCR, empty pages, character count, seconds, and any error."
    if rel == "data/documents/grids/MANIFEST.csv":
        # Guarded before the folder rule below, which would otherwise describe
        # the manifest as one of the grids it indexes.
        return "One row per document the grid builder read, naming its text layer and what the grid recovered, including why a file produced no rows."
    if rel == "data/documents/images/MANIFEST.csv":
        return (
            "One row per physical page in the published extraction slice: source PDF hash, "
            "page number, 300 DPI path, image hash when the PNG is present, and present=0 until rendered."
        )
    if rel.startswith("data/documents/grids/") and suffix == ".csv":
        return "Physical-page word coordinates used to recover table rows and columns."
    if rel.startswith("data/public_markets/sources/") and suffix == ".parquet":
        return "Hash-checked market or alternative-data input described by the public-market audit inventory."
    if rel.startswith("instructions/01-pdf-extraction-csv/worklists/") and suffix == ".csv":
        return "Route assignment with source IDs, physical-page counts, and approved reading-aid paths."
    if rel.startswith("instructions/01-pdf-extraction-csv/dispatch-prompts/") and suffix == ".md":
        return PROMPT_ROLES.get(name, "Generated role brief bound to this route contract.")
    if name == "ATTRIBUTE-NORMALIZER-01.md":
        return "Standing pasteable brief for the fund-constant attribute worksheet; regenerated by fund_attributes dispatch, kept after the slice is settled."
    if rel.startswith("instructions/02-fund-mapping/dispatch-prompts/") and suffix == ".md":
        stem = path.stem
        if stem.startswith("NORMALIZER-"):
            return f"Standing brief for data/normalization/worksheets/fund-part-{stem.split('-')[-1]}.csv: one normalizer, 120 printed fund names."
        if stem.startswith("WEB-MANAGER-"):
            index, lane = stem.split("-")[-2:]
            return f"Standing brief for data/normalization/worksheets/manager-{index}-{lane.lower()}.csv: blind searcher {lane} names the general partner of each lookup with a public source."
    if rel.startswith("data/extracted/wide/") and path.name.startswith("wide_"):
        return "One printed table row per row, one vocabulary name per column, with the observation IDs each row was built from."
    if rel.startswith("data/extracted/raw/") and suffix == ".csv":
        return "Every adjudicated records-final.csv of this route concatenated in document order; 42 contract columns, nothing altered."
    if rel.startswith("data/normalization/worksheets/"):
        stem = path.stem
        if stem.startswith("fund-part-"):
            return "One normalizer's slice of fund-names-matrix.csv, rows sorted by printed name; folded back by `merge`."
        if stem == "attribute-conflicts":
            return "Funds whose remaining printed vintage, strategy, asset class, or geography labels still disagree; folded back by `fund_attributes merge`."
        if stem.startswith("manager-") and stem.endswith("-j"):
            return "One adjudicator's slice of manager-queue.csv with both searchers' answers; folded back by `manager-merge`."
        if stem.startswith("manager-"):
            return "One blind searcher's slice of manager-queue.csv, its own two columns only; folded back by `manager-merge`."
    if rel == "data/public_markets/audit/quality_results.csv":
        return "PMQ01 to PMQ10: population, keys, dates, levels, bounds, and return reconciliation, all PASS."
    if name in FILE_ROLES:
        return FILE_ROLES[name]
    if name in PYTHON_ROLES:
        return PYTHON_ROLES[name]
    lower = name.lower()
    if lower.endswith(".field-ledger.csv"):
        return "One row per visible source field with grain, location, prevalence, and mapping decision."
    if lower.endswith(".file-ledger.csv"):
        return "One row per reviewed source document with the pages read, the fields found, and the disposition."
    if lower.endswith(".sample.csv"):
        return "Source-backed sample rows that tested the field contract before it was frozen."
    if lower.endswith(".schema.md"):
        return "Schema note for the family: record grains, fields, and document prevalence from the ledger."
    if lower.endswith("-records.csv"):
        return "Published observations for one extraction route."
    if lower.endswith("-coverage.csv"):
        return "Published physical-page coverage for one extraction route."
    if lower.startswith("a-batch"):
        return "Agent A document-type classifications for one source slice."
    if lower.startswith("b-batch"):
        return "Agent B document-type classifications for one source slice."
    if suffix == ".py":
        # The module's own first docstring line, the same source the project
        # manifest reads. Restating the filename told a reader nothing and made
        # the folder guide disagree with the manifest for the same file.
        summary = python_docstring(path)
        return summary or f"Python module that implements {humanize(path.stem).lower()}."
    if suffix == ".csv":
        return f"Tabular records for {humanize(path.stem).lower()}."
    if suffix in {".yml", ".yaml"}:
        return f"Configuration for {humanize(path.stem).lower()}."
    if suffix == ".md":
        return f"Guide for {humanize(path.stem).lower()}."
    if suffix == ".sql":
        return "DuckDB schema or query definition."
    if suffix == ".duckdb":
        return "Local analytical database rebuilt from CSV inputs."
    if suffix == ".json":
        return f"Structured contract for {humanize(path.stem).lower()}."
    return f"Tracked file for {humanize(path.stem).lower()}."


def bulk_rows(directory: Path, files: list[Path]) -> list[tuple[str, str]]:
    counts = Counter(path.suffix.lower() or "[extensionless]" for path in files if path.name != "README.md")
    rows = [
        (f"`{path.name}`", describe_file(path))
        for path in sorted(files, key=lambda item: item.name.casefold())
        if path.name in {"MANIFEST.csv", "render-log.csv"}
    ]
    for suffix, count in sorted(counts.items()):
        label = f"`*{suffix}` ({count} files)" if suffix.startswith(".") else f"{suffix} ({count} files)"
        if suffix == ".csv":
            continue
        role = {
            ".pdf": "Source reports identified and hashed in data-gathering/source_ledger.csv.",
            ".txt": "Page-aligned source text regenerated from the PDF corpus.",
            ".parquet": "Market, macro, positioning, volatility, or alternative-data inputs listed in the audit inventory.",
        }.get(suffix, "Files of one controlled data type.")
        rows.append((label, role))
    return rows


def diagram_for(rel: str, files: list[Path], subdirs: list[Path]) -> str:
    if rel.startswith("ledgers/working/pdf-extraction-csv/") and rel.split("/")[-1].startswith("SRC"):
        return """```mermaid
sequenceDiagram
    participant S as Source PDF and page aids
    participant A as Extractor A
    participant B as Extractor B
    participant C as Pairing gate
    participant J as J1 or J2 adjudicator
    participant F as Final publisher
    S->>A: assigned pages, text, images, and grids
    S->>B: assigned pages, text, images, and grids
    A->>C: records-a.csv and coverage-a.csv
    B->>C: records-b.csv and coverage-b.csv
    C->>J: pair-index.csv and coverage-diff.csv
    J->>F: resolution.csv and coverage-resolution.csv
    F->>F: records-final.csv and coverage-final.csv
```"""
    if rel.startswith("instructions/02-fund-mapping/dispatch-prompts/attributes"):
        return """```mermaid
flowchart TD
    H["fund_attributes harvest"] --> E["export attribute-conflicts.csv"]
    E --> D["fund_attributes dispatch"]
    D --> P["ATTRIBUTE-NORMALIZER-01.md stays on disk"]
    P --> A["agent fills remaining splits"]
    A --> M["merge"]
    M --> G{"conflicts --strict clean?"}
    G -- no --> A
    G -- yes --> AP["apply"]
```"""
    if rel.startswith("instructions/01-pdf-extraction-csv/dispatch-prompts") and rel.count("/") >= 3:
        return """```mermaid
sequenceDiagram
    participant O as Operator
    participant A as Extractor A
    participant B as Extractor B
    participant J1 as Adjudicator J1
    participant J2 as Adjudicator J2
    O->>A: 01-EXTRACTOR-A.md
    O->>B: 02-EXTRACTOR-B.md
    A->>O: records-a.csv and coverage-a.csv
    B->>O: records-b.csv and coverage-b.csv
    O->>J1: 03-ADJUDICATOR-J1.md odd work orders
    O->>J2: 04-ADJUDICATOR-J2.md even work orders
    J1->>O: resolution rows
    J2->>O: resolution rows
```"""
    if rel == "data-gathering":
        return """```mermaid
flowchart TD
    U["Public source URLs"] --> A["data-gathering/src/_acquire_lib.py"]
    A --> G{"PDF signature, size, and page probe pass?"}
    G -- "review" --> U
    G -- "accepted" --> L["source_ledger.csv"]
    L --> F["fetch_corpus.py"]
    F --> P["data/documents/pdf"]
    P --> T["text, image, and grid preparation"]
```"""
    if rel == "data":
        return """```mermaid
flowchart TD
    D["documents"] --> E["extracted observations"]
    E --> N["normalization"]
    N --> W["warehouse"]
    S["schemas"] --> E
    P["public_markets"] --> A["analytics"]
    M["synthetic clean and defects"] --> A
    W --> A
    A --> G{"financial and source checks pass?"}
    G -- "repair" --> E
    G -- "pass" --> O["review outputs"]
```"""
    if rel == "data/documents":
        return """```mermaid
flowchart TD
    L["data-gathering/source_ledger.csv"] --> P["pdf: source bytes"]
    P --> T["txt: page-aligned text"]
    P --> I["images: 300 DPI PNG, required for extraction"]
    P --> G["grids: document grids"]
    I --> E["reading groups A and B"]
    T --> E
    G --> E
```"""
    if rel == "data/extracted":
        return """```mermaid
flowchart TD
    R["rounds/*-records.csv"] --> P["pdf-wide-records.csv"]
    C["rounds/*-coverage.csv"] --> V["pdf-wide-coverage.csv"]
    P --> G{"route totals and document keys reconcile?"}
    V --> G
    G -- "drift" --> R
    G -- "pass" --> T["tables/fact_observation.csv"]
    T --> D["data/warehouse/extracted.duckdb"]
```"""
    if rel == "data/synthetic":
        return """```mermaid
flowchart TD
    C["config/synthetic_generation.yml"] --> G["build_mock_universe clean"]
    G --> Q["clean/quality_results.csv"]
    Q --> P{"FAIL rows equal zero?"}
    P -- "repair" --> G
    P -- "pass" --> A["analytics"]
    G --> D["defects population"]
    D --> S["detection_scorecard.csv"]
    S --> K{"each planted family is detected?"}
    K -- "repair" --> G
    K -- "pass" --> M["MANIFEST.csv"]
```"""
    if rel == "data/public_markets":
        return """```mermaid
flowchart TD
    S["sources: 334 retained Parquet files"] --> C["curate_public_markets.py"]
    C --> I["audit/source_file_inventory.csv and source_family_summary.csv"]
    C --> Q["audit/quality_results.csv"]
    Q --> G{"PMQ01 through PMQ10 pass?"}
    G -- "review" --> C
    G -- "pass" --> B["staging benchmark levels and returns"]
    B --> P["PME calculations"]
```"""
    if rel == "instructions/01-pdf-extraction-csv":
        return """```mermaid
flowchart TD
    PDF["assigned PDF"] --> PNG["render_image_corpus.py: 300 DPI PNG per page"]
    PNG --> R["require-images"]
    S["data/schemas routing and field selection"] --> B["build_csv_pipeline build"]
    B --> W["worklists/active"]
    B --> P["dispatch-prompts"]
    R --> E["A and B each on its own file"]
    W --> E
    P --> E
    E --> V{"validate-candidate and audit-file pass?"}
    V -- "repair" --> E
    V -- "pass" --> J["split third reader"]
    J --> F["build-final, validate-final, publish"]
```"""
    if rel == "src":
        return """```mermaid
flowchart TD
    C["catalog"] --> F["flatten"]
    F --> L["load"]
    G["generate"] --> Q["quality"]
    L --> A["analytics"]
    M["market_data"] --> A
    Q --> A
    P["pipeline"] --> C
    P --> G
    P --> A
    R["repository"] --> V{"structure and manifest pass?"}
    V -- "refresh" --> R
    V -- "pass" --> P
```"""
    # A folder whose process is linear carries no diagram: its file table, read
    # top to bottom, is the sequence.
    return ""


def ordered_files(rel: str, files: list[Path]) -> list[Path]:
    """Files in process order where the folder defines one, then the rest by name."""

    names = {path.name: path for path in files}
    order: tuple[str, ...] = FOLDER_ORDER.get(rel, ())
    if rel.startswith("ledgers/working/pdf-extraction-csv/") and rel.split("/")[-1].startswith("SRC"):
        order = WORKING_DOCUMENT_ORDER
    elif "schema-discovery" in rel.split("/"):
        order = tuple(
            name for suffix in SCHEMA_DISCOVERY_ORDER for name in sorted(names) if name.endswith(suffix)
        )
    elif rel == "data/normalization/worksheets":
        order = (*order, *sorted(name for name in names if name.startswith("manager-")))
    ordered = [names[name] for name in order if name in names]
    rest = sorted((path for path in files if path.name not in order), key=lambda path: path.name.casefold())
    return [*ordered, *rest]


def title_for(directory: Path, rel: str) -> str:
    if rel in TITLES:
        return TITLES[rel]
    if rel.startswith("ledgers/working/pdf-extraction-csv/") and directory.name.startswith("SRC"):
        return f"{directory.name} extraction evidence"
    if "schema-discovery" in rel.split("/") and directory.name in FAMILY_FOLDERS:
        return f"{FAMILY_FOLDERS[directory.name]} field survey"
    if rel.startswith("ledgers/promotion-gate/round02/") or rel.startswith("ledgers/working/pdf-extraction-csv/"):
        return f"Route {directory.name}"
    if rel.startswith("instructions/01-pdf-extraction-csv/dispatch-prompts/"):
        return f"Route {directory.name} briefs"
    return directory.name if directory.name.isupper() else humanize(directory.name)


def render_readme(directory: Path) -> str:
    rel = relative(directory)
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() != ".pyc" and path.name != "README.md"
    ]
    subdirs = sorted(
        [path for path in directory.iterdir() if path.is_dir() and path.name not in SKIP_DIRS],
        key=lambda path: path.name.casefold(),
    )
    lines = [f"# {title_for(directory, rel)}", "", purpose_for(rel)]
    if rel in BULK_DIRS:
        rows = bulk_rows(directory, files)
    else:
        rows = [(f"`{path.name}`", describe_file(path)) for path in ordered_files(rel, files)]
    if rows:
        lines.extend(["", "| File | Role |", "|---|---|"])
        for name, role in rows:
            lines.append(f"| {name} | {role} |")
    if subdirs:
        lines.extend(["", "| Folder | Role |", "|---|---|"])
        for path in subdirs:
            lines.append(f"| `{path.name}/` | {purpose_for(relative(path))} |")
    diagram = diagram_for(rel, files, subdirs)
    if diagram:
        lines.extend(["", diagram])
    if rel in NEXT_READMES:
        target, label = NEXT_READMES[rel]
        lines.extend(["", f"Next: [{label}]({target})."])
    lines.append("")
    return "\n".join(lines)


def build(root: Path = PROJECT_ROOT) -> int:
    written = 0
    for directory in project_directories():
        if directory == root:
            continue
        if hand_written(directory):
            continue
        readme = directory / "README.md"
        content = render_readme(directory)
        if not readme.exists() or readme.read_text(encoding="utf-8-sig", errors="replace") != content:
            readme.write_text(content, encoding="utf-8", newline="\n")
            written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        drift = [
            relative(directory)
            for directory in project_directories()
            if directory != PROJECT_ROOT
            and not hand_written(directory)
            and (
                not (directory / "README.md").is_file()
                or (directory / "README.md").read_text(encoding="utf-8-sig", errors="replace")
                != render_readme(directory)
            )
        ]
        if drift:
            for rel in drift:
                print(f"DRIFT: {rel}/README.md")
            raise SystemExit(1)
        print(f"PASS: {len(project_directories())} directories carry current guides")
        return
    written = build()
    print(f"PASS: wrote or refreshed {written} folder guides")


if __name__ == "__main__":
    main()
