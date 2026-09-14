from __future__ import annotations

import csv
import json
import shutil
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from alts_rag.analytics import AnalyticsUnavailable, explain
from alts_rag.approvals import matching_approval, record_approval
from alts_rag.assessment import assess_fields
from alts_rag.citations import number_in_quote
from alts_rag.context import assemble
from alts_rag.evaluate import RESULT_COLUMNS, evaluate_offline
from alts_rag.cli import main
from alts_rag.export import _case_evidence, export_demo
from alts_rag.indexer import _index_version, _page_blocks
from alts_rag.models import (
    ModelResponseError,
    disabled_model_result,
    model_contract_hash,
    openrouter_chat,
    parse_assessments,
)
from alts_rag.network import OutboundRefused
from alts_rag.pages import numbered_footnotes
from alts_rag.review import context_suggestions
from alts_rag.serve import MAX_BODY_BYTES, RagHandler, bind_loopback
from alts_rag.service import Engine
from alts_rag.store import AccessStore, Store
from alts_rag.tables import row_blocks
from alts_rag.types import ClaimRequest, QueryScope

from conftest import FIXTURE_ROOT


def test_loopback_server_accepts_concurrent_browser_connections(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_ROOT, project)
    (project / "rag.html").write_text("<title>RAG reviewer page</title>", encoding="utf-8")
    (project / "dashboard.html").write_text("<title>Main dashboard</title>", encoding="utf-8")
    (project / "GP-Scoring/06-report").mkdir(parents=True)
    (project / "GP-Scoring/06-report/dashboard.html").write_text("<title>GP dashboard</title>", encoding="utf-8")
    (project / "GP-Scoring/04-diagnostics").mkdir(parents=True)
    (project / "GP-Scoring/04-diagnostics/results.csv").write_text("id\n1\n", encoding="utf-8")
    (project / "RAG/evaluation").mkdir(parents=True)
    (project / "RAG/evaluation/public-demo.json").write_text("{}", encoding="utf-8")
    engine = Engine(project_root=project, runtime=tmp_path / "runtime")
    scope = engine.issue_session(
        "reviewer", purpose="local dashboard", document_ids=()
    )
    server = bind_loopback(
        engine, confirm=True, port=0, local_scope_id=scope.session_id
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert isinstance(server, ThreadingHTTPServer)
        assert server.server_address[0] == "127.0.0.1"
        address = f"http://127.0.0.1:{server.server_address[1]}/status"
        with urllib.request.urlopen(address, timeout=5) as response:  # noqa: S310
            assert response.status == 200
            assert json.loads(response.read())["execution_state"] == "EMPTY_RESULTS"
        for path, title in (
            ("/", b"RAG reviewer page"),
            ("/rag.html", b"RAG reviewer page"),
            ("/dashboard.html", b"Main dashboard"),
            ("/GP-Scoring/06-report/dashboard.html", b"GP dashboard"),
        ):
            with urllib.request.urlopen(address.removesuffix("/status") + path, timeout=5) as response:  # noqa: S310
                assert response.status == 200
                assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
                assert "frame-ancestors 'self'" in response.headers["Content-Security-Policy"]
                assert response.headers.get("Set-Cookie") is None
                assert title in response.read()
        preflight = urllib.request.Request(
            address.removesuffix("/status") + "/gp_manager_context",
            method="OPTIONS",
            headers={
                "Origin": "null",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        with urllib.request.urlopen(preflight, timeout=5) as response:  # noqa: S310
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == "null"
            assert response.headers["Access-Control-Allow-Private-Network"] == "true"
        local_file_search = urllib.request.Request(
            address.removesuffix("/status") + "/search_sources",
            method="POST",
            data=b'{"query":"management fees","retrieval_methods":["keyword"]}',
            headers={"Origin": "null", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(local_file_search, timeout=5) as response:  # noqa: S310
            assert response.status == 200
            assert response.headers["Access-Control-Allow-Origin"] == "null"
            assert json.loads(response.read())["execution_state"] in {"OK", "EMPTY_RESULTS"}
        favicon_address = address.removesuffix("/status") + "/favicon.ico"
        with urllib.request.urlopen(favicon_address, timeout=5) as response:  # noqa: S310
            assert response.status == 204
        static_address = address.removesuffix("/status") + "/RAG/evaluation/public-demo.json"
        with urllib.request.urlopen(static_address, timeout=5) as response:  # noqa: S310
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("application/json")
            assert response.read() == b"{}"
        gp_data = address.removesuffix("/status") + "/GP-Scoring/04-diagnostics/results.csv"
        with urllib.request.urlopen(gp_data, timeout=5) as response:  # noqa: S310
            assert response.headers["Content-Type"].startswith("text/csv")
            assert response.read().replace(b"\r\n", b"\n") == b"id\n1\n"
    finally:
        server.shutdown()
        server.server_close()
        engine.close()
        thread.join(timeout=5)


def _document(file_id: str, page_count: int = 1) -> dict:
    return {
        "file_id": file_id,
        "filename": f"{file_id}.pdf",
        "doc_type": "Report",
        "source_version": "v1",
        "page_count": page_count,
        "txt_path": "",
        "pdf_path": "",
        "grid_path": "",
        "image_dir": "",
        "text_state": "native",
        "index_state": "indexed",
        "routing_status": "READY",
        "disagreement": "",
        "product_tier": "A",
        "content_hash": "hash",
        "layout_features": "",
    }


def _block(block_id: str, file_id: str, page: int, text: str, kind: str = "paragraph") -> dict:
    return {
        "block_id": block_id,
        "file_id": file_id,
        "source_version": "v1",
        "physical_page": page,
        "printed_page": None,
        "block_kind": kind,
        "original_text": text,
        "search_text": text.lower(),
        "parent_id": None,
        "layout_uncertain": 0,
        "source_representation": "fixture",
        "text_start": 0,
        "text_end": len(text),
    }


def test_selected_model_stays_disabled_until_provider_contract_is_verified() -> None:
    status = disabled_model_result("verify_claim")
    assert status["requested_model"] == "GPT-5.6 Luna"
    assert status["requested_reasoning"] == "max"
    assert status["identifier_status"] == "unverified"
    assert status["execution_state"] == "MODEL_DISABLED"


def test_status_names_an_unbuilt_index(tmp_path) -> None:
    engine = Engine(FIXTURE_ROOT, tmp_path / "runtime")
    try:
        status = engine.status()
        assert status["execution_state"] == "EMPTY_RESULTS"
        assert status["index_version"] == ""
        assert "INDEX_NOT_BUILT" in status["warnings"]
    finally:
        engine.close()


def test_approval_requires_exact_model_scope_and_authorization_reference(tmp_path) -> None:
    store = AccessStore(tmp_path / "access.sqlite")
    try:
        record_approval(
            store,
            approval_id="approved-job",
            authorization_reference="operator-record-1",
            operation="verify_claim",
            provider="openrouter",
            model_id="provider/exact-model",
            reasoning_setting="max",
            provider_contract_hash="contract-1",
            documents=("DOC1",),
            fields=("value",),
            request_limit=1,
            spending_cap="0.10",
            max_input_tokens=1000,
            max_output_tokens=100,
            input_usd_per_m="1.00",
            output_usd_per_m="2.00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
        assert matching_approval(
            store,
            "verify_claim",
            ("DOC1",),
            provider="openrouter",
            model_id="provider/exact-model",
            reasoning_setting="max",
            provider_contract_hash="contract-1",
            fields=("value",),
        ) is not None
        assert matching_approval(
            store,
            "verify_claim",
            ("DOC1",),
            provider_contract_hash="changed-contract",
        ) is None
        assert matching_approval(store, "verify_claim", ("DOC2",)) is None
        assert matching_approval(store, "verify_claim", ("DOC1",), fields=("fee_basis",)) is None
    finally:
        store.close()


def test_legacy_blank_authorization_does_not_grant_model_access(tmp_path) -> None:
    store = AccessStore(tmp_path / "access.sqlite")
    try:
        store.conn.execute(
            """
            INSERT INTO approvals(
                approval_id, operation, provider, model_id, reasoning_setting, documents,
                fields, request_limit, spending_cap, expires_at, granted_by
            ) VALUES('legacy','verify_claim','openrouter','old/model','max','DOC1','value',1,'1','2099','Moses')
            """
        )
        store.conn.commit()
        assert matching_approval(store, "verify_claim", ("DOC1",)) is None
    finally:
        store.close()


def test_cli_records_only_an_explicit_bounded_approval(tmp_path, capsys, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    config = {
        "provider": "openrouter",
        "model_name": "Configured test model",
        "model_id": "provider/exact-model",
        "reasoning_setting": "max",
        "identifier_status": "verified",
        "reasoning_request": {"reasoning": {"effort": "max"}},
    }
    monkeypatch.setattr("alts_rag.cli.model_configuration", lambda: config)
    assert main(
        [
            "--runtime", str(runtime),
            "--project-root", str(FIXTURE_ROOT),
            "record-approval",
            "--approval-id", "job-1",
            "--authorization-reference", "operator-message-1",
            "--provider", "openrouter",
            "--model-id", "provider/exact-model",
            "--reasoning", "max",
            "--document-id", "FIX001",
            "--field", "value",
            "--request-limit", "1",
            "--spending-cap", "0.05",
            "--max-input-tokens", "1000",
            "--max-output-tokens", "100",
            "--input-usd-per-m", "1",
            "--output-usd-per-m", "2",
            "--expires-at", "2099-01-01T00:00:00+00:00",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out) == {"approval_id": "job-1", "recorded": True}
    store = AccessStore(runtime / "access.sqlite")
    try:
        row = store.conn.execute("SELECT * FROM approvals WHERE approval_id='job-1'").fetchone()
        assert row["authorization_reference"] == "operator-message-1"
        assert row["request_limit"] == 1
        assert row["provider_contract_hash"] == model_contract_hash(config)
    finally:
        store.close()


def test_model_output_must_cover_each_field_and_use_supplied_citations() -> None:
    valid = json.dumps(
        {
            "assessments": [
                {
                    "field": "value",
                    "claimed_value": "8.2",
                    "assessment": "SUPPORTED",
                    "reason": "The value is printed.",
                    "supporting_ids": ["B1"],
                    "conflicting_ids": [],
                }
            ]
        }
    )
    assert parse_assessments(valid, {"value": "8.2"}, {"B1"})[0].assessment == "SUPPORTED"
    with pytest.raises(ModelResponseError):
        parse_assessments(valid.replace("B1", "MADE-UP"), {"value": "8.2"}, {"B1"})


def test_parenthetical_negative_does_not_support_a_positive_claim() -> None:
    assert number_in_quote("(50,614,177)", "Ending balance (50,614,177)")
    assert not number_in_quote("50,614,177", "Ending balance (50,614,177)")


def test_currency_signs_preserve_negative_financial_values() -> None:
    assert number_in_quote("-1000", "Distribution -$1,000")
    assert number_in_quote("-1000", "Loss ($1,000)")
    assert not number_in_quote("1000", "Loss ($1,000)")


def test_context_citations_name_the_context_block() -> None:
    blocks = [
        {
            "block_id": "PRIMARY",
            "original_text": "Performance summary",
            "context": [{"block_id": "NOTE", "original_text": "Net of fees"}],
        }
    ]
    row = assess_fields({"fee_basis": "net"}, blocks)[0]
    assert row.supporting_ids == ("NOTE",)


def test_qualifier_must_share_the_value_result_context() -> None:
    blocks = [
        {"block_id": "VALUE", "original_text": "Reported return 12.5%", "context": []},
        {"block_id": "OTHER", "original_text": "Another schedule is net of fees", "context": []},
    ]
    rows = {row.field: row for row in assess_fields({"value": "12.5", "fee_basis": "net"}, blocks)}
    assert rows["value"].assessment == "SUPPORTED"
    assert rows["fee_basis"].assessment == "INSUFFICIENT_EVIDENCE"

    blocks[0]["context"] = [{"block_id": "NOTE", "original_text": "The reported return is net of fees."}]
    rows = {row.field: row for row in assess_fields({"value": "12.5", "fee_basis": "net"}, blocks)}
    assert rows["fee_basis"].assessment == "SUPPORTED"
    assert rows["fee_basis"].supporting_ids == ("NOTE",)


def test_unit_citations_use_the_claimed_unit_and_blank_values_are_retained() -> None:
    blocks = [
        {"block_id": "VALUE", "original_text": "NAV $12.5", "context": []},
        {"block_id": "PERCENT", "original_text": "Return 7 percent", "context": []},
    ]
    rows = {row.field: row for row in assess_fields({"value": "12.5", "unit": "USD"}, blocks)}
    assert rows["unit"].assessment == "SUPPORTED"
    assert rows["unit"].supporting_ids == ("VALUE",)
    blank = assess_fields({"value": ""}, blocks)
    assert len(blank) == 1
    assert blank[0].assessment == "INSUFFICIENT_EVIDENCE"


def test_grid_rows_with_the_same_label_keep_distinct_row_indices(tmp_path) -> None:
    grid = tmp_path / "grid.csv"
    grid.write_text(
        "file_id,source_page,row_index,source_row_label,column_index,column_x,source_column_label,value_raw\n"
        "DOC1,1,1,Total,1,10,Value,10\n"
        "DOC1,1,2,Total,1,10,Value,20\n",
        encoding="utf-8",
    )
    blocks, relations = row_blocks(grid, "DOC1", "v1")
    assert len(blocks) == 2
    assert len({row["block_id"] for row in blocks}) == 2
    assert all(kind == "row_of_page" for _source, _target, kind in relations)


def test_context_budget_truncates_a_long_primary(tmp_path, monkeypatch) -> None:
    store = Store(tmp_path / "index.sqlite")
    try:
        store.replace_documents([_document("DOC1")])
        store.replace_blocks([_block("B1", "DOC1", 1, "x" * 100)], [])
        monkeypatch.setattr("alts_rag.context.retrieval_policy", lambda: {"context_char_budget": 20})
        scope = QueryScope("S", "reviewer", ("DOC1",), ("extracted",), "test")
        result = assemble(store, [("B1", 1.0, ("keyword",))], scope)
        assert len(result[0]["original_text"]) == 20
        assert result[0]["truncated"] is True
        assert result[0]["continuation_ids"] == ["B1"]
    finally:
        store.close()


def test_coverage_counts_pages_that_have_indexed_blocks(tmp_path) -> None:
    store = Store(tmp_path / "index.sqlite")
    try:
        store.replace_documents([_document("DOC1", page_count=99)])
        store.replace_blocks(
            [_block("B1", "DOC1", 1, "one"), _block("B2", "DOC1", 2, "two")], []
        )
        assert store.coverage()["indexed_pages"] == 2
    finally:
        store.close()


def test_partial_reindex_preserves_other_documents_and_changes_version(tmp_path) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_ROOT, project)
    engine = Engine(project_root=project, runtime=tmp_path / "runtime")
    try:
        engine.index()
        before_ids = {row["file_id"] for row in engine.store.documents()}
        before_version = engine.store.meta("index_version")
        source = project / "data/documents/txt/FIX001_fee.txt"
        source.write_text(source.read_text(encoding="utf-8") + "\nAdditional fact.\n", encoding="utf-8")
        engine.index(("FIX001",))
        assert {row["file_id"] for row in engine.store.documents()} == before_ids
        assert engine.store.meta("index_version") != before_version
    finally:
        engine.close()


def test_freshness_hashes_only_requested_documents_and_reuses_file_signatures(engine, monkeypatch) -> None:
    from alts_rag import indexer

    original = indexer._content_hash
    seen: list[str] = []

    def counted(document, project_root=None):
        seen.append(document["file_id"])
        return original(document, project_root)

    monkeypatch.setattr(indexer, "_content_hash", counted)
    scope = engine.issue_session(
        "reviewer", purpose="freshness", document_ids=("FIX001", "FIX002")
    )
    engine.search_sources(scope.session_id, "Private Equity", file_ids=("FIX001",))
    engine.search_sources(scope.session_id, "Private Equity", file_ids=("FIX001",))
    engine.search_sources(scope.session_id, "other", file_ids=("FIX002",))
    assert seen == ["FIX001", "FIX002"]


def test_query_results_reuse_unchanged_index_coverage(engine, monkeypatch) -> None:
    original = engine.store.coverage
    calls = 0

    def counted():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(engine.store, "coverage", counted)
    scope = engine.issue_session("reviewer", purpose="coverage", document_ids=("FIX001",))
    engine.search_sources(scope.session_id, "Private Equity", file_ids=("FIX001",))
    engine.search_sources(scope.session_id, "8.2", file_ids=("FIX001",))
    assert calls == 1


def test_context_lookup_indexes_exist(tmp_path) -> None:
    store = Store(tmp_path / "index.sqlite")
    try:
        blocks = {row["name"] for row in store.conn.execute("PRAGMA index_list(blocks)")}
        relations = {row["name"] for row in store.conn.execute("PRAGMA index_list(relations)")}
        assert "blocks_file_page_kind_idx" in blocks
        assert {"relations_from_id_idx", "relations_to_id_idx"}.issubset(relations)
    finally:
        store.close()


def test_deleted_index_input_marks_only_that_document_stale(tmp_path) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_ROOT, project)
    engine = Engine(project_root=project, runtime=tmp_path / "runtime")
    try:
        engine.index()
        scope = engine.issue_session(
            "reviewer", purpose="freshness", document_ids=("FIX001", "FIX002")
        )
        (project / "data/documents/txt/FIX001_fee.txt").unlink()
        result = engine.search_sources(scope.session_id, "Private Equity", file_ids=("FIX001",))
        assert result.execution_state == "STALE_SOURCE"
        assert engine.store.document("FIX002")["index_state"] == "indexed"
    finally:
        engine.close()


def test_numbered_footnotes_are_separate_evidence_blocks() -> None:
    rows = numbered_footnotes("Summary\nFootnotes\n1. As of April 30.\n2. NAV means net asset value.")
    assert [(number, text) for number, text, _start, _end in rows] == [
        ("1", "1. As of April 30."),
        ("2", "2. NAV means net asset value."),
    ]


def test_numbered_footnotes_survive_multi_column_reading_order() -> None:
    text = (
        "5. Net leverage is debt less cash divided by NAV.\n"
        "Text from the left column. 6. First-lien percentage is measured at fair value.\n"
        "Footnotes\n"
        "1. As of April 30.\n"
        "2. Distribution rate uses month-end NAV."
    )
    rows = numbered_footnotes(text)
    assert [number for number, _text, _start, _end in rows] == ["5", "6", "1", "2"]


def test_multi_column_layout_marks_all_page_blocks_uncertain() -> None:
    rows = _page_blocks(
        "DOC1",
        "v1",
        1,
        "Summary\n\nFootnotes\n1. As of April 30.",
        "native",
        layout_uncertain=True,
    )
    assert rows
    assert all(row["layout_uncertain"] == 1 for row in rows)


def test_index_version_covers_layout_metadata_and_relations(tmp_path) -> None:
    store = Store(tmp_path / "index.sqlite")
    try:
        document = _document("DOC1")
        block = _block("DOC1:p1:paragraph:1", "DOC1", 1, "Evidence")
        store.replace_documents([document])
        store.replace_blocks([block], [])
        original = _index_version(store)

        document["layout_features"] = "multi_column"
        block["layout_uncertain"] = 1
        store.replace_documents([document])
        store.replace_blocks([block], [(block["block_id"], "DOC1:p1:page:0", "child_of")])
        assert _index_version(store) != original
    finally:
        store.close()


def test_context_review_includes_short_numbered_footnotes(tmp_path) -> None:
    store = Store(tmp_path / "index.sqlite")
    try:
        store.replace_documents([_document("DOC1")])
        store.replace_blocks(
            [_block("DOC1:p1:footnote:1", "DOC1", 1, "1. As of April 30.", "footnote")],
            [],
        )
        scope = QueryScope("S", "reviewer", ("DOC1",), ("extracted",), "test")
        rows = context_suggestions(store, scope, "DOC1", "REQ", tmp_path, tmp_path / "runtime")
        assert [(row["field"], row["evidence_ids"]) for row in rows] == [
            ("condition", "DOC1:p1:footnote:1")
        ]
    finally:
        store.close()


def test_claim_outside_session_is_denied_before_assessment(engine) -> None:
    scope = engine.issue_session("reviewer", purpose="assess", document_ids=("FIX001",))
    claim = ClaimRequest(None, "gross return", {"value": "12.5"}, {}, ("FIX002",))
    assert engine.verify_claim(scope.session_id, claim).execution_state == "ACCESS_DENIED"
    assert engine.model_assess(scope.session_id, claim).execution_state == "ACCESS_DENIED"


def test_model_adapter_is_not_constructed_after_empty_retrieval(engine, monkeypatch) -> None:
    config = {
        "provider": "openrouter",
        "model_name": "Configured test model",
        "model_id": "provider/model",
        "reasoning_setting": "max",
        "identifier_status": "verified",
        "reasoning_request": {"reasoning": {"effort": "max"}},
    }
    monkeypatch.setattr("alts_rag.service.model_configuration", lambda: config)
    monkeypatch.setattr("alts_rag.service.model_is_configured", lambda _config: True)
    monkeypatch.setattr("alts_rag.service.require_approval", lambda *_args, **_kwargs: object())

    def forbidden_adapter(*_args, **_kwargs):
        raise AssertionError("model adapter was constructed after empty retrieval")

    monkeypatch.setattr("alts_rag.service.OpenRouterAdapter", forbidden_adapter)
    scope = engine.issue_session("reviewer", purpose="empty evidence", document_ids=("FIX001",))
    claim = ClaimRequest(None, "zzzz-no-match", {"value": "qqqq-no-match"}, {}, ("FIX001",))
    assert engine.model_assess(scope.session_id, claim).execution_state == "EMPTY_RESULTS"


def test_socket_guard_is_recorded_as_not_sent(monkeypatch) -> None:
    from alts_rag.approvals import Approval

    settings = {
        "provider": "openrouter",
        "model_name": "Test",
        "model_id": "provider/model",
        "reasoning_setting": "max",
        "identifier_status": "verified",
        "reasoning_request": {"reasoning": {"effort": "max"}},
    }
    approval = Approval(
        approval_id="test",
        operation="verify_claim",
        provider="openrouter",
        model_id="provider/model",
        reasoning_setting="max",
        documents=("FIX001",),
        fields=("value",),
        request_limit=1,
        spending_cap="1",
        expires_at="2099-01-01T00:00:00+00:00",
        granted_by="Moses",
        authorization_reference="fixture",
        provider_contract_hash=model_contract_hash(settings),
        max_input_tokens=1000,
        max_output_tokens=100,
        input_usd_per_m="1",
        output_usd_per_m="1",
    )

    def refused(*_args, **_kwargs):
        raise urllib.error.URLError(OutboundRefused("socket disabled"))

    monkeypatch.setattr("alts_rag.models.load_openrouter_key", lambda: "fixture-key")
    monkeypatch.setattr("urllib.request.urlopen", refused)
    with pytest.raises(OutboundRefused):
        openrouter_chat([], approval=approval, settings=settings)


def test_http_refuses_token_in_get_cross_origin_and_large_body(engine) -> None:
    handler = RagHandler(engine)
    status, _headers, _body = handler.handle("GET", "/search?session=secret&q=value")
    assert status == 404
    status, _headers, _body = handler.handle(
        "POST",
        "/search_sources",
        b"{}",
        {"Content-Type": "application/json", "Origin": "https://example.com"},
    )
    assert status == 403
    status, _headers, _body = handler.handle(
        "POST",
        "/search_sources",
        b"",
        {"Content-Type": "application/json", "Content-Length": str(MAX_BODY_BYTES + 1)},
    )
    assert status == 413
    status, _headers, _body = handler.handle(
        "POST",
        "/search_sources",
        b"",
        {"Content-Type": "application/json", "Content-Length": "-1"},
    )
    assert status == 400


def test_fund_metrics_are_limited_to_permitted_source_documents(tmp_path) -> None:
    root = tmp_path / "project" / "data/extracted/fund-level"
    root.mkdir(parents=True)
    (root / "fund_periods.csv").write_text(
        "fund_period_id,fund_id,source_document_id\nP1,F1,SRC1\nP2,F2,SRC2\n",
        encoding="utf-8",
    )
    (root / "fund_metrics.csv").write_text(
        "analysis_result_id,entity_id,input_record_ids,provenance_type\n"
        "M1,F1,P1,EXTRACTED\nM2,F2,P2,EXTRACTED\nM3,F1,P1;C1,EXTRACTED\n",
        encoding="utf-8",
    )
    (root / "fund_cashflows.csv").write_text(
        "cashflow_id,fund_id,file_id\nC1,F1,SRC1\n",
        encoding="utf-8",
    )
    (root / "fund_master.csv").write_text(
        "fund_id,source_document_id\nF1,SRC1\nF2,SRC2\n",
        encoding="utf-8",
    )
    scope = QueryScope("S", "reviewer", ("SRC1",), ("extracted",), "test")
    result = explain(tmp_path / "project", scope, "fund_metrics", {}, "extracted")
    assert [row["analysis_result_id"] for row in result["rows"]] == ["M1", "M3"]
    with pytest.raises(PermissionError):
        explain(tmp_path / "project", scope, "fund_metrics", {}, "integrated")


def test_query_contract_refuses_a_mislabeled_data_group(tmp_path) -> None:
    scope = QueryScope("S", "reviewer", ("SRC1",), ("extracted", "integrated"), "test")
    result = explain(tmp_path, scope, "fund_evidence", {}, "integrated")
    assert result["execution_state"] == "QUERY_UNSUPPORTED"
    assert result["rows"] == []


def test_integrated_result_origin_uses_target_fund_ownership(tmp_path) -> None:
    integrated = tmp_path / "data/integrated"
    integrated.mkdir(parents=True)
    (integrated / "cell-lineage.csv").write_text(
        "target_table,target_record_id,target_field,provenance_type,source_document_id\n"
        "fund_periods,P1,nav,SYNTHETIC,\n"
        "fund_periods,P2,nav,SYNTHETIC,\n",
        encoding="utf-8",
    )
    csv_root = tmp_path / "data/csv"
    csv_root.mkdir(parents=True)
    (csv_root / "fund_master.csv").write_text(
        "fund_id,source_document_id\nF1,SRC1\nF2,SRC2\n",
        encoding="utf-8",
    )
    (csv_root / "fund_periods.csv").write_text(
        "fund_period_id,fund_id\nP1,F1\nP2,F2\n",
        encoding="utf-8",
    )
    scope = QueryScope("S", "reviewer", ("SRC1",), ("integrated",), "test")
    result = explain(tmp_path, scope, "result_origin", {}, "integrated")
    assert [row["target_record_id"] for row in result["rows"]] == ["P1"]


def test_missing_analytical_table_is_not_reported_as_an_empty_result(tmp_path) -> None:
    scope = QueryScope("S", "reviewer", ("SRC1",), ("extracted",), "test")
    with pytest.raises(AnalyticsUnavailable, match="fact_observation.csv"):
        explain(tmp_path, scope, "observation_context", {"observation_id": "OBS1"})


def test_offline_rerun_preserves_and_relabels_historical_model_rows(engine, tmp_path) -> None:
    version = engine.store.document("FIX001")["source_version"]
    cases = tmp_path / "cases.csv"
    cases.write_text(
        "case_id,split,case_kind,file_ids,query,claim_fields,expected_pages,required_context,"
        "expected_field_assessments,source_locations,reference_checked_by,source_version,publication_permission\n"
        f"FIX-1,dev,lookup,FIX001,Private Equity 8.2,,1,,,FIX001:p1,fixture,{version},permitted\n",
        encoding="utf-8",
    )
    output = tmp_path / "results.csv"
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "FIX-1",
                "split": "dev",
                "configuration": "approved_assessor",
                "model_version": "old/model",
                "result": "pass",
                "execution_state": "OK",
                "label": "model",
                "publication_permission": "permitted",
            }
        )
    scope = engine.issue_session("reviewer", purpose="evaluate", document_ids=("FIX001",))
    evaluate_offline(engine, scope.session_id, cases_path=cases, output_path=output)
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    historical = next(row for row in rows if row["configuration"] == "approved_assessor")
    assert historical["label"] == "historical_model_unverified_authorization"
    assert any(row["configuration"] == "keyword" for row in rows)


def test_public_export_is_bounded_and_omits_unrun_model_rows(engine, tmp_path, monkeypatch) -> None:
    evaluation = tmp_path / "evaluation"
    evaluation.mkdir()
    (evaluation / "cases.csv").write_text(
        "case_id,split,file_ids,query,expected_pages,reference_checked_by,publication_permission\n"
        "CASE-1,held,FIX001,Private Equity 8.2,1,native PDF visual review,permitted\n",
        encoding="utf-8",
    )
    with (evaluation / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "CASE-1",
                "split": "held",
                "configuration": "keyword",
                "model_version": "unrun",
                "result": "pass",
                "execution_state": "OK",
                "label": "offline_keyword",
                "publication_permission": "permitted",
            }
        )
        writer.writerow(
            {
                "case_id": "CASE-1",
                "split": "held",
                "configuration": "keyword_vector_context",
                "model_version": "unrun",
                "result": "unrun",
                "execution_state": "MODEL_DISABLED",
                "label": "offline_vector_unrun",
                "publication_permission": "permitted",
            }
        )
    monkeypatch.setattr("alts_rag.export.EVALUATION_DIR", evaluation)
    destination = evaluation / "public-demo.json"
    export_demo(FIXTURE_ROOT, engine=engine, destination=destination)
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert [row["configuration"] for row in payload["measured"]] == ["keyword"]
    assert len(payload["evidence"]) <= 2
    assert all(row["block_kind"] != "page" for row in payload["evidence"])
    assert all(len(row["original_text"]) <= 800 for row in payload["evidence"])


def test_public_export_keeps_cross_page_governing_context() -> None:
    example = {
        "case_id": "CASE",
        "file_ids": ["DOC"],
        "expected_pages": "1",
        "required_context": "page:6|kind:footnote|text:governing basis",
    }
    results = [
        {
            "block_id": "VALUE",
            "file_id": "DOC",
            "physical_page": 1,
            "block_kind": "table_row",
            "original_text": "Reported value 9.00 percent",
            "context": [
                {
                    "block_id": "FOOTNOTE",
                    "file_id": "DOC",
                    "physical_page": 6,
                    "block_kind": "footnote",
                    "original_text": "The governing basis is net asset value.",
                }
            ],
        }
    ]
    rows = _case_evidence(example, results, set())
    assert [(row["block_id"], row["physical_page"]) for row in rows] == [
        ("VALUE", 1),
        ("FOOTNOTE", 6),
    ]


def test_public_export_selects_the_required_block_when_footnotes_overlap() -> None:
    example = {
        "case_id": "CASE",
        "file_ids": ["DOC"],
        "expected_pages": "1",
        "required_context": "block:DOC:p6:footnote:1",
    }
    results = [
        {
            "block_id": "VALUE",
            "file_id": "DOC",
            "physical_page": 1,
            "block_kind": "table_row",
            "original_text": "Reported return 9.43 percent",
            "context": [
                {
                    "block_id": "DOC:p6:footnote:3",
                    "file_id": "DOC",
                    "physical_page": 6,
                    "block_kind": "footnote",
                    "original_text": "Another fact as of April 30.",
                },
                {
                    "block_id": "DOC:p6:footnote:1",
                    "file_id": "DOC",
                    "physical_page": 6,
                    "block_kind": "footnote",
                    "original_text": "The return date is April 30.",
                },
            ],
        }
    ]
    rows = _case_evidence(example, results, set())
    assert [row["block_id"] for row in rows] == ["VALUE", "DOC:p6:footnote:1"]


def test_failed_index_activation_restores_current_index(tmp_path, monkeypatch) -> None:
    engine = Engine(project_root=FIXTURE_ROOT, runtime=tmp_path / "runtime")
    engine.index()
    before = engine.store.meta("index_version")
    original_rename = Path.rename

    def fail_staging_rename(path: Path, target: Path) -> Path:
        if path.name == "staging" and Path(target).name == "current":
            raise OSError("fixture activation failure")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_staging_rename)
    try:
        with pytest.raises(OSError, match="fixture activation failure"):
            engine.index()
        assert engine.store.meta("index_version") == before
        assert engine.store.coverage()["indexed_documents"] > 0
    finally:
        engine.close()
