"""Rebuild the review release in order and receipt every generated artifact.

Each stage declares the files it reads and the files it writes. Both lists are
derived from the modules the stage runs, never kept by hand: the matrices come
from the module's own name constants, the file paths from the module's own path
constants and lookups. A stage that declares an output it did not write fails,
so a receipt can no longer name a stage as the producer of an artifact that some
other command wrote.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import csv
import importlib
import os
import runpy
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Callable, Iterable, Iterator, Sequence

import duckdb

from src.analytics import run_extracted_analytics, run_integrated_analytics
from src.catalog.simple_pdf_extraction import fund_attributes, name_normalization
from src.catalog.simple_pdf_extraction import csv_workflow, source_review
from src.catalog.simple_pdf_extraction.build_csv_pipeline import WORKLIST_ROOT
from src.catalog.simple_pdf_extraction.csv_workflow import ContractFailure
from src.common import matrices
from src.common.matrices import MatrixError
from src.flatten import flatten_extracted, load_star, pivot_wide
from src.flatten.flatten_extracted import FlattenError
from src.flatten.load_star import LoadError
from src.load import load_csv_to_duckdb, promote_extracted_to_fund_level, validate_round02_promotion
from src.load.load_csv_to_duckdb import DatabaseParityError
from src.load.validate_round02_promotion import validate_fund_model_extracted_rows
from src.pipeline import (
    build_extraction_review,
    build_integrated_universe,
    build_reviewer_publication,
    combine_extracted_raw,
    reviewer_check,
)
from src.pipeline.build_extraction_review import ReviewBuildError
from src.pipeline.build_integrated_universe import IntegrationError
from src.pipeline.combine_extracted_raw import CombineError
from src.pipeline.transformation_lineage import (
    ARCHIVE_DIR,
    LineageError,
    RECEIPT_PATH,
    digest,
    display_path,
    missing_current_receipts,
    run_stage,
)
from src.quality import run_fund_checks


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV_DIR = PROJECT_ROOT / "data" / "csv"
TABLE_DIR = PROJECT_ROOT / "data" / "extracted" / "tables"
WIDE_DIR = PROJECT_ROOT / "data" / "extracted" / "wide"
REVIEW_DIR = PROJECT_ROOT / "data" / "extracted" / "review"
AUDIT_DIR = PROJECT_ROOT / "data" / "extracted" / "audit"
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
EXTRACTED_FUND_DIR = PROJECT_ROOT / "data" / "extracted" / "fund-level"
QUALITY_RULES = PROJECT_ROOT / "config" / "quality_rules.yml"
SCOPE_RECORD = PROJECT_ROOT / "ledgers" / "pipeline" / "extraction-scope.csv"
IMAGE_RENDERER = PROJECT_ROOT / "data-gathering/src/render_image_corpus.py"
IMAGE_MANIFEST = PROJECT_ROOT / "data/documents/images/MANIFEST.csv"
SCOPE_COLUMNS = (
    "route",
    "assigned",
    "finished",
    "unfinished",
    "unfinished_documents",
    "backlog_rows",
)

TABLE_OUTPUTS = tuple(
    TABLE_DIR / f"{name}.csv"
    for name in (
        "dim_document",
        "dim_page",
        "dim_entity",
        "entity_alias",
        "dim_metric",
        "fact_observation",
        "fact_holding",
        "unresolved_names",
        "MANIFEST",
    )
)
FUND_MODEL_OUTPUTS = tuple(
    CSV_DIR / filename
    for filename in (
        "manager_master.csv",
        "document_manager_map.csv",
        "fund_master.csv",
        "fund_observations.csv",
        "manager_observations.csv",
        "fund_cashflows.csv",
        "fund_periods.csv",
        "fund_terms.csv",
        "fund_term_clauses.csv",
        "fund_holdings.csv",
    )
)
REVIEWER_OUTPUTS = (
    build_reviewer_publication.OBSERVATION_OUTPUT,
    build_reviewer_publication.PERIOD_OUTPUT,
    build_reviewer_publication.CELL_LINEAGE_OUTPUT,
    build_reviewer_publication.GAP_OUTPUT,
    build_reviewer_publication.ANALYTICS_SUMMARY_OUTPUT,
)
# The review directory holds one file per key of build_outputs, so the stage
# declares the module's own list instead of a copy that can fall behind it.
EXTRACTION_REVIEW_OUTPUTS = (
    TABLE_DIR / "observation_lineage.csv",
    TABLE_DIR / "MANIFEST.csv",
    *(REVIEW_DIR / name for name in build_extraction_review.REVIEW_OUTPUT_NAMES),
)
GOVERNED = "governed-outputs"
RUN_IDS = "run-identifiers"

# The scope the release publishes. Every worklist the scope stage reads and
# every final the corpus stage concatenates come from this one folder.
RELEASE_SCOPE = "active"

# The corpus the closing gate judges: written by the release, receipted by the
# stage that wrote it. The paths are functions in csv_workflow because a test
# patches that module's root; they are resolved here at import, as the other
# governed paths are.
CORPUS_OUTPUTS = (
    csv_workflow.published_records(),
    csv_workflow.published_coverage(),
)

GOVERNED_OUTPUTS = (
    *CORPUS_OUTPUTS,
    SCOPE_RECORD,
    *(combine_extracted_raw.RAW_DIR / f"{route.name}.csv" for route in combine_extracted_raw.rounds()),
    TABLE_DIR / "fact_observation.csv",
    TABLE_DIR / "observation_lineage.csv",
    WAREHOUSE_DIR / "extracted.duckdb",
    *FUND_MODEL_OUTPUTS,
    *build_integrated_universe.extracted_outputs(),
    EXTRACTED_FUND_DIR / "quality_results.csv",
    EXTRACTED_FUND_DIR / "fund_metrics.csv",
    *build_integrated_universe.integrated_outputs(),
    AUDIT_DIR / "attribute-inherit.csv",
    AUDIT_DIR / "attribute-changes.csv",
    CSV_DIR / "quality_results.csv",
    CSV_DIR / "fund_metrics.csv",
    CSV_DIR / "pme_results.csv",
    CSV_DIR / "portfolio_allocations.csv",
    *REVIEWER_OUTPUTS,
    WAREHOUSE_DIR / "alts.duckdb",
    matrices.CHECK_PATH,
)

# The physical cell a published row came from. Two rows sharing this key across
# two publications are the same printed cell, so their attribution must agree.
PHYSICAL_KEY = (
    "file_id",
    "source_page",
    "source_row_label",
    "source_column_label",
    "source_occurrence",
    "record_family",
)

# Every error a stage on this path raises. The handler in main names them once
# so a stage failure prints one FAIL line instead of a traceback.
STAGE_ERRORS = (
    duckdb.Error,
    OSError,
    ValueError,
    CombineError,
    ContractFailure,
    DatabaseParityError,
    FlattenError,
    IntegrationError,
    LineageError,
    LoadError,
    MatrixError,
    ReviewBuildError,
)


class ReleaseError(RuntimeError):
    """Raised when a release stage or closing gate fails."""


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def require_zero(label: str, action: Callable[[], int]) -> int:
    result = action()
    if result != 0:
        raise ReleaseError(f"{label} returned {result}")
    return result


def existing(paths: Iterable[Path]) -> list[Path]:
    """The paths that are files today.

    A stage whose module skips an absent optional table declares the tables it
    can actually open, so the receipt names what was read and no more.
    """

    return [path for path in paths if path.is_file()]


# ---------------------------------------------------------------------------
# Inputs derived from the modules a stage runs


_SKIP_MODULES = frozenset({"src.common.matrices", "src.pipeline.transformation_lineage"})


def _module_source(module: ModuleType) -> ast.Module:
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _matrix_stems() -> frozenset[str]:
    return frozenset(path.stem for path in matrices.matrix_files())


@lru_cache(maxsize=None)
def _named_matrices(module_name: str) -> frozenset[str]:
    """The matrices a module names. A matrix is addressed by its stem, so a
    string constant equal to one is a read of that matrix."""

    tree = _module_source(importlib.import_module(module_name))
    stems = _matrix_stems()
    return frozenset(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in stems
    )


def _src_imports(module_name: str) -> list[str]:
    tree = _module_source(importlib.import_module(module_name))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src."):
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names if alias.name.startswith("src."))
    return names


def module_closure(*modules: ModuleType) -> list[str]:
    """A module and every src module it imports, transitively.

    A stage runs one entry point, and that entry point reads matrices through
    the helpers it imports, so the code path is the import closure.
    """

    seen: list[str] = []
    queue = [module.__name__ for module in modules]
    while queue:
        name = queue.pop(0)
        if name in seen or name in _SKIP_MODULES:
            continue
        try:
            importlib.import_module(name)
        except ImportError:
            continue
        seen.append(name)
        queue.extend(_src_imports(name))
    return seen


def matrix_inputs(*modules: ModuleType) -> list[Path]:
    """Every decision matrix the stage's code path names."""

    names: set[str] = set()
    for module_name in module_closure(*modules):
        names.update(_named_matrices(module_name))
    return [matrices.matrix_path(name) for name in sorted(names)]


