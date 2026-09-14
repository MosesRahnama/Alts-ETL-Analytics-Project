# Investment-manager scoring upgrade

Written for a reader unfamiliar with investment-manager scoring.

The upgraded dashboard compares managers by historical fund results, cash recovery and performance against public markets, then examines individual investments and management evidence. The comparison uses fictional data; documented real-source values remain separate and receive no manager rating.

| Research proposal | Decision |
|---|---|
| Combine performance, team, governance and other qualities into one rating | Retain the established 60% total-value / 40% cash-return score. The supplied data do not justify additional weights. |
| Identify results dependent on remaining valuations | Add cash recovery, capital break-even and benchmark break-even values for every supported fund. |
| Examine company-level performance | Add realized losses, largest-gain dependence and a named operating downside to the three fictional cases. |
| Compare manager repeatability and risk | Add three-manager comparison, fund-level score contributions and rank ranges under existing value/weight scenarios. |
| Separate investment quality from information quality | Keep source coverage, governance findings and financial results as distinct measures. |

Both supplied [research reports](research/README.md) were reviewed in full. The implementation retains the fund-versus-investment distinction in the [Institutional Limited Partners Association performance template](https://ilpa.org/industry-guidance/templates-standards-model-documents/ilpa-templates-hub/ilpa-performance-template/). Company inputs follow the revenue, profit margin, valuation multiple, debt and currency categories in [MSCI's company analysis](https://www.msci.com/data-and-analytics/private-asset-solutions/private-capital-transparency); the implemented calculation is a hypothetical downside, not historical attribution.

| Addition | Calculation and use |
|---|---|
| Capital recovery | Contributions less distributions gives the cash still required to recover capital. Dividing that gap by remaining value identifies how much of the valuation is required. |
| Benchmark wealth | Each payment grows by its matched public-market return through the comparison date; remaining value plus grown distributions less grown contributions measures excess value. |
| Return conventions | Direct Alpha measures annualized excess return against the benchmark. The original effective rate is unchanged; the continuous rate uses the natural logarithm of one plus that rate. Neither establishes market-risk-adjusted manager skill. |
| Score contributions | Each fund's total-value and cash-return points sum to the historical manager score; the dashboard compares up to three ranked managers within one strategy. |
| Investment dependence | Closed-investment cash losses remain separate from active valuations. Removing the largest-gain investment removes both its cost and value. |
| Operating downside | Revenue falls 10%, profit margin falls two percentage points, and the valuation factor falls by one. The ordered effects reconcile to the changed company value and case fund result. |
| Printable summary | Score components, rank range, capital recovery, benchmark counts and available case downside accompany the existing summary. |

| Verification on 2026-09-12 | Result |
|---|---|
| Existing financial results | 7,200 fund cells and 1,920 manager cells match the previous version, including returns, scores, ranks and qualifying fund lists. |
| Case valuation repair | All 11 operating-input calculations match their company marks; only fictional ownership assumptions and generator labels changed. Costs, proceeds, dates and marks are unchanged. |
| Input repairs | Six findings addressed: valuation consistency, currency/date admission, conflicting reports, fund-series ordering, case identities/attribution and manager-strategy model context. |
| Calculation controls | Capital recovery, benchmark wealth, score contributions and operating changes reconcile; zero, missing, invalid and non-finite values have named tests. |
| Build and tests | 123 tests and 27 build checks pass; [executed verification](V2-VALIDATION.csv) records the commands and boundaries. |
| Browser | Seven views, 32 strategy/status combinations, three cases and 33 links pass; mobile layout and the expanded print summary were checked. |
| Retained V1 verifier | Its original strict byte check rejects eight newline-format differences. V2 verifies those same files through newline-only equivalence; changed content still fails. No V1 file was rewritten. |
| Scope | V1 and parent data/code unchanged; no database rebuild, model call, commit, push or deployment. |

| Output | Population |
|---|---|
| Funds | 800 supplied; 693 supported on the common date; 693 reconciled holding records |
| Manager-strategy groups | 640: 38 ranked, 325 partial histories, 277 insufficient histories |
| Benchmark wealth | 546 supported comparisons; 147 current non-US-dollar funds remain without a compatible benchmark |
| Comparisons and scenarios | 16,898 comparison-membership rows; 4,093 fund and 494 manager scenario rows |
| Evidence | 10,691 fund/manager/scenario references; 128 case references; 5,120 field-coverage rows |
| Fictional cases | Three cases; 11 investments and valuations; 36 events; six documents; 31 resolved facts from 32 submitted statements |

The company downside is a sensitivity calculation with debt, ownership and currency fixed. Its effects depend on the declared order; they are neither a forecast nor proof of past value creation. Generated manager histories do not validate predictive manager selection.

[Calculation rules](ARCHITECTURE.md) · [Commands and files](README.md) · [Repair details](DIAGNOSTICS.csv) · [Work history](V2-LIVE-LEDGER.csv)
