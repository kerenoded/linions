#!/usr/bin/env python3
# ruff: noqa: E402
"""Publish a locally-generated episode to the episodes/ folder.

Reads the renderer and director debug output produced by run-renderer-agent.py,
assembles episode.json and thumb.svg, writes them to episodes/<username>/<uuid>/,
and rebuilds episodes/index.json via build-index.js.

Usage:
    python scripts/publish-local.py tmp/renderer-agent/debug-director.json
    python scripts/publish-local.py tmp/renderer-agent/debug-director.json --username myuser
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config
from pipeline.media.thumbnail import extract_thumbnail
from pipeline.models import DirectorOutput, RendererOutput
from pipeline.models.episode import Episode
from pipeline.shared.published_episode import (
    validate_publish_path_segment,
    validate_published_episode_json,
)


def _try_command_stdout(command: list[str]) -> str:
    """Return stripped stdout for a best-effort shell command."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _get_publish_username() -> str:
    """Return the same publish username shape the local proxy uses."""
    gh_username = _try_command_stdout(["gh", "api", "user", "--jq", ".login"])
    if gh_username:
        return validate_publish_path_segment(gh_username, field_name="username")

    git_email = _try_command_stdout(["git", "config", "user.email"])
    at_index = git_email.find("@")
    if at_index > 0:
        return validate_publish_path_segment(git_email[:at_index], field_name="username")

    msg = (
        "Could not determine GitHub username. Authenticate `gh`, configure git user.email, "
        "or pass --username explicitly."
    )
    raise RuntimeError(msg)


def _compute_content_hash(episode_body: dict[str, Any]) -> str:
    """Compute SHA256 content hash matching the orchestrator algorithm."""
    hash_input = {**episode_body, "contentHash": None}
    serialised = json.dumps(hash_input, sort_keys=True, ensure_ascii=False)
    return f"sha256:{hashlib.sha256(serialised.encode('utf-8')).hexdigest()}"


def _clip_identity(
    act_index: int,
    branch: str,
    choice_index: int | None,
) -> tuple[int, str, int | None]:
    return act_index, branch, choice_index


def _build_publish_output_paths(
    *,
    output_root: Path,
    username: str,
    episode_uuid: str,
) -> tuple[Path, Path]:
    """Return the repo publication paths for episode.json and thumb.svg."""
    safe_username = validate_publish_path_segment(username, field_name="username")
    safe_uuid = validate_publish_path_segment(episode_uuid, field_name="uuid")
    output_dir = output_root / safe_username / safe_uuid
    return output_dir / "episode.json", output_dir / "thumb.svg"


def _ensure_publish_targets_are_new(*, episode_path: Path, thumb_path: Path) -> None:
    """Fail rather than silently overwrite an existing published episode."""
    existing_paths = [path for path in (episode_path, thumb_path) if path.exists()]
    if not existing_paths:
        return
    existing_list = ", ".join(str(path) for path in existing_paths)
    msg = f"Refusing to overwrite existing published artifact(s): {existing_list}"
    raise RuntimeError(msg)


