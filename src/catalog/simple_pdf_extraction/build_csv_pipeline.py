"""Generate the deterministic wide-row CSV extraction system.

The generator freezes routing, partitions dispatch scope, writes the schema
artifacts and templates, and emits four self-contained prompts per route.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Iterable, Mapping

from .field_guide import field_guide_markdown
from .csv_wide_contract import (
    RETIRED_FIELDS,
    BENCH_AGENTS,
    EXTRACTOR_AGENTS,
    CANONICAL_DOC_TYPES,
    CONTRACT_VERSION,
    COVERAGE_COLUMNS,
    COVERAGE_RESOLUTION_COLUMNS,
    DEFAULT_PRODUCT_TIER,
    DOC_TYPE_FAMILIES,
    DOC_TYPE_TO_ROUTE,
    EVIDENCE_CLASSES,
    FAMILY_CONTRACTS,
    METRIC_CATEGORIES,
    METRIC_QUALIFIERS,
    METRIC_VOCABULARY,
    PAGE_STATUSES,
    RECORD_COLUMNS,
    RESOLUTION_COLUMNS,
    ROUTES,
    SOURCE_STRUCTURE_TYPES,
    SUBJECT_TYPES,
    TERM_CATEGORIES,
    TERM_QUALIFIERS,
    TERM_VOCABULARY,
    WORKLIST_COLUMNS,
    header_line,
    preferred_categories,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INSTRUCTION_ROOT = PROJECT_ROOT / "instructions" / "01-pdf-extraction-csv"
PROMPT_ROOT = INSTRUCTION_ROOT / "dispatch-prompts"
WORKLIST_ROOT = INSTRUCTION_ROOT / "worklists"
SCHEMA_ROOT = PROJECT_ROOT / "data" / "schemas"
SOURCE_LEDGER = PROJECT_ROOT / "data-gathering" / "source_ledger.csv"
ROUTING_PATH = SCHEMA_ROOT / "EXTRACTION-ROUTING.csv"
SCOPE_PATH = SCHEMA_ROOT / "EXTRACTION-DISPATCH-SCOPE.csv"
MASTER_SCHEMA = SCHEMA_ROOT / "MASTER-EXTRACTION-SCHEMA.md"
FIELD_GUIDE = SCHEMA_ROOT / "EXTRACTED-FIELDS.md"
FAMILY_SCHEMA = SCHEMA_ROOT / "EXTRACTION-RECORD-FAMILIES.csv"
DOC_TYPE_SCHEMA = SCHEMA_ROOT / "EXTRACTION-DOC-TYPE-MAP.csv"
METRIC_SCHEMA = SCHEMA_ROOT / "EXTRACTION-METRIC-CATEGORIES.csv"

ROUTING_COLUMNS = (
    "route_order",
    "file_id",
    "filename",
    "page_count",
    "canonical_doc_type",
    "source_header_doc_type",
    "route",
    "product_tier",
    "routing_status",
    "routing_reason",
    "issuer",
    "source_sha256",
    "txt_path",
    "pdf_path",
    "image_dir",
    "grid_path",
)
SCOPE_COLUMNS = ("file_id", "route", "product_tier", "dispatch_scope", "scope_reason")
DISPATCH_SCOPES = ("ACTIVE", "DEFERRED", "REFERENCE", "UNSCHEDULED")

ROUTE_TITLES = {
    "01-financials": "Financials",
    "02-performance": "Performance",
    "03-institutional-report": "Institutional Report",
    "04-quarterly-report": "Quarterly Report",
    "05-fund-legal-docs": "Fund Legal Documents",
    "06-statements-and-economics": "Statements and Economics",
    "07-institutional-mission": "Institutional Mission",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: Iterable[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(columns),
            extrasaction="raise",
            quoting=csv.QUOTE_ALL,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in writer.fieldnames})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


from src.common import matrices

# The dispatch builder's decisions live in matrices under
# data/normalization/transformations; large prose blocks stay in this module
# and the if-raise checks below refuse an edit that diverges from the matrix.
NUMERIC_TEXT = "numeric-text-format"
REFERENCE_RULES = "reference-source-rules"
ROUTING_STATUS = "routing-status"
DISPATCH_SCOPE = "dispatch-scope-rules"
EXCLUDED_SCOPE_RULES = "excluded-scope"
LABEL_RULES = "label-normalization-rules"
DISAMBIGUATION_RULES = "printed-label-to-category"
TABLE_CELL_RULE = "table-cell-rule"
SIGNATURE_RULES = "family-signature"
CONVENTION_RULES = "adjudication-conventions"


def integer_text(value: str) -> str:
    if not str(value).strip():
        return matrices.resolve(NUMERIC_TEXT, "blank_value")
    if matrices.resolve(NUMERIC_TEXT, "numeric_value") != "int_of_float":
        raise ValueError("numeric-text-format.csv names an unknown rendering")
    return str(int(float(value)))


def source_paths(filename: str) -> tuple[str, str, str, str]:
    stem = Path(filename).stem
    return (
        f"data/documents/txt/{stem}.txt",
        f"data/documents/pdf/{filename}",
        f"data/documents/images/{stem}",
        f"data/documents/grids/{stem}.csv",
    )


def txt_header_doc_type(txt_path: Path) -> str:
    if not txt_path.is_file():
        return ""
    with txt_path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for _ in range(20):
            line = handle.readline()
            if not line:
                break
            match = re.match(r"#\s*doc_type:\s*(.+?)\s*$", line)
            if match:
                return match.group(1).strip()
    return ""


def is_reference_source(row: Mapping[str, str]) -> bool:
    """Route only declared models/examples to the reference product.

    Source-ledger notes contain metadata such as ``char_count_sample``; generic
    substring matching on the notes would therefore misroute ordinary reports.
    """

    license_note = (row.get("license_note") or "").casefold().strip()
    filename = row.get("filename", "")
    notes = (row.get("notes") or "").casefold()
    if license_note == matrices.resolve(REFERENCE_RULES, "license_note_equals", context="rule"):
        return True
    if re.search(matrices.resolve(REFERENCE_RULES, "filename_pattern", context="rule"), filename, re.IGNORECASE):
        return True
    note_markers = tuple(
        row["input_value"] for row in matrices.rows_in(REFERENCE_RULES, "note_marker")
    )
    return any(marker in notes for marker in note_markers)


def bootstrap_route_order() -> dict[str, tuple[str, int]]:
    """Recover the already-adjudicated route assignment and stable ordering."""

    result: dict[str, tuple[str, int]] = {}
    for route in ROUTES:
        path = WORKLIST_ROOT / f"{route}.csv"
        if not path.is_file():
            continue
        for index, row in enumerate(read_csv(path), 1):
            file_id = row.get("file_id", "")
            if file_id in result:
                raise RuntimeError(f"{file_id} appears in two route worklists")
            result[file_id] = (route, index)
    return result


def bootstrap_selected_ids() -> set[str]:
    selected: set[str] = set()
    source_root = WORKLIST_ROOT / "active"
    for route in ROUTES:
        path = source_root / f"{route}.csv"
        if not path.is_file():
            continue
        selected.update(row.get("file_id", "") for row in read_csv(path) if row.get("file_id"))
    return selected


def corpus_size() -> int:
    """Documents in the source ledger. Derived, never hardcoded: the corpus
    changes when documents are purged, and a literal here goes stale silently."""
    return len([row for row in read_csv(SOURCE_LEDGER) if row.get("file_id")])


def build_routing_registry() -> list[dict[str, str]]:
    source_rows = read_csv(SOURCE_LEDGER)
    if not source_rows:
        raise RuntimeError("source_ledger.csv is empty")
    source_by_id = {row["file_id"]: row for row in source_rows}
    if len(source_by_id) != len(source_rows):
        raise RuntimeError("source_ledger.csv contains duplicate file_id values")

    if ROUTING_PATH.is_file():
        existing = read_csv(ROUTING_PATH)
        if {row["file_id"] for row in existing} != set(source_by_id):
            raise RuntimeError("EXTRACTION-ROUTING.csv no longer matches source_ledger.csv")
        route_order = {
            row["file_id"]: (row["route"], int(row["route_order"])) for row in existing
        }
    else:
        route_order = bootstrap_route_order()
        if set(route_order) != set(source_by_id):
            missing = sorted(set(source_by_id) - set(route_order))
            extra = sorted(set(route_order) - set(source_by_id))
            raise RuntimeError(f"Route worklists do not cover source ledger: missing={missing[:5]}, extra={extra[:5]}")

    rows: list[dict[str, str]] = []
    for file_id, source in source_by_id.items():
        ratified = source["doc_type"]
        if ratified not in CANONICAL_DOC_TYPES:
            raise RuntimeError(f"{file_id}: uncontrolled source-ledger doc_type {ratified!r}")
        expected_route = DOC_TYPE_TO_ROUTE[ratified]
        route, order = route_order[file_id]
        if route != expected_route:
            raise RuntimeError(
                f"{file_id}: route {route!r} conflicts with ratified type {ratified!r} ({expected_route})"
            )
        txt_rel, pdf_rel, image_rel, grid_rel = source_paths(source["filename"])
        header_type = txt_header_doc_type(PROJECT_ROOT / txt_rel)
        outcome = "header_matches" if header_type == ratified else "header_differs"
        status = matrices.resolve(ROUTING_STATUS, outcome)
        reason = next(
            row["reason"] for row in matrices.load(ROUTING_STATUS) if row["input_value"] == outcome
        )
        tier = "REFERENCE" if is_reference_source(source) else DEFAULT_PRODUCT_TIER[ratified]
        rows.append(
            {
                "route_order": str(order),
                "file_id": file_id,
                "filename": source["filename"],
                "page_count": integer_text(source.get("page_count", "")),
                "canonical_doc_type": ratified,
                "source_header_doc_type": header_type,
                "route": route,
                "product_tier": tier,
                "routing_status": status,
                "routing_reason": reason,
                "issuer": source.get("issuer", ""),
                "source_sha256": source.get("sha256", ""),
                "txt_path": txt_rel,
                "pdf_path": pdf_rel,
                "image_dir": image_rel,
                "grid_path": grid_rel,
            }
        )
    rows.sort(key=lambda row: (row["route"], int(row["route_order"])))
    write_csv(ROUTING_PATH, ROUTING_COLUMNS, rows)
    return rows


def build_dispatch_scope(routing: list[dict[str, str]]) -> list[dict[str, str]]:
    routing_by_id = {row["file_id"]: row for row in routing}
    if SCOPE_PATH.is_file():
        scope = read_csv(SCOPE_PATH)
        if {row["file_id"] for row in scope} != set(routing_by_id):
            raise RuntimeError("EXTRACTION-DISPATCH-SCOPE.csv no longer matches routing registry")
        for row in scope:
            if row["dispatch_scope"] not in DISPATCH_SCOPES:
                raise RuntimeError(f"{row['file_id']}: invalid dispatch_scope {row['dispatch_scope']!r}")
            route = routing_by_id[row["file_id"]]
            row["route"] = route["route"]
            row["product_tier"] = route["product_tier"]
        write_csv(SCOPE_PATH, SCOPE_COLUMNS, scope)
        return scope

    selected = bootstrap_selected_ids()
    rows: list[dict[str, str]] = []
    for route_row in routing:
        selected_now = route_row["file_id"] in selected
        tier = route_row["product_tier"]
        key = "not_selected" if not selected_now else tier
        scope = matrices.resolve_or_star(DISPATCH_SCOPE, key)
        reason = next(
            row["reason"]
            for row in matrices.load(DISPATCH_SCOPE)
            if row["input_value"] in (key, "*")
            and matrices.decode(row["output_value"]) == scope
        )
        rows.append(
            {
                "file_id": route_row["file_id"],
                "route": route_row["route"],
                "product_tier": tier,
                "dispatch_scope": scope,
                "scope_reason": reason,
            }
        )
    write_csv(SCOPE_PATH, SCOPE_COLUMNS, rows)
    return rows


def worklist_row(order: int, route_row: Mapping[str, str]) -> dict[str, str]:
    return {
        "work_order": str(order),
        **{column: route_row.get(column, "") for column in WORKLIST_COLUMNS if column != "work_order"},
    }


def write_worklists(routing: list[dict[str, str]], scope: list[dict[str, str]]) -> None:
    scope_by_id = {row["file_id"]: row["dispatch_scope"] for row in scope}
    for folder in (WORKLIST_ROOT, WORKLIST_ROOT / "active", WORKLIST_ROOT / "deferred", WORKLIST_ROOT / "reference"):
        folder.mkdir(parents=True, exist_ok=True)
    for route in ROUTES:
        route_rows = [row for row in routing if row["route"] == route]
        write_csv(
            WORKLIST_ROOT / f"{route}.csv",
            WORKLIST_COLUMNS,
            [worklist_row(index, row) for index, row in enumerate(route_rows, 1)],
        )
        for dispatch_scope, folder_name in (
            ("ACTIVE", "active"),
            ("DEFERRED", "deferred"),
            ("REFERENCE", "reference"),
        ):
            selected = [row for row in route_rows if scope_by_id[row["file_id"]] == dispatch_scope]
            write_csv(
                WORKLIST_ROOT / folder_name / f"{route}.csv",
                WORKLIST_COLUMNS,
                [worklist_row(index, row) for index, row in enumerate(selected, 1)],
            )


def write_templates() -> None:
    write_text(INSTRUCTION_ROOT / "CSV-TEMPLATE.csv", header_line(RECORD_COLUMNS))
    write_text(INSTRUCTION_ROOT / "COVERAGE-TEMPLATE.csv", header_line(COVERAGE_COLUMNS))
    write_text(INSTRUCTION_ROOT / "RESOLUTION-TEMPLATE.csv", header_line(RESOLUTION_COLUMNS))
    write_text(
        INSTRUCTION_ROOT / "COVERAGE-RESOLUTION-TEMPLATE.csv",
        header_line(COVERAGE_RESOLUTION_COLUMNS),
    )
    write_text(INSTRUCTION_ROOT / "BATCH-WORKLIST-TEMPLATE.csv", header_line(WORKLIST_COLUMNS))


def schema_rows() -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Families (grain), document types (routing), and the vocabulary (one row
    per name). The three are separate lists, never a product of each other."""

    family_rows: list[dict[str, str]] = []
    for family, contract in FAMILY_CONTRACTS.items():
        family_rows.append(
            {
                "record_family": family,
                "description": contract.description,
                "grain": contract.grain,
                "category_kind": contract.kind,
                "tabular": "yes" if contract.tabular else "no",
                "required_business_fields": "|".join(sorted(contract.required_fields)),
                "allowed_business_fields": "|".join(sorted(contract.allowed_fields)),
                "preferred_categories": "|".join(preferred_categories(family)),
                "table_cell_rule": matrices.resolve(
                    TABLE_CELL_RULE, "tabular" if contract.tabular else "non_tabular"
                ),
            }
        )
    doc_rows: list[dict[str, str]] = []
    for doc_type in CANONICAL_DOC_TYPES:
        doc_rows.append(
            {
                "canonical_doc_type": doc_type,
                "route": DOC_TYPE_TO_ROUTE[doc_type],
                "default_product_tier": DEFAULT_PRODUCT_TIER[doc_type],
                "allowed_record_families": "|".join(DOC_TYPE_FAMILIES[doc_type]),
                "excluded_scope": excluded_scope(doc_type),
            }
        )
    vocabulary_rows: list[dict[str, str]] = [
        {
            "category": name,
            "kind": "metric",
            "definition": definition,
            "unit_hint": unit_hint,
            "preferred_family": preferred_family,
            "qualified": "yes" if METRIC_QUALIFIERS[name]["qualified"] else "no",
            "required_dimensions": "|".join(METRIC_QUALIFIERS[name]["required_dimensions"]),
            "disposition": str(METRIC_QUALIFIERS[name]["disposition"]),
        }
        for name, definition, unit_hint, preferred_family in METRIC_VOCABULARY
    ] + [
        {
            "category": name,
            "kind": "term",
            "definition": definition,
            "unit_hint": "text",
            "preferred_family": preferred_family,
            "qualified": "yes" if TERM_QUALIFIERS[name]["qualified"] else "no",
            "required_dimensions": "|".join(TERM_QUALIFIERS[name]["required_dimensions"]),
            "disposition": str(TERM_QUALIFIERS[name]["disposition"]),
        }
        for name, definition, preferred_family in TERM_VOCABULARY
    ]
    return family_rows, doc_rows, vocabulary_rows


