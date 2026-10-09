"""
Qdrant vector database client manager, collection initialization,
and async search/upsert operations.

Env vars:
  QDRANT_URL           – e.g. http://localhost:6333 or https://xxx.cloud.qdrant.io:6333
  QDRANT_API_KEY       – optional (required for Qdrant Cloud)
  QDRANT_COLLECTION    – collection name (default: document_intelligence)
  QDRANT_VECTOR_SIZE   – embedding dim (default: 1536)
  QDRANT_TIMEOUT       – request timeout seconds (default: 15)
  QDRANT_PREFER_GRPC   – "true"/"1" to prefer gRPC when available (default: false)
"""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import uuid4

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse, ResponseHandlingException

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "document_intelligence")
VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "1536"))
QDRANT_TIMEOUT = float(os.getenv("QDRANT_TIMEOUT", "15"))
PREFER_GRPC = os.getenv("QDRANT_PREFER_GRPC", "false").lower() in ("1", "true", "yes")

_qdrant_client: AsyncQdrantClient | None = None
_collection_ready: bool = False


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------

async def get_qdrant_client() -> AsyncQdrantClient:
    """Get or initialize the singleton AsyncQdrantClient instance."""
    global _qdrant_client
    if _qdrant_client is None:
        kwargs: dict[str, Any] = {
            "url": QDRANT_URL,
            "timeout": QDRANT_TIMEOUT,
            "prefer_grpc": PREFER_GRPC,
        }
        if QDRANT_API_KEY:
            kwargs["api_key"] = QDRANT_API_KEY

        logger.info(
            "Connecting to Qdrant at %s (api_key=%s, timeout=%.1fs)",
            QDRANT_URL,
            "set" if QDRANT_API_KEY else "none",
            QDRANT_TIMEOUT,
        )
        _qdrant_client = AsyncQdrantClient(**kwargs)
    return _qdrant_client


async def close_qdrant_client() -> None:
    """Close the singleton client (call from app shutdown)."""
    global _qdrant_client, _collection_ready
    if _qdrant_client is not None:
        try:
            await _qdrant_client.close()
            logger.info("Qdrant client closed")
        except Exception as e:
            logger.warning("Error closing Qdrant client: %s", e)
        finally:
            _qdrant_client = None
            _collection_ready = False


def is_collection_ready() -> bool:
    """Whether init_qdrant_collection() succeeded at least once this process."""
    return _collection_ready


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------

async def health_check(timeout: float | None = None) -> dict[str, Any]:
    """
    Lightweight connectivity check. Does not raise — returns status dict.
    Useful for /health endpoints without crashing the process.
    """
    try:
        client = await get_qdrant_client()
        collections = await client.get_collections()
        names = [c.name for c in collections.collections]
        return {
            "ok": True,
            "url": QDRANT_URL,
            "collections": names,
            "target_collection_exists": COLLECTION_NAME in names,
            "collection_ready": _collection_ready,
        }
    except Exception as e:
        logger.warning("Qdrant health_check failed: %s", e)
        return {
            "ok": False,
            "url": QDRANT_URL,
            "error": str(e),
            "error_type": type(e).__name__,
            "collection_ready": _collection_ready,
        }


# ---------------------------------------------------------------------------
# Collection init (soft-fail friendly)
# ---------------------------------------------------------------------------

async def init_qdrant_collection(*, raise_on_error: bool = True) -> bool:
    """
    Ensure the Qdrant collection exists with cosine vectors of VECTOR_SIZE.

    Args:
        raise_on_error: If False, log and return False instead of raising
                        (recommended for production lifespan so the API still boots).

    Returns:
        True if collection is ready, False if soft-failed.
    """
    global _collection_ready

    try:
        client = await get_qdrant_client()
        collections = await client.get_collections()
        exists = any(c.name == COLLECTION_NAME for c in collections.collections)

        if not exists:
            logger.info(
                "Creating Qdrant collection '%s' (dim=%s, distance=COSINE)...",
                COLLECTION_NAME,
                VECTOR_SIZE,
            )
            await client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("Collection '%s' created.", COLLECTION_NAME)
        else:
            try:
                info = await client.get_collection(collection_name=COLLECTION_NAME)
                cfg = info.config.params.vectors
                size = getattr(cfg, "size", None) if cfg is not None else None
                if size is not None and int(size) != VECTOR_SIZE:
                    logger.warning(
                        "Collection '%s' vector size is %s but QDRANT_VECTOR_SIZE=%s",
                        COLLECTION_NAME,
                        size,
                        VECTOR_SIZE,
                    )
            except Exception as e:
                logger.debug("Could not verify collection vector size: %s", e)

            logger.info("Qdrant collection '%s' already exists.", COLLECTION_NAME)

        _collection_ready = True
        return True

    except (UnexpectedResponse, ResponseHandlingException, OSError, ConnectionError) as e:
        logger.error("Failed to initialize Qdrant collection: %s", e)
        _collection_ready = False
        if raise_on_error:
            raise
        return False
    except Exception as e:
        logger.exception("Unexpected error during Qdrant init: %s", e)
        _collection_ready = False
        if raise_on_error:
            raise
        return False


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def build_point(
    vector: list[float],
    payload: dict[str, Any] | None = None,
    point_id: str | int | None = None,
) -> models.PointStruct:
    """Build a PointStruct with optional auto-generated UUID id."""
    return models.PointStruct(
        id=point_id if point_id is not None else str(uuid4()),
        vector=vector,
        payload=payload or {},
    )


