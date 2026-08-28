# Work stages

```mermaid
flowchart TD
    L["source_ledger.csv: 442 PDFs, 17 types"] --> T["page-aligned TXT"]
    L --> I["render_image_corpus.py: 300 DPI PNG per page, required for extraction"]
    L --> DG["document grids"]
    I --> C["build_csv_pipeline build: 42-column row format, 7 routes, four briefs per route"]
    T --> C
    DG --> C
    C --> E["extractor A and extractor B, each on its own file<br/>records-a/b.csv, coverage-a/b.csv"]
    E --> V{"validate-candidate and audit-file pass?"}
    V -- "fail" --> E
    V -- "pass" --> M["compare: physical key pairing, conflict typing"]
    M --> J["third readers J1 odd and J2 even, page image in hand<br/>resolution.csv, records-final.csv"]
    J --> F{"validate-final: 29 of 29?"}
    F -- "fail" --> J
    F -- "pass" --> P["publish: rounds, 7,201 records, 311 page rows"]
    P --> N["identity: name matrices, entity IDs, manager round, attributes"]
    N --> G{"conflicts --strict clean?"}
    G -- "no" --> N
    G -- "yes" --> S["flatten, pivot_wide, load_star: extracted.duckdb"]
    S --> Q["promote: 4,284 rows in, 65 withheld<br/>copy taken before fill data/extracted/fund-level"]
    Q --> I["build_integrated_universe: labelled completion on 934 fund IDs"]
    I --> K["23 quality rules, planted-defect overlay, analytics, reviewer files, alts.duckdb"]
    K --> Z{"reviewer_check: 144 checks"}
```

Stage table with commands: [`../PROCESS.md`](../PROCESS.md). Relational models: [`../docs/EXTRACTED-DATA-MODEL.md`](../docs/EXTRACTED-DATA-MODEL.md) for `extracted.duckdb`, [`../docs/DATA-MODEL.md`](../docs/DATA-MODEL.md) for `alts.duckdb`.
