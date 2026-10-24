"""
RAG query API — Tier 1 enterprise document intelligence.

Routes:
  POST /api/v1/rag/query     grounded answer + citations (or refuse)
  POST /api/v1/rag           alias of /query
  GET  /api/v1/rag/health    lightweight RAG stack probe
  GET  /api/v1/rag/config    non-secret runtime defaults
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])

# ---------------------------------------------------------------------------
# Config (env)
# ---------------------------------------------------------------------------

DEFAULT_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
DEFAULT_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.55"))
MAX_QUERY_LEN = int(os.getenv("RAG_MAX_QUERY_LEN", "4000"))
COLLECTION = os.getenv("QDRANT_COLLECTION") or os.getenv(
    "QDRANT_COLLECTION_NAME", "document_intelligence"
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RagQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(DEFAULT_TOP_K, ge=1, le=20)
    score_threshold: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Min similarity; defaults to server RAG_SCORE_THRESHOLD",
    )
    filter_metadata: Optional[dict[str, Any]] = Field(
        None,
        description="Optional Qdrant payload filters (e.g. file_name, document_id)",
    )
    include_snippets: bool = Field(
        True,
        description="If false, source text snippets are omitted (ids/scores only)",
    )

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        q = (v or "").strip()
        if not q:
            raise ValueError("query must not be empty")
        if len(q) > MAX_QUERY_LEN:
            raise ValueError(f"query exceeds {MAX_QUERY_LEN} characters")
        return q


class RagSource(BaseModel):
    n: int = 0
    id: Optional[str] = None
    document_id: Optional[str] = None
    file_name: Optional[str] = None
    title: Optional[str] = None
    page: Optional[int] = None
    score: Optional[float] = None
    text: Optional[str] = None


class RagQueryResponse(BaseModel):
    answer: str
    sources: List[RagSource] = Field(default_factory=list)
    confidence: str = "low"  # high | medium | low
    confidence_score: float = 0.0
    mode: str = "enterprise_only"
    refused: bool = False
    processing_time_ms: Optional[float] = None
    retrieved: int = 0
    collection: str = COLLECTION
    request_id: Optional[str] = None


class RagHealthResponse(BaseModel):
    status: str
    collection: str
    rag_service: bool
    embeddings: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class RagConfigResponse(BaseModel):
    mode: str = "enterprise_only"
    default_top_k: int
    default_score_threshold: float
    max_query_len: int
    collection: str
    grounded_only: bool = True
    web_fallback: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request_id(request: Request | None) -> str | None:
    if request is None:
        return None
    return getattr(request.state, "request_id", None) or request.headers.get(
        "x-request-id"
    )


def _optional_actor(request: Request | None) -> str | None:
    if request is None:
        return None
    auth = request.headers.get("authorization") or request.headers.get(
        "Authorization"
    )
    if not auth:
        return None
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1].strip()
        return f"bearer:{token[:8]}…" if len(token) > 8 else "bearer"
    return None


def _audit_query(
    query: str,
    *,
    refused: bool,
    n_sources: int,
    actor: str | None,
) -> None:
    try:
        from backend.services.audit_service import audit_rag_query

        audit_rag_query(
            query,
            refused=refused,
            n_sources=n_sources,
            actor=actor,
        )
    except Exception as exc:
        logger.debug("audit_rag_query skipped: %s", exp)


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _clip(text: str | None, n: int) -> str | None:
    if text is None:
        return None
    t = str(text).strip()
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def _normalize_sources(
    raw_sources: Any, *, include_snippets: bool
) -> List[RagSource]:
    sources: List[RagSource] = []
    if not raw_sources:
        return sources

    for i, s in enumerate(raw_sources, start=1):
        if isinstance(s, dict):
            text = s.get("text") if include_snippets else None
            sources.append(
                RagSource(
                    n=int(s.get("n") or i),
                    id=s.get("id"),
                    document_id=s.get("document_id") or s.get("doc_id"),
                    file_name=s.get("file_name")
                    or s.get("filename")
                    or s.get("source_file"),
                    title=s.get("title"),
                    page=s.get("page") or s.get("page_number"),
                    score=_safe_float(s.get("score")),
                    text=_clip(text, 800),
                )
            )
        else:
            text = getattr(s, "text", None) if include_snippets else None
            sources.append(
                RagSource(
                    n=i,
                    id=getattr(s, "id", None),
                    document_id=getattr(s, "document_id", None)
                    or getattr(s, "doc_id", None),
                    file_name=getattr(s, "file_name", None)
                    or getattr(s, "filename", None),
                    title=getattr(s, "title", None),
                    page=getattr(s, "page", None),
                    score=_safe_float(getattr(s, "score", None)),
                    text=_clip(text, 800),
                )
            )
    return sources


def _derive_confidence(
    conf_label: Any, conf_score: float, n_sources: int
) -> str:
    if conf_label in ("high", "medium", "low"):
        return str(conf_label)
    if conf_score >= 0.75 and n_sources >= 2:
        return "high"
    if conf_score >= 0.55 or (conf_score >= 0.75 and n_sources >= 1):
        return "medium"
    return "low"


async def _run_rag(
    body: RagQueryRequest,
    *,
    request: Request | None = None,
) -> RagQueryResponse:
    t0 = time.perf_counter()
    rid = _request_id(request)
    actor = _optional_actor(request)

    try:
        from backend.services.rag_service import run_rag
    except ImportError as exc:
        logger.exception("rag_service import failed")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"RAG service unavailable: {exc}",
        ) from exc

    threshold = (
        body.score_threshold
        if body.score_threshold is not None
        else DEFAULT_SCORE_THRESHOLD
    )

    try:
        result = await run_rag(
            query=body.query,
            top_k=body.top_k,
            filter_metadata=body.filter_metadata,
            score_threshold=threshold,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("RAG query failed request_id=%s", rid)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"RAG query failed: {exc}",
        ) from exp

    sources = _normalize_sources(
        getattr(result, "sources", None),
        include_snippets=body.include_snippets,
    )
    answer = (getattr(result, "answer", None) or "").strip()
    conf_score = float(getattr(result, "confidence_score", 0.0) or 0.0)
    confidence = _derive_confidence(
        getattr(result, "confidence", None), conf_score, len(sources)
    )

    refused = bool(getattr(result, "refused", False))
    if not sources:
        refused = True
        if not answer:
            answer = (
                "I could not find this in the approved indexed documents. "
                "Try rephrasing, or upload the relevant policy to the library."
            )

    ms = getattr(result, "processing_time_ms", None)
    if ms is None:
        ms = round((time.perf_counter() - t0) * 1000, 2)

    _audit_query(
        body.query,
        refused=refused,
        n_sources=len(sources),
        actor=actor,
    )

    return RagQueryResponse(
        answer=answer,
        sources=sources,
        confidence=confidence,
        confidence_score=round(conf_score, 4),
        mode="enterprise_only",
        refused=refused,
        processing_time_ms=float(ms),
        retrieved=int(getattr(result, "retrieved", len(sources)) or len(sources)),
        collection=str(getattr(result, "collection", COLLECTION) or COLLECTION),
        request_id=rid,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/query",
    response_model=RagQueryResponse,
    summary="Tier 1 grounded RAG query",
    responses={
        503: {"description": "RAG / vector stack unavailable"},
        500: {"description": "Query execution failed"},
    },
)
async def rag_query(body: RagQueryRequest, request: Request) -> RagQueryResponse:
    """
    Retrieve approved document chunks and return a grounded answer with citations.
    If evidence is insufficient, refused=true and sources are empty.
    """
    return await _run_rag(body, request=request)


@router.post(
    "",
    response_model=RagQueryResponse,
    summary="Tier 1 grounded RAG query (alias)",
    include_in_schema=False,
)
async def rag_query_alias(
    body: RagQueryRequest, request: Request
) -> RagQueryResponse:
    return await _run_rag(body, request=request)


@router.get(
    "/health",
    response_model=RagHealthResponse,
    summary="RAG stack health probe",
)
async def rag_health() -> RagHealthResponse:
    detail: dict[str, Any] = {}
    rag_ok = False
    emb_ok = False

    try:
        from backend.services import rag_service  # noqa: F401

        rag_ok = hasattr(rag_service, "run_rag")
        detail["rag_service"] = "ok" if rag_ok else "missing run_rag"
    except Exception as exc:
        detail["rag_service"] = str(exc)

    try:
        from backend.services import embeddings  # noqa: F401

        emb_ok = True
        detail["embeddings"] = "import_ok"
    except Exception as exp:
        detail["embeddings"] = str(exc)

    try:
        from backend.db.qdrant import get_collection_stats

        stats = await get_collection_stats()
        detail["qdrant"] = stats
    except Exception as exp:
        detail["qdrant"] = str(exc)

    status_label = "ok" if rag_ok else "degraded"
    return RagHealthResponse(
        status=status_label,
        collection=COLLECTION,
        rag_service=rag_ok,
        embeddings=emb_ok,
        detail=detail,
    )


@router.get(
    "/config",
    response_model=RagConfigResponse,
    summary="Public RAG defaults (no secrets)",
)
async def rag_config() -> RagConfigResponse:
    return RagConfigResponse(
        mode="enterprise_only",
        default_top_k=DEFAULT_TOP_K,
        default_score_threshold=DEFAULT_SCORE_THRESHOLD,
        max_query_len=MAX_QUERY_LEN,
        collection=COLLECTION,
        grounded_only=True,
        web_fallback=False,
    )