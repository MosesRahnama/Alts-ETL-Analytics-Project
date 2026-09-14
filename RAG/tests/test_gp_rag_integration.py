from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from alts_rag.gp_scoring import load_real_gp_context, resolve_real_gp_scope
from alts_rag.serve import RagHandler
from alts_rag.service import Engine

from conftest import FIXTURE_ROOT


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _gp_files(project: Path) -> None:
    source_path = project / "data-gathering/source_ledger.csv"
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
        source_fields = list(source_rows[0])
    for row in source_rows:
        if row["file_id"] == "FIX002":
            row["issuer_type"] = "gp"
    _write_csv(source_path, source_fields, source_rows)
    _write_csv(
        project / "data/csv/fund_master.csv",
        [
            "fund_id",
            "fund_name",
            "fund_manager_id",
            "fund_manager_name",
            "strategy",
            "sub_strategy",
            "vintage_year",
            "provenance_type",
            "source_document_id",
            "source_page",
            "source_anchor",
            "record_status",
        ],
        [
            {
                "fund_id": "F1",
                "fund_name": "First Fund",
                "fund_manager_id": "M1",
                "fund_manager_name": "Truncated Mana",
                "strategy": "buyout",
                "sub_strategy": "middle_market",
                "vintage_year": "2020",
                "provenance_type": "EXTRACTED",
                "source_document_id": "FIX001",
                "source_page": "1",
                "source_anchor": "Performance table",
                "record_status": "ACTIVE",
            },
            {
                "fund_id": "F2",
                "fund_name": "Second Fund",
                "fund_manager_id": "",
                "fund_manager_name": "",
                "strategy": "credit",
                "sub_strategy": "",
                "vintage_year": "2021",
                "provenance_type": "EXTRACTED",
                "source_document_id": "FIX002",
                "source_page": "1",
                "source_anchor": "Fund heading",
                "record_status": "ACTIVE",
            },
            {
                "fund_id": "F3",
                "fund_name": "Third Fund",
                "fund_manager_id": "",
                "fund_manager_name": "",
                "strategy": "real_assets",
                "sub_strategy": "",
                "vintage_year": "2022",
                "provenance_type": "EXTRACTED",
                "source_document_id": "FIX004",
                "source_page": "1",
                "source_anchor": "Fund heading",
                "record_status": "ACTIVE",
            },
        ],
    )
    _write_csv(
        project / "data/csv/document_entity_context.csv",
        ["file_id", "fund_id", "manager_id", "manager_name"],
        [{"file_id": "FIX001", "fund_id": "F1", "manager_id": "M1", "manager_name": "First Manager"}],
    )
    _write_csv(
        project / "data/csv/document_manager_map.csv",
        [
            "file_id",
            "manager_id",
            "manager_name_raw",
            "relationship_role",
            "adjudication_status",
        ],
        [
            {
                "file_id": "FIX002",
                "manager_id": "M2",
                "manager_name_raw": "Second Manager, L.P.",
                "relationship_role": "general_partner",
                "adjudication_status": "RESOLVED",
            }
        ],
    )


def test_real_gp_context_uses_source_backed_names_and_keeps_unnamed_funds(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_ROOT, project)
    _gp_files(project)
    context = load_real_gp_context(project, ("FIX001", "FIX002", "FIX004"))

    assert context["execution_state"] == "OK"
    assert context["manager_count"] == 2
    assert context["fund_count"] == 3
    assert context["fund_document_count"] == 3
    assert [row["manager_name"] for row in context["managers"]] == ["First Manager", "Second Manager, L.P."]
    assert context["managers"][0]["funds"][0]["manager_name_source"] == "document_entity_context"
    assert next(row for row in context["funds"] if row["fund_id"] == "F2")["manager_name_source"] == "document_manager_map"
    assert next(row for row in context["funds"] if row["fund_id"] == "F3")["manager_name"] == ""

    manager_scope = resolve_real_gp_scope(context, manager_key=context["managers"][0]["manager_key"])
    fund_scope = resolve_real_gp_scope(context, fund_id="F2")
    assert manager_scope and manager_scope["file_ids"] == ("FIX001",)
    assert fund_scope and fund_scope["file_ids"] == ("FIX002",)
    assert resolve_real_gp_scope(context, manager_key="unknown") is None


def test_engine_gp_search_restricts_retrieval_to_selected_real_fund(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_ROOT, project)
    _gp_files(project)
    engine = Engine(project_root=project, runtime=tmp_path / "runtime")
    try:
        engine.index()
        scope = engine.issue_session(
            "reviewer",
            purpose="GP source research",
            document_ids=("FIX001", "FIX002"),
        )
        context = engine.gp_manager_context(scope.session_id)
        result = engine.gp_manager_search(
            scope.session_id,
            "Private Equity return",
            fund_id="F1",
            retrieval_methods=("keyword",),
        )
        assert result["execution_state"] == "OK"
        assert result["gp_scope"]["scope_type"] == "fund"
        assert result["gp_scope"]["file_ids"] == ["FIX001"]
        assert result["results"] and {row["file_id"] for row in result["results"]} == {"FIX001"}
        assert engine.gp_manager_search(scope.session_id, "value", fund_id="unknown")["execution_state"] == "ACCESS_DENIED"
        assert context["managers"][0]["manager_name"] == "First Manager"

        handler = RagHandler(engine, local_scope_id=scope.session_id)
        body = b"{}"
        status, _headers, response = handler.handle(
            "POST",
            "/gp_manager_context",
            body,
            {
                "content-type": "application/json",
                "content-length": str(len(body)),
            },
        )
        assert status == 200
        assert json.loads(response)["fund_count"] == 2

        search_body = json.dumps(
            {"query": "Private Equity return", "retrieval_methods": ["keyword"]}
        ).encode()
        search_status, _headers, search_response = handler.handle(
            "POST",
            "/search_sources",
            search_body,
            {
                "content-type": "application/json",
                "content-length": str(len(search_body)),
            },
        )
        assert search_status == 200
        assert json.loads(search_response)["execution_state"] == "OK"

        open_status, _headers, open_response = handler.handle(
            "POST",
            "/gp_manager_context",
            body,
            {"content-type": "application/json", "content-length": str(len(body))},
        )
        assert open_status == 200
        assert json.loads(open_response)["execution_state"] == "OK"
    finally:
        engine.close()
