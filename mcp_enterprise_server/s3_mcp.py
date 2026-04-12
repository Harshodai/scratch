"""
AWS S3 MCP Connection
======================
MCP tools for interacting with Amazon S3 with enterprise guardrails.

Architecture:
  ┌─────────────┐    ┌────────────┐    ┌──────────────┐    ┌──────────────┐
  │ MCP Client  │───▶│ MCP Server │───▶│  Guardrails  │───▶│     S3       │
  │ (AI Agent)  │    │ (FastMCP)  │    │  (validate)  │    │ (via boto3)  │
  └─────────────┘    └────────────┘    └──────────────┘    └──────────────┘

Security layers:
  1. IAM Role-Based Access    — STS AssumeRole with short-lived creds
  2. Bucket Whitelisting      — Only approved buckets are accessible
  3. Prefix Whitelisting      — Limit access to specific key prefixes
  4. Extension Blocking       — Block download of dangerous file types
  5. Size Limit Enforcement   — Prevent downloading excessively large objects
  6. Permission Level Control — READ_ONLY blocks PutObject, DeleteObject, etc.
  7. PII Redaction            — Strips PII from text-based object content
  8. Rate Limiting + Audit    — Per-caller throttling and invocation logging

Tools:
  - list_s3_buckets   → List accessible S3 buckets
  - list_s3_objects   → List objects in a bucket with optional prefix filter
  - get_s3_object     → Download and return object content (text-based only)
  - get_s3_metadata   → Get object metadata without downloading content
  - search_s3_objects → Search objects by prefix pattern across a bucket

Design Decisions:
  - Only text-based content is returned to the AI (JSON, CSV, TXT, MD, etc.)
  - Binary files return metadata only (size, type, last modified)
  - All operations use asyncio.to_thread for non-blocking execution
  - Large object content is truncated with a warning
"""

from __future__ import annotations

import asyncio
import json
import posixpath
import time
from typing import TYPE_CHECKING, Any

import structlog

