"""
Qdrant provider — async access layer for the Document Intelligence API.

Env
---
  QDRANT_URL              default http://localhost:6333
  QDRANT_API_KEY          optional (required for Qdrant Cloud)
  QDRANT_COLLECTION       default document_intelligence
  QDRANT_VECTOR_SIZE      default 1536
  QDRANT_TIMEOUT          seconds, default 15
  QDRANT_PREFER_GRPC      true/1 to prefer gRPC when available

Usage
-----
    from backend.providers.qdrant_provider import (
        get_client,
        ensure_collection,
        search,
        upsert_points,
        delete_by_document_id,
        health,
        close,
    )
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Iterable

logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
COLLECTION = os.getenv("QDRANT_COLLECTION") or os.getenv(
    "QDRANT_COLLECTION_NAME", "document_intelligence"
)
VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "1536"))
TIMEOUT = float(os.getenv("QDRANT_TIMEOUT", "15"))
PREFER_GRPC = os.getenv("QDRANT_PREFER_GRPC", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
UPSERT_BATCH = int(os.getenv("QDRANT_UPSERT_BATCH", "64"))

_client: Any | None = None


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


def _build_client() -> Any:
    from qdrant_client import AsyncQdrantClient

    kwargs: dict[str, Any] = {
        "url": QDRANT_URL,
        "timeout": TIMEOUT,
    }
    if QDRANT_API_KEY:
        kwargs["api_key"] = QDRANT_API_KEY
    if PREFER_GRPC:
        kwargs["prefer_grpc"] = True
    return AsyncQdrantClient(**kwargs)


async def get_client() -> Any:
    """Singleton AsyncQdrantClient."""
    global _client
    if _client is None:
        _client = _build_client()
        logger.info(
            "Qdrant provider connected url=%s api_key=%s collection=%s",
            QDRANT_URL,
            "set" if QDRANT_API_KEY else "unset",
            COLLECTION,
        )
    return _client


async def close() -> None:
    """Close and clear the singleton client."""
    global _client
    if _client is None:
        return
    try:
        closer = getattr(_client, "close", None)
        if closer is not None:
            result = closer()
            if hasattr(result, "__await__"):
                await result
    except Exception as exc:
        logger.debug("Qdrant close: %s", exc)
    _client = None


def reset_client() -> None:
    """Drop singleton without awaiting close (tests)."""
    global _client
    _client = None


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


async def ensure_collection(
    *,
    collection_name: str | None = None,
    vector_size: int | None = None,
    distance: str = "Cosine",
    raise_on_error: bool = False,
) -> bool:
    """Create collection if missing. Returns True on success / already exists."""
    name = collection_name or COLLECTION
    size = vector_size or VECTOR_SIZE
    client = await get_client()

    try:
        from qdrant_client.http import models

        collections = await client.get_collections()
        exists = any(c.name == name for c in collections.collections)
        if exists:
            logger.debug("Qdrant collection already exists: %s", name)
            return True

        dist = getattr(models.Distance, distance.upper(), models.Distance.COSINE)
        await client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(size=size, distance=dist),
        )
        # Helpful payload indexes for document management filters
        for field in ("document_id", "doc_id", "file_name", "source_file"):
            try:
                await client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass

        logger.info(
            "Created Qdrant collection '%s' size=%s distance=%s",
            name,
            size,
            distance,
        )
        return True
    except Exception as exc:
        logger.error("ensure_collection failed: %s", exc)
        if raise_on_error:
            raise
        return False


async def collection_exists(collection_name: str | None = None) -> bool:
    name = collection_name or COLLECTION
    client = await get_client()
    collections = await client.get_collections()
    return any(c.name == name for c in collections.collections)


async def get_collection_info(collection_name: str | None = None) -> dict[str, Any]:
    """Return points/vectors stats for telemetry."""
    name = collection_name or COLLECTION
    client = await get_client()
    info = await client.get_collection(collection_name=name)
    return {
        "status": str(getattr(info, "status", "")),
        "vectors_count": getattr(info, "vectors_count", None),
        "points_count": getattr(info, "points_count", None),
        "indexed_vectors_count": getattr(info, "indexed_vectors_count", None),
        "collection_name": name,
        "vector_size": VECTOR_SIZE,
    }


# ---------------------------------------------------------------------------
# Filters / helpers
# ---------------------------------------------------------------------------


def _match_filter(conditions: dict[str, Any] | None) -> Any | None:
    if not conditions:
        return None
    from qdrant_client.http import models

    must = [
        models.FieldCondition(key=k, match=models.MatchValue(value=v))
        for k, v in conditions.items()
    ]
    return models.Filter(must=must)


def point_id(doc_id: str, chunk_idx: int) -> str:
    """Stable UUID5 point id from document_id + chunk index."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{chunk_idx}"))


