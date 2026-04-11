"""Episode assembly and draft persistence helpers for the orchestrator."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pipeline import config
from pipeline.config import STAGE_FAILED, STAGE_RENDER_SVG
from pipeline.media.thumbnail import extract_thumbnail
from pipeline.models import AnimatorOutput, DirectorOutput, Episode, RendererOutput
from pipeline.shared.logging import log_event

if TYPE_CHECKING:
    from pipeline.storage.episode_store import EpisodeStore
    from pipeline.storage.job_store import JobStore


class OrchestratorPersistenceMixin:
    """Provide episode assembly and draft persistence helpers.

    Requires the host class to define these instance attributes in its ``__init__``:
    - ``_job_store: JobStore``
    - ``_episode_store: EpisodeStore | None``
    """

    # Declared so type-checkers can verify mixin attribute access.
    # These are assigned by PipelineOrchestrator.__init__ at runtime.
    if TYPE_CHECKING:
        _job_store: JobStore
        _episode_store: EpisodeStore | None

    def _build_episode_payload(
        self,
        *,
        job_id: str,
        username: str,
        director_output: DirectorOutput,
        renderer_output: RendererOutput,
    ) -> tuple[Episode, str]:
        """Assemble the final episode payload and serialised JSON artifact."""
        clip_svgs = {
            self._clip_identity(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
            ): clip.svg
            for clip in renderer_output.clips
        }
        acts_payload: list[dict[str, Any]] = []
        for act in director_output.acts:
            approach_clip = clip_svgs.get(
                self._clip_identity(
                    act_index=act.act_index,
                    branch="approach",
                    choice_index=None,
                )
            )
            if approach_clip is None:
                msg = f"Missing approach clip for act {act.act_index}"
                raise RuntimeError(msg)

            choices_payload: list[dict[str, Any]] = []
            for choice_index, choice in enumerate(act.choices):
                win_clip = None
                fail_clip = None
                if choice.is_winning:
                    win_clip = clip_svgs.get(
                        self._clip_identity(
                            act_index=act.act_index,
                            branch="win",
                            choice_index=choice_index,
                        )
                    )
                    if win_clip is None:
                        msg = f"Missing win clip for act {act.act_index} choice {choice_index}"
                        raise RuntimeError(msg)
                else:
                    fail_clip = clip_svgs.get(
                        self._clip_identity(
                            act_index=act.act_index,
                            branch="fail",
                            choice_index=choice_index,
                        )
                    )
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
        episode_uuid = self._derive_episode_uuid(job_id)
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
        episode_body["contentHash"] = self._compute_episode_content_hash(episode_body)
        episode = Episode.model_validate(episode_body)
        episode_json = json.dumps(
            episode.model_dump(by_alias=True, mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        if len(episode_json.encode("utf-8")) > config.MAX_EPISODE_JSON_SIZE_BYTES:
            msg = f"Episode JSON size exceeds max of {config.MAX_EPISODE_JSON_SIZE_BYTES} bytes"
            raise RuntimeError(msg)
        return episode, episode_json

    def _compute_episode_content_hash(self, episode_body: dict[str, Any]) -> str:
        """Compute the episode content hash per the schema contract."""
        hash_input = {**episode_body, "contentHash": None}
        serialised = json.dumps(hash_input, sort_keys=True, ensure_ascii=False)
        return f"sha256:{hashlib.sha256(serialised.encode('utf-8')).hexdigest()}"

    def _derive_episode_uuid(self, job_id: str) -> str:
        """Derive the episode UUID component from the generation job id."""
        return job_id.removeprefix("job-")

    def _build_draft_keys(self, *, username: str, episode_uuid: str) -> tuple[str, str]:
        """Return the episode JSON key and thumbnail key under ``drafts/``."""
        return (
            f"drafts/{username}/{episode_uuid}/episode.json",
            f"drafts/{username}/{episode_uuid}/thumb.svg",
        )

    def _collect_supporting_svg_assets(
        self,
        *,
        animator_output: AnimatorOutput,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Collect one resolved obstacle SVG per slug and one background SVG per background slug.

        Args:
            animator_output: Final Animator output after drawing resolution.

        Returns:
            Tuple of ``(obstacle_svgs_by_slug, background_svgs_by_slug)``.

        Raises:
            RuntimeError: If any clip is missing its resolved obstacle or background SVG.
        """
        obstacle_svgs_by_slug: dict[str, str] = {}
        background_svgs_by_slug: dict[str, str] = {}

        for clip in animator_output.clips:
            if clip.obstacle_svg_override is None:
                msg = (
                    f"Missing resolved obstacle SVG for act {clip.act_index} "
                    f"({clip.obstacle_type})"
                )
                raise RuntimeError(msg)
            if clip.background_svg is None:
                msg = f"Missing resolved background SVG for act {clip.act_index}"
                raise RuntimeError(msg)
            obstacle_svgs_by_slug.setdefault(clip.obstacle_type, clip.obstacle_svg_override)
            if clip.background_slug is not None:
                background_svgs_by_slug.setdefault(clip.background_slug, clip.background_svg)

        return obstacle_svgs_by_slug, background_svgs_by_slug

    def _build_supporting_svg_keys(
        self,
        *,
        username: str,
        episode_uuid: str,
        obstacle_slugs: list[str],
        background_slugs: list[str],
    ) -> list[tuple[str, str]]:
        """Return S3 keys and SVG bodies for supporting obstacle/background assets.

        Args:
            username: Developer username used for the draft prefix.
            episode_uuid: Episode UUID component under the draft prefix.
            obstacle_slugs: Sorted obstacle slugs present in the draft.
            background_slugs: Sorted background slugs present in the draft.

        Returns:
            Ordered list of ``(s3_key, asset_kind)`` tuples.
        """
        keys: list[tuple[str, str]] = []
        for slug in obstacle_slugs:
            keys.append((f"drafts/{username}/{episode_uuid}/obstacles/{slug}.svg", "obstacle"))
        for slug in background_slugs:
            keys.append((f"drafts/{username}/{episode_uuid}/backgrounds/{slug}.svg", "background"))
        return keys

    def _persist_supporting_svg_assets(
        self,
        *,
        username: str,
        episode_uuid: str,
        obstacle_svgs_by_slug: dict[str, str],
        background_svgs_by_slug: dict[str, str],
        written_keys: list[str],
    ) -> None:
        """Persist supporting obstacle/background SVGs and append written keys in order.

        Args:
            username: Developer username used for the draft prefix.
            episode_uuid: Episode UUID component under the draft prefix.
            obstacle_svgs_by_slug: One resolved obstacle SVG per slug.
            background_svgs_by_slug: One resolved background SVG per background slug.

        Raises:
            RuntimeError: If any supporting SVG write fails.
        """
        if self._episode_store is None:
            msg = "Episode store is required for draft artifact persistence"
            raise RuntimeError(msg)

        asset_keys = self._build_supporting_svg_keys(
            username=username,
            episode_uuid=episode_uuid,
            obstacle_slugs=sorted(obstacle_svgs_by_slug),
            background_slugs=sorted(background_svgs_by_slug),
        )
        for key, asset_kind in asset_keys:
            if asset_kind == "obstacle":
                obstacle_prefix = f"drafts/{username}/{episode_uuid}/obstacles/"
                slug = key.removeprefix(obstacle_prefix).removesuffix(".svg")
                body = obstacle_svgs_by_slug[slug]
            else:
                bg_prefix = f"drafts/{username}/{episode_uuid}/backgrounds/"
                slug = key.removeprefix(bg_prefix).removesuffix(".svg")
                body = background_svgs_by_slug[slug]
            self._episode_store.put_draft_svg(key, body)
            written_keys.append(key)

    def _complete_successful_run(
        self,
        *,
        job_id: str,
        username: str,
        director_output: DirectorOutput,
        animator_output: AnimatorOutput,
        renderer_output: RendererOutput,
    ) -> dict[str, str]:
        """Persist final episode artifacts and mark the job done.

        Args:
            job_id: Generation job identifier.
            username: Developer username used for draft S3 key generation.
            director_output: Final validated Director output.
            animator_output: Final validated Animator output.
            renderer_output: Final validated and sanitised Renderer output.

        Returns:
            Success result payload.
        """
        if self._episode_store is None:
            msg = "Episode store is required for draft artifact persistence"
            raise RuntimeError(msg)
        log_event(
            "DEBUG",
            "PipelineOrchestrator",
            "complete_successful_run_start",
            message="Persisting the final episode draft artifacts and marking the job done.",
            job_id=job_id,
            act_count=len(director_output.acts),
            clip_count=len(animator_output.clips),
        )
        try:
            episode, episode_json = self._build_episode_payload(
                job_id=job_id,
                username=username,
                director_output=director_output,
                renderer_output=renderer_output,
            )
            first_approach_clip = renderer_output.clips[0].svg
            thumbnail_svg = extract_thumbnail(first_approach_clip)
            obstacle_svgs_by_slug, background_svgs_by_slug = self._collect_supporting_svg_assets(
                animator_output=animator_output
            )
        except Exception as error:
            self._job_store.mark_failed(
                job_id=job_id,
                error_message=f"Failed to assemble episode artifacts: {error}",
                stage=STAGE_FAILED,
            )
            return {
                "result": "failed",
                "reason": "episode_artifact_assembly_failed",
                "error": str(error),
            }

        draft_key, draft_thumbnail_key = self._build_draft_keys(
            username=username,
            episode_uuid=episode.uuid,
        )
        try:
            self._episode_store.put_draft_json(draft_key, episode_json)
        except Exception as error:
            self._job_store.mark_failed(
                job_id=job_id,
                error_message=f"Failed to write draft episode JSON: {error}",
                stage=STAGE_FAILED,
            )
            return {"result": "failed", "reason": "draft_episode_write_failed", "error": str(error)}

        written_supporting_keys: list[str] = []
        supporting_asset_write_started = False
        try:
            self._episode_store.put_draft_thumbnail(draft_thumbnail_key, thumbnail_svg)
            supporting_asset_write_started = True
            self._persist_supporting_svg_assets(
                username=username,
                episode_uuid=episode.uuid,
                obstacle_svgs_by_slug=obstacle_svgs_by_slug,
                background_svgs_by_slug=background_svgs_by_slug,
                written_keys=written_supporting_keys,
            )
        except Exception as error:
            cleanup_errors: list[str] = []
            for key in [*reversed(written_supporting_keys), draft_thumbnail_key, draft_key]:
                try:
                    self._episode_store.delete_draft_object(key)
                except Exception as delete_error:  # pragma: no cover - defensive cleanup path
                    cleanup_errors.append(f"{key}: {delete_error}")

            error_message = (
                f"Failed to write draft supporting SVGs: {error}"
                if supporting_asset_write_started
                else f"Failed to write draft thumbnail SVG: {error}"
            )
            if cleanup_errors:
                error_message += f"; cleanup failed: {'; '.join(cleanup_errors)}"
            self._job_store.mark_failed(
                job_id=job_id,
                error_message=error_message,
                stage=STAGE_FAILED,
            )
            return {
                "result": "failed",
                "reason": (
                    "draft_supporting_svg_write_failed"
                    if supporting_asset_write_started
                    else "draft_thumbnail_write_failed"
                ),
                "error": str(error),
            }

        self._job_store.mark_done(
            job_id=job_id,
            stage=STAGE_RENDER_SVG,
            draft_s3_key=draft_key,
            director_script_json=director_output.model_dump_json(),
            animator_manifest_json=animator_output.model_dump_json(),
        )
        return {"result": "ok", "reason": "renderer_validation_passed", "draftS3Key": draft_key}

