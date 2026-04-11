"""Unit tests for the async orchestrator Lambda handler."""

from __future__ import annotations

from typing import Any

import pytest

import pipeline.lambdas.orchestrator.handler as orchestrator_handler
from pipeline import config


class _FakeJobStore:
    """Capture handler-level failed-job writes for assertions."""

    def __init__(self) -> None:
        self.failed_calls: list[dict[str, Any]] = []

    def mark_failed(self, **kwargs: Any) -> None:
        self.failed_calls.append(kwargs)


def test_handle_orchestrator_logs_entry_and_exit(monkeypatch: Any, capsys: Any) -> None:
    class _FakeRuntimeOrchestrator:
        def run(
            self,
            *,
            job_id: str,
            prompt: str,
            username: str,
            remaining_time_provider: Any | None = None,
        ) -> None:
            assert job_id == "job-123"
            assert prompt == "Linai goes forward"
            assert username == "dev"
            assert remaining_time_provider is None

    monkeypatch.setattr(
        orchestrator_handler,
        "build_pipeline_orchestrator_from_env",
        lambda: _FakeRuntimeOrchestrator(),
    )

    orchestrator_handler.handle(
        {"jobId": "job-123", "prompt": "Linai goes forward", "username": "dev"},
        None,
    )

    logs = capsys.readouterr().out
    assert (
        "DEBUG [job-123] [OrchestratorHandler.request_start] "
        "Received an orchestrator invocation event." in logs
    )
    assert (
        "INFO [job-123] [OrchestratorHandler.request_complete] "
        "Finished handling the orchestrator invocation event." in logs
    )
    assert "result=ok" in logs
    assert "incoming_event=" in logs


def test_handle_orchestrator_logs_error_and_raises(capsys: Any) -> None:
    with pytest.raises(RuntimeError):
        orchestrator_handler.handle({"jobId": "", "prompt": "", "username": ""}, None)

    logs = capsys.readouterr().out
    assert (
        "DEBUG [system] [OrchestratorHandler.request_start] "
        "Received an orchestrator invocation event." in logs
    )
    assert (
        "ERROR [system] [OrchestratorHandler.request_complete] "
        "Orchestrator invocation failed with an unhandled error." in logs
    )
    assert "result=error" in logs


def test_handle_orchestrator_logs_failed_result_without_raising(
    monkeypatch: Any, capsys: Any
) -> None:
    class _FakeRuntimeOrchestrator:
        def run(
            self,
            *,
            job_id: str,
            prompt: str,
            username: str,
            remaining_time_provider: Any | None = None,
        ) -> dict[str, str]:
            assert job_id == "job-123"
            assert prompt == "Linai goes forward"
            assert username == "dev"
            assert remaining_time_provider is None
            return {"result": "failed", "reason": "kb_retrieve_failed"}

    monkeypatch.setattr(
        orchestrator_handler,
        "build_pipeline_orchestrator_from_env",
        lambda: _FakeRuntimeOrchestrator(),
    )

    orchestrator_handler.handle(
        {"jobId": "job-123", "prompt": "Linai goes forward", "username": "dev"},
        None,
    )

    logs = capsys.readouterr().out
    assert "[OrchestratorHandler.request_complete]" in logs
    assert "result=failed" in logs
    assert "reason=kb_retrieve_failed" in logs


def test_handle_orchestrator_includes_error_details_for_failed_call(
    monkeypatch: Any, capsys: Any
) -> None:
    class _FakeRuntimeOrchestrator:
        def run(
            self,
            *,
            job_id: str,
            prompt: str,
            username: str,
            remaining_time_provider: Any | None = None,
        ) -> dict[str, str]:
            assert job_id == "job-123"
            assert prompt == "Linai goes forward"
            assert username == "dev"
            assert remaining_time_provider is None
            return {
                "result": "failed",
                "reason": "director_model_call_failed",
                "errorType": "AccessDeniedException",
                "error": "bedrock:InvokeModel not authorized",
            }

    monkeypatch.setattr(
        orchestrator_handler,
        "build_pipeline_orchestrator_from_env",
        lambda: _FakeRuntimeOrchestrator(),
    )

    orchestrator_handler.handle(
        {"jobId": "job-123", "prompt": "Linai goes forward", "username": "dev"},
        None,
    )

    logs = capsys.readouterr().out
    assert "[OrchestratorHandler.request_complete]" in logs
    assert "result=failed" in logs
    assert "reason=director_model_call_failed" in logs
    assert "error_type=AccessDeniedException" in logs
    assert "error='bedrock:InvokeModel not authorized'" in logs


def test_handle_orchestrator_marks_job_failed_on_unhandled_exception(monkeypatch: Any) -> None:
    class _FakeRuntimeOrchestrator:
        def run(
            self,
            *,
            job_id: str,
            prompt: str,
            username: str,
            remaining_time_provider: Any | None = None,
        ) -> None:
            assert job_id == "job-123"
            assert prompt == "Linai goes forward"
            assert username == "dev"
            assert remaining_time_provider is None
            raise RuntimeError("boom")

    store = _FakeJobStore()
    monkeypatch.setattr(
        orchestrator_handler,
        "build_pipeline_orchestrator_from_env",
        lambda: _FakeRuntimeOrchestrator(),
    )
    monkeypatch.setattr(orchestrator_handler, "build_job_store_from_env", lambda: store)

    with pytest.raises(RuntimeError, match="boom"):
        orchestrator_handler.handle(
            {"jobId": "job-123", "prompt": "Linai goes forward", "username": "dev"},
            None,
        )

    assert len(store.failed_calls) == 1
    assert store.failed_calls[0]["job_id"] == "job-123"
    assert store.failed_calls[0]["stage"] == config.STAGE_FAILED
    assert "Unhandled orchestrator error (RuntimeError): boom" in store.failed_calls[0][
        "error_message"
    ]
