"""Validator, comparer, third-reader builder, and publisher.

This module never extracts source facts.  It enforces the wide-row field list on
human/agent-written CSVs and performs only deterministic file operations.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Iterable, Mapping, Sequence

from .build_csv_pipeline import (
    extraction_checklist,
    PROJECT_ROOT,
    ROUTING_PATH,
    SCOPE_PATH,
    WORKLIST_ROOT,
    corpus_size,
    read_csv as read_simple_csv,
    verify_generated,
)
from .csv_wide_contract import (
    BUSINESS_COLUMNS,
    CANDIDATE_AGENTS,
    CONTRACT_VERSION,
    EXTRACTOR_AGENTS,
    CORE_EVIDENCE_CLASSES,
    COVERAGE_COLUMNS,
    COVERAGE_DIFF_COLUMNS,
    COVERAGE_RESOLUTION_COLUMNS,
    DOC_TYPE_FAMILIES,
    EVIDENCE_CLASSES,
    FAMILY_CONTRACTS,
    KNOWN_CONTRACT_VERSIONS,
    METRIC_QUALIFIERS,
    QUALIFIER_DIMENSIONS,
    RECORD_HEADERS_BY_VERSION,
    PAGE_STATUSES,
    PAIR_COLUMNS,
    RECORD_COLUMNS,
    RESOLUTION_COLUMNS,
    ROUTES,
    SOURCE_STRUCTURE_TYPES,
    SUBJECT_TYPES,
    allowed_metric_categories,
    allowed_term_categories,
    comparison_payload,
    contract_version_key,
    deterministic_sample,
    is_null_like,
    is_template_placeholder,
    normalize_key_text,
    predates_column,
    record_key,
    record_pair_id,
)
from . import semantic_checks

WORKING_ROOT = PROJECT_ROOT / "ledgers" / "working" / "pdf-extraction-csv"
GRID_ROOT = PROJECT_ROOT / "data" / "documents" / "grids"

# Write targets are resolved when used, never captured at import. A constant
# built from PROJECT_ROOT at import time ignores a patched root, which is how
# the unit suite came to write 42 rows into the production model ledger.
def published_records() -> Path:
    return PROJECT_ROOT / "data" / "extracted" / "pdf-wide-records.csv"


def published_coverage() -> Path:
    return PROJECT_ROOT / "data" / "extracted" / "pdf-wide-coverage.csv"


# One consolidated file per extraction round, so a round can be read on its own
# as soon as it is adjudicated instead of waiting for the slowest route. The
# names are fixed by route: same path every time, no run or date in them, and a
# re-publish of a round replaces its own file and nothing else.
def round_records(route: str) -> Path:
    return PROJECT_ROOT / "data" / "extracted" / "rounds" / f"{route}-records.csv"


def round_coverage(route: str) -> Path:
    return PROJECT_ROOT / "data" / "extracted" / "rounds" / f"{route}-coverage.csv"


def model_ledger() -> Path:
    return PROJECT_ROOT / "ledgers" / "analysis" / "model-ledger.csv"


# The rows a page reading still owes the corpus: one line per document, metric
# category and blank dimension. Static path, rewritten whole on every corpus
# publication, so it states the backlog of the scope as it is now.
def qualifier_backlog_ledger() -> Path:
    return PROJECT_ROOT / "ledgers" / "pipeline" / "qualifier-backlog.csv"


QUALIFIER_BACKLOG_COLUMNS: Final = (
    "route",
    "file_id",
    "metric_category",
    "blank_dimension",
    "row_count",
)

ADJUDICATOR_AGENTS = ("J1", "J2")
CLAIMABLE_AGENTS = (*EXTRACTOR_AGENTS, *ADJUDICATOR_AGENTS)
# Who stands behind a published row. A merge on a one-sided pair credits the
# one lane that read the cell and the adjudicator: writing A+B+ADJUDICATOR
# there would report two readers on a row only one of them ever saw.
FINAL_SOURCE_AGENTS = (
    "A+B",
    "A",
    "B",
    "A+B+ADJUDICATOR",
    "A+ADJUDICATOR",
    "B+ADJUDICATOR",
    "ADJUDICATOR",
)
FINAL_STATUSES = ("AGREED", "VERIFIED_ONE_SIDED", "RESOLVED", "ADDED")
# Two candidates pointing at the same printed cell can disagree in three very
# different ways, and an adjudicator should not have to read the row to find out
# which. A wrong number is a transcription error; a wrong category is a mapping
# decision; a missing date or unit is context. They need different attention.
# The decisions below read from matrices under
CONFLICT_SEVERITY = "conflict-severity"
ELIGIBILITY = "eligibility-signals"
ATTRIBUTION = "model-attribution"
GRID_RULES = "grid-thresholds"
REPAIR_RULES = "value-repair"
TOKEN_RULES = "printed-tokens"
REALIGNMENT = "pair-realignment"
SAMPLING_RULES = "review-sampling"
OUTCOMES = "adjudication-outcomes"
COVERAGE_METADATA = "coverage-metadata-policy"
COVERAGE_LAYOUT = "coverage-layout-policy"
LANE_SELECTION = "extraction-lane-selection"
BENCHMARK_MALFORMED_SHARE = "benchmark-malformed-share"
RECORD_STATUS_POLICY = "record-status-policy"

from src.common import matrices

VALUE_FIELDS = frozenset(
    row["input_value"]
    for row in matrices.rows_in(CONFLICT_SEVERITY, "field_class")
    if row["output_value"] == "value_conflict"
)
CLASSIFICATION_FIELDS = frozenset(
    row["input_value"]
    for row in matrices.rows_in(CONFLICT_SEVERITY, "field_class")
    if row["output_value"] == "classification_conflict"
)
PAIR_STATUSES = (
    "EXACT", "VALUE_CONFLICT", "CLASSIFICATION_CONFLICT", "CONTEXT_CONFLICT",
    "A_ONLY", "B_ONLY",
)

# QUALIFIERS_SINCE, the contract version that introduced the qualifier
# columns, used to gate the qualified-category check. It is retired: a row's
# stamp says which columns its header had when it was written, not which
# columns the file has now, and every published row carried a stamp older than
# the qualifier columns, so the check ran on nothing. `columns_carried` reads
# the file's own header instead.


def conflict_kind(differences: Sequence[str]) -> str:
    """Name the worst disagreement present, value first."""
    if any(field in VALUE_FIELDS for field in differences):
        return "VALUE_CONFLICT"
    if any(field in CLASSIFICATION_FIELDS for field in differences):
        return "CLASSIFICATION_CONFLICT"
    return "CONTEXT_CONFLICT"
RESOLUTION_DECISIONS = tuple(
    row["input_value"]
    for row in matrices.rows_in(OUTCOMES, "")
    if row["output_value"] == "legal_decision"
)
KEY_IGNORED_FIELDS = {"agent_role", "notes", "source_agents", "adjudication_status"}
ELIGIBILITY_KEYWORDS = tuple(
    row["input_value"] for row in matrices.rows_in(ELIGIBILITY, "keyword")
)
NUMERIC_SIGNAL = re.compile(matrices.resolve(ELIGIBILITY, "numeric_signal_pattern"))


class ContractFailure(RuntimeError):
    pass


def write_csv(path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
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
            writer.writerow({column: row.get(column, "") for column in columns})


def write_header_if_missing(path: Path, columns: Sequence[str]) -> None:
    if not path.exists():
        write_csv(path, columns, [])


ABSENT_COLUMNS_KEY: Final = "__absent_columns"
ABSENT_COLUMNS_JOIN: Final = "|"


def columns_carried(row: Mapping[str, str]) -> frozenset[str]:
    """The record columns the file this row came from actually has.

    A row built in memory carries every column of the current contract; a row
    read from a narrower file carries the marker `read_strict_csv` stamped on
    it. Checks that require a column ask this first, so a file is held to the
    columns it has and never to columns it predates.
    """

    absent = row.get(ABSENT_COLUMNS_KEY)
    if not absent:
        return frozenset(RECORD_COLUMNS)
    return frozenset(RECORD_COLUMNS) - set(absent.split(ABSENT_COLUMNS_JOIN))


def _legacy_headers(expected_header: Sequence[str]) -> list[tuple[str, ...]]:
    """Every historical shape of a record-carrying header.

    The record field list grows by appended columns, one batch per contract
    version, and files written under an older version keep their shape. A
    header that embeds the record columns (candidates, finals, resolutions,
    rounds) is therefore accepted in any known version's width, and the columns
    that version predates load as blank. Only known shapes load; anything else
    is still a header mismatch.
    """

    expected = tuple(expected_header)
    current = tuple(RECORD_COLUMNS)
    variants: list[tuple[str, ...]] = []
    for start in range(len(expected) - len(current) + 1):
        if expected[start : start + len(current)] == current:
            for header in RECORD_HEADERS_BY_VERSION.values():
                variant = (*expected[:start], *header, *expected[start + len(current):])
                if variant != expected:
                    variants.append(variant)
            break
    return variants


def read_strict_csv(path: Path, expected_header: Sequence[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise ContractFailure(f"Missing file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.reader(handle))
    if not raw_rows:
        raise ContractFailure(f"{path}: empty file")
    header = list(expected_header)
    if raw_rows[0] != header:
        legacy = next(
            (list(variant) for variant in _legacy_headers(expected_header)
             if raw_rows[0] == list(variant)),
            None,
        )
        if legacy is None:
            raise ContractFailure(
                f"{path}: header mismatch\nexpected={list(expected_header)!r}\nactual={raw_rows[0]!r}"
            )
        header = legacy
    rows: list[dict[str, str]] = []
    width = len(header)
    blank_fill = {column: "" for column in expected_header if column not in header}
    # Which columns this file does not have. A row loads every expected column
    # so callers can read it uniformly, and the blanks a narrower header left
    # behind are indistinguishable from a cell the writer left empty. A check
    # that demands a column must know which of the two it is looking at, so the
    # file's own shape travels with the row.
    absent = ABSENT_COLUMNS_JOIN.join(sorted(blank_fill))
    malformed: list[tuple[int, int]] = []
    for line_number, values in enumerate(raw_rows[1:], 2):
        if values == []:
            raise ContractFailure(f"{path}:{line_number}: blank CSV row")
        if len(values) != width:
            malformed.append((line_number, len(values)))
            continue
        row = dict(zip(header, values, strict=True))
        row.update(blank_fill)
        row["__line_number"] = str(line_number)
        row[ABSENT_COLUMNS_KEY] = absent
        rows.append(row)
    if malformed:
        raise ContractFailure(_width_failure(path, header, width, malformed,
                                             len(raw_rows) - 1))
    return rows


def _width_failure(
    path: Path,
    expected_header: Sequence[str],
    width: int,
    malformed: Sequence[tuple[int, int]],
    total: int,
) -> str:
    """Explain a width mismatch as the shape problem it usually is.

    Reporting only the first bad line reads as one typo. When most of a file is
    the same wrong width the cause is a column dropped from every row, and the
    fix is to rewrite the file against the header, not to patch a line.
    """
    counts = Counter(found for _, found in malformed)
    lines = [f"{path}: {len(malformed)} of {total} rows do not have {width} cells"]
    for found, n in counts.most_common(3):
        first = next(ln for ln, f in malformed if f == found)
        lines.append(f"  {n} row(s) with {found} cells, first at line {first}")
    dominant, n = counts.most_common(1)[0]
    if n >= 3 and n >= len(malformed) * 0.8:
        missing = width - dominant
        if missing > 0:
            lines.append(
                f"  This is one shape, not {n} typos: every row is {missing} cell(s) "
                f"short. A column is missing from the whole file."
            )
        else:
            lines.append(
                f"  This is one shape, not {n} typos: every row carries {-missing} "
                f"extra cell(s). An unquoted comma or an added column."
            )
        lines.append(f"  The header has {width} columns: {', '.join(expected_header)}")
        lines.append(
            "  Rewrite the file emitting all "
            f"{width} columns in that order, blank where a field does not apply."
        )
    return "\n".join(lines)


def clean_row(row: Mapping[str, str], columns: Sequence[str]) -> dict[str, str]:
    return {column: row.get(column, "") for column in columns}


def routing_registry() -> dict[str, dict[str, str]]:
    rows = read_simple_csv(ROUTING_PATH)
    return {row["file_id"]: row for row in rows}


def routing_for(route: str, file_id: str) -> dict[str, str]:
    if route not in ROUTES:
        raise ContractFailure(f"Unknown route: {route}")
    row = routing_registry().get(file_id)
    if not row:
        raise ContractFailure(f"Unknown file_id: {file_id}")
    if row["route"] != route:
        raise ContractFailure(f"{file_id}: belongs to {row['route']}, not {route}")
    return row


def page_image_errors(routing: Mapping[str, str]) -> list[str]:
    """Extraction requires one 300 DPI PNG per physical page."""
    image_dir = (routing.get("image_dir") or "").strip()
    file_id = routing.get("file_id", "?")
    filename = routing.get("filename") or f"{file_id}.pdf"
    try:
        page_count = int(float(routing["page_count"]))
    except (KeyError, TypeError, ValueError):
        return [f"{file_id}: page_count failed to parse."]
    if page_count < 1:
        return [f"{file_id}: page_count must be at least 1."]
    command = (
        "    python data-gathering/src/render_image_corpus.py "
        f"--pdf {filename}"
    )
    if not image_dir:
        return [
            f"{file_id}: worklist image_dir is empty. Render the PDF first:\n{command}"
        ]
    missing = [
        page
        for page in range(1, page_count + 1)
        if not (PROJECT_ROOT / image_dir / f"page-{page:03d}.png").is_file()
    ]
    if not missing:
        return []
    shown = ", ".join(f"page-{page:03d}.png" for page in missing[:8])
    extra = f" and {len(missing) - 8} more" if len(missing) > 8 else ""
    return [
        f"{file_id}: extraction requires a 300 DPI PNG for every physical page "
        f"under {image_dir}. Absent: {shown}{extra}. Render the PDF first:\n{command}"
    ]


def require_images_command(route: str, file_id: str) -> None:
    routing = routing_for(route, file_id)
    errors = page_image_errors(routing)
    if errors:
        raise ContractFailure(
            "Page pictures are required for extraction:\n- " + "\n- ".join(errors)
        )
    print(
        f"PASS: {route}/{file_id} has {routing['page_count']} page pictures "
        f"under {routing['image_dir']}"
    )


def file_folder(route: str, file_id: str) -> Path:
    return WORKING_ROOT / route / file_id


# Attribution. Nothing inside a candidate CSV identifies the model that wrote
# it, so the model is declared once per run and stamped onto every row
# mechanically at publish time. The candidate schema is deliberately untouched:
# a 44th column would cost the extractor a field on every row, which is the
# per-row drain this design exists to avoid.
MODEL_LEDGER_COLUMNS: Final = (
    "route", "agent_role", "extractor_model", "claimed_at", "claimed_by",
)
UNDECLARED_MODEL: Final = matrices.resolve(ATTRIBUTION, "undeclared_model")
# An agent asked to name itself will sometimes write a word meaning "I did not
# answer" instead of refusing. Rejecting only the sentinel let a whole route be
# claimed as `unknown`, which reads in the ledger just like a real name and
# loses the attribution the claim exists to capture.


PLACEHOLDER_MODELS: Final = frozenset(
    row["input_value"] for row in matrices.rows_in(ATTRIBUTION, "placeholder")
)


def claim_path(route: str) -> Path:
    return WORKING_ROOT / route / "RUN-CLAIM.csv"


def read_claims(route: str) -> dict[str, dict[str, str]]:
    """The model currently holding each agent slot on this route."""
    path = claim_path(route)
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["agent_role"]: row for row in csv.DictReader(handle)}


def claimed_model(route: str, agent: str) -> str:
    return read_claims(route).get(agent, {}).get("extractor_model", "")


def model_that_wrote(route: str, file_id: str, agent: str) -> str:
    """The model claiming this slot when this candidate file was last written.

    Binding to the current claim would re-attribute finished work every time a
    slot is reused: model X extracts a document, model Y later claims the same
    slot, and X's rows publish under Y's name. The append-only ledger carries
    the claim history, so the honest answer is the newest claim not later than
    the file's own mtime.
    """
    record_path, _ = candidate_paths(route, file_id, agent)
    if not record_path.is_file():
        return claimed_model(route, agent) or UNDECLARED_MODEL
    written = datetime.fromtimestamp(record_path.stat().st_mtime, timezone.utc)
    best = ""
    if model_ledger().is_file():
        with model_ledger().open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("route") != route or row.get("agent_role") != agent:
                    continue
                try:
                    stamp = datetime.strptime(
                        row["claimed_at"], "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                except (KeyError, ValueError):
                    continue
                if stamp <= written:
                    best = row.get("extractor_model", "")
    return best or claimed_model(route, agent) or UNDECLARED_MODEL


def claim_command(route: str, agent: str, model: str, by: str = "") -> None:
    if route == "all":
        for one in ROUTES:
            claim_command(one, agent, model, by)
        return
    if route not in ROUTES:
        raise ContractFailure(f"Unknown route: {route}")
    if agent not in CLAIMABLE_AGENTS:
        raise ContractFailure(
            f"agent must be one of {', '.join(CLAIMABLE_AGENTS)}, found {agent!r}")
    model = " ".join(model.split())
    if not model or model.casefold().strip("<>[]()\"'") in PLACEHOLDER_MODELS:
        raise ContractFailure(
            "--model must name the model actually running, e.g. "
            "'claude-opus-5', 'gpt-5.5-xhigh', 'gemini-3-pro'"
        )
    stamp = _timestamp()
    # The claim file is rewritten whole, and the two adjudicators on a route
    # both claim at startup. Launched together, one read-modify-write could
    # overwrite the other's row, so the update runs under an exclusive lock.
    with _exclusive(claim_path(route)):
        claims = read_claims(route)
        claims[agent] = {
            "route": route, "agent_role": agent, "extractor_model": model,
            "claimed_at": stamp, "claimed_by": by,
        }
        write_csv(claim_path(route), MODEL_LEDGER_COLUMNS,
                  [claims[a] for a in sorted(claims)])
        # Append-only history, so a slot reused by a different model later still
        # leaves the earlier run attributable.
        write_header_if_missing(model_ledger(), MODEL_LEDGER_COLUMNS)
        with model_ledger().open("a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=list(MODEL_LEDGER_COLUMNS),
                           quoting=csv.QUOTE_ALL, lineterminator="\n").writerow(claims[agent])
    print(f"PASS: {route} Extractor {agent} claimed by {model} at {stamp}")


@contextmanager
def _exclusive(path: Path, wait_seconds: float = 10.0):
    """Hold an exclusive lock on `path` via an O_EXCL sidecar.

    A lock file is the one primitive that works the same on every filesystem
    this runs on. If a previous holder died and left the sidecar behind, it is
    treated as stale after `wait_seconds` and taken over, so a crash can never
    wedge every later claim.
    """
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(handle)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                lock.unlink(missing_ok=True)
                continue
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# A page the grid resolved into this many aligned value cells is a table, not a
# page that happens to carry digits. Below the lower bound the evidence is weak;
# above the upper bound no honest narrative, footnote block, or office directory
# has ever reached it, so declaring such a page empty is a hard failure.
GRID_TABLE_CELLS: Final = int(matrices.resolve(GRID_RULES, "table_cells"))
GRID_TABLE_ROWS: Final = int(matrices.resolve(GRID_RULES, "table_rows"))
GRID_CERTAIN_CELLS: Final = int(matrices.resolve(GRID_RULES, "certain_cells"))
# Below this share of the printed values on a dense page, the page was skimmed.
GRID_THIN_RATIO: Final = float(matrices.resolve(GRID_RULES, "thin_ratio"))
# The note prefix a thin extracted page must carry, the counterpart of
# NO_ELIGIBLE_REASON: on a page declared empty. A thin page is often right (a
# cash-flow statement with two lines in scope), so the ratio decides nothing on
# its own; what it demands is the reason, naming what was left out and the
# category test it fails.
PARTIAL_REASON: Final = "PARTIAL_BY_SCOPE:"


def grid_path_for(file_id: str) -> Path | None:
    registry = routing_registry().get(file_id)
    if not registry:
        return None
    return GRID_ROOT / f"{Path(registry['filename']).stem}.csv"


def grid_built(file_id: str) -> bool:
    """Was a grid produced for this document at all?

    A scanned document produces a header-only grid, which is a real answer:
    there is no text layer to measure. That is not the same as never having
    run the builder, and only the second case blinds the audit.
    """
    path = grid_path_for(file_id)
    return bool(path and path.is_file())


def grid_page_shape(file_id: str) -> dict[int, tuple[int, int]]:
    """Per page: how many value cells the grid resolved, over how many rows.

    Only counts values sitting in a column the grid could resolve
    arithmetically, so a page of phone numbers and street addresses stays near
    zero while a partnership schedule runs into the hundreds.
    """
    path = grid_path_for(file_id)
    if not path or not path.is_file():
        return {}
    cells: Counter[int] = Counter()
    rows: dict[int, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                page = int(row["source_page"])
            except (KeyError, ValueError):
                continue
            cells[page] += 1
            rows[page].add(row.get("row_index", ""))
    return {page: (n, len(rows[page])) for page, n in cells.items()}


def candidate_paths(route: str, file_id: str, agent: str) -> tuple[Path, Path]:
    suffix = agent.casefold()
    folder = file_folder(route, file_id)
    return folder / f"records-{suffix}.csv", folder / f"coverage-{suffix}.csv"


def _outcome(name: str) -> tuple[str, str]:
    """The credited agents and the status one adjudication outcome publishes."""

    row = next(row_ for row_ in matrices.load(OUTCOMES) if row_["input_value"] == name)
    return row["source_agents"], row["status"]


def final_paths(route: str, file_id: str) -> tuple[Path, Path]:
    folder = file_folder(route, file_id)
    return folder / "records-final.csv", folder / "coverage-final.csv"


def pair_paths(route: str, file_id: str) -> dict[str, Path]:
    folder = file_folder(route, file_id)
    return {
        "pair": folder / "pair-index.csv",
        "coverage_diff": folder / "coverage-diff.csv",
        "resolution": folder / "resolution.csv",
        "coverage_resolution": folder / "coverage-resolution.csv",
    }


def positive_integer(value: str, label: str, errors: list[str], location: str) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{location}: {label} must be an integer, found {value!r}")
        return None
    if number <= 0:
        errors.append(f"{location}: {label} must be positive, found {value!r}")
        return None
    return number


def nonnegative_integer(value: str, label: str, errors: list[str], location: str) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{location}: {label} must be an integer, found {value!r}")
        return None
    if number < 0:
        errors.append(f"{location}: {label} must be nonnegative, found {value!r}")
        return None
    return number


def record_sort_key(row: Mapping[str, str]) -> tuple[object, ...]:
    try:
        page: object = int(row.get("source_page", ""))
    except ValueError:
        page = 10**9
    try:
        occurrence: object = int(row.get("source_occurrence", ""))
    except ValueError:
        occurrence = 10**9
    return (
        page,
        row.get("record_family", ""),
        normalize_key_text(row.get("source_table", "")),
        normalize_key_text(row.get("source_row_label", "")),
        normalize_key_text(row.get("source_column_label", "")),
        occurrence,
        row.get("metric_category", ""),
        row.get("term_category", ""),
    )


def split_pipe(value: str) -> list[str]:
    if not value.strip():
        return []
    return [part.strip() for part in value.split("|") if part.strip()]


def joined_sorted(values: Iterable[str]) -> str:
    return " | ".join(sorted({value.strip() for value in values if value.strip()}, key=normalize_key_text))


def source_page_texts(routing: Mapping[str, str]) -> dict[int, str]:
    path = PROJECT_ROOT / routing["txt_path"]
    if not path.is_file():
        return {}
    page_text: dict[int, list[str]] = defaultdict(list)
    current_page: int | None = None
    banner = re.compile(r"^=====\s+.*?\s+PAGE\s+(\d+)\s+of\s+(\d+)\s+.*?=====$")
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            match = banner.match(line)
            if match:
                current_page = int(match.group(1))
                continue
            if current_page is not None and not line.startswith("===="):
                page_text[current_page].append(line)
    return {
        page: normalize_key_text(" ".join(lines)) for page, lines in page_text.items()
    }


def actual_page_metadata(records: Sequence[Mapping[str, str]]) -> dict[int, dict[str, object]]:
    family_field = matrices.resolve(COVERAGE_METADATA, "family_field")
    structure_fields = matrices.resolve(COVERAGE_METADATA, "structure_field_order").split("|")
    if matrices.resolve(COVERAGE_METADATA, "collection_rule") != "sorted_unique_nonblank":
        raise ContractFailure("coverage-metadata-policy.csv names an unknown collection rule")
    result: dict[int, dict[str, object]] = defaultdict(
        lambda: {"count": 0, "families": set(), "structures": set()}
    )
    for row in records:
        try:
            page = int(row["source_page"])
        except (KeyError, ValueError):
            continue
        item = result[page]
        item["count"] = int(item["count"]) + 1
        cast_families = item["families"]
        cast_structures = item["structures"]
        assert isinstance(cast_families, set)
        assert isinstance(cast_structures, set)
        cast_families.add(row.get(family_field, ""))
        structure = next((row.get(field, "") for field in structure_fields if row.get(field, "")), "")
        if structure:
            cast_structures.add(structure)
    return result


def row_location(path: Path, row: Mapping[str, str]) -> str:
    return f"{path}:{row.get('__line_number', '?')}"


# A unit the page prints attached to the number. A currency symbol is not here:
# it is checked separately, because `currency_scale` legitimately carries it.
ATTACHED_UNIT_SYMBOLS: Final = ("%", "x")


def dropped_unit_symbol(row: Mapping[str, str]) -> str:
    """The symbol this row's own quote prints on the value but the value lacks.

    The convention is that `metric_value_raw` keeps the printed form. Stated in
    prose it held on two documents of one round and not on the third, where 61
    of 73 rows dropped a printed `%` that their own cited line still shows. The
    result is one metric in two formats, which every consumer downstream has to
    special-case.

    Only the row's own quote is consulted, and only where the symbol sits
    immediately after this value. Searching the whole page instead makes
    the digits of one cell match a percentage printed somewhere else: that
    reading flagged 155 correct rows on a document where the real count is 0.
    """
    value = row.get("metric_value_raw", "").strip()
    quote = row.get("evidence_quote", "")
    if not value or not quote:
        return ""
    for symbol in ATTACHED_UNIT_SYMBOLS:
        if symbol in value:
            continue
        # The lookbehind stops `4` matching the tail of a printed `34%`, and
        # excludes the comparison and approximation prefixes: in
        # `Risk Rating D <1% 1` the `1%` inside the threshold `<1%` is not this
        # cell, and reading it as one rewrote a borrower count of 1 into `1%`.
        attached = re.search(
            rf"(?<![\d.<>=~≤≥]){re.escape(value)}{re.escape(symbol)}(?![\w.])", quote)
        if not attached:
            continue
        # The same quote often prints the value twice, once inside a threshold
        # and once as the cell itself. A standalone bare occurrence means the
        # page does print this value without the symbol, so it is not dropped.
        bare = re.search(
            rf"(?<![\d.<>=~≤≥]){re.escape(value)}(?![\w.]|{re.escape(symbol)})", quote)
        if bare:
            continue
        return symbol
    return ""


GROUPING_MAP = "context-grouping-map"
# Which context of the grouping matrix each printed grouping column is read
# under. `asset_class` also accepts nothing else: an industry has its own
# column and a strategy has its own, and the whole point of the matrix is that
# the three are different dimensions.
GROUPING_COLUMNS: Final = {
    "asset_class": ("asset_class",),
    "strategy": ("strategy", "classifier_output"),
    "sector": ("sector",),
}


def grouping_values(context: str) -> frozenset[str]:
    return frozenset(row["input_value"] for row in matrices.rows_in(GROUPING_MAP, context))


def grouping_errors(row: Mapping[str, str], location: str) -> list[str]:
    """Refuse a printed grouping the taxonomy matrix cannot read.

    Every stage after extraction reads `asset_class`, `strategy`, and `sector`
    through context-grouping-map.csv. A value with no row there reaches the
    fund tables as a grouping nothing can canonicalise, and an industry or a
    benchmark name filed under `asset_class` reaches them as an asset class.
    Both were corrected by hand once; this is the check that stops the next
    one.
    """

    problems: list[str] = []
    for column, contexts in GROUPING_COLUMNS.items():
        value = row.get(column, "").strip()
        if not value:
            continue
        if any(value in grouping_values(context) for context in contexts):
            continue
        if column == "asset_class" and value in grouping_values("sector"):
            problems.append(
                f"{location}: asset_class {value!r} is an industry, not an asset "
                "class; move it to the `sector` column"
            )
            continue
        wrong_column = next(
            (
                other
                for other, other_contexts in GROUPING_COLUMNS.items()
                if other != column
                and any(value in grouping_values(context) for context in other_contexts)
            ),
            "",
        )
        if wrong_column:
            problems.append(
                f"{location}: {column} {value!r} is a {wrong_column} value in "
                f"context-grouping-map.csv; move it to the `{wrong_column}` column"
            )
            continue
        problems.append(
            f"{location}: {column} {value!r} has no row in "
            f"context-grouping-map.csv under context {contexts[0]!r}. Add the "
            "row naming its canonical class, or move the value to the column "
            "whose heading it names."
        )
    return problems


def qualifier_backlog_policy() -> str:
    """What publication does with a blank dimension the row's contract predates."""

    policy = matrices.resolve(RECORD_STATUS_POLICY, "qualifier_backlog")
    if policy != "refused_until_reviewed":
        raise ContractFailure(
            f"{RECORD_STATUS_POLICY}.csv names an unsupported qualifier_backlog "
            f"{policy!r}"
        )
    return policy


