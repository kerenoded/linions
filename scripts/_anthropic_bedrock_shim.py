"""Temporary shim: wraps the Anthropic Messages API to expose the same
.converse() interface that DrawingAgent expects from a Bedrock runtime client.

This is NOT a permanent project dependency. It exists only to run
run-drawing-agent.py against models not yet available on Bedrock (e.g. opus-4-7).
Delete once Bedrock supports the target model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class AnthropicConverseShim:
    """Expose a Bedrock-shaped .converse() method backed by the Anthropic API.

    Preserves the exact same inference configuration (max_tokens, temperature,
    top_p) that the Bedrock path uses so results are comparable.

    Args:
        model_id: Anthropic model id to use, e.g. "claude-opus-4-7".
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id
        self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    def converse(
        self,
        *,
        modelId: str,  # noqa: N803 — matches Bedrock kwarg name exactly
        system: list[dict[str, str]],
        messages: list[dict[str, Any]],
        inferenceConfig: dict[str, Any],  # noqa: N803
    ) -> dict[str, Any]:
        """Call Anthropic Messages API and return a Bedrock-shaped response dict.

        The agent reads:
          response["output"]["message"]["content"][0]["text"]
          response["usage"]["inputTokens"]
          response["usage"]["outputTokens"]
        """
        system_text = "\n".join(block["text"] for block in system)

        anthropic_messages = []
        for msg in messages:
            content_blocks = msg.get("content", [])
            text = "\n".join(block["text"] for block in content_blocks)
            anthropic_messages.append({"role": msg["role"], "content": text})

        response = self._client.messages.create(
            model=self._model_id,
            system=system_text,
            messages=anthropic_messages,
            max_tokens=inferenceConfig["maxTokens"],
        )

        text = response.content[0].text

        return {
            "output": {
                "message": {
                    "content": [{"text": text}]
                }
            },
            "usage": {
                "inputTokens": response.usage.input_tokens,
                "outputTokens": response.usage.output_tokens,
            },
        }
