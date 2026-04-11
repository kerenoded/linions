"""Helpers for reading the bundled obstacle SVG library."""

from __future__ import annotations

from pathlib import Path

from pipeline.media.svg_variant_library import (
    get_library_svg,
)
from pipeline.media.svg_variant_library import (
    list_library_names as _list_names,
)

_LIBRARY_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "obstacles"


def get_obstacle_svg(slug: str) -> str | None:
    """Return bundled obstacle SVG content for one slug.

    Args:
        slug: Obstacle slug to look up in the bundled library.

    Returns:
        SVG text when the slug exists, otherwise ``None``.
    """
    return get_library_svg(_LIBRARY_DIR, slug)


def list_library_names() -> list[str]:
    """Return all bundled obstacle names sorted alphabetically.

    Returns:
        Sorted obstacle slug names from the bundled SVG library.
    """
    return _list_names(_LIBRARY_DIR)
