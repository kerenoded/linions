"""Factory for the real production LibraryLookups instance."""

from pipeline.lambdas.orchestrator.pipeline_orchestrator import LibraryLookups
from pipeline.media import background_library, obstacle_library


def build_library_lookups() -> LibraryLookups:
    """Return a LibraryLookups wired to the bundled obstacle and background libraries.

    Returns:
        Fully-wired production LibraryLookups instance.
    """
    return LibraryLookups(
        get_obstacle_svg=obstacle_library.get_obstacle_svg,
        list_obstacle_names=obstacle_library.list_library_names,
        get_background_svg=background_library.get_background_svg,
        find_background_library_slug=background_library.find_background_library_slug,
        prompt_to_background_slug=background_library.prompt_to_background_slug,
    )
