"""Right-hand panel showing the text scraped from the centre document."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QAction,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from document_text import (
    SEARCH_ANYWHERE,
    SEARCH_IN_RANGE,
    SEARCH_MARK_OUTSIDE,
    SEARCH_SCOPES,
    collapse_whitespace as _collapse_whitespace,
)
from module_settings import (
    BoolSetting,
    ChoiceSetting,
    IntSetting,
    ModuleSettings,
    register_module_settings,
)

from ..widgets import configure_text_box
from . import register_panel
from .base import ContentPanel



@register_panel
@register_module_settings
class ScrapedTextPanel(ContentPanel):
    """Read-only view of scraped page text with selection transfer."""

    panel_id = "scraped_text"
    display_name = "Scraped Text"
    supports_number_key_transfer = True
    supports_search = True

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
            BoolSetting(
                "showSearchBar",
                "Show the document search box",
                default=True,
                help="Searches every page of the open file, not just the one "
                "on screen.",
            ),
            ChoiceSetting(
                "searchScope",
                "How far a search reaches",
                choices=SEARCH_SCOPES,
                default=SEARCH_IN_RANGE,
                help="The page you are on is written into the MID, so jumping "
                "outside the pages a row declares can record a page that row "
                "is not about.",
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
        layout.addWidget(self._build_search_bar())
        layout.addWidget(self.editor)
        layout.addWidget(self._build_results())

    # ------------------------------------------------------------------
    # Searching
    # ------------------------------------------------------------------
    def _build_search_bar(self):
        """The search box, its button, and the line that reports on a search.

        Two rows rather than one. The left sidebar's minimum width leaves this
        panel narrow on smaller windows, and a single row of box + button +
        status is the first thing to be clipped; stacking the status underneath
        keeps the box usable at the widths this panel actually gets.
        """
        self.search_bar = QWidget(self)
        column = QVBoxLayout(self.search_bar)
        column.setContentsMargins(0, 0, 0, 2)
        column.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        self.search_box = QLineEdit(self.search_bar)
        self.search_box.setPlaceholderText("Search this document…")
        self.search_box.setClearButtonEnabled(True)
        # Small, so the box shrinks with the panel instead of clipping it.
        self.search_box.setMinimumWidth(60)
        self.search_box.returnPressed.connect(self._run_search)
        row.addWidget(self.search_box, 1)

        self.search_button = QPushButton("Find", self.search_bar)
        self.search_button.clicked.connect(self._run_search)
        row.addWidget(self.search_button, 0)
        column.addLayout(row)

        self.search_status = QLabel("", self.search_bar)
        self.search_status.setStyleSheet("color: #555;")
        self.search_status.setWordWrap(True)
        column.addWidget(self.search_status)
        return self.search_bar

    def _build_results(self):
        self.results_list = QListWidget(self)
        self.results_list.setMaximumHeight(150)
        self.results_list.setVisible(False)
        self.results_list.itemActivated.connect(self._on_result_chosen)
        self.results_list.itemClicked.connect(self._on_result_chosen)
        return self.results_list

    def _run_search(self):
        query = self.search_box.text().strip()
        if not query:
            self.clear_search()
            return
        self.searchRequested.emit(query)

    def _on_result_chosen(self, item):
        if item is None:
            return
        payload = item.data(Qt.UserRole) or {}
        if not payload.get("selectable", True):
            self.search_status.setText("That page is outside this row.")
            return
        self.pageRequested.emit(int(payload.get("page_index", 0)))

    def show_search_results(self, query, results, truncated=False) -> None:
        """Display what the controller found. Called back after a request."""
        self.results_list.clear()
        results = list(results or [])

        if not results:
            self.search_status.setText(f"No match for “{query}”")
            self.results_list.setVisible(False)
            return

        for result in results:
            item = QListWidgetItem(
                f"{result.get('location', '')}  {result.get('snippet', '')}"
            )
            item.setData(Qt.UserRole, result)
            if not result.get("selectable", True):
                item.setForeground(QColor("#8A8A8A"))
                item.setToolTip("Outside the pages this MID row covers.")
            self.results_list.addItem(item)

        count = len(results)
        summary = f"{count} match{'' if count == 1 else 'es'}"
        if truncated:
            summary += " (showing the first ones)"
        self.search_status.setText(summary)
        self.results_list.setVisible(True)

    def clear_search(self) -> None:
        self.results_list.clear()
        self.results_list.setVisible(False)
        self.search_status.setText("")

    def search_scope(self) -> str:
        return self.setting("searchScope", SEARCH_IN_RANGE)

    def settings_applied(self) -> None:
        self.search_bar.setVisible(bool(self.setting("showSearchBar", True)))
        if not self.setting("showSearchBar", True):
            self.clear_search()

    # ------------------------------------------------------------------
    # Presenting state
    # ------------------------------------------------------------------
    def set_content(self, payload) -> None:
        self.editor.setPlainText("" if payload is None else str(payload))

    def clear(self) -> None:
        self.editor.clear()
        self.clear_search()

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
