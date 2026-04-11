"""Cached AWS client factories for Lambda runtime reuse.

AWS recommends reusing SDK clients across warm Lambda invocations when
possible. These small factories keep creation lazy for tests while still
reusing clients after the first call in production.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from pipeline import config


@lru_cache(maxsize=1)
def get_dynamodb_client() -> Any:
    """Return a cached DynamoDB client."""
    return boto3.client("dynamodb")


@lru_cache(maxsize=1)
def get_lambda_client() -> Any:
    """Return a cached Lambda client."""
    return boto3.client("lambda")


@lru_cache(maxsize=1)
def get_s3_client() -> Any:
    """Return a cached S3 client."""
    return boto3.client("s3")


@lru_cache(maxsize=1)
def get_bedrock_runtime_client() -> Any:
    """Return a cached Bedrock runtime client."""
    return boto3.client(
        "bedrock-runtime",
        config=BotoConfig(
            connect_timeout=config.BEDROCK_CONNECT_TIMEOUT_SECONDS,
            read_timeout=config.AGENT_CALL_TIMEOUT_SECONDS,
        ),
    )


@lru_cache(maxsize=1)
def get_bedrock_agent_runtime_client() -> Any:
    """Return a cached Bedrock Agent Runtime client."""
    return boto3.client("bedrock-agent-runtime")


@lru_cache(maxsize=1)
def get_bedrock_agentcore_client() -> Any:
    """Return a cached Bedrock AgentCore client."""
    return boto3.client("bedrock-agentcore")


def clear_aws_client_caches() -> None:
    """Clear cached AWS clients, primarily for tests."""
    get_dynamodb_client.cache_clear()
    get_lambda_client.cache_clear()
    get_s3_client.cache_clear()
    get_bedrock_runtime_client.cache_clear()
    get_bedrock_agent_runtime_client.cache_clear()
    get_bedrock_agentcore_client.cache_clear()