def excluded_scope(doc_type: str) -> str:
    return matrices.resolve_or_star(EXCLUDED_SCOPE_RULES, doc_type)


def write_schema_files() -> None:
    family_rows, doc_rows, vocabulary_rows = schema_rows()
    write_csv(
        FAMILY_SCHEMA,
        (
            "record_family",
            "description",
            "grain",
            "category_kind",
            "tabular",
            "required_business_fields",
            "allowed_business_fields",
            "preferred_categories",
            "table_cell_rule",
        ),
        family_rows,
    )
    write_csv(
        DOC_TYPE_SCHEMA,
        (
            "canonical_doc_type",
            "route",
            "default_product_tier",
            "allowed_record_families",
            "excluded_scope",
        ),
        doc_rows,
    )
    write_csv(
        METRIC_SCHEMA,
        (
            "category",
            "kind",
            "definition",
            "unit_hint",
            "preferred_family",
            "qualified",
            "required_dimensions",
            "disposition",
        ),
        vocabulary_rows,
    )
    selection_rows: list[dict[str, str]] = []
    for doc_row in doc_rows:
        doc_type = doc_row["canonical_doc_type"]
        for family in DOC_TYPE_FAMILIES[doc_type]:
            contract = FAMILY_CONTRACTS[family]
            selection_rows.append(
                {
                    "canonical_doc_type": doc_type,
                    "default_product_tier": doc_row["default_product_tier"],
                    "record_family": family,
                    "grain": contract.grain,
                    "category_kind": contract.kind,
                    "required_business_fields": "|".join(sorted(contract.required_fields)),
                    "allowed_business_fields": "|".join(sorted(contract.allowed_fields)),
                    "preferred_categories": "|".join(preferred_categories(family)),
                    "table_cell_rule": matrices.resolve(
                        TABLE_CELL_RULE, "tabular" if contract.tabular else "non_tabular"
                    ),
                    "exclusions": doc_row["excluded_scope"],
                }
            )
    write_csv(
        INSTRUCTION_ROOT / "FIELD-SELECTION.csv",
        (
            "canonical_doc_type",
            "default_product_tier",
            "record_family",
            "grain",
            "category_kind",
            "required_business_fields",
            "allowed_business_fields",
            "preferred_categories",
            "table_cell_rule",
            "exclusions",
        ),
        selection_rows,
    )
    write_text(MASTER_SCHEMA, master_schema_markdown(family_rows, doc_rows))
    write_text(FIELD_GUIDE, field_guide_markdown())


def master_schema_markdown(
    family_rows: list[dict[str, str]], doc_rows: list[dict[str, str]]
) -> str:
    lines = [
        "# Field list for printed cells",
        "",
        f"Field-list version: `{CONTRACT_VERSION}`.",
        "",
        "## Fixed rules",
        "",
        "| Rule | Field list |",
        "|---|---|",
        "| Atomic row | One row is one source observation or one listed operative provision. |",
        "| Table grain | One populated allowed value cell produces one row. A row with N populated allowed value columns produces N rows. |",
        "| Nulls | Blank, dash, em dash, and N/A cells produce no record. |",
        "| Identity | Pair on file, family, page, table, row, column, occurrence, and controlled metric/term category. |",
        "| Coverage | Every physical page appears once in the companion coverage CSV. |",
        "| Routing | `data/schemas/EXTRACTION-ROUTING.csv` is fixed; agents do not reclassify documents. |",
        "| Templates | Template and illustrative documents are routed to the REFERENCE product, never mixed with actual fund observations. |",
        "| Values | Copy printed values as printed. Do not calculate, normalize, convert, back-solve, or infer. |",
        "",
        "## Record header",
        "",
        "```csv",
        header_line(RECORD_COLUMNS),
        "```",
        "",
        "## Coverage header",
        "",
        "```csv",
        header_line(COVERAGE_COLUMNS),
        "```",
        "",
        "## Document type routes",
        "",
        "| Ratified document type | Route | Default product | Allowed record families |",
        "|---|---|---|---|",
    ]
    for row in doc_rows:
        lines.append(
            f"| `{row['canonical_doc_type']}` | `{row['route']}` | `{row['default_product_tier']}` | "
            + ", ".join(f"`{value}`" for value in row["allowed_record_families"].split("|"))
            + " |"
        )
    lines += ["", "## Record-family grains", "", "| Family | Grain | Required business fields |", "|---|---|---|"]
    for row in family_rows:
        lines.append(
            f"| `{row['record_family']}` | {row['grain']} | `{row['required_business_fields'].replace('|', '`, `')}` |"
        )
    lines += [
        "",
        "## Controlled categories",
        "",
        f"One vocabulary, one row per name: {len(METRIC_CATEGORIES)} metric names and {len(TERM_CATEGORIES)} term names in `EXTRACTION-METRIC-CATEGORIES.csv`, each with a definition, a unit hint, and a preferred family. A metric family fills `metric_category` from the whole metric vocabulary and a term family fills `term_category` from the whole term vocabulary; the family is the table grain and owns no private list. The preferred family is guidance for a mixed table. The document-type to family matrix used by every prompt is `instructions/01-pdf-extraction-csv/FIELD-SELECTION.csv`.",
        "",
        "| Family | Kind | Preferred names |",
        "|---|---|---|",
        *(
            f"| `{family}` | {contract.kind} | {', '.join(f'`{name}`' for name in preferred_categories(family)) or 'none'} |"
            for family, contract in FAMILY_CONTRACTS.items()
            if contract.kind != "context"
        ),
        "",
        "## Exclusions",
        "",
        "No SSNs/TINs, dates of birth, passport or government-ID numbers, personal bank/wire/routing/account information, signature images, blank form fields, unsupported calculations, generic document transcription, or fields outside the closed contract.",
    ]
    return "\n".join(lines)


def route_contract_table(route: str) -> str:
    lines = [
        "| Document type | Product | Allowed record family | Grain | Usual categories (any name of the family's kind is valid) |",
        "|---|---|---|---|---|",
    ]
    for doc_type in ROUTES[route]:
        for family in DOC_TYPE_FAMILIES[doc_type]:
            contract = FAMILY_CONTRACTS[family]
            categories = preferred_categories(family)
            category_text = ", ".join(f"`{value}`" for value in categories) if categories else "none"
            lines.append(
                f"| `{doc_type}` | `{DEFAULT_PRODUCT_TIER[doc_type]}` | `{family}` | {contract.grain} | {category_text} |"
            )
    return "\n".join(lines)


def vocabulary_table(route: str) -> str:
    """The whole vocabulary of each kind the route's families fill, with
    definitions, so an extractor picks the name by printed meaning."""

    kinds = {
        FAMILY_CONTRACTS[family].kind
        for doc_type in ROUTES[route]
        for family in DOC_TYPE_FAMILIES[doc_type]
    }
    lines: list[str] = [
        "Pick the family from the table shape and the name from the printed meaning. "
        "A family takes any name of its kind below; the usual family is guidance for a mixed table, never a rule.",
        "",
    ]
    if "metric" in kinds:
        def qualified_note(name: str) -> str:
            dimensions = METRIC_QUALIFIERS[name]["required_dimensions"]
            if not dimensions:
                return ""
            joined = "` and `".join(dimensions)
            return (
                f" **Qualified: fill `{joined}`** from what the page states (a footnote"
                " key cited in `definition_keys`, or a printed phrase copied into"
                " `basis_raw`); write `unstated` when the page states nothing."
            )
        lines += [
            "| `metric_category` | Means | Unit | Usual family |",
            "|---|---|---|---|",
            *(
                f"| `{name}` | {definition}{qualified_note(name)} | {unit} | `{family}` |"
                for name, definition, unit, family in METRIC_VOCABULARY
            ),
        ]
    if "term" in kinds:
        if lines:
            lines.append("")
        lines += [
            "| `term_category` | Means | Usual family |",
            "|---|---|---|",
            *(
                f"| `{name}` | {definition} | `{family}` |"
                for name, definition, family in TERM_VOCABULARY
            ),
        ]
    return "\n".join(lines)


def route_exclusions(route: str) -> str:
    return "\n".join(f"- **{doc_type}:** {excluded_scope(doc_type)}" for doc_type in ROUTES[route])


def example_file_id(route: str) -> str:
    for relative in (
        Path("active") / f"{route}.csv",
        Path("deferred") / f"{route}.csv",
        Path("reference") / f"{route}.csv",
        Path(f"{route}.csv"),
    ):
        path = WORKLIST_ROOT / relative
        if path.is_file():
            rows = read_csv(path)
            if rows:
                return rows[0]["file_id"]
    raise RuntimeError(f"No worklist row exists for {route}")


# The rules extraction agents demonstrably stop applying as a session ages,
# each one traced to a defect observed on disk. This list is deliberately the
# short working memory, not the spec: it closes every extractor prompt AND is
# printed by `audit-file` on success, so it re-enters the agent's context right
# before every new document, on every interface, with no compliance required.
CHECKLIST_TAIL = """
 2. metric_name and source_column_label take the LEAF header under a banner,
    never the banner (`Level 1`, not `Fair Value Measurements Using`).
 3. Drop trailing colons AND footnote markers from labels, and every dropped
    marker goes into definition_keys: `Fixed income:` -> `Fixed income`;
    `IRR2` -> `IRR` + definition_keys `2`; `Total Fund***` -> `Total Fund` +
    definition_keys `***`. Spaced name parts stay: `Fund II`, `DT 2020`.
 4. subject_type classifies that row's printed label, row by row, lowercase.
    manager_name, investor_name and portfolio_name go ONLY on the single
    document_context row, never on an observation row.
    An investor capital account uses that investor as its subject, not the fund.
    Capital and loan columns remain separate from their printed TOTAL column.
 5. asset_class, strategy and geography come from the printed grouping that
    governs the row. Fill them whenever the page states them; never infer
    them; never copy subject_name into them.
 6. unit and currency_scale: a label printed once (column header, row label,
    table title, banner) applies to every value under it. A scale over one
    column covers only that column.
 7. metric_value_raw verbatim: commas stay commas (quote the field), `$` only
    if printed, `(1,234)` never becomes -1234. A printed `%` or `x` STAYS in
    the value AND goes in unit: `4.8%` -> value `4.8%`, unit `%`. Never `4.8`.
 8. as_of_date takes the fullest printed form (`December 31, 2015`, not
    `2015`) and stays verbatim: never reformat to ISO.
    A comparative column keeps its own date. `Last Quarter` stays that literal
    when no specific date is printed; never substitute the current report date.
 9. In a fund_economics table, Ending/Fair Market Value -> nav, never
    fair_value. Entity names come off the page, never the filename.
10. A TABLE row always has source_column_label; use UNLABELED_COLUMN_<n> when
    the column prints no header. A currency (USD, $) is never a unit.
11. A period qualifier in the header fills horizon (`1-Yr`, `Fiscal YTD`).
    metric_name drops it; source_column_label keeps the full stack so four
    `Total Return` columns stay distinct.
12. source_occurrence = the Nth time THIS PAGE prints this row label under
    this column label. Two tables with the same row labels -> 1 and 2.
13. Extract EVERY populated cell under a mapped row or column, never a
    selection. expected_observation_count must equal the rows written.
    Dated transactions, component columns and cumulative totals each retain
    their printed row and column labels; no component is silently discarded.
14. NO_ELIGIBLE_DATA is about category, never difficulty. A table unresolved
    from TXT or grid is read from the page image, never skipped.
15. Save after every table and section. Every physical page gets a coverage
    row, and audit-file must pass before the next document is opened.
16. The lane is finished when lane-check prints PASS, never before. It, not
    your own judgement, decides that this run is over.
17. file_id, source_page, source_row_label, source_column_label and
    source_occurrence identify the physical cell. Family, category and table
    title are compared decisions, not identity keys. Every block retains its
    printed heading in source_table, including definitions and footnotes.
18. The document_context row sits on page 1 whatever status page 1 carries. A
    cover page stays REFERENCE_ONLY; that row is bookkeeping, not an
    observation. Never move it to a later page.
19. text_raw starts after the term that names it. `Clawback - GP carried
    interest that must be returned` gives source_row_label `Clawback` and
    text_raw `GP carried interest that must be returned`. Never repeat the
    name inside the text.
20. Outside a table, source_row_label is the printed defined term or clause
    heading: `Investment Period`, `Recall of Distributions`. Never the section
    heading above it, and never the clause's opening words.
21. Definitions, legends and accounting policies are records even without a
    number. REFERENCE_ONLY never excludes an in-scope definition.
22. Inspect each table's date columns, units, account owner and footnotes.
    Agreement on a number does not establish agreement on what it measures."""


