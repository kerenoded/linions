"""Renderer agent implementation for Phase 5.

The Renderer agent translates validated clip manifests plus resolved obstacle
SVGs into complete self-contained scene SVGs. It does not persist artifacts or
call other pipeline stages.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from pipeline import config
from pipeline.media.linai_template import get_linai_part_ids, get_linai_template_svg
from pipeline.models import RendererInput, RendererOutput
from pipeline.shared.logging import log_event

_SYSTEM_COMPOSED_OBSTACLE_MARKER = "__SYSTEM_COMPOSED_OBSTACLE__"
_SYSTEM_COMPOSED_BACKGROUND_MARKER = "__SYSTEM_COMPOSED_BACKGROUND__"
_DOUBLE_QUOTED_ATTR_RE = re.compile(r'="([^"]*)"')
_SVG_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


@cache
def _read_prompt_template(prompt_path: str) -> str:
    """Return cached prompt-template text for one prompt path."""
    return Path(prompt_path).read_text(encoding="utf-8")


def _compact_svg_for_prompt(svg_text: str) -> str:
    """Return a prompt-friendly SVG string with compact single-quoted attributes."""
    compact = _SVG_COMMENT_RE.sub("", svg_text).strip()
    compact = re.sub(r">\s+<", "><", compact)
    compact = re.sub(r"\s{2,}", " ", compact)

    def _replace_attr(match: re.Match[str]) -> str:
        value = match.group(1)
        if "'" in value:
            return match.group(0)
        return f"='{value}'"

    return _DOUBLE_QUOTED_ATTR_RE.sub(_replace_attr, compact)


@dataclass
class RendererUsage:
    """Token usage metadata extracted from the Renderer model response."""

    input_tokens: int
    output_tokens: int


class RendererAgent:
    """Generate a validated ``RendererOutput`` JSON payload from clip manifests."""

    def __init__(
        self,
        model_client: Any | None = None,
        model_id: str = config.BEDROCK_MODEL_ID_RENDERER,
        prompt_path: str | Path = Path(__file__).parent / "prompt.txt",
    ) -> None:
        """Initialise the Renderer agent with deterministic prompt loading.

        Args:
            model_client: Optional external model client, primarily for tests.
            model_id: Bedrock model identifier.
            prompt_path: Prompt template path.
        """
        self._model_client = model_client
        self._model_id = model_id
        self._prompt_path = Path(prompt_path)
        self._prompt_template = _read_prompt_template(str(self._prompt_path.resolve()))
        self._last_usage = RendererUsage(input_tokens=0, output_tokens=0)
        self._last_prompt = ""
        self._last_response_text = ""
        log_event(
            "DEBUG",
            "RendererAgent",
            "init_complete",
            message="Loaded the Renderer prompt template and runtime settings.",
            has_model_client=model_client is not None,
            model_id=model_id,
            prompt_path=str(prompt_path),
            prompt_template_length=len(self._prompt_template),
        )

    def spawn_parallel_worker(self) -> RendererAgent:
        """Return a fresh Renderer agent configured like this one.

        A fresh instance keeps prompt, usage, and raw-response bookkeeping
        isolated so multiple clip-specific Bedrock calls can run in parallel
        safely.
        """
        return RendererAgent(
            model_client=self._model_client,
            model_id=self._model_id,
            prompt_path=self._prompt_path,
        )

    def run(
        self,
        input: RendererInput,
        validation_errors: list[str] | None = None,
    ) -> RendererOutput:
        """Run the Renderer model and return typed output.

        Args:
            input: Typed renderer input payload.
            validation_errors: Optional validator errors from the previous attempt.

        Returns:
            ``RendererOutput`` parsed from model JSON.

        Raises:
            RuntimeError: If model output is missing or not valid JSON.
        """
        log_event(
            "DEBUG",
            "RendererAgent",
            "run_start",
            message="Starting a Renderer agent run for the current job.",
            job_id=input.job_id,
            session_id=input.session_id,
            clip_count=len(input.clips),
            has_validation_errors=validation_errors is not None,
        )
        prompt = self.build_prompt(input=input, validation_errors=validation_errors)
        self._last_prompt = prompt
        response_text, usage = self._invoke_model(prompt=prompt, job_id=input.job_id)
        self._last_response_text = response_text
        self._last_usage = usage

        try:
            parsed = self._parse_json_object(response_text, job_id=input.job_id)
        except json.JSONDecodeError as error:
            log_event(
                "ERROR",
                "RendererAgent",
                "run_failed_invalid_json",
                message="Renderer returned text that could not be parsed as valid JSON.",
                job_id=input.job_id,
                response_length=len(response_text),
            )
            msg = "Renderer model returned invalid JSON"
            raise RuntimeError(msg) from error

        output = RendererOutput.model_validate(parsed)
        log_event(
            "DEBUG",
            "RendererAgent",
            "run_complete",
            message="Renderer returned an SVG clip payload that passed model validation.",
            job_id=input.job_id,
            clip_count=len(output.clips),
        )
        return output

    def get_last_usage(self) -> RendererUsage:
        """Return token usage metadata from the latest ``run`` call.

        Returns:
            ``RendererUsage`` for the latest invocation.
        """
        return self._last_usage

    def get_last_prompt(self) -> str:
        """Return the final prompt text used in the latest ``run`` call.

        Returns:
            Prompt text as sent to the model.
        """
        return self._last_prompt

    def get_last_response_text(self) -> str:
        """Return raw model response text from the latest ``run`` call.

        Returns:
            Raw response text before JSON parsing.
        """
        return self._last_response_text

    def build_prompt(
        self,
        input: RendererInput,
        validation_errors: list[str] | None = None,
    ) -> str:
        """Build the exact prompt text that will be sent to the Renderer model.

        Args:
            input: Renderer input data.
            validation_errors: Optional previous validation errors.

        Returns:
            Final prompt string for the model call.
        """
        return self._build_prompt(input=input, validation_errors=validation_errors)

    def _build_prompt(
        self,
        input: RendererInput,
        validation_errors: list[str] | None,
    ) -> str:
        """Build a deterministic Renderer prompt from template placeholders.

        Args:
            input: Renderer input data.
            validation_errors: Optional previous validation errors.

        Returns:
            Final prompt string for the model call.

        Raises:
            ValueError: If required placeholders are missing.
        """
        required_placeholders = (
            "{clips_json}",
            "{canvas_width}",
            "{canvas_height}",
            "{ground_line_y}",
            "{obstacle_embed_x}",
            "{obstacle_embed_y}",
            "{obstacle_embed_width}",
            "{obstacle_embed_height}",
            "{linai_part_ids_json}",
            "{linai_template_svg}",
        )
        if any(placeholder not in self._prompt_template for placeholder in required_placeholders):
            msg = (
                "Renderer prompt template must include the required placeholders: "
                f"{', '.join(required_placeholders)}"
            )
            raise ValueError(msg)

        prompt = (
            self._prompt_template.replace(
                "{clips_json}",
                json.dumps(
                    [
                        clip.model_copy(
                            update={
                                "obstacle_svg_override": (
                                    _SYSTEM_COMPOSED_OBSTACLE_MARKER
                                    if clip.obstacle_svg_override is not None
                                    else None
                                ),
                                "background_svg": (
                                    _SYSTEM_COMPOSED_BACKGROUND_MARKER
                                    if clip.background_svg is not None
                                    else None
                                ),
                            }
                        ).model_dump(mode="json")
                        for clip in input.clips
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            .replace("{canvas_width}", str(config.CANVAS_WIDTH))
            .replace("{canvas_height}", str(config.CANVAS_HEIGHT))
            .replace("{ground_line_y}", str(config.GROUND_LINE_Y))
            .replace("{obstacle_embed_x}", str(config.OBSTACLE_EMBED_X))
            .replace("{obstacle_embed_y}", str(config.OBSTACLE_EMBED_Y))
            .replace("{obstacle_embed_width}", str(config.OBSTACLE_EMBED_WIDTH))
            .replace("{obstacle_embed_height}", str(config.OBSTACLE_EMBED_HEIGHT))
            .replace(
                "{linai_part_ids_json}",
                json.dumps(get_linai_part_ids(), ensure_ascii=False, separators=(",", ":")),
            )
            .replace("{linai_template_svg}", _compact_svg_for_prompt(get_linai_template_svg()))
        )

        if validation_errors:
            error_block = "\n".join(f"- {error}" for error in validation_errors)
            prompt += (
                "\n\nPrevious attempt failed deterministic validation. "
                "You MUST fix these exact errors:\n"
                f"{error_block}\n"
            )

        log_event(
            "DEBUG",
            "RendererAgent",
            "build_prompt_complete",
            message="Finished assembling the Renderer prompt text.",
            job_id=input.job_id,
            prompt_length=len(prompt),
        )
        return prompt

    def _invoke_model(self, prompt: str, *, job_id: str) -> tuple[str, RendererUsage]:
        """Invoke the configured model client and extract response text plus usage.

        Args:
            prompt: Prompt text to send.
            job_id: Current generation job identifier for logging context.

        Returns:
            Tuple of ``(response_text, usage)``.

        Raises:
            RuntimeError: If no model client is configured or response shape is invalid.
        """
        log_event(
            "DEBUG",
            "RendererAgent",
            "invoke_model_start",
            message="Calling the Bedrock Renderer model.",
            job_id=job_id,
            model_id=self._model_id,
            prompt_length=len(prompt),
            has_model_client=self._model_client is not None,
        )
        if self._model_client is None:
            msg = "RendererAgent requires a model_client for runtime invocation"
            raise RuntimeError(msg)

        response = self._model_client.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": config.MAX_OUTPUT_TOKENS_RENDERER_STAGE,
                "temperature": 0.2,
            },
        )

        try:
            text = response["output"]["message"]["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as error:
            msg = "Renderer model response missing output.message.content[0].text"
            raise RuntimeError(msg) from error

        usage_raw = response.get("usage", {})
        usage = RendererUsage(
            input_tokens=int(usage_raw.get("inputTokens", 0)),
            output_tokens=int(usage_raw.get("outputTokens", 0)),
        )
        log_event(
            "DEBUG",
            "RendererAgent",
            "invoke_model_complete",
            message="Received a response from the Bedrock Renderer model.",
            job_id=job_id,
            model_id=self._model_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            response_length=len(text),
        )
        return text, usage

    def _parse_json_object(self, text: str, *, job_id: str) -> dict[str, Any]:
        """Parse a JSON object from raw model text.

        Args:
            text: Raw model response text.
            job_id: Current generation job identifier for logging context.

        Returns:
            Parsed JSON object.

        Raises:
            json.JSONDecodeError: If JSON parsing fails.
        """
        log_event(
            "DEBUG",
            "RendererAgent",
            "parse_json_object_start",
            message="Parsing a JSON object from the Renderer response text.",
            job_id=job_id,
            text_length=len(text),
        )
        stripped = text.strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        candidate = (
            stripped if start == 0 and end == len(stripped) - 1 else stripped[start : end + 1]
        )
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            log_event(
                "ERROR",
                "RendererAgent",
                "parse_json_object_failed_non_object_root",
                message="Renderer returned JSON with a non-object root value.",
                job_id=job_id,
                root_type=type(parsed).__name__,
            )
            msg = "Renderer JSON root must be an object"
            raise RuntimeError(msg)
        log_event(
            "DEBUG",
            "RendererAgent",
            "parse_json_object_complete",
            message="Parsed a JSON object from the Renderer response text.",
            job_id=job_id,
            key_count=len(parsed),
        )
        return parsed