# ---------------------------------------------------------------------------
# Search / scroll / count
# ---------------------------------------------------------------------------


async def search(
    query_vector: list[float],
    *,
    top_k: int = 5,
    score_threshold: float | None = None,
    filter_conditions: dict[str, Any] | None = None,
    collection_name: str | None = None,
    with_payload: bool = True,
) -> list[Any]:
    """Vector similarity search; returns list of ScoredPoint-like objects."""
    name = collection_name or COLLECTION
    client = await get_client()
    qfilter = _match_filter(filter_conditions)

    try:
        results = await client.query_points(
            collection_name=name,
            query=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=qfilter,
            with_payload=with_payload,
        )
        return list(getattr(results, "points", None) or [])
    except Exception as exc:
        logger.error("Qdrant search failed: %s", exc)
        raise


async def scroll(
    *,
    limit: int = 100,
    offset: Any | None = None,
    filter_conditions: dict[str, Any] | None = None,
    collection_name: str | None = None,
    with_payload: bool = True,
    with_vectors: bool = False,
) -> tuple[list[Any], Any]:
    """Scroll points; returns (points, next_offset)."""
    name = collection_name or COLLECTION
    client = await get_client()
    qfilter = _match_filter(filter_conditions)

    points, next_offset = await client.scroll(
        collection_name=name,
        scroll_filter=qfilter,
        limit=limit,
        offset=offset,
        with_payload=with_payload,
        with_vectors=with_vectors,
    )
    return list(points or []), next_offset


async def scroll_all(
    *,
    batch: int = 250,
    filter_conditions: dict[str, Any] | None = None,
    collection_name: str | None = None,
    max_points: int = 50_000,
) -> list[Any]:
    """Scroll until exhausted or max_points."""
    out: list[Any] = []
    offset = None
    while len(out) < max_points:
        points, offset = await scroll(
            limit=min(batch, max_points - len(out)),
            offset=offset,
            filter_conditions=filter_conditions,
            collection_name=collection_name,
        )
        out.extend(points)
        if offset is None or not points:
            break
    return out


async def count_points(
    filter_conditions: dict[str, Any] | None = None,
    *,
    collection_name: str | None = None,
    exact: bool = True,
) -> int:
    name = collection_name or COLLECTION
    client = await get_client()
    qfilter = _match_filter(filter_conditions)
    result = await client.count(
        collection_name=name,
        count_filter=qfilter,
        exact=exact,
    )
    return int(result.count)


# ---------------------------------------------------------------------------
# Upsert / delete
# ---------------------------------------------------------------------------


async def upsert_points(
    points: list[dict[str, Any]],
    *,
    collection_name: str | None = None,
    batch_size: int | None = None,
) -> int:
    """
    Upsert points shaped as::

        {"id": str|int, "vector": list[float], "payload": dict}

    Returns number of points submitted.
    """
    if not points:
        return 0

    from qdrant_client.http import models

    name = collection_name or COLLECTION
    client = await get_client()
    bs = batch_size or UPSERT_BATCH
    total = 0

    for i in range(0, len(points), bs):
        chunk = points[i : i + bs]
        records = [
            models.PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p.get("payload") or {},
            )
            for p in chunk
        ]
        await client.upsert(collection_name=name, points=records)
        total += len(records)

    return total


