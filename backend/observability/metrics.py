"""
Prometheus metrics for the RAG / document intelligence pipeline.

Dependency:
  pip install prometheus-client

Expose (health router or main.py):

    from fastapi.responses import Response
    from backend.observability.metrics import metrics_payload

    @app.get("/metrics")
    async def metrics() -> Response:
        body, ctype = metrics_payload()
        return Response(body, media_type=ctype)

Env
---
  PROMETHEUS_METRICS=true|false   (default true)
  PROMETHEUS_MULTIPROC_DIR        optional gunicorn multiprocess dir
  PROMETHEUS_PUSHGATEWAY_URL      optional Pushgateway base URL
  PROMETHEUS_PUSH_JOB             default doc-intelligence-api
  PROMETHEUS_PUSH_INSTANCE        instance label (else RENDER_SERVICE_NAME / HOSTNAME)

Grafana examples:
  p95 E2E : histogram_quantile(0.95, rate(rag_e2e_latency_seconds_bucket[5m]))
  p50 E2E : histogram_quantile(0.50, rate(rag_e2e_latency_seconds_bucket[5m]))
  p95 by stage: histogram_quantile(0.95,
      sum by (stage, le) (rate(rag_stage_latency_seconds_bucket[5m])))
  $/request : rate(rag_cost_dollars_total[5m])
              / rate(rag_e2e_latency_seconds_count[5m])
  security  : rate(security_events_total[5m])
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_ENABLED = os.getenv("PROMETHEUS_METRICS", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROM_OK = True
except ImportError:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    REGISTRY = None  # type: ignore[assignment]
    CollectorRegistry = None  # type: ignore[misc, assignment]
    _PROM_OK = False
    Counter = Histogram = Gauge = None  # type: ignore[misc, assignment]
    generate_latest = None  # type: ignore[assignment]
    logger.warning(
        "prometheus_client not installed — RAG metrics are no-ops. "
        "pip install prometheus-client"
    )


def _hist(
    name: str,
    doc: str,
    labels: list[str] | None = None,
    buckets: list[float] | None = None,
):
    if not (_ENABLED and _PROM_OK):
        return None
    kwargs: dict[str, Any] = {}
    if buckets is not None:
        kwargs["buckets"] = buckets
    try:
        if labels:
            return Histogram(name, doc, labels, **kwargs)
        return Histogram(name, doc, **kwargs)
    except ValueError:
        return None


def _counter(name: str, doc: str, labels: list[str] | None = None):
    if not (_ENABLED and _PROM_OK):
        return None
    try:
        if labels:
            return Counter(name, doc, labels)
        return Counter(name, doc)
    except ValueError:
        return None


def _gauge(name: str, doc: str, labels: list[str] | None = None):
    if not (_ENABLED and _PROM_OK):
        return None
    try:
        if labels:
            return Gauge(name, doc, labels)
        return Gauge(name, doc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Core RAG metrics
# ---------------------------------------------------------------------------

E2E_LATENCY = _hist(
    "rag_e2e_latency_seconds",
    "End-to-end RAG query latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0],
)

STAGE_LATENCY = _hist(
    "rag_stage_latency_seconds",
    "Per-stage latency",
    ["stage"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0],
)

TOKENS = _counter(
    "rag_tokens_total",
    "Tokens consumed",
    ["model", "direction"],
)

COST = _counter(
    "rag_cost_dollars_total",
    "Estimated LLM/embedding spend (USD)",
    ["model"],
)

CONFIDENCE = _hist(
    "rag_confidence_score",
    "Confidence score returned to clients",
    buckets=[0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 0.95, 1.0],
)

RETRIEVED = _hist(
    "rag_retrieved_chunks",
    "Chunks retrieved per query",
    buckets=[0, 1, 2, 3, 5, 8, 13, 20],
)

SYNTHESIS_PATH = _counter(
    "rag_synthesis_path_total",
    "Which synthesis path produced the answer",
    ["path"],
)

RAG_REFUSED = _counter(
    "rag_refused_total",
    "RAG queries refused (insufficient evidence / policy)",
    ["reason"],
)

# ---------------------------------------------------------------------------
# HTTP / ingest / infra
# ---------------------------------------------------------------------------

HTTP_REQUESTS = _counter(
    "http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)

HTTP_LATENCY = _hist(
    "http_request_latency_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

INGEST_DOCS = _counter(
    "ingest_documents_total",
    "Document ingest outcomes",
    ["status"],
)

INGEST_CHUNKS = _counter(
    "ingest_chunks_total",
    "Chunks upserted to Qdrant",
)

QDRANT_UP = _gauge(
    "qdrant_up",
    "Qdrant reachability (1=up, 0=down)",
)

APP_UP = _gauge(
    "app_up",
    "API process up (1=up)",
)
if APP_UP is not None:
    APP_UP.set(1)

ERRORS = _counter(
    "app_errors_total",
    "Application errors by component",
    ["component"],
)

# ---------------------------------------------------------------------------
# Security / HITL / ops
# ---------------------------------------------------------------------------

SECURITY_EVENTS = _counter(
    "security_events_total",
    "Security events published to the stream",
    ["threat_type", "severity"],
)

HITL_TRIGGERS_TOTAL = _counter(
    "hitl_triggers_total",
    "Total Human-in-the-Loop review triggers by category",
    ["category"],
)

HITL_QUEUE_DEPTH = _gauge(
    "hitl_queue_depth",
    "Pending HITL items",
    ["status"],
)

OPS_RATE_LIMIT_HITS = _counter(
    "ops_rate_limit_hits_total",
    "Ops/health router rate-limit rejections",
)

CONTENT_TYPE = CONTENT_TYPE_LATEST


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm_path(path: str) -> str:
    norm = re.sub(r"/[a-f0-9-]{32,36}", "/{id}", path or "")
    norm = re.sub(r"/\d+", "/{id}", norm)
    if len(norm) > 120:
        norm = norm[:120]
    return norm or "/"


def observe_e2e(seconds: float) -> None:
    if E2E_LATENCY is not None:
        E2E_LATENCY.observe(max(0.0, float(seconds)))


def observe_stage(stage: str, seconds: float) -> None:
    if STAGE_LATENCY is not None:
        STAGE_LATENCY.labels(stage=stage).observe(max(0.0, float(seconds)))


@contextmanager
def time_stage(stage: str) -> Iterator[None]:
    t0 = time.perf_counter()
    try:
        yield
    finally:
        observe_stage(stage, time.perf_counter() - t0)


@contextmanager
def time_e2e() -> Iterator[None]:
    t0 = time.perf_counter()
    try:
        yield
    finally:
        observe_e2e(time.perf_counter() - t0)


def record_tokens(model: str, direction: str, n: int) -> None:
    if TOKENS is not None and n:
        TOKENS.labels(model=model or "unknown", direction=direction).inc(int(n))


def record_cost(model: str, usd: float) -> None:
    if COST is not None and usd:
        COST.labels(model=model or "unknown").inc(float(usd))

RAG_REQUESTS = _counter(
    "rag_requests_total",
    "Total OpenAI/RAG requests",
    ["model"],
)

RAG_FAILURES = _counter(
    "rag_failures_total",
    "RAG/OpenAI failures",
    ["model", "reason"],
)

RAG_REQUEST_DURATION = _hist(
    "rag_request_duration_seconds",
    "LLM request duration",
    ["model"],
    buckets=[
        0.1,
        0.25,
        0.5,
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        32.0,
    ],
)

RAG_STREAM_REQUESTS = _counter(
    "rag_stream_requests_total",
    "Streaming chat requests",
    ["model"],
)

RAG_EMBEDDING_REQUESTS = _counter(
    "rag_embedding_requests_total",
    "Embedding generation requests",
    ["model"],
)

RAG_RETRIES = _counter(
    "rag_retries_total",
    "Automatic retry attempts",
    ["operation"],
)

RAG_HEALTH_CHECKS = _counter(
    "rag_health_checks_total",
    "OpenAI health checks",
    ["status"],
)

RAG_LOW_CONFIDENCE = _counter(
    "rag_low_confidence_answers_total",
    "Responses below confidence threshold",
)

RAG_RETRIEVAL_FAILURES = _counter(
    "rag_retrieval_failures_total",
    "Retrieval failures",
)

AUTH_FAILURES = _counter(
    "auth_failures_total",
    "Authentication failures",
)   

def record_rag_request(
    model: str,
) -> None:

    if RAG_REQUESTS is not None:
        RAG_REQUESTS.labels(
            model=model or "unknown"
        ).inc()


def record_rag_stream_request(
    model: str,
) -> None:

    if RAG_STREAM_REQUESTS is not None:
        RAG_STREAM_REQUESTS.labels(
            model=model or "unknown"
        ).inc()


def record_embedding_request(
    model: str,
) -> None:

    if RAG_EMBEDDING_REQUESTS is not None:
        RAG_EMBEDDING_REQUESTS.labels(
            model=model or "unknown"
        ).inc()


def record_retry(
    operation: str,
) -> None:

    if RAG_RETRIES is not None:
        RAG_RETRIES.labels(
            operation=operation
        ).inc()


def record_rag_failure(
    model: str,
    reason: str,
) -> None:

    if RAG_FAILURES is not None:

        RAG_FAILURES.labels(
            model=model or "unknown",
            reason=(reason or "error")[:64],
        ).inc()


def record_request_duration(
    model: str,
    seconds: float,
) -> None:

    if RAG_REQUEST_DURATION is not None:

        RAG_REQUEST_DURATION.labels(
            model=model or "unknown"
        ).observe(
            max(0.0, float(seconds))
        )


def record_health_check(
    status: str,
) -> None:

    if RAG_HEALTH_CHECKS is not None:

        RAG_HEALTH_CHECKS.labels(
            status=status
        ).inc()


def record_low_confidence() -> None:

    if RAG_LOW_CONFIDENCE is not None:
        RAG_LOW_CONFIDENCE.inc()


def record_retrieval_failure() -> None:

    if RAG_RETRIEVAL_FAILURES is not None:
        RAG_RETRIEVAL_FAILURES.inc()


def record_auth_failure() -> None:

    if AUTH_FAILURES is not None:
        AUTH_FAILURES.inc()

def record_confidence(score: float | None) -> None:
    if CONFIDENCE is not None and score is not None:
        CONFIDENCE.observe(max(0.0, min(1.0, float(score))))


def record_retrieved(n: int) -> None:
    if RETRIEVED is not None:
        RETRIEVED.observe(max(0, int(n)))


def record_synthesis_path(path: str) -> None:
    if SYNTHESIS_PATH is not None:
        SYNTHESIS_PATH.labels(path=path or "unknown").inc()


def record_rag_refused(reason: str = "insufficient_evidence") -> None:
    if RAG_REFUSED is not None:
        RAG_REFUSED.labels(reason=(reason or "unknown")[:64]).inc()


def record_http(method: str, path: str, status: int, seconds: float) -> None:
    norm = _norm_path(path)
    if HTTP_REQUESTS is not None:
        HTTP_REQUESTS.labels(
            method=(method or "GET").upper(),
            path=norm,
            status=str(status),
        ).inc()
    if HTTP_LATENCY is not None:
        HTTP_LATENCY.labels(
            method=(method or "GET").upper(),
            path=norm,
        ).observe(max(0.0, float(seconds)))


def record_ingest(status: str, chunks: int = 0) -> None:
    if INGEST_DOCS is not None:
        INGEST_DOCS.labels(status=status or "unknown").inc()
    if INGEST_CHUNKS is not None and chunks:
        INGEST_CHUNKS.inc(int(chunks))


def set_qdrant_up(ok: bool) -> None:
    if QDRANT_UP is not None:
        QDRANT_UP.set(1 if ok else 0)


def record_error(component: str) -> None:
    if ERRORS is not None:
        ERRORS.labels(component=component or "unknown").inc()


def record_hitl_trigger(category: str) -> None:
    if HITL_TRIGGERS_TOTAL is not None:
        HITL_TRIGGERS_TOTAL.labels(category=category or "unknown").inc()


def set_hitl_queue_depth(status: str, depth: int) -> None:
    if HITL_QUEUE_DEPTH is not None:
        HITL_QUEUE_DEPTH.labels(status=status or "pending").set(max(0, int(depth)))


def record_security_event(threat_type: str, severity: str) -> None:
    if SECURITY_EVENTS is not None:
        SECURITY_EVENTS.labels(
            threat_type=(threat_type or "event")[:64],
            severity=(severity or "medium")[:16],
        ).inc()


def record_ops_rate_limit_hit() -> None:
    if OPS_RATE_LIMIT_HITS is not None:
        OPS_RATE_LIMIT_HITS.inc()


def record_rag_turn(
    *,
    e2e_seconds: float | None = None,
    retrieved: int | None = None,
    confidence: float | None = None,
    synthesis_path: str | None = None,
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    embed_tokens: int = 0,
    cost_usd: float = 0.0,
    refused: bool = False,
    refuse_reason: str = "insufficient_evidence",
) -> None:
    if e2e_seconds is not None:
        observe_e2e(e2e_seconds)
    if retrieved is not None:
        record_retrieved(retrieved)
    if confidence is not None:
        record_confidence(confidence)
    if refused:
        record_rag_refused(refuse_reason)
        record_synthesis_path(synthesis_path or "refused")
    elif synthesis_path:
        record_synthesis_path(synthesis_path)
    if model:
        record_tokens(model, "prompt", prompt_tokens)
        record_tokens(model, "completion", completion_tokens)
        if embed_tokens:
            record_tokens(model, "embedding", embed_tokens)
        if cost_usd:
            record_cost(model, cost_usd)


def metrics_payload() -> tuple[bytes, str]:
    if not (_ENABLED and _PROM_OK and generate_latest is not None):
        return (
            b"# prometheus_client unavailable or disabled\n",
            "text/plain; charset=utf-8",
        )

    multiproc = os.getenv("PROMETHEUS_MULTIPROC_DIR")
    if multiproc and CollectorRegistry is not None:
        try:
            from prometheus_client import multiprocess

            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            return generate_latest(registry), CONTENT_TYPE_LATEST
        except Exception as exc:
            logger.debug("multiprocess metrics failed: %s", exc)

    return generate_latest(), CONTENT_TYPE_LATEST


def metrics_enabled() -> bool:
    return bool(_ENABLED and _PROM_OK)


# ---------------------------------------------------------------------------
# Pushgateway (optional)
# ---------------------------------------------------------------------------


def _resolve_instance(explicit: str | None = None) -> str | None:
    """instance arg > PROMETHEUS_PUSH_INSTANCE > RENDER_SERVICE_NAME > HOSTNAME."""
    for candidate in (
        explicit,
        os.getenv("PROMETHEUS_PUSH_INSTANCE"),
        os.getenv("RENDER_SERVICE_NAME"),
        os.getenv("HOSTNAME"),
    ):
        if candidate and str(candidate).strip():
            return str(candidate).strip()[:128]
    return None


def push_metrics(
    *,
    gateway: str | None = None,
    job: str | None = None,
    instance: str | None = None,
    grouping: dict[str, str] | None = None,
) -> bool:
    """
    Push current default registry to Prometheus Pushgateway.

    Env (when args omitted):
      PROMETHEUS_PUSHGATEWAY_URL
      PROMETHEUS_PUSH_JOB          default: doc-intelligence-api
      PROMETHEUS_PUSH_INSTANCE     else RENDER_SERVICE_NAME / HOSTNAME

    Grouping always includes ``instance`` when resolved so replicas
    do not overwrite each other on the gateway.
    """
    try:
        if not metrics_enabled():
            return False

        url = (gateway or os.getenv("PROMETHEUS_PUSHGATEWAY_URL") or "").rstrip("/")
        if not url:
            return False

        job_name = job or os.getenv("PROMETHEUS_PUSH_JOB", "doc-intelligence-api")
        grouping_key: dict[str, str] = dict(grouping or {})
        inst = _resolve_instance(instance)
        if inst and "instance" not in grouping_key:
            grouping_key["instance"] = inst

        from prometheus_client import REGISTRY as _REG
        from prometheus_client import push_to_gateway

        push_to_gateway(
            url,
            job=job_name,
            registry=_REG,
            grouping_key=grouping_key or None,
        )
        logger.debug(
            "Pushed metrics to %s job=%s grouping=%s",
            url,
            job_name,
            grouping_key or {},
        )
        return True
    except Exception as exc:
        logger.warning("Pushgateway push failed: %s", exc)
        try:
            record_error("pushgateway")
        except Exception:
            pass
        return False


def push_metrics_enabled() -> bool:
    """True when Prometheus is on and a Pushgateway URL is configured."""
    try:
        if not metrics_enabled():
            return False
        return bool((os.getenv("PROMETHEUS_PUSHGATEWAY_URL") or "").strip())
    except Exception:
        return False


__all__ = [
    "E2E_LATENCY",
    "STAGE_LATENCY",
    "TOKENS",
    "COST",
    "CONFIDENCE",
    "RETRIEVED",
    "SYNTHESIS_PATH",
    "RAG_REFUSED",
    "HTTP_REQUESTS",
    "HTTP_LATENCY",
    "INGEST_DOCS",
    "INGEST_CHUNKS",
    "QDRANT_UP",
    "APP_UP",
    "ERRORS",
    "SECURITY_EVENTS",
    "HITL_TRIGGERS_TOTAL",
    "HITL_QUEUE_DEPTH",
    "OPS_RATE_LIMIT_HITS",
    "CONTENT_TYPE",
    "observe_e2e",
    "observe_stage",
    "time_stage",
    "time_e2e",
    "record_tokens",
    "record_cost",
    "record_confidence",
    "record_retrieved",
    "record_synthesis_path",
    "record_rag_refused",
    "record_http",
    "record_ingest",
    "set_qdrant_up",
    "record_error",
    "record_hitl_trigger",
    "set_hitl_queue_depth",
    "record_security_event",
    "record_ops_rate_limit_hit",
    "record_rag_turn",
    "metrics_payload",
    "metrics_enabled",
    "push_metrics",
    "push_metrics_enabled",
]