def family_rule_line(route: str) -> str:
    """Rule 1, written from the families this route can actually produce."""
    families = [
        family
        for doc_type in ROUTES[route]
        for family in DOC_TYPE_FAMILIES[doc_type]
        if family != "document_context"
    ]
    seen: list[str] = []
    for family in families:
        if family not in seen:
            seen.append(family)
    if {"position_observation", "financial_statement_observation"} <= set(seen):
        return (" 1. Family follows the table. A named holding ->\n"
                "    position_observation; an aggregated line, total, or\n"
                "    fair-value-hierarchy row -> financial_statement_observation.\n"
                "    One table, one family.")
    listed = ", ".join(seen)
    return (" 1. Family follows the table, not the document type. One table, one\n"
            f"    family. This route may only use: {listed}.")


def extraction_checklist(route: str) -> str:
    return ("EXTRACTION CHECKLIST, 22 required rules:\n"
            + family_rule_line(route) + CHECKLIST_TAIL)


# Printed labels that two readers routinely map differently, with the category
# each must land on. Rows are filtered per route: naming a category the route's
# families cannot accept sends an agent straight into a validator rejection.


DISAMBIGUATION: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = tuple(
    (labels, tuple((row["output_value"], row["note"]) for row in group))
    for labels, group in __import__("itertools").groupby(
        matrices.load(DISAMBIGUATION_RULES), key=lambda row: row["input_value"]
    )
)

# The checklist's label rules are verified against label-normalization-rules.csv.
_LABEL_CHECKS = {
    "banner_headers": "never the banner",
    "trailing_colons": "Drop trailing colons",
    "footnote_markers": "footnote markers",
    "spaced_name_parts": "Spaced name parts stay",
}
for _row in matrices.load(LABEL_RULES):
    if _LABEL_CHECKS[_row["input_value"]] not in CHECKLIST_TAIL:
        raise ValueError(f"CHECKLIST_TAIL no longer states the {_row['input_value']} rule")


def disambiguation_table(route: str) -> str:
    """Disambiguation rows, filtered clause by clause to this route.

    Filtering whole rows is not enough: a row kept because one of its
    categories is usable still printed clauses naming categories the route
    forbids, which is how a performance prompt came to mention
    `investment_fair_value`.
    """
    usable: set[str] = set()
    for doc_type in ROUTES[route]:
        for family in DOC_TYPE_FAMILIES[doc_type]:
            usable |= set(FAMILY_CONTRACTS[family].metric_categories)
    families = {
        family
        for doc_type in ROUTES[route]
        for family in DOC_TYPE_FAMILIES[doc_type]
    }
    rows = []
    for label, clauses in DISAMBIGUATION:
        kept = [
            text for category, text in clauses
            if category in usable
            and not [
                named for named in re.findall(r"`([a-z_]+_observation)`", text)
                if named not in families
            ]
        ]
        if kept:
            rows.append(f"| {label} | {'; '.join(kept)} |")
    if not rows:
        return "No ambiguous numeric labels apply to this route."
    return "\n".join(["| Printed label | Category |", "|---|---|", *rows])


# The position-vs-statement test is only meaningful where a route can produce
# both families. Elsewhere it names categories the route forbids.
FAMILY_TEST_SECTION = """### The one test that decides `position_observation` against `financial_statement_observation`

This single choice caused more disagreement between the two extractors than every other field combined, and the category follows it: `fair_value` is the value of one named holding, `investment_fair_value` is a statement line that aggregates holdings. Choose the family wrongly and the category tends to go wrong with it, and the two candidates stop matching altogether.

**Read one row label and ask: does it name one ownable thing, or a group of things?**

| The row label reads | Family | `metric_category` |
|---|---|---|
| `Blackstone Real Estate Partners VIII`, `US Treasury 2.5% 2029` | `position_observation` | `fair_value` |
| `Domestic common and preferred stock`, `Fixed income`, `Corporate debt securities` | `financial_statement_observation` | `investment_fair_value` |

A fair-value hierarchy note (`Level 1 | Level 2 | Level 3 | Total`) aggregates by asset class, so it is `financial_statement_observation` even when the section is titled a schedule of investments. A schedule listing each fund or security by name is `position_observation` even when it appears inside a note.

"""


def family_test_section(route: str) -> str:
    families = {
        family
        for doc_type in ROUTES[route]
        for family in DOC_TYPE_FAMILIES[doc_type]
    }
    if {"position_observation", "financial_statement_observation"} <= families:
        return FAMILY_TEST_SECTION
    return ""


# What a table looks like when it belongs to each family. Rendered per route so
# an extractor is never offered a family its document type forbids, and never
# left without a rule for one it permits.


FAMILY_SIGNATURE: dict[str, str] = matrices.mapping(SIGNATURE_RULES)

# The adjudication guide's conventions are verified against the matrix.
_CONVENTION_CHECKS = {
    "different_numbers_same_cell": "The value printed on the page",
    "same_number_different_column": "column_index",
    "stripped_symbol": "The printed form, symbol included",
    "spacing_difference": "whitespace is the one thing closed",
    "short_quote": "accept the lane with the full line",
}


for _row in matrices.load(CONVENTION_RULES):
    if _CONVENTION_CHECKS[_row["input_value"]] not in Path(__file__).read_text(encoding="utf-8"):
        raise ValueError(f"the adjudicator guide dropped the {_row['input_value']} convention")


def family_chooser(route: str) -> str:
    """One chooser row per family this route can actually produce."""
    families: list[str] = []
    for doc_type in ROUTES[route]:
        for family in DOC_TYPE_FAMILIES[doc_type]:
            if family != "document_context" and family not in families:
                families.append(family)
    rows = [
        f"| {FAMILY_SIGNATURE[family]} | `{family}` | every column in that table |"
        for family in families
        if family in FAMILY_SIGNATURE
    ]
    if not rows:
        return "This document type produces only the single `document_context` row."
    return "\n".join(["| The table's columns include | Family | Applies to |",
                       "|---|---|---|", *rows])


# Routes currently running a model bake-off. Empty in normal operation: the
# contract is blind dual extraction, and a bench lane is a measurement device.
BENCH_ROUTES: frozenset[str] = frozenset()


def source_context_rules() -> str:
    return """### Source interpretation and completion

- Each table is reviewed by column and row: date, unit, scale, subject, method, fee treatment and value scope. A comparative column keeps its own date; a component remains separate from the total.
- A named currency heading remains in `currency_scale` beside every governed monetary cell. A bare `$` does not mean US dollars when the heading states Canadian or Australian dollars. Normalization retains that denomination; unconverted currencies remain separate in fund periods and generated amount inputs.
- A statement label such as Total assets is not an institution name. A row that retains that label as its subject uses `other_printed_scope`; the document context identifies the reporting institution or combined group. A single named fund partnership remains a `fund`, not a pension or institutional reporting entity.
- Definitions, legends, accounting policies and performance-method notes are `definition_context` records, including on pages with no numbers. A mixed disclaimer page still yields its methodology records. Illustrative amounts inside a definition remain text, not actual fund observations.
- Definition markers resolve within the same table and page before a unique document-wide definition. A reused marker with different meanings requires a table-specific reference. A Modified Dietz method under a time-weighted heading requires that refinement in the cited definition.
- Text evidence contains the complete printed number, not a substring of another number. Printed number words remain words in `metric_value_raw`; normalization reads the number-word matrix. A TXT conversion defect uses `IMAGE_ONLY:` with the physical page image and a specific explanation; the adjudicator reviews every image-only row.
- Page counts include definitions and all populated allowed comparative cells. The count comes from the page image before reconciliation with the record CSV. Every zero-observation page with numeric signals needs a `NO_ELIGIBLE_REASON:` explanation; thin pages need `PARTIAL_BY_SCOPE:`. Each explanation names excluded rows or columns and the category test, not reading difficulty.
- `UNREADABLE` and `DEFERRED_BY_SCOPE` are unfinished CORE work. A settled exclusion uses `NO_ELIGIBLE_DATA` or `REFERENCE_ONLY` with source-backed reasons. Candidate handoff and final publication share the grid-completeness check; final construction validates before replacing outputs.
- Gates test recorded evidence and consistency. They do not establish that every permitted source fact was found. Both extractors inspect every page, and the adjudicator reviews every populated table's scope and governing notes, including agreements.
- `lane-check` validates existing finals before marking historical work `DONE`; `REVIEW_REQUIRED` goes to the adjudicator, never to an extractor rewriting original candidates.
"""


