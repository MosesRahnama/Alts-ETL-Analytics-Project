"""Name normalization for the adjudicated wide-row extraction corpus.

Every entity name printed in an extracted document goes through the same
conversion matrices the fund-mapping round already uses, so one entity has one
standardized name and one ID no matter which document or round found it.

    harvest   append new printed names from data/extracted/rounds/*-records.csv
              into data/normalization/*-names-matrix.csv,
              never touching a decided row. Writes a near-duplicate report to
              help the normalizer land variants on one standard.

    autofill  settle the names that carry no judgement: a printed name that is
              the only variant of itself in the whole corpus becomes its own
              standard, marked `auto` so a reviewer can tell it apart from a
              decision a person made. Anything with a sibling variant is left
              for the normalizer.

    check     enforce the matrix invariants, above all: one standardized name
              per entity and one entity per standardized name. Fails closed.

    managers  queue every settled fund that carries no manager into
              web-manager-names.csv for the two-agent web round, and report
              how much of the fund universe already has a general partner.

The standardization decisions themselves are made by hand in the matrix, per
instructions/02-fund-mapping/01-NAME-NORMALIZER.md. This module only harvests,
settles the unambiguous cases, and checks. `src.flatten.flatten_extracted`
reads the matrices and stamps the result onto the relational tables; a name the
matrix has yet to decide lands there as an unresolved alias instead of blocking
the build.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATRIX_DIR = PROJECT_ROOT / "data" / "normalization"
FUND_MATRIX = MATRIX_DIR / "fund-names-matrix.csv"
MANAGER_MATRIX = MATRIX_DIR / "manager-names-matrix.csv"
LP_MATRIX = MATRIX_DIR / "lp-names-matrix.csv"
PLAN_MATRIX = MATRIX_DIR / "plan-names-matrix.csv"
COMPANY_MATRIX = MATRIX_DIR / "company-names-matrix.csv"
ROUNDS_DIR = PROJECT_ROOT / "data" / "extracted" / "rounds"
NEAR_DUPLICATES = MATRIX_DIR / "name-near-duplicates.csv"
WEB_MANAGER_NAMES = MATRIX_DIR / "web-manager-names.csv"

WEB_MANAGER_HEADER = [
    "standardized_fund_name",
    "a_manager_name",
    "a_source",
    "b_manager_name",
    "b_source",
    "final_manager_name",
    "final_source",
]

DECIDED = {"decided", "auto"}

# Which printed subject names name which kind of entity. A subject_type absent
# here prints the scope of a fact instead of an institution: an asset class, a
# benchmark, a peer group, a fee scope, a document. Those keep their printed
# name as an alias and never enter a matrix.
SUBJECT_KIND = {
    "fund": "fund",
    "manager": "manager",
    "service_provider": "manager",
    "investor": "lp",
    "foundation": "plan",
    "reporting_entity": "plan",
    "investment": "company",
}

# The wide contract also carries dedicated name columns beside subject_name.
COLUMN_KIND = {
    "manager_name": "manager",
    "investor_name": "lp",
}

KINDS = {
    "fund": (FUND_MATRIX, "fund_name_raw", "standardized_fund_name", "fund_id"),
    "manager": (MANAGER_MATRIX, "manager_name_raw", "standardized_manager_name", "manager_id"),
    "lp": (LP_MATRIX, "lp_name_raw", "standardized_lp_name", "lp_id"),
    "plan": (PLAN_MATRIX, "plan_name_raw", "standardized_plan_name", "plan_id"),
    "company": (COMPANY_MATRIX, "company_name_raw", "standardized_company_name", "company_id"),
}

# fund_family groups a sponsor's whole series onto one name, so the manager
# round searches once per family instead of once per vehicle. Funds only.
FAMILY_COLUMN = "fund_family"

MATRIX_TAIL = [
    "decision_status",
    "seen_in_agents",
    "source_files",
    "a_count",
    "b_count",
    "merge_note",
]

MATRIX_HEADER = {
    kind: (
        [raw, std, FAMILY_COLUMN, entity_id, *MATRIX_TAIL]
        if kind == "fund"
        else [raw, std, entity_id, *MATRIX_TAIL]
    )
    for kind, (_path, raw, std, entity_id) in KINDS.items()
}

# Suffix/filler words that do not distinguish two vehicles. Single letters are
# deliberately NOT noise: "Fund II-A" and "Class A" are different vehicles from
# "Fund II", and collapsing them would hide a real split.
LEGAL_NOISE = re.compile(
    r"\b(l\.?\s?p|llc|llp|inc|ltd|limited|corp|corporation|company|co|trust|the|of)\b"
)

# A printed name the extractors use for a withheld value carries no identity.
NON_NAMES = {"REDACTED", "NOT_DISCLOSED", "NOT_PRINTED", "N/A", "NA", "-", "--"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in header})


def load_records() -> list[dict[str, str]]:
    """Read every published round. Rounds are the adjudicated publication stage."""

    paths = sorted(ROUNDS_DIR.glob("*-records.csv"))
    if not paths:
        raise SystemExit(
            f"No published rounds to normalize in {ROUNDS_DIR}. "
            "Run `csv_workflow publish --route <route>` first."
        )
    rows: list[dict[str, str]] = []
    for path in paths:
        rows.extend(read_csv(path))
    return rows


def printed_names(records: list[dict[str, str]]) -> dict[str, dict[str, dict]]:
    """Return every printed institution name, by kind, with where it was seen."""

    found: dict[str, dict[str, dict]] = {kind: {} for kind in KINDS}

    def note(kind: str, value: str, record: dict[str, str]) -> None:
        name = (value or "").strip()
        if not name or name.upper() in NON_NAMES:
            return
        entry = found[kind].setdefault(name, {"files": set(), "routes": set(), "count": 0})
        entry["files"].add(record.get("file_id", ""))
        entry["routes"].add(record.get("route", ""))
        entry["count"] += 1

    for record in records:
        kind = SUBJECT_KIND.get(record.get("subject_type", ""))
        if kind:
            note(kind, record.get("subject_name", ""), record)
        for column, column_kind in COLUMN_KIND.items():
            note(column_kind, record.get(column, ""), record)
    return found


def match_key(value: str) -> str:
    """Aggressive key used only to SUGGEST that two names may be one entity.

    Never merges anything on its own: it drives the near-duplicate report the
    human normalizer reads. Series numbers and roman numerals survive, because
    Fund III and Fund IV are different funds.
    """
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = LEGAL_NOISE.sub(" ", text)
    return " ".join(text.split())


def harvest() -> int:
    records = load_records()
    found = printed_names(records)
    total_new = 0
    for kind, (path, raw_col, std_col, id_col) in KINDS.items():
        existing = read_csv(path)
        known = {(row.get(raw_col) or "").strip() for row in existing}
        new_rows = []
        for raw in sorted(found[kind], key=str.casefold):
            if raw in known:
                continue
            entry = found[kind][raw]
            new_rows.append({
                raw_col: raw,
                std_col: "",
                id_col: "",
                "decision_status": "",
                "seen_in_agents": ";".join(sorted(value for value in entry["routes"] if value)),
                "source_files": ";".join(sorted(value for value in entry["files"] if value)),
                "a_count": str(entry["count"]),
                "b_count": "0",
                "merge_note": "",
            })
        if new_rows or not path.is_file():
            combined = existing + new_rows
            combined.sort(key=lambda row: (row.get(raw_col) or "").casefold())
            write_csv(path, MATRIX_HEADER[kind], combined)
        total_new += len(new_rows)
        print(
            f"{kind}: {len(found[kind])} distinct printed name(s), "
            f"{len(new_rows)} new row(s) -> {path.name}"
        )
    write_near_duplicate_report()
    print(
        f"PASS: harvested {total_new} new raw name(s). Settle the plain ones with "
        "`autofill`, then decide the rest per "
        "instructions/02-fund-mapping/01-NAME-NORMALIZER.md"
    )
    return 0


def autofill() -> int:
    """Settle the printed names that carry no judgement.

    A raw name whose match key is unique across its whole matrix has no sibling
    variant to weigh it against, so its standard is itself. That is a definition
    and not a decision, and the row is marked `auto` to say so. A name sharing a
    match key with any other row is left undecided for the normalizer, because
    choosing which variant becomes the standard is the judgement this
    module refuses to make.
    """

    filled = 0
    for kind, (path, raw_col, std_col, id_col) in KINDS.items():
        rows = read_csv(path)
        if not rows:
            continue
        by_key: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            raw = (row.get(raw_col) or "").strip()
            if raw:
                by_key[match_key(raw)].append(row)
        changed = 0
        for group in by_key.values():
            if len(group) != 1:
                continue
            row = group[0]
            if (row.get("decision_status") or "").strip():
                continue
            row[std_col] = (row.get(raw_col) or "").strip()
            row["decision_status"] = "auto"
            row["merge_note"] = (
                "auto: only printed variant of this name in the corpus"
            )
            changed += 1
        if changed:
            write_csv(path, MATRIX_HEADER[kind], rows)
        undecided = sum(
            1 for row in rows if not (row.get("decision_status") or "").strip()
        )
        filled += changed
        print(f"{kind}: {changed} settled as `auto`, {undecided} left for the normalizer")
    print(
        f"PASS: {filled} name(s) settled mechanically. "
        "Run `check`, then decide what remains."
    )
    return 0


def write_near_duplicate_report() -> None:
    """Cluster raw names that look like one entity so a person can rule on them."""
    rows_out = []
    for kind, (path, raw_col, std_col, _id) in KINDS.items():
        rows = read_csv(path)
        by_key: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            raw = (row.get(raw_col) or "").strip()
            if raw:
                by_key[match_key(raw)].append(row)
        for key, group in sorted(by_key.items()):
            if len(group) < 2:
                continue
            standards = {
                (row.get(std_col) or "").strip()
                for row in group
                if (row.get(std_col) or "").strip()
            }
            undecided = [
                row
                for row in group
                if (row.get("decision_status") or "").strip() not in DECIDED
            ]
            if len(standards) <= 1 and not undecided:
                continue  # already one agreed standard, nothing to review
            rows_out.append({
                "kind": kind,
                "match_key": key,
                "raw_variants": " | ".join(
                    sorted((row.get(raw_col) or "").strip() for row in group)
                ),
                "existing_standards": " | ".join(sorted(standards)) or "(none yet)",
                "undecided_count": str(len(undecided)),
                "flag": "MULTIPLE_STANDARDS" if len(standards) > 1 else "NEEDS_DECISION",
            })
    write_csv(
        NEAR_DUPLICATES,
        ["kind", "match_key", "raw_variants", "existing_standards", "undecided_count", "flag"],
        rows_out,
    )
    multi = sum(1 for row in rows_out if row["flag"] == "MULTIPLE_STANDARDS")
    print(
        f"near-duplicate report: {len(rows_out)} cluster(s), "
        f"{multi} already split across standards -> {NEAR_DUPLICATES.name}"
    )


def check() -> int:
    """Enforce the matrix invariants. One entity, one standardized name, one ID."""
    errors: list[str] = []
    warnings: list[str] = []
    for kind, (path, raw_col, std_col, id_col) in KINDS.items():
        rows = read_csv(path)
        if not rows:
            continue
        seen_raw: dict[str, int] = {}
        std_to_ids: dict[str, set[str]] = defaultdict(set)
        id_to_std: dict[str, set[str]] = defaultdict(set)
        raw_values = {(row.get(raw_col) or "").strip() for row in rows}
        for index, row in enumerate(rows, start=2):
            raw = (row.get(raw_col) or "").strip()
            std = (row.get(std_col) or "").strip()
            entity_id = (row.get(id_col) or "").strip()
            status = (row.get("decision_status") or "").strip()
            if not raw:
                errors.append(f"{path.name}:{index}: blank {raw_col}")
                continue
            if raw in seen_raw:
                errors.append(
                    f"{path.name}:{index}: duplicate {raw_col} {raw!r} "
                    f"(first at line {seen_raw[raw]})"
                )
            seen_raw[raw] = index
            if status not in DECIDED:
                continue
            if not std:
                errors.append(f"{path.name}:{index}: settled row has no {std_col}")
                continue
            # Rule 2 of the normalizer brief: the standard must be an observed variant.
            if std not in raw_values:
                errors.append(
                    f"{path.name}:{index}: standard {std!r} never appears as a printed {raw_col}"
                )
            std_to_ids[std].add(entity_id)
            if entity_id:
                id_to_std[entity_id].add(std)
        # THE invariant: one standardized name <-> one entity.
        for std, ids in sorted(std_to_ids.items()):
            real = {value for value in ids if value}
            if len(real) > 1:
                errors.append(
                    f"{path.name}: standardized name {std!r} carries {len(real)} IDs: {sorted(real)}"
                )
        for entity_id, stds in sorted(id_to_std.items()):
            if len(stds) > 1:
                errors.append(
                    f"{path.name}: {entity_id} carries {len(stds)} standardized names: {sorted(stds)}"
                )
        # Soft signal: same entity possibly split across two standards. A cluster
        # a human has already ruled on stays quiet: write `distinct` in merge_note
        # (for genuinely different vehicles, e.g. Fund II vs Fund II-A).
        reviewed = {
            (row.get(std_col) or "").strip()
            for row in rows
            if "distinct" in (row.get("merge_note") or "").casefold()
        }
        by_key: dict[str, set[str]] = defaultdict(set)
        for std in std_to_ids:
            by_key[match_key(std)].add(std)
        for key, stds in sorted(by_key.items()):
            if len(stds) > 1 and not (stds & reviewed):
                warnings.append(
                    f"{path.name}: possible duplicate standards for one entity: {sorted(stds)}"
                )
    for item in warnings[:40]:
        print("WARN: " + item)
    if len(warnings) > 40:
        print(f"WARN: {len(warnings) - 40} further near-duplicate warning(s) in the report")
    if errors:
        print(f"FAIL: {len(errors)} matrix defect(s)")
        for item in errors[:60]:
            print("  " + item)
        return 1
    print(f"PASS: matrices consistent ({len(warnings)} near-duplicate warning(s) to review)")
    return 0


def settled_fund_standards() -> list[str]:
    """Every standardized fund name the matrix has settled, in printed order."""

    path, raw_col, std_col, _id = KINDS["fund"]
    names: dict[str, None] = {}
    for row in read_csv(path):
        if (row.get("decision_status") or "").strip().lower() not in DECIDED:
            continue
        standard = (row.get(std_col) or "").strip()
        if standard:
            names[standard] = None
    return sorted(names, key=str.casefold)


def managers() -> int:
    """Queue the funds with no general partner, and report the coverage gap.

    A fund reaches the web round once. A row already carrying a blank
    `final_manager_name` was attempted and produced no public match, so it keeps
    its row and its evidence instead of being queued again as if it were new.
    Rows for names removed from the settled fund universe are deleted here.
    """

    standards = settled_fund_standards()
    universe = set(standards)
    existing = read_csv(WEB_MANAGER_NAMES)
    before_prune = len(existing)
    existing = [
        row
        for row in existing
        if (row.get("standardized_fund_name") or "").strip() in universe
    ]
    removed = before_prune - len(existing)
    attempted = {(row.get("standardized_fund_name") or "").strip() for row in existing}
    queued = [name for name in standards if name not in attempted]
    if queued:
        existing.extend(
            {
                "standardized_fund_name": name,
                "a_manager_name": "",
                "a_source": "",
                "b_manager_name": "",
                "b_source": "",
                "final_manager_name": "",
                "final_source": "",
            }
            for name in queued
        )
    if queued or removed:
        existing.sort(
            key=lambda row: (row.get("standardized_fund_name") or "").casefold()
        )
        write_csv(WEB_MANAGER_NAMES, WEB_MANAGER_HEADER, existing)

    # The file now contains exactly one row per current standardized fund.
    in_scope = existing
    resolved = {
        (row.get("standardized_fund_name") or "").strip()
        for row in in_scope
        if (row.get("final_manager_name") or "").strip()
    }
    # A row the agents worked carries their evidence even when it names no firm.
    # A row that only holds a fund name has not been searched yet.
    without_manager = {
        (row.get("standardized_fund_name") or "").strip()
        for row in in_scope
        if not (row.get("final_manager_name") or "").strip()
    } - resolved
    searched_without_manager = sum(
        1
        for row in in_scope
        if (row.get("standardized_fund_name") or "").strip() in without_manager
        and (
            (row.get("a_source") or "").strip()
            or (row.get("b_source") or "").strip()
            or (row.get("final_source") or "").strip()
        )
    )
    waiting = len(without_manager) - searched_without_manager
    covered = len(resolved)
    total = len(standards)
    share = (covered / total * 100.0) if total else 0.0
    print(f"fund universe: {total} settled standardized fund name(s)")
    print(f"  with a general partner    : {covered} ({share:.1f}%)")
    print(f"  searched, no firm found   : {searched_without_manager}")
    print(f"  waiting for the web round : {waiting}")
    print(f"  queued by this run        : {len(queued)}")
    print(f"  obsolete rows removed     : {removed}")
    print(
        f"PASS: {len(existing)} row(s) in {WEB_MANAGER_NAMES.name}. "
        "Dispatch 02-WEB-MANAGER-A.md and 03-WEB-MANAGER-B.md, then "
        "04-WEB-MANAGER-ADJUDICATOR.md."
    )
    return 0





STANDARD_CONFLICTS = MATRIX_DIR / "standard-conflicts.csv"
WORKSHEET_DIR = MATRIX_DIR / "worksheets"

# The columns a normalizer may change. Everything else round-trips untouched.
WORKSHEET_EDITABLE = ("standardized_fund_name", FAMILY_COLUMN, "decision_status", "merge_note")


def export_worksheets(kind: str, size: int) -> int:
    """Split the matrix into fixed partitions so normalizers never share a file.

    Concurrent normalizers editing one CSV would overwrite each other, so each
    owns a slice on disk. The folder is regenerated whole by this command and
    consumed by `merge`; nothing accumulates in it between runs.
    """

    path, raw_col, _std, _id = KINDS[kind]
    rows = read_csv(path)
    if not rows:
        raise SystemExit(f"{path.name} holds no rows to split")
    for stale in WORKSHEET_DIR.glob("*.csv"):
        stale.unlink()
    header = MATRIX_HEADER[kind]
    total = len(rows)
    count = (total + size - 1) // size
    for index in range(count):
        slice_rows = rows[index * size : (index + 1) * size]
        target = WORKSHEET_DIR / f"{kind}-part-{index + 1:02d}.csv"
        write_csv(target, header, slice_rows)
        print(
            f"{target.name}: {len(slice_rows)} rows  "
            f"{(slice_rows[0].get(raw_col) or '')[:38]!r} .. "
            f"{(slice_rows[-1].get(raw_col) or '')[:38]!r}"
        )
    print(f"PASS: {count} worksheet(s) -> {WORKSHEET_DIR}")
    return 0


def merge_worksheets(kind: str) -> int:
    """Fold the filled worksheets back into the matrix, refusing any drift."""

    path, raw_col, std_col, _id = KINDS[kind]
    rows = read_csv(path)
    by_raw = {(row.get(raw_col) or "").strip(): row for row in rows}
    worksheets = sorted(WORKSHEET_DIR.glob(f"{kind}-part-*.csv"))
    if not worksheets:
        raise SystemExit(f"No worksheets to merge in {WORKSHEET_DIR}")
    changed = 0
    unknown: list[str] = []
    for worksheet in worksheets:
        for row in read_csv(worksheet):
            raw = (row.get(raw_col) or "").strip()
            target = by_raw.get(raw)
            if target is None:
                unknown.append(f"{worksheet.name}: {raw!r}")
                continue
            for column in WORKSHEET_EDITABLE:
                value = (row.get(column) or "").strip()
                if value != (target.get(column) or "").strip():
                    target[column] = value
                    changed += 1
    seen = {
        (row.get(raw_col) or "").strip()
        for worksheet in worksheets
        for row in read_csv(worksheet)
    }
    dropped = sorted(set(by_raw) - seen)
    if unknown or dropped:
        if unknown:
            print(f"FAIL: {len(unknown)} worksheet row(s) name a fund the matrix does not hold")
            for item in unknown[:20]:
                print("  " + item)
        if dropped:
            print(f"FAIL: {len(dropped)} matrix row(s) reach no worksheet")
            for item in dropped[:20]:
                print("  " + item)
        print("  A worksheet must never add, drop, or respell a printed name.")
        return 1
    rows.sort(key=lambda row: (row.get(raw_col) or "").casefold())
    write_csv(path, MATRIX_HEADER[kind], rows)
    print(f"PASS: {changed} cell(s) merged from {len(worksheets)} worksheet(s) -> {path.name}")
    return 0


MANAGER_QUEUE = MATRIX_DIR / "manager-queue.csv"

MANAGER_QUEUE_HEADER = [
    "lookup_key",
    "lookup_kind",
    "member_count",
    "member_funds",
    "a_manager_name",
    "a_source",
    "b_manager_name",
    "b_source",
    "final_manager_name",
    "final_source",
]


def build_manager_queue() -> int:
    """Turn the fund universe into one lookup per sponsor, not one per vehicle.

    A general partner runs a whole series, so a family of fourteen vehicles is
    one search. Funds the normalizer left without a family keep their own row.
    Existing settled managers seed the queue, so a rerun never asks again for
    something already answered.
    """

    path, _raw, std_col, _id = KINDS["fund"]
    families: dict[str, str] = {}
    for row in read_csv(path):
        if (row.get("decision_status") or "").strip().lower() not in DECIDED:
            continue
        standard = (row.get(std_col) or "").strip()
        if standard:
            families[standard] = (row.get(FAMILY_COLUMN) or "").strip()

    settled = {
        (row.get("standardized_fund_name") or "").strip(): row
        for row in read_csv(WEB_MANAGER_NAMES)
        if (row.get("final_manager_name") or "").strip()
    }

    units: dict[tuple[str, str], list[str]] = defaultdict(list)
    for standard, family in sorted(families.items(), key=lambda item: item[0].casefold()):
        key = (("family", family) if family else ("fund", standard))
        units[key].append(standard)

    previous = {
        (row.get("lookup_kind", ""), row.get("lookup_key", "")): row
        for row in read_csv(MANAGER_QUEUE)
    }
    rows: list[dict[str, str]] = []
    for (kind, key), members in sorted(units.items()):
        carried = previous.get((kind, key), {})
        known = next((settled[name] for name in members if name in settled), {})
        rows.append({
            "lookup_key": key,
            "lookup_kind": kind,
            "member_count": str(len(members)),
            "member_funds": " | ".join(members),
            "a_manager_name": carried.get("a_manager_name", ""),
            "a_source": carried.get("a_source", ""),
            "b_manager_name": carried.get("b_manager_name", ""),
            "b_source": carried.get("b_source", ""),
            "final_manager_name": carried.get("final_manager_name")
            or known.get("final_manager_name", ""),
            "final_source": carried.get("final_source") or known.get("final_source", ""),
        })
    write_csv(MANAGER_QUEUE, MANAGER_QUEUE_HEADER, rows)
    done = sum(1 for row in rows if row["final_manager_name"])
    covered = sum(int(row["member_count"]) for row in rows if row["final_manager_name"])
    print(f"lookup units      : {len(rows)}  ({sum(1 for r in rows if r['lookup_kind']=='family')} families,"
          f" {sum(1 for r in rows if r['lookup_kind']=='fund')} standalone funds)")
    print(f"  already settled : {done}  covering {covered} of {len(families)} funds")
    print(f"  to search       : {len(rows) - done}")
    print(f"funds per search  : {len(families) / max(len(rows), 1):.2f}")
    print(f"PASS: work order -> {MANAGER_QUEUE.name}")
    return 0


def propagate_managers() -> int:
    """Write each lookup's result back onto every fund it covers, found or not.

    A lookup that came back empty is a result too. Propagating only the wins
    leaves its funds completely blank, which is the same shape as a fund nobody
    has searched yet, and the coverage report then cannot tell "we looked and
    there is nothing published" from "this is still queued". So the searchers'
    evidence travels even when it names no firm; only `final_manager_name`
    stays empty.
    """

    queue = read_csv(MANAGER_QUEUE)
    if not queue:
        raise SystemExit(f"No work order at {MANAGER_QUEUE}. Run `manager-queue` first.")
    settled: dict[str, tuple[str, str, str]] = {}
    attempted: dict[str, tuple[dict[str, str], str, str]] = {}
    for row in queue:
        key = (row.get("lookup_key") or "").strip()
        members = [
            member.strip()
            for member in (row.get("member_funds") or "").split(" | ")
            if member.strip()
        ]
        manager = (row.get("final_manager_name") or "").strip()
        if manager:
            source = (row.get("final_source") or "").strip()
            for member in members:
                settled[member] = (manager, source, key)
            continue
        evidence = {
            column: (row.get(column) or "").strip()
            for column in ("a_manager_name", "a_source", "b_manager_name", "b_source")
        }
        final_source = (row.get("final_source") or "").strip()
        if not any(evidence.values()) and not final_source:
            continue
        for member in members:
            attempted[member] = (evidence, key, final_source)

    rows = read_csv(WEB_MANAGER_NAMES)
    by_fund = {(row.get("standardized_fund_name") or "").strip(): row for row in rows}

    def fund_row(fund: str) -> dict[str, str]:
        row = by_fund.get(fund)
        if row is None:
            row = {column: "" for column in WEB_MANAGER_HEADER}
            row["standardized_fund_name"] = fund
            rows.append(row)
            by_fund[fund] = row
        return row

    written = 0
    refreshed = 0
    for fund, (manager, source, key) in sorted(settled.items()):
        row = fund_row(fund)
        existing_manager = (row.get("final_manager_name") or "").strip()
        inherited_source = source if key == fund else f"FAMILY {key}: {source}"
        if existing_manager:
            if existing_manager == manager and row.get("final_source", "") != inherited_source:
                row["final_source"] = inherited_source
                refreshed += 1
            continue
        row["final_manager_name"] = manager
        row["final_source"] = inherited_source
        written += 1

    recorded = 0
    for fund, (evidence, key, final_source) in sorted(attempted.items()):
        row = fund_row(fund)
        if (row.get("final_manager_name") or "").strip():
            continue
        for column, value in evidence.items():
            if not value or (row.get(column) or "").strip():
                continue
            row[column] = value if key == fund else f"FAMILY {key}: {value}"
        if final_source and not (row.get("final_source") or "").strip():
            row["final_source"] = (
                final_source if key == fund else f"FAMILY {key}: {final_source}"
            )
        recorded += 1

    rows.sort(key=lambda row: (row.get("standardized_fund_name") or "").casefold())
    write_csv(WEB_MANAGER_NAMES, WEB_MANAGER_HEADER, rows)
    print(f"PASS: {written} fund(s) received a manager from the work order")
    print(f"      {refreshed} existing manager provenance row(s) refreshed")
    print(f"      {recorded} fund(s) recorded as searched with no firm found")
    return 0


def export_manager_slices(
    size: int, roles: tuple[str, ...] = ("a", "b"), retry: bool = False
) -> int:
    """Split the unsettled work order into per-agent files, A and B separately.

    Agent A and Agent B must not read each other, and neither may share a file
    with another agent, so each gets its own slice carrying only its own two
    columns beside the fund names it is searching.
    """

    queue = [
        row
        for row in read_csv(MANAGER_QUEUE)
        if not (row.get("final_manager_name") or "").strip()
    ]
    if "j" in roles:
        # Adjudication only has something to settle where a searcher spoke.
        queue = [
            row
            for row in queue
            if (row.get("a_manager_name") or "").strip()
            or (row.get("b_manager_name") or "").strip()
            or (row.get("a_source") or "").strip()
            or (row.get("b_source") or "").strip()
        ]
    if not queue:
        print("Every lookup already carries a manager; nothing to search.")
        return 0
    # Exporting the searcher slices starts a new round, so any adjudication
    # slice left from the previous one is stale by definition: it holds a
    # different set of lookups and its settlements are already merged.
    retire = ("a", "b", "j") if "j" not in roles else roles
    for role in retire:
        for stale in WORKSHEET_DIR.glob(f"manager-*-{role}.csv"):
            stale.unlink()
    context = ["lookup_key", "lookup_kind", "member_count", "member_funds"]
    total = len(queue)
    count = (total + size - 1) // size
    for index in range(count):
        chunk = queue[index * size : (index + 1) * size]
        for role in roles:
            if role == "j":
                # The adjudicator needs both searches in front of it and writes
                # the settlement; the searchers never see each other's columns.
                header = [
                    *context,
                    "a_manager_name", "a_source",
                    "b_manager_name", "b_source",
                    "final_manager_name", "final_source",
                ]
            else:
                header = [*context, f"{role}_manager_name", f"{role}_source"]
            target = WORKSHEET_DIR / f"manager-{index + 1:02d}-{role}.csv"
            written = chunk
            if retry:
                # A second pass starts from an empty answer, or the searcher
                # reads the previous lane's `unresolved` and stops. The queue
                # keeps the old evidence until `manager-merge` folds the new
                # answer over it, so nothing is destroyed by exporting.
                blank = [column for column in header if column not in context]
                written = [{**row, **{column: "" for column in blank}} for row in chunk]
            write_csv(target, header, written)
    print(f"PASS: {total} unsettled lookup(s) -> {count} slice(s) x 2 roles in {WORKSHEET_DIR}")
    for index in range(count):
        chunk = queue[index * size : (index + 1) * size]
        print(
            f"  slice {index + 1:02d}: {len(chunk)} lookups, "
            f"{sum(int(row['member_count']) for row in chunk)} funds"
        )
    return 0


def merge_manager_slices() -> int:
    """Fold both agents' slices back into the work order, refusing any drift."""

    queue = read_csv(MANAGER_QUEUE)
    by_key = {
        (row.get("lookup_kind", ""), row.get("lookup_key", "")): row for row in queue
    }
    slices = sorted(WORKSHEET_DIR.glob("manager-*.csv"))
    if not slices:
        raise SystemExit(f"No manager slices to merge in {WORKSHEET_DIR}")
    unknown: list[str] = []
    changed = 0
    for path in slices:
        role = path.stem.rsplit("-", 1)[-1]
        if role not in {"a", "b", "j"}:
            continue
        columns = (
            ("final_manager_name", "final_source")
            if role == "j"
            else (f"{role}_manager_name", f"{role}_source")
        )
        for row in read_csv(path):
            key = (row.get("lookup_kind", ""), row.get("lookup_key", ""))
            target = by_key.get(key)
            if target is None:
                unknown.append(f"{path.name}: {key[1]!r}")
                continue
            for column in columns:
                value = (row.get(column) or "").strip()
                if value and value != (target.get(column) or "").strip():
                    target[column] = value
                    changed += 1
    if unknown:
        print(f"FAIL: {len(unknown)} slice row(s) name a lookup the work order does not hold")
        for item in unknown[:20]:
            print("  " + item)
        return 1
    write_csv(MANAGER_QUEUE, MANAGER_QUEUE_HEADER, queue)
    filled_a = sum(1 for row in queue if (row.get("a_manager_name") or "").strip())
    filled_b = sum(1 for row in queue if (row.get("b_manager_name") or "").strip())
    settled = sum(1 for row in queue if (row.get("final_manager_name") or "").strip())
    agree = sum(
        1
        for row in queue
        if (row.get("a_manager_name") or "").strip()
        and (row.get("a_manager_name") or "").strip() == (row.get("b_manager_name") or "").strip()
    )
    print(
        f"PASS: {changed} cell(s) merged. A named {filled_a}, B named {filled_b}, "
        f"identical on {agree}, settled {settled} of {len(queue)} lookup(s)."
    )
    return 0


