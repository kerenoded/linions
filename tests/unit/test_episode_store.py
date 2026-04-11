"""Unit tests for the EpisodeStore S3 adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from pipeline.storage.episode_store import EpisodeStore


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "PutObject")


class _FakeS3:
    """Minimal S3 client double that records calls and allows injection of errors."""

    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []
        self.delete_calls: list[str] = []
        self._put_error: ClientError | None = None
        self._get_body: bytes = b""

    def raise_on_put(self, error: ClientError) -> None:
        self._put_error = error

    def set_get_body(self, body: bytes) -> None:
        self._get_body = body

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        if self._put_error is not None:
            raise self._put_error
        return {}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append(kwargs["Key"])
        body_mock = MagicMock()
        body_mock.read.return_value = self._get_body
        return {"Body": body_mock}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.delete_calls.append(kwargs["Key"])
        return {}


# ---------------------------------------------------------------------------
# put_draft_json
# ---------------------------------------------------------------------------


def test_put_draft_json_calls_s3_with_correct_content_type() -> None:
    s3 = _FakeS3()
    store = EpisodeStore("my-bucket", s3_client=s3)

    store.put_draft_json("drafts/dev/1/episode.json", '{"hello": "world"}')

    assert len(s3.put_calls) == 1
    call = s3.put_calls[0]
    assert call["Bucket"] == "my-bucket"
    assert call["Key"] == "drafts/dev/1/episode.json"
    assert call["Body"] == b'{"hello": "world"}'
    assert "application/json" in call["ContentType"]
    assert call["IfNoneMatch"] == "*"


def test_put_draft_json_raises_runtime_error_when_object_exists() -> None:
    s3 = _FakeS3()
    s3.raise_on_put(_client_error("ConditionalRequestConflict"))
    store = EpisodeStore("my-bucket", s3_client=s3)

    with pytest.raises(RuntimeError, match="already exists"):
        store.put_draft_json("drafts/dev/1/episode.json", "{}")


def test_put_draft_json_raises_on_precondition_failed() -> None:
    s3 = _FakeS3()
    s3.raise_on_put(_client_error("PreconditionFailed"))
    store = EpisodeStore("my-bucket", s3_client=s3)

    with pytest.raises(RuntimeError, match="already exists"):
        store.put_draft_json("drafts/dev/1/episode.json", "{}")


def test_put_draft_json_wraps_other_client_errors() -> None:
    s3 = _FakeS3()
    s3.raise_on_put(_client_error("AccessDenied"))
    store = EpisodeStore("my-bucket", s3_client=s3)

    with pytest.raises(RuntimeError, match="Failed to write"):
        store.put_draft_json("drafts/dev/1/episode.json", "{}")


# ---------------------------------------------------------------------------
# put_draft_thumbnail
# ---------------------------------------------------------------------------


def test_put_draft_thumbnail_uses_svg_content_type() -> None:
    s3 = _FakeS3()
    store = EpisodeStore("my-bucket", s3_client=s3)

    store.put_draft_thumbnail("drafts/dev/1/thumb.svg", "<svg/>")

    call = s3.put_calls[0]
    assert call["Key"] == "drafts/dev/1/thumb.svg"
    assert call["Body"] == b"<svg/>"
    assert "image/svg+xml" in call["ContentType"]
    assert call["IfNoneMatch"] == "*"


# ---------------------------------------------------------------------------
# put_draft_svg
# ---------------------------------------------------------------------------


def test_put_draft_svg_uses_svg_content_type() -> None:
    s3 = _FakeS3()
    store = EpisodeStore("my-bucket", s3_client=s3)

    store.put_draft_svg("drafts/dev/1/obstacles/wall.svg", "<svg/>")

    call = s3.put_calls[0]
    assert call["Key"] == "drafts/dev/1/obstacles/wall.svg"
    assert "image/svg+xml" in call["ContentType"]
    assert call["IfNoneMatch"] == "*"


# ---------------------------------------------------------------------------
# get_draft_text
# ---------------------------------------------------------------------------


def test_get_draft_text_returns_utf8_decoded_body() -> None:
    s3 = _FakeS3()
    s3.set_get_body(b'{"uuid": "abc"}')
    store = EpisodeStore("my-bucket", s3_client=s3)

    result = store.get_draft_text("drafts/dev/abc/episode.json")

    assert result == '{"uuid": "abc"}'
    assert s3.get_calls == ["drafts/dev/abc/episode.json"]


# ---------------------------------------------------------------------------
# delete_draft_object
# ---------------------------------------------------------------------------


def test_delete_draft_object_delegates_to_s3() -> None:
    s3 = _FakeS3()
    store = EpisodeStore("my-bucket", s3_client=s3)

    store.delete_draft_object("drafts/dev/1/episode.json")

    assert s3.delete_calls == ["drafts/dev/1/episode.json"]
