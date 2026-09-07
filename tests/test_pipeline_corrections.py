"""Source-date, classification, cash-flow, and published arithmetic regressions."""

from decimal import Decimal
from datetime import date
from unittest.mock import patch

import pytest

from src.flatten.flatten_extracted import parse_date, observation_currency, parse_scale
from src.load import promote_extracted_to_fund_level as promote
from src.market_data import curate_public_markets as market
from src.quality.run_fund_checks import _numeric_result
from src.pipeline.build_integrated_universe import _populate_calculated_irr, IntegrationError
from src.common.finance import xirr


def test_slash_dates_require_source_order_or_an_unambiguous_day():
    assert parse_date("03/07/2014", "SRC463") == ("2014-07-03", "day")
    assert parse_date("28/04/2014", "SRC463") == ("2014-04-28", "day")
    assert parse_date("03/07/2014") == ("", "unknown")
    assert parse_date("12/31/2020") == ("2020-12-31", "day")
    assert parse_date("31/02/2020", "SRC463") == ("", "unknown")
    assert parse_date("Last Quarter", "SRC463") == ("", "unknown")


def test_market_strategy_names_use_the_matrix_key():
    expected = {row["input_value"] for row in market.matrices.rows_in(
        market.STRATEGY_BENCHMARKS, "canonical_strategy")}
    assert {row[0] for row in market.STRATEGY_MAP} == expected
    assert all(row[0] != "canonical_strategy" and row[1] == "" for row in market.STRATEGY_MAP)


def test_cashflow_rules_do_not_also_promote_cumulative_distributions():
    row = {"record_family": "cash_flow_observation", "metric_name": "Distribution"}
    assert promote.semantic_rule_for(row, "distribution", "fund_periods") is None
    assert promote.semantic_rule_for(row, "distribution", "fund_cashflows")


def test_conflicting_semantic_rules_fail_before_target_selection():
    rule = {key: "" for key in ("source_category", "record_family", "subject_type",
        "value_scope", "method", "fee_basis", "unit", "label_pattern")}
    rule.update(input_value="one", output_value="one", priority="100",
                target_table="fund_periods", target_column="nav")
    other = dict(rule, input_value="two", output_value="two", target_table="fund_cashflows")
    with patch.object(promote.matrices, "load", return_value=[rule, other]):
        with pytest.raises(ValueError, match="Conflicting semantic rules"):
            promote.semantic_rule_for({}, "nav", "fund_periods")


def test_cashflow_total_replaces_components_and_excludes_cumulative_total():
    base = {"record_family": "cash_flow_observation", "document_id": "SRC463",
            "source_page": "2", "source_table": "Capital Call", "currency": "EUR",
            "subject_entity_id": "LP_1", "as_of_date": "2014-04-28",
            "source_row_label": "28/04/2014"}
    rows = [dict(base, observation_id=str(i), source_column_label=label, value_numeric=value)
            for i, (label, value) in enumerate([
                ("Capital Contribution", "240"), ("Loan Commitment", "449760"),
                ("TOTAL", "450000")])]
    rows.append(dict(rows[-1], observation_id="sum", source_row_label="TOTAL"))
    chosen = promote.cashflow_event_rows(rows)
    assert [r["observation_id"] for r in chosen] == ["2"]
    assert promote.economic_cashflow_amount(chosen[0], "capital_call") == "-450000"
    assert len(rows) == 4 and rows[2]["value_numeric"] == "450000"


def test_published_quality_difference_reconciles_its_displayed_operands():
    row = _numeric_result(True, 9849573173.036812, 9849573173.03681,
                          0.0000019073486328125, 0.01, "Printed tolerance")
    assert Decimal(row["difference"]) == Decimal(row["actual_value"]) - Decimal(row["expected_value"])
    assert row["status"] == "PASS"


def test_completed_irr_excludes_an_investors_separate_cashflows():
    period = {"fund_id": "FUND_1", "as_of_date": "2021-01-01", "nav": "110", "currency": "USD"}
    call = {"fund_id": "FUND_1", "cashflow_date": "2020-01-01", "amount": "-100", "currency": "USD"}
    unrelated = dict(call, lp_id="LP_1", amount="-100000", currency="EUR")
    _populate_calculated_irr([period], [call, unrelated])
    expected = xirr([(date(2020, 1, 1), -100), (date(2021, 1, 1), 110)])
    assert float(period["calculated_irr"]) == pytest.approx(expected, abs=1e-10)
    with pytest.raises(IntegrationError, match="currency"):
        _populate_calculated_irr([period], [dict(call, currency="EUR")])


