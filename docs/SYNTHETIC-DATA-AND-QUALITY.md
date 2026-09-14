# Completion and quality control

| Population | Location | Treatment |
|---|---|---|
| Printed data | `data/extracted/fund-level/` | Source-only snapshot; unsupported size, currency, and status remain blank |
| Integrated demonstration | `data/csv/` | Additional periods and cash flows on the same fund IDs; generated rows and imputed cells labelled |
| Regression fixture | `data/synthetic/` | Separate generated funds for repeatable tests |
| Planted errors | `data/integrated/defect-periods.csv` | Isolated damaged copies; original source and clean completion remain unchanged |

| Control | Enforced result |
|---|---|
| Extraction | Two independent candidates, page coverage, comparison, and source review; publication verifies all reviewed fields |
| Qualifiers | Methods and fee treatment require supporting source wording; entity and table names remain context, not measurement bases |
| Dates | Column and footnote dates retain their meaning; ambiguous slash dates stop normalization until their source-backed order is recorded |
| Cash flows | One total per event; components and cumulative totals are not counted again |
| Accounting scope | Investor positions and whole-fund records retain separate identifiers and currencies |
| Completion currency | Unsupported or conflicting source denominations receive recorded gaps instead of generated monetary rows; no exchange rate is invented |
| Source preservation | Completion cannot supply source-only fund size, currency, status, or source-quality inputs |
| Financial identities | Multiples, commitment, cash-flow signs, valuation changes, and dated returns checked separately |
| Release refusal | Every source and generated failure blocks publication unless a source-value exception matches its record, page, printed amount, and normalized amount |
| Displayed arithmetic | Published differences equal the displayed actual amount minus the displayed expected amount |
| Defect detection | Isolated error families have expected-rule detection scorecards |

Two negative amounts printed in SRC060 retain their FAIL records and [source-backed exceptions](../data/normalization/transformations/quality-source-exceptions.csv). Absent sub-strategy labels remain blank. Parameter medians use qualifying source observations; fallback assumptions carry origin labels.

[Current counts](RELEASE-COUNTS.csv) · [Analytics](../src/analytics/README.md) · [Completion records](../data/integrated/README.md) · [Process](../PROCESS.md)
