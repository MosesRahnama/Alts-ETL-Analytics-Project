"""JSON-RPC stdio adapter. Transport only; financial rules stay in the service."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .service import Engine
from .types import ClaimRequest

TOOLS = [
    {
        "name": "search_sources",
        "description": "Rank permitted source passages for a query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "query": {"type": "string"},
                "file_ids": {"type": "array", "items": {"type": "string"}},
                "retrieval_methods": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["keyword", "vector"]},
                    "uniqueItems": True,
                },
            },
            "required": ["session_id", "query"],
        },
    },
    {
        "name": "get_evidence",
        "description": "Return original quotations for permitted evidence IDs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["session_id", "evidence_ids"],
        },
    },
    {
        "name": "verify_claim",
        "description": "Assess recorded fields against retrieved source passages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "subject": {"type": "string"},
                "field_values": {"type": "object"},
                "file_ids": {"type": "array", "items": {"type": "string"}},
                "context_review": {"type": "boolean"},
                "retrieval_methods": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["keyword", "vector"]},
                    "uniqueItems": True,
                },
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "explain_analytics",
        "description": "Explain a stored analytical result from published tables.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "query_id": {"type": "string"},
                "parameters": {"type": "object"},
                "data_group": {"type": "string"},
            },
            "required": ["session_id", "query_id"],
        },
    },
]


def dispatch(engine: Engine, message: dict[str, Any]) -> dict[str, Any]:
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "alts_rag", "version": "0.1.0"}}}
    if method == "notifications/initialized":
        return {}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            payload = _call(engine, name, arguments)
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}
        text = json.dumps(payload)
        return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}]}}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method unsupported"}}


def _call(engine: Engine, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    session = arguments.get("session_id") or ""
    extra = {key: arguments[key] for key in ("role", "file_path", "worklist") if key in arguments}
    methods = tuple(arguments.get("retrieval_methods") or ())
    if any(method not in {"keyword", "vector"} for method in methods):
        raise ValueError("retrieval_methods must contain keyword or vector")
    if name == "search_sources":
        file_ids = tuple(arguments["file_ids"]) if arguments.get("file_ids") else None
        return engine.search_sources(
            session,
            arguments.get("query", ""),
            file_ids=file_ids,
            extra=extra,
            retrieval_methods=methods or None,
        ).as_dict()
    if name == "get_evidence":
        return engine.get_evidence(session, list(arguments.get("evidence_ids") or []), extra=extra).as_dict()
    if name == "verify_claim":
        claim = ClaimRequest(
            observation_id=arguments.get("observation_id"),
            subject=arguments.get("subject", ""),
            field_values=arguments.get("field_values") or {},
            date_meanings=arguments.get("date_meanings") or {},
            file_ids=tuple(arguments.get("file_ids") or ()),
            context_review=bool(arguments.get("context_review")),
        )
        return engine.verify_claim(
            session,
            claim,
            extra=extra,
            retrieval_methods=methods or None,
        ).as_dict()
    if name == "explain_analytics":
        return engine.explain_analytics(
            session,
            arguments.get("query_id", ""),
            arguments.get("parameters") or {},
            arguments.get("data_group", "extracted"),
        ).as_dict()
    raise ValueError(name)


def serve_stdio(engine: Engine, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
    incoming = stdin or sys.stdin
    outgoing = stdout or sys.stdout
    for line in incoming:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            outgoing.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "invalid JSON"},
                    }
                )
                + "\n"
            )
            outgoing.flush()
            continue
        if not isinstance(message, dict):
            outgoing.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "invalid request"},
                    }
                )
                + "\n"
            )
            outgoing.flush()
            continue
        response = dispatch(engine, message)
        if message.get("id") is not None and response:
            outgoing.write(json.dumps(response) + "\n")
            outgoing.flush()
