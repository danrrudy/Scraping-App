"""Contract for anything that can occupy the right-hand panel.

The right panel presents *some manipulation of the central content*. Today the
only implementation is the scraped text of the current page, but the panel is
addressed exclusively through this interface so that other interactions can be
dropped in without touching the controller.
"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget

from module_settings import ModuleSettings


class ContentPanel(QWidget):
    """Base class for right-hand content panels.

    Subclasses must set :attr:`panel_id` and :attr:`display_name` and implement
    :meth:`set_content` and :meth:`content`.
    """

    #: Stable identifier used by the registry and by saved settings.
    panel_id: str = ""
    #: Human-readable name, suitable for a menu entry.
    display_name: str = ""
    #: What this panel lets the user configure. Subclasses override it and
    #: register with ``@register_module_settings``; the module id must match
    #: ``panel_id`` so a panel's settings travel with it.
    MODULE_SETTINGS = ModuleSettings(module_id="", display_name="")

    #: Whether a number key can send this panel's selection to a sidebar
    #: field. This is what the panel *can* do; a panel that sets it should
    #: also declare a ``numberKeyTransfer`` setting so the user can turn it
    #: off (and get those keys back for typing).
    supports_number_key_transfer = False

    #: Emitted when the user asks to move panel content into a sidebar field.
    #: Arguments are ``(target_key, text)``. ``text`` may be empty, which the
    #: main window reports back to the user rather than silently ignoring.
    transferRequested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._transfer_targets: list[tuple[str, str]] = []
        self._settings = dict(self.MODULE_SETTINGS.defaults)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def apply_settings(self, values) -> None:
        """Adopt the user's values for this panel's declared settings."""
        self._settings = self.MODULE_SETTINGS.resolve(values)
        self.settings_applied()

    def settings_applied(self) -> None:
        """Hook for subclasses that must react to a settings change."""

    def setting(self, key, default=None):
        return self._settings.get(key, default)

    # ------------------------------------------------------------------
    # Presenting state
    # ------------------------------------------------------------------
    def set_content(self, payload) -> None:
        """Display ``payload``. The accepted type is panel-specific."""
        raise NotImplementedError

    def clear(self) -> None:
        self.set_content("")

    def highlight(self, terms) -> None:
        """Emphasise ``terms``, a sequence of ``(text, QColor)`` pairs.

        Panels that cannot highlight may ignore this.
        """

    # ------------------------------------------------------------------
    # Reading state
    # ------------------------------------------------------------------
    def content(self):
        """Return the panel's current content in its native representation."""
        raise NotImplementedError

    def selection(self) -> str:
        """Return the text the user has selected, or an empty string."""
        return ""

    # ------------------------------------------------------------------
    # Pulling content leftward
    # ------------------------------------------------------------------
    def set_transfer_targets(self, targets) -> None:
        """Declare the sidebar fields this panel may push content into.

        ``targets`` is a sequence of ``(key, label)`` pairs supplied by the
        left sidebar, so panels never hard-code field names.
        """
        self._transfer_targets = [(str(key), str(label)) for key, label in targets]

    def transfer_targets(self) -> list[tuple[str, str]]:
        return list(self._transfer_targets)

    def request_transfer(self, target_key: str) -> None:
        """Ask the application to move the current selection into a field."""
        self.transferRequested.emit(str(target_key), self.selection())
