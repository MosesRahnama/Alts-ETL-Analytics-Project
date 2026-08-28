# Promotion gate contracts

The header contracts validate_round02_promotion.py enforces and the acceptance evidence it reads, one batch per extraction route.

| File | Role |
|---|---|
| `adjudication_template.csv` | Header validate_round02_promotion.py requires of every round-02 adjudicated file before a row may enter the fund-level tables. Header-only by design: the gate compares a working file's header against this one. |
| `audit_template.csv` | Header the gate requires of the date and schema audit files that must accompany an adjudication. Header-only by design: the gate compares a working file's header against this one. |
| `audit_adjudication_template.csv` | Header the gate requires of the audit adjudication that settles the two audits and carries the promotion decision. Header-only by design: the gate compares a working file's header against this one. |

| Folder | Role |
|---|---|
| `round02/` | Which documents were accepted for promotion into the fund-level tables, written from the published extraction ledger by promote_extracted_to_fund_level; one batch folder per extraction route. |
