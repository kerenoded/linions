"""Deterministic SVG validation for scene and obstacle SVG output.

This is a pure stateless function — no class, no side effects, no I/O.
Implements a **detect-and-reject** contract: forbidden content is removed from
the parsed tree, but the sanitised result is only returned when *no* violations
were found.  If any violation is detected, returns ``(invalid, None)`` —
the orchestrator must re-prompt the Renderer rather than using a partially-cleaned clip.

See DESIGN.md §6.4 for the full contract, and STANDARDS.md §3.2 for the
validator pattern.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pipeline import config
from pipeline.models import ValidationResult
from pipeline.validators._xml_utils import find_parent, local_name, to_svg_string

# Tags that must never appear in Renderer output (SEC-03).
FORBIDDEN_TAGS = {"script", "iframe", "object", "embed", "foreignObject"}

# Attribute names that carry URL values and must be checked for external URLs.
URL_ATTRS = {"href", "src", "xlink:href"}
ANIMATION_TAGS = {"animate", "animateTransform", "animateMotion", "set"}


def _is_external_url(value: str) -> bool:
    """Return True if *value* is an absolute HTTP or HTTPS URL.

    Used to detect external URL references in ``href``, ``src``, and
    ``xlink:href`` attributes.  Relative paths and data URIs are handled by
    separate checks.

    Args:
        value: The raw attribute value string to inspect.

    Returns:
        ``True`` if the value starts with ``http://`` or ``https://`` (case-insensitive).
    """
    lowered = value.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _find_element_by_id(root: ET.Element, element_id: str) -> ET.Element | None:
    """Return the first element in *root* with the exact given id."""
    for element in root.iter():
        if element.attrib.get("id") == element_id:
            return element
    return None


def _has_animation_for_id(root: ET.Element, element: ET.Element, element_id: str) -> bool:
    """Return True when *element_id* is animated directly or via an href target."""
    if any(local_name(descendant.tag) in ANIMATION_TAGS for descendant in element.iter()):
        return True

    target_ref = f"#{element_id}"
    for candidate in root.iter():
        if local_name(candidate.tag) not in ANIMATION_TAGS:
            continue
        href_value = candidate.attrib.get("href") or candidate.attrib.get(
            "{http://www.w3.org/1999/xlink}href"
        )
        if href_value == target_ref:
            return True
    return False


def validate_and_sanitise_svg(
    svg: str,
    *,
    expected_clip_count: int | None = None,
    output_clip_count: int | None = None,
    required_ids: set[str] | None = None,
    animated_ids: set[str] | None = None,
) -> tuple[ValidationResult, str | None]:
    """Validate one SVG clip from Renderer output against all rules in DESIGN.md §6.4.

    This is a **detect-and-reject** validator.  Forbidden tags and attributes are
    stripped from the parsed tree during validation, but the cleaned result is
    only returned as the second tuple element when *no* violations were found.
    If ``is_valid`` is ``False``, the second element is always ``None`` — the
    orchestrator must treat this as a hard rejection and re-prompt the Renderer.

    Rules checked (in order):
    - Optional clip count check: if both ``expected_clip_count`` and
      ``output_clip_count`` are provided, they must be equal.
    - SVG byte size must not exceed ``MAX_SVG_FILE_SIZE_BYTES``.
    - SVG must be well-formed XML (parse error returns early with None).
    - Root element must be ``<svg>``.
    - Root element must have a ``viewBox`` attribute.
    - No forbidden tags: ``script``, ``iframe``, ``object``, ``embed``, ``foreignObject``.
    - No attributes containing ``javascript:``.
    - No attributes containing ``data:`` (data URIs disallowed entirely).
    - No external URLs in ``href``, ``src``, or ``xlink:href`` attributes.
    - All caller-required ids must be present in the tree.
    - Caller-required animated ids must exist and contain a real SVG animation descendant.

    Args:
        svg: Complete SVG string to validate.
        expected_clip_count: Expected number of clips from ``RendererInput`` (optional).
        output_clip_count: Actual number of clips in ``RendererOutput`` (optional).
            If both are provided and differ, a clip count mismatch error is appended.
        required_ids: Element ids that must exist in the SVG tree. Defaults to
            ``{"linai"}`` for scene clips.
        animated_ids: Element ids that must both exist in the SVG tree and contain
            at least one descendant animation tag such as ``<animate>`` or
            ``<animateTransform>``.

    Returns:
        A tuple of ``(ValidationResult, sanitised_svg_or_None)``.
        On success: ``(ValidationResult(is_valid=True, errors=[]), sanitised_svg_string)``.
        On failure: ``(ValidationResult(is_valid=False, errors=[...]), None)``.

    Raises:
        TypeError: If ``svg`` is ``None`` (programmer error).
    """
    if svg is None:
        msg = "svg cannot be None"
        raise TypeError(msg)

    errors: list[str] = []
    ids_to_require = required_ids if required_ids is not None else {"linai"}
    ids_to_animate = animated_ids if animated_ids is not None else set()

    # Rule: clip count in RendererOutput must match the number of clips in RendererInput.
    if (
        expected_clip_count is not None
        and output_clip_count is not None
        and expected_clip_count != output_clip_count
    ):
        errors.append("renderer output clip count must match RendererInput.clips count")

    # Rule: SVG byte size must not exceed the configured maximum.
    if len(svg.encode("utf-8")) > config.MAX_SVG_FILE_SIZE_BYTES:
        errors.append(f"svg size exceeds max of {config.MAX_SVG_FILE_SIZE_BYTES} bytes")

    # Rule: SVG must be well-formed XML.  Return early — remaining checks require a parsed tree.
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        errors.append(f"malformed svg xml: {exc}")
        return ValidationResult(is_valid=False, errors=errors), None

    # Rule: root element must be <svg>.
    if local_name(root.tag) != "svg":
        errors.append("svg root element must be <svg>")

    # Rule: <svg> root must declare a viewBox attribute so the browser can scale it correctly.
    if "viewBox" not in root.attrib:
        errors.append("svg must include viewBox attribute")

    # Walk every element in the tree; strip forbidden tags and attributes in-place.
    # Iteration over list(root.iter()) avoids mutating the iterator mid-walk.
    for element in list(root.iter()):
        local_tag = local_name(element.tag)

        # Rule: forbidden tags must not appear in Renderer output (SEC-03).
        if local_tag in FORBIDDEN_TAGS:
            parent = find_parent(root, element)
            if parent is not None:
                parent.remove(element)
            errors.append(f"forbidden tag removed: <{local_tag}>")
            continue

        attrs_to_remove: list[str] = []
        for attr_name, attr_value in element.attrib.items():
            name = local_name(attr_name)
            lowered_value = attr_value.strip().lower()

            # Rule: no attribute value may contain a javascript: URI.
            if "javascript:" in lowered_value:
                attrs_to_remove.append(attr_name)
                errors.append(f"forbidden javascript attribute removed: {name}")
                continue

            # Rule: data: URIs are disallowed entirely — no exceptions (SEC-03).
            if "data:" in lowered_value:
                attrs_to_remove.append(attr_name)
                errors.append(f"forbidden data uri attribute removed: {name}")
                continue

            # Rule: href/src/xlink:href must not point to external URLs.
            if name in URL_ATTRS and _is_external_url(attr_value):
                attrs_to_remove.append(attr_name)
                errors.append(f"external url attribute removed: {name}")

        for attr in attrs_to_remove:
            element.attrib.pop(attr, None)

    # Rule: the caller can require specific ids to be present in the output so
    # scene clips and standalone obstacle SVGs can share the same security linter.
    present_ids = {element.attrib.get("id") for element in root.iter() if "id" in element.attrib}
    for required_id in sorted(ids_to_require):
        if required_id not in present_ids:
            errors.append(f'svg must include required element id="{required_id}"')

    for animated_id in sorted(ids_to_animate):
        target = _find_element_by_id(root, animated_id)
        if target is None:
            errors.append(f'svg must include required animated element id="{animated_id}"')
            continue
        if not _has_animation_for_id(root, target, animated_id):
            errors.append(
                f'required animated element id="{animated_id}" must contain an SVG animation tag'
            )

    # Detect-and-reject: if any violation was found, discard the cleaned tree and reject.
    if errors:
        return ValidationResult(is_valid=False, errors=errors), None

    sanitised = to_svg_string(root)
    return ValidationResult(is_valid=True, errors=[]), sanitised
