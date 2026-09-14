"""Warehouse table explanations and lineage helpers for the public dashboard.

Loads table purposes, plain-language explanations, concrete examples, and
derivation chains across all DuckDB tables and views.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPLANATIONS_CSV = ROOT / "audit" / "warehouse-purpose.csv"
LINEAGE_CSV = ROOT / "docs" / "CSV-LINEAGE.csv"

EMBEDDED_EXPLANATIONS: dict[str, dict] = {
  "alts/benchmark_returns": {
    "database": "alts",
    "object": "benchmark_returns",
    "object_type": "table",
    "rows": 42876,
    "columns": 13,
    "role": "Analytical input",
    "plain_title": "Market returns used for comparison",
    "plain_contents": "Each row records the gain or loss of a named comparison market over a stated day or month, with its currency and source.",
    "plain_separation": "Many funds can be compared with the same market series. Keeping that series once avoids repeating every market return for each fund.",
    "plain_example": "The same market return can be used when comparing the payments of several different funds.",
    "index_contents": "Each row is: one day's or one month's return of a public market index used for comparison.\nIt holds: which index, the date, daily or monthly, the return, the currency, and where the figure came from.\nExample: on 2002-02-07 VTI, a fund that tracks the whole US stock market, returned -0.42%.\nWhy its own table: many funds are compared with the same index, so its history is stored once and not copied beside every fund.",
    "csv_source": "data/csv/benchmark_returns.csv"
  },
  "alts/defect_injections": {
    "database": "alts",
    "object": "defect_injections",
    "object_type": "table",
    "rows": 12,
    "columns": 12,
    "role": "Deliberate-error record",
    "plain_title": "The errors deliberately added to test copies",
    "plain_contents": "Each row identifies a field changed in a separate test copy, its original and changed values, and the check expected to detect it.",
    "plain_separation": "The data copy records the changed amount. This table records the intended error, which is compared with the check results to measure detection.",
    "plain_example": "A deliberately altered balance has an expected check recorded here; the published fund-balance table retains its own data.",
    "index_contents": "Each row is: one error the project planted on purpose in a separate test copy of the data, to see whether the checks catch it.\nIt holds: which record and field, the correct value, the planted wrong value, the kind of error, and which check should catch it.\nExample: FUND_0002's value was flipped from 61,408,542 to -61,408,543, and rule R01 (a balance cannot be negative) should flag it.\nWhy its own table: the planted errors live in a separate file, data/integrated/defect-periods.csv, never in the real tables. This list is the answer key used to score the checks.",
    "csv_source": "data/csv/defect_injections.csv"
  },
  "alts/document_fund_map": {
    "database": "alts",
    "object": "document_fund_map",
    "object_type": "table",
    "rows": 156,
    "columns": 27,
    "role": "Reviewed document identity",
    "plain_title": "Evidence that a report names a particular fund",
    "plain_contents": "Each row connects a source report to a reviewed fund identity and records the printed name, page and supporting words.",
    "plain_separation": "A report can name several funds, and a fund can appear in several reports. A separate relationship table records each supported connection.",
    "plain_example": "One pension report listing several funds needs one report-to-fund record for each reviewed relationship.",
    "index_contents": "Each row is: one confirmed link between a report and a fund the report covers.\nIt holds: the report, the fund, the fund name as printed, the page and quote, whether the report shows the whole fund or one investor's stake, and the investor's name.\nExample: report SRC035 covers Madrona Venture Fund III, L.P., as a stake held by the Oregon Growth Account Private Equity Program.\nWhy its own table: one report can cover many funds and one fund can appear in many reports, so each confirmed pairing is its own row.",
    "csv_source": "data/csv/document_fund_map.csv"
  },
  "alts/document_manager_map": {
    "database": "alts",
    "object": "document_manager_map",
    "object_type": "table",
    "rows": 33,
    "columns": 18,
    "role": "Document identity",
    "plain_title": "Evidence that a report names a management company",
    "plain_contents": "Each row connects a report to a named management company, with the page and words supporting that connection.",
    "plain_separation": "A company can be named independently of any particular fund. This relationship records the company attribution at its own level.",
    "plain_example": "A manager's annual report can support a company relationship even when a particular statement concerns the business as a whole.",
    "index_contents": "Each row is: one confirmed link between a report and a fund manager named in it.\nIt holds: the report, the manager ID, the name as printed, the page and the quote.\nExample: report SRC606 names Antares Capital as the manager behind Antares Private Credit Fund (ABDC).\nWhy its own table: naming a manager is a fact about the company, and it does not say which fund a number belongs to.",
    "csv_source": "data/csv/document_manager_map.csv"
  },
  "alts/fund_cashflows": {
    "database": "alts",
    "object": "fund_cashflows",
    "object_type": "table",
    "rows": 6616,
    "columns": 26,
    "role": "Analytical input",
    "plain_title": "Payments into and out of funds",
    "plain_contents": "Each row records a dated payment, its type, amount, currency and source or generation label.",
    "plain_separation": "Two funds can have the same year-end balance but receive money on different dates. Payment dates are needed to calculate returns that account for the time money was invested.",
    "plain_example": "Two contributions made in different months remain two payment records even when one balance row reports their combined total.",
    "index_contents": "Each row is: one dated payment between investors and a fund.\nIt holds: the type (a capital call is money sent in; a distribution is money paid back), the amount, the currency, the date, and whether it came from a report or was generated.\nExample: FUND_0201 called $18,375,000 from its investors on 2015-01-04. This row is generated and marked SYNTHETIC.\nWhy its own table: an annual return depends on when each payment happened, and a year-end balance cannot show that. 29 payments come from reports; the other 6,587 are generated.",
    "csv_source": "data/csv/fund_cashflows.csv"
  },
  "alts/fund_holdings": {
    "database": "alts",
    "object": "fund_holdings",
    "object_type": "table",
    "rows": 2847,
    "columns": 32,
    "role": "Compatibility table",
    "plain_title": "Legacy fund holding projection",
    "plain_contents": "Each row fits a normalized position into the older fund-only holding columns. Source positions appear only when the reviewed owner is a fund; generated rows retain the same legacy shape.",
    "plain_separation": "The normalized fund_position table is the source of truth. This compatibility table remains for older consumers and does not relabel market value as fair value or portfolio weight as ownership.",
    "plain_example": "A reviewed Permanent University Fund position can appear here because its owner is a fund. A holding whose owner cannot fit the legacy fund field stays in fund_position only.",
    "index_contents": "Compatibility projection from normalized positions into the older fund-only holding columns. The authoritative source positions are in fund_position. Market value, fair value, portfolio weight, and ownership remain distinct.",
    "csv_source": "data/csv/fund_holdings.csv"
  },
  "alts/fund_master": {
    "database": "alts",
    "object": "fund_master",
    "object_type": "table",
    "rows": 945,
    "columns": 29,
    "role": "Analytical input",
    "plain_title": "The list of funds",
    "plain_contents": "Each row identifies one fund and records its name, manager, investment type, start year and supported or generated attributes.",
    "plain_separation": "One fund can have many reporting dates and payments. Keeping its identity here avoids treating every dated record as a new fund.",
    "plain_example": "The same fund record is referenced by its year-end balances, individual payments and investment holdings.",
    "index_contents": "Each row is: one fund. This is the master list of funds that every other table in this database points to.\nIt holds: the fund's name, its manager, its strategy (the kind of investing it does), its vintage year (the year it started investing), currency, size and status.\nExample: FUND_0954 is Thoma Bravo Fund XII, L.P., managed by Thoma Bravo, L.P., vintage 2023, taken from report SRC407, page 6.\nWhy its own table: a fund has one identity but many dated balances and payments. Its details are stored once here. Rows marked EXTRACTED come from reports; rows marked SYNTHETIC were generated by the project to fill gaps and are labelled as such.",
    "csv_source": "data/csv/fund_master.csv"
  },
  "alts/fund_metrics": {
    "database": "alts",
    "object": "fund_metrics",
    "object_type": "table",
    "rows": 3764,
    "columns": 14,
    "role": "Calculated result",
    "plain_title": "Fund performance calculated by the project",
    "plain_contents": "Each row records one calculated result, such as value relative to money paid in or an annual return based on payment dates.",
    "plain_separation": "The source tables retain reported amounts and returns. This table records the project's calculation, its formula and the records used.",
    "plain_example": "A calculated total-value multiple divides money returned plus remaining value by money paid in; the source's reported multiple remains a source fact.",
    "index_contents": "Each row is: one number the project calculated for a fund on a date.\nIt holds: the measure, the result, the formula used, and the IDs of the records it was calculated from.\nExample: FUND_1030's calculated annual return (XIRR, which counts the dates of its payments) is 5.44% at 2026-06-05.\nWhy its own table: calculated results must never be confused with numbers printed in reports, which stay in fund_periods and fund_observations. These results use generated data; results from report data alone are in data/extracted/fund-level/fund_metrics.csv.",
    "csv_source": "data/csv/fund_metrics.csv"
  },
  "alts/fund_observations": {
    "database": "alts",
    "object": "fund_observations",
    "object_type": "table",
    "rows": 3857,
    "columns": 40,
    "role": "Fund-specific evidence",
    "plain_title": "Individual source facts assigned to funds",
    "plain_contents": "Each row holds a supported fund measurement with its printed value, meaning, date, investor or share scope and source reference.",
    "plain_separation": "Some valid fund facts fit outside a single reporting-date balance row. This table retains those facts before the balance and payment tables select values for their narrower purposes.",
    "plain_example": "A fund return covering three years remains a dated source measurement even when it is unsuitable for a one-year balance comparison.",
    "index_contents": "Each row is: one report number that belongs to a specific fund, with its date and scope.\nIt holds: the fund and investor, the value as printed and as a number, what it measures, its date, its units, whether it covers the whole fund or one investor's stake, and the source page.\nExample: report SRC063, page 1, gives a 1.0% return for FUND_0305, investor LP_0021, at June 30, 2023, measured time-weighted and after fees.\nWhy its own table: some real numbers, such as a three-year return, do not fit a single year-end balance row. They are kept here so they are not lost.",
    "csv_source": "data/csv/fund_observations.csv"
  },
  "alts/fund_periods": {
    "database": "alts",
    "object": "fund_periods",
    "object_type": "table",
    "rows": 1392,
    "columns": 59,
    "role": "Analytical input",
    "plain_title": "A fund's balances at a reporting date",
    "plain_contents": "Each row puts together dated fund or investor-position amounts: money promised, paid in, returned and still invested, plus reported returns.",
    "plain_separation": "Balances describe the position at a date. Individual payments need their own dates, and the fund's identity needs only one fund record.",
    "plain_example": "A year-end balance row combines cumulative money paid in and returned; the payment table retains the dates of the separate payments.",
    "index_contents": "Each row is: one fund, or one investor's stake in a fund, at one reporting date, with all its balances together. This is the main input to the fund calculations.\nIt holds: money promised, money paid in so far, money paid back so far, current value (NAV), money still to be asked for, the multiples and returns, and what changed during the period.\nExample: Halderman Farmland Separate Account at December 31, 2020, from report SRC457, page 10: $75 million promised, worth $66.2 million, a 1.13 multiple (money back plus value, divided by money in) and a 3.5% annual return.\nWhy its own table: balances describe a position on a date, which needs its own row per date. 451 rows come from reports and 941 are generated; each row says which.",
    "csv_source": "data/csv/fund_periods.csv"
  },
  "alts/fund_term_clauses": {
    "database": "alts",
    "object": "fund_term_clauses",
    "object_type": "table",
    "rows": 953,
    "columns": 22,
    "role": "Legal detail",
    "plain_title": "Contract terms that need words and conditions",
    "plain_contents": "Each row keeps a contract clause, its scope, dates and any investor-specific exception.",
    "plain_separation": "Fixed columns for fee rates and fund duration cover only some contract terms. Clauses about rights or exceptions require text and conditions.",
    "plain_example": "A special reporting right for one investor remains separate from the fund's standard management-fee rate.",
    "index_contents": "Each row is: one contract clause for a fund or one investor, stated in words.\nIt holds: the clause title, its wording, who it applies to, whether it overrides the standard term, and the dates it is in force.\nExample: FUND_0134 has an illustrative key-person clause: investing pauses if a key person leaves. This row is generated and marked SYNTHETIC; no report states it.\nWhy its own table: rights and exceptions need words and conditions, and fixed columns such as fee rate cannot hold them.",
    "csv_source": "data/csv/fund_term_clauses.csv"
  },
  "alts/fund_terms": {
    "database": "alts",
    "object": "fund_terms",
    "object_type": "table",
    "rows": 942,
    "columns": 29,
    "role": "Economic terms",
    "plain_title": "Fee rates and other financial rules",
    "plain_contents": "Each row records a fund's or investor's applicable fee rates, profit-sharing rules, duration and related financial terms.",
    "plain_separation": "These are agreed rules, while balances and payments record amounts at dates. Different investors can also have different terms.",
    "plain_example": "An annual fee rate and an investor-specific fee agreement remain distinct from the fee amount actually paid.",
    "index_contents": "Each row is: one fund's money rules from its contract, or one investor's special version of them.\nIt holds: the management fee rate and what it is charged on, the manager's share of profits (carry), the return investors get first (hurdle), payout order, fund life and extensions, and expense caps.\nExample: FUND_0623 charges 1.94% a year on money promised, takes 20% of profits above an 8% hurdle, and runs 10 years plus 2. This row is generated and marked SYNTHETIC.\nWhy its own table: agreed rules differ from amounts actually paid, and investors in one fund can have different rules. One row comes from a report; the other 941 are generated.",
    "csv_source": "data/csv/fund_terms.csv"
  },
  "alts/manager_master": {
    "database": "alts",
    "object": "manager_master",
    "object_type": "table",
    "rows": 121,
    "columns": 14,
    "role": "Manager reference",
    "plain_title": "The list of fund management companies",
    "plain_contents": "Each row identifies a management company and records its name and available company details.",
    "plain_separation": "A manager can run several funds. Company information belongs in one manager record, while each fund keeps its own investment record.",
    "plain_example": "Two funds run by the same company share a manager reference but keep separate balances and returns.",
    "index_contents": "Each row is: one fund manager, meaning the company that runs funds.\nIt holds: the manager's name, legal name, location, website and currency.\nExample: MGR_0115 is reo® service, taken from report SRC339, page 14.\nWhy its own table: one manager runs several funds, so its details are stored once and each fund points to it.",
    "csv_source": "data/csv/manager_master.csv"
  },
  "alts/manager_observations": {
    "database": "alts",
    "object": "manager_observations",
    "object_type": "table",
    "rows": 55,
    "columns": 31,
    "role": "Manager-specific evidence",
    "plain_title": "Figures about management companies",
    "plain_contents": "Each row records a company-level measurement, such as the assets a manager oversees, together with its date and source.",
    "plain_separation": "A manager's total can cover many funds. Assigning the same company total to each fund would count the amount several times.",
    "plain_example": "A company's total assets under management stays separate from the assets of one fund it manages.",
    "index_contents": "Each row is: one number about a manager as a whole, not about any one fund.\nIt holds: the manager, the measure, the date, the value and the source page.\nExample: report SRC339, page 14, says the reo® stewardship service covered 34 countries from July 2024 to June 2025.\nWhy its own table: a manager's total covers many funds, and copying it onto each fund would count it several times.",
    "csv_source": "data/csv/manager_observations.csv"
  },
  "alts/pme_results": {
    "database": "alts",
    "object": "pme_results",
    "object_type": "table",
    "rows": 1882,
    "columns": 15,
    "role": "Calculated result",
    "plain_title": "Fund results compared with a market investment",
    "plain_contents": "Each row records a comparison between a fund and a public-market investment using the dates of the fund's payments.",
    "plain_separation": "An absolute fund return and a market comparison answer different questions. The comparison also needs a named market and its return history.",
    "plain_example": "The calculation compares the fund result with investing the same amounts in the selected market on the same dates.",
    "index_contents": "Each row is: one comparison of a fund with a public stock index, as if the same money had gone into the index on the same dates.\nIt holds: the comparison result, which index, the formula, and the records used.\nExample: FUND_0955 scores 0.44 against the VTI stock-market fund at 2026-06-05. A score below 1 means the index would have done better.\nWhy its own table: whether a fund made money and whether it beat the market are different questions with different inputs. These results use generated data.",
    "csv_source": "data/csv/pme_results.csv"
  },
  "alts/portfolio_allocations": {
    "database": "alts",
    "object": "portfolio_allocations",
    "object_type": "table",
    "rows": 941,
    "columns": 25,
    "role": "Portfolio result",
    "plain_title": "Proposed shares of a fund portfolio",
    "plain_contents": "Each row records the proposed share assigned to one fund, together with limits and assumptions used in the portfolio calculation.",
    "plain_separation": "These are allocation proposals. Historical fund balances record positions already reported, and one fund can appear in several different proposals.",
    "plain_example": "The same fund can receive different shares in an equal-weight proposal and a proposal based on withdrawal needs.",
    "index_contents": "Each row is: one fund's proposed share of a model portfolio that the project calculated.\nIt holds: the target share, the smallest and largest share allowed, money promised, current value, expected return, risk, and how easily the stake can be sold.\nExample: in the demo portfolio every one of the 941 funds gets the same target share, 1/941 or about 0.11%, with a cap of 5%; FUND_0955 is one of them.\nWhy its own table: these are proposals the project made, not holdings any report shows.",
    "csv_source": "data/csv/portfolio_allocations.csv"
  },
  "alts/quality_results": {
    "database": "alts",
    "object": "quality_results",
    "object_type": "table",
    "rows": 36585,
    "columns": 16,
    "role": "Analytical input and check detail",
    "plain_title": "The results of checks on the records",
    "plain_contents": "Each row records one check on one data record, the expected result, the observed result and whether it passed, failed or was skipped.",
    "plain_separation": "One fund record can face many checks. A separate results table records each check and its reason while leaving the source amounts available for review.",
    "plain_example": "A balance row can pass a currency check and fail a calculation check; both results remain visible.",
    "index_contents": "Each row is: one check run on one record, and its outcome.\nIt holds: which rule, how serious it is, pass, fail or skip, the value found, the value expected, the allowed gap, and the reason.\nExample: record FPRINT_B4A1FCC91F0029F974F0 passes rule R06: money promised (48,700,000) equals money paid in plus money still to be asked for.\nWhy its own table: one record faces many checks, and each result is its own row. The calculations read these results to decide which records they may use.",
    "csv_source": "data/csv/quality_results.csv"
  },
  "alts/synthetic_parameters": {
    "database": "alts",
    "object": "synthetic_parameters",
    "object_type": "table",
    "rows": 10,
    "columns": 17,
    "role": "Generation record",
    "plain_title": "Assumptions used to generate additional data",
    "plain_contents": "Each row records a parameter used to generate data, such as a chosen return, fee rate or investment-life assumption, with its stated basis.",
    "plain_separation": "One assumption can affect many generated rows. Keeping the assumption record apart from those rows supports review of the common input.",
    "plain_example": "A fee-rate assumption can be reused across generated fund records; its value and justification stay available here.",
    "index_contents": "Each row is: one assumption used to generate the fill-in data.\nIt holds: the assumption's name, its value, its unit, and its basis: taken from the report data, or simply declared.\nExample: dpi_median = 0.395, the middle value of the real funds' ratio of money paid back to money paid in.\nWhy its own table: one assumption shapes thousands of generated rows, so it is written down once where anyone can check it.",
    "csv_source": "data/csv/synthetic_parameters.csv"
  },
  "alts/vw_analytics_ready_fund_periods": {
    "database": "alts",
    "object": "vw_analytics_ready_fund_periods",
    "object_type": "view",
    "rows": 1390,
    "columns": 59,
    "role": "Inspection view",
    "plain_title": "Active balance records with recorded errors excluded",
    "plain_contents": "This saved query lists active fund-period rows whose period checks contain zero error-level failures.",
    "plain_separation": "The full period table retains every record. This filtered display is an inspection shortcut; the calculation code also checks required amounts and whether the record belongs in that calculation.",
    "plain_example": "An active row can appear here while still lacking an amount needed for a return calculation.",
    "index_contents": "Each row is: one active fund_periods row with no failed error-level check.\nIt holds: the same 59 columns as fund_periods.\nExample: 1,390 of the 1,392 fund_periods rows pass this filter.\nWhy a view: A view is a saved question: it stores nothing and recalculates from other tables each time it is opened. Its name promises more than it does: the calculation code applies further checks of its own.",
    "csv_source": ""
  },
  "alts/vw_fund_period_math": {
    "database": "alts",
    "object": "vw_fund_period_math",
    "object_type": "view",
    "rows": 1392,
    "columns": 64,
    "role": "Inspection view",
    "plain_title": "Balance calculations beside the stored amounts",
    "plain_contents": "This saved query adds arithmetic checks to each fund-period row, including value-to-paid-in ratios and a recalculated closing balance.",
    "plain_separation": "The balances stay in the fund-period table. The database computes these extra comparison columns each time the query is opened.",
    "plain_example": "Money returned plus remaining value is divided by money paid in and displayed beside the stored fund figures.",
    "index_contents": "Each row is: one fund_periods row with the arithmetic redone beside it.\nIt holds: every fund_periods column plus the multiples recalculated from the raw amounts, and a recalculated closing value.\nExample: FUND_0416's stored multiple of 1.1746 matches the recalculated 1.1746.\nWhy a view: A view is a saved question: it stores nothing and recalculates from other tables each time it is opened. It is for spot checks; the real calculations run in Python and save their results in fund_metrics.",
    "csv_source": ""
  },
  "alts/vw_quality_scorecard": {
    "database": "alts",
    "object": "vw_quality_scorecard",
    "object_type": "view",
    "rows": 23,
    "columns": 8,
    "role": "Inspection view",
    "plain_title": "Totals of checks passed, failed and skipped",
    "plain_contents": "This saved query groups the detailed check results by check type and reports the pass, fail and skip counts.",
    "plain_separation": "The results table keeps individual checks and their reasons. This query calculates the totals for a shorter overview.",
    "plain_example": "A total of failed balance checks can be inspected alongside the individual failures in quality_results.",
    "index_contents": "Each row is: one check rule with its totals.\nIt holds: the number of checks, passes, failures and skips, and the pass rate leaving skips out.\nExample: rule R03, which recalculates the money-paid-back multiple, ran 1,392 times: 941 passed, 0 failed, and 451 were skipped because an input was missing.\nWhy a view: A view is a saved question: it stores nothing and recalculates from other tables each time it is opened. It totals quality_results.",
    "csv_source": ""
  },
  "alts_mock/benchmark_returns": {
    "database": "alts_mock",
    "object": "benchmark_returns",
    "object_type": "table",
    "rows": 450,
    "columns": 13,
    "role": "Analytical input",
    "plain_title": "Market returns used for comparison",
    "plain_contents": "Each row records a generated comparison-market return used for testing.",
    "plain_separation": "The market series is shared by many test funds. Keeping it apart from each fund's return records tests reuse of the same comparison data.",
    "plain_example": "Several generated funds can be compared with one generated market-return series.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one quarter's return of a made-up market index.\nExample: Synthetic Public Equity Benchmark returned 8.71% in the quarter ending 2016-06-30.\nWhy its own table: same reason as alts.benchmark_returns: one index history shared by many funds.",
    "csv_source": "data/synthetic/clean/benchmark_returns.csv"
  },
  "alts_mock/defect_injections": {
    "database": "alts_mock",
    "object": "defect_injections",
    "object_type": "table",
    "rows": 0,
    "columns": 12,
    "role": "Deliberate-error record",
    "plain_title": "The errors deliberately added to test copies",
    "plain_contents": "This table is empty because this database loads the clean generated test dataset.",
    "plain_separation": "The shared structure includes a place for deliberate-error records. Damaged test copies and their error records are kept in the separate defects folder.",
    "plain_example": "An intentionally changed test balance is assessed in the defects files, while this database retains the clean generated records.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: would be one planted error. The table is empty on purpose.\nExample: none here. This database loads only the clean test data; the damaged test copies and their answer keys are in data/synthetic/defects/.\nWhy its own table: the test database copies the exact table layout of alts.duckdb.",
    "csv_source": "data/synthetic/clean/defect_injections.csv"
  },
  "alts_mock/document_fund_map": {
    "database": "alts_mock",
    "object": "document_fund_map",
    "object_type": "table",
    "rows": 0,
    "columns": 27,
    "role": "Reviewed document identity",
    "plain_title": "Evidence that a report names a particular fund",
    "plain_contents": "This table is empty because these test funds are generated records with zero source-report links.",
    "plain_separation": "The database uses the same table structure as the fund model, including a place for report-to-fund links. The generated fixture supplies zero such links.",
    "plain_example": "Source-backed report-to-fund links are stored in the alts database; the test copy keeps the same columns empty.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: would be one link between a report and a fund. The table is empty on purpose.\nExample: none. Made-up funds come from no report, so there is nothing to link.\nWhy its own table: the test database copies the exact table layout of alts.duckdb, including tables it leaves empty.",
    "csv_source": ""
  },
  "alts_mock/document_manager_map": {
    "database": "alts_mock",
    "object": "document_manager_map",
    "object_type": "table",
    "rows": 0,
    "columns": 18,
    "role": "Document identity",
    "plain_title": "Evidence that a report names a management company",
    "plain_contents": "This table is empty because the test managers are generated identities with zero source-report links.",
    "plain_separation": "The shared database structure includes a place for report-to-manager links. Keeping that empty structure tests compatibility with the fund-model database.",
    "plain_example": "The test database can be opened with the same table names as the fund model even when a particular table has zero rows.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: would be one link between a report and a manager. The table is empty on purpose.\nExample: none. Made-up managers come from no report, so there is nothing to link.\nWhy its own table: the test database copies the exact table layout of alts.duckdb, including tables it leaves empty.",
    "csv_source": ""
  },
  "alts_mock/fund_cashflows": {
    "database": "alts_mock",
    "object": "fund_cashflows",
    "object_type": "table",
    "rows": 23983,
    "columns": 26,
    "role": "Analytical input",
    "plain_title": "Payments into and out of funds",
    "plain_contents": "Each row records a generated payment into or out of a test fund, with its date, amount and currency.",
    "plain_separation": "Payment timing affects the calculated return. Individual payments therefore remain separate from quarterly or year-end balance records.",
    "plain_example": "Two generated payments on different dates remain two rows even when their amounts are combined in a period balance.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one dated made-up payment between investors and a fund.\nExample: FUND_SYNTH_000123 called 33.75 from its investors on 2019-02-15.\nWhy its own table: same reason as alts.fund_cashflows: returns depend on payment dates.",
    "csv_source": "data/synthetic/clean/fund_cashflows.csv"
  },
  "alts_mock/fund_holdings": {
    "database": "alts_mock",
    "object": "fund_holdings",
    "object_type": "table",
    "rows": 89503,
    "columns": 32,
    "role": "Investment detail",
    "plain_title": "The investments owned by each fund",
    "plain_contents": "Each row describes a generated investment held by a test fund at a reporting date.",
    "plain_separation": "One fund can hold many investments. Separate holding records test the investment-level relationships independently of the fund's payment list.",
    "plain_example": "A test fund can own several generated bonds while retaining one fund identity.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one made-up investment a made-up fund owns on a date.\nExample: FUND_SYNTH_000092 holds a loan to Synthetic Portfolio Company 000092-01 at 12.2% interest, due 2020-12-31.\nWhy its own table: same reason as alts.fund_holdings: many investments per fund, kept apart from payments.",
    "csv_source": "data/synthetic/clean/fund_holdings.csv"
  },
  "alts_mock/fund_master": {
    "database": "alts_mock",
    "object": "fund_master",
    "object_type": "table",
    "rows": 800,
    "columns": 29,
    "role": "Analytical input",
    "plain_title": "The list of funds",
    "plain_contents": "Each row identifies a made-up fund and records the generated attributes used in the test dataset.",
    "plain_separation": "Test funds have their own identities. Their balances, payments and investments refer to these identities, keeping test records apart from source-backed funds.",
    "plain_example": "One generated fund has a single identity and many dated balance and payment records.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one made-up fund.\nExample: FUND_SYNTH_000121 is Synthetic Buyout Fund 0121, vintage 2013, now liquidated.\nWhy its own table: same reason as alts.fund_master: one identity per fund, many dated rows pointing to it.",
    "csv_source": "data/synthetic/clean/fund_master.csv"
  },
  "alts_mock/fund_metrics": {
    "database": "alts_mock",
    "object": "fund_metrics",
    "object_type": "table",
    "rows": 131188,
    "columns": 14,
    "role": "Calculated result",
    "plain_title": "Fund performance calculated by the project",
    "plain_contents": "Each row records a return or value ratio calculated from the generated test funds.",
    "plain_separation": "Generated input amounts and calculated results remain separate, matching the production structure while using test data.",
    "plain_example": "A total-value ratio is calculated from a test fund's returned money, remaining value and money paid in.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one number the project calculated for a made-up fund on a date.\nExample: FUND_SYNTH_000041's calculated annual return (XIRR) is 11.36% at 2024-09-30.\nWhy its own table: same reason as alts.fund_metrics: calculated results stay apart from input numbers.",
    "csv_source": "data/synthetic/analytics/fund_metrics.csv"
  },
  "alts_mock/fund_observations": {
    "database": "alts_mock",
    "object": "fund_observations",
    "object_type": "table",
    "rows": 327970,
    "columns": 40,
    "role": "Fund-specific evidence",
    "plain_title": "Individual source facts assigned to funds",
    "plain_contents": "Each row records a generated measurement for a test fund, with its date, units and meaning.",
    "plain_separation": "The test dataset reproduces the separate measurement records used by the fund model. Related balance and payment tables group or select those measurements for specific uses.",
    "plain_example": "A generated fund balance and a generated return remain different measurements for the same fund.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one made-up number for a made-up fund, with its date and units.\nExample: FUND_SYNTH_000020 has a current value of 492.58 at 2022-12-31.\nWhy its own table: same reason as alts.fund_observations.",
    "csv_source": "data/synthetic/clean/fund_observations.csv"
  },
  "alts_mock/fund_periods": {
    "database": "alts_mock",
    "object": "fund_periods",
    "object_type": "table",
    "rows": 32797,
    "columns": 59,
    "role": "Analytical input",
    "plain_title": "A fund's balances at a reporting date",
    "plain_contents": "Each row records generated balances and returns for one test fund at a reporting date.",
    "plain_separation": "A test fund can have many reporting dates. Keeping dated balances apart from its identity and individual payments tests those relationships over time.",
    "plain_example": "Successive quarterly records describe the same generated fund at different dates.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one made-up fund, or one made-up investor's stake, at one quarter-end, with all its balances.\nExample: FUND_SYNTH_000266 at 2022-03-31: 334.28 promised, 284.63 paid in, 51.33 paid back, 312.87 current value.\nWhy its own table: same reason as alts.fund_periods, over about 33,000 made-up quarter-ends.",
    "csv_source": "data/synthetic/clean/fund_periods.csv"
  },
  "alts_mock/fund_term_clauses": {
    "database": "alts_mock",
    "object": "fund_term_clauses",
    "object_type": "table",
    "rows": 3400,
    "columns": 22,
    "role": "Legal detail",
    "plain_title": "Contract terms that need words and conditions",
    "plain_contents": "Each row records a generated contract clause or exception for a test fund or investor.",
    "plain_separation": "Textual conditions require different fields from fee rates and balances. These test records exercise the clause structure used by the fund model.",
    "plain_example": "A generated reporting clause can have its own effective date and investor scope.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one made-up contract clause stated in words.\nExample: Synthetic key person suspension: the departure of two named principals suspends the investment period.\nWhy its own table: same reason as alts.fund_term_clauses.",
    "csv_source": "data/synthetic/clean/fund_term_clauses.csv"
  },
  "alts_mock/fund_terms": {
    "database": "alts_mock",
    "object": "fund_terms",
    "object_type": "table",
    "rows": 1084,
    "columns": 29,
    "role": "Economic terms",
    "plain_title": "Fee rates and other financial rules",
    "plain_contents": "Each row records generated fee rates, profit-sharing rules or other financial terms for test funds and investors.",
    "plain_separation": "Agreed terms and generated payments represent different types of record. Their separation tests the fund model's handling of terms and dated amounts.",
    "plain_example": "A generated fee rule can apply to several payment periods.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one made-up fund's money rules, or one investor's special version of them.\nExample: FUND_SYNTH_000713 charges 1.8% a year, takes 20% of profits above an 8% hurdle, and runs 10 years plus 2.\nWhy its own table: same reason as alts.fund_terms.",
    "csv_source": "data/synthetic/clean/fund_terms.csv"
  },
  "alts_mock/manager_master": {
    "database": "alts_mock",
    "object": "manager_master",
    "object_type": "table",
    "rows": 200,
    "columns": 14,
    "role": "Manager reference",
    "plain_title": "The list of fund management companies",
    "plain_contents": "Each row identifies a made-up management company used by the test funds.",
    "plain_separation": "Several generated funds can share a manager. A separate company record tests the same fund-to-manager relationships used in the source-backed data.",
    "plain_example": "Two test funds can refer to one generated management company.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one made-up fund manager.\nExample: MANAGER_SYNTH_00033 is Synthetic Alternatives Manager 0033, LLC.\nWhy its own table: same reason as alts.manager_master: one manager, several funds.",
    "csv_source": "data/synthetic/clean/manager_master.csv"
  },
  "alts_mock/manager_observations": {
    "database": "alts_mock",
    "object": "manager_observations",
    "object_type": "table",
    "rows": 600,
    "columns": 31,
    "role": "Manager-specific evidence",
    "plain_title": "Figures about management companies",
    "plain_contents": "Each row records a generated company-level measurement for a test manager.",
    "plain_separation": "Company totals and individual fund totals represent different subjects. This table tests that the two remain distinct in the data structure.",
    "plain_example": "A generated manager's total assets can cover several generated funds.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one made-up number about a manager as a whole.\nExample: Synthetic Alternatives Manager 0031 runs 4 funds.\nWhy its own table: same reason as alts.manager_observations: a manager's total must not be copied onto each fund.",
    "csv_source": "data/synthetic/clean/manager_observations.csv"
  },
  "alts_mock/pme_results": {
    "database": "alts_mock",
    "object": "pme_results",
    "object_type": "table",
    "rows": 65594,
    "columns": 15,
    "role": "Calculated result",
    "plain_title": "Fund results compared with a market investment",
    "plain_contents": "Each row compares a generated test fund with the generated comparison market using its payment dates.",
    "plain_separation": "The comparison needs both fund payments and market returns. Its result remains separate from the fund's absolute return.",
    "plain_example": "The same generated payment history supplies a fund-return calculation and a separate public-market comparison.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one comparison of a made-up fund with a made-up market index.\nExample: FUND_SYNTH_000082 beat the Synthetic Public Equity Benchmark by 1.83% a year (direct alpha) at 2025-06-30.\nWhy its own table: same reason as alts.pme_results.",
    "csv_source": "data/synthetic/analytics/pme_results.csv"
  },
  "alts_mock/portfolio_allocations": {
    "database": "alts_mock",
    "object": "portfolio_allocations",
    "object_type": "table",
    "rows": 3200,
    "columns": 25,
    "role": "Portfolio result",
    "plain_title": "Proposed shares of a fund portfolio",
    "plain_contents": "Each row records a proposed share for a generated fund. The table contains generated starting allocations and allocations calculated by the analytics code.",
    "plain_separation": "A fund can appear in several proposals. The proposal and calculation identifiers distinguish those versions and must remain part of any grouping.",
    "plain_example": "An equal-weight starting proposal and a calculated equal-weight proposal are two separate sets, even when their fund names and dates match.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one made-up fund's proposed share of a model portfolio.\nExample: in the equal-weight portfolio every one of the 800 funds gets 1/800 or 0.125%; FUND_SYNTH_000717 is one of them.\nWhy its own table: 2,400 starting proposals and 800 calculated ones share fund names and dates, so the proposal ID must stay part of any grouping.",
    "csv_source": "data/synthetic/clean/portfolio_allocations.csv | data/synthetic/analytics/portfolio_allocations.csv"
  },
  "alts_mock/quality_results": {
    "database": "alts_mock",
    "object": "quality_results",
    "object_type": "table",
    "rows": 649490,
    "columns": 16,
    "role": "Analytical input and check detail",
    "plain_title": "The results of checks on the records",
    "plain_contents": "Each row records one check on a clean generated test record and whether the check passed, failed or was skipped.",
    "plain_separation": "The test data and their check results serve different roles. Separate results record which rules ran and what each rule found.",
    "plain_example": "A missing optional field can cause a skipped check; that result stays visible alongside checks that passed.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one check run on one made-up record, and its outcome.\nExample: FUND_SYNTH_000008 passes rule R03: its stored multiple 0.105514 matches the recalculated 0.105514.\nWhy its own table: same reason as alts.quality_results: many checks per record, one row per check.",
    "csv_source": "data/synthetic/clean/quality_results.csv"
  },
  "alts_mock/synthetic_parameters": {
    "database": "alts_mock",
    "object": "synthetic_parameters",
    "object_type": "table",
    "rows": 152,
    "columns": 17,
    "role": "Generation record",
    "plain_title": "Assumptions used to generate additional data",
    "plain_contents": "Each row records an assumption used to create the standalone test funds and their records.",
    "plain_separation": "These assumptions belong to the test dataset. The assumptions used to complete the source-backed fund dataset are recorded in the other database.",
    "plain_example": "One set of return and fee assumptions can produce many generated fund records.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one assumption used to make up the test funds.\nExample: made-up venture funds are given Delaware, US as their legal home.\nWhy its own table: these are the test data's assumptions, separate from the ones used to fill gaps in alts.duckdb.",
    "csv_source": "data/synthetic/clean/synthetic_parameters.csv"
  },
  "alts_mock/vw_analytics_ready_fund_periods": {
    "database": "alts_mock",
    "object": "vw_analytics_ready_fund_periods",
    "object_type": "view",
    "rows": 32797,
    "columns": 59,
    "role": "Inspection view",
    "plain_title": "Active balance records with recorded errors excluded",
    "plain_contents": "This saved query lists active fund-period rows whose period checks contain zero error-level failures.",
    "plain_separation": "The full period table retains every record. This filtered display is an inspection shortcut; the calculation code also checks required amounts and whether the record belongs in that calculation.",
    "plain_example": "An active row can appear here while still lacking an amount needed for a return calculation.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one active made-up fund_periods row with no failed error-level check.\nExample: all 32,797 made-up rows pass this filter.\nWhy a view: A view is a saved question: it stores nothing and recalculates from other tables each time it is opened.",
    "csv_source": ""
  },
  "alts_mock/vw_fund_period_math": {
    "database": "alts_mock",
    "object": "vw_fund_period_math",
    "object_type": "view",
    "rows": 32797,
    "columns": 64,
    "role": "Inspection view",
    "plain_title": "Balance calculations beside the stored amounts",
    "plain_contents": "This saved query adds arithmetic checks to each fund-period row, including value-to-paid-in ratios and a recalculated closing balance.",
    "plain_separation": "The balances stay in the fund-period table. The database computes these extra comparison columns each time the query is opened.",
    "plain_example": "Money returned plus remaining value is divided by money paid in and displayed beside the stored fund figures.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one made-up fund_periods row with the arithmetic redone beside it.\nExample: FUND_SYNTH_000266's stored multiple 1.279556 matches the recalculated 1.2795559.\nWhy a view: A view is a saved question: it stores nothing and recalculates from other tables each time it is opened.",
    "csv_source": ""
  },
  "alts_mock/vw_quality_scorecard": {
    "database": "alts_mock",
    "object": "vw_quality_scorecard",
    "object_type": "view",
    "rows": 23,
    "columns": 8,
    "role": "Inspection view",
    "plain_title": "Totals of checks passed, failed and skipped",
    "plain_contents": "This saved query groups the detailed check results by check type and reports the pass, fail and skip counts.",
    "plain_separation": "The results table keeps individual checks and their reasons. This query calculates the totals for a shorter overview.",
    "plain_example": "A total of failed balance checks can be inspected alongside the individual failures in quality_results.",
    "index_contents": "Test data: made-up funds used to test the calculations. Nothing here comes from a real report.\nEach row is: one check rule with its totals over the made-up data.\nExample: rule R05, which recalculates the total-value multiple, ran 32,797 times and passed every time.\nWhy a view: A view is a saved question: it stores nothing and recalculates from other tables each time it is opened.",
    "csv_source": ""
  },
  "extracted/bridge_pivot_observation": {
    "database": "extracted",
    "object": "bridge_pivot_observation",
    "object_type": "table",
    "rows": 9538,
    "columns": 3,
    "role": "Source-cell links",
    "plain_title": "Links between grouped rows and their source facts",
    "plain_contents": "Each row matches a row of grouped figures to one printed fact used to build it. It stores the two record numbers and the name of the grouped table.",
    "plain_separation": "One grouped row can use several facts, and one fact can appear in several grouped tables. Keeping these links here avoids copying the full amount, page and quote for every use.",
    "plain_example": "A row containing money paid in, money returned and remaining value has a link to each of those three source facts.",
    "index_contents": "Each row is: one link between a combined row in one of the wide_ tables and one single fact it was built from.\nIt holds: three IDs only: which wide_ table, which row in it, and which fact in fact_observation.\nExample: the wide_fund_economics_observation row for the AEW Essential Housing Fund on report SRC058, page 2, combines six printed figures, so it has six links here, one to each fact.\nWhy its own table: one combined row uses several facts, and one fact can appear in several combined rows. A plain list of links records that without copying any fact a second time.",
    "csv_source": "data/extracted/wide/bridge_pivot_observation.csv"
  },
  "extracted/dim_document": {
    "database": "extracted",
    "object": "dim_document",
    "object_type": "table",
    "rows": 36,
    "columns": 17,
    "role": "Evidence reference",
    "plain_title": "The list of extracted reports",
    "plain_contents": "Each row identifies a report that has completed extraction. It records the report's file, publisher, type, source address and page totals.",
    "plain_separation": "A report can supply hundreds of facts. Those facts refer to one report record instead of requiring a separate report description for every number.",
    "plain_example": "Every accepted number from the same pension report refers to the same document record.",
    "index_contents": "Each row is: one report (one PDF file) that has been fully read.\nIt holds: the file name, who published it, what kind of report it is, where it was downloaded from, how many pages it has, how many pages had usable numbers, and how many numbers were taken from it.\nExample: SRC375 is the University of Virginia investment office's 2025 annual report highlights: 2 pages, both with data, and 110 numbers taken.\nWhy its own table: one report supplies up to hundreds of numbers. Each number points to this one row instead of repeating the report's details beside every number.",
    "csv_source": "data/extracted/tables/dim_document.csv"
  },
  "extracted/dim_entity": {
    "database": "extracted",
    "object": "dim_entity",
    "object_type": "table",
    "rows": 972,
    "columns": 8,
    "role": "Identity reference",
    "plain_title": "The names used consistently across reports",
    "plain_contents": "Each row identifies one named fund, manager, company, investor or pension plan. It records the chosen name and the kind of organization or investment.",
    "plain_separation": "The same subject can appear under several spellings. A shared identity groups its facts while keeping funds, their managers and their investors distinct.",
    "plain_example": "Two spellings of the same fund refer to one fund identity; its management company has a separate identity.",
    "index_contents": "Each row is: one named thing that appears in the reports: a fund, a fund manager (the company that runs funds), a company, an investor, or a pension plan.\nIt holds: an ID, what kind of thing it is, the one name the project uses for it, its fund family (a brand with several funds), and its manager if known.\nExample: FUND_0684 is KKR Asian Fund II TE Blocker L.P., family KKR, managed by Kohlberg Kravis Roberts & Co. L.P.\nWhy its own table: the same fund is printed under different spellings in different reports. One ID per real thing keeps all its numbers together, and keeps funds apart from the companies that run them.",
    "csv_source": "data/extracted/tables/dim_entity.csv"
  },
  "extracted/dim_metric": {
    "database": "extracted",
    "object": "dim_metric",
    "object_type": "table",
    "rows": 114,
    "columns": 9,
    "role": "Measurement reference",
    "plain_title": "The meaning of each kind of measurement",
    "plain_contents": "Each row describes a kind of value, such as money paid into a fund, remaining investment value or an annual return.",
    "plain_separation": "Thousands of facts can report the same kind of measurement. This table keeps the shared definition apart from each fund's amount and date.",
    "plain_example": "Two funds' reported returns use a common measurement definition while retaining their own percentages and reporting periods.",
    "index_contents": "Each row is: one kind of number the project collects, such as money paid into a fund, a fund's current value, or an annual return.\nIt holds: the name of the measure, the group it belongs to, whether it is money, a percent, a multiple or a count, how many facts use it, and a one-line definition.\nExample: fund_economics_observation.paid_in_capital means money investors have actually sent into a fund so far. 288 facts in the database are this kind of number.\nWhy its own table: thousands of facts share about a hundred meanings. Each definition is written once here, and every fact points to one.",
    "csv_source": "data/extracted/tables/dim_metric.csv"
  },
  "extracted/dim_page": {
    "database": "extracted",
    "object": "dim_page",
    "object_type": "table",
    "rows": 693,
    "columns": 11,
    "role": "Extraction coverage",
    "plain_title": "The record of pages reviewed",
    "plain_contents": "Each row records the review of one physical report page, including the page number, layout review and counts of expected and recorded findings.",
    "plain_separation": "A list of extracted numbers only records pages that supplied numbers. This table also records pages containing covers, contents or other material outside the extraction scope.",
    "plain_example": "A contents page can have a completed page-review record and zero extracted figures.",
    "index_contents": "Each row is: one physical page of one report, and what the readers found on it.\nIt holds: the page number, whether it had usable data, how many numbers were expected from it, how many were written, and a note explaining any page where nothing was taken.\nExample: SRC376, page 20, has zero numbers taken. Its note says the page prints an operating-lease schedule, which is outside what the project collects.\nWhy its own table: fact_observation only shows pages that gave numbers. This table proves every page was looked at, including the empty ones.",
    "csv_source": "data/extracted/tables/dim_page.csv"
  },
  "extracted/entity_alias": {
    "database": "extracted",
    "object": "entity_alias",
    "object_type": "table",
    "rows": 1638,
    "columns": 10,
    "role": "Name mapping",
    "plain_title": "Printed names and the identities they refer to",
    "plain_contents": "Each row connects a name printed in a report to the name and record used consistently in the database.",
    "plain_separation": "One fund can have several printed name variants. A separate list keeps all those variants and their source references beside a single fund identity.",
    "plain_example": "A shortened fund name and its full legal name can each point to the same reviewed fund record.",
    "index_contents": "Each row is: one way a name was actually printed in a report, and the ID it belongs to.\nIt holds: the name exactly as printed, a cleaned-up version, what kind of thing it names, the ID it was matched to, how the match was decided, and which reports use that spelling.\nExample: the printed name Clearlake Capital Partners VII (USTE), L.P. in report SRC407 is matched to fund ID FUND_0439.\nWhy its own table: one fund can be printed several ways. This list keeps every printed spelling and points each one at the single ID in dim_entity.",
    "csv_source": "data/extracted/tables/entity_alias.csv"
  },
  "extracted/fact_holding": {
    "database": "extracted",
    "object": "fact_holding",
    "object_type": "table",
    "rows": 487,
    "columns": 28,
    "role": "Grouped source holding",
    "plain_title": "Investments assembled from the source figures",
    "plain_contents": "Each row groups the reported values for one investment, such as its purchase cost, current value, quantity and reporting date.",
    "plain_separation": "Several printed facts describe one investment. This grouped record supplies the investment-level data used later to build the fund's holdings list.",
    "plain_example": "The cost and current value of one bond can be read together here; each amount still points to its source fact.",
    "index_contents": "Each row is: one investment a fund owns, put together from the separate numbers printed about it.\nIt holds: the investment's name, the report page, the date, the currency, and whichever of these the page prints: what it cost, what it is worth now, how many units, its share of the portfolio, and its interest rate.\nExample: report SRC407, page 3, lists Genstar Capital Partners VIII BL (EU), L.P. at December 31, 2025: cost $1,511,649, now worth $2,553,625.\nWhy its own table: several printed numbers describe one investment. This one row per investment is what the project's list of fund holdings (fund_holdings) is built from.",
    "csv_source": "data/extracted/tables/fact_holding.csv"
  },
  "extracted/fact_observation": {
    "database": "extracted",
    "object": "fact_observation",
    "object_type": "table",
    "rows": 8613,
    "columns": 72,
    "role": "Accepted source evidence",
    "plain_title": "The accepted facts from the reports",
    "plain_contents": "Each row holds one accepted number or statement, its original wording, its page and the words supporting it. The subject, date and units stay beside the value.",
    "plain_separation": "One fund can report many figures with different dates and meanings. A separate record for each fact keeps those distinctions before figures are grouped for analysis.",
    "plain_example": "The AEW fund row on source document SRC058, page 2, becomes six fact records: one for each printed field.",
    "index_contents": "Each row is: one number or one sentence copied off a report page and accepted after review. This is the main evidence table; almost every other table in this database is built from it.\nIt holds: the value exactly as printed and as a clean number, what it measures, who or what it is about, its date, its units, the page, the exact words on the page that prove it, and how the review decided it.\nExample: report SRC035, page 2, prints a TVPI of 1.74 for K4 Private Investors, L.P. at December 31, 2021. TVPI is money paid back plus what is still invested, divided by money paid in, so every dollar paid in is now worth $1.74.\nWhy its own table: one row per printed number keeps each number's own date, units and meaning. Combining numbers any earlier would lose those details.",
    "csv_source": "data/extracted/tables/fact_observation.csv"
  },
  "extracted/observation_lineage": {
    "database": "extracted",
    "object": "observation_lineage",
    "object_type": "table",
    "rows": 8613,
    "columns": 13,
    "role": "Extraction review record",
    "plain_title": "The review decision behind each accepted fact",
    "plain_contents": "Each row records the two extractors' proposals for a printed fact and the review decision that selected the accepted result.",
    "plain_separation": "The fact table stores the accepted value. This table stores the comparison and decision behind that value, which a reviewer can inspect on its own.",
    "plain_example": "If two readers enter different amounts from one page, this record identifies their entries and explains the final choice.",
    "index_contents": "Each row is: the review record behind one accepted fact. There is exactly one row here for every row of fact_observation.\nIt holds: the row Reader A wrote, the row Reader B wrote, whether they agreed, which fields they disagreed on, what the reviewer decided (keep A, keep B, combine both, or write it fresh from the page), and the reason. Readers A and B are two AI models that each read every report on its own; a third model checks the page image when they disagree.\nExample: both readers took the 1.74 for K4 Private Investors. They disagreed only on the section heading, the name of the measure and the quote, and the reviewer combined the two after checking the page image.\nWhy its own table: fact_observation stores only the final answer. This table stores how the answer was reached, so any number can be traced back to the two original readings.",
    "csv_source": "data/extracted/tables/observation_lineage.csv"
  },
  "extracted/unresolved_names": {
    "database": "extracted",
    "object": "unresolved_names",
    "object_type": "table",
    "rows": 0,
    "columns": 6,
    "role": "Name-review exceptions",
    "plain_title": "Names awaiting an identity decision",
    "plain_contents": "Each row would record a printed name that still needs a supported match to an entity, plus the source documents and reason.",
    "plain_separation": "Pending name decisions stay apart from accepted identities. An empty table means the current name-review queue has zero entries.",
    "plain_example": "A name with two possible fund matches would stay here until source evidence supports a decision.",
    "index_contents": "Each row is: one printed name that has not yet been matched to an ID. The table is empty right now.\nIt holds: the printed name, how often it appears, which reports use it, and why it is still undecided.\nExample: none today. Every printed name has been matched to an ID or labelled as not naming a fund, manager or investor.\nWhy its own table: undecided names stay out of the matched list, so nothing unconfirmed is treated as decided.",
    "csv_source": "data/extracted/tables/unresolved_names.csv"
  },
  "extracted/wide_allocation_observation": {
    "database": "extracted",
    "object": "wide_allocation_observation",
    "object_type": "table",
    "rows": 388,
    "columns": 47,
    "role": "Grouped source records",
    "plain_title": "Investment shares and allocation targets",
    "plain_contents": "Each row groups the reported share of money assigned to an investment category, its target share and any reported value.",
    "plain_separation": "Allocation describes where money is invested. Performance describes money earned or lost, so the two subjects have different columns and review tables.",
    "plain_example": "An actual share and a target share for private equity appear together, with their reporting date.",
    "index_contents": "Each row is: one line of a report table saying how much of a portfolio sits in one category of investment.\nIt holds: the actual share in percent, the target share, and any dollar value, with the date and the category.\nExample: the CalSTRS report SRC602, page 10, prints a 4% interim target for Special Mandates within private equity.\nWhy its own table: where money sits is a different question from how much it earned, so shares and targets have their own columns. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_allocation_observation.csv"
  },
  "extracted/wide_cash_flow_observation": {
    "database": "extracted",
    "object": "wide_cash_flow_observation",
    "object_type": "table",
    "rows": 45,
    "columns": 52,
    "role": "Grouped source records",
    "plain_title": "Payments as the report presents them",
    "plain_contents": "Each row groups reported payments and their components, such as a contribution, distribution, interest or expense.",
    "plain_separation": "The source can split one payment into several parts. This table keeps that split for review; the later fund payment table applies the project's payment categories.",
    "plain_example": "A payment notice can show returned capital and interest as separate parts of the same distribution.",
    "index_contents": "Each row is: one money movement printed on an investor's statement.\nIt holds: capital called (money the fund asked the investor to send), distributions (money paid back), and any split of a payment into returned capital, income, interest or expenses.\nExample: on report SRC463, page 2, Northumberland County Council paid a capital call of 3,185,400 euros on 25/09/2014.\nWhy its own table: a statement can split one payment into parts, and this keeps the parts as printed. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it. The calculations use fund_cashflows instead.",
    "csv_source": "data/extracted/wide/wide_cash_flow_observation.csv"
  },
  "extracted/wide_ddq_quantitative_observation": {
    "database": "extracted",
    "object": "wide_ddq_quantitative_observation",
    "object_type": "table",
    "rows": 48,
    "columns": 56,
    "role": "Grouped source records",
    "plain_title": "Numbers from manager questionnaires",
    "plain_contents": "Each row groups numbers reported in a due-diligence questionnaire, which asks about a manager's staff, borrowing, fees and investment terms.",
    "plain_separation": "Staff counts and withdrawal terms describe how a business or fund operates. They have different meanings and units from investment returns.",
    "plain_example": "A staff count and a minimum investment amount remain separate fields in the questionnaire records.",
    "index_contents": "Each row is: one numeric answer from a due-diligence questionnaire (DDQ), the standard form an investor sends a fund manager before investing.\nIt holds: staff counts, assets managed, borrowing (leverage), lock-up and notice periods, minimum investment, limits and fees.\nExample: the Bear Stearns questionnaire SRC107 gives a $1,000,000 minimum initial investment for its High Grade Structured Credit fund, and 125 investment professionals at the manager.\nWhy its own table: these numbers describe how a business runs, not what a fund earned, and they come in their own units. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_ddq_quantitative_observation.csv"
  },
  "extracted/wide_definition_context": {
    "database": "extracted",
    "object": "wide_definition_context",
    "object_type": "table",
    "rows": 456,
    "columns": 15,
    "role": "Grouped source records",
    "plain_title": "Definitions attached to reported figures",
    "plain_contents": "Each row keeps a report's definition or explanatory note and the figures or section that it applies to.",
    "plain_separation": "A single footnote can explain several numbers. Keeping it once as a definition avoids repeating its text beside every related figure.",
    "plain_example": "A footnote stating that returns include fees remains linked to the return figures it explains.",
    "index_contents": "Each row is: one definition, footnote or method note printed in a report, and what it applies to.\nIt holds: the marker (such as footnote 1), the definition wording, what it applies to, and the printed quote.\nExample: report SRC363 explains that its endowment's 4.5 percent distribution rate is based on the trailing 28 quarters.\nWhy its own table: one footnote can explain many numbers, so it is stored once and the numbers point to it by its marker. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_definition_context.csv"
  },
  "extracted/wide_document_context": {
    "database": "extracted",
    "object": "wide_document_context",
    "object_type": "table",
    "rows": 36,
    "columns": 34,
    "role": "Grouped source records",
    "plain_title": "Facts about the report as a whole",
    "plain_contents": "Each row groups printed report details, such as its title, named manager or investor, reporting dates and stated currency.",
    "plain_separation": "These details apply across a report. The document list records the file and publisher; this table records context extracted from the report itself.",
    "plain_example": "A report-wide currency statement belongs here even when many separate tables use that currency.",
    "index_contents": "Each row is: one report, with the facts about the report as a whole that are printed inside it.\nIt holds: the report's printed title, the named manager or investor, the portfolio, the report date and the currency.\nExample: SRC375's printed title is Annual Report 2025 Highlights, for the University of Virginia's Long Term Pool, at June 30, 2025.\nWhy its own table: dim_document records the file (name, publisher, page count); this records what the report says about itself. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_document_context.csv"
  },
  "extracted/wide_fee_observation": {
    "database": "extracted",
    "object": "wide_fee_observation",
    "object_type": "table",
    "rows": 83,
    "columns": 50,
    "role": "Grouped source records",
    "plain_title": "Fees and their reported comparisons",
    "plain_contents": "Each row groups reported fees with related comparisons, offsets or the asset amount used to express a fee as a rate.",
    "plain_separation": "A fee amount and a fee rate answer different questions. Keeping their labels and comparison amounts together avoids treating them as the same charge.",
    "plain_example": "A management fee and the amount used to calculate its percentage can be reviewed in the same row.",
    "index_contents": "Each row is: one line of a printed fee table.\nIt holds: management fees, performance fees, costs in basis points (one basis point is one hundredth of a percent), fee offsets, a comparison fee level, and the asset amount a fee rate is measured against.\nExample: the PSERS fee report SRC028 prints a base management fee of 48 basis points (0.48% a year) for Emerging Markets fixed income, at June 30, 2017.\nWhy its own table: a fee in dollars and a fee as a rate answer different questions, and a comparison figure must stay beside the fee it compares. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_fee_observation.csv"
  },
  "extracted/wide_financial_statement_observation": {
    "database": "extracted",
    "object": "wide_financial_statement_observation",
    "object_type": "table",
    "rows": 838,
    "columns": 64,
    "role": "Grouped source records",
    "plain_title": "Amounts from accounting statements",
    "plain_contents": "Each row groups amounts from a financial statement, such as cash, assets, debts, income, expenses and opening or closing balances.",
    "plain_separation": "Accounting statements describe several kinds of balances and changes. This table keeps their structure before supported fund figures are selected for calculations.",
    "plain_example": "An opening balance and closing balance for the same account retain their separate columns and dates.",
    "index_contents": "Each row is: one line of an accounting statement: a balance sheet, an income statement or a cash-flow statement.\nIt holds: cash, total assets, debts, net assets, investments at cost and at current value, income, expenses, gains and losses, and opening and closing balances.\nExample: report SRC377, note 3, lists Berkshire Hathaway B shares at a current value of $9,821,340 thousand (about $9.8 billion) at December 31, 2015.\nWhy its own table: accounting statements have their own set of balances and changes, and this keeps them as printed before any fund figures are picked out. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_financial_statement_observation.csv"
  },
  "extracted/wide_financing_observation": {
    "database": "extracted",
    "object": "wide_financing_observation",
    "object_type": "table",
    "rows": 2,
    "columns": 45,
    "role": "Grouped source records",
    "plain_title": "Borrowing reported by the fund",
    "plain_contents": "Each row records a financing amount, such as the outstanding balance of a loan, with its date and source.",
    "plain_separation": "Borrowed money is a debt. Investor contributions and investment values have different accounting meanings and remain in their own tables.",
    "plain_example": "A reported loan balance is recorded as borrowing instead of money paid into the fund by an investor.",
    "index_contents": "Each row is: one borrowing amount printed in a report.\nIt holds: how much is still owed on a loan or a credit line, with its date.\nExample: report SRC152 prints $132,000,000 of line-of-credit advances outstanding at June 30, 2016.\nWhy its own table: borrowed money is a debt, not money investors put in, so it must never be added to investor payments. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_financing_observation.csv"
  },
  "extracted/wide_fund_economics_observation": {
    "database": "extracted",
    "object": "wide_fund_economics_observation",
    "object_type": "table",
    "rows": 1510,
    "columns": 71,
    "role": "Grouped source records",
    "plain_title": "Related fund figures from the same report row",
    "plain_contents": "Each row puts related fund or investor figures together: money promised, paid in, returned, still invested and any reported return.",
    "plain_separation": "The original fact table has one printed field per row. This version places related fields in columns for source review; the later fund-period table converts supported amounts for analysis.",
    "plain_example": "The six accepted AEW fields from source document SRC058, page 2, form one grouped row here.",
    "index_contents": "Each row is: one line of a report table about a fund, or about one investor's stake in a fund, with all the figures from that line side by side.\nIt holds: money promised (commitment), money paid in, money paid back (distributions), what the stake is worth now (NAV), money still to be asked for, the multiples (money back plus value, divided by money in) and returns.\nExample: report SRC058, page 1, prints the Timber fund, started 1991, at December 31, 2024: $46.5 million promised, $57.5 million paid in, $68 million paid back, worth $0 now, a 1.18 multiple and a 2.29% annual return.\nWhy its own table: fact_observation keeps one number per row; this puts a report line's numbers back together. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_fund_economics_observation.csv"
  },
  "extracted/wide_legal_clause": {
    "database": "extracted",
    "object": "wide_legal_clause",
    "object_type": "table",
    "rows": 23,
    "columns": 56,
    "role": "Grouped source records",
    "plain_title": "Rights and duties written in contracts",
    "plain_contents": "Each row records a contract provision, such as reporting duties, transfer rights or the conditions for replacing a manager.",
    "plain_separation": "These statements describe rights and duties, which often depend on conditions. Fee-rate and balance columns record amounts and rates; this table retains the full provision.",
    "plain_example": "A requirement to send reports every quarter is stored as a contract statement as its own contract record.",
    "index_contents": "Each row is: one contract clause that states a right or a duty in words.\nIt holds: the clause wording, filed under its type: key-person rules, removing the manager, ending the fund, reporting duties, transfers, tax, governing law, confidentiality and notices.\nExample: contract SRC612, page 8, requires the manager to notify SERS, the pension plan it works for, promptly if any of its stated facts change.\nWhy its own table: these are words and conditions, not numbers, so fee-rate and balance columns cannot hold them. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_legal_clause.csv"
  },
  "extracted/wide_legal_term": {
    "database": "extracted",
    "object": "wide_legal_term",
    "object_type": "table",
    "rows": 18,
    "columns": 58,
    "role": "Grouped source records",
    "plain_title": "Financial terms written in contracts",
    "plain_contents": "Each row groups a contract's financial terms, such as fees, profit sharing, fund duration or the order in which investors receive payments.",
    "plain_separation": "Contract terms describe an agreed rule. Actual fee charges and cash payments describe events, so they remain separate records.",
    "plain_example": "A stated annual management-fee rate belongs here; a fee amount charged during a quarter belongs among reported fees.",
    "index_contents": "Each row is: one money-related rule written in a fund contract or offering document.\nIt holds: the wording of the term, filed under its type: management fee, carried interest (the manager's share of profits), payout order, clawback, expense limits, fund life and extensions, investment period.\nExample: the Apollo S3 Private Markets Fund offering document SRC421, page 33, says the fund's term is perpetual unless the fund is terminated.\nWhy its own table: an agreed rule is different from a fee actually charged or a payment actually made. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_legal_term.csv"
  },
  "extracted/wide_nav_observation": {
    "database": "extracted",
    "object": "wide_nav_observation",
    "object_type": "table",
    "rows": 106,
    "columns": 53,
    "role": "Grouped source records",
    "plain_title": "Fund values and values per share",
    "plain_contents": "Each row groups the reported value of a fund or a share, related share counts, transaction prices or withdrawal limits.",
    "plain_separation": "A fund's total value, one share's value and a return percentage measure different things. This table keeps the share and valuation details together.",
    "plain_example": "A value per share and the number of shares remain distinct from the total value of the fund.",
    "index_contents": "Each row is: one printed value of a fund, or of one share in a fund.\nIt holds: NAV (what the fund's investments are worth), value per share, number of shares, the price new investors pay, and limits on taking money out.\nExample: the Starwood Real Estate Income Trust statement SRC247 prints a Class D value per share of $22.50 at May 31, 2024.\nWhy its own table: a whole-fund value, a one-share value and a share count are three different measures and must not be mixed. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_nav_observation.csv"
  },
  "extracted/wide_performance_observation": {
    "database": "extracted",
    "object": "wide_performance_observation",
    "object_type": "table",
    "rows": 1336,
    "columns": 54,
    "role": "Grouped source records",
    "plain_title": "Performance figures printed in reports",
    "plain_contents": "Each row groups reported investment results, including returns and comparisons, with their dates, time periods and measurement methods.",
    "plain_separation": "Reported results must retain the source's method and period. Results calculated by this project have their own output tables.",
    "plain_example": "A one-year return and a return since the fund began remain separate, even when they refer to the same fund.",
    "index_contents": "Each row is: one printed performance line: a fund's or a portfolio's return over a stated period.\nIt holds: returns, IRR (an annual return that counts when money went in and out), the difference versus a comparison index, yield, assets managed, how the return was measured, and whether fees were taken out first.\nExample: report SRC063, page 2, prints a one-year return of -10.6% for Sacramento Venture Hines DT at June 30, 2023, measured time-weighted and after fees.\nWhy its own table: a printed return means nothing without its period and method beside it, and returns the project calculates itself go in fund_metrics, never here. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_performance_observation.csv"
  },
  "extracted/wide_position_observation": {
    "database": "extracted",
    "object": "wide_position_observation",
    "object_type": "table",
    "rows": 505,
    "columns": 52,
    "role": "Grouped source records",
    "plain_title": "Rows from reported investment lists",
    "plain_contents": "Each row groups the quantities, costs, values, weights or maturity dates printed for an investment.",
    "plain_separation": "This version rebuilds the source investment list for review. The holding-specific table groups values for later conversion into fund holdings, so the grouping rules can differ.",
    "plain_example": "A bond's cost, current value and maturity date can be compared in one source row while retaining links to each printed fact.",
    "index_contents": "Each row is: one line of a printed list of a fund's investments.\nIt holds: quantity, cost, current value, market value, contract (notional) amount, share of the portfolio, interest rate and maturity date.\nExample: report SRC407, page 3, lists Fifth Cinven Fund (No.3) Limited Partnership at a cost of $2,025,627 and a current value of $1,614,981 at December 31, 2025.\nWhy its own table: this rebuilds the report's investment list exactly as printed. fact_holding groups the same numbers under slightly different rules to build the fund holdings list. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_position_observation.csv"
  },
  "extracted/wide_stewardship_observation": {
    "database": "extracted",
    "object": "wide_stewardship_observation",
    "object_type": "table",
    "rows": 175,
    "columns": 51,
    "role": "Grouped source records",
    "plain_title": "Reported oversight of investments",
    "plain_contents": "Each row groups reported activity measures, such as company meetings, votes, discussions with companies or coverage of those activities.",
    "plain_separation": "Counts of oversight activity measure actions taken by an investor or manager. They remain distinct from financial returns and policy statements.",
    "plain_example": "A count of shareholder votes records activity; a written voting policy belongs in the policy table.",
    "index_contents": "Each row is: one printed count or score about how an investor oversees the companies it owns.\nIt holds: meetings held, votes cast, companies engaged, coverage, scores and targets.\nExample: the NZ Super Fund report SRC339, page 15, counts 6 corporate-governance milestones achieved through talks with companies.\nWhy its own table: these count actions, not money, so they stay out of the financial columns. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_stewardship_observation.csv"
  },
  "extracted/wide_stewardship_policy": {
    "database": "extracted",
    "object": "wide_stewardship_policy",
    "object_type": "table",
    "rows": 81,
    "columns": 45,
    "role": "Grouped source records",
    "plain_title": "Policies for overseeing investments",
    "plain_contents": "Each row records a stated policy for voting, meeting companies or overseeing investments, together with its source.",
    "plain_separation": "A policy states an intended rule or approach. Activity counts record actions performed, so the two require separate records.",
    "plain_example": "A policy about discussing environmental risks with companies stays separate from the reported number of company meetings.",
    "index_contents": "Each row is: one stated policy about voting or overseeing companies.\nIt holds: the policy wording, who it belongs to, and where it is printed.\nExample: the NZ Super Fund report SRC339, page 20, lists recreational cannabis among the products it will not invest in.\nWhy its own table: a policy is a stated rule, while wide_stewardship_observation counts what was actually done. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_stewardship_policy.csv"
  },
  "extracted/wide_subscription_reference": {
    "database": "extracted",
    "object": "wide_subscription_reference",
    "object_type": "table",
    "rows": 19,
    "columns": 51,
    "role": "Grouped source records",
    "plain_title": "Details from investment applications",
    "plain_contents": "Each row groups details from an application to invest: fund and manager names, amounts requested or accepted, applicant type and signing date.",
    "plain_separation": "An application and an actual cash payment are different events. Requested and accepted commitments also need separate fields.",
    "plain_example": "An amount requested on an application can differ from the amount the fund accepts and from the amount later paid.",
    "index_contents": "Each row is: one detail from a subscription agreement, the form an investor signs to join a fund.\nIt holds: the fund and its general partner (the manager's legal entity), the amount requested and the amount accepted, the investor type, the fund's legal home, and the signing date.\nExample: in SRC607 the Pennsylvania State Employees' Retirement System requests a $25 million subscription and signs on 6/25/14.\nWhy its own table: asking to invest, being accepted and actually paying are three different events with three different amounts. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_subscription_reference.csv"
  },
  "extracted/wide_valuation_observation": {
    "database": "extracted",
    "object": "wide_valuation_observation",
    "object_type": "table",
    "rows": 31,
    "columns": 50,
    "role": "Grouped source records",
    "plain_title": "Methods used to value investments",
    "plain_contents": "Each row records reported valuation methods, who performs the valuation, its frequency, review arrangements and any related stated value.",
    "plain_separation": "The reported value is a number. Its valuation method explains how that number was determined, so that explanation needs its own record.",
    "plain_example": "A method based on recent market prices and a method based on estimated future income must remain distinguishable.",
    "index_contents": "Each row is: one statement about how investments are valued.\nIt holds: the valuation method, how often values are updated, who values them, who oversees that, whether an outside firm reviews them, and any stated company value (enterprise value).\nExample: the Starwood statement SRC247 says its value per share is updated as of the last calendar day of each month.\nWhy its own table: this explains how a value was reached, which is a different thing from the value itself. Built from fact_observation so a person can check the numbers against the report, line by line. The fund calculations do not read it.",
    "csv_source": "data/extracted/wide/wide_valuation_observation.csv"
  },
  "extracted/vw_document_coverage": {
    "database": "extracted",
    "object": "vw_document_coverage",
    "object_type": "view",
    "rows": 36,
    "columns": 10,
    "role": "Inspection view",
    "plain_title": "Page-review totals for each extracted report",
    "plain_contents": "This saved query combines each report's details with its page-review totals and its expected and recorded finding counts.",
    "plain_separation": "The document table records reports and the page table records individual pages. The query summarizes their records for a report-level inspection.",
    "plain_example": "A report's total combines pages containing extracted figures with other pages whose review found material outside the extraction scope.",
    "index_contents": "Each row is: one report with its page-review totals.\nIt holds: pages reviewed, pages with data, pages with nothing in scope, numbers expected and numbers written.\nExample: SRC607 has 43 pages reviewed, 11 with data, 17 with nothing in scope, and 28 numbers expected and 28 written.\nWhy a view: A view is a saved question: it stores nothing and recalculates from other tables each time it is opened. This one adds up dim_document and dim_page.",
    "csv_source": ""
  },
  "extracted/vw_manager_coverage": {
    "database": "extracted",
    "object": "vw_manager_coverage",
    "object_type": "view",
    "rows": 164,
    "columns": 5,
    "role": "Inspection view",
    "plain_title": "A count of funds with named managers",
    "plain_contents": "This saved query groups fund identities by fund family and counts how many have a recorded manager.",
    "plain_separation": "Individual identities belong in the entity table. This display calculates the family totals when it is opened.",
    "plain_example": "A family group can contain several funds; its manager count shows how many of those funds have a manager attribution.",
    "index_contents": "Each row is: one fund family (a brand with several funds) and how many of its funds have a known manager.\nIt holds: the number of funds, how many have a manager, how many got the manager from the family name, and the number of facts.\nExample: the ABRY family has 2 funds, and both have a manager.\nWhy a view: A view is a saved question: it stores nothing and recalculates from other tables each time it is opened. Each row is a family, so 164 rows are not 164 managers.",
    "csv_source": ""
  },
  "extracted/vw_observation_resolved": {
    "database": "extracted",
    "object": "vw_observation_resolved",
    "object_type": "view",
    "rows": 4622,
    "columns": 76,
    "role": "Inspection view",
    "plain_title": "Facts attached to a known named subject",
    "plain_contents": "This saved query displays facts whose subject has a matched entity record, with the chosen name and manager details beside them.",
    "plain_separation": "Source facts and shared identity records remain separate tables. This query joins them for inspection and includes only facts with a matched subject.",
    "plain_example": "A fund-specific figure can appear here, while an investment-category total can remain only in the full fact table.",
    "index_contents": "Each row is: one accepted fact whose subject is a known fund, manager, investor or company, shown with that subject's name and manager.\nIt holds: every fact_observation column plus the matched name, kind, family and manager from dim_entity.\nExample: the RVPI (current value divided by money paid in) of 0.60 for Hammes Partners III, L.P., from report SRC457, page 9, shown with its manager Hammes Partners.\nWhy a view: A view is a saved question: it stores nothing and recalculates from other tables each time it is opened. Facts about categories or totals with no named subject, about 4,000 of them, are left out, so this is not a count of all facts.",
    "csv_source": ""
  },
  "extracted/vw_observation_scaled": {
    "database": "extracted",
    "object": "vw_observation_scaled",
    "object_type": "view",
    "rows": 8613,
    "columns": 73,
    "role": "Inspection view",
    "plain_title": "Printed amounts expressed in full units",
    "plain_contents": "This saved query displays the accepted facts and an extra amount after applying the report's unit multiplier.",
    "plain_separation": "The original printed number and multiplier stay in the fact table. The database calculates this display from them when it is opened.",
    "plain_example": "A value printed as 250 under a heading of millions appears as 250,000,000 in the extra field; currency exchange requires a separate calculation.",
    "index_contents": "Each row is: one accepted fact with one extra column: the printed number multiplied out by its unit (thousands, millions).\nIt holds: every fact_observation column plus value_scaled.\nExample: the Timber fund's paid-in amount is printed as 57.5 in a table headed in millions, and value_scaled shows 57,500,000.\nWhy a view: A view is a saved question: it stores nothing and recalculates from other tables each time it is opened. The printed number and its unit stay untouched in fact_observation. It does not convert currencies.",
    "csv_source": ""
  }
}

# E01 normalized-holdings tables.
_NORMALIZED_TABLE_TEXT = {
    "investment_owner": ("Holding owners", "Each row is one economic or reporting owner used by normalized positions.", "Owner identity is kept apart from the asset being held, so a held fund cannot become its own owner by accident."),
    "investment_target": ("Investment targets", "Each row is one investee identity such as a company, fund, project, real asset, or unresolved target.", "One target can issue several instruments, so the target identity stays separate from the security or fund interest."),
    "investment_instrument": ("Investment instruments", "Each row is one fund interest, equity security, debt claim, derivative, or other instrument linked to one target.", "Security terms belong to the instrument while the investee identity remains in investment_target."),
    "fund_position": ("Normalized positions", "Each row is one owner-by-instrument position at one measurement grain and date.", "The position keeps fair value, market value, ownership, and portfolio weight as different fields and retains the source holding ID."),
    "lookthrough_edge": ("Direct look-through links", "Each row is one source-supported relationship from a parent position to an underlying fund, target, or position.", "An empty table means the project did not infer an underlying relationship from ownership alone."),
    "holding_field_lineage": ("Normalized field origins", "Each row states where one normalized owner, target, instrument, position, or look-through field came from.", "Field origins stay separate from the business records so one record can contain fields supported by different source observations or rules."),
}
_NORMALIZED_COUNTS = {
    "alts": {"investment_owner": (948, 19), "investment_target": (3270, 20), "investment_instrument": (3277, 23), "fund_position": (3277, 40), "lookthrough_edge": (0, 23), "holding_field_lineage": (16812, 33)},
    "alts_mock": {"investment_owner": (800, 19), "investment_target": (4475, 20), "investment_instrument": (4475, 23), "fund_position": (89503, 40), "lookthrough_edge": (0, 23), "holding_field_lineage": (0, 33)},
}
for _db, _counts in _NORMALIZED_COUNTS.items():
    for _object, (_rows, _columns) in _counts.items():
        _title, _contents, _separation = _NORMALIZED_TABLE_TEXT[_object]
        _prefix = "Generated regression data. " if _db == "alts_mock" else ""
        EMBEDDED_EXPLANATIONS[f"{_db}/{_object}"] = {
            "database": _db,
            "object": _object,
            "object_type": "table",
            "rows": _rows,
            "columns": _columns,
            "role": "Normalized holdings",
            "plain_title": _title,
            "plain_contents": _prefix + _contents,
            "plain_separation": _separation,
            "plain_example": "Open one row to inspect its identity, classification, values, and source or generation labels.",
            "index_contents": _prefix + _contents + " " + _separation,
            "csv_source": f"data/{'synthetic/clean' if _db == 'alts_mock' else 'csv'}/{_object}.csv",
        }


def load_warehouse_explanations() -> dict[tuple[str, str], dict]:
    """Load warehouse explanations by (db_stem, object_name)."""
    if EXPLANATIONS_CSV.is_file():
        try:
            with EXPLANATIONS_CSV.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                result = {}
                for row in reader:
                    db = Path(row["database"]).stem
                    key = (db, row["object"])
                    result[key] = {
                        "database": db,
                        "object": row["object"],
                        "object_type": row["object_type"],
                        "rows": int(row["rows"]),
                        "columns": int(row["columns"]),
                        "role": row.get("role", ""),
                        "plain_title": row["plain_title"],
                        "plain_contents": row["plain_contents"],
                        "plain_separation": row["plain_separation"],
                        "plain_example": row["plain_example"],
                        "index_contents": row["index_contents"],
                        "csv_source": row.get("csv_source", ""),
                    }
                if len(result) >= len(EMBEDDED_EXPLANATIONS):
                    return result
        except Exception:
            pass
    return {
        (v["database"], v["object"]): v
        for v in EMBEDDED_EXPLANATIONS.values()
    }


def load_lineage() -> dict[str, dict[str, str]]:
    if not LINEAGE_CSV.is_file():
        return {}
    try:
        with LINEAGE_CSV.open(encoding="utf-8-sig", newline="") as handle:
            return {row["csv_path"]: row for row in csv.DictReader(handle)}
    except Exception:
        return {}


def load_produced() -> dict[str, dict[str, str]]:
    produced: dict[str, dict[str, str]] = {}
    try:
        from src.pipeline.publish_review_release import stages
        for stage in stages():
            try:
                outputs = list(stage.declared_outputs())
            except Exception:
                continue
            for output in outputs:
                try:
                    key = output.resolve().relative_to(ROOT).as_posix()
                except ValueError:
                    continue
                produced[key] = {
                    "order": str(stage.order),
                    "stage": stage.stage_id,
                    "command": stage.command,
                }
    except Exception:
        pass
    return produced


def get_derivation(
    db: str,
    table: str,
    csv_source: str,
    lineage: dict[str, dict[str, str]],
    produced: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Return the chain of processing that produced this table."""
    steps: list[dict[str, str]] = []
    if not csv_source:
        return steps
    for source in csv_source.split(" | "):
        row = lineage.get(source, {})
        origin = row.get("origin_csv", "")
        module = row.get("python_file", "")
        operation = row.get("agent_operation", "")
        instructions = row.get("instructions_file", "")
        if origin:
            steps.append({"label": "Read from", "value": origin,
                          "note": "The input files recorded for this output."})
        if module:
            steps.append({"label": "Written by", "value": module,
                          "note": "The module recorded for this output."})
        if operation:
            steps.append({"label": "Agent step", "value": operation,
                          "note": "The extraction or review step for these records."})
        if instructions:
            steps.append({"label": "Instructions", "value": instructions,
                          "note": "The instructions for that step."})
        stage = produced.get(source)
        if stage:
            num = stage["order"]
            steps.append({"label": f"Release stage {num}", "value": stage["stage"],
                          "note": stage["command"]})
        steps.append({"label": "Source table file", "value": source,
                      "note": "Records loaded into the database from this file."})
    steps.append({"label": "Loaded into", "value": f"data/warehouse/{db}.duckdb",
                  "note": "A queryable copy of the source table files."})
    return steps


def get_constraints_and_sql(db_path: Path) -> tuple[dict[str, list[dict[str, str]]], dict[str, str]]:
    """Extract constraints and view SQL definitions from a DuckDB database."""
    constraints: dict[str, list[dict[str, str]]] = defaultdict(list)
    views_sql: dict[str, str] = {}
    try:
        import duckdb
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            for t, k, text in con.execute(
                "select table_name, constraint_type, constraint_text from duckdb_constraints()"
            ).fetchall():
                constraints[t].append({"kind": k, "text": text})
            for v, sql in con.execute(
                "select view_name, sql from duckdb_views() where not internal"
            ).fetchall():
                views_sql[v] = sql
        finally:
            con.close()
    except Exception:
        pass
    return constraints, views_sql
