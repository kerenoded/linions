"""Unit tests for DynamoDB-backed job store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from botocore.exceptions import ClientError

from pipeline.storage.job_store import JobStore


class _FakeDynamoDbClient:
    """Minimal fake DynamoDB client for JobStore tests."""

    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.item: dict[str, dict[str, str]] | None = None
        self.put_raises: Exception | None = None

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        if self.put_raises is not None:
            raise self.put_raises
        self.item = kwargs["Item"]
        return {}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.update_calls.append(kwargs)
        return {}

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append(kwargs)
        if self.item is None:
            return {}
        return {"Item": self.item}


def _make_client_error(code: str) -> ClientError:
    """Build a minimal ClientError for a given error code."""
    return ClientError({"Error": {"Code": code, "Message": code}}, "put_item")


def test_create_pending_job_writes_required_fields(capsys: Any) -> None:
    fake = _FakeDynamoDbClient()
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    store.create_pending_job("job-1", "somedev")

    call = fake.put_calls[0]
    assert call["TableName"] == "linions-jobs"
    item = call["Item"]
    assert item["job-id"]["S"] == "job-1"
    assert item["username"]["S"] == "somedev"
    assert item["status"]["S"] == "PENDING"
    assert item["stage"]["S"] == "Pending"
    # Ensure created-at is a valid ISO timestamp.
    datetime.fromisoformat(item["created-at"]["S"]).astimezone(UTC)
    assert int(item["ttl"]["N"]) > int(datetime.now(UTC).timestamp())
    logs = capsys.readouterr().out
    assert (
        "DEBUG [system] [JobStore.init_start] Initializing the DynamoDB job store client." in logs
    )
    assert " [job-1] [JobStore.create_pending_job_start]" in logs
    assert "Creating a new pending job record in DynamoDB." in logs


def test_transition_pending_to_generating_uses_expected_condition() -> None:
    fake = _FakeDynamoDbClient()
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    store.transition_pending_to_generating("job-1", "starting")

    call = fake.update_calls[0]
    assert call["ConditionExpression"] == "#status = :expectedStatus"
    assert call["ExpressionAttributeValues"][":expectedStatus"]["S"] == "PENDING"
    assert call["ExpressionAttributeValues"][":nextStatus"]["S"] == "GENERATING"


def test_mark_done_stores_phase4_script_payload_field() -> None:
    fake = _FakeDynamoDbClient()
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    store.mark_done(job_id="job-1", stage="done", director_script_json="{}")

    call = fake.update_calls[0]
    assert "#directorScriptJson" in call["ExpressionAttributeNames"]
    assert call["ExpressionAttributeNames"]["#directorScriptJson"] == "director-script-json"
    assert call["ExpressionAttributeValues"][":directorScriptJson"]["S"] == "{}"


def test_mark_done_stores_animator_manifest_payload_field() -> None:
    fake = _FakeDynamoDbClient()
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    store.mark_done(job_id="job-1", stage="done", animator_manifest_json='{"clips":[]}')

    call = fake.update_calls[0]
    assert "#animatorManifestJson" in call["ExpressionAttributeNames"]
    assert call["ExpressionAttributeNames"]["#animatorManifestJson"] == "animator-manifest-json"
    assert call["ExpressionAttributeValues"][":animatorManifestJson"]["S"] == '{"clips":[]}'


def test_get_job_maps_dynamodb_attribute_values_to_flat_dict() -> None:
    fake = _FakeDynamoDbClient()
    fake.item = {
        "job-id": {"S": "job-1"},
        "status": {"S": "DONE"},
        "stage": {"S": "ok"},
        "ttl": {"N": "123"},
    }
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    item = store.get_job("job-1")

    assert item == {"job-id": "job-1", "status": "DONE", "stage": "ok", "ttl": 123}


def test_create_pending_job_raises_on_conditional_check_failure() -> None:
    """ConditionalCheckFailedException must surface as RuntimeError (double-write guard)."""
    fake = _FakeDynamoDbClient()
    fake.put_raises = _make_client_error("ConditionalCheckFailedException")
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    with pytest.raises(RuntimeError, match="Job already exists: job-dup"):
        store.create_pending_job("job-dup", "somedev")


def test_create_pending_job_re_raises_other_client_errors() -> None:
    """Non-conditional ClientError must propagate unchanged."""
    fake = _FakeDynamoDbClient()
    fake.put_raises = _make_client_error("ProvisionedThroughputExceededException")
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    with pytest.raises(ClientError):
        store.create_pending_job("job-1", "somedev")


def test_create_pending_job_rejects_empty_username() -> None:
    """create_pending_job must reject empty usernames before writing."""
    fake = _FakeDynamoDbClient()
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    with pytest.raises(ValueError, match="username must be non-empty"):
        store.create_pending_job("job-1", "")


def test_update_stage_generating_writes_stage_with_condition() -> None:
    """update_stage_generating must send the correct UpdateExpression and ConditionExpression."""
    fake = _FakeDynamoDbClient()
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    store.update_stage_generating("job-1", "[2/5] Generating story script...")

    call = fake.update_calls[0]
    assert call["TableName"] == "linions-jobs"
    assert call["Key"]["job-id"]["S"] == "job-1"
    assert ":stage" in call["ExpressionAttributeValues"]
    assert call["ExpressionAttributeValues"][":stage"]["S"] == "[2/5] Generating story script..."
    assert call["ConditionExpression"] == "#status = :generating"


def test_mark_done_without_optional_fields_uses_minimal_expression() -> None:
    """mark_done with no optional args must only set status and stage."""
    fake = _FakeDynamoDbClient()
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    store.mark_done(job_id="job-1", stage="[3/5] Validating script structure...")

    call = fake.update_calls[0]
    # No optional fields injected.
    assert "#draftKey" not in call["ExpressionAttributeNames"]
    assert "#directorScriptJson" not in call["ExpressionAttributeNames"]
    assert call["ExpressionAttributeValues"][":done"]["S"] == "DONE"


def test_mark_done_with_draft_key_injects_s3_field() -> None:
    """mark_done with draft_s3_key must include the draftKey attribute."""
    fake = _FakeDynamoDbClient()
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    store.mark_done(job_id="job-1", stage="done", draft_s3_key="drafts/dev/abc/episode.json")

    call = fake.update_calls[0]
    assert "#draftKey" in call["ExpressionAttributeNames"]
    assert call["ExpressionAttributeValues"][":draftKey"]["S"] == "drafts/dev/abc/episode.json"


def test_mark_failed_writes_error_message_and_failed_status() -> None:
    """mark_failed must write FAILED status and the error_message attribute."""
    fake = _FakeDynamoDbClient()
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    store.mark_failed(job_id="job-1", error_message="Boom", stage="Generation failed")

    call = fake.update_calls[0]
    assert call["ExpressionAttributeValues"][":failed"]["S"] == "FAILED"
    assert call["ExpressionAttributeValues"][":error"]["S"] == "Boom"
    assert call["ConditionExpression"] == "#status = :generating"


def test_get_job_returns_none_when_item_absent() -> None:
    """get_job must return None when DynamoDB returns no Item."""
    fake = _FakeDynamoDbClient()
    # item stays None — get_item will return {}
    store = JobStore(table_name="linions-jobs", dynamodb_client=fake)

    result = store.get_job("job-missing")

    assert result is None
