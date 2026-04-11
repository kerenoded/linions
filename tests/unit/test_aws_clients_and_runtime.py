"""Unit tests for cached AWS client factories and Lambda runtime helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.config import Config as BotoConfig

from pipeline import config
from pipeline.lambdas.shared.aws_clients import (
    clear_aws_client_caches,
    get_bedrock_agent_runtime_client,
    get_bedrock_agentcore_client,
    get_bedrock_runtime_client,
    get_dynamodb_client,
    get_lambda_client,
    get_s3_client,
)
from pipeline.lambdas.shared.runtime import build_episode_store_from_env, build_job_store_from_env


def _clear_and_mock_boto3(monkeypatch: Any) -> MagicMock:
    """Clear all caches and install a boto3 mock that returns distinct fakes."""
    clear_aws_client_caches()
    mock_client = MagicMock()
    monkeypatch.setattr("boto3.client", mock_client)
    return mock_client


def test_get_dynamodb_client_calls_boto3_and_caches(monkeypatch: Any) -> None:
    """get_dynamodb_client must call boto3.client('dynamodb') and cache the result."""
    mock = _clear_and_mock_boto3(monkeypatch)

    result1 = get_dynamodb_client()
    result2 = get_dynamodb_client()

    mock.assert_called_once_with("dynamodb")
    assert result1 is result2


def test_get_lambda_client_calls_boto3_and_caches(monkeypatch: Any) -> None:
    """get_lambda_client must call boto3.client('lambda') and cache the result."""
    mock = _clear_and_mock_boto3(monkeypatch)

    result1 = get_lambda_client()
    result2 = get_lambda_client()

    mock.assert_called_once_with("lambda")
    assert result1 is result2


def test_get_s3_client_calls_boto3_and_caches(monkeypatch: Any) -> None:
    """get_s3_client must call boto3.client('s3') and cache the result."""
    mock = _clear_and_mock_boto3(monkeypatch)

    result1 = get_s3_client()
    result2 = get_s3_client()

    mock.assert_called_once_with("s3")
    assert result1 is result2


def test_get_bedrock_runtime_client_calls_boto3_and_caches(monkeypatch: Any) -> None:
    """get_bedrock_runtime_client must call boto3.client('bedrock-runtime')."""
    mock = _clear_and_mock_boto3(monkeypatch)

    result1 = get_bedrock_runtime_client()
    result2 = get_bedrock_runtime_client()

    mock.assert_called_once()
    args, kwargs = mock.call_args
    assert args == ("bedrock-runtime",)
    assert isinstance(kwargs["config"], BotoConfig)
    assert kwargs["config"].connect_timeout == config.BEDROCK_CONNECT_TIMEOUT_SECONDS
    assert kwargs["config"].read_timeout == config.AGENT_CALL_TIMEOUT_SECONDS
    assert result1 is result2


def test_get_bedrock_agent_runtime_client_calls_boto3_and_caches(monkeypatch: Any) -> None:
    """get_bedrock_agent_runtime_client must call boto3.client('bedrock-agent-runtime')."""
    mock = _clear_and_mock_boto3(monkeypatch)

    result1 = get_bedrock_agent_runtime_client()
    result2 = get_bedrock_agent_runtime_client()

    mock.assert_called_once_with("bedrock-agent-runtime")
    assert result1 is result2


def test_get_bedrock_agentcore_client_calls_boto3_and_caches(monkeypatch: Any) -> None:
    """get_bedrock_agentcore_client must call boto3.client('bedrock-agentcore')."""
    mock = _clear_and_mock_boto3(monkeypatch)

    result1 = get_bedrock_agentcore_client()
    result2 = get_bedrock_agentcore_client()

    mock.assert_called_once_with("bedrock-agentcore")
    assert result1 is result2


def test_clear_aws_client_caches_forces_fresh_client_on_next_call(monkeypatch: Any) -> None:
    """clear_aws_client_caches must evict all cached clients so the next call creates fresh ones."""
    mock = _clear_and_mock_boto3(monkeypatch)

    get_dynamodb_client()
    assert mock.call_count == 1

    clear_aws_client_caches()
    get_dynamodb_client()
    assert mock.call_count == 2


def test_build_job_store_from_env_reads_table_name_from_env(monkeypatch: Any) -> None:
    """build_job_store_from_env must build a JobStore from the JOBS_TABLE_NAME env var."""
    monkeypatch.setenv("JOBS_TABLE_NAME", "my-jobs-table")
    _clear_and_mock_boto3(monkeypatch)

    store = build_job_store_from_env()

    assert store._table_name == "my-jobs-table"


def test_build_job_store_from_env_raises_when_env_var_missing(monkeypatch: Any) -> None:
    """build_job_store_from_env must raise KeyError when JOBS_TABLE_NAME is not set."""
    monkeypatch.delenv("JOBS_TABLE_NAME", raising=False)

    with pytest.raises(KeyError):
        build_job_store_from_env()


def test_build_episode_store_from_env_reads_bucket_name_from_env(monkeypatch: Any) -> None:
    """build_episode_store_from_env must build an EpisodeStore from env config."""
    monkeypatch.setenv("EPISODES_BUCKET_NAME", "my-episodes-bucket")
    _clear_and_mock_boto3(monkeypatch)

    store = build_episode_store_from_env()

    assert store._bucket_name == "my-episodes-bucket"


def test_build_episode_store_from_env_raises_when_env_var_missing(monkeypatch: Any) -> None:
    """build_episode_store_from_env must raise KeyError when the env var is absent."""
    monkeypatch.delenv("EPISODES_BUCKET_NAME", raising=False)

    with pytest.raises(KeyError):
        build_episode_store_from_env()
