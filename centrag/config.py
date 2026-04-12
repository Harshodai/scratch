"""
CentRAG Configuration — Type-safe, environment-driven settings.

Design Pattern: CONFIGURATION PATTERN (Pydantic Settings)
    - All config from environment variables
    - Validated at startup (fail fast if misconfigured)
    - Grouped by concern (db, redis, qdrant, aws, etc.)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Self

from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The WHY:
    Allows the system to "Fail Fast" at boot time. By using
    Pydantic for validation, we ensure that the system never
    starts if critical environment variables (e.g., PG_PASSWORD or
    QDRANT_HOST) are missing or type-mismatched.

    FAIL-FAST POLICY: In 'production' environment, critical infrastructure
    (Postgres, Redis, Qdrant) URLs are strictly forbidden from
    pointing to 'localhost' or '127.0.0.1'.
    """

    @model_validator(mode="after")
    def validate_production_infrastructure(self) -> Self:
        """Reject local infrastructure in production mode."""
        if self.env.lower() == "production":
            critical_urls = {
                "pg_host": self.pg_host,
                "redis_url": self.redis_url,
                "qdrant_host": self.qdrant_host,
            }
            for key, value in critical_urls.items():
                if any(local in value.lower() for local in ["localhost", "127.0.0.1"]):
                    raise ValueError(
                        f"CRITICAL CONFIG ERROR: {key}='{value}' is pointing to localhost "
                        "which is forbidden in PRODUCTION mode. Deploy production infrastructure "
                        "and update environment variables."
                    )
        return self

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
        """Postgres Data Source Name constructed from individual variables."""
        return f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_db}"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600

    # --- Qdrant ---
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_collection: str = "centrag"
    qdrant_cache_collection: str = "cache_responses"
    qdrant_memory_collection: str = "memories"
    qdrant_api_key: str = ""  # Qdrant Cloud API key
    qdrant_local_path: str = ""  # Path for Local Mode (serverless)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def qdrant_url(self) -> str:
        """Full Qdrant HTTP API endpoint."""
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

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

    # --- VECTORLESS path: PageIndex (tree-based reasoning retrieval) ---
    pageindex_model: str = "gpt-4o"  # LLM for tree building + navigation
    pageindex_add_summaries: bool = True  # Include node summaries in tree
    pageindex_add_node_text: bool = True  # Include full text in tree nodes
    data_dir: str = "data/documents"  # Filesystem storage for DocumentStore

    # --- Security ---
    api_key_hash_pepper: str = "change-this-in-production"
    rate_limit_default: int = 60  # requests per minute per team

    # --- Feature Flags & Provider Selection ---
    enable_docs_routes: bool = True
    enable_retrieval_routes: bool = True
    enable_pageindex: bool = True  # VECTORLESS path enabled
    enable_vector: bool = True  # VECTOR path (requires Qdrant)
    enable_mcp: bool = True  # Model Context Protocol integration

    # Advancements
    enable_contextual_retrieval: bool = False  # Pre-computation summary (Anthropic 2024)
    enable_contextual_compression: bool = False  # Retrieval-time LLM refinement

    # Provider selection: "noop", "bedrock", "openai"
    embedder_provider: str = "noop"
    # Provider selection: "noop", "bedrock", "openai"
    llm_provider: str = "noop"
    # Provider selection: "console", "otel"
    observability_provider: str = "console"

    # API Keys (Read from env directly if preferred, but exposed here for wiring)
    openai_api_key: str = ""
    llama_cloud_api_key: str = ""

    query_transformer_strategy: str = "llm_extractor"  # "llm_extractor" or "hyde"
    cors_origins: list[str] = ["*"]

    @property
    def is_production(self) -> bool:
        """Convenience helper to check if running in production mode."""
        return self.env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance.

    The WHY:
        Prevent reading the environment and re-instantiating the
        config object multiple times during a single process. This
        improves performance and ensures consistency across the
        application.
    """
    return Settings()
