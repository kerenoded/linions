"""Helpers for running multiple Renderer clip calls in parallel."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from pipeline.agents.renderer.agent import RendererAgent, RendererUsage
from pipeline.models import RendererInput, RendererOutput


@dataclass
class RendererClipRunResult:
    """Result bundle for one clip-specific Renderer model call."""

    clip_identity: tuple[int, str, int | None]
    renderer_input: RendererInput
    output: RendererOutput | None
    usage: RendererUsage
    prompt: str
    response_text: str
    elapsed_ms: int
    error: Exception | None = None


def run_renderer_clips_in_parallel(
    *,
    base_agent: RendererAgent,
    renderer_inputs: list[RendererInput],
    validation_errors_by_identity: (
        dict[tuple[int, str, int | None], list[str] | None] | None
    ) = None,
) -> list[RendererClipRunResult]:
    """Run one Renderer Bedrock call per clip in parallel.

    Args:
        base_agent: Configured Renderer agent to clone for each worker.
        renderer_inputs: One-clip Renderer inputs to run.
        validation_errors_by_identity: Optional retry errors keyed by clip identity.

    Returns:
        Results for all clip calls in arbitrary completion order.
    """

    def _run_one_clip(renderer_input: RendererInput) -> RendererClipRunResult:
        clip = renderer_input.clips[0]
        clip_identity = (clip.act_index, clip.branch, clip.choice_index)
        worker = base_agent.spawn_parallel_worker()
        started = time.perf_counter()
        try:
            output = worker.run(
                renderer_input,
                validation_errors=(
                    validation_errors_by_identity.get(clip_identity)
                    if validation_errors_by_identity is not None
                    else None
                ),
            )
        except Exception as error:  # pragma: no cover - covered via orchestrator tests
            return RendererClipRunResult(
                clip_identity=clip_identity,
                renderer_input=renderer_input,
                output=None,
                usage=worker.get_last_usage(),
                prompt=worker.get_last_prompt(),
                response_text=worker.get_last_response_text(),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error=error,
            )

        return RendererClipRunResult(
            clip_identity=clip_identity,
            renderer_input=renderer_input,
            output=output,
            usage=worker.get_last_usage(),
            prompt=worker.get_last_prompt(),
            response_text=worker.get_last_response_text(),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    if not renderer_inputs:
        return []

    max_workers = len(renderer_inputs)
    results: list[RendererClipRunResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_run_one_clip, renderer_input) for renderer_input in renderer_inputs
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return results
