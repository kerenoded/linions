"""Drawing and Renderer stage helpers for the pipeline orchestrator."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

from pipeline import config
from pipeline.agents.drawing.parallel import run_drawing_tasks_in_parallel
from pipeline.agents.renderer.parallel import run_renderer_clips_in_parallel
from pipeline.agents.renderer.scene_composer import compose_renderer_scene_svg
from pipeline.config import STAGE_DRAW_ASSETS, STAGE_FAILED, STAGE_RENDER_SVG

if TYPE_CHECKING:
    from pipeline.agents.drawing.agent import DrawingAgent
    from pipeline.agents.renderer.agent import RendererAgent
    from pipeline.lambdas.orchestrator.pipeline_orchestrator import LibraryLookups
    from pipeline.storage.job_store import JobStore

from pipeline.models import (
    AnimatorOutput,
    ClipManifest,
    DirectorOutput,
    DrawingInput,
    RendererInput,
    RendererOutput,
    SvgClip,
)
from pipeline.shared.logging import log_event
from pipeline.validators.renderer_motion_repairs import (
    repair_renderer_body_scale,
    repair_renderer_eye_motion,
    repair_renderer_root_translate,
    repair_renderer_unsupported_animation_targets,
)
from pipeline.validators.renderer_motion_validator import validate_renderer_motion
from pipeline.validators.svg_linter import validate_and_sanitise_svg

DRAWING_REQUIRED_IDS = {"obstacle-root", "obstacle-main", "obstacle-animated-part"}
DRAWING_ANIMATED_IDS = {"obstacle-animated-part"}
BACKGROUND_REQUIRED_IDS: set[str] = {
    "background-root",
    "background-main",
    "background-animated-part",
}
BACKGROUND_ANIMATED_IDS: set[str] = {"background-animated-part"}
RENDERER_REQUIRED_LINAI_IDS = {
    "linai-body",
    "linai-eye-left",
    "linai-eye-right",
    "linai-mouth",
    "linai-inner-patterns",
    "linai-particles",
    "linai-trails",
}
RENDERER_REQUIRED_IDS = RENDERER_REQUIRED_LINAI_IDS | {
    "linai",
    "obstacle-root",
    "obstacle-main",
    "obstacle-animated-part",
}
RENDERER_ANIMATED_IDS = {"obstacle-animated-part"}


class OrchestratorRenderAssetsMixin:
    """Provide Drawing and Renderer stage workflows.

    Requires the host class to define these instance attributes in its ``__init__``:
    - ``_job_store: JobStore``
    - ``_drawing_agent: DrawingAgent | None``
    - ``_renderer_agent: RendererAgent | None``
    - ``_library_lookups: LibraryLookups``
    Also inherits shared helpers from ``OrchestratorStageCommonMixin``.
    """

    if TYPE_CHECKING:
        _job_store: JobStore
        _drawing_agent: DrawingAgent | None
        _renderer_agent: RendererAgent | None
        _library_lookups: LibraryLookups

    def _resolve_drawing_svgs(
        self,
        *,
        job_id: str,
        session_id: str,
        director_output: DirectorOutput,
        animator_output: AnimatorOutput,
    ) -> AnimatorOutput | dict[str, str]:
        """Resolve missing obstacle SVGs and per-act backgrounds in parallel."""
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "resolve_drawing_svgs_start",
            message="Resolving missing obstacle SVGs and act backgrounds for the render stage.",
            job_id=job_id,
            clip_count=len(animator_output.clips),
            unique_obstacle_count=len({clip.obstacle_type for clip in animator_output.clips}),
            act_count=len(director_output.acts),
        )
        self._job_store.update_stage_generating(job_id, STAGE_DRAW_ASSETS)
        obstacle_svgs: dict[str, str] = {}
        background_svgs: dict[int, str] = {}
        background_svgs_by_slug: dict[str, str] = {}
        background_slug_by_act_index: dict[int, str] = {}
        drawing_inputs_by_identity: dict[tuple[str, str], DrawingInput] = {}
        obstacle_slug_by_identity: dict[tuple[str, str], str] = {}
        background_act_by_identity: dict[tuple[str, str], list[int]] = {}

        for slug in sorted({act.obstacle_type for act in director_output.acts}):
            svg = self._library_lookups.get_obstacle_svg(slug)
            if svg is None:
                act_for_slug = next(
                    act for act in director_output.acts if act.obstacle_type == slug
                )
                drawing_input = DrawingInput(
                    job_id=job_id,
                    session_id=session_id,
                    obstacle_type=slug,
                    drawing_prompt=act_for_slug.drawing_prompt or "",
                    drawing_type="obstacle",
                )
                identity = (drawing_input.drawing_type, drawing_input.obstacle_type)
                drawing_inputs_by_identity[identity] = drawing_input
                obstacle_slug_by_identity[identity] = slug
                continue
            obstacle_svgs[slug] = svg

        used_library_slugs: set[str] = set()
        used_background_slugs: set[str] = set()
        for act in director_output.acts:
            background_library_slug = self._library_lookups.find_background_library_slug(
                act.background_drawing_prompt,
                act.approach_description,
            )
            if (
                background_library_slug is not None
                and background_library_slug not in used_library_slugs
            ):
                background_svg = background_svgs_by_slug.get(background_library_slug)
                if background_svg is None:
                    background_svg = self._library_lookups.get_background_svg(
                        background_library_slug
                    )
                if background_svg is not None:
                    used_library_slugs.add(background_library_slug)
                    used_background_slugs.add(background_library_slug)
                    background_svgs_by_slug[background_library_slug] = background_svg
                    background_svgs[act.act_index] = background_svg
                    background_slug_by_act_index[act.act_index] = background_library_slug
                    continue

            base_bg_slug = self._library_lookups.prompt_to_background_slug(
                act.background_drawing_prompt
            )
            bg_slug = self._allocate_unique_background_slug(
                base_slug=base_bg_slug,
                used_slugs=used_background_slugs,
            )
            identity = ("background", bg_slug)
            drawing_input = DrawingInput(
                job_id=job_id,
                session_id=session_id,
                obstacle_type=bg_slug,
                drawing_prompt=act.background_drawing_prompt,
                drawing_type="background",
            )
            drawing_inputs_by_identity[identity] = drawing_input
            background_act_by_identity[identity] = [act.act_index]
            background_slug_by_act_index[act.act_index] = bg_slug

        completed_svgs_by_identity: dict[tuple[str, str], str] = {}
        errors_for_retry_by_identity: dict[tuple[str, str], list[str] | None] = {
            identity: None for identity in drawing_inputs_by_identity
        }

        for attempt in range(config.MAX_AGENT_RETRY_COUNT + 1):
            pending_identities = sorted(errors_for_retry_by_identity)
            if not pending_identities:
                break

            stage_budget_failure = self._ensure_stage_start_budget(
                job_id=job_id,
                human_label="Drawing",
            )
            if stage_budget_failure is not None:
                return stage_budget_failure

            log_event(
                "DEBUG",
                "PipelineOrchestrator",
                "drawing_attempt_start",
                message="Starting parallel Drawing generation for the remaining render assets.",
                job_id=job_id,
                attempt=attempt,
                max_attempt=config.MAX_AGENT_RETRY_COUNT,
                task_count=len(pending_identities),
                has_validation_errors=any(
                    errors is not None for errors in errors_for_retry_by_identity.values()
                ),
            )

            next_errors_for_retry_by_identity: dict[tuple[str, str], list[str] | None] = {}
            collected_validation_errors: list[str] = []
            results = run_drawing_tasks_in_parallel(
                base_agent=self._drawing_agent,
                drawing_inputs=[
                    drawing_inputs_by_identity[identity] for identity in pending_identities
                ],
                validation_errors_by_identity=errors_for_retry_by_identity,
                max_workers=config.MAX_PARALLEL_DRAWING_TASKS,
            )

            for result in sorted(results, key=lambda item: item.task_identity):
                drawing_input = result.drawing_input
                human_label = self._describe_drawing_task(drawing_input)
                elapsed_ms = result.elapsed_ms

                if result.error is not None:
                    failure = self._handle_agent_invoke_failure(
                        job_id=job_id,
                        attempt=attempt,
                        error=result.error,
                        elapsed_ms=elapsed_ms,
                        component="DrawingAgent",
                        event="drawing_invoke_failed",
                        stop_reason="drawing_model_call_failed",
                        model_id=config.BEDROCK_MODEL_ID_DRAWING,
                        human_label=human_label,
                    )
                    if failure is not None:
                        return failure
                    next_errors_for_retry_by_identity[result.task_identity] = None
                    continue

                if result.output is None:
                    msg = f"{human_label} finished without output or error"
                    raise RuntimeError(msg)

                token_failure = self._handle_output_token_ceiling(
                    job_id=job_id,
                    attempt=attempt,
                    usage=result.usage,
                    elapsed_ms=elapsed_ms,
                    component="DrawingAgent",
                    human_label=human_label,
                    max_output_tokens=config.MAX_OUTPUT_TOKENS_DRAWING_STAGE,
                    prompt=result.prompt,
                    response_text=result.response_text,
                    model_id=config.BEDROCK_MODEL_ID_DRAWING,
                )
                if token_failure is not None:
                    return token_failure

                required_ids = (
                    BACKGROUND_REQUIRED_IDS
                    if drawing_input.drawing_type == "background"
                    else DRAWING_REQUIRED_IDS
                )
                animated_ids = (
                    BACKGROUND_ANIMATED_IDS
                    if drawing_input.drawing_type == "background"
                    else DRAWING_ANIMATED_IDS
                )
                validation_result, sanitised_svg = validate_and_sanitise_svg(
                    result.output.svg,
                    required_ids=required_ids,
                    animated_ids=animated_ids,
                )
                validation_errors = None if validation_result.is_valid else validation_result.errors
                self._log_agent_event(
                    level="INFO" if validation_errors is None else "WARN",
                    job_id=job_id,
                    component="DrawingAgent",
                    event="agent_call_complete",
                    message=(
                        f"{human_label} completed and passed deterministic validation."
                        if validation_errors is None
                        else (
                            f"{human_label} completed but the output failed "
                            "deterministic validation."
                        )
                    ),
                    duration_ms=elapsed_ms,
                    model_id=config.BEDROCK_MODEL_ID_DRAWING,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    retry_count=attempt,
                    validation_result="pass" if validation_errors is None else "fail",
                    validation_errors=validation_errors,
                    prompt=result.prompt,
                    response_text=result.response_text,
                )

                if validation_errors is None:
                    if sanitised_svg is None:
                        msg = "Drawing validation passed without a sanitised SVG"
                        raise RuntimeError(msg)
                    completed_svgs_by_identity[result.task_identity] = sanitised_svg
                    continue

                truncation_errors = self._build_drawing_truncation_errors(result.usage)
                retry_errors = (
                    truncation_errors if truncation_errors is not None else validation_errors
                )
                collected_validation_errors.extend(
                    f"{human_label} {error}" for error in retry_errors
                )
                next_errors_for_retry_by_identity[result.task_identity] = retry_errors

            if not next_errors_for_retry_by_identity:
                break

            if attempt == config.MAX_AGENT_RETRY_COUNT:
                self._job_store.mark_failed(
                    job_id=job_id,
                    error_message="; ".join(collected_validation_errors),
                    stage=STAGE_FAILED,
                )
                return {"result": "failed", "reason": "drawing_validation_retries_exhausted"}

            errors_for_retry_by_identity = next_errors_for_retry_by_identity
            self._sleep_with_backoff(attempt)

        for identity, slug in obstacle_slug_by_identity.items():
            obstacle_svgs[slug] = completed_svgs_by_identity[identity]
        for identity, act_indices in background_act_by_identity.items():
            svg = completed_svgs_by_identity[identity]
            for act_index in act_indices:
                background_svgs[act_index] = svg

        for clip in animator_output.clips:
            clip.obstacle_svg_override = obstacle_svgs[clip.obstacle_type]
            clip.background_svg = background_svgs[clip.act_index]
            clip.background_slug = background_slug_by_act_index[clip.act_index]

        return animator_output

    def _allocate_unique_background_slug(
        self,
        *,
        base_slug: str,
        used_slugs: set[str],
    ) -> str:
        """Return a background slug that avoids collisions with prior assignments."""
        if base_slug not in used_slugs:
            used_slugs.add(base_slug)
            return base_slug

        suffix = 1
        while True:
            candidate = f"{base_slug}-{suffix}"
            if candidate not in used_slugs:
                used_slugs.add(candidate)
                return candidate
            suffix += 1

    def _build_drawing_truncation_errors(self, usage: Any) -> list[str] | None:
        """Return truncation retry guidance when Drawing output hit the token ceiling."""
        if usage.output_tokens < config.MAX_OUTPUT_TOKENS_DRAWING_STAGE:
            return None
        return [
            "Previous attempt was truncated at the output token limit.",
            "Output only raw SVG markup — no explanation, no markdown fences.",
            (
                "Simplify the SVG: use fewer shapes, shorter path data, fewer animation "
                "keyframes, and avoid redundant repeated values."
            ),
        ]

    def _describe_drawing_task(self, drawing_input: DrawingInput) -> str:
        """Return a readable label for one Drawing task."""
        if drawing_input.drawing_type == "background":
            obstacle_type = drawing_input.obstacle_type
            if obstacle_type.startswith("bg-act-"):
                return f"Drawing background act {obstacle_type.removeprefix('bg-act-')}"
            return f"Drawing background {obstacle_type}"
        return f"Drawing obstacle '{drawing_input.obstacle_type}'"

    def _build_renderer_input(
        self,
        *,
        job_id: str,
        session_id: str,
        animator_output: AnimatorOutput,
    ) -> RendererInput:
        """Build the typed Renderer input from validated Animator output.

        Args:
            job_id: Generation job identifier.
            session_id: Shared AgentCore session id.
            animator_output: Validated Animator output with resolved obstacle SVGs.

        Returns:
            Fully-typed ``RendererInput``.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "build_renderer_input_start",
            message="Building the Renderer input from validated Animator output.",
            job_id=job_id,
            clip_count=len(animator_output.clips),
        )
        return RendererInput(
            job_id=job_id,
            session_id=session_id,
            clips=animator_output.clips,
        )

    def _run_renderer_attempts(
        self,
        *,
        job_id: str,
        renderer_input: RendererInput,
    ) -> RendererOutput | dict[str, str]:
        """Run the Renderer stage one clip at a time with retries."""
        if self._renderer_agent is None:
            msg = "Renderer agent is required for the render stage"
            raise RuntimeError(msg)

        self._job_store.update_stage_generating(job_id, STAGE_RENDER_SVG)
        completed_outputs: dict[tuple[int, str, int | None], SvgClip] = {}
        errors_for_retry_by_identity: dict[tuple[int, str, int | None], list[str] | None] = {
            self._clip_identity(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
            ): None
            for clip in renderer_input.clips
        }
        for attempt in range(config.MAX_AGENT_RETRY_COUNT + 1):
            pending_identities = sorted(errors_for_retry_by_identity)
            if not pending_identities:
                return self._merge_renderer_outputs(
                    renderer_input=renderer_input,
                    completed_outputs=completed_outputs,
                )

            stage_budget_failure = self._ensure_stage_start_budget(
                job_id=job_id,
                human_label="Renderer",
            )
            if stage_budget_failure is not None:
                return stage_budget_failure

            log_event(
                "DEBUG",
                "PipelineOrchestrator",
                "renderer_attempt_start",
                message="Starting a Renderer generation attempt for the remaining episode clips.",
                job_id=job_id,
                attempt=attempt,
                max_attempt=config.MAX_AGENT_RETRY_COUNT,
                has_validation_errors=any(
                    errors is not None for errors in errors_for_retry_by_identity.values()
                ),
                clip_count=len(pending_identities),
            )

            next_errors_for_retry_by_identity: dict[
                tuple[int, str, int | None], list[str] | None
            ] = {}
            collected_validation_errors: list[str] = []
            clip_inputs = [
                self._build_single_clip_renderer_input(
                    renderer_input=renderer_input,
                    clip=clip,
                )
                for clip in renderer_input.clips
                if self._clip_identity(
                    act_index=clip.act_index,
                    branch=clip.branch,
                    choice_index=clip.choice_index,
                )
                in errors_for_retry_by_identity
            ]
            results = run_renderer_clips_in_parallel(
                base_agent=self._renderer_agent,
                renderer_inputs=clip_inputs,
                validation_errors_by_identity=errors_for_retry_by_identity,
            )

            for result in sorted(
                results,
                key=lambda item: (
                    item.renderer_input.clips[0].act_index,
                    item.renderer_input.clips[0].branch,
                    (
                        -1
                        if item.renderer_input.clips[0].choice_index is None
                        else item.renderer_input.clips[0].choice_index
                    ),
                ),
            ):
                clip = result.renderer_input.clips[0]
                identity = result.clip_identity
                human_label = self._describe_renderer_clip(clip)
                elapsed_ms = result.elapsed_ms

                if result.error is not None:
                    retry_errors = self._build_renderer_retry_errors_for_model_failure(
                        error=result.error,
                        usage=result.usage,
                    )
                    if retry_errors is not None:
                        self._log_agent_event(
                            level="WARN",
                            job_id=job_id,
                            component="RendererAgent",
                            event="renderer_invoke_failed",
                            message=(
                                f"{human_label} model call was truncated and will be retried "
                                "with compact-output guidance."
                            ),
                            duration_ms=elapsed_ms,
                            model_id=config.BEDROCK_MODEL_ID_RENDERER,
                            input_tokens=result.usage.input_tokens,
                            output_tokens=result.usage.output_tokens,
                            retry_count=attempt,
                            validation_result="fail",
                            validation_errors=retry_errors,
                            retryable=attempt < config.MAX_AGENT_RETRY_COUNT,
                            prompt=result.prompt,
                            response_text=result.response_text,
                        )
                        collected_validation_errors.extend(retry_errors)
                        next_errors_for_retry_by_identity[identity] = retry_errors
                        continue

                    failure = self._handle_agent_invoke_failure(
                        job_id=job_id,
                        attempt=attempt,
                        error=result.error,
                        elapsed_ms=elapsed_ms,
                        component="RendererAgent",
                        event="renderer_invoke_failed",
                        stop_reason="renderer_model_call_failed",
                        model_id=config.BEDROCK_MODEL_ID_RENDERER,
                        human_label=human_label,
                    )
                    if failure is not None:
                        return failure
                    next_errors_for_retry_by_identity[identity] = None
                    continue

                if result.output is None:
                    msg = f"{human_label} finished without output or error"
                    raise RuntimeError(msg)

                token_failure = self._handle_output_token_ceiling(
                    job_id=job_id,
                    attempt=attempt,
                    usage=result.usage,
                    elapsed_ms=elapsed_ms,
                    component="RendererAgent",
                    human_label=human_label,
                    max_output_tokens=config.MAX_OUTPUT_TOKENS_RENDERER_STAGE,
                    prompt=result.prompt,
                    response_text=result.response_text,
                    model_id=config.BEDROCK_MODEL_ID_RENDERER,
                )
                if token_failure is not None:
                    return token_failure

                validation_errors, sanitised_output = self._validate_renderer_output(
                    output=result.output,
                    renderer_input=result.renderer_input,
                )
                self._log_agent_event(
                    level="INFO" if validation_errors is None else "WARN",
                    job_id=job_id,
                    component="RendererAgent",
                    event="agent_call_complete",
                    message=(
                        f"{human_label} completed and passed deterministic validation."
                        if validation_errors is None
                        else (
                            f"{human_label} completed but the output failed "
                            "deterministic validation."
                        )
                    ),
                    duration_ms=elapsed_ms,
                    model_id=config.BEDROCK_MODEL_ID_RENDERER,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    retry_count=attempt,
                    validation_result="pass" if validation_errors is None else "fail",
                    validation_errors=validation_errors,
                    prompt=result.prompt,
                    response_text=result.response_text,
                )

                if validation_errors is None:
                    if sanitised_output is None or len(sanitised_output.clips) != 1:
                        msg = "Renderer validation passed without exactly one sanitised clip"
                        raise RuntimeError(msg)
                    completed_outputs[identity] = sanitised_output.clips[0]
                    continue

                collected_validation_errors.extend(validation_errors)
                next_errors_for_retry_by_identity[identity] = validation_errors

            if not next_errors_for_retry_by_identity:
                return self._merge_renderer_outputs(
                    renderer_input=renderer_input,
                    completed_outputs=completed_outputs,
                )

            if attempt == config.MAX_AGENT_RETRY_COUNT:
                self._job_store.mark_failed(
                    job_id=job_id,
                    error_message="; ".join(collected_validation_errors),
                    stage=STAGE_FAILED,
                )
                return {"result": "failed", "reason": "renderer_validation_retries_exhausted"}

            errors_for_retry_by_identity = next_errors_for_retry_by_identity
            self._sleep_with_backoff(attempt)

        return {"result": "failed", "reason": "unexpected_fallthrough"}  # pragma: no cover

    def _build_single_clip_renderer_input(
        self,
        *,
        renderer_input: RendererInput,
        clip: ClipManifest,
    ) -> RendererInput:
        """Build a one-clip Renderer input to keep each model call within budget."""
        return RendererInput(
            job_id=renderer_input.job_id,
            session_id=renderer_input.session_id,
            clips=[clip],
            character_template_id=renderer_input.character_template_id,
        )

    def _build_renderer_retry_errors_for_model_failure(
        self,
        *,
        error: Exception,
        usage: Any,
    ) -> list[str] | None:
        """Return retry guidance for renderer failures caused by truncated output."""
        if "invalid JSON" not in str(error):
            return None
        if usage.output_tokens < config.MAX_OUTPUT_TOKENS_RENDERER_STAGE:
            return None
        return [
            "Previous attempt was truncated at the output token limit.",
            "Return valid JSON only with no markdown fences or commentary.",
            (
                "Simplify the SVG: keep it compact, animate only parts that materially "
                "change, use fewer keyTimes, and avoid redundant repeated values."
            ),
        ]

    def _merge_renderer_outputs(
        self,
        *,
        renderer_input: RendererInput,
        completed_outputs: dict[tuple[int, str, int | None], SvgClip],
    ) -> RendererOutput:
        """Merge completed sanitised clip outputs back into the original input order."""
        ordered_clips: list[SvgClip] = []
        for clip in renderer_input.clips:
            identity = self._clip_identity(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
            )
            output_clip = completed_outputs.get(identity)
            if output_clip is None:
                msg = (
                    "Missing sanitised renderer clip for "
                    f"(act_index={clip.act_index}, branch={clip.branch}, "
                    f"choice_index={clip.choice_index})"
                )
                raise RuntimeError(msg)
            ordered_clips.append(output_clip)
        return RendererOutput(clips=ordered_clips)

    def _describe_renderer_clip(self, clip: ClipManifest) -> str:
        """Return a readable label for one Renderer clip attempt."""
        if clip.choice_index is None:
            return f"Renderer clip act {clip.act_index} {clip.branch}"
        return f"Renderer clip act {clip.act_index} {clip.branch} choice {clip.choice_index}"

    def _validate_renderer_output(
        self,
        *,
        output: RendererOutput,
        renderer_input: RendererInput,
    ) -> tuple[list[str] | None, RendererOutput | None]:
        """Run deterministic validation for Renderer output.

        Args:
            output: Renderer output to validate.
            renderer_input: Original typed Renderer input for identity checks.

        Returns:
            Tuple of ``(errors_or_none, sanitised_output_or_none)``.
        """
        expected_by_identity = {
            self._clip_identity(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
            ): clip
            for clip in renderer_input.clips
        }
        errors: list[str] = []
        seen_identities: set[tuple[int, str, int | None]] = set()
        sanitised_by_identity: dict[tuple[int, str, int | None], SvgClip] = {}

        if len(output.clips) != len(renderer_input.clips):
            errors.append("renderer output clip count must match RendererInput.clips count")

        for clip in output.clips:
            identity = self._clip_identity(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
            )
            if identity not in expected_by_identity:
                errors.append(
                    "renderer output included unexpected clip "
                    f"(act_index={clip.act_index}, branch={clip.branch}, "
                    f"choice_index={clip.choice_index})"
                )
                continue
            if identity in seen_identities:
                errors.append(
                    "renderer output duplicated clip "
                    f"(act_index={clip.act_index}, branch={clip.branch}, "
                    f"choice_index={clip.choice_index})"
                )
                continue
            seen_identities.add(identity)

            expected_clip = expected_by_identity[identity]
            if clip.duration_ms != expected_clip.duration_ms:
                errors.append(
                    "renderer output duration mismatch for "
                    f"(act_index={clip.act_index}, branch={clip.branch}, "
                    f"choice_index={clip.choice_index}): "
                    f"{clip.duration_ms}!={expected_clip.duration_ms}"
                )

            try:
                composed_svg = compose_renderer_scene_svg(
                    scene_svg=clip.svg,
                    clip=expected_clip,
                )
            except (ValueError, ET.ParseError):
                composed_svg = clip.svg

            validation_result, sanitised_svg = validate_and_sanitise_svg(
                composed_svg,
                required_ids=self._renderer_required_ids_for_clip(expected_clip),
                animated_ids=self._renderer_animated_ids_for_clip(expected_clip),
            )
            if not validation_result.is_valid or sanitised_svg is None:
                for error in validation_result.errors:
                    errors.append(
                        "renderer clip "
                        f"(act_index={clip.act_index}, branch={clip.branch}, "
                        f"choice_index={clip.choice_index}) "
                        f"{error}"
                    )
                continue

            motion_result = validate_renderer_motion(svg=sanitised_svg, clip=expected_clip)
            if (
                not motion_result.is_valid
                and any(
                    "must not animate unsupported Linai element id" in error
                    for error in motion_result.errors
                )
            ):
                repaired_svg = repair_renderer_unsupported_animation_targets(sanitised_svg)
                motion_result = validate_renderer_motion(svg=repaired_svg, clip=expected_clip)
                if motion_result.is_valid:
                    sanitised_svg = repaired_svg
            if (
                not motion_result.is_valid
                and any("eye interior motion subtle" in error for error in motion_result.errors)
            ):
                repaired_svg = repair_renderer_eye_motion(sanitised_svg)
                motion_result = validate_renderer_motion(svg=repaired_svg, clip=expected_clip)
                if motion_result.is_valid:
                    sanitised_svg = repaired_svg
            if (
                not motion_result.is_valid
                and any(
                    "must not translate #linai downward past" in error
                    for error in motion_result.errors
                )
            ):
                max_y_px = (
                    config.RENDERER_FAIL_ROOT_TRANSLATE_MAX_Y_PX
                    if expected_clip.branch == "fail"
                    else config.RENDERER_ROOT_TRANSLATE_MAX_Y_PX
                )
                repaired_svg = repair_renderer_root_translate(sanitised_svg, max_y_px=max_y_px)
                motion_result = validate_renderer_motion(svg=repaired_svg, clip=expected_clip)
                if motion_result.is_valid:
                    sanitised_svg = repaired_svg
            if (
                not motion_result.is_valid
                and any(
                    "must keep linai-body scale within" in error
                    for error in motion_result.errors
                )
            ):
                body_scale_max = (
                    config.RENDERER_FAIL_BODY_SCALE_MAX
                    if expected_clip.branch == "fail"
                    else config.RENDERER_BODY_SCALE_MAX
                )
                repaired_svg = repair_renderer_body_scale(
                    sanitised_svg,
                    scale_min=config.RENDERER_BODY_SCALE_MIN,
                    scale_max=body_scale_max,
                )
                motion_result = validate_renderer_motion(svg=repaired_svg, clip=expected_clip)
                if motion_result.is_valid:
                    sanitised_svg = repaired_svg
            if not motion_result.is_valid:
                for error in motion_result.errors:
                    errors.append(
                        "renderer clip "
                        f"(act_index={clip.act_index}, branch={clip.branch}, "
                        f"choice_index={clip.choice_index}) "
                        f"{error}"
                    )
                continue

            sanitised_by_identity[identity] = SvgClip(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
                svg=sanitised_svg,
                duration_ms=expected_clip.duration_ms,
            )

        missing_identities = [
            identity for identity in expected_by_identity if identity not in seen_identities
        ]
        for act_index, branch, choice_index in missing_identities:
            errors.append(
                "renderer output missing clip "
                f"(act_index={act_index}, branch={branch}, choice_index={choice_index})"
            )

        if errors:
            return errors, None

        ordered_clips = [
            sanitised_by_identity[
                self._clip_identity(
                    act_index=clip.act_index,
                    branch=clip.branch,
                    choice_index=clip.choice_index,
                )
            ]
            for clip in renderer_input.clips
        ]
        return None, RendererOutput(clips=ordered_clips)

    def _renderer_required_ids_for_clip(self, clip: ClipManifest) -> set[str]:
        """Return the required SVG ids for one rendered clip."""
        if clip.background_slug is None:
            return RENDERER_REQUIRED_IDS
        return RENDERER_REQUIRED_IDS | BACKGROUND_REQUIRED_IDS

    def _renderer_animated_ids_for_clip(self, clip: ClipManifest) -> set[str]:
        """Return the animated SVG ids required for one rendered clip."""
        if clip.background_slug is None:
            return RENDERER_ANIMATED_IDS
        return RENDERER_ANIMATED_IDS | BACKGROUND_ANIMATED_IDS

    def _clip_identity(
        self,
        *,
        act_index: int,
        branch: str,
        choice_index: int | None,
    ) -> tuple[int, str, int | None]:
        """Return the stable clip identity tuple used across retries and merges."""
        return (act_index, branch, choice_index)
