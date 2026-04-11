"""Deterministic validation for Director agent output.

This is a pure stateless function — no class, no side effects, no I/O.
Returns ``ValidationResult`` for domain failures; raises for programmer errors.
See DESIGN.md §6.2 for the complete contract and STANDARDS.md §3.2 for the
validator pattern.
"""

from __future__ import annotations

import re

from pipeline import config
from pipeline.models import OBSTACLE_SLUG_PATTERN, DirectorOutput, ValidationResult

_OBSTACLE_SLUG_RE = re.compile(OBSTACLE_SLUG_PATTERN)


def _build_range_error(
    *,
    field_label: str,
    actual_count: int,
    min_count: int,
    max_count: int,
) -> str | None:
    """Return a config-driven count-range error message when a count is invalid.

    Args:
        field_label: Human-readable field label used in the error message.
        actual_count: Count observed in the script.
        min_count: Inclusive minimum from config.
        max_count: Inclusive maximum from config.

    Returns:
        Error message when out of bounds, otherwise ``None``.
    """
    if min_count <= actual_count <= max_count:
        return None
    return (
        f"{field_label} must be between {min_count} and {max_count}; "
        f"got {actual_count}"
    )


def validate_script(
    script: DirectorOutput,
    *,
    preferred_obstacle_library_names: list[str] | None = None,
) -> ValidationResult:
    """Validate Director output against all rules defined in DESIGN.md §6.2.

    Checks every rule and collects all failures rather than stopping at the
    first error.  The full errors list is included in the retry prompt so the
    Director agent can fix all issues in one pass.

    Rules checked (in order):
    - Act count is between ``MIN_OBSTACLE_ACTS`` and ``MAX_OBSTACLE_ACTS`` (inclusive).
    - Episode title is ≤ 60 characters.
    - Episode description is ≤ 120 characters.
    - Each act's obstacle type is a non-empty slug matching the shared pattern.
    - No duplicate ``act_index`` values across acts.
    - Each act has between ``MIN_CHOICES_PER_ACT`` and ``MAX_CHOICES_PER_ACT`` choices (inclusive).
    - Each act has exactly one choice with ``is_winning=True``.
    - Every choice label is ≤ 40 characters.
    - ``act_index`` values are 0-based, sequential, and contiguous (no gaps).
    - Non-library obstacles must have ``drawing_prompt`` ≥ 50 characters.
    - Every act must have ``background_drawing_prompt`` ≥ 50 characters.

    Args:
        script: The ``DirectorOutput`` to validate.
        preferred_obstacle_library_names: Obstacle slugs with pre-authored SVGs.

    Returns:
        ``ValidationResult`` with ``is_valid=True`` and empty errors on success,
        or ``is_valid=False`` with all failed rules listed in ``errors``.

    Raises:
        TypeError: If ``script`` is ``None`` (programmer error — orchestrator
            must never pass None here).
    """
    if script is None:
        msg = "script cannot be None"
        raise TypeError(msg)

    errors: list[str] = []
    act_count = len(script.acts)
    _library_names = set(preferred_obstacle_library_names or [])

    # Rule: episode must have between MIN_OBSTACLE_ACTS and MAX_OBSTACLE_ACTS acts.
    act_count_error = _build_range_error(
        field_label="acts count",
        actual_count=act_count,
        min_count=config.MIN_OBSTACLE_ACTS,
        max_count=config.MAX_OBSTACLE_ACTS,
    )
    if act_count_error is not None:
        errors.append(act_count_error)

    # Rule: episode title must be ≤ MAX_TITLE_LENGTH_CHARS.
    if len(script.title) > config.MAX_TITLE_LENGTH_CHARS:
        errors.append(
            f"title must be {config.MAX_TITLE_LENGTH_CHARS} characters or fewer"
        )

    # Rule: episode description must be ≤ MAX_DESCRIPTION_LENGTH_CHARS.
    if len(script.description) > config.MAX_DESCRIPTION_LENGTH_CHARS:
        errors.append(
            f"description must be {config.MAX_DESCRIPTION_LENGTH_CHARS} characters or fewer"
        )

    seen_indices: set[int] = set()
    sorted_indices: list[int] = []

    for act in script.acts:
        sorted_indices.append(act.act_index)

        # Rule: obstacle_type must be a lowercase slug so it can be used for
        # obstacle library lookup and Drawing-agent cache keys.
        if not _OBSTACLE_SLUG_RE.fullmatch(act.obstacle_type):
            errors.append(
                f"act {act.act_index} has invalid obstacle_type slug: {act.obstacle_type}"
            )

        # Rule: act_index values must be unique (no duplicates).
        if act.act_index in seen_indices:
            errors.append(f"duplicate act_index found: {act.act_index}")
        seen_indices.add(act.act_index)

        # Rule: each act must have between MIN_CHOICES_PER_ACT and MAX_CHOICES_PER_ACT choices.
        choices_count = len(act.choices)
        choice_count_error = _build_range_error(
            field_label=f"act {act.act_index} choices count",
            actual_count=choices_count,
            min_count=config.MIN_CHOICES_PER_ACT,
            max_count=config.MAX_CHOICES_PER_ACT,
        )
        if choice_count_error is not None:
            errors.append(choice_count_error)

        # Rule: exactly one choice per act must be the winning choice.
        winner_count = sum(1 for choice in act.choices if choice.is_winning)
        if winner_count != 1:
            errors.append(f"act {act.act_index} must have exactly one winning choice")

        # Rule: every choice label must be ≤ MAX_CHOICE_LABEL_LENGTH_CHARS.
        for choice_index, choice in enumerate(act.choices):
            if len(choice.label) > config.MAX_CHOICE_LABEL_LENGTH_CHARS:
                errors.append(
                    f"act {act.act_index} choice {choice_index} label must be "
                    f"{config.MAX_CHOICE_LABEL_LENGTH_CHARS} characters or fewer"
                )

        # Rule: non-library obstacles must provide a drawing_prompt.
        is_library_obstacle = act.obstacle_type in _library_names
        if not is_library_obstacle and act.drawing_prompt is None:
            errors.append(
                f"act {act.act_index} obstacle_type '{act.obstacle_type}' is not in the "
                "pre-authored library; drawing_prompt is required"
            )

        # Rule: drawing_prompt, when present, must be at least 50 characters.
        if act.drawing_prompt is not None and len(act.drawing_prompt) < 50:
            errors.append(
                f"act {act.act_index} drawing_prompt must be at least 50 characters; "
                f"got {len(act.drawing_prompt)}"
            )

        # Rule: background_drawing_prompt must be at least 50 characters.
        if len(act.background_drawing_prompt) < 50:
            errors.append(
                f"act {act.act_index} background_drawing_prompt must be at least "
                f"50 characters; got {len(act.background_drawing_prompt)}"
            )

    # Rule: act_index values must be 0-based, sequential, and contiguous.
    # e.g. [0, 1, 2] is valid; [0, 2] or [1, 2, 3] are not.
    expected_indices = list(range(len(script.acts)))
    if sorted(sorted_indices) != expected_indices:
        errors.append("act_index values must be sequential and 0-based starting at 0 with no gaps")

    return ValidationResult(is_valid=len(errors) == 0, errors=errors)
