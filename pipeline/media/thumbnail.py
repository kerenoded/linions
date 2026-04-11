"""Shared thumbnail extraction utility for SVG clips.

Used by two callers: the orchestrator Lambda at generation time, and the CI
deploy script at PR merge time. One function, two callers, no duplication.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pipeline.validators._xml_utils import find_parent, local_name

ANIMATION_TAGS = {"animate", "animateTransform", "animateMotion", "set"}


def extract_thumbnail(approach_svg: str) -> str:
    """Strip Linai animation elements; keep background and obstacle animations."""
    if approach_svg is None:
        msg = "approach_svg cannot be None"
        raise TypeError(msg)

    try:
        root = ET.fromstring(approach_svg)
    except ET.ParseError as exc:
        msg = f"Malformed SVG: {exc}"
        raise ValueError(msg) from exc

    linai_group = next(
        (el for el in root.iter() if el.attrib.get("id") == "linai"),
        None,
    )
    if linai_group is None:
        msg = 'Thumbnail SVG is missing required id="linai" element'
        raise ValueError(msg)

    animation_nodes = [
        el for el in linai_group.iter() if local_name(el.tag) in ANIMATION_TAGS
    ]
    for node in animation_nodes:
        parent = find_parent(root, node)
        if parent is not None:
            # Preserve whitespace: ET stores the text after a closing tag as the
            # element's `.tail`.  When we remove an animation node its tail (usually
            # a newline + indent) would be silently dropped, collapsing the next
            # sibling onto the same line.  Transfer it to the previous sibling's
            # tail (or to the parent's text if the node is the first child) so the
            # serialised output stays stable across repeated runs.
            children = list(parent)
            node_index = children.index(node)
            tail = node.tail or ""
            if node_index > 0:
                prev = children[node_index - 1]
                prev.tail = (prev.tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail
            parent.remove(node)

    return ET.tostring(root, encoding="unicode")