def extractor_prompt(route: str, agent: str) -> str:
    others = ", ".join(a for a in EXTRACTOR_AGENTS if a != agent)
    # Legal-provision guidance is dead weight on a numeric route: no family
    # there permits term_category, so the text can only mislead.
    has_terms = any(
        FAMILY_CONTRACTS[family].kind == "term"
        for doc_type in ROUTES[route]
        for family in DOC_TYPE_FAMILIES[doc_type]
    )
    legal_split = (
        "\n\n  For a legal provision the same split applies: `term_category` is the"
        " controlled value and the printed wording goes in `text_raw`."
        if has_terms else ""
    )
    term_sort = ", term_category" if has_terms else ""
    disambiguation = disambiguation_table(route)
    family_test = family_test_section(route)
    family_chooser_table = family_chooser(route)
    checklist = extraction_checklist(route)
    record_name = f"records-{agent.lower()}.csv"
    coverage_name = f"coverage-{agent.lower()}.csv"
    return f"""# {ROUTE_TITLES[route]}: EXTRACTOR {agent}

> **Binding:** Do not dispatch sub-agents. Do not use Python, scripts, regex, or automated table parsing to read or extract source content. The extractor reads the source and writes the candidate rows directly into the output CSV. Do not write a generator, builder, emitter, or intermediate data file that expands into rows: the only Python permitted is the validator, audit, and lane commands named below, verbatim except for `<file_id>`, which names the document in progress. **`validate-candidate` and `lane-check` refuse to run while a script that writes candidate rows exists anywhere in the repository, and they name the file.** A generated candidate is not a second reading: it is the first lane's summary retyped by a program, so the two lanes stop being independent and the third reader is comparing a document against itself. On one 149-page document the script classified 104 pages in a single `for page in range(...)` loop, stamping one identical structure name and one identical note across all of them. The judgement happened to be right, and that is the danger: the coverage file reports 104 page readings that were one decision, so a page inside the range that printed something else would have been recorded as reviewed and never looked at. Both the validator and the completeness audit passed it, because a candidate written by a loop and a candidate read off the pages are the same CSV. **The two output CSVs named below are the only files this run creates in the repository.** If you genuinely need a scratch file, it goes in `tmp/` and nowhere else, and you delete it when you are done; a generator is refused there too. Never write one at the repository root: a stray file there fails the structure gate for whoever runs next, and one round left four behind, including a header copy and two helper scripts. Append rows to the output CSVs and save after each table, section, and page, never in one batch at the end of a file. Run `validate-candidate` after the first three pages and `audit-file` after each finished document; both must report PASS before the next document is opened. **`lane-check` decides when this run is over, not your own judgement.** Never delete, empty, overwrite, or reset a candidate file: rows already on disk are finished work, including rows written by an earlier session, and the only permitted write is an append.

- **Project root:** the repository root, the folder holding `README.md`; every path below is relative to it
- **Worklist:** `instructions/01-pdf-extraction-csv/worklists/active/{route}.csv`
- **Record output:** `ledgers/working/pdf-extraction-csv/{route}/<file_id>/{record_name}`
- **Coverage output:** `ledgers/working/pdf-extraction-csv/{route}/<file_id>/{coverage_name}`

Read only this prompt, the assigned worklist, and the listed TXT/PDF/PNG source files. Never open another extractor's candidate ({others}), a comparison file, a resolution, or a final file.

## Your assignment, and how this run ends

**Run this first, before reading any document:**

```powershell
python instructions/01-pdf-extraction-csv/workflow.py lane-check --route {route} --agent {agent}
```

It prints every worklisted document's state. **Work documents marked `NOT_STARTED` or `IN_PROGRESS`, in worklist order.** `DONE` leaves historical candidates unchanged; `REVIEW_REQUIRED` returns an invalid final to the adjudicator without reopening extraction. The command validates existing finals without disclosing their contents; for unfinished extraction it reads only your lane.

Do not take your assignment from the message that dispatched you, from which files happen to exist, or from a count of documents that sounds reasonable. An operator's message can name fewer documents than the worklist holds, and the worklist wins.

**Run it again as your last action.** It re-derives every document's state from the files on disk and fails while any assigned document is unstarted or unfinished. **You are finished when `lane-check` prints PASS, and at no earlier point.** Until then the run is still open, whatever else has passed: a document you never opened produces no failing per-file command anywhere, because `validate-candidate` and `audit-file` each take one `--file` and can only judge a document someone chose to name. One round lost three documents that way, one of them never opened at all, and all three lanes reported themselves finished.

If a document is genuinely beyond this run, say so in your closing report and name it. Silence and a passing per-file check are not the same as a finished lane.

## Deterministic unit

**One CSV row is one source observation.** For a table, one populated allowed value cell is one observation. A printed source row with N populated allowed value columns produces N CSV rows. Never combine several values into one row and never split one value into field-name/value EAV rows.

**Outside a table the same rule is counted differently, and this is where two lanes drift furthest apart.** A table supplies a bounded set of cells, so the row count is not a judgement. Running prose does not: every figure in a sentence is a candidate, and "how many rows does this page yield" has no obvious answer. Measured across one round, extraction volume between the two lanes tracked almost nothing except how much of the document was narrative: on tabular routes the lanes landed within 4% of each other, on a 41%-narrative route one lane wrote 1.9x the other, and on a 68%-narrative route 3.0x. They were not reading different numbers, one lane simply stopped earlier: of 32 values one lane took from a stewardship report, all 32 were in the other lane's set, which held 41 more.

Narrative is counted the same way as a table:

- **Every printed figure in the running text that states a fact about the reporting entity is one row.** `carried out 543 engagement activities, covering 352 companies in 34 countries` is three rows, not one and not a summary. Take them all, including the ones that arrive late in a sentence or in a parenthesis.
- **A figure describing someone else is not allowed**: a market total, a peer or index statistic, a counterparty's own scale, or an external framework's own numbers, unless the page states it as a measure of this entity.
- **A figure repeated from a table already extracted on that page is not a second row.** Prose restating a table cell is the same observation.
- **A provision row (`text_raw`) is one operative statement**: one rule, commitment, threshold, or duty that binds the entity. A sentence carrying two distinct duties is two rows; a paragraph of background around one duty is one row, quoted at the duty.
- **`text_raw` carries the statement itself, not the term that names it.** The page prints `Investment Period: The Company may make investments...` and `Carried Interest ("Carry") - The GP's share of the profits...`; the name and its colon or dash belong in `source_row_label`, and `text_raw` starts at `The Company may make investments...` and `The GP's share of the profits...`. Repeating the name inside the text puts the same fact in two columns and splits the row from the other lane's: one round wrote every paired provision and every paired definition in two forms on two documents, and not one of the nineteen matched. Take the wording after the separator, verbatim from there to the end of the statement.
- If a page is genuinely all background, `NO_ELIGIBLE_DATA` with a category reason is right. This rule invents no rows; it forbids stopping early on a page that keeps printing facts.

Correct:

```text
Fund A | Commitment 100 | Paid-In 80 | Unfunded 20
=> three rows with source_column_label Commitment, Paid-In, and Unfunded.
```

Wrong:

```text
one row containing "Commitment | Paid-In | Unfunded" or one row that keeps only 100.
```

A dash, em dash, blank cell, `$ -`, `N/A`, or `not applicable` produces **no record**. A redacted printed value may be recorded as `REDACTED` with `evidence_class=redacted`.

Performance and benchmark rows remain separate source observations. Example:

```text
Endowment          4.3   7.3
Policy Benchmark   4.4   6.4
```

This produces four rows: two with `subject_type=portfolio` and two with `subject_type=benchmark`.

## Frozen routing

Use `canonical_doc_type`, `route`, and `product_tier` verbatim from the worklist. The TXT header may contain a stale earlier classification; do not reclassify the document.

## Source method

Each worklist row supplies four views of the same document:

| Column | What it is |
|---|---|
| `txt_path` | Page-aligned text. Good for finding content and copying `evidence_quote`. Loses column alignment. |
| `grid_path` | **Pre-computed table grid.** Every numeric cell with its row label, column number and column header, taken from the PDF's own coordinates. |
| `image_dir` | One PNG per page. The authority on layout. |
| `pdf_path` | The original. |

1. Read the TXT header and every physical page in order.
2. Use TXT to locate content and copy `evidence_quote`.
3. **For any table, read `grid_path` for that page before assigning a value to a column.** It lists `source_page, source_row_label, column_index, source_column_label, value_raw`, so which column a number belongs to is already decided. Reading a wide table off linearised text and counting columns by eye is the single largest source of wrong values in this work.
4. Open the corresponding PNG whenever layout, rows, columns, merged headers, chart labels, checkboxes, footnotes, indentation, wide page orientation, OCR, or redaction affects meaning. The PNG decides layout.
5. Finish and save both CSVs for one file before opening the next file.

### Scope and limits of the grid

The grid is a **word map**. The page picture is the source. The grid is not an extraction. It reports what is printed and where. The extractor still decides the record family, the category, the scope, and whether a value is allowed at all.

It is deliberately incomplete, and that is not an error:

- **A page absent from the grid has no detected numeric table.** Narrative pages produce nothing. Scanned pages produce nothing because there is no text layer to measure. Check `data/documents/grids/MANIFEST.csv`: a `text_layer` of `ocr` means that document must be read from its PNGs.
- **Column headers are best-effort.** Some PDFs draw their header text twice, so a header can arrive garbled. `column_index` and `column_x` are always reliable, so when a header is unreadable, name the column once from the PNG and apply it to every row in that column.
- **The grid never decides eligibility.** It lists every number on the page, including totals, subtotals and figures outside this document type's allowed categories. Extract only what the route's scope permits.

If the grid and the PNG disagree, the PNG wins.

## Save progressively (hard requirement)

**Append to the record CSV during reading, never at the end.** Save after every finished table, section, or page. Never hold a document's rows in memory and write them once at the end.

The loop for every document is:

1. Read the next table, section, or page.
2. Extract the observations it supports.
3. **Append those rows to the record CSV and save.**
4. Append that page's row to the page-coverage CSV once the page is finished, and save.
5. Only then move to the next table, section, or page.

Rules:

- Write the header once, then append. Never rewrite the file from scratch and never lose rows already saved.
- Keep the sort order correct in the finished file; sorting at the end is fine, but the rows must already be on disk before that.
- A page is complete only when its coverage row is saved, so records and coverage stay consistent at every point.
- If the session stops mid-document, everything already read is on disk and the next session resumes at the first page with no coverage row.

Long documents are where extractions get lost. Saving per section instead of per file is what makes an interrupted run recoverable and progress visible during the run.

## Allowed scope

{route_contract_table(route)}

### Vocabulary

{vocabulary_table(route)}

### Definitions are data: the `definition_context` family

{source_context_rules()}

The footnotes, legends, and methodology notes that define the numbers are extracted, never discarded. One `definition_context` row per printed footnote, definition, methodology note, or legend entry:

- `definition_keys` carries the printed marker the note is keyed by (`1`, `*`, `**`, `*NM`), verbatim without parentheses; a note with no marker gets a short stable key naming its subject (`METHODOLOGY`, `LEGEND`).
- `text_raw` carries the note's wording, verbatim, **starting after the term it defines**. A glossary line printing `Clawback - GP carried interest that must be returned...` gives `source_row_label` `Clawback` and `text_raw` `GP carried interest that must be returned...`. The defined term is not repeated inside the text; twelve glossary entries split on this alone in one round.
- `condition_raw` carries what the note governs when the page states it (a column, a table, marked rows); blank otherwise.
- `source_structure_type` is `FOOTNOTE` for a footnote, else what the note physically is; `source_table` or `source_section` names the table or section the note annotates; `evidence_class` is `actual`, because the note is printed content.

On a value row, `definition_keys` lists the printed markers attached to that row or its column, pipe-joined. A key resolves to one meaning within its table and page, or to a unique document-wide definition. Conflicting meanings are refused. A marker dropped from a label (checklist rule 3) lands here.

For a qualified category (marked **Qualified** in the vocabulary above), fill its named dimensions (`method`, `fee_basis`, `value_scope`) from a cited footnote or a phrase copied into `basis_raw`. A fund position held by an investor differs from the whole fund. A portfolio total differs from a holding and from a financial-statement line. Strategy components under fund columns use `value_scope=allocation_bucket`; only the total-fund row uses `fund_total`. Component strategy labels are not the fund's constant strategy. A report author's logo does not establish fund management. Write `unstated` only after checking the governing header and footnotes; never infer net fees from the word IRR. Publication rejects blank required dimensions, including historical rows.

### Excluded scope

{route_exclusions(route)}

Only the vocabulary names above are permitted. Do not use `other`, generic dimensions, invented categories, or `SCHEMA_GAP` rows. Put a genuinely useful excluded concept in `notes` of the page-coverage row; do not extract it.

## Record CSV field list

Header, verbatim:

```csv
{header_line(RECORD_COLUMNS)}
```

Rules:

- UTF-8 CSV; quote every cell; **{len(RECORD_COLUMNS)} cells on every single row**, header and data alike.
- **Never omit a column, and never add one.** A column with no value is written as an empty pair of quotes `""`, in its own position. Omitting it shifts every later value one column left, so the row silently reports the wrong field. Count the cells before saving: a correct row contains {len(RECORD_COLUMNS) - 1} commas outside quotes.
- **Extra cells come from unescaped punctuation.** A value containing a comma, a quote, or a line break splits into two cells unless it is quoted correctly. Wrap every cell in double quotes and double any quote inside a value: a printed `Smith, Jones "A" LP` is written as `"Smith, Jones ""A"" LP"`. If a row has too many cells, an unescaped comma or quote inside one of its values is the cause.
- `record_family` is a closed vocabulary. Use only the families listed for this document type in **Allowed scope** below. Never invent one: `holding_position`, `allocation_bucket`, and similar are rejected. If no listed family fits the table, the table is out of scope, so record it in the page-coverage `notes` and extract nothing from it.
- `contract_version` is `{CONTRACT_VERSION}`.
- `agent_role` is `{agent}`; `source_agents` and `adjudication_status` are blank.
- `source_page` is the physical page number.
- `source_structure_type` is one of **{", ".join(SOURCE_STRUCTURE_TYPES)}** and is **UPPERCASE**. A `document_context` row is always `DOCUMENT`; a row read out of a ruled table is `TABLE`.
- `subject_type` is one of {", ".join(SUBJECT_TYPES)} and is **lowercase**. It classifies **what `subject_name` names on the page**, so read the row label and pick from that, never once per document. `Domestic common and preferred stock` is `asset_class`; `Blackstone Capital Partners VII` is `fund`; `Total net assets` on a statement is `reporting_entity`; a named sleeve or pool is `portfolio`. A whole table of `investment` is a sign the label was not read: an aggregated line is not an ownable investment.
- Controlled values are matched character for character. `table` is rejected where `TABLE` is required, and `Fund` is rejected where `fund` is required. Copy the spellings above; do not type them from memory.
- `source_table` is the printed table/figure title, verbatim, the caption that names the whole table. If none exists, use the nearest printed section heading. If neither exists, use `UNTITLED_TABLE_1`, `UNTITLED_TABLE_2`, etc., top-to-bottom on that page. **Never a date, and never a header that sits over only some of the columns.** `December 31, 2015` is a column-group heading, not a table name; the table there is `(3) Investments`. The whole table gets one `source_table`, identical on every row taken from it.

  `source_table` records the printed heading for tables, glossary entries, footnotes and narrative blocks. Table names are compared decisions, not pairing keys.

- The physical-cell key is `file_id`, `source_page`, `source_row_label`, `source_column_label`, and `source_occurrence`. Family, category and table title are compared separately. Labels retain their source wording; a disagreement can require source review even when the values agree.
- `source_row_label` is the printed row/entity/metric label, verbatim. Use `DOCUMENT` only for the single document-context row.

  **Outside a table, it is the printed term the passage defines or the clause heading it runs under, and nothing wider or narrower.** `Investment Period`, `Recall of Distributions`, `Management Fee`, `Carried Interest`. Two mistakes split a row from its partner. Taking the **section heading above the passage** files several different provisions under one label, so `Interim Distributions` arrives three times for three different clauses. Taking the **clause's opening words** invents a label the page never uses as a name, so `(i) First`, `(ii) Second`, and `all legal, tax, and accounting fees` end up in the column. Both happened on one 69-page memorandum: the two lanes wrote the same six provisions and not one of the six met its partner, because one lane used the heading and the other used the opener. If the passage prints no defined term and no clause heading, use the shortest printed phrase that names the subject, never a whole sentence.
- `source_column_label` is the printed **leaf** header for the value cell: the lowest header directly above the column, not the banner spanning several columns. Blank only when the source has no column. Where a table prints `Fair Value Measurements Using` across four columns and `Level 1 | Level 2 | Level 3 | Total` beneath it, the leaf headers are `Level 1`, `Level 2`, `Level 3`, `Total`, and the same rule fixes `metric_name`.
- **The column label must identify the column uniquely within its row.** When the leaf alone repeats across columns, keep the stacked header that separates them, top line first. A table printing `1-Yr 3-Yr 5-Yr 10-Yr` over four columns all headed `Total Return` gives `1-Yr Total Return`, `3-Yr Total Return`, `5-Yr Total Return`, `10-Yr Total Return`. Writing `Total Return` four times collides four values onto one record key and the file is rejected.
- `source_occurrence` is the **Nth time this page prints this row label under this column label**, counted top to bottom then left to right. Normally `1`. It is decided by position on the page and nothing else, so both extractors reach the same number without agreeing on anything interpretive. **A page carrying two tables with the same row labels is the case this exists for**: a page printing `Forward contracts` under `Derivative assets` in one table and again in a second table gives the first `1` and the second `2`. **Count every printing of the label, including ones whose cell under this column is a dash or blank and so produces no row.** A page with eight `Value Added` rows whose first three print `-` under `10 Year` gives the five extracted rows occurrences `4` through `8`, not `1` through `5`: whether a cell is populated is a judgement, where the label sits is not, and one round mis-paired 72 correctly-read cells because the two lanes counted these two ways. Two rows that share a page, row label, column label and occurrence are the same cell by definition, so two different values written there mean that one of them needs the next occurrence number. The single `document_context` row is always `1`.
- **No cell may contain a line break.** Where the source wraps across lines, join it with single spaces so the value stays on one CSV row.
- `evidence_quote` is required on every row and must be **500 characters or fewer**. One short printed line, not a paragraph.
- **`metric_category` and `metric_name` are different columns and must not be swapped.** `metric_category` is a controlled value chosen from the list for that record family in **Allowed scope**. `metric_name` is the label printed on the page, verbatim. They are usually different text, and putting the printed label in `metric_category` is rejected.

  ```text
  printed column header:  Fair Value Rate of Return
  metric_category = return                       (controlled value)
  metric_name     = Fair Value Rate of Return    (printed label, verbatim)
  ```
{legal_split}

  **`metric_name` is the leaf column header, never the banner above it.** If `metric_name` comes out identical on every row of a wide table, the spanning header has been copied and it names the table, not the metric. `Fair Value Measurements Using` spans four columns; the metric names are `Level 1`, `Level 2`, `Level 3`, `Total`.

  Which label names the measure depends on the table's shape, so read the shape first and apply the matching line. Both reading groups reading the same table must map to the same answer, and a run where they did not produced 455 paired rows and **zero** matching pairs.

  | The table's rows are | The table's columns are | `metric_name` is | Example |
  |---|---|---|---|
  | measures (`Total Return`, `Value Added`, `Net Assets`) | periods or dates | the **row label** | `Value Added` over `1 Year / 3 Year` gives `Value Added`, with `3 Year` in `horizon` |
  | entities, funds, or securities | measures (`Level 1`, `Fair Value`, `Cost`) | the **leaf column header** | `Fair Value Measurements Using` spanning `Level 1 / Level 2` gives `Level 1` |
  | entities, funds, or securities | periods or dates | the **measure the table itself names**, from its title or banner, **in its printed wording** | a table titled `Annualized Returns` listing funds by `1 Year / 3 Year` gives `Annualized Returns`, not `Return` |

  Only the third shape may take the name from a banner or title, and only because neither axis names a measure there. Never take a section heading, and never trim, singularise, or paraphrase the printed words. **A period is never a metric name:** if `metric_name` and `horizon` come out identical, the wrong axis has been used.
- `metric_value_raw` and `text_raw` are copied verbatim as printed. Do not calculate or normalize. **A printed `%`, `x`, or currency symbol stays in the value** (`(51.90%)`, `1.4x`, `$61.4`) **and is also recorded in `unit` or `currency_scale`**; the one thing closed is whitespace, so `$ 4,858.5` is written `$4,858.5`. Recording the symbol in `unit` does not license removing it from the value: both carry it. Where the page spells the word instead (`3.6 percent`) there is no symbol to copy and `unit` alone carries it.

  **This is enforced.** `validate-candidate` rejects any row whose own `evidence_quote` shows a `%` or `x` printed against the value while the value has dropped it, and names the row. It is checked on the candidate, not on the adjudicator's desk, because caught here it is one row to retype and caught there it is a conflict on every affected cell: one run split 549 otherwise identical values on this, and a later one shipped 61 of 73 rows in the stripped form.
- `evidence_quote` is a short one-line excerpt, verbatim from the cited page.
- One `document_context` row per document, not one per page or table. **Its `source_page` is always `1`**, whatever page supplied the document's identity. It describes the whole document, so the page number is a constant and not a reading: two lanes that file it on different pages produce a row that cannot pair, and the document's own context row then reaches the adjudicator as two one-sided rows. Six documents of one round split this way, on pages as far apart as 1 and 29.

  **Page 1 keeps the status its printed content deserves, and the context row does not change it.** A cover page is `REFERENCE_ONLY` even though the identity row cites it, because that row is bookkeeping and not an observation. Do not mark page 1 `ELIGIBLE_DATA_EXTRACTED` to account for it, and do not move the row to a later page to free page 1 for another status: ten of twenty-nine published documents moved it, on to pages as far along as 7, and not one of those rows can pair. `records_written` still counts the context row, because it is a record row citing that page.
- Populate only business columns allowed for the selected record family. Every other column is still present on the row as `""`; "blank" means an empty cell, never a missing cell.

Sort records by:

```text
source_page, record_family, source_table, source_row_label,
source_column_label, source_occurrence, metric_category{term_sort}
```

## Field discipline

These rules exist because two independent extractors must produce the same row from the same cell. Every one of them settles a real disagreement seen in practice.

### Only the printed page is a source

Every value must be **visible on the cited physical page**. Never take a value from:

- the TXT header block (`# issuer:`, `# doc_type:`, `# filename:`, `# sha256:`);
- the PDF filename;
- the worklist;
- prior knowledge of the institution.

The header block identifies the document; it is not content. If a page prints `Public Employees' Retirement Fund (PERF)`, that is the value, even when the header names the parent institution. Copy what the page prints, not the organisation's known name.

### Entity fields

| Column | What goes in it |
|---|---|
| `subject_type` | Decided by the row's own printed label, the same way on every row. A label naming a vehicle (`... Fund V, L.P.`, `... LLC`, `... Trust`, a named fund) is `fund`. A label naming the owner's aggregate (`Total Plan`, `Endowment`, `Alternatives Portfolio`, a pool) is `portfolio`. A single holding, security, or property inside a vehicle is `investment`. An index or policy benchmark is `benchmark`; a peer universe, median, or percentile line (`NACUBO`, a Cambridge Associates universe, `Peer Median`) is `peer_group`. A period label (`Q2 2009`, `1-Yr`) is never a subject of any kind; it is `horizon`. One round split `fund` against `investment` on 465 of 466 rows of one document. |
| `subject_name` | The thing this row measures: the printed fund, portfolio, position, or benchmark row label. **Where the page prints both a full name and a ticker or abbreviation for the same subject, take the full name.** A page carrying `Antares Private Credit Fund (ABDC)` gives `Antares Private Credit Fund`, never `ABDC`: two lanes that split on this produce rows naming the same fund two ways, and nothing downstream can join them. |
| `asset_class`, `strategy`, `geography` | **Core analytical dimensions. Fill them whenever the page states them**, because the delivered database is filtered on these. Take the value from the printed grouping that governs the row, in this order: the row's own group heading inside the table (`Private Equity`, `Real Estate`, `Fixed income:`), then the table title, then a document-level statement of what the table covers. Copy it verbatim, colon dropped, and apply the same value to every row under that grouping. Two limits bound it: **never infer a value the page does not state**, and **never copy `subject_name` into these fields**, so a row already labelled `Domestic common and preferred stock` leaves `asset_class` blank because the row label already is the grouping. To spot a group heading mechanically: **a row that prints a label but no values in its value columns is a heading, and it governs every row beneath it until the next such heading.** A returns table printing a bare `Private Assets` line above `Private Equity`, `Absolute Return`, `Real Estate`, `Real Assets`, `Private Credit`, and `Cash` gives all six rows `asset_class` `Private Assets`. Leaving these blank on a page that states them is the single most damaging defect here: the delivered database is filtered on these three columns, so an unlabelled row is invisible to every query that matters. **Which column takes the grouping follows what the grouping names**: an asset-class grouping (`Private Equity`, `Real Estate`) goes to `asset_class`, a style or strategy grouping (`Buyout`, `Opportunistic`, `Value Add`) to `strategy`, and an industry grouping (`Manufacturing`, `Media`, `Hospitality`) to `sector`, never to `asset_class`. |
| `source_section` | The printed section heading above the table, verbatim. Blank only when the page prints no heading. A financial statement's own title (`Statements of Financial Position`, `Statements of Operations`) is a heading: record it. **The reporting entity's name is never a section heading**: on a page headed `Oregon Public Employees Retirement Fund` over `Alternatives Portfolio`, the section is `Alternatives Portfolio` and the entity belongs on the single `document_context` row, not here. Blank here while the page prints a title is a defect, not a judgement call. **A provision or definition outside a table takes the heading its passage runs under**, the same as a table row does: on a memorandum page headed `SUMMARY OF THE OPERATING AGREEMENT`, every provision on that page carries it. One lane left it blank on every provision of a 69-page memorandum while the other filled it, which put a conflict on all seven rows the two lanes shared. |

**When more than one printed name could fill a column, take the nearest and most specific one to the row.**

`manager_name`, `investor_name` and `portfolio_name` are **document-level facts and belong only on the single `document_context` row**. They name the manager, the asset owner, and the portfolio the whole document reports on, so repeating them on every observation adds nothing and the validator rejects them there. Record each once, on the context row, verbatim as the page prints it.

A document title, cover heading, or report name is not a portfolio. If the only candidate for `portfolio_name` is the document title, leave it blank on the context row too.

Worked example. A page titled `University Endowment Fund Profile` prints a table whose rows include `University Long Term Portfolio`:

```text
document_context row: portfolio_name = University Long Term Portfolio
NOT                                     University Endowment Fund   (that is the document title)
observation rows:     portfolio_name = ""                          (document-level, never repeated)
```

### Dates, scale, and units

| Column | Rule |
|---|---|
| `as_of_date`, `period_start`, `period_end` | Copy the fullest printed date governing the individual column. Under `December 31, 2016 and 2015`, the 2016 column uses `December 31, 2016` and the 2015 column uses `December 31, 2015`. Relative dates remain literal when no specific date is printed. |
| `currency_scale` | Copy the printed currency/scale statement verbatim, **parentheses included**: a page printing `($ in millions)` is recorded as `($ in millions)`, not `$ in millions`. Blank only when the page prints no scale. **A magnitude word printed inline with the number belongs here, not in the value.** Prose reading `stood at $52 billion` gives `metric_value_raw` `$52` and `currency_scale` `billion`. The value column holds the numeral, its currency symbol, separators, decimals, sign, and parentheses, and nothing else, so that two rows measuring the same thing stay comparable. |
| `horizon` | The printed measurement period for that value, copied from the header as rendered: `1-Yr`, `3 Year`, `10-Yr`, `Fiscal YTD 9 Months`, `ITD`, `Since Inception`. **Whenever the column header carries a period qualifier, `horizon` is required.** Where the stacked header reads `1-Yr` over `Total Return`, the qualifier goes in `horizon` and `metric_name` is the metric without it (`Total Return`), while `source_column_label` keeps the full `1-Yr Total Return`. Blank only for a value the page attaches to no period. |
| `unit` | The unit of measure printed for that value, and nothing else: `%`, `x`, `bps`, `years`, `shares`. **A currency or a scale is never a unit.** `USD`, `$`, `USD millions`, and `$ in thousands` belong in `currency_scale`, never here. If the page prints no unit of measure, leave `unit` blank; do not infer one. **A `%` or `x` printed in the cell or in the column header is a printed unit and `unit` is required**: `(51.90%)` gives `unit` `%` **and `metric_value_raw` `(51.90%)`**, `1.4x` gives `x` **and `1.4x`**. Filling `unit` never means emptying the symbol out of the value; the two are recorded together and `validate-candidate` rejects a value that dropped one. One round left `unit` blank on 1,007 percentage values, and another stripped the symbol from 61 of 73. |
| `metric_value_raw` | Copy the printed value verbatim, including its currency symbol, thousands separators, decimals, sign, and any parentheses. Two normalisations only: trim leading and trailing spaces, and close the gap between a currency symbol and its digits, so `$ 61.4` is recorded as `$61.4`. Nothing else changes: never round, rescale, strip a symbol, or convert `(1,234)` to `-1234`. |

#### A label printed once still applies to every value under it

**"Printed" means printed anywhere that governs the value, not printed in the same cell.** A table states its unit and its scale once, in a column header, a row label, a table title, or a banner line above the table, and every value underneath inherits it. Reading "printed" as "printed in this cell" leaves whole tables of numbers with no unit and no scale, which is the single most common defect in this work: it strips the meaning from the value and nothing downstream can put it back. `4.3` is not data. `4.3` `%` is.

Apply the nearest governing label, and apply it no wider than it governs:

| The page prints | Applies to | Example |
|---|---|---|
| A unit in the column header (`Return (%)`, `Multiple (x)`) | Every value in **that column** | `unit` = `%` |
| A unit in the row label (`Net IRR (%)`, `TVPI (x)`) | Every value in **that row** | `unit` = `%` |
| A unit or scale in the table title or a banner above it | Every value in **that table** | `$ in thousands` |
| A scale over one column only (`Market Value in Millions ($)`) | **That column only** | leave the percent columns' `currency_scale` blank |

A `Return (%)` banner applies percent units to every governed value. Period labels such as `1 Year` do not establish a unit by themselves.

The limit is unchanged: infer nothing the page does not state somewhere. If no header, label, title, or banner gives a unit, leave `unit` blank.

#### Three more fields that carry the value's meaning

| Column | Rule |
|---|---|
| `as_of_date` | The printed date governing this column or transaction, copied verbatim. A cover date governs only values reported for that date. A governing footnote can state a different measurement date or define a broad label such as Investments as loan commitments; copy that specific date and classify the defined measure. Comparative columns retain their own printed dates. `Last Quarter` remains literal when no specific date is printed; an undated fact stays undated. Ambiguous slash dates require a source-backed date-order decision during normalization. |
| `source_column_label` | On any `TABLE` row, the printed header of the column the value sits in, copied verbatim. Never blank on a `TABLE` row: if the column has no printed header, write `UNLABELED_COLUMN_<n>` using its position from the left, counting the label column as 0. |
| `metric_value_raw` | Never substitute a character to avoid a CSV problem. A thousands comma stays a comma: quote the field. Writing `8,312,575` as `8.312.575` or `8312575` changes the number and no later step can detect it. |

### `evidence_quote`

One short line copied verbatim from the cited TXT page that contains the value. Use the printed source line the value sits on. It must appear on that page verbatim, and **it must contain `metric_value_raw` itself**: the quote proves this number itself, and a page alone proves nothing. A quote naming the table or the row without the figure is rejected. Do not paraphrase, join two lines, or summarise. On a scanned page where the TXT cannot supply the line, start `notes` with `IMAGE_ONLY:`. **Start the quote at the first word of the line's content, dropping a leading list marker**: a bullet, dash, or asterisk that opens a glossary or bulleted line is typography, not wording, the same way a trailing colon is dropped from a label. One lane kept the bullet and the other did not, and six otherwise identical glossary quotes were reported as disagreements.

### Choosing the record family

**The family follows the table, not the document type and not the route name.** A document routed to one lane still yields whichever of its permitted families the table at hand calls for: a performance report containing a partnership capital schedule yields capital-account rows, not return rows. Decide per table, never once per document, and only from the families listed below.

Read the table's column headers and pick the first rule that matches. Only families this document type permits are listed:

{family_chooser_table}

{family_test}### Cells that must be extracted

The scope tables above say what is *allowed* once a cell is picked. This says which cells must be picked, and it is not a matter of judgement. Two readers choosing different subsets of the same page is the largest single source of unusable output in this work: thousands of rows where one extractor recorded a cell the other never looked at, which no third reader can resolve because only one side ever saw it.

For every printed table, in order:

1. Read the table title, every row label, and every column label.
2. Map each value-bearing row or column to one allowed category for the chosen family.
3. **Where a row or column maps to an allowed category, extract every populated cell governed by that mapping.** All of them. A table with 30 rows and 6 mapped columns yields up to 180 rows.
4. Never extract a selection. Take every mapped cell: the small values, the later rows, every row inside a group, and the lines beside the totals. "I captured the important ones" is a failed extraction.
5. Blank, dash, em dash and N/A cells produce nothing. They are not skipped cells; there is no value there to record.
6. A total or subtotal row is extracted only when its own label maps to an allowed category and its grain is clear. `Total Fund` on a returns table is a real observation; a column sum with no printed label is not.
7. Before leaving the page, count the mapped populated cells and put that number in `expected_observation_count`. It must equal the rows written.

If a mapped column is too dense or too wide to resolve from the TXT, open the page image and read it there. Extracting fewer rows is never the answer to a hard table.

**One table produces one family.** Do not split a single printed table across two families because one of its columns looks like a return. A partnership table showing `Capital Commitment | Total Capital Contributed | Total Capital Distributed | Ending Market Value | IRR (%) | TVPI` is entirely `fund_economics_observation`: the IRR and TVPI columns belong to that family too, because they are reported as attributes of the capital account.

The family says what shape of table the cell came from; the category says what the cell means. The two are chosen separately: a TVPI printed in a capital-account table is `fund_economics_observation` with `tvpi`, and the same TVPI in a returns table is `performance_observation` with `tvpi`. Never invent a family to fit a name, and never change a name to fit a family.

### Category disambiguation

When the printed label is ambiguous, use this mapping so both extractors map to the same category:

{disambiguation}

## Page-coverage CSV field list

Header, verbatim:

```csv
{header_line(COVERAGE_COLUMNS)}
```

Write one row for every physical page, including pages with no allowed data. `page_status` is one of: {', '.join(PAGE_STATUSES)}. `layout_checked` is `YES` or `NO` and must be `YES` for any page with an extracted observation.

For each page:

- `expected_observation_count` is the count of populated allowed value cells plus bounded narrative provisions.
- `records_written` must equal the actual number of record rows citing that page.
- `ELIGIBLE_DATA_EXTRACTED` requires at least one observation, and the single `document_context` row is not one.
- Every other status requires zero observation rows on the page. The `document_context` row is the one exception: it sits on page 1 whatever status page 1 carries, and it is still counted in `records_written`.
- `REFERENCE_ONLY` covers a blank page, cover, contents list, contact directory or disclaimer with no in-scope facts or definitions. Glossaries, footnotes and accounting or performance-method notes yield `definition_context` records. `NO_ELIGIBLE_DATA` covers substantive content entirely outside the permitted categories.
- **A `NO_ELIGIBLE_DATA` page that still prints monetary amounts, percentages, or multiples must justify itself: start `notes` with `NO_ELIGIBLE_REASON:` followed by why those figures fall outside this document type's allowed categories.** The validator scans the page for those signals and rejects the row without that prefix, so a page is never silently skipped.
- **An `ELIGIBLE_DATA_EXTRACTED` page whose observation rows fall below a quarter of the values the page grid resolved must justify the gap the same way: start `notes` with `PARTIAL_BY_SCOPE:` naming the rows or columns left out and the category test they fail.** `audit-file` compares what you wrote with what the grid resolved on every page of twelve or more values, the same trigger that challenges a page declared empty, and refuses a thin page whose note lacks that prefix or describes how hard the page was to read. A cash-flow statement with only its opening and closing cash lines in scope is a legitimate thin page, and the note is what says so: `PARTIAL_BY_SCOPE: operating, investing and financing flows, no allowed category; only cash beginning and end of year match`. Two lanes on one audited financial statement published 2 and 4 rows against 23 and 32 printed values with an empty note, and nothing stopped either of them.

#### `NO_ELIGIBLE_DATA` means the page prints nothing allowed, never that it was hard to read

The most valuable pages in this corpus are usually the hardest: a fund-by-fund or holding-by-holding schedule of ten or more columns, running across several pages. **Difficulty is not ineligibility.** The reason must be about *category*, not about *legibility*.

| Not a reason | Why |
|---|---|
| `column assignment not reliable` | The page still prints the data. Resolve the columns from the PNG. |
| `grid and TXT drop columns` | The grid is an aid, not the source. It drops columns on dense tables; that is a known limit of the tool, not a property of the page. |
| `values are not recoverable` | They are printed. They are recoverable from the image. |
| `labels are merged in TXT` | Read the PNG, where they are not merged. |

A valid reason names the category test: `NO_ELIGIBLE_REASON: office contact details, outside the allowed financial categories`. Glossary definitions require records. The same category test governs a `PARTIAL_BY_SCOPE:` note on a thin extracted page.

**When a table is too dense to resolve from the TXT, open the page image and read it there.** That is the escalation, and it is required, not optional. A validator rejects a readability complaint on a page that prints allowed figures. Skipping a partnership schedule because it is wide loses more value than every other defect in this work combined.
- Coverage rows are sorted by `source_page`, one row per page, no page repeated and no page missing.
- `source_structures` lists table/figure/section titles verbatim separated by ` | `.
- `relevant_record_families` lists controlled family names separated by ` | `.

This coverage file is the machine-checkable omission check. Do not mark a page complete until the populated allowed cells have been counted against the PNG.

## Evidence and product rules

Allowed evidence classes: {', '.join(EVIDENCE_CLASSES)}.

- `CORE` candidates may contain only `actual` or `redacted` evidence.
- Template and illustrative documents belong in the `reference` worklist, never the active worklist.
- No personal identifiers, signature images, or personal/operational bank and wire details.

## Declare the executing model, once

Before the first document, run this once. It takes no per-row effort and is never repeated:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py claim --route {route} --agent {agent} --model "<model name>"
```

Name the model actually executing this run, as specifically as it can be identified (for example `claude-opus-5`, `gpt-5.5-xhigh`, `gemini-3-pro`). Rows are stamped with it mechanically at publish time, so **never add a model column to the CSV** and never mention the model in any row. If the model cannot be identified, say so in `--model` instead of guessing a different one.

## Validate each file

```powershell
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route {route} --file <file_id> --agent {agent}
```

Repair until the command passes, then continue to the next worklist row. A valid no-data document has a header-only record CSV and complete page coverage.

**Run it once after the first three pages, before extracting anything else**, adding `--through-page 3`:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route {route} --file <file_id> --agent {agent} --through-page 3
```

`--through-page N` checks everything written up to page N and does not ask for pages not yet reached; a document shorter than N is checked in full, so this command is safe on a one-page or two-page document. Without it the command requires coverage for the whole document, which the opening pages can never satisfy. A row-shape mistake repeats on every row written, so catching it here costs a minute and catching it at the end costs the whole document. It runs after page 3 and not after page 1 because page 1 is a cover, a letter, or a contents page on eleven of the twenty-nine documents published so far, and a coverage row for a cover says nothing about the shape of an observation row: through page 3 the check reaches printed values on twenty-five of those documents where page 1 alone reaches eighteen. Extract pages 1 to 3 first, because the command asks for a coverage row on each page up to 3 and reports the ones not yet reached. Do not extract a fourth page until it passes. Run the command without `--through-page` when the document is finished.

## Audit each finished document

Validation proves the file is well formed. It cannot prove the file is finished, because a page declared empty and a page that is empty look identical in the CSV. Before moving to the next worklist row, run:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route {route} --file <file_id> --agent {agent}
```

It compares the written rows against what the document actually prints, and reports two things:

| Finding | Meaning | Action |
|---|---|---|
| Pages with no coverage row | The run stopped before the end of the document | Cover every remaining page |
| Pages declared empty that the grid resolved into a table | A printed table may have been skipped | Open that page image. Extract it, or replace the note with a reason naming the category test it fails |

**This command must pass before the next document is opened.** It is not advisory and it does not need anyone's approval: run it, act on what it says, run it again.

A flagged page requires source review. Contact details and unrelated statutory text may be excluded with a category reason; relevant glossary definitions are extracted. A difficulty explanation does not settle eligibility.

## Finish the lane

`audit-file` proves one document is finished. It cannot prove the lane is finished, because a document nobody opened is named in no command. Before reporting back, run:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py lane-check --route {route} --agent {agent}
```

It re-derives the state of every worklist document from the files on disk and names each one that is unstarted or unfinished, with the reason. Work those documents and run it again. **Report back only after it prints PASS**, and if you stop while it still fails, say in your reply which documents it named.

## Working memory

This prompt is the spec; the block below is the working memory, and `audit-file` reprints it every time it passes so it stays fresh. When output drifts from it mid-file, stop and re-read the relevant section above before writing another row.

```text
{checklist}
```
"""


