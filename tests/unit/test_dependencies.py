"""
Comprehensive Extended Unit Test Suite for FastAPI Security Dependencies.
Tests API keys, Bearer tokens, optional auth, tenant isolation, RBAC roles,
granular permissions, wildcard scopes, subscription tiers, correlation tracking, and edge cases.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.security.dependencies import (
    SecurityContext,
    get_correlation_id,
    get_optional_security_context,
    get_security_context,
    get_tenant_id,
    require_permission,
    require_role,
    require_tier,
)


def test_get_security_context_with_valid_api_key() -> None:
    """Test successful authentication using a valid X-API-Key header."""
    ctx = get_security_context(x_api_key="tenant-alpha-api-key", x_tenant_id=None)
    
    assert isinstance(ctx, SecurityContext)
    assert ctx.tenant_id == "tenant_alpha"
    assert ctx.tier == "pro"
    assert ctx.has_role("user") is True
    assert ctx.has_permission("documents:read") is True


def test_get_security_context_with_bearer_token() -> None:
    """Test successful authentication using a Bearer token in the Authorization header."""
    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tenant-beta-api-key")
    ctx = get_security_context(bearer=bearer)

    assert ctx.tenant_id == "tenant_beta"
    assert ctx.tier == "standard"
    assert ctx.has_role("reviewer") is True


def test_get_security_context_missing_credentials() -> None:
    """Test that missing API key and Bearer token raises 401 Unauthorized."""
    with pytest.raises(HTTPException) as exc_info:
        get_security_context(x_api_key=None, bearer=None)

    assert exc_info.value.status_code == 401
    assert "Missing authentication credentials" in exc_info.value.detail


def test_get_security_context_invalid_key() -> None:
    """Test that an invalid API key raises 401 Unauthorized."""
    with pytest.raises(HTTPException) as exc_info:
        get_security_context(x_api_key="invalid-fake-key-999")

    assert exc_info.value.status_code == 401
    assert "Invalid authentication credentials" in exc_info.value.detail


def test_tenant_isolation_violation() -> None:
    """Test that mismatched X-Tenant-ID header raises 403 Forbidden."""
    with pytest.raises(HTTPException) as exc_info:
        get_security_context(
            x_api_key="tenant-alpha-api-key",
            x_tenant_id="tenant_beta",  # Mismatched tenant spoofing attempt
        )

    assert exc_info.value.status_code == 403
    assert "Tenant ID mismatch" in exc_info.value.detail


def test_admin_tenant_bypass_isolation() -> None:
    """Test that admin keys can pass tenant headers without triggering mismatch violations."""
    ctx = get_security_context(
        x_api_key="admin-super-secret-key-2026",
        x_tenant_id="tenant_alpha",
    )
    assert ctx.tenant_id == "tenant_admin"


def test_get_correlation_id() -> None:
    """Test extraction and auto-generation of request correlation trace IDs."""
    # Custom trace ID provided
    custom_id = "trace-xyz-789"
    assert get_correlation_id(x_request_id=custom_id) == custom_id

    # Missing trace ID -> auto-generates a UUID string
    generated = get_correlation_id(x_request_id=None)
    assert isinstance(generated, str)
    assert len(generated) > 0


def test_get_optional_security_context() -> None:
    """Test optional security context behavior with credentials, missing credentials, invalid keys, and tenant mismatches."""
    # Without credentials -> returns None
    assert get_optional_security_context(x_api_key=None, bearer=None) is None

    # With valid credentials -> returns populated SecurityContext
    ctx = get_optional_security_context(x_api_key="tenant-alpha-api-key")
    assert ctx is not None
    assert ctx.tenant_id == "tenant_alpha"

    # With invalid key -> returns None instead of raising 401
    assert get_optional_security_context(x_api_key="bad-key") is None

    # With tenant mismatch -> returns None instead of raising 403
    assert get_optional_security_context(x_api_key="tenant-alpha-api-key", x_tenant_id="tenant_beta") is None


def test_get_tenant_id_convenience_dependency() -> None:
    """Test the get_tenant_id convenience dependency wrapper."""
    ctx = SecurityContext(
        tenant_id="tenant_test",
        api_key="test-key",
        roles=["user"],
        permissions=[],
        tier="standard",
    )
    assert get_tenant_id(ctx) == "tenant_test"


def test_require_role_rbac() -> None:
    """Test role-based access control requirement dependencies."""
    ctx_admin = SecurityContext(
        tenant_id="admin",
        api_key="k",
        roles=["admin"],
        permissions=[],
        tier="enterprise",
    )
    ctx_user = SecurityContext(
        tenant_id="user",
        api_key="k",
        roles=["user"],
        permissions=[],
        tier="standard",
    )

    verifier = require_role("admin")

    # Admin passes role check
    assert verifier(ctx_admin) == ctx_admin

    # Regular user fails admin role check -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        verifier(ctx_user)
    assert exc_info.value.status_code == 403
    assert "Required role: 'admin'" in exc_info.value.detail


def test_require_permission_scopes_and_wildcards() -> None:
    """Test granular permission checks, wildcard expansion, and global admin bypass."""
    ctx_scoped = SecurityContext(
        tenant_id="t1",
        api_key="k",
        roles=["user"],
        permissions=["documents:read", "audit:*"],
        tier="pro",
    )
    ctx_superadmin = SecurityContext(
        tenant_id="t2",
        api_key="k",
        roles=["admin"],
        permissions=["system:admin"],
        tier="enterprise",
    )

    # Exact match permission
    assert require_permission("documents:read")(ctx_scoped) == ctx_scoped

    # Wildcard expansion match (audit:* covers audit:write)
    assert require_permission("audit:write")(ctx_scoped) == ctx_scoped

    # Super-admin bypasses any permission check
    assert require_permission("any:custom:scope")(ctx_superadmin) == ctx_superadmin

    # Missing permission -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        require_permission("documents:write")(ctx_scoped)
    assert exc_info.value.status_code == 403
    assert "Required permission scope" in exc_info.value.detail


def test_require_tier_enforcement_and_case_insensitivity() -> None:
    """Test tenant subscription tier hierarchy and case-insensitive matching."""
    ctx_standard = SecurityContext(
        tenant_id="t1",
        api_key="k",
        roles=["user"],
        permissions=[],
        tier="standard",
    )
    ctx_enterprise = SecurityContext(
        tenant_id="t2",
        api_key="k",
        roles=["admin"],
        permissions=[],
        tier="ENTERPRISE",  # Uppercase tier string test
    )

    enterprise_verifier = require_tier("enterprise")

    # Enterprise tenant passes enterprise tier check regardless of case
    assert enterprise_verifier(ctx_enterprise) == ctx_enterprise

    # Standard tenant fails enterprise tier check -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        enterprise_verifier(ctx_standard)
    assert exc_info.value.status_code == 403
    assert "Feature restricted to 'enterprise'" in exc_info.value.detail