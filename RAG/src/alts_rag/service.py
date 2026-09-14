"""Shared RAG service used by the CLI, MCP adapter, and dashboard handlers."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from .analytics import AnalyticsUnavailable, explain
from .approvals import ApprovalMissing, require_approval
from .assessment import assess_fields
from .catalog import load_catalogue, resolve_document_path
from .context import assemble, load_permitted_block, block_dict
from .embed import (
    Embedder,
    build_vectors,
    default_vector_file_ids,
    embedding_settings,
    model_directory,
    prepare_local_model,
    validate_model_directory,
)
from .gp_scoring import load_real_gp_context, resolve_real_gp_scope
from .indexer import build_index, refresh_staleness
from .models import (
    OpenRouterAdapter,
    disabled_model_result,
    model_configuration,
    model_contract_hash,
    model_is_configured,
    model_method,
)
from .network import OutboundRefused
from .paths import PROJECT_ROOT, access_path, index_path, runtime_dir
from .permissions import AccessDenied, issue_session, load_session, reject_expansion
from .policy import retrieval_policy
from .retrieval import retrieve, sanitize_query
from .review import context_suggestions
from .store import AccessStore, Store
from .types import ClaimRequest, FieldAssessment, QueryResult, QueryScope

DOCUMENT_FIELDS = (
    "file_id",
    "filename",
    "doc_type",
    "source_version",
    "page_count",
    "txt_path",
    "pdf_path",
    "grid_path",
    "image_dir",
    "text_state",
    "index_state",
    "routing_status",
    "disagreement",
    "product_tier",
    "layout_features",
)


class Engine:
    def __init__(
        self,
        project_root: Path | None = None,
        runtime: Path | None = None,
        *,
        embedder: Embedder | None = None,
    ) -> None:
        self.project_root = Path(project_root) if project_root else PROJECT_ROOT
        self.runtime = runtime_dir(runtime)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.store = Store(index_path(self.runtime))
        self.access = AccessStore(access_path(self.runtime))
        self.cache_dir = self.runtime / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._source_signatures: dict[str, tuple[tuple[str, int, int], ...]] = {}
        self._coverage_cache: dict[str, int] | None = None
        self.embedder = embedder

    def close(self) -> None:
        self.store.close()
        self.access.close()

    def status(self) -> dict[str, Any]:
        settings = retrieval_policy()
        embedding = embedding_settings()
        prepared_path = model_directory(self.runtime, embedding)
        try:
            model_prepared = bool(validate_model_directory(prepared_path))
        except Exception:
            model_prepared = False
        catalogue, warnings = load_catalogue(self.project_root)
        coverage = self._coverage()
        index_version = self.store.meta("index_version")
        if not index_version:
            warnings.append("INDEX_NOT_BUILT")
        return {
            "execution_state": "OK" if index_version else "EMPTY_RESULTS",
            "project_root": str(self.project_root),
            "runtime": str(self.runtime),
            "index_path": str(self.store.path),
            "index_version": index_version,
            "keyword_enabled": bool(settings.get("keyword_enabled", True)),
            "vector_enabled": (
                bool(settings.get("vector_enabled"))
                and self.store.meta("vector_enabled") == "1"
                and coverage.get("vector_blocks", 0) > 0
            ),
            "hybrid_default": bool(settings.get("hybrid_default")),
            "embedding": {
                "model": embedding["name"],
                "revision": embedding["revision"],
                "dimension": embedding["dimension"],
                "model_prepared": model_prepared,
                "model_path": str(prepared_path),
                "active_model_key": self.store.meta("embedding_model_key"),
                "vector_version": self.store.meta("vector_version"),
                **self.store.vector_coverage(self.store.meta("embedding_model_key") or None),
            },
            "coverage": coverage,
            "catalogue_count": len(catalogue),
            "warnings": warnings[:20],
            "model": disabled_model_result("status"),
        }

    def prepare_model(self, source: Path | None = None) -> dict[str, Any]:
        return prepare_local_model(self.runtime, source)

    def reviewed_document_ids(self) -> tuple[str, ...]:
        return default_vector_file_ids(self.store, self.project_root)

    def build_vectors(
        self,
        *,
        file_ids: tuple[str, ...] | None = None,
        all_documents: bool = False,
        block_kinds: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        result = build_vectors(
            self.store,
            self.project_root,
            self.runtime,
            file_ids=file_ids,
            all_documents=all_documents,
            block_kinds=block_kinds,
            embedder=self.embedder,
        )
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._coverage_cache = None
        return result

    def index(self, file_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
        staging = self.runtime / "index" / "staging"
        current = self.runtime / "index" / "current"
        previous = self.runtime / "index" / "previous"
        self.store.close()
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        current_database = current / "index.sqlite"
        if current_database.is_file():
            shutil.copy2(current_database, staging / "index.sqlite")
        staging_store = Store(staging / "index.sqlite")
        try:
            result = build_index(staging_store, self.project_root, file_ids=file_ids)
            staging_store.close()
        except Exception:
            staging_store.close()
            self.store = Store(index_path(self.runtime))
            raise
        moved_current = False
        try:
            if current.exists():
                if previous.exists():
                    shutil.rmtree(previous)
                current.rename(previous)
                moved_current = True
            staging.rename(current)
        except Exception:
            if moved_current and previous.exists() and not current.exists():
                previous.rename(current)
            self.store = Store(index_path(self.runtime))
            raise
        self.store = Store(index_path(self.runtime))
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._source_signatures.clear()
        self._coverage_cache = None
        result["execution_state"] = "OK"
        return result

    def _coverage(self) -> dict[str, int]:
        if self._coverage_cache is None:
            self._coverage_cache = self.store.coverage()
        return dict(self._coverage_cache)

    def _source_signature(self, document) -> tuple[tuple[str, int, int], ...]:
        signature: list[tuple[str, int, int]] = []
        for key in ("pdf_path", "txt_path", "grid_path"):
            path = resolve_document_path(document, key, self.project_root)
            try:
                stat = path.stat() if path is not None and path.is_file() else None
            except OSError:
                stat = None
            signature.append((key, stat.st_size if stat else -1, stat.st_mtime_ns if stat else -1))
        return tuple(signature)

    def _refresh_staleness(self, file_ids: tuple[str, ...]) -> None:
        changed: list[str] = []
        for file_id in dict.fromkeys(file_ids):
            document = self.store.document(file_id)
            if document is None:
                continue
            signature = self._source_signature(document)
            if self._source_signatures.get(file_id) != signature:
                changed.append(file_id)
                self._source_signatures[file_id] = signature
        if changed:
            if refresh_staleness(
                self.store,
                tuple(changed),
                project_root=self.project_root,
            ):
                self._coverage_cache = None

    def issue_session(
        self,
        role: str,
        *,
        purpose: str,
        document_ids: tuple[str, ...] | None = None,
        worklist: Path | None = None,
        data_groups: tuple[str, ...] = ("extracted",),
    ) -> QueryScope:
        public_ids = tuple(self._demo_ids())
        return issue_session(
            self.access,
            role,  # type: ignore[arg-type]
            document_ids=document_ids,
            worklist=worklist,
            data_groups=data_groups,
            purpose=purpose,
            public_ids=public_ids,
        )

    def gp_manager_context(self, session_id: str) -> dict[str, Any]:
        """Return real managers and funds backed by the session's reviewed documents."""

        try:
            scope = load_session(self.access, session_id)
        except AccessDenied:
            return {"execution_state": "ACCESS_DENIED", "warnings": ["ACCESS_DENIED"]}
        if scope.role != "reviewer":
            return {"execution_state": "ACCESS_DENIED", "warnings": ["ACCESS_DENIED"]}
        result = load_real_gp_context(self.project_root, scope.permitted_document_ids)
        result["index_version"] = self.store.meta("index_version")
        return result

    def gp_manager_search(
        self,
        session_id: str,
        query: str,
        *,
        manager_key: str = "",
        fund_id: str = "",
        result_limit: int | None = None,
        retrieval_methods: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Search only documents linked to one selected real manager or real fund."""

        try:
            scope = load_session(self.access, session_id)
        except AccessDenied:
            return {"execution_state": "ACCESS_DENIED", "warnings": ["ACCESS_DENIED"]}
        if scope.role != "reviewer":
            return {"execution_state": "ACCESS_DENIED", "warnings": ["ACCESS_DENIED"]}
        if not query.strip():
            return {"execution_state": "QUERY_UNSUPPORTED", "error": "a source question is required"}
        context = load_real_gp_context(self.project_root, scope.permitted_document_ids)
        selected = resolve_real_gp_scope(context, manager_key=manager_key, fund_id=fund_id)
        if selected is None or not selected["file_ids"]:
            return {"execution_state": "ACCESS_DENIED", "warnings": ["ACCESS_DENIED"]}
        result = self.search_sources(
            session_id,
            query,
            file_ids=selected["file_ids"],
            result_limit=result_limit,
            retrieval_methods=retrieval_methods,
        ).as_dict()
        result["gp_scope"] = {key: value for key, value in selected.items() if key != "file_ids"}
        result["gp_scope"]["file_ids"] = list(selected["file_ids"])
        return result

    def _demo_ids(self) -> list[str]:
        path = self.project_root / "RAG" / "evaluation" / "public-demo.json"
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("permitted_document_ids") or [])

    def _result(
        self,
        operation: str,
        state: str,
        scope: QueryScope,
        results: list[Any] | None = None,
        warnings: list[str] | None = None,
        assessments: list | None = None,
        methods: tuple[str, ...] = (),
    ) -> QueryResult:
        return QueryResult(
            request_id=uuid.uuid4().hex,
            operation=operation,
            execution_state=state,  # type: ignore[arg-type]
            source_version=self.store.meta("index_version"),
            index_version=self.store.meta("index_version"),
            scope=scope,
            coverage=self._coverage(),
            results=results or [],
            warnings=warnings or [],
            methods_used=methods,
            assessments=assessments or [],
        )

    def _cache_key(self, operation: str, payload: dict[str, Any]) -> Path:
        blob = json.dumps({"op": operation, "payload": payload}, sort_keys=True)
        digest = hashlib.sha256(blob.encode()).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _denied(self, operation: str, session_id: str) -> QueryResult:
        empty = QueryScope(session_id, "public_demo", (), (), "denied")
        return self._result(operation, "ACCESS_DENIED", empty, warnings=["ACCESS_DENIED"])

    def search_sources(
        self,
        session_id: str,
        query: str,
        *,
        file_ids: tuple[str, ...] | None = None,
        result_limit: int | None = None,
        extra: dict[str, Any] | None = None,
        retrieval_methods: tuple[str, ...] | None = None,
    ) -> QueryResult:
        try:
            scope = load_session(self.access, session_id)
            if extra:
                reject_expansion(scope, extra)
        except AccessDenied:
            return self._denied("search_sources", session_id)
        if scope.role == "public_demo":
            return self._search_demo(scope, query)
        requested = file_ids or ()
        if requested:
            extra_ids = set(requested) - set(scope.permitted_document_ids)
            if extra_ids:
                return self._result("search_sources", "ACCESS_DENIED", scope, warnings=["ACCESS_DENIED"])
            narrowed = QueryScope(scope.session_id, scope.role, requested, scope.permitted_data_groups, scope.purpose)
        else:
            narrowed = scope
        self._refresh_staleness(narrowed.permitted_document_ids)
        stale_ids = {
            file_id
            for file_id in narrowed.permitted_document_ids
            if (self.store.document(file_id) is not None)
            and self.store.document(file_id)["index_state"] == "stale"
        }
        if requested and stale_ids:
            return self._result("search_sources", "STALE_SOURCE", narrowed, warnings=["STALE_SOURCE"])
        warnings: list[str] = []
        if stale_ids:
            warnings.append("STALE_SOURCE_WITHHELD")
            narrowed = QueryScope(
                narrowed.session_id,
                narrowed.role,
                tuple(item for item in narrowed.permitted_document_ids if item not in stale_ids),
                narrowed.permitted_data_groups,
                narrowed.purpose,
            )
        if not narrowed.permitted_document_ids:
            state = "STALE_SOURCE" if stale_ids else "EMPTY_RESULTS"
            return self._result("search_sources", state, narrowed, warnings=warnings)
        cache = self._cache_key(
            "search_sources",
            {
                "query": query,
                "docs": list(narrowed.permitted_document_ids),
                "index_version": self.store.meta("index_version"),
                "result_limit": result_limit,
                "retrieval_methods": list(retrieval_methods or ()),
                "vector_version": self.store.meta("vector_version"),
                "retrieval_policy": {
                    key: retrieval_policy().get(key)
                    for key in (
                        "candidate_limit",
                        "result_limit",
                        "rrf_k",
                        "keyword_enabled",
                        "vector_enabled",
                        "hybrid_default",
                        "keyword_weight",
                        "vector_weight",
                    )
                },
            },
        )
        fused = None
        methods: tuple[str, ...] = ()
        if cache.is_file():
            try:
                payload = json.loads(cache.read_text(encoding="utf-8"))
                fused = [(item[0], float(item[1]), tuple(item[2])) for item in payload.get("fused") or []]
                methods = tuple(payload.get("methods") or ())
            except (json.JSONDecodeError, TypeError, ValueError, KeyError, IndexError):
                fused = None
        if fused is None:
            fused, methods = retrieve(
                self.store,
                sanitize_query(query) or query,
                narrowed,
                result_limit,
                runtime=self.runtime,
                embedder=self.embedder,
                active_methods=retrieval_methods,
            )
            cache.write_text(json.dumps({"fused": fused, "methods": methods}), encoding="utf-8")
        assembled = assemble(self.store, fused, narrowed)
        state = "OK" if assembled else "EMPTY_RESULTS"
        return self._result("search_sources", state, narrowed, assembled, warnings=warnings, methods=methods)

    def _search_demo(self, scope: QueryScope, query: str) -> QueryResult:
        path = self.project_root / "RAG" / "evaluation" / "public-demo.json"
        if not path.is_file():
            return self._result("search_sources", "ENGINE_ABSENT", scope, warnings=["public demo export is absent"])
        data = json.loads(path.read_text(encoding="utf-8"))
        tokens = set(sanitize_query(query).lower().split())
        hits = []
        for item in data.get("evidence") or []:
            if item.get("file_id") not in scope.permitted_document_ids:
                continue
            text = (item.get("original_text") or "").lower()
            if tokens and not tokens.issubset(set(text.replace("%", " % ").split())):
                if not any(token in text for token in tokens):
                    continue
            hits.append(item)
        state = "OK" if hits else "EMPTY_RESULTS"
        return self._result("search_sources", state, scope, hits[:10], methods=("static_export",))

    def get_evidence(self, session_id: str, evidence_ids: list[str], extra: dict[str, Any] | None = None) -> QueryResult:
        try:
            scope = load_session(self.access, session_id)
            if extra:
                reject_expansion(scope, extra)
        except AccessDenied:
            return self._denied("get_evidence", session_id)
        if len(evidence_ids) > 100:
            return self._result("get_evidence", "QUERY_UNSUPPORTED", scope, warnings=["evidence limit is 100"])
        blocks = []
        for block_id in evidence_ids:
            block = load_permitted_block(self.store, block_id, scope)
            if block is None:
                return self._result("get_evidence", "ACCESS_DENIED", scope, warnings=["ACCESS_DENIED"])
            blocks.append(block)
        self._refresh_staleness(tuple(dict.fromkeys(block.file_id for block in blocks)))
        output = []
        for block in blocks:
            document = self.store.document(block.file_id)
            if document and document["index_state"] == "stale":
                return self._result("get_evidence", "STALE_SOURCE", scope, warnings=["STALE_SOURCE"])
            output.append(block_dict(block))
        state = "OK" if output else "EMPTY_RESULTS"
        return self._result("get_evidence", state, scope, output)

    def verify_claim(
        self,
        session_id: str,
        claim: ClaimRequest,
        extra: dict[str, Any] | None = None,
        *,
        retrieval_methods: tuple[str, ...] | None = None,
    ) -> QueryResult:
        try:
            scope = load_session(self.access, session_id)
            if extra:
                reject_expansion(scope, extra)
        except AccessDenied:
            return self._denied("verify_claim", session_id)
        if scope.role != "reviewer":
            return self._result("verify_claim", "ACCESS_DENIED", scope, warnings=["extractor and public roles cannot run assessments"])
        if not claim.file_ids or any(file_id not in scope.permitted_document_ids for file_id in claim.file_ids):
            return self._result("verify_claim", "ACCESS_DENIED", scope, warnings=["ACCESS_DENIED"])
        if claim.context_review:
            if len(claim.file_ids) != 1:
                return self._result("verify_claim", "QUERY_UNSUPPORTED", scope, warnings=["context review requires exactly one file_id"])
            file_id = claim.file_ids[0]
            self._refresh_staleness((file_id,))
            document = self.store.document(file_id)
            if document and document["index_state"] == "stale":
                return self._result("verify_claim", "STALE_SOURCE", scope, warnings=["STALE_SOURCE"])
            request_id = uuid.uuid4().hex
            rows = context_suggestions(self.store, scope, file_id, request_id, self.project_root, self.runtime)
            result = self._result("verify_claim", "OK", scope, rows)
            result.request_id = request_id
            return result
        query_parts = [claim.subject, *claim.field_values.values()]
        search = self.search_sources(
            session_id,
            " ".join(part for part in query_parts if part),
            file_ids=claim.file_ids or None,
            retrieval_methods=retrieval_methods,
        )
        if search.execution_state != "OK":
            return self._result(
                "verify_claim",
                search.execution_state,
                scope,
                search.results,
                warnings=search.warnings,
                methods=search.methods_used,
            )
        assessments = assess_fields(claim.field_values, search.results)
        result = self._result("verify_claim", "OK", scope, search.results, assessments=assessments, methods=search.methods_used)
        result.usage = {"model": disabled_model_result("verify_claim")}
        return result

    def model_assess(self, session_id: str, claim: ClaimRequest) -> QueryResult:
        try:
            scope = load_session(self.access, session_id)
        except AccessDenied:
            return self._denied("verify_claim", session_id)
        if scope.role != "reviewer":
            return self._result(
                "verify_claim",
                "ACCESS_DENIED",
                scope,
                warnings=["extractor and public roles cannot run assessments"],
            )
        if (
            not claim.file_ids
            or not claim.field_values
            or any(file_id not in scope.permitted_document_ids for file_id in claim.file_ids)
        ):
            return self._result("verify_claim", "ACCESS_DENIED", scope, warnings=["ACCESS_DENIED"])

        def disabled() -> QueryResult:
            result = self._result("verify_claim", "MODEL_DISABLED", scope, warnings=["MODEL_DISABLED"])
            result.assessments = [
                FieldAssessment(
                    field=field,
                    claimed_value=value,
                    assessment=None,
                    reason="Field awaits an approved model request.",
                    supporting_ids=(),
                    conflicting_ids=(),
                    method="unrun",
                    review_state="pending_model",
                )
                for field, value in claim.field_values.items()
            ]
            return result

        config = model_configuration()
        if not model_is_configured(config):
            return disabled()
        try:
            require_approval(
                self.access,
                "verify_claim",
                claim.file_ids,
                provider=config["provider"],
                model_id=config["model_id"],
                reasoning_setting=config["reasoning_setting"],
                provider_contract_hash=model_contract_hash(config),
                fields=tuple(claim.field_values),
            )
        except ApprovalMissing:
            return disabled()
        query_parts = [claim.subject, *claim.field_values.values()]
        search = self.search_sources(
            session_id,
            " ".join(part for part in query_parts if part),
            file_ids=claim.file_ids or None,
        )
        if search.execution_state != "OK" or not search.results:
            return self._result(
                "verify_claim",
                search.execution_state,
                scope,
                search.results,
                warnings=search.warnings,
                methods=search.methods_used,
            )
        request_id = uuid.uuid4().hex
        adapter = OpenRouterAdapter(self.access)
        try:
            assessments, usage = adapter.assess(
                claim.file_ids,
                claim.subject,
                claim.field_values,
                search.results,
                request_id,
            )
        except ApprovalMissing:
            return disabled()
        except OutboundRefused:
            result = self._result(
                "verify_claim",
                "MODEL_ERROR",
                scope,
                search.results,
                warnings=["MODEL_ERROR"],
                methods=search.methods_used,
            )
            result.request_id = request_id
            return result
        except Exception:
            result = self._result(
                "verify_claim",
                "MODEL_ERROR",
                scope,
                search.results,
                warnings=["MODEL_ERROR"],
                methods=search.methods_used,
            )
            result.request_id = request_id
            result.usage = {"execution_state": "MODEL_ERROR", "model": model_method()}
            return result
        result = self._result(
            "verify_claim",
            "OK",
            scope,
            search.results,
            assessments=assessments,
            methods=search.methods_used + (model_method(),),
        )
        result.request_id = request_id
        result.usage = usage
        return result

    def explain_analytics(self, session_id: str, query_id: str, parameters: dict[str, str], data_group: str = "extracted") -> QueryResult:
        try:
            scope = load_session(self.access, session_id)
        except AccessDenied:
            return self._result("explain_analytics", "ACCESS_DENIED", QueryScope(session_id, "public_demo", (), (), "denied"), warnings=["ACCESS_DENIED"])
        if scope.role != "reviewer":
            return self._result("explain_analytics", "ACCESS_DENIED", scope, warnings=["ACCESS_DENIED"])
        try:
            payload = explain(self.project_root, scope, query_id, parameters, data_group)
        except AnalyticsUnavailable as exc:
            return self._result("explain_analytics", "DATABASE_UNAVAILABLE", scope, warnings=[str(exc)])
        except PermissionError:
            return self._result("explain_analytics", "ACCESS_DENIED", scope, warnings=["ACCESS_DENIED"])
        state = payload.get("execution_state") or "OK"
        return self._result("explain_analytics", state, scope, [payload])

    def observations(self, file_id: str) -> list[dict[str, str]]:
        path = self.project_root / "data/extracted/tables/fact_observation.csv"
        if not path.is_file():
            return []
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return [row for row in csv.DictReader(handle) if row.get("document_id") == file_id]