def adjudicator_prompt(route: str, shard: int) -> str:
    parity = "odd" if shard == 1 else "even"
    return f"""# {ROUTE_TITLES[route]}: ADJUDICATOR J{shard}

> **Binding:** Do not dispatch sub-agents. Do not use Python, scripts, regex, or automated table parsing to read source content. The workflow may be used only to validate, pair, and build files mechanically. Append decisions to the resolution CSVs and save after each settled group, never in one batch at the end.

- **Project root:** the repository root, the folder holding `README.md`; every path below is relative to it
- **Worklist:** `instructions/01-pdf-extraction-csv/worklists/active/{route}.csv`
- **Shard:** worklist rows with {parity} `work_order` values.

Existing `records-final.csv` or `coverage-final.csv` files require `validate-final` first. A passing final completes that document: preserve its candidates, comparisons, and decisions, then skip it. A failing or incomplete final requires a reported correction request before further work. Reordering the worklist does not reopen completed review.

For each assigned file, wait until both extractors have finished it: `coverage-a.csv` and `coverage-b.csv` each carry a row for every page. Read only this prompt, those candidates, the generated comparison files, the pre-computed table grid at the worklist's `grid_path`, and the source TXT/PDF/PNGs. **The page images at the worklist's `image_dir` are the adjudicator's to open and are expected to be used**; unlike the extractors, the adjudicator is never limited to linearised text.

## Check both lanes before opening a single file

An extractor that stopped early reports itself finished, because every per-file check it runs can only judge a document it chose to name. Run both of these first:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py lane-check --route {route} --agent A
python instructions/01-pdf-extraction-csv/workflow.py lane-check --route {route} --agent B
```

Each prints every worklist document with that lane's state and fails while any is unstarted or unfinished. **A document either lane has not finished cannot be adjudicated**: one side of the comparison does not exist, and `compare` and `build-final` refuse anyway. Adjudicate a document marked `DONE` by both commands only when it has no existing final; preserve completed review and report unfinished extraction by file ID. Do not extract the missing work yourself: a third reader who writes one lane's rows is no longer independent of them.

## Candidate validation and ownership

Both candidates must pass the current candidate and page-completeness checks before a fresh comparison. A failing candidate returns to its original extractor with the reported file, row and error. The adjudicator does not rewrite either blind file or copy a passing lane over a failing lane.

```powershell
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route {route} --file <file_id> --agent A
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route {route} --file <file_id> --agent A
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route {route} --file <file_id> --agent B
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route {route} --file <file_id> --agent B
```

Historical reconstruction reads the original candidates under their recorded contract and uses the existing pair-index and adjudication decisions. It does not certify an old candidate under the current rules. Every constructed final must pass the current semantic and completeness checks before either final output is replaced.

## Declare the executing model, once

Before the first file, run this once. It is never repeated and costs no per-row effort:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py claim --route {route} --agent J{shard} --model "<model name>"
```

Added or resolved rows are stamped with it mechanically at publish time, so **never add a model column** and never name the model in a row.

## Build the deterministic comparison

```powershell
python instructions/01-pdf-extraction-csv/workflow.py compare --route {route} --file <file_id>
```

The command writes `pair-index.csv`, `coverage-diff.csv`, an empty `resolution.csv`, and an empty `coverage-resolution.csv` in the file folder.

A/B records align on the **physical cell**, nothing else:

```text
file_id + source_page + source_row_label + source_column_label + source_occurrence
```

Family, category and table title are deliberately **not** part of identity. They are read decisions, and two careful readers disagree about them on the same printed cell. Pairing on them turned one observation into two unrelated rows and made whole documents unadjudicatable. They are compared instead, so a disagreement arrives as one row with two readings, which is what it always was.

Extractor-created labels and row counts do not establish agreement.

Each conflict is typed so its nature is known before the page is opened:

- `VALUE_CONFLICT`: different readings of a printed cell; resolve against the image.
- `CLASSIFICATION_CONFLICT`: different family, category or subject; review the image and the route vocabulary. A component assigned to a fund total changes the analysis even when the number agrees.
- `CONTEXT_CONFLICT`: different date, unit, scale, horizon or qualifier; review the governing header and notes. A populated field is not automatically correct.

{source_context_rules()}

{route_contract_table(route)}

{vocabulary_table(route)}

{disambiguation_table(route)}

## The adjudicator is the resolving authority

The adjudicator compares both candidates with the source. Unsupported readings remain blocked; no value, identity or qualifier is guessed to obtain a PASS. Every conflict, one-sided record and coverage difference requires a source-backed decision.

Three things follow from that, and they override any instinct to be conservative:

**Open the page image. It is the authority, not a last resort.** The worklist row for this file gives `image_dir`; the pages are `page-001.png`, `page-002.png`, and so on, one per printed page. On a value conflict, a column-assignment question, a header the grid rendered blank or as prose, or any row the TXT leaves unsettled, **read the image before deciding**. The TXT is linearised and loses columns. On the 29 reviewed documents, the corrected grid found 5,509 of 6,577 in-scope printed cells and retained a source header on 92.9% of its matches. The image is what the document actually prints. One adjudicator recovered 260 real cells from a page image that both extractors had skipped, and they verified against the printed arithmetic.

**Correct source readings through adjudication.** After valid candidates have been compared, a source-backed correction uses `MERGE`; a missed definition or value uses `ADD`. Failing candidate validation returns to its owner before comparison. A missing source fact remains blocked pending source review.

**Read the cells both reading groups missed.** `ADD` exists for this. If the page prints an allowed cell neither candidate holds, write it: `pair_id` blank, `agent_role=ADJUDICATED`, `source_agents=ADJUDICATOR`, status `ADDED`, with a real `evidence_quote` from the page. Rows quarantined into `malformed-a.csv` or `malformed-b.csv` are not lost data, they are unread cells: read them off the image and either merge them into the pair or add them.

## Rows requiring source review

Review every conflict, every one-sided pair, every image-only record, and each sampled agreement. Inspect every populated table's date columns, account owner, units and governing footnotes. A defect found in an agreed row requires `MERGE` or `REJECT` even when `requires_review=NO`; review every affected row in that source block.

The source rule is fixed: one populated allowed value cell is one row. A printed row with N populated allowed value columns requires N rows; blanks and dash/N/A cells require zero rows.

**A one-sided row is a claim to check against the page picture.** `A_ONLY` and `B_ONLY` mean one reading group saw a cell the other did not. Read the page: if the cell is printed and allowed, the row is right and the other reading group missed it; if it is not, reject it. Read the page picture. Do not take the one-sided row as proved.

**A document where nothing pairs is expected on prose families, not a failure.** Provisions (`legal_term`, `legal_clause`, `subscription_reference`, `ddq_quantitative_observation`, `stewardship_policy`) are keyed on `source_row_label`, which for prose is whichever fragment each reading group chose, so two reading groups rarely map to the same key. One legal document paired 0 of 88 rows with both reading groups valid. Expect to work those documents row by row against the page instead of by rule, and expect the row count to be the sum of both reading groups minus the merged duplicates.

## Deciding a disagreement

Judge against the printed page, never by which candidate has more rows. The recurring disagreements have fixed answers:

**Consult the grid on a value or column disagreement, then confirm on the page.** The worklist's `grid_path` lists every printed numeric cell for that page with its row label, `column_index` and column header, taken from the PDF's own coordinates. It is a strong witness on column membership, which is where linearised text fails.

It is not an authority. On the 29 reviewed documents, it found **5,509 of 6,577 in-scope printed cells (83.8% recall)**, and 5,509 of its 6,398 rows matched a reviewed cell (86.1% precision). On a dense table it can drop a column, and on a page with narrative text above the table it can take a fragment of a sentence as a column header. So:

- A grid column header that reads as prose (`as of`, `billion`, `2025, up from`) means the grid failed on that page. Ignore its headers there and read them off the PNG.
- A value the grid does not list is not thereby wrong. The grid omits columns it failed to resolve. Check the PNG before deleting a row.
- **When the grid and the page image disagree, the image wins.** Always.

A page is absent from the grid when it is scanned or holds no numeric table; `data/documents/grids/MANIFEST.csv` says which.

A convention applies only within the source block that supports it. Every value, classification and context decision retains its source rationale; agreement between the lanes does not establish correctness.

| Disagreement | Correct answer |
|---|---|
| Same row and column, different numbers | The value printed on the page. Use the grid to locate it, the PNG to confirm it. |
| Same number, different column | The `column_index` the grid assigns it, once the grid's header for that column is confirmed as a real header and not a prose fragment. This is the commonest wrong-value defect: a wide table read from linearised text shifts a column, and the numbers stay plausible. |
| Same number, one side keeps the printed `%`, `x`, or currency symbol and the other strips it (`0.52` vs `0.52%`, `(51.90)` vs `(51.90%)`) | **The printed form, symbol included,** with `unit` set to `%` or `x` and `currency_scale` to the currency. The value column is raw; stripping is a normalisation and is wrong. This single convention was 549 of the 551 value conflicts on one document. **`validate-final` enforces it**: any row whose own `evidence_quote` prints a `%` or `x` attached to the value while the value drops it is rejected, naming the row. Apply it to every row of every document, including the ones where the conflict stays invisible: one shard applied it on two documents and not the third, leaving 61 of 73 rows in the other format, and the same metric reads two ways. Where the page spells the word (`3.6 percent`) there is no symbol to keep, and `unit` alone carries it. |
| Value differs only by spacing | `$61.4` and `$4,858.5`, with no gap between symbol and digits; whitespace is the one thing closed. |
| Same cell, one lane cites the full printed line and the other cites only the value (`(51.90%)`) | The rows are otherwise equal; accept the lane with the full line, because its quote proves the value and the short one proves only that the digits occur somewhere on the page. |
| One side gives `unit` or `currency_scale`, the other blanks it | The populated side, if the page prints that unit or scale in the cell, the column header, the row label, the table title, or a banner above the table. A label printed once governs every value under it. A `%` printed in the cell or column header is a printed unit, so a blank `unit` beside a percentage is wrong. |
| One side blanks any context field: `source_section`, `source_table`, `asset_class`, `strategy`, `geography`, `horizon`, `as_of_date`, `period_start`, `period_end`, `vintage_year`, `currency_scale` | If the page prints it, the populated candidate is right. If the page does not print it, the blank is right. These are per-page facts, so check the page once and apply the answer to every row on it: one lane left `source_section` blank on 1,600 rows whose pages all printed the heading. |
| `source_section` vs `asset_class` for the same heading (`Real Assets`, `Private Assets`, `Fixed income:`) | A heading **inside** the table that governs the rows beneath it is the rows' `asset_class` (or `strategy` or `geography`, by what it names), never `source_section`. `source_section` is the page's section heading **above** the table. Both can be populated on one row; they are different headings. |
| One lane puts a two-level grouping in `asset_class` alone (`Opportunistic`) and leaves `strategy` blank; the other splits it (`Real Estate` / `Opportunistic`) | The split. The broader printed grouping is `asset_class`, the narrower is `strategy`. |
| `subject_type` `fund` vs `investment` vs `portfolio`, or `benchmark` vs `peer_group` | By the row's own label: a vehicle (`... Fund V, L.P.`, `... LLC`, a named fund) is `fund`; the owner's aggregate (`Total Plan`, `Endowment`, `Alternatives Portfolio`) is `portfolio`; a holding, security, or property inside a vehicle is `investment`; an index or policy line is `benchmark`; a peer universe, median, or percentile line (`NACUBO`, a Cambridge universe, `Peer Median`) is `peer_group`. One document split `fund` against `investment` on 465 of 466 rows. |
| Entity name differs | The name **printed on the cited page**, at the most specific level, **in full**: `Antares Private Credit Fund`, never its ticker `ABDC`. A value taken from the TXT header block, the filename, or general knowledge of the institution is wrong even when it names the same organisation. A period label (`Q2 2009`, `1-Yr`) is never a `subject_name`; it belongs in `horizon`. |
| `metric_name` differs only by trimming, singularising, or dropping a qualifier (`Return` vs `Annualized Returns`, `Distribution Rate` vs `Annualized Distribution Rate`) | The printed wording, in full. |
| `metric_name` taken from different axes (`3 Year` vs `Annualized Returns` for the same cell) | Apply the table-shape rule in the extractor prompts: rows that are measures name the metric; rows that are entities under measure columns take the leaf column header; only a table whose rows are entities and whose columns are periods takes its own title. A period is never a metric name. |
| `alpha` vs `return` on a `Value Added`, `Excess Return`, or `Difference` row | `alpha`: the row is the portfolio's return minus its benchmark's. |
| Date format differs | The date **printed verbatim**. `September 30, 2022` is correct; `2022-09-30` is a reformat and is wrong. Where both are verbatim and one is fuller (`March 31, 2026` vs `March 2026`), the fuller printed form. |
| `source_table` is the short heading on one side and the full printed title on the other | The full printed title that names the whole table. |
| Category or family differs | Apply the disambiguation table in the extractor prompts; the family follows the table shape and the category follows the printed meaning, each judged on its own. |
| Family differs on a fund-by-fund table that prints capital-account columns (Commitment, Unfunded, PIC, Market Value) beside multiples and IRRs | `fund_economics_observation`, **every column in that table**, per the extractor chooser. A lane that typed it `performance_observation` also tends to have skipped the capital columns, so its rows are wrong on family and its gaps are filled from the other lane one-sided. On one such table this was 676 paired rows and 126 rows only one lane extracted. |
| Period columns (`Qtr`, `1 Year`, `3 Year`) read as `return` by one lane and `irr` by the other | **The banner over the column block decides, in either family.** A banner reading `IRR`, `Net IRR`, or `Since Inception IRR` makes the columns `irr`; a banner reading `Time Weighted Return`, `TWR`, `Net Time Weighted Returns`, or `Modified Dietz` makes them `return`, and `fund_economics_observation` permits `return` for this case. Name the banner in `reason`. One schedule printed both blocks side by side, `Net Time Weighted Returns (1)` and `Inception IRR (4)`, and 452 rows of the first block were settled as `irr` because the family was thought to forbid `return`; that reading is wrong and is the case this rule exists for. |
| A rate the page labels assumed, expected, target, or actuarial (`Actuarial Assumed Interest Rate`, `Smooth Expected Rate of Return`) | Not `return` and not `irr`. It is an assumption; reject it unless the family has a category for it. |
| A balance-sheet line (`Collective trust funds`, `Investments, at fair value`) read as `nav` | `investment_fair_value` in a `financial_statement_observation` table. `nav` is a fund's or share class's net asset value on a performance, capital-account, or NAV page. |
| A plan's or endowment's total value (`market value of the PUF was $39.5 billion`) read as `nav` | `aum`. |
| A waterfall component (`Preferred return`, `Return of capital`) read as `distribution` | The narrower name when the vocabulary has one: `preferred_return`, `return_of_capital`. A total distribution line stays `distribution`. |
| An expense ratio (`Total Annual Expenses 9.89%`) read as `fee` | `fund_expense` with `unit` `%`. |
| A portfolio share of an asset class (`34%` beside `Natural Resources (Net)`) read as `ownership_percentage` | `actual_allocation`. `ownership_percentage` is a stake in a vehicle or a firm. |
| `Market Value` read as `aum` vs `nav` | `nav` in a `fund_economics_observation` table; `market_value` in a `position_observation` table; `aum` only for a manager's or plan's stated total assets under management. |
| `PIC` or `Paid-In` read as `moic` | `paid_in_capital`. PIC is an amount; `moic` is a multiple. |
| A row carries `REPAIRED_SHIFT` in `notes` | Adjudicate it like any other row. The note records that its cells were realigned; its value is that lane's own reading. |
| The two lanes file the `document_context` row on different pages | `source_page` `1`. The row describes the whole document, so its page is a constant. Merge the two one-sided rows into one. |
| An `A_ONLY` row and a `B_ONLY` row on the same page describe the same printed thing, and differ only in a key column: one lane blank where the other carries a printed heading, most often `source_table` | They are one cell, not two. **Publish one row, not both.** Take the side that carries the printed value, since a heading printed on the page is never correctly blank, and reject the other. Twelve glossary definitions arrived this way on one document, identical in wording, and publishing both sides would have doubled every one of them. Before ruling a page's one-sided rows genuine, sort them by `source_row_label` and check whether an unpaired row on the other side carries the same label. |
| A cover page carries the `document_context` row and one lane marked it `ELIGIBLE_DATA_EXTRACTED` while the other marked it `REFERENCE_ONLY` | `REFERENCE_ONLY`, or whatever the page's printed content deserves. The identity row is bookkeeping and never makes a page eligible, and it stays on page 1 regardless. |
| One lane's `text_raw` repeats the term that names the row and the other's starts after it: `Clawback - GP carried interest that must be returned` against `GP carried interest that must be returned` | The shorter one. The term is already in `source_row_label`, so repeating it stores the same fact twice. **Rule the document once and apply it to every row**: this split arrives on every provision and every definition a lane wrote, never on one of them, and one round produced nineteen of these across two documents. |
| Two one-sided provision rows on the same page carry the same operative wording under different `source_row_label` values, one the section heading above the passage and one the clause's opening words | The printed defined term or clause heading (`Investment Period`, `Recall of Distributions`), and one row, not two. A section heading repeated across several provisions is the giveaway: three clauses filed as `Interim Distributions` are three rows that each belong under their own printed name. Read the page before merging, then reject the duplicate. |
| Prose or provisions on a mixed page | Review the individual clause against its permitted family. Binding rules and definitions are records; historical narrative and unrelated boilerplate are excluded. A document-wide narrative label never overrides a qualifying clause or methodology note. |
| A lane declares a page `NO_ELIGIBLE_DATA` with a reasoned `NO_ELIGIBLE_REASON:` note naming a category test, and the other extracted from it | The note is evidence of judgement, not of abandonment, so read the page before overriding it. If the page prints something in an allowed category the extracting lane is right; if the note correctly identifies it as out of category, the zero is right and the other lane's rows are rejected. Do not resolve it by preferring the larger lane. |

Record the reason applied alongside the decision.

## Resolution CSV

Header, verbatim:

```csv
{header_line(RESOLUTION_COLUMNS)}
```

Allowed decisions:

- `CONFIRM` : the sampled `EXACT` pair is source-correct.
- `ACCEPT_A` : A is source-correct.
- `ACCEPT_B` : B is source-correct.
- `MERGE` : neither candidate is complete; provide one corrected full record in the appended record columns.
- `REJECT` : neither candidate is publishable.

`MERGE` and `ADD` fill the appended record columns; other decisions leave them blank. New or corrected records use contract_version `{CONTRACT_VERSION}`.
- `ADD` : both missed an allowed observation; leave `pair_id` blank and provide the full record.

Every required pair carries one decision. For `MERGE` and `ADD`, use `agent_role=ADJUDICATED`; provide direct source evidence and controlled family/category values. Do not edit A or B.

## Coverage resolution

Header, verbatim:

```csv
{header_line(COVERAGE_RESOLUTION_COLUMNS)}
```

Write one row for every page in `coverage-diff.csv`, after counting allowed source observations from the PNG. The final expected count must equal the final record count on that page. Do not resolve a coverage conflict by choosing the larger candidate automatically.

Three coverage disagreements recur on every document and have fixed answers:

| Disagreement | Correct answer |
|---|---|
| Both lanes report zero rows | Check the page for missing definitions and permitted values before deciding its status. Add in-scope footnotes, legends, accounting policies and methodology with `ADD`; a disclaimer heading does not exclude them. Only then settle `REFERENCE_ONLY` or `NO_ELIGIBLE_DATA`. |
| `expected_observation_count` differs with both reading groups `ELIGIBLE_DATA_EXTRACTED` | Neither reading group's count: each reading group counted what it extracted. Count the allowed cells on the PNG directly; the answer is usually the larger of the two plus whatever both missed, and is never decided by averaging. |
| One reading group `NO_ELIGIBLE_DATA`, the other extracted rows | Read the page. A case study, sidebar, or marketing panel that prints real fund figures (`Fund Commitment $25.7M`, a loss rate, a count of deals) is allowed and its `evidence_class` is `actual` if the figures are stated as fact; the reading group that skipped it was wrong. A panel of hypothetical or illustrative figures is `REFERENCE_ONLY` and the rows are rejected. |

## Save progressively (hard requirement)

**Append each decision when made and save, never in one batch at the end.** Save `resolution.csv` after each settled group of pairs, and `coverage-resolution.csv` after each settled page. Write the header once, then append; never rewrite a file from scratch and lose decisions already recorded. If the session stops, every decision already made is on disk and the next session resumes at the first unresolved pair.

## Allowed scope

{route_contract_table(route)}

### Excluded scope

{route_exclusions(route)}

## Build and validate the final files

```powershell
python instructions/01-pdf-extraction-csv/workflow.py build-final --route {route} --file <file_id>
python instructions/01-pdf-extraction-csv/workflow.py validate-final --route {route} --file <file_id>
```

The workflow publishes agreed unsampled records mechanically and applies the adjudicator's decisions to reviewed pairs. Final rows receive `agent_role=ADJUDICATED`, populated `source_agents`, and an adjudication status of `AGREED`, `VERIFIED_ONE_SIDED`, `RESOLVED`, or `ADDED`.

Finish one file and save its final records and final coverage before opening the next worklist row.
"""


