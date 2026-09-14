# One-Day Pricing

Self-contained LP-interest pricing demonstration. It reads controlled parent data, generates fictional seller transactions and forecasts locally, and produces buyer price ceilings, returns, funding scenarios, QC, synthetic comparable-price evaluation, and an offline dashboard. GP-Scoring is not a runtime dependency.

| File or folder | Content |
|---|---|
| `run.py` | Candidate build, publication, archive, receipt, and verification |
| `inputs.py`, `simulate.py` | Read-only parent adapter and fictional transaction generation |
| `finance.py`, `pricing.py` | Local XNPV/XIRR, settlement, forecasts, position and portfolio pricing |
| `qc.py`, `tests/` | Pricing controls and 27 focused tests |
| `market.py` | Separate fictional comparable-trade baseline and ridge experiment |
| `briefing.py` | Deterministic briefs plus optional OpenRouter/Anthropic adapters |
| `report.py` | Self-contained HTML reviewer report |
| `policy.json` | Dates, transaction settings, scenarios, hurdles and model limits |
| `DATA-PLAN.csv`, `IMPLEMENTATION.csv`, `VALIDATION.csv` | Data plan, stage status, and executed validation |
| `ROADMAP.md`, `IMPLEMENTATION-REPORT.md` | Pricing rules and completed implementation summary |
| `01-inputs/`, `02-pricing/`, `03-report/` | Active integrated-demo build inputs, calculations, dashboard and receipt |
| `archive/previous.zip` | Previous successful active bundle |
| `02_Valuation_Lab.html` | Separate interactive interview-education lab; not read by `run.py` |
| `IDEAS.md` | Research questions about secondary pricing signals and public disclosure; not read by `run.py` |

| Command from parent root | Result |
|---|---|
| `python One-Day-Pricing\run.py --parent . --population integrated_demo --llm off` | Seven-position hypothetical integrated demo |
| `python One-Day-Pricing\run.py --parent . --population fixture --llm preview --provider openrouter` | 100-position fictional scale demo with no model call |
| `python One-Day-Pricing\run.py --parent . --population observed --llm off --skip-market` | Named source evidence only, with no synthetic price |
| `python One-Day-Pricing\run.py --parent . --check-only` | Read-only input/code/output hash verification |
| `python -m pytest One-Day-Pricing\tests\test_pricing.py -q -p no:cacheprovider` | Focused pricing tests |
| `One-Day-Pricing\open-dashboard.cmd` | Open the active reviewer dashboard |

Current active build: `02ac7efa1eb2c894`, integrated demo, 15/15 runtime checks. The seller positions, transaction events, forecasts and comparable trades are synthetic. Buyer ceilings are return-based outputs, not observed market-clearing prices or AlpInvest prices. No live model call has been made.
