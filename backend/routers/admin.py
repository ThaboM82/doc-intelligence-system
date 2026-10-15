"""
Admin API — dashboard, telemetry, AI threat scan, users, ops controls.

All routes require JWT (or X-API-Key admin) plus RBAC permissions.
Prefix: /api/v1/admin
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from backend.core.rbac import Permission, Role, can_assign_role, permissions_for
from backend.core.security import (
    audit_event,
    require_permissions,
    require_roles,
)
from backend.core.telemetry import get_telemetry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ThreatScanRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=100_000)
    use_ai: bool = True
    document_id: str | None = None


class ThreatScanResponse(BaseModel):
    flagged: bool
    score: float
    severity: str
    detector: str
    hits: list[dict[str, Any]] = []
    rationale: str | None = None
    ai_label: str | None = None


class SetRoleRequest(BaseModel):
    role: str = Field(..., description="viewer | analyst | admin")


class UserRow(BaseModel):
    id: str
    email: str
    full_name: str | None = None
    role: str
    active: bool = True
    permissions: list[str] = []
    created_at: float = 0.0


class HealthOpsResponse(BaseModel):
    api: str = "ok"
    qdrant: dict[str, Any] = {}
    telemetry: dict[str, Any] = {}
    uptime_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Dashboard & telemetry
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def admin_dashboard(
    request: Request,
    user: dict = Depends(require_permissions(Permission.TELEMETRY_READ)),
) -> dict[str, Any]:
    snap = get_telemetry().admin_dashboard()
    # Enrich with Qdrant if available
    try:
        from backend.db.qdrant import health_check, is_collection_ready

        q = await health_check()
        snap["qdrant"] = {**q, "collection_ready": is_collection_ready()}
    except Exception as exc:
        snap["qdrant"] = {"ok": False, "error": str(exc)}
    audit_event("admin.dashboard.view", user=user, request=request)
    return snap


@router.get("/telemetry/summary")
async def telemetry_summary(
    user: dict = Depends(require_permissions(Permission.TELEMETRY_READ)),
) -> dict[str, Any]:
    """Shape for SecurityDashboard / AdminDashboard KPIs."""
    return get_telemetry().summary()


@router.get("/telemetry/metrics")
async def telemetry_metrics(
    user: dict = Depends(require_permissions(Permission.METRICS_READ)),
) -> dict[str, Any]:
    return get_telemetry().metrics_snapshot()


@router.get("/ops/health", response_model=HealthOpsResponse)
async def ops_health(
    user: dict = Depends(require_permissions(Permission.HEALTH_READ)),
) -> HealthOpsResponse:
    tel = get_telemetry()
    qdrant: dict[str, Any] = {}
    try:
        from backend.db.qdrant import health_check, is_collection_ready

        qdrant = await health_check()
        qdrant["collection_ready"] = is_collection_ready()
    except Exception as exc:
        qdrant = {"ok": False, "error": str(exc)}
    return HealthOpsResponse(
        api="ok",
        qdrant=qdrant,
        telemetry={
            "total_caught": tel.summary().get("total_caught"),
            "active_threats": tel.summary().get("active_threats"),
        },
        uptime_seconds=tel.metrics_snapshot().get("uptime_seconds", 0.0),
    )


# ---------------------------------------------------------------------------
# AI / heuristic threat scan
# ---------------------------------------------------------------------------


@router.post("/threat-scan", response_model=ThreatScanResponse)
async def threat_scan(
    body: ThreatScanRequest,
    request: Request,
    user: dict = Depends(require_permissions(Permission.SECURITY_SCAN)),
) -> ThreatScanResponse:
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "—")
    )
    result = await get_telemetry().analyze_and_record(
        body.text,
        source_ip=client_ip,
        document_id=body.document_id,
        user_email=user.get("email"),
        use_ai=body.use_ai,
    )
    audit_event(
        "admin.threat_scan",
        user=user,
        request=request,
        extra={
            "flagged": result.get("flagged"),
            "score": result.get("score"),
            "detector": result.get("detector"),
        },
    )
    return ThreatScanResponse(
        flagged=bool(result.get("flagged")),
        score=float(result.get("score") or 0),
        severity=str(result.get("severity") or "low"),
        detector=str(result.get("detector") or "heuristic"),
        hits=list(result.get("hits") or []),
        rationale=result.get("rationale"),
        ai_label=result.get("ai_label"),
    )


@router.post("/threats/clear-active")
async def clear_active_threats(
    request: Request,
    user: dict = Depends(require_roles("admin")),
) -> dict[str, Any]:
    tel = get_telemetry()
    prev = tel.active_threats
    tel.active_threats = 0
    audit_event(
        "admin.threats.clear_active",
        user=user,
        request=request,
        extra={"previous": prev},
    )
    return {"status": "ok", "previous_active_threats": prev}


# ---------------------------------------------------------------------------
# Collection / vector ops
# ---------------------------------------------------------------------------


@router.get("/collection/stats")
async def collection_stats(
    user: dict = Depends(require_permissions(Permission.COLLECTION_STATS)),
) -> dict[str, Any]:
    try:
        from backend.db.qdrant import get_collection_stats

        return await get_collection_stats()
    except ImportError:
        try:
            from backend.db.qdrant import get_qdrant_client
            import os

            client = await get_qdrant_client()
            name = os.getenv("QDRANT_COLLECTION", "document_intelligence")
            info = await client.get_collection(collection_name=name)
            return {
                "status": str(info.status),
                "points_count": getattr(info, "points_count", None),
                "vectors_count": getattr(info, "vectors_count", None),
                "indexed_vectors_count": getattr(info, "indexed_vectors_count", None),
            }
        except Exception as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Collection stats unavailable: {exc}",
            ) from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# User administration (in-memory store from auth.py)
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[UserRow])
async def list_users(
    user: dict = Depends(require_permissions(Permission.USERS_ADMIN)),
) -> list[UserRow]:
    from backend.routers import auth as auth_mod

    rows: list[UserRow] = []
    for u in getattr(auth_mod, "_users", {}).values():
        rows.append(
            UserRow(
                id=u["id"],
                email=u["email"],
                full_name=u.get("full_name"),
                role=u.get("role", "viewer"),
                active=bool(u.get("active", True)),
                permissions=permissions_for(u.get("role")),
                created_at=float(u.get("created_at") or 0),
            )
        )
    rows.sort(key=lambda r: r.created_at)
    return rows


@router.patch("/users/{user_id}/role", response_model=UserRow)
async def set_user_role(
    user_id: str,
    body: SetRoleRequest,
    request: Request,
    actor: dict = Depends(require_permissions(Permission.USERS_ADMIN)),
) -> UserRow:
    from backend.routers import auth as auth_mod

    target = getattr(auth_mod, "_users", {}).get(user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    if not can_assign_role(actor.get("role"), body.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cannot assign that role")
    try:
        new_role = Role(body.role.strip().lower()).value
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="role must be viewer | analyst | admin",
        ) from exc
    old = target.get("role")
    target["role"] = new_role
    audit_event(
        "admin.user.set_role",
        user=actor,
        request=request,
        resource=user_id,
        extra={"from": old, "to": new_role, "target_email": target.get("email")},
    )
    return UserRow(
        id=target["id"],
        email=target["email"],
        full_name=target.get("full_name"),
        role=new_role,
        active=bool(target.get("active", True)),
        permissions=permissions_for(new_role),
        created_at=float(target.get("created_at") or 0),
    )


@router.patch("/users/{user_id}/active", response_model=UserRow)
async def set_user_active(
    user_id: str,
    active: bool,
    request: Request,
    actor: dict = Depends(require_permissions(Permission.USERS_ADMIN)),
) -> UserRow:
    from backend.routers import auth as auth_mod

    target = getattr(auth_mod, "_users", {}).get(user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    if target["id"] == actor.get("id"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )
    target["active"] = bool(active)
    audit_event(
        "admin.user.set_active",
        user=actor,
        request=request,
        resource=user_id,
        extra={"active": active, "target_email": target.get("email")},
    )
    return UserRow(
        id=target["id"],
        email=target["email"],
        full_name=target.get("full_name"),
        role=target.get("role", "viewer"),
        active=bool(target.get("active", True)),
        permissions=permissions_for(target.get("role")),
        created_at=float(target.get("created_at") or 0),
    )


# ---------------------------------------------------------------------------
# RBAC matrix (docs for UI)
# ---------------------------------------------------------------------------


@router.get("/rbac-matrix")
async def rbac_matrix(
    user: dict = Depends(require_roles("admin")),
) -> dict[str, list[str]]:
    from backend.core.rbac import describe_matrix

    return describe_matrix()