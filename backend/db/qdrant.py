"""
Qdrant vector database client manager, collection initialization,
and async search/upsert operations.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "document_intelligence")
VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "1536"))

_qdrant_client: AsyncQdrantClient | None = None


async def get_qdrant_client() -> AsyncQdrantClient:
    """Get or initialize the singleton AsyncQdrantClient instance."""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = AsyncQdrantClient(url=QDRANT_URL)
    return _qdrant_client


async def init_qdrant_collection() -> None:
    """Ensure the Qdrant collection exists with proper cosine vector configuration."""
    client = await get_qdrant_client()
    try:
        collections = await client.get_collections()
        exists = any(c.name == COLLECTION_NAME for c in collections.collections)

        if not exists:
            logger.info(f"Creating Qdrant collection '{COLLECTION_NAME}' with vector size {VECTOR_SIZE}...")
            await client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=models.Distance.COSINE
                ),
            )
            logger.info(f"Collection '{COLLECTION_NAME}' successfully created.")
        else:
            logger.info(f"Qdrant collection '{COLLECTION_NAME}' already exists.")
    except UnexpectedResponse as e:
        logger.error(f"Failed to initialize Qdrant collection: {e}")
        raise


async def upsert_documents(points: list[models.PointStruct]) -> bool:
    """Upsert document points (vectors + metadata payloads) into Qdrant."""
    client = await get_qdrant_client()
    try:
        await client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=True
        )
        return True
    except Exception as e:
        logger.error(f"Error upserting document points into Qdrant: {e}")
        raise


async def search_vectors(
    query_vector: list[float],
    top_k: int = 5,
    score_threshold: float | None = None,
    filter_conditions: dict[str, Any] | None = None,
) -> list[models.ScoredPoint]:
    """
    Perform vector similarity search with optional payload filters and score thresholds.
    """
    client = await get_qdrant_client()

    qdrant_filter = None
    if filter_conditions:
        must_conditions = [
            models.FieldCondition(
                key=k,
                match=models.MatchValue(value=v)
            )
            for k, v in filter_conditions.items()
        ]
        qdrant_filter = models.Filter(must=must_conditions)

    try:
        results = await client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=qdrant_filter,
        )
        return results.points
    except Exception as e:
        logger.error(f"Error executing vector search in Qdrant: {e}")
        raise


async def get_collection_stats() -> dict[str, Any]:
    """Retrieve collection status and point count metrics for telemetry."""
    client = await get_qdrant_client()
    try:
        info = await client.get_collection(collection_name=COLLECTION_NAME)
        return {
            "status": str(info.status),
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
            "indexed_vectors_count": info.indexed_vectors_count,
        }
    except Exception as e:
        logger.error(f"Error fetching Qdrant collection stats: {e}")
        raise