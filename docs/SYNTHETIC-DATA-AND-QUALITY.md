# Completion and quality control

| Population | Location | Treatment |
|---|---|---|
| Printed data | `data/extracted/fund-level/` | Source-only snapshot; unsupported size, currency, and status remain blank |
| Integrated demonstration | `data/csv/` | Additional periods and cash flows on the same fund IDs; generated rows and imputed cells labelled |
| Regression fixture | `data/synthetic/` | Separate generated funds for repeatable tests |
| Planted errors | `data/integrated/defect-periods.csv` | Isolated damaged copies; original source and clean completion remain unchanged |

| Control | Enforced result |
|---|---|
| Extraction | Two independent candidates, page coverage, comparison, and source source review |
| Qualifiers | Missing required method, fee basis, or scope stops publication; source silence is recorded |
| Dates | Specific column and footnote dates supersede report headings; ambiguous dates remain unparsed |
| Cash flows | One total per event; components and cumulative totals are not counted again |
| Accounting scope | Investor positions and whole-fund records retain separate identifiers and currencies |
| Source preservation | Completion cannot supply source-only fund size, currency, status, or source-quality inputs |
| Financial identities | Multiples, commitment, cash-flow signs, valuation changes, and dated returns checked separately |
| Displayed arithmetic | Published differences equal the displayed actual amount minus the displayed expected amount |
| Defect detection | Isolated error families have expected-rule detection scorecards |

Two negative amounts printed in SRC060 remain source discrepancies. Absent sub-strategy labels remain source gaps; the system does not invent them. Parameter medians use qualifying source observations, and fallback assumptions carry their own origin labels.

[Current counts](RELEASE-COUNTS.csv) · [Analytics](../src/analytics/README.md) · [Completion records](../data/integrated/README.md) · [Process](../PROCESS.md)
