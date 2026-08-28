# SRC034 extraction evidence

Blind candidates, coverage, comparison, decisions, and final records for SRC034.

| File | Role |
|---|---|
| `records-a.csv` | Blind Extractor A observations. |
| `records-b.csv` | Blind Extractor B observations. |
| `coverage-a.csv` | Physical pages reviewed by Extractor A. |
| `coverage-b.csv` | Physical pages reviewed by Extractor B. |
| `pair-index.csv` | Paired agreements, disagreements, and one-sided candidate rows. |
| `coverage-diff.csv` | Page-level differences between the two extraction lanes. |
| `resolution.csv` | Adjudicator decisions for candidate pairs. |
| `coverage-resolution.csv` | Adjudicator decisions for page-coverage differences. |
| `records-final.csv` | Source-backed final observations for one document. |
| `coverage-final.csv` | Final physical-page coverage for one document. |

```mermaid
sequenceDiagram
    participant S as Source PDF and page aids
    participant A as Extractor A
    participant B as Extractor B
    participant C as Pairing gate
    participant J as J1 or J2 adjudicator
    participant F as Final publisher
    S->>A: assigned pages, text, images, and grids
    S->>B: assigned pages, text, images, and grids
    A->>C: records-a.csv and coverage-a.csv
    B->>C: records-b.csv and coverage-b.csv
    C->>J: pair-index.csv and coverage-diff.csv
    J->>F: resolution.csv and coverage-resolution.csv
    F->>F: records-final.csv and coverage-final.csv
```
