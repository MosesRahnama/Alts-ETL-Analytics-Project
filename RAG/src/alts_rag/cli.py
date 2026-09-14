"""Command-line interface for the Alts RAG engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .approvals import record_approval
from .evaluate import evaluate_assessor, evaluate_offline
from .export import export_demo
from .models import model_configuration, model_contract_hash, model_is_configured
from .paths import runtime_dir
from .service import Engine
from .types import ClaimRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alts_rag")
    parser.add_argument("--runtime", default="", help="Override ALTS_RAG_RUNTIME")
    parser.add_argument("--project-root", default="", help="Override the project checkout")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    index = sub.add_parser("index")
    index.add_argument("--file-id", action="append", dest="file_ids")
    prepare = sub.add_parser("prepare-model")
    prepare.add_argument("--source", default="")
    embed = sub.add_parser("embed")
    embed.add_argument("--file-id", action="append", dest="file_ids")
    embed.add_argument("--all-documents", action="store_true")
    embed.add_argument("--block-kind", action="append", dest="block_kinds")
    search = sub.add_parser("search")
    search.add_argument("--session", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--file-id", action="append", dest="file_ids")
    search.add_argument("--limit", type=int, default=None)
    search_mode = search.add_mutually_exclusive_group()
    search_mode.add_argument("--keyword-only", action="store_true")
    search_mode.add_argument("--hybrid", action="store_true")
    review = sub.add_parser("context-review")
    review.add_argument("--session", required=True)
    review.add_argument("--file", required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--offline", action="store_true")
    evaluate.add_argument("--assessor", action="store_true")
    evaluate.add_argument("--session", default="")
    serve = sub.add_parser("serve")
    serve.add_argument("--confirm-loopback", action="store_true")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--reviewed-corpus", action="store_true")
    sub.add_parser("mcp")
    sub.add_parser("export-demo")
    session = sub.add_parser("issue-session")
    session.add_argument("--role", required=True)
    session.add_argument("--purpose", required=True)
    session.add_argument("--document-id", action="append", dest="document_ids")
    session.add_argument("--data-group", action="append", dest="data_groups")
    session.add_argument("--worklist", default="")
    session.add_argument("--reviewed-corpus", action="store_true")
    approval = sub.add_parser("record-approval")
    approval.add_argument("--approval-id", required=True)
    approval.add_argument("--authorization-reference", required=True)
    approval.add_argument("--operation", default="verify_claim")
    approval.add_argument("--provider", required=True)
    approval.add_argument("--model-id", required=True)
    approval.add_argument("--reasoning", required=True)
    approval.add_argument("--document-id", action="append", required=True, dest="document_ids")
    approval.add_argument("--field", action="append", required=True, dest="fields")
    approval.add_argument("--request-limit", type=int, required=True)
    approval.add_argument("--spending-cap", required=True)
    approval.add_argument("--max-input-tokens", type=int, required=True)
    approval.add_argument("--max-output-tokens", type=int, required=True)
    approval.add_argument("--input-usd-per-m", required=True)
    approval.add_argument("--output-usd-per-m", required=True)
    approval.add_argument("--expires-at", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = Path(args.runtime) if args.runtime else runtime_dir()
    project = Path(args.project_root) if args.project_root else None
    engine = Engine(project_root=project, runtime=runtime)
    try:
        if args.command == "status":
            print(json.dumps(engine.status(), indent=2))
            return 0
        if args.command == "index":
            file_ids = tuple(args.file_ids) if args.file_ids else None
            print(json.dumps(engine.index(file_ids), indent=2, default=str))
            return 0
        if args.command == "prepare-model":
            source = Path(args.source) if args.source else None
            print(json.dumps(engine.prepare_model(source), indent=2, default=str))
            return 0
        if args.command == "embed":
            if args.all_documents and args.file_ids:
                raise ValueError("--all-documents and --file-id cannot be combined")
            file_ids = tuple(args.file_ids) if args.file_ids else None
            kinds = tuple(args.block_kinds) if args.block_kinds else None
            print(
                json.dumps(
                    engine.build_vectors(
                        file_ids=file_ids,
                        all_documents=bool(args.all_documents),
                        block_kinds=kinds,
                    ),
                    indent=2,
                    default=str,
                )
            )
            return 0
        if args.command == "issue-session":
            worklist = Path(args.worklist) if args.worklist else None
            if args.reviewed_corpus and args.document_ids:
                raise ValueError("--reviewed-corpus and --document-id cannot be combined")
            documents = tuple(args.document_ids) if args.document_ids else None
            if args.reviewed_corpus:
                if args.role != "reviewer":
                    raise ValueError("--reviewed-corpus is available to reviewer sessions only")
                documents = engine.reviewed_document_ids()
            groups = tuple(args.data_groups) if args.data_groups else ("extracted",)
            scope = engine.issue_session(
                args.role,
                purpose=args.purpose,
                document_ids=documents,
                worklist=worklist,
                data_groups=groups,
            )
            print(json.dumps({
                "session_id": scope.session_id,
                "role": scope.role,
                "permitted_document_ids": list(scope.permitted_document_ids),
                "purpose": scope.purpose,
            }, indent=2))
            return 0
        if args.command == "record-approval":
            config = model_configuration()
            if not model_is_configured(config):
                raise ValueError("the provider contract must be verified in retrieval.json first")
            if (
                args.provider != config["provider"]
                or args.model_id != config["model_id"]
                or args.reasoning != config["reasoning_setting"]
            ):
                raise ValueError("approval settings do not match the verified provider contract")
            approval = record_approval(
                engine.access,
                approval_id=args.approval_id,
                authorization_reference=args.authorization_reference,
                operation=args.operation,
                provider=args.provider,
                model_id=args.model_id,
                reasoning_setting=args.reasoning,
                provider_contract_hash=model_contract_hash(config),
                documents=tuple(args.document_ids),
                fields=tuple(args.fields),
                request_limit=args.request_limit,
                spending_cap=args.spending_cap,
                max_input_tokens=args.max_input_tokens,
                max_output_tokens=args.max_output_tokens,
                input_usd_per_m=args.input_usd_per_m,
                output_usd_per_m=args.output_usd_per_m,
                expires_at=args.expires_at,
            )
            print(json.dumps({"approval_id": approval.approval_id, "recorded": True}, indent=2))
            return 0
        if args.command == "search":
            methods = None
            if args.keyword_only:
                methods = ("keyword",)
            elif args.hybrid:
                methods = ("keyword", "vector")
            result = engine.search_sources(
                args.session,
                args.query,
                file_ids=tuple(args.file_ids) if args.file_ids else None,
                result_limit=args.limit,
                retrieval_methods=methods,
            )
            print(json.dumps(result.as_dict(), indent=2))
            return 0
        if args.command == "context-review":
            claim = ClaimRequest(None, "", {}, {}, (args.file,), context_review=True)
            result = engine.verify_claim(args.session, claim)
            print(json.dumps(result.as_dict(), indent=2))
            return 0
        if args.command == "evaluate":
            if not args.offline and not args.assessor:
                print("evaluate requires --offline or --assessor", file=sys.stderr)
                return 2
            session = args.session
            if not session:
                docs = tuple(
                    row["file_id"]
                    for row in engine.store.documents()
                    if row["index_state"] in {"indexed", "restricted"}
                )
                session = engine.issue_session(
                    "reviewer",
                    purpose="evaluation",
                    document_ids=docs,
                ).session_id
            path = None
            if args.offline:
                path = evaluate_offline(engine, session)
            if args.assessor:
                path = evaluate_assessor(engine, session)
            print(str(path))
            return 0
        if args.command == "export-demo":
            print(str(export_demo(engine.project_root, engine=engine)))
            return 0
        if args.command == "serve":
            from .serve import bind_loopback

            scope = None
            if args.reviewed_corpus:
                scope = engine.issue_session(
                    "reviewer",
                    purpose="local dashboard",
                    document_ids=engine.reviewed_document_ids(),
                )
            server = bind_loopback(
                engine,
                confirm=args.confirm_loopback,
                port=args.port,
                local_scope_id=scope.session_id if scope else "",
            )
            payload = {
                "url": f"http://127.0.0.1:{args.port}/rag.html#console",
                "dashboard_url": (
                    f"http://127.0.0.1:{args.port}/dashboard.html#gp-scoring"
                ),
                "gp_scoring_url": (
                    f"http://127.0.0.1:{args.port}/GP-Scoring/06-report/dashboard.html"
                    "#view=research"
                ),
            }
            if scope:
                payload["document_count"] = len(scope.permitted_document_ids)
            print(json.dumps(payload, indent=2), flush=True)
            server.serve_forever()
            return 0
        if args.command == "mcp":
            from .mcp import serve_stdio

            serve_stdio(engine)
            return 0
        return 2
    finally:
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
