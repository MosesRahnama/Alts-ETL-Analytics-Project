# Analytics runbook

| Command | Output |
|---|---|
| `python -m src.analytics.run_extracted_analytics` | Metrics supported by frozen extracted periods alone |
| `python -m src.analytics.run_integrated_analytics` | Four metrics, two PME results, and one allocation per completed real fund |
| `python -m src.analytics.run_round04_analytics --benchmark-id <id>` | Direct configurable analytics run |

The extracted run reads `data/extracted/fund-level/`; the integrated run selects `INTEGRATED_COMPLETION_V1`. Both use quality-approved periods and write formula, input, and benchmark IDs. The SPY series carries `DEMONSTRATION_ONLY` rights and `DEMO_PROXY_ONLY` use; the bounded allocation does not estimate risk.

Next: [`../REVIEWER-GUIDE.md`](../REVIEWER-GUIDE.md).