def module_paths(module: ModuleType) -> set[Path]:
    """Every file a module names through its own path constants.

    A read such as `CSV_DIR / "fund_periods.csv"` is a path constant of the
    module joined to a literal, so the files a module opens can be read off its
    source instead of copied into a list that falls behind it. A join that ends
    in a directory carries no suffix and is left out; the caller subtracts the
    files the module writes.
    """

    tree = _module_source(module)

    def resolve(node: ast.AST) -> Path | str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            value = getattr(module, node.id, None)
            return value if isinstance(value, Path) else None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = resolve(node.left)
            right = resolve(node.right)
            if isinstance(left, Path) and isinstance(right, str):
                return left / right
        return None

    found: set[Path] = set()
    for node in ast.walk(tree):
        value = resolve(node)
        if isinstance(value, Path) and value.suffix:
            found.add(value)
    return found


# ---------------------------------------------------------------------------
# Input and output lists per stage


def working_final_files() -> list[Path]:
    return sorted(
        path
        for path in (PROJECT_ROOT / "ledgers" / "working" / "pdf-extraction-csv").glob(
            "*/SRC*/records-final.csv"
        )
    )


def active_worklists() -> list[Path]:
    return sorted((WORKLIST_ROOT / RELEASE_SCOPE).glob("*.csv"))


def scope_documents() -> list[tuple[str, str]]:
    """Every (route, file_id) the active worklists assign, in worklist order."""

    return [
        (worklist.stem, row["file_id"])
        for worklist in active_worklists()
        for row in csv_rows(worklist)
    ]


def corpus_inputs() -> list[Path]:
    """Every file publish_corpus opens.

    The corpus is concatenated from the round files, each checked against the
    finals of its documents first, so the stage reads the worklists, both finals
    of every finished document, the model claims and ledger the attribution is
    read from, and the round files themselves.
    """

    paths: list[Path] = [*active_worklists()]
    for route, file_id in scope_documents():
        records, coverage = csv_workflow.final_paths(route, file_id)
        if records.is_file():
            paths.extend((records, coverage))
    for route in csv_workflow.ROUTES:
        paths.extend(
            (
                csv_workflow.claim_path(route),
                csv_workflow.round_records(route),
                csv_workflow.round_coverage(route),
            )
        )
    paths.append(csv_workflow.model_ledger())
    return [*existing(paths), *matrix_inputs(csv_workflow)]


def corpus_outputs() -> tuple[Path, ...]:
    return (
        csv_workflow.published_records(),
        csv_workflow.published_coverage(),
        csv_workflow.qualifier_backlog_ledger(),
    )


