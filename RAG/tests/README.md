# RAG tests

Offline fixture tests for text and vector search, access, field assessment, approval controls, static export, dashboard integration, and in-process handlers.

python -B -m pytest -q RAG/tests -p no:cacheprovider

Set PYTHONPATH to RAG/src and the repository root. Tests write runtime files to a temporary ALTS_RAG_RUNTIME directory.

| File | Role |
|---|---|
| `conftest.py` | Temporary runtime and fixture Engine. |
| `test_offline_engine.py` | Search, access, assessment, CLI, and transport checks. |
| `test_citations.py` | Number-boundary quote matching. |
| `test_semantic_probe.py` | Existing qualifier-check behavior used by field assessment. |
| `test_hardening.py` | Access, approval, model-response, reindex, export, and HTTP regression checks. |
| `test_vectors.py` | Local model, vector cache, atomic rebuild, stale-version, permission, hybrid, and loopback document checks. |
| `test_dashboard_integration.py` | Local evidence controls and a static dashboard with no loopback probe. |
| `fixtures/` | Mini corpus and extractor worklist. |
