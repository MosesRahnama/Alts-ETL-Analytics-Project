"""The promotion from extraction into the fund-level tables, and its gate.

Three things have to hold. Every promoted row names a fund and traces to a
document the gate accepted. Money reaches the analytical grain on one scale, so
a ratio built from two differently scaled cells cannot be a million times wrong.
And the gate refuses a row whose document is missing, which is the property that
makes the promotion evidence worth writing at all.
"""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from src.load import promote_extracted_to_fund_level as promote
from src.load.validate_round02_promotion import (
    PromotionGateError,
    validate_fund_model_extracted_rows,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSV_DIR = PROJECT_ROOT / "data" / "csv"
GATE_DIR = PROJECT_ROOT / "ledgers" / "promotion-gate" / "round02"


def read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


class MoneyScaleTests(unittest.TestCase):
    def test_a_currency_cell_carries_its_scale_into_the_analytical_grain(self) -> None:
        row = {
            "value_numeric": "1586.4", "value_kind": "currency",
            "currency": "USD", "unit_scale_multiplier": "1000000",
        }
        self.assertEqual(promote.scaled_amount(row), "1586400000")

    def test_a_dollar_sign_in_the_heading_still_counts_as_money(self) -> None:
        """A schedule that prints `$` once above the column and bare numbers
        under it yields value_kind `number`, and the currency code is what
        settles it. Reading value_kind alone dropped 213 real amounts."""
        row = {
            "value_numeric": "50000000", "value_kind": "number",
            "currency": "USD", "unit_scale_multiplier": "1",
        }
        self.assertTrue(promote.is_money(row))
        self.assertEqual(promote.period_cell("commitment", row), "50000000")

    def test_a_multiple_never_lands_in_a_money_column(self) -> None:
        """A page printing `1.73` under a paid-in heading is a multiple, and
        placing it in paid_in_capital_itd made one fund's RVPI 18 million."""
        row = {"value_numeric": "1.73", "value_kind": "number", "currency": ""}
        self.assertIsNone(promote.period_cell("paid_in_capital_itd", row))

    def test_a_printed_percent_becomes_a_decimal_rate(self) -> None:
        row = {"value_numeric": "9", "value_kind": "percent", "currency": ""}
        self.assertEqual(promote.period_cell("reported_irr", row), "0.09")


class PromotedTableTests(unittest.TestCase):
    def test_promoted_legal_terms_load_under_the_database_contract(self) -> None:
        import duckdb

        source = observation(
            record_family="legal_term", metric_id="legal_term",
            term_category="organizational_expense", value_raw="", value_numeric="",
            value_text="The Fund bears its organizational expenses.",
        )
        risk = {**source, "observation_id": "OBS_2", "record_family": "legal_clause",
                "term_category": "risk_factor", "value_text": "Investments may lose value."}
        terms = promote.build_fund_terms([source])
        clauses = promote.build_fund_term_clauses([source, risk])
        self.assertEqual([r["metric_id"] for r in clauses],
                         ["terms.special_term", "terms.risk_factor"])
        self.assertEqual(clauses[0]["value_raw"], source["value_text"])
        self.assertEqual(clauses[1]["value_raw"], risk["value_text"])
        zero = promote.build_fund_term_clauses([{**source, "value_raw": "0"}])[0]
        self.assertEqual(zero["value_raw"], "0")
        with duckdb.connect(":memory:") as connection:
            connection.execute((PROJECT_ROOT / "sql/duckdb/02_fund_level_ddl.sql").read_text())
            connection.execute("INSERT INTO fund_master (fund_id, provenance_type, record_status) "
                               "VALUES ('FUND_0001', 'EXTRACTED', 'ACTIVE')")
            for table, rows in (("fund_terms", terms), ("fund_term_clauses", clauses)):
                for row in rows:
                    self.assertEqual(row["term_scope"], "base_fund")
                    columns = ", ".join(f'"{key}"' for key in row)
                    placeholders = ", ".join("?" for _ in row)
                    connection.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
                                       list(row.values()))
                self.assertEqual(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0],
                                 len(rows))

    def test_source_master_retains_only_settled_printed_constants(self) -> None:
        rows = [
            {"fund_id": "FUND_1", "strategy": "Buyout", "vintage_year": "2020"},
            {
                "fund_id": "FUND_2",
                "strategy": "Diversified Alternatives",
                "vintage_year": "2011",
            },
        ]
        lookup = {
            "FUND_1": {"strategy": "Buyout", "vintage_year": "2020"},
            "FUND_2": {"strategy": "Growth Equity"},
        }
        cleaned = promote.retain_supported_master_attributes(rows, lookup)
        self.assertEqual(cleaned[0]["strategy"], "Buyout")
        self.assertEqual(cleaned[0]["vintage_year"], "2020")
        self.assertEqual(cleaned[1]["strategy"], "")
        self.assertEqual(cleaned[1]["vintage_year"], "")

    def test_every_observed_fund_has_a_source_master_row(self) -> None:
        observed = {
            row["fund_id"] for row in read(CSV_DIR / "fund_observations.csv")
        }
        mastered = {row["fund_id"] for row in read(CSV_DIR / "fund_master.csv")}
        self.assertEqual(observed - mastered, set())

    def test_every_promoted_row_names_a_fund_and_a_document(self) -> None:
        for name, key in (
            ("fund_observations.csv", "file_id"),
            ("fund_periods.csv", "source_document_id"),
            ("fund_cashflows.csv", "file_id"),
            ("fund_holdings.csv", "source_document_id"),
        ):
            rows = read(CSV_DIR / name)
            self.assertTrue(rows, f"{name} holds no promoted rows")
            for row in rows:
                self.assertTrue(row["fund_id"].startswith("FUND_"), f"{name}: {row}")
                if row["provenance_type"] != "EXTRACTED":
                    self.assertTrue(row.get("synthetic_parameter_set_id"))
                    continue
                self.assertTrue(row[key], f"{name} row without a source document")

    def test_every_period_traces_to_the_observations_it_was_built_from(self) -> None:
        observations = {
            row["observation_id"] for row in read(CSV_DIR / "fund_observations.csv")
        }
        for row in read(CSV_DIR / "fund_periods.csv"):
            if row["provenance_type"] != "EXTRACTED":
                self.assertEqual(
                    row["synthetic_parameter_set_id"], "INTEGRATED_COMPLETION_V1"
                )
                continue
            cited = [part for part in row["input_observation_ids"].split(" | ") if part]
            self.assertTrue(cited, f"period {row['fund_period_id']} cites no observation")
            for observation_id in cited:
                self.assertIn(observation_id, observations)

    def test_manager_observations_resolve_to_the_manager_master(self) -> None:
        known = {row["manager_id"] for row in read(CSV_DIR / "manager_master.csv")}
        for row in read(CSV_DIR / "manager_observations.csv"):
            self.assertIn(row["manager_id"], known)

    def test_source_master_constants_have_printed_evidence(self) -> None:
        changes = {
            (row["fund_id"], row["field"], row["new_value"])
            for row in read(PROJECT_ROOT / "data" / "extracted" / "audit" / "attribute-changes.csv")
            if row.get("target_table") == "fund_master"
        }
        for row in read(PROJECT_ROOT / "data" / "extracted" / "fund-level" / "fund_master.csv"):
            for field in ("strategy", "vintage_year"):
                if row.get(field):
                    self.assertIn((row["fund_id"], field, row[field]), changes)


