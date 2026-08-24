"""Right-hand panel showing the text scraped from the centre document."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import QAction, QMenu, QTextEdit, QVBoxLayout

from module_settings import (
    BoolSetting,
    IntSetting,
    ModuleSettings,
    register_module_settings,
)

from ..widgets import configure_text_box
from . import register_panel
from .base import ContentPanel

# Qt reports paragraph and line separators inside selections; treat them, and a
# non-breaking space, as ordinary whitespace when matching.
_WHITESPACE_EXTRAS = {"\u2029", "\u2028", "\u00a0"}


def _collapse_whitespace(text: str) -> tuple[str, list[int]]:
    """Collapse runs of whitespace and map each kept character to its origin.

    Returns ``(collapsed, index_map)`` where ``index_map[i]`` is the index in
    ``text`` that produced ``collapsed[i]``.
    """
    collapsed: list[str] = []
    index_map: list[int] = []
    previous_was_space = False

    for index, character in enumerate(text):
        if character.isspace() or character in _WHITESPACE_EXTRAS:
            if not previous_was_space:
                collapsed.append(" ")
                index_map.append(index)
                previous_was_space = True
            continue
        collapsed.append(character)
        index_map.append(index)
        previous_was_space = False

    while collapsed and collapsed[0] == " ":
        collapsed.pop(0)
        index_map.pop(0)
    while collapsed and collapsed[-1] == " ":
        collapsed.pop()
        index_map.pop()

    return "".join(collapsed), index_map


@register_panel
@register_module_settings
class ScrapedTextPanel(ContentPanel):
    """Read-only view of scraped page text with selection transfer."""

    panel_id = "scraped_text"
    display_name = "Scraped Text"
    supports_number_key_transfer = True

    MODULE_SETTINGS = ModuleSettings(
        module_id="scraped_text",
        display_name="Scraped Text Panel",
        settings=(
            BoolSetting(
                "numberKeyTransfer",
                "Send the selection to a field with a number key",
                default=True,
                help="Pressing 1-9 puts the highlighted text into that "
                "editable field. Turn this off to type digits into fields "
                "instead.",
            ),
            IntSetting(
                "transferFieldCount",
                "How many fields the number keys reach",
                default=4,
                minimum=1,
                maximum=9,
                help="1 binds only the key 1, 9 binds 1 through 9.",
            ),
            BoolSetting(
                "showTransferMenu",
                'Offer "Send Selection To" on right-click',
                default=True,
            ),
            BoolSetting(
                "highlightFieldMatches",
                "Highlight field text where it appears in the page",
                default=True,
            ),
        ),
    )

    def __init__(self, parent=None):
        super().__init__(parent)

        self.editor = configure_text_box(QTextEdit(self))
        self.editor.setReadOnly(True)
        self.editor.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.editor.setUndoRedoEnabled(False)
        self.editor.setContextMenuPolicy(Qt.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self._show_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.editor)

    # ------------------------------------------------------------------
    # Presenting state
    # ------------------------------------------------------------------
    def set_content(self, payload) -> None:
        self.editor.setPlainText("" if payload is None else str(payload))

    def clear(self) -> None:
        self.editor.clear()

    def highlight(self, terms) -> None:
        """Highlight every occurrence of ``(text, QColor)`` pairs in ``terms``."""
        document = self.editor.document()
        if document is None:
            return
        if not self.setting("highlightFieldMatches", True):
            self.editor.setExtraSelections([])
            return

        haystack, index_map = _collapse_whitespace(document.toPlainText())
        haystack_lower = haystack.lower()
        selections = []

        for text, color in terms:
            needle, _ = _collapse_whitespace((text or "").strip())
            if not needle:
                continue
            # Very short fragments match almost everywhere; only allow them
            # when they are numeric (years and counts are worth marking).
            if len(needle) < 3 and not needle.isdigit():
                continue

            needle_lower = needle.lower()
            start = 0
            while True:
                position = haystack_lower.find(needle_lower, start)
                if position == -1:
                    break
                end = position + len(needle)

                cursor = QTextCursor(document)
                cursor.setPosition(index_map[position])
                cursor.setPosition(index_map[end - 1] + 1, QTextCursor.KeepAnchor)

                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                text_format = QTextCharFormat()
                text_format.setBackground(color or QColor("#FFFF00"))
                selection.format = text_format
                selections.append(selection)

                start = end

        self.editor.setExtraSelections(selections)

    # ------------------------------------------------------------------
    # Reading state
    # ------------------------------------------------------------------
    def content(self) -> str:
        return self.editor.toPlainText()

    def selection(self) -> str:
        cursor = self.editor.textCursor()
        selected = cursor.selectedText() or ""
        return selected.replace("\u2029", " ").strip()

    # ------------------------------------------------------------------
    # Pulling content leftward
    # ------------------------------------------------------------------
    def _show_context_menu(self, position):
        menu = self.editor.createStandardContextMenu()
        targets = (
            self.transfer_targets()
            if self.setting("showTransferMenu", True)
            else []
        )
        if targets:
            menu.addSeparator()
            send_menu = QMenu("Send Selection To", menu)
            send_menu.setEnabled(bool(self.selection()))
            for key, label in targets:
                action = QAction(label, send_menu)
                action.triggered.connect(
                    lambda _checked=False, target=key: self.request_transfer(target)
                )
                send_menu.addAction(action)
            menu.addMenu(send_menu)
        menu.exec_(self.editor.viewport().mapToGlobal(position))
