#!/usr/bin/env python3
# ruff: noqa: E402
"""Run the Director agent locally and save its exact prompt and JSON outputs."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config
from pipeline.agents.director.agent import DirectorAgent
from pipeline.lambdas.orchestrator.knowledge_base import BedrockKnowledgeBaseService
from pipeline.lambdas.shared.aws_clients import (
    get_bedrock_agent_runtime_client,
    get_bedrock_runtime_client,
)
from pipeline.media.obstacle_library import list_library_names
from pipeline.models import DirectorInput
from pipeline.validators.script_validator import validate_script


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the Director-agent dev runner.

    Returns:
        Configured ``ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        description="Run the Director agent and save prompt/input/output artifacts."
    )
    parser.add_argument(
        "prompt",
        help='Story prompt to send to the Director agent, for example: "Linai meets a robot"',
    )
    parser.add_argument(
        "--output-dir",
        default="tmp/director-agent",
        help="Directory where prompt and JSON artifacts will be written.",
    )
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Optional filename prefix. Defaults to the resolved job id.",
    )
    parser.add_argument(
        "--username",
        default="debug-user",
        help="Username to include in the typed DirectorInput payload.",
    )
    parser.add_argument(
        "--job-id",
        default="debug-director",
        help="Optional job id override for the debug run.",
    )
    parser.add_argument(
        "--session-id",
        default="debug-session",
        help="Optional session id override for the debug run.",
    )
    parser.add_argument(
        "--rag-context",
        default="",
        help="Literal RAG context text to inject. Defaults to an empty string.",
    )
    parser.add_argument(
        "--rag-context-file",
        default=None,
        help="Path to a UTF-8 text/markdown file whose contents become rag_context.",
    )
    parser.add_argument(
        "--knowledge-base-id",
        default=None,
        help=(
            "Bedrock Knowledge Base id to query for real RAG context. If omitted, the script "
            "falls back to BEDROCK_KNOWLEDGE_BASE_ID and then CloudFormation stack output "
            "discovery when no manual RAG context is supplied."
        ),
    )
    parser.add_argument(
        "--stack-name",
        default="LinionsStack",
        help="CloudFormation stack name used for automatic KnowledgeBaseId discovery.",
    )
    parser.add_argument(
        "--aws-profile",
        default=None,
        help="Optional AWS profile name used for CloudFormation KnowledgeBaseId discovery.",
    )
    parser.add_argument(
        "--aws-region",
        default=None,
        help="Optional AWS region used for CloudFormation KnowledgeBaseId discovery.",
    )
    parser.add_argument(
        "--preferred-obstacle",
        action="append",
        default=[],
        help=(
            "Optional preferred prepared obstacle slug. Repeat to override the default "
            "bundled library list."
        ),
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
        "--print-rag-context",
        action="store_true",
        help="Print the resolved rag_context to stdout after writing it to disk.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the validated Director JSON to stdout after writing it to disk.",
    )
    parser.add_argument(
        "--print-raw",
        action="store_true",
        help="Print the raw model response text to stdout after writing it to disk.",
    )
    return parser


def discover_knowledge_base_id(
    *,
    stack_name: str,
    aws_profile: str | None,
    aws_region: str | None,
) -> str | None:
    """Discover the deployed Bedrock Knowledge Base id from CloudFormation outputs.

    Args:
        stack_name: CloudFormation stack name to inspect.
        aws_profile: Optional AWS profile for the boto3 session.
        aws_region: Optional AWS region for the boto3 session.

    Returns:
        The discovered Knowledge Base id string, or ``None`` when unavailable.
    """
    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    client = session.client("cloudformation")
    response = client.describe_stacks(StackName=stack_name)
    outputs = response.get("Stacks", [{}])[0].get("Outputs", [])
    for output in outputs:
        if output.get("OutputKey") == "KnowledgeBaseId" and output.get("OutputValue"):
            return str(output["OutputValue"])
    return None


def resolve_rag_context(
    *,
    prompt: str,
    rag_context: str,
    rag_context_file: str | None,
    knowledge_base_id: str | None,
    stack_name: str,
    aws_profile: str | None,
    aws_region: str | None,
) -> str:
    """Resolve the exact rag_context text for a local Director-agent run.

    Args:
        prompt: User prompt that may be used for Bedrock Knowledge Base retrieval.
        rag_context: Literal RAG context text supplied on the CLI.
        rag_context_file: Optional file path containing RAG context text.
        knowledge_base_id: Optional Bedrock Knowledge Base id for live retrieval.
        stack_name: CloudFormation stack name for Knowledge Base id discovery.
        aws_profile: Optional AWS profile for stack lookup.
        aws_region: Optional AWS region for stack lookup.

    Returns:
        Final RAG context string.

    Raises:
        ValueError: If conflicting RAG context sources are supplied together.
    """
    kb_id = knowledge_base_id or os.getenv("BEDROCK_KNOWLEDGE_BASE_ID")
    manual_sources = int(bool(rag_context)) + int(rag_context_file is not None)
    if manual_sources > 1:
        msg = "Use only one of --rag-context or --rag-context-file"
        raise ValueError(msg)
    if manual_sources == 1 and knowledge_base_id is not None:
        msg = "Do not combine manual RAG context with --knowledge-base-id"
        raise ValueError(msg)
    if rag_context:
        return rag_context
    if rag_context_file is not None:
        path = Path(rag_context_file)
        if not path.exists():
            msg = (
                f"RAG context file not found: {path}. "
                'Create it first, or use --rag-context "..." instead.'
            )
            raise FileNotFoundError(msg)
        return path.read_text(encoding="utf-8")
    if kb_id is None:
        kb_id = discover_knowledge_base_id(
            stack_name=stack_name,
            aws_profile=aws_profile,
            aws_region=aws_region,
        )
    if kb_id is None:
        msg = (
            "No RAG context source provided. Use --rag-context, --rag-context-file, "
            "--knowledge-base-id, export BEDROCK_KNOWLEDGE_BASE_ID, or make sure the "
            f"CloudFormation stack '{stack_name}' exposes a KnowledgeBaseId output."
        )
        raise ValueError(msg)
    kb_service = BedrockKnowledgeBaseService(
        client=get_bedrock_agent_runtime_client(),
        knowledge_base_id=kb_id,
    )
    return kb_service.build_rag_context(prompt)


def build_director_input(args: argparse.Namespace) -> DirectorInput:
    """Build the typed input payload for one local Director-agent run.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Typed ``DirectorInput`` payload.
    """
    preferred_obstacles = [str(name) for name in args.preferred_obstacle] or list_library_names()
    rag_context = resolve_rag_context(
        prompt=str(args.prompt),
        rag_context=str(args.rag_context),
        rag_context_file=str(args.rag_context_file) if args.rag_context_file is not None else None,
        knowledge_base_id=(
            str(args.knowledge_base_id) if args.knowledge_base_id is not None else None
        ),
        stack_name=str(args.stack_name),
        aws_profile=str(args.aws_profile) if args.aws_profile is not None else None,
        aws_region=str(args.aws_region) if args.aws_region is not None else None,
    )
    return DirectorInput(
        prompt=str(args.prompt),
        username=str(args.username),
        job_id=str(args.job_id),
        session_id=str(args.session_id),
        rag_context=rag_context,
        preferred_obstacle_library_names=preferred_obstacles,
    )


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text to disk, creating parent directories when needed.

    Args:
        path: Target path to write.
        content: Text content to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def combine_attempt_sections(
    *,
    label: str,
    sections: list[tuple[int, str]],
) -> str:
    """Combine one or more per-attempt text artifacts into one readable blob.

    Args:
        label: Human-readable section label such as ``"PROMPT"`` or ``"RAW RESPONSE"``.
        sections: Ordered ``(attempt_index, content)`` tuples.

    Returns:
        Combined text. A single section is returned verbatim to preserve
        backwards-compatible artifact readability.
    """
    if not sections:
        return ""
    if len(sections) == 1:
        return sections[0][1]
    return "\n\n".join(
        f"===== ATTEMPT {attempt} {label} =====\n{content}" for attempt, content in sections
    )


def run_director_debug_session(
    *,
    director_input: DirectorInput,
    output_dir: Path,
    output_prefix: str,
    validation_errors: list[str],
    agent: DirectorAgent,
    print_prompt: bool = False,
    print_rag_context: bool = False,
    print_json: bool = False,
    print_raw: bool = False,
) -> int:
    """Run the local Director debug flow with deterministic-validation retries.

    Args:
        director_input: Fully constructed Director input payload.
        output_dir: Base output directory for prompt/raw/json artifacts.
        output_prefix: Filename prefix used for all written artifacts.
        validation_errors: Optional retry-style errors for the first attempt.
        agent: Configured Director agent instance.
        print_prompt: Whether to echo the combined prompt artifact to stdout.
        print_rag_context: Whether to echo the resolved RAG context to stdout.
        print_json: Whether to echo the validated final JSON to stdout.
        print_raw: Whether to echo the combined raw-response artifact to stdout.

    Returns:
        Process-style exit code. ``0`` on success, ``1`` on failure.
    """
    input_path = output_dir / f"{output_prefix}.input.json"
    rag_context_path = output_dir / f"{output_prefix}.rag-context.txt"
    prompt_path = output_dir / f"{output_prefix}.prompt.txt"
    raw_response_path = output_dir / f"{output_prefix}.raw.txt"
    output_path = output_dir / f"{output_prefix}.json"

    write_text(input_path, director_input.model_dump_json(indent=2))
    write_text(rag_context_path, director_input.rag_context)

    errors_for_retry = validation_errors or None
    prompt_sections: list[tuple[int, str]] = []
    raw_sections: list[tuple[int, str]] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for attempt in range(config.MAX_AGENT_RETRY_COUNT + 1):
        attempt_prompt_path = output_dir / f"{output_prefix}.attempt-{attempt}.prompt.txt"
        attempt_raw_path = output_dir / f"{output_prefix}.attempt-{attempt}.raw.txt"
        attempt_output_path = output_dir / f"{output_prefix}.attempt-{attempt}.json"

        try:
            output = agent.run(director_input, validation_errors=errors_for_retry)
        except Exception as error:
            prompt_text = agent.get_last_prompt()
            raw_response_text = agent.get_last_response_text()
            if prompt_text:
                write_text(attempt_prompt_path, prompt_text)
                prompt_sections.append((attempt, prompt_text))
                write_text(
                    prompt_path,
                    combine_attempt_sections(label="PROMPT", sections=prompt_sections),
                )
            if raw_response_text:
                write_text(attempt_raw_path, raw_response_text)
                raw_sections.append((attempt, raw_response_text))
                write_text(
                    raw_response_path,
                    combine_attempt_sections(label="RAW RESPONSE", sections=raw_sections),
                )
            if attempt == config.MAX_AGENT_RETRY_COUNT:
                print(
                    "Director-agent run failed after "
                    f"{config.MAX_AGENT_RETRY_COUNT + 1} attempts: {error}",
                    file=sys.stderr,
                )
                print(f"Input written to: {input_path}", file=sys.stderr)
                print(f"RAG context written to: {rag_context_path}", file=sys.stderr)
                if prompt_text:
                    print(f"Prompt written to: {prompt_path}", file=sys.stderr)
                    print(f"Per-attempt prompt written to: {attempt_prompt_path}", file=sys.stderr)
                if raw_response_text:
                    print(f"Raw response written to: {raw_response_path}", file=sys.stderr)
                    print(
                        f"Per-attempt raw response written to: {attempt_raw_path}",
                        file=sys.stderr,
                    )
                return 1
            continue

        prompt_text = agent.get_last_prompt()
        raw_response_text = agent.get_last_response_text()
        usage = agent.get_last_usage()
        total_input_tokens += usage.input_tokens
        total_output_tokens += usage.output_tokens

        write_text(attempt_prompt_path, prompt_text)
        write_text(attempt_raw_path, raw_response_text)
        write_text(attempt_output_path, output.model_dump_json(indent=2))
        prompt_sections.append((attempt, prompt_text))
        raw_sections.append((attempt, raw_response_text))
        write_text(prompt_path, combine_attempt_sections(label="PROMPT", sections=prompt_sections))
        write_text(
            raw_response_path,
            combine_attempt_sections(label="RAW RESPONSE", sections=raw_sections),
        )

        result = validate_script(
            output,
            preferred_obstacle_library_names=list(director_input.preferred_obstacle_library_names),
        )
        if result.is_valid:
            write_text(output_path, output.model_dump_json(indent=2))
            print(f"Job id: {director_input.job_id}")
            print(f"Input: {input_path}")
            print(f"RAG context: {rag_context_path}")
            print(f"Prompt: {prompt_path}")
            print(f"Raw response: {raw_response_path}")
            print(f"Validated output: {output_path}")
            print(f"Attempts: {attempt + 1}")
            print(f"Input tokens: {total_input_tokens}")
            print(f"Output tokens: {total_output_tokens}")

            if print_prompt:
                print("\n--- PROMPT ---")
                print(combine_attempt_sections(label="PROMPT", sections=prompt_sections))
            if print_rag_context:
                print("\n--- RAG CONTEXT ---")
                print(director_input.rag_context)
            if print_raw:
                print("\n--- RAW RESPONSE ---")
                print(combine_attempt_sections(label="RAW RESPONSE", sections=raw_sections))
            if print_json:
                print("\n--- JSON ---")
                print(output.model_dump_json(indent=2))
            return 0

        if attempt == config.MAX_AGENT_RETRY_COUNT:
            print(
                "Director-agent output failed deterministic script validation after "
                f"{config.MAX_AGENT_RETRY_COUNT + 1} attempts.",
                file=sys.stderr,
            )
            for error in result.errors:
                print(f"- {error}", file=sys.stderr)
            print(f"Input written to: {input_path}", file=sys.stderr)
            print(f"RAG context written to: {rag_context_path}", file=sys.stderr)
            print(f"Prompt written to: {prompt_path}", file=sys.stderr)
            print(f"Raw response written to: {raw_response_path}", file=sys.stderr)
            print(f"Last parsed output written to: {attempt_output_path}", file=sys.stderr)
            return 1

        errors_for_retry = result.errors

    print("Director-agent debug runner reached an unexpected fallthrough.", file=sys.stderr)
    return 1


def run() -> int:
    """Execute the Director-agent debug flow from CLI arguments.

    Returns:
        Process exit code. ``0`` on success, ``1`` on model or validation failure.
    """
    args = build_argument_parser().parse_args()
    output_dir = Path(args.output_dir)
    validation_errors = [str(error) for error in args.validation_error]
    try:
        director_input = build_director_input(args)
    except (FileNotFoundError, ValueError) as error:
        print(f"Director-agent input error: {error}", file=sys.stderr)
        return 1
    output_prefix = (
        str(args.output_prefix) if args.output_prefix is not None else director_input.job_id
    )
    return run_director_debug_session(
        director_input=director_input,
        output_dir=output_dir,
        output_prefix=output_prefix,
        validation_errors=validation_errors,
        agent=DirectorAgent(model_client=get_bedrock_runtime_client()),
        print_prompt=args.print_prompt,
        print_rag_context=args.print_rag_context,
        print_json=args.print_json,
        print_raw=args.print_raw,
    )


if __name__ == "__main__":
    raise SystemExit(run())
