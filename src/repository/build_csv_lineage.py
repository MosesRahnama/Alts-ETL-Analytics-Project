"""Record where every CSV in the repository came from.

One row per CSV file, five columns: the file, the CSV it was built from, the
Python module that performed the transformation, the agent operation where a
model produced the rows, and the brief that governed that operation.

A stage that starts from something other than a CSV leaves `origin_csv` empty:
the PDF corpus, the parquet market files, the TXT pages, and the vocabularies
that live as Python constants all enter the pipeline that way. A stage that runs
as code alone leaves `agent_operation` and `instructions_file` empty.

    python -m src.repository.build_csv_lineage
    python -m src.repository.build_csv_lineage --check

Paths are repository-relative and use forward slashes, matching
docs/PROJECT-MANIFEST.csv.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
from pathlib import Path

from src.repository.build_project_manifest import paths as manifest_paths


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = PROJECT_ROOT / "docs" / "CSV-LINEAGE.csv"
SKIP_NAMES = {".git", ".pytest_cache", "__pycache__"}

COLUMNS = (
    "csv_path",
    "origin_csv",
    "python_file",
    "agent_operation",
    "instructions_file",
)

# Stage modules, named once so a rename shows up here rather than in 20 rules.
WORKFLOW = "src/catalog/simple_pdf_extraction/csv_workflow.py"
PIPELINE = "src/catalog/simple_pdf_extraction/build_csv_pipeline.py"
GRIDS = "src/catalog/simple_pdf_extraction/build_page_grids.py"
NAMES = "src/catalog/simple_pdf_extraction/name_normalization.py"
ATTRIBUTES = "src/catalog/simple_pdf_extraction/fund_attributes.py"
FLATTEN = "src/flatten/flatten_extracted.py"
WIDE = "src/flatten/pivot_wide.py"
PROMOTE = "src/load/promote_extracted_to_fund_level.py"
INTEGRATE = "src/pipeline/build_integrated_universe.py"
REVIEW = "src/pipeline/build_extraction_review.py"
PUBLICATION = "src/pipeline/build_reviewer_publication.py"
QUALITY = "src/quality/run_fund_checks.py"
MOCK = "src/pipeline/build_mock_universe.py"
GENERATE = "src/generate/generate_synthetic_funds.py"
ROUND04 = "src/analytics/run_round04_analytics.py"
MARKETS = "src/market_data/curate_public_markets.py"

# Extraction briefs, one set per route folder.
BRIEF_A = "instructions/01-pdf-extraction-csv/dispatch-prompts/{route}/01-EXTRACTOR-A.md"
BRIEF_B = "instructions/01-pdf-extraction-csv/dispatch-prompts/{route}/02-EXTRACTOR-B.md"
BRIEF_J = (
    "instructions/01-pdf-extraction-csv/dispatch-prompts/{route}/03-ADJUDICATOR-J1.md|"
    "instructions/01-pdf-extraction-csv/dispatch-prompts/{route}/04-ADJUDICATOR-J2.md"
)
NORMALIZER_BRIEF = "instructions/02-fund-mapping/01-NAME-NORMALIZER.md"
MANAGER_BRIEFS = (
    "instructions/02-fund-mapping/02-WEB-MANAGER-A.md|"
    "instructions/02-fund-mapping/03-WEB-MANAGER-B.md|"
    "instructions/02-fund-mapping/04-WEB-MANAGER-ADJUDICATOR.md"
)
ATTRIBUTE_BRIEF = "instructions/02-fund-mapping/05-ATTRIBUTE-NORMALIZER.md"

SOURCE_LEDGER = "data-gathering/source_ledger.csv"
DOC_TYPE_AUDIT = "ledgers/doc-type/doc-type-audit.csv"
TXT_MANIFEST = "data/documents/txt/MANIFEST.csv"
SCOPE = "data/schemas/EXTRACTION-DISPATCH-SCOPE.csv"
ROUTING = "data/schemas/EXTRACTION-ROUTING.csv"
FACTS = "data/extracted/tables/fact_observation.csv"
ROUNDS_GLOB = "data/extracted/rounds/*-records.csv"

# Fund-model tables that stage 95 freezes by copying data/csv into
# data/extracted/fund-level. Two files in that folder are written after the
# freeze and carry their own rules.
SNAPSHOT_FILES = {
    "fund_master.csv",
    "manager_master.csv",
    "document_fund_map.csv",
    "document_manager_map.csv",
    "fund_observations.csv",
    "manager_observations.csv",
    "fund_periods.csv",
    "fund_cashflows.csv",
    "fund_holdings.csv",
    "fund_terms.csv",
    "fund_term_clauses.csv",
}

# Fund-model tables the promotion stage writes from the evidence tables.
PROMOTED_FILES = {
    "fund_master.csv",
    "manager_master.csv",
    "document_manager_map.csv",
    "fund_observations.csv",
    "manager_observations.csv",
    "fund_periods.csv",
    "fund_cashflows.csv",
    "fund_holdings.csv",
    "fund_terms.csv",
    "fund_term_clauses.csv",
}

# Identity working files in data/csv that the fund-mapping round produced and
# the promotion stage reads. No module in this repository writes them.
CARRIED_IDENTITY = {
    "document_fund_map.csv",
    "document_entity_context.csv",
    "entity_registry.csv",
}

ANALYTICS_FILES = {"fund_metrics.csv", "pme_results.csv", "portfolio_allocations.csv"}

# Analysis ledgers a survey agent wrote, with the CSV each one read.
SURVEY_LEDGERS = {
    "document_field_inventory.csv": (SOURCE_LEDGER, "document schema survey"),
    "document_type_field_schema.csv": (SOURCE_LEDGER, "document schema survey"),
    "report_subtype_schema.csv": (SOURCE_LEDGER, "document schema survey"),
    "round1_family_survey_fields.csv": (TXT_MANIFEST, "round-1 family field survey"),
    "derived_manager_ledger.csv": ("data/csv/fund_master.csv", "manager derivation review"),
}

WORKING = re.compile(
    r"^ledgers/working/pdf-extraction-csv/(?P<route>[^/]+)/(?P<doc>SRC\d+)/(?P<name>[a-z-]+)\.csv$"
)
ROUND_FILE = re.compile(r"^data/extracted/rounds/(?P<route>.+)-(?P<kind>records|coverage)\.csv$")
SCHEMA_DISCOVERY = re.compile(r"^data/schemas/schema-discovery/.+\.csv$")


def relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def working_row(match: re.Match[str]) -> tuple[str, str, str, str]:
    """One document's ten working files, in the order the stages write them."""
    route, doc, name = match["route"], match["doc"], match["name"]
    folder = f"ledgers/working/pdf-extraction-csv/{route}/{doc}"
    worklist = f"instructions/01-pdf-extraction-csv/worklists/active/{route}.csv"
    if name in {"records-a", "coverage-a"}:
        return worklist, WORKFLOW, "blind extraction, agent A", BRIEF_A.format(route=route)
    if name in {"records-b", "coverage-b"}:
        return worklist, WORKFLOW, "blind extraction, agent B", BRIEF_B.format(route=route)
    if name == "pair-index":
        return f"{folder}/records-a.csv", WORKFLOW, "", ""
    if name == "coverage-diff":
        return f"{folder}/coverage-a.csv", WORKFLOW, "", ""
    if name == "resolution":
        return f"{folder}/pair-index.csv", WORKFLOW, "adjudication", BRIEF_J.format(route=route)
    if name == "coverage-resolution":
        return (
            f"{folder}/coverage-diff.csv",
            WORKFLOW,
            "coverage adjudication",
            BRIEF_J.format(route=route),
        )
    if name == "records-final":
        return f"{folder}/resolution.csv", WORKFLOW, "", ""
    if name == "coverage-final":
        return f"{folder}/coverage-resolution.csv", WORKFLOW, "", ""
    return "", WORKFLOW, "", ""


