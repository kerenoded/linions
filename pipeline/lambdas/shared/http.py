"""HTTP-style Lambda helpers shared by API-facing handlers."""

from __future__ import annotations

import json
from typing import Any

from pipeline.shared.logging import log_event


def log_api_event(
    *,
    level: str,
    handler: str,
    event: str,
    message: str | None = None,
    job_id: str | None = None,
    status_code: int | None = None,
    duration_ms: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Emit one readable API lifecycle log line."""
    log_event(
        level,
        handler,
        event,
        message=message,
        job_id=job_id,
        status_code=status_code,
        duration_ms=duration_ms,
        **(details or {}),
    )


def json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Create the standard JSON response object for Function URL handlers."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def extract_body(event: dict[str, Any]) -> dict[str, Any]:
    """Extract and parse a JSON request body from a Lambda event."""
    raw = event.get("body")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        msg = "Request body must be a JSON string"
        raise ValueError(msg)
    return json.loads(raw)


def extract_job_id(event: dict[str, Any]) -> str:
    """Extract ``jobId`` from several Function URL request shapes."""
    path_parameters = event.get("pathParameters") or {}
    candidate = str(path_parameters.get("jobId") or event.get("jobId") or "").strip()
    if candidate:
        return candidate

    query = event.get("queryStringParameters") or {}
    query_candidate = str(query.get("jobId") or "").strip()
    if query_candidate:
        return query_candidate

    raw_path = str(event.get("rawPath") or "").strip()
    marker = "/status/"
    if marker in raw_path:
        return raw_path.split(marker, 1)[1].strip("/")

    request_context = event.get("requestContext") or {}
    http_context = request_context.get("http") or {}
    http_path = str(http_context.get("path") or "").strip()
    if marker in http_path:
        return http_path.split(marker, 1)[1].strip("/")

    return ""


def request_id_from_event(event: dict[str, Any]) -> str | None:
    """Extract a request id when the event includes HTTP request context."""
    request_context = event.get("requestContext") or {}
    return request_context.get("requestId") or (request_context.get("http") or {}).get("requestId")