def test_explicit_fund_position_requires_and_carries_the_document_investor():
    fact = {"document_id": "SRC_TEST", "subject_entity_id": "FUND_1", "value_scope": "fund_position"}
    context = {"document_id": "SRC_TEST", "record_family": "document_context", "investor_entity_id": "LP_1"}
    assert promote.fund_position_context([context, fact])["FUND_1", "SRC_TEST"] == {
        "perspective": "lp_position", "lp_id": "LP_1"}
    with pytest.raises(ValueError, match="investor"):
        promote.fund_position_context([fact])
    with pytest.raises(ValueError, match="Conflicting"):
        promote.fund_position_context([context, fact, dict(fact, value_scope="fund_total")])


def test_source_master_discards_completed_values_without_source_evidence():
    stale = {"fund_id": "FUND_1", "fund_size": "999", "base_currency": "USD",
             "fund_size_currency": "USD", "fund_status": "ACTIVE_OR_UNKNOWN"}
    result = promote.source_master_fields([stale], [])[0]
    assert all(result[field] == "" for field in promote.matrices.mapping(promote.SOURCE_MASTER_FIELDS))
    source = {"subject_entity_id": "FUND_1", "metric_category": "fund_size",
              "value_numeric": "25", "currency": "EUR", "unit_scale_multiplier": "1000000",
              "observation_id": "OBS_1", "document_id": "SRC1", "source_page": "2"}
    result = promote.source_master_fields([stale], [source])[0]
    assert result["fund_size"] == "25000000"
    assert result["fund_size_currency"] == "EUR"
    assert result["base_currency"] == "" and "OBS_1" in result["source_anchor"]


def test_distribution_and_portfolio_yield_are_not_total_return_or_nav():
    base = {"subject_type": "fund", "record_family": "performance_observation", "unit": "%"}
    distribution = promote.semantic_rule_for(dict(base, metric_name="Annualized Distribution Rate"), "yield")
    investment = promote.semantic_rule_for(dict(base, metric_name="Weighted average investment yield"), "yield")
    assert distribution["output_value"] == "distribution_rate"
    assert investment["output_value"] == "weighted_average_investment_yield"
    assert distribution["target_table"] == investment["target_table"] == "fund_observations"
    loan = promote.semantic_rule_for(dict(base, document_id="SRC606", metric_name="Investments", value_scope="portfolio_total"), "commitment")
    assert loan["output_value"] == "portfolio_loan_commitments"
    assert loan["target_table"] == "fund_observations"

    other = promote.semantic_rule_for(dict(base, document_id="OTHER", metric_name="Investments", value_scope="portfolio_total"), "commitment")
    assert other["input_value"] != "RULE_LOAN_COMMITMENTS"


def test_portfolio_component_labels_are_not_fund_attributes():
    from src.catalog.simple_pdf_extraction import fund_attributes as fa
    assert not fa.attribute_scope_allowed({"value_scope": "allocation_bucket", "strategy": "Real Estate"})
    assert fa.attribute_scope_allowed({"value_scope": "fund_total", "strategy": "Real Estate"})


@pytest.mark.parametrize("change,error", [
    ({"field": "metric_value_raw"}, "cannot change"),
    ({"source_quote": ""}, "Incomplete evidence"),
    ({"evidence_page": "0"}, "Invalid physical page"),
])
def test_source_correction_refuses_numeric_edits_and_invalid_evidence(change, error):
    from src.catalog.simple_pdf_extraction import source_review as review
    rule = dict(zip(review.FIELDS, (
        "R1", "02-performance", "SRC1", "P1", "method", "", "modified_dietz",
        "1", "1", "Modified Dietz", "Printed method",
    )))
    with patch.object(review, "read", return_value=[dict(rule, **change)]):
        with pytest.raises(ValueError, match=error):
            review.plans()