def backfill_prompt(route: str) -> str:
    return f"""# {ROUTE_TITLES[route]}: DEFINITION BACKFILL (lane A or B)

> **Binding:** Do not dispatch sub-agents. Do not use Python, scripts, regex, or automated table parsing to read source content; the only Python permitted is the workflow commands named below. Work one lane (`--agent A` or `--agent B`) named by your dispatch, and never open the other lane's files.

The original extraction read the footnotes that define the numbers and discarded them. This pass goes back to the pages of one already-extracted document and captures them as data. It changes no existing value.

- **Worklist:** `instructions/01-pdf-extraction-csv/worklists/active/{route}.csv`
- **Files:** `ledgers/working/pdf-extraction-csv/{route}/<file_id>/records-<lane>.csv` (rewrite in place; the header is the current {len(RECORD_COLUMNS)}-column contract)

{source_context_rules()}

What this pass writes, and nothing else:

1. **New `definition_context` rows**, one per printed footnote, definition, methodology note, or legend entry, per the Definitions section of this route's extractor prompt: `definition_keys` = the printed marker, `text_raw` = the full printed wording verbatim, `condition_raw` = what it governs when stated, `source_structure_type` = `FOOTNOTE` or what it physically is, `evidence_class` = `actual`, `evidence_quote` = a line of the note. `contract_version` on a new row is `{CONTRACT_VERSION}`; `agent_role` is your lane.
2. **The new columns on existing rows**: `definition_keys` (the printed markers attached to that row or its column, pipe-joined), and for a qualified category `method`, `fee_basis`, `value_scope`, from what the page states through a cited key or a `basis_raw` phrase, else `unstated`.

The atomic unit is unchanged: one populated allowed value cell is one row. This pass adds definition rows beside the value rows and fills their new columns; it never merges, splits, or re-derives a value row.

What never changes, on any existing row: every pre-existing cell. The row's `contract_version`, its value, its labels, its dates, its quotes all stay byte-for-byte. Rows are identified by the physical cell (`source_page`, `source_row_label`, `source_column_label`, `source_occurrence`); never renumber, resort, or delete.

Keep the file sorted by the contract sort order (new definition rows land in position). After each finished document, run and pass both:

```powershell
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route {route} --file <file_id> --agent <lane>
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route {route} --file <file_id> --agent <lane>
```

The dispatching agent reruns both commands independently before the document is called done, then `compare` pairs the two lanes and an adjudicator settles the definition rows like any others.
"""