def publish_corpus_action() -> int:
    """Write the corpus files and the backlog ledger from the rounds in scope."""

    records, coverage, backlog, unfinished = csv_workflow.publish_corpus(RELEASE_SCOPE)
    backlog_rows = sum(int(row["row_count"]) for row in backlog)
    print(
        f"corpus: {records} records, {coverage} page-coverage rows; "
        f"qualifier backlog {backlog_rows} rows; unfinished {len(unfinished)}"
    )
    return records


def raw_files() -> list[Path]:
    return [
        combine_extracted_raw.RAW_DIR / f"{route.name}.csv"
        for route in combine_extracted_raw.rounds()
    ]


def round_files() -> list[Path]:
    return sorted(flatten_extracted.ROUNDS_DIR.glob("*.csv"))


def record_round_files() -> list[Path]:
    return [path for path in round_files() if path.name.endswith("-records.csv")]


def flatten_inputs() -> list[Path]:
    return [
        *round_files(),
        flatten_extracted.SOURCE_LEDGER,
        flatten_extracted.CATEGORY_CATALOGUE,
        flatten_extracted.STANDARD_MEASURES,
        flatten_extracted.REGISTRY,
        flatten_extracted.WEB_MANAGERS,
        *(entry[0] for entry in name_normalization.KINDS.values()),
        *matrix_inputs(flatten_extracted),
    ]


def extraction_review_inputs() -> list[Path]:
    paths = [
        IMAGE_RENDERER,
        TABLE_DIR / "dim_document.csv",
        TABLE_DIR / "dim_page.csv",
        TABLE_DIR / "fact_observation.csv",
        TABLE_DIR / "MANIFEST.csv",
        PROJECT_ROOT / "data" / "schemas" / "EXTRACTION-ROUTING.csv",
        PROJECT_ROOT / "data-gathering" / "source_ledger.csv",
    ]
    for folder in build_extraction_review.data_folders(build_extraction_review.WORKING_ROOT):
        paths.extend(
            folder / name
            for name in (
                "records-a.csv",
                "records-b.csv",
                "records-final.csv",
                "coverage-final.csv",
                "pair-index.csv",
                "resolution.csv",
            )
        )
    paths.extend(matrix_inputs(build_extraction_review))
    renderer = runpy.run_path(str(IMAGE_RENDERER))
    paths.extend(PROJECT_ROOT / "data/documents/images" / Path(page["filename"]).stem
                 / f"page-{int(page['page_number']):03d}.png"
                 for page in renderer["published_pages"]())
    return paths


def extraction_review_action() -> object:
    result = build_extraction_review.build()
    runpy.run_path(str(IMAGE_RENDERER))["write_published_manifest"]()
    return result


def wide_inputs() -> list[Path]:
    return [
        TABLE_DIR / "fact_observation.csv",
        TABLE_DIR / "fact_holding.csv",
        TABLE_DIR / "entity_alias.csv",
        *matrix_inputs(pivot_wide),
    ]


def wide_outputs() -> list[Path]:
    names = [pivot_wide.table_name(family) for family in pivot_wide.families()]
    names.append("bridge_pivot_observation")
    return [*(WIDE_DIR / f"{name}.csv" for name in names), WIDE_DIR / "MANIFEST.csv", pivot_wide.DDL_PATH]


def star_inputs() -> list[Path]:
    return [
        *(TABLE_DIR / f"{name}.csv" for name in load_star.TABLE_ORDER),
        *(WIDE_DIR / f"{name}.csv" for name in load_star.wide_table_order()),
        load_star.DDL,
        load_star.WIDE_DDL,
        *matrix_inputs(load_star),
    ]


def gate_outputs() -> list[Path]:
    routes = sorted({row["route"] for row in csv_rows(TABLE_DIR / "fact_observation.csv")})
    outputs = [promote_extracted_to_fund_level.GATE_DIR / "progress.csv"]
    for route in routes:
        outputs.extend(
            (
                promote_extracted_to_fund_level.GATE_DIR / route / "assignment.json",
                promote_extracted_to_fund_level.GATE_DIR / route / "worksheet.csv",
            )
        )
    return outputs


def promotion_inputs() -> list[Path]:
    module = promote_extracted_to_fund_level
    candidates = [
        PROJECT_ROOT / matrices.resolve(module.MASTER_INPUTS, f"input_source_{rank}")
        for rank in (1, 2)
    ]
    master_input = next((path for path in candidates if path.is_file()), candidates[-1])
    return [
        TABLE_DIR / "fact_observation.csv",
        TABLE_DIR / "fact_holding.csv",
        fund_attributes.MATRIX,
        module.NORMALIZATION_DIR / "entity-ids.csv",
        PROJECT_ROOT / module.STANDARD_MEASURES_PATH,
        master_input,
        *existing(
            (
                PROJECT_ROOT / matrices.resolve(module.REPORTING_FUND, "map_source"),
                CSV_DIR / "manager_master.csv",
            )
        ),
        *working_final_files(),
        *matrix_inputs(module),
    ]


def promotion_outputs() -> list[Path]:
    return [
        *FUND_MODEL_OUTPUTS,
        AUDIT_DIR / "promotion-category-mismatches.csv",
        fund_attributes.ATTRIBUTE_CHANGES,
        *gate_outputs(),
    ]


def gate_inputs() -> list[Path]:
    """Every file validate_fund_model_extracted_rows opens.

    The batch marker stage 80 writes is the gate's only route: it names the
    batches, each batch names its assignment and worksheet, and a working folder
    without the marker is refused before any gated table is read.
    """

    module = validate_round02_promotion
    working = module.DEFAULT_WORKING_DIR
    marker = working / Path(matrices.resolve(module.GATE_ROUTE, "lean_marker"))
    paths = [CSV_DIR / entry[0] for entry in module.GATED_TABLES.values()]
    paths.append(marker)
    if marker.is_file():
        for row in csv_rows(marker):
            batch = row.get("batch_id", "").strip()
            if batch:
                paths.extend(
                    (marker.parent / batch / "assignment.json", marker.parent / batch / "worksheet.csv")
                )
    paths.extend(
        (
            module.DEFAULT_PUBLIC_MARKET_AUDIT_DIR / "source_file_inventory.csv",
            module.DEFAULT_PUBLIC_MARKET_AUDIT_DIR / "quality_results.csv",
            module.DEFAULT_PUBLIC_MARKET_STAGING_DIR / "benchmark_master_candidates.csv",
            module.DEFAULT_BENCHMARK_POLICY,
        )
    )
    return [*existing(paths), *matrix_inputs(module)]


