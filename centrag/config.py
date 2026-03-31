"""
CentRAG Configuration — Type-safe, environment-driven settings.

Design Pattern: CONFIGURATION PATTERN (Pydantic Settings)
    - All config from environment variables
    - Validated at startup (fail fast if misconfigured)
    - Grouped by concern (db, redis, qdrant, aws, etc.)
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — loaded from .env file or environment."""

    model_config = SettingsConfigDict(
        env_prefix="CENTRAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Application ---
    env: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # --- PostgreSQL ---
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_db: str = "centrag"
    pg_user: str = "centrag"
    pg_password: str = "centrag_dev_only"
    pg_pool_min: int = 2
    pg_pool_max: int = 10

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pg_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600

    # --- Qdrant ---
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_collection: str = "documents"
    qdrant_cache_collection: str = "cache_responses"
    qdrant_memory_collection: str = "memories"

    # --- AWS ---
    aws_region: str = "us-east-1"
    s3_bucket: str = "centrag-documents-dev"
    sqs_queue_url: str = ""
    bedrock_embed_model: str = "amazon.titan-embed-text-v2:0"
    bedrock_llm_model: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    # --- Cohere ---
    cohere_api_key: str = ""

    # --- Langfuse ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # --- Security ---
    api_key_hash_pepper: str = "change-this-in-production"
    rate_limit_default: int = 60  # requests per minute per team

    # --- Feature Flags ---
    enable_docs_routes: bool = True
    enable_retrieval_routes: bool = True

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings — loaded once, cached forever."""
    return Settings()
