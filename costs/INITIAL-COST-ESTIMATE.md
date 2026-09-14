# Initial cost estimate

Written for a reader who has not seen this project. It answers one question: what does it cost to read all 442 catalogued PDF reports and turn the printed numbers into data?

A large language model reads each report and types what it finds into a CSV file. The model is billed for the text sent to it and the text it returns. This estimate prices that work from five timed runs.

**The estimate below is $2,785 for one reading of the catalogue. A test on a 149-page report has since shown the method overcharges long reports by a factor of five, so treat $2,785 as a ceiling.** The test is reported in full further down, and the coefficients have not been refitted, because one test document cannot replace them.

| Scope                                              |       Interactive |    Batch pricing |
| -------------------------------------------------- | ----------------: | ---------------: |
| One reading of the catalogue                       |            $2,785 |           $1,392 |
| Two readings, each working alone                   |            $8,355 |           $4,177 |
| **Two readings plus the third-model review** | **$11,139** | **$5,570** |

442 reports, 40,788 pages, an estimated 1.11 million typed rows. That averages **$6.30 per report** for one reading, or **$25.20** for all three passes.

## The method

A model does not read a report in one step. It looks at part of a page, decides what is printed there, writes some rows, then asks the model what to do next. Each of those steps is one **turn**, and each turn is billed.

Turns are the unit because the price of a turn holds steady. Two runs whose workload differed ninefold came out at $0.006538 and $0.006531 per turn. The tool trims the conversation as it grows, so each turn bills a roughly fixed amount and the cost of a report reduces to counting its turns.

Two things drive the turn count: pages to open, and rows to write.

```text
turns = (9.09 x pages) + (0.0499 x rows)
cost  = turns x $0.006534

COST = ($0.0594 x pages) + ($0.000326 x rows)
```

Two coefficients need two equations, so two reports of opposite shape were timed. A four-page report yielding 93 rows took 41 turns. A three-page report yielding 876 rows took 71. Solving both gives 9.09 turns to open a page and 0.0499 turns to write a row.

Dividing one cost by the other gives the unit to quote on: **one page costs the same as 182 rows.**

**page-equivalents = pages + rows / 182, priced at $0.0594 each.**

The catalogue is 46,892 page-equivalents. At $0.0594 that is $2,785 for one reading, matching the two-term result, so the single rate loses no accuracy.

## The two single rates that fail

| Rate          | 4-page return | 3-page schedule |         Spread |
| ------------- | ------------: | --------------: | -------------: |
| Cost per page |       $0.0670 |         $0.1546 | **2.3x** |
| Cost per row  |      $0.00288 |        $0.00053 | **5.4x** |
| Rows per page |          23.2 |           292.0 |          12.6x |

Both rates move with density, and density across the 29 reviewed reports runs from 0.5 to 292 rows per page, a **580x** range. A page rate overcharges legal prose and undercharges financial schedules. A row rate does the reverse. Combining both into page-equivalents holds steady across that range.

## The test that the estimate failed

SRC371 is a 149-page Form 990-PF, thirty-seven times longer than any report used to build the coefficients. Both readings finished and passed both checks. Neither came close to the predicted cost.

| Run                              | Pages | Rows | Predicted turns |  Actual turns |           Ratio | Predicted cost |       Actual cost |
| -------------------------------- | ----: | ---: | --------------: | ------------: | --------------: | -------------: | ----------------: |
| SRC247, first reading            |     4 |   93 |              41 |            41 |           1.00x |          $0.27 |           $0.2680 |
| SRC058, first reading            |     3 |  876 |              71 |            71 |           1.00x |          $0.46 |           $0.4637 |
| **SRC371, first reading**  |   149 |   32 | **1,356** | **249** | **0.18x** |          $8.86 | **$4.5999** |
| **SRC371, second reading** |   149 |    8 | **1,355** |  **53** | **0.04x** |          $8.85 | **$0.3040** |

The first two runs sit on the line because the coefficients were solved from them. SRC371 is the first report priced before it was read, and the prediction was five to twenty-five times too high.

The cause is that turns per page is not one number. It falls as reports get longer and less dense:

| Report                            | Turns per page | Cost per page |
| --------------------------------- | -------------: | ------------: |
| SRC058, 3 pages, dense schedule   |          23.67 |       $0.1546 |
| SRC247, 4 pages                   |          10.25 |       $0.0670 |
| SRC371, 149 pages, first reading  | **1.67** |       $0.0309 |
| SRC371, 149 pages, second reading | **0.36** |       $0.0020 |

