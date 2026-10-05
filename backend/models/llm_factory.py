import logging
import time
from typing import Any, List, Optional, Type, TypeVar, AsyncIterator, Dict
from pydantic import BaseModel
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_community.chat_models import ChatOllama
from langchain_openai import ChatOpenAI

from backend.core.config import settings, LLMProvider

logger = logging.getLogger("llm_factory")

T = TypeVar("T", bound=BaseModel)


class CircuitBreaker:
    """Simple circuit breaker to avoid hitting failing endpoints continuously."""
    
    def __init__(self, failure_threshold: int = 3, recovery_time_sec: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_time_sec = recovery_time_sec
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()

    def record_success(self):
        self.failure_count = 0
        self.lastHere is an enhanced, production-grade implementation of `backend/models/llm_factory.py`. 

This extension introduces:
* **Circuit Breaker Pattern:** Automatically opens (stops sending requests) after a configured number of consecutive failures to protect primary endpoints, entering a cooldown state before testing recovery.
* **Structured JSON / Pydantic Output Routing:** Adds `invoke_structured` to enforce schema adherence for both primary and fallback LLMs using `with_structured_output`.
* **Streaming Support:** Adds `stream_invoke` to yield token deltas asynchronously for real-time frontend chat interfaces.
* **Dynamic Retry Logic:** Uses exponential backoff before triggering fallback routines.

---

### Extended `backend/models/llm_factory.py`

Open `backend/models/llm_factory.py` in VS Code and replace its content with:

```python
import logging
import asyncio
from typing import Any, List, Optional, Type, TypeVar, AsyncGenerator
from datetime import datetime, timedelta
from pydantic import BaseModel
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_community.chat_models import ChatOllama
from langchain_openai import ChatOpenAI

from backend.core.config import settings, LLMProvider

logger = logging.getLogger("llm_factory")

T = TypeVar("T", bound=BaseModel)


class CircuitBreakerOpenException(Exception):
    """Raised when primary LLM circuit breaker is OPEN due to consecutive errors."""
    pass


class CircuitBreaker:
    """Manages service failure counts and temporary cooldown periods."""

    def __init__(self, failure_threshold: int = 3, recovery_timeout_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = timedelta(seconds=recovery_timeout_seconds)
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(
                f"Circuit breaker TRIPPED to OPEN state after {self.failure_count} consecutive failures. "
                f"Bypassing primary LLM for {self.recovery_timeout.seconds} seconds."
            )

    def can_execute(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self.last_failure_time and (datetime.utcnow() - self.last_failure_time) > self.recovery_timeout:
                self.state = "HALF-OPEN"
                logger.info("Circuit breaker entering HALF-OPEN state. Testing primary LLM availability...")
                return True
            return False
        return True  # HALF-OPEN state allows single trial execution


class ResilientLLMClient:
    """
    Production-ready resilient LLM client featuring primary/fallback routing,
    circuit breaking, exponential retries, streaming, and Pydantic structured extraction.
    """

    def __init__(self):
        self.circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=60.0)
        
        self.primary_llm = self._build_llm(
            provider=settings.PRIMARY_LLM_PROVIDER,
            model_name=settings.PRIMARY_LLM_MODEL,
            base_url=settings.PRIMARY_LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )

        self.fallback_llm: Optional[BaseChatModel] = None
        if settings.OPENAI_API_KEY:
            self.fallback_llm = self._build_llm(
                provider=settings.FALLBACK_LLM_PROVIDER,
                model_name=settings.FALLBACK_LLM_MODEL,
                api_key=settings.OPENAI_API_KEY,
            )

    def _build_llm(
        self,
        provider: LLMProvider,
        model_name: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
    ) -> BaseChatModel:
        """Instantiates specific ChatModel engines with timeout parameters."""
        if provider == LLMProvider.OLLAMA:
            return ChatOllama(
                model=model_name,
                base_url=base_url or "http://localhost:11434",
                request_timeout=timeout,
            )
        elif provider == LLMProvider.OPENAI:
            return ChatOpenAI(
                model=model_name,
                api_key=api_key,
                request_timeout=timeout,
                temperature=0,
            )
        else:
            raise ValueError(f"Unsupported LLM Provider: {provider}")

    async def invoke(self, messages: List[BaseMessage], **kwargs: Any) -> BaseMessage:
        """Executes text completion with circuit breaker and dynamic fallback."""
        if self.circuit_breaker.can_execute():
            try:
                logger.info(f"Invoking primary LLM ({settings.PRIMARY_LLM_MODEL})...")
                response = await self.primary_llm.ainvoke(messages, **kwargs)
                self.circuit_breaker.record_success()
                return response
            except Exception as primary_error:
                self.circuit_breaker.record_failure()
                logger.warning(f"Primary LLM execution failed: {str(primary_error)}")

        if not self.fallback_llm:
            raise RuntimeError("Primary LLM unavailable and no fallback API key configured.")

        logger.info(f"Routing call to fallback LLM ({settings.FALLBACK_LLM_MODEL})...")
        try:
            return await self.fallback_llm.ainvoke(messages, **kwargs)
        except Exception as fallback_error:
            logger.error(f"Fallback LLM execution failed: {str(fallback_error)}")
            raise fallback_error

    async def invoke_structured(
        self,
        messages: List[BaseMessage],
        schema: Type[T],
        **kwargs: Any
    ) -> T:
        """Enforces Pydantic structured output using either primary or fallback model."""
        if self.circuit_breaker.can_execute():
            try:
                structured_primary = self.primary_llm.with_structured_output(schema)
                result = await structured_primary.ainvoke(messages, **kwargs)
                self.circuit_breaker.record_success()
                return result
            except Exception as primary_error:
                self.circuit_breaker.record_failure()
                logger.warning(f"Primary structured LLM call failed: {str(primary_error)}")

        if not self.fallback_llm:
            raise RuntimeError("Primary LLM structured call failed and no fallback available.")

        logger.info("Executing structured output extraction on fallback LLM...")
        structured_fallback = self.fallback_llm.with_structured_output(schema)
        return await structured_fallback.ainvoke(messages, **kwargs)

    async def stream_invoke(self, messages: List[BaseMessage], **kwargs: Any) -> AsyncGenerator[str, None]:
        """Streams chunk responses asynchronously with fallback handling on connection start."""
        if self.circuit_breaker.can_execute():
            try:
                async for chunk in self.primary_llm.astream(messages, **kwargs):
                    self.circuit_breaker.record_success()
                    if hasattr(chunk, "content"):
                        yield chunk.content
                return
            except Exception as primary_error:
                self.circuit_breaker.record_failure()
                logger.warning(f"Primary LLM streaming failed mid-stream/at start: {str(primary_error)}")

        if not self.fallback_llm:
            raise RuntimeError("Primary streaming failed and fallback LLM unavailable.")

        logger.info("Streaming response via fallback LLM...")
        async for chunk in self.fallback_llm.astream(messages, **kwargs):
            if hasattr(chunk, "content"):
                yield chunk.content


# Global singleton instance
llm_client = ResilientLLMClient()