from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncGenerator
from typing import Any

from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """
    Enterprise OpenAI Provider

    Responsibilities
    ----------------
    - Client lifecycle
    - Chat completions
    - Streaming completions
    - Embeddings
    - Usage tracking
    - Cost estimation
    - Health checks
    - Retry policies

    Future
    ------
    - Azure OpenAI
    - Model routing
    - Multi-provider failover
    """

    _client: AsyncOpenAI | None = None

    DEFAULT_CHAT_MODEL = os.getenv(
        "OPENAI_CHAT_MODEL",
        "gpt-4o"
    )

    DEFAULT_EMBEDDING_MODEL = os.getenv(
        "OPENAI_EMBEDDING_MODEL",
        "text-embedding-3-small"
    )

    DEFAULT_TEMPERATURE = float(
        os.getenv(
            "OPENAI_TEMPERATURE",
            "0.1"
        )
    )

    DEFAULT_MAX_TOKENS = int(
        os.getenv(
            "OPENAI_MAX_TOKENS",
            "4096"
        )
    )

    # =====================================================================
    # Client
    # =====================================================================

    @classmethod
    def get_client(cls) -> AsyncOpenAI:

        if cls._client is not None:
            return cls._client

        api_key = os.getenv(
            "OPENAI_API_KEY"
        )

        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured."
            )

        cls._client = AsyncOpenAI(
            api_key=api_key,
            base_url=os.getenv(
                "OPENAI_BASE_URL"
            ) or None,
            organization=os.getenv(
                "OPENAI_ORG_ID"
            ) or None,
            project=os.getenv(
                "OPENAI_PROJECT_ID"
            ) or None,
            timeout=float(
                os.getenv(
                    "OPENAI_TIMEOUT",
                    "30"
                )
            ),
            max_retries=int(
                os.getenv(
                    "OPENAI_MAX_RETRIES",
                    "3"
                )
            ),
        )

        logger.info(
            "OpenAI client initialized"
        )

        return cls._client

    @classmethod
    def reset_client(cls) -> None:

        cls._client = None

        logger.info(
            "OpenAI client reset"
        )

    # =====================================================================
    # Health
    # =====================================================================

    @classmethod
    async def verify_connection(cls) -> bool:

        try:

            client = cls.get_client()

            await client.models.list()

            return True

        except Exception:

            logger.exception(
                "OpenAI health check failed"
            )

            return False

    @classmethod
    async def health_check(
        cls
    ) -> dict[str, Any]:

        start = time.perf_counter()

        ok = await cls.verify_connection()

        elapsed = round(
            time.perf_counter() - start,
            3
        )

        return {
            "provider": "openai",
            "status":
                "healthy"
                if ok
                else "unhealthy",
            "latency_seconds":
                elapsed,
            "chat_model":
                cls.DEFAULT_CHAT_MODEL,
            "embedding_model":
                cls.DEFAULT_EMBEDDING_MODEL,
        }

    # =====================================================================
    # Chat
    # =====================================================================

    @classmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(
            multiplier=1,
            min=2,
            max=10,
        ),
        retry=retry_if_exception_type(
            Exception
        ),
        reraise=True,
    )
    async def complete(
        cls,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:

        client = cls.get_client()

        started = time.perf_counter()

        response = await (
            client.chat.completions.create(
                model=model
                or cls.DEFAULT_CHAT_MODEL,
                messages=messages,
                temperature=(
                    temperature
                    if temperature
                    is not None
                    else cls.DEFAULT_TEMPERATURE
                ),
                max_tokens=(
                    max_tokens
                    if max_tokens
                    is not None
                    else cls.DEFAULT_MAX_TOKENS
                ),
            )
        )

        duration = round(
            time.perf_counter()
            - started,
            3
        )

        return {
            "content":
                response.choices[0]
                .message.content,
            "usage":
                cls.usage_summary(
                    response.usage
                ),
            "model":
                response.model,
            "duration_seconds":
                duration,
        }

    # =====================================================================
    # Streaming Chat
    # =====================================================================

    @classmethod
    async def stream_completion(
        cls,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[str, None]:

        client = cls.get_client()

        stream = await (
            client.chat.completions.create(
                model=model
                or cls.DEFAULT_CHAT_MODEL,
                messages=messages,
                temperature=(
                    temperature
                    if temperature
                    is not None
                    else cls.DEFAULT_TEMPERATURE
                ),
                max_tokens=(
                    max_tokens
                    if max_tokens
                    is not None
                    else cls.DEFAULT_MAX_TOKENS
                ),
                stream=True,
            )
        )

        async for chunk in stream:

            delta = (
                chunk.choices[0]
                .delta.content
            )

            if delta:
                yield delta

    # =====================================================================
    # Embeddings
    # =====================================================================

    @classmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(
            multiplier=1,
            min=2,
            max=10,
        ),
        retry=retry_if_exception_type(
            Exception
        ),
        reraise=True,
    )
    async def create_embedding(cls, text: str) -> list[float]:
        client = cls.get_client()

        response = await (
            client.embeddings.create(
                model=
                cls.DEFAULT_EMBEDDING_MODEL,
                input=text,
            )
        )

        return (
            response.data[0]
            .embedding
        )

    @classmethod
    async def create_embeddings(
        cls,
        texts: list[str],
    ) -> list[list[float]]:

        if not texts:
            return []

        client = cls.get_client()

        response = await (
            client.embeddings.create(
                model=
                cls.DEFAULT_EMBEDDING_MODEL,
                input=texts,
            )
        )

        return [
            item.embedding
            for item in response.data
        ]

    # =====================================================================
    # Usage
    # =====================================================================

    @classmethod
    def usage_summary(
        cls,
        usage: Any | None,
    ) -> dict[str, int]:

        if not usage:

            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        return {
            "prompt_tokens":
                getattr(
                    usage,
                    "prompt_tokens",
                    0,
                ),
            "completion_tokens":
                getattr(
                    usage,
                    "completion_tokens",
                    0,
                ),
            "total_tokens":
                getattr(
                    usage,
                    "total_tokens",
                    0,
                ),
        }

    # =====================================================================
    # Costing
    # =====================================================================

    @classmethod
    def estimate_cost(
        cls,
        *,
        total_tokens: int,
        cost_per_1k_tokens: float,
    ) -> float:

        return round(
            (
                total_tokens
                / 1000
            )
            * cost_per_1k_tokens,
            6,
        )

    # =====================================================================
    # Configuration
    # =====================================================================

    @classmethod
    def configuration(
        cls
    ) -> dict[str, Any]:

        return {
            "provider": "openai",
            "chat_model":
                cls.DEFAULT_CHAT_MODEL,
            "embedding_model":
                cls.DEFAULT_EMBEDDING_MODEL,
            "timeout":
                os.getenv(
                    "OPENAI_TIMEOUT",
                    "30"
                ),
            "max_retries":
                os.getenv(
                    "OPENAI_MAX_RETRIES",
                    "3"
                ),
        }