def integrated_inputs() -> list[Path]:
    module = build_integrated_universe
    return [
        *module.extracted_outputs(),
        module.CONFIG_PATH,
        module.QUALITY_CONFIG,
        module.ATTRIBUTE_CHANGES_PATH,
        module.NORMALIZATION_DIR / "entity-ids.csv",
        module.NORMALIZATION_DIR / "fund-attributes-matrix.csv",
        module.PUBLIC_MARKET_DIR / "benchmark_master_candidates.csv",
        module.PUBLIC_MARKET_DIR / "benchmark_return_candidates.csv",
        *matrix_inputs(module),
    ]


QUALITY_TABLES = (
    "fund_periods.csv",
    "fund_cashflows.csv",
    "fund_master.csv",
    "manager_observations.csv",
    "manager_master.csv",
    "fund_terms.csv",
    "fund_term_clauses.csv",
    "fund_holdings.csv",
)


def quality_inputs(directory: Path) -> list[Path]:
    return [
        *(directory / name for name in QUALITY_TABLES),
        EXTRACTED_FUND_DIR / "fund_master.csv",
        QUALITY_RULES,
        TABLE_DIR / "fact_observation.csv",
        *matrix_inputs(run_fund_checks),
    ]


def reviewer_publication_inputs() -> list[Path]:
    """Every file build_reviewer_publication opens.

    The reads are the module's own path constants joined to the file names in
    its source, less the five files it writes, plus the attribute matrix its
    two fund_attributes lookups open. A new read in the module is declared here
    by construction.
    """

    module = build_reviewer_publication
    return [
        *sorted(module_paths(module) - set(REVIEWER_OUTPUTS)),
        fund_attributes.MATRIX,
        *matrix_inputs(module),
    ]


def analytics_inputs() -> list[Path]:
    return [
        CSV_DIR / "fund_periods.csv",
        CSV_DIR / "fund_cashflows.csv",
        CSV_DIR / "fund_master.csv",
        CSV_DIR / "benchmark_returns.csv",
        CSV_DIR / "quality_results.csv",
        build_integrated_universe.CONFIG_PATH,
        QUALITY_RULES,
        *matrix_inputs(run_integrated_analytics),
    ]


def fund_database_inputs() -> list[Path]:
    return [
        *existing(CSV_DIR / filename for filename in load_csv_to_duckdb.TABLE_FILES.values()),
        *load_csv_to_duckdb.DDL_FILES,
        *gate_inputs(),
        *matrix_inputs(load_csv_to_duckdb),
    ]


_governed_names = set(matrices.mapping(GOVERNED))
for _path in GOVERNED_OUTPUTS:
    _rel = _path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    if _rel not in _governed_names:
        raise RuntimeError(f"governed-outputs.csv lacks {_rel}")


# ---------------------------------------------------------------------------
# Stage actions


def scope_final_files() -> list[Path]:
    """Every adjudicated final the active worklists assign, in worklist order."""

    paths: list[Path] = []
    for worklist in active_worklists():
        for row in csv_rows(worklist):
            final = (
                combine_extracted_raw.WORKING_DIR
                / worklist.stem
                / row["file_id"]
                / "records-final.csv"
            )
            if final.is_file():
                paths.append(final)
    return paths


def scope_qualifier_backlog() -> list[dict[str, str]]:
    """The qualifier backlog the finals in scope carry, derived here again.

    Publication writes the ledger from the same rule while it validates each
    final; this reads the finals a second time and rebuilds the table, so a
    ledger edited or left behind by an older publication cannot pass as the
    live list the page-reading step works from.
    """

    entries: list[dict[str, str]] = []
    for worklist in active_worklists():
        route = worklist.stem
        for row in csv_rows(worklist):
            final = (
                combine_extracted_raw.WORKING_DIR / route / row["file_id"] / "records-final.csv"
            )
            if final.is_file():
                entries.extend(
                    csv_workflow.final_backlog_entries(final, route, row["file_id"])
                )
    return csv_workflow.backlog_table(entries)


def require_backlog_ledger(derived: Sequence[dict[str, str]]) -> None:
    """Refuse a published backlog ledger that is not what the finals now carry."""

    ledger = csv_workflow.qualifier_backlog_ledger()
    if not ledger.is_file():
        raise ReleaseError(
            f"{display_path(ledger, PROJECT_ROOT)} is absent; run "
            "`python instructions/01-pdf-extraction-csv/workflow.py publish "
            "--scope active` to write it"
        )
    columns = list(csv_workflow.QUALIFIER_BACKLOG_COLUMNS)
    published = [
        tuple(row.get(column, "") for column in columns) for row in csv_rows(ledger)
    ]
    expected = [tuple(row[column] for column in columns) for row in derived]
    if published == expected:
        return
    only_published = [row for row in published if row not in expected]
    only_derived = [row for row in expected if row not in published]
    raise ReleaseError(
        f"{display_path(ledger, PROJECT_ROOT)} states {len(published)} backlog "
        f"rows and the finals in scope carry {len(expected)}; "
        f"{len(only_published)} row(s) only in the ledger, "
        f"{len(only_derived)} only in the finals: "
        + "; ".join(",".join(row) for row in (*only_published[:3], *only_derived[:3]))
    )


