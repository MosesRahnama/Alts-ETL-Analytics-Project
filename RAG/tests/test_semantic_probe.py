"""Reproduce the semantic_checks component result. This is not a production-row audit."""

from src.catalog.simple_pdf_extraction.semantic_checks import unbacked_qualifiers


def test_populated_definition_keys_yield_an_empty_unsupported_list() -> None:
    row = {
        "definition_keys": "rounding",
        "method": "unstated",
        "fee_basis": "net",
        "basis_raw": "figures are rounded",
        "source_row_label": "Private Equity",
        "source_column_label": "Return",
        "metric_name": "Return",
    }
    assert unbacked_qualifiers(row) == []


def test_net_fee_without_definition_or_printed_fee_words_is_listed() -> None:
    row = {
        "definition_keys": "",
        "method": "unstated",
        "fee_basis": "net",
        "basis_raw": "figures are rounded",
        "source_row_label": "Private Equity",
        "source_column_label": "Return",
        "metric_name": "Return",
    }
    assert "fee_basis" in unbacked_qualifiers(row)
