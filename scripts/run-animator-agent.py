#!/usr/bin/env python3
# ruff: noqa: E402
"""Run the Animator agent locally and save its exact prompt and JSON outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config
from pipeline.agents.animator.agent import AnimatorAgent
from pipeline.agents.animator.parallel import run_animator_acts_in_parallel
from pipeline.lambdas.shared.aws_clients import get_bedrock_runtime_client
from pipeline.models import AnimatorInput, AnimatorOutput, DirectorOutput
from pipeline.validators.frame_validator import validate_frames


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the Animator-agent dev runner.

    Returns:
        Configured ``ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        description="Run the Animator agent and save prompt/input/output artifacts."
    )
    parser.add_argument(
        "director_output_path",
        help="Path to a Director output JSON file whose acts will feed the Animator agent.",
    )
    parser.add_argument(
        "--output-dir",
        default="tmp/animator-agent",
        help="Directory where prompt and JSON artifacts will be written.",
    )
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Optional filename prefix. Defaults to the Director output filename stem.",
    )
    parser.add_argument(
        "--job-id",
        default="debug-animator",
        help="Optional job id override for the debug run.",
    )
    parser.add_argument(
        "--session-id",
        default="debug-session",
        help="Optional session id override for the debug run.",
    )
    parser.add_argument(
        "--walk-duration-seconds",
        type=int,
        default=config.WALK_DURATION_SECONDS,
        help="Walk duration seconds to include in AnimatorInput.",
    )
    parser.add_argument(
        "--canvas-width",
        type=int,
        default=config.CANVAS_WIDTH,
        help="Canvas width to include in AnimatorInput.",
    )
    parser.add_argument(
        "--canvas-height",
        type=int,
        default=config.CANVAS_HEIGHT,
        help="Canvas height to include in AnimatorInput.",
    )
    parser.add_argument(
        "--ground-line-y",
        type=int,
        default=config.GROUND_LINE_Y,
        help="Ground line Y coordinate to include in AnimatorInput.",
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
        help="Print the validated Animator JSON to stdout after writing it to disk.",
    )
    parser.add_argument(
        "--print-raw",
        action="store_true",
        help="Print the raw model response text to stdout after writing it to disk.",
    )
    return parser


def build_animator_input(args: argparse.Namespace) -> AnimatorInput:
    """Build the typed input payload for one local Animator-agent run.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Typed ``AnimatorInput`` payload.
    """
    director_output_path = Path(args.director_output_path)
    if not director_output_path.exists():
        msg = (
            f"Director output file not found: {director_output_path}. "
            "Run scripts/run-director-agent.py until it writes a validated .json file first."
        )
        raise FileNotFoundError(msg)
    director_output = DirectorOutput.model_validate_json(
        director_output_path.read_text(encoding="utf-8")
    )
    return AnimatorInput(
        job_id=str(args.job_id),
        session_id=str(args.session_id),
        acts=director_output.acts,
        walk_duration_seconds=int(args.walk_duration_seconds),
        canvas_width=int(args.canvas_width),
        canvas_height=int(args.canvas_height),
        ground_line_y=int(args.ground_line_y),
        handoff_character_x=int(config.HANDOFF_CHARACTER_X),
        requires_handoff_in=False,
        requires_handoff_out=False,
    )


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text to disk, creating parent directories when needed.

    Args:
        path: Target path to write.
        content: Text content to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def merge_act_outputs(
    *,
    animator_input: AnimatorInput,
    act_outputs: dict[int, AnimatorOutput],
) -> AnimatorOutput:
    """Merge one validated act-specific AnimatorOutput into one episode manifest."""
    clips = []
    for act in animator_input.acts:
        output = act_outputs.get(act.act_index)
        if output is None:
            msg = f"Missing Animator output for act {act.act_index}"
            raise RuntimeError(msg)
        clips.extend(output.clips)
    return AnimatorOutput(clips=clips)


def run_animator_debug_session(
    *,
    animator_input: AnimatorInput,
    output_dir: Path,
    output_prefix: str,
    validation_errors: list[str],
    agent: AnimatorAgent,
) -> int:
    """Run the local Animator debug flow with per-act retries.

    Args:
        animator_input: Full typed Animator input.
        output_dir: Base directory for all debug artifacts.
        output_prefix: Stable file prefix for this debug run.
        validation_errors: Optional initial retry-style errors from the CLI.
        agent: Configured Animator agent or compatible fake for tests.

    Returns:
        Process-style exit code. ``0`` on success, ``1`` on failure.
    """
    input_path = output_dir / f"{output_prefix}.input.json"
    prompt_path = output_dir / f"{output_prefix}.prompt.txt"
    raw_response_path = output_dir / f"{output_prefix}.raw.txt"
    output_path = output_dir / f"{output_prefix}.json"

    write_text(input_path, animator_input.model_dump_json(indent=2))

    first_act_index = animator_input.acts[0].act_index if animator_input.acts else 0
    act_inputs = [
        AnimatorInput(
            job_id=animator_input.job_id,
            session_id=animator_input.session_id,
            acts=[act],
            walk_duration_seconds=animator_input.walk_duration_seconds,
            canvas_width=animator_input.canvas_width,
            canvas_height=animator_input.canvas_height,
            ground_line_y=animator_input.ground_line_y,
            handoff_character_x=animator_input.handoff_character_x,
            requires_handoff_in=act.act_index != first_act_index,
            requires_handoff_out=False,
        )
        for act in animator_input.acts
    ]
    act_input_by_index = {act_input.acts[0].act_index: act_input for act_input in act_inputs}
    errors_for_retry_by_act = {
        act_input.acts[0].act_index: (validation_errors or None) for act_input in act_inputs
    }
    completed_outputs: dict[int, AnimatorOutput] = {}
    combined_prompt_sections: list[str] = []
    combined_raw_sections: list[str] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for attempt in range(config.MAX_AGENT_RETRY_COUNT + 1):
        pending_act_indices = sorted(errors_for_retry_by_act)
        if not pending_act_indices:
            break

        act_results = run_animator_acts_in_parallel(
            base_agent=agent,
            animator_inputs=[act_input_by_index[act_index] for act_index in pending_act_indices],
            validation_errors_by_act=errors_for_retry_by_act,
        )
        ordered_results = sorted(act_results, key=lambda result: result.act_index)
        next_errors_for_retry_by_act: dict[int, list[str] | None] = {}
        collected_errors: list[str] = []

        for result in ordered_results:
            act_prompt_path = output_dir / f"{output_prefix}.act-{result.act_index}.prompt.txt"
            act_raw_path = output_dir / f"{output_prefix}.act-{result.act_index}.raw.txt"
            act_output_path = output_dir / f"{output_prefix}.act-{result.act_index}.json"
            attempt_prompt_path = (
                output_dir / f"{output_prefix}.act-{result.act_index}.attempt-{attempt}.prompt.txt"
            )
            attempt_raw_path = (
                output_dir / f"{output_prefix}.act-{result.act_index}.attempt-{attempt}.raw.txt"
            )
            attempt_output_path = (
                output_dir / f"{output_prefix}.act-{result.act_index}.attempt-{attempt}.json"
            )

            write_text(act_prompt_path, result.prompt)
            write_text(attempt_prompt_path, result.prompt)
            combined_prompt_sections.append(
                f"===== ATTEMPT {attempt} ACT {result.act_index} PROMPT =====\n{result.prompt}"
            )

            total_input_tokens += result.usage.input_tokens
            total_output_tokens += result.usage.output_tokens

            if result.response_text:
                write_text(act_raw_path, result.response_text)
                write_text(attempt_raw_path, result.response_text)
                combined_raw_sections.append(
                    f"===== ATTEMPT {attempt} ACT {result.act_index} RAW RESPONSE =====\n"
                    f"{result.response_text}"
                )

            if result.error is not None:
                collected_errors.append(str(result.error))
                if attempt == config.MAX_AGENT_RETRY_COUNT:
                    write_text(prompt_path, "\n\n".join(combined_prompt_sections))
                    if combined_raw_sections:
                        write_text(raw_response_path, "\n\n".join(combined_raw_sections))
                    print(
                        f"Animator-agent run failed for act {result.act_index}: {result.error}",
                        file=sys.stderr,
                    )
                    print(f"Input written to: {input_path}", file=sys.stderr)
                    print(f"Prompt written to: {prompt_path}", file=sys.stderr)
                    if combined_raw_sections:
                        print(f"Raw response written to: {raw_response_path}", file=sys.stderr)
                    print(f"Per-act prompt written to: {act_prompt_path}", file=sys.stderr)
                    if result.response_text:
                        print(f"Per-act raw response written to: {act_raw_path}", file=sys.stderr)
                    return 1
                next_errors_for_retry_by_act[result.act_index] = None
                continue

            if result.output is None:
                msg = f"Animator act {result.act_index} finished without output or error"
                raise RuntimeError(msg)

            write_text(attempt_output_path, result.output.model_dump_json(indent=2))
            validation_result = validate_frames(
                result.output,
                animator_input,
                act_indices_to_validate={result.act_index},
            )
            if validation_result.is_valid:
                completed_outputs[result.act_index] = result.output
                write_text(act_output_path, result.output.model_dump_json(indent=2))
                continue

            collected_errors.extend(validation_result.errors)
            next_errors_for_retry_by_act[result.act_index] = validation_result.errors

        write_text(prompt_path, "\n\n".join(combined_prompt_sections))
        if combined_raw_sections:
            write_text(raw_response_path, "\n\n".join(combined_raw_sections))

        if not next_errors_for_retry_by_act:
            break

        if attempt == config.MAX_AGENT_RETRY_COUNT:
            print("Animator-agent output failed after retries.", file=sys.stderr)
            for error in collected_errors:
                print(f"- {error}", file=sys.stderr)
            print(f"Input written to: {input_path}", file=sys.stderr)
            print(f"Prompt written to: {prompt_path}", file=sys.stderr)
            if combined_raw_sections:
                print(f"Raw response written to: {raw_response_path}", file=sys.stderr)
            return 1

        errors_for_retry_by_act = next_errors_for_retry_by_act

    output = merge_act_outputs(animator_input=animator_input, act_outputs=completed_outputs)
    merged_result = validate_frames(output, animator_input)
    if not merged_result.is_valid:
        print("Animator-agent output failed deterministic frame validation.", file=sys.stderr)
        for error in merged_result.errors:
            print(f"- {error}", file=sys.stderr)
        print(f"Input written to: {input_path}", file=sys.stderr)
        print(f"Prompt written to: {prompt_path}", file=sys.stderr)
        if combined_raw_sections:
            print(f"Raw response written to: {raw_response_path}", file=sys.stderr)
        return 1

    write_text(output_path, output.model_dump_json(indent=2))
    print(f"Job id: {animator_input.job_id}")
    print(f"Input: {input_path}")
    print(f"Prompt: {prompt_path}")
    if combined_raw_sections:
        print(f"Raw response: {raw_response_path}")
    print(f"Validated output: {output_path}")
    print("Animator runs: one Bedrock call per act, launched in parallel")
    print(f"Input tokens: {total_input_tokens}")
    print(f"Output tokens: {total_output_tokens}")
    return 0


def run() -> int:
    """Execute the Animator-agent debug flow from CLI arguments.

    Returns:
        Process exit code. ``0`` on success, ``1`` on model or validation failure.
    """
    args = build_argument_parser().parse_args()
    output_dir = Path(args.output_dir)
    validation_errors = [str(error) for error in args.validation_error]
    try:
        animator_input = build_animator_input(args)
    except (FileNotFoundError, ValidationError, ValueError) as error:
        print(f"Animator-agent input error: {error}", file=sys.stderr)
        return 1
    default_prefix = Path(args.director_output_path).stem
    output_prefix = str(args.output_prefix) if args.output_prefix is not None else default_prefix

    agent = AnimatorAgent(model_client=get_bedrock_runtime_client())
    exit_code = run_animator_debug_session(
        animator_input=animator_input,
        output_dir=output_dir,
        output_prefix=output_prefix,
        validation_errors=validation_errors,
        agent=agent,
    )

    if exit_code != 0:
        return exit_code

    prompt_path = output_dir / f"{output_prefix}.prompt.txt"
    raw_response_path = output_dir / f"{output_prefix}.raw.txt"
    output_path = output_dir / f"{output_prefix}.json"
    combined_prompt = prompt_path.read_text(encoding="utf-8")
    combined_raw_response = (
        raw_response_path.read_text(encoding="utf-8") if raw_response_path.exists() else ""
    )
    output = AnimatorOutput.model_validate_json(output_path.read_text(encoding="utf-8"))

    if args.print_prompt:
        print("\n--- PROMPT ---")
        print(combined_prompt)
    if args.print_raw and combined_raw_response:
        print("\n--- RAW RESPONSE ---")
        print(combined_raw_response)
    if args.print_json:
        print("\n--- JSON ---")
        print(output.model_dump_json(indent=2))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
