# Page pictures

Extraction requires these files. A report is read after every physical page has a 300 DPI PNG. Both reading groups and the third reader open the pictures. Git tracks the manifest. The PNG files stay on the local machine because 300 DPI pages are large.

| Job | Command |
|---|---|
| Full corpus | `python data-gathering/src/render_image_corpus.py` |
| The 29 reports already read | `python data-gathering/src/render_image_corpus.py --published-slice` |
| One future PDF | `python data-gathering/src/render_image_corpus.py --pdf Fee_Report_PSERS_Aon_Base_Management_Fees_FY2017.pdf` |
| Manifest only | `python data-gathering/src/render_image_corpus.py --manifest-only` |
| One assigned file | `python instructions/01-pdf-extraction-csv/workflow.py require-images --route 02-performance --file SRC060` |

One PNG per physical page, named `page-001.png`, under `data/documents/images/<stem>/`. Each page uses that page's crop box and rotation. Existing pages are skipped. `validate-candidate` refuses a file whose picture folder is short.

| File | Role |
|---|---|
| `MANIFEST.csv` | One row per physical page in the published extraction slice: source PDF hash, page number, 300 DPI path, image hash when the PNG is present, and present=0 until rendered. |