def blank_qualified_dimensions(
    row: Mapping[str, str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The qualified dimensions this row leaves blank: backlog first, errors second.

    A qualified category states its dimensions whenever the file has the columns
    to state them in. Which of the two a blank is depends on the row's own
    contract stamp. A blank in a column that stamp predates is backlog: the
    reader was never asked for the dimension, so the cell says nobody read it,
    and only a page reading turns that into a printed value or into `unstated`.
    A blank on a row stamped at or after the version that introduced the column
    is an error, because that reader was asked and answered nothing.

    One rule, two readers: the validator routes the two lists apart, and the
    ledger the publisher writes counts the first.
    """

    contract = FAMILY_CONTRACTS.get(row.get("record_family", ""))
    if contract is None or not contract.metric_categories:
        return (), ()
    qualifier = METRIC_QUALIFIERS.get(row.get("metric_category", ""))
    if not (qualifier and qualifier["qualified"]):
        return (), ()
    carried = columns_carried(row)
    version = row.get("contract_version", "")
    backlog: list[str] = []
    unanswered: list[str] = []
    for dimension in qualifier["required_dimensions"]:
        if dimension not in carried or row.get(dimension, "").strip():
            continue
        if version in KNOWN_CONTRACT_VERSIONS and predates_column(version, dimension):
            backlog.append(dimension)
        else:
            unanswered.append(dimension)
    return tuple(backlog), tuple(unanswered)


def validate_record_rows(
    path: Path,
    records: list[dict[str, str]],
    routing: Mapping[str, str],
    agent_role: str,
    *,
    final: bool,
    enforce_file_invariants: bool = True,
    warnings: list[str] | None = None,
    backlog: list[dict[str, str]] | None = None,
    strict_semantics: bool = True,
) -> list[str]:
    errors: list[str] = []
    # A grouping the matrix does not carry is a refusal on a final and a
    # warning on a candidate: a lane reads the whole document before an
    # adjudicator settles a new heading, and stopping the lane mid-read to
    # argue about a vocabulary row costs the reading.
    if warnings is None:
        warnings = []
    page_limit = int(routing["page_count"])
    allowed_families = set(DOC_TYPE_FAMILIES[routing["canonical_doc_type"]])
    page_text = source_page_texts(routing)
    seen_keys: dict[tuple[str, ...], str] = {}
    context_rows = 0

    definition_keys_by_page: dict[str, set[str]] = defaultdict(set)
    definition_pages_by_key: dict[str, set[str]] = defaultdict(set)
    for row in records:
        if row.get("record_family") == "definition_context":
            for key in split_pipe(row.get("definition_keys", "")):
                page = row.get("source_page", "")
                definition_keys_by_page[page].add(key)
                definition_pages_by_key[key].add(page)

    for row in records:
        location = row_location(path, row)
        # A row keeps the version stamp of the contract it was extracted
        # under; the stamp must be a known version, and the columns that
        # version predates loaded as blank.
        row_version = row.get("contract_version", "")
        if row_version not in KNOWN_CONTRACT_VERSIONS:
            errors.append(
                f"{location}: contract_version must be one of "
                f"{KNOWN_CONTRACT_VERSIONS}, found {row_version!r}"
            )
        for column, expected in (
            ("file_id", routing["file_id"]),
            ("source_sha256", routing["source_sha256"]),
            ("canonical_doc_type", routing["canonical_doc_type"]),
            ("route", routing["route"]),
            ("product_tier", routing["product_tier"]),
            ("agent_role", agent_role),
        ):
            if row.get(column, "") != expected:
                errors.append(
                    f"{location}: {column} must be {expected!r}, found {row.get(column, '')!r}"
                )
        for column in RECORD_COLUMNS:
            value = row.get(column, "")
            if "\n" in value or "\r" in value:
                errors.append(f"{location}: {column} contains a line break")
            if final and "\ufffd" in value:
                errors.append(
                    f"{location}: {column} contains an unreadable character (U+FFFD); "
                    "the adjudicator must verify the page image before publication"
                )
        family = row.get("record_family", "")
        if family not in allowed_families:
            errors.append(
                f"{location}: record_family {family!r} is not allowed for {routing['canonical_doc_type']}"
            )
            continue
        contract = FAMILY_CONTRACTS[family]
        page = positive_integer(row.get("source_page", ""), "source_page", errors, location)
        if page is not None and page > page_limit:
            errors.append(f"{location}: source_page {page} exceeds physical page count {page_limit}")
        if row.get("source_structure_type", "") not in SOURCE_STRUCTURE_TYPES:
            errors.append(
                f"{location}: source_structure_type must be one of {SOURCE_STRUCTURE_TYPES}, found {row.get('source_structure_type', '')!r}"
            )
        if not row.get("source_row_label", "").strip():
            errors.append(f"{location}: source_row_label is required")
        if (row.get("source_structure_type") == "TABLE"
                and not row.get("source_column_label", "").strip()):
            errors.append(
                f"{location}: a TABLE row requires source_column_label; use "
                "UNLABELED_COLUMN_<n> when the column prints no header")
        unit_value = row.get("unit", "").strip()
        if unit_value and normalize_key_text(unit_value) in CURRENCY_NOT_UNIT:
            errors.append(
                f"{location}: {unit_value!r} is a currency, not a unit of measure; "
                "it belongs in currency_scale")
        positive_integer(
            row.get("source_occurrence", ""), "source_occurrence", errors, location
        )
        if contract.tabular and not row.get("source_table", "").strip():
            errors.append(f"{location}: {family} requires source_table")
        if not row.get("source_table", "").strip() and not row.get("source_section", "").strip():
            errors.append(f"{location}: source_table or source_section is required")
        for required in contract.required_fields:
            if not row.get(required, "").strip():
                errors.append(f"{location}: {family} requires {required}")
        for business_column in BUSINESS_COLUMNS - contract.allowed_fields:
            if row.get(business_column, "").strip():
                errors.append(
                    f"{location}: {family} leaves unrelated field {business_column} blank"
                )
        subject_type = row.get("subject_type", "")
        if subject_type and subject_type not in SUBJECT_TYPES:
            errors.append(
                f"{location}: subject_type must be one of {SUBJECT_TYPES}, found {subject_type!r}"
            )
        metric_category = row.get("metric_category", "")
        term_category = row.get("term_category", "")
        allowed_metrics = set(allowed_metric_categories(family))
        allowed_terms = set(allowed_term_categories(family, routing["canonical_doc_type"]))
        if allowed_metrics:
            if metric_category not in allowed_metrics:
                errors.append(
                    f"{location}: metric_category {metric_category!r} is not in the metric vocabulary"
                )
            if term_category:
                errors.append(f"{location}: metric family leaves term_category blank")
            value = row.get("metric_value_raw", "")
            if is_null_like(value):
                errors.append(f"{location}: null-like metric value {value!r} must not be extracted")
            elif (value.strip() and not any(c.isdigit() for c in value)
                  and metric_category not in QUALITATIVE_METRICS):
                # A measured value carries digits. Without this, a lost number
                # leaves a bare unit behind ('%'), and prose lands in the value
                # column, both of which validate clean and read as real data.
                if (normalize_key_text(value) not in PRINTED_NOT_MEANINGFUL
                        and normalize_key_text(value) not in matrices.mapping("printed-number-words")):
                    errors.append(
                        f"{location}: metric_value_raw {value[:40]!r} contains no digit. "
                        "A measured value is a number as printed; a unit belongs in "
                        "`unit`, and wording belongs in `text_raw` on a term row."
                    )
        elif allowed_terms:
            if term_category not in allowed_terms:
                errors.append(
                    f"{location}: term_category {term_category!r} is not in the term vocabulary"
                )
            if metric_category:
                errors.append(f"{location}: term family leaves metric_category blank")
        elif metric_category or term_category:
            errors.append(f"{location}: {family} leaves metric_category and term_category blank")
        for dimension in ("method", "fee_basis", "value_scope"):
            stated = row.get(dimension, "").strip()
            if not stated:
                continue
            allowed_values = QUALIFIER_DIMENSIONS.get(dimension, ())
            if stated not in allowed_values:
                errors.append(
                    f"{location}: {dimension} must be one of {allowed_values}, found {stated!r}"
                )
            elif stated != "unstated" and not (
                row.get("definition_keys", "").strip() or row.get("basis_raw", "").strip()
            ):
                errors.append(
                    f"{location}: {dimension} {stated!r} needs backing: cite the "
                    "footnote key in definition_keys or copy the printed phrase "
                    "into basis_raw; a value the page does not state is `unstated`"
                )
        # A qualified category states its dimensions whenever the file has the
        # columns to state them in. The gate used to key on the row's own
        # contract_version, which meant a file written under today's header
        # skipped the check on every row stamped with an older contract, and
        # every published row carried the older stamp. The file's shape is the
        # honest gate: a header with `method` is a file that can answer for it.
        # A caller that collects a backlog takes the blanks the row's contract
        # predates as a table row instead of an error; a caller that collects
        # none is refusing the file, and every blank is an error.
        carried_backlog, unanswered = blank_qualified_dimensions(row)
        if backlog is None:
            unanswered = (*carried_backlog, *unanswered)
        else:
            backlog.extend(
                {
                    "route": row.get("route", ""),
                    "file_id": row.get("file_id", ""),
                    "metric_category": metric_category,
                    "blank_dimension": dimension,
                }
                for dimension in carried_backlog
            )
        for dimension in unanswered:
            errors.append(
                f"{location}: qualified category {metric_category!r} requires "
                f"{dimension} (write `unstated` when the page states none)"
            )
        grouping_problems = grouping_errors(row, location)
        (errors if final else warnings).extend(grouping_problems)
        # Only a whole document can answer whether a key resolves. A resolution
        # file carries the reviewed pairs alone, so its definition rows sit in
        # the candidates it was built from, not in it.
        if enforce_file_invariants and family != "definition_context":
            for key in split_pipe(row.get("definition_keys", "")):
                page_keys = definition_keys_by_page.get(row.get("source_page", ""), set())
                if key in page_keys:
                    continue
                definition_pages = definition_pages_by_key.get(key, set())
                if not definition_pages:
                    errors.append(
                        f"{location}: definition_keys names {key!r} with no "
                        "definition_context row in this document"
                    )
                elif len(definition_pages) > 1:
                    errors.append(
                        f"{location}: definition_keys names {key!r} away from its "
                        "source page, but that key has definitions on multiple pages; "
                        "cite a key defined on the same page"
                    )
        if family == "document_context":
            context_rows += 1
            if row.get("source_row_label") != "DOCUMENT":
                errors.append(f"{location}: document_context source_row_label must be DOCUMENT")
            if row.get("source_occurrence") != "1":
                errors.append(f"{location}: document_context source_occurrence must be 1")
            if row.get("source_structure_type") != "DOCUMENT":
                errors.append(f"{location}: document_context source_structure_type must be DOCUMENT")
        if family == "performance_observation" and not any(
            row.get(field, "").strip() for field in ("horizon", "as_of_date", "period_end")
        ):
            errors.append(
                f"{location}: {family} requires horizon, as_of_date, or period_end"
            )
        evidence_class = row.get("evidence_class", "")
        if evidence_class not in EVIDENCE_CLASSES:
            errors.append(
                f"{location}: evidence_class must be one of {EVIDENCE_CLASSES}, found {evidence_class!r}"
            )
        tier = routing["product_tier"]
        if tier == "CORE" and evidence_class not in CORE_EVIDENCE_CLASSES:
            errors.append(
                f"{location}: CORE records allow evidence_class actual or redacted only"
            )
        if tier == "SECONDARY" and evidence_class not in (*CORE_EVIDENCE_CLASSES, "definition"):
            errors.append(
                f"{location}: SECONDARY records allow actual, redacted, or definition evidence"
            )
        if tier != "REFERENCE":
            for field in ("metric_value_raw", "text_raw", "basis_raw", "condition_raw"):
                if row.get(field, "") and is_template_placeholder(row[field]):
                    errors.append(
                        f"{location}: template placeholder in {field} belongs to the REFERENCE product"
                    )
        if "SCHEMA_GAP:" in row.get("notes", ""):
            errors.append(f"{location}: SCHEMA_GAP rows are not part of the closed contract")
        quote = row.get("evidence_quote", "").strip()
        if not quote:
            errors.append(f"{location}: evidence_quote is required")
        elif len(quote) > 500:
            errors.append(f"{location}: evidence_quote exceeds 500 characters")
        elif page is not None:
            value = row.get("metric_value_raw", "").strip()
            image_only = row.get("notes", "").startswith("IMAGE_ONLY:")
            if value and not image_only:
                digits = value.lstrip("$(").rstrip(")%").strip()
                contains = (semantic_checks.complete_value_in_quote(value, quote) if strict_semantics
                            else normalize_key_text(digits) in normalize_key_text(quote))
                if digits and (any(c.isdigit() for c in digits)
                               or normalize_key_text(digits) in matrices.mapping("printed-number-words")) and not contains:
                    errors.append(
                        f"{location}: evidence_quote does not contain "
                        f"{value!r}. The quote must be the printed line the value "
                        "sits on, so it proves that value and not merely that the "
                        "page exists."
                    )
            normalized_page = page_text.get(page, "")
            normalized_quote = normalize_key_text(quote)
            if image_only and strict_semantics:
                image = PROJECT_ROOT / routing.get("image_dir", "") / f"page-{page:03d}.png"
                explanation = row.get("notes", "").removeprefix("IMAGE_ONLY:").strip()
                if not image.is_file() or not explanation:
                    errors.append(f"{location}: IMAGE_ONLY requires the cited page image and an explanation of the TXT defect")
            if normalized_page and normalized_quote not in normalized_page and not (image_only and strict_semantics):
                errors.append(
                    f"{location}: evidence_quote is absent from TXT page {page}"
                )
            elif not normalized_page and not row.get("notes", "").startswith("IMAGE_ONLY:"):
                errors.append(
                    f"{location}: page {page} has no TXT text; notes must start IMAGE_ONLY:"
                )
        # Checked on candidates as well as finals: caught at extraction this is
        # one row to retype, caught at adjudication it is a conflict on every
        # affected cell, and 549 of one document's 551 value conflicts were
        # this case.
        dropped = dropped_unit_symbol(row)
        if dropped:
            errors.append(
                f"{location}: value {row.get('metric_value_raw', '')!r} drops the "
                f"{dropped!r} that its own evidence_quote prints attached to it. Copy "
                "the printed form, symbol included, and record the symbol in `unit` too. "
                "Stripping it is a normalisation: it makes the same metric read two ways "
                "across a document."
            )
        if final:
            if row.get("source_agents", "") not in FINAL_SOURCE_AGENTS:
                errors.append(
                    f"{location}: final source_agents must be one of {FINAL_SOURCE_AGENTS}"
                )
            if row.get("adjudication_status", "") not in FINAL_STATUSES:
                errors.append(
                    f"{location}: final adjudication_status must be one of {FINAL_STATUSES}"
                )
        else:
            if row.get("source_agents", ""):
                errors.append(f"{location}: blind candidate leaves source_agents blank")
            if row.get("adjudication_status", ""):
                errors.append(f"{location}: blind candidate leaves adjudication_status blank")
        key = record_key(row)
        if key in seen_keys:
            errors.append(
                f"{location}: another row already claims page "
                f"{row.get('source_page','')}, row {row.get('source_row_label','')!r}, "
                f"column {row.get('source_column_label','')!r}, occurrence "
                f"{row.get('source_occurrence','')} (first seen at {seen_keys[key]}). "
                "Two rows at one printed cell are the same observation. If the page "
                "prints that row and column twice, in two tables or two blocks, give "
                "the second one the next source_occurrence."
            )
        else:
            seen_keys[key] = location

    if enforce_file_invariants:
        if records:
            if context_rows != 1:
                errors.append(f"{path}: expected one document_context row, found {context_rows}")
            expected_order = sorted(records, key=record_sort_key)
            if [record_key(row) for row in records] != [record_key(row) for row in expected_order]:
                errors.append(f"{path}: rows are not in the required deterministic sort order")
    if strict_semantics:
        errors.extend(f"{row_location(path, row)}: {code}: {detail}"
                      for row, code, detail in semantic_checks.record_errors(
                          records, page_text, whole_document=enforce_file_invariants))
    return errors


# Printed shorthand a performance table uses where a number cannot be computed.
# These are the page's own words for the cell, not a missing value.
PRINTED_NOT_MEANINGFUL: Final = frozenset(
    row["input_value"] for row in matrices.rows_in(TOKEN_RULES, "not_meaningful")
)

# Categories whose printed value is a word, not a number: a valuation method is
# "Discounted Cash Flow", a valuer is "External Appraiser". Requiring a digit
# here made whole families unextractable.
# A currency names the money, not what is measured. The prompts say so; this
# makes the validator say so too.

CURRENCY_NOT_UNIT: Final = frozenset(
    row["input_value"] for row in matrices.rows_in(TOKEN_RULES, "currency")
)

QUALITATIVE_METRICS: Final = frozenset(
    row["input_value"] for row in matrices.rows_in(TOKEN_RULES, "qualitative")
)


def difficulty_excuse(note: str) -> str | None:
    """The phrase making this a readability complaint, if it is one.

    ``NO_ELIGIBLE_DATA`` means the page prints nothing in an allowed category.
    It does not mean the page was hard to read. Left unchecked the two collapse,
    and an extractor drops a dense fund-by-fund schedule, the most valuable
    table in the corpus, while the file still validates clean.
    """
    lowered = note.casefold()
    for phrase in DIFFICULTY_EXCUSES:
        if phrase in lowered:
            return phrase
    return None


def page_has_eligibility_signal(normalized_page_text: str) -> bool:
    return bool(NUMERIC_SIGNAL.search(normalized_page_text)) and any(
        keyword in normalized_page_text for keyword in ELIGIBILITY_KEYWORDS
    )


def completeness_errors(routing: Mapping[str, str], records: Sequence[Mapping[str, str]],
                        coverage: Sequence[Mapping[str, str]]) -> list[str]:
    """Check page accounting against grid counts; reviewers establish source meaning."""
    errors: list[str] = []
    file_id = routing["file_id"]
    if not grid_built(file_id):
        errors.append(f"{file_id}: no page grid; build the active source grids before completion")
    shapes = grid_page_shape(file_id)
    texts = source_page_texts(routing)
    counts = Counter(r["source_page"] for r in records if r.get("record_family") != "document_context")
    covered = {r["source_page"]: r for r in coverage}
    minimum = int(matrices.resolve(semantic_checks.POLICY, "reason_min_words", context="coverage"))
    blocked = matrices.mapping(semantic_checks.POLICY, "incomplete_status")
    for page in range(1, int(routing["page_count"]) + 1):
        row = covered.get(str(page))
        if row is None:
            errors.append(f"{file_id} page {page}: missing coverage row")
            continue
        cells, grid_rows = shapes.get(page, (0, 0))
        written = counts[str(page)]
        note = row.get("notes", "").strip()
        if row.get("page_status") in blocked and routing["product_tier"] == "CORE":
            errors.append(f"{file_id} page {page}: {row['page_status']} is not completed extraction; source review must settle eligibility")
        if not written and semantic_checks.matches("definition_signal", texts.get(page, "")):
            errors.append(f"{file_id} page {page}: DEFINITION_OMISSION: printed accounting, glossary or method definitions cannot be treated as zero-observation reference material")
        thin = cells >= GRID_TABLE_CELLS and 0 < written < cells * GRID_THIN_RATIO
        empty_signal = not written and ((cells >= GRID_TABLE_CELLS and grid_rows >= GRID_TABLE_ROWS)
                                       or page_has_eligibility_signal(texts.get(page, "")))
        if not thin and not empty_signal:
            continue
        prefix = PARTIAL_REASON if thin else "NO_ELIGIBLE_REASON:"
        description = "partly extracted with no reason" if thin else "zero observations despite source signals"
        if not note.startswith(prefix) or len(note.removeprefix(prefix).split()) < minimum:
            errors.append(f"{file_id} page {page}: {description}; {written} records against {cells} grid cells; notes must start {prefix} and name excluded rows or columns and their category test")
        excuse = difficulty_excuse(note)
        if excuse:
            errors.append(f"{file_id} page {page}: {excuse!r} describes how hard the page is to read, not category eligibility")
        if row.get("layout_checked") != "YES":
            errors.append(f"{file_id} page {page}: source signals require layout_checked=YES even when no observations are extracted")
    return errors


def validate_coverage_rows(
    path: Path,
    coverage: list[dict[str, str]],
    records: list[dict[str, str]],
    routing: Mapping[str, str],
    agent_role: str,
    through_page: int | None = None,
) -> list[str]:
    errors: list[str] = []
    page_limit = int(routing["page_count"])
    metadata = actual_page_metadata(records)
    page_text = source_page_texts(routing)
    grid_shape = grid_page_shape(routing["file_id"])
    seen_pages: set[int] = set()
    last_page = 0
    for row in coverage:
        location = row_location(path, row)
        if row.get("contract_version", "") not in KNOWN_CONTRACT_VERSIONS:
            errors.append(
                f"{location}: contract_version must be one of "
                f"{KNOWN_CONTRACT_VERSIONS}, found {row.get('contract_version', '')!r}"
            )
        for column, expected in (
            ("file_id", routing["file_id"]),
            ("source_sha256", routing["source_sha256"]),
            ("canonical_doc_type", routing["canonical_doc_type"]),
            ("route", routing["route"]),
            ("product_tier", routing["product_tier"]),
            ("agent_role", agent_role),
        ):
            if row.get(column, "") != expected:
                errors.append(
                    f"{location}: {column} must be {expected!r}, found {row.get(column, '')!r}"
                )
        page = positive_integer(row.get("source_page", ""), "source_page", errors, location)
        if page is None:
            continue
        if page > page_limit:
            errors.append(f"{location}: source_page {page} exceeds page count {page_limit}")
        if through_page is not None and page > through_page:
            errors.append(
                f"{location}: page {page} is beyond --through-page {through_page}")
        if page in seen_pages:
            errors.append(f"{location}: source_page {page} appears more than once")
        seen_pages.add(page)
        if page <= last_page:
            errors.append(f"{location}: coverage rows must be sorted by source_page")
        last_page = page
        status = row.get("page_status", "")
        if status not in PAGE_STATUSES:
            errors.append(
                f"{location}: page_status must be one of {PAGE_STATUSES}, found {status!r}"
            )
        if row.get("layout_checked", "") not in {"YES", "NO"}:
            errors.append(f"{location}: layout_checked must be YES or NO")
        for list_field in ("source_structures", "relevant_record_families"):
            value = row.get(list_field, "")
            if value != joined_sorted(split_pipe(value)):
                errors.append(
                    f"{location}: {list_field} must be a sorted unique ` | ` list"
                )
        expected = nonnegative_integer(
            row.get("expected_observation_count", ""),
            "expected_observation_count",
            errors,
            location,
        )
        written = nonnegative_integer(
            row.get("records_written", ""), "records_written", errors, location
        )
        actual = int(metadata.get(page, {}).get("count", 0))
        if written is not None and written != actual:
            errors.append(
                f"{location}: records_written={written} but record CSV contains {actual} rows on page {page}"
            )
        if expected is not None and written is not None and expected != written:
            errors.append(
                f"{location}: expected_observation_count must equal records_written"
            )
        # The document-identity row is bookkeeping, so it does not make a page
        # populated. Counting it did: a cover page carrying only that row
        # failed both branches below, leaving it no valid status at all, and
        # ten of the twenty-nine published documents escaped by filing the row
        # on a later page, which is the one thing that row may not do.
        only_context = set(metadata.get(page, {}).get("families", ())) == {
            "document_context"
        }
        if actual > 0 and not only_context:
            if status != "ELIGIBLE_DATA_EXTRACTED":
                errors.append(
                    f"{location}: a populated page must use ELIGIBLE_DATA_EXTRACTED"
                )
            if row.get("layout_checked") != "YES":
                errors.append(f"{location}: populated page requires layout_checked=YES")
        elif status == "ELIGIBLE_DATA_EXTRACTED":
            if only_context:
                # Without this an agent can note the page's data in coverage,
                # extract none of it, and still validate clean.
                errors.append(
                    f"{location}: only the document_context row cites page {page}. "
                    "ELIGIBLE_DATA_EXTRACTED means observations were extracted: "
                    "extract the printed amounts this page's coverage note "
                    "describes, or give the page the status its printed content "
                    "deserves. The document_context row may stay on page 1 "
                    "under any status; it is not an observation."
                )
            else:
                errors.append(
                    f"{location}: ELIGIBLE_DATA_EXTRACTED requires at least one record"
                )
        if actual > 0:
            # These describe what the page carries, so they hold whatever the
            # status is, including a cover page carrying only the context row.
            actual_families = joined_sorted(metadata[page]["families"])
            actual_structures = joined_sorted(metadata[page]["structures"])
            if row.get("relevant_record_families", "") != actual_families:
                errors.append(
                    f"{location}: relevant_record_families must equal {actual_families!r}"
                )
            if row.get("source_structures", "") != actual_structures:
                errors.append(
                    f"{location}: source_structures must equal {actual_structures!r}"
                )
        if actual == 0 and status == "NO_ELIGIBLE_DATA":
            note = row.get("notes", "")
            cells, grid_rows = grid_shape.get(page, (0, 0))
            if (cells >= GRID_CERTAIN_CELLS and grid_rows >= GRID_TABLE_ROWS
                    and not note.startswith("NO_ELIGIBLE_REASON:")):
                errors.append(
                    f"{location}: the page grid resolved {cells} aligned value cells "
                    f"across {grid_rows} rows on page {page}. That is a printed table, "
                    "so the page is not empty. Extract it, reading the page image if "
                    "the TXT will not resolve the columns."
                )
            if page_has_eligibility_signal(page_text.get(page, "")):
                if not note.startswith("NO_ELIGIBLE_REASON:"):
                    errors.append(
                        f"{location}: page contains alternative-investment numeric signals; notes must start NO_ELIGIBLE_REASON:"
                    )
                else:
                    excuse = difficulty_excuse(note)
                    if excuse:
                        errors.append(
                            f"{location}: {excuse!r} describes how hard the page is to read, "
                            "which is not a reason a page holds no eligible data. "
                            "NO_ELIGIBLE_DATA means the page prints nothing in an allowed "
                            "category. If it prints a table the TXT leaves unresolved "
                            "or the grid, read it from the page image and extract it."
                        )
        if status in {"DEFERRED_BY_SCOPE", "REFERENCE_ONLY", "UNREADABLE"} and not row.get(
            "notes", ""
        ).strip():
            errors.append(f"{location}: {status} requires an explanatory note")
    # `through_page` supports validating a document in progress: everything
    # written so far is checked, without demanding pages not yet reached. The
    # prompt tells the extractor to validate after page 1, which was impossible
    # while this always required coverage for the whole document.
    last = page_limit if through_page is None else min(through_page, page_limit)
    expected_pages = set(range(1, last + 1))
    missing = sorted(expected_pages - seen_pages)
    extra = sorted(seen_pages - expected_pages)
    if missing:
        errors.append(f"{path}: missing coverage rows for pages {missing}")
    if extra:
        errors.append(f"{path}: extra coverage pages {extra}")
    return errors


REPAIR_NOTE: Final = "REPAIRED_SHIFT"
# Fields whose agreement decides where the dropped cell was. The quote and
# notes are excluded because the two lanes legitimately quote different spans
# of the same line, and a row that agreed with the reference on nothing but its
# own free text would prove nothing about its shape.
DIFFICULTY_EXCUSES: Final = tuple(
    row["input_value"] for row in matrices.rows_in(ELIGIBILITY, "excuse")
)

REPAIR_IGNORED: Final = frozenset(
    row["input_value"] for row in matrices.rows_in(REPAIR_RULES, "ignored")
)


def repair_shifted_rows(
    short: Sequence[str], reference: Mapping[tuple, Mapping[str, str]]
) -> tuple[dict[str, str] | None, str]:
    """Put the one missing cell back where it belongs, or refuse.

    A row one cell short has lost a column somewhere, and everything after the
    gap has slid one field left. Tried standalone, the repair is ambiguous: a
    shifted row has several insertion points that all pass validation. Scored
    against the other lane's row for the same printed cell it is not: the
    insertion that makes the two rows agree on the most fields is the real one,
    and on 49 of 49 shifted rows it was unique and was always the same column.
    The value placed back is still this lane's own reading, so agreement with
    the reference afterwards is two-source confirmation, not an echo.

    Returns (repaired_row, "") or (None, reason). Refuses when no reference row
    exists for the cell, or when the best-scoring insertions disagree on any
    field that matters, because a guess here writes a wrong value into a row
    that will then look validated.
    """
    width = len(RECORD_COLUMNS)
    candidates = []
    for position in range(width):
        cells = list(short[:position]) + [""] + list(short[position:])
        row = dict(zip(RECORD_COLUMNS, cells, strict=True))
        ref = reference.get(record_key(row))
        if ref is None:
            continue
        score = sum(
            1 for column in RECORD_COLUMNS
            if column not in REPAIR_IGNORED
            and normalize_key_text(row[column]) == normalize_key_text(ref.get(column, ""))
        )
        candidates.append((score, position, row))
    if not candidates:
        return None, "no reference row for any reading of this cell"
    best = max(score for score, _, _ in candidates)
    top = [(position, row) for score, position, row in candidates if score == best]
    for column in RECORD_COLUMNS:
        if column in REPAIR_IGNORED:
            continue
        if len({normalize_key_text(row[column]) for _, row in top}) > 1:
            return None, (f"{len(top)} insertion points tie and disagree on "
                          f"{column}; cannot tell which cell was dropped")
    position, row = top[0]
    dropped = RECORD_COLUMNS[position]
    note = f"{REPAIR_NOTE}: restored blank {dropped} using the other lane as reference"
    row["notes"] = f"{note}; {row['notes']}" if row["notes"].strip() else note
    return row, ""


def repair_shifted_command(route: str, file_id: str, agent: str) -> None:
    """Repair a candidate's one-cell-short rows against the other lane.

    Rows that cannot be repaired unambiguously move to `malformed-<agent>.csv`
    in the same folder, so the candidate validates and pairs on everything
    else, and the adjudicator reads the quarantined cells from the page.
    Rows of any other wrong width are quarantined without an attempt.
    """
    if agent not in CANDIDATE_AGENTS:
        raise ContractFailure(
            f"repair-shifted pairs one candidate against the other; agent must be "
            f"one of {', '.join(CANDIDATE_AGENTS)}, found {agent!r}")
    other = next(a for a in CANDIDATE_AGENTS if a != agent)
    record_path, _ = candidate_paths(route, file_id, agent)
    other_path, _ = candidate_paths(route, file_id, other)
    reference = {record_key(row): row for row in read_strict_csv(other_path, RECORD_COLUMNS)}

    with record_path.open(encoding="utf-8-sig", newline="") as handle:
        raw = list(csv.reader(handle))
    if not raw or raw[0] != list(RECORD_COLUMNS):
        raise ContractFailure(f"{record_path}: header mismatch; repair only fixes row width")
    width = len(RECORD_COLUMNS)
    kept: list[dict[str, str]] = []
    quarantined: list[dict[str, str]] = []
    repaired = 0
    for line_number, cells in enumerate(raw[1:], 2):
        if len(cells) == width:
            kept.append(dict(zip(RECORD_COLUMNS, cells, strict=True)))
            continue
        reason = f"{len(cells)} cells, expected {width}"
        if len(cells) == width - 1:
            row, refusal = repair_shifted_rows(cells, reference)
            if row is not None:
                kept.append(row)
                repaired += 1
                continue
            reason = f"one cell short; {refusal}"
        padded = list(cells[:width]) + [""] * max(0, width - len(cells))
        bad = dict(zip(RECORD_COLUMNS, padded, strict=True))
        bad["notes"] = f"QUARANTINED line {line_number}: {reason}"
        quarantined.append(bad)

    if not repaired and not quarantined:
        print(f"PASS: {route}/{file_id} Extractor {agent}: no shifted rows, nothing changed")
        return
    write_csv(record_path, RECORD_COLUMNS, kept)
    quarantine_path = record_path.with_name(f"malformed-{agent.lower()}.csv")
    if quarantined:
        write_csv(quarantine_path, RECORD_COLUMNS, quarantined)
    elif quarantine_path.exists():
        quarantine_path.unlink()
    print(f"PASS: {route}/{file_id} Extractor {agent}: repaired {repaired} shifted "
          f"rows against Extractor {other}; quarantined {len(quarantined)}"
          + (f" to {quarantine_path.name}" if quarantined else "")
          + f"; {len(kept)} rows kept")


VALUE_FORMAT_NOTE: Final = "REPAIRED_VALUE_FORMAT"


def repair_value_format_command(route: str, file_id: str, agent: str) -> None:
    """Restore a printed `%` or `x` the row's own quote proves it dropped.

    `compare` and `build-final` both refuse to run on a candidate that fails
    validation, so a stripped symbol does not merely blemish a row: it
    deadlocks the file before any pair-index exists, and the adjudicator never
    reaches the merge where the prompt says to fix it. On one round this was
    both lanes of one document and 513 rows of another.

    The repair is deterministic and touches no digits. The symbol comes from
    the row's own `evidence_quote`, and the result is asserted equal to the
    value plus that symbol before it is written, so nothing is inferred. Rows
    the matcher does not fire on are left as they are.
    """
    if agent not in EXTRACTOR_AGENTS:
        raise ContractFailure(
            f"agent must be one of {', '.join(EXTRACTOR_AGENTS)}, found {agent!r}")
    record_path, _ = candidate_paths(route, file_id, agent)
    rows = read_strict_csv(record_path, RECORD_COLUMNS)
    repaired = 0
    unit_blank = 0
    for row in rows:
        symbol = dropped_unit_symbol(row)
        if not symbol:
            continue
        value = row["metric_value_raw"].strip()
        printed = f"{value}{symbol}"
        if printed not in row["evidence_quote"]:
            continue
        row["metric_value_raw"] = printed
        note = f"{VALUE_FORMAT_NOTE}: restored the printed {symbol!r} its evidence_quote shows"
        row["notes"] = f"{note}; {row['notes']}" if row["notes"].strip() else note
        repaired += 1
        if not row["unit"].strip():
            unit_blank += 1
    if not repaired:
        print(f"PASS: {route}/{file_id} Extractor {agent}: no stripped symbols, nothing changed")
        return
    write_csv(record_path, RECORD_COLUMNS, [{c: r.get(c, "") for c in RECORD_COLUMNS} for r in rows])
    print(f"PASS: {route}/{file_id} Extractor {agent}: restored the printed symbol on "
          f"{repaired} rows; {len(rows)} rows kept")
    if unit_blank:
        print(f"  {unit_blank} of them leave `unit` blank. A printed % or x is a printed "
              "unit, so set it in the merged record when the row is adjudicated.")


def validate_candidate_data(
    route: str, file_id: str, agent: str, through_page: int | None = None,
    warnings: list[str] | None = None,
    *, allow_legacy_qualifiers: bool = False,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    if agent not in EXTRACTOR_AGENTS:
        raise ContractFailure(
            f"agent must be one of {', '.join(EXTRACTOR_AGENTS)}, found {agent!r}")
    routing = routing_for(route, file_id)
    record_path, coverage_path = candidate_paths(route, file_id, agent)
    records = read_strict_csv(record_path, RECORD_COLUMNS)
    coverage = read_strict_csv(coverage_path, COVERAGE_COLUMNS)
    errors = validate_record_rows(
        record_path, records, routing, agent, final=False, warnings=warnings,
        backlog=[] if allow_legacy_qualifiers else None,
        strict_semantics=not allow_legacy_qualifiers,
    )
    if not allow_legacy_qualifiers:
        with record_path.open(encoding="utf-8-sig", newline="") as handle:
            if next(csv.reader(handle), []) != list(RECORD_COLUMNS):
                errors.append(f"{record_path}: current extraction requires the issued {len(RECORD_COLUMNS)}-column header; historical headers are read only during final reconstruction")
    errors.extend(
        validate_coverage_rows(coverage_path, coverage, records, routing, agent,
                               through_page=through_page)
    )
    # Attribution is cheapest to demand here, on the first page, before a whole
    # document is written by a model nothing will be able to name afterwards.
    if records and not claimed_model(route, agent):
        errors.append(
            f"{record_path}: this run has not declared its model. Run once, "
            "then continue:\n    python instructions/01-pdf-extraction-csv/"
            f"workflow.py claim --route {route} --agent {agent} "
            '--model "<model name>"'
        )
    return records, coverage, errors


def validate_candidate_command(
    route: str, file_id: str, agent: str, through_page: int | None = None
) -> None:
    refuse_generator_scripts()
    warnings: list[str] = []
    _, _, errors = validate_candidate_data(
        route, file_id, agent, through_page, warnings
    )
    errors = page_image_errors(routing_for(route, file_id)) + errors
    if errors:
        raise ContractFailure("Candidate validation failed:\n- " + "\n- ".join(errors))
    for warning in warnings:
        print(f"WARN: {warning}")
    scope = "" if through_page is None else f" through page {through_page}"
    print(f"PASS: {route}/{file_id} Extractor {agent} candidate{scope}")


def audit_file_command(
    route: str, file_id: str, agent: str, quiet: bool = False,
    require_images: bool = True,
) -> None:
    """Check the candidate and its page accounting before handoff."""
    routing = routing_for(route, file_id)
    records, coverage, errors = validate_candidate_data(route, file_id, agent)
    if require_images:
        errors.extend(page_image_errors(routing))
    if errors:
        raise ContractFailure("Candidate validation failed before completeness audit:\n- " + "\n- ".join(errors))
    errors.extend(completeness_errors(routing, records, coverage))
    if errors:
        raise ContractFailure(f"Document audit failed for {route}/{file_id} Extractor {agent}:\n- "
                              + "\n- ".join(errors))
    if not quiet:
        print(f"PASS: {route}/{file_id} Extractor {agent} audit; every page accounted for")
        print()
        print(extraction_checklist(route))


def cited_line_key(row: Mapping[str, str]) -> tuple[str, str, str, str]:
    """Identify a printed cell by the line it sits on, not by counting.

    `source_occurrence` counts how many times a page has repeated a row label,
    so a lane that misses one row renumbers every later row beneath it and its
    cells pair against the wrong cells. One run mis-paired 72 cells this way,
    each read correctly by both lanes, and every one reached the adjudicator
    as a value conflict where both sides were right.

    The cited line does not drift: two lanes reading the same physical row quote
    the same printed text, whatever they numbered it.
    """
    fields = tuple(
        rank_row["output_value"]
        for rank_row in sorted(
            matrices.rows_in(REALIGNMENT, "cited_line_key"),
            key=lambda item: int(item["input_value"]),
        )
    )
    return (
        row.get(fields[0], ""),
        str(row.get(fields[1], "")),
        normalize_key_text(row.get(fields[2], "")),
        normalize_key_text(row.get(fields[3], "")),
    )


def realign_by_cited_line(
    a_map: dict[tuple, tuple[int, dict[str, str]]],
    b_map: dict[tuple, tuple[int, dict[str, str]]],
) -> int:
    """Re-key B's unmatched rows onto A's where both cite the same line.

    Only unambiguous matches move: one unmatched row on each side carrying that
    cited line. Anything else is left unpaired for the adjudicator to read,
    because a guess here silently invents agreement.
    """
    a_unmatched = [key for key in a_map if key not in b_map]
    b_unmatched = [key for key in b_map if key not in a_map]
    if not a_unmatched or not b_unmatched:
        return 0

    def index_by_line(keys, source):
        grouped = defaultdict(list)
        for key in keys:
            line = cited_line_key(source[key][1])
            if all(part for part in line[2:3]):
                grouped[line].append(key)
        return grouped

    a_lines = index_by_line(a_unmatched, a_map)
    b_lines = index_by_line(b_unmatched, b_map)
    moved = 0
    for line, b_keys in b_lines.items():
        a_keys = a_lines.get(line)
        if not a_keys or len(a_keys) != 1 or len(b_keys) != 1:
            continue
        target, source = a_keys[0], b_keys[0]
        if target in b_map:
            continue
        b_map[target] = b_map.pop(source)
        moved += 1
    return moved


def _bare_value(row: Mapping[str, str]) -> str:
    """A value with its symbols and spacing removed, for matching only."""
    bare = normalize_key_text(row.get("metric_value_raw", ""))
    for stripped_row in matrices.rows_in(REALIGNMENT, "bare_value"):
        symbol = " " if stripped_row["input_value"] == "<space>" else stripped_row["input_value"]
        bare = bare.replace(symbol, "")
    return bare


def realign_by_renamed_column(
    a_map: dict[tuple, tuple[int, dict[str, str]]],
    b_map: dict[tuple, tuple[int, dict[str, str]]],
) -> int:
    """Re-key B's unmatched rows onto A's where only the column's name differs.

    Two lanes reading one cell can name its column two ways: one copies the
    printed `Market Value ($)`, the other writes `Market Value`; one joins a
    stacked `Since Inception IRR`, the other abbreviates to `SI IRR`. The cell is
    the same, so the rows should meet as a pair and the header convention
    decides the name. Unpaired, they reach the adjudicator as 162 one-sided
    rows on one document, with the shared value invisible.

    A value match alone is not enough: adjacent period columns often repeat a
    value, and pairing A's `20 Year` to B's `25 Year` would hide a missed cell.
    So the match is taken only when neither lane uses the other's column label
    anywhere on that page. Two names that both exist on both sides are two real
    columns, and the coincidence is left for the adjudicator to see.
    """
    a_unmatched = [k for k in a_map if k not in b_map]
    b_unmatched = [k for k in b_map if k not in a_map]
    if not a_unmatched or not b_unmatched:
        return 0

    def labels_by_page(source):
        seen = defaultdict(set)
        for _, row in source.values():
            seen[str(row.get("source_page", ""))].add(
                normalize_key_text(row.get("source_column_label", "")))
        return seen

    a_labels, b_labels = labels_by_page(a_map), labels_by_page(b_map)

    def anchor(row):
        return (row.get("file_id", ""), str(row.get("source_page", "")),
                normalize_key_text(row.get("source_row_label", "")), _bare_value(row))

    a_by = defaultdict(list)
    for key in a_unmatched:
        a_by[anchor(a_map[key][1])].append(key)
    b_by = defaultdict(list)
    for key in b_unmatched:
        b_by[anchor(b_map[key][1])].append(key)

    moved = 0
    for anchor_key, b_keys in b_by.items():
        a_keys = a_by.get(anchor_key)
        if not a_keys or len(a_keys) != 1 or len(b_keys) != 1 or not anchor_key[3]:
            continue
        target, source = a_keys[0], b_keys[0]
        if target in b_map:
            continue
        page = anchor_key[1]
        a_col = normalize_key_text(a_map[target][1].get("source_column_label", ""))
        b_col = normalize_key_text(b_map[source][1].get("source_column_label", ""))
        if a_col != b_col and (a_col in b_labels[page] or b_col in a_labels[page]):
            continue
        b_map[target] = b_map.pop(source)
        moved += 1
    return moved


def pair_records(
    a_records: list[dict[str, str]], b_records: list[dict[str, str]]
) -> tuple[list[dict[str, str]], dict[str, tuple[dict[str, str] | None, dict[str, str] | None]]]:
    a_map = {record_key(row): (index, row) for index, row in enumerate(a_records, 1)}
    b_map = {record_key(row): (index, row) for index, row in enumerate(b_records, 1)}
    realign_by_cited_line(a_map, b_map)
    realign_by_renamed_column(a_map, b_map)
    pair_rows: list[dict[str, str]] = []
    pair_values: dict[str, tuple[dict[str, str] | None, dict[str, str] | None]] = {}
    exact_by_page: dict[str, list[dict[str, str]]] = defaultdict(list)
    for key in sorted(set(a_map) | set(b_map)):
        a_item = a_map.get(key)
        b_item = b_map.get(key)
        a_row = a_item[1] if a_item else None
        b_row = b_item[1] if b_item else None
        exemplar = a_row or b_row
        assert exemplar is not None
        pair_id = record_pair_id(exemplar)
        if a_row is not None and b_row is not None:
            if comparison_payload(a_row) == comparison_payload(b_row):
                status = "EXACT"
                differences: list[str] = []
            else:
                differences = [
                    column
                    for column in RECORD_COLUMNS
                    if column not in KEY_IGNORED_FIELDS
                    and normalize_key_text(a_row.get(column, ""))
                    != normalize_key_text(b_row.get(column, ""))
                ]
                status = conflict_kind(differences)
        elif a_row is not None:
            status, differences = "A_ONLY", []
        else:
            status, differences = "B_ONLY", []
        pair = {
            "pair_id": pair_id,
            "pair_status": status,
            # review-sampling.csv: every non-exact pair, plus the stable sample.
            "requires_review": "YES"
            if matrices.resolve(SAMPLING_RULES, "requires_review") == "non_exact_or_sample"
            and (status != "EXACT" or deterministic_sample(pair_id))
            else "NO",
            "source_page": exemplar.get("source_page", ""),
            "record_family": exemplar.get("record_family", ""),
            "source_table": exemplar.get("source_table", ""),
            "source_row_label": exemplar.get("source_row_label", ""),
            "source_column_label": exemplar.get("source_column_label", ""),
            "source_occurrence": exemplar.get("source_occurrence", ""),
            "metric_category": exemplar.get("metric_category", ""),
            "term_category": exemplar.get("term_category", ""),
            "a_row_number": str(a_item[0]) if a_item else "",
            "b_row_number": str(b_item[0]) if b_item else "",
            "difference_fields": "|".join(differences),
        }
        pair_rows.append(pair)
        pair_values[pair_id] = (a_row, b_row)
        if status == "EXACT":
            exact_by_page[pair["source_page"]].append(pair)
    for page_pairs in exact_by_page.values():
        if not any(pair["requires_review"] == "YES" for pair in page_pairs):
            page_pairs[0]["requires_review"] = "YES"
    return pair_rows, pair_values


def pair_coverage(
    a_coverage: list[dict[str, str]], b_coverage: list[dict[str, str]]
) -> list[dict[str, str]]:
    a_map = {row["source_page"]: row for row in a_coverage}
    b_map = {row["source_page"]: row for row in b_coverage}
    compared = (
        "page_status",
        "layout_checked",
        "expected_observation_count",
        "source_structures",
        "relevant_record_families",
    )
    output: list[dict[str, str]] = []
    pages = sorted(set(a_map) | set(b_map), key=int)
    file_id = (a_coverage or b_coverage)[0]["file_id"]
    first_page = pages[0] if pages else ""
    last_page = pages[-1] if pages else ""
    for page in pages:
        a = a_map.get(page, {})
        b = b_map.get(page, {})
        differences = [field for field in compared if a.get(field, "") != b.get(field, "")]
        if not differences:
            sampled = (
                page in {first_page, last_page}
                or deterministic_sample(
                    matrices.resolve(SAMPLING_RULES, "coverage_sample_id").format(
                        file_id=file_id, page=page
                    )
                )
            )
            if not sampled:
                continue
            differences = ["DETERMINISTIC_SAMPLE"]
        output.append(
            {
                "source_page": page,
                "a_page_status": a.get("page_status", ""),
                "b_page_status": b.get("page_status", ""),
                "a_layout_checked": a.get("layout_checked", ""),
                "b_layout_checked": b.get("layout_checked", ""),
                "a_expected_observation_count": a.get("expected_observation_count", ""),
                "b_expected_observation_count": b.get("expected_observation_count", ""),
                "a_source_structures": a.get("source_structures", ""),
                "b_source_structures": b.get("source_structures", ""),
                "a_relevant_record_families": a.get("relevant_record_families", ""),
                "b_relevant_record_families": b.get("relevant_record_families", ""),
                "difference_fields": "|".join(differences),
            }
        )
    return output


def compare_command(route: str, file_id: str) -> None:
    a_records, a_coverage, a_errors = validate_candidate_data(route, file_id, "A")
    b_records, b_coverage, b_errors = validate_candidate_data(route, file_id, "B")
    errors = [*a_errors, *b_errors]
    if errors:
        raise ContractFailure("Cannot compare invalid candidates:\n- " + "\n- ".join(errors))
    pairs, _ = pair_records(a_records, b_records)
    coverage_diff = pair_coverage(a_coverage, b_coverage)
    paths = pair_paths(route, file_id)
    write_csv(paths["pair"], PAIR_COLUMNS, pairs)
    write_csv(paths["coverage_diff"], COVERAGE_DIFF_COLUMNS, coverage_diff)
    write_header_if_missing(paths["resolution"], RESOLUTION_COLUMNS)
    write_header_if_missing(paths["coverage_resolution"], COVERAGE_RESOLUTION_COLUMNS)
    counts = Counter(row["pair_status"] for row in pairs)
    review_count = sum(row["requires_review"] == "YES" for row in pairs)
    print(
        f"PASS: paired {len(pairs)} records; EXACT={counts['EXACT']} "
        f"VALUE={counts['VALUE_CONFLICT']} "
        f"CLASS={counts['CLASSIFICATION_CONFLICT']} "
        f"CONTEXT={counts['CONTEXT_CONFLICT']} "
        f"A_ONLY={counts['A_ONLY']} B_ONLY={counts['B_ONLY']} "
        f"review={review_count} coverage_diffs={len(coverage_diff)}"
    )


def individual_adjudicated_record_errors(
    row: dict[str, str], routing: Mapping[str, str], location: str
) -> list[str]:
    temporary = dict(row)
    temporary["__line_number"] = location
    # Final lineage is added by the builder; validate the substantive record as a
    # candidate-shaped adjudicator row first.
    temporary["source_agents"] = ""
    temporary["adjudication_status"] = ""
    return validate_record_rows(
        Path("resolution.csv"), [temporary], routing, "ADJUDICATED", final=False
    )


def load_and_validate_resolutions(
    route: str,
    file_id: str,
    pairs: list[dict[str, str]],
    pair_values: Mapping[str, tuple[dict[str, str] | None, dict[str, str] | None]],
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]], dict[str, dict[str, str]]]:
    routing = routing_for(route, file_id)
    paths = pair_paths(route, file_id)
    rows = read_strict_csv(paths["resolution"], RESOLUTION_COLUMNS)
    required = {row["pair_id"] for row in pairs if row["requires_review"] == "YES"}
    resolutions: dict[str, dict[str, str]] = {}
    additions: list[dict[str, str]] = []
    errors: list[str] = []
    pair_status = {row["pair_id"]: row["pair_status"] for row in pairs}
    for row in rows:
        location = row_location(paths["resolution"], row)
        decision = row.get("decision", "")
        if decision not in RESOLUTION_DECISIONS:
            errors.append(
                f"{location}: decision must be one of {RESOLUTION_DECISIONS}, found {decision!r}"
            )
            continue
        if not row.get("reason", "").strip():
            errors.append(f"{location}: reason is required")
        pair_id = row.get("pair_id", "")
        record = {column: row.get(column, "") for column in RECORD_COLUMNS}
        has_record = any(value.strip() for value in record.values())
        if decision == "ADD":
            if pair_id:
                errors.append(f"{location}: ADD leaves pair_id blank")
            if not has_record:
                errors.append(f"{location}: ADD requires a full record")
            else:
                additions.append(record)
            continue
        if not pair_id or pair_id not in pair_values:
            errors.append(f"{location}: unknown or blank pair_id {pair_id!r}")
            continue
        if pair_id not in required and decision not in {"MERGE", "REJECT"}:
            errors.append(f"{location}: an additional source review requires MERGE or REJECT")
        if pair_id in resolutions:
            errors.append(f"{location}: pair {pair_id} has more than one resolution")
        resolutions[pair_id] = row
        if decision in {"MERGE"}:
            if not has_record:
                errors.append(f"{location}: MERGE requires a full corrected record")
        elif has_record:
            errors.append(f"{location}: {decision} leaves appended record columns blank")
        status = pair_status.get(pair_id, "")
        if decision == "CONFIRM" and status != "EXACT":
            errors.append(f"{location}: CONFIRM is valid only for an EXACT sampled pair")
    missing = sorted(required - set(resolutions))
    if missing:
        errors.append(f"{paths['resolution']}: missing resolutions for {missing}")

    coverage_diff = read_strict_csv(paths["coverage_diff"], COVERAGE_DIFF_COLUMNS)
    coverage_rows = read_strict_csv(
        paths["coverage_resolution"], COVERAGE_RESOLUTION_COLUMNS
    )
    required_pages = {row["source_page"] for row in coverage_diff}
    coverage_resolutions: dict[str, dict[str, str]] = {}
    page_limit = int(routing["page_count"])
    for row in coverage_rows:
        location = row_location(paths["coverage_resolution"], row)
        try:
            page = int(row.get("source_page", ""))
        except ValueError:
            errors.append(f"{location}: source_page must be an integer")
            continue
        if page < 1 or page > page_limit:
            errors.append(f"{location}: source_page {page} outside 1..{page_limit}")
        page_text = str(page)
        if page_text in coverage_resolutions:
            errors.append(f"{location}: source_page {page} repeated")
        coverage_resolutions[page_text] = row
        if row.get("final_page_status", "") not in PAGE_STATUSES:
            errors.append(
                f"{location}: final_page_status must be one of {PAGE_STATUSES}"
            )
        nonnegative_integer(
            row.get("final_expected_observation_count", ""),
            "final_expected_observation_count",
            errors,
            location,
        )
        if not row.get("reason", "").strip():
            errors.append(f"{location}: reason is required")
    missing_pages = sorted(required_pages - set(coverage_resolutions), key=int)
    if missing_pages:
        errors.append(
            f"{paths['coverage_resolution']}: missing page resolutions for {missing_pages}"
        )

    # Validate MERGE and ADD records only after row-level resolution coverage is known.
    for pair_id, resolution in resolutions.items():
        if resolution["decision"] == "MERGE":
            record = {column: resolution.get(column, "") for column in RECORD_COLUMNS}
            temporary = dict(record)
            temporary["source_agents"] = "A+B+ADJUDICATOR"
            temporary["adjudication_status"] = "RESOLVED"
            temporary["agent_role"] = "ADJUDICATED"
            errors.extend(
                validate_record_rows(
                    paths["resolution"],
                    [dict(temporary, __line_number=resolution.get("__line_number", "?"))],
                    routing,
                    "ADJUDICATED",
                    final=True,
                    enforce_file_invariants=False,
                )
            )
    for addition in additions:
        temporary = dict(addition)
        temporary["source_agents"] = "ADJUDICATOR"
        temporary["adjudication_status"] = "ADDED"
        temporary["agent_role"] = "ADJUDICATED"
        errors.extend(
            validate_record_rows(
                paths["resolution"],
                [dict(temporary, __line_number="ADD")],
                routing,
                "ADJUDICATED",
                final=True,
                enforce_file_invariants=False,
            )
        )
    if errors:
        raise ContractFailure("Resolution validation failed:\n- " + "\n- ".join(errors))
    return resolutions, additions, coverage_resolutions


def final_record(
    source: Mapping[str, str], source_agents: str, status: str
) -> dict[str, str]:
    row = {column: source.get(column, "") for column in RECORD_COLUMNS}
    row["agent_role"] = "ADJUDICATED"
    row["source_agents"] = source_agents
    row["adjudication_status"] = status
    return row


def build_final_command(route: str, file_id: str) -> None:
    routing = routing_for(route, file_id)
    a_records, a_coverage, a_errors = validate_candidate_data(
        route, file_id, "A", allow_legacy_qualifiers=True)
    b_records, b_coverage, b_errors = validate_candidate_data(
        route, file_id, "B", allow_legacy_qualifiers=True)
    if a_errors or b_errors:
        raise ContractFailure(
            "Cannot build final from invalid candidates:\n- "
            + "\n- ".join([*a_errors, *b_errors])
        )
    pairs, pair_values = pair_records(a_records, b_records)
    pair_path = pair_paths(route, file_id)["pair"]
    disk_pairs = read_strict_csv(pair_path, PAIR_COLUMNS)
    if [clean_row(row, PAIR_COLUMNS) for row in disk_pairs] != pairs:
        raise ContractFailure(
            f"{pair_path}: stale comparison; rerun compare before build-final"
        )
    resolutions, additions, coverage_resolutions = load_and_validate_resolutions(
        route, file_id, pairs, pair_values
    )
    output: list[dict[str, str]] = []
    for pair in pairs:
        pair_id = pair["pair_id"]
        a_row, b_row = pair_values[pair_id]
        resolution = resolutions.get(pair_id)
        if pair["requires_review"] == "NO" and resolution is None:
            assert pair["pair_status"] == "EXACT" and a_row is not None and b_row is not None
            output.append(final_record(a_row, *_outcome("EXACT_unreviewed")))
            continue
        assert resolution is not None
        decision = resolution["decision"]
        if decision == "REJECT":
            continue
        if decision == "CONFIRM":
            assert a_row is not None and b_row is not None
            output.append(final_record(a_row, *_outcome("CONFIRM_outcome")))
        elif decision == "ACCEPT_A":
            if a_row is None:
                raise ContractFailure(f"{pair_id}: ACCEPT_A has no A row")
            status = (
                "VERIFIED_ONE_SIDED" if pair["pair_status"] == "A_ONLY" else "RESOLVED"
            )
            assert status in _outcome("ACCEPT_A_outcome")[1].split("|")
            output.append(final_record(a_row, _outcome("ACCEPT_A_outcome")[0], status))
        elif decision == "ACCEPT_B":
            if b_row is None:
                raise ContractFailure(f"{pair_id}: ACCEPT_B has no B row")
            status = (
                "VERIFIED_ONE_SIDED" if pair["pair_status"] == "B_ONLY" else "RESOLVED"
            )
            assert status in _outcome("ACCEPT_B_outcome")[1].split("|")
            output.append(final_record(b_row, _outcome("ACCEPT_B_outcome")[0], status))
        elif decision == "MERGE":
            merged = {column: resolution.get(column, "") for column in RECORD_COLUMNS}
            # A merge credits the readers that saw the cell. On a one-sided
            # pair only one lane ever read it, so crediting A+B there would
            # report agreement between two readers where one never saw the row.
            outcome = {
                "A_ONLY": "MERGE_A_ONLY_outcome",
                "B_ONLY": "MERGE_B_ONLY_outcome",
            }.get(pair["pair_status"], "MERGE_outcome")
            output.append(final_record(merged, *_outcome(outcome)))
        else:
            raise ContractFailure(f"{pair_id}: unsupported decision {decision}")
    for addition in additions:
        output.append(final_record(addition, *_outcome("ADD_outcome")))
    output.sort(key=record_sort_key)
    final_record_path, final_coverage_path = final_paths(route, file_id)
    record_errors = validate_record_rows(
        final_record_path,
        [dict(row, __line_number=str(index + 2)) for index, row in enumerate(output)],
        routing,
        "ADJUDICATED",
        final=True,
    )
    if record_errors:
        raise ContractFailure("Constructed final records are invalid:\n- " + "\n- ".join(record_errors))

    # Both halves of one document report the same contract. Stamping the
    # coverage with the current CONTRACT_VERSION while the records keep the
    # stamp they were written under published two answers for one document,
    # and a reader keying behaviour off the stamp got whichever half it opened.
    # A document that holds a row written under a newer contract is a document
    # of that contract, so the coverage takes the newest stamp its own records
    # carry.
    final_contract_version = max(
        (row.get("contract_version", "") for row in output if row.get("contract_version")),
        key=contract_version_key,
        default=CONTRACT_VERSION,
    )
    a_coverage_map = {row["source_page"]: row for row in a_coverage}
    b_coverage_map = {row["source_page"]: row for row in b_coverage}
    metadata = actual_page_metadata(output)
    final_coverage: list[dict[str, str]] = []
    coverage_errors: list[str] = []
    for page_number in range(1, int(routing["page_count"]) + 1):
        page = str(page_number)
        actual = int(metadata.get(page_number, {}).get("count", 0))
        a = a_coverage_map[page]
        b = b_coverage_map[page]
        same = all(
            a.get(field, "") == b.get(field, "")
            for field in (
                "page_status",
                "layout_checked",
                "expected_observation_count",
                "source_structures",
                "relevant_record_families",
            )
        )
        resolved = coverage_resolutions.get(page)
        if resolved:
            status = resolved["final_page_status"]
            expected = int(resolved["final_expected_observation_count"])
            note = resolved["reason"]
        elif same:
            status = a["page_status"]
            expected = int(a["expected_observation_count"])
            note = " | ".join(dict.fromkeys(r.get("notes", "").strip() for r in (a, b)
                                           if r.get("notes", "").strip()))
        else:
            coverage_errors.append(f"page {page}: unresolved A/B coverage difference")
            continue
        if expected != actual:
            coverage_errors.append(
                f"page {page}: final expected count {expected} does not equal constructed record count {actual}; add or correct coverage-resolution.csv"
            )
        # The document-identity row does not make a page populated, the same
        # exemption `validate_coverage_rows` already applies. Without it a
        # cover page carrying only that row had no valid status here: this
        # check refused REFERENCE_ONLY and the validator two calls later
        # refused ELIGIBLE_DATA_EXTRACTED, so the document could not be built
        # at all.
        only_context = set(metadata.get(page_number, {}).get("families", ())) == {
            "document_context"
        }
        if actual > 0 and not only_context and status != "ELIGIBLE_DATA_EXTRACTED":
            coverage_errors.append(
                f"page {page}: populated final page requires ELIGIBLE_DATA_EXTRACTED"
            )
        if actual == 0 and status == "ELIGIBLE_DATA_EXTRACTED":
            coverage_errors.append(
                f"page {page}: ELIGIBLE_DATA_EXTRACTED requires a final record"
            )
        structures = joined_sorted(metadata.get(page_number, {}).get("structures", set()))
        families = joined_sorted(metadata.get(page_number, {}).get("families", set()))
        final_coverage.append(
            {
                "contract_version": final_contract_version,
                "file_id": file_id,
                "source_sha256": routing["source_sha256"],
                "canonical_doc_type": routing["canonical_doc_type"],
                "route": route,
                "product_tier": routing["product_tier"],
                "agent_role": "ADJUDICATED",
                "source_page": page,
                "page_status": status,
                "layout_checked": (
                    a["layout_checked"]
                    if (
                        layout_policy := matrices.resolve(
                            COVERAGE_LAYOUT,
                            "records_present"
                            if actual > 0
                            else ("empty_agents_agree" if same else "empty_agents_disagree"),
                        )
                    )
                    == "SOURCE"
                    else layout_policy
                ),
                "source_structures": structures,
                "relevant_record_families": families,
                "expected_observation_count": str(actual),
                "records_written": str(actual),
                "notes": note,
            }
        )
    if coverage_errors:
        raise ContractFailure("Final coverage construction failed:\n- " + "\n- ".join(coverage_errors))
    coverage_errors = validate_coverage_rows(
        final_coverage_path, final_coverage, output, routing, "ADJUDICATED")
    coverage_errors.extend(completeness_errors(routing, output, final_coverage))
    coverage_errors.extend(page_image_errors(routing))
    if coverage_errors:
        raise ContractFailure("Final preflight failed before replacing outputs:\n- " + "\n- ".join(coverage_errors))
    write_csv(final_record_path, RECORD_COLUMNS, output)
    write_csv(final_coverage_path, COVERAGE_COLUMNS, final_coverage)
    validate_final_command(route, file_id)
    print(f"PASS: built {len(output)} final records for {route}/{file_id}")


def validate_final_data(
    route: str, file_id: str, *, backlog: list[dict[str, str]] | None = None
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    routing = routing_for(route, file_id)
    record_path, coverage_path = final_paths(route, file_id)
    records = read_strict_csv(record_path, RECORD_COLUMNS)
    coverage = read_strict_csv(coverage_path, COVERAGE_COLUMNS)
    errors = validate_record_rows(
        record_path, records, routing, "ADJUDICATED", final=True, backlog=backlog
    )
    for row in records:
        qualifier = METRIC_QUALIFIERS.get(row.get("metric_category", ""), {})
        if qualifier.get("qualified"):
            for dimension in qualifier["required_dimensions"]:
                if not row.get(dimension, "").strip():
                    errors.append(f"{record_path}:{row.get('__line_number', '?')}: publication requires "
                                  f"a reviewed {dimension}, including on historical records")
    errors.extend(
        validate_coverage_rows(
            coverage_path, coverage, records, routing, "ADJUDICATED"
        )
    )
    errors.extend(completeness_errors(routing, records, coverage))
    errors.extend(page_image_errors(routing))
    return records, coverage, errors


def backlog_table(entries: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """One row per route, document, metric category and blank dimension.

    Sorted by those four fields, so the ledger on disk is the same file for the
    same corpus and a difference between two derivations is a real difference.
    """

    counts = Counter(
        (
            entry["route"],
            entry["file_id"],
            entry["metric_category"],
            entry["blank_dimension"],
        )
        for entry in entries
    )
    return [
        {
            "route": route,
            "file_id": file_id,
            "metric_category": metric_category,
            "blank_dimension": dimension,
            "row_count": str(count),
        }
        for (route, file_id, metric_category, dimension), count in sorted(counts.items())
    ]


def final_backlog_entries(path: Path, route: str, file_id: str) -> list[dict[str, str]]:
    """One entry per row of an adjudicated final that carries a backlog blank.

    The publisher reaches the same rule through the validator; a caller holding
    the file path alone, such as the release stage that re-derives the ledger,
    reaches it through here. Both read `blank_qualified_dimensions`.
    """

    entries: list[dict[str, str]] = []
    for row in read_strict_csv(path, RECORD_COLUMNS):
        dimensions, _ = blank_qualified_dimensions(row)
        entries.extend(
            {
                "route": route,
                "file_id": file_id,
                "metric_category": row.get("metric_category", ""),
                "blank_dimension": dimension,
            }
            for dimension in dimensions
        )
    return entries


def validate_final_command(route: str, file_id: str) -> None:
    _, _, errors = validate_final_data(route, file_id)
    if errors:
        raise ContractFailure("Final validation failed:\n- " + "\n- ".join(errors))
    print(f"PASS: {route}/{file_id} final records and coverage")


def worklist_for_scope(route: str, scope: str) -> list[dict[str, str]]:
    if scope == "full":
        path = WORKLIST_ROOT / f"{route}.csv"
    else:
        path = WORKLIST_ROOT / scope / f"{route}.csv"
    return read_simple_csv(path)


def prepare_command(route: str | None, scope: str, bench: bool = False) -> None:
    routes = [route] if route else list(ROUTES)
    created = 0
    for selected_route in routes:
        for row in worklist_for_scope(selected_route, scope):
            folder = file_folder(selected_route, row["file_id"])
            folder.mkdir(parents=True, exist_ok=True)
            lanes = [
                agent.lower()
                for agent in matrices.resolve(
                    LANE_SELECTION, "bench" if bench else "production"
                ).split("|")
            ]
            for agent in lanes:
                before = sum(
                    path.exists()
                    for path in (folder / f"records-{agent}.csv", folder / f"coverage-{agent}.csv")
                )
                write_header_if_missing(folder / f"records-{agent}.csv", RECORD_COLUMNS)
                write_header_if_missing(folder / f"coverage-{agent}.csv", COVERAGE_COLUMNS)
                created += 2 - before
    lanes = ", ".join(
        matrices.resolve(LANE_SELECTION, "bench" if bench else "production").split("|")
    )
    print(f"PASS: prepared {created} new candidate files for scope={scope} "
          f"(lanes {lanes})")


def _has_rows(path: Path) -> bool:
    """True when a CSV holds at least one data row.

    `prepare` writes header-only stubs, so file existence alone would report
    every prepared document as finished.
    """
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            return any(row and any(cell.strip() for cell in row) for row in reader)
    except OSError:
        return False


def _lane_worked(folder: Path, agent: str) -> bool:
    """An extractor lane is done when its page coverage is written.

    A header-only records file is legitimate (no eligible data on any page), but
    coverage must carry one row per physical page, so it is the reliable signal.
    """
    return (folder / f"records-{agent}.csv").is_file() and _has_rows(
        folder / f"coverage-{agent}.csv"
    )


def _lane_state(route: str, file_id: str, agent: str) -> str:
    """Validate completed finals without reopening historical candidate files."""
    if any(path.is_file() for path in final_paths(route, file_id)):
        errors = _completed_final_errors(route, file_id)
        return matrices.resolve(semantic_checks.POLICY,
                                "invalid_final" if errors else "valid_final", context="lane_state")
    record_path, coverage_path = candidate_paths(route, file_id, agent)
    records_started = _has_rows(record_path)
    coverage_started = _has_rows(coverage_path)
    if not records_started and not coverage_started:
        return "NOT_STARTED"
    if not coverage_started:
        return "IN_PROGRESS"
    try:
        audit_file_command(
            route, file_id, agent, quiet=True, require_images=False
        )
    except ContractFailure:
        return "IN_PROGRESS"
    return "DONE"


def _completed_final_errors(route: str, file_id: str) -> list[str]:
    try:
        _, _, errors = validate_final_data(route, file_id)
        return errors
    except (ContractFailure, OSError, ValueError) as exc:
        return [str(exc)]


# Where an agent drops a scratch script: beside the repository README, in the
# working ledger next to the candidate it writes, or in the scratch folder.
# A generator is refused wherever it sits, `tmp` included: that folder is for
# scratch, and a candidate emitted by a program is not scratch.
GENERATOR_SEARCH_ROOTS: Final = (".", "ledgers", "tmp")
GENERATOR_MARKERS: Final = ("pdf-extraction-csv", "records-a.csv", "records-b.csv",
                            "coverage-a.csv", "coverage-b.csv")


def generator_scripts() -> list[str]:
    """Scripts that write a candidate file, which no extractor may use.

    The prompts forbid a generator in their first paragraph, and nothing could
    tell one had been used: a candidate emitted by a loop and a candidate read
    off the pages are the same CSV. One 149-page document was filed this way,
    its coverage written by a script that never opened a page, and both the
    validator and the completeness audit passed it.
    """
    found: list[str] = []
    for root in GENERATOR_SEARCH_ROOTS:
        base = PROJECT_ROOT / root
        if not base.is_dir():
            continue
        pattern = "*.py" if root == "." else "**/*.py"
        for path in sorted(base.glob(pattern)):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(marker in text for marker in GENERATOR_MARKERS):
                found.append(path.relative_to(PROJECT_ROOT).as_posix())
    return found


def refuse_generator_scripts() -> None:
    scripts = generator_scripts()
    if scripts:
        raise ContractFailure(
            "a script that writes candidate rows is present: "
            + ", ".join(scripts)
            + ". An extractor reads the source and types the rows; a generated "
            "candidate is not a second reading of the document, so the two "
            "lanes stop being independent. Delete the script and extract the "
            "document by reading it."
        )


def _lane_reason(route: str, file_id: str, agent: str) -> str:
    """Why one document is not finished for one lane, in one line.

    `_lane_state` throws the audit message away because it answers a
    three-value question. The lane gate reports the document back to the
    extractor that has to fix it, so it needs the reason as well as the state.
    """
    if any(path.is_file() for path in final_paths(route, file_id)):
        errors = _completed_final_errors(route, file_id)
        return "Reviewer repair required; retain original candidates: " + (errors[0][:160] if errors else "")
    try:
        audit_file_command(route, file_id, agent, quiet=True, require_images=False)
    except ContractFailure as exc:
        detail = next(
            (line.lstrip("- ").strip()
             for line in str(exc).splitlines()[1:] if line.strip()),
            str(exc).splitlines()[0],
        )
        # The absolute candidate path is the same for every row of this report
        # and crowds out the sentence that says what is wrong.
        folder = str(file_folder(route, file_id))
        detail = detail.replace(folder + os.sep, "").replace(folder, "")
        return detail[:200]
    return ""


def lane_state_rows(route: str, agent: str, scope: str) -> list[dict[str, str]]:
    """Every document this lane is assigned, with the state of each.

    The lane's assignment is the whole worklist for its route: a lane does not
    choose its documents and no operator message is needed to name them.
    """
    rows: list[dict[str, str]] = []
    for worklist in worklist_for_scope(route, scope):
        file_id = worklist["file_id"]
        record_path, coverage_path = candidate_paths(route, file_id, agent)
        state = _lane_state(route, file_id, agent)
        rows.append(
            {
                "file_id": file_id,
                "pages": worklist.get("page_count", ""),
                "records": str(_row_count(record_path)),
                "covered": str(_row_count(coverage_path)),
                "state": state,
                "reason": "" if state == "DONE" else _lane_reason(route, file_id, agent),
            }
        )
    return rows


def _row_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            return sum(1 for row in reader if row and any(cell.strip() for cell in row))
    except OSError:
        return 0


def lane_check_command(route: str, agent: str, scope: str = "active") -> None:
    """The lane's assignment, and the gate that says the lane is finished.

    Every other check takes one `--file`, so a document the lane never opened
    produces no failing command anywhere: to a per-file gate, not started and
    not assigned look the same. One round lost three documents this way, one of
    them never touched at all, and each lane reported itself finished. This
    reads the worklist, recomputes every document's state from the files on
    disk, and refuses while any of them is unfinished.
    """
    if agent not in EXTRACTOR_AGENTS:
        raise ContractFailure(
            f"agent must be one of {', '.join(EXTRACTOR_AGENTS)}, found {agent!r}")
    refuse_generator_scripts()
    rows = lane_state_rows(route, agent, scope)
    unfinished = [row for row in rows if row["state"] != "DONE"]
    print(f"Lane {agent} on {route}: {len(rows)} document(s) assigned, "
          f"{len(rows) - len(unfinished)} finished.")
    for row in rows:
        mark = "DONE" if row["state"] == "DONE" else row["state"]
        print(f"  {row['file_id']:<8}{row['pages']:>4}p  "
              f"records={row['records']:<6}covered={row['covered']:<5}{mark}")
        if row["reason"]:
            print(f"           {row['reason']}")
    if unfinished:
        review_state = matrices.resolve(semantic_checks.POLICY, "invalid_final", context="lane_state")
        held = [row["file_id"] for row in unfinished if row["state"] == review_state]
        if held:
            raise ContractFailure("Existing finals require reviewer repair: " + ", ".join(held)
                                  + ". Leave original candidate files unchanged; lane-check cannot close until finals validate.")
        raise ContractFailure(
            f"Lane {agent} on {route} is not finished: "
            + ", ".join(row["file_id"] for row in unfinished)
            + ". Work each one to a passing audit-file, then run lane-check again."
        )
    print(f"PASS: lane {agent} on {route} finished every assigned document.")


def _comparison_done(folder: Path) -> bool:
    """True after comparison writes page-level coverage results.

    A valid document can yield zero observation pairs, so the page-level
    coverage comparison is the completion signal rather than pair-index rows.
    """
    return (folder / "pair-index.csv").is_file() and _has_rows(
        folder / "coverage-diff.csv"
    )


def _final_state(route: str, file_id: str) -> tuple[bool, int]:
    """Whether the final satisfies the live contract, and its backlog row count.

    A blank dimension the row's own contract predates is not a defect in the
    adjudication: nobody was asked for it. The document is finished and carries
    a debt, and status says which rather than calling it unfinished.
    """

    folder = file_folder(route, file_id)
    if not _has_rows(folder / "coverage-final.csv"):
        return False, 0
    entries: list[dict[str, str]] = []
    try:
        _, _, errors = validate_final_data(route, file_id, backlog=entries)
    except (ContractFailure, OSError):
        return False, 0
    return not errors, len(entries)


def _final_done(route: str, file_id: str) -> bool:
    """True only when the adjudicated records still satisfy the live contract."""
    return _final_state(route, file_id)[0]


def status_command(scope: str) -> None:
    rows: list[dict[str, object]] = []
    for route in ROUTES:
        for worklist in worklist_for_scope(route, scope):
            file_id = worklist["file_id"]
            folder = file_folder(route, file_id)
            a_state = _lane_state(route, file_id, "A")
            b_state = _lane_state(route, file_id, "B")
            paired = (
                a_state == "DONE"
                and b_state == "DONE"
                and _comparison_done(folder)
            )
            # An adjudicated final that satisfies the contract is final, whether
            # or not the candidate lanes still look paired today. Publication
            # reads the final alone, so gating this on the lane state made
            # status call a document unfinished that the corpus publishes.
            done, backlog_rows = _final_state(route, file_id)
            rows.append(
                {
                    "route": route,
                    "file_id": file_id,
                    "A": a_state,
                    "B": b_state,
                    "paired": paired,
                    "final": done,
                    "backlog": backlog_rows,
                }
            )
    counts = Counter()
    for row in rows:
        for field in ("A", "B"):
            counts[field] += row[field] == "DONE"
            counts[f"{field}_partial"] += row[field] == "IN_PROGRESS"
        for field in ("paired", "final"):
            counts[field] += bool(row[field])
        counts["backlog_documents"] += bool(row["final"] and row["backlog"])
        counts["backlog_rows"] += int(row["backlog"]) if row["final"] else 0
    print(
        f"scope={scope} documents={len(rows)} "
        f"A done={counts['A']} partial={counts['A_partial']} "
        f"B done={counts['B']} partial={counts['B_partial']} "
        f"paired={counts['paired']} final={counts['final']} "
        f"backlog={counts['backlog_rows']} rows in "
        f"{counts['backlog_documents']} documents"
    )
    unclaimed = []
    for route in ROUTES:
        claims = read_claims(route)
        held = [f"{a}={claims.get(a, {}).get('extractor_model', '-')}"
                for a in CLAIMABLE_AGENTS]
        if any(claims.get(a) for a in CLAIMABLE_AGENTS):
            print(f"  claim {route:<28}{'  '.join(held)}")
        else:
            unclaimed.append(route)
    if unclaimed:
        print(f"  claim UNCLAIMED: {', '.join(unclaimed)}")
    short = {"NOT_STARTED": "-", "IN_PROGRESS": "part", "DONE": "DONE"}
    for row in rows:
        if row["final"] and not row["backlog"]:
            continue
        final_mark = f"BACKLOG:{row['backlog']}" if row["final"] else "-"
        print(
            f"{row['route']:<28}{row['file_id']:<8}"
            f"A={short[row['A']]:<5}B={short[row['B']]:<5}"
            f"P={'Y' if row['paired'] else '-'} F={final_mark}"
        )


ROUND_RECORD_COLUMNS: Final = (*RECORD_COLUMNS, "extractor_model")
ROUND_COVERAGE_COLUMNS: Final = (*COVERAGE_COLUMNS, "extractor_model")


def collect_round(
    route: str, scope: str
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[str],
    list[dict[str, str]],
    list[str],
]:
    """Every adjudicated row of one round, with its model attribution.

    Stage one of consolidation, and the only stage that reads a document. It
    returns errors instead of raising so a caller can report every bad document
    in a round at once, rather than stopping at the first. Three outcomes, and
    A final with missing required qualifiers blocks publication regardless of
    its contract date. A document without a final remains in the unfinished list.
    """
    qualifier_backlog_policy()
    records: list[dict[str, str]] = []
    coverage: list[dict[str, str]] = []
    errors: list[str] = []
    entries: list[dict[str, str]] = []
    unfinished: list[str] = []
    for worklist in worklist_for_scope(route, scope):
        file_id = worklist["file_id"]
        if not final_paths(route, file_id)[0].is_file():
            unfinished.append(f"{route}/{file_id}")
            continue
        document_entries: list[dict[str, str]] = []
        try:
            final_records, final_coverage, final_errors = validate_final_data(
                route, file_id, backlog=document_entries
            )
        except ContractFailure as exc:
            errors.append(f"{route}/{file_id}: {exc}")
            continue
        if final_errors:
            errors.extend(f"{route}/{file_id}: {error}" for error in final_errors)
            continue
        entries.extend(document_entries)
        claims = {
            slot: {"extractor_model": model_that_wrote(route, file_id, slot)}
            for slot in CANDIDATE_AGENTS
        }
        claims.update({j: read_claims(route).get(j, {}) for j in ADJUDICATOR_AGENTS})
        for row in final_records:
            published = clean_row(row, RECORD_COLUMNS)
            published["extractor_model"] = _model_for_final(row, claims)
            records.append(published)
        for row in final_coverage:
            published = clean_row(row, COVERAGE_COLUMNS)
            published["extractor_model"] = _model_for_final_coverage(row, claims)
            coverage.append(published)
    records.sort(key=lambda row: (row["route"], row["file_id"], *record_sort_key(row)))
    coverage.sort(key=lambda row: (row["route"], row["file_id"], int(row["source_page"])))
    return records, coverage, errors, backlog_table(entries), unfinished


ATTRIBUTION_RECORD_KEY: Final = (
    "file_id",
    "source_page",
    "source_row_label",
    "source_column_label",
    "source_occurrence",
    "record_family",
)
ATTRIBUTION_COVERAGE_KEY: Final = ("file_id", "source_page")


def _attribution_key(row: Mapping[str, str], fields: Sequence[str]) -> tuple[str, ...]:
    return tuple(row.get(field, "") for field in fields)


def _published_attribution(
    path: Path, columns: Sequence[str], fields: Sequence[str]
) -> dict[tuple[str, ...], str]:
    """The model each row of the round on disk already publishes under."""

    if not path.is_file():
        return {}
    try:
        rows = read_strict_csv(path, columns)
    except ContractFailure:
        # A round file written under a header this contract no longer accepts
        # cannot be read row by row. Deriving attribution afresh is then the
        # only option, and it is the behaviour that was in place before.
        return {}
    return {
        _attribution_key(row, fields): row.get("extractor_model", "")
        for row in rows
        if row.get("extractor_model", "")
    }


def freeze_attribution(
    rows: list[dict[str, str]],
    published: Mapping[tuple[str, ...], str],
    fields: Sequence[str],
) -> int:
    """Keep the model a already-published row publishes under.

    `model_that_wrote` reads a candidate file's mtime against the claim
    ledger, so a lane claimed by a new model re-attributes every document on
    the route the next time it is published, including the documents that lane
    never opened. A row already in the round file was written by whoever the
    round said wrote it; republishing is a consolidation, not a re-reading, so
    only a key the round has never carried takes a derived model.
    """

    frozen = 0
    for row in rows:
        previous = published.get(_attribution_key(row, fields))
        if previous and previous != row.get("extractor_model", ""):
            row["extractor_model"] = previous
            frozen += 1
        elif previous:
            row["extractor_model"] = previous
    return frozen


def publish_round(
    route: str, scope: str
) -> tuple[int, int, list[dict[str, str]], list[str]]:
    """Stage one: consolidate one round into its own pair of files.

    A round is readable the moment it is adjudicated, without waiting for the
    slowest route, and re-publishing it rewrites only its own two files. The
    backlog table and the unfinished documents travel back with the counts so
    the command can state both.
    """
    records, coverage, errors, backlog, unfinished = collect_round(route, scope)
    if errors:
        raise ContractFailure(
            f"Round {route} not publishable:\n- " + "\n- ".join(errors))
    policy = matrices.resolve(ATTRIBUTION, "republish_attribution")
    if policy != "frozen_per_published_key":
        raise ContractFailure(
            f"{ATTRIBUTION}.csv names an unsupported republish_attribution {policy!r}"
        )
    freeze_attribution(
        records,
        _published_attribution(
            round_records(route), ROUND_RECORD_COLUMNS, ATTRIBUTION_RECORD_KEY
        ),
        ATTRIBUTION_RECORD_KEY,
    )
    freeze_attribution(
        coverage,
        _published_attribution(
            round_coverage(route), ROUND_COVERAGE_COLUMNS, ATTRIBUTION_COVERAGE_KEY
        ),
        ATTRIBUTION_COVERAGE_KEY,
    )
    round_records(route).parent.mkdir(parents=True, exist_ok=True)
    write_csv(round_records(route), ROUND_RECORD_COLUMNS, records)
    write_csv(round_coverage(route), ROUND_COVERAGE_COLUMNS, coverage)
    return len(records), len(coverage), backlog, unfinished


def publish_corpus(scope: str) -> tuple[int, int, list[dict[str, str]], list[str]]:
    """Stage two: concatenate the published rounds into the corpus files.

    This reads the round files rather than the documents, so the corpus is
    the same rounds that were checked at stage one and a failure is already
    localised to a round before this runs. Each round is re-derived from its
    documents and compared against its published file first: a round edited or
    re-adjudicated since it was published is named and blocks the corpus, which
    is the one way stale data could otherwise reach the end of the pipeline.

    The qualifier backlog of the whole scope is written on every run, so the
    page-reading step that closes it reads one live list.
    """
    records: list[dict[str, str]] = []
    coverage: list[dict[str, str]] = []
    errors: list[str] = []
    backlog: list[dict[str, str]] = []
    unfinished: list[str] = []
    for route in ROUTES:
        (
            expected_records,
            expected_coverage,
            route_errors,
            route_backlog,
            route_unfinished,
        ) = collect_round(route, scope)
        backlog.extend(route_backlog)
        unfinished.extend(route_unfinished)
        if route_errors:
            errors.extend(route_errors)
            continue
        if not expected_records:
            continue
        if not round_records(route).is_file():
            errors.append(
                f"{route}: adjudicated but never consolidated; run "
                f"`publish --route {route}` first")
            continue
        published = read_strict_csv(round_records(route), ROUND_RECORD_COLUMNS)
        stale = _round_drift(published, expected_records)
        if stale:
            errors.append(f"{route}: {stale}; re-run `publish --route {route}`")
            continue
        records.extend(clean_row(row, ROUND_RECORD_COLUMNS) for row in published)
        coverage.extend(
            clean_row(row, ROUND_COVERAGE_COLUMNS)
            for row in read_strict_csv(round_coverage(route), ROUND_COVERAGE_COLUMNS)
        )
    if errors:
        raise ContractFailure("Corpus publication blocked:\n- " + "\n- ".join(errors))
    records.sort(key=lambda row: (row["route"], row["file_id"], *record_sort_key(row)))
    coverage.sort(key=lambda row: (row["route"], row["file_id"], int(row["source_page"])))
    backlog.sort(
        key=lambda row: (
            row["route"],
            row["file_id"],
            row["metric_category"],
            row["blank_dimension"],
        )
    )
    write_csv(published_records(), ROUND_RECORD_COLUMNS, records)
    write_csv(published_coverage(), ROUND_COVERAGE_COLUMNS, coverage)
    qualifier_backlog_ledger().parent.mkdir(parents=True, exist_ok=True)
    write_csv(qualifier_backlog_ledger(), QUALIFIER_BACKLOG_COLUMNS, backlog)
    return len(records), len(coverage), backlog, unfinished


def _round_drift(published: Sequence[Mapping[str, str]],
                 expected: Sequence[Mapping[str, str]]) -> str:
    """How a published round differs from what its documents now say."""
    if len(published) != len(expected):
        return (f"published file holds {len(published)} records but its documents "
                f"now yield {len(expected)}")
    published_keys = Counter(record_key(row) for row in published)
    expected_keys = Counter(record_key(row) for row in expected)
    if published_keys != expected_keys:
        moved = sum((expected_keys - published_keys).values())
        return f"{moved} record keys differ from the documents"
    changed = sum(
        1 for a, b in zip(published, expected)
        if normalize_key_text(a.get("metric_value_raw", ""))
        != normalize_key_text(b.get("metric_value_raw", ""))
    )
    if changed:
        return f"{changed} values differ from the documents"
    return ""


def _print_scope_state(
    backlog: Sequence[Mapping[str, str]], unfinished: Sequence[str]
) -> None:
    """The two facts a publication states beside its counts.

    A document with no adjudicated final is named rather than counted, and the
    rows a page reading still owes are counted rather than named, because the
    ledger names them.
    """

    print(f"unfinished: {', '.join(unfinished) if unfinished else 'none'}")
    rows = sum(int(row["row_count"]) for row in backlog)
    documents = len({(row["route"], row["file_id"]) for row in backlog})
    print(f"qualifier backlog: {rows} rows in {documents} documents")


def publish_command(scope: str, route_filter: str | None = None) -> None:
    """Consolidate adjudicated output, one round at a time then the corpus.

    Publication blocks on any document whose final fails validation, so a
    half-adjudicated round cannot ship, and the corpus is assembled only from
    rounds that already passed that check. A document with no final at all is
    named and skipped, and a blank qualified dimension the row's contract
    predates is published and counted.
    """
    if route_filter:
        n_records, n_coverage, backlog, unfinished = publish_round(route_filter, scope)
        print(f"PASS: consolidated round {route_filter}: {n_records} records, "
              f"{n_coverage} page-coverage rows")
        _print_scope_state(backlog, unfinished)
        print(f"  -> {round_records(route_filter)}")
        print(f"  -> {round_coverage(route_filter)}")
        _print_attribution(round_records(route_filter))
        return
    n_records, n_coverage, backlog, unfinished = publish_corpus(scope)
    rounds = sorted(r for r in ROUTES if round_records(r).is_file())
    print(f"PASS: published corpus: {n_records} records, {n_coverage} "
          f"page-coverage rows from {len(rounds)} consolidated rounds")
    _print_scope_state(backlog, unfinished)
    print(f"  -> {qualifier_backlog_ledger()}")
    print(f"  -> {published_records()}")
    print(f"  -> {published_coverage()}")
    print(f"  rounds: {', '.join(rounds)}")
    _print_attribution(published_records())


def _prior_publication(path: Path) -> tuple[Path | None, list[dict[str, str]]]:
    """The archived copy of this file's last publication, read as stage 15 reads it.

    The release gate finds it through the receipt ledger, which records the hash
    of every artifact a stage read or wrote and keeps the bytes under that hash.
    Calling the gate's own reader is what makes the restore and the check agree:
    a row this returns is exactly a row the gate would compare. The import sits
    inside the function because the release module imports this one.
    """

    from src.pipeline import publish_review_release as release

    archived = release.previous_object(path)
    if archived is None:
        return None, []
    with archived.open("r", encoding="utf-8-sig", newline="") as handle:
        return archived, list(csv.DictReader(handle))


def restore_attribution(route: str) -> tuple[Counter[str], Path | None]:
    """Put back the model a round published before a republish re-derived it.

    Republishing a route used to re-derive `extractor_model` for every candidate
    file it saw, so documents the republishing lane never opened changed hands.
    A physical key whose core fields are unchanged is the same printed cell read
    by the same lane, so its prior model is the true one and is written back. A
    key whose core fields changed was read again and keeps its current model.
    """

    policy = matrices.resolve(ATTRIBUTION, "restore_attribution")
    if policy != "prior_model_on_unchanged_key":
        raise ContractFailure(
            f"{ATTRIBUTION}.csv names an unsupported restore_attribution {policy!r}"
        )
    path = round_records(route)
    if not path.is_file():
        raise ContractFailure(f"Round {route} has no published records file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    if header != list(ROUND_RECORD_COLUMNS):
        raise ContractFailure(
            f"{path.name}: header is not the current round contract; republish it first"
        )
    core = [column for column in ROUND_RECORD_COLUMNS if column != "extractor_model"]
    archived, prior_rows = _prior_publication(path)
    if archived is None:
        raise ContractFailure(
            f"Round {route} has no archived prior publication in the receipt ledger"
        )

    from src.pipeline import publish_review_release as release

    prior = release._attribution_index(prior_rows, core)
    current = release._attribution_index(rows, core)
    restorable = {
        key: prior[key][1]
        for key, (fields, model) in current.items()
        if key in prior and prior[key][0] == fields and prior[key][1] != model
    }
    restored: Counter[str] = Counter()
    for row in rows:
        model = restorable.get(_attribution_key(row, ATTRIBUTION_RECORD_KEY))
        if model and model != row.get("extractor_model", ""):
            row["extractor_model"] = model
            restored[row.get("file_id", "")] += 1
    if restored:
        write_csv(path, ROUND_RECORD_COLUMNS, rows)
    return restored, archived


def restore_attribution_command(route: str) -> None:
    restored, archived = restore_attribution(route)
    print(
        f"PASS: restored {sum(restored.values())} row(s) on {route} from "
        f"{archived.name if archived else 'no archive'}"
    )
    for document, count in sorted(restored.items()):
        print(f"  {document:<12}{count:>8} records")
    if not restored:
        print("  every unchanged key already publishes under its prior model")
    else:
        print(f"  -> {round_records(route)}")


def _print_attribution(path: Path) -> None:
    """Which models stand behind the rows in a published file."""
    attribution = Counter(
        row["extractor_model"]
        for row in read_strict_csv(path, ROUND_RECORD_COLUMNS)
    )
    for model, n in attribution.most_common():
        print(f"  {model:<40}{n:>8} records")
    if attribution.get(UNDECLARED_MODEL):
        print("  Run `claim` before a run so its rows carry the model that wrote them.")


def _model_for_final(row: Mapping[str, str], claims: Mapping[str, Mapping[str, str]]) -> str:
    """Which model produced a final row, from the agents credited on it.

    A final row carries `source_agents` such as `A`, `B`, `A+B`, or
    `ADJUDICATOR` where the adjudicator added the row itself. Every credited
    party is named, because two models agreeing on a value and one model
    asserting it alone are different evidence.
    """
    credited = row.get("source_agents", "").split("+")
    models: list[str] = []
    for slot in ("A", "B"):
        if slot in credited:
            models.append(claims.get(slot, {}).get("extractor_model", UNDECLARED_MODEL))
    if "ADJUDICATOR" in credited:
        models.extend(_adjudicator_models(claims))
    seen = list(dict.fromkeys(models))
    return "+".join(seen) if seen else UNDECLARED_MODEL


def _adjudicator_models(claims: Mapping[str, Mapping[str, str]]) -> list[str]:
    found = [claims[j]["extractor_model"] for j in ADJUDICATOR_AGENTS
             if claims.get(j, {}).get("extractor_model")]
    return list(dict.fromkeys(found)) or [UNDECLARED_MODEL]


def _model_for_final_coverage(
    row: Mapping[str, str], claims: Mapping[str, Mapping[str, str]]
) -> str:
    """A final page-coverage row is a decision over both candidates.

    Its `agent_role` is `ADJUDICATED`, which names no model, so credit every
    model that worked the route: both extractors and whichever adjudicator
    settled it.
    """
    models = [claims.get(slot, {}).get("extractor_model", UNDECLARED_MODEL)
              for slot in CANDIDATE_AGENTS]
    models.extend(_adjudicator_models(claims))
    seen = [m for m in dict.fromkeys(models) if m != UNDECLARED_MODEL]
    return "+".join(seen) if seen else UNDECLARED_MODEL


def bench_command(route: str) -> None:
    """Compare every extractor lane on one route, document by document."""
    claims = read_claims(route)
    work = worklist_for_scope(route, "active")

    print(f"=== bench: {route}\n")
    header = (f"{'document':<9}{'lane':<5}{'model':<24}{'rows':>7}{'bad':>6}"
              f"{'pages':>7}{'quotes':>8}{'valid':>7}{'audit':>7}")
    print(header)
    print("-" * len(header))
    totals: dict[str, dict[str, int]] = {}
    for row in work:
        file_id = row["file_id"]
        pages = int(float(row["page_count"]))
        for lane in EXTRACTOR_AGENTS:
            record_path, _ = candidate_paths(route, file_id, lane)
            if not record_path.is_file():
                continue
            with record_path.open(encoding="utf-8-sig", newline="") as handle:
                raw = list(csv.reader(handle))
            if len(raw) < 2:
                continue
            width = len(raw[0])
            good = [r for r in raw[1:] if len(r) == width]
            malformed = len(raw) - 1 - len(good)
            index = {c: i for i, c in enumerate(raw[0])}
            cited = {r[index["source_page"]] for r in good}
            try:
                _, _, errors = validate_candidate_data(route, file_id, lane)
            except ContractFailure as exc:
                errors = [str(exc)]
            quote_fail = sum(1 for e in errors if "evidence_quote" in e)
            try:
                audit_file_command(
                    route, file_id, lane, quiet=True, require_images=False
                )
                audited = "PASS"
            except ContractFailure:
                audited = "fail"
            model = claims.get(lane, {}).get("extractor_model", UNDECLARED_MODEL)
            print(f"{file_id:<9}{lane:<5}{model[:23]:<24}{len(good):>7}{malformed:>6}"
                  f"{len(cited):>3}/{pages:<3}{quote_fail:>8}"
                  f"{('PASS' if not errors else 'fail'):>7}{audited:>7}")
            bucket = totals.setdefault(lane, {"rows": 0, "bad": 0, "quote": 0,
                                              "valid": 0, "audit": 0, "docs": 0})
            bucket["rows"] += len(good)
            bucket["bad"] += malformed
            bucket["quote"] += quote_fail
            bucket["valid"] += not errors
            bucket["audit"] += audited == "PASS"
            bucket["docs"] += 1

    if not totals:
        print("  no lane has written rows yet")
        return
    print(f"\n{'lane':<5}{'model':<24}{'rows':>7}{'malformed':>11}"
          f"{'quote fails':>13}{'valid':>8}{'audited':>9}")
    print("-" * 77)
    for lane in EXTRACTOR_AGENTS:
        t = totals.get(lane)
        if not t:
            continue
        model = claims.get(lane, {}).get("extractor_model", UNDECLARED_MODEL)
        multiplier = float(matrices.resolve(BENCHMARK_MALFORMED_SHARE, "percent_multiplier"))
        floor = int(matrices.resolve(BENCHMARK_MALFORMED_SHARE, "denominator_floor"))
        places = int(matrices.resolve(BENCHMARK_MALFORMED_SHARE, "decimal_places"))
        share_value = multiplier * t["bad"] / max(t["rows"] + t["bad"], floor)
        share = f"{share_value:.{places}f}%"
        print(f"{lane:<5}{model[:23]:<24}{t['rows']:>7}{t['bad']:>7} {share:<4}"
              f"{t['quote']:>12}{t['valid']:>5}/{t['docs']:<3}{t['audit']:>6}/{t['docs']:<3}")
    print("\nmalformed = rows one cell short or long. `repair-shifted` restores a "
          "dropped cell where the\nother lane's row for the same printed cell fixes "
          "its place; what it cannot place unambiguously\nis quarantined, never guessed.")


def model_report_command() -> None:
    """Rank the models actually doing the work, on the defects that matter.

    Every measure here is one we have had to find by hand at least once: rows
    that never reach the contract's shape, quotes that are not on the page, and
    documents abandoned partway.
    """
    rows: list[dict[str, object]] = []
    for route in ROUTES:
        claims = read_claims(route)
        for worklist in worklist_for_scope(route, "active"):
            file_id = worklist["file_id"]
            for agent in EXTRACTOR_AGENTS:
                record_path, _ = candidate_paths(route, file_id, agent)
                if not record_path.is_file():
                    continue
                with record_path.open(encoding="utf-8-sig", newline="") as handle:
                    raw = list(csv.reader(handle))
                if len(raw) < 2:
                    continue
                width = len(raw[0])
                malformed = sum(1 for r in raw[1:] if len(r) != width)
                model = claims.get(agent, {}).get("extractor_model", UNDECLARED_MODEL)
                try:
                    _, _, errors = validate_candidate_data(route, file_id, agent)
                except ContractFailure as exc:
                    errors = [str(exc)]
                try:
                    audit_ok = True
                    audit_file_command(
                        route, file_id, agent, quiet=True, require_images=False
                    )
                except ContractFailure:
                    audit_ok = False
                rows.append({
                    "model": model, "route": route, "file_id": file_id,
                    "agent": agent, "rows": len(raw) - 1, "malformed": malformed,
                    "quote_failures": sum(1 for e in errors if "evidence_quote is absent" in e),
                    "errors": len(errors), "valid": not errors, "audited": audit_ok,
                })
    if not rows:
        print("No candidate files carry rows yet.")
        return
    by_model: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_model[str(row["model"])].append(row)
    header = (f"{'model':<28}{'docs':>6}{'rows':>8}{'malformed':>11}"
              f"{'quote fails':>13}{'valid':>8}{'audited':>9}")
    print(header)
    print("-" * len(header))
    for model in sorted(by_model, key=lambda m: -sum(int(r["rows"]) for r in by_model[m])):
        rs = by_model[model]
        n = len(rs)
        print(f"{model:<28}{n:>6}{sum(int(r['rows']) for r in rs):>8}"
              f"{sum(int(r['malformed']) for r in rs):>11}"
              f"{sum(int(r['quote_failures']) for r in rs):>13}"
              f"{sum(1 for r in rs if r['valid']):>4}/{n:<3}"
              f"{sum(1 for r in rs if r['audited']):>5}/{n:<3}")
    write_csv(model_ledger().with_name("model-scorecard.csv"),
              ("model", "route", "file_id", "agent", "rows", "malformed",
               "quote_failures", "errors", "valid", "audited"), rows)
    print(f"\nPASS: wrote {len(rows)} candidate rows -> "
          f"{model_ledger().with_name('model-scorecard.csv')}")


def verify_contract_command() -> None:
    errors = verify_generated()
    routing = read_simple_csv(ROUTING_PATH)
    scope = read_simple_csv(SCOPE_PATH)
    expected = corpus_size()
    if len(routing) != expected:
        errors.append(f"routing registry contains {len(routing)} rows, expected {expected}")
    if len(scope) != expected:
        errors.append(f"dispatch scope contains {len(scope)} rows, expected {expected}")
    if set(row["file_id"] for row in routing) != set(row["file_id"] for row in scope):
        errors.append("routing and dispatch-scope file_id sets differ")
    if errors:
        raise ContractFailure("Contract verification failed:\n- " + "\n- ".join(errors))
    print(
        f"PASS: contract {CONTRACT_VERSION}; routing={expected}; families={len(FAMILY_CONTRACTS)}; prompts={len(ROUTES) * 5}"
    )


def migrate_contract_command() -> None:
    """Rewrite every working record CSV to the current record field list.

    A contract version appends columns; the files already written keep their
    older shape and load with those columns blank. This makes the blanks
    physical: each candidate, final, and resolution CSV is reparsed under its
    own known header and rewritten under the current one, every existing cell
    byte-identical and every appended cell empty. Coverage files carry no
    record columns and are untouched. Deterministic and idempotent; content is
    asserted unchanged before anything is written.
    """

    rewritten = skipped = 0
    for route in ROUTES:
        route_dir = WORKING_ROOT / route
        if not route_dir.is_dir():
            continue
        for folder in sorted(path for path in route_dir.iterdir() if path.is_dir()):
            targets = [
                (folder / f"records-{agent.lower()}.csv", RECORD_COLUMNS)
                for agent in EXTRACTOR_AGENTS
            ]
            targets.append((folder / "records-final.csv", RECORD_COLUMNS))
            targets.append((folder / "resolution.csv", RESOLUTION_COLUMNS))
            for path, columns in targets:
                if not path.is_file():
                    continue
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    on_disk = list(csv.reader(handle))
                if on_disk and on_disk[0] == list(columns):
                    skipped += 1
                    continue
                rows = read_strict_csv(path, columns)
                for row, source in zip(rows, on_disk[1:], strict=True):
                    kept = [row[column] for column in on_disk[0]]
                    if kept != source:
                        raise ContractFailure(
                            f"{path}: migration would alter row {row['__line_number']}"
                        )
                stat = path.stat()
                write_csv(path, columns, rows)
                # Attribution binds a candidate to the claim ledger through the
                # file's mtime; a mechanical header rewrite is not a write of
                # the rows, so the timestamp is put back.
                os.utime(path, (stat.st_atime, stat.st_mtime))
                rewritten += 1
    print(
        f"PASS: migrated {rewritten} working record file(s) to contract "
        f"{CONTRACT_VERSION}; {skipped} already current. Regenerate the derived "
        "files next: combine_extracted_raw, then publish, then the release."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("verify-contract")

    subparsers.add_parser(
        "migrate-contract",
        help="rewrite working record CSVs to the current field list, appended columns blank",
    )

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--route", choices=tuple(ROUTES))
    prepare.add_argument(
        "--scope", choices=("active", "deferred", "reference", "full"), default="active"
    )
    prepare.add_argument("--bench", action="store_true",
                         help="also create the C and D comparison lanes")

    images = subparsers.add_parser("require-images")
    images.add_argument("--route", required=True, choices=tuple(ROUTES))
    images.add_argument("--file", required=True)

    candidate = subparsers.add_parser("validate-candidate")
    candidate.add_argument("--route", required=True, choices=tuple(ROUTES))
    candidate.add_argument("--file", required=True)
    candidate.add_argument("--agent", required=True, choices=EXTRACTOR_AGENTS)
    candidate.add_argument("--through-page", type=int, default=None,
                           help="validate only what is written up to this page")

    claim = subparsers.add_parser("claim")
    claim.add_argument("--route", required=True, choices=(*ROUTES, "all"),
                       help="one route, or 'all' to claim every route at once")
    claim.add_argument("--agent", required=True, choices=CLAIMABLE_AGENTS)
    claim.add_argument("--model", required=True,
                       help="the model actually running, e.g. claude-opus-5")
    claim.add_argument("--by", default="", help="optional operator or session note")

    subparsers.add_parser("model-report")

    bench = subparsers.add_parser("bench")
    bench.add_argument("--route", required=True, choices=tuple(ROUTES))

    audit = subparsers.add_parser("audit-file")
    audit.add_argument("--route", required=True, choices=tuple(ROUTES))
    audit.add_argument("--file", required=True)
    audit.add_argument("--agent", required=True, choices=EXTRACTOR_AGENTS)

    lane = subparsers.add_parser(
        "lane-check",
        help="one lane's assigned documents and whether every one of them is finished")
    lane.add_argument("--route", required=True, choices=tuple(ROUTES))
    lane.add_argument("--agent", required=True, choices=EXTRACTOR_AGENTS)
    lane.add_argument(
        "--scope", choices=("active", "deferred", "reference", "full"), default="active"
    )

    repair = subparsers.add_parser(
        "repair-shifted",
        help="restore the dropped cell in one-cell-short rows using the other lane")
    repair.add_argument("--route", required=True, choices=tuple(ROUTES))
    repair.add_argument("--file", required=True)
    repair.add_argument("--agent", required=True, choices=CANDIDATE_AGENTS)

    fmt = subparsers.add_parser(
        "repair-value-format",
        help="restore a printed %% or x that a row's own evidence_quote proves it dropped")
    fmt.add_argument("--route", required=True, choices=tuple(ROUTES))
    fmt.add_argument("--file", required=True)
    fmt.add_argument("--agent", required=True, choices=EXTRACTOR_AGENTS)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--route", required=True, choices=tuple(ROUTES))
    compare.add_argument("--file", required=True)

    build_final = subparsers.add_parser("build-final")
    build_final.add_argument("--route", required=True, choices=tuple(ROUTES))
    build_final.add_argument("--file", required=True)

    validate_final = subparsers.add_parser("validate-final")
    validate_final.add_argument("--route", required=True, choices=tuple(ROUTES))
    validate_final.add_argument("--file", required=True)

    status = subparsers.add_parser("status")
    status.add_argument(
        "--scope", choices=("active", "deferred", "reference", "full"), default="active"
    )

    publish = subparsers.add_parser("publish")
    publish.add_argument(
        "--scope", choices=("active", "deferred", "reference", "full"), default="active"
    )
    publish.add_argument(
        "--route", choices=tuple(ROUTES), default=None,
        help="publish one route only; the published files are rewritten whole")

    restore = subparsers.add_parser(
        "restore-attribution",
        help="put back the model a round published before a republish re-derived it")
    restore.add_argument("--route", required=True, choices=tuple(ROUTES))
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify-contract":
            verify_contract_command()
        elif args.command == "migrate-contract":
            migrate_contract_command()
        elif args.command == "require-images":
            require_images_command(args.route, args.file)
        elif args.command == "prepare":
            prepare_command(args.route, args.scope, args.bench)
        elif args.command == "validate-candidate":
            validate_candidate_command(args.route, args.file, args.agent,
                                       args.through_page)
        elif args.command == "claim":
            claim_command(args.route, args.agent, args.model, args.by)
        elif args.command == "bench":
            bench_command(args.route)
        elif args.command == "model-report":
            model_report_command()
        elif args.command == "audit-file":
            audit_file_command(args.route, args.file, args.agent)
        elif args.command == "lane-check":
            lane_check_command(args.route, args.agent, args.scope)
        elif args.command == "repair-shifted":
            repair_shifted_command(args.route, args.file, args.agent)
        elif args.command == "repair-value-format":
            repair_value_format_command(args.route, args.file, args.agent)
        elif args.command == "compare":
            compare_command(args.route, args.file)
        elif args.command == "build-final":
            build_final_command(args.route, args.file)
        elif args.command == "validate-final":
            validate_final_command(args.route, args.file)
        elif args.command == "status":
            status_command(args.scope)
        elif args.command == "publish":
            publish_command(args.scope, args.route)
        elif args.command == "restore-attribution":
            restore_attribution_command(args.route)
        else:
            raise ContractFailure(f"Unsupported command: {args.command}")
    except ContractFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
