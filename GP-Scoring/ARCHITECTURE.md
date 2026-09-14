# GP Scoring architecture

Written for a reader unfamiliar with the add-on's data and calculations.

V2 reads the parent project's fictional fund data and saved V1 scores, calculates additional diagnostics, and writes a separate report. Real document evidence and fictional case records remain separate from the ranked population.

| Component | Current behavior |
|---|---|
| Input owner | Parent CSV tables; no database writes |
| V1 reference | Existing scores remain unchanged; V2 assigns competition ranks to ties: 1, 1, 3 |
| V1 historical behavior | V1's retained rank helper uses dense ties: 1, 1, 2; the current ranked scores contain no ties |
| Fund score | 60% of the total-value comparison plus 40% of the distributed-cash comparison |
| Comparison percentile | Percentage of qualifying peer values below the fund value, with half credit for equal values |
| Total-value multiple | Distributions plus remaining value, divided by paid-in capital |
| Distributed-cash multiple | Distributions divided by paid-in capital |
| Manager score | Equal average of qualifying fund scores within one strategy |
| Ranking eligibility | At least two scored funds and 75% coverage of supplied same-strategy funds |
| Reference peers | Same strategy, currency, date, accounting scope and five-year vintage group; at least ten funds from five other managers |
| Alternative peers | Policy-controlled sub-strategy matching, stricter sample sizes and within-currency size groups |
| Return admission | Whole-fund scope, supported dates, current quality approval and compatible currency; missing optional results include reasons |
| Dated annualized return | The existing parent solver discounts investor payments and terminal remaining value |
| Trailing return | Negative opening value, payments after the opening date, and positive closing value; both boundaries require supported records |
| Same-age comparison | Report on or before the first-call anniversary, within the policy's maximum lag |
| Benchmark comparison | Strategy-matched synthetic public series; unsupported currency comparisons remain blank |
| Capital recovery | Contributions less cash distributions, floored at zero; divided by remaining value to calculate the fraction still required for capital recovery |
| Benchmark wealth | Each dated payment grows by the benchmark's change through the economic date; distributions plus remaining value less contributions gives excess value, in the fund's currency |
| Return conventions | The existing effective Direct Alpha is unchanged; its continuous equivalent is the natural logarithm of one plus that rate |
| Score contributions | Each qualifying fund contributes its weighted comparison points divided by the qualifying fund count; contributions reconcile to the published manager score |
| Terms | Active effective-dated base terms plus linked investor/class overrides; absent override fields inherit |
| Concentration | Current company and sector shares; snapshot costs do not establish realized losses |
| Holding availability | Same-date synthetic holdings without report dates use the matching approved fund report; named later dates and currency mismatches are refused |
| Sensitivity | Named changes to remaining value, holdings, weights or peers; excluded histories receive no official scenario rank |
| Evidence coverage | Sum of supported fields divided by sum of required fields; no investment-quality points |
| Case scope | Three fictional examples using existing identities; each appears only under its assigned strategy |
| Case accounting | Dated cash and debt reconcile; borrowing replacement changes only the financed amount and related interest |
| Investment gains | Proceeds plus remaining value less cost; closed-investment losses remain separate from active valuation losses; one investment and valuation per company are required |
| Winner dependence | Largest positive gain divided by total positive gains; the return without that investment excludes both its cost and value |
| Company operating value | Revenue times profit margin times valuation multiple, less net debt; zero floor, ownership share and currency conversion produce the fund's company value |
| Operating downside | Revenue falls 10%, margin falls two percentage points and the multiple falls by one, in that order; debt, ownership and currency stay fixed. Sequential effects reconcile to the changed value and case fund result. |
| Scenario boundary | Operating effects describe hypothetical changes, not historical causal attribution; the corrected fictional ownership inputs reproduce existing marks without changing case cash flows. |
| Timing scenario | A retrospective hypothetical delays historical distributions by 60 days; actual records remain unchanged |
| Source checks | Case, entity, field, unit, dates, status, document family and cited HTML text must agree |
| Calculation references | Fund, manager, scenario and case values cite their input records in evidence.json |
| Model boundary | Preview by default; authorized prose requests have budget, timeout, response, cache and evidence checks; typed-fact extraction is deferred |
| Publication | Validated candidate replaces V2 outputs; receipt is published last; interrupted retries retain the last complete recovery bundle |
| Protected files | V1 and parent data/code remain fixed; the repository file catalog and its local rendered page may refresh to register V2 documentation |

| Script | Reads | Writes |
|---|---|---|
| v2_inputs.py; v2_features.py; v2_analysis.py | V1, parent tables and policy | [04-diagnostics](04-diagnostics/README.md) |
| v2_stress.py | Accepted diagnostics and policy | [05-scenarios](05-scenarios/README.md) |
| generate_v2_cases.py | Existing identities and core diagnostics | [Case data](data/README.md) |
| v2_diligence.py; v2_analysis.py | Case tables and registered documents | Case evidence, company results and operating scenarios within the diagnostic bundle |
| run_v2.py; v2_dashboard.py | Diagnostics, scenarios and optional cases | [06-report](06-report/README.md) |

[Current verification](V2-IMPLEMENTATION-REPORT.md)
