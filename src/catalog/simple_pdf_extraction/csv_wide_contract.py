"""Closed wide-row field list for deterministic PDF extraction.

One CSV row is one source observation or one bounded narrative provision.  The
module is the field list used by the prompt generator, validators,
pairing, third reader, migration, and tests.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Final, Iterable, Mapping

from src.common import matrices

CONTRACT_VERSION: Final = "2026-09-01.2"

# Every plain decision below reads from a matrix under
RECORD_COLS = "record-columns"
DIMENSION_VALUES_MATRIX = "dimension-values"
DOC_ROUTES = "doc-type-route"
RETIRED = "retired-fields"
VOCABULARIES = "closed-vocabularies"
METRICS = "metric-vocabulary"
TERMS = "term-vocabulary"
TEXT_HINTS = "text-categories"
RECORD_FAMILIES = "record-families"
DOC_FAMILIES = "doc-type-families"
NULL_LIKE = "null-like-values"
TEMPLATES = "template-patterns"
KEY_RULES = "key-normalization"
PAIR_KEY = "pair-key"
SAMPLING = "sampling-policy"


ROUTES: Final[dict[str, tuple[str, ...]]] = {}
for _row in matrices.load(DOC_ROUTES):
    if _row["input_value"] != "product_tiers":
        ROUTES.setdefault(_row["output_value"], ())
        ROUTES[_row["output_value"]] = (*ROUTES[_row["output_value"]], _row["input_value"])

CANONICAL_DOC_TYPES: Final[tuple[str, ...]] = tuple(
    doc_type for doc_types in ROUTES.values() for doc_type in doc_types
)
DOC_TYPE_TO_ROUTE: Final[dict[str, str]] = {
    doc_type: route for route, doc_types in ROUTES.items() for doc_type in doc_types
}

PRODUCT_TIERS: Final = tuple(matrices.resolve(DOC_ROUTES, "product_tiers").split("|"))
DEFAULT_PRODUCT_TIER: Final[dict[str, str]] = {
    row["input_value"]: row["product_tier"]
    for row in matrices.load(DOC_ROUTES)
    if row["input_value"] != "product_tiers"
}


# Field names that are not columns. Generated prose that names one
# tells an agent to fill a column that does not exist; the rows of
# retired-fields.csv.
RETIRED_FIELDS: Final[tuple[str, ...]] = tuple(matrices.mapping(RETIRED))

# Extraction lanes. These live here, not in the workflow, because the prompt
# generator and the validator both need them and the generator cannot import
# the workflow. One list keeps a dropped lane out of the prompts.
CANDIDATE_AGENTS: Final[tuple[str, ...]] = ("A", "B")
# Bench lanes are judged like A and B but never paired or adjudicated:
# they compare models on identical work, they do not produce final rows. Empty
# means no bake-off is running: name a lane here and a route in BENCH_ROUTES to
# start one, and the prompt, the candidate files, and the dashboard row follow.
BENCH_AGENTS: Final[tuple[str, ...]] = ()
EXTRACTOR_AGENTS: Final[tuple[str, ...]] = (*CANDIDATE_AGENTS, *BENCH_AGENTS)

# The record field list is a matrix: one row per column, ordered by position,
# each stamped with the contract version that introduced it. Loaders accept any
# version's header and treat the columns a row's version predates as blank.
def contract_version_key(value: str) -> tuple[date, int]:
    """Return the date and numeric revision encoded in a contract version."""

    try:
        day, revision = value.rsplit(".", 1)
        if not revision.isdigit():
            raise ValueError
        return date.fromisoformat(day), int(revision)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"contract version must use YYYY-MM-DD.<revision>, found {value!r}"
        ) from exc


_RECORD_COLUMN_ROWS = sorted(matrices.load(RECORD_COLS), key=lambda row: int(row["input_value"]))
RECORD_COLUMNS: Final[tuple[str, ...]] = tuple(row["output_value"] for row in _RECORD_COLUMN_ROWS)
KNOWN_CONTRACT_VERSIONS: Final[tuple[str, ...]] = tuple(
    sorted(
        {row["since_contract"] for row in _RECORD_COLUMN_ROWS},
        key=contract_version_key,
    )
)
RECORD_HEADERS_BY_VERSION: Final[dict[str, tuple[str, ...]]] = {
    version: tuple(
        row["output_value"]
        for row in _RECORD_COLUMN_ROWS
        if contract_version_key(row["since_contract"]) <= contract_version_key(version)
    )
    for version in KNOWN_CONTRACT_VERSIONS
}
if RECORD_HEADERS_BY_VERSION[CONTRACT_VERSION] != RECORD_COLUMNS:
    raise ValueError("record-columns.csv carries a column newer than CONTRACT_VERSION")

COVERAGE_COLUMNS: Final[tuple[str, ...]] = (
    "contract_version",
    "file_id",
    "source_sha256",
    "canonical_doc_type",
    "route",
    "product_tier",
    "agent_role",
    "source_page",
    "page_status",
    "layout_checked",
    "source_structures",
    "relevant_record_families",
    "expected_observation_count",
    "records_written",
    "notes",
)

WORKLIST_COLUMNS: Final[tuple[str, ...]] = (
    "work_order",
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

PAIR_COLUMNS: Final[tuple[str, ...]] = (
    "pair_id",
    "pair_status",
    "requires_review",
    "source_page",
    "record_family",
    "source_table",
    "source_row_label",
    "source_column_label",
    "source_occurrence",
    "metric_category",
    "term_category",
    "a_row_number",
    "b_row_number",
    "difference_fields",
)

RESOLUTION_COLUMNS: Final[tuple[str, ...]] = (
    "pair_id",
    "decision",
    "reason",
    *RECORD_COLUMNS,
)

COVERAGE_DIFF_COLUMNS: Final[tuple[str, ...]] = (
    "source_page",
    "a_page_status",
    "b_page_status",
    "a_layout_checked",
    "b_layout_checked",
    "a_expected_observation_count",
    "b_expected_observation_count",
    "a_source_structures",
    "b_source_structures",
    "a_relevant_record_families",
    "b_relevant_record_families",
    "difference_fields",
)

COVERAGE_RESOLUTION_COLUMNS: Final[tuple[str, ...]] = (
    "source_page",
    "final_page_status",
    "final_expected_observation_count",
    "reason",
)

EVIDENCE_CLASSES: Final = tuple(
    row["input_value"] for row in matrices.rows_in(VOCABULARIES, "evidence_class")
)
CORE_EVIDENCE_CLASSES: Final = tuple(
    row["input_value"] for row in matrices.rows_in(VOCABULARIES, "core_evidence_class")
)
def _vocabulary(context: str) -> tuple[str, ...]:
    """One closed vocabulary of dimension-values.csv, in matrix row order.

    Order is load-bearing: the generated prompts and the field guide print
    these lists, so a reordered matrix rewrites prose the prompt tests pin.
    """

    return tuple(row["input_value"] for row in matrices.rows_in(DIMENSION_VALUES_MATRIX, context))


REFERENCE_EVIDENCE_CLASSES: Final = _vocabulary("reference_evidence_class")

SOURCE_STRUCTURE_TYPES: Final = _vocabulary("source_structure_type")

PAGE_STATUSES: Final = _vocabulary("page_status")

SUBJECT_TYPES: Final = _vocabulary("subject_type")

# The vocabulary: one row per name, once. `record_family` is the table grain
# (statement, holdings, capital account, allocation, and so on) and owns no
# private list; a metric family accepts any metric name and a term family any
# term name. The preferred family is guidance for a mixed table, and the
# validator does not enforce it. Names are the printed measures and terms of
# the 442-document corpus.
#
# (category, definition, unit_hint, preferred_family)

# (category, definition, preferred_family)

METRIC_VOCABULARY: Final[tuple[tuple[str, str, str, str], ...]] = tuple(
    (row["input_value"], row["output_value"], row["unit_hint"], row["preferred_family"])
    for row in matrices.load(METRICS)
)
TERM_VOCABULARY: Final[tuple[tuple[str, str, str], ...]] = tuple(
    (row["input_value"], row["output_value"], row["preferred_family"])
    for row in matrices.load(TERMS)
)

METRIC_CATEGORIES: Final[tuple[str, ...]] = tuple(row[0] for row in METRIC_VOCABULARY)
TERM_CATEGORIES: Final[tuple[str, ...]] = tuple(row[0] for row in TERM_VOCABULARY)
METRIC_DEFINITIONS: Final[dict[str, tuple[str, str]]] = {row[0]: (row[1], row[2]) for row in METRIC_VOCABULARY}
TERM_DEFINITIONS: Final[dict[str, str]] = {row[0]: row[1] for row in TERM_VOCABULARY}
PREFERRED_METRIC_FAMILY: Final[dict[str, str]] = {row[0]: row[3] for row in METRIC_VOCABULARY}
PREFERRED_TERM_FAMILY: Final[dict[str, str]] = {row[0]: row[2] for row in TERM_VOCABULARY}
# Metric names whose printed value is wording, not a number; the unit hints
# come from text-categories.csv under the contract context.
TEXT_METRICS: Final[frozenset[str]] = frozenset(
    name
    for name, (_, unit) in METRIC_DEFINITIONS.items()
    if unit in set(matrices.resolve(TEXT_HINTS, "text_unit_hints", context="contract").split("|"))
)

# Qualifier columns of the vocabulary matrices: which categories need a stated
# method, fee basis, or value scope before their number means one thing, and
# what each category's disposition downstream is. The allowed values of each
# dimension live in dimension-values.csv alone, so they cannot drift.
METRIC_QUALIFIERS: Final[dict[str, dict[str, object]]] = {
    row["input_value"]: {
        "qualified": row["qualified"] == "yes",
        "required_dimensions": tuple(part for part in row["required_dimensions"].split("|") if part),
        "disposition": row["disposition"],
    }
    for row in matrices.load(METRICS)
}
TERM_QUALIFIERS: Final[dict[str, dict[str, object]]] = {
    row["input_value"]: {
        "qualified": row["qualified"] == "yes",
        "required_dimensions": tuple(part for part in row["required_dimensions"].split("|") if part),
        "disposition": row["disposition"],
    }
    for row in matrices.load(TERMS)
}
QUALIFIER_DIMENSIONS: Final[dict[str, tuple[str, ...]]] = {}
for _row in matrices.rows_in(DIMENSION_VALUES_MATRIX, "qualifier"):
    _dimension, _, _value = _row["input_value"].partition(":")
    QUALIFIER_DIMENSIONS.setdefault(_dimension, ())
    QUALIFIER_DIMENSIONS[_dimension] = (*QUALIFIER_DIMENSIONS[_dimension], _value)


def preferred_categories(record_family: str) -> tuple[str, ...]:
    """The vocabulary names whose preferred home is this family, in vocabulary order."""

    metrics = tuple(name for name, family in PREFERRED_METRIC_FAMILY.items() if family == record_family)
    terms = tuple(name for name, family in PREFERRED_TERM_FAMILY.items() if family == record_family)
    return (*metrics, *terms)


PROVENANCE_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "contract_version",
        "file_id",
        "source_sha256",
        "canonical_doc_type",
        "route",
        "product_tier",
        "agent_role",
        "record_family",
        "source_page",
        "source_structure_type",
        "source_section",
        "source_table",
        "source_row_label",
        "source_column_label",
        "source_occurrence",
        "evidence_quote",
        "evidence_class",
        "notes",
        "source_agents",
        "adjudication_status",
    }
)
BUSINESS_COLUMNS: Final[frozenset[str]] = frozenset(RECORD_COLUMNS) - PROVENANCE_COLUMNS

# The business columns each family shape may fill. They are the rows of
# dimension-values.csv under one context per shape, so the validator and the
# prompt generator read one list and a column added to a family is a matrix
# row rather than an edit here.
COMMON_METRIC_FIELDS: Final[frozenset[str]] = frozenset(_vocabulary("common_metric_fields"))
COMMON_TERM_FIELDS: Final[frozenset[str]] = frozenset(_vocabulary("common_term_fields"))
DEFINITION_FIELDS: Final[frozenset[str]] = frozenset(_vocabulary("definition_fields"))
CONTEXT_FIELDS: Final[frozenset[str]] = frozenset(_vocabulary("context_fields"))
for _name, _fields in (
    ("common_metric_fields", COMMON_METRIC_FIELDS),
    ("common_term_fields", COMMON_TERM_FIELDS),
    ("definition_fields", DEFINITION_FIELDS),
    ("context_fields", CONTEXT_FIELDS),
):
    _unknown = sorted(_fields - set(RECORD_COLUMNS))
    if _unknown:
        raise ValueError(
            f"dimension-values.csv context {_name} names columns the record "
            f"contract does not carry: {', '.join(_unknown)}"
        )


@dataclass(frozen=True)
class FamilyContract:
    """The grain of one table shape. `kind` says which category column the
    family fills: a metric family fills `metric_category` from the whole metric
    vocabulary, a term family fills `term_category` from the whole term
    vocabulary, and the context family fills neither."""

    description: str
    grain: str
    required_fields: frozenset[str]
    allowed_fields: frozenset[str]
    kind: str = "context"
    tabular: bool = False

    @property
    def metric_categories(self) -> tuple[str, ...]:
        return METRIC_CATEGORIES if self.kind == "metric" else ()

    @property
    def term_categories(self) -> tuple[str, ...]:
        return TERM_CATEGORIES if self.kind == "term" else ()


FAMILY_CONTRACTS: Final[dict[str, FamilyContract]] = {
    "document_context": FamilyContract(
        "One source-backed document identity and reporting context row.",
        "one row per document",
        frozenset({"subject_type", "subject_name"}),
        CONTEXT_FIELDS,
    ),
    "financial_statement_observation": FamilyContract(
        "A whitelisted alternative-investment financial-statement value cell.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "performance_observation": FamilyContract(
        "A printed return, multiple, risk, valuation, or benchmark value cell.",
        "one populated allowed source value cell",
        frozenset({"subject_type", "subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "fund_economics_observation": FamilyContract(
        "A printed commitment, paid-in, distribution, NAV, unfunded, multiple, or capital-account value cell.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "position_observation": FamilyContract(
        "A printed holding or private-market position measure.",
        "one populated allowed source value cell for one named position",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "allocation_observation": FamilyContract(
        "A printed portfolio allocation amount or percentage.",
        "one populated allowed source value cell for one allocation bucket",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "fee_observation": FamilyContract(
        "A printed fee, carry, expense, offset, cost, rate, or benchmark value.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "cash_flow_observation": FamilyContract(
        "A printed call, contribution, distribution, fee, expense, or other investor cash-flow value.",
        "one populated allowed source value cell or one notice component the page states in words",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "nav_observation": FamilyContract(
        "A printed NAV, share-class, transaction-price, component, repurchase, assumption, or sensitivity value.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "valuation_observation": FamilyContract(
        "A printed valuation result, method, input, adjustment, frequency, or governance fact.",
        "one printed valuation fact or one populated value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "financing_observation": FamilyContract(
        "A printed borrowing, facility, balance, rate, availability, or maturity value.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "legal_term": FamilyContract(
        "A whitelisted fund, economic, liquidity, governance, or investor-protection term.",
        "one printed term or one numbered provision whose primary meaning matches the whitelist",
        frozenset({"term_category", "text_raw"}),
        COMMON_TERM_FIELDS,
        kind="term",
    ),
    "legal_clause": FamilyContract(
        "A listed operative right, duty, restriction, waiver, or trigger.",
        "one numbered or separately headed operative provision whose primary meaning matches the whitelist",
        frozenset({"term_category", "text_raw"}),
        COMMON_TERM_FIELDS,
        kind="term",
    ),
    "ddq_quantitative_observation": FamilyContract(
        "A selected quantitative due-diligence fact; narrative question-and-answer transcription is excluded.",
        "one printed quantitative answer or table value",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "stewardship_observation": FamilyContract(
        "A printed stewardship, voting, engagement, climate, or governance metric.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "stewardship_policy": FamilyContract(
        "A concise operative stewardship policy from a named framework or policy section.",
        "one separately headed operative policy statement",
        frozenset({"term_category", "text_raw"}),
        COMMON_TERM_FIELDS,
        kind="term",
    ),
    "subscription_reference": FamilyContract(
        "A non-sensitive subscription-document reference fact; qualification narratives and personal identifiers are excluded.",
        "one whitelisted subscription reference fact",
        frozenset({"term_category", "text_raw"}),
        COMMON_TERM_FIELDS,
        kind="term",
    ),
    "definition_context": FamilyContract(
        "One printed footnote, definition, methodology note, or legend entry, captured verbatim with the key it defines.",
        "one printed footnote, definition, methodology note, or legend entry",
        frozenset({"definition_keys", "text_raw"}),
        DEFINITION_FIELDS,
    ),
}

# record-families.csv is the identity registry: one row per family with its
# grain. The contracts below carry the structural field lists; a mismatch
# between the registry and the contracts stops the import.
_family_registry = {row["input_value"]: row["grain"] for row in matrices.load(RECORD_FAMILIES)}
if set(_family_registry) != set(FAMILY_CONTRACTS) or any(
    _family_registry[name] != contract.grain for name, contract in FAMILY_CONTRACTS.items()
):
    raise ValueError("record-families.csv and FAMILY_CONTRACTS disagree")


DOC_TYPE_FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    row["input_value"]: tuple(row["output_value"].split("|"))
    for row in matrices.load(DOC_FAMILIES)
}

NULL_LIKE_VALUES: Final[frozenset[str]] = frozenset(matrices.mapping(NULL_LIKE))
TEMPLATE_PATTERN: Final = re.compile(
    matrices.resolve(TEMPLATES, "template_pattern"), re.IGNORECASE
)
WHITESPACE_PATTERN: Final = re.compile(matrices.resolve(KEY_RULES, "whitespace_pattern"))


def route_for_doc_type(doc_type: str) -> str:
    try:
        return DOC_TYPE_TO_ROUTE[doc_type]
    except KeyError as exc:
        raise ValueError(f"Unknown ratified document type: {doc_type!r}") from exc


def normalize_key_text(value: str) -> str:
    normalized = unicodedata.normalize(matrices.resolve(KEY_RULES, "unicode_form"), value or "")
    normalized = normalized.replace("\u00a0", " ")
    return WHITESPACE_PATTERN.sub(" ", normalized).strip().casefold()


def record_key(row: Mapping[str, str]) -> tuple[str, ...]:
    """Physical address of the printed cell, used for A/B pairing.

    Identity is *where the value is printed*, never what an extractor decided it
    means. `record_family`, `metric_category`, `term_category`, and
    `source_table` are chosen by the reader, so they sit in
    `comparison_payload` rather than in this key: a classification disagreement
    is a conflict on one row, not two unpaired readings of the same cell.

    `source_table` is excluded for the same reason: on a page carrying a report
    title, a section heading and a table caption, two readers legitimately
    transcribe different titles for the same table.
    """

    fields = tuple(
        (rank_row["output_value"], rank_row["normalized"])
        for rank_row in sorted(
            (row_ for row_ in matrices.load(PAIR_KEY) if row_["input_value"] != "pair_id_format"),
            key=lambda item: int(item["input_value"]),
        )
    )
    return tuple(
        normalize_key_text(row.get(field, "")) if norm == "key_text" else str(row.get(field, ""))
        for field, norm in fields
    )


def record_pair_id(row: Mapping[str, str]) -> str:
    material = "\x1f".join(record_key(row)).encode("utf-8")
    return "PAIR_" + hashlib.sha256(material).hexdigest()[:24].upper()


def comparison_payload(row: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """Everything two candidates must agree on once they point at the same cell.

    Semantic fields sit here, so a classification difference is a conflict on
    one row rather than two unpaired readings.
    """
    ignored = {"agent_role", "notes", "source_agents", "adjudication_status"}
    return tuple((column, normalize_key_text(row.get(column, ""))) for column in RECORD_COLUMNS if column not in ignored)


def is_null_like(value: str) -> bool:
    return normalize_key_text(value) in NULL_LIKE_VALUES


def is_template_placeholder(value: str) -> bool:
    return bool(TEMPLATE_PATTERN.search(value or ""))


def allowed_business_columns(record_family: str) -> frozenset[str]:
    return FAMILY_CONTRACTS[record_family].allowed_fields


def required_business_columns(record_family: str) -> frozenset[str]:
    return FAMILY_CONTRACTS[record_family].required_fields


def allowed_metric_categories(record_family: str) -> tuple[str, ...]:
    """The whole metric vocabulary for a metric family, nothing for the rest."""

    return FAMILY_CONTRACTS[record_family].metric_categories


def allowed_term_categories(
    record_family: str, canonical_doc_type: str | None = None
) -> tuple[str, ...]:
    """The whole term vocabulary for a term family, nothing for the rest. The
    document type is accepted for call compatibility; routing is by family."""

    return FAMILY_CONTRACTS[record_family].term_categories


def deterministic_sample(pair_id: str, *, modulus: int | None = None) -> bool:
    """Stable 10% sample used to source-check otherwise matching A/B pairs."""

    if modulus is None:
        modulus = int(matrices.resolve(SAMPLING, "sample_modulus"))
    digest = int(hashlib.sha256(pair_id.encode("ascii")).hexdigest()[:8], 16)
    return digest % modulus == int(matrices.resolve(SAMPLING, "sample_residue"))


def header_line(columns: Iterable[str]) -> str:
    return ",".join(f'"{column}"' for column in columns)


def empty_record() -> dict[str, str]:
    return {column: "" for column in RECORD_COLUMNS}


def empty_coverage() -> dict[str, str]:
    return {column: "" for column in COVERAGE_COLUMNS}


# Which contract version introduced each record column. New names go at the end
# of this module: several matrices cite a line number in it, and an insertion
# higher up moves the line every one of them points at.
COLUMN_SINCE_CONTRACT: Final[dict[str, str]] = {
    row["output_value"]: row["since_contract"] for row in _RECORD_COLUMN_ROWS
}


def predates_column(contract_version: str, column: str) -> bool:
    """True when a row stamped `contract_version` was written before `column` existed.

    The stamp names the columns the writer of that row was asked to fill. A
    blank in a column the writer never had is a dimension nobody read, which is
    a different fact from `unstated`, the word for a page that states none.
    Only a page reading turns the first into either.
    """

    try:
        since = COLUMN_SINCE_CONTRACT[column]
    except KeyError as exc:
        raise ValueError(f"record-columns.csv carries no column {column!r}") from exc
    return contract_version_key(contract_version) < contract_version_key(since)