def auto_settle_manager_queue() -> int:
    """Settle the lookups where the blind pair needs no judgement call.

    Identical strings and clear spelling variants of the same firm are not a
    decision, the way an `auto` name standard is not a decision: there is
    nothing to weigh. A row where only one agent found a name is settled too,
    per the adjudicator brief's own rule that one-sided is not a reason to
    leave a manager blank, since the searching agent already screened out an
    LP, consultant, administrator, auditor, custodian, or placement agent.
    Genuine disagreements and rows neither agent could source are left for a
    person, and are what `manager-export --role adjudicate` queues.
    """

    rows = read_csv(MANAGER_QUEUE)
    settled = identical = variant = onesided = repaired = closed_without_manager = left = 0
    for row in rows:
        a_name = (row.get("a_manager_name") or "").strip()
        a_source = (row.get("a_source") or "").strip()
        b_name = (row.get("b_manager_name") or "").strip()
        b_source = (row.get("b_source") or "").strip()
        final_name = (row.get("final_manager_name") or "").strip()
        final_source = (row.get("final_source") or "").strip()
        if final_name:
            # Earlier versions selected the first non-empty source on a
            # one-sided match. When the other lane recorded a negative search,
            # that unsupported note could become the provenance for the manager
            # actually identified by its peer. Repair those rows deterministically.
            if "[AUTO: one-sided]" in final_source and bool(a_name) != bool(b_name):
                supporting_name, supporting_source = (
                    (a_name, a_source) if a_name else (b_name, b_source)
                )
                corrected = f"{supporting_source}  [AUTO: one-sided]"
                if final_name == supporting_name and final_source != corrected:
                    row["final_source"] = corrected
                    repaired += 1
            continue
        if a_name and b_name:
            if a_name == b_name:
                row["final_manager_name"] = a_name
                row["final_source"] = a_source or b_source
                row["final_source"] += "  [AUTO: identical]"
                identical += 1
            elif match_key(a_name) == match_key(b_name) or match_key(a_name) in match_key(
                b_name
            ) or match_key(b_name) in match_key(a_name):
                fuller = a_name if len(a_name) >= len(b_name) else b_name
                fuller_source = a_source if fuller == a_name else b_source
                row["final_manager_name"] = fuller
                row["final_source"] = f"{fuller_source}  [AUTO: {a_name} = {b_name}]"
                variant += 1
            else:
                left += 1
                continue
        elif a_name or b_name:
            name, source = (a_name, a_source) if a_name else (b_name, b_source)
            row["final_manager_name"] = name
            row["final_source"] = f"{source}  [AUTO: one-sided]"
            onesided += 1
        else:
            if final_source:
                closed_without_manager += 1
                continue
            left += 1
            continue
        settled += 1
    write_csv(MANAGER_QUEUE, MANAGER_QUEUE_HEADER, rows)
    print(f"auto-settled  : {settled}  (identical {identical}, same-firm variant {variant}, one-sided {onesided})")
    print(f"provenance repaired: {repaired}")
    print(f"closed without a published manager: {closed_without_manager}")
    print(f"left to adjudicate: {left}")
    print(f"PASS: {MANAGER_QUEUE.name} updated")
    return 0


