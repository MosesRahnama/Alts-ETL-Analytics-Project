# Data ownership

| Layer | Owner | Output and next stage |
|---|---|---|
| Native evidence | Source publishers | [PDF, text, images, and grids](../data/documents/README.md) |
| Accepted extraction | Independent A/B readers and adjudicator | [Final records and review decisions](../instructions/01-pdf-extraction-csv/README.md) |
| Source corrections | Page-backed review matrix | [Corrected fields and retained original proposals](../data/normalization/source-review-corrections.csv) |
| Normalization | Reviewed name, attribute, and transformation matrices | [Evidence tables](../data/extracted/tables/README.md) |
| Fund-model promotion | `promote_extracted_to_fund_level.py` | [Source-only snapshot](../data/extracted/fund-level/README.md) |
| Completion | `build_integrated_universe.py` | [Generated additions and cell origins](../data/integrated/README.md) |
| Quality and analytics | Financial checks and calculation modules | [Integrated CSVs](../data/csv/README.md) |
| Reviewer publication | Flat export and dashboard builders | [Review files](../data/extracted/review/README.md) |
| Query copies | Database loaders with full-content parity checks | [DuckDB files](../data/warehouse/README.md) |
| Regression fixture | Separate generator and planted-error tests | [Synthetic fixture](../data/synthetic/README.md) |

Original candidate values remain separate from source review corrections. Source-only masters exclude generated defaults; completion records every added field. Whole-fund and investor cash flows are separate calculation populations. [PROCESS.md](../PROCESS.md) defines execution order; [release results](FINAL-RELEASE-AUDIT.md) record verification.
