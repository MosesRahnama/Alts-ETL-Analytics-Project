# Extraction audit

| File | Contents |
|---|---|
| `promotion-category-mismatches.csv` | 65 cells withheld from promotion because metric category and printed value kind disagree (61 paid-in capital, 4 income) |
| `attribute-inherit.csv` | 330 blank observation contexts filled from the same fund's settled printed value, with the source |
| `attribute-changes.csv` | 598 fund-model vintage and strategy cells: 452 inherited, 146 baseline confirmed, each with old value, new value, source, and rule |
| `source-lineage-audit.csv` | Source hash and extraction-lineage findings per file |
| `source-lineage-audit.md` | The SRC384 rebind: how a changed source hash was traced through TXT, grid, both lanes, and the final file |

Pair-level evidence stays in `ledgers/working/pdf-extraction-csv/<route>/<file>/` (`records-a.csv`, `records-b.csv`, `pair-index.csv`, `resolution.csv`); the per-document rollup is `data/extracted/review/document-summary.csv`.