def observation(**overrides: str) -> dict[str, str]:
    """One fund-scoped observation with the fields both builders read."""

    row = {
        "observation_id": "OBS_1",
        "document_id": "SRC001",
        "record_family": "fund_economics_observation",
        "metric_id": "fund_economics_observation.irr",
        "metric_category": "irr",
        "metric_name": "IRR (%)",
        "subject_type": "fund",
        "subject_entity_id": "FUND_0001",
        "as_of_date": "2021-12-31",
        "as_of_date_raw": "December 31, 2021",
        "date_precision": "day",
        "horizon": "",
        "value_kind": "percent",
        "value_raw": "11.97",
        "value_numeric": "11.97",
        "unit": "%",
        "currency": "",
        "source_page": "1",
        "contract_version": "2026-08-22.2",
        "method": "",
        "fee_basis": "",
        "definition_keys": "",
        "value_scope": "",
    }
    row.update(overrides)
    return row


class QualifierTests(unittest.TestCase):
    """A promoted rate carries what the page said it means, or it is not
    promoted. The qualifiers are the difference between a comparable number and
    a number whose meaning a reader cannot recover."""

    def test_fund_observations_carry_the_four_qualifiers(self) -> None:
        rows = promote.build_fund_observations([
            observation(method="modified_dietz", fee_basis="net",
                        definition_keys="1", value_scope="fund_position"),
            {"record_family": "document_context", "document_id": "SRC001", "investor_entity_id": "LP_1"}
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["method"], "modified_dietz")
        self.assertEqual(rows[0]["fee_basis"], "net")
        self.assertEqual(rows[0]["definition_keys"], "1")
        self.assertEqual(rows[0]["value_scope"], "fund_position")

    def test_an_irr_with_no_stated_fee_basis_stays_an_observation(self) -> None:
        """255 promoted IRRs stated no basis and shared one column with 55 that
        did. A blank is a row nobody qualified, so it is reported, not placed."""

        periods, _, mismatches = promote.build_fund_periods([observation(fee_basis="")])
        self.assertEqual(periods, [])
        self.assertEqual(len(mismatches), 1)
        self.assertIn("fee_basis", mismatches[0]["finding"])
        self.assertEqual(mismatches[0]["period_column"], "reported_irr")

    def test_an_irr_stating_unstated_is_promoted_and_labelled(self) -> None:
        periods, _, _ = promote.build_fund_periods([observation(fee_basis="unstated")])
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["reported_irr"], "0.1197")
        self.assertEqual(periods[0]["reported_irr_fee_basis"], "unstated")

    def test_a_qualified_return_reaches_its_own_column_with_its_qualifiers(self) -> None:
        periods, _, _ = promote.build_fund_periods([
            observation(metric_category="return", method="modified_dietz", fee_basis="net")
        ])
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["period_return"], "0.1197")
        self.assertEqual(periods[0]["period_return_method"], "modified_dietz")
        self.assertEqual(periods[0]["period_return_fee_basis"], "net")

    def test_an_unqualified_return_never_reaches_a_period_column(self) -> None:
        periods, _, mismatches = promote.build_fund_periods([
            observation(metric_category="return", method="", fee_basis="")
        ])
        self.assertEqual(periods, [])
        self.assertEqual(len(mismatches), 1)

    def test_a_net_and_a_gross_rate_are_told_apart_on_the_period(self) -> None:
        """Both money-weighted rules target reported_irr, so without the
        qualifier beside it the column held two different measures."""

        net, _, _ = promote.build_fund_periods([
            observation(metric_category="return", method="money_weighted", fee_basis="net")
        ])
        gross, _, _ = promote.build_fund_periods([
            observation(metric_category="return", method="money_weighted", fee_basis="gross")
        ])
        self.assertEqual(net[0]["reported_irr_fee_basis"], "net")
        self.assertEqual(gross[0]["reported_irr_fee_basis"], "gross")
        self.assertEqual(net[0]["reported_irr_method"], "money_weighted")


