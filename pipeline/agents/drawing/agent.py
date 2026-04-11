"""Drawing agent implementation for Phase 5 obstacle and background generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline import config
from pipeline.models import DrawingInput, DrawingOutput
from pipeline.shared.logging import log_event


@dataclass
class DrawingUsage:
    """Token usage metadata extracted from the Drawing model response."""

    input_tokens: int
    output_tokens: int


class DrawingAgent:
    """Generate a standalone SVG from a Director-provided drawing prompt.

    Supports obstacle and background drawing types, each with its own
    system prompt. The user message is the Director's ``drawing_prompt``.

    Args:
        model_client: Optional Bedrock runtime-like client. Must expose
            ``converse(...)`` when provided.
        model_id: Bedrock model identifier used for generation.

    Raises:
        RuntimeError: If no model client is configured or response shape
            is invalid.
    """

    _OBSTACLE_SYSTEM_PROMPT = (
        "You are an expert SVG illustrator. When asked to draw something:\n"
        "- Output only raw SVG markup, no explanation, no markdown fences\n"
        "- Use viewBox='0 0 120 150'\n"
        "- Set id='obstacle-root' on the root <svg>\n"
        "- Put the full obstacle illustration inside <g id='obstacle-main'>\n"
        "- Put one clearly visible self-contained animated detail inside "
        "<g id='obstacle-animated-part'>\n"
        "- obstacle-animated-part must include inline SVG animation, ideally "
        "<animateTransform type='rotate'>, so every obstacle visibly idles\n"
        "- The animated detail must stay readable at player size; do not hide it "
        "inside tiny or fully covered shapes\n"
        "- Use hardcoded hex colors for physical scenes\n"
        "- Layer overlapping opaque shapes to create depth\n"
        "- Keep proportions plausible but artistic, not strictly to scale\n"
        "- Use <path>, <ellipse>, <polygon> for organic forms\n"
        "- Include fine details: highlights, shadows via darker fills, "
        "texture via repeated shapes\n"
        "- Keep the SVG background transparent at all times\n"
        "- Do not draw sky, ground, horizon, glow panels, or any full-canvas backdrop\n"
        "- Negative space around the obstacle must remain empty so the renderer can "
        "place it over a scene background\n"
        "- Fill the canvas richly — avoid sparse compositions\n"
        "- Your response must be only <svg> and nothing else\n"
        "- All coordinates must stay within the viewBox bounds\n"
        "- If the obstacle depicts a character, person, or creature that stands on "
        "the ground, position their feet near the bottom of the viewBox (y around 120-150) "
        "so they appear grounded in the scene"
    )

    _BACKGROUND_SYSTEM_PROMPT = (
        "You are an expert SVG illustrator specializing in "
        "full-canvas backgrounds.\n"
        "- Output only raw SVG markup, no explanation, no markdown fences\n"
        "- Use viewBox='0 0 800 200'\n"
        "- Set id='background-root' on the root <svg>\n"
        "- Put the full scene inside <g id='background-main'>\n"
        "- Put 4-6 clearly visible ambient details inside "
        "<g id='background-animated-part'>\n"
        "- background-animated-part must contain inline SVG animation so every "
        "background has unmistakable life in the player\n"
        "- Use hardcoded hex colors\n"
        "- Layer overlapping opaque shapes to create depth and atmosphere\n"
        "- Fill the entire canvas — no empty space\n"
        "- Animations must only use opacity and fill changes "
        "— no translate, rotate, or scale\n"
        "- Use <animate attributeName='opacity'> and "
        "<animate attributeName='fill'> only\n"
        "- Make the animation contrast readable from a distance: opacity pulses "
        "should usually swing across a broad range such as 0.2-1.0, and fill "
        "changes should visibly shift brightness or color temperature\n"
        "- Keep the animated details readable at full-scene scale; do not hide "
        "all motion in barely visible micro-elements or only one tiny corner\n"
        "- Your response must be only <svg> and nothing else\n"
        "- All coordinates must stay within the viewBox bounds"
    )

    def __init__(
        self,
        model_client: Any | None = None,
        model_id: str = config.BEDROCK_MODEL_ID_DRAWING,
    ) -> None:
        """Initialise the Drawing agent.

        Args:
            model_client: Optional external model client, primarily for tests.
            model_id: Bedrock model identifier.
        """
        self._model_client = model_client
        self._model_id = model_id
        self._last_usage = DrawingUsage(input_tokens=0, output_tokens=0)
        self._last_prompt = ""
        self._last_response_text = ""
        log_event(
            "DEBUG",
            "DrawingAgent",
            "init_complete",
            message="Initialised the Drawing agent runtime settings.",
            has_model_client=model_client is not None,
            model_id=model_id,
        )

    def spawn_parallel_worker(self) -> DrawingAgent:
        """Return a fresh Drawing agent configured like this one.

        A fresh instance keeps prompt, usage, and raw-response bookkeeping
        isolated so multiple Drawing model calls can run in parallel safely.
        """
        return DrawingAgent(
            model_client=self._model_client,
            model_id=self._model_id,
        )

    def run(
        self,
        input: DrawingInput,
        validation_errors: list[str] | None = None,
    ) -> DrawingOutput:
        """Run the Drawing model and return the generated SVG payload.

        Args:
            input: Typed drawing input payload.
            validation_errors: Optional validator errors from the previous attempt.

        Returns:
            ``DrawingOutput`` containing one standalone SVG.
        """
        log_event(
            "DEBUG",
            "DrawingAgent",
            "run_start",
            message="Starting a Drawing agent run for the current job.",
            job_id=input.job_id,
            session_id=input.session_id,
            obstacle_type=input.obstacle_type,
            drawing_type=input.drawing_type,
            has_validation_errors=validation_errors is not None,
        )
        prompt = self.build_prompt(input=input, validation_errors=validation_errors)
        self._last_prompt = prompt
        response_text, usage = self._invoke_model(
            prompt=prompt,
            job_id=input.job_id,
            drawing_type=input.drawing_type,
        )
        self._last_response_text = response_text
        self._last_usage = usage

        output = DrawingOutput(svg=response_text.strip())
        log_event(
            "DEBUG",
            "DrawingAgent",
            "run_complete",
            message="Drawing agent returned an SVG payload.",
            job_id=input.job_id,
            obstacle_type=input.obstacle_type,
            drawing_type=input.drawing_type,
            svg_length=len(output.svg),
        )
        return output

    def get_last_usage(self) -> DrawingUsage:
        """Return token usage metadata from the latest ``run`` call.

        Returns:
            ``DrawingUsage`` for the latest invocation.
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
            Raw response text before any validation.
        """
        return self._last_response_text

    def build_prompt(
        self,
        input: DrawingInput,
        validation_errors: list[str] | None = None,
    ) -> str:
        """Build the exact prompt text that will be sent to the Drawing model.

        Args:
            input: Drawing input data.
            validation_errors: Optional previous validation errors.

        Returns:
            Final prompt string for the model call.
        """
        return self._build_prompt(input=input, validation_errors=validation_errors)

    def _build_prompt(
        self,
        input: DrawingInput,
        validation_errors: list[str] | None,
    ) -> str:
        """Build a prompt from the Director's drawing_prompt plus any errors.

        Args:
            input: Drawing input data.
            validation_errors: Optional previous validation errors.

        Returns:
            Final prompt string for the model call.
        """
        prompt = input.drawing_prompt

        if validation_errors:
            error_block = "\n".join(f"- {error}" for error in validation_errors)
            prompt += (
                "\n\nPrevious attempt failed deterministic validation. "
                "You MUST fix these exact errors:\n"
                f"{error_block}\n"
            )

        log_event(
            "DEBUG",
            "DrawingAgent",
            "build_prompt_complete",
            message="Finished assembling the Drawing prompt text.",
            job_id=input.job_id,
            prompt_length=len(prompt),
        )
        return prompt

    def _get_system_prompt(self, drawing_type: str) -> str:
        """Select the system prompt based on drawing type.

        Args:
            drawing_type: Either ``"obstacle"`` or ``"background"``.

        Returns:
            System prompt string appropriate for the drawing type.
        """
        if drawing_type == "background":
            return self._BACKGROUND_SYSTEM_PROMPT
        return self._OBSTACLE_SYSTEM_PROMPT

    def _invoke_model(
        self,
        prompt: str,
        *,
        job_id: str,
        drawing_type: str,
    ) -> tuple[str, DrawingUsage]:
        """Invoke the configured model client and extract response text plus usage.

        Args:
            prompt: Prompt text to send.
            job_id: Current generation job identifier for logging context.
            drawing_type: Either ``"obstacle"`` or ``"background"``.

        Returns:
            Tuple of ``(response_text, usage)``.

        Raises:
            RuntimeError: If no model client is configured or response shape
                is invalid.
        """
        log_event(
            "DEBUG",
            "DrawingAgent",
            "invoke_model_start",
            message="Calling the Bedrock Drawing model.",
            job_id=job_id,
            model_id=self._model_id,
            prompt_length=len(prompt),
            drawing_type=drawing_type,
            has_model_client=self._model_client is not None,
        )
        if self._model_client is None:
            msg = "DrawingAgent requires a model_client for runtime invocation"
            raise RuntimeError(msg)

        response = self._model_client.converse(
            modelId=self._model_id,
            system=[{"text": self._get_system_prompt(drawing_type)}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": config.MAX_OUTPUT_TOKENS_DRAWING_STAGE,
                "temperature": config.DRAWING_TEMPERATURE,
            },
        )

        try:
            text = response["output"]["message"]["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as error:
            msg = "Drawing model response missing output.message.content[0].text"
            raise RuntimeError(msg) from error

        usage_raw = response.get("usage", {})
        usage = DrawingUsage(
            input_tokens=int(usage_raw.get("inputTokens", 0)),
            output_tokens=int(usage_raw.get("outputTokens", 0)),
        )
        log_event(
            "DEBUG",
            "DrawingAgent",
            "invoke_model_complete",
            message="Received a response from the Bedrock Drawing model.",
            job_id=job_id,
            model_id=self._model_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            response_length=len(text),
        )
        return text, usage
