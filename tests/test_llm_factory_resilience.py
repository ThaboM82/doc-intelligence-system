"""
Comprehensive unit tests for CircuitBreaker, LLMCache, and LLMFactory resilience features.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel
import pytest

from backend.models.llm_factory import CircuitBreaker, CircuitState, LLMCache, LLMFactory


class DummySchema(BaseModel):
    answer: str
    confidence: float


def test_circuit_breaker_initial_state() -> None:
    """Verify circuit starts closed and allows requests."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout_sec=1.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True


def test_circuit_breaker_trips_and_recovers() -> None:
    """Verify circuit opens after threshold failures and enters half-open after timeout."""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout_sec=0.1)
    
    # Record failures up to threshold
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False

    # Wait for recovery timeout to elapse
    time.sleep(0.15)
    
    # Should allow one probe (HALF_OPEN)
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN

    # A success should fully close the circuit
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_llm_cache_set_and_get() -> None:
    """Verify cache stores values and retrieves them successfully."""
    cache = LLMCache(ttl_sec=60.0, max_size=10)
    messages = [{"role": "user", "content": "Hello"}]
    kwargs = {"temperature": 0.2}

    await cache.set("invoke", messages, kwargs, "Cached Response")
    
    result = await cache.get("invoke", messages, kwargs)
    assert result == "Cached Response"


@pytest.mark.asyncio
async def test_llm_cache_ttl_expiration() -> None:
    """Verify cached items expire after the configured TTL."""
    cache = LLMCache(ttl_sec=0.05, max_size=10)
    messages = [{"role": "user", "content": "Fast expire"}]
    
    await cache.set("invoke", messages, {}, "Val")
    assert await cache.get("invoke", messages, {}) == "Val"

    # Sleep past the TTL window
    await asyncio.sleep(0.08)
    
    expired = await cache.get("invoke", messages, {})
    assert expired is None


@pytest.mark.asyncio
async def test_llm_factory_caching_behavior() -> None:
    """Verify LLMFactory utilizes cache on repeated invoke calls."""
    primary_mock = MagicMock()
    primary_mock.ainvoke = AsyncMock(return_value=MagicMock(content="Generated Answer"))

    factory = LLMFactory(primary=primary_mock, enable_cache=True, cache_ttl_sec=10.0)
    messages = [{"role": "user", "content": "Explain quantum computing"}]

    # First call - cache miss (invokes model)
    res1 = await factory.invoke(messages)
    assert res1.content == "Generated Answer"
    assert primary_mock.ainvoke.call_count == 1

    # Second call - cache hit (bypasses model invocation)
    res2 = await factory.invoke(messages)
    assert res2.content == "Generated Answer"
    assert primary_mock.ainvoke.call_count == 1


@pytest.mark.asyncio
async def test_llm_factory_fallback_on_primary_failure() -> None:
    """Verify factory seamlessly switches to fallback model when primary fails."""
    primary_mock = MagicMock()
    primary_mock.ainvoke = AsyncMock(side_effect=RuntimeError("Primary Down"))

    fallback_mock = MagicMock()
    fallback_mock.ainvoke = AsyncMock(return_value=MagicMock(content="Fallback Answer"))

    factory = LLMFactory(primary=primary_mock, fallback=fallback_mock, max_retries=1)
    messages = [{"role": "user", "content": "Test fallback"}]

    result = await factory.invoke(messages)
    assert result.content == "Fallback Answer"
    assert fallback_mock.ainvoke.call_count == 1


@pytest.mark.asyncio
async def test_llm_factory_invoke_structured() -> None:
    """Verify structured output parsing and validation through Pydantic schemas."""
    structured_mock = MagicMock()
    structured_mock.ainvoke = AsyncMock(return_value=DummySchema(answer="Yes", confidence=0.95))

    primary_mock = MagicMock()
    primary_mock.with_structured_output.return_value = structured_mock

    factory = LLMFactory(primary=primary_mock, enable_cache=False)
    messages = [{"role": "user", "content": "Is Paris the capital of France?"}]

    result = await factory.invoke_structured(messages, schema=DummySchema)
    assert isinstance(result, DummySchema)
    assert result.answer == "Yes"
    assert result.confidence == 0.95
    primary_mock.with_structured_output.assert_called_once_with(DummySchema)


@pytest.mark.asyncio
async def test_llm_factory_streaming() -> None:
    """Verify streaming generator yields chunks correctly."""
    async def mock_stream(*args, **kwargs):
        yield MagicMock(content="Hello ")
        yield MagicMock(content="World!")

    primary_mock = MagicMock()
    primary_mock.astream = mock_stream

    factory = LLMFactory(primary=primary_mock)
    messages = [{"role": "user", "content": "Stream test"}]

    chunks = []
    async for token in factory.stream_invoke(messages):
        chunks.append(token)

    assert chunks == ["Hello ", "World!"]


@pytest.mark.asyncio
async def test_llm_factory_unrecoverable_client_error() -> None:
    """Verify 401/Client errors fail fast without retry loops or circuit trips."""
    primary_mock = MagicMock()
    primary_mock.ainvoke = AsyncMock(side_effect=ValueError("401 Unauthorized: invalid_api_key"))

    factory = LLMFactory(primary=primary_mock, max_retries=2)
    messages = [{"role": "user", "content": "Bad key"}]

    with pytest.raises(ValueError, match="401 Unauthorized"):
        await factory.invoke(messages)

    # Should only attempt once (fail fast)
    assert primary_mock.ainvoke.call_count == 1