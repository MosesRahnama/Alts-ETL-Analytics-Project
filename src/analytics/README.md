# Analytics

| File | Role |
|---|---|
| `run_round04_analytics.py` | The engine: DPI, RVPI, TVPI, XIRR (Newton with bisection fallback, actual/365), KS-PME and Direct Alpha with a backward-only benchmark join, and bounded equal-weight allocation |
| `run_extracted_analytics.py` | Stage 115: the metrics the frozen extracted periods support alone |
| `run_integrated_analytics.py` | Stage 120: metrics, PME, and allocation on the completed panel |
| `__init__.py` | Package marker |

Reviewer results: [`../../data/extracted/review/reviewer-analytics-summary.csv`](../../data/extracted/review/reviewer-analytics-summary.csv).