def build_episode_json(
    *,
    username: str,
    episode_uuid: str,
    director_output: DirectorOutput,
    renderer_output: RendererOutput,
) -> str:
    """Assemble and serialise episode.json, mirroring the orchestrator payload builder."""
    clip_svgs = {
        _clip_identity(clip.act_index, clip.branch, clip.choice_index): clip.svg
        for clip in renderer_output.clips
    }

    acts_payload: list[dict[str, Any]] = []
    for act in director_output.acts:
        approach_clip = clip_svgs.get(_clip_identity(act.act_index, "approach", None))
        if approach_clip is None:
            msg = f"Missing approach clip for act {act.act_index}"
            raise RuntimeError(msg)

        choices_payload: list[dict[str, Any]] = []
        for choice_index, choice in enumerate(act.choices):
            win_clip = None
            fail_clip = None
            if choice.is_winning:
                win_clip = clip_svgs.get(_clip_identity(act.act_index, "win", choice_index))
                if win_clip is None:
                    msg = f"Missing win clip for act {act.act_index} choice {choice_index}"
                    raise RuntimeError(msg)
            else:
                fail_clip = clip_svgs.get(_clip_identity(act.act_index, "fail", choice_index))
                if fail_clip is None:
                    msg = f"Missing fail clip for act {act.act_index} choice {choice_index}"
                    raise RuntimeError(msg)

            choices_payload.append(
                {
                    "choiceIndex": choice_index,
                    "label": choice.label,
                    "isWinning": choice.is_winning,
                    "outcomeText": choice.outcome_description,
                    "winClip": win_clip,
                    "failClip": fail_clip,
                }
            )

        acts_payload.append(
            {
                "actIndex": act.act_index,
                "obstacleType": act.obstacle_type,
                "approachText": act.approach_description,
                "clips": {
                    "approach": approach_clip,
                    "choices": choices_payload,
                },
            }
        )

    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    episode_body: dict[str, Any] = {
        "schemaVersion": config.EPISODE_SCHEMA_VERSION,
        "uuid": episode_uuid,
        "username": username,
        "title": director_output.title,
        "description": director_output.description,
        "generatedAt": generated_at,
        "contentHash": None,
        "actCount": len(director_output.acts),
        "acts": acts_payload,
    }
    episode_body["contentHash"] = _compute_content_hash(episode_body)

    # Validate schema before writing.
    Episode.model_validate(episode_body)

    episode_json = json.dumps(episode_body, ensure_ascii=False, indent=2)
    size = len(episode_json.encode("utf-8"))
    if size > config.MAX_EPISODE_JSON_SIZE_BYTES:
        msg = f"Episode JSON size {size} exceeds max of {config.MAX_EPISODE_JSON_SIZE_BYTES} bytes"
        raise RuntimeError(msg)
    return episode_json


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish a locally-generated episode to episodes/.",
    )
    parser.add_argument(
        "renderer_output_path",
        help=(
            "Path to the renderer output JSON produced by run-renderer-agent.py "
            "(e.g. tmp/renderer-agent/debug-director.json). The prefix is used to locate the "
            "director output at tmp/director-agent/<prefix>.json."
        ),
    )
    parser.add_argument(
        "--username",
        default=None,
        help="Episode username (default: GitHub login, or git user.email local-part fallback).",
    )
    parser.add_argument(
        "--episode-uuid",
        default=None,
        help="Episode UUID (default: fresh uuid4).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "episodes"),
        help="Root episodes output directory (default: episodes/).",
    )
    args = parser.parse_args()

    prefix = Path(args.renderer_output_path).stem
    renderer_output_path = Path(args.renderer_output_path)
    if not renderer_output_path.is_absolute():
        renderer_output_path = PROJECT_ROOT / renderer_output_path
    director_output_path = PROJECT_ROOT / "tmp" / "director-agent" / f"{prefix}.json"

    if not renderer_output_path.exists():
        print(
            f"Renderer output not found: {renderer_output_path}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not director_output_path.exists():
        print(
            f"Director output not found: {director_output_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    renderer_output = RendererOutput.model_validate_json(
        renderer_output_path.read_text(encoding="utf-8")
    )
    director_output = DirectorOutput.model_validate_json(
        director_output_path.read_text(encoding="utf-8")
    )

    username = validate_publish_path_segment(
        args.username or _get_publish_username(),
        field_name="username",
    )
    episode_uuid = validate_publish_path_segment(
        args.episode_uuid or str(uuid.uuid4()),
        field_name="uuid",
    )

    print(f"Username:      {username}")
    print(f"Episode UUID:  {episode_uuid}")

    episode_json = build_episode_json(
        username=username,
        episode_uuid=episode_uuid,
        director_output=director_output,
        renderer_output=renderer_output,
    )
    validate_published_episode_json(episode_json)

    first_approach_svg = next(
        clip.svg for clip in renderer_output.clips
        if clip.branch == "approach"
    )
    thumbnail_svg = extract_thumbnail(first_approach_svg)

    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root
    episode_path, thumb_path = _build_publish_output_paths(
        output_root=output_root,
        username=username,
        episode_uuid=episode_uuid,
    )
    _ensure_publish_targets_are_new(
        episode_path=episode_path,
        thumb_path=thumb_path,
    )
    episode_path.parent.mkdir(parents=True, exist_ok=True)
    episode_path.write_text(episode_json, encoding="utf-8")
    thumb_path.write_text(thumbnail_svg, encoding="utf-8")

    print(f"episode.json:  {episode_path}")
    print(f"thumb.svg:     {thumb_path}")

    print("\nRebuilding episodes/index.json...")
    result = subprocess.run(
        ["node", "scripts/build-index.js"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        print("build-index.js failed — index.json not updated.", file=sys.stderr)
        sys.exit(result.returncode)

    print("Done.")


if __name__ == "__main__":
    main()
