"""Check contradictions between recorded values, headers, and definitions."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence

from src.common import matrices
from .csv_wide_contract import normalize_key_text

POLICY = "extraction-semantic-checks"


def pattern(name: str) -> str:
    return matrices.resolve(POLICY, name, context="pattern")


def matches(name: str, text: str) -> bool:
    return bool(re.search(pattern(name), normalize_key_text(text)))


def complete_value_in_quote(value: str, quote: str) -> bool:
    """Check numeral boundaries while retaining the existing whitespace convention."""
    value = normalize_key_text(value).strip().lstrip("$(").rstrip(")%").strip()
    quote = normalize_key_text(quote)
    if not value:
        return True
    if not any(c.isdigit() for c in value):
        return bool(re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", quote))
    return bool(re.search(pattern("number_boundary").format(value=re.escape(value)), quote))


def definition_targets(records: Sequence[Mapping[str, str]], row: Mapping[str, str], key: str):
    """Resolve a marker within its table, page, then document."""
    targets = [r for r in records if r.get("record_family") == "definition_context"
               and key in [p.strip() for p in r.get("definition_keys", "").split("|")]]
    on_page = [r for r in targets if r.get("source_page") == row.get("source_page")]
    in_table = [r for r in on_page if r.get("source_table") == row.get("source_table")]
    return in_table or on_page or targets


def record_errors(records: Sequence[Mapping[str, str]], page_text: Mapping[int, str],
                  *, whole_document: bool = True) -> list[tuple[Mapping[str, str], str, str]]:
    """Return contradictions; source review remains responsible for interpretation."""
    errors = []
    return_categories = matrices.mapping(POLICY, "return_category")
    account_categories = matrices.mapping(POLICY, "account_category")
    context = next((r for r in records if r.get("record_family") == "document_context"), {})
    total_columns = set()
    for row in records:
        if row.get("subject_type") == "fund" and matches("whole_fund", row.get("source_row_label", "")):
            total_columns.add((row.get("source_page"), row.get("source_table"),
                               normalize_key_text(row.get("source_column_label", ""))))

    def fail(row, code, detail):
        errors.append((row, code, detail))

    for row in records:
        category = row.get("metric_category", "")
        if row.get("record_family") == "financial_statement_observation":
            name = row.get("subject_name", "")
            required = next(iter(matrices.mapping(POLICY, "statement_label_scope")))
            if matches("statement_label", name) and row.get("subject_type") != required:
                fail(row, "STATEMENT_LABEL_IDENTITY", f"{name!r} is an accounting label; retain it as {required}, not an institution or fund")
            if row.get("subject_type") == "reporting_entity" and matches("named_partnership_fund", name):
                fail(row, "FUND_ENTITY_TYPE", "the printed name identifies one fund partnership; retain its fund identity")
        if whole_document and row.get("record_family") != "definition_context":
            for key in filter(None, (p.strip() for p in row.get("definition_keys", "").split("|"))):
                targets = definition_targets(records, row, key)
                meanings = {(r.get("source_page"), normalize_key_text(r.get("text_raw", ""))) for r in targets}
                if len(meanings) > 1:
                    fail(row, "DEFINITION_AMBIGUOUS", f"definition_keys {key!r} has multiple meanings; identify its table-specific definition")
        if not row.get("metric_value_raw"):
            continue
        column = row.get("source_column_label", "").strip()
        date = row.get("as_of_date", "") or row.get("period_end", "")
        if re.fullmatch(pattern("year_column"), column):
            years = set(re.findall(pattern("year_token"), date))
            if years and years != {column}:
                fail(row, "COMPARATIVE_DATE", f"column {column!r} conflicts with date {date!r}; use the date governing this column")
        label = row.get("source_row_label", "")
        if matches("relative_prior", label):
            peers = [r for r in records if r.get("source_page") == row.get("source_page")
                     and r.get("source_table") == row.get("source_table")
                     and r.get("subject_name") == row.get("subject_name")
                     and r.get("source_column_label") == column
                     and r.get("metric_category") == category
                     and not matches("relative_prior", r.get("source_row_label", ""))]
            if date and any(date == (r.get("as_of_date") or r.get("period_end")) for r in peers):
                fail(row, "RELATIVE_DATE", "Last Quarter repeats the current row date; retain the printed relative date or its source-stated date")
        block = (row.get("source_page"), row.get("source_table"), normalize_key_text(column))
        if category in return_categories and row.get("subject_type") == "fund" and block in total_columns:
            if normalize_key_text(row.get("subject_name", "")) == normalize_key_text(column):
                rule = "total_scope" if matches("whole_fund", label) else "component_scope"
                required = next(iter(matrices.mapping(POLICY, rule)))
                if row.get("value_scope") != required:
                    fail(row, "FUND_COMPONENT_SCOPE", f"row {label!r} under fund column {column!r} requires value_scope={required}")
        if category in account_categories and row.get("subject_type") == "investor":
            required = next(iter(matrices.mapping(POLICY, "account_scope")))
            if row.get("value_scope") != required:
                fail(row, "INVESTOR_SCOPE", f"an investor balance requires value_scope={required}")
        if whole_document and context.get("investor_name") and category:
            try:
                text = page_text.get(int(context.get("source_page", "0")), "")
            except ValueError:
                text = ""
            if (matches("capital_account", context.get("source_table", ""))
                    and matches("investee_label", text) and matches("investor_label", text)
                    and row.get("subject_type") == "fund"
                    and normalize_key_text(row.get("subject_name", "")) == normalize_key_text(context.get("subject_name", ""))):
                fail(row, "ACCOUNT_OWNER", "the capital-account form names both investor and investee; record the investor account as the subject")
        if category in return_categories:
            header = normalize_key_text(" ".join(row.get(k, "") for k in (
                "source_row_label", "source_column_label", "metric_name")))
            fee_signals = {r["input_value"] for r in matrices.rows_in(POLICY, "fee_header")
                           if re.search(r["output_value"], header)}
            fee = row.get("fee_basis", "")
            exceptions = matrices.mapping(POLICY, "fee_exception")
            if len(fee_signals) == 1 and fee not in fee_signals and fee not in exceptions:
                fail(row, "FEE_HEADER", f"printed header states {next(iter(fee_signals))}; fee_basis is {fee!r}")
            method_signals = {r["input_value"] for r in matrices.rows_in(POLICY, "method_header")
                              if re.search(r["output_value"], header)}
            if len(method_signals) == 1 and row.get("method") != next(iter(method_signals)):
                signal = next(iter(method_signals))
                refinement = matrices.mapping(POLICY, "method_refinement").get(signal)
                backing = row.get("basis_raw", "")
                for key in filter(None, (p.strip() for p in row.get("definition_keys", "").split("|"))):
                    backing += " " + " ".join(r.get("text_raw", "") for r in definition_targets(records, row, key))
                supported = (refinement and row.get("method") == refinement
                             and re.search(matrices.resolve(POLICY, refinement, context="method_header"),
                                           normalize_key_text(backing)))
                if not whole_document and refinement == row.get("method") and row.get("definition_keys"):
                    # A single MERGE row cannot resolve definitions in its siblings.
                    # The constructed document must prove this reference before writing.
                    supported = True
                if not supported:
                    fail(row, "METHOD_HEADER", f"printed header states {signal}; method is {row.get('method', '')!r} without a cited refinement")
    return errors
