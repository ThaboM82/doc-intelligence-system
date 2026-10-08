import asyncio
import logging
import time
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


class EmbeddingsManager(Embeddings):
    """Production-grade embeddings manager with batching, retries, and dimension validation."""

    def __init__(
        self,
        model_name: str = "text-embedding-3-small",
        dimensions: int = 1536,
        max_batch_size: int = 100,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
        api_key: str | None = None,
    ):
        self.model_name = model_name
        self.dimensions = dimensions
        self.max_batch_size = max_batch_size
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "dimensions": self.dimensions,
        }
        if api_key:
            kwargs["api_key"] = api_key

        self._client = OpenAIEmbeddings(**kwargs)

    def _clean_text(self, text: str) -> str:
        """Sanitizes text by replacing newlines and stripping trailing whitespace."""
        if not text or not isinstance(text, str):
            return ""
        return text.replace("\n", " ").strip()

    def _chunk_list(self, items: list[Any], chunk_size: int):
        """Yield successive chunks from a list."""
        for i in range(0, len(items), chunk_size):
            yield items[i : i + chunk_size]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Synchronously embeds document strings with batching and retries."""
        if not texts:
            return []

        cleaned_texts = [self._clean_text(t) for t in texts]
        results: list[list[float]] = []

        for batch_idx, batch in enumerate(self._chunk_list(cleaned_texts, self.max_batch_size)):
            for attempt in range(1, self.max_retries + 1):
                try:
                    embeddings = self._client.embed_documents(batch)
                    self._validate_dimensions(embeddings)
                    results.extend(embeddings)
                    break
                except Exception as e:
                    if attempt == self.max_retries:
                        logger.error(
                            f"Batch {batch_idx} failed after {self.max_retries} attempts: {e}"
                        )
                        raise e
                    sleep_time = self.backoff_factor ** attempt
                    logger.warning(
                        f"Retry {attempt}/{self.max_retries} for batch {batch_idx} after error: {e}. Waiting {sleep_time:.2f}s"
                    )
                    time.sleep(sleep_time)

        return results

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Asynchronously embeds document strings with batching and retries."""
        if not texts:
            return []

        cleaned_texts = [self._clean_text(t) for t in texts]
        results: list[list[float]] = []

        for batch_idx, batch in enumerate(self._chunk_list(cleaned_texts, self.max_batch_size)):
            for attempt in range(1, self.max_retries + 1):
                try:
                    embeddings = await self._client.aembed_documents(batch)
                    self._validate_dimensions(embeddings)
                    results.extend(embeddings)
                    break
                except Exception as e:
                    if attempt == self.max_retries:
                        logger.error(
                            f"Async batch {batch_idx} failed after {self.max_retries} attempts: {e}"
                        )
                        raise e
                    sleep_time = self.backoff_factor ** attempt
                    logger.warning(
                        f"Async retry {attempt}/{self.max_retries} for batch {batch_idx}: {e}. Waiting {sleep_time:.2f}s"
                    )
                    await asyncio.sleep(sleep_time)

        return results

    def embed_query(self, text: str) -> list[float]:
        """Synchronously embeds a query string."""
        cleaned = self._clean_text(text)
        if not cleaned:
            return []

        for attempt in range(1, self.max_retries + 1):
            try:
                vec = self._client.embed_query(cleaned)
                if len(vec) != self.dimensions:
                    raise ValueError(f"Expected dimension {self.dimensions}, got {len(vec)}")
                return vec
            except Exception as e:
                if attempt == self.max_retries:
                    logger.error(f"Query embedding failed: {e}")
                    raise e
                time.sleep(self.backoff_factor ** attempt)
        return []

    async def aembed_query(self, text: str) -> list[float]:
        """Asynchronously embeds a query string."""
        cleaned = self._clean_text(text)
        if not cleaned:
            return []

        for attempt in range(1, self.max_retries + 1):
            try:
                vec = await self._client.aembed_query(cleaned)
                if len(vec) != self.dimensions:
                    raise ValueError(f"Expected dimension {self.dimensions}, got {len(vec)}")
                return vec
            except Exception as e:
                if attempt == self.max_retries:
                    logger.error(f"Async query embedding failed: {e}")
                    raise e
                await asyncio.sleep(self.backoff_factor ** attempt)
        return []

    def _validate_dimensions(self, embeddings: list[list[float]]) -> None:
        """Verifies vector outputs match configured dimensionality."""
        for idx, emb in enumerate(embeddings):
            if len(emb) != self.dimensions:
                raise ValueError(
                    f"Vector at index {idx} has length {len(emb)}, expected {self.dimensions}"
                )
