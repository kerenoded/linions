"""Helpers for reading the bundled background SVG library."""

from __future__ import annotations

import re
from pathlib import Path

from pipeline.media.svg_variant_library import get_library_svg, list_library_names
from pipeline.shared.logging import log_event

_LIBRARY_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "backgrounds"
_STOP_WORDS = frozenset([
    # articles, prepositions, conjunctions
    "a", "an", "the", "and", "or", "with", "in", "on", "at", "of", "to",
    "for", "by", "from", "into", "over", "under", "above", "below", "very",
    "some", "this", "that", "these", "those", "its", "their", "our", "there",
    "here", "is", "are", "was", "be", "been", "being", "has", "have", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "across", "through", "during", "along", "beside", "between",
    # drawing instruction verbs (common in drawing prompts)
    "draw", "create", "render", "generate", "paint", "make", "show", "depict",
    "illustrate", "design", "include", "add", "use", "place", "set", "fill",
    "feature", "display",
    # technical SVG/canvas terms that appear in prompt boilerplate
    "svg", "canvas", "viewbox", "output", "document", "complete", "inline",
    "assign", "technical", "requirements", "return", "markdown", "fences",
    # generic quality/structural words that add no scene meaning
    "simple", "basic", "clean", "nice", "beautiful", "pretty", "complex",
    "detailed", "full", "wide", "vast", "bright",
    "background", "scene", "environment", "setting",
])
_WORD_RE = re.compile(r"[a-z0-9]+")

# All background library slugs must be exactly 3 words.
# Keywords extracted from prompts are also exactly 3 words.
# Matching requires all 3 words to be present (order-independent).
_BG_KEYWORD_COUNT: int = 3


def get_background_svg(slug: str) -> str | None:
    """Return bundled background SVG content for one slug.

    Args:
        slug: Background slug to look up in the bundled library.

    Returns:
        SVG text when the slug exists, otherwise ``None``.
    """
    return get_library_svg(_LIBRARY_DIR, slug)


def list_background_library_names() -> list[str]:
    """Return all bundled background names sorted alphabetically.

    Returns:
        Sorted background slug names from the bundled SVG library.
    """
    return list_library_names(_LIBRARY_DIR)


def _extract_keywords(text: str) -> list[str]:
    """Extract up to ``_BG_KEYWORD_COUNT`` meaningful words from text.

    Strips stop words and returns the first N non-stop words in order.
    """
    words = [w for w in _WORD_RE.findall(text.lower()) if w not in _STOP_WORDS]
    return words[:_BG_KEYWORD_COUNT]


def prompt_to_background_slug(prompt: str) -> str:
    """Derive a 3-word kebab-case slug from a background drawing prompt.

    Strips stop words and joins the first 3 meaningful words with hyphens.
    Always returns a non-empty string.

    Args:
        prompt: Background drawing prompt text from the Director.

    Returns:
        Kebab-case slug, e.g. ``"tropical-blue-beach"``.
    """
    keywords = _extract_keywords(prompt)
    return "-".join(keywords) or "background"


def find_background_library_slug(*texts: str | None) -> str | None:
    """Return a matching bundled background slug for the provided text.

    Extracts exactly 3 scene keywords from the combined texts and looks for a
    library slug that is also exactly 3 words and contains all 3 keywords
    (order-independent).  Returns the first match found.

    Args:
        texts: Scene-description text snippets to inspect (e.g. drawing
            prompt, approach description).

    Returns:
        Matching background slug, or ``None`` when no slug qualifies.
    """
    combined = " ".join(t for t in texts if t)
    keywords = _extract_keywords(combined)
    log_event(
        "DEBUG",
        "BackgroundLibrary",
        "find_background_library_slug_start",
        message="Looking for a library background matching the extracted keywords.",
        keywords=keywords,
        keyword_count=len(keywords),
    )
    if len(keywords) < _BG_KEYWORD_COUNT:
        log_event(
            "DEBUG",
            "BackgroundLibrary",
            "find_background_library_slug_result",
            message="No library background matched: too few keywords extracted.",
            matched_slug=None,
        )
        return None

    kw_set = set(keywords)
    matched_slug: str | None = None
    for slug in list_background_library_names():
        slug_words = slug.split("-")
        if len(slug_words) != _BG_KEYWORD_COUNT:
            continue
        if set(slug_words) == kw_set:
            matched_slug = slug
            break

    log_event(
        "DEBUG",
        "BackgroundLibrary",
        "find_background_library_slug_result",
        message=(
            f"Library background matched: {matched_slug!r}."
            if matched_slug is not None
            else "No library background matched the extracted keywords."
        ),
        matched_slug=matched_slug,
    )
    return matched_slug