# The briefs and the generated prompts are instructions; the matrices and
# worksheets they operate on are data. The two roots are independent.
INSTRUCTIONS_DIR = PROJECT_ROOT / "instructions" / "02-fund-mapping"
DISPATCH_DIR = INSTRUCTIONS_DIR / "dispatch-prompts"

# One generated prompt = one shared brief plus the one file that agent owns.
# The brief is the spec and is written by hand; the header is what makes the
# prompt pasteable, and it can only be written once the slices exist, which is
# why this is generated rather than kept in the repo by hand.
DISPATCH_ROLES = (
    {
        "folder": "normalize",
        "brief": "01-NAME-NORMALIZER.md",
        "pattern": "fund-part-*.csv",
        "stem": "NORMALIZER",
        "title": "Name normalizer",
        "writes": "`standardized_fund_name`, `fund_family`, `decision_status`, `merge_note`",
        # `autofill` prefills a standard and marks it `auto`, meaning proposed
        # and not yet read. Only `decided` or `review` is a person's ruling, so
        # a filled name is not evidence the row is finished.
        "finished": lambda row: (row.get("decision_status") or "").strip()
        in {"decided", "review"},
        "unit": "printed fund names",
    },
    {
        "folder": "web-manager",
        "brief": "02-WEB-MANAGER-A.md",
        "pattern": "manager-*-a.csv",
        "stem": "WEB-MANAGER",
        "suffix": "A",
        "title": "Web manager A",
        "writes": "`a_manager_name`, `a_source`",
        # A negative search names no firm but still carries a source, so
        # evidence, not a name, is what marks the lookup complete.
        "finished": lambda row: bool(
            (row.get("a_manager_name") or "").strip() or (row.get("a_source") or "").strip()
        ),
        "unit": "GP lookups",
    },
    {
        "folder": "web-manager",
        "brief": "03-WEB-MANAGER-B.md",
        "pattern": "manager-*-b.csv",
        "stem": "WEB-MANAGER",
        "suffix": "B",
        "title": "Web manager B",
        "writes": "`b_manager_name`, `b_source`",
        "finished": lambda row: bool(
            (row.get("b_manager_name") or "").strip() or (row.get("b_source") or "").strip()
        ),
        "unit": "GP lookups",
    },
    {
        "folder": "adjudicate",
        "brief": "04-WEB-MANAGER-ADJUDICATOR.md",
        "pattern": "manager-*-j.csv",
        "stem": "WEB-MANAGER",
        "suffix": "J",
        "title": "Web manager adjudicator",
        "writes": "`final_manager_name`, `final_source`",
        "finished": lambda row: bool(
            (row.get("final_manager_name") or "").strip()
            or (row.get("final_source") or "").strip()
        ),
        "unit": "unsettled lookups",
    },
)


