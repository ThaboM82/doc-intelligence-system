"""
backend/services/embeddings.py
──────────────────────────────
Shared text → vector helpers for RAG search and document ingest.

Same model + dimension must be used for:
  • query embedding (rag_service)
  • chunk embedding (ingest_service)
  • seed scripts

Default: OpenAI text-embedding-3-small → 1536-d (cosine in Qdrant).

Env:
  OPENAI_API_KEY
  OPENAI_EMBED_MODEL      default text-embedding-3-small
  QDRANT_VECTOR_SIZE      default 1536
  EMBED_BATCH_SIZE        default 16
  EMBED_MAX_CHARS         default 30000 (per input truncation)
  EMBED_MAX_RETRIES       default 3
  EMBED_RETRY_BASE_SEC    default 0.8
  EMBED_ALLOW_MOCK        default false
  EMBED_CACHE_SIZE        default 256 (in-process LRU for identical strings)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import struct
import time
from collections import OrderedDict
from typing import Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "1536"))
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "16"))
EMBED_MAX_CHARS = int(os.getenv("EMBED_MAX_CHARS", "30000"))
EMBED_MAX_RETRIES = int(os.getenv("EMBED_MAX_RETRIES", "3"))
EMBED_RETRY_BASE_SEC = float(os.getenv("EMBED_RETRY_BASE_SEC", "0.8"))
ALLOW_MOCK = os.getenv("EMBED_ALLOW_MOCK", "false").lower() in ("1", "true", "yes")
CACHE_SIZE = int(os.getenv("EMBED_CACHE_SIZE", "256"))


class EmbeddingError(RuntimeError):
    """Raised when a vector cannot be produced."""


# ---------------------------------------------------------------------------
# Small in-process LRU (optional speed-up for repeated queries)
# ---------------------------------------------------------------------------

class _EmbedCache:
    def __init__(self, maxsize: int) -> None:
        self.maxsize = max(0, maxsize)
        self._data: OrderedDict[str, list[float]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def _key(self, text: str) -> str:
        # Include model + dim so env changes don't serve stale vectors
        raw = f"{EMBED_MODEL}|{VECTOR_SIZE}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, text: str) -> list[float] | None:
        if self.maxsize <= 0:
            return None
        k = self._key(text)
        if k not in self._data:
            self.misses += 1
            return None
        self._data.move_to_end(k)
        self.hits += 1
        return list(self._data[k])

    def put(self, text: str, vector: list[float]) -> None:
        if self.maxsize <= 0:
            return
        k = self._key(text)
        self._data[k] = list(vector)
        self._data.move_to_end(k)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def stats(self) -> dict[str, int]:
        return {
            "size": len(self._data),
            "maxsize": self.maxsize,
            "hits": self.hits,
            "misses": self.misses,
        }

    def clear(self) -> None:
        self._data.clear()
        self.hits = 0
        self.misses = 0


_cache = _EmbedCache(CACHE_SIZE)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _require_api_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise EmbeddingError(
            "OPENAI_API_KEY is not set. "
            "Configure Render / .env, or set EMBED_ALLOW_MOCK=true for local tests only."
        )
    return key


def _normalize(vec: list[float]) -> list[float]:
    norm = sum(x * x for x in vec) ** 0.5
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def _mock_embed(text: str, dim: int = VECTOR_SIZE) -> list[float]:
    """Deterministic pseudo-vector for offline tests (not for production search)."""
    seed = hashlib.sha256((text or "").encode("utf-8")).digest()
    out: list[float] = []
    counter = 0
    while len(out) < dim:
        block = hashlib.sha256(seed + counter.to_bytes(4, "little")).digest()
        for i in range(0, len(block), 4):
            if len(out) >= dim:
                break
            if i + 4 <= len(block):
                (val,) = struct.unpack_from(">i", block, i)
            else:
                val = 0
            out.append(val / float(2**31))
        counter += 1
    return _normalize(out)


def _validate_dim(vec: list[float], *, context: str = "") -> list[float]:
    if len(vec) != VECTOR_SIZE:
        logger.warning(
            "Embedding dim %s != QDRANT_VECTOR_SIZE %s %s",
            len(vec),
            VECTOR_SIZE,
            context,
        )
    return vec


def _truncate(text: str) -> str:
    t = (text or "").strip() or " "
    if len(t) > EMBED_MAX_CHARS:
        return t[:EMBED_MAX_CHARS]
    return t


def _openai_embed_sync(texts: Sequence[str]) -> list[list[float]]:
    """
    Blocking OpenAI batch call with simple retries on rate limits / transient errors.
    """
    from openai import OpenAI

    client = OpenAI(api_key=_require_api_key())
    cleaned = [_truncate(t) for t in texts]
    last_exc: Exception | None = None

    for attempt in range(EMBED_MAX_RETRIES + 1):
        try:
            response = client.embeddings.create(input=cleaned, model=EMBED_MODEL)
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors = [_validate_dim(list(item.embedding), context=f"idx={item.index}") for item in ordered]
            return vectors
        except Exception as exc:
            last_exc = exc
            name = type(exc).__name__
            msg = str(exc).lower()
            retryable = (
                "rate" in msg
                or "timeout" in msg
                or "429" in msg
                or "500" in msg
                or "502" in msg
                or "503" in msg
                or "529" in msg
            )
            if attempt >= EMBED_MAX_RETRIES or not retryable:
                break
            delay = EMBED_RETRY_BASE_SEC * (2**attempt)
            logger.warning(
                "Embed retry %s/%s after %s: %s",
                attempt + 1,
                EMBED_MAX_RETRIES,
                name,
                exc,
            )
            time.sleep(delay)

    raise EmbeddingError(f"OpenAI embedding failed: {last_exc}") from last_exc


def _openai_embed_one_sync(text: str) -> list[float]:
    return _openai_embed_sync([text])[0]


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def embed_query(text: str, *, use_cache: bool = True) -> list[float]:
    """
    Embed a single query or chunk (async).

    Raises EmbeddingError on empty input or API failure.
    """
    text = (text or "").strip()
    if not text:
        raise EmbeddingError("Empty text for embedding")

    if use_cache:
        cached = _cache.get(text)
        if cached is not None:
            return cached

    if not os.getenv("OPENAI_API_KEY", "").strip():
        if ALLOW_MOCK:
            logger.warning("EMBED_ALLOW_MOCK: mock vector for query")
            vec = _mock_embed(text)
            _cache.put(text, vec)
            return vec
        raise EmbeddingError("OPENAI_API_KEY is required for embeddings")

    vec = await asyncio.to_thread(_openai_embed_one_sync, text)
    if use_cache:
        _cache.put(text, vec)
    return vec


async def embed_texts(
    texts: Sequence[str],
    *,
    use_cache: bool = True,
) -> list[list[float]]:
    """
    Embed many strings with batching. Order preserved.

    Cached strings are skipped in the API call and merged back in order.
    """
    if not texts:
        return []

    cleaned = [(t or "").strip() or " " for t in texts]
    results: list[list[float] | None] = [None] * len(cleaned)
    pending_idx: list[int] = []
    pending_txt: list[str] = []

    for i, t in enumerate(cleaned):
        if use_cache:
            hit = _cache.get(t)
            if hit is not None:
                results[i] = hit
                continue
        pending_idx.append(i)
        pending_txt.append(t)

    if not pending_txt:
        return [v for v in results if v is not None]  # all cached

    if not os.getenv("OPENAI_API_KEY", "").strip():
        if ALLOW_MOCK:
            logger.warning("EMBED_ALLOW_MOCK: %s mock vectors", len(pending_txt))
            for i, t in zip(pending_idx, pending_txt):
                vec = _mock_embed(t)
                results[i] = vec
                _cache.put(t, vec)
            return [v if v is not None else _mock_embed(" ") for v in results]
        raise EmbeddingError("OPENAI_API_KEY is required for embeddings")

    batch_size = max(1, EMBED_BATCH_SIZE)
    for offset in range(0, len(pending_txt), batch_size):
        batch = pending_txt[offset : offset + batch_size]
        batch_indices = pending_idx[offset : offset + batch_size]
        try:
            vectors = await asyncio.to_thread(_openai_embed_sync, batch)
        except EmbeddingError:
            raise
        except Exception as exc:
            logger.exception("Embed batch failed at pending offset %s", offset)
            raise EmbeddingError(f"Embedding batch failed: {exc}") from exc

        if len(vectors) != len(batch):
            raise EmbeddingError(
                f"Embedding count mismatch: got {len(vectors)} for batch of {len(batch)}"
            )
        for i, vec in zip(batch_indices, vectors):
            results[i] = vec
            if use_cache:
                _cache.put(cleaned[i], vec)

    out: list[list[float]] = []
    for v in results:
        if v is None:
            raise EmbeddingError("Internal error: missing embedding in result slot")
        out.append(v)
    return out


async def embed_query_safe(text: str) -> list[float] | None:
    """embed_query that returns None on failure instead of raising."""
    try:
        return await embed_query(text)
    except Exception as exc:
        logger.warning("embed_query_safe failed: %s", exc)
        return None


def clear_embed_cache() -> None:
    _cache.clear()


def embedding_config() -> dict[str, object]:
    """Diagnostics for health/admin (never exposes the API key)."""
    return {
        "model": EMBED_MODEL,
        "vector_size": VECTOR_SIZE,
        "batch_size": EMBED_BATCH_SIZE,
        "max_chars": EMBED_MAX_CHARS,
        "max_retries": EMBED_MAX_RETRIES,
        "openai_key_set": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "allow_mock": ALLOW_MOCK,
        "cache": _cache.stats(),
    }