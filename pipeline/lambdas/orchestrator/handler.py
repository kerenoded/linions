"""Async orchestrator Lambda handler for the generation pipeline."""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

from pipeline.config import STAGE_FAILED
from pipeline.lambdas.orchestrator.runtime import build_pipeline_orchestrator_from_env
from pipeline.lambdas.shared.runtime import build_job_store_from_env
from pipeline.shared.logging import log_event


def handle(event: dict[str, Any], _context: Any) -> None:
    """Run the pipeline orchestrator for an asynchronously-invoked job event."""
    started = time.perf_counter()
    job_id = str(event.get("jobId", ""))
    prompt = str(event.get("prompt", ""))
    username = str(event.get("username", ""))
    log_event(
        "DEBUG",
        "OrchestratorHandler",
        "request_start",
        message="Received an orchestrator invocation event.",
        job_id=job_id or None,
        username=username,
        prompt_length=len(prompt),
        incoming_event=event,
    )

    try:
        if not job_id or not prompt or not username:
            msg = "Orchestrator payload must include non-empty jobId, prompt, and username"
            raise RuntimeError(msg)

        outcome = build_pipeline_orchestrator_from_env().run(
            job_id=job_id,
            prompt=prompt,
            username=username,
            remaining_time_provider=(
                _context.get_remaining_time_in_millis
                if _context is not None and hasattr(_context, "get_remaining_time_in_millis")
                else None
            ),
        )
        result = outcome.get("result", "ok") if isinstance(outcome, dict) else "ok"
        log_event(
            "INFO" if result == "ok" else "WARN",
            "OrchestratorHandler",
            "request_complete",
            message="Finished handling the orchestrator invocation event.",
            job_id=job_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            result=result,
            reason=outcome.get("reason") if isinstance(outcome, dict) else None,
            error_type=outcome.get("errorType") if isinstance(outcome, dict) else None,
            error=outcome.get("error") if isinstance(outcome, dict) else None,
        )
    except Exception as error:
        if job_id:
            with suppress(Exception):
                build_job_store_from_env().mark_failed(
                    job_id=job_id,
                    error_message=f"Unhandled orchestrator error ({type(error).__name__}): {error}",
                    stage=STAGE_FAILED,
                )
        log_event(
            "ERROR",
            "OrchestratorHandler",
            "request_complete",
            message="Orchestrator invocation failed with an unhandled error.",
            job_id=job_id or None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            result="error",
            error_type=type(error).__name__,
            error=str(error),
        )
        raise
