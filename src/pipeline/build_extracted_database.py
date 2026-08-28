"""Write the decided rounds into a queryable relational database.

Twelve stages, each runnable alone with `--stage`, each printing what it did and
refusing to continue when its gate fails. The stages that touch entity identity
come first, because a name the matrix has yet to settle should be settled before
the tables are built, not after.

    names-harvest   pull every printed entity name out of the published rounds
                    into the conversion matrices, leaving new ones undecided
    names-autofill  settle the names with only one printed variant as `auto`
    names-mint      assign an entity ID to every settled standardized name
    names-check     enforce one standardized name per entity; fails closed
    managers        queue every settled fund carrying no general partner into
                    web-manager-names.csv, and report the coverage gap
    flatten         split the 42-column rows into dimensions and facts
    attributes-harvest
                    one row per fund from printed vintage, strategy, asset class,
                    and geography on fact_observation
    attributes-autofill
                    report unique and spelling-collapsed fund-constant values
    attributes-dispatch
                    export the conflict worksheet and write the standing
                    ATTRIBUTE-NORMALIZER-01.md brief; the file stays after the
                    slice is settled
    wide            pivot the facts into one modelling table per record family,
                    with a bridge back to every observation
    load            rebuild data/warehouse/extracted.duckdb from all of those tables
    report          print the entity backlog a person still has to decide

The `managers` stage prepares a second review queue. A fund name and its general
partner are separate facts: the name is printed in the document, the manager
usually is not, so it comes from the two-agent web round in
`02-WEB-MANAGER-A.md`, `03-WEB-MANAGER-B.md`, and `04-WEB-MANAGER-ADJUDICATOR.md`.
The stage only builds the queue and reports coverage; it never fills a manager.

Between `names-autofill` and `names-mint` a reviewer decides what is left:
`data/normalization/name-near-duplicates.csv` lists the
clusters, and the brief is `instructions/02-fund-mapping/01-NAME-NORMALIZER.md`.
Running every stage without that pass is valid and expected: undecided names
land as unresolved aliases and their rows still reach the tables.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

from src.catalog.simple_pdf_extraction import fund_attributes as attributes
from src.catalog.simple_pdf_extraction import name_normalization as names
from src.flatten import flatten_extracted, load_star, pivot_wide
from src.pipeline import build_extraction_review

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENTITY_IDS = PROJECT_ROOT / "instructions" / "02-fund-mapping" / "entity_ids.py"

STAGES = (
    "names-harvest",
    "names-autofill",
    "names-mint",
    "names-check",
    "managers",
    "flatten",
    "attributes-harvest",
    "attributes-autofill",
    "attributes-dispatch",
    "wide",
    "load",
    "report",
)


class PipelineError(RuntimeError):
    """Raised when a stage gate refuses to continue."""


def _entity_ids_module():
    """Load the fund-mapping ID minter, which lives outside the src package."""

    spec = importlib.util.spec_from_file_location("entity_ids", ENTITY_IDS)
    if spec is None or spec.loader is None:
        raise PipelineError(f"Cannot load the entity ID minter at {ENTITY_IDS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def undecided_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for kind, (path, raw_col, _std, _id) in names.KINDS.items():
        rows = read_csv(path)
        counts[kind] = sum(
            1
            for row in rows
            if (row.get(raw_col) or "").strip()
            and (row.get("decision_status") or "").strip() not in names.DECIDED
        )
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--stage",
        action="append",
        choices=STAGES,
        help="Run one stage. Repeat the flag to run several. Omit to run all.",
    )
    parser.add_argument("--table-dir", type=Path, default=flatten_extracted.OUTPUT_DIR)
    parser.add_argument("--wide-dir", type=Path, default=pivot_wide.WIDE_DIR)
    parser.add_argument("--database", type=Path, default=load_star.DEFAULT_DATABASE)
    parser.add_argument(
        "--require-all-names-settled",
        action="store_true",
        help=(
            "Refuse to flatten while any printed name is still undecided. Off by "
            "default: an unresolved name is recorded, not a reason to stop."
        ),
    )
    return parser


def run(args: argparse.Namespace) -> int:
    stages = args.stage or list(STAGES)

    if "names-harvest" in stages:
        names.harvest()

    if "names-autofill" in stages:
        names.autofill()

    if "names-mint" in stages:
        _entity_ids_module().mint_ids()

    if "names-check" in stages:
        if names.check() != 0:
            raise PipelineError(
                "The conversion matrices are inconsistent; the flatten stays gated "
                "until one standardized name maps to one entity."
            )

    if "managers" in stages:
        names.managers()

    if "flatten" in stages:
        pending = undecided_counts()
        total_pending = sum(pending.values())
        if total_pending and args.require_all_names_settled:
            raise PipelineError(
                f"{total_pending} printed name(s) are still undecided "
                f"({', '.join(f'{k}={v}' for k, v in sorted(pending.items()) if v)}); "
                "decide them or drop --require-all-names-settled."
            )
        written = flatten_extracted.build_tables(args.table_dir)
        for name, count in sorted(written.items()):
            print(f"flatten: {name}: {count} rows")
        review_counts = build_extraction_review.build(
            args.table_dir.parent / "review",
            root=PROJECT_ROOT,
            table_dir=args.table_dir,
        )
        print(
            "flatten: observation_lineage: "
            f"{review_counts['tables/observation_lineage.csv']} rows"
        )

    if "attributes-harvest" in stages:
        attributes.harvest()

    if "attributes-autofill" in stages:
        attributes.autofill()

    if "attributes-dispatch" in stages:
        attributes.export_worksheet()
        attributes.dispatch()

    if "wide" in stages:
        written = pivot_wide.build_wide_tables(args.table_dir, args.wide_dir)
        for name, count in sorted(written.items()):
            print(f"wide: {name}: {count} rows")

    if "load" in stages:
        counts = load_star.load(args.table_dir, args.database, rebuild=True, wide_dir=args.wide_dir)
        print(
            f"load: {sum(counts.values())} rows across {len(counts)} tables -> {args.database}"
        )

    if "report" in stages:
        backlog = read_csv(args.table_dir / "unresolved_names.csv")
        if not backlog:
            print("report: every printed name resolves to an entity")
        else:
            by_kind = Counter(row["entity_kind"] for row in backlog)
            occurrences = sum(int(row["occurrences"]) for row in backlog)
            print(
                f"report: {len(backlog)} printed name(s) still undecided across "
                f"{occurrences} observation(s): "
                + ", ".join(f"{kind}={count}" for kind, count in sorted(by_kind.items()))
            )
            for row in backlog[:10]:
                print(
                    f"report:   {row['entity_kind']:<8} {row['occurrences']:>4}x  {row['raw_name']}"
                )
            if len(backlog) > 10:
                print(f"report:   ... {len(backlog) - 10} more in unresolved_names.csv")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (PipelineError, flatten_extracted.FlattenError, load_star.LoadError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
