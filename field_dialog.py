"""Dialog for defining the left sidebar's editable fields.

Each field is one MID column. A column the MID does not have yet is created
when it loads, so a new field needs no spreadsheet work first. A field is a
free-text box unless it is given options, in which case it is a dropdown or
a row of radio buttons; and it may be one level of a nested hierarchy, which
gives it a ``+`` button for adding a row beneath the current one.
"""

from __future__ import annotations

import pandas as pd
from PyQt5.QtWidgets import (
    QCheckBox,
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
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from logger import setup_logger
from mid_schema import FIELD_KINDS, FieldConfig, MIDSchema, normalize_sheet_name

#: What each kind is called in the dialog.
KIND_LABELS = {
    "text": "Text box",
    "dropdown": "Dropdown list",
    "radio": "Radio buttons",
}


def sheet_columns(settings) -> list[str]:
    """The configured MID's column names, or nothing if it cannot be read.

    Only a convenience for the column picker: a field may name a column the
    sheet does not have yet.
    """
    path = settings.get("MIDLocation", "")
    if not path:
        return []
    try:
        frame = pd.read_excel(
            path,
            sheet_name=normalize_sheet_name(settings.get("MIDSheetName", 0)),
            nrows=0,
        )
    except Exception:
        return []
    return [str(column).strip() for column in frame.columns]


class FieldDialog(QDialog):
    """List the configured fields and edit the selected one."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.logger = setup_logger()
        self.setWindowTitle("Configure Fields")
        self.resize(680, 560)

        self.settings = settings
        self.schema = MIDSchema.from_settings(settings)
        self.definitions = [field.to_mapping() for field in self.schema.fields]
        self.columns = sheet_columns(settings)
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
            "Fields appear in the left sidebar in this order. Each one edits "
            "the MID column you name; the column is created if the MID does "
            "not already have it. Give a field options to make it a list "
            "instead of a text box, and mark it as a hierarchy level to get "
            'a "+" button that adds a row beneath the current one.'
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
        group = QGroupBox("Selected field")
        form = QFormLayout()

        # Editable so a column the sheet lacks can still be typed in.
        self.column_combo = QComboBox()
        self.column_combo.setEditable(True)
        self.column_combo.setInsertPolicy(QComboBox.NoInsert)
        self.column_combo.addItems(self.columns)
        self.column_combo.setCurrentText("")

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Shown beside the field (optional)")

        self.kind_combo = QComboBox()
        for kind in FIELD_KINDS:
            self.kind_combo.addItem(KIND_LABELS[kind], kind)

        self.options_edit = QPlainTextEdit()
        self.options_edit.setPlaceholderText("One option per line")
        self.options_edit.setMaximumHeight(90)

        self.hierarchy_check = QCheckBox('Hierarchy level (adds a "+" button)')
        self.shortcut_edit = QLineEdit()
        self.shortcut_edit.setPlaceholderText('Shortcut for "+", e.g. F2 (optional)')

        form.addRow("MID column:", self.column_combo)
        form.addRow("Label:", self.label_edit)
        form.addRow("Edited as:", self.kind_combo)
        form.addRow("Options:", self.options_edit)
        form.addRow(self.hierarchy_check)
        form.addRow('"+" shortcut:', self.shortcut_edit)

        self.column_combo.currentTextChanged.connect(self._commit_editor)
        self.label_edit.textChanged.connect(self._commit_editor)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self.options_edit.textChanged.connect(self._commit_editor)
        self.hierarchy_check.stateChanged.connect(self._on_hierarchy_toggled)
        self.shortcut_edit.textChanged.connect(self._commit_editor)

        group.setLayout(form)
        return group

    def _editor_widgets(self):
        return (
            self.column_combo,
            self.label_edit,
            self.kind_combo,
            self.options_edit,
            self.hierarchy_check,
            self.shortcut_edit,
        )

    # ------------------------------------------------------------------
    # List <-> editor
    # ------------------------------------------------------------------
    @staticmethod
    def _summary(definition) -> str:
        field = FieldConfig.from_mapping(definition)
        if field is None:
            return "(unnamed)"
        summary = f"{field.label}  →  {field.column}"
        if field.is_choice:
            summary += f"  ({KIND_LABELS[field.kind]}, {len(field.options)} options)"
        if field.hierarchy:
            summary += "  [+]"
        return summary

    def _refresh_list(self):
        current = self.list_widget.currentRow()
        self._loading = True
        self.list_widget.clear()
        for definition in self.definitions:
            self.list_widget.addItem(QListWidgetItem(self._summary(definition)))
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

        definition = definition or {}
        self.column_combo.setCurrentText(definition.get("column", ""))
        self.label_edit.setText(definition.get("label", ""))
        index = self.kind_combo.findData(definition.get("kind", "text"))
        self.kind_combo.setCurrentIndex(max(0, index))
        self.options_edit.setPlainText("\n".join(definition.get("options", [])))
        self.hierarchy_check.setChecked(bool(definition.get("hierarchy", False)))
        self.shortcut_edit.setText(definition.get("addShortcut", ""))
        self._apply_dependent_enabled()
        self._loading = False

    def _apply_dependent_enabled(self):
        editing = self.kind_combo.isEnabled()
        kind = str(self.kind_combo.currentData() or "text")
        self.options_edit.setEnabled(editing and kind != "text")
        self.shortcut_edit.setEnabled(editing and self.hierarchy_check.isChecked())

    def _on_kind_changed(self, _index):
        self._apply_dependent_enabled()
        self._commit_editor()

    def _on_hierarchy_toggled(self, _state):
        self._apply_dependent_enabled()
        self._commit_editor()

    def _commit_editor(self):
        """Write the editor back into the selected definition as it is typed."""
        if self._loading:
            return
        row = self.list_widget.currentRow()
        if not (0 <= row < len(self.definitions)):
            return

        definition = self.definitions[row]
        definition["column"] = self.column_combo.currentText().strip()
        definition["label"] = self.label_edit.text().strip()
        definition["kind"] = str(self.kind_combo.currentData() or "text")
        definition["options"] = [
            line.strip()
            for line in self.options_edit.toPlainText().splitlines()
            if line.strip()
        ]
        definition["hierarchy"] = self.hierarchy_check.isChecked()
        definition["addShortcut"] = self.shortcut_edit.text().strip()

        self._refresh_list()

    # ------------------------------------------------------------------
    # List operations
    # ------------------------------------------------------------------
    def _add(self):
        self.definitions.append(
            {
                "column": "",
                "label": "",
                "kind": "text",
                "options": [],
                "hierarchy": False,
                "addShortcut": "",
            }
        )
        self._refresh_list()
        self.list_widget.setCurrentRow(len(self.definitions) - 1)
        self.column_combo.setFocus()

    def _remove(self):
        row = self.list_widget.currentRow()
        if not (0 <= row < len(self.definitions)):
            return
        removed = self.definitions.pop(row)
        self.logger.info(f"Removed field '{removed.get('column', '')}'")
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
    def build_schema(self) -> MIDSchema:
        """The schema with these fields in it.

        Raises ``ValueError`` when the fields do not make sense, which is
        what the OK button turns into a warning.
        """
        incomplete = [
            index + 1
            for index, definition in enumerate(self.definitions)
            if not str(definition.get("column", "")).strip()
        ]
        if incomplete:
            raise ValueError(
                f"Every field needs a MID column. Missing for field(s) {incomplete}."
            )
        columns = [str(definition["column"]).strip() for definition in self.definitions]
        if len(set(columns)) != len(columns):
            raise ValueError(
                "Two fields edit the same MID column. Give each its own."
            )
        for definition in self.definitions:
            field = FieldConfig.from_mapping(definition)
            if field is not None and field.is_choice and not field.options:
                raise ValueError(
                    f"'{field.column}' is a {KIND_LABELS[field.kind].lower()} "
                    "but has no options. Add some, or make it a text box."
                )
        return self.schema.with_fields(self.definitions)

    def accept(self):
        try:
            schema = self.build_schema()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Field Configuration", str(exc))
            return

        self.updated_settings["midSchema"] = schema.to_mapping()
        self.logger.info(f"Saved {len(schema.fields)} field definition(s)")
        super().accept()
