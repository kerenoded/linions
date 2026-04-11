#!/usr/bin/env python3
# ruff: noqa: E402
"""Run the Renderer agent locally and save prompt/input/output artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config
from pipeline.agents.drawing.agent import DrawingAgent
from pipeline.agents.drawing.parallel import run_drawing_tasks_in_parallel
from pipeline.agents.renderer.agent import RendererAgent
from pipeline.agents.renderer.parallel import run_renderer_clips_in_parallel
from pipeline.agents.renderer.scene_composer import compose_renderer_scene_svg
from pipeline.lambdas.shared.aws_clients import get_bedrock_runtime_client
from pipeline.media.background_library import (
    find_background_library_slug,
    get_background_svg,
    prompt_to_background_slug,
)
from pipeline.media.obstacle_library import get_obstacle_svg
from pipeline.models import (
    AnimatorOutput,
    ClipManifest,
    DirectorOutput,
    DrawingInput,
    RendererInput,
    RendererOutput,
    SvgClip,
)
from pipeline.validators.renderer_motion_validator import validate_renderer_motion
from pipeline.validators.svg_linter import validate_and_sanitise_svg

DRAWING_REQUIRED_IDS = {"obstacle-root", "obstacle-main", "obstacle-animated-part"}
DRAWING_ANIMATED_IDS = {"obstacle-animated-part"}
BACKGROUND_REQUIRED_IDS = {"background-root", "background-main", "background-animated-part"}
BACKGROUND_ANIMATED_IDS = {"background-animated-part"}
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


def renderer_required_ids_for_clip(clip: ClipManifest) -> set[str]:
    """Return the required SVG ids for one composed renderer clip."""
    required_ids = set(RENDERER_REQUIRED_IDS)
    if clip.background_svg is not None:
        required_ids.update(BACKGROUND_REQUIRED_IDS)
    return required_ids


def renderer_animated_ids_for_clip(clip: ClipManifest) -> set[str]:
    """Return the animated SVG ids that must remain alive in one renderer clip."""
    animated_ids = set(RENDERER_ANIMATED_IDS)
    if clip.background_svg is not None:
        animated_ids.update(BACKGROUND_ANIMATED_IDS)
    return animated_ids


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the Renderer-agent dev runner.

    Returns:
        Configured ``ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        description="Run the Renderer agent and save prompt/input/output artifacts."
    )
    parser.add_argument(
        "animator_output_path",
        help=(
            "Path to an Animator output JSON file. If obstacle_svg_override is missing on any "
            "clip, the runner tries the bundled obstacle library and then locally calls the "
            "Drawing agent for any missing obstacle slugs."
        ),
    )
    parser.add_argument(
        "--director-output",
        default=None,
        help=(
            "Path to a Director output JSON file. When provided, the runner generates "
            "background SVGs for each act using the Director's background_drawing_prompt "
            "and injects them into matching clips before rendering. When omitted, the "
            "runner auto-detects tmp/director-agent/<same filename>.json if it exists."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="tmp/renderer-agent",
        help="Directory where prompt and output artifacts will be written.",
    )
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Optional filename prefix. Defaults to the Animator output filename stem.",
    )
    parser.add_argument(
        "--job-id",
        default="debug-renderer",
        help="Optional job id override for the debug run.",
    )
    parser.add_argument(
        "--session-id",
        default="debug-session",
        help="Optional session id override for the debug run.",
    )
    parser.add_argument(
        "--validation-error",
        action="append",
        default=[],
        help="Optional validation error text to append to a retry-style prompt. Repeatable.",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="Print the final prompt to stdout after writing it to disk.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the sanitised Renderer JSON to stdout after writing it to disk.",
    )
    parser.add_argument(
        "--print-raw",
        action="store_true",
        help="Print the raw model response text to stdout after writing it to disk.",
    )
    return parser


def write_generated_obstacle_artifacts(
    *,
    output_dir: Path,
    obstacle_type: str,
    prompt: str,
    raw_svg: str,
    sanitised_svg: str,
) -> None:
    """Write debug artifacts for one obstacle SVG generated by DrawingAgent.

    Args:
        output_dir: Base renderer debug output directory.
        obstacle_type: Obstacle slug that was drawn.
        prompt: Final prompt text sent to the Drawing agent.
        raw_svg: Raw SVG text returned by the model.
        sanitised_svg: Sanitised SVG that passed deterministic validation.
    """
    generated_dir = output_dir / "generated-obstacles"
    write_text(generated_dir / f"{obstacle_type}.prompt.txt", prompt)
    write_text(generated_dir / f"{obstacle_type}.raw.svg", raw_svg)
    write_text(generated_dir / f"{obstacle_type}.svg", sanitised_svg)


def load_cached_generated_svg(
    *,
    path: Path,
    required_ids: set[str],
    animated_ids: set[str],
) -> str | None:
    """Return a cached generated SVG when it still passes deterministic validation."""
    if not path.exists():
        return None

    result, sanitised_svg = validate_and_sanitise_svg(
        path.read_text(encoding="utf-8"),
        required_ids=required_ids,
        animated_ids=animated_ids,
    )
    if result.is_valid and sanitised_svg is not None:
        return sanitised_svg
    return None


def draw_missing_obstacle_svg(
    *,
    obstacle_type: str,
    job_id: str,
    session_id: str,
    drawing_agent: DrawingAgent,
    output_dir: Path,
) -> str:
    """Generate one missing obstacle SVG locally using DrawingAgent retries.

    Args:
        obstacle_type: Obstacle slug that needs a standalone SVG.
        job_id: Debug job id to pass through to the Drawing agent.
        session_id: Debug session id to pass through to the Drawing agent.
        drawing_agent: Configured Drawing agent instance.
        output_dir: Base renderer debug output directory.

    Returns:
        Sanitised standalone obstacle SVG.

    Raises:
        RuntimeError: If the Drawing agent call itself fails after retries.
        ValueError: If the generated SVG keeps failing deterministic validation.
    """
    cached_svg = load_cached_generated_svg(
        path=output_dir / "generated-obstacles" / f"{obstacle_type}.svg",
        required_ids=DRAWING_REQUIRED_IDS,
        animated_ids=DRAWING_ANIMATED_IDS,
    )
    if cached_svg is not None:
        return cached_svg

    drawing_input = DrawingInput(
        job_id=job_id,
        session_id=session_id,
        obstacle_type=obstacle_type,
        drawing_prompt=(
            f"Draw a detailed, high-quality SVG illustration of a {obstacle_type}. "
            "Use rich layering of shapes for depth. Technical requirements: Output one "
            "complete <svg>...</svg> document with viewBox='0 0 120 150'. Valid XML, "
            "inline only — no external images, scripts, or foreignObject. Assign these IDs: "
            "obstacle-root on the root <svg>, obstacle-main on the <g> containing the full "
            "body, obstacle-animated-part on a naturally self-contained element for idle "
            "animation with <animateTransform type='rotate'> for gentle sway."
        ),
    )
    errors_for_retry: list[str] | None = None
    last_error: Exception | None = None

    for attempt in range(config.MAX_AGENT_RETRY_COUNT + 1):
        try:
            output = drawing_agent.run(drawing_input, validation_errors=errors_for_retry)
        except Exception as error:
            last_error = error
            if attempt == config.MAX_AGENT_RETRY_COUNT:
                msg = (
                    f"DrawingAgent failed for obstacle '{obstacle_type}' after "
                    f"{config.MAX_AGENT_RETRY_COUNT + 1} attempts: {error}"
                )
                raise RuntimeError(msg) from error
            continue

        result, sanitised_svg = validate_and_sanitise_svg(
            output.svg,
            required_ids=DRAWING_REQUIRED_IDS,
            animated_ids=DRAWING_ANIMATED_IDS,
        )
        if result.is_valid and sanitised_svg is not None:
            write_generated_obstacle_artifacts(
                output_dir=output_dir,
                obstacle_type=obstacle_type,
                prompt=drawing_agent.get_last_prompt(),
                raw_svg=output.svg,
                sanitised_svg=sanitised_svg,
            )
            return sanitised_svg

        errors_for_retry = result.errors
        if attempt == config.MAX_AGENT_RETRY_COUNT:
            error_text = "; ".join(result.errors)
            msg = (
                f"DrawingAgent produced invalid SVG for obstacle '{obstacle_type}' after "
                f"{config.MAX_AGENT_RETRY_COUNT + 1} attempts: {error_text}"
            )
            raise ValueError(msg)

    if last_error is not None:  # pragma: no cover - defensive fallthrough
        raise RuntimeError(str(last_error))
    msg = f"Failed to resolve obstacle '{obstacle_type}'"
    raise RuntimeError(msg)  # pragma: no cover


def draw_background_svg(
    *,
    act_index: int,
    background_drawing_prompt: str,
    job_id: str,
    session_id: str,
    drawing_agent: DrawingAgent,
    output_dir: Path,
) -> str:
    """Generate one background SVG locally using DrawingAgent retries.

    Args:
        act_index: Act index for logging and artifact naming.
        background_drawing_prompt: Director-authored drawing prompt for the background.
        job_id: Debug job id to pass through to the Drawing agent.
        session_id: Debug session id to pass through to the Drawing agent.
        drawing_agent: Configured Drawing agent instance.
        output_dir: Base renderer debug output directory.

    Returns:
        Sanitised background SVG string.

    Raises:
        RuntimeError: If the Drawing agent call itself fails after retries.
        ValueError: If the generated SVG keeps failing deterministic validation.
    """
    drawing_input = DrawingInput(
        job_id=job_id,
        session_id=session_id,
        obstacle_type=f"background-act-{act_index}",
        drawing_prompt=background_drawing_prompt,
        drawing_type="background",
    )
    errors_for_retry: list[str] | None = None
    last_error: Exception | None = None

    for attempt in range(config.MAX_AGENT_RETRY_COUNT + 1):
        try:
            output = drawing_agent.run(drawing_input, validation_errors=errors_for_retry)
        except Exception as error:
            last_error = error
            if attempt == config.MAX_AGENT_RETRY_COUNT:
                msg = (
                    f"DrawingAgent failed for background act {act_index} after "
                    f"{config.MAX_AGENT_RETRY_COUNT + 1} attempts: {error}"
                )
                raise RuntimeError(msg) from error
            continue

        result, sanitised_svg = validate_and_sanitise_svg(
            output.svg,
            required_ids=BACKGROUND_REQUIRED_IDS,
            animated_ids=BACKGROUND_ANIMATED_IDS,
        )
        if result.is_valid and sanitised_svg is not None:
            generated_dir = output_dir / "generated-backgrounds"
            write_text(
                generated_dir / f"act-{act_index}.prompt.txt",
                drawing_agent.get_last_prompt(),
            )
            write_text(generated_dir / f"act-{act_index}.raw.svg", output.svg)
            write_text(generated_dir / f"act-{act_index}.svg", sanitised_svg)
            return sanitised_svg

        errors_for_retry = result.errors
        if attempt == config.MAX_AGENT_RETRY_COUNT:
            error_text = "; ".join(result.errors)
            msg = (
                f"DrawingAgent produced invalid background SVG for act {act_index} after "
                f"{config.MAX_AGENT_RETRY_COUNT + 1} attempts: {error_text}"
            )
            raise ValueError(msg)

    if last_error is not None:  # pragma: no cover - defensive fallthrough
        raise RuntimeError(str(last_error))
    msg = f"Failed to resolve background for act {act_index}"
    raise RuntimeError(msg)  # pragma: no cover


def resolve_background_svgs(
    *,
    clips: list[ClipManifest],
    director_output: DirectorOutput,
    job_id: str,
    session_id: str,
    drawing_agent: DrawingAgent,
    output_dir: Path,
) -> list[ClipManifest]:
    """Generate background SVGs per act and inject into matching clips.

    Args:
        clips: Clip manifests with obstacle SVGs already resolved.
        director_output: Director output containing background_drawing_prompt per act.
        job_id: Debug job id.
        session_id: Debug session id.
        drawing_agent: Configured Drawing agent instance.
        output_dir: Base renderer debug output directory.

    Returns:
        Updated clip list with ``background_svg`` populated.
    """
    bg_by_act: dict[int, str] = {}
    pending_background_inputs: list[DrawingInput] = []
    background_act_by_identity: dict[tuple[str, str], int] = {}

    for act in director_output.acts:
        bg_slug = prompt_to_background_slug(act.background_drawing_prompt)
        cached_svg = load_cached_generated_svg(
            path=output_dir / "generated-backgrounds" / f"{bg_slug}.svg",
            required_ids=BACKGROUND_REQUIRED_IDS,
            animated_ids=BACKGROUND_ANIMATED_IDS,
        )
        if cached_svg is not None:
            bg_by_act[act.act_index] = cached_svg
            continue

        library_slug = find_background_library_slug(
            act.background_drawing_prompt,
            act.approach_description,
        )
        if library_slug is not None:
            library_svg = get_background_svg(library_slug)
            if library_svg is not None:
                bg_by_act[act.act_index] = library_svg
                continue

        drawing_input = DrawingInput(
            job_id=job_id,
            session_id=session_id,
            obstacle_type=bg_slug,
            drawing_prompt=act.background_drawing_prompt,
            drawing_type="background",
        )
        pending_background_inputs.append(drawing_input)
        background_act_by_identity[(drawing_input.drawing_type, drawing_input.obstacle_type)] = (
            act.act_index
        )

    if pending_background_inputs:
        completed_svgs = resolve_drawing_tasks_locally(
            drawing_agent=drawing_agent,
            drawing_inputs=pending_background_inputs,
            output_dir=output_dir,
        )
        for identity, act_index in background_act_by_identity.items():
            bg_by_act[act_index] = completed_svgs[identity]

    return [
        clip.model_copy(update={"background_svg": bg_by_act.get(clip.act_index)})
        if clip.background_svg is None and clip.act_index in bg_by_act
        else clip
        for clip in clips
    ]


def describe_drawing_input(drawing_input: DrawingInput) -> str:
    """Return a readable label for one local Drawing task."""
    if drawing_input.drawing_type == "background":
        return f"background '{drawing_input.obstacle_type}'"
    return f"obstacle '{drawing_input.obstacle_type}'"


def resolve_drawing_tasks_locally(
    *,
    drawing_agent: DrawingAgent,
    drawing_inputs: list[DrawingInput],
    output_dir: Path,
) -> dict[tuple[str, str], str]:
    """Run multiple Drawing tasks locally in parallel with retries and validation."""
    completed_svgs: dict[tuple[str, str], str] = {}
    errors_for_retry_by_identity: dict[tuple[str, str], list[str] | None] = {
        (drawing_input.drawing_type, drawing_input.obstacle_type): None
        for drawing_input in drawing_inputs
    }
    drawing_input_by_identity = {
        (drawing_input.drawing_type, drawing_input.obstacle_type): drawing_input
        for drawing_input in drawing_inputs
    }

    for attempt in range(config.MAX_AGENT_RETRY_COUNT + 1):
        pending_identities = sorted(errors_for_retry_by_identity)
        if not pending_identities:
            return completed_svgs

        results = run_drawing_tasks_in_parallel(
            base_agent=drawing_agent,
            drawing_inputs=[drawing_input_by_identity[identity] for identity in pending_identities],
            validation_errors_by_identity=errors_for_retry_by_identity,
            max_workers=config.MAX_PARALLEL_DRAWING_TASKS,
        )
        next_errors_for_retry_by_identity: dict[tuple[str, str], list[str] | None] = {}

        for result in sorted(results, key=lambda item: item.task_identity):
            drawing_input = result.drawing_input
            task_label = describe_drawing_input(drawing_input)
            if result.error is not None:
                if attempt == config.MAX_AGENT_RETRY_COUNT:
                    msg = (
                        f"DrawingAgent failed for {task_label} after "
                        f"{config.MAX_AGENT_RETRY_COUNT + 1} attempts: {result.error}"
                    )
                    raise RuntimeError(msg) from result.error
                next_errors_for_retry_by_identity[result.task_identity] = None
                continue

            if result.output is None:
                msg = f"Drawing task {task_label} finished without output or error"
                raise RuntimeError(msg)

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
            if validation_result.is_valid and sanitised_svg is not None:
                if drawing_input.drawing_type == "background":
                    generated_dir = output_dir / "generated-backgrounds"
                    write_text(
                        generated_dir / f"{drawing_input.obstacle_type}.prompt.txt",
                        result.prompt,
                    )
                    write_text(
                        generated_dir / f"{drawing_input.obstacle_type}.raw.svg",
                        result.output.svg,
                    )
                    write_text(generated_dir / f"{drawing_input.obstacle_type}.svg", sanitised_svg)
                else:
                    write_generated_obstacle_artifacts(
                        output_dir=output_dir,
                        obstacle_type=drawing_input.obstacle_type,
                        prompt=result.prompt,
                        raw_svg=result.output.svg,
                        sanitised_svg=sanitised_svg,
                    )
                completed_svgs[result.task_identity] = sanitised_svg
                continue

            if attempt == config.MAX_AGENT_RETRY_COUNT:
                error_text = "; ".join(validation_result.errors)
                msg = (
                    f"DrawingAgent produced invalid SVG for {task_label} after "
                    f"{config.MAX_AGENT_RETRY_COUNT + 1} attempts: {error_text}"
                )
                raise ValueError(msg)
            next_errors_for_retry_by_identity[result.task_identity] = validation_result.errors

        errors_for_retry_by_identity = next_errors_for_retry_by_identity

    return completed_svgs


def build_renderer_input(
    args: argparse.Namespace,
    *,
    drawing_agent: DrawingAgent,
    output_dir: Path,
) -> tuple[RendererInput, list[str]]:
    """Build the typed Renderer input payload for one local debug run.

    Args:
        args: Parsed CLI arguments.
        drawing_agent: Drawing agent used for missing obstacle slugs.
        output_dir: Base renderer debug output directory.

    Returns:
        Tuple of typed ``RendererInput`` payload and generated obstacle slugs.

    Raises:
        RuntimeError: If a missing obstacle cannot be generated locally.
    """
    animator_output_path = Path(args.animator_output_path)
    if not animator_output_path.exists():
        msg = (
            f"Animator output file not found: {animator_output_path}. "
            "Run scripts/run-animator-agent.py until it writes a validated .json file first."
        )
        raise FileNotFoundError(msg)

    animator_output = AnimatorOutput.model_validate_json(
        animator_output_path.read_text(encoding="utf-8")
    )
    resolved_by_slug: dict[str, str] = {}
    generated_obstacle_types: list[str] = []
    pending_obstacle_inputs: list[DrawingInput] = []
    override_by_slug = {
        clip.obstacle_type: clip.obstacle_svg_override
        for clip in animator_output.clips
        if clip.obstacle_svg_override is not None
    }
    clips = []
    for obstacle_type in sorted({clip.obstacle_type for clip in animator_output.clips}):
        resolved_svg = override_by_slug.get(obstacle_type) or resolved_by_slug.get(obstacle_type)
        if resolved_svg is None:
            resolved_svg = get_obstacle_svg(obstacle_type)
        if resolved_svg is None:
            resolved_svg = load_cached_generated_svg(
                path=output_dir / "generated-obstacles" / f"{obstacle_type}.svg",
                required_ids=DRAWING_REQUIRED_IDS,
                animated_ids=DRAWING_ANIMATED_IDS,
            )
        if resolved_svg is not None:
            resolved_by_slug[obstacle_type] = resolved_svg
            continue
        pending_obstacle_inputs.append(
            DrawingInput(
                job_id=str(args.job_id),
                session_id=str(args.session_id),
                obstacle_type=obstacle_type,
                drawing_prompt=(
                    f"Draw a detailed, high-quality SVG illustration of a {obstacle_type}. "
                    "Use rich layering of shapes for depth. Technical requirements: Output one "
                    "complete <svg>...</svg> document with viewBox='0 0 120 150'. Valid XML, "
                    "inline only — no external images, scripts, or foreignObject. Assign these "
                    "IDs: obstacle-root on the root <svg>, obstacle-main on the <g> containing "
                    "the full body, obstacle-animated-part on a naturally self-contained "
                    "element for idle animation with <animateTransform type='rotate'> for "
                    "gentle sway."
                ),
            )
        )

    if pending_obstacle_inputs:
        completed_svgs = resolve_drawing_tasks_locally(
            drawing_agent=drawing_agent,
            drawing_inputs=pending_obstacle_inputs,
            output_dir=output_dir,
        )
        for drawing_input in pending_obstacle_inputs:
            resolved_by_slug[drawing_input.obstacle_type] = completed_svgs[
                (drawing_input.drawing_type, drawing_input.obstacle_type)
            ]
            generated_obstacle_types.append(drawing_input.obstacle_type)

    for clip in animator_output.clips:
        clips.append(
            clip.model_copy(
                update={
                    "obstacle_svg_override": (
                        clip.obstacle_svg_override or resolved_by_slug[clip.obstacle_type]
                    )
                }
            )
        )

    return (
        RendererInput(
            job_id=str(args.job_id),
            session_id=str(args.session_id),
            clips=clips,
        ),
        sorted(set(generated_obstacle_types)),
    )


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text to disk, creating parent directories when needed.

    Args:
        path: Target path to write.
        content: Text content to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def resolve_director_output_path(
    *,
    animator_output_path: Path,
    director_output_argument: str | None,
) -> Path | None:
    """Return the explicit or auto-discovered Director output path for backgrounds.

    Args:
        animator_output_path: Animator output JSON path passed to the runner.
        director_output_argument: Optional explicit ``--director-output`` value.

    Returns:
        Path to the Director output JSON, or ``None`` when no usable file is available.
    """
    if director_output_argument is not None:
        return Path(director_output_argument)

    if animator_output_path.parent.name != "animator-agent":
        return None

    candidate = animator_output_path.parent.parent / "director-agent" / animator_output_path.name
    if candidate.exists():
        return candidate
    return None


def build_single_clip_renderer_input(
    *,
    renderer_input: RendererInput,
    clip: ClipManifest,
) -> RendererInput:
    """Build a one-clip Renderer input for a budget-safe local debug call."""
    return RendererInput(
        job_id=renderer_input.job_id,
        session_id=renderer_input.session_id,
        clips=[clip],
        character_template_id=renderer_input.character_template_id,
    )


def clip_output_suffix(clip: ClipManifest | SvgClip) -> str:
    """Return a stable filename suffix for one clip's debug artifacts."""
    if clip.choice_index is None:
        return f"act-{clip.act_index}.approach"
    return f"act-{clip.act_index}.{clip.branch}-choice-{clip.choice_index}"


