# Repository

Folder-guide, project-manifest, and structure-verification tools.

| File | Role |
|---|---|
| `build_readmes.py` | Write this project-wide set of folder guides. |
| `build_project_manifest.py` | Record each project file, folder, role, size, and repository policy. |
| `check_project_structure.py` | Verify folder guides, manifest coverage, hashes, and source ownership. |
| `__init__.py` | Package marker so Python can import the modules in this folder. |
| `build_csv_lineage.py` | Record where every CSV in the repository came from. |
| `release_audit.py` | Open every project file with a check for its type, then verify the manifest, folder guides, Git policy, source ledger, landing-page text, and the committed dashboard page. |