That is a 66x range in the coefficient that sets 87 percent of the estimate.

Two mechanisms produce it. A page the model extracts from and a page it clears are different work: the first reading of SRC371 took rows from 10 pages and cleared the other 139, and clearing a page costs one coverage row and little else. Separately, the fixed startup cost of reading the brief and the worklist is spread over 149 pages instead of three.

**One caution on the second reading of SRC371.** It cost $0.30 and wrote 8 rows where the first reading wrote 32. The two readings agreed on no row, and disagreed on the status of all 149 pages. The cheaper reading may have done less of the work, so $0.30 is a floor for a reading that may be wrong, not evidence that the work costs $0.30.

## The second reading, and why it is budgeted at twice the first

Two documents have been read twice, and both second readings cost more than the first.

| Document                  |        First reading |      Second reading | Ratio |
| ------------------------- | -------------------: | ------------------: | ----: |
| SRC058, 3 pages, 876 rows |  $0.4637 in 71 turns | $1.0791 in 92 turns |  2.3x |
| SRC371, 149 pages         | $4.5999 in 249 turns | $0.3040 in 53 turns | 0.07x |

The SRC058 second reading is the one the 2x budget rests on, and its figure is adjusted, not billed. It was charged $2.158 over 183 turns, because it spent 88 of those turns building and debugging a program to write the rows, which the brief forbids and progressive writing removes. Halving both the turns and the cost gives the $1.0791 above, and that adjusted figure is 2.3 times the first reading of the same document. Both figures are carried in `extraction-runs.csv` so the adjustment is visible.

The SRC371 second reading points the other way, at 0.07x, but it cannot lower the budget: it agreed with the first reading on no row, so its low cost may reflect work left undone. Until a second reading matches a first on the same document at a lower price, twice the first reading stands as the planning figure.

## Next step for the estimate

The current form assumes every page costs the same. The measured form is closer to:

```text
turns = fixed + (a1 x pages_extracted) + (a2 x pages_cleared) + (b x rows)
```

Separating those terms needs one more timed report of middle length, 15 to 30 pages, which costs about $0.50 to run. Until then the $2,785 stands as a ceiling, and it is most wrong on the two largest types: Financials at 61 percent of catalogue pages and Foundations_Annual at 7 percent, both long-report types.

## Estimated cost by report type

Each type uses its own measured rows per page where the reviewed slice covers it, and the catalogue pooled rate of 23.2 rows per page where it does not.

| Report type              |       Reports |            Pages |      Rows/page | Yield basis |           Est. rows |       Page-equiv |       $/report |            $ total |
| ------------------------ | ------------: | ---------------: | -------------: | ----------- | ------------------: | ---------------: | -------------: | -----------------: |
| Financials               |           221 |           24,968 |           15.9 | measured    |             395,769 |           27,142 |           7.29 |           1,611.93 |
| Institutional_Report     |            71 |            6,225 |           25.2 | measured    |             157,107 |            7,088 |           5.93 |             420.95 |
| Performance              |            46 |              934 |          171.8 | measured    |             160,414 |            1,815 |           2.34 |             107.80 |
| Quarterly_Report         |            36 |            2,265 |           85.0 | measured    |             192,606 |            3,323 |           5.48 |             197.34 |
| Fee_Report               |            12 |              328 |           88.0 | measured    |              28,864 |              487 |           2.41 |              28.89 |
| Schedule_Inv             |             9 |            1,042 |           73.3 | measured    |              76,350 |            1,461 |           9.64 |              86.79 |
| PPM                      |             7 |            1,227 |           23.2 | pooled      |              28,410 |            1,383 |          11.73 |              82.14 |
| NAV_Statement            |             6 |               74 |           28.8 | measured    |               2,128 |               86 |           0.85 |               5.09 |
| Valuation                |             6 |              218 |            8.0 | measured    |               1,744 |              228 |           2.25 |              13.52 |
| Stewardship_Proxy_Report |             5 |              202 |            4.0 | measured    |                 802 |              206 |           2.45 |              12.26 |
| Subscription             |             4 |              158 |            0.5 | measured    |                  73 |              158 |           2.35 |               9.41 |
| Cash_Flow_Notice         |             4 |               25 |           23.2 | pooled      |                 579 |               28 |           0.42 |               1.67 |
| Foundations_Annual       |             4 |            2,823 |           23.2 | pooled      |              65,365 |            3,182 |          47.24 |             188.98 |
| LPA                      |             3 |              185 |            0.6 | measured    |                 112 |              186 |           3.67 |              11.02 |
| PCAP                     |             3 |                7 |           39.5 | measured    |                 276 |                9 |           0.17 |               0.51 |
| DDQ                      |             3 |               86 |            2.2 | measured    |                 192 |               87 |           1.72 |               5.17 |
| Side_Letter              |             2 |               21 |           23.2 | pooled      |                 486 |               24 |           0.70 |               1.41 |
| **Total**          | **442** | **40,788** | **27.2** |             | **1,111,278** | **46,892** | **6.30** | **2,784.87** |

