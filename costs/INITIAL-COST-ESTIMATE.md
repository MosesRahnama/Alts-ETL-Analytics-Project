# Initial cost estimate

What it costs to extract the whole 442-document corpus, derived from three measured runs rather than from a quoted rate.

| Scope | Interactive | Batch pricing |
|---|---:|---:|
| One extraction lane | $2,785 | $1,392 |
| Two blind lanes | $8,355 | $4,177 |
| **Two lanes plus adjudication** | **$11,139** | **$5,570** |

442 documents, 40,788 pages, an estimated 1.11 million extracted rows. Averages to **$6.30 per document** for one lane, or **$25.20** for the full three-pass pipeline.

## The metric question

Neither cost per page nor cost per row survives contact with the corpus. Measured on two documents read by the same model under the same brief:

| Metric | 4-page NAV statement | 3-page performance schedule | Spread |
|---|---:|---:|---:|
| Cost per page | $0.0670 | $0.1546 | **2.3x** |
| Cost per row | $0.00288 | $0.00053 | **5.4x** |
| Row density | 23.2 rows/page | 292.0 rows/page | 12.6x |

Both single-factor metrics are artefacts of density, and density across the 29 already-extracted documents ranges from 0.5 to 292 rows per page, a **580x** spread. A per-page quote overcharges legal prose and undercharges financial schedules; a per-row quote does the reverse. Neither can price a mixed corpus.

Cost is driven by two separate things: opening a page is expensive, and writing a row once the page is open is nearly free.

```text
turns = 9.09 x pages + 0.0499 x rows
cost  = turns x $0.006534

COST = $0.0594 x pages + $0.000326 x rows
```

The coefficient ratio gives the unit that does work: **one page costs the same as 182 rows.** That yields a single number to quote on:

**page-equivalents = pages + rows / 182, priced at $0.0594 each.**

The corpus is 46,892 page-equivalents. At $0.0594 that is $2,785 for one lane, identical to the two-term result, so the simplification gives up no accuracy.

## Estimation rationale

Three runs on two documents, chosen to be opposite in shape so the two coefficients could be separated rather than assumed.

| Run | Document | Pages | Rows | Turns | Cost | $/turn | Values correct |
|---|---|---:|---:|---:|---:|---:|---|
| Lane A | NAV statement | 4 | 93 | 41 | $0.2680 | $0.00654 | 93 of 93 |
| Lane A | Performance schedule | 3 | 876 | 71 | $0.4637 | $0.00653 | 866 of 866 shared cells |
| Lane B | Performance schedule | 3 | 876 | 92 | $1.0791 | $0.01173 | 876 of 876 |

Four things make this an estimate rather than a guess.

**Cost per turn is constant.** The two lane-A runs differ 9.4x in row count and land on the same per-turn price to three decimals. The harness compacts context, so each turn bills a roughly fixed amount and cost reduces to counting turns.

**The law predicted before it was fitted.** Built on the first document alone, it predicted the second at $0.445 against an actual $0.4637, an error of **4.0%**.

**Output was verified, not assumed.** Lane A reproduced a prior independent extraction of the same document at 100% agreement on every printed value. A cost figure for output that was never checked would be worthless.

**Row counts are projected from measured yield.** The 1.11M row figure applies each document type's measured rows-per-page to its unextracted pages, not a flat average.

Lane B figures are halved from what was billed. It spent 48% of its turns building and debugging a row generator before writing anything, an approach the brief forbids and a progressive-write rule eliminates. Billed was 183 turns and $2.158; the table carries the recoverable half.

## Estimation matrix

Per document type, using each type's own measured yield where the extracted slice covers it and the corpus pooled rate of 23.2 rows/page where it does not.

