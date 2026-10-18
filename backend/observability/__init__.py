"""Observability for the RAG pipeline: metrics, cost, tracing."""

from backend.observability.metrics import (  # noqa: F401
    E2E_LATENCY,
    STAGE_LATENCY,
    TOKENS,
    COST,
    CONFIDENCE,
    RETRIEVED,
    SYNTHESIS_PATH,
)
