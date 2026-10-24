"""
Enterprise FastAPI Security Dependencies.

Provides:
- API Key & Bearer Token authentication (mandatory and optional)
- Multi-tenant ID resolution and cross-tenant isolation checks
- Fine-grained permission scopes and RBAC verifiers
- Tenant subscription tier enforcement
- Request correlation ID (X-Request-ID) tracing
- Automatic security event auditing
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Callable
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from backend.security.audit import (
    EVENT_LOGIN_FAILURE,
    EVENT_LOGIN_SUCCESS,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_MEDIUM,
    record_security_event,
)

logger = logging.getLogger(__name__)

# Security scheme extractors
api_key_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

# Expanded API Key registry with scopes and subscription tiers
VALID_API_KEYS: dict[str, dict[str, Any]] = {
    "admin-super-secret-key-2026": {
        "tenant_id": "tenant_admin",
        "roles": ["admin", "reviewer", "user"],
        "permissions": ["documents:*", "audit:*", "system:admin"],
        "tier": "enterprise",
        "user_id": "usr_admin_01",
        "username": "admin_sys",
    },
    "tenant-alpha-api-key": {
        "tenant_id": "tenant_alpha",
        "roles": ["user"],
        "permissions": ["documents:read", "documents:write"],
        "tier": "pro",
        "user_id": "usr_alpha_01",
        "username": "alpha_user",
    },
    "tenant-beta-api-key": {
        "tenant_id": "tenant_beta",
        "roles": ["user", "reviewer"],
        "permissions": ["documents:read", "documents:write", "quarantine:review"],
        "tier": "standard",
        "user_id": "usr_beta_01",
        "username": "beta_reviewer",
    },
}


# ============================================================================
# Models & Context
# ============================================================================

class SecurityContext:
    def __init__(
        self,
        tenant_id: str,
        api_key: str,
        roles: list[str],
        permissions: list[str],
        tier: str,
        user_id: str | None = None,
        username: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.api_key = api_key
        self.roles = roles
        self.permissions = permissions
        self.tier = tier
        self.user_id = user_id
        self.username = username

    def has_role(self, role: str) -> bool:
        return role in self.roles or "admin" in self.roles

    def has_permission(self, permission: str) -> bool:
        if "*" in self.permissions or "system:admin" in self.permissions:
            return True
        
        # Support wildcard scopes like "documents:*"
        parts = permission.split(":")
        if len(parts) == 2:
            wildcard = f"{parts[0]}:*"
            if wildcard in self.permissions:
                return True

        return permission in self.permissions


# ============================================================================
# Core Authentication & Tenant Resolution
# ============================================================================

def get_correlation_id(
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> str:
    """Extracts or generates an end-to-end request trace ID."""
    return x_request_id or str(uuid4())


def get_security_context(
    x_api_key: Annotated[str | None, Security(api_key_header_scheme)] = None,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    correlation_id: str = Depends(get_correlation_id),
) -> SecurityContext:
    """
    Validates mandatory credentials, resolves tenant context, prevents cross-tenant spoofing,
    and returns an active SecurityContext.
    """
    provided_key = x_api_key
    if not provided_key and bearer:
        provided_key = bearer.credentials

    if not provided_key:
        record_security_event(
            tenant_id=x_tenant_id or "unknown",
            action=EVENT_LOGIN_FAILURE,
            severity=SEVERITY_MEDIUM,
            metadata={"reason": "Missing API key or Bearer token", "correlation_id": correlation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials (X-API-Key or Bearer token required)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client_info = VALID_API_KEYS.get(provided_key)
    if not client_info:
        record_security_event(
            tenant_id=x_tenant_id or "unknown",
            action=EVENT_LOGIN_FAILURE,
            severity=SEVERITY_HIGH,
            metadata={"reason": "Invalid or revoked API key provided", "correlation_id": correlation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    resolved_tenant = client_info["tenant_id"]

    if x_tenant_id and x_tenant_id != resolved_tenant and resolved_tenant != "tenant_admin":
        record_security_event(
            tenant_id=x_tenant_id,
            action=EVENT_LOGIN_FAILURE,
            severity=SEVERITY_HIGH,
            metadata={
                "reason": "Tenant mismatch violation",
                "attempted_tenant": x_tenant_id,
                "bound_tenant": resolved_tenant,
                "correlation_id": correlation_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant ID mismatch or unauthorized cross-tenant access",
        )

    record_security_event(
        tenant_id=resolved_tenant,
        action=EVENT_LOGIN_SUCCESS,
        severity=SEVERITY_INFO,
        user_id=client_info.get("user_id"),
        username=client_info.get("username"),
        metadata={"correlation_id": correlation_id},
    )

    return SecurityContext(
        tenant_id=resolved_tenant,
        api_key=provided_key,
        roles=client_info.get("roles", []),
        permissions=client_info.get("permissions", []),
        tier=client_info.get("tier", "standard"),
        user_id=client_info.get("user_id"),
        username=client_info.get("username"),
    )


def get_optional_security_context(
    x_api_key: Annotated[str | None, Security(api_key_header_scheme)] = None,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
) -> SecurityContext | None:
    """Optional security context for endpoints that allow anonymous or unauthenticated access."""
    provided_key = x_api_key
    if not provided_key and bearer:
        provided_key = bearer.credentials

    if not provided_key:
        return None

    client_info = VALID_API_KEYS.get(provided_key)
    if not client_info:
        return None

    resolved_tenant = client_info["tenant_id"]
    if x_tenant_id and x_tenant_id != resolved_tenant and resolved_tenant != "tenant_admin":
        return None

    return SecurityContext(
        tenant_id=resolved_tenant,
        api_key=provided_key,
        roles=client_info.get("roles", []),
        permissions=client_info.get("permissions", []),
        tier=client_info.get("tier", "standard"),
        user_id=client_info.get("user_id"),
        username=client_info.get("username"),
    )


def get_tenant_id(
    ctx: Annotated[SecurityContext, Depends(get_security_context)],
) -> str:
    """Convenience dependency returning the active authenticated tenant ID."""
    return ctx.tenant_id


# ============================================================================
# Authorization & Enforcement Factories (RBAC, Scopes, Tiers)
# ============================================================================

def require_role(required_role: str) -> Callable[[SecurityContext], SecurityContext]:
    """Dependency factory enforcing mandatory user role requirements."""
    def role_verifier(
        ctx: Annotated[SecurityContext, Depends(get_security_context)],
    ) -> SecurityContext:
        if not ctx.has_role(required_role):
            record_security_event(
                tenant_id=ctx.tenant_id,
                action=EVENT_LOGIN_FAILURE,
                severity=SEVERITY_HIGH,
                user_id=ctx.user_id,
                username=ctx.username,
                metadata={"reason": f"Insufficient permissions. Required role: {required_role}"},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: '{required_role}'.",
            )
        return ctx

    return role_verifier


def require_permission(required_permission: str) -> Callable[[SecurityContext], SecurityContext]:
    """Dependency factory enforcing granular permission scopes."""
    def permission_verifier(
        ctx: Annotated[SecurityContext, Depends(get_security_context)],
    ) -> SecurityContext:
        if not ctx.has_permission(required_permission):
            record_security_event(
                tenant_id=ctx.tenant_id,
                action=EVENT_LOGIN_FAILURE,
                severity=SEVERITY_HIGH,
                user_id=ctx.user_id,
                username=ctx.username,
                metadata={"reason": f"Missing required permission scope: {required_permission}"},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required permission scope: '{required_permission}'.",
            )
        return ctx

    return permission_verifier


def require_tier(minimum_tier: str) -> Callable[[SecurityContext], SecurityContext]:
    """Dependency factory enforcing tenant subscription tier access."""
    tier_hierarchy = {"standard": 1, "pro": 2, "enterprise": 3}

    def tier_verifier(
        ctx: Annotated[SecurityContext, Depends(get_security_context)],
    ) -> SecurityContext:
        user_tier_level = tier_hierarchy.get(ctx.tier.lower(), 1)
        min_tier_level = tier_hierarchy.get(minimum_tier.lower(), 1)

        if user_tier_level < min_tier_level:
            record_security_event(
                tenant_id=ctx.tenant_id,
                action=EVENT_LOGIN_FAILURE,
                severity=SEVERITY_MEDIUM,
                metadata={"reason": f"Feature requires {minimum_tier} tier. Tenant is on {ctx.tier} tier."},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Feature restricted to '{minimum_tier}' subscription tier or higher.",
            )
        return ctx

    return tier_verifier