def write_extraction_scope() -> dict[str, int]:
    """Record what the active worklists assign, what the tree finished, and what it owes.

    The count the release states is read from the assignment, so it cannot
    drift from it, and every assigned document with no adjudicated final is
    named. A run passes with unfinished documents only because they are named.
    The backlog column counts the rows whose qualifier dimension nobody was
    asked to read; the ledger names them and is checked against the finals here.
    """

    backlog = scope_qualifier_backlog()
    require_backlog_ledger(backlog)
    backlog_by_route: dict[str, int] = {}
    for row in backlog:
        backlog_by_route[row["route"]] = backlog_by_route.get(row["route"], 0) + int(
            row["row_count"]
        )
    rows: list[dict[str, str]] = []
    assigned = finished = 0
    unfinished_all: list[str] = []
    for path in active_worklists():
        route = path.stem
        documents = [row["file_id"] for row in csv_rows(path)]
        unfinished = [
            file_id
            for file_id in documents
            if not (combine_extracted_raw.WORKING_DIR / route / file_id / "records-final.csv").is_file()
        ]
        assigned += len(documents)
        finished += len(documents) - len(unfinished)
        unfinished_all.extend(f"{route}/{file_id}" for file_id in unfinished)
        rows.append(
            {
                "route": route,
                "assigned": str(len(documents)),
                "finished": str(len(documents) - len(unfinished)),
                "unfinished": str(len(unfinished)),
                "unfinished_documents": " | ".join(unfinished),
                "backlog_rows": str(backlog_by_route.get(route, 0)),
            }
        )
    for row in rows:
        named = [name for name in row["unfinished_documents"].split(" | ") if name]
        if len(named) != int(row["unfinished"]):
            raise ReleaseError(
                f"{row['route']}: {row['unfinished']} unfinished document(s) and {len(named)} named"
            )
    SCOPE_RECORD.parent.mkdir(parents=True, exist_ok=True)
    with SCOPE_RECORD.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SCOPE_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    named = ", ".join(unfinished_all) if unfinished_all else "none"
    backlog_rows = sum(backlog_by_route.values())
    print(f"scope: assigned={assigned} finished={finished} unfinished={len(unfinished_all)}: {named}")
    print(
        f"scope: qualifier backlog {backlog_rows} rows in "
        f"{len({(row['route'], row['file_id']) for row in backlog})} documents"
    )
    return {
        "assigned": assigned,
        "finished": finished,
        "unfinished": len(unfinished_all),
        "backlog_rows": backlog_rows,
    }


def _receipt_rows() -> list[dict[str, str]]:
    if not RECEIPT_PATH.is_file():
        return []
    csv.field_size_limit(64 * 1024 * 1024)
    with RECEIPT_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def previous_object(path: Path, receipts: Sequence[dict[str, str]] | None = None) -> Path | None:
    """The archived copy of the last version of this file that differs from it.

    The receipt ledger records the hash of every artifact a stage read or wrote,
    and the archive keeps the bytes under that hash, so the file as it stood
    before the current publication is recoverable without a second live copy.
    """

    if not path.is_file():
        return None
    current = digest(path)
    name = display_path(path, PROJECT_ROOT)
    for row in reversed(list(_receipt_rows() if receipts is None else receipts)):
        candidates: list[str] = []
        if row.get("output_path") == name:
            candidates.append(row.get("output_sha256", ""))
            candidates.append(row.get("prior_output_sha256", ""))
        for item in row.get("input_artifacts", "").split(" | "):
            recorded, _, sha = item.strip().rpartition("#")
            if recorded == name:
                candidates.append(sha)
        for sha in candidates:
            if len(sha) != 64 or sha == current:
                continue
            archived = ARCHIVE_DIR / f"sha256-{sha}{path.suffix.casefold()}"
            if archived.is_file():
                return archived
    return None


def _attribution_index(rows: Sequence[dict[str, str]], core: Sequence[str]) -> dict[tuple[str, ...], tuple[tuple[str, ...], str]]:
    index: dict[tuple[str, ...], tuple[tuple[str, ...], str]] = {}
    repeated: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(row.get(field, "") for field in PHYSICAL_KEY)
        if key in index:
            repeated.add(key)
            continue
        index[key] = (tuple(row.get(field, "") for field in core), row.get("extractor_model", ""))
    for key in repeated:
        index.pop(key, None)
    return index


def verify_raw_round_relation() -> int:
    compared = 0
    unchecked: list[str] = []
    receipts = _receipt_rows()
    for raw_path in raw_files():
        route = raw_path.stem
        round_path = flatten_extracted.ROUNDS_DIR / f"{route}-records.csv"
        if not round_path.is_file():
            raise ReleaseError(f"missing published records file for {route}")
        with raw_path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw_reader = csv.DictReader(handle)
            raw_header = list(raw_reader.fieldnames or [])
            raw_rows = list(raw_reader)
        with round_path.open("r", encoding="utf-8-sig", newline="") as handle:
            round_reader = csv.DictReader(handle)
            round_header = list(round_reader.fieldnames or [])
            published_rows = list(round_reader)
        if round_header != [*raw_header, "extractor_model"]:
            raise ReleaseError(f"{round_path.name}: expected raw columns plus extractor_model")
        projected = [{field: row.get(field, "") for field in raw_header} for row in published_rows]
        if projected != raw_rows:
            raise ReleaseError(f"{route}: raw and published record bytes differ by core field")
        if any(not row.get("extractor_model", "") for row in published_rows):
            raise ReleaseError(f"{route}: published row lacks extractor_model attribution")
        # A row whose printed cell and core fields are unchanged is the same
        # extraction, so the model credited with it cannot change between two
        # publications. Republishing a route re-derives attribution for every
        # candidate file it sees, which is how untouched documents were
        # re-attributed with no stage reporting it.
        archived = previous_object(round_path, receipts)
        if archived is None:
            unchecked.append(route)
            continue
        with archived.open("r", encoding="utf-8-sig", newline="") as handle:
            prior_rows = list(csv.DictReader(handle))
        prior = _attribution_index(prior_rows, raw_header)
        current = _attribution_index(published_rows, raw_header)
        changed = [
            key
            for key, (core, model) in current.items()
            if key in prior and prior[key][0] == core and prior[key][1] != model
        ]
        if changed:
            sample = "; ".join("/".join(key) for key in sorted(changed)[:5])
            raise ReleaseError(
                f"{route}: {len(changed)} unchanged row(s) changed extractor_model: {sample}"
            )
        compared += len(raw_rows)
    if unchecked:
        print(f"attribution: no archived prior publication for {', '.join(unchecked)}")
    return compared


