"""Mint append-only fund, manager, and LP IDs on the conversion matrices.

The ID belongs to the standardized name, not the raw spelling. Variants that
share a standard share an ID. New decided standards get the next unused
number. Existing IDs are never reused or renumbered.

    python instructions/02-fund-mapping/entity_ids.py

The matrices it stamps are data, not instructions, and live in
`data/normalization/`. Rules: `data/normalization/README.md`.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
# instructions/02-fund-mapping -> instructions -> the repo root.
PROJECT_ROOT = HERE.parents[1]
MATRIX_DIR = PROJECT_ROOT / "data" / "normalization"
REGISTRY_PATH = MATRIX_DIR / "entity-ids.csv"
FUND_MATRIX = MATRIX_DIR / "fund-names-matrix.csv"
MANAGER_MATRIX = MATRIX_DIR / "manager-names-matrix.csv"
LP_MATRIX = MATRIX_DIR / "lp-names-matrix.csv"
PLAN_MATRIX = MATRIX_DIR / "plan-names-matrix.csv"
COMPANY_MATRIX = MATRIX_DIR / "company-names-matrix.csv"
WEB_MANAGER_MATRIX = MATRIX_DIR / "web-manager-names-matrix.csv"
WEB_MANAGER_NAMES = MATRIX_DIR / "web-manager-names.csv"
FUND_MASTER = PROJECT_ROOT / "data" / "csv" / "fund_master.csv"
MANAGER_MASTER = PROJECT_ROOT / "data" / "csv" / "manager_master.csv"

LEDGER_IDENTITY_COLS = [
    "fund_id",
    "standardized_fund_name",
    "manager_id",
    "standardized_manager_name",
    "lp_id",
    "standardized_lp_name",
]

REGISTRY_HEADER = ["kind", "entity_id", "standardized_name"]
PREFIX = {"fund": "FUND", "manager": "MGR", "lp": "LP", "plan": "PLAN", "company": "CO"}
ID_RE = re.compile(r"^(FUND|MGR|LP|PLAN|CO)_(\d{4})$")

# A name is settled either because a person decided it or because it was the only
# printed variant of itself in the corpus, which is a definition and not a call.
SETTLED = {"decided", "auto"}

FUND_MATRIX_HEADER = [
    "fund_name_raw",
    "standardized_fund_name",
    "fund_family",
    "fund_id",
    "decision_status",
    "seen_in_agents",
    "source_files",
    "a_count",
    "b_count",
    "merge_note",
]
MANAGER_MATRIX_HEADER = [
    "manager_name_raw",
    "standardized_manager_name",
    "manager_id",
    "decision_status",
    "seen_in_agents",
    "source_files",
    "a_count",
    "b_count",
    "merge_note",
]
LP_MATRIX_HEADER = [
    "lp_name_raw",
    "standardized_lp_name",
    "lp_id",
    "decision_status",
    "seen_in_agents",
    "source_files",
    "a_count",
    "b_count",
    "merge_note",
]
PLAN_MATRIX_HEADER = [
    "plan_name_raw",
    "standardized_plan_name",
    "plan_id",
    "decision_status",
    "seen_in_agents",
    "source_files",
    "a_count",
    "b_count",
    "merge_note",
]
COMPANY_MATRIX_HEADER = [
    "company_name_raw",
    "standardized_company_name",
    "company_id",
    "decision_status",
    "seen_in_agents",
    "source_files",
    "a_count",
    "b_count",
    "merge_note",
]
WEB_MANAGER_HEADER = [
    "manager_name_raw",
    "standardized_manager_name",
    "manager_id",
    "decision_status",
    "n_funds",
    "merge_note",
]


def write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=header,
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_id(value: str, kind: str) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    match = ID_RE.fullmatch(text)
    prefix = PREFIX[kind]
    if not match or match.group(1) != prefix:
        raise SystemExit(f"bad {kind} id {text!r}")
    return int(match.group(2))


def format_id(kind: str, number: int) -> str:
    return f"{PREFIX[kind]}_{number:04d}"


def load_registry() -> dict[str, dict[str, str]]:
    """kind -> standardized_name -> entity_id. Append-only; names are never dropped."""
    by_kind: dict[str, dict[str, str]] = {kind: {} for kind in PREFIX}
    for row in read_csv(REGISTRY_PATH):
        kind = (row.get("kind") or "").strip()
        name = (row.get("standardized_name") or "").strip()
        entity_id = (row.get("entity_id") or "").strip()
        if not kind or not name or not entity_id:
            continue
        if kind not in PREFIX:
            raise SystemExit(f"bad registry kind {kind!r}")
        parse_id(entity_id, kind)
        prior = by_kind[kind].get(name)
        if prior and prior != entity_id:
            raise SystemExit(
                f"registry conflict: {kind} {name!r} has {prior} and {entity_id}"
            )
        by_kind[kind][name] = entity_id
    return by_kind


def adopt(by_kind: dict[str, dict[str, str]], kind: str, name: str, entity_id: str) -> None:
    name = name.strip()
    entity_id = entity_id.strip()
    if not name or not entity_id:
        return
    parse_id(entity_id, kind)
    existing = by_kind[kind].get(name)
    if existing and existing != entity_id:
        raise SystemExit(
            f"cannot restamp {kind} {name!r}: already {existing}, matrix has {entity_id}"
        )
    by_kind[kind][name] = entity_id


def collect_matrix_ids(by_kind: dict[str, dict[str, str]]) -> None:
    specs = [
        (FUND_MATRIX, "fund", "standardized_fund_name", "fund_id"),
        (MANAGER_MATRIX, "manager", "standardized_manager_name", "manager_id"),
        (WEB_MANAGER_MATRIX, "manager", "standardized_manager_name", "manager_id"),
        (LP_MATRIX, "lp", "standardized_lp_name", "lp_id"),
        (PLAN_MATRIX, "plan", "standardized_plan_name", "plan_id"),
        (COMPANY_MATRIX, "company", "standardized_company_name", "company_id"),
    ]
    # Two raw spellings merged onto one standard can still carry the two IDs
    # they were minted under separately. The registry wins when it already knows
    # the name; otherwise the lowest ID wins, and stamp_matrix rewrites both rows.
    candidates: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path, kind, std_col, id_col in specs:
        for row in read_csv(path):
            status = (row.get("decision_status") or "").strip().lower()
            standard = (row.get(std_col) or "").strip()
            entity_id = (row.get(id_col) or "").strip()
            if status in SETTLED and standard and entity_id:
                candidates[(kind, standard)].add(entity_id)
    for (kind, standard), ids in sorted(candidates.items()):
        if standard in by_kind[kind]:
            continue
        adopt(by_kind, kind, standard, min(ids, key=lambda value: parse_id(value, kind)))


def seed_from_masters(by_kind: dict[str, dict[str, str]]) -> tuple[int, int]:
    """Reuse live-master IDs on literal name match. Skip DERIVED managers."""
    fund_seeded = 0
    manager_seeded = 0
    for row in read_csv(FUND_MASTER):
        name = (row.get("fund_name") or "").strip()
        entity_id = (row.get("fund_id") or "").strip()
        if name and entity_id and name not in by_kind["fund"]:
            adopt(by_kind, "fund", name, entity_id)
            fund_seeded += 1
    for row in read_csv(MANAGER_MASTER):
        if (row.get("provenance_type") or "").strip() != "EXTRACTED":
            continue
        name = (row.get("manager_name") or "").strip()
        entity_id = (row.get("manager_id") or "").strip()
        if name and entity_id and name not in by_kind["manager"]:
            adopt(by_kind, "manager", name, entity_id)
            manager_seeded += 1
    return fund_seeded, manager_seeded


def reserved_numbers(by_kind: dict[str, dict[str, str]], kind: str) -> set[int]:
    numbers = {parse_id(entity_id, kind) for entity_id in by_kind[kind].values()}
    numbers.discard(None)
    if kind == "fund":
        for row in read_csv(FUND_MASTER):
            numbers.add(parse_id(row.get("fund_id") or "", "fund"))
    if kind == "manager":
        for row in read_csv(MANAGER_MASTER):
            numbers.add(parse_id(row.get("manager_id") or "", "manager"))
    return {n for n in numbers if n is not None}


def next_number(reserved: set[int]) -> int:
    return (max(reserved) if reserved else 0) + 1


def decided_standards(path: Path, std_col: str) -> set[str]:
    names: set[str] = set()
    for row in read_csv(path):
        status = (row.get("decision_status") or "").strip().lower()
        standard = (row.get(std_col) or "").strip()
        if status in SETTLED and standard:
            names.add(standard)
    return names


def mint_missing(by_kind: dict[str, dict[str, str]]) -> dict[str, int]:
    needed = {
        "fund": decided_standards(FUND_MATRIX, "standardized_fund_name"),
        "manager": decided_standards(MANAGER_MATRIX, "standardized_manager_name")
        | decided_standards(WEB_MANAGER_MATRIX, "standardized_manager_name"),
        "lp": decided_standards(LP_MATRIX, "standardized_lp_name"),
        "plan": decided_standards(PLAN_MATRIX, "standardized_plan_name"),
        "company": decided_standards(COMPANY_MATRIX, "standardized_company_name"),
    }
    minted = {kind: 0 for kind in PREFIX}
    for kind, names in needed.items():
        reserved = reserved_numbers(by_kind, kind)
        for name in sorted(names, key=lambda item: item.casefold()):
            if name in by_kind[kind]:
                continue
            number = next_number(reserved)
            entity_id = format_id(kind, number)
            adopt(by_kind, kind, name, entity_id)
            reserved.add(number)
            minted[kind] += 1
    return minted


def stamp_matrix(
    path: Path,
    header: list[str],
    kind: str,
    std_col: str,
    id_col: str,
    by_kind: dict[str, dict[str, str]],
) -> None:
    if not path.exists():
        return
    rows = read_csv(path)
    out = []
    for row in rows:
        item = dict(row)
        status = (item.get("decision_status") or "").strip().lower()
        standard = (item.get(std_col) or "").strip()
        if status in SETTLED and standard:
            item[id_col] = by_kind[kind][standard]
        else:
            item[id_col] = ""
        out.append(item)
    write_csv(path, header, out)


def write_registry(by_kind: dict[str, dict[str, str]]) -> None:
    rows = []
    for kind in ("fund", "manager", "lp", "plan", "company"):
        for name, entity_id in sorted(
            by_kind[kind].items(), key=lambda item: parse_id(item[1], kind) or 0
        ):
            rows.append(
                {
                    "kind": kind,
                    "entity_id": entity_id,
                    "standardized_name": name,
                }
            )
    write_csv(REGISTRY_PATH, REGISTRY_HEADER, rows)


def mint_ids() -> dict[str, int]:
    by_kind = load_registry()
    collect_matrix_ids(by_kind)
    seed_from_masters(by_kind)
    minted = mint_missing(by_kind)
    write_registry(by_kind)
    stamp_matrix(
        FUND_MATRIX, FUND_MATRIX_HEADER, "fund",
        "standardized_fund_name", "fund_id", by_kind,
    )
    stamp_matrix(
        MANAGER_MATRIX, MANAGER_MATRIX_HEADER, "manager",
        "standardized_manager_name", "manager_id", by_kind,
    )
    stamp_matrix(
        WEB_MANAGER_MATRIX, WEB_MANAGER_HEADER, "manager",
        "standardized_manager_name", "manager_id", by_kind,
    )
    stamp_matrix(
        LP_MATRIX, LP_MATRIX_HEADER, "lp",
        "standardized_lp_name", "lp_id", by_kind,
    )
    stamp_matrix(
        PLAN_MATRIX, PLAN_MATRIX_HEADER, "plan",
        "standardized_plan_name", "plan_id", by_kind,
    )
    stamp_matrix(
        COMPANY_MATRIX, COMPANY_MATRIX_HEADER, "company",
        "standardized_company_name", "company_id", by_kind,
    )
    print(
        "entity ids: registry "
        + str(REGISTRY_PATH)
        + " "
        + " ".join(
            f"{kind}s {len(by_kind[kind])} (new {minted[kind]})" for kind in sorted(PREFIX)
        )
    )
    return minted


def _matrix_lookups(path: Path, raw_col: str, std_col: str, id_col: str) -> tuple[dict[str, str], dict[str, str]]:
    raw_to_std: dict[str, str] = {}
    std_to_id: dict[str, str] = {}
    for row in read_csv(path):
        raw = (row.get(raw_col) or "").strip()
        standard = (row.get(std_col) or "").strip()
        entity_id = (row.get(id_col) or "").strip()
        status = (row.get("decision_status") or "").strip().lower()
        if status not in SETTLED or not standard:
            continue
        if raw:
            raw_to_std[raw] = standard
        if entity_id:
            std_to_id[standard] = entity_id
    return raw_to_std, std_to_id


def _web_manager_by_fund() -> dict[str, str]:
    out: dict[str, str] = {}
    for row in read_csv(WEB_MANAGER_NAMES):
        fund = (row.get("standardized_fund_name") or "").strip()
        manager = (row.get("final_manager_name") or "").strip()
        if fund and manager:
            out[fund] = manager
    return out


def identity_lookups() -> dict[str, dict[str, str]]:
    registry = load_registry()
    fund_raw, fund_ids = _matrix_lookups(
        FUND_MATRIX, "fund_name_raw", "standardized_fund_name", "fund_id"
    )
    mgr_raw, mgr_ids = _matrix_lookups(
        MANAGER_MATRIX, "manager_name_raw", "standardized_manager_name", "manager_id"
    )
    web_raw, web_ids = _matrix_lookups(
        WEB_MANAGER_MATRIX, "manager_name_raw", "standardized_manager_name", "manager_id"
    )
    lp_raw, lp_ids = _matrix_lookups(
        LP_MATRIX, "lp_name_raw", "standardized_lp_name", "lp_id"
    )
    fund_ids = {**registry["fund"], **fund_ids}
    mgr_ids = {**registry["manager"], **mgr_ids, **web_ids}
    lp_ids = {**registry["lp"], **lp_ids}
    mgr_raw = {**mgr_raw, **web_raw}
    return {
        "fund_raw": fund_raw,
        "fund_ids": fund_ids,
        "mgr_raw": mgr_raw,
        "mgr_ids": mgr_ids,
        "lp_raw": lp_raw,
        "lp_ids": lp_ids,
        "web_by_fund": _web_manager_by_fund(),
    }


def resolve_standard(value: str, raw_to_std: dict[str, str]) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return raw_to_std.get(value, value)


def apply_identity(row: dict[str, str], lookups: dict[str, dict[str, str]] | None = None) -> dict[str, str]:
    """Stamp fund/manager/LP ids and standardized names onto a paired or settled row."""
    lookups = lookups or identity_lookups()
    fund_std = (row.get("txt_fund_name_normalized") or "").strip()
    if not fund_std:
        fund_std = resolve_standard(
            row.get("final_txt_fund_name") or "", lookups["fund_raw"]
        )
    fund_id = lookups["fund_ids"].get(fund_std, "")

    mgr_std = (row.get("txt_manager_name_normalized") or "").strip()
    if not mgr_std:
        mgr_std = resolve_standard(
            row.get("final_txt_manager_name") or "", lookups["mgr_raw"]
        )
    if not mgr_std:
        mgr_std = resolve_standard(
            lookups["web_by_fund"].get(fund_std, ""), lookups["mgr_raw"]
        )
    mgr_id = lookups["mgr_ids"].get(mgr_std, "")

    lp_std = (row.get("txt_lp_name_normalized") or "").strip()
    if not lp_std:
        lp_std = resolve_standard(row.get("final_txt_lp_name") or "", lookups["lp_raw"])
    lp_id = lookups["lp_ids"].get(lp_std, "")

    row["fund_id"] = fund_id
    row["standardized_fund_name"] = fund_std
    row["manager_id"] = mgr_id
    row["standardized_manager_name"] = mgr_std
    row["lp_id"] = lp_id
    row["standardized_lp_name"] = lp_std
    return row


def with_identity_header(header: list[str]) -> list[str]:
    existing = [col for col in header if col not in LEDGER_IDENTITY_COLS]
    if "txt_lp_name_normalized" in existing:
        index = existing.index("txt_lp_name_normalized") + 1
        return existing[:index] + LEDGER_IDENTITY_COLS + existing[index:]
    return existing + LEDGER_IDENTITY_COLS


def stamp_ledger(path: Path) -> int:
    if not path.exists():
        return 0
    rows = read_csv(path)
    if not rows:
        return 0
    lookups = identity_lookups()
    for row in rows:
        apply_identity(row, lookups)
    header = with_identity_header(list(rows[0].keys()))
    write_csv(path, header, rows)
    with_fund = sum(1 for row in rows if row.get("fund_id"))
    with_mgr = sum(1 for row in rows if row.get("manager_id"))
    named_mgr = sum(1 for row in rows if row.get("standardized_manager_name"))
    print(
        f"stamped {path.name}: {len(rows)} rows, "
        f"{with_fund} with fund_id, {named_mgr} with standardized manager, "
        f"{with_mgr} with manager_id"
    )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    """Mint an entity ID for every settled standardized name."""

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument(
        "--stamp-ledger",
        type=Path,
        action="append",
        default=[],
        help="Also stamp identity columns onto a Round 01 ledger CSV.",
    )
    args = parser.parse_args(argv)
    mint_ids()
    for path in args.stamp_ledger:
        stamp_ledger(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
