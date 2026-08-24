"""Dialog for defining buttons that compute one editable field from the others.

A button names a target field and an arithmetic expression over the editable
fields — ``Match = LMIG_Exp * 0.10``. Expressions are checked here so a broken
one is caught where it is written rather than when it is pressed.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QComboBox,
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

import field_formula
from app_settings import normalize_field_buttons
from logger import setup_logger
from mid_schema import MIDSchema


class FieldButtonDialog(QDialog):
    """List the configured buttons and edit the selected one."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.logger = setup_logger()
        self.setWindowTitle("Configure Field Buttons")
        self.resize(640, 520)

        self.settings = settings
        self.definitions = normalize_field_buttons(settings.get("fieldButtons"))
        self.updated_settings = {}
        self._loading = False

        try:
            self.fields = list(MIDSchema.from_settings(settings).interaction_columns)
        except ValueError:
            self.fields = []
        self.variables = field_formula.variable_names(self.fields)

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
            "Each button computes a value from the editable fields and writes "
            "it into one of them. Formulas may use the field names below, "
            "numbers, + - * / % **, and abs / min / max / round."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        available = QLabel(
            "Available: "
            + (", ".join(sorted(self.variables)) or "no editable fields configured")
        )
        available.setWordWrap(True)
        available.setStyleSheet("color: #555; font-family: monospace;")
        layout.addWidget(available)

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
        group = QGroupBox("Selected button")
        form = QFormLayout()

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("10%")

        self.target_combo = QComboBox()
        self.target_combo.addItems(self.fields)

        self.expression_edit = QLineEdit()
        self.expression_edit.setPlaceholderText("LMIG_Exp * 0.10")

        self.decimals_spin = QSpinBox()
        self.decimals_spin.setRange(0, 6)
        self.decimals_spin.setValue(2)

        form.addRow("Button text:", self.label_edit)
        form.addRow("Writes into:", self.target_combo)
        form.addRow("Formula:", self.expression_edit)
        form.addRow("Decimal places:", self.decimals_spin)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        form.addRow(self.status_label)

        self.label_edit.textChanged.connect(self._commit_editor)
        self.expression_edit.textChanged.connect(self._commit_editor)
        self.target_combo.currentTextChanged.connect(self._commit_editor)
        self.decimals_spin.valueChanged.connect(self._commit_editor)

        group.setLayout(form)
        return group

    # ------------------------------------------------------------------
    # List <-> editor
    # ------------------------------------------------------------------
    def _refresh_list(self):
        current = self.list_widget.currentRow()
        self._loading = True
        self.list_widget.clear()
        for definition in self.definitions:
            self.list_widget.addItem(
                QListWidgetItem(
                    f"{definition['label']}:  {definition['target']} = "
                    f"{definition['expression']}"
                )
            )
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
        for widget in (
            self.label_edit,
            self.target_combo,
            self.expression_edit,
            self.decimals_spin,
        ):
            widget.setEnabled(enabled)

        definition = definition or {}
        self.label_edit.setText(definition.get("label", ""))
        self.expression_edit.setText(definition.get("expression", ""))
        self.decimals_spin.setValue(int(definition.get("decimals", 2)))
        target = definition.get("target", "")
        if target and self.target_combo.findText(target) < 0:
            self.target_combo.addItem(target)
        self.target_combo.setCurrentText(target)
        self._loading = False
        self._check_expression()

    def _commit_editor(self):
        if self._loading:
            return
        row = self.list_widget.currentRow()
        if not (0 <= row < len(self.definitions)):
            return

        definition = self.definitions[row]
        definition["label"] = self.label_edit.text().strip()
        definition["target"] = self.target_combo.currentText().strip()
        definition["expression"] = self.expression_edit.text().strip()
        definition["decimals"] = self.decimals_spin.value()
        definition["tooltip"] = f"{definition['target']} = {definition['expression']}"

        self._refresh_list()
        self._check_expression()

    def _check_expression(self):
        """Report on the formula as it is typed."""
        expression = self.expression_edit.text().strip()
        if not expression:
            self.status_label.setText("")
            return
        error = self._expression_error(expression)
        if error:
            self.status_label.setText(f"⚠ {error}")
            self.status_label.setStyleSheet("color: #8A1F11;")
        else:
            self.status_label.setText("✓ Formula reads correctly.")
            self.status_label.setStyleSheet("color: #1F7A34;")

    def _expression_error(self, expression) -> str:
        try:
            field_formula.validate(expression, self.fields)
        except field_formula.FormulaError as exc:
            return str(exc)
        return ""

    # ------------------------------------------------------------------
    # List operations
    # ------------------------------------------------------------------
    def _add(self):
        self.definitions.append(
            {
                "key": "",
                "label": "New button",
                "target": self.fields[0] if self.fields else "",
                "expression": "",
                "decimals": 2,
                "tooltip": "",
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
        self.logger.info(f"Removed field button '{removed.get('label', '')}'")
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
        for definition in self.definitions:
            name = definition["label"] or "(unnamed)"
            if not (definition["label"] and definition["target"]):
                QMessageBox.warning(
                    self,
                    "Incomplete Button",
                    f"'{name}' needs both a button text and a target field.",
                )
                return
            error = self._expression_error(definition["expression"])
            if error:
                QMessageBox.warning(
                    self, "Invalid Formula", f"'{name}': {error}"
                )
                return

        self.updated_settings["fieldButtons"] = normalize_field_buttons(
            self.definitions
        )
        self.logger.info(f"Saved {len(self.definitions)} field button(s)")
        super().accept()
