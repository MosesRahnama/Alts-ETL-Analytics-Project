# Extraction audit records

| File | Content |
|---|---|
| `source-review-changes.csv` | Applied field corrections with old value, new value, native page, quote, and reason |
| `promotion-category-mismatches.csv` | Values withheld from analytical columns because their printed type differs |
| `attribute-inherit.csv` | Observation attributes copied from the same fund's settled source evidence |
| `attribute-changes.csv` | Fund-model attribute changes with before/after values and source |
| `source-lineage-audit.csv` | Per-file source and extraction-reference checks |
| `source-lineage-audit.md` | Historical SRC384 source correction |

Original A/B candidates and comparisons remain in `ledgers/working/pdf-extraction-csv/`; reviewed corrections update resolution records before final publication.

[Authored correction matrix](../../normalization/source-review-corrections.csv) · [Extraction review](../review/README.md)
