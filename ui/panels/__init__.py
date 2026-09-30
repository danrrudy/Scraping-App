"""Registry of right-hand content panels.

Register a new interaction by subclassing :class:`ContentPanel` and decorating
it with :func:`register_panel`; nothing else in the application needs to change.
"""

from __future__ import annotations

from .base import ContentPanel

_REGISTRY: dict[str, type[ContentPanel]] = {}

DEFAULT_PANEL_ID = "scraped_text"


def register_panel(panel_class: type[ContentPanel]) -> type[ContentPanel]:
    """Class decorator that adds ``panel_class`` to the registry."""
    if not panel_class.panel_id:
        raise ValueError(f"{panel_class.__name__} must define a panel_id")
    _REGISTRY[panel_class.panel_id] = panel_class
    return panel_class


def available_panels() -> dict[str, str]:
    """Return ``{panel_id: display_name}`` for every registered panel."""
    return {
        panel_id: panel_class.display_name or panel_id
        for panel_id, panel_class in _REGISTRY.items()
    }


def create_panel(panel_id: str, parent=None) -> ContentPanel:
    """Instantiate a registered panel."""
    try:
        panel_class = _REGISTRY[panel_id]
    except KeyError:
        raise KeyError(
            f"Unknown content panel '{panel_id}'. Registered: {sorted(_REGISTRY)}"
        ) from None
    return panel_class(parent)


# Importing the built-in panels registers them.
from .text_panel import ScrapedTextPanel  # noqa: E402
from .html_panel import RenderedTablePanel  # noqa: E402

__all__ = [
    "ContentPanel",
    "DEFAULT_PANEL_ID",
    "RenderedTablePanel",
    "ScrapedTextPanel",
    "available_panels",
    "create_panel",
    "register_panel",
]
