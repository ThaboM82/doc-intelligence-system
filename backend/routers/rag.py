"""
RAG query API — embed → Qdrant retrieve → LLM synthesize.

Env:
  QDRANT_URL, QDRANT_API_KEY, QDRANT_COLLECTION (default: document_intelligence)
  QDRANT_VECTOR_SIZE (default: 1536)
  OPENAI_API_KEY, OPENAI_EMBED_MODEL, LLM_MODEL_NAME
  EMBEDDING_MODEL_NAME (local sentence-transformers fallback)
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])

COLLECTION = os.getenv("QDRANT_COLLECTION") or os.getenv(
    "QDRANT_COLLECTION_NAME", "document_intelligence"
)
VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "1536"))
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
LLM_MODEL = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RagQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(5, ge=1, le=20)
    filter_metadata: dict[str, Any] | None = None
    score_threshold: float | None = Field(
        None, ge=0.0, le=1.0, description="Optional min similarity (cosine)"
    )


class RagSource(BaseModel):
    id: str | None = None
    title: str | None = None
    file_name: str | None = None
    text: str | None = None
    score: float | None = None
    page: int | None = None
    doc_id: str | None = None
    chunk_id: str | None = None


class RagQueryResponse(BaseModel):
    answer: str
    sources: list[RagSource] = []
    confidence_score: float | None = None
    processing_time_ms: float | None = None
    collection: str | None = None
    retrieved: int | None = None


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def _openai_embed(text: str) -> list[float]:
    from openai import OpenAI

    client = OpenAI()
    res = client.embeddings.create(input=[text], model=EMBED_MODEL)
    return list(res.data[0].embedding)


def _st_embed(text: str) -> list[float]:
    try:
        sentence_transformers = importlib.import_module("sentence_transformers")
    except ImportError as exc:
        raise RuntimeError("sentence-transformers is not installed") from exc

    if not hasattr(_st_embed, "_model"):
        name = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
        _st_embed._model = sentence_transformers.SentenceTransformer(name)  # type: ignore[attr-defined]
    vec = _st_embed._model.encode(text)  # type: ignore[attr-defined]
    return vec.tolist()


async def get_embedding(text: str) -> list[float]:
    """
    Prefer OpenAI (1536) to match seeded Qdrant collection.
    Fall back to sentence-transformers only if dims will match VECTOR_SIZE.
    """
    if os.getenv("OPENAI_API_KEY"):
        try:
            return await asyncio.to_thread(_openai_embed, text)
        except Exception as exc:
            logger.warning("OpenAI embedding failed: %s", exc)

    try:
        vec = await asyncio.to_thread(_st_embed, text)
        if len(vec) != VECTOR_SIZE:
            logger.warning(
                "Local embedding dim %s != QDRANT_VECTOR_SIZE=%s — "
                "search may fail. Prefer OpenAI text-embedding-3-small.",
                len(vec),
                VECTOR_SIZE,
            )
        return vec
    except Exception as exc:
        logger.warning("sentence-transformers embedding failed: %s", exc)

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "No embedding backend available. Set OPENAI_API_KEY "
            f"(model {EMBED_MODEL}, dim {VECTOR_SIZE}) or install sentence-transformers."
        ),
    )


# ---------------------------------------------------------------------------
# Qdrant retrieve
# ---------------------------------------------------------------------------


async def retrieve_hits(
    query_vector: list[float],
    top_k: int,
    filter_metadata: dict[str, Any] | None = None,
    score_threshold: float | None = None,
) -> list[Any]:
    """Try project helpers first, then raw AsyncQdrantClient."""
    # 1) Project helper
    try:
        from backend.db import qdrant as qmod

        if hasattr(qmod, "search_vectors"):
            return await qmod.search_vectors(
                query_vector=query_vector,
                top_k=top_k,
                collection_name=COLLECTION,
                filter_metadata=filter_metadata,
                score_threshold=score_threshold,
            )
        if hasattr(qmod, "search"):
            return await qmod.search(
                query_vector=query_vector,
                top_k=top_k,
                filter_conditions=filter_metadata,
                score_threshold=score_threshold,
            )
    except ImportError:
        logger.debug("backend.db.qdrant helpers not available; using client fallback")
    except TypeError:
        # Signature mismatch — fall through
        logger.debug("search helper signature mismatch; using client fallback")
    except Exception as exc:
        logger.warning("Project Qdrant search failed: %s", exc)

    # 2) Async client via get_qdrant_client
    try:
        from backend.db.qdrant import get_qdrant_client
        from qdrant_client.http import models

        client = await get_qdrant_client()
        qfilter = None
        if filter_metadata:
            must = [
                models.FieldCondition(key=k, match=models.MatchValue(value=v))
                for k, v in filter_metadata.items()
            ]
            qfilter = models.Filter(must=must)

        # Prefer query_points (newer API)
        if hasattr(client, "query_points"):
            result = await client.query_points(
                collection_name=COLLECTION,
                query=query_vector,
                limit=top_k,
                score_threshold=score_threshold,
                query_filter=qfilter,
            )
            return list(result.points or [])

        return await client.search(
            collection_name=COLLECTION,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=qfilter,
        )
    except Exception as exc:
        logger.exception("Qdrant retrieve failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Vector search unavailable: {exc}",
        ) from exc


def hits_to_sources(hits: list[Any]) -> list[RagSource]:
    sources: list[RagSource] = []
    for h in hits:
        payload = getattr(h, "payload", None) or {}
        if not isinstance(payload, dict):
            payload = {}
        score = getattr(h, "score", None)
        page = payload.get("page") or payload.get("page_number")
        sources.append(
            RagSource(
                id=str(getattr(h, "id", "") or payload.get("chunk_id") or ""),
                title=payload.get("title")
                or payload.get("source_file")
                or payload.get("doc_id"),
                file_name=payload.get("source_file")
                or payload.get("file_name")
                or payload.get("filename"),
                text=payload.get("text")
                or payload.get("content")
                or payload.get("chunk_text"),
                score=round(float(score), 4) if score is not None else None,
                page=int(page) if page is not None else None,
                doc_id=str(payload.get("doc_id")) if payload.get("doc_id") else None,
                chunk_id=str(payload.get("chunk_id"))
                if payload.get("chunk_id")
                else None,
            )
        )
    return sources


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = (
    "You are a precise document assistant for enterprise policies and security. "
    "Answer ONLY using the provided context. If the context is insufficient, say so. "
    "Be concise. Cite sources by their bracket numbers when helpful."
)


def _openai_chat(query: str, context_str: str) -> str:
    from openai import OpenAI

    client = OpenAI()
    user = (
        f"--- CONTEXT ---\n{context_str}\n--- END CONTEXT ---\n\n"
        f"Question: {query}\nAnswer:"
    )
    completion = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    )
    return (completion.choices[0].message.content or "").strip()


async def synthesize_answer(
    query: str, sources: list[RagSource]
) -> tuple[str, float]:
    if not sources:
        return (
            "No relevant documents were found in the vector store for that query. "
            "Ingest or seed documents first, then try again.",
            0.0,
        )

    blocks: list[str] = []
    for i, src in enumerate(sources, 1):
        name = src.file_name or src.title or src.doc_id or src.id or "Unknown"
        text = (src.text or "").strip() or "(empty chunk)"
        score_s = f" score={src.score:.3f}" if src.score is not None else ""
        blocks.append(f"[{i}] {name}{score_s}\n{text}")
    context_str = "\n\n".join(blocks)

    avg_score = sum(s.score or 0.0 for s in sources) / len(sources)
    confidence = round(min(max(avg_score, 0.0), 1.0), 3)

    # Prefer project LLMFactory if present
    try:
        from backend.models.llm_factory import build_default_factory

        factory = build_default_factory(
            primary=None  # type: ignore[arg-type]
        )  # may not match your signature — catch below
    except Exception:
        factory = None

    if factory is not None and hasattr(factory, "ainvoke"):
        try:
            # Adjust if your factory API differs
            result = await factory.ainvoke(  # type: ignore[misc]
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Context:\n{context_str}\n\nQuestion: {query}",
                    },
                ]
            )
            text = getattr(result, "content", None) or str(result)
            return str(text).strip(), confidence
        except Exception as exc:
            logger.warning("LLMFactory synthesis failed: %s", exc)

    if os.getenv("OPENAI_API_KEY"):
        try:
            ans = await asyncio.to_thread(_openai_chat, query, context_str)
            if ans:
                return ans, confidence
        except Exception as exc:
            logger.warning("OpenAI chat failed: %s", exc)

    # Extractive fallback
    top = sources[0]
    return (
        f"Based on {top.file_name or top.title or top.id}:\n\n"
        f"{(top.text or '').strip()}\n\n"
        f"(Extractive summary from {len(sources)} chunk(s); configure OPENAI_API_KEY for full synthesis.)",
        confidence,
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/query", response_model=RagQueryResponse)
async def rag_query(body: RagQueryRequest) -> RagQueryResponse:
    t0 = time.perf_counter()

    query_vector = await get_embedding(body.query.strip())
    if len(query_vector) != VECTOR_SIZE:
        logger.warning(
            "Query vector dim %s != collection dim %s",
            len(query_vector),
            VECTOR_SIZE,
        )

    try:
        hits = await retrieve_hits(
            query_vector=query_vector,
            top_k=body.top_k,
            filter_metadata=body.filter_metadata,
            score_threshold=body.score_threshold,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected retrieve error")
        hits = []
        logger.warning("Continuing with empty hits: %s", exc)

    sources = hits_to_sources(hits)
    answer, confidence = await synthesize_answer(body.query.strip(), sources)
    ms = round((time.perf_counter() - t0) * 1000, 2)

    return RagQueryResponse(
        answer=answer,
        sources=sources,
        confidence_score=confidence,
        processing_time_ms=ms,
        collection=COLLECTION,
        retrieved=len(sources),
    )