class RoutingTests(unittest.TestCase):
    def test_a_rule_routing_to_no_table_is_refused_at_both_grains(self) -> None:
        """An actuarial assumed rate is evidence. build_fund_periods refused it
        only because no fund_periods rule matched; a baseline column rule for
        its category would have overturned that."""

        evidence_only = observation(
            metric_category="return", method="actuarial", fee_basis="net",
        )
        self.assertEqual(
            promote.routed_target_table(evidence_only, "return"), promote.NO_TARGET_TABLE
        )
        self.assertEqual(promote.build_fund_observations([evidence_only]), [])
        periods, _, _ = promote.build_fund_periods([evidence_only])
        self.assertEqual(periods, [])

    def test_the_evidence_only_token_still_names_rules(self) -> None:
        promote.assert_no_target_table_is_live()


class TaxonomyTests(unittest.TestCase):
    def test_a_period_carries_the_reading_of_its_printed_grouping(self) -> None:
        periods, _, _ = promote.build_fund_periods([
            observation(fee_basis="unstated", strategy="Buyout")
        ])
        self.assertEqual(periods[0]["canonical_asset_class"], "private_equity")
        self.assertEqual(periods[0]["canonical_strategy"], "buyout")

    def test_the_master_reading_comes_from_the_grouping_matrix(self) -> None:
        filled = promote.read_master_groupings([
            {"fund_id": "FUND_0001", "strategy": "Buyout"},
            {"fund_id": "FUND_0002", "strategy": ""},
        ])
        self.assertEqual(filled[0]["canonical_asset_class"], "private_equity")
        self.assertEqual(filled[0]["canonical_strategy"], "buyout")
        self.assertEqual(filled[1]["canonical_asset_class"], "")

    def test_a_printed_industry_is_read_as_an_industry_and_never_a_class(self) -> None:
        reading = promote.canonical_grouping({"sector": "Manufacturing"})
        self.assertEqual(reading["canonical_strategy"], "")


