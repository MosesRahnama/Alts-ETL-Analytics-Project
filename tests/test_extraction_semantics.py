"""Source-context and omission checks for original and incremental extraction."""

import csv
from pathlib import Path
from unittest import mock

import pytest

from src.catalog.simple_pdf_extraction import csv_workflow as workflow
from src.catalog.simple_pdf_extraction import semantic_checks as semantic
from src.catalog.simple_pdf_extraction.build_csv_pipeline import source_context_rules
from src.flatten.flatten_extracted import parse_value


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("value,quote,accepted", [
    ("6", "six percent; 6.9 percent", False),
    ("3", "three percent; 3.6 percent", False),
    ("43", "143 million", False),
    ("14", "target 1444", False),
    ("16.1", "actual 16.13", False),
    ("1", "1,234", False),
    ("234", "1,234", False),
    ("10.09%", "and10.09%", True),
    ("(1,234)", "Amount (1,234)", True),
    ("six", "six percent", True),
    ("six", "sixty percent", False),
])
def test_evidence_requires_a_complete_printed_value(value, quote, accepted):
    assert semantic.complete_value_in_quote(value, quote) is accepted


@pytest.mark.parametrize("word,number", [("six", "6"), ("three", "3")])
def test_number_words_preserve_numeric_meaning(word, number):
    assert parse_value(word, "%") == parse_value(number, "%")


def codes(rows, **kwargs):
    return {code for _, code, _ in semantic.record_errors(rows, {}, **kwargs)}


def test_repeated_marker_resolves_to_its_table_not_a_neighbour():
    fact = {"record_family": "performance_observation", "source_page": "1",
            "source_table": "Fund returns", "definition_keys": "1"}
    definition = {"record_family": "definition_context", "source_page": "1",
                  "source_table": "Fund returns", "definition_keys": "1",
                  "text_raw": "Net of management fees"}
    other = dict(definition, source_table="Benchmark returns", text_raw="Gross returns")
    assert "DEFINITION_AMBIGUOUS" not in codes([fact, definition, other])
    assert "DEFINITION_AMBIGUOUS" in codes([dict(fact, source_table=""), definition, other])


def test_method_refinement_requires_support_in_the_constructed_document():
    fact = {"record_family": "performance_observation", "source_page": "1",
            "source_table": "Returns", "source_column_label": "Time-weighted return",
            "metric_category": "return", "metric_value_raw": "5.0%",
            "method": "modified_dietz", "definition_keys": "1"}
    definition = {"record_family": "definition_context", "source_page": "1",
                  "source_table": "Returns", "definition_keys": "1",
                  "text_raw": "Returns use the Modified Dietz method."}
    assert "METHOD_HEADER" not in codes([fact, definition])
    assert "METHOD_HEADER" in codes([fact])
    assert "METHOD_HEADER" in codes([fact, dict(definition, text_raw="Values in USD")])
    assert "METHOD_HEADER" not in codes([fact], whole_document=False)


def test_header_fee_basis_cannot_be_relabelled():
    fact = {"metric_category": "return", "metric_value_raw": "5.0%",
            "source_column_label": "Net Return", "fee_basis": "gross"}
    assert "FEE_HEADER" in codes([fact])
    assert "FEE_HEADER" not in codes([dict(fact, fee_basis="net")])


@pytest.mark.parametrize("label", ["Total assets", "Capital contributions", "Other expenses", "Partners' capital, January 1, 2025"])
def test_statement_labels_are_not_institutions(label):
    row = {"record_family": "financial_statement_observation", "subject_name": label,
           "subject_type": "reporting_entity", "metric_category": "total_assets", "metric_value_raw": "10"}
    assert "STATEMENT_LABEL_IDENTITY" in codes([row])
    assert "STATEMENT_LABEL_IDENTITY" not in codes([dict(row, subject_type="other_printed_scope")])


def test_one_named_fund_is_distinct_from_a_combined_statement():
    row = {"record_family": "financial_statement_observation", "subject_type": "reporting_entity",
           "subject_name": "Example Fund IV, L.P."}
    assert "FUND_ENTITY_TYPE" in codes([row])
    assert "FUND_ENTITY_TYPE" not in codes([dict(row, subject_name="Example Fund I and Example Fund II, L.P.")])
    assert "FUND_ENTITY_TYPE" not in codes([dict(row, subject_type="fund")])


