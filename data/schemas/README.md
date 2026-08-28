# Extraction schemas

Document routing, the 17 record families, the vocabulary of 89 metric and 30 term names, and the family surveys that define the field list.

| File | Role |
|---|---|
| `EXTRACTION-ROUTING.csv` | Document type to extraction route mapping. |
| `EXTRACTION-DISPATCH-SCOPE.csv` | Active, deferred, reference, and unscheduled source scope. |
| `EXTRACTION-DOC-TYPE-MAP.csv` | Ratified source-type crosswalk. |
| `EXTRACTION-RECORD-FAMILIES.csv` | The 17 record families: grain, category kind (metric, term, or context), fields, and usual vocabulary names. |
| `EXTRACTION-METRIC-CATEGORIES.csv` | The vocabulary, one row per name: 89 metric and 30 term names with definition, unit hint, and usual family. |
| `MASTER-EXTRACTION-SCHEMA.md` | Human field list for source observations. |
| `EXTRACTED-FIELDS.md` | Readable field-selection guide by source type. |
| `METRIC-STANDARD-MEASURES.csv` | One row per published metric ID with a cross-document label, reported scope, and source note; joined into dim_metric.csv. |
| `RETURN-METHOD-BY-DOCUMENT.csv` | Method, fee basis, and supporting source text for each published return group, keyed by document, table, and column. |

| Folder | Role |
|---|---|
| `schema-discovery/` | Per-document-family evidence for extraction fields; one folder per family surveyed. |
