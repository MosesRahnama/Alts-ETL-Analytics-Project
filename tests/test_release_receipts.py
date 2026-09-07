"""The release receipt declares what each stage reads and what it writes.

Two defects the audit found are pinned here. A stage that declared an artifact
another command wrote passed on the file being present, and the ledger then
named it as the producer. A stage that read a matrix or a table it never
declared changed its output with no declared input hash moving.
"""

from __future__ import annotations

import ast
import csv
import importlib
import inspect
from pathlib import Path

import pytest

from src.catalog.simple_pdf_extraction import csv_workflow
from src.catalog.simple_pdf_extraction.csv_wide_contract import RECORD_COLUMNS
from src.common import matrices
from src.pipeline import combine_extracted_raw, publish_review_release as release
from src.pipeline.transformation_lineage import LineageError, run_stage

PROJECT_ROOT = release.PROJECT_ROOT
TRANSFORMATIONS = matrices.ROOT.resolve()

# The modules each stage runs, restated here so a change to the release has to
# be made twice before the declared matrices can drift from the code path.
STAGE_MODULES: dict[int, tuple[str, ...]] = {
    3: ("src.catalog.simple_pdf_extraction.csv_workflow",),
    5: ("src.catalog.simple_pdf_extraction.csv_workflow",),
    10: (),
    15: (),
    20: (),
    30: ("src.flatten.flatten_extracted",),
    40: ("src.pipeline.build_extraction_review",),
    50: ("src.flatten.pivot_wide",),
    60: ("src.flatten.load_star",),
    70: ("src.catalog.simple_pdf_extraction.fund_attributes",),
    80: ("src.load.promote_extracted_to_fund_level",),
    90: ("src.load.validate_round02_promotion",),
    95: (),
    100: ("src.pipeline.build_integrated_universe",),
    105: ("src.load.validate_round02_promotion",),
    110: ("src.quality.run_fund_checks",),
    112: ("src.quality.run_fund_checks",),
    115: ("src.analytics.run_extracted_analytics",),
    120: ("src.analytics.run_integrated_analytics",),
    130: ("src.pipeline.build_reviewer_publication",),
    140: ("src.load.load_csv_to_duckdb", "src.load.validate_round02_promotion"),
}


def stage_by_order(order: int) -> release.Stage:
    return next(item for item in release.stages() if item.order == order)


def declared(order: int) -> set[Path]:
    item = stage_by_order(order)
    return {path.resolve() for path in (*item.declared_inputs(), *item.declared_outputs())}


def matrix_paths(order: int) -> set[str]:
    return {
        path.stem
        for path in stage_by_order(order).declared_inputs()
        if path.resolve().parent == TRANSFORMATIONS
    }


def named_paths(function) -> set[Path]:
    """Every repository file the function's own code names.

    The quality stages pass their tables in from the release module, so the
    files they open are literals in this module and can be read off the source
    instead of guessed.
    """

    module = importlib.import_module(function.__module__)
    tree = ast.parse(inspect.getsource(function))

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
        return None

    found: set[Path] = set()
    for node in ast.walk(tree):
        value = resolve(node)
        if isinstance(value, Path) and value.suffix:
            found.add(value.resolve())
    return found


# ---------------------------------------------------------------------------
# A declared output the stage did not write


