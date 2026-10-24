"""
Soft-fail publish into the security SSE / telemetry buffer.

Call sites: file_scanner, ingest_service, HITL, admin threat-scan, RAG, documents.
Never raises into business logic — logging only on failure.

Env
---
  SECURITY_EVENTS_ENABLED       true/1 to allow publish (default true)
  SECURITY_EVENTS_MIN_SEVERITY  drop events below this level (default low)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_ENABLED = os.getenv("SECURITY_EVENTS_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_SEVERITIES = frozenset(_SEVERITY_RANK)

_MIN_SEVERITY = os.getenv("SECURITY_EVENTS_MIN_SEVERITY", "low").strip().lower()
if _MIN_SEVERITY not in _SEVERITIES:
    _MIN_SEVERITY = "low"


def _norm_severity(value: Any, *, default: str = "medium") -> str:
    s = str(value or default).strip().lower()
    return s if s in _SEVERITIES else default


def _passes_min_severity(severity: str) -> bool:
    return _SEVERITY_RANK.get(severity, 0) >= _SEVERITY_RANK.get(_MIN_SEVERITY, 0)


def emit_security_event(
    *,
    threat_type: str,
    severity: str = "medium",
    document_id: str | None = None,
    detail: str | None = None,
    detector: str | None = None,
    filename: str | None = None,
    source_ip: str | None = None,
    status: str | None = None,
    confidence_score: float | None = None,
    **extra: Any,
) -> dict[str, Any] | None:
    """
    Publish one security/telemetry event.

    Returns the normalized event dict if published, else None.
    """
    if not _ENABLED:
        return None

    sev = _norm_severity(severity)
    if not _passes_min_severity(sev):
        return None

    conf: float | None = None
    if confidence_score is not None:
        try:
            conf = max(0.0, min(1.0, float(confidence_score)))
        except (TypeError, ValueError):
            conf = None

    payload: dict[str, Any] = {
        "threat_type": (threat_type or "event")[:200],
        "severity": sev,
        "document_id": document_id,
        "detail": (detail or "")[:800] or None,
        "detector": detector,
        "filename": filename,
        "source_ip": source_ip or "—",
        "status": status,
        "confidence_score": conf,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    for k, v in extra.items():
        if v is not None and k not in payload:
            payload[k] = v
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        from backend.routers.security_stream import publish_security_event

        published = publish_security_event(payload)
    except Exception as exc:  # pragma: no cover
        logger.debug("security event not published: %s", exc)
        return None

    # Metrics only after a successful publish
    try:
        from backend.observability.metrics import record_security_event

        record_security_event(
            str(payload.get("threat_type") or "event"),
            str(payload.get("severity") or "medium"),
        )
    except Exception:
        pass

    return published


# ---------------------------------------------------------------------------
# File scan / ingest
# ---------------------------------------------------------------------------


def emit_file_scan_failed(
    *,
    document_id: str | None,
    filename: str,
    reasons: list[str] | None = None,
    severity: str = "high",
    confidence_score: float | None = None,
    detector: str = "file_scanner",
) -> dict[str, Any] | None:
    detail = "; ".join(reasons or []) or "File failed security scan"
    return emit_security_event(
        threat_type="file_scan",
        severity=severity,
        document_id=document_id,
        detail=detail,
        detector=detector,
        filename=filename,
        status="quarantine_candidate",
        confidence_score=confidence_score,
    )


def emit_file_scan_error(
    *,
    document_id: str | None,
    filename: str,
    error: str,
) -> dict[str, Any] | None:
    return emit_security_event(
        threat_type="file_scan_error",
        severity="medium",
        document_id=document_id,
        detail=str(error)[:500],
        detector="file_scanner",
        filename=filename,
        status="scan_error",
    )


def emit_ingest_quarantine(
    *,
    document_id: str,
    filename: str,
    reasons: list[str] | None = None,
    severity: str = "high",
) -> dict[str, Any] | None:
    return emit_security_event(
        threat_type="ingest_quarantine",
        severity=severity,
        document_id=document_id,
        detail="; ".join(reasons or []) or "Document quarantined at ingest",
        detector="ingest_service",
        filename=filename,
        status="quarantined",
    )


def emit_ingest_indexed(
    *,
    document_id: str,
    filename: str,
    chunks: int,
    collection: str | None = None,
) -> dict[str, Any] | None:
    detail = f"Indexed {chunks} chunk(s)"
    if collection:
        detail += f" into '{collection}'"
    return emit_security_event(
        threat_type="ingest_indexed",
        severity="low",
        document_id=document_id,
        detail=detail,
        detector="ingest_service",
        filename=filename,
        status="indexed",
        chunks_upserted=chunks,
        collection=collection,
    )


def emit_ingest_failed(
    *,
    document_id: str,
    filename: str,
    error: str,
) -> dict[str, Any] | None:
    return emit_security_event(
        threat_type="ingest_failed",
        severity="medium",
        document_id=document_id,
        detail=str(error)[:500],
        detector="ingest_service",
        filename=filename,
        status="failed",
    )


def emit_document_deleted(
    *,
    document_id: str,
    filename: str | None = None,
    points_deleted: int | None = None,
) -> dict[str, Any] | None:
    detail = f"Deleted document_id={document_id}"
    if points_deleted is not None:
        detail += f" ({points_deleted} points)"
    return emit_security_event(
        threat_type="document_deleted",
        severity="low",
        document_id=document_id,
        detail=detail,
        detector="documents",
        filename=filename,
        status="deleted",
        points_deleted=points_deleted,
    )


# ---------------------------------------------------------------------------
# AI / admin threat scan
# ---------------------------------------------------------------------------


def emit_threat_scan_result(
    *,
    flagged: bool,
    severity: str = "medium",
    score: float | None = None,
    rationale: str | None = None,
    detector: str = "threat_scan",
    source_ip: str | None = None,
    sample: str | None = None,
) -> dict[str, Any] | None:
    """Manual / admin AI threat analysis result."""
    detail = rationale or ("Flagged by threat scan" if flagged else "Clean")
    if sample:
        detail = f"{detail} | sample={sample[:120]}"
    return emit_security_event(
        threat_type="threat_scan",
        severity=severity if flagged else "low",
        detail=detail,
        detector=detector,
        status="flagged" if flagged else "clean",
        confidence_score=score,
        source_ip=source_ip,
        flagged=flagged,
    )


# ---------------------------------------------------------------------------
# HITL
# ---------------------------------------------------------------------------


def emit_hitl_queued(
    *,
    item_id: str,
    document_id: str | None = None,
    reason: str | None = None,
    severity: str = "medium",
) -> dict[str, Any] | None:
    return emit_security_event(
        threat_type="hitl_queued",
        severity=severity,
        document_id=document_id,
        detail=reason or "Queued for human review",
        detector="hitl",
        status="pending",
        item_id=item_id,
    )


def emit_hitl_resolved(
    *,
    item_id: str,
    decision: str,
    document_id: str | None = None,
    actor: str | None = None,
) -> dict[str, Any] | None:
    return emit_security_event(
        threat_type="hitl_resolved",
        severity="low",
        document_id=document_id,
        detail=f"HITL decision={decision}"
        + (f" by {actor}" if actor else ""),
        detector="hitl",
        status=decision,
        item_id=item_id,
        actor=actor,
    )


# ---------------------------------------------------------------------------
# RAG / query layer
# ---------------------------------------------------------------------------


def emit_rag_refused(
    *,
    query: str,
    reason: str | None = None,
    collection: str | None = None,
) -> dict[str, Any] | None:
    return emit_security_event(
        threat_type="rag_refused",
        severity="low",
        detail=(reason or "Insufficient evidence in approved documents")
        + f" | q={query[:160]}",
        detector="rag_service",
        status="refused",
        collection=collection,
    )


def emit_prompt_injection_blocked(
    *,
    source: str = "query",
    patterns: list[str] | None = None,
    document_id: str | None = None,
    severity: str = "high",
) -> dict[str, Any] | None:
    detail = "; ".join(patterns or []) or "Prompt injection blocked"
    return emit_security_event(
        threat_type="prompt_injection",
        severity=severity,
        document_id=document_id,
        detail=f"{source}: {detail}"[:800],
        detector="prompt_injection_detector",
        status="blocked",
    )


def emit_rate_limit_hit(
    *,
    client: str | None = None,
    path: str | None = None,
) -> dict[str, Any] | None:
    return emit_security_event(
        threat_type="rate_limit",
        severity="medium",
        detail=f"Rate limit on {path or '/'}",
        detector="middleware",
        source_ip=client or "—",
        status="throttled",
        path=path,
    )


__all__ = [
    "emit_security_event",
    "emit_file_scan_failed",
    "emit_file_scan_error",
    "emit_ingest_quarantine",
    "emit_ingest_indexed",
    "emit_ingest_failed",
    "emit_document_deleted",
    "emit_threat_scan_result",
    "emit_hitl_queued",
    "emit_hitl_resolved",
    "emit_rag_refused",
    "emit_prompt_injection_blocked",
    "emit_rate_limit_hit",
]