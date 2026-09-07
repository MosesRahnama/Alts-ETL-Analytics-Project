"""The promotion helpers return the matrix output, and a row's presence alone decides nothing.

A lookup that only asked whether a key exists would keep passing if every
output_value were replaced, so each helper is exercised against a patched
matrix whose values differ from the pipeline's own.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.load import promote_extracted_to_fund_level as promotion


class PromotionReadsTheMatrixTests(unittest.TestCase):
    def test_measure_basis_returns_the_matrix_value(self) -> None:
        with patch.object(promotion.matrices, "mapping", return_value={"dpi": "matrix_basis"}), patch.object(
            promotion.matrices, "resolve", return_value="matrix_basis"
        ):
            self.assertEqual(promotion.measure_basis("dpi", "number", True), "matrix_basis")

    def test_period_eligibility_reads_the_output_value(self) -> None:
        with patch.object(promotion.matrices, "mapping", return_value={"": "not_eligible"}):
            self.assertFalse(promotion.period_eligible(""))
        with patch.object(promotion.matrices, "mapping", return_value={"": "period_eligible"}):
            self.assertTrue(promotion.period_eligible(""))

    def test_column_lookups_read_the_matrix(self) -> None:
        with patch.object(promotion.matrices, "mapping", return_value={"nav": "matrix_column"}):
            self.assertEqual(promotion.column_of("nav"), "matrix_column")
            self.assertIsNone(promotion.column_of("absent"))
        with patch.object(promotion.matrices, "resolve_or_star", return_value="matrix_kind"):
            self.assertEqual(promotion.column_kind("nav"), "matrix_kind")

    def test_the_qualifier_policy_is_read_off_the_matrix(self) -> None:
        """The admission rule is a matrix fact. Reading it from a literal would
        keep passing if the matrix said something else."""

        patched = [{
            "input_value": "return",
            "output_value": "matrix_column",
            "requires_stated": "matrix_qualifier",
            "carries_qualifiers": "matrix_qualifier|second",
        }]
        with patch.object(promotion.matrices, "load", return_value=patched):
            self.assertEqual(promotion.required_qualifiers("return"), ("matrix_qualifier",))
            self.assertEqual(
                promotion.carried_qualifiers("return"), ("matrix_qualifier", "second")
            )
            self.assertEqual(promotion.required_qualifiers("absent"), ())

    def test_the_published_policy_names_the_qualified_categories(self) -> None:
        self.assertEqual(promotion.required_qualifiers("return"), ("method", "fee_basis"))
        self.assertEqual(promotion.required_qualifiers("irr"), ("fee_basis",))
        self.assertEqual(promotion.required_qualifiers("nav"), ())

    def test_the_grouping_reading_comes_from_the_grouping_matrix(self) -> None:
        patched = [{
            "context": "strategy",
            "input_value": "Buyout",
            "output_value": "matrix_class",
            "canonical_strategy": "matrix_strategy",
            "canonical_sub_strategy": "",
            "sector": "",
        }]
        promotion._GROUPING = None
        with patch.object(promotion.matrices, "load", return_value=patched), patch.object(
            promotion.matrices, "decode", side_effect=lambda value: value
        ):
            reading = promotion.canonical_grouping({"strategy": "Buyout"})
        promotion._GROUPING = None
        self.assertEqual(reading["canonical_asset_class"], "matrix_class")
        self.assertEqual(reading["canonical_strategy"], "matrix_strategy")


if __name__ == "__main__":
    unittest.main()
