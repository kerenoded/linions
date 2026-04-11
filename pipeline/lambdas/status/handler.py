"""Status Lambda handler for reading current job state."""

from __future__ import annotations

import time
from typing import Any

from pipeline.lambdas.shared.http import (
    extract_job_id,
    json_response,
    log_api_event,
    request_id_from_event,
)
from pipeline.lambdas.shared.runtime import build_job_store_from_env
from pipeline.shared.logging import log_event


def handle(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Return current generation job status with a single DynamoDB read.

    Idempotency strategy:
    - Read-only endpoint, no state mutation.
    """
    started = time.perf_counter()
    request_id = request_id_from_event(event)
    log_api_event(
        level="DEBUG",
        handler="StatusHandler",
        event="request_start",
        message="Received a status request.",
        details={"request_id": request_id, "incoming_event": event},
    )

    try:
        job_id = extract_job_id(event)
        if not job_id:
            duration_ms = int((time.perf_counter() - started) * 1000)
            log_api_event(
                level="WARN",
                handler="StatusHandler",
                event="request_complete",
                message="Rejected the status request because jobId is missing.",
                status_code=400,
                duration_ms=duration_ms,
                details={"request_id": request_id, "field": "jobId", "error": "jobId is required"},
            )
            return json_response(400, {"error": "jobId is required", "field": "jobId"})

        store = build_job_store_from_env()
        job = store.get_job(job_id)
        if job is None:
            duration_ms = int((time.perf_counter() - started) * 1000)
            log_api_event(
                level="WARN",
                handler="StatusHandler",
                event="request_complete",
                message="Status request completed but the job was not found.",
                job_id=job_id,
                status_code=404,
                duration_ms=duration_ms,
                details={"request_id": request_id, "error": "Job not found"},
            )
            return json_response(404, {"error": "Job not found"})

        duration_ms = int((time.perf_counter() - started) * 1000)
        log_api_event(
            level="INFO",
            handler="StatusHandler",
            event="request_complete",
            message="Returned the latest job status.",
            job_id=job_id,
            status_code=200,
            duration_ms=duration_ms,
            details={
                "request_id": request_id,
                "status": job.get("status"),
                "stage": job.get("stage"),
                "has_draft_key": bool(job.get("draft-s3-key")),
            },
        )
        return json_response(
            200,
            {
                "jobId": job.get("job-id"),
                "username": job.get("username"),
                "status": job.get("status"),
                "stage": job.get("stage"),
                "draftS3Key": job.get("draft-s3-key"),
                "directorScriptJson": job.get("director-script-json"),
                "animatorManifestJson": job.get("animator-manifest-json"),
                "errorMessage": job.get("error-message"),
            },
        )
    except Exception as error:
        duration_ms = int((time.perf_counter() - started) * 1000)
        log_event(
            "ERROR",
            "StatusHandler",
            "unexpected_error",
            message="Status handler failed with an unexpected error.",
            request_id=request_id,
            duration_ms=duration_ms,
            error_type=type(error).__name__,
            error=str(error),
        )
        log_api_event(
            level="ERROR",
            handler="StatusHandler",
            event="request_complete",
            message="Status request failed with an unexpected error.",
            status_code=500,
            duration_ms=duration_ms,
            details={
                "request_id": request_id,
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
        return json_response(500, {"error": "Internal server error"})
