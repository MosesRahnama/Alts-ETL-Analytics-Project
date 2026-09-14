# Completion and quality runbook

| Command | Result |
|---|---|
| `python -m src.pipeline.build_integrated_universe --snapshot-only` | Freeze source-backed fund tables |
| `python -m src.pipeline.build_integrated_universe` | Complete gaps on funds with supported currencies and write cell-origin records |
| `python -m src.quality.run_fund_checks --run-id INTEGRATED_QC_V1` | Check fund-model records |
| `python -m src.pipeline.build_mock_universe` | Optional standalone regression fixture |

Integration refuses identity loss, overwritten source rows, broken fund math, missing origin records, or missed planted errors. Unsupported currencies remain source-only with declared completion gaps. The release command checks failures across both populations against [value-specific source exceptions](../../data/normalization/transformations/quality-source-exceptions.csv).

Next: [`../04-analytics/README.md`](../04-analytics/README.md).
