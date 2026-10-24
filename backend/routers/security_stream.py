"""
SSE stream of security / telemetry events.

Routes
------
  GET  /api/v1/security/events/stream   Server-Sent Events (live)
  GET  /api/v1/security/events          Recent events (JSON snapshot)
  GET  /api/v1/security/events/stats    Buffer + subscriber metrics
  POST /api/v1/security/events/publish  Manual inject (ops / tests)

Publish from scanners / ingest::

    from backend.routers.security_stream import publish_security_event
    publish_security_event({
        "threat_type": "prompt_injection",
        "severity": "high",
        "document_id": doc_id,
        "detail": "...",
        "source_ip": "—",
        "detector": "file_scanner",
    })

Env
---
  SECURITY_EVENT_BUFFER   ring size (default 200)
  SECURITY_EVENT_REPLAY   events sent on SSE connect (default 30)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/security", tags=["security"])

_MAX = max(50, int(os.getenv("SECURITY_EVENT_BUFFER", "200")))
_REPLAY = max(0, int(os.getenv("SECURITY_EVENT_REPLAY", "30")))

_events: list[dict[str, Any]] = []
_subscribers: list[asyncio.Queue[dict[str, Any]]] = []
_lock = threading.Lock()
_published_total = 0


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SecurityEventIn(BaseModel):
    threat_type: str = Field(..., min_length=1, max_length=200)
    severity: str = Field("medium", max_length=32)
    document_id: str | None = None
    detail: str | None = None
    source_ip: str | None = None
    detector: str | None = None
    confidence_score: float | None = Field(None, ge=0.0, le=1.0)
    extra: dict[str, Any] | None = None


class SecurityEventOut(BaseModel):
    id: str
    timestamp: str
    threat_type: str
    severity: str
    document_id: str | None = None
    detail: str | None = None
    source_ip: str | None = None
    detector: str | None = None
    confidence_score: float | None = None


class EventListResponse(BaseModel):
    events: list[dict[str, Any]]
    total: int
    buffer_capacity: int


class EventStatsResponse(BaseModel):
    buffered: int
    buffer_capacity: int
    subscribers: int
    published_total: int
    replay_on_connect: int


# ---------------------------------------------------------------------------
# Core buffer
# ---------------------------------------------------------------------------


def _normalize(event: dict[str, Any]) -> dict[str, Any]:
    severity = str(event.get("severity") or "medium").strip().lower()
    if severity not in ("low", "medium", "high", "critical"):
        severity = "medium"
    row: dict[str, Any] = {
        "id": event.get("id") or f"EVT-{int(time.time() * 1000)}",
        "timestamp": event.get("timestamp")
        or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "threat_type": str(
            event.get("threat_type") or event.get("type") or "event"
        ),
        "severity": severity,
        "document_id": event.get("document_id"),
        "detail": event.get("detail") or event.get("message"),
        "source_ip": event.get("source_ip") or "—",
        "detector": event.get("detector"),
        "confidence_score": event.get("confidence_score"),
    }
    # Preserve unknown keys for forward compatibility
    for k, v in event.items():
        if k not in row and k != "extra":
            row[k] = v
    if isinstance(event.get("extra"), dict):
        row.update(event["extra"])
    return row


def publish_security_event(event: dict[str, Any]) -> dict[str, Any]:
    """
    Append to ring buffer and fan-out to SSE subscribers.
    Safe to call from sync code (ingest, scanners).
    """
    global _published_total
    row = _normalize(event)
    with _lock:
        _events.append(row)
        if len(_events) > _MAX:
            del _events[: len(_events) - _MAX]
        _published_total += 1
        subs = list(_subscribers)

    dead: list[asyncio.Queue[dict[str, Any]]] = []
    for q in subs:
        try:
            q.put_nowait(row)
        except asyncio.QueueFull:
            dead.append(q)
        except Exception as exp:
            logger.debug("subscriber drop: %s", exp)
            dead.append(q)

    if dead:
        with _lock:
            for q in dead:
                if q in _subscribers:
                    _subscribers.remove(q)

    logger.debug(
        "security event id=%s severity=%s type=%s",
        row.get("id"),
        row.get("severity"),
        row.get("threat_type"),
    )
    return row


def list_events(
    *,
    limit: int = 50,
    severity: str | None = None,
    threat_type: str | None = None,
) -> list[dict[str, Any]]:
    with _lock:
        rows = list(_events)
    if severity:
        sev = severity.strip().lower()
        rows = [r for r in rows if str(r.get("severity", "")).lower() == sev]
    if threat_type:
        tt = threat_type.strip().lower()
        rows = [
            r
            for r in rows
            if tt in str(r.get("threat_type", "")).lower()
        ]
    # newest first
    rows = list(reversed(rows))
    return rows[: max(1, min(limit, _MAX))]


def get_buffer_stats() -> dict[str, int]:
    with _lock:
        return {
            "buffered": len(_events),
            "buffer_capacity": _MAX,
            "subscribers": len(_subscribers),
            "published_total": _published_total,
            "replay_on_connect": _REPLAY,
        }


def clear_events() -> int:
    """Test helper — clear ring buffer."""
    with _lock:
        n = len(_events)
        _events.clear()
        return n


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/events/stream",
    summary="SSE: live security events",
    response_class=StreamingResponse,
)
async def security_events_stream(
    request: Request,
    severity: str | None = Query(
        None, description="Optional filter: low|medium|high|critical"
    ),
):
    """
    Server-Sent Events stream.

    - On connect: replays last N buffered events (newest among buffer order)
    - Then pushes new events as they are published
    - Keepalive comments every ~25s
    """
    sev_filter = severity.strip().lower() if severity else None

    async def gen():
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50)
        with _lock:
            _subscribers.append(q)
            snapshot = list(_events[-_REPLAY:]) if _REPLAY else []

        try:
            for ev in snapshot:
                if sev_filter and str(ev.get("severity", "")).lower() != sev_filter:
                    continue
                yield f"data: {json.dumps(ev, default=str)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=25.0)
                    if sev_filter and str(ev.get("severity", "")).lower() != sev_filter:
                        continue
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            with _lock:
                if q in _subscribers:
                    _subscribers.remove(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/events",
    response_model=EventListResponse,
    summary="Recent security events (snapshot)",
)
async def get_security_events(
    limit: int = Query(50, ge=1, le=200),
    severity: str | None = Query(None),
    threat_type: str | None = Query(None),
) -> EventListResponse:
    rows = list_events(limit=limit, severity=severity, threat_type=threat_type)
    return EventListResponse(
        events=rows,
        total=len(rows),
        buffer_capacity=_MAX,
    )


@router.get(
    "/events/stats",
    response_model=EventStatsResponse,
    summary="Event buffer and subscriber stats",
)
async def security_events_stats() -> EventStatsResponse:
    s = get_buffer_stats()
    return EventStatsResponse(**s)


@router.post(
    "/events/publish",
    summary="Publish a security event (ops / integration tests)",
    status_code=status.HTTP_201_CREATED,
)
async def publish_event_http(body: SecurityEventIn) -> dict[str, Any]:
    """
    Manual publish endpoint. Protect with admin auth in production
    by adding Depends(require_admin) when RBAC is enabled.
    """
    payload = body.model_dump(exclude_none=True)
    extra = payload.pop("extra", None)
    if extra:
        payload.update(extra)
    row = publish_security_event(payload)
    return {"status": "published", "event": row}


@router.delete(
    "/events",
    summary="Clear in-memory event buffer (dev/test)",
    include_in_schema=False,
)
async def clear_security_events() -> dict[str, Any]:
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Buffer clear disabled in production",
        )
    n = clear_events()
    return {"status": "cleared", "removed": n}