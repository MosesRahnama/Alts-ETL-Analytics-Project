# PDF reading code

The active 42-column field list, prompt builder, validator, and publisher.

| File | Role |
|---|---|
| `csv_wide_contract.py` | The field list: 42 record columns, 17 record families with their grain and kind, document-type routing, and the one vocabulary of 89 metric and 30 term names with definitions. |
| `field_guide.py` | Render allowed field guidance from the route field list. |
| `build_csv_pipeline.py` | Generate worklists, role briefs, and route field lists from schema inputs. |
| `page_grid.py` | Convert PDF word coordinates into row and column word maps. |
| `build_page_grids.py` | Build positional word grids for selected source documents. |
| `csv_workflow.py` | Validate candidates, compare reading groups, build finals, and publish routes. |
| `name_normalization.py` | Collect and standardize fund and manager identities. |
| `fund_attributes.py` | Collect fund constants, decide printed values, and write inheritance and changed-cell evidence for promotion. |
| `__init__.py` | Package marker so Python can import the modules in this folder. |
