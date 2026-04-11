"""Helpers for running multiple Drawing tasks in parallel."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from pipeline import config
from pipeline.agents.drawing.agent import DrawingAgent, DrawingUsage
from pipeline.models import DrawingInput, DrawingOutput


@dataclass
class DrawingTaskRunResult:
    """Result bundle for one Drawing task model call."""

    task_identity: tuple[str, str]
    drawing_input: DrawingInput
    output: DrawingOutput | None
    usage: DrawingUsage
    prompt: str
    response_text: str
    elapsed_ms: int
    error: Exception | None = None


def run_drawing_tasks_in_parallel(
    *,
    base_agent: DrawingAgent,
    drawing_inputs: list[DrawingInput],
    validation_errors_by_identity: dict[tuple[str, str], list[str] | None] | None = None,
    max_workers: int = config.MAX_PARALLEL_DRAWING_TASKS,
) -> list[DrawingTaskRunResult]:
    """Run multiple Drawing Bedrock calls in parallel.

    Args:
        base_agent: Configured Drawing agent to clone for each worker.
        drawing_inputs: Drawing inputs to run.
        validation_errors_by_identity: Optional retry errors keyed by task identity.
        max_workers: Maximum worker count to use.

    Returns:
        Results for all drawing tasks in arbitrary completion order.
    """

    def _run_one_task(drawing_input: DrawingInput) -> DrawingTaskRunResult:
        task_identity = (drawing_input.drawing_type, drawing_input.obstacle_type)
        worker = base_agent.spawn_parallel_worker()
        started = time.perf_counter()
        try:
            output = worker.run(
                drawing_input,
                validation_errors=(
                    validation_errors_by_identity.get(task_identity)
                    if validation_errors_by_identity is not None
                    else None
                ),
            )
        except Exception as error:  # pragma: no cover - covered via orchestrator tests
            return DrawingTaskRunResult(
                task_identity=task_identity,
                drawing_input=drawing_input,
                output=None,
                usage=worker.get_last_usage(),
                prompt=worker.get_last_prompt(),
                response_text=worker.get_last_response_text(),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error=error,
            )

        return DrawingTaskRunResult(
            task_identity=task_identity,
            drawing_input=drawing_input,
            output=output,
            usage=worker.get_last_usage(),
            prompt=worker.get_last_prompt(),
            response_text=worker.get_last_response_text(),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    if not drawing_inputs:
        return []

    bounded_workers = min(len(drawing_inputs), max_workers)
    results: list[DrawingTaskRunResult] = []
    with ThreadPoolExecutor(max_workers=bounded_workers) as executor:
        futures = [
            executor.submit(_run_one_task, drawing_input) for drawing_input in drawing_inputs
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return results
