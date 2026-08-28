# Completion and quality runbook

| Command | Result |
|---|---|
| `python -m src.pipeline.build_integrated_universe --snapshot-only` | Freeze source-backed fund tables |
| `python -m src.pipeline.build_integrated_universe` | Complete gaps on the same fund IDs and write lineage |
| `python -m src.quality.run_fund_checks --run-id INTEGRATED_QC_V1` | Check fund-model records |
| `python -m src.pipeline.build_mock_universe` | Optional standalone regression fixture |

The integration command refuses identity loss, overwritten extracted period or cash-flow IDs, broken fund math, missing lineage, or an undetected planted-error family.

Next: [`../04-analytics/README.md`](../04-analytics/README.md).
