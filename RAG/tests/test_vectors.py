from __future__ import annotations

import csv
import json
import shutil

import pytest

from alts_rag.embed import EmbeddingUnavailable, FakeEmbedder
from alts_rag.evaluate import evaluate_offline
from alts_rag.indexer import _content_hash
from alts_rag.mcp import _call
from alts_rag.serve import RagHandler
from alts_rag.service import Engine

from conftest import FIXTURE_ROOT, WORKLIST


class FailingEmbedder(FakeEmbedder):
    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingUnavailable("fixture failure")


def _engine(tmp_path, project=FIXTURE_ROOT, embedder=None) -> Engine:
    item = Engine(project_root=project, runtime=tmp_path / "runtime", embedder=embedder)
    item.index()
    return item


def test_vector_build_excludes_page_blocks_and_reports_coverage(tmp_path) -> None:
    engine = _engine(tmp_path, embedder=FakeEmbedder())
    try:
        result = engine.build_vectors(all_documents=True)
        assert result["active_vectors"] == result["eligible_blocks"]
        assert result["active_vectors"] > 0
        assert engine.store.conn.execute(
            "SELECT COUNT(*) FROM vectors JOIN blocks USING(block_id) WHERE block_kind='page'"
        ).fetchone()[0] == 0
        status = engine.status()
        assert status["vector_enabled"] is True
        assert status["coverage"]["vector_blocks"] == result["active_vectors"]
        assert status["embedding"]["vector_documents"] == 7
    finally:
        engine.close()


def test_vector_search_filters_permission_before_scoring(tmp_path) -> None:
    engine = _engine(tmp_path, embedder=FakeEmbedder())
    try:
        engine.build_vectors(all_documents=True)
        scope = engine.issue_session(
            "extractor_a", purpose="fixture", worklist=WORKLIST
        )
        result = engine.search_sources(
            scope.session_id,
            "assets liabilities shares appraisals",
            retrieval_methods=("vector",),
        )
        assert all(row["file_id"] == "FIX001" for row in result.results)
        assert not any(row["file_id"] == "FIX007" for row in result.results)
    finally:
        engine.close()


def test_mcp_can_request_hybrid_retrieval(tmp_path) -> None:
    engine = _engine(tmp_path, embedder=FakeEmbedder())
    try:
        engine.build_vectors(file_ids=("FIX001",))
        scope = engine.issue_session(
            "extractor_a", purpose="fixture", worklist=WORKLIST
        )
        result = _call(
            engine,
            "search_sources",
            {
                "session_id": scope.session_id,
                "query": "quarter return",
                "retrieval_methods": ["keyword", "vector"],
            },
        )
        assert result["execution_state"] == "OK"
        assert result["methods_used"] == ["keyword", "vector"]
    finally:
        engine.close()


def test_partial_reindex_invalidates_only_selected_document_vectors(tmp_path) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_ROOT, project)
    engine = _engine(tmp_path, project=project, embedder=FakeEmbedder())
    try:
        engine.build_vectors(file_ids=("FIX001", "FIX002"))
        before = {
            row["file_id"]: int(row["n"])
            for row in engine.store.conn.execute(
                "SELECT file_id, COUNT(*) AS n FROM vectors GROUP BY file_id"
            )
        }
        engine.index(("FIX001",))
        after = {
            row["file_id"]: int(row["n"])
            for row in engine.store.conn.execute(
                "SELECT file_id, COUNT(*) AS n FROM vectors GROUP BY file_id"
            )
        }
        assert "FIX001" not in after
        assert after["FIX002"] == before["FIX002"]
        assert engine.status()["vector_enabled"] is True
    finally:
        engine.close()


def test_rebuild_reuses_embedding_cache(tmp_path) -> None:
    engine = _engine(tmp_path, embedder=FakeEmbedder())
    try:
        first = engine.build_vectors(file_ids=("FIX001",))
        second = engine.build_vectors(file_ids=("FIX001",))
        assert first["embedded_blocks"] == first["eligible_blocks"]
        assert second["embedded_blocks"] == 0
        assert second["cache_hits"] == second["eligible_blocks"]
        assert second["vector_version"] == first["vector_version"]
    finally:
        engine.close()


def test_full_text_reindex_keeps_the_embedding_cache(tmp_path) -> None:
    engine = _engine(tmp_path, embedder=FakeEmbedder())
    try:
        first = engine.build_vectors(file_ids=("FIX001",))
        assert first["embedded_blocks"] > 0
        engine.index()
        assert engine.status()["vector_enabled"] is False
        second = engine.build_vectors(file_ids=("FIX001",))
        assert second["embedded_blocks"] == 0
        assert second["cache_hits"] == second["eligible_blocks"]
    finally:
        engine.close()