async def upsert_documents(points: list[models.PointStruct]) -> bool:
    """Upsert document points (vectors + metadata payloads) into Qdrant."""
    if not points:
        logger.warning("upsert_documents called with empty points list")
        return True

    client = await get_qdrant_client()
    try:
        await client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=True,
        )
        logger.debug("Upserted %d points into '%s'", len(points), COLLECTION_NAME)
        return True
    except Exception as e:
        logger.error("Error upserting points into Qdrant: %s", e)
        raise


async def upsert_texts(
    texts: list[str],
    vectors: list[list[float]],
    metadatas: list[dict[str, Any]] | None = None,
    ids: list[str | int] | None = None,
) -> bool:
    """
    Convenience wrapper: build points from parallel lists and upsert.
    Lengths of texts, vectors, metadatas (if given), and ids (if given) must match.
    """
    if len(texts) != len(vectors):
        raise ValueError("texts and vectors must have the same length")
    if metadatas is not None and len(metadatas) != len(texts):
        raise ValueError("metadatas length must match texts")
    if ids is not None and len(ids) != len(texts):
        raise ValueError("ids length must match texts")

    points: list[models.PointStruct] = []
    for i, (text, vector) in enumerate(zip(texts, vectors)):
        payload = dict(metadatas[i]) if metadatas else {}
        payload.setdefault("text", text)
        pid = ids[i] if ids else None
        points.append(build_point(vector=vector, payload=payload, point_id=pid))

    return await upsert_documents(points)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

async def search_vectors(
    query_vector: list[float],
    top_k: int = 5,
    score_threshold: float | None = None,
    filter_conditions: dict[str, Any] | None = None,
    with_payload: bool = True,
    with_vectors: bool = False,
) -> list[models.ScoredPoint]:
    """Vector similarity search with optional payload filters and score threshold."""
    client = await get_qdrant_client()

    qdrant_filter = None
    if filter_conditions:
        must_conditions = [
            models.FieldCondition(
                key=k,
                match=models.MatchValue(value=v),
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
            with_payload=with_payload,
            with_vectors=with_vectors,
        )
        return list(results.points)
    except Exception as e:
        logger.error("Error executing vector search in Qdrant: %s", e)
        raise


# ---------------------------------------------------------------------------
# Delete / scroll / stats
# ---------------------------------------------------------------------------

async def delete_points(
    point_ids: list[str | int] | None = None,
    filter_conditions: dict[str, Any] | None = None,
) -> bool:
    """
    Delete by point IDs and/or payload filter.
    At least one of point_ids or filter_conditions must be provided.
    """
    if not point_ids and not filter_conditions:
        raise ValueError("Provide point_ids and/or filter_conditions")

    client = await get_qdrant_client()

    if point_ids and not filter_conditions:
        points_selector: models.PointsSelector = models.PointIdsList(points=point_ids)
    elif filter_conditions and not point_ids:
        must = [
            models.FieldCondition(key=k, match=models.MatchValue(value=v))
            for k, v in filter_conditions.items()
        ]
        points_selector = models.FilterSelector(filter=models.Filter(must=must))
    else:
        points_selector = models.PointIdsList(points=point_ids)  # type: ignore[arg-type]

    try:
        await client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=points_selector,
            wait=True,
        )
        return True
    except Exception as e:
        logger.error("Error deleting points from Qdrant: %s", e)
        raise


async def scroll_points(
    limit: int = 100,
    offset: str | int | None = None,
    filter_conditions: dict[str, Any] | None = None,
    with_payload: bool = True,
    with_vectors: bool = False,
) -> tuple[list[models.Record], str | int | None]:
    """
    Scroll (paginate) points. Returns (records, next_offset).
    next_offset is None when there are no more pages.
    """
    client = await get_qdrant_client()

    qdrant_filter = None
    if filter_conditions:
        must = [
            models.FieldCondition(key=k, match=models.MatchValue(value=v))
            for k, v in filter_conditions.items()
        ]
        qdrant_filter = models.Filter(must=must)

    try:
        records, next_offset = await client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=qdrant_filter,
            limit=limit,
            offset=offset,
            with_payload=with_payload,
            with_vectors=with_vectors,
        )
        return list(records), next_offset
    except Exception as e:
        logger.error("Error scrolling Qdrant points: %s", e)
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
            "collection_name": COLLECTION_NAME,
            "vector_size": VECTOR_SIZE,
        }
    except Exception as e:
        logger.error("Error fetching Qdrant collection stats: %s", e)
        raise


async def count_points(filter_conditions: dict[str, Any] | None = None) -> int:
    """Exact or filtered point count."""
    client = await get_qdrant_client()
    qdrant_filter = None
    if filter_conditions:
        must = [
            models.FieldCondition(key=k, match=models.MatchValue(value=v))
            for k, v in filter_conditions.items()
        ]
        qdrant_filter = models.Filter(must=must)

    try:
        result = await client.count(
            collection_name=COLLECTION_NAME,
            count_filter=qdrant_filter,
            exact=True,
        )
        return int(result.count)
    except Exception as e:
        logger.error("Error counting Qdrant points: %s", e)
        raise