| Document type | Docs | Pages | Rows/page | Yield basis | Est. rows | Page-equiv | $/doc | $ total |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| Financials | 221 | 24,968 | 15.9 | measured | 395,769 | 27,142 | 7.29 | 1,611.93 |
| Institutional_Report | 71 | 6,225 | 25.2 | measured | 157,107 | 7,088 | 5.93 | 420.95 |
| Performance | 46 | 934 | 171.8 | measured | 160,414 | 1,815 | 2.34 | 107.80 |
| Quarterly_Report | 36 | 2,265 | 85.0 | measured | 192,606 | 3,323 | 5.48 | 197.34 |
| Fee_Report | 12 | 328 | 88.0 | measured | 28,864 | 487 | 2.41 | 28.89 |
| Schedule_Inv | 9 | 1,042 | 73.3 | measured | 76,350 | 1,461 | 9.64 | 86.79 |
| PPM | 7 | 1,227 | 23.2 | pooled | 28,410 | 1,383 | 11.73 | 82.14 |
| NAV_Statement | 6 | 74 | 28.8 | measured | 2,128 | 86 | 0.85 | 5.09 |
| Valuation | 6 | 218 | 8.0 | measured | 1,744 | 228 | 2.25 | 13.52 |
| Stewardship_Proxy_Report | 5 | 202 | 4.0 | measured | 802 | 206 | 2.45 | 12.26 |
| Subscription | 4 | 158 | 0.5 | measured | 73 | 158 | 2.35 | 9.41 |
| Cash_Flow_Notice | 4 | 25 | 23.2 | pooled | 579 | 28 | 0.42 | 1.67 |
| Foundations_Annual | 4 | 2,823 | 23.2 | pooled | 65,365 | 3,182 | 47.24 | 188.98 |
| LPA | 3 | 185 | 0.6 | measured | 112 | 186 | 3.67 | 11.02 |
| PCAP | 3 | 7 | 39.5 | measured | 276 | 9 | 0.17 | 0.51 |
| DDQ | 3 | 86 | 2.2 | measured | 192 | 87 | 1.72 | 5.17 |
| Side_Letter | 2 | 21 | 23.2 | pooled | 486 | 24 | 0.70 | 1.41 |
| **Total** | **442** | **40,788** | **27.2** | | **1,111,278** | **46,892** | **6.30** | **2,784.87** |

Financials alone is 58% of the bill on 61% of the pages. Pages contribute 87% of total cost and rows 13%, so **the bill is set by how many pages are opened, not by how much is pulled from them.**

## Cost by document shape

The same law, applied to four real shapes, shows why one flat rate cannot work.

| Shape | Pages | Rows | Page-equiv | Cost |
|---|---:|---:|---:|---:|
| Dense schedule | 3 | 876 | 7.8 | $0.46 |
| Small NAV statement | 4 | 93 | 4.5 | $0.27 |
| Sparse legal agreement | 48 | 29 | 48.2 | $2.86 |
| Median corpus report | 64 | 1,482 | 72.1 | $4.28 |

A 3-page schedule yielding 876 rows costs a sixth of a 48-page agreement yielding 29. Density is the cost saver, not the cost driver.

## Batch pricing

Batch endpoints are half list price. Verified across four providers: input, output and cache-read rates all at 0.50x, with no exception found.

That halves every figure in the summary table, and the condition attached is architectural rather than commercial. **The measured runs are interactive agent loops of 41 to 92 turns, where each turn depends on the previous tool result. Those cannot be submitted as a batch.** Capturing the discount requires restructuring the first pass into self-contained per-page requests, each carrying the page text, the positional grid, the page image and the extraction contract, with the mechanical validators run afterwards instead of during.

That restructuring is worth more than the 50%, because it also removes most of the 9.09 turns per page of fixed reading cost, which is 87% of the current bill. It trades away the agent's ability to re-read a page it found confusing, and it defers validation, which matters given that two of the observed failure modes were self-certified page completions that passed the mechanical gates. The batch column is therefore a floor on a redesigned first pass, not a discount available on today's pipeline.

## Confidence and limits

| Item | Status |
|---|---|
| Cost per turn | Measured twice, stable to three decimals |
| Two coefficients | Fitted on two documents from one model. A third shape would test rather than fit them |
| Predictive check | One out-of-sample prediction at 4.0% error |
| Output quality | Verified against an independent prior extraction at 100% value agreement |
| Row projection | Per-type yield applied to unextracted pages, not a count. The four pooled-rate types carry 9% of corpus pages |
| Second lane at 2x | Budget assumption. The one adjusted measurement came in at 2.3x |
| Adjudication | Assumed equal to one lane, never measured. It scales with conflicts rather than pages, so it is the softest figure here |
| Batch column | Requires the redesign described above |
| Prices | Move often, and one model's input price fell 80% during this study. The law is expressed in turns; only the $0.006534 per turn needs repricing |

## Throughput

Spend is not the binding constraint. At the measured 7.5 minutes per page, one lane across the corpus is 211 days of serial compute.

| Parallel agents | Days per lane | Days, all three passes |
|---:|---:|---:|
| 10 | 21.1 | 84.5 |
| 20 | 10.6 | 42.2 |
| 50 | 4.2 | 16.9 |
