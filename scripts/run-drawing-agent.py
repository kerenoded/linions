#!/usr/bin/env python3
# ruff: noqa: E402
"""Run the Drawing agent locally for one obstacle slug and save its outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.agents.drawing.agent import DrawingAgent
from pipeline.lambdas.shared.aws_clients import get_bedrock_runtime_client
from pipeline.models import DrawingInput
from pipeline.validators.svg_linter import validate_and_sanitise_svg

OBSTACLE_REQUIRED_IDS = {"obstacle-root", "obstacle-main", "obstacle-animated-part"}
OBSTACLE_ANIMATED_IDS = {"obstacle-animated-part"}
BACKGROUND_REQUIRED_IDS = {"background-root", "background-main", "background-animated-part"}
BACKGROUND_ANIMATED_IDS = {"background-animated-part"}


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the Drawing-agent dev runner.

    Returns:
        Configured ``ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        description="Run the Drawing agent for one obstacle slug and save prompt/SVG outputs."
    )
    parser.add_argument("obstacle_type", help="Obstacle slug to draw, for example: horse")
    parser.add_argument(
        "drawing_prompt",
        help=(
            "Rich drawing prompt describing what to draw. For obstacles, include visual "
            "description, layering, ID assignments, and animation direction. For backgrounds, "
            "include scene description, composition, and animation direction."
        ),
    )
    parser.add_argument(
        "--drawing-type",
        choices=["obstacle", "background"],
        default="obstacle",
        help="Type of SVG to draw: obstacle (default) or background.",
    )
    parser.add_argument(
        "--output-dir",
        default="tmp/drawing-agent",
        help="Directory where prompt and SVG files will be written.",
    )
    parser.add_argument(
        "--job-id",
        default=None,
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
        help="Optional validation error text to append to the retry prompt. Repeatable.",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="Print the final prompt to stdout after writing it to disk.",
    )
    parser.add_argument(
        "--print-svg",
        action="store_true",
        help="Print the sanitised SVG to stdout after writing it to disk.",
    )
    return parser


def build_drawing_input(
    obstacle_type: str,
    *,
    drawing_prompt: str,
    drawing_type: str,
    job_id: str | None,
    session_id: str,
) -> DrawingInput:
    """Build the typed input payload for one local Drawing-agent run.

    Args:
        obstacle_type: Obstacle slug to draw.
        drawing_prompt: Rich drawing prompt describing the SVG to generate.
        drawing_type: Type of SVG to draw — ``"obstacle"`` or ``"background"``.
        job_id: Optional job identifier override.
        session_id: Session identifier to pass through to the agent.

    Returns:
        Typed ``DrawingInput`` payload.
    """
    resolved_job_id = job_id or f"debug-drawing-{obstacle_type}"
    return DrawingInput(
        job_id=resolved_job_id,
        session_id=session_id,
        obstacle_type=obstacle_type,
        drawing_prompt=drawing_prompt,
        drawing_type=drawing_type,
    )


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text to disk, creating parent directories when needed.

    Args:
        path: Target path to write.
        content: Text content to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run() -> int:
    """Execute the Drawing-agent debug flow from CLI arguments.

    Returns:
        Process exit code. ``0`` on success, ``1`` when SVG validation fails.
    """
    args = build_argument_parser().parse_args()
    obstacle_type = str(args.obstacle_type)
    output_dir = Path(args.output_dir)

    drawing_input = build_drawing_input(
        obstacle_type,
        drawing_prompt=str(args.drawing_prompt),
        drawing_type=str(args.drawing_type),
        job_id=args.job_id,
        session_id=str(args.session_id),
    )
    validation_errors = [str(error) for error in args.validation_error]

    agent = DrawingAgent(model_client=get_bedrock_runtime_client())
    prompt = agent.build_prompt(drawing_input, validation_errors=validation_errors or None)
    output = agent.run(drawing_input, validation_errors=validation_errors or None)
    usage = agent.get_last_usage()

    prompt_path = output_dir / f"{obstacle_type}.prompt.txt"
    raw_svg_path = output_dir / f"{obstacle_type}.raw.svg"
    svg_path = output_dir / f"{obstacle_type}.svg"

    write_text(prompt_path, prompt)
    write_text(raw_svg_path, output.svg)

    drawing_type = str(args.drawing_type)
    if drawing_type == "background":
        required_ids = BACKGROUND_REQUIRED_IDS
        animated_ids = BACKGROUND_ANIMATED_IDS
    else:
        required_ids = OBSTACLE_REQUIRED_IDS
        animated_ids = OBSTACLE_ANIMATED_IDS

    result, sanitised_svg = validate_and_sanitise_svg(
        output.svg,
        required_ids=required_ids,
        animated_ids=animated_ids,
    )
    if not result.is_valid or sanitised_svg is None:
        print("Drawing-agent output failed deterministic SVG validation.", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        print(f"Prompt written to: {prompt_path}", file=sys.stderr)
        print(f"Raw SVG written to: {raw_svg_path}", file=sys.stderr)
        return 1

    write_text(svg_path, sanitised_svg)

    print(f"Obstacle: {obstacle_type}")
    print(f"Prompt: {prompt_path}")
    print(f"Raw SVG: {raw_svg_path}")
    print(f"Sanitised SVG: {svg_path}")
    print(f"Input tokens: {usage.input_tokens}")
    print(f"Output tokens: {usage.output_tokens}")
    print(f"To inspect visually, open: {svg_path}")

    if args.print_prompt:
        print("\n--- PROMPT ---")
        print(prompt)
    if args.print_svg:
        print("\n--- SVG ---")
        print(sanitised_svg)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
