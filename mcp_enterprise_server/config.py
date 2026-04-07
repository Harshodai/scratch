"""
Enterprise MCP Server Configuration
====================================
Centralizes all configuration for AWS, GOS DB, and guardrails.
Uses pydantic-settings for type-safe, environment-variable-driven config.

Environment variables override defaults. In production, inject secrets via
AWS Secrets Manager or HashiCorp Vault — never commit credentials to source.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class AWSRegion(str, Enum):
    US_EAST_1 = "us-east-1"
    US_WEST_2 = "us-west-2"
    EU_WEST_1 = "eu-west-1"
    AP_SOUTH_1 = "ap-south-1"


class PermissionLevel(str, Enum):
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# GOS DB Configuration  (Oracle-compatible internal JPMC database)
# ---------------------------------------------------------------------------
class GOSDBConfig(BaseSettings):
    """
    GOS DB is an internal JPMC Oracle-compatible database.
    Connection uses the oracledb (thin-mode) driver which doesn't need
    a local Oracle Client install.
    """
    model_config = SettingsConfigDict(env_prefix="GOS_DB_")

    host: str = Field(default="gosdb.internal.jpmc.com", description="GOS DB hostname")
    port: int = Field(default=1521, description="GOS DB listener port")
    service_name: str = Field(default="GOSDB_PROD", description="Oracle service name")
    username: str = Field(default="mcp_reader", description="Service account username")
    password: SecretStr = Field(default=SecretStr(""), description="Service account password")
    wallet_location: Optional[str] = Field(
        default=None,
        description="Path to Oracle wallet dir for mTLS. Preferred over password auth."
    )
    pool_min: int = Field(default=2, description="Min connections in pool")
    pool_max: int = Field(default=10, description="Max connections in pool")
    pool_increment: int = Field(default=1, description="Pool growth increment")
    permission_level: PermissionLevel = Field(
        default=PermissionLevel.READ_ONLY,
        description="Enforced permission level for MCP tools"
    )
    # Guardrails
    max_rows_per_query: int = Field(default=5000, description="Hard cap on rows returned")
    query_timeout_seconds: int = Field(default=30, description="Max query execution time")
    allowed_schemas: list[str] = Field(
        default=["APP_DATA", "ANALYTICS", "REPORTING"],
        description="Whitelisted schemas the MCP tools can access"
    )
    blocked_keywords: list[str] = Field(
        default=["DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE", "DELETE"],
        description="SQL keywords blocked in read-only mode"
    )

    @property
    def dsn(self) -> str:
        return f"{self.host}:{self.port}/{self.service_name}"


# ---------------------------------------------------------------------------
# AWS DynamoDB Configuration
# ---------------------------------------------------------------------------
class DynamoDBConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DYNAMODB_")

    region: AWSRegion = Field(default=AWSRegion.US_EAST_1)
    role_arn: Optional[str] = Field(
        default=None,
        description="IAM Role ARN to assume. Uses instance profile if None."
    )
    session_duration_seconds: int = Field(default=3600, description="STS session duration")
    endpoint_url: Optional[str] = Field(
        default=None,
        description="Custom endpoint for local DynamoDB or VPC endpoint"
    )
    permission_level: PermissionLevel = Field(default=PermissionLevel.READ_ONLY)
    # Guardrails
    allowed_tables: list[str] = Field(
        default=[],
        description="Whitelisted table names. Empty = all tables allowed."
    )
    max_items_per_scan: int = Field(default=1000, description="Limit items per scan/query")
    max_write_batch_size: int = Field(default=25, description="Max items per batch write")
    enable_streams: bool = Field(default=False, description="Allow DynamoDB streams access")


# ---------------------------------------------------------------------------
# AWS Athena Configuration
# ---------------------------------------------------------------------------
class AthenaConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATHENA_")

    region: AWSRegion = Field(default=AWSRegion.US_EAST_1)
    role_arn: Optional[str] = Field(default=None, description="IAM Role ARN to assume")
    session_duration_seconds: int = Field(default=3600)
    workgroup: str = Field(default="primary", description="Athena workgroup name")
    output_bucket: str = Field(
        default="s3://enterprise-mcp-athena-results/",
        description="S3 location for query results"
    )
    catalog: str = Field(default="AwsDataCatalog", description="Glue catalog name")
    database: str = Field(default="default", description="Default Glue database")
    permission_level: PermissionLevel = Field(default=PermissionLevel.READ_ONLY)
    # Guardrails
    allowed_databases: list[str] = Field(
        default=[],
        description="Whitelisted Glue databases. Empty = all allowed."
    )
    max_scan_bytes: int = Field(
        default=10 * 1024 * 1024 * 1024,  # 10 GB
        description="Max bytes scanned per query for cost control"
    )
    query_timeout_seconds: int = Field(default=300, description="Max Athena query wait time")
    blocked_keywords: list[str] = Field(
        default=["DROP", "TRUNCATE", "ALTER", "CREATE", "DELETE"],
        description="SQL keywords blocked in read-only mode"
    )


# ---------------------------------------------------------------------------
# AWS S3 Configuration
# ---------------------------------------------------------------------------
class S3Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="S3_")

    region: AWSRegion = Field(default=AWSRegion.US_EAST_1)
    role_arn: Optional[str] = Field(default=None, description="IAM Role ARN to assume")
    session_duration_seconds: int = Field(default=3600)
    permission_level: PermissionLevel = Field(default=PermissionLevel.READ_ONLY)
    # Guardrails
    allowed_buckets: list[str] = Field(
        default=[],
        description="Whitelisted S3 bucket names. Empty = all buckets the role can access."
    )
    allowed_prefixes: list[str] = Field(
        default=[],
        description="Whitelisted key prefixes. Empty = all prefixes allowed."
    )
    max_object_size_bytes: int = Field(
        default=50 * 1024 * 1024,  # 50 MB
        description="Max object size to retrieve (prevents downloading huge files)"
    )
    max_list_results: int = Field(
        default=1000,
        description="Max objects returned in list operations"
    )
    blocked_extensions: list[str] = Field(
        default=[".exe", ".dll", ".so", ".bin", ".zip", ".tar.gz"],
        description="File extensions blocked from download"
    )


# ---------------------------------------------------------------------------
# Rate Limiting & Observability Configuration
# ---------------------------------------------------------------------------
class GuardrailsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GUARDRAILS_")

    global_rate_limit: str = Field(
        default="60/minute",
        description="Global rate limit (python-limits format)"
    )
    per_tool_rate_limit: str = Field(
        default="20/minute",
        description="Per-tool rate limit"
    )
    enable_audit_logging: bool = Field(default=True)
    enable_pii_redaction: bool = Field(
        default=True,
        description="Redact PII patterns (SSN, credit card, etc.) from results"
    )
    max_result_size_bytes: int = Field(
        default=5 * 1024 * 1024,  # 5 MB
        description="Max size of any single tool result"
    )
    human_in_the_loop_operations: list[str] = Field(
        default=["write", "delete", "update"],
        description="Operations requiring human approval"
    )


# ---------------------------------------------------------------------------
# Root Configuration
# ---------------------------------------------------------------------------
class MCPServerConfig(BaseSettings):
    """Root configuration that aggregates all sub-configs."""
    model_config = SettingsConfigDict(env_prefix="MCP_SERVER_")

    server_name: str = Field(default="Enterprise RAG MCP Server")
    server_version: str = Field(default="1.0.0")
    transport: str = Field(
        default="streamable-http",
        description="MCP transport: stdio | sse | streamable-http"
    )
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    gosdb: GOSDBConfig = Field(default_factory=GOSDBConfig)
    dynamodb: DynamoDBConfig = Field(default_factory=DynamoDBConfig)
    athena: AthenaConfig = Field(default_factory=AthenaConfig)
    s3: S3Config = Field(default_factory=S3Config)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
