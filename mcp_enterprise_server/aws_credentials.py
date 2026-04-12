"""
AWS Credential Manager
======================
Provides secure, short-lived AWS credentials via STS AssumeRole.
Caches sessions to avoid redundant STS calls within a session window.

Key Principles:
  - Never hardcode credentials — use IAM roles and instance profiles
  - Always prefer AssumeRole with shortest practical session duration
  - Support cross-account access via external role ARNs
  - Thread-safe credential caching with automatic refresh
"""

from __future__ import annotations

import threading
import time

import boto3
import structlog
from botocore.config import Config as BotoConfig

logger = structlog.get_logger("aws_credentials")


class AWSCredentialManager:
    """
    Manages AWS sessions with temporary credentials via STS AssumeRole.

    If no role_arn is provided, falls back to the default credential chain
    (instance profile, env vars, ~/.aws/credentials).
    """

    def __init__(
        self,
        region: str,
        role_arn: str | None = None,
        session_name: str = "MCPEnterpriseSession",
        session_duration: int = 3600,
        endpoint_url: str | None = None,
    ):
        self._region = region
        self._role_arn = role_arn
        self._session_name = session_name
        self._session_duration = session_duration
        self._endpoint_url = endpoint_url

        # Cached session + expiry
        self._lock = threading.Lock()
        self._cached_session: boto3.Session | None = None
        self._session_expiry: float = 0.0

        # Boto retry config
        self._boto_config = BotoConfig(
            region_name=region,
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=30,
        )

    def get_session(self) -> boto3.Session:
        """
        Return a boto3.Session with valid credentials.
        Thread-safe; refreshes automatically when credentials expire.
        """
        with self._lock:
            now = time.time()
            # Refresh 5 minutes before expiry to avoid edge-case failures
            if self._cached_session and now < (self._session_expiry - 300):
                return self._cached_session

            if self._role_arn:
                session = self._assume_role()
            else:
                # Use default credential chain (instance profile, env, config)
                session = boto3.Session(region_name=self._region)
                # Default sessions don't expire, set far-future expiry
                self._session_expiry = now + 86400

            self._cached_session = session
            return session

    def _assume_role(self) -> boto3.Session:
        """Assume an IAM role and return a session with temporary credentials."""
        logger.info(
            "assuming_role",
            role_arn=self._role_arn,
            session_name=self._session_name,
            duration=self._session_duration,
        )

        sts_client = boto3.client("sts", region_name=self._region)
        response = sts_client.assume_role(
            RoleArn=self._role_arn,
            RoleSessionName=self._session_name,
            DurationSeconds=self._session_duration,
        )

        credentials = response["Credentials"]
        self._session_expiry = credentials["Expiration"].timestamp()

        session = boto3.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=self._region,
        )

        logger.info(
            "role_assumed",
            role_arn=self._role_arn,
            expires_at=credentials["Expiration"].isoformat(),
        )
        return session

    def get_client(self, service_name: str, **kwargs) -> boto3.client:
        """Get a boto3 client for a specific AWS service with managed credentials."""
        session = self.get_session()
        client_kwargs = {"config": self._boto_config, **kwargs}
        if self._endpoint_url:
            client_kwargs["endpoint_url"] = self._endpoint_url
        return session.client(service_name, **client_kwargs)

    def get_resource(self, service_name: str, **kwargs) -> boto3.resource:
        """Get a boto3 resource for a specific AWS service with managed credentials."""
        session = self.get_session()
        resource_kwargs = {"config": self._boto_config, **kwargs}
        if self._endpoint_url:
            resource_kwargs["endpoint_url"] = self._endpoint_url
        return session.resource(service_name, **resource_kwargs)
