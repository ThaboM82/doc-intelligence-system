"""
Retrieve from Qdrant + synthesize answer.

Pipeline: embed query → vector search → (optional) re-rank by score →
truncate context → LLM (OpenAI / LLMFactory) → extractive fallback.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from backend.services.embeddings import embed_query
from backend.observability.cost import chat_cost

logger = logging.getLogger(__name__)

COLLECTION = os.getenv("QDRANT_COLLECTION") or os.getenv(
    "QDRANT_COLLECTION_NAME", "document_intelligence"
)
LLM_MODEL = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "12000"))
MAX_CHUNK_CHARS = int(os.getenv("RAG_MAX_CHUNK_CHARS", "1500"))
DEFAULT_TOP_K = int(os.getenv("RAG_DEFAULT_TOP_K", "5"))
MIN_SCORE = os.getenv("RAG_MIN_SCORE")  # optional float as string

SYSTEM = (
    "You are a precise enterprise document assistant for policies, security, "
    "and compliance. Answer ONLY from the provided context. "
    "If the context is insufficient, say clearly that you cannot find the answer "
    "in the indexed documents. Be concise. Cite sources using [n] when helpful."
)


@dataclass
class RagSource:
    id: str | None = None
    title: str | None = None
    file_name: str | None = None
    text: str | None = None
    score: float | None = None
    page: int | None = None
    doc_id: str | None = None
    chunk_index: int | None = None


@dataclass
class RagResult:
    answer: str
    sources: list[RagSource] = field(default_factory=list)
    confidence_score: float = 0.0
    processing_time_ms: float = 0.0
    collection: str = COLLECTION
    retrieved: int = 0
    embed_ms: float | None = None
    search_ms: float | None = None
    llm_ms: float | None = None
    used_llm: bool = False


def _hit_to_source(h: Any) -> RagSource:
    payload = getattr(h, "payload", None) or {}
    if not isinstance(payload, dict):
        payload = {}
    score = getattr(h, "score", None)
    page = payload.get("page") or payload.get("page_number")
    chunk_index = payload.get("chunk_index")
    return RagSource(
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
        doc_id=str(payload["doc_id"]) if payload.get("doc_id") else None,
        chunk_index=int(chunk_index) if chunk_index is not None else None,
    )


def _build_filter(filter_metadata: dict[str, Any] | None) -> Any:
    if not filter_metadata:
        return None
    from qdrant_client.http import models

    must = []
    for k, v in filter_metadata.items():
        if v is None:
            continue
        if isinstance(v, list):
            must.append(
                models.FieldCondition(key=k, match=models.MatchAny(any=v))
            )
        else:
            must.append(
                models.FieldCondition(key=k, match=models.MatchValue(value=v))
            )
    return models.Filter(must=must) if must else None


async def _search(
    vector: list[float],
    top_k: int,
    filter_metadata: dict[str, Any] | None = None,
    score_threshold: float | None = None,
) -> list[Any]:
    from backend.db.qdrant import get_qdrant_client

    client = await get_qdrant_client()
    qfilter = _build_filter(filter_metadata)

    # Prefer query_points (Qdrant client >= 1.7)
    if hasattr(client, "query_points"):
        result = await client.query_points(
            collection_name=COLLECTION,
            query=vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=qfilter,
            with_payload=True,
        )
        return list(result.points or [])

    return await client.search(
        collection_name=COLLECTION,
        query_vector=vector,
        limit=top_k,
        score_threshold=score_threshold,
        query_filter=qfilter,
        with_payload=True,
    )


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _build_context(sources: list[RagSource]) -> str:
    blocks: list[str] = []
    used = 0
    for i, s in enumerate(sources, 1):
        name = s.file_name or s.title or s.doc_id or s.id or "Unknown"
        body = _truncate(s.text or "", MAX_CHUNK_CHARS)
        sc = f" score={s.score:.3f}" if s.score is not None else ""
        page = f" p.{s.page}" if s.page is not None else ""
        block = f"[{i}] {name}{page}{sc}\n{body or '(empty)'}"
        if used + len(block) + 2 > MAX_CONTEXT_CHARS and blocks:
            break
        blocks.append(block)
        used += len(block) + 2
    return "\n\n".join(blocks)


def _confidence(sources: list[RagSource]) -> float:
    if not sources:
        return 0.0
    scores = [s.score for s in sources if s.score is not None]
    if not scores:
        return 0.0
    # Weight top hit more heavily
    top = scores[0]
    avg = sum(scores) / len(scores)
    return round(min(max(0.7 * top + 0.3 * avg, 0.0), 1.0), 3)


def _openai_chat_sync(query: str, context: str) -> str:
    from openai import OpenAI

    client = OpenAI()
    completion = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        messages=[
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": (
                    f"--- CONTEXT ---\n{context}\n--- END CONTEXT ---\n\n"
                    f"Question: {query}\nAnswer:"
                ),
            },
        ],
    )
    
    # Track chat token costs via observability tracker
    if hasattr(completion, "usage") and completion.usage:
        try:
            chat_cost(
                model=LLM_MODEL,
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                route="/api/v1/chat/rag"
            )
        except Exception:
            pass

    return (completion.choices[0].message.content or "").strip()


async def _llm_factory_chat(query: str, context: str) -> str | None:
    """Optional path via project LLMFactory if wired."""
    try:
        from backend.routers.intelligence import get_active_llm_factory  # type: ignore
    except ImportError:
        try:
            from backend.models.llm_factory import get_active_llm_factory  # type: ignore
        except ImportError:
            return None

    try:
        factory = get_active_llm_factory()  # type: ignore[misc]
    except Exception:
        return None
    if factory is None:
        return None

    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {query}",
        },
    ]
    try:
        if hasattr(factory, "ainvoke"):
            result = await factory.ainvoke(messages)  # type: ignore[misc]
        elif hasattr(factory, "invoke"):
            result = await asyncio.to_thread(factory.invoke, messages)
        else:
            return None
        return str(getattr(result, "content", None) or result).strip() or None
    except Exception as exc:
        logger.warning("LLMFactory synthesis failed: %s", exc)
        return None


async def synthesize(query: str, sources: list[RagSource]) -> tuple[str, float, bool, float]:
    """
    Returns (answer, confidence, used_llm, llm_ms).
    """
    conf = _confidence(sources)
    if not sources:
        return (
            "No relevant documents found. Seed or ingest documents into Qdrant, then retry.",
            0.0,
            False,
            0.0,
        )

    context = _build_context(sources)
    t_llm = time.perf_counter()

    # 1) LLMFactory if available
    ans = await _llm_factory_chat(query, context)
    if ans:
        return ans, conf, True, round((time.perf_counter() - t_llm) * 1000, 2)

    # 2) Direct OpenAI
    if os.getenv("OPENAI_API_KEY"):
        try:
            ans = await asyncio.to_thread(_openai_chat_sync, query, context)
            if ans:
                return ans, conf, True, round((time.perf_counter() - t_llm) * 1000, 2)
        except Exception as exc:
            logger.warning("OpenAI synthesis failed: %s", exc)

    # 3) Extractive fallback
    top = sources[0]
    extractive = (
        f"Based on {top.file_name or top.title or top.id}:\n\n"
        f"{_truncate(top.text or '', MAX_CHUNK_CHARS)}\n\n"
        f"(Extractive fallback from {len(sources)} chunk(s); "
        f"set OPENAI_API_KEY for full synthesis.)"
    )
    return extractive, conf, False, round((time.perf_counter() - t_llm) * 1000, 2)


async def run_rag(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    filter_metadata: dict[str, Any] | None = None,
    score_threshold: float | None = None,
) -> RagResult:
    query = (query or "").strip()
    if not query:
        return RagResult(answer="Query is empty.", confidence_score=0.0, retrieved=0)

    top_k = max(1, min(int(top_k or DEFAULT_TOP_K), 20))
    if score_threshold is None and MIN_SCORE:
        try:
            score_threshold = float(MIN_SCORE)
        except ValueError:
            score_threshold = None

    t0 = time.perf_counter()

    t_embed = time.perf_counter()
    vector = await embed_query(query)
    embed_ms = round((time.perf_counter() - t_embed) * 1000, 2)

    t_search = time.perf_counter()
    try:
        hits = await _search(vector, top_k, filter_metadata, score_threshold)
    except Exception:
        logger.exception("Qdrant search failed")
        raise
    search_ms = round((time.perf_counter() - t_search) * 1000, 2)

    sources = [_hit_to_source(h) for h in hits]
    # Sort by score descending when present
    sources.sort(key=lambda s: s.score if s.score is not None else -1.0, reverse=True)

    answer, conf, used_llm, llm_ms = await synthesize(query, sources)
    total_ms = round((time.perf_counter() - t0) * 1000, 2)

    logger.info(
        "RAG query collection=%s retrieved=%s embed_ms=%.1f search_ms=%.1f llm_ms=%.1f total_ms=%.1f used_llm=%s",
        COLLECTION,
        len(sources),
        embed_ms,
        search_ms,
        llm_ms,
        total_ms,
        used_llm,
    )

    return RagResult(
        answer=answer,
        sources=sources,
        confidence_score=conf,
        processing_time_ms=total_ms,
        collection=COLLECTION,
        retrieved=len(sources),
        embed_ms=embed_ms,
        search_ms=search_ms,
        llm_ms=llm_ms,
        used_llm=used_llm,
    )