def quality_action() -> int:
    periods = run_fund_checks.read_csv(CSV_DIR / "fund_periods.csv")
    results = run_fund_checks.run_quality_checks(
        periods,
        run_fund_checks.read_csv(CSV_DIR / "fund_cashflows.csv"),
        run_fund_checks.read_csv(CSV_DIR / "fund_master.csv"),
        manager_observations=run_fund_checks.read_csv(CSV_DIR / "manager_observations.csv"),
        manager_master=run_fund_checks.read_csv(CSV_DIR / "manager_master.csv"),
        fund_terms=run_fund_checks.read_csv(CSV_DIR / "fund_terms.csv"),
        fund_term_clauses=run_fund_checks.read_csv(CSV_DIR / "fund_term_clauses.csv"),
        fund_holdings=run_fund_checks.read_csv(CSV_DIR / "fund_holdings.csv"),
        run_id=matrices.resolve(RUN_IDS, "integrated_qc_run_id"),
        source_fund_master=run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_master.csv"),
        checked_at=matrices.resolve(RUN_IDS, "integrated_qc_checked_at"),
        tolerances=run_fund_checks.load_tolerances(QUALITY_RULES),
        printed_precision=run_fund_checks.printed_precision_from_observations(
            periods, run_fund_checks.read_csv(TABLE_DIR / "fact_observation.csv")
        ),
    )
    run_fund_checks.write_results(CSV_DIR / "quality_results.csv", results)
    return len(results)


def extracted_quality_action() -> int:
    periods = run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_periods.csv")
    results = run_fund_checks.run_quality_checks(
        periods,
        run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_cashflows.csv"),
        run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_master.csv"),
        manager_observations=run_fund_checks.read_csv(
            EXTRACTED_FUND_DIR / "manager_observations.csv"
        ),
        manager_master=run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "manager_master.csv"),
        fund_terms=run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_terms.csv"),
        fund_term_clauses=run_fund_checks.read_csv(
            EXTRACTED_FUND_DIR / "fund_term_clauses.csv"
        ),
        fund_holdings=run_fund_checks.read_csv(EXTRACTED_FUND_DIR / "fund_holdings.csv"),
        run_id="EXTRACTED_QC_V1",
        checked_at="1970-01-01T00:00:00Z",
        tolerances=run_fund_checks.load_tolerances(QUALITY_RULES),
        printed_precision=run_fund_checks.printed_precision_from_observations(
            periods, run_fund_checks.read_csv(TABLE_DIR / "fact_observation.csv")
        ),
    )
    run_fund_checks.write_results(EXTRACTED_FUND_DIR / "quality_results.csv", results)
    return len(results)


def closing_gate() -> list[str]:
    checks, open_items = reviewer_check.run_checks(PROJECT_ROOT)
    failures = [check for check in checks if not check.passed]
    if failures:
        rendered = "; ".join(
            f"{check.name}={check.actual!r} expected {check.expected!r}" for check in failures
        )
        raise ReleaseError(f"reviewer gate failed: {rendered}")
    missing = missing_current_receipts(GOVERNED_OUTPUTS)
    if missing:
        raise ReleaseError("current outputs lack receipts: " + ", ".join(missing))
    print(f"PASS: closing reviewer gate; checks={len(checks)}, open_items={len(open_items)}")
    for item in open_items:
        print(f"OPEN: {item}")
    return open_items


# ---------------------------------------------------------------------------
# Running a stage


