"""Right-hand panel that renders scraped content as HTML.

Registered so that table-formatted scrapes have somewhere to go; the controller
selects it by id rather than by widget type.
"""

from __future__ import annotations

from PyQt5.QtWidgets import QTextBrowser, QVBoxLayout

from module_settings import BoolSetting, ModuleSettings, register_module_settings

from . import register_panel
from .base import ContentPanel


@register_panel
@register_module_settings
class RenderedTablePanel(ContentPanel):
    """Read-only HTML view, used for table-shaped scrape results."""

    panel_id = "rendered_table"
    display_name = "Rendered Table"

    MODULE_SETTINGS = ModuleSettings(
        module_id="rendered_table",
        display_name="Rendered Table Panel",
        settings=(
            BoolSetting(
                "openExternalLinks",
                "Follow links in the rendered table",
                default=False,
            ),
        ),
    )

    def __init__(self, parent=None):
        super().__init__(parent)

        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(False)
        self.browser.setTabChangesFocus(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)

    def settings_applied(self) -> None:
        self.browser.setOpenExternalLinks(
            bool(self.setting("openExternalLinks", False))
        )

    def set_content(self, payload) -> None:
        self.browser.setHtml("" if payload is None else str(payload))

    def clear(self) -> None:
        self.browser.clear()

    def content(self) -> str:
        return self.browser.toHtml()

    def selection(self) -> str:
        selected = self.browser.textCursor().selectedText() or ""
        return selected.replace("\u2029", " ").strip()
