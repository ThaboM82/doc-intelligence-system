"""
Enterprise Embedding Factory

Responsibilities
----------------
- Embedding provider selection
- Model configuration
- Dimension management
- Service instantiation

Supported Providers
-------------------
- OpenAI
- Azure OpenAI (future)
- Local Models (future)

Supported Models
----------------
- text-embedding-3-small
- text-embedding-3-large
"""

from __future__ import annotations

import os

from .embedding_service import EmbeddingService


class EmbeddingFactory:
    """
    Central entry point for embedding configuration.
    """

    SUPPORTED_MODELS = {
        "text-embedding-3-small": {
            "dimensions": 1536,
            "provider": "openai",
        },
        "text-embedding-3-large": {
            "dimensions": 3072,
            "provider": "openai",
        },
    }

    @classmethod
    def get_provider(cls) -> str:
        return os.getenv(
            "EMBEDDING_PROVIDER",
            "openai",
        )

    @classmethod
    def get_model_name(cls) -> str:
        return os.getenv(
            "EMBEDDING_MODEL",
            "text-embedding-3-large",
        )

    @classmethod
    def get_dimensions(cls) -> int:
        model = cls.get_model_name()

        config = cls.SUPPORTED_MODELS.get(
            model
        )

        if not config:
            raise ValueError(
                f"Unsupported embedding model: {model}"
            )

        return config["dimensions"]

    @classmethod
    def get_model_config(
        cls,
    ) -> dict:
        model = cls.get_model_name()

        config = cls.SUPPORTED_MODELS.get(
            model
        )

        if not config:
            raise ValueError(
                f"Unsupported embedding model: {model}"
            )

        return {
            "model": model,
            "provider": config["provider"],
            "dimensions": config["dimensions"],
        }

    @classmethod
    def create_service(
        cls,
    ) -> EmbeddingService:

        provider = cls.get_provider()

        if provider == "openai":
            return EmbeddingService()

        raise ValueError(
            f"Unsupported embedding provider: {provider}"
        )

    @classmethod
    def collection_config(
        cls,
    ) -> dict:
        """
        Useful when creating Qdrant collections.
        """

        return {
            "vector_size": cls.get_dimensions(),
            "distance": "Cosine",
            "provider": cls.get_provider(),
            "model": cls.get_model_name(),
        }

    @classmethod
    def validate_configuration(
        cls,
    ) -> dict:

        model = cls.get_model_name()

        if model not in cls.SUPPORTED_MODELS:

            return {
                "valid": False,
                "error":
                    f"Unsupported model {model}",
            }

        return {
            "valid": True,
            "provider":
                cls.get_provider(),
            "model": model,
            "dimensions":
                cls.get_dimensions(),
        }