def build_renderer_retry_errors_for_model_failure(
    *,
    error: Exception,
    usage: Any,
) -> list[str] | None:
    """Return retry guidance for renderer failures caused by truncated JSON."""
    if "invalid JSON" not in str(error):
        return None
    if usage.output_tokens < config.MAX_OUTPUT_TOKENS_RENDERER_STAGE:
        return None
    return [
        "Previous attempt was truncated at the output token limit.",
        "Return valid JSON only with no markdown fences or commentary.",
        (
            "Simplify the SVG: keep it compact, animate only parts that materially change, "
            "use fewer keyTimes, and avoid redundant repeated values."
        ),
    ]


def validate_single_renderer_clip_output(
    *,
    renderer_input: RendererInput,
    renderer_output: RendererOutput,
) -> tuple[list[str] | None, SvgClip | None]:
    """Validate and sanitise one clip-specific renderer response."""
    if len(renderer_input.clips) != 1:
        raise ValueError("validate_single_renderer_clip_output requires exactly one input clip")

    expected = renderer_input.clips[0]
    identity = (expected.act_index, expected.branch, expected.choice_index)
    errors: list[str] = []

    if len(renderer_output.clips) != 1:
        return ["renderer output clip count must match RendererInput.clips count"], None

    clip = renderer_output.clips[0]
    if (clip.act_index, clip.branch, clip.choice_index) != identity:
        errors.append(
            "unexpected renderer clip "
            f"(act_index={clip.act_index}, branch={clip.branch}, choice_index={clip.choice_index})"
        )
    if clip.duration_ms != expected.duration_ms:
        errors.append(
            "renderer duration mismatch for "
            f"(act_index={clip.act_index}, branch={clip.branch}, choice_index={clip.choice_index})"
        )

    try:
        composed_svg = compose_renderer_scene_svg(scene_svg=clip.svg, clip=expected)
    except (ValueError, ET.ParseError):
        composed_svg = clip.svg

    result, sanitised_svg = validate_and_sanitise_svg(
        composed_svg,
        required_ids=renderer_required_ids_for_clip(expected),
        animated_ids=renderer_animated_ids_for_clip(expected),
    )
    if not result.is_valid or sanitised_svg is None:
        errors.extend(result.errors)
    else:
        motion_result = validate_renderer_motion(svg=sanitised_svg, clip=expected)
        if not motion_result.is_valid:
            errors.extend(motion_result.errors)

    if errors:
        return errors, None

    return (
        None,
        SvgClip(
            act_index=clip.act_index,
            branch=clip.branch,
            choice_index=clip.choice_index,
            duration_ms=expected.duration_ms,
            svg=sanitised_svg,
        ),
    )