def test_source_correction_identifiers_are_unique():
    from src.catalog.simple_pdf_extraction import source_review as review
    rule = dict(zip(review.FIELDS, (
        "R1", "02-performance", "SRC1", "P1", "method", "", "modified_dietz",
        "1", "1", "Modified Dietz", "Printed method",
    )))
    with patch.object(review, "read", return_value=[rule, dict(rule, pair_id="P2")]):
        with pytest.raises(ValueError, match="Duplicate source correction ID"):
            review.plans()


def test_source_correction_refuses_an_invalid_header(tmp_path):
    from src.catalog.simple_pdf_extraction import source_review as review
    path = tmp_path / "corrections.csv"
    path.write_text("rule_id,field\nR1,method\n", encoding="utf-8")
    with patch.object(review, "RULES", path):
        with pytest.raises(ValueError, match="header"):
            review.read(path)


@pytest.mark.parametrize("raw,heading,expected", [
    ("$29,323,226", "(Expressed in Canadian dollars)", "CAD"),
    ("$10", "Australian dollars in millions", "AUD"),
    ("EUR 10", "USD in thousands", "EUR"),
    ("€10", "US$ in millions", "EUR"),
    ("C$10", "$", "CAD"),
    ("10", "CAD in thousands", "CAD"),
    ("$10", "", "USD"),
])
def test_currency_codes_and_headings_resolve_ambiguous_dollar_symbols(raw, heading, expected):
    assert observation_currency(raw, heading) == expected
    assert parse_scale("CAD in thousands") == ("CAD", "thousands", 1000.0)


def test_fund_periods_retain_currency_and_refuse_mixed_amounts():
    fact = {"subject_entity_id": "FUND_1", "subject_type": "fund", "document_id": "SRC_TEST",
            "as_of_date": "2016-12-20", "record_family": "financial_statement_observation",
            "metric_category": "commitment", "metric_name": "Committed capital", "value_numeric": "29323226",
            "value_kind": "currency", "value_scope": "fund_total", "currency": "CAD", "observation_id": "OBS1"}
    rows, _, errors = promote.build_fund_periods([fact])
    assert not errors and rows[0]["currency"] == "CAD" and rows[0]["commitment"] == "29323226"
    with pytest.raises(ValueError, match="Conflicting monetary currencies"):
        promote.build_fund_periods([fact, dict(fact, observation_id="OBS2", currency="USD")])


def test_completion_does_not_relabel_foreign_amounts_as_target_currency():
    from src.pipeline import build_integrated_universe as integrated
    cfg = {"seed": 1, "as_of_date": "2025-12-31", "fund_size_fallback": 1000,
           "currency_fallback": "USD", "parameter_set_id": "TEST"}
    master = {"fund_id": "FUND_1", "vintage_year": "2015", "fund_size": "1000", "base_currency": "USD"}
    derived = {"paid_in_ratio_median": 0.6, "dpi_median": 0.5, "rvpi_median": 0.6}
    source = {"currency": "CAD", "commitment": "29323226", "paid_in_capital_itd": "20000000"}
    foreign = integrated._target_period(cfg, master, [source], derived, 0.1)
    absent = integrated._target_period(cfg, master, [], derived, 0.1)
    assert foreign == absent
    matched = integrated._target_period(cfg, master, [dict(source, currency="USD")], derived, 0.1)
    assert matched["currency"] == "USD" and float(matched["commitment"]) == 29323226


def test_jefferson_commitment_keeps_canadian_denomination_in_published_data():
    import csv
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    with (root / "data/extracted/tables/fact_observation.csv").open(encoding="utf-8-sig", newline="") as handle:
        observations = [r for r in csv.DictReader(handle) if r["document_id"] == "SRC102"
                        and r["subject_type"] == "fund" and r["metric_category"] == "commitment"]
    assert len(observations) == 1 and observations[0]["currency"] == "CAD"
    with (root / "data/extracted/fund-level/fund_periods.csv").open(encoding="utf-8-sig", newline="") as handle:
        periods = [r for r in csv.DictReader(handle) if r["fund_id"] == observations[0]["subject_entity_id"]]
    assert periods and all(r["currency"] == "CAD" for r in periods)
