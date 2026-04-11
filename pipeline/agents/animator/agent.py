"""Animator agent implementation for Phase 5.

The Animator agent translates a validated Director script into precise clip
manifests and keyframes. It does not perform persistence or any cross-agent
calls; it only builds a deterministic prompt, invokes the model, and validates
the model-shaped JSON into typed Pydantic models.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from pipeline import config
from pipeline.media.linai_template import get_linai_part_ids
from pipeline.models import AnimatorInput, AnimatorOutput
from pipeline.shared.logging import log_event


@cache
def _read_prompt_template(prompt_path: str) -> str:
    """Return cached prompt-template text for one prompt path."""
    return Path(prompt_path).read_text(encoding="utf-8")


@dataclass
class AnimatorUsage:
    """Token usage metadata extracted from the Animator model response.

    Args:
        input_tokens: Number of input tokens consumed by the model call.
        output_tokens: Number of output tokens produced by the model call.
    """

    input_tokens: int
    output_tokens: int


class AnimatorAgent:
    """Generate a validated ``AnimatorOutput`` JSON payload from script input.

    Args:
        model_client: Optional Bedrock runtime-like client. Must expose
            ``converse(...)`` when provided.
        model_id: Bedrock model identifier used for generation.
        prompt_path: Absolute or relative path to the Animator prompt template.

    Raises:
        ValueError: If required prompt placeholders are missing.
        RuntimeError: If the model output cannot be parsed as valid JSON.
    """

    def __init__(
        self,
        model_client: Any | None = None,
        model_id: str = config.BEDROCK_MODEL_ID_ANIMATOR,
        prompt_path: str | Path = Path(__file__).parent / "prompt.txt",
    ) -> None:
        """Initialise the Animator agent with deterministic prompt loading.

        Args:
            model_client: Optional external model client, primarily for tests.
            model_id: Bedrock model identifier.
            prompt_path: Prompt template path.
        """
        self._model_client = model_client
        self._model_id = model_id
        self._prompt_path = Path(prompt_path)
        self._prompt_template = _read_prompt_template(str(self._prompt_path.resolve()))
        self._last_usage = AnimatorUsage(input_tokens=0, output_tokens=0)
        self._last_prompt = ""
        self._last_response_text = ""
        log_event(
            "DEBUG",
            "AnimatorAgent",
            "init_complete",
            message="Loaded the Animator prompt template and runtime settings.",
            has_model_client=model_client is not None,
            model_id=model_id,
            prompt_path=str(prompt_path),
            prompt_template_length=len(self._prompt_template),
        )

    def spawn_parallel_worker(self) -> AnimatorAgent:
        """Return a fresh Animator agent configured like this one.

        A fresh instance keeps per-run prompt/response bookkeeping isolated so
        multiple act-specific Bedrock calls can run in parallel safely.
        """
        return AnimatorAgent(
            model_client=self._model_client,
            model_id=self._model_id,
            prompt_path=self._prompt_path,
        )

    def run(
        self,
        input: AnimatorInput,
        validation_errors: list[str] | None = None,
    ) -> AnimatorOutput:
        """Run the Animator model and return typed output.

        Args:
            input: Typed animator input payload.
            validation_errors: Optional validator errors from the previous attempt.

        Returns:
            ``AnimatorOutput`` parsed from model JSON.

        Raises:
            RuntimeError: If model output is missing or not valid JSON.
        """
        log_event(
            "DEBUG",
            "AnimatorAgent",
            "run_start",
            message="Starting an Animator agent run for the current job.",
            job_id=input.job_id,
            session_id=input.session_id,
            act_count=len(input.acts),
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
                "AnimatorAgent",
                "run_failed_invalid_json",
                message="Animator returned text that could not be parsed as valid JSON.",
                job_id=input.job_id,
                response_length=len(response_text),
            )
            msg = "Animator model returned invalid JSON"
            raise RuntimeError(msg) from error

        output = AnimatorOutput.model_validate(parsed)
        log_event(
            "DEBUG",
            "AnimatorAgent",
            "run_complete",
            message="Animator returned a keyframe payload that passed model validation.",
            job_id=input.job_id,
            clip_count=len(output.clips),
        )
        return output

    def get_last_usage(self) -> AnimatorUsage:
        """Return token usage metadata from the latest ``run`` call.

        Returns:
            ``AnimatorUsage`` for the latest invocation.
        """
        log_event(
            "DEBUG",
            "AnimatorAgent",
            "get_last_usage",
            message="Returning token usage from the latest Animator run.",
            input_tokens=self._last_usage.input_tokens,
            output_tokens=self._last_usage.output_tokens,
        )
        return self._last_usage

    def get_last_prompt(self) -> str:
        """Return the final prompt text used in the latest ``run`` call.

        Returns:
            Prompt text as sent to the model.
        """
        log_event(
            "DEBUG",
            "AnimatorAgent",
            "get_last_prompt",
            message="Returning the latest prompt sent to the Animator model.",
            prompt_length=len(self._last_prompt),
        )
        return self._last_prompt

    def get_last_response_text(self) -> str:
        """Return raw model response text from the latest ``run`` call.

        Returns:
            Raw response text before JSON parsing.
        """
        log_event(
            "DEBUG",
            "AnimatorAgent",
            "get_last_response_text",
            message="Returning the latest raw response from the Animator model.",
            response_length=len(self._last_response_text),
        )
        return self._last_response_text

    def build_prompt(
        self,
        input: AnimatorInput,
        validation_errors: list[str] | None = None,
    ) -> str:
        """Build the exact prompt text that will be sent to the Animator model.

        Args:
            input: Animator input data.
            validation_errors: Optional previous validation errors.

        Returns:
            Final prompt string for the model call.
        """
        return self._build_prompt(input=input, validation_errors=validation_errors)

    def _build_prompt(
        self,
        input: AnimatorInput,
        validation_errors: list[str] | None,
    ) -> str:
        """Build a deterministic Animator prompt from template placeholders.

        Args:
            input: Animator input data.
            validation_errors: Optional previous validation errors.

        Returns:
            Final prompt string for the model call.

        Raises:
            ValueError: If required placeholders are missing.
        """
        log_event(
            "DEBUG",
            "AnimatorAgent",
            "build_prompt_start",
            message="Building the Animator prompt from the template and inputs.",
            job_id=input.job_id,
            has_validation_errors=validation_errors is not None,
        )

        required_placeholders = (
            "{acts_json}",
            "{walk_duration_seconds}",
            "{canvas_width}",
            "{canvas_height}",
            "{ground_line_y}",
            "{handoff_character_x}",
            "{min_character_y_in_frame_px}",
            "{max_grounded_approach_character_x}",
            "{support_y_tolerance_px}",
            "{handoff_support_y_tolerance_px}",
            "{requires_handoff_in}",
            "{requires_handoff_out}",
            "{linai_part_ids_json}",
        )
        if any(placeholder not in self._prompt_template for placeholder in required_placeholders):
            msg = (
                "Animator prompt template must include the required placeholders: "
                f"{', '.join(required_placeholders)}"
            )
            raise ValueError(msg)

        prompt = (
            self._prompt_template.replace(
                "{acts_json}",
                json.dumps(
                    [act.model_dump(mode="json") for act in input.acts],
                    ensure_ascii=False,
                ),
            )
            .replace("{walk_duration_seconds}", str(input.walk_duration_seconds))
            .replace("{canvas_width}", str(input.canvas_width))
            .replace("{canvas_height}", str(input.canvas_height))
            .replace("{ground_line_y}", str(input.ground_line_y))
            .replace("{handoff_character_x}", str(input.handoff_character_x))
            .replace(
                "{min_character_y_in_frame_px}",
                str(config.MIN_CHARACTER_Y_IN_FRAME_PX),
            )
            .replace(
                "{max_grounded_approach_character_x}",
                str(config.MAX_GROUNDED_APPROACH_CHARACTER_X),
            )
            .replace("{support_y_tolerance_px}", str(config.SUPPORT_Y_TOLERANCE_PX))
            .replace(
                "{handoff_support_y_tolerance_px}",
                str(config.HANDOFF_SUPPORT_Y_TOLERANCE_PX),
            )
            .replace("{requires_handoff_in}", json.dumps(input.requires_handoff_in))
            .replace("{requires_handoff_out}", json.dumps(input.requires_handoff_out))
            .replace(
                "{linai_part_ids_json}",
                json.dumps(get_linai_part_ids(), ensure_ascii=False),
            )
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
            "AnimatorAgent",
            "build_prompt_complete",
            message="Finished assembling the Animator prompt text.",
            job_id=input.job_id,
            prompt_length=len(prompt),
        )
        return prompt

    def _invoke_model(self, prompt: str, *, job_id: str) -> tuple[str, AnimatorUsage]:
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
            "AnimatorAgent",
            "invoke_model_start",
            message="Calling the Bedrock Animator model.",
            job_id=job_id,
            model_id=self._model_id,
            prompt_length=len(prompt),
            has_model_client=self._model_client is not None,
        )
        if self._model_client is None:
            msg = "AnimatorAgent requires a model_client for runtime invocation"
            raise RuntimeError(msg)

        response = self._model_client.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": config.MAX_OUTPUT_TOKENS_ANIMATOR_STAGE,
                "temperature": 0.2,
            },
        )

        try:
            text = response["output"]["message"]["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as error:
            msg = "Animator model response missing output.message.content[0].text"
            raise RuntimeError(msg) from error

        usage_raw = response.get("usage", {})
        usage = AnimatorUsage(
            input_tokens=int(usage_raw.get("inputTokens", 0)),
            output_tokens=int(usage_raw.get("outputTokens", 0)),
        )

        log_event(
            "DEBUG",
            "AnimatorAgent",
            "invoke_model_complete",
            message="Received a response from the Bedrock Animator model.",
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
            "AnimatorAgent",
            "parse_json_object_start",
            message="Parsing a JSON object from the Animator response text.",
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
                "AnimatorAgent",
                "parse_json_object_failed_non_object_root",
                message="Animator returned JSON with a non-object root value.",
                job_id=job_id,
                root_type=type(parsed).__name__,
            )
            msg = "Animator JSON root must be an object"
            raise RuntimeError(msg)
        log_event(
            "DEBUG",
            "AnimatorAgent",
            "parse_json_object_complete",
            message="Parsed a JSON object from the Animator response text.",
            job_id=job_id,
            key_count=len(parsed),
        )
        return parsed
