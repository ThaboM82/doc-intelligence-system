"""
Extended FastAPI router for document ingestion, RAG querying,
real-time token streaming, and structured document extraction.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from qdrant_client.http import models

from backend.db.qdrant import search_vectors, upsert_documents, get_collection_stats
from backend.models.llm_factory import LLMFactory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/intelligence", tags=["Document Intelligence"])

_active_llm_factory: LLMFactory | None = None


def set_active_llm_factory(factory: LLMFactory) -> None:
    """Set the application-wide LLM factory instance."""
    global _active_llm_factory
    _active_llm_factory = factory


def get_llm_factory() -> LLMFactory:
    """Dependency to retrieve the LLM factory."""
    if _active_llm_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LLM Factory has not been initialized."
        )
    return _active_llm_factory


# --- Pydantic Schemas ---

class DocumentChunk(BaseModel):
    text: str = Field(..., description="The raw text content of the document chunk.")
    vector: list[float] = Field(..., description="Pre-computed embedding vector matching Qdrant dimension.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional payload metadata.")


class IngestRequest(BaseModel):
    documents: list[DocumentChunk]


class QueryRequest(BaseModel):
    query: str = Field(..., description="The user's question or search prompt.")
    query_vector: list[float] = Field(..., description="The embedding vector for the user query.")
    top_k: int = Field(default=3, ge=1, le=20, description="Number of relevant chunks to retrieve.")
    score_threshold: float | None = Field(default=None, description="Optional minimum similarity score threshold.")
    filter_conditions: dict[str, Any] | None = Field(default=None, description="Optional payload metadata filters.")


class QueryResponse(BaseModel):
    answer: str
    retrieved_sources: list[dict[str, Any]]
    collection_stats: dict[str, Any]


class ExtractRequest(BaseModel):
    document_text: str = Field(..., description="Raw unstructured text from a document to extract information from.")
    extraction_goal: str = Field(..., description="Instructions on what information to extract.")


# --- Endpoints ---

@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_documents(payload: IngestRequest) -> dict[str, Any]:
    """Ingest document chunks and embedding vectors into Qdrant."""
    try:
        points = [
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=doc.vector,
                payload={"text": doc.text, **doc.metadata}
            )
            for doc in payload.documents
        ]

        await upsert_documents(points)
        stats = await get_collection_stats()

        logger.info(f"Successfully ingested {len(points)} document chunks.")
        return {
            "status": "success",
            "ingested_count": len(points),
            "collection_stats": stats
        }
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest documents: {str(e)}"
        )


@router.post("/query", response_model=QueryResponse)
async def query_intelligence(payload: QueryRequest) -> QueryResponse:
    """
    Perform a RAG query: retrieve relevant document context from Qdrant
    and synthesize an answer using the resilient LLMFactory.
    """
    factory = get_llm_factory()

    try:
        scored_points = await search_vectors(
            query_vector=payload.query_vector,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
            filter_conditions=payload.filter_conditions
        )

        contexts: list[str] = []
        sources: list[dict[str, Any]] = []

        for point in scored_points:
            payload_data = point.payload or {}
            text_snippet = payload_data.get("text", "")
            if text_snippet:
                contexts.append(text_snippet)
                sources.append({
                    "id": point.id,
                    "score": point.score,
                    "metadata": payload_data
                })

        if not contexts:
            return QueryResponse(
                answer="No relevant document context was found matching your query.",
                retrieved_sources=[],
                collection_stats=await get_collection_stats()
            )

        context_block = "\n\n---\n\n".join(contexts)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert Document Intelligence Assistant. Answer the user's question "
                    "strictly and accurately using only the provided context snippets below."
                )
            },
            {
                "role": "user",
                "content": f"Context:\n{context_block}\n\nQuestion: {payload.query}"
            }
        ]

        response = await factory.invoke(messages)
        answer_text = getattr(response, "content", str(response))
        stats = await get_collection_stats()

        return QueryResponse(
            answer=answer_text,
            retrieved_sources=sources,
            collection_stats=stats
        )

    except Exception as e:
        logger.error(f"RAG query execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query processing failed: {str(e)}"
        )


@router.post("/query/stream")
async def query_intelligence_stream(payload: QueryRequest) -> StreamingResponse:
    """
    Perform a streaming RAG query, returning chunks incrementally as Server-Sent Events (SSE)
    or raw chunked text stream.
    """
    factory = get_llm_factory()

    try:
        scored_points = await search_vectors(
            query_vector=payload.query_vector,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
            filter_conditions=payload.filter_conditions
        )

        contexts = [p.payload.get("text", "") for p in scored_points if p.payload and p.payload.get("text")]
        
        if not contexts:
            async def empty_stream() -> AsyncGenerator[str, None]:
                yield "No relevant document context found."
            return StreamingResponse(empty_stream(), media_type="text/plain")

        context_block = "\n\n---\n\n".join(contexts)
        messages = [
            {
                "role": "system",
                "content": "You are a precise Document Intelligence Assistant. Answer using only the provided context."
            },
            {
                "role": "user",
                "content": f"Context:\n{context_block}\n\nQuestion: {payload.query}"
            }
        ]

        async def token_generator() -> AsyncGenerator[str, None]:
            try:
                async for chunk in factory.stream_invoke(messages):
                    yield chunk
            except Exception as stream_err:
                logger.error(f"Streaming error occurred: {stream_err}")
                yield f"\n[Error during generation: {str(stream_err)}]"

        return StreamingResponse(token_generator(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Streaming initialization failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stream setup failed: {str(e)}"
        )


@router.post("/extract")
async def extract_structured_data(payload: ExtractRequest) -> dict[str, Any]:
    """
    Extract structured metadata from unstructured text using Pydantic schema validation
    via the LLMFactory structured output pipeline.
    """
    factory = get_llm_factory()

    class DynamicExtractionSchema(BaseModel):
        summary: str = Field(..., description="A concise summary addressing the extraction goal.")
        extracted_entities: list[str] = Field(default_factory=list, description="Key entities or terms identified.")
        confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the extraction.")

    messages = [
        {
            "role": "system",
            "content": f"You are a data extraction engine. Goal: {payload.extraction_goal}"
        },
        {
            "role": "user",
            "content": f"Document Text:\n{payload.document_text}"
        }
    ]

    try:
        structured_result = await factory.invoke_structured(messages, schema=DynamicExtractionSchema)
        return {
            "status": "success",
            "extracted_data": structured_result.dict()
        }
    except Exception as e:
        logger.error(f"Structured extraction failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Extraction failed: {str(e)}"
        )