def _repo_path(path: Path) -> str:
    """Path as written in a prompt: repo-relative where it can be."""

    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _brief_body(path: Path) -> str:
    """Return the brief without its own H1, so the generated file keeps one."""

    lines = path.read_text(encoding="utf-8").splitlines()
    start = 1 if lines and lines[0].startswith("# ") else 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    return "\n".join(lines[start:]).rstrip() + "\n"


def _remaining(rows: list[dict[str, str]], role: dict) -> int:
    """How many rows in this slice still need the agent."""

    return sum(1 for row in rows if not role["finished"](row))


def _slice_scale(rows: list[dict[str, str]], role: dict) -> str:
    """Describe the slice in the unit the agent actually works in."""

    scale = f"{len(rows)} {role['unit']}"
    members = sum(int(row.get("member_count") or 0) for row in rows if row.get("member_count"))
    if members:
        scale += f", covering {members} funds"
    done = len(rows) - _remaining(rows, role)
    if done:
        scale += f"; {done} already finished in an earlier session"
    return scale


def _prompt_target(role: dict, worksheet: Path) -> Path:
    index = worksheet.stem.split("-")[-1 if role["folder"] == "normalize" else -2]
    suffix = f"-{role['suffix']}" if role.get("suffix") else ""
    return DISPATCH_DIR / role["folder"] / f"{role['stem']}-{index}{suffix}.md"


