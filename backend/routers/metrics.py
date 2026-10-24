"""
GET /metrics — Prometheus scrape endpoint.

Uses backend.observability.metrics.metrics_payload() so all RAG / HTTP /
security / HITL series are registered on the default registry.

Env
---
  PROMETHEUS_METRICS          true|false (honored inside metrics_payload)
  METRICS_REQUIRE_TOKEN       if set, require Authorization: Bearer <token>
  METRICS_SCRAPE_TOKEN        shared scrape secret (optional)
  METRICS_RATE_LIMIT          max scrapes per client per window (0 = off)
  METRICS_RATE_WINDOW_SEC     window seconds (default 60)

Mount once in main.py::

    from backend.routers.metrics import router as metrics_router
    app.include_router(metrics_router)

Do not also define /metrics on health.py or main.py.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ops"])

_REQUIRE_TOKEN = os.getenv("METRICS_REQUIRE_TOKEN", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_SCRAPE_TOKEN = os.getenv("METRICS_SCRAPE_TOKEN") or os.getenv("ADMIN_API_KEY") or ""
_RATE_LIMIT = max(0, int(os.getenv("METRICS_RATE_LIMIT", "0")))
_RATE_WINDOW = max(5, int(os.getenv("METRICS_RATE_WINDOW_SEC", "60")))

_rate_buckets: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = Lock()


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _check_rate_limit(request: Request) -> None:
    if _RATE_LIMIT <= 0:
        return
    key = _client_key(request)
    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets[key]
        while bucket and (now - bucket[0]) > _RATE_WINDOW:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT:
            try:
                from backend.observability.metrics import record_ops_rate_limit_hit

                record_ops_rate_limit_hit()
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Metrics scrape rate limit exceeded",
                headers={"Retry-After": str(_RATE_WINDOW)},
            )
        bucket.append(now)


def _check_token(authorization: str | None) -> None:
    if not _REQUIRE_TOKEN:
        return
    if not _SCRAPE_TOKEN:
        logger.warning(
            "METRICS_REQUIRE_TOKEN is set but METRICS_SCRAPE_TOKEN/ADMIN_API_KEY is empty"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics token not configured",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if token != _SCRAPE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid metrics scrape token",
        )


def _build_metrics_response() -> Response:
    from backend.observability.metrics import metrics_enabled, metrics_payload

    body, ctype = metrics_payload()
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "X-Metrics-Enabled": "true" if metrics_enabled() else "false",
    }
    return Response(content=body, media_type=ctype, headers=headers)


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    response_class=Response,
)
async def prometheus_metrics(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    """
    Prometheus text exposition format.

    - Soft-fails to a comment body if prometheus_client is missing
    - Optional Bearer token via METRICS_REQUIRE_TOKEN
    - Optional per-IP rate limit via METRICS_RATE_LIMIT
    """
    _check_token(authorization)
    _check_rate_limit(request)

    try:
        return _build_metrics_response()
    except Exception as exc:
        logger.warning("prometheus metrics unavailable: %s", exc)
        return Response(
            content=b"# prometheus_client not installed or metrics module failed\n",
            media_type="text/plain; charset=utf-8",
            status_code=200,
            headers={"X-Metrics-Enabled": "false"},
        )


@router.head(
    "/metrics",
    summary="Prometheus metrics (HEAD)",
    include_in_schema=False,
)
async def prometheus_metrics_head(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    """HEAD for scrape probes that only check reachability."""
    _check_token(authorization)
    _check_rate_limit(request)
    try:
        from backend.observability.metrics import metrics_enabled

        enabled = metrics_enabled()
    except Exception:
        enabled = False
    return Response(
        status_code=200,
        headers={
            "Cache-Control": "no-store",
            "X-Metrics-Enabled": "true" if enabled else "false",
        },
    )


@router.get(
    "/metrics/status",
    summary="Metrics subsystem status (JSON)",
    include_in_schema=False,
)
async def metrics_status(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Lightweight JSON for ops dashboards (not Prometheus format)."""
    _check_token(authorization)
    try:
        from backend.observability.metrics import metrics_enabled

        enabled = metrics_enabled()
    except Exception as exc:
        return {
            "enabled": False,
            "error": str(exc)[:200],
            "token_required": _REQUIRE_TOKEN,
        }
    return {
        "enabled": enabled,
        "token_required": _REQUIRE_TOKEN,
        "rate_limit": _RATE_LIMIT or None,
        "rate_window_sec": _RATE_WINDOW if _RATE_LIMIT else None,
        "path": "/metrics",
    }


__all__ = ["router"]