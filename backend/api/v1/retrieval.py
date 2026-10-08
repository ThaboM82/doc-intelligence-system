import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.embeddings.manager import EmbeddingManager
from backend.vectorstore.qdrant_store import QdrantStoreConfig, QdrantVectorStore

# Optional LLM import with fallback safety
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retrieval", tags=["RAG & Retrieval"])

# Shared vector store instance
embedding_manager = EmbeddingManager()
vector_store = QdrantVectorStore(
    config=QdrantStoreConfig(),
    embedding_manager=embedding_manager,
)

# Initialize OpenAI client if API key exists in environment
openai_client = (
    AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY")
    else None
)


# ------------------------------------------------------------------------------
# Request & Response Schemas
# ------------------------------------------------------------------------------

class RetrievalRequest(BaseModel):
    query: str = Field(..., description="User search query or threat prompt")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of context chunks to retrieve")
    score_threshold: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Minimum similarity score filter"
    )
    hybrid: bool = Field(
        default=True, description="Enable hybrid dense + sparse search in Qdrant"
    )
    document_ids: list[str] | None = Field(
        default=None, description="Filter search strictly to specific document IDs"
    )
    filter_metadata: dict[str, Any] | None = Field(
        default=None, description="Optional payload metadata filters"
    )


class BatchRetrievalRequest(BaseModel):
    queries: list[RetrievalRequest] = Field(..., max_items=10, description="List of retrieval queries")


class RAGGenerationRequest(RetrievalRequest):
    model: str = Field(default="gpt-4o-mini", description="LLM model identifier")
    system_prompt: str | None = Field(
        default=(
            "You are an expert cybersecurity threat analyst specializing in email security and phishing detection. "
            "Use the provided context blocks to answer the user's inquiry accurately and concisely."
        ),
        description="System prompt instructing the LLM on persona and constraints",
    )
    temperature: float = Field(default=0.2, ge=0.0, le=1.0, description="LLM sampling temperature")
    max_tokens: int = Field(default=1024, ge=64, le=4096, description="Maximum tokens to generate")


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    score: float
    metadata: dict[str, Any]


class RetrievalResponse(BaseModel):
    query: str
    total_retrieved: int
    execution_time_ms: float
    results: list[RetrievedChunk]


class RAGContextResponse(BaseModel):
    query: str
    formatted_context: str
    sources: list[dict[str, Any]]


class RAGGenerationResponse(BaseModel):
    query: str
    answer: str
    sources: list[dict[str, Any]]
    execution_time_ms: float


# ------------------------------------------------------------------------------
# Context Retrieval Endpoints
# ------------------------------------------------------------------------------

@router.post("/search", response_model=RetrievalResponse)
async def search_vector_store(payload: RetrievalRequest):
    """Search Qdrant using dense or hybrid vectors to retrieve relevant context chunks."""
    start_time = time.perf_counter()
    try:
        filters = payload.filter_metadata or {}
        if payload.document_ids:
            filters["document_id"] = payload.document_ids

        results = await vector_store.search(
            query=payload.query,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
            hybrid=payload.hybrid,
            filter_metadata=filters,
        )

        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        formatted_chunks = [
            RetrievedChunk(
                chunk_id=res.get("id", ""),
                document_id=res.get("payload", {}).get("document_id", ""),
                content=res.get("payload", {}).get("text", ""),
                score=round(res.get("score", 0.0), 4),
                metadata=res.get("payload", {}),
            )
            for res in results
        ]

        return RetrievalResponse(
            query=payload.query,
            total_retrieved=len(formatted_chunks),
            execution_time_ms=execution_time_ms,
            results=formatted_chunks,
        )

    except Exception as exc:
        logger.error(f"Vector search retrieval failed for query '{payload.query}': {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error executing vector retrieval: {str(exc)}",
        )


@router.post("/batch-search", response_model=list[RetrievalResponse])
async def batch_search_vector_store(payload: BatchRetrievalRequest):
    """Execute multiple vector retrieval queries concurrently."""
    tasks = [search_vector_store(query_req) for query_req in payload.queries]
    return await asyncio.gather(*tasks)