def write_prompts() -> None:
    for route in ROUTES:
        folder = PROMPT_ROOT / route
        folder.mkdir(parents=True, exist_ok=True)
        # Route READMEs are repository guides, not generated role prompts.
        # Remove only numbered prompt artifacts so a contract rebuild cannot
        # erase the required directory guide.
        for old in folder.glob("[0-9][0-9]-*.md"):
            old.unlink()
        write_text(folder / "01-EXTRACTOR-A.md", extractor_prompt(route, "A"))
        write_text(folder / "02-EXTRACTOR-B.md", extractor_prompt(route, "B"))
        write_text(folder / "05-DEFINITION-BACKFILL.md", backfill_prompt(route))
        # Comparison lanes exist only where a model bake-off is running, and
        # are numbered after the adjudicators. Prompt files are unlinked above,
        # so a lane that leaves BENCH_AGENTS or a route that leaves BENCH_ROUTES
        # is not rewritten.
        if route in BENCH_ROUTES:
            for offset, lane in enumerate(BENCH_AGENTS):
                write_text(folder / f"{offset + 5:02d}-EXTRACTOR-{lane}.md",
                           extractor_prompt(route, lane))
        write_text(folder / "03-ADJUDICATOR-J1.md", adjudicator_prompt(route, 1))
        write_text(folder / "04-ADJUDICATOR-J2.md", adjudicator_prompt(route, 2))


