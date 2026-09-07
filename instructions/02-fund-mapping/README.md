# Fund identity and manager mapping

This stage turns printed fund names into stable fund-level identities while keeping managers, LPs, plans, share classes, and portfolio companies separate. Uncertain names remain open; none is guessed. After flatten, the same folder owns fund-constant attributes: vintage, strategy, asset class, and geography copied from printed context at fund grain.

**Identity matrices land in `data/normalization/`**. The headline output is `fund-names-matrix.csv` (1,055 printed-name rows mapped to 1,011 fund standards in 186 sponsor families), beside it `manager-queue.csv`, `web-manager-names.csv`, `entity-ids.csv`, `fund-attributes-matrix.csv`, and the per-agent slices in `worksheets/`. Generated prompts land under `dispatch-prompts/`. `00-OPERATOR-RUNBOOK.md` carries the command-to-file tables, and `name_normalization paths` plus `fund_attributes paths` print the same maps from the code.

| File | Role |
|---|---|
| `00-OPERATOR-RUNBOOK.md` | Full command order, dispatch rules, failure gates, and rerun behavior |
| `01-NAME-NORMALIZER.md` | Copy-ready brief for one fund-name worksheet |
| `02-WEB-MANAGER-A.md` | Blind manager-research role A |
| `03-WEB-MANAGER-B.md` | Blind manager-research role B |
| `04-WEB-MANAGER-ADJUDICATOR.md` | Source-based resolution of manager-search differences |
| `05-ATTRIBUTE-NORMALIZER.md` | Copy-ready brief for remaining fund-constant attribute spelling splits |
| `dispatch-prompts/` | Generated pasteable prompts, one per worksheet. `dispatch` regenerates them and keeps them after the slice is settled |
| `entity_ids.py` | Mints append-only fund, manager, LP, plan, and company IDs after name decisions |

```mermaid
sequenceDiagram
    participant O as Operator commands
    participant N as Name normalizer
    participant A as Manager researcher A
    participant B as Manager researcher B
    participant J as Manager adjudicator
    participant D as Normalization data
    O->>D: harvest printed names from published extraction
    O->>D: autofill single-variant rows and export worksheets
    O->>N: dispatch 01-NAME-NORMALIZER.md per worksheet
    N->>D: standardized name, fund family, decision status, note
    O->>D: merge and run conflicts --strict
    alt a standard conflict remains
        D-->>O: refuse identity publication
    else names are consistent
        O->>D: entity_ids.py mints stable IDs
        O->>A: dispatch blind manager worksheet A
        O->>B: dispatch blind manager worksheet B
        A->>D: manager name and public source
        B->>D: manager name and public source
        O->>D: merge and autosettle supported agreements
        D->>J: export disagreements and unresolved searches
        J->>D: final manager name or sourced unresolved result
        O->>D: propagate to fund rows, flatten, and load
        O->>D: harvest fund-constant attributes from fact_observation
        O->>N: dispatch ATTRIBUTE-NORMALIZER-01.md, kept after the slice is settled
        N->>D: chosen printed spelling or a blank none status
        O->>D: apply inheritance audit; promotion writes fund-model rows
    end
```

| State | Meaning |
|---|---|
| `auto` | One printed variant maps to itself; still distinct from a human decision |
| `decided` | A normalizer accepted a standard and fund family |
| `review` | Evidence is insufficient or identity remains ambiguous |
| `WEB_MANAGER: unresolved` | Independent public search found no support; the search is complete but the manager stays blank |

Current identity results: 1,055 printed-name rows, all decided, producing 1,011 fund standards in 186 sponsor families. The manager round contains 535 lookups (186 by family and 349 by fund); 314 matched automatically, 956 standards carry a general partner, and 55 have a recorded source-silent or public-search result. The fund-constant attribute matrix contains 853 funds and 0 conflicts.

Next: [`../03-synthetic-qc/README.md`](../03-synthetic-qc/README.md).
