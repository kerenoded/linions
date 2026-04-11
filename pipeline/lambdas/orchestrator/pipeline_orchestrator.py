"""Pipeline orchestration entrypoint for the generate Lambda workflow."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pipeline.agents.animator.agent import AnimatorAgent
from pipeline.agents.director.agent import DirectorAgent
from pipeline.agents.drawing.agent import DrawingAgent
from pipeline.agents.renderer.agent import RendererAgent
from pipeline.config import (
    STAGE_FAILED,
    STAGE_KB_QUERY,
)
from pipeline.lambdas.orchestrator.director_animator_flow import (
    OrchestratorDirectorAnimatorMixin,
)
from pipeline.lambdas.orchestrator.knowledge_base import BedrockKnowledgeBaseService
from pipeline.lambdas.orchestrator.persistence_flow import OrchestratorPersistenceMixin
from pipeline.lambdas.orchestrator.render_assets_flow import OrchestratorRenderAssetsMixin
from pipeline.lambdas.orchestrator.stage_common import OrchestratorStageCommonMixin
from pipeline.models import DirectorOutput
from pipeline.shared.logging import log_event
from pipeline.storage.episode_store import EpisodeStore
from pipeline.storage.job_store import JobStore


@dataclass
class LibraryLookups:
    """Bundled library lookup callables injected into the orchestrator.

    Wrapping these as a dataclass rather than importing the library modules
    directly means tests can substitute fakes without monkey-patching module
    globals. Each field is a callable matching the real library function's
    signature.

    Attributes:
        get_obstacle_svg: Return the bundled obstacle SVG for a slug, or ``None``.
        list_obstacle_names: Return all bundled obstacle slug names.
        get_background_svg: Return the bundled background SVG for a slug, or ``None``.
        find_background_library_slug: Heuristically match a prompt to a library slug, or ``None``.
        prompt_to_background_slug: Convert a background prompt to a stable slug string.
    """

    get_obstacle_svg: Callable[[str], str | None]
    list_obstacle_names: Callable[[], list[str]]
    get_background_svg: Callable[[str], str | None]
    find_background_library_slug: Callable[[str, str], str | None]
    prompt_to_background_slug: Callable[[str], str]


class PipelineOrchestrator(
    OrchestratorDirectorAnimatorMixin,
    OrchestratorRenderAssetsMixin,
    OrchestratorPersistenceMixin,
    OrchestratorStageCommonMixin,
):
    """Run the generation pipeline through the currently implemented stages."""

    def __init__(
        self,
        job_store: JobStore,
        director_agent: DirectorAgent,
        animator_agent: AnimatorAgent,
        drawing_agent: DrawingAgent | None,
        renderer_agent: RendererAgent | None,
        knowledge_base_service: BedrockKnowledgeBaseService,
        agentcore_client: Any,
        episode_store: EpisodeStore | None,
        library_lookups: LibraryLookups,
    ) -> None:
        """Initialise the orchestrator with its integration dependencies.

        Args:
            job_store: DynamoDB-backed job state persistence adapter.
            director_agent: Director stage model wrapper.
            animator_agent: Animator stage model wrapper.
            drawing_agent: Drawing stage model wrapper, used for unknown obstacle slugs.
            renderer_agent: Renderer stage model wrapper.
            knowledge_base_service: Bedrock Knowledge Base retrieval adapter.
            agentcore_client: AgentCore session client.
            episode_store: S3-backed episode artifact store.
            library_lookups: Bundled obstacle/background library lookup callables.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "init_start",
            message="Initializing the pipeline orchestrator dependencies.",
            has_job_store=job_store is not None,
            has_director_agent=director_agent is not None,
            has_animator_agent=animator_agent is not None,
            has_drawing_agent=drawing_agent is not None,
            has_renderer_agent=renderer_agent is not None,
            has_knowledge_base_service=knowledge_base_service is not None,
            has_agentcore_client=agentcore_client is not None,
            has_episode_store=episode_store is not None,
            has_library_lookups=library_lookups is not None,
        )
        self._job_store = job_store
        self._director_agent = director_agent
        self._animator_agent = animator_agent
        self._drawing_agent = drawing_agent
        self._renderer_agent = renderer_agent
        self._knowledge_base_service = knowledge_base_service
        self._agentcore_client = agentcore_client
        self._episode_store = episode_store
        self._library_lookups = library_lookups
        self._run_started_at: float | None = None
        self._remaining_time_provider: Callable[[], int] | None = None

    def run(
        self,
        *,
        job_id: str,
        prompt: str,
        username: str,
        remaining_time_provider: Callable[[], int] | None = None,
    ) -> dict[str, str]:
        """Execute the generation pipeline for one job.

        Args:
            job_id: Generation job identifier.
            prompt: User prompt text.
            username: Developer GitHub username injected by the proxy.
            remaining_time_provider: Optional Lambda remaining-time callback.

        Returns:
            Small result dictionary summarizing success or failure reason.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "run_start",
            message="Starting the pipeline orchestration flow for the job.",
            job_id=job_id,
            username=username,
            prompt_length=len(prompt),
        )
        self._run_started_at = time.perf_counter()
        self._remaining_time_provider = remaining_time_provider
        try:
            self._ensure_job_is_generating(job_id)
            session_id = self._create_agentcore_session(job_id=job_id)

            try:
                rag_context = self._retrieve_rag_context(job_id=job_id, prompt=prompt)
            except Exception as error:
                return self._handle_rag_context_failure(job_id=job_id, error=error)

            director_output_or_failure = self._run_director_attempts(
                job_id=job_id,
                prompt=prompt,
                username=username,
                session_id=session_id,
                rag_context=rag_context,
            )
            if isinstance(director_output_or_failure, dict):
                return director_output_or_failure
            director_output: DirectorOutput = director_output_or_failure

            animator_output_or_failure = self._run_animator_attempts(
                job_id=job_id,
                session_id=session_id,
                director_output=director_output,
            )
            if isinstance(animator_output_or_failure, dict):
                return animator_output_or_failure
            animator_output = animator_output_or_failure

            drawing_resolution_or_failure = self._resolve_drawing_svgs(
                job_id=job_id,
                session_id=session_id,
                director_output=director_output,
                animator_output=animator_output,
            )
            if isinstance(drawing_resolution_or_failure, dict):
                return drawing_resolution_or_failure
            animator_output = drawing_resolution_or_failure

            renderer_input = self._build_renderer_input(
                job_id=job_id,
                session_id=session_id,
                animator_output=animator_output,
            )
            renderer_output_or_failure = self._run_renderer_attempts(
                job_id=job_id,
                renderer_input=renderer_input,
            )
            if isinstance(renderer_output_or_failure, dict):
                return renderer_output_or_failure
            renderer_output = renderer_output_or_failure

            return self._complete_successful_run(
                job_id=job_id,
                username=username,
                director_output=director_output,
                animator_output=animator_output,
                renderer_output=renderer_output,
            )
        finally:
            self._run_started_at = None
            self._remaining_time_provider = None

    def _ensure_job_is_generating(self, job_id: str) -> None:
        """Fail loudly when the job is missing or not in ``GENERATING`` state.

        Args:
            job_id: Generation job identifier.

        Raises:
            RuntimeError: If the job does not exist or is not ``GENERATING``.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "ensure_job_is_generating_start",
            message="Checking that the job is ready to continue orchestration.",
            job_id=job_id,
        )
        job = self._job_store.get_job(job_id)
        if job is None:
            msg = f"Job not found: {job_id}"
            raise RuntimeError(msg)
        if job.get("status") != "GENERATING":
            msg = f"Job {job_id} not in GENERATING state"
            raise RuntimeError(msg)

    def _retrieve_rag_context(self, *, job_id: str, prompt: str) -> str:
        """Update stage state and build the Director RAG context.

        Args:
            job_id: Generation job identifier.
            prompt: User prompt text.

        Returns:
            Formatted RAG context string.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "retrieve_rag_context_start",
            message="Retrieving grounding context from the knowledge base for the Director stage.",
            job_id=job_id,
            prompt_length=len(prompt),
        )
        self._job_store.update_stage_generating(job_id, STAGE_KB_QUERY)
        return self._knowledge_base_service.build_rag_context(prompt)

    def _handle_rag_context_failure(self, *, job_id: str, error: Exception) -> dict[str, str]:
        """Log and persist a KB retrieval failure.

        Args:
            job_id: Generation job identifier.
            error: Retrieval failure.

        Returns:
            Failure result payload.
        """
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "handle_rag_context_failure_start",
            message="Handling a knowledge-base retrieval failure before agent execution.",
            job_id=job_id,
            error_type=type(error).__name__,
        )
        error_type = type(error).__name__
        self._log_agent_event(
            level="ERROR",
            job_id=job_id,
            component="KnowledgeBaseRetrieve",
            event="retrieve_failed",
            message="Knowledge-base retrieval failed and the generation run cannot continue.",
            duration_ms=0,
            model_id=None,
            input_tokens=0,
            output_tokens=0,
            retry_count=0,
            validation_result="fail",
            validation_errors=[f"{error_type}: {error}"],
        )
        self._job_store.mark_failed(
            job_id=job_id,
            error_message=f"Knowledge base retrieve failed ({error_type}): {error}",
            stage=STAGE_FAILED,
        )
        return {
            "result": "failed",
            "reason": "kb_retrieve_failed",
            "errorType": error_type,
            "error": str(error),
        }
