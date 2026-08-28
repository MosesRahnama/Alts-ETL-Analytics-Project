# Layers

| Layer | Owner | Main output |
|---|---|---|
| Source | PDF reports and source catalog | `data/documents/` |
| Extraction | 300 DPI PNG per page, then A/B candidates, each on its own file, and the third reader | `data/extracted/rounds/` |
| Evidence | Printed cells and A/B origin records | `data/extracted/tables/`, `extracted.duckdb` |
| Identity | Reviewed entity and attribute matrices | `data/normalization/` |
| Fund-level promotion | Source-backed rows written by `promote_extracted_to_fund_level`, checked by `validate_round02_promotion` | `data/extracted/fund-level/` (copy taken before fill) |
| Completion | Extracted-first completion with a label and a fill record per cell | `data/csv/`, `data/integrated/` |
| Quality and analytics | 23 rules, then multiples, XIRR, PME, and allocation, each row copying its input period's origin mark | `data/csv/quality_results.csv`, `fund_metrics.csv`, `pme_results.csv`, `portfolio_allocations.csv` |
| Review | Flat observations, periods, gaps, fill records, and the dashboard | `data/extracted/review/`, `dashboard.html` |
| Query | Copies of the CSV layers with the same rows and values | `extracted.duckdb`, `alts.duckdb` |
| Fixture | A separate 800-fund population for rule and generator tests | `data/synthetic/`, `alts_mock.duckdb` |
| History | Readable transformation receipts; large backups stay local | `ledgers/pipeline/`, sibling artifact archive |

```mermaid
flowchart LR
    P["PDF"] --> I["300 DPI PNG, required for extraction"]
    P --> T["TXT and document grids"]
    I --> AB["Extractor A and B, each on its own file"]
    T --> AB
    AB --> J["compare, then third reader on the page image"]
    J --> E["fact_observation: 7,201 printed values"]
    E --> PR["fund-level promotion: 4,284 rows"]
    PR -- "65 category/value mismatches" --> W["withheld"]
    PR --> S["source-only snapshot: 378 periods, EXTRACTED"]
    S --> M["DPI, RVPI, TVPI on 268 approved periods"]
    S --> C["completion: 934 SYNTHETIC periods, generated flows, cell fill records"]
    C --> X["XIRR, KS-PME, Direct Alpha, allocation"]
    S --> Q["23 quality rules, both populations"]
    C --> Q
```

The analytics path reads `data/csv/` alone. The regression fixture under `data/synthetic/` goes into `alts_mock.duckdb` and nothing else.

Next: [`FINAL-RELEASE-AUDIT.md`](FINAL-RELEASE-AUDIT.md).
