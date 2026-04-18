"""
S3 AWS MCP Tools
=================
Generates tool sets for an AWSSource containing S3 capabilities.
"""

import asyncio
import json
import posixpath

from centrag.guardrails.pii import redact_pii
from centrag.mcp.source_registry import AWSSource
from centrag.mcp.tool_registry import MCPTool, ToolAnnotations, ToolManifest
from centrag.utils.logger import get_logger

logger = get_logger("mcp.aws.s3")

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
    if content_type and content_type.lower() in _TEXT_CONTENT_TYPES:
        return True
    ext = posixpath.splitext(key)[1].lower()
    return ext in _TEXT_EXTENSIONS


def cap_result_size(data: str, max_bytes: int = 5 * 1024 * 1024) -> str:
    """Truncate results that exceed the maximum size."""
    encoded = data.encode("utf-8")
    if len(encoded) > max_bytes:
        truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return truncated + f"\n\n[TRUNCATED: Result exceeded {max_bytes} bytes]"
    return data


def generate_s3_tools(source: AWSSource) -> list[MCPTool]:
    """Generate all S3 interactive tools bounds to the specific source."""

    # Extract options from declarative source.
    options = source._config.options
    allowed_buckets = options.get("allowed_buckets", [])
    allowed_prefixes = options.get("allowed_prefixes", [])
    blocked_extensions = options.get("blocked_extensions", [".exe", ".dll", ".so"])
    max_list_results = options.get("max_list_results", 1000)
    max_object_size_bytes = options.get("max_object_size_bytes", 5 * 1024 * 1024)

    def _validate_bucket(bucket: str) -> None:
        if allowed_buckets and bucket not in allowed_buckets:
            raise PermissionError(f"Bucket '{bucket}' is not in the allowed list: {allowed_buckets}")

    def _validate_prefix(key: str) -> None:
        if not allowed_prefixes:
            return
        for prefix in allowed_prefixes:
            if key.startswith(prefix):
                return
        raise PermissionError(f"Key '{key}' does not match any allowed prefix: {allowed_prefixes}")

    def _validate_extension(key: str) -> None:
        ext = posixpath.splitext(key)[1].lower()
        if ext in blocked_extensions:
            raise PermissionError(f"File extension '{ext}' is blocked for security reasons.")

    def _get_client():
        return source.cred_manager.get_client("s3")

    async def list_s3_buckets(**kwargs) -> str:
        def _list():
            client = _get_client()
            response = client.list_buckets()
            buckets = response.get("Buckets", [])
            result = []
            for b in buckets:
                name = b["Name"]
                if allowed_buckets and name not in allowed_buckets:
                    continue
                result.append(
                    {
                        "name": name,
                        "creation_date": b.get("CreationDate", "").isoformat() if b.get("CreationDate") else "",
                    }
                )
            return sorted(result, key=lambda x: x["name"])

        try:
            buckets = await asyncio.to_thread(_list)
            return json.dumps(
                {
                    "status": "success",
                    "bucket_count": len(buckets),
                    "buckets": buckets,
                },
                default=str,
                indent=2,
            )
        except Exception as e:
            return f"S3 Error: {e}"

    async def list_s3_objects(**kwargs) -> str:
        bucket = kwargs.get("bucket", "")
        prefix = kwargs.get("prefix", "")
        max_results = kwargs.get("max_results", 100)

        try:
            _validate_bucket(bucket)
            effective_max = min(max_results, max_list_results)

            def _list():
                client = _get_client()
                params = {"Bucket": bucket, "MaxKeys": effective_max}
                if prefix:
                    params["Prefix"] = prefix
                response = client.list_objects_v2(**params)
                objects = [
                    {
                        "key": obj["Key"],
                        "size_bytes": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else "",
                        "storage_class": obj.get("StorageClass", "STANDARD"),
                    }
                    for obj in response.get("Contents", [])
                ]
                return {
                    "objects": objects,
                    "count": len(objects),
                    "truncated": response.get("IsTruncated", False),
                    "prefix": prefix,
                }

            result_data = await asyncio.to_thread(_list)
            response = {"status": "success", "bucket": bucket, **result_data}
            result_str = redact_pii(json.dumps(response, default=str, indent=2), enable=True)
            return cap_result_size(result_str)
        except Exception as e:
            return f"S3 Error: {e}"

    async def get_s3_object(**kwargs) -> str:
        bucket = kwargs.get("bucket", "")
        key = kwargs.get("key", "")

        try:
            _validate_bucket(bucket)
            _validate_prefix(key)
            _validate_extension(key)

            def _get():
                client = _get_client()
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
                }

                if not _is_text_content(key, content_type):
                    return {**metadata, "content": None, "note": "Binary file."}

                if size > max_object_size_bytes:
                    return {**metadata, "content": None, "note": "Object too large."}

                body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
                try:
                    content = body.decode("utf-8")
                except UnicodeDecodeError:
                    content = body.decode("latin-1", errors="replace")
                return {**metadata, "content": content}

            result_data = await asyncio.to_thread(_get)
            response = {"status": "success", **result_data}
            result_str = redact_pii(json.dumps(response, default=str, indent=2), enable=True)
            return cap_result_size(result_str)
        except Exception as e:
            return f"S3 Error: {e}"

    # Return registered tools
    target_source_name = source.name
    ans = ToolAnnotations.read_only()

    return [
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.list_s3_buckets",
                description=f"List accessible S3 buckets on source {target_source_name}.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[],
            ),
            handler=list_s3_buckets,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.list_s3_objects",
                description=f"List objects in an S3 bucket with optional prefix on source {target_source_name}.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[
                    {"name": "bucket", "type": "string", "description": "Bucket name"},
                    {"name": "prefix", "type": "string", "description": "Optional prefix", "required": False},
                    {"name": "max_results", "type": "integer", "description": "Max results", "required": False},
                ],
            ),
            handler=list_s3_objects,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.get_s3_object",
                description=f"Get object content (text) or metadata (binary) on source {target_source_name}.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[
                    {"name": "bucket", "type": "string"},
                    {"name": "key", "type": "string"},
                ],
            ),
            handler=get_s3_object,
        ),
    ]