from mcp_enterprise_server.aws_credentials import AWSCredentialManager
from mcp_enterprise_server.guardrails import (
    audit_log,
    cap_result_size,
    check_rate_limit,
    redact_pii,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context, FastMCP
    from mcp.server.session import ServerSession

    from mcp_enterprise_server.config import S3Config

logger = structlog.get_logger("s3_mcp")


# ---------------------------------------------------------------------------
# Content Type Classification
# ---------------------------------------------------------------------------
_TEXT_CONTENT_TYPES = {
    "application/json",
    "text/plain",
    "text/csv",
    "text/html",
    "text/xml",
    "text/markdown",
    "application/xml",
    "application/yaml",
    "text/yaml",
    "application/x-yaml",
    "text/tab-separated-values",
}

_TEXT_EXTENSIONS = {
    ".json",
    ".csv",
    ".txt",
    ".md",
    ".xml",
    ".yaml",
    ".yml",
    ".html",
    ".htm",
    ".log",
    ".tsv",
    ".sql",
    ".py",
    ".js",
    ".ts",
    ".java",
    ".go",
    ".rs",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".sh",
    ".bat",
    ".ps1",
    ".dockerfile",
}


def _is_text_content(key: str, content_type: str | None) -> bool:
    """Determine if an S3 object contains text-based content."""
    if content_type and content_type.lower() in _TEXT_CONTENT_TYPES:
        return True
    ext = posixpath.splitext(key)[1].lower()
    return ext in _TEXT_EXTENSIONS


# ---------------------------------------------------------------------------
# S3 Client Wrapper
# ---------------------------------------------------------------------------
class S3Client:
    """
    Managed S3 client with credential rotation and guardrails.
    """

    def __init__(self, config: S3Config):
        self._config = config
        self._cred_manager = AWSCredentialManager(
            region=config.region.value,
            role_arn=config.role_arn,
            session_name="MCP_S3_Session",
            session_duration=config.session_duration_seconds,
        )

    def _get_client(self):
        return self._cred_manager.get_client("s3")

    def _validate_bucket(self, bucket: str) -> None:
        """Validate bucket is in the whitelist."""
        if self._config.allowed_buckets and bucket not in self._config.allowed_buckets:
            raise PermissionError(f"Bucket '{bucket}' is not in the allowed list: {self._config.allowed_buckets}")

    def _validate_prefix(self, key: str) -> None:
        """Validate key prefix is in the whitelist (if configured)."""
        if not self._config.allowed_prefixes:
            return  # No prefix restriction
        for prefix in self._config.allowed_prefixes:
            if key.startswith(prefix):
                return
        raise PermissionError(f"Key '{key}' does not match any allowed prefix: {self._config.allowed_prefixes}")

    def _validate_extension(self, key: str) -> None:
        """Block download of dangerous file types."""
        ext = posixpath.splitext(key)[1].lower()
        if ext in self._config.blocked_extensions:
            raise PermissionError(f"File extension '{ext}' is blocked for security reasons.")

    # -- List Buckets --
    async def list_buckets(self) -> list[dict[str, Any]]:
        """List S3 buckets, filtered by whitelist if configured."""

        def _list():
            client = self._get_client()
            response = client.list_buckets()
            buckets = response.get("Buckets", [])

            result = []
            for b in buckets:
                name = b["Name"]
                if self._config.allowed_buckets and name not in self._config.allowed_buckets:
                    continue
                result.append(
                    {
                        "name": name,
                        "creation_date": b.get("CreationDate", "").isoformat() if b.get("CreationDate") else "",
                    }
                )
            return sorted(result, key=lambda x: x["name"])

        return await asyncio.to_thread(_list)

    # -- List Objects --
    async def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        max_results: int = 100,
    ) -> dict[str, Any]:
        """List objects in a bucket with optional prefix filter."""
        self._validate_bucket(bucket)

        effective_max = min(max_results, self._config.max_list_results)

        def _list():
            client = self._get_client()
            params: dict[str, Any] = {
                "Bucket": bucket,
                "MaxKeys": effective_max,
            }
            if prefix:
                params["Prefix"] = prefix

            response = client.list_objects_v2(**params)
            objects = []
            for obj in response.get("Contents", []):
                objects.append(
                    {
                        "key": obj["Key"],
                        "size_bytes": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else "",
                        "storage_class": obj.get("StorageClass", "STANDARD"),
                    }
                )

            return {
                "objects": objects,
                "count": len(objects),
                "truncated": response.get("IsTruncated", False),
                "prefix": prefix,
            }

        return await asyncio.to_thread(_list)

    # -- Get Object Content --
    async def get_object(
        self,
        bucket: str,
        key: str,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        """
        Get object content (text-based) or metadata (binary).

        Text files: Returns content as string (truncated if too large).
        Binary files: Returns metadata only (size, type, last modified).
        """
        self._validate_bucket(bucket)
        self._validate_prefix(key)
        self._validate_extension(key)

        effective_max = max_bytes or self._config.max_object_size_bytes

        def _get():
            client = self._get_client()

            # First, HEAD to check size and content type
            head = client.head_object(Bucket=bucket, Key=key)
            content_type = head.get("ContentType", "application/octet-stream")
            size = head.get("ContentLength", 0)

            metadata = {
                "key": key,
                "bucket": bucket,
                "size_bytes": size,
                "content_type": content_type,
                "last_modified": head["LastModified"].isoformat() if head.get("LastModified") else "",
                "etag": head.get("ETag", "").strip('"'),
                "metadata": head.get("Metadata", {}),
            }

            # Binary files: return metadata only
            if not _is_text_content(key, content_type):
                return {
                    **metadata,
                    "content": None,
                    "note": "Binary file — only metadata returned. Use get_s3_metadata for binary file info.",
                }

            # Size guard
            if size > effective_max:
                return {
                    **metadata,
                    "content": None,
                    "note": f"Object too large ({size:,} bytes). Max allowed: {effective_max:,} bytes.",
                }

            # Download text content
            response = client.get_object(Bucket=bucket, Key=key)
            body = response["Body"].read()

            try:
                content = body.decode("utf-8")
            except UnicodeDecodeError:
                content = body.decode("latin-1", errors="replace")

            return {
                **metadata,
                "content": content,
            }

        return await asyncio.to_thread(_get)

    # -- Get Object Metadata --
    async def get_metadata(self, bucket: str, key: str) -> dict[str, Any]:
        """Get object metadata without downloading content."""
        self._validate_bucket(bucket)

        def _head():
            client = self._get_client()
            head = client.head_object(Bucket=bucket, Key=key)
            return {
                "key": key,
                "bucket": bucket,
                "size_bytes": head.get("ContentLength", 0),
                "content_type": head.get("ContentType", "unknown"),
                "last_modified": head["LastModified"].isoformat() if head.get("LastModified") else "",
                "etag": head.get("ETag", "").strip('"'),
                "storage_class": head.get("StorageClass", "STANDARD"),
                "metadata": head.get("Metadata", {}),
                "version_id": head.get("VersionId"),
            }

        return await asyncio.to_thread(_head)

    # -- Search Objects by Pattern --
    async def search_objects(
        self,
        bucket: str,
        prefix: str = "",
        suffix: str = "",
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """Search objects by prefix and/or suffix (extension)."""
        self._validate_bucket(bucket)

        effective_max = min(max_results, self._config.max_list_results)

        def _search():
            client = self._get_client()
            paginator = client.get_paginator("list_objects_v2")

            params: dict[str, Any] = {"Bucket": bucket}
            if prefix:
                params["Prefix"] = prefix

            results = []
            for page in paginator.paginate(**params):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if suffix and not key.endswith(suffix):
                        continue
                    results.append(
                        {
                            "key": key,
                            "size_bytes": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else "",
                        }
                    )
                    if len(results) >= effective_max:
                        return results
            return results

        return await asyncio.to_thread(_search)


# ---------------------------------------------------------------------------
# Tool Functions
# ---------------------------------------------------------------------------
async def list_s3_buckets(
    *,
    s3_client: S3Client,
    caller_id: str = "system",
) -> str:
    """List accessible S3 buckets."""
    start = time.monotonic()
    try:
        check_rate_limit(caller_id, "list_s3_buckets")
        buckets = await s3_client.list_buckets()
        response = {
            "status": "success",
            "bucket_count": len(buckets),
            "buckets": buckets,
        }
        result = json.dumps(response, default=str, indent=2)
        duration = (time.monotonic() - start) * 1000
        audit_log("list_s3_buckets", caller_id, {}, f"{len(buckets)} buckets", True, duration)
        return result
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit_log("list_s3_buckets", caller_id, {}, "", False, duration, error=str(e))
        raise


async def list_s3_objects(
    bucket: str,
    prefix: str = "",
    max_results: int = 100,
    *,
    s3_client: S3Client,
    caller_id: str = "system",
) -> str:
    """List objects in an S3 bucket with optional prefix."""
    start = time.monotonic()
    try:
        check_rate_limit(caller_id, "list_s3_objects")
        result_data = await s3_client.list_objects(bucket, prefix, max_results)
        response = {"status": "success", "bucket": bucket, **result_data}
        result = json.dumps(response, default=str, indent=2)
        result = redact_pii(result, enable=True)
        result = cap_result_size(result)

        duration = (time.monotonic() - start) * 1000
        audit_log(
            "list_s3_objects",
            caller_id,
            {"bucket": bucket, "prefix": prefix},
            f"{result_data['count']} objects",
            True,
            duration,
        )
        return result
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit_log(
            "list_s3_objects",
            caller_id,
            {"bucket": bucket, "prefix": prefix},
            "",
            False,
            duration,
            error=str(e),
        )
        raise


async def get_s3_object(
    bucket: str,
    key: str,
    *,
    s3_client: S3Client,
    caller_id: str = "system",
) -> str:
    """Get object content (text) or metadata (binary)."""
    start = time.monotonic()
    try:
        check_rate_limit(caller_id, "get_s3_object")
        result_data = await s3_client.get_object(bucket, key)
        response = {"status": "success", **result_data}
        result = json.dumps(response, default=str, indent=2)
        result = redact_pii(result, enable=True)
        result = cap_result_size(result)

        duration = (time.monotonic() - start) * 1000
        audit_log(
            "get_s3_object",
            caller_id,
            {"bucket": bucket, "key": key},
            f"size={result_data.get('size_bytes', 0)}",
            True,
            duration,
        )
        return result
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit_log(
            "get_s3_object",
            caller_id,
            {"bucket": bucket, "key": key},
            "",
            False,
            duration,
            error=str(e),
        )
        raise


async def get_s3_metadata(
    bucket: str,
    key: str,
    *,
    s3_client: S3Client,
    caller_id: str = "system",
) -> str:
    """Get object metadata without downloading content."""
    start = time.monotonic()
    try:
        check_rate_limit(caller_id, "get_s3_metadata")
        metadata = await s3_client.get_metadata(bucket, key)
        response = {"status": "success", **metadata}
        result = json.dumps(response, default=str, indent=2)

        duration = (time.monotonic() - start) * 1000
        audit_log(
            "get_s3_metadata",
            caller_id,
            {"bucket": bucket, "key": key},
            "metadata returned",
            True,
            duration,
        )
        return result
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit_log(
            "get_s3_metadata",
            caller_id,
            {"bucket": bucket, "key": key},
            "",
            False,
            duration,
            error=str(e),
        )
        raise


async def search_s3_objects(
    bucket: str,
    prefix: str = "",
    suffix: str = "",
    max_results: int = 100,
    *,
    s3_client: S3Client,
    caller_id: str = "system",
) -> str:
    """Search objects by prefix pattern and/or file extension."""
    start = time.monotonic()
    try:
        check_rate_limit(caller_id, "search_s3_objects")
        results = await s3_client.search_objects(bucket, prefix, suffix, max_results)
        response = {
            "status": "success",
            "bucket": bucket,
            "prefix": prefix,
            "suffix": suffix,
            "result_count": len(results),
            "results": results,
        }
        result = json.dumps(response, default=str, indent=2)
        result = redact_pii(result, enable=True)
        result = cap_result_size(result)

        duration = (time.monotonic() - start) * 1000
        audit_log(
            "search_s3_objects",
            caller_id,
            {"bucket": bucket, "prefix": prefix, "suffix": suffix},
            f"{len(results)} matches",
            True,
            duration,
        )
        return result
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit_log(
            "search_s3_objects",
            caller_id,
            {"bucket": bucket, "prefix": prefix, "suffix": suffix},
            "",
            False,
            duration,
            error=str(e),
        )
        raise


# ---------------------------------------------------------------------------
# Register tools on a FastMCP server
# ---------------------------------------------------------------------------
def register_s3_tools(mcp_server: FastMCP, config: S3Config) -> None:
    """
    Register all S3 MCP tools on the given FastMCP server instance.

    Tools registered:
      - list_s3_buckets    — List accessible S3 buckets
      - list_s3_objects    — Browse objects in a bucket
      - get_s3_object      — Read text file content from S3
      - get_s3_metadata    — Get object metadata (size, type, dates)
      - search_s3_objects  — Search by prefix and file extension
    """
    # Create managed client (handles credential rotation internally)
    s3_client = S3Client(config)

    @mcp_server.tool(
        name="list_s3_buckets",
        description=(
            "List all S3 buckets accessible to the MCP server. "
            "Returns bucket names and creation dates. "
            "Only buckets in the whitelist are shown (if configured)."
        ),
    )
    async def tool_list_buckets(
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """List accessible S3 buckets."""
        caller = ctx.client_id or "unknown" if ctx else "unknown"
        return await list_s3_buckets(s3_client=s3_client, caller_id=caller)

    @mcp_server.tool(
        name="list_s3_objects",
        description=(
            "List objects in an S3 bucket. Optionally filter by key prefix. "
            "Returns key names, sizes, and last modified dates. "
            f"Max {config.max_list_results} objects per request."
        ),
    )
    async def tool_list_objects(
        bucket: str,
        prefix: str = "",
        max_results: int = 100,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """List objects in an S3 bucket."""
        caller = ctx.client_id or "unknown" if ctx else "unknown"
        return await list_s3_objects(
            bucket=bucket,
            prefix=prefix,
            max_results=max_results,
            s3_client=s3_client,
            caller_id=caller,
        )

    @mcp_server.tool(
        name="get_s3_object",
        description=(
            "Read the content of a text-based file from S3 (JSON, CSV, TXT, "
            "MD, XML, YAML, etc.). Binary files return metadata only. "
            f"Max file size: {config.max_object_size_bytes // (1024 * 1024)} MB. "
            "Blocked extensions: " + ", ".join(config.blocked_extensions)
        ),
    )
    async def tool_get_object(
        bucket: str,
        key: str,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """Get object content (text) or metadata (binary)."""
        caller = ctx.client_id or "unknown" if ctx else "unknown"
        return await get_s3_object(
            bucket=bucket,
            key=key,
            s3_client=s3_client,
            caller_id=caller,
        )

    @mcp_server.tool(
        name="get_s3_metadata",
        description=(
            "Get metadata for an S3 object without downloading its content. "
            "Returns size, content type, last modified date, ETag, and custom metadata. "
            "Use this for binary files or to check file info before downloading."
        ),
    )
    async def tool_get_metadata(
        bucket: str,
        key: str,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """Get object metadata."""
        caller = ctx.client_id or "unknown" if ctx else "unknown"
        return await get_s3_metadata(
            bucket=bucket,
            key=key,
            s3_client=s3_client,
            caller_id=caller,
        )

    @mcp_server.tool(
        name="search_s3_objects",
        description=(
            "Search for objects in an S3 bucket by prefix and/or file extension. "
            "Use prefix to narrow to a directory, suffix for file type (e.g. '.csv'). "
            "Returns matching keys with size and last modified date."
        ),
    )
    async def tool_search_objects(
        bucket: str,
        prefix: str = "",
        suffix: str = "",
        max_results: int = 100,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """Search S3 objects by prefix/suffix."""
        caller = ctx.client_id or "unknown" if ctx else "unknown"
        return await search_s3_objects(
            bucket=bucket,
            prefix=prefix,
            suffix=suffix,
            max_results=max_results,
            s3_client=s3_client,
            caller_id=caller,
        )

    logger.info("s3_tools_registered", tool_count=5)
