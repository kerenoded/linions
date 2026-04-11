"""Director and Animator stage helpers for the pipeline orchestrator."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from pipeline import config
from pipeline.agents.animator.parallel import run_animator_acts_in_parallel
from pipeline.config import (
    STAGE_ANIMATE_KEYFRAMES,
    STAGE_FAILED,
    STAGE_GENERATE_SCRIPT,
    STAGE_VALIDATE_SCRIPT,
)

if TYPE_CHECKING:
    from pipeline.agents.animator.agent import AnimatorAgent
    from pipeline.agents.director.agent import DirectorAgent
    from pipeline.lambdas.orchestrator.pipeline_orchestrator import LibraryLookups
    from pipeline.storage.job_store import JobStore

from pipeline.models import (
    Act,
    AnimatorInput,
    AnimatorOutput,
    Choice,
    ClipManifest,
    DirectorInput,
    DirectorOutput,
)
from pipeline.shared.logging import log_event
from pipeline.validators.frame_repairs import repair_animator_keyframe_bounds
from pipeline.validators.frame_validator import validate_frames
from pipeline.validators.script_validator import validate_script


class OrchestratorDirectorAnimatorMixin:
    """Provide the Director and Animator stage workflows.

    Requires the host class to define these instance attributes in its ``__init__``:
    - ``_job_store: JobStore``
    - ``_director_agent: DirectorAgent``
    - ``_animator_agent: AnimatorAgent``
    - ``_library_lookups: LibraryLookups``
    Also inherits shared helpers from ``OrchestratorStageCommonMixin``.
    """

    if TYPE_CHECKING:
        _job_store: JobStore
        _director_agent: DirectorAgent
        _animator_agent: AnimatorAgent
        _library_lookups: LibraryLookups

    def _run_director_attempts(
        self,
        *,
        job_id: str,
        prompt: str,
        username: str,
        session_id: str,
        rag_context: str,
    ) -> DirectorOutput | dict[str, str]:
        """Run the Director stage with retries for model and validation failures.

        Args:
            job_id: Generation job identifier.
            prompt: User prompt text.
            username: Developer username.
            session_id: Shared AgentCore session id.
            rag_context: Retrieved RAG context.

        Returns:
            ``DirectorOutput`` on success, otherwise a failure result payload.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "run_director_attempts_start",
            message="Starting the Director retry loop for this job.",
            job_id=job_id,
            username=username,
            session_id=session_id,
            has_rag_context=bool(rag_context),
            rag_context_length=len(rag_context),
        )
        errors_for_retry: list[str] | None = None

        for attempt in range(config.MAX_AGENT_RETRY_COUNT + 1):
            stage_budget_failure = self._ensure_stage_start_budget(
                job_id=job_id,
                human_label="Director",
            )
            if stage_budget_failure is not None:
                return stage_budget_failure
            log_event(
                "DEBUG",
                "PipelineOrchestrator",
                "director_attempt_start",
                message="Starting a Director generation attempt.",
                job_id=job_id,
                attempt=attempt,
                max_attempt=config.MAX_AGENT_RETRY_COUNT,
                has_validation_errors=errors_for_retry is not None,
            )
            self._job_store.update_stage_generating(job_id, STAGE_GENERATE_SCRIPT)
            started = time.perf_counter()

            try:
                output = self._director_agent.run(
                    DirectorInput(
                        prompt=prompt,
                        username=username,
                        job_id=job_id,
                        session_id=session_id,
                        rag_context=rag_context,
                        preferred_obstacle_library_names=self._library_lookups.list_obstacle_names(),
                    ),
                    validation_errors=errors_for_retry,
                )
            except Exception as error:
                failure = self._handle_agent_invoke_failure(
                    job_id=job_id,
                    attempt=attempt,
                    error=error,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    component="DirectorAgent",
                    event="director_invoke_failed",
                    stop_reason="director_model_call_failed",
                    model_id=config.BEDROCK_MODEL_ID_DIRECTOR,
                    human_label="Director",
                )
                if failure is not None:
                    return failure
                continue

            usage = self._director_agent.get_last_usage()
            elapsed_ms = int((time.perf_counter() - started) * 1000)

            token_failure = self._handle_output_token_ceiling(
                job_id=job_id,
                attempt=attempt,
                usage=usage,
                elapsed_ms=elapsed_ms,
                component="DirectorAgent",
                human_label="Director",
                max_output_tokens=config.MAX_OUTPUT_TOKENS_DIRECTOR_STAGE,
                prompt=self._director_agent.get_last_prompt(),
                response_text=self._director_agent.get_last_response_text(),
                model_id=config.BEDROCK_MODEL_ID_DIRECTOR,
            )
            if token_failure is not None:
                return token_failure

            output = self._normalise_director_output(job_id=job_id, output=output)
            validation_errors = self._validate_director_output(job_id=job_id, output=output)
            self._log_agent_event(
                level="INFO" if validation_errors is None else "WARN",
                job_id=job_id,
                component="DirectorAgent",
                event="agent_call_complete",
                message=(
                    "Director call completed and passed deterministic validation."
                    if validation_errors is None
                    else "Director call completed but the output failed deterministic validation."
                ),
                duration_ms=elapsed_ms,
                model_id=config.BEDROCK_MODEL_ID_DIRECTOR,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                retry_count=attempt,
                validation_result="pass" if validation_errors is None else "fail",
                validation_errors=validation_errors,
                prompt=self._director_agent.get_last_prompt(),
                response_text=self._director_agent.get_last_response_text(),
            )

            if validation_errors is None:
                return output

            if attempt == config.MAX_AGENT_RETRY_COUNT:
                self._job_store.mark_failed(
                    job_id=job_id,
                    error_message="; ".join(validation_errors),
                    stage=STAGE_FAILED,
                )
                return {"result": "failed", "reason": "validation_retries_exhausted"}

            if self._retry_exceeds_deadline_budget(last_attempt_elapsed_ms=elapsed_ms):
                return self._fail_due_to_retry_deadline(
                    job_id=job_id,
                    human_label="Director",
                    validation_errors=validation_errors,
                )

            errors_for_retry = validation_errors
            self._sleep_with_backoff(attempt)

        return {"result": "failed", "reason": "unexpected_fallthrough"}  # pragma: no cover

    def _run_animator_attempts(
        self,
        *,
        job_id: str,
        session_id: str,
        director_output: DirectorOutput,
    ) -> AnimatorOutput | dict[str, str]:
        """Run the Animator stage with retries for model and validation failures.

        Args:
            job_id: Generation job identifier.
            session_id: Shared AgentCore session id.
            director_output: Validated Director output.

        Returns:
            ``AnimatorOutput`` on success, otherwise a failure result payload.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "run_animator_attempts_start",
            message="Starting the Animator retry loop for this job.",
            job_id=job_id,
            session_id=session_id,
            act_count=len(director_output.acts),
        )
        animator_input = self._build_animator_input(
            job_id=job_id,
            session_id=session_id,
            director_output=director_output,
        )
        completed_outputs: dict[int, AnimatorOutput] = {}
        errors_for_retry_by_act: dict[int, list[str] | None] = {
            act.act_index: None for act in animator_input.acts
        }

        for attempt in range(config.MAX_AGENT_RETRY_COUNT + 1):
            pending_act_indices = sorted(errors_for_retry_by_act)
            if not pending_act_indices:
                merged_output = self._merge_animator_outputs(
                    animator_input=animator_input,
                    completed_outputs=completed_outputs,
                )
                merged_validation_errors = self._validate_animator_output(
                    job_id=job_id,
                    output=merged_output,
                    animator_input=animator_input,
                )
                if merged_validation_errors is None:
                    return merged_output
                self._job_store.mark_failed(
                    job_id=job_id,
                    error_message="; ".join(merged_validation_errors),
                    stage=STAGE_FAILED,
                )
                return {"result": "failed", "reason": "animator_validation_retries_exhausted"}

            stage_budget_failure = self._ensure_stage_start_budget(
                job_id=job_id,
                human_label="Animator",
            )
            if stage_budget_failure is not None:
                return stage_budget_failure

            log_event(
                "DEBUG",
                "PipelineOrchestrator",
                "animator_attempt_start",
                message="Starting parallel Animator generation for the remaining acts.",
                job_id=job_id,
                attempt=attempt,
                max_attempt=config.MAX_AGENT_RETRY_COUNT,
                pending_act_indices=pending_act_indices,
            )
            self._job_store.update_stage_generating(job_id, STAGE_ANIMATE_KEYFRAMES)
            attempt_started = time.perf_counter()
            results = run_animator_acts_in_parallel(
                base_agent=self._animator_agent,
                animator_inputs=[
                    self._build_animator_input(
                        job_id=job_id,
                        session_id=session_id,
                        director_output=director_output,
                        acts=[act],
                    )
                    for act in animator_input.acts
                    if act.act_index in errors_for_retry_by_act
                ],
                validation_errors_by_act=errors_for_retry_by_act,
            )

            next_errors_for_retry_by_act: dict[int, list[str] | None] = {}
            collected_validation_errors: list[str] = []

            for result in sorted(results, key=lambda item: item.act_index):
                act_human_label = f"Animator act {result.act_index}"
                elapsed_ms = int((time.perf_counter() - attempt_started) * 1000)

                if result.error is not None:
                    failure = self._handle_agent_invoke_failure(
                        job_id=job_id,
                        attempt=attempt,
                        error=result.error,
                        elapsed_ms=elapsed_ms,
                        component="AnimatorAgent",
                        event="animator_invoke_failed",
                        stop_reason="animator_model_call_failed",
                        model_id=config.BEDROCK_MODEL_ID_ANIMATOR,
                        human_label=act_human_label,
                    )
                    if failure is not None:
                        return failure
                    next_errors_for_retry_by_act[result.act_index] = None
                    continue

                if result.output is None:
                    msg = f"Animator act {result.act_index} finished without output or error"
                    raise RuntimeError(msg)

                output = self._normalise_animator_output(
                    job_id=job_id,
                    output=result.output,
                )
                token_failure = self._handle_output_token_ceiling(
                    job_id=job_id,
                    attempt=attempt,
                    usage=result.usage,
                    elapsed_ms=elapsed_ms,
                    component="AnimatorAgent",
                    human_label=act_human_label,
                    max_output_tokens=config.MAX_OUTPUT_TOKENS_ANIMATOR_STAGE,
                    prompt=result.prompt,
                    response_text=result.response_text,
                    model_id=config.BEDROCK_MODEL_ID_ANIMATOR,
                )
                if token_failure is not None:
                    return token_failure

                validation_errors = self._validate_animator_output(
                    job_id=job_id,
                    output=output,
                    animator_input=animator_input,
                    act_indices_to_validate={result.act_index},
                )
                self._log_agent_event(
                    level="INFO" if validation_errors is None else "WARN",
                    job_id=job_id,
                    component="AnimatorAgent",
                    event="agent_call_complete",
                    message=(
                        (
                            f"Animator act {result.act_index} completed and passed "
                            "deterministic validation."
                        )
                        if validation_errors is None
                        else (
                            f"Animator act {result.act_index} completed but failed deterministic "
                            "validation."
                        )
                    ),
                    duration_ms=elapsed_ms,
                    model_id=config.BEDROCK_MODEL_ID_ANIMATOR,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    retry_count=attempt,
                    validation_result="pass" if validation_errors is None else "fail",
                    validation_errors=validation_errors,
                    prompt=result.prompt,
                    response_text=result.response_text,
                )

                if validation_errors is not None and all(
                    "out of bounds" in error for error in validation_errors
                ):
                    repaired_output = repair_animator_keyframe_bounds(
                        output,
                        canvas_width=animator_input.canvas_width,
                        canvas_height=animator_input.canvas_height,
                    )
                    repaired_errors = self._validate_animator_output(
                        job_id=job_id,
                        output=repaired_output,
                        animator_input=animator_input,
                        act_indices_to_validate={result.act_index},
                    )
                    if repaired_errors is None:
                        output = repaired_output
                        validation_errors = None

                if validation_errors is None:
                    completed_outputs[result.act_index] = output
                    continue

                collected_validation_errors.extend(validation_errors)
                next_errors_for_retry_by_act[result.act_index] = validation_errors

            if not next_errors_for_retry_by_act:
                merged_output = self._merge_animator_outputs(
                    animator_input=animator_input,
                    completed_outputs=completed_outputs,
                )
                merged_validation_errors = self._validate_animator_output(
                    job_id=job_id,
                    output=merged_output,
                    animator_input=animator_input,
                )
                if merged_validation_errors is None:
                    return merged_output
                self._job_store.mark_failed(
                    job_id=job_id,
                    error_message="; ".join(merged_validation_errors),
                    stage=STAGE_FAILED,
                )
                return {"result": "failed", "reason": "animator_validation_retries_exhausted"}

            if attempt == config.MAX_AGENT_RETRY_COUNT:
                self._job_store.mark_failed(
                    job_id=job_id,
                    error_message="; ".join(collected_validation_errors),
                    stage=STAGE_FAILED,
                )
                return {"result": "failed", "reason": "animator_validation_retries_exhausted"}

            if self._retry_exceeds_deadline_budget(
                last_attempt_elapsed_ms=int((time.perf_counter() - attempt_started) * 1000)
            ):
                return self._fail_due_to_retry_deadline(
                    job_id=job_id,
                    human_label="Animator",
                    validation_errors=collected_validation_errors,
                )

            errors_for_retry_by_act = next_errors_for_retry_by_act
            self._sleep_with_backoff(attempt)

        return {"result": "failed", "reason": "unexpected_fallthrough"}  # pragma: no cover

    def _validate_director_output(
        self,
        *,
        job_id: str,
        output: DirectorOutput,
    ) -> list[str] | None:
        """Run deterministic validation for Director output.

        Args:
            job_id: Generation job identifier.
            output: Director output to validate.

        Returns:
            ``None`` when valid, otherwise the exact validation errors list.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "validate_director_output_start",
            message="Running deterministic validation for the Director output.",
            job_id=job_id,
        )
        self._job_store.update_stage_generating(job_id, STAGE_VALIDATE_SCRIPT)
        result = validate_script(
            output,
            preferred_obstacle_library_names=self._library_lookups.list_obstacle_names(),
        )
        if result.is_valid:
            return None
        return result.errors

    def _normalise_director_output(
        self,
        *,
        job_id: str,
        output: DirectorOutput,
    ) -> DirectorOutput:
        """Clamp minor Director text overflows to configured UI-safe limits."""
        title = self._truncate_text_for_limit(
            output.title,
            config.MAX_TITLE_LENGTH_CHARS,
        )
        description = self._truncate_text_for_limit(
            output.description,
            config.MAX_DESCRIPTION_LENGTH_CHARS,
        )
        trimmed_choice_labels = 0
        acts: list[Act] = []
        acts_changed = False
        for act in output.acts:
            choices: list[Choice] = []
            choices_changed = False
            for choice in act.choices:
                label = self._truncate_text_for_limit(
                    choice.label,
                    config.MAX_CHOICE_LABEL_LENGTH_CHARS,
                )
                if label != choice.label:
                    trimmed_choice_labels += 1
                    choices_changed = True
                choices.append(
                    choice
                    if label == choice.label
                    else choice.model_copy(update={"label": label})
                )
            acts.append(
                act if not choices_changed else act.model_copy(update={"choices": choices})
            )
            acts_changed = acts_changed or choices_changed

        if title == output.title and description == output.description and not acts_changed:
            return output

        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "normalise_director_output",
            message=(
                "Normalised Director text fields to configured UI-safe limits "
                "before validation."
            ),
            job_id=job_id,
            title_trimmed=title != output.title,
            description_trimmed=description != output.description,
            trimmed_choice_labels=trimmed_choice_labels,
        )
        return output.model_copy(
            update={
                "title": title,
                "description": description,
                "acts": acts,
            }
        )

    def _truncate_text_for_limit(self, value: str, max_length: int) -> str:
        """Return text trimmed to ``max_length``, preserving readability with ellipsis."""
        if len(value) <= max_length:
            return value
        if max_length <= 3:
            return value[:max_length]
        return f"{value[: max_length - 3].rstrip()}..."

    def _build_animator_input(
        self,
        *,
        job_id: str,
        session_id: str,
        director_output: DirectorOutput,
        acts: list[Any] | None = None,
    ) -> AnimatorInput:
        """Build the typed Animator input from validated Director output.

        Args:
            job_id: Generation job identifier.
            session_id: Shared AgentCore session id.
            director_output: Validated Director output.

        Returns:
            Fully-typed ``AnimatorInput``.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "build_animator_input_start",
            message="Building the Animator input from validated Director output and config.",
            job_id=job_id,
            session_id=session_id,
            act_count=len(director_output.acts),
        )
        selected_acts = director_output.acts if acts is None else acts
        first_act_index = director_output.acts[0].act_index if director_output.acts else 0
        requires_handoff_in = False
        requires_handoff_out = False
        if len(selected_acts) == 1:
            selected_act_index = selected_acts[0].act_index
            requires_handoff_in = selected_act_index != first_act_index
        return AnimatorInput(
            job_id=job_id,
            session_id=session_id,
            acts=selected_acts,
            walk_duration_seconds=config.WALK_DURATION_SECONDS,
            canvas_width=config.CANVAS_WIDTH,
            canvas_height=config.CANVAS_HEIGHT,
            ground_line_y=config.GROUND_LINE_Y,
            handoff_character_x=config.HANDOFF_CHARACTER_X,
            requires_handoff_in=requires_handoff_in,
            requires_handoff_out=requires_handoff_out,
        )

    def _normalise_animator_output(
        self,
        *,
        job_id: str,
        output: AnimatorOutput,
    ) -> AnimatorOutput:
        """Snap small grounded character_y near-misses onto support_y before validation."""
        normalised_clip_count = 0
        normalised_keyframe_count = 0
        updated_clips: list[ClipManifest] = []

        for clip in output.clips:
            updated_keyframes: list[Any] = []
            clip_changed = False
            for keyframe in clip.keyframes:
                if (
                    keyframe.is_grounded
                    and keyframe.character_y != keyframe.support_y
                    and abs(keyframe.character_y - keyframe.support_y)
                    <= config.ANIMATOR_GROUNDED_CHARACTER_Y_NORMALIZE_TOLERANCE_PX
                ):
                    updated_keyframes.append(
                        keyframe.model_copy(update={"character_y": keyframe.support_y})
                    )
                    clip_changed = True
                    normalised_keyframe_count += 1
                    continue
                updated_keyframes.append(keyframe)

            if clip_changed:
                updated_clips.append(clip.model_copy(update={"keyframes": updated_keyframes}))
                normalised_clip_count += 1
            else:
                updated_clips.append(clip)

        if normalised_keyframe_count == 0:
            return output

        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "normalise_animator_output",
            message=(
                "Normalised small grounded Animator character_y drifts onto support_y "
                "before validation."
            ),
            job_id=job_id,
            normalised_clip_count=normalised_clip_count,
            normalised_keyframe_count=normalised_keyframe_count,
            normalize_tolerance_px=config.ANIMATOR_GROUNDED_CHARACTER_Y_NORMALIZE_TOLERANCE_PX,
        )
        return output.model_copy(update={"clips": updated_clips})

    def _merge_animator_outputs(
        self,
        *,
        animator_input: AnimatorInput,
        completed_outputs: dict[int, AnimatorOutput],
    ) -> AnimatorOutput:
        """Merge one validated AnimatorOutput per act into one episode manifest."""
        ordered_clips = []
        for act in animator_input.acts:
            output = completed_outputs.get(act.act_index)
            if output is None:
                msg = f"Missing completed Animator output for act {act.act_index}"
                raise RuntimeError(msg)
            ordered_clips.extend(output.clips)
        return AnimatorOutput(clips=ordered_clips)

    def _validate_animator_output(
        self,
        *,
        job_id: str,
        output: AnimatorOutput,
        animator_input: AnimatorInput,
        act_indices_to_validate: set[int] | None = None,
    ) -> list[str] | None:
        """Run deterministic validation for Animator output.

        Args:
            job_id: Generation job identifier.
            output: Animator output to validate.
            animator_input: Original typed Animator input for contextual checks.
            act_indices_to_validate: Optional subset of act indexes to validate.

        Returns:
            ``None`` when valid, otherwise the exact validation errors list.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "validate_animator_output_start",
            message="Running deterministic validation for the Animator output.",
            job_id=job_id,
            clip_count=len(output.clips),
        )
        result = validate_frames(
            output,
            animator_input,
            act_indices_to_validate=act_indices_to_validate,
        )
        if result.is_valid:
            return None
        return result.errors

