"""
Enterprise Retrieval Service

Responsibilities:
- Query Embeddings
- Qdrant Search
- Metadata Filtering
- Result Normalization
- Re-ranking

Used By:
- Retrieval Orchestrator
- RAG Service
- Analytics
"""

from __future__ import annotations

import logging
from typing import Any

from backend.services.retrieval.reranker import (
    RetrievalReranker,
)

logger = logging.getLogger(__name__)


class RetrievalService:

    def __init__(
        self,
        embeddings_service,
        vector_store,
    ):
        self.embeddings_service = (
            embeddings_service
        )

        self.vector_store = (
            vector_store
        )

        self.reranker = (
            RetrievalReranker()
        )

    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: dict[str, Any]
        | None = None,
    ) -> list[dict[str, Any]]:

        try:

            query_embedding = (
                await self.embeddings_service
                .embed_query(query)
            )

            response = (
                await self.vector_store.search(
                    embedding=query_embedding,
                    top_k=top_k,
                    filters=filters,
                )
            )

            normalized = (
                self._normalize_results(
                    response
                )
            )

            reranked = (
                self.reranker.rerank(
                    query=query,
                    results=normalized,
                )
            )

            return reranked

        except Exception as exc:

            logger.exception(
                "Retrieval search failed: %s",
                exc,
            )

            return []

    def _normalize_results(
        self,
        results: list[Any],
    ) -> list[dict[str, Any]]:

        normalized = []

        for item in results:

            payload = (
                item.payload
                if hasattr(
                    item,
                    "payload"
                )
                else item.get(
                    "payload",
                    {},
                )
            )

            score = (
                item.score
                if hasattr(
                    item,
                    "score"
                )
                else item.get(
                    "score",
                    0.0,
                )
            )

            normalized.append(
                {
                    "chunk_id":
                        payload.get(
                            "chunk_id"
                        ),
                    "document_id":
                        payload.get(
                            "document_id"
                        ),
                    "document_name":
                        payload.get(
                            "document_name"
                        ),
                    "page":
                        payload.get(
                            "page"
                        ),
                    "title":
                        payload.get(
                            "title",
                            ""
                        ),
                    "content":
                        payload.get(
                            "content",
                            ""
                        ),
                    "metadata":
                        payload.get(
                            "metadata",
                            {},
                        ),
                    "score":
                        round(
                            float(score),
                            4,
                        ),
                }
            )

        return normalized

    async def retrieve_document_chunks(
        self,
        document_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:

        try:

            results = (
                await self.vector_store
                .get_document_chunks(
                    document_id,
                    limit=limit,
                )
            )

            return self._normalize_results(
                results
            )

        except Exception as exc:

            logger.exception(
                "Failed to retrieve chunks for "
                "document %s: %s",
                document_id,
                exc,
            )

            return []

    async def retrieve_by_metadata(
        self,
        metadata_filter: dict[
            str,
            Any,
        ],
        limit: int = 25,
    ) -> list[dict[str, Any]]:

        try:

            results = (
                await self.vector_store
                .metadata_search(
                    metadata_filter,
                    limit=limit,
                )
            )

            return self._normalize_results(
                results
            )

        except Exception as exc:

            logger.exception(
                "Metadata search failed: %s",
                exc,
            )

            return []

    async def health_check(
        self,
    ) -> dict[str, Any]:

        try:

            collection_info = (
                await self.vector_store
                .collection_info()
            )

            return {
                "status": "healthy",
                "vector_store":
                    "connected",
                "collection":
                    collection_info,
            }

        except Exception as exc:

            logger.exception(
                "Vector store health "
                "check failed: %s",
                exc,
            )

            return {
                "status": "unhealthy",
                "error": str(exc),
            }