@contextmanager
def record_writes(seen: set[Path]) -> Iterator[None]:
    """Collect every path opened for writing while the block runs."""

    real_open = builtins.open
    real_path_open = Path.open
    real_write_text = Path.write_text
    real_write_bytes = Path.write_bytes
    real_replace = os.replace

    def note(target: object, mode: object) -> None:
        if not isinstance(mode, str) or not any(character in mode for character in "wxa+"):
            return
        try:
            seen.add(Path(target).resolve())  # type: ignore[arg-type]
        except (OSError, TypeError, ValueError):
            pass

    def open_(file, *args, **kwargs):  # type: ignore[no-untyped-def]
        note(file, kwargs.get("mode", args[0] if args else "r"))
        return real_open(file, *args, **kwargs)

    def path_open(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        note(self, kwargs.get("mode", args[0] if args else "r"))
        return real_path_open(self, *args, **kwargs)

    def write_text(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        note(self, "w")
        return real_write_text(self, *args, **kwargs)

    def write_bytes(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        note(self, "w")
        return real_write_bytes(self, *args, **kwargs)

    def replace(source, target, *args, **kwargs):  # type: ignore[no-untyped-def]
        note(target, "w")
        return real_replace(source, target, *args, **kwargs)

    builtins.open = open_  # type: ignore[assignment]
    Path.open = path_open  # type: ignore[assignment]
    Path.write_text = write_text  # type: ignore[assignment]
    Path.write_bytes = write_bytes  # type: ignore[assignment]
    os.replace = replace  # type: ignore[assignment]
    try:
        yield
    finally:
        builtins.open = real_open  # type: ignore[assignment]
        Path.open = real_path_open  # type: ignore[assignment]
        Path.write_text = real_write_text  # type: ignore[assignment]
        Path.write_bytes = real_write_bytes  # type: ignore[assignment]
        os.replace = real_replace  # type: ignore[assignment]


def guard_outputs(stage_id: str, outputs: Sequence[Path], action: Callable[[], object]) -> Callable[[], object]:
    """Wrap a stage action so a declared output it never wrote fails the stage.

    Presence is not production. A verification stage that declares another
    command's artifact passes the file-exists test and then appears in the
    ledger as that artifact's producer, which is how two stages came to be
    credited with files written outside the release.
    """

    def guarded() -> object:
        before = {path: (path.stat().st_mtime_ns if path.is_file() else None) for path in outputs}
        written: set[Path] = set()
        with record_writes(written):
            result = action()
        untouched = [
            path
            for path in outputs
            if before[path] is not None
            and path.resolve() not in written
            and path.is_file()
            and path.stat().st_mtime_ns == before[path]
        ]
        if untouched:
            raise ReleaseError(
                f"{stage_id} declares output(s) it did not write: "
                + ", ".join(display_path(path, PROJECT_ROOT) for path in untouched)
            )
        return result

    return guarded


@dataclass(frozen=True)
class Stage:
    """One stage, with the lists it declares read when it runs.

    A stage that reads a directory listing has to read it after the stage that
    writes into it, so the lists are callables and not values fixed when the
    release starts.
    """

    order: int
    stage_id: str
    command: str
    inputs: Callable[[], Iterable[Path]]
    outputs: Callable[[], Iterable[Path]]
    action: Callable[[], object]

    def declared_inputs(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys(Path(path) for path in self.inputs()))

    def declared_outputs(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys(Path(path) for path in self.outputs()))


def stage(
    order: int,
    stage_id: str,
    command: str,
    inputs: Iterable[Path],
    outputs: Iterable[Path],
    action: Callable[[], object],
) -> object:
    declared_inputs = tuple(dict.fromkeys(Path(path) for path in inputs))
    declared_outputs = tuple(dict.fromkeys(Path(path) for path in outputs))
    try:
        result, receipts = run_stage(
            stage_id=stage_id,
            stage_order=order,
            command=command,
            inputs=declared_inputs,
            outputs=declared_outputs,
            action=guard_outputs(stage_id, declared_outputs, action),
        )
    except ReleaseError:
        raise
    except STAGE_ERRORS as exc:
        # A stage error carries no stage name of its own, so it escaped as a
        # traceback while the release contract promises one FAIL line.
        raise ReleaseError(f"{order:03d} {stage_id}: {type(exc).__name__}: {exc}") from exc
    print(f"PASS: {order:03d} {stage_id}; new_receipts={len(receipts)}")
    return result


def stages() -> tuple[Stage, ...]:
    """Every release stage with the files it reads and the files it writes.

    A gate declares no output: it reads and refuses, and the artifact it checks
    keeps the receipt of the stage that wrote it.
    """

    return (
        Stage(
            3,
            "corpus-publication",
            f"python instructions/01-pdf-extraction-csv/workflow.py publish --scope {RELEASE_SCOPE}",
            corpus_inputs,
            corpus_outputs,
            publish_corpus_action,
        ),
        Stage(
            5,
            "extraction-scope",
            "read the active worklists and their finals; record assigned, finished, "
            "unfinished, and backlog rows against the published backlog ledger",
            lambda: [
                *active_worklists(),
                *scope_final_files(),
                *existing([csv_workflow.qualifier_backlog_ledger()]),
                *matrix_inputs(csv_workflow),
            ],
            lambda: (SCOPE_RECORD,),
            write_extraction_scope,
        ),
        Stage(
            10,
            "raw-combination",
            "python -m src.pipeline.combine_extracted_raw",
            working_final_files,
            raw_files,
            lambda: require_zero("raw combination", lambda: combine_extracted_raw.combine(False)),
        ),
        Stage(
            15,
            "round-publication-verification",
            "verify raw core fields; hold extractor_model attribution across publications",
            lambda: (*raw_files(), *record_round_files()),
            tuple,
            verify_raw_round_relation,
        ),
        Stage(
            20,
            "normalization-gates",
            "source_review; name_normalization check; fund_attributes conflicts --strict; matrices --check",
            # `name_normalization.check` reads the four alias ledgers in KINDS and
            # the matrices its module names: `name-status-policy` for the settled
            # statuses it counts, and `subject-kind`, `column-kind`, `legal-noise`,
            # `non-names`, `name-match-key` and `manager-auto-settle-rules`, which
            # the module resolves as it loads. `matrix_inputs` names exactly those.
            # `matrix_files` is the wider list because the third check on this
            # stage, `matrices.check_and_record`, opens every matrix in the folder.
            lambda: (
                *(entry[0] for entry in name_normalization.KINDS.values()),
                fund_attributes.MATRIX,
                source_review.RULES,
                source_review.CHANGES,
                *(csv_workflow.file_folder(route, file_id) / filename
                  for route, file_id in scope_documents()
                  for filename in ("resolution.csv", "records-a.csv", "records-b.csv", "pair-index.csv")),
                *matrix_inputs(name_normalization, fund_attributes),
                *matrices.matrix_files(),
            ),
            lambda: (fund_attributes.CONFLICTS, matrices.CHECK_PATH),
            lambda: (
                require_zero("source corrections", source_review.check),
                require_zero("name normalization", name_normalization.check),
                require_zero("attribute conflicts", lambda: fund_attributes.conflicts(True)),
                require_zero("transformation matrices", matrices.check_and_record),
            ),
        ),
        Stage(
            30,
            "flatten",
            "python -m src.flatten.flatten_extracted",
            flatten_inputs,
            lambda: TABLE_OUTPUTS,
            lambda: flatten_extracted.build_tables(TABLE_DIR),
        ),
        Stage(
            40,
            "extraction-review",
            "python -m src.pipeline.build_extraction_review; render_image_corpus.py --manifest-only",
            extraction_review_inputs,
            lambda: (*EXTRACTION_REVIEW_OUTPUTS, IMAGE_MANIFEST),
            extraction_review_action,
        ),
        Stage(
            50,
            "wide",
            "python -m src.flatten.pivot_wide",
            wide_inputs,
            wide_outputs,
            lambda: pivot_wide.build_wide_tables(TABLE_DIR, WIDE_DIR),
        ),
        Stage(
            60,
            "extracted-database",
            "python -m src.flatten.load_star",
            star_inputs,
            lambda: (WAREHOUSE_DIR / "extracted.duckdb",),
            lambda: load_star.load(
                TABLE_DIR, WAREHOUSE_DIR / "extracted.duckdb", rebuild=True, wide_dir=WIDE_DIR
            ),
        ),
        Stage(
            70,
            "attribute-audit",
            "python -m src.catalog.simple_pdf_extraction.fund_attributes apply",
            lambda: (
                fund_attributes.FACT_OBSERVATION,
                fund_attributes.MATRIX,
                *matrix_inputs(fund_attributes),
            ),
            lambda: (fund_attributes.INHERIT_LOG,),
            fund_attributes.apply,
        ),
        Stage(
            80,
            "fund-model-promotion",
            "python -m src.load.promote_extracted_to_fund_level",
            promotion_inputs,
            promotion_outputs,
            promote_extracted_to_fund_level.promote,
        ),
        Stage(
            90,
            "promotion-gate",
            "python -m src.load.validate_round02_promotion",
            gate_inputs,
            tuple,
            lambda: validate_fund_model_extracted_rows(CSV_DIR),
        ),
        Stage(
            95,
            "extracted-fund-level-snapshot",
            "python -m src.pipeline.build_integrated_universe --snapshot-only",
            lambda: (CSV_DIR / filename for filename in build_integrated_universe.EXTRACTED_FILES),
            build_integrated_universe.extracted_outputs,
            build_integrated_universe.snapshot_extracted,
        ),
        Stage(
            100,
            "integrated-completion",
            "python -m src.pipeline.build_integrated_universe",
            integrated_inputs,
            build_integrated_universe.integrated_outputs,
            build_integrated_universe.build,
        ),
        Stage(
            105,
            "benchmark-rights-gate",
            "python -m src.load.validate_round02_promotion",
            gate_inputs,
            tuple,
            lambda: validate_fund_model_extracted_rows(CSV_DIR),
        ),
        Stage(
            110,
            "quality",
            "python -m src.quality.run_fund_checks --run-id INTEGRATED_QC_V1",
            lambda: quality_inputs(CSV_DIR),
            lambda: (CSV_DIR / "quality_results.csv",),
            quality_action,
        ),
        Stage(
            112,
            "extracted-only-quality",
            "python -m src.quality.run_fund_checks --run-id EXTRACTED_QC_V1",
            lambda: quality_inputs(EXTRACTED_FUND_DIR),
            lambda: (EXTRACTED_FUND_DIR / "quality_results.csv",),
            extracted_quality_action,
        ),
        Stage(
            115,
            "extracted-only-analytics",
            "python -m src.analytics.run_extracted_analytics",
            lambda: (
                EXTRACTED_FUND_DIR / "fund_periods.csv",
                EXTRACTED_FUND_DIR / "fund_cashflows.csv",
                EXTRACTED_FUND_DIR / "quality_results.csv",
                *matrix_inputs(run_extracted_analytics),
            ),
            lambda: (EXTRACTED_FUND_DIR / "fund_metrics.csv",),
            lambda: run_extracted_analytics.run(
                EXTRACTED_FUND_DIR,
                quality_path=EXTRACTED_FUND_DIR / "quality_results.csv",
            ),
        ),
        Stage(
            120,
            "analytics",
            "python -m src.analytics.run_integrated_analytics",
            analytics_inputs,
            lambda: (
                CSV_DIR / "fund_metrics.csv",
                CSV_DIR / "pme_results.csv",
                CSV_DIR / "portfolio_allocations.csv",
            ),
            lambda: run_integrated_analytics.run(CSV_DIR),
        ),
        Stage(
            130,
            "reviewer-publication",
            "python -m src.pipeline.build_reviewer_publication",
            reviewer_publication_inputs,
            lambda: REVIEWER_OUTPUTS,
            build_reviewer_publication.build,
        ),
        Stage(
            140,
            "fund-model-database",
            "python -m src.load.load_csv_to_duckdb --rebuild",
            fund_database_inputs,
            lambda: (WAREHOUSE_DIR / "alts.duckdb",),
            lambda: load_csv_to_duckdb.load(
                CSV_DIR, WAREHOUSE_DIR / "alts.duckdb", rebuild=True
            ),
        ),
    )


def publish() -> list[str]:
    from src.pipeline.release_checks import run_check
    from src.repository import build_release_audit

    if not working_final_files():
        raise ReleaseError("no adjudicated records-final.csv files found")
    if not round_files():
        raise ReleaseError("no published round CSVs found")
    try:
        for item in stages():
            run_check(
                item.stage_id, item.command,
                lambda item=item: stage(
                    item.order, item.stage_id, item.command,
                    item.declared_inputs(), item.declared_outputs(), item.action,
                ),
                describe=lambda result: "Stage completed; output receipts record data changes",
            )
        return run_check(
            "reviewer-check", "python -m src.pipeline.reviewer_check", closing_gate,
            describe=lambda items: f"Closing data checks passed; {len(items)} documented observation(s)",
        )
    finally:
        build_release_audit.build()


# What this command certifies ends at the closing reviewer gate. The folder
# guides, the manifest, the file-type audit, and the test suite are the
# repository gate, run after it as README.md's Reproduction table lists them;
# a final line that read "publication-ready" while those were still to run
# certified a state the repository's own checks then rejected.
REPOSITORY_GATE = (
    "python -m src.repository.build_release_audit --verify-inputs; "
    "python -m src.repository.build_readmes; "
    "python -m src.repository.build_csv_lineage; "
    "python -m src.repository.build_project_manifest; "
    "python -m src.dashboard.build_dashboard; "
    "python -m src.repository.build_release_audit --verify-repository; "
    "python -m src.repository.build_project_manifest; "
    "python -m src.dashboard.build_dashboard"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        open_items = publish()
    except ReleaseError as exc:
        print(f"FAIL: {exc}")
        return 1
    except STAGE_ERRORS as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(
        "PASS: every release stage rebuilt with a receipt and the closing reviewer "
        f"gate passed with {len(open_items)} open item(s); the repository gate runs next: "
        f"{REPOSITORY_GATE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