def _render_dispatch(role: dict, worksheet: Path, index: str) -> str:
    """Build one self-contained prompt: the role, the worksheet, then the spec."""

    rows = read_csv(worksheet)
    remaining = _remaining(rows, role)
    name = f"{role['title']}: slice {index}"
    relative = _repo_path(worksheet)
    brief = INSTRUCTIONS_DIR / role["brief"]
    if remaining:
        slice_line = f"- **Slice:** {_slice_scale(rows, role)}"
    else:
        slice_line = (
            f"- **Slice:** {_slice_scale(rows, role)}. Every row is finished. "
            "This file stays: it is the standing brief for this slice."
        )
    header = [
        f"# {name}",
        "",
        f"*Generated by `name_normalization dispatch` from `{role['brief']}` and"
        f" `{worksheet.name}`. Regenerate this file; do not hand-edit it. "
        "Do not delete it when the slice is settled.*",
        "",
        "- **Project root:** the repository root, the folder holding `README.md`; every path below is relative to it",
        f"- **Worksheet:** `{relative}`",
        slice_line,
        f"- **Written cells:** {role['writes']} in that file, and nothing else anywhere.",
        "",
        "**Resuming.** A row whose cells are already filled is finished work, from"
        " an earlier session or an earlier attempt at this slice. Skip it, start at"
        " the first empty row, and never clear or rewrite a filled cell. Sessions do"
        " fail part way through, and the only thing that loses work is starting over.",
        "",
        "",
    ]
    return "\n".join(header) + _brief_body(brief)