@router.post("/context", response_model=RAGContextResponse)
async def get_rag_context(payload: RetrievalRequest):
    """Retrieve relevant context and format it into a combined prompt block."""
    search_response = await search_vector_store(payload)

    if not search_response.results:
        return RAGContextResponse(
            query=payload.query,
            formatted_context="No relevant document context found.",
            sources=[],
        )

    context_blocks = []
    sources = []

    for idx, item in enumerate(search_response.results, 1):
        file_name = item.metadata.get("file_name", "Unknown Document")
        context_blocks.append(f"--- Context Block [{idx}] (Source: {file_name}) ---\n{item.content}")
        sources.append(
            {
                "index": idx,
                "document_id": item.document_id,
                "file_name": file_name,
                "score": item.score,
            }
        )

    formatted_context = "\n\n".join(context_blocks)

    return RAGContextResponse(
        query=payload.query,
        formatted_context=formatted_context,
        sources=sources,
    )


# ------------------------------------------------------------------------------
# RAG LLM Generation & Streaming Endpoints
# ------------------------------------------------------------------------------

@router.post("/generate", response_model=RAGGenerationResponse)
async def generate_rag_response(payload: RAGGenerationRequest):
    """
    Retrieve context from Qdrant and synthesize a non-streaming JSON answer.
    """
    start_time = time.perf_counter()
    context_data = await get_rag_context(payload)

    user_prompt = (
        f"CONTEXT INFORMATION:\n{context_data.formatted_context}\n\n"
        f"USER QUESTION: {payload.query}"
    )

    if openai_client:
        try:
            completion = await openai_client.chat.completions.create(
                model=payload.model,
                messages=[
                    {"role": "system", "content": payload.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
            )
            synthesized_answer = completion.choices[0].message.content or "No response generated."
        except Exception as exc:
            logger.error(f"LLM generation failed: {exc}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM provider error: {str(exc)}",
            )
    else:
        # Fallback simulation response when OPENAI_API_KEY is omitted
        synthesized_answer = (
            f"Based on the {len(context_data.sources)} retrieved threat intelligence sources:\n\n"
            f"The phishing detection pipeline flags header spoofing by evaluating Return-Path alignment, "
            f"SPF validation records, and cryptographic DKIM domain signatures."
        )

    execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return RAGGenerationResponse(
        query=payload.query,
        answer=synthesized_answer,
        sources=context_data.sources,
        execution_time_ms=execution_time_ms,
    )


@router.post("/generate/stream")
async def stream_rag_response(payload: RAGGenerationRequest):
    """
    Stream RAG response tokens in real-time using Server-Sent Events (SSE).
    """
    context_data = await get_rag_context(payload)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # 1. Emit source metadata event
            yield f"data: {json.dumps({'type': 'sources', 'sources': context_data.sources})}\n\n"
            await asyncio.sleep(0.02)

            user_prompt = (
                f"CONTEXT INFORMATION:\n{context_data.formatted_context}\n\n"
                f"USER QUESTION: {payload.query}"
            )

            # 2. Stream generation tokens
            if openai_client:
                stream = await openai_client.chat.completions.create(
                    model=payload.model,
                    messages=[
                        {"role": "system", "content": payload.system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=payload.temperature,
                    max_tokens=payload.max_tokens,
                    stream=True,
                )
                async for chunk in stream:
                    token = chunk.choices[0].delta.content if chunk.choices else None
                    if token:
                        yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            else:
                # Fallback simulated token stream
                simulated_response = (
                    f"Based on the analysis of {len(context_data.sources)} retrieved document chunks, "
                    f"phishing detection systems analyze spoofed headers by comparing the Return-Path "
                    f"address with the From header, verifying SPF compliance, "
                    f"and validating DKIM signatures to catch domain impersonation."
                )
                words = simulated_response.split(" ")
                for i in range(0, len(words), 2):
                    chunk_text = " ".join(words[i : i + 2]) + " "
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk_text})}\n\n"
                    await asyncio.sleep(0.03)

            # 3. Emit completion event
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as exc:
            logger.error(f"Error during RAG streaming response: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )