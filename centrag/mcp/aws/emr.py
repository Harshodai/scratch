"""
EMR AWS MCP Tools
=================
Generates tools for an AWSSource containing EMR capabilities.
"""

import asyncio
import json

from centrag.guardrails.pii import redact_pii
from centrag.mcp.source_registry import AWSSource
from centrag.mcp.tool_registry import MCPTool, ToolAnnotations, ToolManifest
from centrag.utils.logger import get_logger

logger = get_logger("mcp.aws.emr")


def cap_result_size(data: str, max_bytes: int = 5 * 1024 * 1024) -> str:
    encoded = data.encode("utf-8")
    if len(encoded) > max_bytes:
        truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return truncated + f"\n\n[TRUNCATED: Result exceeded {max_bytes} bytes]"
    return data


def generate_emr_tools(source: AWSSource) -> list[MCPTool]:
    """Generate all EMR interactive tools bounds to the specific source."""

    def _get_client():
        return source.cred_manager.get_client("emr")

    async def list_emr_clusters(**kwargs) -> str:
        def _list():
            client = _get_client()
            response = client.list_clusters(ClusterStates=["STARTING", "BOOTSTRAPPING", "RUNNING", "WAITING"])
            return response.get("Clusters", [])

        try:
            clusters = await asyncio.to_thread(_list)
            result = json.dumps({"status": "success", "clusters": clusters}, default=str, indent=2)
            return cap_result_size(redact_pii(result))
        except Exception as e:
            return f"EMR Error: {e}"

    async def describe_emr_cluster(**kwargs) -> str:
        cluster_id = kwargs.get("cluster_id")

        def _describe():
            return _get_client().describe_cluster(ClusterId=cluster_id)

        try:
            cluster_info = await asyncio.to_thread(_describe)
            result = json.dumps(
                {"status": "success", "cluster": cluster_info.get("Cluster", {})}, default=str, indent=2
            )
            return cap_result_size(redact_pii(result))
        except Exception as e:
            return f"EMR Error: {e}"

    async def terminate_emr_cluster(**kwargs) -> str:
        cluster_id = kwargs.get("cluster_id")

        def _terminate():
            _get_client().terminate_job_flows(JobFlowIds=[cluster_id])

        try:
            await asyncio.to_thread(_terminate)
            return json.dumps({"status": "success", "message": f"Termination initiated for {cluster_id}"})
        except Exception as e:
            return f"EMR Error: {e}"

    def _get_serverless_client():
        return source.cred_manager.get_client("emr-serverless")

    async def list_emr_serverless_apps(**kwargs) -> str:
        def _list():
            client = _get_serverless_client()
            paginator = client.get_paginator("list_applications")
            apps = []
            for page in paginator.paginate():
                for app in page.get("applications", []):
                    apps.append(app)
            return apps

        try:
            apps = await asyncio.to_thread(_list)
            result = json.dumps({"status": "success", "applications": apps}, default=str, indent=2)
            return cap_result_size(redact_pii(result))
        except Exception as e:
            return f"EMR Error: {e}"

    async def get_emr_serverless_app(**kwargs) -> str:
        application_id = kwargs.get("application_id")

        def _get():
            return _get_serverless_client().get_application(applicationId=application_id)

        try:
            app_info = await asyncio.to_thread(_get)
            result = json.dumps(
                {"status": "success", "application": app_info.get("application", {})}, default=str, indent=2
            )
            return cap_result_size(redact_pii(result))
        except Exception as e:
            return f"EMR Error: {e}"

    async def start_emr_serverless_app(**kwargs) -> str:
        application_id = kwargs.get("application_id")

        def _start():
            _get_serverless_client().start_application(applicationId=application_id)

        try:
            await asyncio.to_thread(_start)
            return json.dumps({"status": "success", "message": f"Start initiated for app {application_id}"})
        except Exception as e:
            return f"EMR Error: {e}"

    target_source_name = source.name
    ans = ToolAnnotations.read_only()

    return [
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.list_emr_clusters",
                description=f"List active EMR clusters on source {target_source_name}.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[],
            ),
            handler=list_emr_clusters,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.describe_emr_cluster",
                description="Get detailed information about a specific EMR EC2 cluster by its JobFlowId / ClusterId.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[{"name": "cluster_id", "type": "string", "description": "The JobFlowId / ClusterId"}],
            ),
            handler=describe_emr_cluster,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.terminate_emr_cluster",
                description="Terminate a specific EMR EC2 cluster.",
                source_name=target_source_name,
                annotations=ToolAnnotations.destructive(),
                parameters=[{"name": "cluster_id", "type": "string", "description": "The JobFlowId / ClusterId"}],
            ),
            handler=terminate_emr_cluster,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.list_emr_serverless_apps",
                description="List EMR Serverless applications.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[],
            ),
            handler=list_emr_serverless_apps,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.get_emr_serverless_app",
                description="Get detailed information about an EMR Serverless application by ID.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[{"name": "application_id", "type": "string", "description": "The application ID"}],
            ),
            handler=get_emr_serverless_app,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.start_emr_serverless_app",
                description="Start an EMR Serverless application.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[{"name": "application_id", "type": "string", "description": "The application ID"}],
            ),
            handler=start_emr_serverless_app,
        ),
    ]
