from __future__ import annotations

import io
import json
import socket
from pathlib import Path

import pytest

from alts_rag.cli import main
from alts_rag.mcp import dispatch, serve_stdio
from alts_rag.network import OutboundRefused, install_socket_guard
from alts_rag.serve import RagHandler
from alts_rag.types import ClaimRequest

from conftest import WORKLIST


def test_status_has_zero_model_activity(engine) -> None:
    status = engine.status()
    assert status["execution_state"] == "OK"
    assert status["keyword_enabled"] is True
    assert status["vector_enabled"] is False
    assert status["coverage"]["indexed_documents"] >= 1
    assert status["coverage"]["textless_documents"] >= 1
    assert status["model"]["execution_state"] == "MODEL_DISABLED"


def test_keyword_search_finds_the_assigned_page(engine) -> None:
    scope = engine.issue_session("extractor_a", purpose="search", worklist=WORKLIST)
    result = engine.search_sources(scope.session_id, "Private Equity 8.2")
    assert result.execution_state == "OK"
    assert result.methods_used == ("keyword",)
    pages = {item["physical_page"] for item in result.results}
    files = {item["file_id"] for item in result.results}
    assert 1 in pages
    assert "FIX001" in files
    assert "FIX002" not in files


def test_unauthorized_document_is_withheld(engine) -> None:
    scope = engine.issue_session("extractor_a", purpose="search", worklist=WORKLIST)
    result = engine.search_sources(scope.session_id, "gross return 12.5")
    files = {item["file_id"] for item in result.results}
    assert "FIX002" not in files
    denied = engine.search_sources(scope.session_id, "gross return", file_ids=("FIX002",))
    assert denied.execution_state == "ACCESS_DENIED"


def test_role_name_in_the_request_is_refused(engine) -> None:
    scope = engine.issue_session("extractor_a", purpose="search", worklist=WORKLIST)
    result = engine.search_sources(scope.session_id, "Private Equity", extra={"role": "reviewer"})
    assert result.execution_state == "ACCESS_DENIED"


def test_extractor_cannot_run_assessment(engine) -> None:
    scope = engine.issue_session("extractor_a", purpose="search", worklist=WORKLIST)
    claim = ClaimRequest(None, "Private Equity", {"value": "8.2", "fee_basis": "net"}, {}, ("FIX001",))
    result = engine.verify_claim(scope.session_id, claim)
    assert result.execution_state == "ACCESS_DENIED"


def test_constructed_rounding_note_is_insufficient_fee_evidence(engine) -> None:
    scope = engine.issue_session("reviewer", purpose="assess", document_ids=("FIX001",))
    claim = ClaimRequest(
        None,
        "Private Equity",
        {"value": "8.2", "fee_basis": "net"},
        {},
        ("FIX001",),
    )
    result = engine.verify_claim(scope.session_id, claim)
    by_field = {item.field: item for item in result.assessments}
    assert by_field["value"].assessment == "SUPPORTED"
    assert by_field["fee_basis"].assessment == "INSUFFICIENT_EVIDENCE"
    assert by_field["fee_basis"].assessment != "SUPPORTED"


def test_net_fee_and_modified_dietz_are_supported(engine) -> None:
    scope = engine.issue_session("reviewer", purpose="assess", document_ids=("FIX006",))
    claim = ClaimRequest(
        None,
        "TOTAL FUND",
        {"value": "10.0", "fee_basis": "net", "method": "modified dietz"},
        {},
        ("FIX006",),
    )
    result = engine.verify_claim(scope.session_id, claim)
    by_field = {item.field: item.assessment for item in result.assessments}
    assert by_field["fee_basis"] == "SUPPORTED"
    assert by_field["method"] == "SUPPORTED"
    notes = [item for item in result.results if item.get("block_kind") == "note" or any(ctx.get("block_kind") == "note" for ctx in item.get("context") or [])]
    assert notes or any(item.get("context") for item in result.results)