def resolve(rel: str) -> tuple[str, str, str, str]:
    """Return origin CSV, Python file, agent operation, and brief for one path."""
    name = rel.rsplit("/", 1)[-1]
    folder = rel.rsplit("/", 1)[0] if "/" in rel else ""

    match = WORKING.match(rel)
    if match:
        return working_row(match)

    # Acquisition and typing.
    if rel == SOURCE_LEDGER:
        return "", "data-gathering/src/_merge_rows.py", "corpus gathering", (
            "data-gathering/AGENT-A1-CORPUS-GATHERING.md"
        )
    if rel == "data-gathering/document-types.csv":
        return "", "", "document-type ratification", ""
    if folder == "ledgers/doc-type":
        if name == "doc-type-audit.csv":
            return "ledgers/doc-type/a-batch1.csv", "", "document-type adjudication", ""
        lane = "agent A" if name.startswith("a-") else "agent B"
        return SOURCE_LEDGER, "", f"blind document typing, {lane}", ""

    # Reading the corpus.
    if rel == TXT_MANIFEST:
        return SOURCE_LEDGER, "src/catalog/build_txt_corpus.py", "", ""
    if folder == "data/documents/grids":
        return SCOPE, GRIDS, "", ""

    # Survey and row format.
    if SCHEMA_DISCOVERY.match(rel):
        return TXT_MANIFEST, "", "document-family schema survey", ""
    if folder == "ledgers/analysis":
        if name in SURVEY_LEDGERS:
            origin, operation = SURVEY_LEDGERS[name]
            return origin, "", operation, ""
        if name == "field_label_census.csv":
            return TXT_MANIFEST, "src/catalog/census_field_labels.py", "", ""
        if name == "manager_locus_sweep.csv":
            return "data/csv/document_fund_map.csv", "src/catalog/sweep_manager_loci.py", "", ""
        if name == "split_number_audit.csv":
            return TXT_MANIFEST, "src/catalog/repair_split_numbers.py", "", ""
        if name == "synthetic_parameter_candidates.csv":
            return FACTS, "src/pipeline/build_calibration_candidates.py", "", ""
        if name == "model-ledger.csv":
            return (
                "ledgers/working/pdf-extraction-csv/01-financials/RUN-CLAIM.csv",
                WORKFLOW,
                "",
                "",
            )
    if rel == ROUTING:
        return SOURCE_LEDGER, PIPELINE, "", ""
    if rel == SCOPE:
        return ROUTING, PIPELINE, "", ""
    if rel == "data/schemas/METRIC-STANDARD-MEASURES.csv":
        return "", "", "metric vocabulary review", ""
    if rel == "data/schemas/RETURN-METHOD-BY-DOCUMENT.csv":
        return "", "", "return-method evidence review", ""
    if folder == "data/schemas":
        return "", PIPELINE, "", ""
    if rel.startswith("instructions/01-pdf-extraction-csv/worklists/"):
        return SCOPE, PIPELINE, "", ""
    if folder == "instructions/01-pdf-extraction-csv":
        return "", PIPELINE, "", ""
    if rel.endswith("/RUN-CLAIM.csv"):
        return SCOPE, WORKFLOW, "", ""

    # Publication of the adjudicated rounds.
    match = ROUND_FILE.match(rel)
    if match:
        route, kind = match["route"], match["kind"]
        source = "records-final.csv" if kind == "records" else "coverage-final.csv"
        return (
            f"ledgers/working/pdf-extraction-csv/{route}/SRC034/{source}"
            if route == "01-financials"
            else f"ledgers/working/pdf-extraction-csv/{route}/*/{source}",
            WORKFLOW,
            "",
            "",
        )
    if rel == "data/extracted/pdf-wide-records.csv":
        return ROUNDS_GLOB, WORKFLOW, "", ""
    if rel == "data/extracted/pdf-wide-coverage.csv":
        return "data/extracted/rounds/*-coverage.csv", WORKFLOW, "", ""
    if folder == "data/extracted/raw":
        route = name.removesuffix(".csv")
        return (
            f"ledgers/working/pdf-extraction-csv/{route}/*/records-final.csv",
            "src/pipeline/combine_extracted_raw.py",
            "",
            "",
        )

    # Identity and attributes.
    if rel == "data/normalization/entity-ids.csv":
        return "data/normalization/fund-names-matrix.csv", (
            "instructions/02-fund-mapping/entity_ids.py"
        ), "", ""
    if rel == "data/normalization/web-manager-names.csv":
        return "data/normalization/manager-queue.csv", NAMES, "blind manager search", MANAGER_BRIEFS
    if rel in {
        "data/normalization/fund-attributes-matrix.csv",
        "data/normalization/attribute-conflicts.csv",
        "data/normalization/worksheets/attribute-conflicts.csv",
    }:
        return FACTS, ATTRIBUTES, "attribute normalization", ATTRIBUTE_BRIEF
    if folder == "data/normalization/worksheets":
        operation = "manager adjudication" if name.startswith("manager-") else "name normalization"
        brief = MANAGER_BRIEFS if name.startswith("manager-") else NORMALIZER_BRIEF
        return "data/normalization/fund-names-matrix.csv", NAMES, operation, brief
    if folder == "data/normalization":
        return ROUNDS_GLOB, NAMES, "name normalization", NORMALIZER_BRIEF

    # Evidence tables, wide tables, and the review files.
    if rel == "data/extracted/tables/observation_lineage.csv":
        return FACTS, REVIEW, "", ""
    if folder == "data/extracted/tables":
        return ROUNDS_GLOB, FLATTEN, "", ""
    if folder == "data/extracted/wide":
        return FACTS, WIDE, "", ""
    if folder == "data/extracted/review":
        if name.startswith("reviewer-"):
            return FACTS, PUBLICATION, "", ""
        return FACTS, REVIEW, "", ""
    if folder == "data/extracted/audit":
        if name.startswith("attribute-"):
            return FACTS, ATTRIBUTES, "", ""
        if name == "promotion-category-mismatches.csv":
            return FACTS, PROMOTE, "", ""
        return SOURCE_LEDGER, "", "source-lineage audit", ""
    if rel == "audit/metric-vocabulary/misfiled-rows.csv":
        return FACTS, "", "metric-vocabulary audit", BRIEF_J.format(route="01-financials")

    # The promotion gate. The templates are hand-written column headers that
    # validate_round02_promotion.py requires; the round-02 evidence is written
    # by the promotion stage off the adjudicated final files.
    if rel.startswith("ledgers/promotion-gate/round02/"):
        route = rel.split("/")[3]
        origin = (
            f"ledgers/working/pdf-extraction-csv/{route}/*/records-final.csv"
            if route != "progress.csv"
            else "ledgers/promotion-gate/round02/01-financials/worksheet.csv"
        )
        return origin, PROMOTE, "", ""
    if folder == "ledgers/promotion-gate":
        return "", "", "", ""

    # The fund model.
    if folder == "data/csv":
        if name in CARRIED_IDENTITY:
            return ROUNDS_GLOB, "", "fund-mapping identity round", NORMALIZER_BRIEF
        if name in ANALYTICS_FILES:
            return "data/csv/fund_periods.csv", "src/analytics/run_integrated_analytics.py", "", ""
        if name == "quality_results.csv":
            return "data/csv/fund_periods.csv", QUALITY, "", ""
        if name in PROMOTED_FILES:
            return f"data/extracted/fund-level/{name}", INTEGRATE, "", ""
        return "", INTEGRATE, "", ""
    if folder == "data/extracted/fund-level":
        if name == "fund_metrics.csv":
            return (
                "data/extracted/fund-level/fund_periods.csv",
                "src/analytics/run_extracted_analytics.py",
                "",
                "",
            )
        if name == "quality_results.csv":
            return "data/extracted/fund-level/fund_periods.csv", QUALITY, "", ""
        if name in SNAPSHOT_FILES:
            return f"data/csv/{name}", INTEGRATE, "", ""
        return f"data/csv/{name}", PROMOTE, "", ""
    if folder == "data/integrated":
        return "data/csv/fund_periods.csv", INTEGRATE, "", ""

    # Public markets, generated fixtures, and the repository checks.
    if rel.startswith("data/public_markets/"):
        return "", MARKETS, "", ""
    if rel == "data/synthetic/fixture-parameters.csv":
        return "", "", "", ""
    if folder == "data/synthetic":
        return "data/synthetic/clean/fund_master.csv", MOCK, "", ""
    if folder == "data/synthetic/clean":
        return "data/csv/synthetic_parameters.csv", GENERATE, "", ""
    if folder == "data/synthetic/defects":
        if name == "detection_scorecard.csv":
            return "data/synthetic/defects/quality_results.csv", MOCK, "", ""
        return f"data/synthetic/clean/{name}", GENERATE, "", ""
    if folder == "data/synthetic/analytics":
        return "data/synthetic/clean/fund_periods.csv", ROUND04, "", ""
    if folder == "data/demo":
        return "data/synthetic/fixture-parameters.csv", MOCK, "", ""
    if rel == TXT_MANIFEST:
        return SOURCE_LEDGER, "src/catalog/build_txt_corpus.py", "", ""
    if rel == "data/documents/images/MANIFEST.csv":
        return (
            "data/extracted/tables/dim_page.csv",
            "data-gathering/src/render_image_corpus.py",
            "",
            "",
        )
    if rel == "ledgers/pipeline/transformation-receipts.csv":
        return "", "src/pipeline/transformation_lineage.py", "", ""
    if rel == "docs/PROJECT-MANIFEST.csv":
        return "", "src/repository/build_project_manifest.py", "", ""
    if rel == "docs/FINAL-RELEASE-AUDIT.csv":
        return "docs/PROJECT-MANIFEST.csv", "src/repository/release_audit.py", "", ""
    if rel == "docs/CSV-LINEAGE.csv":
        return "", "src/repository/build_csv_lineage.py", "", ""
    return "", "", "", ""


def csv_paths() -> list[Path]:
    return sorted(
        (
            path
            for path in manifest_paths(PROJECT_ROOT)
            if path.is_file() and path.suffix.casefold() == ".csv"
        ),
        key=relative,
    )


def render() -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    for path in csv_paths():
        rel = relative(path)
        origin, module, operation, brief = resolve(rel)
        writer.writerow(
            {
                "csv_path": rel,
                "origin_csv": origin,
                "python_file": module,
                "agent_operation": operation,
                "instructions_file": brief,
            }
        )
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare without writing.")
    args = parser.parse_args()
    text = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8-sig") if OUTPUT.is_file() else ""
        if current != text:
            raise SystemExit(f"stale: {relative(OUTPUT)}")
        print(f"current: {relative(OUTPUT)}")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    rows = text.count("\n") - 1
    print(f"{relative(OUTPUT)}: {rows} rows")


if __name__ == "__main__":
    main()
