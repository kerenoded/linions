"""Generate Lambda handler for job creation and async orchestration dispatch."""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import suppress
from typing import Any

from pipeline import config
from pipeline.lambdas.shared.aws_clients import get_lambda_client
from pipeline.lambdas.shared.http import (
    extract_body,
    json_response,
    log_api_event,
    request_id_from_event,
)
from pipeline.lambdas.shared.runtime import build_job_store_from_env
from pipeline.shared.logging import log_event


def _validation_response(
    *,
    started: float,
    request_id: str | None,
    field: str,
    error: str,
) -> dict[str, Any]:
    """Log and return a standard 400 validation response."""
    duration_ms = int((time.perf_counter() - started) * 1000)
    log_api_event(
        level="WARN",
        handler="GenerateHandler",
        event="request_complete",
        message="Rejected the generate request because validation failed.",
        status_code=400,
        duration_ms=duration_ms,
        details={"request_id": request_id, "field": field, "error": error},
    )
    return json_response(400, {"error": error, "field": field})


def _validate_request(
    *,
    prompt: str,
    username: str,
    started: float,
    request_id: str | None,
) -> dict[str, Any] | None:
    """Validate request inputs and return a ready-made error response when needed."""
    if not prompt:
        return _validation_response(
            started=started,
            request_id=request_id,
            field="prompt",
            error="Prompt is required",
        )
    if len(prompt) < 10:
        return _validation_response(
            started=started,
            request_id=request_id,
            field="prompt",
            error="Prompt must be at least 10 characters",
        )
    if len(prompt) > config.MAX_PROMPT_LENGTH_CHARS:
        return _validation_response(
            started=started,
            request_id=request_id,
            field="prompt",
            error=f"Prompt exceeds max length {config.MAX_PROMPT_LENGTH_CHARS}",
        )
    if not username:
        return _validation_response(
            started=started,
            request_id=request_id,
            field="username",
            error="Username is required",
        )
    return None


def _invoke_orchestrator_async(job_id: str, prompt: str, username: str) -> None:
    """Invoke the orchestrator Lambda asynchronously for the new job."""
    response = get_lambda_client().invoke(
        FunctionName=os.environ["ORCHESTRATOR_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps({"jobId": job_id, "prompt": prompt, "username": username}).encode(
            "utf-8"
        ),
    )
    status_code = int(response.get("StatusCode", 0))
    if status_code != 202:
        msg = f"Async orchestrator invoke returned unexpected status {status_code}"
        raise RuntimeError(msg)


def handle(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Create a generation job and invoke the orchestrator asynchronously.

    Idempotency strategy:
    - Each request generates a unique jobId.
    - DynamoDB conditional create protects against accidental duplicate writes.
    """
    started = time.perf_counter()
    request_id = request_id_from_event(event)
    log_api_event(
        level="DEBUG",
        handler="GenerateHandler",
        event="request_start",
        message="Received a generate request.",
        details={
            "request_id": request_id,
            "has_body": "body" in event,
            "incoming_event": event,
        },
    )

    try:
        try:
            body = extract_body(event)
        except ValueError as error:
            return _validation_response(
                started=started,
                request_id=request_id,
                field="body",
                error=str(error),
            )

        prompt = str(body.get("prompt", "")).strip()
        username = str(body.get("username", "")).strip()
        validation_response = _validate_request(
            prompt=prompt,
            username=username,
            started=started,
            request_id=request_id,
        )
        if validation_response is not None:
            return validation_response

        job_id = f"job-{uuid.uuid4()}"
        store = build_job_store_from_env()

        try:
            store.create_pending_job(job_id, username)
            store.transition_pending_to_generating(job_id, config.STAGE_KB_QUERY)
        except Exception as error:
            duration_ms = int((time.perf_counter() - started) * 1000)
            log_event(
                "ERROR",
                "GenerateHandler",
                "job_create_failed",
                message="Failed to create the job record before invoking the orchestrator.",
                job_id=job_id,
                request_id=request_id,
                duration_ms=duration_ms,
                error_type=type(error).__name__,
                error=str(error),
            )
            log_api_event(
                level="ERROR",
                handler="GenerateHandler",
                event="request_complete",
                message="Generate request failed while creating the job record.",
                job_id=job_id,
                status_code=500,
                duration_ms=duration_ms,
                details={"request_id": request_id, "error": str(error)},
            )
            return json_response(500, {"error": "Failed to create job"})

        try:
            _invoke_orchestrator_async(job_id=job_id, prompt=prompt, username=username)
        except Exception as error:
            with suppress(Exception):
                store.mark_failed(
                    job_id=job_id,
                    error_message=(
                        "Failed to dispatch orchestrator invocation "
                        f"({type(error).__name__}): {error}"
                    ),
                    stage=config.STAGE_FAILED,
                )
            duration_ms = int((time.perf_counter() - started) * 1000)
            log_event(
                "ERROR",
                "GenerateHandler",
                "dispatch_failed",
                message="Created the job record but failed to dispatch the orchestrator invoke.",
                job_id=job_id,
                request_id=request_id,
                duration_ms=duration_ms,
                error_type=type(error).__name__,
                error=str(error),
            )
            log_api_event(
                level="ERROR",
                handler="GenerateHandler",
                event="request_complete",
                message="Generate request failed while dispatching the orchestrator invocation.",
                job_id=job_id,
                status_code=500,
                duration_ms=duration_ms,
                details={"request_id": request_id, "error": str(error)},
            )
            return json_response(500, {"error": "Failed to dispatch generation job"})

        duration_ms = int((time.perf_counter() - started) * 1000)
        log_api_event(
            level="INFO",
            handler="GenerateHandler",
            event="request_complete",
            message="Accepted the generate request and invoked the orchestrator.",
            job_id=job_id,
            status_code=200,
            duration_ms=duration_ms,
            details={"request_id": request_id, "prompt_length": len(prompt), "username": username},
        )
        return json_response(200, {"jobId": job_id})
    except Exception as error:
        duration_ms = int((time.perf_counter() - started) * 1000)
        log_event(
            "ERROR",
            "GenerateHandler",
            "unexpected_error",
            message="Generate handler failed with an unexpected error.",
            request_id=request_id,
            duration_ms=duration_ms,
            error_type=type(error).__name__,
            error=str(error),
        )
        log_api_event(
            level="ERROR",
            handler="GenerateHandler",
            event="request_complete",
            message="Generate request failed with an unexpected error.",
            status_code=500,
            duration_ms=duration_ms,
            details={
                "request_id": request_id,
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
        return json_response(500, {"error": "Internal server error"})