def test_quote_from_another_number_fails_assessment(engine) -> None:
    scope = engine.issue_session("reviewer", purpose="assess", document_ids=("FIX005",))
    claim = ClaimRequest(None, "peer median", {"value": "8.2"}, {}, ("FIX005",))
    result = engine.verify_claim(scope.session_id, claim)
    by_field = {item.field: item.assessment for item in result.assessments}
    assert by_field["value"] == "INSUFFICIENT_EVIDENCE"


def test_prompt_injection_is_flagged_and_not_executed(engine) -> None:
    scope = engine.issue_session("reviewer", purpose="search", document_ids=("FIX004",))
    result = engine.search_sources(scope.session_id, "fee median 134")
    assert any(item.get("instruction_like") for item in result.results)
    handler = RagHandler(engine)
    status, _headers, body = handler.handle("GET", "/page/C:/Windows/System32/config")
    assert status == 403


def test_missing_text_is_counted(engine) -> None:
    coverage = engine.store.coverage()
    assert coverage["textless_documents"] >= 1
    document = engine.store.document("FIX003")
    assert document["index_state"] == "textless"


def test_stale_source_is_withheld_from_assessment(engine) -> None:
    txt = Path(engine.store.document("FIX008")["txt_path"])
    original = txt.read_bytes()
    try:
        txt.write_bytes(original + b"\nchanged\n")
        scope = engine.issue_session("reviewer", purpose="assess", document_ids=("FIX008",))
        claim = ClaimRequest(None, "cash", {"value": "13,307,614"}, {}, ("FIX008",))
        result = engine.verify_claim(scope.session_id, claim)
        assert result.execution_state == "STALE_SOURCE"
    finally:
        txt.write_bytes(original)


def test_restricted_document_is_counted(engine) -> None:
    document = engine.store.document("FIX007")
    assert document["index_state"] == "restricted"


def test_model_path_stays_disabled(engine) -> None:
    scope = engine.issue_session("reviewer", purpose="assess", document_ids=("FIX001",))
    claim = ClaimRequest(None, "Private Equity", {"fee_basis": "net"}, {}, ("FIX001",))
    result = engine.model_assess(scope.session_id, claim)
    assert result.execution_state == "MODEL_DISABLED"
    assert all(item.assessment is None for item in result.assessments)


def test_cache_hit_still_checks_access(engine) -> None:
    reviewer = engine.issue_session("reviewer", purpose="search", document_ids=("FIX001", "FIX002"))
    first = engine.search_sources(reviewer.session_id, "gross return 12.5")
    assert any(item["file_id"] == "FIX002" for item in first.results)
    extractor = engine.issue_session("extractor_a", purpose="search", worklist=WORKLIST)
    second = engine.search_sources(extractor.session_id, "gross return 12.5")
    assert all(item["file_id"] != "FIX002" for item in second.results)


def test_unknown_session_is_denied(engine) -> None:
    result = engine.search_sources("missing", "Private Equity")
    assert result.execution_state == "ACCESS_DENIED"


def test_in_process_http_and_mcp(engine) -> None:
    scope = engine.issue_session("reviewer", purpose="tools", document_ids=("FIX001",))
    handler = RagHandler(engine)
    status, headers, body = handler.handle(
        "POST",
        "/search_sources",
        json.dumps({"session_id": scope.session_id, "query": "Private Equity"}).encode(),
        {"Content-Type": "application/json"},
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["operation"] == "search_sources"
    listed = dispatch(engine, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [item["name"] for item in listed["result"]["tools"]]
    assert names == ["search_sources", "get_evidence", "verify_claim", "explain_analytics"]
    called = dispatch(
        engine,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "search_sources", "arguments": {"session_id": scope.session_id, "query": "8.2"}},
        },
    )
    assert "result" in called


def test_stdio_mcp_ignores_notifications_and_answers_requests(engine) -> None:
    incoming = io.StringIO(
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
    )
    outgoing = io.StringIO()
    serve_stdio(engine, incoming, outgoing)
    messages = outgoing.getvalue().splitlines()
    assert len(messages) == 1
    assert json.loads(messages[0])["id"] == 1