def test_failed_rebuild_keeps_active_vectors(tmp_path) -> None:
    engine = _engine(tmp_path, embedder=FakeEmbedder())
    try:
        first = engine.build_vectors(file_ids=("FIX001",))
        engine.embedder = FailingEmbedder(key="fake:v2")
        with pytest.raises(EmbeddingUnavailable):
            engine.build_vectors(file_ids=("FIX002",))
        assert engine.store.vector_count("fake:v1") == first["active_vectors"]
        assert engine.store.meta("embedding_model_key") == "fake:v1"
        assert engine.status()["vector_enabled"] is True
        assert engine.store.conn.execute(
            "SELECT COUNT(*) FROM vector_staging"
        ).fetchone()[0] == 0
    finally:
        engine.close()


def test_wrong_embedder_key_disables_vector_results(tmp_path) -> None:
    engine = _engine(tmp_path, embedder=FakeEmbedder(key="fake:v1"))
    try:
        engine.build_vectors(file_ids=("FIX001",))
        engine.embedder = FakeEmbedder(key="fake:v2")
        scope = engine.issue_session(
            "extractor_a", purpose="fixture", worklist=WORKLIST
        )
        result = engine.search_sources(
            scope.session_id,
            "quarter return",
            retrieval_methods=("vector",),
        )
        assert result.execution_state == "EMPTY_RESULTS"
        assert result.methods_used == ()
    finally:
        engine.close()


def test_vector_version_participates_in_search_cache_key(tmp_path) -> None:
    engine = _engine(tmp_path, embedder=FakeEmbedder())
    try:
        engine.build_vectors(file_ids=("FIX001",))
        scope = engine.issue_session(
            "extractor_a", purpose="fixture", worklist=WORKLIST
        )
        engine.search_sources(scope.session_id, "quarter return")
        first = sorted(path.name for path in engine.cache_dir.glob("*.json"))
        engine.store.set_meta("vector_version", "changed")
        engine.search_sources(scope.session_id, "quarter return")
        second = sorted(path.name for path in engine.cache_dir.glob("*.json"))
        assert len(second) == len(first) + 1
    finally:
        engine.close()


