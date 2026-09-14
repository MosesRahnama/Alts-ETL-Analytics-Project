"""Typed request and result records for the RAG engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["extractor_a", "extractor_b", "reviewer", "public_demo"]
AssessmentLabel = Literal["SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"]
ExecutionState = Literal[
    "OK",
    "TEST_DOUBLE",
    "MODEL_DISABLED",
    "MODEL_ERROR",
    "STALE_SOURCE",
    "ACCESS_DENIED",
    "QUERY_UNSUPPORTED",
    "ENGINE_ABSENT",
    "DATABASE_UNAVAILABLE",
    "EMPTY_RESULTS",
]


@dataclass(frozen=True)
class QueryScope:
    session_id: str
    role: Role
    permitted_document_ids: tuple[str, ...]
    permitted_data_groups: tuple[str, ...]
    purpose: str


@dataclass(frozen=True)
class Location:
    physical_page: int
    printed_page: str | None
    text_start: int | None
    text_end: int | None
    bbox: tuple[float, float, float, float] | None
    page_width: float | None
    page_height: float | None
    coordinate_convention: str | None
    layout_uncertain: bool = False


@dataclass(frozen=True)
class EvidenceBlock:
    block_id: str
    file_id: str
    source_version: str
    physical_page: int
    printed_page: str | None
    block_kind: str
    original_text: str
    source_representation: str
    location: Location
    parent_id: str | None
    relation_ids: tuple[str, ...]
    layout_uncertainty: bool
    filename: str = ""
    doc_type: str = ""
    truncated: bool = False
    continuation_ids: tuple[str, ...] = ()


@dataclass
class ClaimRequest:
    observation_id: str | None
    subject: str
    field_values: dict[str, str]
    date_meanings: dict[str, str]
    file_ids: tuple[str, ...]
    context_review: bool = False


@dataclass
class FieldAssessment:
    field: str
    claimed_value: str
    assessment: AssessmentLabel | None
    reason: str
    supporting_ids: tuple[str, ...]
    conflicting_ids: tuple[str, ...]
    method: str
    review_state: str


@dataclass
class QueryResult:
    request_id: str
    operation: str
    execution_state: ExecutionState
    source_version: str
    index_version: str
    scope: QueryScope
    coverage: dict[str, Any]
    results: list[Any]
    warnings: list[str]
    usage: dict[str, Any] = field(default_factory=dict)
    methods_used: tuple[str, ...] = ()
    assessments: list[FieldAssessment] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "operation": self.operation,
            "execution_state": self.execution_state,
            "source_version": self.source_version,
            "index_version": self.index_version,
            "scope": {
                "session_id": self.scope.session_id,
                "role": self.scope.role,
                "permitted_document_ids": list(self.scope.permitted_document_ids),
                "permitted_data_groups": list(self.scope.permitted_data_groups),
                "purpose": self.scope.purpose,
            },
            "coverage": self.coverage,
            "results": self.results,
            "warnings": self.warnings,
            "usage": self.usage,
            "methods_used": list(self.methods_used),
            "assessments": [
                {
                    "field": item.field,
                    "claimed_value": item.claimed_value,
                    "assessment": item.assessment,
                    "reason": item.reason,
                    "supporting_ids": list(item.supporting_ids),
                    "conflicting_ids": list(item.conflicting_ids),
                    "method": item.method,
                    "review_state": item.review_state,
                }
                for item in self.assessments
            ],
        }