def test_stdio_mcp_reports_malformed_input_and_continues(engine) -> None:
    incoming = io.StringIO(
        "{not-json}\n"
        "[]\n"
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
    )
    outgoing = io.StringIO()
    serve_stdio(engine, incoming, outgoing)
    messages = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert [row.get("error", {}).get("code") for row in messages[:2]] == [-32700, -32600]
    assert messages[2]["id"] == 2


def test_cli_status(runtime, monkeypatch) -> None:
    monkeypatch.setenv("ALTS_RAG_RUNTIME", str(runtime))
    from alts_rag.service import Engine
    from conftest import FIXTURE_ROOT

    engine = Engine(project_root=FIXTURE_ROOT, runtime=runtime)
    engine.index()
    engine.close()
    assert main(["--runtime", str(runtime), "--project-root", str(FIXTURE_ROOT), "status"]) == 0


def test_parse_assessments_refuses_missing_fields() -> None:
    from alts_rag.models import ModelResponseError, parse_assessments

    with pytest.raises(ModelResponseError):
        parse_assessments(
            '{"assessments":[{"field":"value","claimed_value":"8.2",'
            '"assessment":"SUPPORTED","reason":"quoted","supporting_ids":["b1"],'
            '"conflicting_ids":[]}]}',
            {"value": "8.2", "fee_basis": "net"},
            {"b1"},
        )


def test_evaluate_offline_writes_temp(engine, tmp_path) -> None:
    from alts_rag.evaluate import evaluate_offline

    cases = tmp_path / "cases.csv"
    cases.write_text(
        "case_id,split,case_kind,file_ids,query,claim_fields,expected_pages,"
        "required_context,expected_field_assessments,source_locations,"
        "reference_checked_by,source_version,publication_permission\n"
        "FIX-1,dev,lookup,FIX001,Private Equity 8.2,,1,,,FIX001:p1,fixture,abc,permitted\n",
        encoding="utf-8",
    )
    out = tmp_path / "results.csv"
    scope = engine.issue_session("reviewer", purpose="offline", document_ids=("FIX001",))
    version = engine.store.document("FIX001")["source_version"]
    text = cases.read_text(encoding="utf-8").replace(",abc,permitted", f",{version},permitted")
    cases.write_text(text, encoding="utf-8")
    path = evaluate_offline(engine, scope.session_id, cases_path=cases, output_path=out)
    text = path.read_text(encoding="utf-8")
    assert "FIX-1" in text
    assert "pass" in text


def test_export_demo_omits_restricted(tmp_path) -> None:
    from alts_rag.export import export_demo
    from alts_rag.paths import PROJECT_ROOT

    path = export_demo(PROJECT_ROOT, destination=tmp_path / "public-demo.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    ids = set(payload.get("permitted_document_ids") or [])
    assert "SRC132" not in ids
    assert "FIX007" not in ids
    for example in payload.get("examples") or []:
        assert "SRC132" not in example.get("file_ids", [])
        assert "FIX007" not in example.get("file_ids", [])
    for item in payload.get("evidence") or []:
        assert item.get("file_id") not in {"SRC132", "FIX007"}
    for row in payload.get("measured") or []:
        assert row.get("case_id", "").startswith("DEV-132") is False


def test_outbound_socket_is_refused(engine) -> None:
    install_socket_guard()
    with pytest.raises(OutboundRefused):
        socket.create_connection(("example.com", 80), timeout=1)


def test_context_review_writes_runtime_csv(engine) -> None:
    scope = engine.issue_session("reviewer", purpose="review", document_ids=("FIX001",))
    claim = ClaimRequest(None, "", {}, {}, ("FIX001",), context_review=True)
    result = engine.verify_claim(scope.session_id, claim)
    assert result.execution_state == "OK"
    path = engine.runtime / "review" / "review-suggestions.csv"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "suggestion_id" in text
    assert "FIX001" in text
