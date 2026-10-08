"""
Extended LLM factory with circuit breaker, structured output, streaming,
retries, concurrency throttling, token telemetry, and TTL response caching.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncGenerator
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Opens after consecutive failures; cools down, then half-open probe."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_sec: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.opened_at: float | None = None

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if (
                self.opened_at is not None
                and (time.monotonic() - self.opened_at) >= self.recovery_timeout_sec
            ):
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN — allow one probe

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.opened_at = None

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()
            logger.warning("Circuit breaker OPEN after %s failures", self.failure_count)


class LLMCache:
    """Thread-safe / Async-safe in-memory TTL cache for LLM responses."""

    def __init__(self, ttl_sec: float = 300.0, max_size: int = 1000) -> None:
        self.ttl_sec = ttl_sec
        self.max_size = max_size
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    def _generate_key(self, prefix: str, messages: list[Any], kwargs: dict[str, Any], schema_name: str | None = None) -> str:
        serialized = []
        for msg in messages:
            if hasattr(msg, "content"):
                serialized.append(getattr(msg, "content"))
            else:
                serialized.append(str(msg))
        
        payload = {
            "prefix": prefix,
            "messages": serialized,
            "kwargs": str(sorted(kwargs.items())),
            "schema": schema_name,
        }
        raw_str = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    async def get(self, prefix: str, messages: list[Any], kwargs: dict[str, Any], schema_name: str | None = None) -> Any | None:
        key = self._generate_key(prefix, messages, kwargs, schema_name)
        async with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if (time.time() - timestamp) <= self.ttl_sec:
                    logger.debug("LLM Cache HIT for key %s...", key[:10])
                    return value
                else:
                    # Expired
                    del self._cache[key]
        return None

    async def set(self, prefix: str, messages: list[Any], kwargs: dict[str, Any], value: Any, schema_name: str | None = None) -> None:
        key = self._generate_key(prefix, messages, kwargs, schema_name)
        async with self._lock:
            if len(self._cache) >= self.max_size:
                # Evict oldest entry
                oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[key] = (value, time.time())


class LLMFactory:
    """
    Primary + fallback LLM wrapper with rate limiting, retries,
    circuit breaking, structured output, token telemetry, and caching.
    """

    def __init__(
        self,
        primary: Any,
        fallback: Any | None = None,
        max_retries: int = 2,
        base_backoff_sec: float = 0.5,
        circuit: CircuitBreaker | None = None,
        max_concurrent_requests: int = 10,
        enable_cache: bool = True,
        cache_ttl_sec: float = 300.0,
        max_cache_size: int = 1000,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.max_retries = max_retries
        self.base_backoff_sec = base_backoff_sec
        self.circuit = circuit or CircuitBreaker()
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        
        self.enable_cache = enable_cache
        self.cache = LLMCache(ttl_sec=cache_ttl_sec, max_size=max_cache_size) if enable_cache else None

    async def invoke(self, messages: list[Any], **kwargs: Any) -> Any:
        if self.cache:
            cached = await self.cache.get("invoke", messages, kwargs)
            if cached is not None:
                return cached

        async with self.semaphore:
            result = await self._run_with_resilience(
                lambda model: self._ainvoke(model, messages, **kwargs)
            )

        if self.cache:
            await self.cache.set("invoke", messages, kwargs, result)
        return result

    async def invoke_structured(
        self,
        messages: list[Any],
        schema: type[T],
        **kwargs: Any,
    ) -> T:
        schema_name = schema.__name__
        if self.cache:
            cached = await self.cache.get("structured", messages, kwargs, schema_name=schema_name)
            if cached is not None:
                return cached

        async def _call(model: Any) -> T:
            structured = model.with_structured_output(schema)
            return await self._ainvoke(structured, messages, **kwargs)

        async with self.semaphore:
            result = await self._run_with_resilience(_call)

        if self.cache:
            await self.cache.set("structured", messages, kwargs, result, schema_name=schema_name)
        return result

    async def stream_invoke(
        self, messages: list[Any], **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        async with self.semaphore:
            model = self._select_model()
            if not hasattr(model, "astream"):
                result = await self.invoke(messages, **kwargs)
                text = getattr(result, "content", str(result))
                yield text
                return

            try:
                async for chunk in model.astream(messages, **kwargs):
                    content = getattr(chunk, "content", None)
                    if content:
                        yield content if isinstance(content, str) else str(content)
                self.circuit.record_success()
            except Exception:
                self.circuit.record_failure()
                if self.fallback is not None and model is self.primary:
                    async for token in self.stream_invoke_fallback(messages, **kwargs):
                        yield token
                else:
                    raise

    async def stream_invoke_fallback(
        self, messages: list[Any], **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        if self.fallback is None:
            raise RuntimeError("No fallback LLM configured")
        async for chunk in self.fallback.astream(messages, **kwargs):
            content = getattr(chunk, "content", None)
            if content:
                yield content if isinstance(content, str) else str(content)

    def _select_model(self) -> Any:
        if self.circuit.allow_request():
            return self.primary
        if self.fallback is not None:
            logger.warning("Circuit open — using fallback LLM")
            return self.fallback
        raise RuntimeError("Circuit open and no fallback LLM available")

    async def _ainvoke(self, model: Any, messages: list[Any], **kwargs: Any) -> Any:
        start_time = time.perf_counter()
        if hasattr(model, "ainvoke"):
            response = await model.ainvoke(messages, **kwargs)
        else:
            response = await asyncio.to_thread(model.invoke, messages, **kwargs)
        
        duration = time.perf_counter() - start_time
        self._extract_and_log_telemetry(response, duration)
        return response

    def _extract_and_log_telemetry(self, response: Any, duration: float) -> None:
        usage_metadata = getattr(response, "usage_metadata", None)
        if not usage_metadata and hasattr(response, "response_metadata"):
            usage_metadata = response.response_metadata.get("token_usage")

        if usage_metadata:
            prompt_tokens = usage_metadata.get("prompt_tokens", 0)
            completion_tokens = usage_metadata.get("completion_tokens", 0)
            total_tokens = usage_metadata.get("total_tokens", prompt_tokens + completion_tokens)
            logger.info(
                "LLM call telemetry - duration: %.3fs | prompt_tokens: %d | completion_tokens: %d | total_tokens: %d",
                duration, prompt_tokens, completion_tokens, total_tokens
            )
        else:
            logger.info("LLM call telemetry - duration: %.3fs (token metadata unavailable)", duration)

    async def _run_with_resilience(self, call_fn) -> Any:
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            model = self._select_model()
            try:
                result = await call_fn(model)
                self.circuit.record_success()
                return result
            except Exception as exc:
                last_err = exc
                err_str = str(exc).lower()
                if any(code in err_str for code in ["400", "401", "403", "invalid_api_key", "bad_request"]):
                    logger.error("Unrecoverable LLM client error: %s", exc)
                    raise exc

                self.circuit.record_failure()
                logger.exception("LLM call failed (attempt %s/%s)", attempt + 1, self.max_retries + 1)
                
                if attempt < self.max_retries:
                    backoff = self.base_backoff_sec * (2 ** attempt)
                    await asyncio.sleep(backoff)
                    continue

                if self.fallback is not None and model is self.primary:
                    try:
                        logger.info("Max retries reached on primary model. Attempting fallback.")
                        result = await call_fn(self.fallback)
                        return result
                    except Exception as fb_exc:
                        last_err = fb_exc

        assert last_err is not None
        raise last_err


def build_default_factory(
    primary: Any,
    fallback: Any | None = None,
    **kwargs: Any,
) -> LLMFactory:
    return LLMFactory(primary=primary, fallback=fallback, **kwargs)