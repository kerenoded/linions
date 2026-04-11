"""Shared readable logging helpers for the pipeline package.

The pipeline emits human-readable single-line logs instead of raw JSON blobs.
Every log line uses the same ``key=value`` shape so CloudWatch searches remain
easy while the output is still readable during development. Each log should
also include a short sentence describing what the code is doing so operators do
not need to decode internal event names while reading the console. Timestamps
are omitted from the message body because CloudWatch and local terminals
already add them externally.
"""

from __future__ import annotations

from typing import Any

_SENSITIVE_KEYS = {"authorization", "x-api-key", "cookie", "set-cookie"}
_MAX_LOG_VALUE_LENGTH = 500


def sanitize_for_log(value: Any, *, depth: int = 0) -> Any:
    """Return a log-safe version of ``value`` with secrets redacted."""
    if depth >= 4:
        return "<max-depth>"

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            lowered_key = str(key).lower()
            if lowered_key in _SENSITIVE_KEYS:
                sanitized[str(key)] = "<redacted>"
                continue
            sanitized[str(key)] = sanitize_for_log(nested, depth=depth + 1)
        return sanitized

    if isinstance(value, list):
        return [sanitize_for_log(item, depth=depth + 1) for item in value[:20]]

    if isinstance(value, str):
        if len(value) <= _MAX_LOG_VALUE_LENGTH:
            return value
        return f"{value[:_MAX_LOG_VALUE_LENGTH]}..."

    return value


def _quote_string(text: str) -> str:
    """Return a readable quoted string when the value needs escaping."""
    escaped = text.replace("\\", "\\\\").replace("\n", "\\n").replace("'", "\\'")
    if not text or any(char.isspace() or char in "|={}[]," for char in text):
        return f"'{escaped}'"
    return escaped


def _format_sanitized_value(value: Any) -> str:
    """Format an already-sanitized value for a single-line log field."""
    if isinstance(value, dict):
        items = ", ".join(
            f"{key}={_format_sanitized_value(nested)}" for key, nested in sorted(value.items())
        )
        return f"{{{items}}}"

    if isinstance(value, list):
        items = ", ".join(_format_sanitized_value(item) for item in value)
        return f"[{items}]"

    if isinstance(value, bool):
        return "true" if value else "false"

    if value is None:
        return "null"

    if isinstance(value, str):
        return _quote_string(value)

    return str(value)


def format_log_value(value: Any) -> str:
    """Format ``value`` for readable logging after sanitization."""
    return _format_sanitized_value(sanitize_for_log(value))


def _select_log_context(fields: dict[str, Any]) -> str:
    """Return the best available context label for the log prefix."""
    for key in ("job_id", "request_id", "session_id", "context_id"):
        candidate = fields.pop(key, None)
        if candidate is None:
            continue
        candidate_text = str(candidate).strip()
        if candidate_text and candidate_text.lower() != "n/a":
            return candidate_text
    return "system"


def log_event(
    level: str,
    component: str,
    event: str,
    *,
    message: str | None = None,
    **fields: Any,
) -> None:
    """Emit one readable log line with stable shared fields."""
    raw_fields = {key: value for key, value in fields.items() if value is not None}
    context = _format_sanitized_value(_select_log_context(raw_fields))
    sanitized_fields = {key: sanitize_for_log(value) for key, value in raw_fields.items()}
    prefix = f"{level} [{context}] [{component}.{event}]"
    if message:
        prefix = f"{prefix} {message}"

    if not sanitized_fields:
        print(prefix)
        return

    parts = [f"{key}={_format_sanitized_value(value)}" for key, value in sanitized_fields.items()]
    print(f"{prefix} - {' | '.join(parts)}")