def test_stale_source_vectors_are_not_counted_or_scored(tmp_path) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_ROOT, project)
    engine = _engine(tmp_path, project=project, embedder=FakeEmbedder())
    try:
        engine.build_vectors(file_ids=("FIX008",))
        source = project / "data/documents/txt/FIX008_stale.txt"
        source.write_text(source.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        scope = engine.issue_session(
            "reviewer", purpose="stale vector", document_ids=("FIX008",)
        )
        result = engine.search_sources(
            scope.session_id,
            "cash balance",
            file_ids=("FIX008",),
            retrieval_methods=("vector",),
        )
        assert result.execution_state == "STALE_SOURCE"
        status = engine.status()
        assert status["coverage"]["vector_blocks"] == 0
        assert status["vector_enabled"] is False
    finally:
        engine.close()


def test_offline_evaluation_runs_hybrid_for_claim_and_access_cases(tmp_path) -> None:
    engine = _engine(tmp_path, embedder=FakeEmbedder())
    try:
        engine.build_vectors(file_ids=("FIX001", "FIX002"))
        version_1 = engine.store.document("FIX001")["source_version"]
        version_2 = engine.store.document("FIX002")["source_version"]
        cases = tmp_path / "cases.csv"
        cases.write_text(
            "case_id,split,case_kind,file_ids,query,claim_fields,expected_pages,required_context,"
            "expected_field_assessments,source_locations,reference_checked_by,source_version,publication_permission\n"
            f"SEM-1,held-out,lookup,FIX001,quarterly performance,,1,text:return 8.2,,FIX001:p1,fixture,{version_1},permitted\n"
            f"CLAIM-1,dev,constructed_claim,FIX001,Private Equity return,value=8.2;fee_basis=net,1,,"
            f"value=SUPPORTED;fee_basis=INSUFFICIENT_EVIDENCE,FIX001:p1,fixture,{version_1},permitted\n"
            f"ACCESS-1,dev,access_denied,FIX002,Other Fund,,,,,FIX002:p1,fixture,{version_2},permitted\n",
            encoding="utf-8",
        )
        output = tmp_path / "results.csv"
        scope = engine.issue_session(
            "reviewer",
            purpose="evaluation",
            document_ids=("FIX001", "FIX002"),
        )
        evaluate_offline(engine, scope.session_id, cases_path=cases, output_path=output)
        with output.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        hybrid = {
            row["case_id"]: row
            for row in rows
            if row["configuration"] == "keyword_vector_context"
        }
        assert set(hybrid) == {"SEM-1", "CLAIM-1", "ACCESS-1"}
        assert all(row["result"] == "pass" for row in hybrid.values())
        summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
        assert summary["case_count"] == 3
        assert summary["semantic_case_count"] == 1
        assert summary["activation"]["safety_regression"] is False
    finally:
        engine.close()


def test_local_http_serves_dashboard_and_permission_checked_pdf(tmp_path) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_ROOT, project)
    (project / "dashboard.html").write_text("<h1>Fixture dashboard</h1>", encoding="utf-8")
    (project / "rag.html").write_text("<h1>Fixture RAG page</h1>", encoding="utf-8")
    pdf = project / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    engine = _engine(tmp_path, project=project)
    try:
        engine.store.conn.execute(
            "UPDATE documents SET pdf_path=? WHERE file_id='FIX001'", (str(pdf),)
        )
        document = dict(engine.store.document("FIX001"))
        engine.store.conn.execute(
            "UPDATE documents SET content_hash=? WHERE file_id='FIX001'",
            (_content_hash(document),),
        )
        engine.store.conn.commit()
        block_id = engine.store.conn.execute(
            "SELECT block_id FROM blocks WHERE file_id='FIX001' AND block_kind!='page' LIMIT 1"
        ).fetchone()[0]
        permitted = engine.issue_session(
            "reviewer", purpose="source", document_ids=("FIX001",)
        )
        denied = engine.issue_session(
            "reviewer", purpose="other source", document_ids=("FIX002",)
        )
        handler = RagHandler(engine)
        status, headers, body = handler.handle("GET", "/")
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert b"Fixture RAG page" in body
        assert "connect-src 'self'" in headers["Content-Security-Policy"]

        request = json.dumps(
            {"session_id": permitted.session_id, "block_id": block_id}
        ).encode()
        status, headers, body = handler.handle(
            "POST", "/document", request, {"Content-Type": "application/json"}
        )
        assert status == 200
        assert headers["Content-Type"] == "application/pdf"
        assert headers["X-RAG-Physical-Page"] == "1"
        assert body.startswith(b"%PDF")

        request = json.dumps(
            {"session_id": denied.session_id, "block_id": block_id}
        ).encode()
        status, _headers, _body = handler.handle(
            "POST", "/document", request, {"Content-Type": "application/json"}
        )
        assert status == 403
    finally:
        engine.close()


def test_document_endpoint_rebases_a_pdf_path_from_an_old_checkout(tmp_path) -> None:
    project = tmp_path / "current-project"
    shutil.copytree(FIXTURE_ROOT, project)
    pdf = project / "data/documents/pdf/FIX001_fee.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\ncurrent checkout\n%%EOF\n")
    engine = _engine(tmp_path, project=project)
    try:
        old_path = tmp_path / "old-worktree/data/documents/pdf/FIX001_fee.pdf"
        engine.store.conn.execute(
            "UPDATE documents SET pdf_path=? WHERE file_id='FIX001'", (str(old_path),)
        )
        document = dict(engine.store.document("FIX001"))
        engine.store.conn.execute(
            "UPDATE documents SET content_hash=? WHERE file_id='FIX001'",
            (_content_hash(document, project),),
        )
        engine.store.conn.commit()
        block_id = engine.store.conn.execute(
            "SELECT block_id FROM blocks WHERE file_id='FIX001' AND block_kind!='page' LIMIT 1"
        ).fetchone()[0]
        permitted = engine.issue_session(
            "reviewer", purpose="moved checkout", document_ids=("FIX001",)
        )
        handler = RagHandler(engine)
        request = json.dumps(
            {"session_id": permitted.session_id, "block_id": block_id}
        ).encode()

        status, headers, body = handler.handle(
            "POST", "/document", request, {"Content-Type": "application/json"}
        )

        assert status == 200
        assert headers["Content-Type"] == "application/pdf"
        assert headers["X-RAG-File-ID"] == "FIX001"
        assert body == pdf.read_bytes()
        assert engine.store.document("FIX001")["index_state"] == "indexed"
    finally:
        engine.close()