async def upsert_chunks(
    document_id: str,
    filename: str,
    chunks: Iterable[str],
    vectors: list[list[float]],
    *,
    extra_payload: dict[str, Any] | None = None,
    collection_name: str | None = None,
) -> int:
    """
    Convenience: map parallel chunk texts + vectors into points with
    document_id / file_name / chunk_index payload.
    """
    texts = list(chunks)
    if len(texts) != len(vectors):
        raise ValueError(
            f"chunks ({len(texts)}) and vectors ({len(vectors)}) length mismatch"
        )

    base = dict(extra_payload or {})
    points: list[dict[str, Any]] = []
    for idx, (text, vector) in enumerate(zip(texts, vectors)):
        payload = {
            **base,
            "document_id": document_id,
            "doc_id": document_id,
            "file_name": filename,
            "source_file": filename,
            "chunk_index": idx,
            "text": text,
            "content": text,
        }
        points.append(
            {
                "id": point_id(document_id, idx),
                "vector": vector,
                "payload": payload,
            }
        )
    return await upsert_points(points, collection_name=collection_name)


async def delete_by_ids(
    ids: list[Any],
    *,
    collection_name: str | None = None,
) -> int:
    if not ids:
        return 0
    from qdrant_client.http import models

    name = collection_name or COLLECTION
    client = await get_client()
    await client.delete(
        collection_name=name,
        points_selector=models.PointIdsList(points=ids),
    )
    return len(ids)


async def delete_by_filter(
    filter_conditions: dict[str, Any],
    *,
    collection_name: str | None = None,
) -> None:
    from qdrant_client.http import models

    name = collection_name or COLLECTION
    client = await get_client()
    qfilter = _match_filter(filter_conditions)
    if qfilter is None:
        raise ValueError("filter_conditions required for delete_by_filter")
    await client.delete(
        collection_name=name,
        points_selector=models.FilterSelector(filter=qfilter),
    )


async def delete_by_document_id(
    document_id: str,
    *,
    collection_name: str | None = None,
) -> int:
    """
    Delete all points for a document_id.
    Tries payload filter on document_id / doc_id, then scroll fallback.
    Returns approximate points deleted (0 if filter-only path).
    """
    document_id = (document_id or "").strip()
    if not document_id:
        raise ValueError("document_id required")

    name = collection_name or COLLECTION
    for key in ("document_id", "doc_id"):
        try:
            await delete_by_filter({key: document_id}, collection_name=name)
            return 0  # filter delete — count unknown without prior count
        except Exception as exc:
            logger.debug("filter delete key=%s failed: %s", key, exc)

    # Fallback: scroll + id delete
    points = await scroll_all(
        filter_conditions=None,
        collection_name=name,
    )
    ids: list[Any] = []
    for p in points:
        payload = getattr(p, "payload", None) or {}
        if not isinstance(payload, dict):
            continue
        if (
            str(payload.get("document_id") or "") == document_id
            or str(payload.get("doc_id") or "") == document_id
        ):
            ids.append(getattr(p, "id"))
    if not ids:
        return 0
    return await delete_by_ids(ids, collection_name=name)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def health() -> dict[str, Any]:
    """Lightweight reachability + collection presence probe."""
    t0 = time.perf_counter()
    out: dict[str, Any] = {
        "ok": False,
        "url": QDRANT_URL,
        "collection": COLLECTION,
        "collection_ready": False,
        "latency_ms": None,
        "error": None,
    }
    try:
        client = await get_client()
        collections = await client.get_collections()
        names = {c.name for c in collections.collections}
        out["ok"] = True
        out["collection_ready"] = COLLECTION in names
    except Exception as exc:
        out["error"] = str(exc)[:300]
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return out


__all__ = [
    "QDRANT_URL",
    "COLLECTION",
    "VECTOR_SIZE",
    "get_client",
    "close",
    "reset_client",
    "ensure_collection",
    "collection_exists",
    "get_collection_info",
    "point_id",
    "search",
    "scroll",
    "scroll_all",
    "count_points",
    "upsert_points",
    "upsert_chunks",
    "delete_by_ids",
    "delete_by_filter",
    "delete_by_document_id",
    "health",
]