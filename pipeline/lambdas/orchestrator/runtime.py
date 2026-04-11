"""Factory helpers for assembling orchestrator-lambda dependencies from env."""

from __future__ import annotations

import os

from pipeline.agents.animator.agent import AnimatorAgent
from pipeline.agents.director.agent import DirectorAgent
from pipeline.agents.drawing.agent import DrawingAgent
from pipeline.agents.renderer.agent import RendererAgent
from pipeline.lambdas.orchestrator.dependencies import build_library_lookups
from pipeline.lambdas.orchestrator.knowledge_base import BedrockKnowledgeBaseService
from pipeline.lambdas.orchestrator.pipeline_orchestrator import PipelineOrchestrator
from pipeline.lambdas.shared.aws_clients import (
    get_bedrock_agent_runtime_client,
    get_bedrock_agentcore_client,
    get_bedrock_runtime_client,
)
from pipeline.lambdas.shared.runtime import build_episode_store_from_env, build_job_store_from_env


def build_pipeline_orchestrator_from_env() -> PipelineOrchestrator:
    """Build the current pipeline orchestrator from Lambda environment values."""
    runtime_client = get_bedrock_runtime_client()
    return PipelineOrchestrator(
        job_store=build_job_store_from_env(),
        director_agent=DirectorAgent(model_client=runtime_client),
        animator_agent=AnimatorAgent(model_client=runtime_client),
        drawing_agent=DrawingAgent(model_client=runtime_client),
        renderer_agent=RendererAgent(model_client=runtime_client),
        knowledge_base_service=BedrockKnowledgeBaseService(
            client=get_bedrock_agent_runtime_client(),
            knowledge_base_id=os.environ["BEDROCK_KNOWLEDGE_BASE_ID"],
        ),
        agentcore_client=get_bedrock_agentcore_client(),
        episode_store=build_episode_store_from_env(),
        library_lookups=build_library_lookups(),
    )
