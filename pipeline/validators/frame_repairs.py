"""Deterministic repair helpers for known Animator frame drift."""

from __future__ import annotations

from pipeline.models import AnimatorOutput, ClipManifest, Keyframe


def repair_animator_keyframe_bounds(
    output: AnimatorOutput,
    *,
    canvas_width: int,
    canvas_height: int,
) -> AnimatorOutput:
    """Clamp out-of-range keyframe coordinates to stay inside the scene canvas.

    The model occasionally generates ``character_y`` or ``support_y`` values
    that drift just below ``canvas_height``. This clamps each coordinate rather
    than triggering a full model retry.

    For grounded keyframes the clamped ``character_y`` and ``support_y`` are
    set to the same value so the grounded-proximity check still passes.

    Args:
        output: Animator output that may contain out-of-bounds keyframes.
        canvas_width: Scene canvas width in pixels.
        canvas_height: Scene canvas height in pixels.

    Returns:
        New ``AnimatorOutput`` with all keyframe coordinates clamped.
    """
    new_clips: list[ClipManifest] = []
    for clip in output.clips:
        new_keyframes: list[Keyframe] = []
        clip_changed = False
        for kf in clip.keyframes:
            new_char_x = max(0.0, min(float(canvas_width), kf.character_x))
            new_char_y = max(0.0, min(float(canvas_height), kf.character_y))
            new_sup_y = max(0.0, min(float(canvas_height), kf.support_y))
            # Keep grounded frames consistent: if character_y was clamped and
            # the keyframe is grounded, pull support_y to match so the
            # proximity check still passes.
            if kf.is_grounded and new_char_y != kf.character_y:
                new_sup_y = new_char_y
            changed = (
                new_char_x != kf.character_x
                or new_char_y != kf.character_y
                or new_sup_y != kf.support_y
            )
            if changed:
                clip_changed = True
                new_keyframes.append(
                    kf.model_copy(
                        update={
                            "character_x": new_char_x,
                            "character_y": new_char_y,
                            "support_y": new_sup_y,
                        }
                    )
                )
            else:
                new_keyframes.append(kf)
        new_clips.append(
            clip.model_copy(update={"keyframes": new_keyframes}) if clip_changed else clip
        )
    return output.model_copy(update={"clips": new_clips})
