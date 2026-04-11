"""Deterministic validation for Animator agent output.

This is a pure stateless function — no class, no side effects, no I/O.
Returns ``ValidationResult`` for domain failures; raises for programmer errors.
See DESIGN.md §6.3 for the complete contract and STANDARDS.md §3.2 for the
validator pattern.
"""

from __future__ import annotations

from collections import Counter

from pipeline import config
from pipeline.media.linai_template import get_linai_part_ids
from pipeline.models import AnimatorInput, AnimatorOutput, ValidationResult


def validate_frames(
    frames: AnimatorOutput,
    animator_input: AnimatorInput,
    act_indices_to_validate: set[int] | None = None,
) -> ValidationResult:
    """Validate Animator output against all rules defined in DESIGN.md §6.3.

    Checks every rule and collects all failures rather than stopping at the
    first error.  The full errors list is included in the retry prompt so the
    Animator agent can fix all issues in one pass.

    Rules checked per clip:
    - ``duration_ms`` is > 0.
    - ``duration_ms`` is ≤ ``MAX_EPISODE_DURATION_SECONDS * 1000``.
    - ``obstacle_x`` is within ``[50, canvas_width - 50]``.
    - Grounded approach clips may end close to the obstacle, but must still
      read as "blocked before the choice" rather than already past it.

    Rules checked per keyframe within a clip:
    - ``character_x`` is within ``[0, canvas_width]``.
    - ``character_y`` is within ``[0, canvas_height]``.
    - ``character_y`` keeps enough top headroom for Linai to remain fully in frame.
    - ``support_y`` is within ``[0, canvas_height]``.
    - Grounded keyframes keep ``character_y`` on or near ``support_y`` within
      ``SUPPORT_Y_TOLERANCE_PX``.
    - ``is_handoff_pose`` may only appear on later-act approach entry keyframes.
    - Handoff poses must also be grounded.
    - Handoff poses keep ``character_y`` on or near ``support_y`` within
      ``HANDOFF_SUPPORT_Y_TOLERANCE_PX``.
    - Handoff poses must keep ``character_x`` near ``handoff_character_x`` within
      ``HANDOFF_X_TOLERANCE_PX``.
    - ``time_ms`` is ≥ 0.
    - ``time_ms`` values are strictly increasing within the clip.

    Rules checked per act (cross-clip structure):
    - Each act has exactly one approach clip.
    - Each winning choice has exactly one win clip and no fail clip.
    - Each losing choice has exactly one fail clip and no win clip.

    Args:
        frames: The ``AnimatorOutput`` to validate.
        animator_input: The ``AnimatorInput`` that produced this output; provides
            canvas dimensions, baseline ground line Y, and the act/choice structure.
        act_indices_to_validate: Optional subset of act indexes to validate. Use
            this when validating one act output against the full episode act list.

    Returns:
        ``ValidationResult`` with ``is_valid=True`` and empty errors on success,
        or ``is_valid=False`` with all failed rules listed in ``errors``.

    Raises:
        TypeError: If either ``frames`` or ``animator_input`` is ``None``
            (programmer error — orchestrator must never pass None here).
    """
    if frames is None:
        msg = "frames cannot be None"
        raise TypeError(msg)
    if animator_input is None:
        msg = "animator_input cannot be None"
        raise TypeError(msg)

    errors: list[str] = []
    acts_by_index = {act.act_index: act for act in animator_input.acts}
    valid_linai_part_ids = set(get_linai_part_ids())
    first_act_index = animator_input.acts[0].act_index if animator_input.acts else 0
    act_indices = (
        act_indices_to_validate
        if act_indices_to_validate is not None
        else {act.act_index for act in animator_input.acts}
    )

    for clip in frames.clips:
        if clip.act_index not in act_indices and clip.act_index in acts_by_index:
            continue
        act = acts_by_index.get(clip.act_index)

        # Rule: every clip must point at a real Director act. The Animator is
        # only allowed to choreograph acts that exist in the script.
        if act is None:
            errors.append(f"clip references unknown act_index: {clip.act_index}")
            continue

        # Rule: every clip must carry forward the owning act's obstacle slug
        # exactly so downstream obstacle resolution uses one stable key.
        if clip.obstacle_type != act.obstacle_type:
            errors.append(
                f"clip act {clip.act_index} obstacle_type must match act obstacle_type: "
                f"{clip.obstacle_type}"
            )

        # Rule: each clip must have a positive duration.
        if clip.duration_ms <= 0:
            errors.append(f"clip act {clip.act_index} has non-positive duration_ms")

        # Rule: no single clip may exceed the maximum total episode duration.
        if clip.duration_ms > config.MAX_EPISODE_DURATION_SECONDS * 1000:
            errors.append(
                f"clip act {clip.act_index} duration_ms exceeds "
                f"{config.MAX_EPISODE_DURATION_SECONDS * 1000}"
            )

        # Rule: obstacle must be placed at least 50px from each canvas edge
        # so it is always fully visible and not clipped.
        if clip.obstacle_x < 50 or clip.obstacle_x > animator_input.canvas_width - 50:
            errors.append(f"clip act {clip.act_index} obstacle_x out of bounds: {clip.obstacle_x}")

        # Rule: every clip needs at least two keyframes so the Renderer has a
        # start pose and an end pose to interpolate between.
        if len(clip.keyframes) < 2:
            errors.append(f"clip act {clip.act_index} must contain at least 2 keyframes")

        # Rule: approach clips are the walk-up before a choice exists, so they
        # must not be tied to any specific choice index.
        if clip.branch == "approach" and clip.choice_index is not None:
            errors.append(f"clip act {clip.act_index} approach clip must use choice_index null")

        # Rule: an approach clip should still read as blocked by the obstacle
        # when the player is asked to choose. Linai may settle close to it, but
        # if the final grounded pose lands too far right for the fixed staging
        # the scene reads as if she already crossed before the choice.
        final_keyframe = clip.keyframes[-1] if clip.keyframes else None
        max_grounded_approach_x = min(
            clip.obstacle_x - config.APPROACH_OBSTACLE_CLEARANCE_PX,
            config.MAX_GROUNDED_APPROACH_CHARACTER_X,
        )
        if (
            clip.branch == "approach"
            and final_keyframe is not None
            and final_keyframe.is_grounded
            and final_keyframe.character_x > max_grounded_approach_x
        ):
            errors.append(
                f"clip act {clip.act_index} final grounded approach character_x must stay at "
                f"or before x={max_grounded_approach_x} so Linai stops close to, but not past, "
                f"the obstacle: "
                f"{final_keyframe.character_x}"
            )

        # Rule: win/fail clips resolve a specific choice, so they must always
        # point at one concrete choice index within the act's choice list.
        if clip.branch in {"win", "fail"}:
            if clip.choice_index is None:
                errors.append(
                    f"clip act {clip.act_index} {clip.branch} clip must include choice_index"
                )
            elif clip.choice_index < 0 or clip.choice_index >= len(act.choices):
                errors.append(
                    f"clip act {clip.act_index} has invalid choice_index: {clip.choice_index}"
                )

        previous_time: int | None = None
        for keyframe_index, keyframe in enumerate(clip.keyframes):
            # Rule: character must remain within the horizontal canvas bounds.
            if keyframe.character_x < 0 or keyframe.character_x > animator_input.canvas_width:
                errors.append(
                    f"clip act {clip.act_index} has keyframe character_x out of bounds: "
                    f"{keyframe.character_x}"
                )

            # Rule: the character anchor point must stay within the scene.
            if keyframe.character_y < 0 or keyframe.character_y > animator_input.canvas_height:
                errors.append(
                    f"clip act {clip.act_index} has keyframe character_y out of bounds: "
                    f"{keyframe.character_y}"
                )

            # Rule: the character anchor point also needs enough top headroom
            # for the full cloud silhouette and vapor trails to stay visible
            # during upward motion beats.
            if keyframe.character_y < config.MIN_CHARACTER_Y_IN_FRAME_PX:
                errors.append(
                    f"clip act {clip.act_index} keyframe {keyframe.time_ms} character_y "
                    f"must be at least {config.MIN_CHARACTER_Y_IN_FRAME_PX} to keep "
                    f"Linai in frame: {keyframe.character_y}"
                )

            # Rule: the support line under Linai can move for ramps, platforms,
            # and elevated paths, but it must still remain inside the canvas.
            if keyframe.support_y < 0 or keyframe.support_y > animator_input.canvas_height:
                errors.append(
                    f"clip act {clip.act_index} has keyframe support_y out of bounds: "
                    f"{keyframe.support_y}"
                )

            # Rule: grounded poses keep Linai's root anchored near the local
            # support line. Airborne and falling poses may move above or below it.
            tolerance = config.SUPPORT_Y_TOLERANCE_PX
            if keyframe.is_grounded and abs(keyframe.character_y - keyframe.support_y) > tolerance:
                errors.append(
                    f"clip act {clip.act_index} has grounded keyframe character_y outside "
                    f"support_y±{config.SUPPORT_Y_TOLERANCE_PX}: "
                    f"{keyframe.character_y}!={keyframe.support_y}"
                )

            is_first_approach_keyframe = (
                clip.branch == "approach"
                and keyframe_index == 0
                and clip.act_index != first_act_index
            )
            is_valid_handoff_slot = is_first_approach_keyframe

            # Rule: handoff poses are reserved for act boundaries only.
            if keyframe.is_handoff_pose and not is_valid_handoff_slot:
                errors.append(
                    f"clip act {clip.act_index} keyframe {keyframe.time_ms} must not set "
                    "is_handoff_pose outside an act boundary"
                )

            # Rule: a handoff pose must be stable and grounded.
            if keyframe.is_handoff_pose and not keyframe.is_grounded:
                errors.append(
                    f"clip act {clip.act_index} keyframe {keyframe.time_ms} handoff pose "
                    "must be grounded"
                )

            # Rule: handoff poses must also stay vertically anchored near the
            # support line so separately generated acts do not pop on entry/exit.
            handoff_y_tolerance = config.HANDOFF_SUPPORT_Y_TOLERANCE_PX
            if (
                keyframe.is_handoff_pose
                and abs(keyframe.character_y - keyframe.support_y) > handoff_y_tolerance
            ):
                errors.append(
                    f"clip act {clip.act_index} keyframe {keyframe.time_ms} handoff pose "
                    f"character_y must be within {config.HANDOFF_SUPPORT_Y_TOLERANCE_PX}px of "
                    f"support_y {keyframe.support_y}: {keyframe.character_y}"
                )

            # Rule: every act-boundary handoff pose must land at one canonical
            # x-position so separately generated acts can stitch cleanly.
            x_tolerance = config.HANDOFF_X_TOLERANCE_PX
            if (
                keyframe.is_handoff_pose
                and abs(keyframe.character_x - animator_input.handoff_character_x) > x_tolerance
            ):
                errors.append(
                    f"clip act {clip.act_index} keyframe {keyframe.time_ms} handoff pose "
                    f"character_x must be within {config.HANDOFF_X_TOLERANCE_PX}px of "
                    f"handoff_character_x {animator_input.handoff_character_x}: "
                    f"{keyframe.character_x}"
                )

            # Rule: keyframe timestamps must be non-negative.
            if keyframe.time_ms < 0:
                errors.append(
                    f"clip act {clip.act_index} has negative keyframe time_ms: {keyframe.time_ms}"
                )

            # Rule: keyframe timestamps must be strictly increasing within a clip
            # so that SVG animations interpolate correctly.
            if previous_time is not None and keyframe.time_ms <= previous_time:
                errors.append(
                    f"clip act {clip.act_index} keyframe times must be strictly increasing"
                )
            previous_time = keyframe.time_ms

            seen_target_ids: set[str] = set()
            for part_note in keyframe.part_notes:
                # Rule: part notes may only target real ids from the canonical
                # Linai template so the Renderer never receives impossible ids.
                if part_note.target_id not in valid_linai_part_ids:
                    errors.append(
                        f"clip act {clip.act_index} keyframe {keyframe.time_ms} uses unknown "
                        f"part_notes target_id: {part_note.target_id}"
                    )

                # Rule: a single keyframe may describe each target id at most
                # once to avoid conflicting instructions for one SVG part.
                if part_note.target_id in seen_target_ids:
                    errors.append(
                        f"clip act {clip.act_index} keyframe {keyframe.time_ms} has duplicate "
                        f"part_notes target_id: {part_note.target_id}"
                    )
                seen_target_ids.add(part_note.target_id)

    for act in animator_input.acts:
        if act.act_index not in act_indices:
            continue
        clips_for_act = [clip for clip in frames.clips if clip.act_index == act.act_index]

        # Rule: each act must have exactly one approach clip (the walk-up animation).
        approach_clips = [clip for clip in clips_for_act if clip.branch == "approach"]
        if len(approach_clips) != 1:
            errors.append(f"act {act.act_index} must contain exactly one approach clip")
        elif (
            act.act_index != first_act_index and not approach_clips[0].keyframes[0].is_handoff_pose
        ):
            errors.append(
                f"act {act.act_index} approach clip must start with exactly one handoff pose"
            )

        # Count win and fail clips per (choice_index, branch) pair.
        branch_counter: Counter[tuple[int, str]] = Counter()
        for clip in clips_for_act:
            if (
                clip.branch in {"win", "fail"}
                and clip.choice_index is not None
                and 0 <= clip.choice_index < len(act.choices)
            ):
                branch_counter[(clip.choice_index, clip.branch)] += 1

        # Rule: each choice resolves to exactly one branch. Winners get one
        # win clip and no fail clip; losers get one fail clip and no win clip.
        for choice_index, choice in enumerate(act.choices):
            expected_branch = "win" if choice.is_winning else "fail"
            opposite_branch = "fail" if choice.is_winning else "win"
            if branch_counter[(choice_index, expected_branch)] != 1:
                errors.append(
                    f"act {act.act_index} choice {choice_index} must contain exactly one "
                    f"{expected_branch} clip"
                )
            if branch_counter[(choice_index, opposite_branch)] != 0:
                errors.append(
                    f"act {act.act_index} choice {choice_index} must not contain a "
                    f"{opposite_branch} clip"
                )

    return ValidationResult(is_valid=len(errors) == 0, errors=errors)
