from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.load import build_normalized_holdings as normalized
from src.load import promote_extracted_to_fund_level as promotion
from src.load.validate_normalized_holdings import validate

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def source_model():
    return normalized.build_source_rows()


def test_every_source_holding_maps_or_refuses_exactly_once(source_model) -> None:
    tables, refusals = source_model
    with (PROJECT_ROOT / "data/extracted/tables/fact_holding.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        source = list(csv.DictReader(handle))
    mapped = [row["source_holding_id"] for row in tables["fund_position"]]
    refused = [row["source_holding_id"] for row in refusals]
    source_ids = {row["holding_id"] for row in source}
    assert len(source) == 487
    assert len(mapped) == 454
    assert len(refused) == 33
    assert set(mapped).isdisjoint(refused)
    assert set(mapped) | set(refused) == source_ids
    assert {row["refusal_code"] for row in refusals} == {
        "NON_INVESTEE_AGGREGATE", "NON_POSITION_SUMMARY"
    }


def test_reviewed_owner_model_repairs_owner_target_confusion(source_model) -> None:
    tables, _ = source_model
    owners = {row["owner_id"]: row for row in tables["investment_owner"]}
    positions = tables["fund_position"]
    assert owners["OWNER_FUND_1060"]["owner_fund_id"] == "FUND_1060"
    assert owners["OWNER_FUND_1060"]["parent_owner_id"] == "OWNER_UT_SYSTEM"
    src356 = [row for row in positions if row["source_document_id"] == "SRC356"]
    assert len(src356) == 24
    assert {row["owner_id"] for row in src356} == {"OWNER_FUND_1060"}
    assert {row["owner_fund_id"] for row in src356} == {"FUND_1060"}
    assert all(row["owner_fund_id"] != row["instrument_id"] for row in src356)
    src034 = [row for row in positions if row["source_document_id"] == "SRC034"]
    assert len(src034) == 7
    assert {row["owner_id"] for row in src034} == {"OWNER_SRC034_VERSA_COMBINED"}
    assert {row["owner_fund_id"] for row in src034} == {""}


def test_market_value_and_portfolio_weight_keep_their_meaning(source_model) -> None:
    tables, _ = source_model
    positions = tables["fund_position"]
    src356 = [row for row in positions if row["source_document_id"] == "SRC356"]
    assert all(row["market_value"] for row in src356)
    assert all(not row["fair_value"] for row in src356)
    src034 = [row for row in positions if row["source_document_id"] == "SRC034"]
    fractions = sorted(float(row["portfolio_weight_fraction"]) for row in src034)
    assert fractions[0] == pytest.approx(0.0023)
    assert fractions[-1] == pytest.approx(0.3422)
    assert all(not row["fund_ownership_fraction"] for row in src034)


def test_debt_security_titles_do_not_become_company_targets(source_model) -> None:
    tables, _ = source_model
    targets = {row["target_id"]: row for row in tables["investment_target"]}
    instruments = tables["investment_instrument"]
    debt = [
        row
        for row in instruments
        if row["security_title_raw"].startswith(("FNMA", "GNMA", "United States Treasury"))
        or row["security_title_raw"] in {"CRC CF 5/4/2026", "Gate SME Ser 144A 12/15/2025"}
    ]
    assert len(debt) == 10
    assert {row["instrument_kind"] for row in debt} == {"OTHER_DEBT"}
    for instrument in debt:
        target = targets[instrument["target_id"]]
        assert target["target_kind"] == "UNRESOLVED"
        assert target["company_entity_id"] == ""


def test_aggregate_derivative_rows_remain_source_evidence_only(source_model) -> None:
    tables, refusals = source_model
    src377_refusals = [row for row in refusals if row["source_document_id"] == "SRC377"]
    assert len(src377_refusals) == 8
    assert not any(row["source_document_id"] == "SRC377" for row in tables["fund_position"])


def test_statement_summaries_do_not_duplicate_derivative_positions(source_model) -> None:
    tables, refusals = source_model
    positions = [
        row for row in tables["fund_position"]
        if row["source_document_id"] == "SRC407" and row["position_class"] == "DERIVATIVE"
    ]
    assert len(positions) == 4
    assert sorted(float(row["fair_value"]) for row in positions) == [
        -654668.0, -621670.0, -502856.0, 1518309.0
    ]
    summary_refusals = [
        row for row in refusals
        if row["source_document_id"] == "SRC407"
        and row["refusal_code"] == "NON_POSITION_SUMMARY"
    ]
    assert {row["holding_label"] for row in summary_refusals} == {
        "Equity Forward Contract", "Foreign Currency Forward Contract"
    }


def test_derivative_counterparties_are_not_portfolio_companies(source_model) -> None:
    tables, _ = source_model
    targets = {row["target_id"]: row for row in tables["investment_target"]}
    instruments = {row["instrument_id"]: row for row in tables["investment_instrument"]}
    counterparties = {
        targets[instruments[row["instrument_id"]]["target_id"]]["canonical_name"]:
        targets[instruments[row["instrument_id"]]["target_id"]]["target_kind"]
        for row in tables["fund_position"]
        if row["source_document_id"] == "SRC407" and row["position_class"] == "DERIVATIVE"
    }
    assert counterparties == {
        "Lloyds Bank plc.": "COUNTERPARTY",
        "Nomura Global Financial Products Inc.": "COUNTERPARTY",
    }


def test_legacy_holding_projection_never_confuses_owner_and_investee() -> None:
    holdings = normalized._read(PROJECT_ROOT / "data/extracted/tables/fact_holding.csv")
    observations = normalized._read(PROJECT_ROOT / "data/extracted/tables/fact_observation.csv")
    projected = promotion.build_fund_holdings(holdings, observations)
    assert len(projected) == 24
    assert {row["fund_id"] for row in projected} == {"FUND_1060"}
    assert all(row["portfolio_company_id"] != row["fund_id"] for row in projected)
    assert all(not row["fair_value"] for row in projected)
    assert all(not row["ownership_percent"] for row in projected)


def test_source_tables_load_and_return_zero_normalized_findings(tmp_path: Path) -> None:
    output = tmp_path / "normalized"
    refusal_path = tmp_path / "refusals.csv"
    counts = normalized.write_source(output, refusal_path)
    result = validate(
        output,
        fund_master_path=PROJECT_ROOT / "data/csv/fund_master.csv",
        fact_holding_path=PROJECT_ROOT / "data/extracted/tables/fact_holding.csv",
        refusal_path=refusal_path,
    )
    assert counts["fund_position.csv"] == 454
    assert result["mapped_source_positions"] == 454
    assert result["refusals"] == 33
    assert result["qa_errors"] == 0
    assert result["qa_warnings"] == 0


def test_generated_compatibility_holding_gets_owner_target_instrument_position() -> None:
    masters = [
        {
            "fund_id": "FUND_SYNTH_TEST",
            "fund_name": "Synthetic Test Fund",
            "provenance_type": "SYNTHETIC",
            "synthetic_parameter_set_id": "TEST_SET",
        }
    ]
    holdings = [
        {
            "holding_id": "HOLD_TEST",
            "fund_id": "FUND_SYNTH_TEST",
            "portfolio_company_id": "COMPANY_TEST",
            "portfolio_company_name": "Synthetic Borrower",
            "instrument_id": "INSTR_TEST",
            "instrument_name": "Unitranche Loan",
            "security_type": "Unitranche",
            "currency": "USD",
            "cost": "90",
            "fair_value": "100",
            "principal_amount": "90",
            "interest_rate": "0.10",
            "spread_bps": "500",
            "maturity_date": "2030-12-31",
            "ownership_percent": "0.25",
            "as_of_date": "2026-06-30",
            "date_role": "as_of",
            "date_precision": "day",
            "provenance_type": "SYNTHETIC",
            "synthetic_parameter_set_id": "TEST_SET",
            "record_status": "ACTIVE",
        }
    ]
    tables = normalized.build_flat_rows(holdings, masters, origin_type="SYNTHETIC_FIXTURE")
    assert len(tables["investment_owner"]) == 1
    assert len(tables["investment_target"]) == 1
    assert len(tables["investment_instrument"]) == 1
    assert len(tables["fund_position"]) == 1
    position = tables["fund_position"][0]
    assert position["owner_fund_id"] == "FUND_SYNTH_TEST"
    assert position["position_class"] == "DEBT_INVESTMENT"
    assert position["fund_ownership_fraction"] == "0.25"
    assert tables["investment_instrument"][0]["instrument_kind"] == "LOAN"
