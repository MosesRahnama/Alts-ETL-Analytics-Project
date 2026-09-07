# Decision and evidence ledgers

Classification decisions, schema evidence, promotion contracts, and extraction audit trails. Folders here carry no number because they are not a sequence: each holds the evidence of one workflow.

| Folder | Role |
|---|---|
| `analysis/` | Field inventories, schema surveys, manager evidence, and calibration candidates. |
| `doc-type/` | Blind document-type classifications and their adjudicated result. |
| `pipeline/` | Append-only transformation receipts linking every governed input and output hash. |
| `promotion-gate/` | The header contracts validate_round02_promotion.py enforces and the acceptance evidence it reads, one batch per extraction route. |
| `working/` | Document-level evidence produced by the active CSV extraction runtime. |
