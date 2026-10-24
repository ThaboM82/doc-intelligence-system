from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Optional

from backend.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class EmbeddingServiceError(Exception):
    """Custom exception raised when embedding generation fails."""
    pass


class EmbeddingService:
    """
    Enterprise-grade embedding service responsible for batch vector generation,
    rate-limit retries, input sanitization, and telemetry logging for RAG pipelines.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        batch_size: int = 64,
        max_concurrent: int = 5,
        max_retries: int = 3,
        initial_backoff: float = 2.0,
    ) -> None:
        self.model_name = model_name or OpenAIProvider.DEFAULT_EMBEDDING_MODEL
        self.batch_size = max(1, batch_size)
        self.max_concurrent = max(1, max_concurrent)
        self.max_retries = max(1, max_retries)
        self.initial_backoff = initial_backoff
        
        logger.info(
            f"Initialized EmbeddingService with model={self.model_name}, "
            f"batch_size={self.batch_size}, max_concurrent={self.max_concurrent}"
        )

    def _sanitize_texts(self, texts: List[str]) -> List[str]:
        """Sanitize and validate input text chunks before vectorization."""
        cleaned = []
        for i, text in enumerate(texts):
            if not text or not isinstance(text, str):
                logger.warning(f"Encountered empty or non-string text at index {i}. Replacing with empty string.")
                cleaned.append("")
                continue
            # Strip excessive whitespace / control characters that bloat tokens
            stripped = text.strip()
            if not stripped:
                cleaned.append("")
            else:
                cleaned.append(stripped)
        return cleaned

    async def _process_batch_with_retry(
        self, client, batch: List[str], batch_idx: int
    ) -> List[List[float]]:
        """Process a single batch with exponential backoff retry logic for transient API failures."""
        backoff = self.initial_backoff
        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                start_time = time.perf_counter()
                response = await client.embeddings.create(
                    model=self.model_name,
                    input=batch,
                )
                duration = time.perf_counter() - start_time
                
                # Extract embeddings and preserve order
                embeddings = [item.embedding for item in response.data]
                
                # Log telemetry usage if available
                usage = getattr(response, "usage", None)
                tokens_used = usage.total_tokens if usage else "unknown"
                logger.debug(
                    f"Batch {batch_idx} (size {len(batch)}) vectorized successfully in {duration:.3f}s. "
                    f"Tokens consumed: {tokens_used}"
                )
                return embeddings

            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Embedding generation attempt {attempt}/{self.max_retries} failed for batch {batch_idx}: {e}. "
                    f"Retrying in {backoff} seconds..."
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2.0  # Exponential backoff

        logger.error(f"All {self.max_retries} attempts failed for batch {batch_idx}.")
        raise EmbeddingServiceError(f"Failed to generate embeddings after {self.max_retries} retries: {last_exception}")

    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Generate vector embeddings for a list of text chunks in safe concurrent batches
        with rate-limit protection and performance monitoring.
        """
        if not texts:
            logger.info("generate_embeddings called with empty text list. Returning empty array.")
            return []

        sanitized_texts = self._sanitize_texts(texts)
        client = OpenAIProvider.get_client()
        semaphore = asyncio.Semaphore(self.max_concurrent)

        # Chunk input texts into configured batch sizes
        batches = [
            sanitized_texts[i : i + self.batch_size]
            for i in range(0, len(sanitized_texts), self.batch_size)
        ]

        logger.info(
            f"Starting vectorization pipeline: {len(sanitized_texts)} total items split across "
            f"{len(batches)} batches (max_concurrent={self.max_concurrent})."
        )

        overall_start = time.perf_counter()

        async def bounded_batch_task(batch_idx: int, batch_content: List[str]) -> List[List[float]]:
            async with semaphore:
                return await self._process_batch_with_retry(client, batch_content, batch_idx)

        # Execute batches concurrently under the semaphore limit
        tasks = [bounded_batch_task(idx, batch) for idx, batch in enumerate(batches)]
        
        try:
            batch_results = await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Embedding pipeline execution failed: {e}")
            raise EmbeddingServiceError(f"Embedding pipeline failed: {e}") from e

        # Flatten results back into a single contiguous list
        all_embeddings: List[List[float]] = []
        for result in batch_results:
            all_embeddings.extend(result)

        total_duration = time.perf_counter() - overall_start
        logger.info(
            f"Successfully generated {len(all_embeddings)} embeddings in {total_duration:.3f} seconds "
            f"({len(sanitized_texts) / max(total_duration, 0.001):.1f} items/sec)."
        )

        return all_embeddings

    async def generate_single_embedding(self, text: str) -> List[float]:
        """Generate a single vector embedding for search queries or quick ingestion."""
        embeddings = await self.generate_embeddings([text])
        if not embeddings:
            raise EmbeddingServiceError("Failed to generate embedding for single text input.")
        return embeddings[0]