def _dispatch_plan() -> tuple[list[tuple[Path, str]], list[str], list[str]]:
    """One prompt per worksheet that exists, including slices already settled.

    The prompt set is a process artifact. `dispatch` regenerates it from the
    briefs and the worksheets, so a later run can reproduce the same paste-ins.
    A prompt is removed only when its worksheet is gone.
    """

    plan: list[tuple[Path, str]] = []
    finished: list[str] = []
    open_slices: list[str] = []
    for role in DISPATCH_ROLES:
        brief = INSTRUCTIONS_DIR / role["brief"]
        if not brief.exists():
            raise SystemExit(f"Missing brief {brief}")
        for worksheet in sorted(WORKSHEET_DIR.glob(role["pattern"])):
            remaining = _remaining(read_csv(worksheet), role)
            index = worksheet.stem.split("-")[-1 if role["folder"] == "normalize" else -2]
            target = _prompt_target(role, worksheet)
            plan.append((target, _render_dispatch(role, worksheet, index)))
            if remaining:
                open_slices.append(worksheet.name)
            else:
                finished.append(worksheet.name)
    return plan, finished, open_slices


def _existing_prompts() -> set[Path]:
    existing: set[Path] = set()
    for role in DISPATCH_ROLES:
        folder = DISPATCH_DIR / role["folder"]
        if folder.exists():
            existing.update(path for path in folder.glob("*.md") if path.name != "README.md")
    return existing


