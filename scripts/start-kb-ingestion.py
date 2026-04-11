#!/usr/bin/env python3
"""Start and optionally wait for Bedrock Knowledge Base ingestion.

This script is intended to be run after `cdk deploy` so the latest files in the
knowledge-base S3 bucket are indexed before generation requests call Retrieve.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import boto3


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed CLI arguments.
    """
    parser = argparse.ArgumentParser(description="Start Bedrock KB ingestion for Linions.")
    parser.add_argument("--stack-name", default="LinionsStack", help="CloudFormation stack name.")
    parser.add_argument("--profile", default=None, help="AWS profile name.")
    parser.add_argument("--region", default=None, help="AWS region.")
    parser.add_argument(
        "--knowledge-base-id",
        default=None,
        help=(
            "Optional explicit KB id. If omitted, read from CloudFormation output KnowledgeBaseId."
        ),
    )
    parser.add_argument(
        "--data-source-id",
        default=None,
        help="Optional explicit data-source id. If omitted, the first data source is used.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait until ingestion reaches a terminal status.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=900,
        help="Max wait time when --wait is set.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=5,
        help="Polling interval when --wait is set.",
    )
    return parser.parse_args()


def _stack_output(cloudformation: Any, stack_name: str, output_key: str) -> str:
    """Read one stack output value by key.

    Args:
        cloudformation: boto3 CloudFormation client.
        stack_name: Stack name.
        output_key: Output key.

    Returns:
        Output value string.

    Raises:
        RuntimeError: If the output key is missing.
    """
    response = cloudformation.describe_stacks(StackName=stack_name)
    outputs = response.get("Stacks", [{}])[0].get("Outputs", [])
    for output in outputs:
        if output.get("OutputKey") == output_key and output.get("OutputValue"):
            return str(output["OutputValue"])
    msg = f"Required stack output '{output_key}' not found in stack '{stack_name}'."
    raise RuntimeError(msg)


def main() -> int:
    """Start ingestion and optionally wait for completion.

    Returns:
        Process exit code.
    """
    args = parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    cloudformation = session.client("cloudformation")
    bedrock_agent = session.client("bedrock-agent")

    kb_id = args.knowledge_base_id or _stack_output(
        cloudformation=cloudformation,
        stack_name=args.stack_name,
        output_key="KnowledgeBaseId",
    )

    data_source_id = args.data_source_id
    if not data_source_id:
        list_response = bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)
        summaries = list_response.get("dataSourceSummaries", [])
        if not summaries:
            print(
                f"No data sources found for knowledge base {kb_id}.",
                file=sys.stderr,
            )
            return 1
        data_source_id = str(summaries[0]["dataSourceId"])

    start_response = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=data_source_id,
    )
    ingestion_job = start_response.get("ingestionJob", {})
    ingestion_job_id = str(ingestion_job.get("ingestionJobId", "unknown"))
    print(
        json.dumps(
            {
                "event": "ingestion_started",
                "knowledgeBaseId": kb_id,
                "dataSourceId": data_source_id,
                "ingestionJobId": ingestion_job_id,
                "status": ingestion_job.get("status"),
            }
        )
    )

    if not args.wait:
        return 0

    deadline = time.time() + args.timeout_seconds
    while time.time() < deadline:
        status_response = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=data_source_id,
            ingestionJobId=ingestion_job_id,
        )
        status_payload = status_response.get("ingestionJob", {})
        status = str(status_payload.get("status", "UNKNOWN"))
        print(
            json.dumps(
                {
                    "event": "ingestion_status",
                    "knowledgeBaseId": kb_id,
                    "dataSourceId": data_source_id,
                    "ingestionJobId": ingestion_job_id,
                    "status": status,
                }
            )
        )

        if status == "COMPLETE":
            return 0
        if status in {"FAILED", "STOPPED"}:
            print(
                json.dumps(
                    {
                        "event": "ingestion_failed",
                        "knowledgeBaseId": kb_id,
                        "dataSourceId": data_source_id,
                        "ingestionJobId": ingestion_job_id,
                        "status": status,
                        "failureReasons": status_payload.get("failureReasons", []),
                    }
                ),
                file=sys.stderr,
            )
            return 2

        time.sleep(args.poll_seconds)

    print(
        json.dumps(
            {
                "event": "ingestion_timeout",
                "knowledgeBaseId": kb_id,
                "dataSourceId": data_source_id,
                "ingestionJobId": ingestion_job_id,
                "timeoutSeconds": args.timeout_seconds,
            }
        ),
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
