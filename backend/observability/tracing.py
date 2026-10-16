"""
Tracing via LangSmith — zero new infrastructure; `langsmith` is already a dep.

Setup:
  1. Create an API key at https://smith.langchain.com
  2. Set env vars (.env / Render / CI):
       LANGSMITH_TRACING=true
       LANGSMITH_API_KEY=lsv2_pt_...   # or ls__...
       LANGSMITH_PROJECT=doc-intelligence-prod
       LANGSMITH_ENDPOINT=https://api.smith.langchain.com   # optional

LangSmith provides: per-request traces, retrieval/LLM span breakdown,
token counts, latency waterfall, cost rollups, dataset experiments.

`@traceable` / helpers degrade to no-ops when tracing is disabled or
langsmith is missing.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, ParamSpec

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

_tracing_enabled: bool | None = None
_langsmith_ok: bool = False

# ---------------------------------------------------------------------------
# Import langsmith (optional)
# ---------------------------------------------------------------------------

try:
    from langsmith import traceable as _ls_traceable  # type: ignore
    from langsmith import Client as _LSClient  # type: ignore

    _langsmith_ok = True
except Exception:  # pragma: no cover
    _ls_traceable = None  # type: ignore
    _LSClient = None  # type: ignore
    logger.info("langsmith not available — tracing is a no-op")


def tracing_enabled() -> bool:
    """Cache env check so we do not re-read os.environ every request."""
    global _tracing_enabled
    if _tracing_enabled is None:
        flag = os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1", "yes", "on")
        key = bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))
        _tracing_enabled = bool(flag and key and _langsmith_ok)
        if flag and not key:
            logger.warning("LANGSMITH_TRACING set but LANGSMITH_API_KEY missing")
        if flag and key and not _langsmith_ok:
            logger.warning("LANGSMITH_TRACING set but langsmith package failed to import")
    return bool(_tracing_enabled)


def project_name() -> str:
    return (
        os.getenv("LANGSMITH_PROJECT")
        or os.getenv("LANGCHAIN_PROJECT")
        or "doc-intelligence"
    )


def _noop_traceable(fn: Callable[P, R] | None = None, **_kwargs: Any):
    """No-op decorator matching langsmith.traceable call styles."""
    if fn is None:
        return lambda f: f
    return fn


def traceable(fn: Callable[P, R] | None = None, **kwargs: Any):
    """
    Decorator: LangSmith @traceable when enabled, else identity.

    Usage:
      @traceable(name="rag.run", run_type="chain")
      async def run_rag(...): ...
    """
    if not tracing_enabled() or _ls_traceable is None:
        return _noop_traceable(fn, **kwargs)

    kwargs.setdefault("project_name", project_name())
    return _ls_traceable(fn, **kwargs) if fn is not None else _ls_traceable(**kwargs)


def get_client() -> Any | None:
    """LangSmith client or None."""
    if not tracing_enabled() or _LSClient is None:
        return None
    try:
        return _LSClient()
    except Exception as exc:
        logger.warning("LangSmith client init failed: %s", exc)
        return None


def ensure_env() -> dict[str, str]:
    """
    Normalize common LangChain/LangSmith env aliases for child processes.
    Call once at app startup if desired.
    """
    out: dict[str, str] = {}
    key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if key:
        os.environ.setdefault("LANGSMITH_API_KEY", key)
        os.environ.setdefault("LANGCHAIN_API_KEY", key)
        out["api_key_set"] = "1"
    proj = project_name()
    os.environ.setdefault("LANGSMITH_PROJECT", proj)
    os.environ.setdefault("LANGCHAIN_PROJECT", proj)
    out["project"] = proj
    if tracing_enabled():
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        out["tracing"] = "true"
    else:
        out["tracing"] = "false"
    return out


def trace_metadata(
    *,
    request_id: str | None = None,
    route: str | None = None,
    document_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Standard metadata bag for runs."""
    meta: dict[str, Any] = {
        "service": "doc-intelligence",
        "project": project_name(),
    }
    if request_id:
        meta["request_id"] = request_id
    if route:
        meta["route"] = route
    if document_id:
        meta["document_id"] = document_id
    if extra:
        meta.update(extra)
    return meta


def wrap_rag(fn: Callable[P, R]) -> Callable[P, R]:
    """Shortcut: mark a function as a RAG chain span."""
    return traceable(name="rag.run", run_type="chain")(fn)  # type: ignore[misc]


def wrap_embed(fn: Callable[P, R]) -> Callable[P, R]:
    return traceable(name="rag.embed", run_type="embedding")(fn)  # type: ignore[misc]


def wrap_retrieve(fn: Callable[P, R]) -> Callable[P, R]:
    return traceable(name="rag.retrieve", run_type="retriever")(fn)  # type: ignore[misc]


def wrap_synthesize(fn: Callable[P, R]) -> Callable[P, R]:
    return traceable(name="rag.synthesize", run_type="llm")(fn)  # type: ignore[misc]


def wrap_ingest(fn: Callable[P, R]) -> Callable[P, R]:
    return traceable(name="ingest.run", run_type="chain")(fn)  # type: ignore[misc]


def status() -> dict[str, Any]:
    """For /ready or admin diagnostics."""
    return {
        "langsmith_import_ok": _langsmith_ok,
        "tracing_enabled": tracing_enabled(),
        "project": project_name(),
        "api_key_configured": bool(
            os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
        ),
    }


__all__ = [
    "tracing_enabled",
    "project_name",
    "traceable",
    "get_client",
    "ensure_env",
    "trace_metadata",
    "wrap_rag",
    "wrap_embed",
    "wrap_retrieve",
    "wrap_synthesize",
    "wrap_ingest",
    "status",
]