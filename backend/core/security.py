"""
Auth dependencies, RBAC gates, and request security helpers.

Supports:
  - Authorization: Bearer <jwt>
  - X-API-Key: <ADMIN_API_KEY>  → synthetic admin (ops / scripts)
  - require_permissions / require_any_permission / require_roles
  - Optional auth (public routes that enrich when logged in)
  - Lightweight in-memory JWT jti denylist (logout)
  - Audit helper for sensitive actions
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.rbac import (
    Permission,
    missing_permissions,
    parse_role,
    role_at_least,
    role_has,
)

logger = logging.getLogger(__name__)

security_scheme = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AUTH_REQUIRED_DEFAULT = os.getenv("AUTH_REQUIRED", "false").lower() in (
    "1",
    "true",
    "yes",
)
JWT_DENYLIST_MAX = int(os.getenv("JWT_DENYLIST_MAX", "10000"))

# jti -> expires_at (unix). Stateless JWT logout best-effort.
_jti_denylist: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Denylist (logout)
# ---------------------------------------------------------------------------


def deny_jti(jti: str, exp: float | None = None) -> None:
    """Mark a token id as revoked until exp (or +24h)."""
    if not jti:
        return
    if len(_jti_denylist) > JWT_DENYLIST_MAX:
        now = time.time()
        for k, v in list(_jti_denylist.items()):
            if v < now:
                _jti_denylist.pop(k, None)
    _jti_denylist[jti] = float(exp or (time.time() + 86400))


def is_jti_denied(jti: str | None) -> bool:
    if not jti:
        return False
    exp = _jti_denylist.get(jti)
    if exp is None:
        return False
    if exp < time.time():
        _jti_denylist.pop(jti, None)
        return False
    return True


# ---------------------------------------------------------------------------
# User loading
# ---------------------------------------------------------------------------


def _synthetic_admin() -> dict[str, Any]:
    return {
        "id": "admin-key",
        "email": "admin@system",
        "role": "admin",
        "full_name": "API Key",
        "active": True,
        "auth_method": "api_key",
    }


def _load_user_from_token(token: str) -> dict[str, Any]:
    from backend.routers.auth import _decode_token, get_user_record

    payload = _decode_token(token)
    jti = payload.get("jti")
    if is_jti_denied(str(jti) if jti else None):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = str(payload.get("sub") or "")
    user = get_user_record(user_id)
    if not user or not user.get("active", True):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="User not found or disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Attach token claims for logout / audit
    out = dict(user)
    out["token_jti"] = jti
    out["token_exp"] = payload.get("exp")
    out["auth_method"] = "jwt"
    return out


def _try_api_key(x_api_key: str | None) -> dict[str, Any] | None:
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if admin_key and x_api_key and x_api_key == admin_key:
        return _synthetic_admin()
    return None


# ---------------------------------------------------------------------------
# Core dependencies
# ---------------------------------------------------------------------------


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Require a valid JWT or ADMIN_API_KEY."""
    key_user = _try_api_key(x_api_key)
    if key_user is not None:
        return key_user

    if creds is None or not creds.credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _load_user_from_token(creds.credentials)


async def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> dict[str, Any] | None:
    """Never raises — returns None if anonymous."""
    try:
        key_user = _try_api_key(x_api_key)
        if key_user is not None:
            return key_user
        if creds is None or not creds.credentials:
            return None
        return _load_user_from_token(creds.credentials)
    except HTTPException:
        return None


async def get_current_user_if_auth_required(
    creds: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> dict[str, Any] | None:
    """
    If AUTH_REQUIRED=true, enforce login; otherwise allow anonymous.
    Use on routes you want to lock only in production.
    """
    if AUTH_REQUIRED_DEFAULT:
        return await get_current_user(creds, x_api_key)
    return await get_optional_user(creds, x_api_key)


# ---------------------------------------------------------------------------
# RBAC dependencies
# ---------------------------------------------------------------------------


def require_permissions(*perms: Permission) -> Callable[..., Any]:
    """User must hold ALL listed permissions."""

    async def _dep(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        role = user.get("role") or "viewer"
        missing = missing_permissions(role, perms)
        if missing:
            logger.warning(
                "RBAC deny user=%s role=%s missing=%s",
                user.get("email"),
                role,
                missing,
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "Forbidden",
                    "missing_permissions": missing,
                    "role": role,
                },
            )
        return user

    return _dep


def require_any_permission(*perms: Permission) -> Callable[..., Any]:
    """User must hold at least one permission."""

    async def _dep(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        role = user.get("role") or "viewer"
        if not any(role_has(role, p) for p in perms):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "Forbidden",
                    "required_any": [p.value for p in perms],
                    "role": role,
                },
            )
        return user

    return _dep


def require_roles(*roles: str) -> Callable[..., Any]:
    async def _dep(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user.get("role") not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return user

    return _dep


def require_role_at_least(minimum: str) -> Callable[..., Any]:
    """e.g. require_role_at_least('analyst') → analyst or admin."""

    async def _dep(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if not role_at_least(user.get("role"), minimum):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{minimum}' or higher",
            )
        return user

    return _dep


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def audit_event(
    action: str,
    *,
    user: dict[str, Any] | None = None,
    request: Request | None = None,
    resource: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Structured audit log line (ship to SIEM later)."""
    payload = {
        "ts": time.time(),
        "action": action,
        "user_id": (user or {}).get("id"),
        "email": (user or {}).get("email"),
        "role": (user or {}).get("role"),
        "auth_method": (user or {}).get("auth_method"),
        "resource": resource,
        "path": str(request.url.path) if request else None,
        "method": request.method if request else None,
        "client": (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request and request.client else None)
        )
        if request
        else None,
        **(extra or {}),
    }
    logger.info("AUDIT %s", payload)


# ---------------------------------------------------------------------------
# Logout helper (call from auth router)
# ---------------------------------------------------------------------------


def revoke_current_token(user: dict[str, Any]) -> None:
    jti = user.get("token_jti")
    exp = user.get("token_exp")
    exp_ts: float | None = None
    if exp is not None:
        try:
            # jose may give datetime or int
            if hasattr(exp, "timestamp"):
                exp_ts = float(exp.timestamp())  # type: ignore[union-attr]
            else:
                exp_ts = float(exp)
        except (TypeError, ValueError):
            exp_ts = None
    if jti:
        deny_jti(str(jti), exp_ts)
        logger.info("Revoked jti=%s user=%s", jti, user.get("email"))