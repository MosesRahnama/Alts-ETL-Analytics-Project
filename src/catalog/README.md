# Catalog

Corpus text preparation, field census, repair, and extraction routing support.

| File | Role |
|---|---|
| `build_txt_corpus.py` | Build page-aligned text from every ledgered PDF. |
| `repair_split_numbers.py` | Repair source-text numbers split across extraction tokens. |
| `census_field_labels.py` | Count recurring source labels used during schema design. |
| `sweep_manager_loci.py` | Collect manager-name evidence from source text. |
| `__init__.py` | Package marker so Python can import the modules in this folder. |

| Folder | Role |
|---|---|
| `simple_pdf_extraction/` | The active 42-column field list, prompt builder, validator, and publisher. |
