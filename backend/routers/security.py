"""
Security & telemetry API routes.

Routes (prefix /api/v1/security unless noted)
--------------------------------------------
  GET  /api/v1/security/health
  GET  /api/v1/security/telemetry/summary
  GET  /api/v1/security/status
  POST /api/v1/security/scan/text
  POST /api/v1/security/scan/phishing

Also exports get_vector_store() for tests / DI.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/security", tags=["security"])

# ---------------------------------------------------------------------------
# Vector store DI (tests import get_vector_store from this module)
# ---------------------------------------------------------------------------

_vector_store_override: Callable[[], Any] | None = None
_cached_store: Any = None


def set_vector_store_factory(factory: Callable[[], Any] | None) -> None:
    """Install or clear a factory used by get_vector_store(). None restores default."""
    global _vector_store_override, _cached_store
    _vector_store_override = factory
    _cached_store = None


def clear_vector_store_cache() -> None:
    global _cached_store
    _cached_store = None


def get_vector_store() -> Any | None:
    """
    Return the vector-store module/client used by security flows.

    Order: test override → backend.db.qdrant → backend.providers.qdrant_provider → None
    """
    global _cached_store

    if _vector_store_override is not None:
        try:
            return _vector_store_override()
        except Exception as exc:
            logger.debug("vector_store override failed: %s", exc)
            return None

    if _cached_store is not None:
        return _cached_store

    try:
        from backend.db import qdrant as qdrant_mod

        _cached_store = qdrant_mod
        return _cached_store
    except Exception as exc:
        logger.debug("backend.db.qdrant unavailable: %s", exc)

    try:
        from backend.providers import qdrant_provider as qdrant_provider_mod

        _cached_store = qdrant_provider_mod
        return _cached_store
    except Exception as exc:
        logger.debug("backend.providers.qdrant_provider unavailable: %s", exc)

    return None


async def get_qdrant_client_or_none() -> Any | None:
    store = get_vector_store()
    if store is None:
        return None
    for name in ("get_qdrant_client", "get_client"):
        getter = getattr(store, name, None)
        if callable(getter):
            try:
                return await getter()
            except Exception as exc:
                logger.debug("%s failed: %s", name, exc)
    return None


def vector_store_status() -> dict[str, Any]:
    store = get_vector_store()
    return {
        "available": store is not None,
        "module": getattr(store, "__name__", None) if store is not None else None,
        "override_active": _vector_store_override is not None,
    }


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TextScanRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=200_000)
    source: str | None = Field(None, max_length=120)


class PhishingScanRequest(BaseModel):
    payload: str = Field(..., min_length=1, max_length=50_000)
    scan_type: str = Field("url", pattern="^(url|email|text)$")


class ScanResponse(BaseModel):
    flagged: bool
    risk_score: float = 0.0
    severity: str = "low"
    findings: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    detail: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _telemetry_fallback() -> dict[str, Any]:
    return {
        "total_caught": 0,
        "active_threats": 0,
        "events": [],
        "source": "fallback",
    }


async def _collection_stats_soft() -> dict[str, Any]:
    store = get_vector_store()
    if store is None:
        return {"status": "unavailable", "points_count": 0}
    fn = getattr(store, "get_collection_stats", None)
    if not callable(fn):
        return {"status": "unavailable", "points_count": 0}
    try:
        stats = await fn()
        return stats if isinstance(stats, dict) else {"status": "ok", "raw": stats}
    except Exception as exc:
        logger.debug("collection stats failed: %s", exc)
        return {"status": "error", "detail": str(exc)[:200]}


def _scan_text_local(text: str) -> ScanResponse:
    """Soft-fail local scan using validators / file_scanner when present."""
    findings: list[str] = []
    categories: list[str] = []
    risk = 0.0

    try:
        from backend.security.validators import PromptInjectionDetector

        det = PromptInjectionDetector()
        result = det.scan_text(text)
        if getattr(result, "is_flagged", False):
            findings.extend(list(getattr(result, "matched_patterns", None) or [])[:20])
            categories.append("prompt_injection")
            risk = max(risk, float(getattr(result, "risk_score", 0.5) or 0.5))
    except Exception as exc:
        logger.debug("PromptInjectionDetector unavailable: %s", exc)

    # Lightweight keyword heuristics
    lowered = text.lower()
    for kw, cat, score in (
        ("ignore all previous", "jailbreak", 0.8),
        ("system prompt", "exfiltration", 0.6),
        ("sk-proj-", "secret", 0.9),
        ("password=", "credential", 0.7),
    ):
        if kw in lowered:
            findings.append(kw)
            categories.append(cat)
            risk = max(risk, score)

    risk = min(1.0, risk)
    severity = (
        "critical"
        if risk >= 0.9
        else "high"
        if risk >= 0.7
        else "medium"
        if risk >= 0.4
        else "low"
    )
    flagged = risk >= 0.4 or bool(findings)

    if flagged:
        try:
            from backend.security.event_publish import emit_security_event

            emit_security_event(
                threat_type="text_scan",
                severity=severity,
                detail="; ".join(findings[:5]) or "flagged",
                detector="security.router",
                status="flagged" if flagged else "clean",
            )
        except Exception:
            pass

    return ScanResponse(
        flagged=flagged,
        risk_score=round(risk, 4),
        severity=severity,
        findings=findings[:20],
        categories=sorted(set(categories)),
        detail="scanned",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health", summary="Security router liveness")
async def security_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "router": "security",
        "vector_store": vector_store_status(),
        "ts": time.time(),
    }


@router.get("/status", summary="Security + vector store status")
async def security_status() -> dict[str, Any]:
    stats = await _collection_stats_soft()
    return {
        "status": "ok",
        "vector_store": vector_store_status(),
        "collection": stats,
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


@router.get(
    "/telemetry/summary",
    summary="Threat telemetry summary for dashboards",
)
async def telemetry_summary() -> dict[str, Any]:
    # Prefer core telemetry if present
    try:
        from backend.core import telemetry as tel

        if hasattr(tel, "get_summary"):
            data = tel.get_summary()
            if isinstance(data, dict):
                return data
        if hasattr(tel, "summary"):
            data = tel.summary()
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("core.telemetry unavailable: %s", exc)

    # Ring buffer from security_stream if mounted
    try:
        from backend.routers import security_stream as ss

        events = list(getattr(ss, "_events", []) or [])[-50:]
        active = sum(
            1
            for e in events
            if str(e.get("severity", "")).lower() in {"high", "critical"}
        )
        return {
            "total_caught": len(events),
            "active_threats": active,
            "events": events,
            "source": "security_stream",
        }
    except Exception as exc:
        logger.debug("security_stream unavailable: %s", exc)

    return _telemetry_fallback()


@router.post(
    "/scan/text",
    response_model=ScanResponse,
    summary="Scan free text for injection / secrets",
)
async def scan_text(body: TextScanRequest) -> ScanResponse:
    return _scan_text_local(body.text)


@router.post(
    "/scan/phishing",
    response_model=ScanResponse,
    summary="Lightweight phishing / suspicious payload scan",
)
async def scan_phishing(body: PhishingScanRequest) -> ScanResponse:
    text = body.payload
    result = _scan_text_local(text)
    # Boost risk for url-like lure patterns
    if body.scan_type in {"url", "email"}:
        lure = ("login", "verify", "wallet", "seed phrase", "urgent")
        hits = [k for k in lure if k in text.lower()]
        if hits:
            result.findings = list(result.findings) + [f"lure:{h}" for h in hits]
            result.risk_score = min(1.0, max(result.risk_score, 0.55))
            result.flagged = True
            result.severity = (
                "high"
                if result.risk_score >= 0.7
                else "medium"
                if result.risk_score >= 0.4
                else result.severity
            )
            result.categories = sorted(set(list(result.categories) + ["phishing"]))
    return result


__all__ = [
    "router",
    "get_vector_store",
    "set_vector_store_factory",
    "clear_vector_store_cache",
    "get_qdrant_client_or_none",
    "vector_store_status",
]