"""Unit tests for publish-local helper behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script_module(relative_path: str, module_name: str) -> object:
    """Load one script file as a test module."""
    script_path = PROJECT_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        msg = f"Unable to load script module: {script_path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_get_publish_username_prefers_gh_login(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script_module("scripts/publish-local.py", "publish_local_prefers_gh")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        if command[:3] == ["gh", "api", "user"]:
            return SimpleNamespace(returncode=0, stdout="kerenoded\n")
        return SimpleNamespace(returncode=0, stdout="ignored@example.com\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module._get_publish_username() == "kerenoded"
    assert calls == [["gh", "api", "user", "--jq", ".login"]]


def test_get_publish_username_falls_back_to_git_email(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script_module("scripts/publish-local.py", "publish_local_fallback_email")

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if command[:3] == ["gh", "api", "user"]:
            raise FileNotFoundError
        return SimpleNamespace(returncode=0, stdout="linions.dev@example.com\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module._get_publish_username() == "linions.dev"


def test_ensure_publish_targets_are_new_rejects_existing_files(tmp_path: Path) -> None:
    module = _load_script_module("scripts/publish-local.py", "publish_local_existing_targets")
    episode_path = tmp_path / "episodes" / "kerenoded" / "episode-123" / "episode.json"
    thumb_path = episode_path.parent / "thumb.svg"
    episode_path.parent.mkdir(parents=True)
    episode_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Refusing to overwrite existing published artifact"):
        module._ensure_publish_targets_are_new(
            episode_path=episode_path,
            thumb_path=thumb_path,
        )
