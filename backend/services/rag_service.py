"""
Retrieve from Qdrant + synthesize answer (Tier 1 enterprise).

Pipeline: embed query → vector search → rank → truncate context →
LLM (OpenAI / LLMFactory) → extractive fallback.

Tier 1: answer only from context; refuse when confidence is low / no hits.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.services.embeddings import embed_query

logger = logging.getLogger(__name__)

try:
    from backend.observability.cost import chat_cost
except ImportError:  # pragma: no cover

    def chat_cost(*_a, **_k):  # type: ignore
        return 0.0


try:
    from backend.services.retrieval.confidence import score_confidence, should_refuse
except ImportError:  # pragma: no cover

    def score_confidence(scores, **_kwargs):
        if not scores:
            return "low", 0.0
        top = float(max(scores))
        if top >= 0.75 and len(scores) >= 2:
            return "high", top
        if top >= 0.55 or top >= 0.75:
            return "medium", top
        return "low", top

    def should_refuse(label, *, allow_medium=True):
        if label == "low":
            return True
        if label == "medium" and not allow_medium:
            return True
        return False


try:
    from backend.services.generation.prompts import (
        TIER1_SYSTEM,
        REFUSAL_ANSWER,
        build_context_blocks,
    )

    SYSTEM = TIER1_SYSTEM
except ImportError:  # pragma: no cover
    SYSTEM = (
        "You are a precise enterprise document assistant for policies, security, "
        "and compliance. Answer ONLY from the provided context. "
        "If the context is insufficient, say clearly that you cannot find the answer "
        "in the indexed documents. Be concise. Cite sources using [n] when helpful. "
        "Do not use general world knowledge."
    )
    REFUSAL_ANSWER = (
        "I could not find this in the approved indexed documents. "
        "Try rephrasing your question, or upload the relevant policy to the library."
    )

    def build_context_blocks(sources: list[dict]) -> str:
        blocks: list[str] = []
        for i, s in enumerate(sources, 1):
            name = s.get("file_name") or s.get("title") or s.get("id") or "Unknown"
            text = (s.get("text") or "").strip() or "(empty)"
            blocks.append(f"[{i}] {name}\n{text}")
        return "\n\n".join(blocks)


COLLECTION = os.getenv("QDRANT_COLLECTION") or os.getenv(
    "QDRANT_COLLECTION_NAME", "document_intelligence"
)
LLM_MODEL = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "12000"))
MAX_CHUNK_CHARS = int(os.getenv("RAG_MAX_CHUNK_CHARS", "1500"))
DEFAULT_TOP_K = int(os.getenv("RAG_DEFAULT_TOP_K", "5"))
MIN_SCORE = os.getenv("RAG_MIN_SCORE")  # optional float as string
ALLOW_MEDIUM = os.getenv("RAG_ALLOW_MEDIUM", "true").lower() in (
    "1",
    "true",
    "yes",
)
# Prefer points marked as passed security scan (set false if field not indexed yet)
REQUIRE_SECURITY_PASS = os.getenv("RAG_REQUIRE_SECURITY_PASS", "true").lower() in (
    "1",
    "true",
    "yes",
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
    confidence: Literal["high", "medium", "low"] = "low"
    refused: bool = False
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
        doc_id=str(payload["doc_id"])
        if payload.get("doc_id")
        else (
            str(payload["document_id"]) if payload.get("document_id") else None
        ),
        chunk_index=int(chunk_index) if chunk_index is not None else None,
    )


def _build_filter(filter_metadata: dict[str, Any] | None) -> Any:
    from qdrant_client.http import models

    must: list[Any] = []

    if REQUIRE_SECURITY_PASS:
        must.append(
            models.FieldCondition(
                key="security_scan_passed",
                match=models.MatchValue(value=True),
            )
        )

    if filter_metadata:
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

    async def _do(filt: Any) -> list[Any]:
        if hasattr(client, "query_points"):
            result = await client.query_points(
                collection_name=COLLECTION,
                query=vector,
                limit=top_k,
                score_threshold=score_threshold,
                query_filter=filt,
                with_payload=True,
            )
            return list(result.points or [])
        return await client.search(
            collection_name=COLLECTION,
            query_vector=vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=filt,
            with_payload=True,
        )

    try:
        return await _do(qfilter)
    except Exception as exc:
        # Payload field may be missing on older points — retry without filter
        if qfilter is not None:
            logger.warning(
                "Filtered search failed (%s); retrying without filter", exp
            )
            return await _do(None)
        raise


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _build_context(sources: list[RagSource]) -> str:
    # Prefer shared helper when available
    try:
        payload = [
            {
                "file_name": s.file_name,
                "title": s.title,
                "id": s.id,
                "page": s.page,
                "text": _truncate(s.text or "", MAX_CHUNK_CHARS),
            }
            for s in sources
        ]
        ctx = build_context_blocks(payload)
        if len(ctx) > MAX_CONTEXT_CHARS:
            return ctx[: MAX_CONTEXT_CHARS - 1].rstrip() + "…"
        return ctx
    except Exception:
        pass

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

    if hasattr(completion, "usage") and completion.usage:
        try:
            chat_cost(
                model=LLM_MODEL,
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                route="/api/v1/rag/query",
            )
        except TypeError:
            try:
                chat_cost(
                    model=LLM_MODEL,
                    prompt_tokens=completion.usage.prompt_tokens,
                    completion_tokens=completion.usage.completion_tokens,
                )
            except Exception:
                pass
        except Exception:
            pass

    return (completion.choices[0].message.content or "").strip()


async def _llm_factory_chat(query: str, context: str) -> str | None:
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
    except Exception as exp:
        logger.warning("LLMFactory synthesis failed: %s", exp)
        return None


async def synthesize(
    query: str, sources: list[RagSource]
) -> tuple[str, float, bool, float]:
    """Returns (answer, confidence, used_llm, llm_ms)."""
    conf = _confidence(sources)
    if not sources:
        return REFUSAL_ANSWER, 0.0, False, 0.0

    context = _build_context(sources)
    t_llm = time.perf_counter()

    ans = await _llm_factory_chat(query, context)
    if ans:
        return ans, conf, True, round((time.perf_counter() - t_llm) * 1000, 2)

    if os.getenv("OPENAI_API_KEY"):
        try:
            ans = await asyncio.to_thread(_openai_chat_sync, query, context)
            if ans:
                return ans, conf, True, round((time.perf_counter() - t_llm) * 1000, 2)
        except Exception as exp:
            logger.warning("OpenAI synthesis failed: %s", exp)

    top = sources[0]
    extractive = (
        f"Based on {top.file_name or top.title or top.id}:\n\n"
        f"{_truncate(top.text or '', MAX_CHUNK_CHARS)}\n\n"
        f"(Extractive fallback from {len(sources)} chunk(s); "
        f"set OPENAI_API_KEY for full synthesis.)"
    )
    return extractive, conf, False, round((time.perf_counter() - t_llm) * 1000, 2)


def _audit(query: str, *, refused: bool, n_sources: int) -> None:
    try:
        from backend.services.audit_service import audit_rag_query

        audit_rag_query(query, refused=refused, n_sources=n_sources)
    except Exception:
        pass


async def run_rag(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    filter_metadata: dict[str, Any] | None = None,
    score_threshold: float | None = None,
) -> RagResult:
    query = (query or "").strip()
    if not query:
        return RagResult(
            answer="Query is empty.",
            confidence_score=0.0,
            confidence="low",
            refused=True,
            retrieved=0,
        )

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
    sources.sort(
        key=lambda s: s.score if s.score is not None else -1.0, reverse=True
    )

    scores = [float(s.score) for s in sources if s.score is not None]
    label, top_score = score_confidence(scores)

    # Tier 1 refuse: low confidence or no hits
    if should_refuse(label, allow_medium=ALLOW_MEDIUM) or not sources:
        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        _audit(query, refused=True, n_sources=0)
        logger.info(
            "RAG refuse collection=%s retrieved=%s label=%s top=%.3f total_ms=%.1f",
            COLLECTION,
            len(sources),
            label,
            top_score,
            total_ms,
        )
        return RagResult(
            answer=REFUSAL_ANSWER,
            sources=[],
            confidence_score=top_score if sources else 0.0,
            confidence=label if sources else "low",
            refused=True,
            processing_time_ms=total_ms,
            collection=COLLECTION,
            retrieved=0,
            embed_ms=embed_ms,
            search_ms=search_ms,
            llm_ms=0.0,
            used_llm=False,
        )

    answer, conf, used_llm, llm_ms = await synthesize(query, sources)
    total_ms = round((time.perf_counter() - t0) * 1000, 2)
    _audit(query, refused=False, n_sources=len(sources))

    logger.info(
        "RAG query collection=%s retrieved=%s embed_ms=%.1f search_ms=%.1f "
        "llm_ms=%.1f total_ms=%.1f used_llm=%s confidence=%s",
        COLLECTION,
        len(sources),
        embed_ms,
        search_ms,
        llm_ms,
        total_ms,
        used_llm,
        label,
    )

    return RagResult(
        answer=answer,
        sources=sources,
        confidence_score=conf,
        confidence=label,
        refused=False,
        processing_time_ms=total_ms,
        collection=COLLECTION,
        retrieved=len(sources),
        embed_ms=embed_ms,
        search_ms=search_ms,
        llm_ms=llm_ms,
        used_llm=used_llm,
    )