def sanitise_renderer_output(
    *,
    renderer_input: RendererInput,
    renderer_output: RendererOutput,
) -> RendererOutput:
    """Validate and sanitise renderer output locally, mirroring orchestrator rules.

    Args:
        renderer_input: Original Renderer input.
        renderer_output: Raw Renderer output to validate.

    Returns:
        Sanitised ``RendererOutput`` ordered to match the input clip manifests.

    Raises:
        ValueError: If metadata mismatches or SVG linting fails.
    """
    expected_by_identity = {
        (clip.act_index, clip.branch, clip.choice_index): clip for clip in renderer_input.clips
    }
    seen: set[tuple[int, str, int | None]] = set()
    sanitised_by_identity: dict[tuple[int, str, int | None], SvgClip] = {}
    errors: list[str] = []

    if len(renderer_output.clips) != len(renderer_input.clips):
        errors.append("renderer output clip count must match RendererInput.clips count")

    for clip in renderer_output.clips:
        identity = (clip.act_index, clip.branch, clip.choice_index)
        expected = expected_by_identity.get(identity)
        if expected is None:
            errors.append(
                "unexpected renderer clip "
                f"(act_index={clip.act_index}, branch={clip.branch}, "
                f"choice_index={clip.choice_index})"
            )
            continue
        if identity in seen:
            errors.append(
                "duplicate renderer clip "
                f"(act_index={clip.act_index}, branch={clip.branch}, "
                f"choice_index={clip.choice_index})"
            )
            continue
        seen.add(identity)
        if clip.duration_ms != expected.duration_ms:
            errors.append(
                "renderer duration mismatch for "
                f"(act_index={clip.act_index}, branch={clip.branch}, "
                f"choice_index={clip.choice_index})"
            )

        try:
            composed_svg = compose_renderer_scene_svg(scene_svg=clip.svg, clip=expected)
        except (ValueError, ET.ParseError):
            composed_svg = clip.svg

        result, sanitised_svg = validate_and_sanitise_svg(
            composed_svg,
            required_ids=renderer_required_ids_for_clip(expected),
            animated_ids=renderer_animated_ids_for_clip(expected),
        )
        if not result.is_valid or sanitised_svg is None:
            errors.extend(result.errors)
            continue

        motion_result = validate_renderer_motion(svg=sanitised_svg, clip=expected)
        if not motion_result.is_valid:
            errors.extend(motion_result.errors)
            continue

        sanitised_by_identity[identity] = SvgClip(
            act_index=clip.act_index,
            branch=clip.branch,
            choice_index=clip.choice_index,
            duration_ms=expected.duration_ms,
            svg=sanitised_svg,
        )

    missing = [
        identity for identity in expected_by_identity if identity not in sanitised_by_identity
    ]
    for act_index, branch, choice_index in missing:
        errors.append(
            "missing renderer clip "
            f"(act_index={act_index}, branch={branch}, choice_index={choice_index})"
        )

    if errors:
        raise ValueError("; ".join(errors))

    ordered = [
        sanitised_by_identity[(clip.act_index, clip.branch, clip.choice_index)]
        for clip in renderer_input.clips
    ]
    return RendererOutput(clips=ordered)


