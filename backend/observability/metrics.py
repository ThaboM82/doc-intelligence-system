"""
Prometheus metrics for the RAG / document intelligence pipeline.

Dependency:
  pip install prometheus-client

Expose in main.py (preferred — real Prometheus format):

    from fastapi.responses import Response
    from backend.observability.metrics import metrics_payload, CONTENT_TYPE

    @app.get("/metrics")
    async def metrics() -> Response:
        body, ctype = metrics_payload()
        return Response(body, media_type=ctype)

Grafana examples:
  p95 E2E : histogram_quantile(0.95, rate(rag_e2e_latency_seconds_bucket[5m]))
  p50 E2E : histogram_quantile(0.50, rate(rag_e2e_latency_seconds_bucket[5m]))
  p95 by stage: histogram_quantile(0.95,
      sum by (stage, le) (rate(rag_stage_latency_seconds_bucket[5m])))
  $/request : rate(rag_cost_dollars_total[5m])
              / rate(rag_e2e_latency_seconds_count[5m])
"""

from __future__ import annotations

import logging
import os
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
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
    _PROM_OK = True
except ImportError:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    _PROM_OK = False
    Counter = Histogram = Gauge = None  # type: ignore[misc, assignment]
    generate_latest = None  # type: ignore[assignment]
    logger.warning(
        "prometheus_client not installed — RAG metrics are no-ops. "
        "pip install prometheus-client"
    )


def _hist(name: str, doc: str, labels: list[str] | None = None, buckets=None):
    if not (_ENABLED and _PROM_OK):
        return None
    kwargs: dict[str, Any] = {}
    if buckets is not None:
        kwargs["buckets"] = buckets
    if labels:
        return Histogram(name, doc, labels, **kwargs)
    return Histogram(name, doc, **kwargs)


def _counter(name: str, doc: str, labels: list[str] | None = None):
    if not (_ENABLED and _PROM_OK):
        return None
    if labels:
        return Counter(name, doc, labels)
    return Counter(name, doc)


def _gauge(name: str, doc: str, labels: list[str] | None = None):
    if not (_ENABLED and _PROM_OK):
        return None
    if labels:
        return Gauge(name, doc, labels)
    return Gauge(name, doc)


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
    ["stage"],  # embed | search | synthesize | ingest
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0],
)

TOKENS = _counter(
    "rag_tokens_total",
    "Tokens consumed",
    ["model", "direction"],  # prompt | completion | embedding
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
    ["path"],  # llm_factory | openai | extractive_fallback
)

# ---------------------------------------------------------------------------
# HTTP / app & HITL metrics
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
    ["status"],  # indexed | quarantined | failed
)

INGEST_CHUNKS = _counter(
    "ingest_chunks_total",
    "Chunks upserted to Qdrant",
)

QDRANT_UP = _gauge(
    "qdrant_up",
    "Qdrant reachability (1=up, 0=down)",
)

ERRORS = _counter(
    "app_errors_total",
    "Application errors by component",
    ["component"],
)

HITL_TRIGGERS_TOTAL = _counter(
    "hitl_triggers_total",
    "Total Human-in-the-Loop review triggers by category",
    ["category"],
)

CONTENT_TYPE = CONTENT_TYPE_LATEST


# ---------------------------------------------------------------------------
# Helpers (safe no-ops when prometheus missing/disabled)
# ---------------------------------------------------------------------------


def observe_e2e(seconds: float) -> None:
    if E2E_LATENCY is not None:
        E2E_LATENCY.observe(max(0.0, float(seconds)))


def observe_stage(stage: str, seconds: float) -> None:
    if STAGE_LATENCY is not None:
        STAGE_LATENCY.labels(stage=stage).observe(max(0.0, float(seconds)))


@contextmanager
def time_stage(stage: str) -> Iterator[None]:
    """with time_stage('embed'): ..."""
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


def record_confidence(score: float | None) -> None:
    if CONFIDENCE is not None and score is not None:
        CONFIDENCE.observe(max(0.0, min(1.0, float(score))))


def record_retrieved(n: int) -> None:
    if RETRIEVED is not None:
        RETRIEVED.observe(max(0, int(n)))


def record_synthesis_path(path: str) -> None:
    if SYNTHESIS_PATH is not None:
        SYNTHESIS_PATH.labels(path=path or "unknown").inc()


def record_http(method: str, path: str, status: int, seconds: float) -> None:
    # normalize path ids for cardinality
    import re

    norm = re.sub(r"/[a-f0-9-]{32,36}", "/{id}", path or "")
    norm = re.sub(r"/\d+", "/{id}", norm)
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
) -> None:
    """Single helper for rag_service after a query completes."""
    if e2e_seconds is not None:
        observe_e2e(e2e_seconds)
    if retrieved is not None:
        record_retrieved(retrieved)
    if confidence is not None:
        record_confidence(confidence)
    if synthesis_path:
        record_synthesis_path(synthesis_path)
    if model:
        record_tokens(model, "prompt", prompt_tokens)
        record_tokens(model, "completion", completion_tokens)
        if cost_usd:
            record_cost(model, cost_usd)
    if embed_tokens and model:
        record_tokens(model, "embedding", embed_tokens)


def metrics_payload() -> tuple[bytes, str]:
    """Body + content-type for FastAPI Response."""
    if not (_ENABLED and _PROM_OK and generate_latest is not None):
        return (
            b"# prometheus_client unavailable or disabled\n",
            "text/plain; charset=utf-8",
        )
    return generate_latest(), CONTENT_TYPE_LATEST


def metrics_enabled() -> bool:
    return bool(_ENABLED and _PROM_OK)


__all__ = [
    "E2E_LATENCY",
    "STAGE_LATENCY",
    "TOKENS",
    "COST",
    "CONFIDENCE",
    "RETRIEVED",
    "SYNTHESIS_PATH",
    "HTTP_REQUESTS",
    "HTTP_LATENCY",
    "INGEST_DOCS",
    "INGEST_CHUNKS",
    "QDRANT_UP",
    "ERRORS",
    "HITL_TRIGGERS_TOTAL",
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
    "record_http",
    "record_ingest",
    "set_qdrant_up",
    "record_error",
    "record_hitl_trigger",
    "record_rag_turn",
    "metrics_payload",
    "metrics_enabled",
]