def test_run_stage_fails_when_a_declared_output_was_not_written(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    output = tmp_path / "output.csv"
    output.write_text("b\n2\n", encoding="utf-8")
    receipts = tmp_path / "receipts.csv"
    with pytest.raises(release.ReleaseError) as error:
        run_stage(
            stage_id="verification-only",
            stage_order=1,
            command="check",
            inputs=[source],
            outputs=[output],
            action=release.guard_outputs("verification-only", [output], lambda: 0),
            receipt_path=receipts,
            archive_dir=tmp_path / "archive",
            root=tmp_path,
        )
    assert "did not write" in str(error.value)
    assert "output.csv" in str(error.value)
    written = list(csv.DictReader(receipts.open(encoding="utf-8-sig")))
    assert [row["status"] for row in written] == ["FAIL"]


def test_run_stage_passes_when_the_action_writes_its_output(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    output = tmp_path / "output.csv"
    output.write_text("b\n2\n", encoding="utf-8")
    result, receipts = run_stage(
        stage_id="writer",
        stage_order=1,
        command="write",
        inputs=[source],
        outputs=[output],
        action=release.guard_outputs(
            "writer", [output], lambda: output.write_text("b\n3\n", encoding="utf-8")
        ),
        receipt_path=tmp_path / "receipts.csv",
        archive_dir=tmp_path / "archive",
        root=tmp_path,
    )
    assert result is not None
    assert [row["status"] for row in receipts] == ["PASS"]


def test_a_missing_output_still_fails_run_stage(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(LineageError):
        run_stage(
            stage_id="absent",
            stage_order=1,
            command="write",
            inputs=[source],
            outputs=[tmp_path / "never.csv"],
            action=release.guard_outputs("absent", [tmp_path / "never.csv"], lambda: 0),
            receipt_path=tmp_path / "receipts.csv",
            archive_dir=tmp_path / "archive",
            root=tmp_path,
        )


def test_the_write_tracer_sees_every_write_form(tmp_path: Path) -> None:
    import os

    seen: set[Path] = set()
    with release.record_writes(seen):
        with open(tmp_path / "builtin.csv", "w", encoding="utf-8") as handle:
            handle.write("a\n")
        with (tmp_path / "pathopen.csv").open("w", encoding="utf-8") as handle:
            handle.write("a\n")
        (tmp_path / "text.csv").write_text("a\n", encoding="utf-8")
        (tmp_path / "bytes.csv").write_bytes(b"a\n")
        (tmp_path / "staged.csv").write_text("a\n", encoding="utf-8")
        os.replace(tmp_path / "staged.csv", tmp_path / "renamed.csv")
        (tmp_path / "builtin.csv").read_text(encoding="utf-8")
    assert {path.name for path in seen} == {
        "builtin.csv",
        "pathopen.csv",
        "text.csv",
        "bytes.csv",
        "staged.csv",
        "renamed.csv",
    }


def test_the_write_tracer_restores_the_real_writers(tmp_path: Path) -> None:
    import builtins

    real = builtins.open
    with release.record_writes(set()):
        pass
    assert builtins.open is real


# ---------------------------------------------------------------------------
# Declared inputs equal what the stage opens


def test_every_declared_input_is_a_file() -> None:
    missing = [
        f"{item.order} {release.display_path(path, PROJECT_ROOT)}"
        for item in release.stages()
        for path in item.declared_inputs()
        if not path.is_file()
    ]
    assert missing == []


def test_every_declared_input_is_inside_the_project() -> None:
    """A stage reads project files, so a declared path outside it is leaked state.

    A test that redirects a module constant into a temporary directory and does
    not put it back leaves the stage lists pointing there. The paths then still
    read as absolute paths, so only the missing-file check catches it, and only
    while the temporary directory is already deleted.
    """

    stray = [
        f"{item.order} {path}"
        for item in release.stages()
        for path in item.declared_inputs()
        if not path.resolve().is_relative_to(PROJECT_ROOT)
    ]
    assert stray == []


def test_every_stage_declares_the_matrices_its_code_path_names() -> None:
    for order, module_names in STAGE_MODULES.items():
        if not module_names:
            continue
        modules = [importlib.import_module(name) for name in module_names]
        expected = {path.stem for path in release.matrix_inputs(*modules)}
        assert matrix_paths(order) == expected, f"stage {order}"


def test_the_quality_stages_declare_exactly_the_files_they_open() -> None:
    for order, action in ((110, release.quality_action), (112, release.extracted_quality_action)):
        opened = named_paths(action)
        assert opened == {path for path in declared(order) if path.parent != TRANSFORMATIONS}


def test_no_stage_declares_the_whole_transformations_folder_by_hand() -> None:
    # Stage 20 validates every matrix, so it alone declares all of them.
    everything = {path.stem for path in matrices.matrix_files()}
    for item in release.stages():
        if item.order == 20:
            continue
        assert matrix_paths(item.order) != everything, f"stage {item.order}"


# ---------------------------------------------------------------------------
# The findings this fix closes


def test_stage_ten_writes_the_raw_files_it_declares() -> None:
    item = stage_by_order(10)
    assert set(item.declared_outputs()) == set(release.raw_files())
    assert "--check" not in item.command


def test_stage_fifteen_declares_the_round_files_as_inputs_and_writes_nothing() -> None:
    item = stage_by_order(15)
    assert item.declared_outputs() == ()
    assert set(release.record_round_files()) <= set(item.declared_inputs())


def test_the_verification_gates_declare_no_output() -> None:
    for order in (15, 90, 105):
        assert stage_by_order(order).declared_outputs() == (), f"stage {order}"


def test_stage_thirty_declares_the_name_matrices_and_the_web_manager_list() -> None:
    names = {path.name for path in stage_by_order(30).declared_inputs()}
    assert {
        "manager-names-matrix.csv",
        "lp-names-matrix.csv",
        "plan-names-matrix.csv",
        "company-names-matrix.csv",
        "fund-names-matrix.csv",
        "web-manager-names.csv",
        "observation-columns.csv",
    } <= names


def test_stage_forty_declares_the_label_category_ambiguity_report() -> None:
    from src.pipeline import build_extraction_review

    assert "label-category-ambiguity.csv" in build_extraction_review.REVIEW_OUTPUT_NAMES
    outputs = {path.name for path in stage_by_order(40).declared_outputs()}
    assert set(build_extraction_review.REVIEW_OUTPUT_NAMES) <= outputs


def test_stage_fifty_declares_entity_alias_and_every_pivot_matrix() -> None:
    names = {path.name for path in stage_by_order(50).declared_inputs()}
    assert "entity_alias.csv" in names
    assert {
        "family-pivot.csv",
        "wide-grain.csv",
        "category-field-precedence.csv",
        "wide-column-renames.csv",
        "wide-context-precedence.csv",
        "context-alias-fallback.csv",
        "record-family-routing.csv",
    } <= names


def test_stage_sixty_declares_both_data_definition_files() -> None:
    from src.flatten import load_star

    inputs = {path.resolve() for path in stage_by_order(60).declared_inputs()}
    assert load_star.DDL.resolve() in inputs
    assert load_star.WIDE_DDL.resolve() in inputs


def test_stage_eighty_declares_every_file_the_promotion_reads() -> None:
    names = {path.name for path in stage_by_order(80).declared_inputs()}
    assert {
        "METRIC-STANDARD-MEASURES.csv",
        "metric-semantic-map.csv",
        "document_fund_map.csv",
        "manager_master.csv",
        "fund_master.csv",
    } <= names


def test_the_gate_stages_declare_the_batch_marker_and_no_retired_lineage_file() -> None:
    """The gate reads the batch marker, the batches it names, and the gated
    tables. The round-02 lineage files and the three header templates it held
    them to are retired, so no stage may declare one."""

    from src.load import validate_round02_promotion as gate

    marker = (
        gate.DEFAULT_WORKING_DIR / matrices.resolve(gate.GATE_ROUTE, "lean_marker")
    ).resolve()
    for order in (90, 105, 140):
        inputs = stage_by_order(order).declared_inputs()
        assert marker in {path.resolve() for path in inputs}, f"stage {order}"
        names = {path.name for path in inputs}
        assert not any(name.startswith("round-02-") for name in names), f"stage {order}"
        assert names.isdisjoint(
            {
                "adjudication_template.csv",
                "audit_template.csv",
                "audit_adjudication_template.csv",
            }
        ), f"stage {order}"
    assert not hasattr(release, "legacy_lineage_inputs")
    assert not hasattr(release, "LEGACY_LINEAGE_READS")


def test_stage_one_hundred_declares_the_attribute_changes_and_the_quality_rules() -> None:
    from src.pipeline import build_integrated_universe

    inputs = {path.resolve() for path in stage_by_order(100).declared_inputs()}
    assert build_integrated_universe.ATTRIBUTE_CHANGES_PATH.resolve() in inputs
    assert build_integrated_universe.QUALITY_CONFIG.resolve() in inputs


def test_stage_one_hundred_ten_drops_the_files_it_never_opens() -> None:
    names = {path.name for path in stage_by_order(110).declared_inputs()}
    assert "quality_rules.yml" in names
    assert "fact_observation.csv" in names
    for absent in (
        "document_manager_map.csv",
        "fund_observations.csv",
        "benchmark_returns.csv",
        "synthetic_parameters.csv",
        "defect_injections.csv",
        "gap-ledger.csv",
        "cell-lineage.csv",
        "reconciliation-results.csv",
        "benchmark-policy.csv",
        "defect-periods.csv",
        "defect-quality-results.csv",
        "detection-scorecard.csv",
    ):
        assert absent not in names


def test_stage_one_hundred_twenty_declares_the_quality_rules() -> None:
    assert release.QUALITY_RULES in stage_by_order(120).declared_inputs()


def test_stage_one_hundred_thirty_declares_what_it_reads_and_no_more() -> None:
    names = {path.name for path in stage_by_order(130).declared_inputs() if path.parent != TRANSFORMATIONS}
    assert "promotion-category-mismatches.csv" in names
    assert "manager_observations.csv" not in names
    assert "fund_cashflows.csv" not in names


# ---------------------------------------------------------------------------
# The corpus is a release artifact (A6-03)


def test_the_corpus_stage_runs_before_the_scope_record_and_writes_both_corpus_files() -> None:
    """The closing gate judges pdf-wide-records.csv, so the release writes it.

    publish_corpus ran outside the release and the file it left behind was
    whatever the last extraction run wrote; the gate then failed on data the
    rounds no longer contained. The stage sits before the scope record, which
    checks the backlog ledger this stage writes against the finals."""

    item = stage_by_order(3)
    assert item.stage_id == "corpus-publication"
    assert item.order < stage_by_order(5).order < stage_by_order(10).order
    assert set(item.declared_outputs()) == {
        csv_workflow.published_records(),
        csv_workflow.published_coverage(),
        csv_workflow.qualifier_backlog_ledger(),
    }
    inputs = set(item.declared_inputs())
    assert set(release.active_worklists()) <= inputs
    for route in csv_workflow.ROUTES:
        if csv_workflow.round_records(route).is_file():
            assert csv_workflow.round_records(route) in inputs, route
            assert csv_workflow.round_coverage(route) in inputs, route
    for route, file_id in release.scope_documents():
        records, coverage = csv_workflow.final_paths(route, file_id)
        if records.is_file():
            assert records in inputs and coverage in inputs, f"{route}/{file_id}"
    assert csv_workflow.published_records() not in inputs


def test_both_corpus_files_are_governed_outputs() -> None:
    assert set(release.CORPUS_OUTPUTS) <= set(release.GOVERNED_OUTPUTS)
    governed = set(matrices.mapping(release.GOVERNED))
    for path in release.CORPUS_OUTPUTS:
        assert path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix() in governed


# ---------------------------------------------------------------------------
# Inputs derived from the module's own constants (A5-07, A6-07, A6-08, A5-08)


def test_the_gate_stages_declare_every_gated_table_and_no_output() -> None:
    from src.load import validate_round02_promotion as gate

    gated = {(release.CSV_DIR / entry[0]).resolve() for entry in gate.GATED_TABLES.values()}
    for order in (90, 105):
        item = stage_by_order(order)
        assert item.declared_outputs() == (), f"stage {order}"
        assert gated <= {path.resolve() for path in item.declared_inputs()}, f"stage {order}"


def test_module_paths_reads_the_files_a_module_names_through_its_constants() -> None:
    from src.pipeline import build_reviewer_publication as module

    found = release.module_paths(module)
    assert module.TABLE_DIR / "fact_observation.csv" in found
    assert module.EXTRACTED_FUND_DIR / "fund_periods.csv" in found
    assert module.AUDIT_DIR / "promotion-category-mismatches.csv" in found
    assert module.OBSERVATION_OUTPUT in found
    assert all(path.suffix for path in found)


def test_stage_one_hundred_thirty_inputs_are_derived_from_the_module() -> None:
    """Stage 130 read nine files it never declared, so a read the module adds
    now reaches the receipt without a hand list being updated."""

    from src.catalog.simple_pdf_extraction import fund_attributes
    from src.pipeline import build_reviewer_publication as module

    inputs = stage_by_order(130).declared_inputs()
    files = {path.resolve() for path in inputs if path.resolve().parent != TRANSFORMATIONS}
    expected = {
        path.resolve()
        for path in release.module_paths(module) - set(release.REVIEWER_OUTPUTS)
    } | {fund_attributes.MATRIX.resolve()}
    assert files == expected
    assert (module.EXTRACTED_FUND_DIR / "fund_periods.csv").resolve() in files
    assert (module.AUDIT_DIR / "promotion-category-mismatches.csv").resolve() in files
    assert {
        "summary-statistics",
        "status-precedence",
        "attribute-origin-vocabulary",
        "reviewer-promotion-status",
        "coverage-population",
        "record-preference-order",
    } <= matrix_paths(130)


def test_stage_one_hundred_forty_declares_the_ddl_the_loader_matrices_and_the_gate_files() -> None:
    from src.load import load_csv_to_duckdb as loader
    from src.load import validate_round02_promotion as gate

    inputs = {path.resolve() for path in stage_by_order(140).declared_inputs()}
    for ddl in loader.DDL_FILES:
        assert ddl.resolve() in inputs
    assert {loader.PARITY_NULLS, loader.LOAD_NULLS, loader.MISSING_INPUTS} <= matrix_paths(140)
    assert {
        (release.CSV_DIR / filename).resolve()
        for filename in loader.TABLE_FILES.values()
        if (release.CSV_DIR / filename).is_file()
    } <= inputs
    for path in (
        gate.DEFAULT_PUBLIC_MARKET_AUDIT_DIR / "source_file_inventory.csv",
        gate.DEFAULT_PUBLIC_MARKET_AUDIT_DIR / "quality_results.csv",
        gate.DEFAULT_PUBLIC_MARKET_STAGING_DIR / "benchmark_master_candidates.csv",
        gate.DEFAULT_BENCHMARK_POLICY,
    ):
        assert path.resolve() in inputs, path.name


# ---------------------------------------------------------------------------
# The scope the release states


def test_the_scope_record_states_assigned_finished_and_unfinished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worklists = tmp_path / "worklists" / "active"
    worklists.mkdir(parents=True)
    with (worklists / "01-route.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file_id"], lineterminator="\n")
        writer.writeheader()
        writer.writerows([{"file_id": "SRC001"}, {"file_id": "SRC002"}])
    working = tmp_path / "working"
    (working / "01-route" / "SRC001").mkdir(parents=True)
    # The stage reads the finals in scope to rebuild the backlog table, so the
    # fixture final carries the record header it is held to and no rows.
    (working / "01-route" / "SRC001" / "records-final.csv").write_text(
        ",".join(f'"{column}"' for column in RECORD_COLUMNS) + "\n", encoding="utf-8"
    )
    ledger = tmp_path / "ledgers" / "pipeline" / "qualifier-backlog.csv"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        ",".join(f'"{column}"' for column in csv_workflow.QUALIFIER_BACKLOG_COLUMNS) + "\n",
        encoding="utf-8",
    )
    record = tmp_path / "extraction-scope.csv"
    monkeypatch.setattr(release, "WORKLIST_ROOT", tmp_path / "worklists")
    monkeypatch.setattr(combine_extracted_raw, "WORKING_DIR", working)
    monkeypatch.setattr(csv_workflow, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(release, "SCOPE_RECORD", record)

    counts = release.write_extraction_scope()

    assert counts == {"assigned": 2, "finished": 1, "unfinished": 1, "backlog_rows": 0}
    rows = list(csv.DictReader(record.open(encoding="utf-8-sig")))
    assert rows[0]["assigned"] == "2"
    assert rows[0]["unfinished"] == "1"
    assert rows[0]["unfinished_documents"] == "SRC002"
    assert rows[0]["backlog_rows"] == "0"


def test_the_scope_stage_refuses_a_backlog_ledger_the_finals_contradict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ledger downstream reads is the backlog the finals carry today.

    Publication writes it; this stage derives it again and refuses a ledger that
    has drifted, so a stale list cannot pass as the live one.
    """

    worklists = tmp_path / "worklists" / "active"
    worklists.mkdir(parents=True)
    (worklists / "01-route.csv").write_text("file_id\n", encoding="utf-8")
    monkeypatch.setattr(release, "WORKLIST_ROOT", tmp_path / "worklists")
    monkeypatch.setattr(combine_extracted_raw, "WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr(csv_workflow, "PROJECT_ROOT", tmp_path)

    with pytest.raises(release.ReleaseError, match="is absent"):
        release.require_backlog_ledger([])

    ledger = csv_workflow.qualifier_backlog_ledger()
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "route,file_id,metric_category,blank_dimension,row_count\n"
        "01-route,SRC001,nav,value_scope,7\n",
        encoding="utf-8",
    )
    with pytest.raises(release.ReleaseError, match="backlog rows"):
        release.require_backlog_ledger(release.scope_qualifier_backlog())


def test_stage_five_declares_the_finals_and_the_backlog_ledger() -> None:
    declared_inputs = set(stage_by_order(5).declared_inputs())
    assert set(release.active_worklists()) <= declared_inputs
    assert set(release.scope_final_files()) <= declared_inputs
    assert csv_workflow.qualifier_backlog_ledger() in declared_inputs or not (
        csv_workflow.qualifier_backlog_ledger().is_file()
    )


def test_the_release_states_the_scope_the_active_worklists_assign() -> None:
    assigned = sum(len(release.csv_rows(path)) for path in release.active_worklists())
    counts = {
        row["route"]: row for row in release.csv_rows(release.SCOPE_RECORD)
    } if release.SCOPE_RECORD.is_file() else {}
    if counts:
        assert sum(int(row["assigned"]) for row in counts.values()) == assigned


# ---------------------------------------------------------------------------
# Attribution held across two publications


def _round_file(path: Path, rows: list[dict[str, str]]) -> None:
    columns = ["file_id", "source_page", "source_row_label", "source_column_label",
               "source_occurrence", "record_family", "value_raw", "extractor_model"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _raw_file(path: Path, rows: list[dict[str, str]]) -> None:
    columns = ["file_id", "source_page", "source_row_label", "source_column_label",
               "source_occurrence", "record_family", "value_raw"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: row[key] for key in columns} for row in rows)


def _attribution_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_model: str) -> None:
    from src.flatten import flatten_extracted

    row = {
        "file_id": "SRC001",
        "source_page": "1",
        "source_row_label": "Net IRR",
        "source_column_label": "Value",
        "source_occurrence": "1",
        "record_family": "performance",
        "value_raw": "12.0%",
        "extractor_model": "model-a",
    }
    rounds = tmp_path / "rounds"
    rounds.mkdir()
    raw = tmp_path / "raw"
    raw.mkdir()
    prior = tmp_path / "prior.csv"
    _round_file(prior, [row])
    _round_file(rounds / "01-route-records.csv", [{**row, "extractor_model": new_model}])
    _raw_file(raw / "01-route.csv", [row])
    monkeypatch.setattr(release, "raw_files", lambda: [raw / "01-route.csv"])
    monkeypatch.setattr(flatten_extracted, "ROUNDS_DIR", rounds)
    monkeypatch.setattr(release, "previous_object", lambda path, receipts=None: prior)


def test_republishing_may_not_re_attribute_an_unchanged_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _attribution_fixture(tmp_path, monkeypatch, "model-b")
    with pytest.raises(release.ReleaseError) as error:
        release.verify_raw_round_relation()
    assert "extractor_model" in str(error.value)


def test_an_unchanged_attribution_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _attribution_fixture(tmp_path, monkeypatch, "model-a")
    assert release.verify_raw_round_relation() == 1


def test_a_blank_attribution_still_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _attribution_fixture(tmp_path, monkeypatch, "")
    with pytest.raises(release.ReleaseError) as error:
        release.verify_raw_round_relation()
    assert "attribution" in str(error.value)


# ---------------------------------------------------------------------------
# One FAIL line for every error a stage raises


def test_main_reports_each_stage_error_as_one_fail_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from src.catalog.simple_pdf_extraction.csv_workflow import ContractFailure
    from src.flatten.flatten_extracted import FlattenError
    from src.pipeline.build_integrated_universe import IntegrationError
    from src.pipeline.combine_extracted_raw import CombineError
    from src.pipeline.transformation_lineage import LineageError as Lineage

    monkeypatch.setattr("sys.argv", ["publish_review_release"])
    for error in (CombineError, ContractFailure, FlattenError, Lineage, IntegrationError,
                  release.ReleaseError, release.duckdb.ConstraintException):
        def raise_it(exc=error) -> None:
            raise exc("stage 10 refused")

        monkeypatch.setattr(release, "publish", raise_it)
        assert release.main() == 1
        printed = capsys.readouterr().out
        assert printed.startswith("FAIL: "), error.__name__
        assert "stage 10 refused" in printed
        assert "Traceback" not in printed


def test_a_stage_error_is_reported_with_the_stage_that_raised_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.pipeline.combine_extracted_raw import CombineError

    def refuse(**kwargs: object) -> None:
        raise CombineError("two documents not adjudicated")

    monkeypatch.setattr(release, "run_stage", refuse)
    with pytest.raises(release.ReleaseError) as error:
        release.stage(10, "raw-combination", "command", [], [], lambda: 0)
    assert "010 raw-combination" in str(error.value)
    assert "CombineError" in str(error.value)
