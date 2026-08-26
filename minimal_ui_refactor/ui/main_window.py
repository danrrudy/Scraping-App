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

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QScrollArea,
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
    # Menu-only actions. They are declared here too so every UI action
    # resolves through one table.
    "first_unedited_entry": "goto_first_unedited_entry",
    "open_statistics": "open_statistics",
}

#: Qt's "no maximum" sentinel, for lifting a maximum we set ourselves.
QWIDGETSIZE_MAX = (1 << 24) - 1

#: How narrow the sidebar may be dragged. Below what its content needs, on
#: purpose: the sidebar is in a scroll area, so squeezing it past the point
#: where everything fits scrolls rather than clips, and the document and the
#: content panel get the room instead.
SIDEBAR_MINIMUM_WIDTH = 180

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
        self.left_scroll = None
        self.document_view = None
        self.content_panel = None

        self._shortcuts = []
        self._reserved_plain_keys: set[str] = set()
        self._content_payload = ""
        self._panel_actions = {}
        self._menu_initialized = False
        #: File ▸ Entry. Kept as an attribute so per-entry controls can be
        #: added to it without rebuilding the menu bar.
        self.entry_menu = None
        self.entry_edited_action = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def setup(self, panel_id: str = panels.DEFAULT_PANEL_ID) -> None:
        self._log("debug", f"Initializing UI in {self.context.normalized_mode} mode")

        central = QWidget(self.app)
        self.app.setCentralWidget(central)

        self.left = LeftSidebar(self.context, central)
        # In a scroll area so the splitter can make it narrower than its
        # contents need. Without this the widest control in the sidebar sets a
        # floor on the whole pane, and there is no way for a user to get that
        # width back for the document.
        self.left_scroll = QScrollArea(central)
        self.left_scroll.setWidget(self.left)
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QScrollArea.NoFrame)
        self.left_scroll.setMinimumWidth(SIDEBAR_MINIMUM_WIDTH)
        # Watched so the sidebar can be held to the height of its viewport
        # whenever its content is able to compress that far. See
        # _fit_sidebar_to_viewport.
        self.left_scroll.viewport().installEventFilter(self)

        self.document_view = DocumentView(central)

        self._panel_host = QWidget(central)
        self._panel_layout = QVBoxLayout(self._panel_host)
        self._panel_layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Horizontal, central)
        # A little wider than the default: these handles are now the way a
        # user reclaims space from the sidebar, so they should be easy to grab.
        self.splitter.setHandleWidth(8)
        self.splitter.addWidget(self.left_scroll)
        self.splitter.addWidget(self.document_view)
        self.splitter.addWidget(self._panel_host)
        # The sidebar takes the width its content needs and keeps it; extra
        # space goes to the document and the panel, which are the two that
        # benefit from it. The user can still drag it narrower — down to
        # SIDEBAR_MINIMUM_WIDTH, scrolling what no longer fits.
        self.splitter.setStretchFactor(0, 0)
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

    def eventFilter(self, watched, event):
        if (
            self.left_scroll is not None
            and watched is self.left_scroll.viewport()
            and event.type() == QEvent.Resize
        ):
            self._fit_sidebar_to_viewport()
        return super().eventFilter(watched, event)

    def _fit_sidebar_to_viewport(self) -> None:
        """Keep the sidebar within its viewport while its content allows it.

        The editable fields are vertically expanding within a maximum, so the
        column can absorb a shorter window by making them shorter — but only
        if something holds it to the viewport's height. Left to itself the
        scroll area sizes the sidebar to what its content would prefer and
        shows a scrollbar that was never needed.

        Once the content genuinely cannot fit, the cap is lifted and the
        scrollbar appears, which is the point at which it is telling the user
        something true.
        """
        viewport_height = self.left_scroll.viewport().height()
        if self.left.minimumSizeHint().height() <= viewport_height:
            self.left.setMaximumHeight(viewport_height)
        else:
            self.left.setMaximumHeight(QWIDGETSIZE_MAX)

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
        self._connect_if_present(self.left.userEdited, "on_entry_edited_by_user")
        self._connect_if_present(
            self.document_view.pageStepRequested, "step_page"
        )
        self._connect_if_present(
            self.document_view.entryStepRequested, "step_entry"
        )

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
        file_menu.addSeparator()

        unedited_action = QAction("Go to First &Unedited Entry", self.app)
        unedited_action.setShortcut("Ctrl+U")
        unedited_action.setStatusTip(
            "Jump to the first MID row no change has ever been saved to."
        )
        unedited_action.triggered.connect(
            lambda: self._dispatch_action("first_unedited_entry")
        )
        file_menu.addAction(unedited_action)

        # Controls that act on the row currently open. Deliberately its own
        # submenu so more per-entry actions have somewhere to go.
        self.entry_menu = file_menu.addMenu("&Entry")
        self.entry_edited_action = QAction("Mark as &Edited", self.app)
        self.entry_edited_action.setCheckable(True)
        self.entry_edited_action.setStatusTip(
            "Whether this row counts as edited when jumping to unedited entries."
        )
        self.entry_edited_action.triggered.connect(self._on_entry_edited_toggled)
        self.entry_menu.addAction(self.entry_edited_action)

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

        # Everything about the person doing the work, rather than the document
        # in front of them. Settings appears here as well as on the sidebar
        # button: this is where a user looks for it.
        user_menu = menu_bar.addMenu("&User")

        user_settings_action = QAction("&Settings…", self.app)
        user_settings_action.setStatusTip(
            "Configure the MID, the sidebar, and the tools that read documents."
        )
        user_settings_action.triggered.connect(
            lambda: self._dispatch_action("open_settings")
        )
        user_menu.addAction(user_settings_action)

        statistics_action = QAction("S&tatistics…", self.app)
        statistics_action.setStatusTip("How far this session has got, and how fast.")
        statistics_action.triggered.connect(
            lambda: self._dispatch_action("open_statistics")
        )
        user_menu.addAction(statistics_action)

        self._menu_initialized = True

    def _on_entry_edited_toggled(self, checked: bool) -> None:
        handler = getattr(self.app, "set_entry_edited", None)
        if callable(handler):
            handler(checked)
        else:
            self._log("error", "Controller has no handler 'set_entry_edited'")

    def set_entry_edited_checked(self, checked: bool) -> None:
        """Show the current row's persistent edited flag, without firing it."""
        if self.entry_edited_action is None:
            return
        self.entry_edited_action.blockSignals(True)
        self.entry_edited_action.setChecked(bool(checked))
        self.entry_edited_action.blockSignals(False)

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
        self._connect_if_present(
            self.content_panel.searchRequested, "search_document"
        )
        self._connect_if_present(
            self.content_panel.pageRequested, "go_to_document_page"
        )
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

    def show_search_results(self, query, results, truncated=False) -> None:
        if self.content_panel is not None:
            self.content_panel.show_search_results(query, results, truncated)

    def clear_search(self) -> None:
        panel = self.content_panel
        if panel is not None and hasattr(panel, "clear_search"):
            panel.clear_search()

    def search_scope(self):
        """How far the active panel's search is configured to reach."""
        panel = self.content_panel
        if panel is not None and hasattr(panel, "search_scope"):
            return panel.search_scope()
        return None

    def panel_supports_search(self) -> bool:
        return bool(getattr(self.content_panel, "supports_search", False))

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
    def _note_row_edit(self) -> None:
        """Report a write to the widgets that hold the current row's values.

        These setters block their widgets' signals, so a change made through
        the façade would otherwise be invisible to the edit tracking. The
        controller decides what to do with it: while it is presenting a row,
        the report is ignored.
        """
        handler = getattr(self.app, "on_entry_edited_by_user", None)
        if callable(handler):
            handler()

    def set_field_text(self, key: str, value) -> None:
        self.left.set_field_text(key, value)
        self._note_row_edit()

    def set_field_texts(self, values) -> None:
        self.left.set_field_texts(values)
        self._note_row_edit()

    def clear_fields(self) -> None:
        self.left.clear_fields()
        self._note_row_edit()

    def focus_field(self, key: str) -> None:
        self.left.focus_field(key)

    def set_notes_text(self, value) -> None:
        self.left.set_notes_text(value)
        self._note_row_edit()

    def set_reviewer_notes_text(self, value) -> None:
        self.left.set_reviewer_notes_text(value)
        self._note_row_edit()

    def set_toggle(self, key: str, checked: bool, notify: bool = False) -> None:
        self.left.set_toggle(key, checked, notify)
        self._note_row_edit()

    def set_toggles(self, values) -> None:
        self.left.set_toggles(values)
        self._note_row_edit()

    def set_counter(self, key: str, value) -> None:
        self.left.set_counter(key, value)
        self._note_row_edit()

    def set_counters(self, values) -> None:
        self.left.set_counters(values)
        self._note_row_edit()

    def set_counter_enabled(self, key: str, enabled: bool) -> None:
        self.left.set_counter_enabled(key, enabled)

    def set_entry_position(self, current: int, total: int) -> None:
        self.left.set_entry_position(current, total)

    def set_statistic_specs(self, specs) -> None:
        """Which session statistics are pinned above the entry counter."""
        self.left.set_statistic_specs(specs)

    def set_statistic_values(self, values) -> None:
        self.left.set_statistic_values(values)

    def pinned_statistic_keys(self) -> tuple[str, ...]:
        return tuple(self.left.statistic_labels)

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
        self._note_row_edit()

    def set_scheme(self, name: str) -> None:
        self.left.set_scheme(name)
        self._note_row_edit()

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