class GateTests(unittest.TestCase):
    def test_the_accepted_batches_cover_every_promoted_document(self) -> None:
        accepted = set()
        for assignment in GATE_DIR.glob("*/assignment.json"):
            payload = json.loads(assignment.read_text(encoding="utf-8"))
            accepted.update(item["file_id"] for item in payload["files"])
        for name, key in (
            ("fund_observations.csv", "file_id"),
            ("fund_periods.csv", "source_document_id"),
        ):
            for row in read(CSV_DIR / name):
                if row.get("provenance_type") != "EXTRACTED":
                    continue
                self.assertIn(row[key], accepted)

    def test_the_gate_refuses_a_row_whose_document_was_not_accepted(self) -> None:
        """The gate has to bite, or the acceptance evidence proves nothing."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            working = Path(raw) / "promotion-gate"
            shutil.copytree(GATE_DIR.parent, working)
            # Drop a document that actually produced promoted rows; a document
            # whose extraction found nothing eligible would leave the gate with
            # nothing to reject and the test would pass for the wrong reason.
            promoted = {row["file_id"] for row in read(CSV_DIR / "fund_observations.csv")}
            for batch in sorted((working / "round02").glob("*/assignment.json")):
                payload = json.loads(batch.read_text(encoding="utf-8"))
                keep = [item for item in payload["files"] if item["file_id"] not in promoted]
                if len(keep) == len(payload["files"]):
                    continue
                dropped = next(
                    item["file_id"] for item in payload["files"] if item["file_id"] in promoted
                )
                payload["files"] = [
                    item for item in payload["files"] if item["file_id"] != dropped
                ]
                batch.write_text(json.dumps(payload), encoding="utf-8")
                break
            else:
                self.fail("no accepted batch carries a document with promoted rows")
            worksheet = batch.parent / "worksheet.csv"
            kept = [row for row in read(worksheet) if row["file_id"] != dropped]
            with worksheet.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(kept[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows(kept)
            with self.assertRaises(PromotionGateError):
                validate_fund_model_extracted_rows(CSV_DIR, working)


if __name__ == "__main__":
    unittest.main()
