import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

# --- Optional Provider Dependencies ---
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    from langchain_openai import OpenAIEmbeddings
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import cohere
    COHERE_AVAILABLE = True
except ImportError:
    COHERE_AVAILABLE = False

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

logger = logging.getLogger(__name__)


class EmbeddingConfig(BaseModel):
    provider: str = Field(
        default="sentence-transformers",
        description="Provider: 'sentence-transformers', 'openai', 'cohere', 'ollama', or 'huggingface'",
    )
    model_name: str = Field(default="BAAI/bge-small-en-v1.5", description="Model identifier")
    dimension: int = Field(default=384, description="Vector output dimension")
    device: str = Field(default="cpu", description="Device for local models ('cpu', 'cuda', 'mps')")
    batch_size: int = Field(default=32, description="Batch size for vector encoding")
    api_key: str | None = Field(default=None, description="API key for cloud providers")
    base_url: str | None = Field(default=None, description="Base URL for Ollama or custom endpoints")
    max_retries: int = Field(default=3, description="Maximum retry attempts on API failure")
    timeout: float = Field(default=30.0, description="Request timeout in seconds")
    enable_cache: bool = Field(default=True, description="Enable in-memory LRU query cache")
    cache_max_size: int = Field(default=1000, description="Max cached embeddings")


class EmbeddingManager:
    """Production-ready embedding manager supporting multiple local and cloud-based providers."""

    def __init__(
        self,
        config: EmbeddingConfig | None = None,
        fallback_config: EmbeddingConfig | None = None,
    ):
        self.config = config or EmbeddingConfig()
        self.fallback_config = fallback_config
        
        self._model: Any = None
        self._fallback_manager: EmbeddingManager | None = None
        self._cache: dict[str, list[float]] = {}
        
        self._initialize_model()

        if self.fallback_config:
            logger.info("Initializing fallback embedding manager...")
            self._fallback_manager = EmbeddingManager(config=self.fallback_config)

    def _initialize_model(self) -> None:
        provider = self.config.provider.lower()

        if provider == "sentence-transformers":
            if not SENTENCE_TRANSFORMERS_AVAILABLE:
                raise ImportError(
                    "sentence-transformers is required. Run `pip install sentence-transformers`."
                )
            logger.info(f"Loading SentenceTransformer: {self.config.model_name} on {self.config.device}")
            self._model = SentenceTransformer(self.config.model_name, device=self.config.device)
            self.config.dimension = self._model.get_sentence_embedding_dimension()

        elif provider == "openai":
            if not OPENAI_AVAILABLE:
                raise ImportError("langchain-openai is required. Run `pip install langchain-openai`.")
            logger.info(f"Loading OpenAIEmbeddings: {self.config.model_name}")
            kwargs: dict[str, Any] = {"model": self.config.model_name}
            if self.config.api_key:
                kwargs["openai_api_key"] = self.config.api_key
            self._model = OpenAIEmbeddings(**kwargs)
            
            # Auto-set dimension defaults if known
            if "3-small" in self.config.model_name:
                self.config.dimension = 1536
            elif "3-large" in self.config.model_name:
                self.config.dimension = 3072

        elif provider == "cohere":
            if not COHERE_AVAILABLE:
                raise ImportError("cohere package is required. Run `pip install cohere`.")
            logger.info(f"Loading Cohere client for model: {self.config.model_name}")
            self._model = cohere.AsyncClient(api_key=self.config.api_key, timeout=self.config.timeout)
            if "v3" in self.config.model_name:
                self.config.dimension = 1024

        elif provider in ("ollama", "huggingface"):
            if not HTTPX_AVAILABLE:
                raise ImportError("httpx is required for REST embedding providers. Run `pip install httpx`.")
            self.config.base_url = self.config.base_url or (
                "http://localhost:11434" if provider == "ollama" else "https://api-inference.huggingface.co"
            )
            logger.info(f"Configured REST provider '{provider}' using endpoint {self.config.base_url}")

        else:
            raise ValueError(f"Unsupported embedding provider '{provider}'.")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document strings with chunked batch processing and optional fallback."""
        if not texts:
            return []

        try:
            return await self._execute_embed_documents(texts)
        except Exception as e:
            logger.error(f"Primary embedding provider '{self.config.provider}' failed: {e}")
            if self._fallback_manager:
                logger.warning(f"Failing over to fallback provider '{self.fallback_config.provider}'")
                return await self._fallback_manager.embed_documents(texts)
            raise

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single search query string, leveraging LRU caching if enabled."""
        if not text:
            return [0.0] * self.config.dimension

        if self.config.enable_cache and text in self._cache:
            return self._cache[text]

        try:
            if self.config.provider == "sentence-transformers":
                vecs = await asyncio.to_thread(self._embed_st_sync, [text])
                res = vecs[0]
            elif self.config.provider == "openai":
                res = await self._model.aembed_query(text)
            elif self.config.provider == "cohere":
                response = await self._model.embed(
                    texts=[text],
                    model=self.config.model_name,
                    input_type="search_query",
                )
                res = response.embeddings[0]
            elif self.config.provider == "ollama":
                res = await self._embed_ollama_single(text)
            elif self.config.provider == "huggingface":
                res = await self._embed_hf_single(text)
            else:
                res = [0.0] * self.config.dimension

            if self.config.enable_cache:
                self._update_cache(text, res)

            return res

        except Exception as e:
            logger.error(f"Primary query embedding failed: {e}")
            if self._fallback_manager:
                return await self._fallback_manager.embed_query(text)
            raise

    async def _execute_embed_documents(self, texts: list[str]) -> list[list[float]]:
        provider = self.config.provider.lower()

        # Batch texts to respect payload limits
        results: list[list[float]] = []
        for i in range(0, len(texts), self.config.batch_size):
            batch = texts[i : i + self.config.batch_size]

            if provider == "sentence-transformers":
                batch_res = await asyncio.to_thread(self._embed_st_sync, batch)
            elif provider == "openai":
                batch_res = await self._model.aembed_documents(batch)
            elif provider == "cohere":
                response = await self._model.embed(
                    texts=batch,
                    model=self.config.model_name,
                    input_type="search_document",
                )
                batch_res = response.embeddings
            elif provider == "ollama":
                batch_res = await asyncio.gather(*[self._embed_ollama_single(t) for t in batch])
            elif provider == "huggingface":
                batch_res = await self._embed_hf_batch(batch)
            else:
                batch_res = []

            results.extend(batch_res)

        return results

    def _embed_st_sync(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(
            texts,
            batch_size=self.config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    async def _embed_ollama_single(self, text: str) -> list[float]:
        url = f"{self.config.base_url.rstrip('/')}/api/embeddings"
        payload = {"model": self.config.model_name, "prompt": text}
        
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json().get("embedding", [])

    async def _embed_hf_single(self, text: str) -> list[float]:
        res = await self._embed_hf_batch([text])
        return res[0] if res else []

    async def _embed_hf_batch(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.config.base_url.rstrip('/')}/pipeline/feature-extraction/{self.config.model_name}"
        headers = {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
        payload = {"inputs": texts, "options": {"wait_for_model": True}}

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    def _update_cache(self, key: str, value: list[float]) -> None:
        if len(self._cache) >= self.config.cache_max_size:
            # Simple FIFO eviction
            first_key = next(iter(self._cache))
            del self._cache[first_key]
        self._cache[key] = value

    def clear_cache(self) -> None:
        self._cache.clear()