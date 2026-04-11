"""Helpers for reading the canonical Linai SVG template."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

_LINAI_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "frontend" / "public" / "linai-template.svg"
)


def _read_linai_template_text() -> str:
    """Read the canonical Linai SVG template from disk.

    Returns:
        Full SVG template text as UTF-8.

    Raises:
        RuntimeError: If the template file is missing.
    """
    try:
        return _LINAI_TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        msg = f"Linai template SVG not found: {_LINAI_TEMPLATE_PATH}"
        raise RuntimeError(msg) from error


@lru_cache(maxsize=1)
def get_linai_part_ids() -> list[str]:
    """Return all targetable SVG ids defined inside the canonical Linai group.

    Returns:
        Document-order list of ids from the ``#linai`` group and its descendants.

    Raises:
        RuntimeError: If the template cannot be parsed or lacks ``id="linai"``.
    """
    try:
        root = ET.fromstring(_read_linai_template_text())
    except ET.ParseError as error:
        msg = f"Invalid Linai template SVG: {_LINAI_TEMPLATE_PATH}"
        raise RuntimeError(msg) from error

    linai_group: ET.Element | None = None
    for element in root.iter():
        if element.get("id") == "linai":
            linai_group = element
            break
    if linai_group is None:
        msg = f'Linai template missing required id="linai": {_LINAI_TEMPLATE_PATH}'
        raise RuntimeError(msg)

    ids: list[str] = []
    for element in linai_group.iter():
        element_id = element.get("id")
        if element_id is not None:
            ids.append(element_id)
    return ids


@lru_cache(maxsize=1)
def get_linai_template_svg() -> str:
    """Return the canonical Linai SVG template as UTF-8 text.

    Returns:
        Full SVG template text from ``frontend/public/linai-template.svg``.

    Raises:
        RuntimeError: If the template file cannot be parsed or lacks ``id="linai"``.
    """
    svg_text = _read_linai_template_text()
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as error:
        msg = f"Invalid Linai template SVG: {_LINAI_TEMPLATE_PATH}"
        raise RuntimeError(msg) from error

    has_linai = any(element.get("id") == "linai" for element in root.iter())
    if not has_linai:
        msg = f'Linai template missing required id="linai": {_LINAI_TEMPLATE_PATH}'
        raise RuntimeError(msg)
    return svg_text
