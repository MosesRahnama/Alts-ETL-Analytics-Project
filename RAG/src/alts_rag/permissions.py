"""Session issuance and permission checks."""

from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .policy import access_policy
from .store import AccessStore
from .types import QueryScope, Role

ROLES: frozenset[str] = frozenset({"extractor_a", "extractor_b", "reviewer", "public_demo"})
EXTRACTOR_ROLES = frozenset({"extractor_a", "extractor_b"})


class AccessDenied(RuntimeError):
    def __init__(self, message: str = "ACCESS_DENIED") -> None:
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split(value: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def worklist_ids(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        return ()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    key = "file_id" if rows and "file_id" in rows[0] else None
    if key is None:
        return ()
    return tuple(row[key] for row in rows if row.get(key))


def issue_session(
    store: AccessStore,
    role: Role,
    *,
    document_ids: tuple[str, ...] | None = None,
    worklist: Path | None = None,
    data_groups: tuple[str, ...] = ("extracted",),
    purpose: str,
    public_ids: tuple[str, ...] = (),
) -> QueryScope:
    if role not in ROLES:
        raise AccessDenied("unknown role")
    if role in EXTRACTOR_ROLES:
        assigned = worklist_ids(worklist) if worklist else ()
        if document_ids:
            extra = set(document_ids) - set(assigned)
            if extra:
                raise AccessDenied("extractor sessions cannot expand the worklist")
        permitted = assigned
        groups: tuple[str, ...] = ()
    elif role == "public_demo":
        permitted = public_ids
        groups = ()
    else:
        if document_ids is None:
            raise AccessDenied("reviewer sessions require an operator document set")
        permitted = document_ids
        allowed_groups = set(access_policy().get("data_groups") or [])
        if not data_groups or any(group not in allowed_groups for group in data_groups):
            raise AccessDenied("unknown data group")
        groups = data_groups
    session_id = uuid.uuid4().hex
    store.conn.execute(
        """
        INSERT INTO sessions(session_id, role, purpose, document_ids, data_groups, issued_at)
        VALUES(?,?,?,?,?,?)
        """,
        (session_id, role, purpose, ",".join(permitted), ",".join(groups), _now()),
    )
    store.conn.commit()
    return QueryScope(session_id, role, permitted, groups, purpose)


def load_session(store: AccessStore, session_id: str) -> QueryScope:
    row = store.conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if row is None:
        raise AccessDenied("unknown session")
    return QueryScope(
        session_id=row["session_id"],
        role=row["role"],
        permitted_document_ids=_split(row["document_ids"]),
        permitted_data_groups=_split(row["data_groups"]),
        purpose=row["purpose"],
    )


def permitted_file(scope: QueryScope, file_id: str) -> bool:
    return file_id in scope.permitted_document_ids


def filter_ids(scope: QueryScope, file_ids: list[str]) -> list[str]:
    allowed = set(scope.permitted_document_ids)
    return [file_id for file_id in file_ids if file_id in allowed]


def reject_expansion(scope: QueryScope, requested: dict) -> None:
    for key in ("role", "document_ids", "file_path", "worklist"):
        if key in requested:
            raise AccessDenied("requests cannot expand access")


def dump_scope(scope: QueryScope) -> str:
    return json.dumps(
        {
            "session_id": scope.session_id,
            "role": scope.role,
            "permitted_document_ids": list(scope.permitted_document_ids),
            "permitted_data_groups": list(scope.permitted_data_groups),
            "purpose": scope.purpose,
        }
    )
