"""DynamoDB-backed job persistence for generation orchestration.

The job store is the single place that reads and writes job lifecycle state.
All transitions are guarded by condition expressions so the DynamoDB table
itself enforces the legal state machine defined in DESIGN.md §10.

This module intentionally owns persistence only. It does not orchestrate model
calls or Lambda behavior, but it does emit lightweight entry logs for every
method so state changes are easier to trace in CloudWatch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from pipeline import config
from pipeline.shared.logging import log_event


class JobStore:
    """Persist and transition orchestration jobs in DynamoDB."""

    def __init__(self, table_name: str, dynamodb_client: Any | None = None) -> None:
        """Initialise a job store instance."""
        log_event(
            "DEBUG",
            "JobStore",
            "init_start",
            message="Initializing the DynamoDB job store client.",
            table_name=table_name,
            has_custom_client=dynamodb_client is not None,
        )
        self._table_name = table_name
        self._ddb = dynamodb_client or boto3.client("dynamodb")

    def create_pending_job(self, job_id: str, username: str) -> None:
        """Create a new ``PENDING`` job record."""
        log_event(
            "DEBUG",
            "JobStore",
            "create_pending_job_start",
            message="Creating a new pending job record in DynamoDB.",
            table_name=self._table_name,
            job_id=job_id,
            username=username,
        )
        if username.strip() == "":
            msg = "username must be non-empty"
            raise ValueError(msg)
        now = datetime.now(UTC)
        ttl_epoch = int(now.timestamp()) + config.JOB_TTL_SECONDS
        try:
            self._ddb.put_item(
                TableName=self._table_name,
                Item={
                    "job-id": {"S": job_id},
                    "username": {"S": username},
                    "status": {"S": "PENDING"},
                    "stage": {"S": "Pending"},
                    "created-at": {"S": now.isoformat()},
                    "ttl": {"N": str(ttl_epoch)},
                },
                ConditionExpression="attribute_not_exists(#jobId)",
                ExpressionAttributeNames={"#jobId": "job-id"},
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                msg = f"Job already exists: {job_id}"
                raise RuntimeError(msg) from error
            raise

    def transition_pending_to_generating(self, job_id: str, stage: str) -> None:
        """Transition a job from ``PENDING`` to ``GENERATING``."""
        log_event(
            "DEBUG",
            "JobStore",
            "transition_pending_to_generating_start",
            message="Transitioning the job from PENDING to GENERATING in DynamoDB.",
            table_name=self._table_name,
            job_id=job_id,
            stage=stage,
        )
        self._conditional_update_status(
            job_id=job_id,
            expected="PENDING",
            next_status="GENERATING",
            stage=stage,
        )

    def update_stage_generating(self, job_id: str, stage: str) -> None:
        """Update stage text for a job currently in ``GENERATING`` status."""
        log_event(
            "DEBUG",
            "JobStore",
            "update_stage_generating_start",
            message="Updating the current GENERATING stage in DynamoDB.",
            table_name=self._table_name,
            job_id=job_id,
            stage=stage,
        )
        self._ddb.update_item(
            TableName=self._table_name,
            Key={"job-id": {"S": job_id}},
            UpdateExpression="SET #stage = :stage",
            ConditionExpression="#status = :generating",
            ExpressionAttributeNames={"#stage": "stage", "#status": "status"},
            ExpressionAttributeValues={
                ":stage": {"S": stage},
                ":generating": {"S": "GENERATING"},
            },
        )

    def mark_done(
        self,
        job_id: str,
        stage: str,
        draft_s3_key: str | None = None,
        director_script_json: str | None = None,
        animator_manifest_json: str | None = None,
    ) -> None:
        """Mark a ``GENERATING`` job as ``DONE``."""
        log_event(
            "DEBUG",
            "JobStore",
            "mark_done_start",
            message="Marking the job as DONE and storing its final fields.",
            table_name=self._table_name,
            job_id=job_id,
            stage=stage,
            has_draft_s3_key=draft_s3_key is not None,
            has_director_script_json=director_script_json is not None,
            has_animator_manifest_json=animator_manifest_json is not None,
        )
        update_parts = ["#status = :done", "#stage = :stage"]
        values: dict[str, dict[str, str]] = {
            ":done": {"S": "DONE"},
            ":stage": {"S": stage},
            ":generating": {"S": "GENERATING"},
        }
        names = {"#status": "status", "#stage": "stage"}

        if draft_s3_key is not None:
            update_parts.append("#draftKey = :draftKey")
            names["#draftKey"] = "draft-s3-key"
            values[":draftKey"] = {"S": draft_s3_key}

        if director_script_json is not None:
            update_parts.append("#directorScriptJson = :directorScriptJson")
            names["#directorScriptJson"] = "director-script-json"
            values[":directorScriptJson"] = {"S": director_script_json}

        if animator_manifest_json is not None:
            update_parts.append("#animatorManifestJson = :animatorManifestJson")
            names["#animatorManifestJson"] = "animator-manifest-json"
            values[":animatorManifestJson"] = {"S": animator_manifest_json}

        self._ddb.update_item(
            TableName=self._table_name,
            Key={"job-id": {"S": job_id}},
            UpdateExpression=f"SET {', '.join(update_parts)}",
            ConditionExpression="#status = :generating",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def mark_failed(self, job_id: str, error_message: str, stage: str) -> None:
        """Mark a ``GENERATING`` job as ``FAILED``."""
        log_event(
            "DEBUG",
            "JobStore",
            "mark_failed_start",
            message="Marking the job as FAILED and storing the error message.",
            table_name=self._table_name,
            job_id=job_id,
            stage=stage,
            error_message=error_message,
        )
        self._ddb.update_item(
            TableName=self._table_name,
            Key={"job-id": {"S": job_id}},
            UpdateExpression="SET #status = :failed, #stage = :stage, #error = :error",
            ConditionExpression="#status = :generating",
            ExpressionAttributeNames={
                "#status": "status",
                "#stage": "stage",
                "#error": "error-message",
            },
            ExpressionAttributeValues={
                ":failed": {"S": "FAILED"},
                ":stage": {"S": stage},
                ":error": {"S": error_message},
                ":generating": {"S": "GENERATING"},
            },
        )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Read a job record by id."""
        log_event(
            "DEBUG",
            "JobStore",
            "get_job_start",
            message="Running a DynamoDB GetItem call for the job record.",
            table_name=self._table_name,
            job_id=job_id,
        )
        result = self._ddb.get_item(
            TableName=self._table_name,
            Key={"job-id": {"S": job_id}},
        )
        item = result.get("Item")
        if item is None:
            return None
        mapped: dict[str, Any] = {}
        for key, value in item.items():
            if "S" in value:
                mapped[key] = value["S"]
            elif "N" in value:
                mapped[key] = int(value["N"])
        return mapped

    def _conditional_update_status(
        self,
        job_id: str,
        expected: str,
        next_status: str,
        stage: str,
    ) -> None:
        """Perform a conditional status transition update."""
        log_event(
            "DEBUG",
            "JobStore",
            "conditional_update_status_start",
            message="Applying a conditional job status transition in DynamoDB.",
            table_name=self._table_name,
            job_id=job_id,
            expected_status=expected,
            next_status=next_status,
            stage=stage,
        )
        self._ddb.update_item(
            TableName=self._table_name,
            Key={"job-id": {"S": job_id}},
            UpdateExpression="SET #status = :nextStatus, #stage = :stage",
            ConditionExpression="#status = :expectedStatus",
            ExpressionAttributeNames={"#status": "status", "#stage": "stage"},
            ExpressionAttributeValues={
                ":nextStatus": {"S": next_status},
                ":expectedStatus": {"S": expected},
                ":stage": {"S": stage},
            },
        )
