"""Shared XML helper utilities used by svg_linter and thumbnail."""

from __future__ import annotations

import xml.etree.ElementTree as ET

SVG_NAMESPACE = "http://www.w3.org/2000/svg"


def local_name(tag: str) -> str:
    """Return the local tag name, stripping any namespace URI prefix."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def find_parent(root: ET.Element, target: ET.Element) -> ET.Element | None:
    """Return the direct parent of *target* within the tree rooted at *root*.

    Iterates the entire tree (O(n)) because ElementTree does not maintain
    parent references. Returns None if *target* is not found under *root*.
    """
    for parent in root.iter():
        if target in list(parent):
            return parent
    return None


def to_svg_string(root: ET.Element) -> str:
    """Serialise an SVG tree without introducing ``ns0`` namespace prefixes.

    Args:
        root: Parsed SVG root element.

    Returns:
        Unicode SVG string.
    """
    ET.register_namespace("", SVG_NAMESPACE)
    return ET.tostring(root, encoding="unicode")