def dispatch(check: bool = False) -> int:
    """Write one pasteable prompt per worksheet, or prove the ones on disk match.

    The slices decide how many files there are, so the prompts are generated,
    not kept by hand. A prompt naming a slice that no longer exists is removed.
    A slice whose rows are all finished still keeps its prompt.
    """

    plan, finished, open_slices = _dispatch_plan()
    if not plan:
        raise SystemExit(
            f"No worksheets in {WORKSHEET_DIR}. Run `export` and `manager-export` first."
        )
    wanted = {path for path, _ in plan}
    existing = _existing_prompts()
    if check:
        stale = [
            path
            for path, content in plan
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        orphan = sorted(existing - wanted)
        for path in stale:
            print(f"STALE  : {_repo_path(path)}")
        for path in orphan:
            print(f"ORPHAN : {_repo_path(path)}")
        if stale or orphan:
            print(f"FAIL: {len(stale)} stale, {len(orphan)} orphaned. Run `dispatch`.")
            return 1
        print(f"PASS: {len(plan)} dispatch prompt(s) match the briefs and the slices")
        return 0
    for path in sorted(existing - wanted):
        path.unlink()
    for path, content in plan:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    by_folder: dict[str, int] = defaultdict(int)
    for path, _ in plan:
        by_folder[path.parent.name] += 1
    for folder in sorted(by_folder):
        print(f"{folder:<12} {by_folder[folder]} prompt(s)")
    if finished:
        print(f"{'standing':<12} {len(finished)} slice(s) finished; prompts kept")
    if open_slices:
        print(f"{'open':<12} {len(open_slices)} slice(s) still have rows to fill")
    else:
        print("Every identity slice on disk is finished. Prompts stay as standing briefs.")
    print(f"PASS: {len(plan)} dispatch prompt(s) -> {DISPATCH_DIR}")
    return 0


def batches(kind: str, size: int) -> int:
    """Print stable row ranges so several normalizers can work without colliding.

    Ranges are derived from the file's own order and never stored: a batch is a
    dispatch detail, not a fact about a fund.
    """

    path, raw_col, _std, _id = KINDS[kind]
    rows = read_csv(path)
    if not rows:
        print(f"{path.name} holds no rows")
        return 0
    total = len(rows)
    count = (total + size - 1) // size
    print(f"{path.name}: {total} rows, {count} batch(es) of up to {size}")
    for index in range(count):
        start = index * size
        stop = min(start + size, total)
        print(
            f"  batch {index + 1:02d}  csv lines {start + 2}-{stop + 1}  "
            f"{(rows[start].get(raw_col) or '')[:40]!r} .. {(rows[stop - 1].get(raw_col) or '')[:40]!r}"
        )
    return 0


def conflicts(strict: bool = False) -> int:
    """Report every fund whose printed variants landed on more than one standard.

    This is the check that one repeatedly printed fund never ends up with two or
    three standardized names. A cluster a person has ruled genuinely distinct
    says so in merge_note and stops being reported.
    """

    rows_out: list[dict[str, str]] = []
    for kind, (path, raw_col, std_col, _id) in KINDS.items():
        rows = read_csv(path)
        by_key: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            raw = (row.get(raw_col) or "").strip()
            if raw:
                by_key[match_key(raw)].append(row)
        for key, group in sorted(by_key.items()):
            standards = sorted(
                {
                    (row.get(std_col) or "").strip()
                    for row in group
                    if (row.get(std_col) or "").strip()
                }
            )
            if len(standards) < 2:
                continue
            if any("distinct" in (row.get("merge_note") or "").casefold() for row in group):
                continue
            rows_out.append({
                "kind": kind,
                "match_key": key,
                "standard_count": str(len(standards)),
                "standards": " | ".join(standards),
                "raw_variants": " | ".join(
                    sorted((row.get(raw_col) or "").strip() for row in group)
                ),
                "occurrences": str(
                    sum(int((row.get("a_count") or "0") or 0) for row in group)
                ),
            })
    write_csv(
        STANDARD_CONFLICTS,
        ["kind", "match_key", "standard_count", "standards", "raw_variants", "occurrences"],
        rows_out,
    )
    if not rows_out:
        print(f"PASS: no fund carries two standardized names -> {STANDARD_CONFLICTS.name}")
        return 0
    print(
        f"{'FAIL' if strict else 'REVIEW'}: {len(rows_out)} name cluster(s) carry more "
        f"than one standard -> {STANDARD_CONFLICTS.name}"
    )
    for row in rows_out[:15]:
        print(f"  {row['kind']:<8} {row['standards']}")
    if len(rows_out) > 15:
        print(f"  ... {len(rows_out) - 15} more")
    print(
        "  Merge each cluster onto one standard, or write `distinct` in merge_note "
        "when the vehicles genuinely differ."
    )
    return 1 if strict else 0


def families() -> int:
    """Report how far the sponsor-family column has collapsed the manager round."""

    path, raw_col, std_col, _id = KINDS["fund"]
    rows = [
        row
        for row in read_csv(path)
        if (row.get("decision_status") or "").strip().lower() in DECIDED
        and (row.get(std_col) or "").strip()
    ]
    standards = {(row.get(std_col) or "").strip() for row in rows}
    named = {
        (row.get(std_col) or "").strip(): (row.get(FAMILY_COLUMN) or "").strip()
        for row in rows
        if (row.get(FAMILY_COLUMN) or "").strip()
    }
    groups = sorted(set(named.values()))
    unfamilied = len(standards) - len(named)
    print(f"settled funds        : {len(standards)}")
    print(f"  carrying a family  : {len(named)}")
    print(f"  no family yet      : {unfamilied}")
    print(f"distinct families    : {len(groups)}")
    by_key: dict[str, set[str]] = defaultdict(set)
    for family in groups:
        by_key[match_key(family)].add(family)
    split = {key: value for key, value in by_key.items() if len(value) > 1}
    if split:
        print(f"  spelled more than one way: {len(split)}")
        for key, value in sorted(split.items()):
            print(f"    {sorted(value)}")
    if named:
        saved = len(named) - len(groups)
        print(f"manager searches saved by grouping: {saved}")
    return 0


# Where every verb writes. An operator reading the runbook should never have to
# open this file to learn where a command puts its output, and a reader who does
# open it should find one place that answers it. The `paths` verb prints this and
# the runbook renders the same table; a test fails if the two drift, or if a verb
# is added to the parser without an entry here.
WRITES: dict[str, tuple[str, ...]] = {
    "harvest": (
        "data/normalization/fund-names-matrix.csv",
        "data/normalization/manager-names-matrix.csv",
        "data/normalization/lp-names-matrix.csv",
        "data/normalization/plan-names-matrix.csv",
        "data/normalization/company-names-matrix.csv",
    ),
    "autofill": ("data/normalization/<kind>-names-matrix.csv",),
    "check": ("data/normalization/name-near-duplicates.csv",),
    "conflicts": ("data/normalization/standard-conflicts.csv",),
    "export": ("data/normalization/worksheets/fund-part-NN.csv",),
    "merge": ("data/normalization/<kind>-names-matrix.csv",),
    "manager-queue": ("data/normalization/manager-queue.csv",),
    "manager-export": ("data/normalization/worksheets/manager-NN-<role>.csv",),
    "manager-merge": ("data/normalization/manager-queue.csv",),
    "manager-autosettle": ("data/normalization/manager-queue.csv",),
    "propagate": ("data/normalization/web-manager-names.csv",),
    "managers": ("data/normalization/web-manager-names.csv",),
    "dispatch": ("instructions/02-fund-mapping/dispatch-prompts/<role>/",),
    # Reporting verbs: they read the matrices and print, writing nothing.
    "batches": (),
    "families": (),
    "paths": (),
}

REPORT_ONLY = "prints a report; writes nothing"


def paths() -> int:
    """Print which file each verb writes, so a destination is never a guess."""
    width = max(len(verb) for verb in WRITES)
    for verb in sorted(WRITES):
        targets = WRITES[verb] or (f"({REPORT_ONLY})",)
        for index, target in enumerate(targets):
            print(f"  {verb if index == 0 else '':<{width}}  {target}")
    print(
        "\nEvery matrix, queue, and worksheet lives under data/normalization/."
        "\ninstructions/02-fund-mapping/entity_ids.py writes data/normalization/entity-ids.csv."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("paths", help="print the output file each command writes")
    sub.add_parser("harvest", help="append new printed names into the conversion matrices")
    sub.add_parser("autofill", help="settle the names that have only one printed variant")
    sub.add_parser("check", help="enforce one standardized name per entity")
    sub.add_parser("managers", help="queue funds with no general partner and report coverage")
    batch_parser = sub.add_parser("batches", help="print stable row ranges for dispatch")
    batch_parser.add_argument("--kind", default="fund", choices=sorted(KINDS))
    batch_parser.add_argument("--size", type=int, default=120)
    conflict_parser = sub.add_parser(
        "conflicts", help="report any fund carrying more than one standardized name"
    )
    conflict_parser.add_argument("--strict", action="store_true")
    export_parser = sub.add_parser("export", help="split a matrix into per-normalizer worksheets")
    export_parser.add_argument("--kind", default="fund", choices=sorted(KINDS))
    export_parser.add_argument("--size", type=int, default=120)
    merge_parser = sub.add_parser("merge", help="fold filled worksheets back into the matrix")
    merge_parser.add_argument("--kind", default="fund", choices=sorted(KINDS))
    sub.add_parser("families", help="report the sponsor-family grouping and what it saves")
    sub.add_parser("manager-queue", help="build one manager lookup per sponsor family")
    sub.add_parser("manager-autosettle", help="settle lookups needing no judgement call")
    sub.add_parser("propagate", help="write settled managers onto every fund they cover")
    ms = sub.add_parser("manager-export", help="split the work order into per-agent slices")
    ms.add_argument("--size", type=int, default=45)
    ms.add_argument("--role", default="ab", choices=("ab", "adjudicate"))
    ms.add_argument(
        "--retry",
        action="store_true",
        help="re-open lookups already searched: export them with empty answer cells",
    )
    sub.add_parser("manager-merge", help="fold agent slices back into the work order")
    dp = sub.add_parser(
        "dispatch",
        help="write one pasteable prompt per worksheet; keep it after the slice is settled",
    )
    dp.add_argument(
        "--check",
        action="store_true",
        help="fail if a prompt on disk is stale or orphaned instead of rewriting it",
    )
    args = parser.parse_args()
    if args.command == "paths":
        sys.exit(paths())
    if args.command == "harvest":
        sys.exit(harvest())
    if args.command == "autofill":
        sys.exit(autofill())
    if args.command == "check":
        sys.exit(check())
    if args.command == "managers":
        sys.exit(managers())
    if args.command == "batches":
        sys.exit(batches(args.kind, args.size))
    if args.command == "export":
        sys.exit(export_worksheets(args.kind, args.size))
    if args.command == "merge":
        sys.exit(merge_worksheets(args.kind))
    if args.command == "conflicts":
        sys.exit(conflicts(args.strict))
    if args.command == "families":
        sys.exit(families())
    if args.command == "manager-queue":
        sys.exit(build_manager_queue())
    if args.command == "manager-autosettle":
        sys.exit(auto_settle_manager_queue())
    if args.command == "propagate":
        sys.exit(propagate_managers())
    if args.command == "manager-export":
        roles = ("a", "b") if args.role == "ab" else ("j",)
        sys.exit(export_manager_slices(args.size, roles, args.retry))
    if args.command == "manager-merge":
        sys.exit(merge_manager_slices())
    if args.command == "dispatch":
        sys.exit(dispatch(args.check))


if __name__ == "__main__":
    main()
