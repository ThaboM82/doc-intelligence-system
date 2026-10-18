"""
Enterprise security dependencies for authentication, multi-tenant isolation, 
and request context verification.
"""

from __future__ import annotations

import os
import logging
from fastapi import Header, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

logger = logging.getLogger("document_intelligence.security")

# API Key security scheme configuration
API_KEY_NAME = "X-API-Key"
api_key_header_scheme = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def verify_and_get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID")
) -> str:
    """
    Validates and extracts the tenant ID from request headers.
    Guarantees strict multi-tenant isolation in Qdrant vector collections 
    and downstream storage layers.
    """
    if not x_tenant_id or not x_tenant_id.strip():
        logger.warning("Security Alert: Request blocked due to missing X-Tenant-ID header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or empty required tenant identification header: X-Tenant-ID",
        )
    
    sanitized_tenant_id = x_tenant_id.strip()
    
    # Optional basic format security check (e.g., prevent path injection characters)
    if not sanitized_tenant_id.replace("-", "").replace("_", "").isalnum():
        logger.warning("Security Alert: Malformed tenant ID format detected: %s", sanitized_tenant_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tenant ID format. Alphanumeric characters, hyphens, and underscores only.",
        )
        
    return sanitized_tenant_id


async def verify_enterprise_api_key(
    api_key: str | None = Security(api_key_header_scheme)
) -> str:
    """
    Validates the enterprise service API key passed via X-API-Key header.
    In production, this can be integrated with a secure secret manager or database lookup.
    """
    master_api_key = os.getenv("ENTERPRISE_API_KEY", "")

    # If no master key is set in development, allow fallback or warn
    if not master_api_key and os.getenv("ENVIRONMENT", "development").lower() == "development":
        logger.debug("Development mode: API key validation bypassed.")
        return "dev-mode-key"

    if not api_key or api_key != master_api_key:
        logger.error("Unauthorized access attempt with invalid or missing API Key.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing enterprise API key.",
        )
        
    return api_key