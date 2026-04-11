"""Shared retry, deadline, and logging helpers for the orchestrator."""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pipeline import config
from pipeline.config import STAGE_FAILED
from pipeline.shared.logging import log_event

if TYPE_CHECKING:
    from pipeline.storage.job_store import JobStore

NON_RETRYABLE_MODEL_ERROR_MARKERS = (
    "accessdeniedexception",
    "not authorized",
)


class OrchestratorStageCommonMixin:
    """Provide shared retry, deadline, and logging helpers.

    Requires the host class to define these instance attributes in its ``__init__``:
    - ``_job_store: JobStore``
    - ``_agentcore_client: Any``
    - ``_run_started_at: float | None``
    - ``_remaining_time_provider: Callable[[], int] | None``
    """

    # Declared so type-checkers can verify mixin attribute access.
    # These are assigned by PipelineOrchestrator.__init__ at runtime.
    if TYPE_CHECKING:
        _job_store: JobStore
        _agentcore_client: Any
        _run_started_at: float | None
        _remaining_time_provider: Callable[[], int] | None

    def _handle_agent_invoke_failure(
        self,
        *,
        job_id: str,
        attempt: int,
        error: Exception,
        elapsed_ms: int,
        component: str,
        event: str,
        stop_reason: str,
        model_id: str,
        human_label: str,
    ) -> dict[str, str] | None:
        """Log an agent model-call failure and decide whether to retry.

        Args:
            job_id: Generation job identifier.
            attempt: Zero-based attempt number.
            error: Invocation failure.
            elapsed_ms: Stage duration in milliseconds.
            component: Logging component name.
            event: Logging event name.
            stop_reason: Failure reason code returned on terminal failure.
            model_id: Bedrock model identifier.
            human_label: Readable agent label for messages.

        Returns:
            ``None`` when the caller should retry, otherwise a failure result payload.
        """
        retryable = (
            attempt < config.MAX_AGENT_RETRY_COUNT and not self._is_non_retryable_model_error(error)
        )
        deadline_retry_blocked = retryable and self._retry_exceeds_deadline_budget(
            last_attempt_elapsed_ms=elapsed_ms
        )
        if deadline_retry_blocked:
            retryable = False
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "handle_agent_invoke_failure_start",
            message="Handling an agent model invocation failure.",
            job_id=job_id,
            agent_component=component,
            attempt=attempt,
            elapsed_ms=elapsed_ms,
            error_type=type(error).__name__,
            retryable=retryable,
        )
        error_type = type(error).__name__
        error_message = f"{error_type}: {error}"
        self._log_agent_event(
            level="WARN" if retryable else "ERROR",
            job_id=job_id,
            component=component,
            event=event,
            message=(
                f"{human_label} model call failed and will be retried."
                if retryable
                else f"{human_label} model call failed and the job will stop."
            ),
            duration_ms=elapsed_ms,
            model_id=model_id,
            input_tokens=0,
            output_tokens=0,
            retry_count=attempt,
            validation_result="fail",
            validation_errors=[error_message],
            retryable=retryable,
        )

        if not retryable:
            if deadline_retry_blocked:
                return self._fail_due_to_retry_deadline(
                    job_id=job_id,
                    human_label=human_label,
                    validation_errors=[error_message],
                )
            self._job_store.mark_failed(
                job_id=job_id,
                error_message=f"{human_label} model call failed ({error_type}): {error}",
                stage=STAGE_FAILED,
            )
            return {
                "result": "failed",
                "reason": stop_reason,
                "errorType": error_type,
                "error": str(error),
            }

        self._sleep_with_backoff(attempt)
        return None

    def _handle_output_token_ceiling(
        self,
        *,
        job_id: str,
        attempt: int,
        usage: Any,
        elapsed_ms: int,
        component: str,
        human_label: str,
        max_output_tokens: int,
        prompt: str,
        response_text: str,
        model_id: str = "",
    ) -> dict[str, str] | None:
        """Fail immediately when a stage response exceeds the output budget.

        Args:
            job_id: Generation job identifier.
            attempt: Zero-based attempt number.
            usage: Usage object exposing ``input_tokens`` and ``output_tokens``.
            elapsed_ms: Stage duration in milliseconds.
            component: Logging component name.
            human_label: Readable stage label.
            max_output_tokens: Allowed output-token ceiling for this one stage.
            prompt: Latest prompt text.
            response_text: Latest raw response text.
            model_id: Bedrock model identifier for logging context.

        Returns:
            ``None`` when the output is within budget, otherwise a failure payload.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "handle_output_token_ceiling_start",
            message="Checking whether the stage output exceeded the configured token budget.",
            job_id=job_id,
            agent_component=component,
            attempt=attempt,
            elapsed_ms=elapsed_ms,
            output_tokens=usage.output_tokens,
            max_output_tokens=max_output_tokens,
        )
        if usage.output_tokens <= max_output_tokens:
            return None

        self._job_store.mark_failed(
            job_id=job_id,
            error_message=(
                f"{human_label} output token ceiling exceeded: "
                f"{usage.output_tokens}>{max_output_tokens}"
            ),
            stage=STAGE_FAILED,
        )
        self._log_agent_event(
            level="ERROR",
            job_id=job_id,
            component=component,
            event="agent_call_complete",
            message=(
                f"{human_label} call completed but exceeded the configured output token budget."
            ),
            duration_ms=elapsed_ms,
            model_id=model_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            retry_count=attempt,
            validation_result="fail",
            validation_errors=["output token ceiling exceeded"],
            prompt=prompt,
            response_text=response_text,
        )
        return {"result": "failed", "reason": "output_token_ceiling_exceeded"}

    def _create_agentcore_session(self, *, job_id: str) -> str:
        """Create a new AgentCore session for one generation job.

        Args:
            job_id: Generation job identifier.

        Returns:
            Session identifier string.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "create_agentcore_session_start",
            message="Creating or reusing an AgentCore session for the job.",
            job_id=job_id,
            has_create_session=hasattr(self._agentcore_client, "create_session"),
        )
        if hasattr(self._agentcore_client, "create_session"):
            response = self._agentcore_client.create_session(clientToken=job_id)
            return str(response.get("sessionId") or response.get("sessionArn") or job_id)
        return job_id

    def _remaining_job_deadline_ms(self) -> int:
        """Return the remaining soft job deadline budget in milliseconds."""
        if self._run_started_at is None:
            soft_remaining_ms = config.JOB_DEADLINE_SECONDS * 1000
        else:
            elapsed_ms = int((time.perf_counter() - self._run_started_at) * 1000)
            soft_remaining_ms = max(0, config.JOB_DEADLINE_SECONDS * 1000 - elapsed_ms)
        if self._remaining_time_provider is None:
            return soft_remaining_ms
        return min(soft_remaining_ms, int(self._remaining_time_provider()))

    def _ensure_stage_start_budget(
        self,
        *,
        job_id: str,
        human_label: str,
    ) -> dict[str, str] | None:
        """Fail fast when too little deadline budget remains for another heavy stage."""
        remaining_ms = self._remaining_job_deadline_ms()
        minimum_required_ms = config.MIN_STAGE_START_BUDGET_SECONDS * 1000
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "ensure_stage_start_budget",
            message="Checking whether enough deadline budget remains to start a heavy stage.",
            job_id=job_id,
            human_label=human_label,
            remaining_ms=remaining_ms,
            minimum_required_ms=minimum_required_ms,
        )
        if remaining_ms >= minimum_required_ms:
            return None
        return self._fail_due_to_retry_deadline(
            job_id=job_id,
            human_label=human_label,
            validation_errors=[
                f"remaining job deadline budget {remaining_ms}ms is below the minimum "
                f"stage-start budget of {minimum_required_ms}ms"
            ],
        )

    def _retry_exceeds_deadline_budget(self, *, last_attempt_elapsed_ms: int) -> bool:
        """Return whether another similarly expensive retry would exceed the deadline."""
        remaining_ms = self._remaining_job_deadline_ms()
        required_ms = last_attempt_elapsed_ms + (
            config.RETRY_DEADLINE_SAFETY_MARGIN_SECONDS * 1000
        )
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "retry_deadline_budget_check",
            message="Checking whether enough job deadline budget remains for another retry.",
            remaining_ms=remaining_ms,
            last_attempt_elapsed_ms=last_attempt_elapsed_ms,
            required_ms=required_ms,
        )
        return remaining_ms <= required_ms

    def _fail_due_to_retry_deadline(
        self,
        *,
        job_id: str,
        human_label: str,
        validation_errors: list[str],
    ) -> dict[str, str]:
        """Mark the job failed when another safe retry cannot fit the deadline."""
        error_message = (
            f"{human_label} retry skipped because the remaining job deadline is too short for "
            f"another safe attempt. Remaining budget ms: {self._remaining_job_deadline_ms()}. "
            f"Latest errors: {'; '.join(validation_errors)}"
        )
        self._job_store.mark_failed(
            job_id=job_id,
            error_message=error_message,
            stage=STAGE_FAILED,
        )
        return {"result": "failed", "reason": "job_deadline_exhausted", "error": error_message}

    def _is_non_retryable_model_error(self, error: Exception) -> bool:
        """Return whether the model error is known to be non-transient.

        Args:
            error: Exception raised by the Bedrock call.

        Returns:
            ``True`` when the error should stop immediately, otherwise ``False``.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "is_non_retryable_model_error_start",
            message="Classifying whether the model error should be retried.",
            error_type=type(error).__name__,
        )
        error_text = f"{type(error).__name__}: {error}".lower()
        return any(marker in error_text for marker in NON_RETRYABLE_MODEL_ERROR_MARKERS)

    def _log_agent_event(
        self,
        *,
        level: str,
        job_id: str,
        component: str,
        event: str,
        message: str,
        duration_ms: int,
        model_id: str | None,
        input_tokens: int,
        output_tokens: int,
        retry_count: int,
        validation_result: str,
        validation_errors: list[str] | None = None,
        retryable: bool | None = None,
        prompt: str | None = None,
        response_text: str | None = None,
    ) -> None:
        """Emit one readable orchestrator log line for agent activity.

        Args:
            level: Log level string.
            job_id: Generation job identifier.
            component: Component label for the log line.
            event: Event label for the log line.
            message: Human-readable log message.
            duration_ms: Stage duration in milliseconds.
            model_id: Model identifier when applicable.
            input_tokens: Input token count.
            output_tokens: Output token count.
            retry_count: Attempt number.
            validation_result: ``pass`` or ``fail``.
            validation_errors: Optional exact validation errors.
            retryable: Optional retryability flag for failures.
            prompt: Optional prompt text for VERBOSE logging.
            response_text: Optional raw response text for VERBOSE logging.
        """
        fields: dict[str, Any] = {
            "job_id": job_id,
            "duration_ms": duration_ms,
            "model_id": model_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "retry_count": retry_count,
            "validation_result": validation_result,
            "validation_errors": validation_errors,
            "retryable": retryable,
        }
        if os.getenv("VERBOSE", "false").lower() == "true":
            fields["prompt"] = prompt
            fields["response_text"] = response_text
        log_event(level, component, event, message=message, **fields)

    def _sleep_with_backoff(self, attempt: int) -> None:
        """Sleep using exponential backoff plus jitter.

        Args:
            attempt: Zero-based retry attempt number.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "sleep_with_backoff_start",
            message="Sleeping before the next retry attempt.",
            attempt=attempt,
        )
        base = 0.25
        delay = base * (2**attempt) + random.random()
        time.sleep(delay)

