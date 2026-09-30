"""Dialog for defining the left sidebar's checkboxes.

Each checkbox writes true/false to one MID column. A column that the MID does
not have yet is created when it loads, so a new checkbox needs no spreadsheet
work first.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app_settings import normalize_checkboxes
from logger import setup_logger


class CheckboxDialog(QDialog):
    """List the configured checkboxes and edit the selected one."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.logger = setup_logger()
        self.setWindowTitle("Configure Checkboxes")
        self.resize(620, 520)

        self.settings = settings
        self.definitions = normalize_checkboxes(settings.get("checkboxes"))
        self.updated_settings = {}
        self._loading = False

        self._init_ui()
        self._refresh_list()
        if self.definitions:
            self.list_widget.setCurrentRow(0)
        else:
            self._show_definition(None)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _init_ui(self):
        layout = QVBoxLayout(self)

        explanation = QLabel(
            "Checkboxes appear in the left sidebar in this order. Each one "
            "stores true or false in the MID column you name; the column is "
            "created if the MID does not already have it."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        body = QHBoxLayout()

        list_column = QVBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        list_column.addWidget(self.list_widget)

        buttons = QHBoxLayout()
        for label, handler in (
            ("Add", self._add),
            ("Remove", self._remove),
            ("Up", lambda: self._move(-1)),
            ("Down", lambda: self._move(1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        list_column.addLayout(buttons)
        body.addLayout(list_column, 1)

        body.addWidget(self._build_editor(), 1)
        layout.addLayout(body)

        dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)

    def _build_editor(self):
        group = QGroupBox("Selected checkbox")
        form = QFormLayout()

        self.label_edit = QLineEdit()
        self.column_edit = QLineEdit()
        self.shortcut_edit = QLineEdit()
        self.message_edit = QLineEdit()

        self.column_edit.setPlaceholderText("_flag")
        self.shortcut_edit.setPlaceholderText("Ctrl+F (optional)")
        self.message_edit.setPlaceholderText("Status-bar text (optional)")

        form.addRow("Label:", self.label_edit)
        form.addRow("MID column:", self.column_edit)
        form.addRow("Shortcut:", self.shortcut_edit)
        form.addRow("Status message:", self.message_edit)

        self.counter_check = QCheckBox("Add a number box, live while ticked")
        self.counter_check.stateChanged.connect(self._on_counter_toggled)
        form.addRow(self.counter_check)

        self.counter_column_edit = QLineEdit()
        self.counter_label_edit = QLineEdit()
        self.counter_maximum_spin = QSpinBox()
        self.counter_maximum_spin.setRange(1, 9999)
        self.counter_maximum_spin.setValue(20)

        self.counter_column_edit.setPlaceholderText("years_to_evaluation")
        self.counter_label_edit.setPlaceholderText("Years to eval:")

        form.addRow("Number column:", self.counter_column_edit)
        form.addRow("Number label:", self.counter_label_edit)
        form.addRow("Largest value:", self.counter_maximum_spin)

        for widget in self._editor_widgets():
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._commit_editor)
        self.counter_maximum_spin.valueChanged.connect(self._commit_editor)

        group.setLayout(form)
        return group

    def _editor_widgets(self):
        return (
            self.label_edit,
            self.column_edit,
            self.shortcut_edit,
            self.message_edit,
            self.counter_column_edit,
            self.counter_label_edit,
        )

    # ------------------------------------------------------------------
    # List <-> editor
    # ------------------------------------------------------------------
    def _refresh_list(self):
        current = self.list_widget.currentRow()
        self._loading = True
        self.list_widget.clear()
        for definition in self.definitions:
            summary = f"{definition['label']}  →  {definition['column']}"
            if definition["counter"]:
                summary += f"  (+ {definition['counter']['column']})"
            self.list_widget.addItem(QListWidgetItem(summary))
        self._loading = False
        if 0 <= current < len(self.definitions):
            self.list_widget.setCurrentRow(current)

    def _on_row_changed(self, row):
        if self._loading:
            return
        self._show_definition(
            self.definitions[row] if 0 <= row < len(self.definitions) else None
        )

    def _show_definition(self, definition):
        self._loading = True
        enabled = definition is not None
        for widget in self._editor_widgets():
            widget.setEnabled(enabled)
        self.counter_check.setEnabled(enabled)
        self.counter_maximum_spin.setEnabled(enabled)

        definition = definition or {}
        counter = definition.get("counter") or {}
        self.label_edit.setText(definition.get("label", ""))
        self.column_edit.setText(definition.get("column", ""))
        self.shortcut_edit.setText(definition.get("shortcut", ""))
        self.message_edit.setText(definition.get("message", ""))
        self.counter_check.setChecked(bool(counter))
        self.counter_column_edit.setText(counter.get("column", ""))
        self.counter_label_edit.setText(counter.get("label", ""))
        self.counter_maximum_spin.setValue(int(counter.get("maximum", 20) or 20))
        self._apply_counter_enabled()
        self._loading = False

    def _apply_counter_enabled(self):
        enabled = self.counter_check.isChecked() and self.counter_check.isEnabled()
        self.counter_column_edit.setEnabled(enabled)
        self.counter_label_edit.setEnabled(enabled)
        self.counter_maximum_spin.setEnabled(enabled)

    def _on_counter_toggled(self, _state):
        self._apply_counter_enabled()
        self._commit_editor()

    def _commit_editor(self):
        """Write the editor back into the selected definition as it is typed."""
        if self._loading:
            return
        row = self.list_widget.currentRow()
        if not (0 <= row < len(self.definitions)):
            return

        definition = self.definitions[row]
        definition["label"] = self.label_edit.text().strip()
        definition["column"] = self.column_edit.text().strip()
        definition["shortcut"] = self.shortcut_edit.text().strip()
        definition["message"] = self.message_edit.text().strip()
        definition["key"] = definition["column"].lstrip("_") or definition["column"]

        if self.counter_check.isChecked():
            definition["counter"] = {
                "column": self.counter_column_edit.text().strip(),
                "label": self.counter_label_edit.text().strip(),
                "minimum": 0,
                "maximum": self.counter_maximum_spin.value(),
            }
        else:
            definition["counter"] = None

        self._refresh_list()

    # ------------------------------------------------------------------
    # List operations
    # ------------------------------------------------------------------
    def _add(self):
        self.definitions.append(
            {
                "key": "",
                "column": "",
                "label": "New checkbox",
                "shortcut": "",
                "message": "",
                "counter": None,
            }
        )
        self._refresh_list()
        self.list_widget.setCurrentRow(len(self.definitions) - 1)
        self.label_edit.setFocus()

    def _remove(self):
        row = self.list_widget.currentRow()
        if not (0 <= row < len(self.definitions)):
            return
        removed = self.definitions.pop(row)
        self.logger.info(f"Removed checkbox '{removed.get('label', '')}'")
        self._refresh_list()
        if self.definitions:
            self.list_widget.setCurrentRow(min(row, len(self.definitions) - 1))
        else:
            self._show_definition(None)

    def _move(self, offset):
        row = self.list_widget.currentRow()
        target = row + offset
        if not (0 <= row < len(self.definitions) and 0 <= target < len(self.definitions)):
            return
        self.definitions[row], self.definitions[target] = (
            self.definitions[target],
            self.definitions[row],
        )
        self._refresh_list()
        self.list_widget.setCurrentRow(target)

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------
    def accept(self):
        incomplete = [
            definition["label"] or "(unnamed)"
            for definition in self.definitions
            if not definition["column"]
        ]
        if incomplete:
            QMessageBox.warning(
                self,
                "Incomplete Checkbox",
                "Every checkbox needs a MID column. Missing for: "
                f"{', '.join(incomplete)}",
            )
            return

        normalized = normalize_checkboxes(self.definitions)
        if len(normalized) != len(self.definitions):
            QMessageBox.warning(
                self,
                "Duplicate Checkbox",
                "Two checkboxes use the same MID column. Give each its own.",
            )
            return

        self.updated_settings["checkboxes"] = normalized
        self.logger.info(f"Saved {len(normalized)} checkbox definition(s)")
        super().accept()