def run() -> int:
    """Execute the Renderer-agent debug flow from CLI arguments.

    Returns:
        Process exit code. ``0`` on success, ``1`` on validation failure.
    """
    args = build_argument_parser().parse_args()
    output_dir = Path(args.output_dir)
    validation_errors = [str(error) for error in args.validation_error]
    model_client = get_bedrock_runtime_client()
    drawing_agent = DrawingAgent(model_client=model_client)
    renderer_input, generated_obstacle_types = build_renderer_input(
        args,
        drawing_agent=drawing_agent,
        output_dir=output_dir,
    )

    # Resolve background SVGs if a Director output is provided.
    generated_background_acts: list[int] = []
    director_output_path = resolve_director_output_path(
        animator_output_path=Path(args.animator_output_path),
        director_output_argument=args.director_output,
    )
    if director_output_path is not None:
        if not director_output_path.exists():
            print(
                f"Director output file not found: {director_output_path}",
                file=sys.stderr,
            )
            return 1
        if args.director_output is None:
            print(f"Auto-detected Director output: {director_output_path}")
        director_output = DirectorOutput.model_validate_json(
            director_output_path.read_text(encoding="utf-8")
        )
        updated_clips = resolve_background_svgs(
            clips=renderer_input.clips,
            director_output=director_output,
            job_id=str(args.job_id),
            session_id=str(args.session_id),
            drawing_agent=drawing_agent,
            output_dir=output_dir,
        )
        renderer_input = RendererInput(
            job_id=renderer_input.job_id,
            session_id=renderer_input.session_id,
            clips=updated_clips,
            character_template_id=renderer_input.character_template_id,
        )
        generated_background_acts = sorted({act.act_index for act in director_output.acts})

    default_prefix = Path(args.animator_output_path).stem
    output_prefix = str(args.output_prefix) if args.output_prefix is not None else default_prefix

    input_path = output_dir / f"{output_prefix}.input.json"
    prompt_path = output_dir / f"{output_prefix}.prompt.txt"
    raw_response_path = output_dir / f"{output_prefix}.raw.txt"
    output_path = output_dir / f"{output_prefix}.json"

    write_text(input_path, renderer_input.model_dump_json(indent=2))

    agent = RendererAgent(model_client=model_client)
    clip_inputs = [
        build_single_clip_renderer_input(renderer_input=renderer_input, clip=clip)
        for clip in renderer_input.clips
    ]
    clip_order = {
        (clip.act_index, clip.branch, clip.choice_index): index
        for index, clip in enumerate(renderer_input.clips)
    }
    prompt_sections: list[str] = []
    raw_sections: list[str] = []
    completed_clips: dict[tuple[int, str, int | None], SvgClip] = {}
    total_input_tokens = 0
    total_output_tokens = 0
    errors_for_retry_by_identity: dict[tuple[int, str, int | None], list[str] | None] = {
        (clip.act_index, clip.branch, clip.choice_index): (validation_errors or None)
        for clip in renderer_input.clips
    }

    for attempt in range(config.MAX_AGENT_RETRY_COUNT + 1):
        pending_inputs = [
            clip_input
            for clip_input in clip_inputs
            if (
                clip_input.clips[0].act_index,
                clip_input.clips[0].branch,
                clip_input.clips[0].choice_index,
            )
            in errors_for_retry_by_identity
        ]
        if not pending_inputs:
            break

        results = run_renderer_clips_in_parallel(
            base_agent=agent,
            renderer_inputs=pending_inputs,
            validation_errors_by_identity=errors_for_retry_by_identity,
        )
        ordered_results = sorted(results, key=lambda result: clip_order[result.clip_identity])
        next_errors_for_retry_by_identity: dict[tuple[int, str, int | None], list[str] | None] = {}
        collected_errors: list[str] = []

        for result in ordered_results:
            clip = result.renderer_input.clips[0]
            clip_suffix = clip_output_suffix(clip)
            clip_prompt_path = output_dir / f"{output_prefix}.{clip_suffix}.prompt.txt"
            clip_raw_path = output_dir / f"{output_prefix}.{clip_suffix}.raw.txt"
            clip_output_path = output_dir / f"{output_prefix}.{clip_suffix}.json"
            attempt_prompt_path = (
                output_dir / f"{output_prefix}.{clip_suffix}.attempt-{attempt}.prompt.txt"
            )
            attempt_raw_path = (
                output_dir / f"{output_prefix}.{clip_suffix}.attempt-{attempt}.raw.txt"
            )
            attempt_output_path = (
                output_dir / f"{output_prefix}.{clip_suffix}.attempt-{attempt}.json"
            )

            write_text(clip_prompt_path, result.prompt)
            write_text(attempt_prompt_path, result.prompt)
            prompt_sections.append(
                f"===== ATTEMPT {attempt} {clip_suffix.upper()} PROMPT =====\n{result.prompt}"
            )

            total_input_tokens += result.usage.input_tokens
            total_output_tokens += result.usage.output_tokens

            if result.response_text:
                write_text(clip_raw_path, result.response_text)
                write_text(attempt_raw_path, result.response_text)
                raw_sections.append(
                    f"===== ATTEMPT {attempt} {clip_suffix.upper()} RAW RESPONSE =====\n"
                    f"{result.response_text}"
                )

            if result.error is not None:
                retry_errors = build_renderer_retry_errors_for_model_failure(
                    error=result.error,
                    usage=result.usage,
                )
                if retry_errors is not None:
                    collected_errors.extend(retry_errors)
                    next_errors_for_retry_by_identity[result.clip_identity] = retry_errors
                    continue
                if attempt == config.MAX_AGENT_RETRY_COUNT:
                    write_text(prompt_path, "\n\n".join(prompt_sections))
                    if raw_sections:
                        write_text(raw_response_path, "\n\n".join(raw_sections))
                    print(
                        f"Renderer-agent run failed for {clip_suffix}: {result.error}",
                        file=sys.stderr,
                    )
                    print(f"Input written to: {input_path}", file=sys.stderr)
                    print(f"Prompt written to: {prompt_path}", file=sys.stderr)
                    print(f"Per-clip prompt written to: {clip_prompt_path}", file=sys.stderr)
                    if raw_sections:
                        print(f"Raw response written to: {raw_response_path}", file=sys.stderr)
                    if result.response_text:
                        print(f"Per-clip raw response written to: {clip_raw_path}", file=sys.stderr)
                    return 1
                next_errors_for_retry_by_identity[result.clip_identity] = None
                collected_errors.append(str(result.error))
                continue

            if result.output is None:
                msg = f"Renderer clip {clip_suffix} finished without output or error"
                raise RuntimeError(msg)

            write_text(attempt_output_path, result.output.model_dump_json(indent=2))
            clip_validation_errors, sanitised_clip = validate_single_renderer_clip_output(
                renderer_input=result.renderer_input,
                renderer_output=result.output,
            )
            if clip_validation_errors is None and sanitised_clip is not None:
                completed_clips[result.clip_identity] = sanitised_clip
                write_text(
                    clip_output_path,
                    RendererOutput(clips=[sanitised_clip]).model_dump_json(indent=2),
                )
                continue

            if clip_validation_errors is None:
                msg = f"Renderer clip {clip_suffix} validation returned no errors and no output"
                raise RuntimeError(msg)
            collected_errors.extend(clip_validation_errors)
            next_errors_for_retry_by_identity[result.clip_identity] = clip_validation_errors

        write_text(prompt_path, "\n\n".join(prompt_sections))
        if raw_sections:
            write_text(raw_response_path, "\n\n".join(raw_sections))

        if not next_errors_for_retry_by_identity:
            break
        if attempt == config.MAX_AGENT_RETRY_COUNT:
            print("Renderer-agent output failed after retries.", file=sys.stderr)
            for error in collected_errors:
                print(f"- {error}", file=sys.stderr)
            print(f"Input written to: {input_path}", file=sys.stderr)
            print(f"Prompt written to: {prompt_path}", file=sys.stderr)
            if raw_sections:
                print(f"Raw response written to: {raw_response_path}", file=sys.stderr)
            return 1

        errors_for_retry_by_identity = next_errors_for_retry_by_identity

    combined_prompt = "\n\n".join(prompt_sections)
    combined_raw_response = "\n\n".join(raw_sections)
    write_text(prompt_path, combined_prompt)
    if raw_sections:
        write_text(raw_response_path, combined_raw_response)

    missing_identities = [
        (clip.act_index, clip.branch, clip.choice_index)
        for clip in renderer_input.clips
        if (clip.act_index, clip.branch, clip.choice_index) not in completed_clips
    ]
    if missing_identities:
        print(
            f"Renderer-agent ended without completed clips for: {missing_identities}",
            file=sys.stderr,
        )
        print(f"Input written to: {input_path}", file=sys.stderr)
        print(f"Prompt written to: {prompt_path}", file=sys.stderr)
        if raw_sections:
            print(f"Raw response written to: {raw_response_path}", file=sys.stderr)
        return 1

    sanitised_output = RendererOutput(
        clips=[
            completed_clips[(clip.act_index, clip.branch, clip.choice_index)]
            for clip in renderer_input.clips
        ]
    )

    write_text(output_path, sanitised_output.model_dump_json(indent=2))

    for clip in sanitised_output.clips:
        clip_path = output_dir / f"{output_prefix}.{clip_output_suffix(clip)}.svg"
        write_text(clip_path, clip.svg)

    print(f"Input: {input_path}")
    print(f"Prompt: {prompt_path}")
    print(f"Raw response: {raw_response_path}")
    print(f"Sanitised output JSON: {output_path}")
    if generated_obstacle_types:
        print("Generated obstacles:", ", ".join(generated_obstacle_types))
    if generated_background_acts:
        act_list = ", ".join(str(a) for a in generated_background_acts)
        print(f"Resolved backgrounds for acts: {act_list}")
    print(f"Input tokens: {total_input_tokens}")
    print(f"Output tokens: {total_output_tokens}")

    if args.print_prompt:
        print("\n--- PROMPT ---")
        print(combined_prompt)
    if args.print_raw:
        print("\n--- RAW RESPONSE ---")
        print(combined_raw_response)
    if args.print_json:
        print("\n--- SANITISED JSON ---")
        print(sanitised_output.model_dump_json(indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
