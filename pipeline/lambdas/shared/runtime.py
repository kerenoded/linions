"""Runtime dependency factories shared by Lambda handlers."""

from __future__ import annotations

import os

from pipeline.lambdas.shared.aws_clients import get_dynamodb_client, get_s3_client
from pipeline.storage.episode_store import EpisodeStore
from pipeline.storage.job_store import JobStore


def build_job_store_from_env(table_name_env_var: str = "JOBS_TABLE_NAME") -> JobStore:
    """Build a ``JobStore`` from Lambda environment configuration."""
    table_name = os.environ[table_name_env_var]
    return JobStore(table_name=table_name, dynamodb_client=get_dynamodb_client())


def build_episode_store_from_env(bucket_name_env_var: str = "EPISODES_BUCKET_NAME") -> EpisodeStore:
    """Build an ``EpisodeStore`` from Lambda environment configuration."""
    bucket_name = os.environ[bucket_name_env_var]
    return EpisodeStore(bucket_name=bucket_name, s3_client=get_s3_client())
