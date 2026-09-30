"""User-interface layer for the scraping review application.

The window is three panes:

``left sidebar``
    Every user control and editable field. See :mod:`ui.left_sidebar`.
``document view``
    The viewer for the content being worked on. See :mod:`ui.document_view`.
``content panel``
    A swappable manipulation of the centre content. See :mod:`ui.panels`.

:class:`~ui.main_window.MainWindowUI` assembles the three and is the only
object the controller talks to. Widgets are owned here, never by the
application class.
"""

from .context import (
    CounterSpec,
    FieldButtonSpec,
    FieldSpec,
    InfoSpec,
    ToggleSpec,
    UIContext,
)
from .document_view import DocumentView
from .left_sidebar import LeftSidebar
from .main_window import ACTION_HANDLERS, MainWindowUI
from .panels import (
    ContentPanel,
    DEFAULT_PANEL_ID,
    available_panels,
    create_panel,
    register_panel,
)

__all__ = [
    "ACTION_HANDLERS",
    "ContentPanel",
    "DEFAULT_PANEL_ID",
    "DocumentView",
    "CounterSpec",
    "FieldButtonSpec",
    "FieldSpec",
    "InfoSpec",
    "LeftSidebar",
    "MainWindowUI",
    "ToggleSpec",
    "UIContext",
    "available_panels",
    "create_panel",
    "register_panel",
]
