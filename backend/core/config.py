"""
Central settings for Document Intelligence API.

All env reads should prefer this module so Render / local stay consistent.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_name: str = "Document Intelligence & Security API"
    api_version: str = "1.3.1"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"

    # --- HTTP ---
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = (
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"
    )
    rate_limit_max_requests: int = 120
    rate_limit_window_seconds: int = 60
    rate_limit_max_tracked_clients: int = 5000

    # --- Auth / RBAC ---
    jwt_secret: str = Field(default="dev-only-change-me", alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    admin_api_key: str = Field(default="", alias="ADMIN_API_KEY")
    auth_required: bool = False
    password_salt: str = "doc-intel-salt"

    # --- OpenAI / LLM ---
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_embed_model: str = "text-embedding-3-small"
    llm_model_name: str = Field(default="gpt-4o-mini", alias="LLM_MODEL_NAME")
    llm_primary_model: str = "gpt-4o"
    llm_fallback_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.1

    # --- Qdrant ---
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_api_key: str = Field(default="", alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(
        default="document_intelligence", alias="QDRANT_COLLECTION"
    )
    qdrant_vector_size: int = Field(default=1536, alias="QDRANT_VECTOR_SIZE")
    qdrant_timeout_sec: float = 15.0

    # --- RAG ---
    rag_default_top_k: int = 5
    rag_max_context_chars: int = 12000
    rag_max_chunk_chars: int = 1500
    rag_min_score: float | None = None

    # --- Ingest ---
    max_upload_bytes: int = 25 * 1024 * 1024
    ingest_chunk_size: int = 800
    ingest_chunk_overlap: int = 120
    ingest_embed_batch: int = 16
    ingest_upsert_batch: int = 64
    max_ingest_chars: int = 500_000
    upload_dir: str = "backend/data/uploads"
    quarantine_dir: str = "backend/data/quarantine"

    # --- Telemetry ---
    telemetry_buffer_size: int = 500
    telemetry_retention_events: int = 200

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _strip_origins(cls, v: object) -> object:
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allow_all_cors(self) -> bool:
        return "*" in self.cors_origin_list

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def require_openai(self) -> str:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        return self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    # Also accept QDRANT_COLLECTION_NAME as alias if set
    if not os.getenv("QDRANT_COLLECTION") and os.getenv("QDRANT_COLLECTION_NAME"):
        os.environ["QDRANT_COLLECTION"] = os.environ["QDRANT_COLLECTION_NAME"]
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()