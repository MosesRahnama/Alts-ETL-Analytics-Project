# GP Scoring

Written for a reader unfamiliar with fund-manager scoring.

A general partner (GP) manages an investment fund. This engine compares fictional managers by their fund results, then examines cash returned, dependence on company valuations, benchmark performance and documented management risks. The historical score remains separate from the additional analyses.

[Current dashboard](06-report/dashboard.html) · [Results and verification](V2-IMPLEMENTATION-REPORT.md) · [Repairs](DIAGNOSTICS.csv)

| Analysis | Result |
|---|---|
| Three-manager comparison | Same-strategy scores, each fund's point contribution, cash recovery and rank changes under alternative assumptions |
| Capital recovery | Cash still required to recover investor contributions and the fall in remaining value the fund could absorb before that shortfall appears |
| Public-market comparison | Each payment matched to its dated benchmark; excess value and the remaining value required to match that benchmark |
| Investment dependence | Individual company gains, realized cash losses and the return after removing the largest-gain investment |
| Company operating downside | Separate effects of lower revenue, profit margin and valuation multiple on three fictional company holdings and their case fund results |
| Diligence and quality control | Team history, source conflicts, borrowing comparisons, evidence references and refusal tests for invalid inputs |

| File or folder | Content |
|---|---|
| ARCHITECTURE.md | Calculation rules and stage inputs/outputs |
| V2-ROADMAP.md; V2-EXECUTION.csv | Delivered scope and deferred work |
| V2-LIVE-LEDGER.csv; V2-VALIDATION.csv | Work history and current verification results |
| v2-policy.json | Dates, comparison groups, scenario assumptions and numerical tolerances |
| v2_inputs.py; v2-baseline.json | Input checks and protection of V1 and parent data |
| v2_features.py; v2_stress.py | Returns, holdings, terms, comparisons and sensitivity calculations |
| v2_analysis.py | Capital recovery, benchmark wealth, score contributions and company scenarios |
| v2_diligence.py; generate_v2_cases.py; data/ | Three fictional cases, document checks and payment reconciliation |
| v2_dashboard.py; run_v2.py | Seven views, printable summary, build checks and publication |
| 04-diagnostics/; 05-scenarios/; 06-report/ | Results and evidence; changed-assumption results; dashboard and checks |
| tests/ | Numerical, refusal, recovery and browser tests |
| v2-archive/; v2_ledger.py | Previous complete V2 output; work-ledger writer |
| policy.json; inputs.py; scoring.py; briefing.py; dashboard.py; run.py; brief-prompt.txt | Retained V1 engine and model settings |
| 01-inputs/; 02-scoring/; 03-report/; archive/ | Unchanged V1 inputs, scores, report and recovery bundle |
| ROADMAP.md; implementation.csv; IMPLEMENTATION-REPORT.md | Historical V1 records |
| research/; sources.csv | Supplied research and qualified source references |
| DIAGNOSTICS.md; DIAGNOSTICS.csv; V2-IMPLEMENTATION-REPORT.md | Findings, repairs and upgrade results |

| Command from repository root | Result |
|---|---|
| python -B GP-Scoring/run_v2.py --include-cases | Rebuilds the current report from validated cases; no model calls |
| python -B GP-Scoring/run_v2.py --check-only | Verifies saved outputs without writing |
| python -B -m pytest GP-Scoring/tests -q -p no:cacheprovider | Runs the add-on tests |
| python -B GP-Scoring/run_v2.py | Rebuilds core diagnostics without cases |
| python -B GP-Scoring/generate_v2_cases.py | Regenerates cases from current core diagnostics |

Changed core inputs require the last two commands in that order, followed by the case-inclusive build. The 19 core checks expand to 27 with cases. The parent data, V1 and online dashboard remain unchanged; model calls require separate authorization.
