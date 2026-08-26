"""Left pane: every user control, plus read/write access to their state.

Nothing outside this module touches the sidebar widgets. Controllers ask for
values (:meth:`field_text`, :meth:`toggles`, ...) and hand back values
(:meth:`set_field_text`, :meth:`set_info_values`, ...).
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .widgets import (
    FIELD_BOX_MAX_HEIGHT,
    FIELD_BOX_MIN_HEIGHT,
    configure_button,
    configure_text_box,
)

#: Backgrounds used when marking sidebar text inside the content panel.
FIELD_HIGHLIGHT_PALETTE = (
    "#FFF2A8",
    "#CFF7D3",
    "#CFE8FF",
    "#FFD1DC",
    "#D8F3F0",
    "#FDE2C5",
    "#E2D5F8",
    "#DDE5B6",
)

ALL_MODES = ("user", "dev", "reviewer")

#: Checkboxes are laid out across this many columns before wrapping.
TOGGLE_COLUMNS = 2

#: How narrow one checkbox cell may become. See the note where it is applied.
TOGGLE_MIN_WIDTH = 90


@dataclass(frozen=True)
class ControlSpec:
    """Declarative description of a sidebar button.

    Adding a control is a one-line change here plus one entry in
    ``MainWindowUI.ACTION_HANDLERS``.
    """

    action: str
    label: str
    modes: tuple[str, ...] = ALL_MODES
    shortcut: str = ""
    requires_expandable_fields: bool = False
    #: Consecutive controls sharing a group id are laid out side by side.
    group: str = ""


CONTROL_SPECS = (
    ControlSpec("restart", "Restart", shortcut="Ctrl+R"),
    ControlSpec("previous_page", "< Page", group="page"),
    ControlSpec("next_page", "Page >", group="page"),
    ControlSpec("previous_entry", "< Entry", shortcut="Ctrl+Left", group="entry"),
    ControlSpec("next_entry", "Entry >", shortcut="Ctrl+Right", group="entry"),
    ControlSpec("jump_to_entry", "Jump to MID Entry...", shortcut="Ctrl+O"),
    ControlSpec(
        "add_observation",
        "Add Observation from this Document",
        modes=("user", "dev"),
        shortcut="Ctrl+N",
    ),
    ControlSpec("delete_entry", "Delete this MID Entry", modes=("user", "dev")),
    ControlSpec(
        "duplicate_year",
        "Copy Previous Year",
        modes=("user", "dev"),
        requires_expandable_fields=True,
    ),
    ControlSpec("open_settings", "Settings"),
    ControlSpec("run_audit", "Run MID Audit", modes=("dev",)),
    ControlSpec("load_cases", "Load Cases", modes=("dev", "reviewer")),
    ControlSpec("export_results", "Export Review Results", modes=("dev",)),
)

#: The restriction combo box is inserted immediately before this control.
RESTRICTION_BEFORE_ACTION = "load_cases"


class LeftSidebar(QWidget):
    """Owns the information block, the editable fields, and the controls."""

    #: A declarative control was activated; the argument is its action id.
    actionTriggered = pyqtSignal(str)
    #: The "+" button beside an expandable field was pressed.
    addLevelRequested = pyqtSignal(str)
    #: A user-defined computed button was pressed; the argument is its key.
    fieldButtonClicked = pyqtSignal(str)
    #: The classification scheme selection changed.
    schemeChanged = pyqtSignal(str)
    #: A checkbox changed; arguments are ``(toggle key, checked)``.
    toggleChanged = pyqtSignal(str, bool)
    #: A checkbox's numeric companion changed; ``(toggle key, value)``.
    counterChanged = pyqtSignal(str, int)
    #: The user changed something the current MID row stores. Every ``set_*``
    #: method below blocks its widget's signals, so presenting a row never
    #: raises this — only a person at the keyboard does.
    userEdited = pyqtSignal()

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self._mode_widgets: dict[str, list[QWidget]] = {mode: [] for mode in ALL_MODES}

        self.info_labels: dict[str, QLabel] = {}
        self.statistic_labels: dict[str, QLabel] = {}
        self.field_editors: dict[str, QTextEdit] = {}
        self.add_level_buttons: dict[str, QPushButton] = {}
        self.field_buttons: dict[str, QPushButton] = {}
        self.control_buttons: dict[str, QPushButton] = {}
        self.metric_status_buttons: dict[str, QRadioButton] = {}
        self.toggle_boxes: dict[str, QCheckBox] = {}
        self.counter_boxes: dict[str, QSpinBox] = {}
        self._highlight_colors: dict[str, QColor] = {}
        self._focus_chain_ready = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._build_info_block())
        layout.addLayout(self._build_control_block())

        self.set_scheme_options(context.evaluation_classes, context.default_class)

        self._focus_chain_ready = True
        self.apply_focus_chain()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_info_block(self):
        # Kept on the instance so the ordering inside it can be asserted: the
        # statistics block is specified to sit directly above the counter.
        info_layout = self.info_layout = QVBoxLayout()

        # Session statistics, when the user has pinned any. Its own layout so
        # the set can be changed from Settings without rebuilding the sidebar,
        # and above the entry counter because it is context for it rather than
        # part of the row on screen.
        self.statistics_layout = QVBoxLayout()
        self.statistics_layout.setContentsMargins(0, 0, 0, 0)
        self.statistics_layout.setSpacing(1)
        info_layout.addLayout(self.statistics_layout)

        self.entry_index_label = QLabel("Entry 0 of 0")
        self.entry_index_label.setStyleSheet("font-weight: bold;")
        self.entry_index_label.setWordWrap(True)
        info_layout.addWidget(self.entry_index_label)

        for spec in self.context.info:
            label = QLabel(f"{spec.title}: ")
            label.setStyleSheet("font-weight: bold;")
            # Wrapped, because one of these carries the document's filename.
            # A label that cannot wrap reports its minimum width as the full
            # width of its text, so a long filename would the whole
            # sidebar open and could never be read anyway.
            label.setWordWrap(True)
            info_layout.addWidget(label)
            self.info_labels[spec.key] = label

        # Shown in every mode; carries load-time and per-row problems.
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(
            "color: #8A6100; background: #FFF4D6; border: 1px solid #E8C98A;"
            " border-radius: 3px; padding: 4px;"
        )
        self.warning_label.setVisible(False)
        info_layout.addWidget(self.warning_label)

        info_layout.addWidget(self._build_fields_group())
        info_layout.addWidget(self._build_reviewer_group())
        return info_layout

    def _build_fields_group(self):
        group = QGroupBox("Fields")
        form = QFormLayout()
        # A form row is normally label-beside-field, and its minimum width is
        # therefore both of them together. Allowing a long row to stack instead
        # lets the whole sidebar be made much narrower before anything clips.
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        # Tight, so the whole sidebar fits without scrolling on an ordinary
        # window. Empty spacer rows used to separate the blocks below; spacing
        # does the same job in a fraction of the height.
        form.setVerticalSpacing(6)

        for index, spec in enumerate(self.context.fields):
            color = FIELD_HIGHLIGHT_PALETTE[index % len(FIELD_HIGHLIGHT_PALETTE)]
            self._highlight_colors[spec.key] = QColor(color)

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            editor = configure_text_box(QTextEdit())
            editor.setMaximumHeight(FIELD_BOX_MAX_HEIGHT)
            editor.setMinimumHeight(FIELD_BOX_MIN_HEIGHT)
            editor.textChanged.connect(self.userEdited)
            self.field_editors[spec.key] = editor
            row_layout.addWidget(editor, 1)

            # Computed buttons sit beside the field they write into.
            for button_spec in self.context.buttons_for(spec.key):
                button = QPushButton(button_spec.label)
                button.setToolTip(button_spec.tooltip)
                button.setMaximumWidth(70)
                button.clicked.connect(
                    lambda _checked=False, key=button_spec.key: (
                        self.fieldButtonClicked.emit(key)
                    )
                )
                self.field_buttons[button_spec.key] = button
                row_layout.addWidget(button, 0)

            if spec.expandable:
                add_button = QPushButton("+")
                add_button.setFixedWidth(26)
                add_button.setToolTip(f"Add new {spec.key} row")
                add_button.clicked.connect(
                    lambda _checked=False, key=spec.key: self.addLevelRequested.emit(
                        key
                    )
                )
                self.add_level_buttons[spec.key] = add_button
                row_layout.addWidget(add_button, 0)

            form.addRow(f"{spec.label}:", row)

        self._add_classification_controls(form)
        self._add_toggle_controls(form)
        self._add_notes_controls(form)

        group.setLayout(form)
        return group

    def _add_classification_controls(self, form):
        # Label above the combo rather than beside it. Side by side, the two
        # together set a floor on the sidebar's width that neither needs on
        # its own, and wrapping the label instead clips its second line.
        scheme_container = QWidget()
        scheme_row = QVBoxLayout(scheme_container)
        scheme_row.setContentsMargins(0, 0, 0, 0)
        scheme_row.setSpacing(2)
        scheme_row.addWidget(QLabel("Classification Scheme:"))

        self.scheme_combo = QComboBox()
        scheme_row.addWidget(self.scheme_combo)

        form.addRow(scheme_container)

        metric_container = QWidget()
        metric_layout = QVBoxLayout(metric_container)
        metric_layout.setSpacing(4)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.addWidget(QLabel("Metric Status:"))

        self.metric_status_group = QButtonGroup(self)
        self.metric_status_container = QWidget()
        self.metric_status_layout = QHBoxLayout(self.metric_status_container)
        self.metric_status_layout.setSpacing(8)
        self.metric_status_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.addWidget(self.metric_status_container)

        form.addRow(metric_container)

        self.scheme_combo.currentTextChanged.connect(self._on_scheme_combo_changed)

    def _add_toggle_controls(self, form):
        """Build the user-defined checkboxes, wrapping across a grid."""
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)

        for index, spec in enumerate(self.context.toggles):
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(4)

            box = QCheckBox(spec.label)
            if spec.shortcut:
                box.setShortcut(spec.shortcut)
            box.stateChanged.connect(
                lambda _state, key=spec.key: self._on_toggle_changed(key)
            )
            self.toggle_boxes[spec.key] = box
            cell_layout.addWidget(box)

            if spec.counter:
                counter = QSpinBox()
                counter.setRange(spec.counter.minimum, spec.counter.maximum)
                counter.setSpecialValueText("")
                counter.setEnabled(False)
                counter.setFixedWidth(48)
                counter.valueChanged.connect(
                    lambda value, key=spec.key: self.counterChanged.emit(key, value)
                )
                counter.valueChanged.connect(self.userEdited)
                self.counter_boxes[spec.key] = counter
                cell_layout.addWidget(QLabel(spec.counter.label))
                cell_layout.addWidget(counter)

            cell_layout.addStretch(1)
            # A QCheckBox reports the full width of its label as its minimum
            # and cannot wrap, so a grid of them would hold the sidebar open.
            # The label is repeated as a tooltip for when it is clipped.
            box.setMinimumWidth(TOGGLE_MIN_WIDTH)
            if not box.toolTip():
                box.setToolTip(spec.label)
            cell.setMinimumWidth(TOGGLE_MIN_WIDTH)
            grid.addWidget(cell, index // TOGGLE_COLUMNS, index % TOGGLE_COLUMNS)

        container = QWidget()
        container.setLayout(grid)
        form.addRow(container)

    def _add_notes_controls(self, form):
        row = QHBoxLayout()
        label = "User Notes:" if self.context.normalized_mode == "reviewer" else "Notes:"
        self.notes_label = QLabel(label)
        self.notes_edit = QLineEdit()
        self.notes_edit.textEdited.connect(self.userEdited)
        row.addWidget(self.notes_label)
        row.addWidget(self.notes_edit)
        form.addRow(row)

    def _build_reviewer_group(self):
        self.reviewer_group = QGroupBox("Reviewer Tools")
        layout = QVBoxLayout()

        notes_row = QHBoxLayout()
        self.reviewer_notes_label = QLabel("Reviewer Notes:")
        self.reviewer_notes_edit = QLineEdit()
        self.reviewer_notes_edit.textEdited.connect(self.userEdited)
        notes_row.addWidget(self.reviewer_notes_label)
        notes_row.addWidget(self.reviewer_notes_edit)
        layout.addLayout(notes_row)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        buttons = QHBoxLayout()
        for action, label in (("accept", "Accept"), ("reject", "Reject")):
            button = configure_button(QPushButton(label))
            button.clicked.connect(
                lambda _checked=False, name=action: self.actionTriggered.emit(name)
            )
            self.control_buttons[action] = button
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.reviewer_group.setLayout(layout)
        self._mode_widgets["reviewer"].append(self.reviewer_group)
        return self.reviewer_group

    def _build_control_block(self):
        controls = QVBoxLayout()
        expandable = bool(self.context.expandable_field_keys)
        open_group = None
        row = None

        for spec in CONTROL_SPECS:
            if spec.requires_expandable_fields and not expandable:
                continue
            if spec.action == RESTRICTION_BEFORE_ACTION:
                open_group, row = None, None
                self._add_restriction_controls(controls)

            button = configure_button(QPushButton(spec.label))
            button.clicked.connect(
                lambda _checked=False, action=spec.action: self.actionTriggered.emit(
                    action
                )
            )
            if spec.shortcut:
                button.setShortcut(spec.shortcut)

            # Paired controls (previous/next) sit side by side on one row.
            if spec.group and spec.group == open_group:
                row.addWidget(button)
            elif spec.group:
                row = QHBoxLayout()
                row.setSpacing(4)
                row.addWidget(button)
                controls.addLayout(row)
                open_group = spec.group
            else:
                open_group, row = None, None
                controls.addWidget(button)

            self.control_buttons[spec.action] = button
            self._register_modes(button, spec.modes)

        controls.addStretch()
        return controls

    def _add_restriction_controls(self, controls):
        self.restriction_label = QLabel("Restrict to:")
        self.restriction_combo = QComboBox()
        self.restriction_combo.addItems(list(self.context.restriction_options))
        controls.addWidget(self.restriction_label)
        controls.addWidget(self.restriction_combo)
        for widget in (self.restriction_label, self.restriction_combo):
            self._register_modes(widget, ("dev", "reviewer"))

    def _register_modes(self, widget, modes):
        """Record which modes show ``widget``. Unregistered widgets always show."""
        if set(modes) == set(ALL_MODES):
            return
        for mode in modes:
            self._mode_widgets[mode].append(widget)

    # ------------------------------------------------------------------
    # Internal signal adapters
    # ------------------------------------------------------------------
    def _on_toggle_changed(self, key):
        """A checkbox owns its companion counter: live only while ticked."""
        checked = self.toggle_boxes[key].isChecked()
        if key in self.counter_boxes:
            self.set_counter_enabled(key, checked)
            if not checked:
                self.set_counter(key, 0)
        self.toggleChanged.emit(key, checked)
        self.userEdited.emit()

    def _on_metric_status_toggled(self, checked):
        """Only the radio being switched on is a change worth reporting."""
        if checked:
            self.userEdited.emit()

    def _on_scheme_combo_changed(self, name):
        self.rebuild_metric_status_options(name)
        self.schemeChanged.emit(name)
        self.userEdited.emit()

    # ------------------------------------------------------------------
    # Keyboard navigation
    # ------------------------------------------------------------------
    def focus_widgets(self) -> list[QWidget]:
        """Every sidebar input, in the order Tab should visit them."""
        widgets: list[QWidget] = list(self.field_editors.values())
        widgets.append(self.scheme_combo)
        widgets.extend(self.metric_status_buttons.values())
        for key, box in self.toggle_boxes.items():
            widgets.append(box)
            if key in self.counter_boxes:
                widgets.append(self.counter_boxes[key])
        widgets.append(self.notes_edit)
        widgets.append(self.reviewer_notes_edit)
        return [widget for widget in widgets if widget is not None]

    def apply_focus_chain(self) -> None:
        """Make Tab / Shift+Tab walk the sidebar inputs in visual order.

        Re-applied whenever the metric-status radios are rebuilt, since those
        widgets are destroyed and recreated when the scheme changes.
        """
        if not self._focus_chain_ready:
            return
        widgets = self.focus_widgets()
        for current, following in zip(widgets, widgets[1:]):
            QWidget.setTabOrder(current, following)

    # ------------------------------------------------------------------
    # Reading state
    # ------------------------------------------------------------------
    def field_text(self, key: str) -> str:
        editor = self.field_editors.get(key)
        return editor.toPlainText().strip() if editor else ""

    def field_texts(self) -> dict[str, str]:
        return {key: self.field_text(key) for key in self.field_editors}

    def notes_text(self) -> str:
        return self.notes_edit.text().strip()

    def reviewer_notes_text(self) -> str:
        return self.reviewer_notes_edit.text().strip()

    def toggles(self) -> dict[str, bool]:
        return {key: box.isChecked() for key, box in self.toggle_boxes.items()}

    def is_toggled(self, key: str) -> bool:
        box = self.toggle_boxes.get(key)
        return bool(box and box.isChecked())

    def counters(self) -> dict[str, int]:
        return {key: box.value() for key, box in self.counter_boxes.items()}

    def counter(self, key: str) -> int:
        box = self.counter_boxes.get(key)
        return box.value() if box else 0

    def metric_status(self) -> str:
        for key, button in self.metric_status_buttons.items():
            if button.isChecked():
                return key
        return ""

    def metric_status_labels(self) -> list[str]:
        return [str(key) for key in self.metric_status_buttons]

    def scheme_name(self) -> str:
        return self.scheme_combo.currentText()

    def restriction_choice(self) -> str:
        return self.restriction_combo.currentText()

    def highlight_color(self, key: str) -> QColor:
        return self._highlight_colors.get(key, QColor("#FFFF00"))

    def transfer_targets(self) -> list[tuple[str, str]]:
        """Fields the content panel may push text into, in display order."""
        return [(spec.key, spec.label) for spec in self.context.fields]

    # ------------------------------------------------------------------
    # Presenting state
    # ------------------------------------------------------------------
    def set_field_text(self, key: str, value) -> None:
        editor = self.field_editors.get(key)
        if editor is None:
            return
        editor.blockSignals(True)
        editor.setPlainText(value or "")
        editor.blockSignals(False)

    def set_field_texts(self, values) -> None:
        for key in self.field_editors:
            self.set_field_text(key, values.get(key, ""))

    def clear_fields(self) -> None:
        for editor in self.field_editors.values():
            editor.clear()

    def focus_field(self, key: str) -> None:
        editor = self.field_editors.get(key)
        if editor is not None:
            editor.setFocus()

    def set_notes_text(self, value) -> None:
        self._set_line_edit(self.notes_edit, value)

    def set_reviewer_notes_text(self, value) -> None:
        self._set_line_edit(self.reviewer_notes_edit, value)

    @staticmethod
    def _set_line_edit(widget, value, focus: bool = False) -> None:
        widget.blockSignals(True)
        widget.setText(value or "")
        widget.blockSignals(False)
        if focus:
            widget.setFocus()

    def set_toggle(self, key: str, checked: bool, notify: bool = False) -> None:
        """Set one checkbox.

        Loading a row presents state and must stay silent, so signals are
        blocked by default. ``notify=True`` lets the change behave like a
        click — the companion counter follows it and listeners are told.
        """
        box = self.toggle_boxes.get(key)
        if box is None:
            return
        box.blockSignals(not notify)
        box.setChecked(bool(checked))
        box.blockSignals(False)

    def set_toggles(self, values) -> None:
        for key in self.toggle_boxes:
            self.set_toggle(key, values.get(key, False))

    def set_counter(self, key: str, value) -> None:
        box = self.counter_boxes.get(key)
        if box is None:
            return
        box.blockSignals(True)
        box.setValue(int(value or 0))
        box.blockSignals(False)

    def set_counters(self, values) -> None:
        for key in self.counter_boxes:
            self.set_counter(key, values.get(key, 0))

    def set_counter_enabled(self, key: str, enabled: bool) -> None:
        box = self.counter_boxes.get(key)
        if box is not None:
            box.setEnabled(bool(enabled))

    def set_entry_position(self, current: int, total: int) -> None:
        self.entry_index_label.setText(f"Entry {current:,} of {total:,}")

    def set_statistic_specs(self, specs) -> None:
        """Rebuild the pinned-statistics block from ``(key, label)`` pairs.

        Called whenever the user's choice changes, so the block appears and
        disappears without a restart. Passing nothing empties it, which is the
        default state.
        """
        while self.statistics_layout.count():
            item = self.statistics_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.statistic_labels.clear()

        for key, title in specs or ():
            label = QLabel(f"{title}: —")
            # Lighter than the entry counter below it: this is context for the
            # work, not the work itself.
            label.setStyleSheet("color: #4A5A6B;")
            label.setWordWrap(True)
            self.statistics_layout.addWidget(label)
            self.statistic_labels[key] = label

    def set_statistic_values(self, values) -> None:
        for key, label in self.statistic_labels.items():
            if key not in values:
                continue
            title = label.text().split(":", 1)[0]
            label.setText(f"{title}: {values[key]}")

    def set_info_values(self, values) -> None:
        for key, label in self.info_labels.items():
            if key not in values:
                continue
            title = label.text().split(":", 1)[0]
            label.setText(f"{title}: {values[key]}")

    def set_warning(self, text) -> None:
        """Show a prominent problem message, or hide the banner when empty."""
        self.warning_label.setText(text or "")
        self.warning_label.setVisible(bool(text))

    def warning_text(self) -> str:
        return self.warning_label.text()

    def set_hint(self, text) -> None:
        self.hint_label.setText(text or "")

    def set_metric_status(self, value) -> None:
        for key, button in self.metric_status_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == value)
            button.blockSignals(False)

    def select_metric_status_by_index(self, index: int) -> None:
        buttons = list(self.metric_status_buttons.values())
        if 0 <= index < len(buttons):
            buttons[index].setChecked(True)

    def clear_metric_status(self) -> None:
        """Only ever reached from the keyboard, so it counts as an edit."""
        self.metric_status_group.setExclusive(False)
        for button in self.metric_status_buttons.values():
            button.setChecked(False)
        self.metric_status_group.setExclusive(True)
        self.userEdited.emit()

    def set_scheme(self, name: str) -> None:
        self.scheme_combo.blockSignals(True)
        self.scheme_combo.setCurrentText(name)
        self.scheme_combo.blockSignals(False)
        self.rebuild_metric_status_options(name)

    def set_scheme_options(self, classes, default_name: str = "") -> None:
        """Repopulate the scheme combo from ``{name: {"option_types": [...]}}``."""
        self.context.evaluation_classes = classes or {}
        self.context.default_class = default_name or ""
        names = list(self.context.evaluation_classes)

        self.scheme_combo.blockSignals(True)
        self.scheme_combo.clear()
        self.scheme_combo.addItems(names)
        self.scheme_combo.blockSignals(False)

        if default_name in names:
            self.scheme_combo.setCurrentText(default_name)
            self.rebuild_metric_status_options(default_name)
        elif names:
            self.scheme_combo.setCurrentIndex(0)
            self.rebuild_metric_status_options(names[0])
        else:
            self.rebuild_metric_status_options(None)

    def rebuild_metric_status_options(self, scheme_name) -> None:
        for button in self.metric_status_buttons.values():
            self.metric_status_group.removeButton(button)
            button.setParent(None)
            button.deleteLater()
        self.metric_status_buttons = {}

        while self.metric_status_layout.count():
            item = self.metric_status_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        classes = self.context.evaluation_classes or {}
        options = []
        if scheme_name and scheme_name in classes:
            options = classes[scheme_name].get("option_types", []) or []

        for option in options:
            button = QRadioButton(str(option))
            button.toggled.connect(self._on_metric_status_toggled)
            self.metric_status_group.addButton(button)
            self.metric_status_buttons[str(option)] = button
            self.metric_status_layout.addWidget(button)

        self.metric_status_layout.addStretch(1)
        self.apply_focus_chain()

    def set_restriction_options(self, options) -> None:
        self.restriction_combo.blockSignals(True)
        self.restriction_combo.clear()
        self.restriction_combo.addItems(list(options))
        self.restriction_combo.blockSignals(False)

    def apply_mode(self, mode: str) -> None:
        """Show the widget set for ``mode`` and hide the others."""
        mode = (mode or "user").lower()
        for other in ALL_MODES:
            if other == mode:
                continue
            for widget in self._mode_widgets[other]:
                widget.setVisible(False)
        # Applied last so a widget shared between modes ends up visible.
        for widget in self._mode_widgets.get(mode, []):
            widget.setVisible(True)

    def trigger_add_level(self, key: str) -> None:
        """Behave as though the user clicked the ``+`` button for ``key``."""
        button = self.add_level_buttons.get(key)
        if button is not None:
            button.click()
        elif key in self.field_editors:
            self.addLevelRequested.emit(key)
