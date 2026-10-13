"""
Role-based access control for Document Intelligence API.

Roles (least → most privilege):
  viewer   — read health, RAG query, list docs
  analyst  — viewer + upload, scan, delete vectors
  admin    — full control
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class Role(str, Enum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMIN = "admin"


class Permission(str, Enum):
    HEALTH_READ = "health:read"
    READY_READ = "ready:read"
    METRICS_READ = "metrics:read"

    RAG_QUERY = "rag:query"
    RAG_STREAM = "rag:stream"
    INTELLIGENCE_QUERY = "intelligence:query"

    DOCS_LIST = "docs:list"
    DOCS_UPLOAD = "docs:upload"
    DOCS_DELETE = "docs:delete"
    DOCS_DOWNLOAD = "docs:download"
    DOCS_REINDEX = "docs:reindex"

    SECURITY_SCAN = "security:scan"
    SECURITY_HEADERS = "security:headers"
    PHISHING_SCAN = "security:phishing"

    QUARANTINE_READ = "quarantine:read"
    QUARANTINE_MANAGE = "quarantine:manage"

    TELEMETRY_READ = "telemetry:read"
    COLLECTION_STATS = "collection:stats"
    MODEL_RETRAIN = "model:retrain"
    USERS_ADMIN = "users:admin"
    AUDIT_READ = "audit:read"
    SETTINGS_WRITE = "settings:write"


_VIEWER: frozenset[Permission] = frozenset(
    {
        Permission.HEALTH_READ,
        Permission.READY_READ,
        Permission.RAG_QUERY,
        Permission.RAG_STREAM,
        Permission.INTELLIGENCE_QUERY,
        Permission.DOCS_LIST,
        Permission.DOCS_DOWNLOAD,
        Permission.COLLECTION_STATS,
    }
)

_ANALYST: frozenset[Permission] = _VIEWER | frozenset(
    {
        Permission.DOCS_UPLOAD,
        Permission.DOCS_DELETE,
        Permission.DOCS_REINDEX,
        Permission.SECURITY_SCAN,
        Permission.SECURITY_HEADERS,
        Permission.PHISHING_SCAN,
        Permission.QUARANTINE_READ,
    }
)

_ADMIN: frozenset[Permission] = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.ANALYST: _ANALYST,
    Role.ADMIN: _ADMIN,
}

ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 1,
    Role.ANALYST: 2,
    Role.ADMIN: 3,
}

DEFAULT_REGISTER_ROLE = Role.VIEWER


def parse_role(role: str | Role | None) -> Role | None:
    if role is None:
        return None
    if isinstance(role, Role):
        return role
    try:
        return Role(str(role).strip().lower())
    except ValueError:
        return None


def role_has(role: str | Role | None, permission: Permission | str) -> bool:
    r = parse_role(role)
    if r is None:
        return False
    try:
        perm = permission if isinstance(permission, Permission) else Permission(permission)
    except ValueError:
        return False
    return perm in ROLE_PERMISSIONS.get(r, frozenset())


def role_has_all(role: str | Role | None, permissions: Iterable[Permission | str]) -> bool:
    return all(role_has(role, p) for p in permissions)


def role_has_any(role: str | Role | None, permissions: Iterable[Permission | str]) -> bool:
    return any(role_has(role, p) for p in permissions)


def permissions_for(role: str | Role | None) -> list[str]:
    r = parse_role(role)
    if r is None:
        return []
    return sorted(p.value for p in ROLE_PERMISSIONS.get(r, frozenset()))


def missing_permissions(
    role: str | Role | None, required: Iterable[Permission | str]
) -> list[str]:
    out: list[str] = []
    for p in required:
        if not role_has(role, p):
            out.append(p.value if isinstance(p, Permission) else str(p))
    return out


def role_at_least(role: str | Role | None, minimum: Role | str) -> bool:
    r = parse_role(role)
    m = parse_role(minimum)
    if r is None or m is None:
        return False
    return ROLE_RANK[r] >= ROLE_RANK[m]


def can_assign_role(actor_role: str | Role | None, target_role: str | Role | None) -> bool:
    actor = parse_role(actor_role)
    target = parse_role(target_role)
    if actor is None or target is None:
        return False
    return actor == Role.ADMIN


def describe_matrix() -> dict[str, list[str]]:
    return {role.value: permissions_for(role) for role in Role}