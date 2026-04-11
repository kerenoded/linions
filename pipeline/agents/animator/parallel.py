"""Helpers for running multiple Animator act calls in parallel."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from pipeline.agents.animator.agent import AnimatorAgent, AnimatorUsage
from pipeline.models import AnimatorInput, AnimatorOutput


@dataclass
class AnimatorActRunResult:
    """Result bundle for one act-specific Animator model call."""

    act_index: int
    animator_input: AnimatorInput
    output: AnimatorOutput | None
    usage: AnimatorUsage
    prompt: str
    response_text: str
    error: Exception | None = None


def run_animator_acts_in_parallel(
    *,
    base_agent: AnimatorAgent,
    animator_inputs: list[AnimatorInput],
    validation_errors_by_act: dict[int, list[str] | None] | None = None,
) -> list[AnimatorActRunResult]:
    """Run one Animator Bedrock call per act in parallel.

    Args:
        base_agent: Configured Animator agent to clone for each worker.
        animator_inputs: One-act Animator inputs to run.
        validation_errors_by_act: Optional retry errors keyed by act index.

    Returns:
        Results for all act calls in arbitrary completion order.
    """

    def _run_one_act(animator_input: AnimatorInput) -> AnimatorActRunResult:
        act_index = animator_input.acts[0].act_index
        worker = base_agent.spawn_parallel_worker()
        try:
            output = worker.run(
                animator_input,
                validation_errors=(
                    validation_errors_by_act.get(act_index)
                    if validation_errors_by_act is not None
                    else None
                ),
            )
        except Exception as error:  # pragma: no cover - covered via orchestrator tests
            return AnimatorActRunResult(
                act_index=act_index,
                animator_input=animator_input,
                output=None,
                usage=worker.get_last_usage(),
                prompt=worker.get_last_prompt(),
                response_text=worker.get_last_response_text(),
                error=error,
            )

        return AnimatorActRunResult(
            act_index=act_index,
            animator_input=animator_input,
            output=output,
            usage=worker.get_last_usage(),
            prompt=worker.get_last_prompt(),
            response_text=worker.get_last_response_text(),
        )

    if not animator_inputs:
        return []

    max_workers = len(animator_inputs)
    results: list[AnimatorActRunResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_run_one_act, animator_input) for animator_input in animator_inputs
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return results
