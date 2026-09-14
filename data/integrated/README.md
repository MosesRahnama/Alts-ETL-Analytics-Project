# Integrated completion records

| File | Content |
|---|---|
| `gap-ledger.csv` | Missing analytical fields, their resolutions, and source gaps that remain unfilled |
| `cell-lineage.csv` | Every added cell or row, its source, formula, parameter, and precedence |
| `reconciliation-results.csv` | Identity, source preservation, and financial checks |
| `benchmark-policy.csv` | Benchmark source, permitted use, and rights status |
| `defect-periods.csv` | Isolated copies with planted errors |
| `defect-quality-results.csv` | Quality results on the damaged copies |
| `detection-scorecard.csv` | Expected-rule detection by planted-error family |

Completion retains the [source-only snapshot](../extracted/fund-level/README.md) and adds labelled data on the same fund IDs. The [currency policy](../normalization/transformations/completion-currency-policy.csv) withholds generated monetary rows for unsupported denominations and records unfilled currency gaps; investor flows remain separate from whole-fund calculations.

Next: [fund-model CSVs](../csv/README.md).
