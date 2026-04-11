"""Episode S3 persistence adapter for draft episode artifacts."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from pipeline.shared.logging import log_event


class EpisodeStore:
    """Persist draft episode JSON and thumbnail SVG files in S3."""

    def __init__(self, bucket_name: str, s3_client: Any | None = None) -> None:
        """Initialise an episode store instance.

        Args:
            bucket_name: S3 bucket name where draft artifacts are stored.
            s3_client: Optional custom S3 client, primarily for tests.
        """
        self._bucket_name = bucket_name
        self._s3 = s3_client or boto3.client("s3")
        log_event(
            "DEBUG",
            "EpisodeStore",
            "init_complete",
            message="Initialized the S3-backed episode store.",
            bucket_name=bucket_name,
            has_custom_client=s3_client is not None,
        )

    def put_draft_json(self, key: str, body: str) -> None:
        """Write a draft episode JSON object without overwriting an existing key.

        Args:
            key: Draft S3 object key under ``drafts/``.
            body: UTF-8 JSON payload.

        Raises:
            RuntimeError: If the object already exists or the upload fails.
        """
        self._put_object(
            key=key,
            body=body.encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )

    def put_draft_thumbnail(self, key: str, body: str) -> None:
        """Write a draft thumbnail SVG object without overwriting an existing key.

        Args:
            key: Draft thumbnail S3 object key under ``drafts/``.
            body: UTF-8 SVG payload.

        Raises:
            RuntimeError: If the object already exists or the upload fails.
        """
        self._put_object(
            key=key,
            body=body.encode("utf-8"),
            content_type="image/svg+xml; charset=utf-8",
        )

    def put_draft_svg(self, key: str, body: str) -> None:
        """Write one supporting draft SVG object without overwriting an existing key.

        Args:
            key: Draft SVG S3 object key under ``drafts/``.
            body: UTF-8 SVG payload.

        Raises:
            RuntimeError: If the object already exists or the upload fails.
        """
        self._put_object(
            key=key,
            body=body.encode("utf-8"),
            content_type="image/svg+xml; charset=utf-8",
        )

    def get_draft_text(self, key: str) -> str:
        """Read one draft object as UTF-8 text.

        Args:
            key: Draft object key under ``drafts/``.

        Returns:
            Object body decoded as UTF-8 text.
        """
        log_event(
            "DEBUG",
            "EpisodeStore",
            "get_draft_text_start",
            message="Reading a draft object from S3.",
            s3_key=key,
            bucket_name=self._bucket_name,
        )
        response = self._s3.get_object(Bucket=self._bucket_name, Key=key)
        return response["Body"].read().decode("utf-8")

    def delete_draft_object(self, key: str) -> None:
        """Delete one draft object from S3.

        Args:
            key: Draft object key under ``drafts/``.
        """
        log_event(
            "DEBUG",
            "EpisodeStore",
            "delete_draft_object_start",
            message="Deleting a draft object from S3.",
            s3_key=key,
            bucket_name=self._bucket_name,
        )
        self._s3.delete_object(Bucket=self._bucket_name, Key=key)

    def _put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        """Write one object to S3 with overwrite protection.

        Args:
            key: S3 object key.
            body: Raw object bytes.
            content_type: HTTP content type metadata for the object.

        Raises:
            RuntimeError: If the object already exists or the upload fails.
        """
        log_event(
            "DEBUG",
            "EpisodeStore",
            "put_object_start",
            message="Writing a draft object to S3.",
            s3_key=key,
            bucket_name=self._bucket_name,
            content_type=content_type,
            body_bytes=len(body),
        )
        try:
            self._s3.put_object(
                Bucket=self._bucket_name,
                Key=key,
                Body=body,
                ContentType=content_type,
                IfNoneMatch="*",
            )
        except ClientError as error:
            error_code = error.response.get("Error", {}).get("Code", "")
            if error_code in {"PreconditionFailed", "ConditionalRequestConflict"}:
                msg = f"Draft object already exists: {key}"
                raise RuntimeError(msg) from error
            msg = f"Failed to write draft object: {key}"
            raise RuntimeError(msg) from error