Financials alone is 58 percent of the bill on 61 percent of the pages. Pages account for 87 percent of the total and rows for 13 percent, so **the bill is set by how many pages are opened, not by how much is taken from them.** SRC371 is the sharpest case: 149 pages against the Foundations_Annual line above, which prices that type at $47.24 per report while the timed reading cost $4.60.

## Cost by report shape

| Shape                   | Pages |  Rows | Page-equiv |  Cost |
| ----------------------- | ----: | ----: | ---------: | ----: |
| Dense schedule          |     3 |   876 |        7.8 | $0.46 |
| Small NAV statement     |     4 |    93 |        4.5 | $0.27 |
| Sparse legal agreement  |    48 |    29 |       48.2 | $2.86 |
| Median catalogue report |    64 | 1,482 |       72.1 | $4.28 |

A 3-page schedule yielding 876 rows costs a sixth of a 48-page agreement yielding 29. Density lowers the cost; it does not raise it.

## Batch pricing

Batch endpoints run at half list price. That was checked across four providers, and input, output and cache-read rates were all half, with no exception found.

That halves every figure in the summary table, and the condition attached is structural. **The timed runs are interactive loops of 41 to 249 turns, in which each turn depends on the result of the previous one. Those cannot be submitted as a batch.** Taking the discount means rebuilding the first pass into self-contained per-page requests, each carrying the page text, the positional grid, the page image and the field list, with the checks run afterwards, not during.

That rebuild is worth more than the 50 percent, because it also removes most of the per-page reading cost that makes up 87 percent of the current bill. It gives up the model's ability to re-read a page it found confusing, and it defers the checks, which matters because the checks have twice accepted work that later proved unusable: one reading of SRC058 whose row labels were all wrong, and both readings of SRC371, which passed every check while agreeing on no row and disagreeing on the status of all 149 pages. The batch column is a floor on a rebuilt first pass, not a discount available on the current one.

## Confidence and limits

| Item                              | Status                                                                                                                                                               |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cost per turn                     | Measured on two runs, steady to three decimals                                                                                                                       |
| The two coefficients              | **Failed an out-of-sample test at 149 pages, overshooting by 5.4x. Not refitted, because one test report cannot replace them**                                 |
| Predictive check, short reports   | One prediction at 4.0 percent error                                                                                                                                  |
| Predictive check, long reports    | One prediction at 444 percent error                                                                                                                                  |
| Output quality                    | The first reading of SRC058 reproduced an earlier independent reading on every printed value                                                                         |
| Row projection                    | Each type's measured yield applied to its unread pages. This is a projection, not a count. The four pooled-rate types hold 9 percent of catalogue pages              |
| Second reading at twice the first | Rests on one adjusted measurement, the SRC058 second reading at 2.3x. Its billed figure was halved because 88 of its 183 turns went on a generator the brief forbids |
| Third-model review                | Assumed equal to one reading and never timed. It scales with disagreements, not with pages, so it is the softest figure here                                         |
| Batch column                      | Requires the rebuild described above                                                                                                                                 |
| Prices                            | Move often, and one model's input price fell 80 percent during this study. The law is written in turns, so only the $0.006534 per turn needs repricing               |

## Throughput

Spend is not the binding constraint. At the measured 7.5 minutes per page, one reading of the catalogue is 211 days of serial compute. The SRC371 test lowers this too: that reading ran at 0.32 minutes per page.

| Parallel readers | Days per reading | Days, all three passes |
| ---------------: | ---------------: | ---------------------: |
|               10 |             21.1 |                   84.5 |
|               20 |             10.6 |                   42.2 |
|               50 |              4.2 |                   16.9 |
