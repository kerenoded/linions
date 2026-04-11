"""Director agent implementation for Phase 4.

The Director agent is responsible for generating a script-shaped JSON payload
from a user prompt plus pre-assembled RAG context supplied by the orchestrator.
The agent does not perform any RAG retrieval itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from pipeline import config
from pipeline.models import DirectorInput, DirectorOutput
from pipeline.shared.logging import log_event


@cache
def _read_prompt_template(prompt_path: str) -> str:
    """Return cached prompt-template text for one prompt path."""
    return Path(prompt_path).read_text(encoding="utf-8")


@dataclass
class DirectorUsage:
    """Token usage metadata extracted from the model response.

    Args:
        input_tokens: Number of input tokens consumed by the model call.
        output_tokens: Number of output tokens produced by the model call.
    """

    input_tokens: int
    output_tokens: int


class DirectorAgent:
    """Generate a validated ``DirectorOutput`` JSON payload from prompt + RAG context.

    Args:
        model_client: Optional Bedrock runtime-like client. Must expose
            ``converse(...)`` when provided.
        model_id: Bedrock model identifier used for generation.
        prompt_path: Absolute/relative path to the prompt template file.

    Raises:
        ValueError: If prompt template placeholders are missing.
        RuntimeError: If model output cannot be parsed as valid JSON.
    """

    def __init__(
        self,
        model_client: Any | None = None,
        model_id: str = config.BEDROCK_MODEL_ID_DIRECTOR,
        prompt_path: str | Path = Path(__file__).parent / "prompt.txt",
    ) -> None:
        """Initialise the Director agent with deterministic prompt template loading.

        Args:
            model_client: Optional external model client (primarily for tests).
            model_id: Bedrock model identifier.
            prompt_path: Prompt template path.
        """
        self._model_client = model_client
        self._model_id = model_id
        self._prompt_template = _read_prompt_template(str(Path(prompt_path).resolve()))
        self._last_usage = DirectorUsage(input_tokens=0, output_tokens=0)
        self._last_prompt = ""
        self._last_response_text = ""
        log_event(
            "DEBUG",
            "DirectorAgent",
            "init_complete",
            message="Loaded the Director prompt template and runtime settings.",
            has_model_client=model_client is not None,
            model_id=model_id,
            prompt_path=str(prompt_path),
            prompt_template_length=len(self._prompt_template),
        )

    def run(
        self,
        input: DirectorInput,
        validation_errors: list[str] | None = None,
    ) -> DirectorOutput:
        """Run the Director model and return typed output.

        Args:
            input: Typed director input payload.
            validation_errors: Optional validator errors from the previous attempt.

        Returns:
            ``DirectorOutput`` parsed from model JSON.

        Raises:
            RuntimeError: If model output is missing or not valid JSON.
        """
        log_event(
            "DEBUG",
            "DirectorAgent",
            "run_start",
            message="Starting a Director agent run for the current job.",
            job_id=input.job_id,
            username=input.username,
            session_id=input.session_id,
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
                "DirectorAgent",
                "run_failed_invalid_json",
                message="Director returned text that could not be parsed as valid JSON.",
                job_id=input.job_id,
                response_length=len(response_text),
            )
            msg = "Director model returned invalid JSON"
            raise RuntimeError(msg) from error

        output = DirectorOutput.model_validate(parsed)
        log_event(
            "DEBUG",
            "DirectorAgent",
            "run_complete",
            message="Director returned a script payload that passed model validation.",
            job_id=input.job_id,
            act_count=len(output.acts),
            title=output.title,
        )
        return output

    def get_last_usage(self) -> DirectorUsage:
        """Return token usage metadata from the latest ``run`` call.

        Returns:
            ``DirectorUsage`` for the latest invocation.
        """
        log_event(
            "DEBUG",
            "DirectorAgent",
            "get_last_usage",
            message="Returning token usage from the latest Director run.",
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
            "DirectorAgent",
            "get_last_prompt",
            message="Returning the latest prompt sent to the Director model.",
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
            "DirectorAgent",
            "get_last_response_text",
            message="Returning the latest raw response from the Director model.",
            response_length=len(self._last_response_text),
        )
        return self._last_response_text

    def build_prompt(
        self,
        input: DirectorInput,
        validation_errors: list[str] | None = None,
    ) -> str:
        """Build the exact prompt text that will be sent to the Director model.

        Args:
            input: Director input data.
            validation_errors: Optional previous validation errors.

        Returns:
            Final prompt string for the model call.
        """
        return self._build_prompt(input=input, validation_errors=validation_errors)

    def _build_prompt(
        self,
        input: DirectorInput,
        validation_errors: list[str] | None,
    ) -> str:
        """Build a deterministic prompt from template placeholders.

        Args:
            input: Director input data.
            validation_errors: Optional previous validation errors.

        Returns:
            Final prompt string for the model call.

        Raises:
            ValueError: If required placeholders are missing.
        """
        log_event(
            "DEBUG",
            "DirectorAgent",
            "build_prompt_start",
            message="Building the Director prompt from the template and inputs.",
            job_id=input.job_id,
            has_validation_errors=validation_errors is not None,
        )
        required_placeholders = (
            "{rag_context}",
            "{prompt}",
            "{preferred_obstacle_library_names}",
            "{min_obstacle_acts}",
            "{max_obstacle_acts}",
            "{min_choices_per_act}",
            "{max_choices_per_act}",
            "{max_title_length_chars}",
            "{max_description_length_chars}",
            "{max_choice_label_length_chars}",
        )
        if any(placeholder not in self._prompt_template for placeholder in required_placeholders):
            msg = (
                "Director prompt template must include {rag_context}, {prompt}, "
                "{preferred_obstacle_library_names}, {min_obstacle_acts}, "
                "{max_obstacle_acts}, {min_choices_per_act}, {max_choices_per_act}, "
                "{max_title_length_chars}, {max_description_length_chars}, and "
                "{max_choice_label_length_chars} placeholders"
            )
            raise ValueError(msg)

        prompt = (
            self._prompt_template.replace("{rag_context}", input.rag_context)
            .replace("{prompt}", input.prompt)
            .replace(
                "{preferred_obstacle_library_names}",
                ", ".join(input.preferred_obstacle_library_names),
            )
            .replace("{min_obstacle_acts}", str(config.MIN_OBSTACLE_ACTS))
            .replace("{max_obstacle_acts}", str(config.MAX_OBSTACLE_ACTS))
            .replace("{min_choices_per_act}", str(config.MIN_CHOICES_PER_ACT))
            .replace("{max_choices_per_act}", str(config.MAX_CHOICES_PER_ACT))
            .replace("{max_title_length_chars}", str(config.MAX_TITLE_LENGTH_CHARS))
            .replace(
                "{max_description_length_chars}",
                str(config.MAX_DESCRIPTION_LENGTH_CHARS),
            )
            .replace(
                "{max_choice_label_length_chars}",
                str(config.MAX_CHOICE_LABEL_LENGTH_CHARS),
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
            "DirectorAgent",
            "build_prompt_complete",
            message="Finished assembling the Director prompt text.",
            job_id=input.job_id,
            prompt_length=len(prompt),
        )
        return prompt

    def _invoke_model(self, prompt: str, *, job_id: str) -> tuple[str, DirectorUsage]:
        """Invoke the configured model client and extract response text + usage.

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
            "DirectorAgent",
            "invoke_model_start",
            message="Calling the Bedrock Director model.",
            job_id=job_id,
            model_id=self._model_id,
            prompt_length=len(prompt),
            has_model_client=self._model_client is not None,
        )
        if self._model_client is None:
            msg = "DirectorAgent requires a model_client for runtime invocation"
            raise RuntimeError(msg)

        response = self._model_client.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": config.MAX_OUTPUT_TOKENS_DIRECTOR_STAGE,
                "temperature": 0.2,
            },
        )

        try:
            text = response["output"]["message"]["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as error:
            msg = "Director model response missing output.message.content[0].text"
            raise RuntimeError(msg) from error

        usage_raw = response.get("usage", {})
        usage = DirectorUsage(
            input_tokens=int(usage_raw.get("inputTokens", 0)),
            output_tokens=int(usage_raw.get("outputTokens", 0)),
        )

        log_event(
            "DEBUG",
            "DirectorAgent",
            "invoke_model_complete",
            message="Received a response from the Bedrock Director model.",
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
            "DirectorAgent",
            "parse_json_object_start",
            message="Parsing a JSON object from the Director response text.",
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
                "DirectorAgent",
                "parse_json_object_failed_non_object_root",
                message="Director returned JSON with a non-object root value.",
                job_id=job_id,
                root_type=type(parsed).__name__,
            )
            msg = "Director JSON root must be an object"
            raise RuntimeError(msg)
        log_event(
            "DEBUG",
            "DirectorAgent",
            "parse_json_object_complete",
            message="Parsed a JSON object from the Director response text.",
            job_id=job_id,
            key_count=len(parsed),
        )
        return parsed
