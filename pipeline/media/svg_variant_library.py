"""Shared helpers for bundled SVG variant libraries."""

from __future__ import annotations

import random
import re
from pathlib import Path

_VARIANT_SUFFIX_RE = re.compile(r"^(?P<base>[a-z0-9-]+?)(?:-(?P<variant>\d+))?$")


def list_matching_variant_paths(library_dir: Path, slug: str) -> list[Path]:
    """Return all valid prepared SVG variant paths for one base slug.

    Args:
        library_dir: Directory containing bundled SVG variants.
        slug: Base library slug to match.

    Returns:
        Sorted list of matching SVG paths such as ``robot.svg`` and ``robot-2.svg``.
    """
    if not library_dir.exists():
        return []

    matching_paths: list[Path] = []
    for path in library_dir.glob("*.svg"):
        match = _VARIANT_SUFFIX_RE.fullmatch(path.stem)
        if match is None:
            continue
        if match.group("base") != slug:
            continue
        matching_paths.append(path)

    def sort_key(path: Path) -> tuple[int, int]:
        match = _VARIANT_SUFFIX_RE.fullmatch(path.stem)
        if match is None:
            return (1, 0)
        variant_text = match.group("variant")
        if variant_text is None:
            return (0, 0)
        return (1, int(variant_text))

    return sorted(matching_paths, key=sort_key)


def get_library_svg(library_dir: Path, slug: str) -> str | None:
    """Return bundled SVG content for one slug from one library directory.

    Args:
        library_dir: Directory containing bundled SVG variants.
        slug: Library slug to look up.

    Returns:
        SVG text when the slug exists, otherwise ``None``.
    """
    variant_paths = list_matching_variant_paths(library_dir, slug)
    if not variant_paths:
        return None
    path = random.choice(variant_paths)
    return path.read_text(encoding="utf-8")


def list_library_names(library_dir: Path) -> list[str]:
    """Return all bundled slug names in one library directory.

    Args:
        library_dir: Directory containing bundled SVG variants.

    Returns:
        Sorted unique base slugs from the bundled SVG library.
    """
    if not library_dir.exists():
        return []

    names: set[str] = set()
    for path in library_dir.glob("*.svg"):
        match = _VARIANT_SUFFIX_RE.fullmatch(path.stem)
        if match is None:
            continue
        names.add(match.group("base"))
    return sorted(names)
