"""Loopback HTTP handlers. Tests call these in-process; sockets stay optional."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any
from urllib.parse import unquote, urlparse

from .catalog import resolve_document_path
from .service import Engine
from .types import ClaimRequest

MAX_BODY_BYTES = 1_000_000
STATIC_FILES = {
    "/RAG/evaluation/public-demo.json": (
        "RAG/evaluation/public-demo.json",
        "application/json; charset=utf-8",
    ),
    "/RAG/README.md": ("RAG/README.md", "text/markdown; charset=utf-8"),
    "/RAG/IMPLEMENTATION.md": ("RAG/IMPLEMENTATION.md", "text/markdown; charset=utf-8"),
    "/RAG/src/alts_rag/service.py": (
        "RAG/src/alts_rag/service.py",
        "text/plain; charset=utf-8",
    ),
}
GP_STATIC_ROOTS = frozenset({"04-diagnostics", "05-scenarios", "06-report", "data"})
GP_STATIC_TYPES = {
    ".csv": "text/csv; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


class RagHandler:
    def __init__(self, engine: Engine, *, local_scope_id: str = "") -> None:
        self.engine = engine
        self.local_scope_id = local_scope_id
        self._engine_lock = RLock()

    def handle(self, method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        headers = {key.lower(): value for key, value in (headers or {}).items()}
        parsed = urlparse(path)
        origin = headers.get("origin", "")
        if origin and origin != "null":
            parsed_origin = urlparse(origin)
            if parsed_origin.scheme != "http" or parsed_origin.hostname not in {"127.0.0.1", "localhost"}:
                return self._json(403, {"execution_state": "ACCESS_DENIED", "error": "origin refused"})
        if method == "OPTIONS":
            return self._plain(204, b"")
        if method == "GET" and parsed.path == "/favicon.ico":
            return self._plain(204, b"")
        if parsed.path.startswith("/page/"):
            return self._plain(403, b"filesystem paths are refused")
        if method == "GET" and parsed.path in {"/", "/rag.html", "/dashboard.html"}:
            page_name = "dashboard.html" if parsed.path == "/dashboard.html" else "rag.html"
            page = self.engine.project_root / page_name
            if not page.is_file():
                return self._plain(404, f"{page_name} not found".encode())
            return self._bytes(200, page.read_bytes(), "text/html; charset=utf-8")
        if method == "GET" and parsed.path in STATIC_FILES:
            relative_path, content_type = STATIC_FILES[parsed.path]
            source = self.engine.project_root / relative_path
            if not source.is_file():
                return self._plain(404, b"not found")
            return self._bytes(200, source.read_bytes(), content_type)
        if method == "GET" and parsed.path.startswith("/GP-Scoring/"):
            return self._gp_static(parsed.path)
        if method == "GET" and parsed.path == "/status":
            with self._engine_lock:
                status_payload = self.engine.status()
            return self._json(200, status_payload)
        if method == "POST" and parsed.path in {
            "/search_sources",
            "/get_evidence",
            "/verify_claim",
            "/explain_analytics",
            "/gp_manager_context",
            "/gp_search",
            "/document",
        }:
            try:
                declared_length = int(headers.get("content-length") or len(body))
            except ValueError:
                return self._json(400, {"execution_state": "QUERY_UNSUPPORTED", "error": "invalid content length"})
            if declared_length < 0:
                return self._json(400, {"execution_state": "QUERY_UNSUPPORTED", "error": "invalid content length"})
            if declared_length > MAX_BODY_BYTES or len(body) > MAX_BODY_BYTES:
                return self._json(413, {"execution_state": "QUERY_UNSUPPORTED", "error": "request too large"})
            content_type = headers.get("content-type", "")
            if not content_type.lower().startswith("application/json"):
                return self._json(415, {"execution_state": "QUERY_UNSUPPORTED", "error": "application/json required"})
            try:
                payload = json.loads(body.decode("utf-8") or "{}") if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._json(400, {"execution_state": "QUERY_UNSUPPORTED", "error": "invalid JSON"})
            if self.local_scope_id and not (payload.get("session_id") or payload.get("session")):
                payload = {**payload, "session_id": self.local_scope_id}
            try:
                with self._engine_lock:
                    if parsed.path == "/document":
                        return self._document(payload)
                    result = self._dispatch(parsed.path.lstrip("/"), payload)
            except Exception as exc:
                return self._json(400, {"execution_state": "QUERY_UNSUPPORTED", "error": str(exc)})
            return self._json(200, result.as_dict() if hasattr(result, "as_dict") else result)
        return self._plain(404, b"not found")

    def _dispatch(self, operation: str, payload: dict[str, Any]):
        session = payload.get("session_id") or payload.get("session") or ""
        extra = {key: payload[key] for key in ("role", "file_path", "worklist") if key in payload}
        methods = tuple(payload.get("retrieval_methods") or ())
        if any(method not in {"keyword", "vector"} for method in methods):
            raise ValueError("retrieval_methods must contain keyword or vector")
        if operation == "search_sources":
            file_ids = tuple(payload["file_ids"]) if payload.get("file_ids") else None
            return self.engine.search_sources(
                session,
                payload.get("query", ""),
                file_ids=file_ids,
                result_limit=payload.get("result_limit"),
                extra=extra,
                retrieval_methods=methods or None,
            )
        if operation == "gp_manager_context":
            return self.engine.gp_manager_context(str(session))
        if operation == "gp_search":
            return self.engine.gp_manager_search(
                str(session),
                str(payload.get("query") or ""),
                manager_key=str(payload.get("manager_key") or ""),
                fund_id=str(payload.get("fund_id") or ""),
                result_limit=payload.get("result_limit"),
                retrieval_methods=methods or None,
            )
        if operation == "get_evidence":
            return self.engine.get_evidence(session, list(payload.get("evidence_ids") or []), extra=extra)
        if operation == "verify_claim":
            claim = ClaimRequest(
                observation_id=payload.get("observation_id"),
                subject=payload.get("subject", ""),
                field_values=payload.get("field_values") or {},
                date_meanings=payload.get("date_meanings") or {},
                file_ids=tuple(payload.get("file_ids") or ()),
                context_review=bool(payload.get("context_review")),
            )
            return self.engine.verify_claim(
                session,
                claim,
                extra=extra,
                retrieval_methods=methods or None,
            )
        if operation == "explain_analytics":
            return self.engine.explain_analytics(
                session,
                payload.get("query_id", ""),
                payload.get("parameters") or {},
                payload.get("data_group", "extracted"),
            )
        raise ValueError(operation)

    def _gp_static(self, path: str) -> tuple[int, dict[str, str], bytes]:
        relative = PurePosixPath(unquote(path.removeprefix("/GP-Scoring/")))
        if not relative.parts or relative.parts[0] not in GP_STATIC_ROOTS or ".." in relative.parts:
            return self._plain(404, b"not found")
        content_type = GP_STATIC_TYPES.get(relative.suffix.lower())
        if content_type is None:
            return self._plain(404, b"not found")
        root = (self.engine.project_root / "GP-Scoring").resolve()
        try:
            source = (root / Path(*relative.parts)).resolve(strict=True)
            source.relative_to(root)
        except (OSError, ValueError):
            return self._plain(404, b"not found")
        if not source.is_file():
            return self._plain(404, b"not found")
        return self._bytes(200, source.read_bytes(), content_type)

    def _document(self, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        session = str(payload.get("session_id") or payload.get("session") or "")
        block_id = str(payload.get("block_id") or "")
        if not session or not block_id:
            return self._json(
                400,
                {"execution_state": "QUERY_UNSUPPORTED", "error": "session_id and block_id are required"},
            )
        result = self.engine.get_evidence(session, [block_id])
        if result.execution_state == "ACCESS_DENIED":
            return self._json(403, result.as_dict())
        if result.execution_state == "STALE_SOURCE":
            return self._json(409, result.as_dict())
        if result.execution_state != "OK" or not result.results:
            return self._json(404, result.as_dict())
        block = result.results[0]
        document = self.engine.store.document(str(block.get("file_id") or ""))
        resolved = (
            resolve_document_path(document, "pdf_path", self.engine.project_root)
            if document is not None
            else None
        )
        if resolved is None:
            return self._json(
                404,
                {"execution_state": "EMPTY_RESULTS", "error": "source PDF is unavailable"},
            )
        if not resolved.is_file() or resolved.suffix.lower() != ".pdf":
            return self._json(
                404,
                {"execution_state": "EMPTY_RESULTS", "error": "source PDF is unavailable"},
            )
        filename = "".join(character for character in resolved.name if character.isalnum() or character in "._-")
        status, headers, body = self._bytes(200, resolved.read_bytes(), "application/pdf")
        headers["Content-Disposition"] = f'inline; filename="{filename}"'
        headers["X-RAG-File-ID"] = str(block.get("file_id") or "")
        headers["X-RAG-Physical-Page"] = str(block.get("physical_page") or "")
        return status, headers, body

    def _json(self, status: int, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        body = json.dumps(payload).encode("utf-8")
        return self._bytes(status, body, "application/json; charset=utf-8")

    def _plain(self, status: int, body: bytes) -> tuple[int, dict[str, str], bytes]:
        return self._bytes(status, body, "text/plain; charset=utf-8")

    @staticmethod
    def _bytes(status: int, body: bytes, content_type: str) -> tuple[int, dict[str, str], bytes]:
        return status, {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "SAMEORIGIN",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "img-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; object-src 'none'; "
                "frame-ancestors 'self'; base-uri 'none'"
            ),
        }, body


def bind_loopback(
    engine: Engine,
    *,
    confirm: bool,
    host: str = "127.0.0.1",
    port: int = 8765,
    local_scope_id: str = "",
) -> ThreadingHTTPServer:
    if not confirm:
        raise PermissionError("serve requires --confirm-loopback")
    if host not in {"127.0.0.1", "localhost"}:
        raise PermissionError("the server binds loopback only")
    handler = RagHandler(engine, local_scope_id=local_scope_id)

    class Adapter(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._run("GET")

        def do_POST(self) -> None:  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            body = self.rfile.read(length) if 0 < length <= MAX_BODY_BYTES else b""
            self._run("POST", body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._run("OPTIONS")

        def _run(self, method: str, body: bytes = b"") -> None:
            status, headers, payload = handler.handle(method, self.path, body, dict(self.headers))
            origin = self.headers.get("Origin", "")
            parsed_origin = urlparse(origin) if origin and origin != "null" else None
            if origin == "null" or (
                parsed_origin is not None
                and parsed_origin.scheme == "http"
                and parsed_origin.hostname in {"127.0.0.1", "localhost"}
            ):
                headers["Access-Control-Allow-Origin"] = origin
                headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                headers["Access-Control-Allow-Headers"] = "Content-Type"
                headers["Access-Control-Allow-Private-Network"] = "true"
                headers["Vary"] = "Origin"
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return ThreadingHTTPServer((host, port), Adapter)
