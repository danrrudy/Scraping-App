"""Assembles the three-pane main window and exposes it as one façade.

Layout
------
``[ left sidebar | document view | content panel ]``

* **left sidebar** - all user controls and editable fields.
* **document view** - the viewer for whatever the user is working with.
* **content panel** - a swappable manipulation of the centre content.

The controller never touches a widget. It reads state through the ``*_text`` /
``*s()`` accessors and presents state through the ``set_*`` / ``show_*``
methods defined here.
"""

from __future__ import annotations

from PyQt5.QtCore import QObject, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QShortcut,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import panels
from .document_view import DocumentView
from .left_sidebar import CONTROL_SPECS, LeftSidebar

#: Maps a sidebar action id to the controller method that services it.
ACTION_HANDLERS = {
    "restart": "restart_application",
    "previous_page": "prev_page",
    "next_page": "next_page",
    "next_entry": "next_mid_entry",
    "previous_entry": "prev_mid_entry",
    "jump_to_entry": "select_mid_entry",
    "add_observation": "add_observation_from_document",
    "delete_entry": "delete_mid_entry",
    "duplicate_year": "duplicate_prior_year",
    "open_settings": "open_settings",
    "run_audit": "run_mid_audit",
    "load_cases": "handle_load_failures",
    "export_results": "export_review_results",
    "accept": "accept_scrape",
    "reject": "reject_scrape",
}

#: Single-key transfer shortcuts, in order. How many are bound is the
#: content panel's decision, not the window's.
FIELD_TRANSFER_KEYS = ("1", "2", "3", "4", "5", "6", "7", "8", "9")
#: Function keys that add a new row at an expandable field's level.
ADD_LEVEL_KEYS = ("F1", "F2", "F3", "F4")

#: Declared controls with no controller method would be silently dead buttons.
UNMAPPED_CONTROLS = tuple(
    spec.action for spec in CONTROL_SPECS if spec.action not in ACTION_HANDLERS
)