def readme_text() -> str:
    return f"""# PDF extraction and source review

Independent extraction and source review preserve printed values, definitions, table context, and page evidence under contract `{CONTRACT_VERSION}`; [the runbook](00-OPERATOR-RUNBOOK.md) specifies the commands.

| File | Authority |
|---|---|
| `data/schemas/EXTRACTION-ROUTING.csv` | Frozen document classification and route. |
| `data/schemas/EXTRACTION-DISPATCH-SCOPE.csv` | Active, deferred, reference, or unscheduled scope. |
| `data/schemas/MASTER-EXTRACTION-SCHEMA.md` | Human-readable wide-row contract. |
| `FIELD-SELECTION.csv` | Document-type/family/category matrix used by prompts. |
| `CSV-TEMPLATE.csv` | One-row-per-observation record header. |
| `COVERAGE-TEMPLATE.csv` | One-row-per-page omission-control header. |
| `data/documents/grids/` | Pre-computed table grids: every printed numeric cell with its row label and column, from the PDF's coordinates. A reading aid, not an extraction. See that folder's README. |
| `workflow.py` | Mechanical validation, pairing, finalization, and publication. |

Shared candidate and final checks reject incomplete page coverage, contradictory dates and accounting scopes, ambiguous definition references, and incomplete-number quotes; source review determines meaning and eligibility.
"""


def runbook_text(routing: list[dict[str, str]], scope: list[dict[str, str]]) -> str:
    scope_counts = {value: 0 for value in DISPATCH_SCOPES}
    for row in scope:
        scope_counts[row["dispatch_scope"]] += 1
    override_total = sum(1 for row in routing if row["routing_status"] == "RATIFIED_HEADER_OVERRIDE")
    scheduled_ids = {
        row["file_id"] for row in scope if row["dispatch_scope"] != "UNSCHEDULED"
    }
    scheduled_overrides = sum(
        1
        for row in routing
        if row["file_id"] in scheduled_ids
        and row["routing_status"] == "RATIFIED_HEADER_OVERRIDE"
    )
    route_lines = []
    for route, doc_types in ROUTES.items():
        total = sum(1 for row in routing if row["route"] == route)
        active = sum(
            1
            for row in routing
            if row["route"] == route
            and next(item for item in scope if item["file_id"] == row["file_id"])["dispatch_scope"] == "ACTIVE"
        )
        route_lines.append(
            f"| `{route}` | {', '.join(doc_types)} | {total} | {active} | 4 |"
        )
    return f"""# Wide-Row PDF Extraction: Operator Runbook

## Contract

- Version: `{CONTRACT_VERSION}`.
- One record row = one source observation or one whitelisted provision.
- One coverage row = one physical page.
- A and B use identical schemas, routing, grain, categories, and validators.
- J1 handles odd work orders; J2 handles even work orders.

## Current scope

| Scope | Documents |
|---|---:|
| Active assignments | {scope_counts['ACTIVE']} |
| Deferred assignments | {scope_counts['DEFERRED']} |
| Reference/template | {scope_counts['REFERENCE']} |
| Unscheduled full corpus | {scope_counts['UNSCHEDULED']} |

| Route | Document types | Full corpus | Active | Sessions |
|---|---|---:|---:|---:|
{chr(10).join(route_lines)}

## Rebuild and verify the contract

```powershell
python -m src.catalog.simple_pdf_extraction.build_csv_pipeline build
python -m src.catalog.simple_pdf_extraction.build_csv_pipeline verify
python instructions/01-pdf-extraction-csv/workflow.py verify-contract
```

## Build the page grids

Every worklist row points at a pre-computed table grid in `grid_path`. Build them before dispatching, and rebuild whenever the corpus changes:

```powershell
python -m src.catalog.simple_pdf_extraction.build_page_grids --scope active
```

About 1.5 seconds per document. See `data/documents/grids/README.md` for what the grid does and does not cover; `data/documents/grids/MANIFEST.csv` records which documents produced one and why any did not.

Routing comes from `data-gathering/source_ledger.csv` and is frozen in `data/schemas/EXTRACTION-ROUTING.csv`. `{override_total}` corpus documents and `{scheduled_overrides}` currently scheduled documents have stale TXT-header classifications marked `RATIFIED_HEADER_OVERRIDE`; agents never reclassify documents.

To change scope, edit only `data/schemas/EXTRACTION-DISPATCH-SCOPE.csv` and rerun the builder. Valid scope values are `ACTIVE`, `DEFERRED`, `REFERENCE`, and `UNSCHEDULED`.

## Dispatch

For each route, launch:

1. `01-EXTRACTOR-A.md`
2. `02-EXTRACTOR-B.md`
3. `03-ADJUDICATOR-J1.md`
4. `04-ADJUDICATOR-J2.md`

Prompts are under `dispatch-prompts/<route>/`. Each is self-contained. `05-DEFINITION-BACKFILL.md` is the brief for the definition-backfill pass over already-extracted documents; it runs as two lanes plus adjudication like an extraction, and the dispatching agent, never the extracting one, runs `validate-candidate` and `audit-file` on each lane before a document is called done.

## Per-file lifecycle

```powershell
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 02-performance --file SRC060 --agent A
python instructions/01-pdf-extraction-csv/workflow.py validate-candidate --route 02-performance --file SRC060 --agent B
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route 02-performance --file SRC060 --agent A
python instructions/01-pdf-extraction-csv/workflow.py audit-file --route 02-performance --file SRC060 --agent B
python instructions/01-pdf-extraction-csv/workflow.py compare --route 02-performance --file SRC060
python instructions/01-pdf-extraction-csv/workflow.py build-final --route 02-performance --file SRC060
python instructions/01-pdf-extraction-csv/workflow.py validate-final --route 02-performance --file SRC060
```

`validate-candidate` proves the file is well formed. `audit-file` proves it is finished: it reports pages with no coverage row, and pages declared empty that the grid resolved into a printed table. Extractors run it themselves after each document; it needs no operator decision.

## Per-lane completion

Both commands above take one `--file`, so neither can see a document the lane never opened: to a per-file check, unstarted and unassigned look the same. This reads the worklist instead, recomputes every document's state from the files on disk, and fails while any of them is unstarted or unfinished.

```powershell
python instructions/01-pdf-extraction-csv/workflow.py lane-check --route 02-performance --agent A
python instructions/01-pdf-extraction-csv/workflow.py lane-check --route 02-performance --agent B
```

Each extractor runs it first, to read its assignment, and last, as the condition for reporting back. **Run it yourself before dispatching an adjudicator**: a lane that stopped early reports itself finished, and the adjudicator would then work a document with one side missing. It also removes the need to name file ids in a dispatch message, because the worklist already states them and this command states what is left.

## Monitor and publish

```powershell
python instructions/01-pdf-extraction-csv/workflow.py status --scope active
```

Consolidation runs in two stages, each checked on its own, so a failure is located before it can spread.

**Stage 1, one round.** Validates every adjudicated document in that round and writes the round's own pair of files. Run it as soon as a round is adjudicated; it never waits for another route and rewrites nothing but its own two files.

```powershell
python instructions/01-pdf-extraction-csv/workflow.py publish --scope active --route 04-quarterly-report
```

- `data/extracted/rounds/<route>-records.csv` (the {len(RECORD_COLUMNS)} contract columns plus `extractor_model`)
- `data/extracted/rounds/<route>-coverage.csv`

**Stage 2, the corpus.** Concatenates the published rounds. It reads the round files, not the documents, so what ships is what stage 1 checked.

```powershell
python instructions/01-pdf-extraction-csv/workflow.py publish --scope active
```

- `data/extracted/pdf-wide-records.csv`
- `data/extracted/pdf-wide-coverage.csv`

Both stages block instead of shipping a partial result. Stage 1 fails if any document in the round is missing or fails `validate-final`, naming every bad document at once. Stage 2 fails if a round in scope was never consolidated, and re-derives each round from its documents to compare against the published file, so a round edited or re-adjudicated since it was published is named and blocked instead of leaving stale rows in the corpus.

"""


def _assert_no_retired_fields() -> list[str]:
    """Generated prompts must not name a field the contract has removed."""
    problems = []
    for path in sorted(PROMPT_ROOT.rglob("[0-9][0-9]-*.md")):
        text = path.read_text(encoding="utf-8")
        for field in RETIRED_FIELDS:
            if field in text:
                n = sum(1 for line in text.splitlines() if field in line)
                problems.append(f"{path.name}: {n} line(s) name retired field {field!r}")
    return problems


def verify_generated() -> list[str]:
    errors: list[str] = _assert_no_retired_fields()
    routing = read_csv(ROUTING_PATH) if ROUTING_PATH.is_file() else []
    expected = corpus_size()
    if len(routing) != expected or len({row.get("file_id") for row in routing}) != expected:
        errors.append(
            f"routing registry must contain {expected} unique documents, found {len(routing)}"
        )
    if set(row.get("canonical_doc_type") for row in routing) != set(CANONICAL_DOC_TYPES):
        errors.append(f"routing registry must cover all {len(CANONICAL_DOC_TYPES)} ratified document types")
    for route in ROUTES:
        full = read_csv(WORKLIST_ROOT / f"{route}.csv")
        if any(row.get("route") != route for row in full):
            errors.append(f"{route}: worklist route mismatch")
        prompts = sorted((PROMPT_ROOT / route).glob("[0-9][0-9]-*.md"))
        # Two extractors, two adjudicators, one definition-backfill brief; plus
        # the comparison lanes while this route is running a model bake-off.
        expected = 5 + (len(EXTRACTOR_AGENTS) - 2 if route in BENCH_ROUTES else 0)
        if len(prompts) != expected:
            errors.append(
                f"{route}: expected {expected} prompts, found {len(prompts)}")
        for prompt in prompts:
            text = prompt.read_text(encoding="utf-8")
            for banned in ("one row = one field occurrence", "record_label", "field_name,value_raw"):
                if banned in text:
                    errors.append(f"{prompt}: contains retired EAV marker {banned!r}")
            if "one populated allowed value cell" not in text.casefold():
                errors.append(f"{prompt}: missing atomic table-cell rule")
            if b"\r\n" in prompt.read_bytes():
                errors.append(f"{prompt}: CRLF line endings")
    expected_headers = {
        INSTRUCTION_ROOT / "CSV-TEMPLATE.csv": RECORD_COLUMNS,
        INSTRUCTION_ROOT / "COVERAGE-TEMPLATE.csv": COVERAGE_COLUMNS,
        INSTRUCTION_ROOT / "RESOLUTION-TEMPLATE.csv": RESOLUTION_COLUMNS,
        INSTRUCTION_ROOT / "COVERAGE-RESOLUTION-TEMPLATE.csv": COVERAGE_RESOLUTION_COLUMNS,
        INSTRUCTION_ROOT / "BATCH-WORKLIST-TEMPLATE.csv": WORKLIST_COLUMNS,
    }
    for path, expected in expected_headers.items():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            actual = next(csv.reader(handle))
        if actual != list(expected):
            errors.append(f"{path}: header mismatch")
    selected: list[str] = []
    for folder in ("active", "deferred", "reference"):
        for route in ROUTES:
            selected.extend(row["file_id"] for row in read_csv(WORKLIST_ROOT / folder / f"{route}.csv"))
    if len(selected) != len(set(selected)):
        errors.append("active/deferred/reference worklists overlap")
    if errors:
        return errors
    return []


def build() -> None:
    routing = build_routing_registry()
    scope = build_dispatch_scope(routing)
    write_worklists(routing, scope)
    write_templates()
    write_schema_files()
    write_prompts()
    # The repository README is a reviewer guide with generated accounting.
    # A contract rebuild may seed it in a bare checkout, but it must preserve
    # the tracked guide during ordinary regeneration.
    readme_path = INSTRUCTION_ROOT / "README.md"
    if not readme_path.is_file():
        write_text(readme_path, readme_text())
    write_text(INSTRUCTION_ROOT / "00-OPERATOR-RUNBOOK.md", runbook_text(routing, scope))
    errors = verify_generated()
    if errors:
        raise RuntimeError("Generated contract failed verification:\n- " + "\n- ".join(errors))
    print(
        f"PASS: generated {len(ROUTES) * 5} prompts, {corpus_size()} routing rows, "
        f"{len(FAMILY_CONTRACTS)} record families, contract {CONTRACT_VERSION}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"), nargs="?", default="build")
    args = parser.parse_args()
    if args.command == "build":
        build()
        return
    errors = verify_generated()
    if errors:
        raise SystemExit("FAIL:\n- " + "\n- ".join(errors))
    print("PASS: generated wide-row extraction contract is internally consistent")


if __name__ == "__main__":
    main()
