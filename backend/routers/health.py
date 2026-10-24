"""
Ops probes: liveness, readiness, Prometheus metrics, and light rate limiting.

Routes
------
  GET /
  GET /health
  GET /ready
  GET /metrics

Env
---
  API_VERSION, SERVICE_NAME, ENVIRONMENT
  OPS_RATE_LIMIT          max requests per window per client (default 120)
  OPS_RATE_WINDOW_SEC     window seconds (default 60)
  OPS_RATE_LIMIT_ENABLED  true/false (default true)

Mount::

    from backend.routers.health import (
        router as health_router,
        set_feature_flags,
        record_request,
    )
    app.include_router(health_router)
    set_feature_flags(_features)  # after other routers mount
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ops"])

API_VERSION = os.getenv("API_VERSION", "1.5.0")
SERVICE_NAME = os.getenv("SERVICE_NAME", "doc-intelligence-api")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
APP_STARTED_AT = time.monotonic()

# --- in-process counters ---
_total_requests = 0
_request_counts: dict[str, int] = defaultdict(int)
_features: dict[str, bool] = {}

# --- rate limit (ops routes only) ---
_RATE_ENABLED = os.getenv("OPS_RATE_LIMIT_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_RATE_LIMIT = max(10, int(os.getenv("OPS_RATE_LIMIT", "120")))
_RATE_WINDOW = max(5, int(os.getenv("OPS_RATE_WINDOW_SEC", "60")))
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = Lock()
_rate_hits_total = 0


def set_feature_flags(flags: dict[str, bool]) -> None:
    global _features
    _features = dict(flags)


def record_request(path: str) -> None:
    global _total_requests
    _total_requests += 1
    p = (path or "/").split("?", 1)[0]
    if len(p) > 120:
        p = p[:120]
    _request_counts[p] += 1


def get_uptime_seconds() -> float:
    return round(time.monotonic() - APP_STARTED_AT, 1)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


def check_ops_rate_limit(request: Request) -> None:
    """Sliding-window limiter for this router. Raises HTTP 429 when exceeded."""
    global _rate_hits_total
    if not _RATE_ENABLED:
        return

    key = _client_key(request)
    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets[key]
        while bucket and (now - bucket[0]) > _RATE_WINDOW:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT:
            _rate_hits_total += 1
            try:
                from backend.security.event_publish import emit_rate_limit_hit

                emit_rate_limit_hit(client=key, path=request.url.path)
            except Exception:
                pass
            try:
                from backend.observability.metrics import record_ops_rate_limit_hit

                record_ops_rate_limit_hit()
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "limit": _RATE_LIMIT,
                    "window_sec": _RATE_WINDOW,
                },
                headers={"Retry-After": str(_RATE_WINDOW)},
            )
        bucket.append(now)


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _psutil_stats() -> dict[str, Any]:
    out: dict[str, Any] = {
        "memory_usage_mb": None,
        "cpu_percent": None,
        "threads": None,
    }
    try:
        import psutil

        proc = psutil.Process()
        out["memory_usage_mb"] = round(proc.memory_info().rss / (1024 * 1024), 2)
        out["cpu_percent"] = psutil.cpu_percent(interval=0.0)
        out["threads"] = proc.num_threads()
    except Exception:
        pass
    return out


async def _qdrant_probe() -> dict[str, Any]:
    t0 = time.perf_counter()
    result: dict[str, Any] = {
        "ok": False,
        "collection_ready": False,
        "latency_ms": None,
        "stats": None,
        "error": None,
    }
    try:
        from backend.db.qdrant import get_collection_stats, get_qdrant_client

        await get_qdrant_client()
        stats = await get_collection_stats()
        result["ok"] = True
        result["collection_ready"] = bool(stats)
        result["stats"] = stats if isinstance(stats, dict) else {"raw": str(stats)}
    except Exception as exc:
        result["error"] = str(exc)[:300]
        if _features.get("qdrant"):
            result["ok"] = True
            result["collection_ready"] = True
            result["error"] = f"live probe failed; startup flag ok ({exc})"[:300]
    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return result


def _openai_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _feature(name: str) -> bool:
    return bool(_features.get(name, False))


def _pushgateway_status() -> dict[str, Any]:
    try:
        from backend.observability.push_loop import get_push_loop_status

        return get_push_loop_status()
    except Exception:
        return {
            "enabled": bool((os.getenv("PROMETHEUS_PUSHGATEWAY_URL") or "").strip()),
            "running": False,
        }


def _sync_qdrant_gauge(ok: bool) -> None:
    try:
        from backend.observability.metrics import set_qdrant_up

        set_qdrant_up(bool(ok))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", summary="API root", include_in_schema=False)
async def root(request: Request) -> dict[str, Any]:
    check_ops_rate_limit(request)
    return {
        "name": "Document Intelligence & Security API",
        "service": SERVICE_NAME,
        "version": API_VERSION,
        "environment": ENVIRONMENT,
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready",
        "metrics": "/metrics",
    }


@router.get("/health", summary="Liveness + dependency snapshot")
async def health(request: Request) -> dict[str, Any]:
    check_ops_rate_limit(request)
    proc = _psutil_stats()
    qdrant = await _qdrant_probe()
    _sync_qdrant_gauge(bool(qdrant["ok"]))

    status_str = "ok"
    if not qdrant["ok"] or not qdrant["collection_ready"]:
        status_str = "degraded"

    return {
        "status": status_str,
        "service": SERVICE_NAME,
        "version": API_VERSION,
        "environment": ENVIRONMENT,
        "uptime_seconds": get_uptime_seconds(),
        "total_requests": _total_requests,
        "memory_usage_mb": proc["memory_usage_mb"],
        "cpu_percent": proc["cpu_percent"],
        "threads": proc["threads"],
        "qdrant_ok": qdrant["ok"],
        "collection_ready": qdrant["collection_ready"],
        "qdrant_latency_ms": qdrant["latency_ms"],
        "collection": (qdrant.get("stats") or {}).get("collection_name"),
        "points_count": (qdrant.get("stats") or {}).get("points_count"),
        "vectors_count": (qdrant.get("stats") or {}).get("vectors_count"),
        "openai_configured": _openai_configured(),
        "rate_limit": {
            "enabled": _RATE_ENABLED,
            "limit": _RATE_LIMIT,
            "window_sec": _RATE_WINDOW,
            "hits_total": _rate_hits_total,
        },
        "pushgateway": _pushgateway_status(),
        "features": dict(_features),
    }


@router.get("/ready", summary="Readiness: can serve traffic")
async def ready(request: Request) -> dict[str, Any]:
    check_ops_rate_limit(request)
    qdrant = await _qdrant_probe()
    _sync_qdrant_gauge(bool(qdrant["ok"]))

    details: dict[str, Any] = {
        "qdrant": "ok" if qdrant["ok"] else "unavailable",
        "collection": "ok" if qdrant["collection_ready"] else "unavailable",
        "qdrant_latency_ms": qdrant["latency_ms"],
        "openai": "configured" if _openai_configured() else "missing_key",
        "llm_factory": "ok" if _feature("llm_factory") else "unavailable",
        "documents_router": "ok" if _feature("documents") else "unavailable",
        "ingestion_pipeline": (
            "ok"
            if _feature("ingestion") or _feature("documents")
            else "unavailable"
        ),
        "rag_router": "ok" if _feature("rag") else "unavailable",
        "security_stream": "ok" if _feature("security_stream") else "unavailable",
        "auth": "ok" if _feature("auth") else "unavailable",
        "admin": "ok" if _feature("admin") else "unavailable",
        "hitl": "ok" if _feature("hitl") else "unavailable",
        "intelligence": "ok" if _feature("intelligence") else "unavailable",
        "pushgateway": _pushgateway_status(),
    }
    if qdrant.get("error") and not qdrant["ok"]:
        details["qdrant_error"] = qdrant["error"]

    pipeline_ready = bool(
        _feature("documents") or _feature("ingestion") or _feature("rag")
    )
    if not qdrant["ok"]:
        overall = "not_ready" if ENVIRONMENT == "production" else "degraded"
    elif not pipeline_ready and ENVIRONMENT == "production":
        overall = "degraded"
    else:
        overall = "ok"

    return {
        "status": overall,
        "validators_ready": True,
        "pipeline_ready": pipeline_ready,
        "qdrant_ready": qdrant["ok"],
        "collection_ready": qdrant["collection_ready"],
        "uptime_seconds": get_uptime_seconds(),
        "version": API_VERSION,
        "details": details,
    }


@router.get("/metrics", summary="Prometheus metrics")
async def metrics(request: Request) -> Response:
    """
    Prometheus scrape via observability.metrics.metrics_payload().
    Rate-limited like other ops routes (raise OPS_RATE_LIMIT for scrapers).
    """
    check_ops_rate_limit(request)

    try:
        from backend.observability.metrics import metrics_enabled, metrics_payload

        body, ctype = metrics_payload()
        return Response(
            content=body,
            media_type=ctype,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "X-Metrics-Enabled": "true" if metrics_enabled() else "false",
            },
        )
    except Exception as exc:
        logger.debug("metrics_payload unavailable: %s", exc)

    lines = [
        "# HELP app_up API process up",
        "# TYPE app_up gauge",
        "app_up 1",
        "# HELP app_uptime_seconds Process uptime",
        "# TYPE app_uptime_seconds gauge",
        f"app_uptime_seconds {get_uptime_seconds()}",
        "# HELP app_requests_total Total HTTP requests (in-process)",
        "# TYPE app_requests_total counter",
        f"app_requests_total {_total_requests}",
        "# HELP ops_rate_limit_hits_total Ops rate limit rejections",
        "# TYPE ops_rate_limit_hits_total counter",
        f"ops_rate_limit_hits_total {_rate_hits_total}",
        "# HELP ops_rate_limit_max Configured ops rate limit",
        "# TYPE ops_rate_limit_max gauge",
        f"ops_rate_limit_max {_RATE_LIMIT}",
    ]
    for path, count in list(_request_counts.items())[:80]:
        safe = path.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'app_path_requests_total{{path="{safe}"}} {count}')
    body = "\n".join(lines) + "\n"
    return PlainTextResponse(
        body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
        headers={"X-Metrics-Enabled": "false"},
    )


__all__ = [
    "router",
    "set_feature_flags",
    "record_request",
    "check_ops_rate_limit",
    "get_uptime_seconds",
    "APP_STARTED_AT",
    "API_VERSION",
]