class MainWindowUI(QObject):
    """Builds and owns the main window's widgets.

    ``MainWindowUI`` is not a window. ``TextScrapingReviewApp`` remains the only
    ``QMainWindow``; this class populates it and mediates every interaction
    with its widgets.
    """

    def __init__(self, app, context, module_settings=None):
        super().__init__(app)
        self.app = app
        self.context = context
        self.logger = getattr(app, "logger", None)
        # ``{module_id: {key: value}}``, supplied by the controller.
        self.module_settings = dict(module_settings or {})

        self.left = None
        self.document_view = None
        self.content_panel = None

        self._shortcuts = []
        self._reserved_plain_keys: set[str] = set()
        self._content_payload = ""
        self._panel_actions = {}
        self._menu_initialized = False

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def setup(self, panel_id: str = panels.DEFAULT_PANEL_ID) -> None:
        self._log("debug", f"Initializing UI in {self.context.normalized_mode} mode")

        central = QWidget(self.app)
        self.app.setCentralWidget(central)

        self.left = LeftSidebar(self.context, central)
        self.document_view = DocumentView(central)

        self._panel_host = QWidget(central)
        self._panel_layout = QVBoxLayout(self._panel_host)
        self._panel_layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Horizontal, central)
        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.document_view)
        self.splitter.addWidget(self._panel_host)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setCollapsible(0, False)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.splitter)

        self.document_view.apply_settings(
            self.module_settings.get(self.document_view.MODULE_SETTINGS.module_id, {})
        )
        self.show_panel(panel_id)
        self._connect_controller()
        self._build_menu()
        self.bind_shortcuts()
        self.apply_mode(self.context.mode)
        for action in UNMAPPED_CONTROLS:
            self._log("warning", f"Sidebar control '{action}' has no handler")
        self._log("debug", "Main window UI constructed")

    def _connect_controller(self) -> None:
        """Wire every sidebar signal to its controller method, in one place."""
        self.left.actionTriggered.connect(self._dispatch_action)
        self._connect_if_present(self.left.addLevelRequested, "on_add_level_clicked")
        self._connect_if_present(
            self.left.fieldButtonClicked, "on_field_button_clicked"
        )
        self._connect_if_present(self.left.schemeChanged, "on_scheme_changed")
        self._connect_if_present(self.left.toggleChanged, "on_toggle_changed")
        self._connect_if_present(self.left.counterChanged, "on_counter_changed")

    def _connect_if_present(self, signal, handler_name: str) -> None:
        handler = getattr(self.app, handler_name, None)
        if callable(handler):
            signal.connect(handler)
        else:
            self._log("warning", f"Controller has no handler '{handler_name}'")

    def _dispatch_action(self, action: str) -> None:
        handler_name = ACTION_HANDLERS.get(action)
        handler = getattr(self.app, handler_name, None) if handler_name else None
        if callable(handler):
            handler()
        else:
            self._log("error", f"No controller handler for UI action '{action}'")

    def _build_menu(self) -> None:
        if self._menu_initialized:
            return
        menu_bar = self.app.menuBar()

        file_menu = menu_bar.addMenu("&File")
        save_action = QAction("Save MID…", self.app)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(
            lambda: getattr(self.app, "save_mid_to_file", lambda: None)()
        )
        file_menu.addAction(save_action)

        view_menu = menu_bar.addMenu("&View")
        group = QActionGroup(self.app)
        group.setExclusive(True)
        for panel_id, display_name in panels.available_panels().items():
            action = QAction(display_name, self.app)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, target=panel_id: self.show_panel(target)
            )
            group.addAction(action)
            view_menu.addAction(action)
            self._panel_actions[panel_id] = action
        self._sync_panel_actions()

        self._menu_initialized = True

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def bind_shortcuts(self) -> None:
        """(Re)install the application shortcuts."""
        for shortcut in self._shortcuts:
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._shortcuts = []
        self._reserved_plain_keys = set()

        # Metric status radios: Ctrl+1..Ctrl+9 select, 0 clears.
        for index in range(9):
            self._bind(
                f"Ctrl+{index + 1}",
                lambda position=index: self.left.select_metric_status_by_index(position),
            )
        self._bind("0", self.left.clear_metric_status)

        # Page and entry navigation.
        self._bind("-", lambda: self._dispatch_action("previous_page"))
        self._bind("=", lambda: self._dispatch_action("next_page"))
        self._bind("Ctrl+Return", lambda: self._dispatch_action("next_entry"))
        self._bind("Ctrl+Enter", lambda: self._dispatch_action("next_entry"))

        # Pull the content panel's selection into a sidebar field, if the
        # active panel offers that at all.
        for key, field_key in zip(
            self._transfer_keys(), self.context.field_keys
        ):
            self._bind(key, lambda target=field_key: self.transfer_selection(target))

        # Expand the hierarchy at a given level.
        for key, field_key in zip(
            ADD_LEVEL_KEYS, self.context.expandable_field_keys
        ):
            self._bind(key, lambda target=field_key: self.left.trigger_add_level(target))

    def _transfer_keys(self) -> tuple[str, ...]:
        """The number keys the active panel wants bound to field transfer."""
        panel = self.content_panel
        if panel is None or not panel.supports_number_key_transfer:
            return ()
        if not panel.setting("numberKeyTransfer", True):
            return ()
        count = int(panel.setting("transferFieldCount", len(FIELD_TRANSFER_KEYS)) or 0)
        return FIELD_TRANSFER_KEYS[: max(0, count)]

    def _bind(self, sequence: str, handler) -> None:
        shortcut = QShortcut(QKeySequence(sequence), self.app)
        shortcut.setContext(Qt.ApplicationShortcut)
        shortcut.activated.connect(handler)
        self._shortcuts.append(shortcut)
        if len(sequence) == 1:
            self._reserved_plain_keys.add(sequence)

    def reserved_plain_keys(self) -> set[str]:
        """Unmodified keys the window must swallow rather than insert as text."""
        return set(self._reserved_plain_keys)

    # ------------------------------------------------------------------
    # Right panel
    # ------------------------------------------------------------------
    def show_panel(self, panel_id: str) -> None:
        """Swap in a registered content panel, preserving the current content."""
        if self.content_panel is not None:
            if self.content_panel.panel_id == panel_id:
                return
            self._panel_layout.removeWidget(self.content_panel)
            self.content_panel.setParent(None)
            self.content_panel.deleteLater()

        self.content_panel = panels.create_panel(panel_id, self._panel_host)
        self.content_panel.apply_settings(self.module_settings.get(panel_id, {}))
        self.content_panel.set_transfer_targets(self.left.transfer_targets())
        self.content_panel.transferRequested.connect(self._on_transfer_requested)
        self._panel_layout.addWidget(self.content_panel)
        self.content_panel.set_content(self._content_payload)
        self._sync_panel_actions()
        # The panel decides how many transfer keys exist, so rebind for it.
        if self._shortcuts:
            self.bind_shortcuts()
        self._log("debug", f"Content panel switched to '{panel_id}'")

    def _sync_panel_actions(self) -> None:
        if self.content_panel is None:
            return
        for panel_id, action in self._panel_actions.items():
            action.setChecked(panel_id == self.content_panel.panel_id)

    def active_panel_id(self) -> str:
        return self.content_panel.panel_id if self.content_panel else ""

    def set_content(self, payload) -> None:
        self._content_payload = payload
        self.content_panel.set_content(payload)

    def content(self):
        return self.content_panel.content()

    def clear_content(self) -> None:
        self._content_payload = ""
        self.content_panel.clear()

    def selection(self) -> str:
        return self.content_panel.selection()

    def refresh_highlights(self) -> None:
        """Mark sidebar values wherever they appear in the content panel."""
        if not self.content_panel.isVisible():
            return
        terms = [
            (self.left.field_text(key), self.left.highlight_color(key))
            for key in self.context.field_keys
        ]
        self.content_panel.highlight(terms)

    # ------------------------------------------------------------------
    # Pulling content leftward
    # ------------------------------------------------------------------
    def transfer_selection(self, target_key: str) -> None:
        """Ask the controller to move the panel selection into ``target_key``."""
        self.content_panel.request_transfer(target_key)

    def _on_transfer_requested(self, target_key: str, text: str) -> None:
        if not text:
            self.set_status_message("No highlighted text to transfer.", 2000)
            return
        handler = getattr(self.app, "on_content_transfer", None)
        if callable(handler):
            handler(target_key, text)
        else:
            self._log("error", "Controller has no handler 'on_content_transfer'")

    # ------------------------------------------------------------------
    # Centre viewer
    # ------------------------------------------------------------------
    def show_page_pixmap(self, pixmap) -> None:
        self.document_view.show_page_pixmap(pixmap)

    def show_page_png(self, png_bytes) -> None:
        self.document_view.show_page_png(png_bytes)

    def show_canvas_image(self, pixmap, meta=None) -> None:
        self.document_view.show_canvas_image(pixmap, meta=meta)

    def refresh_document_view(self) -> None:
        self.document_view.refresh()

    def clear_document_view(self) -> None:
        self.document_view.clear()

    def active_document_view(self) -> str:
        return self.document_view.active_view()

    # ------------------------------------------------------------------
    # Left sidebar - reading state
    # ------------------------------------------------------------------
    def field_text(self, key: str) -> str:
        return self.left.field_text(key)

    def field_texts(self) -> dict[str, str]:
        return self.left.field_texts()

    def notes_text(self) -> str:
        return self.left.notes_text()

    def reviewer_notes_text(self) -> str:
        return self.left.reviewer_notes_text()

    def toggles(self) -> dict[str, bool]:
        return self.left.toggles()

    def is_toggled(self, key: str) -> bool:
        return self.left.is_toggled(key)

    def counters(self) -> dict[str, int]:
        return self.left.counters()

    def counter(self, key: str) -> int:
        return self.left.counter(key)

    def focus_widgets(self) -> list:
        return self.left.focus_widgets()

    def metric_status(self) -> str:
        return self.left.metric_status()

    def metric_status_labels(self) -> list[str]:
        return self.left.metric_status_labels()

    def scheme_name(self) -> str:
        return self.left.scheme_name()

    def restriction_choice(self) -> str:
        return self.left.restriction_choice()

    # ------------------------------------------------------------------
    # Left sidebar - presenting state
    # ------------------------------------------------------------------
    def set_field_text(self, key: str, value) -> None:
        self.left.set_field_text(key, value)

    def set_field_texts(self, values) -> None:
        self.left.set_field_texts(values)

    def clear_fields(self) -> None:
        self.left.clear_fields()

    def focus_field(self, key: str) -> None:
        self.left.focus_field(key)

    def set_notes_text(self, value) -> None:
        self.left.set_notes_text(value)

    def set_reviewer_notes_text(self, value) -> None:
        self.left.set_reviewer_notes_text(value)

    def set_toggle(self, key: str, checked: bool) -> None:
        self.left.set_toggle(key, checked)

    def set_toggles(self, values) -> None:
        self.left.set_toggles(values)

    def set_counter(self, key: str, value) -> None:
        self.left.set_counter(key, value)

    def set_counters(self, values) -> None:
        self.left.set_counters(values)

    def set_counter_enabled(self, key: str, enabled: bool) -> None:
        self.left.set_counter_enabled(key, enabled)

    def set_entry_position(self, current: int, total: int) -> None:
        self.left.set_entry_position(current, total)

    def set_info_values(self, values) -> None:
        self.left.set_info_values(values)

    def set_warning(self, text) -> None:
        self.left.set_warning(text)

    def warning_text(self) -> str:
        return self.left.warning_text()

    def set_hint(self, text) -> None:
        self.left.set_hint(text)

    def set_metric_status(self, value) -> None:
        self.left.set_metric_status(value)

    def set_scheme(self, name: str) -> None:
        self.left.set_scheme(name)

    def set_scheme_options(self, classes, default_name: str = "") -> None:
        self.left.set_scheme_options(classes, default_name)

    def set_restriction_options(self, options) -> None:
        self.left.set_restriction_options(options)

    def apply_module_settings(self, module_settings) -> None:
        """Push a fresh set of module values into the widgets that own them."""
        self.module_settings = dict(module_settings or {})
        self.document_view.apply_settings(
            self.module_settings.get(self.document_view.MODULE_SETTINGS.module_id, {})
        )
        if self.content_panel is not None:
            self.content_panel.apply_settings(
                self.module_settings.get(self.content_panel.panel_id, {})
            )
        self.bind_shortcuts()

    def active_module_ids(self) -> tuple[str, ...]:
        """The modules currently on screen, for the settings window to show."""
        ids = [self.document_view.MODULE_SETTINGS.module_id]
        if self.content_panel is not None:
            ids.append(self.content_panel.panel_id)
        return tuple(module_id for module_id in ids if module_id)

    def apply_mode(self, mode: str) -> None:
        self.context.mode = mode
        self.left.apply_mode(mode)

    def set_status_message(self, text: str, timeout: int = 0) -> None:
        self.app.statusBar().showMessage(text, timeout)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _log(self, level: str, message: str) -> None:
        if self.logger is not None:
            getattr(self.logger, level)(message)
