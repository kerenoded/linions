"""Unit tests for generate/status Lambda handlers."""

from __future__ import annotations

import json
from typing import Any

import pipeline.lambdas.generate.handler as generate_handler
import pipeline.lambdas.status.handler as status_handler


class _FakeLambdaClient:
    """Fake Lambda client that captures invoke calls."""

    def __init__(
        self,
        *,
        response_status_code: int = 202,
        invoke_error: Exception | None = None,
    ) -> None:
        self.invocations: list[dict[str, Any]] = []
        self._response_status_code = response_status_code
        self._invoke_error = invoke_error

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        self.invocations.append(kwargs)
        if self._invoke_error is not None:
            raise self._invoke_error
        return {"StatusCode": self._response_status_code}


class _FakeJobStore:
    """Fake JobStore for handler tests."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.transitions: list[tuple[str, str]] = []
        self.failed: list[dict[str, Any]] = []
        self.items: dict[str, dict[str, Any]] = {}

    def create_pending_job(self, job_id: str, username: str) -> None:
        self.created.append(job_id)
        self.items[job_id] = {
            "job-id": job_id,
            "username": username,
            "status": "GENERATING",
            "stage": "starting",
        }

    def transition_pending_to_generating(self, job_id: str, stage: str) -> None:
        self.transitions.append((job_id, stage))
        self.items[job_id]["status"] = "GENERATING"
        self.items[job_id]["stage"] = stage

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.items.get(job_id)

    def mark_failed(self, job_id: str, error_message: str, stage: str) -> None:
        self.failed.append(
            {
                "job_id": job_id,
                "error_message": error_message,
                "stage": stage,
            }
        )
        self.items[job_id]["status"] = "FAILED"
        self.items[job_id]["stage"] = stage
        self.items[job_id]["error-message"] = error_message


def test_handle_generate_creates_job_and_invokes_orchestrator(
    monkeypatch: Any, capsys: Any
) -> None:
    fake_store = _FakeJobStore()
    fake_lambda = _FakeLambdaClient()

    monkeypatch.setenv("ORCHESTRATOR_FUNCTION_NAME", "linions-orchestrator")
    monkeypatch.setattr(generate_handler, "build_job_store_from_env", lambda: fake_store)
    monkeypatch.setattr(generate_handler, "get_lambda_client", lambda: fake_lambda)

    response = generate_handler.handle(
        {
            "body": json.dumps(
                {
                    "prompt": "Linai meets a bird and tries two funny options.",
                    "username": "somedev",
                }
            )
        },
        None,
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["jobId"].startswith("job-")
    assert fake_store.created
    assert fake_store.transitions
    assert fake_lambda.invocations[0]["InvocationType"] == "Event"
    logs = capsys.readouterr().out
    assert "DEBUG [system] [GenerateHandler.request_start] Received a generate request." in logs
    assert "INFO [" in logs
    assert "[GenerateHandler.request_complete]" in logs
    assert "incoming_event=" in logs


def test_handle_generate_rejects_missing_username() -> None:
    response = generate_handler.handle(
        {"body": json.dumps({"prompt": "This prompt has enough length."})},
        None,
    )

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["field"] == "username"


def test_handle_status_returns_mapped_payload(monkeypatch: Any, capsys: Any) -> None:
    fake_store = _FakeJobStore()
    fake_store.items["job-1"] = {
        "job-id": "job-1",
        "username": "somedev",
        "status": "DONE",
        "stage": "done",
        "draft-s3-key": "drafts/somedev/a/episode.json",
        "animator-manifest-json": '{"clips":[]}',
        "error-message": "",
    }
    monkeypatch.setattr(status_handler, "build_job_store_from_env", lambda: fake_store)

    response = status_handler.handle({"pathParameters": {"jobId": "job-1"}}, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["jobId"] == "job-1"
    assert body["username"] == "somedev"
    assert body["draftS3Key"] == "drafts/somedev/a/episode.json"
    assert body["animatorManifestJson"] == '{"clips":[]}'
    logs = capsys.readouterr().out
    assert "DEBUG [system] [StatusHandler.request_start] Received a status request." in logs
    assert "INFO [job-1] [StatusHandler.request_complete] Returned the latest job status." in logs
    assert "incoming_event=" in logs


def test_handle_status_returns_not_found() -> None:
    class _EmptyStore:
        def get_job(self, _job_id: str) -> None:
            return None

    status_handler.build_job_store_from_env = lambda: _EmptyStore()  # type: ignore[assignment]
    response = status_handler.handle({"pathParameters": {"jobId": "missing"}}, None)
    assert response["statusCode"] == 404


def test_handle_status_extracts_job_id_from_raw_path(monkeypatch: Any) -> None:
    fake_store = _FakeJobStore()
    fake_store.items["job-raw"] = {
        "job-id": "job-raw",
        "username": "somedev",
        "status": "GENERATING",
        "stage": "stage",
    }
    monkeypatch.setattr(status_handler, "build_job_store_from_env", lambda: fake_store)

    response = status_handler.handle({"rawPath": "/status/job-raw"}, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["jobId"] == "job-raw"


def test_handle_generate_returns_500_on_unexpected_error(monkeypatch: Any) -> None:
    class _FailingStore:
        def create_pending_job(self, _job_id: str, _username: str) -> None:
            raise RuntimeError("boom")

        def transition_pending_to_generating(self, _job_id: str, _stage: str) -> None:
            raise AssertionError("should not be called")

    monkeypatch.setattr(generate_handler, "build_job_store_from_env", lambda: _FailingStore())

    response = generate_handler.handle(
        {
            "body": json.dumps(
                {
                    "prompt": "Linai meets a bird and tries two funny options.",
                    "username": "somedev",
                }
            )
        },
        None,
    )

    assert response["statusCode"] == 500


def test_handle_generate_marks_job_failed_when_dispatch_raises(monkeypatch: Any) -> None:
    fake_store = _FakeJobStore()
    fake_lambda = _FakeLambdaClient(invoke_error=RuntimeError("dispatch boom"))

    monkeypatch.setenv("ORCHESTRATOR_FUNCTION_NAME", "linions-orchestrator")
    monkeypatch.setattr(generate_handler, "build_job_store_from_env", lambda: fake_store)
    monkeypatch.setattr(generate_handler, "get_lambda_client", lambda: fake_lambda)

    response = generate_handler.handle(
        {
            "body": json.dumps(
                {
                    "prompt": "Linai meets a bird and tries two funny options.",
                    "username": "somedev",
                }
            )
        },
        None,
    )

    assert response["statusCode"] == 500
    assert fake_store.failed
    assert fake_store.failed[0]["stage"] == generate_handler.config.STAGE_FAILED
    assert "dispatch boom" in fake_store.failed[0]["error_message"]


def test_handle_generate_marks_job_failed_when_dispatch_returns_non_202(
    monkeypatch: Any,
) -> None:
    fake_store = _FakeJobStore()
    fake_lambda = _FakeLambdaClient(response_status_code=500)

    monkeypatch.setenv("ORCHESTRATOR_FUNCTION_NAME", "linions-orchestrator")
    monkeypatch.setattr(generate_handler, "build_job_store_from_env", lambda: fake_store)
    monkeypatch.setattr(generate_handler, "get_lambda_client", lambda: fake_lambda)

    response = generate_handler.handle(
        {
            "body": json.dumps(
                {
                    "prompt": "Linai meets a bird and tries two funny options.",
                    "username": "somedev",
                }
            )
        },
        None,
    )

    assert response["statusCode"] == 500
    assert fake_store.failed
    assert "unexpected status 500" in fake_store.failed[0]["error_message"]

def test_handle_status_returns_400_when_job_id_missing(monkeypatch: Any) -> None:
    """Status handler must return 400 when no jobId can be extracted from the event."""
    monkeypatch.setattr(status_handler, "build_job_store_from_env", lambda: _FakeJobStore())

    # Event with no pathParameters, no rawPath — extract_job_id returns empty string.
    response = status_handler.handle({}, None)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["field"] == "jobId"


def test_handle_status_returns_500_on_unexpected_error(monkeypatch: Any) -> None:
    """Status handler must catch unexpected exceptions and return 500."""

    class _BoomStore:
        def get_job(self, _job_id: str) -> None:
            raise RuntimeError("unexpected boom")

    monkeypatch.setattr(status_handler, "build_job_store_from_env", lambda: _BoomStore())

    response = status_handler.handle({"pathParameters": {"jobId": "job-1"}}, None)

    assert response["statusCode"] == 500
    body = json.loads(response["body"])
    assert "error" in body