def test_normalized_statement_items_do_not_create_entities():
    with (ROOT / "data/extracted/tables/fact_observation.csv").open(encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))
    items = [r for r in records if r["record_family"] == "financial_statement_observation"
             and semantic.matches("statement_label", r["subject_name"])]
    assert items
    assert all(r["subject_type"] == "other_printed_scope" and not r["subject_entity_id"] for r in items)


@pytest.mark.parametrize("route,file_id,agent,expected", [
    ("02-performance", "SRC594", "A", "FUND_COMPONENT_SCOPE"),
    ("02-performance", "SRC594", "B", "FUND_COMPONENT_SCOPE"),
    ("06-statements-and-economics", "SRC463", "A", "ACCOUNT_OWNER"),
    ("06-statements-and-economics", "SRC463", "A", "RELATIVE_DATE"),
    ("01-financials", "SRC102", "A", "COMPARATIVE_DATE"),
    ("01-financials", "SRC102", "B", "INVESTOR_SCOPE"),
])
def test_original_mistakes_fail_the_shared_rule(route, file_id, agent, expected):
    routing = workflow.routing_for(route, file_id)
    path, _ = workflow.candidate_paths(route, file_id, agent)
    records = workflow.read_strict_csv(path, workflow.RECORD_COLUMNS)
    errors = semantic.record_errors(records, workflow.source_page_texts(routing))
    assert expected in {code for _, code, _ in errors}
    final, _ = workflow.final_paths(route, file_id)
    records = workflow.read_strict_csv(final, workflow.RECORD_COLUMNS)
    assert semantic.record_errors(records, workflow.source_page_texts(routing)) == []


def completeness(records=(), *, status="REFERENCE_ONLY", note="", text="", shape=(0, 0)):
    routing = {"file_id": "TEST", "page_count": "1", "product_tier": "CORE"}
    coverage = [{"source_page": "1", "page_status": status,
                 "layout_checked": "YES", "notes": note}]
    with mock.patch.object(workflow, "grid_built", return_value=True), \
         mock.patch.object(workflow, "grid_page_shape", return_value={1: shape}), \
         mock.patch.object(workflow, "source_page_texts", return_value={1: text}):
        return workflow.completeness_errors(routing, records, coverage)


@pytest.mark.parametrize("status", ["REFERENCE_ONLY", "NO_ELIGIBLE_DATA", "DEFERRED_BY_SCOPE"])
def test_zero_page_status_never_bypasses_table_signals(status):
    assert any("zero observations" in e for e in completeness(status=status, shape=(60, 8)))


def test_reference_definition_page_requires_definition_records():
    errors = completeness(text="Glossary of terms\nNAV means net asset value")
    assert any("DEFINITION_OMISSION" in e for e in errors)


def test_partial_table_requires_a_specific_exclusion():
    records = [{"source_page": "1", "record_family": "performance_observation"}]
    assert any("partly extracted" in e for e in completeness(records, shape=(60, 8)))
    reason = "PARTIAL_BY_SCOPE: Remaining columns contain employee counts outside permitted fund metric categories."
    assert completeness(records, status="ELIGIBLE_DATA_EXTRACTED", note=reason, shape=(60, 8)) == []
    assert completeness(records, note="PARTIAL_BY_SCOPE: done", shape=(60, 8))


@pytest.mark.parametrize("status", ["UNREADABLE", "DEFERRED_BY_SCOPE"])
def test_unfinished_core_page_is_not_final(status):
    assert any("not completed extraction" in e for e in completeness(status=status))


def test_every_active_final_passes_shared_checks():
    documents = []
    for route in workflow.ROUTES:
        for item in workflow.worklist_for_scope(route, "active"):
            file_id = item["file_id"]
            _, _, errors = workflow.validate_final_data(route, file_id)
            assert not errors, (route, file_id, errors)
            documents.append(file_id)
    assert {"SRC099", "SRC376", "SRC463", "SRC594", "SRC602"} <= set(documents)
    assert len(documents) >= 34


def test_all_generated_roles_share_source_context_rules():
    root = ROOT / "instructions/01-pdf-extraction-csv/dispatch-prompts"
    for route in workflow.ROUTES:
        prompts = list((root / route).glob("*.md"))
        role_prompts = [p for p in prompts if p.name[:2] in {"01", "02", "03", "04", "05"}]
        assert len(role_prompts) == 5
        for path in role_prompts:
            content = path.read_text(encoding="utf-8-sig")
            assert source_context_rules() in content, path
            assert "harmless classification" not in content, path
