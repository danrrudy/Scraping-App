"""Dialog for assigning MID columns to application roles."""

from __future__ import annotations

import pandas as pd
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

from mid_schema import MIDSchema, normalize_sheet_name


USE_XY_PAIR = "<Compose from X/Y>"
USE_FIRST_PAGE = "<Use first page>"
USE_DEFAULT_FORMAT = "<Use default scraper>"
NOT_CONFIGURED = "<Not configured>"

#: Placeholder entries that mean "no column", whatever combo they appear in.
PLACEHOLDERS = frozenset(
    {USE_XY_PAIR, USE_FIRST_PAGE, USE_DEFAULT_FORMAT, NOT_CONFIGURED}
)


class MIDSchemaDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.schema = MIDSchema.from_settings(settings)
        self.columns = self._load_columns()
        self.updated_schema = self.schema
        self.setWindowTitle("Configure MID Columns")
        self.resize(560, 620)
        self._init_ui()

    def _load_columns(self) -> list[str]:
        path = self.settings.get("MIDLocation", "")
        sheet_name = normalize_sheet_name(self.settings.get("MIDSheetName", 0))
        if not path:
            raise ValueError("Select a Master Input Document before configuring columns.")
        try:
            frame = pd.read_excel(path, sheet_name=sheet_name, nrows=0)
        except Exception as exc:
            raise ValueError(f"Could not read MID columns: {exc}") from exc
        columns = [str(column).strip() for column in frame.columns]
        if len(columns) < 2:
            raise ValueError("The MID must contain at least two columns.")
        return columns

    def _combo(self, *, optional_label=None, current="", allow_new=False):
        """Build a role combo.

        ``allow_new`` makes the combo editable so a column that is not in the
        sheet yet can be named; it is created when the MID loads.
        """
        combo = QComboBox()
        if optional_label:
            combo.addItem(optional_label, "")
        for column in self.columns:
            combo.addItem(column, column)
        if allow_new:
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif current and allow_new:
            combo.setEditText(current)
        return combo

    def _init_ui(self):
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Every MID row must say which document it refers to, so the "
            "document filename is the only column that has to already exist "
            "in the sheet.\n\n"
            "X/Y identifiers are optional. Leave them unconfigured, or list "
            "them as editable fields below to assign them from within the app "
            "— you can type a column name that the sheet does not have yet "
            "and it will be created.\n\n"
            "If no filename column is configured, the X/Y pair composes the "
            "filename instead and cannot be edited."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        self.document_combo = self._combo(
            optional_label=USE_XY_PAIR, current=self.schema.document_column
        )
        self.x_combo = self._combo(
            optional_label=NOT_CONFIGURED, current=self.schema.x_column, allow_new=True
        )
        self.y_combo = self._combo(
            optional_label=NOT_CONFIGURED, current=self.schema.y_column, allow_new=True
        )
        self.page_combo = self._combo(
            optional_label=USE_FIRST_PAGE, current=self.schema.page_column
        )
        self.format_combo = self._combo(
            optional_label=USE_DEFAULT_FORMAT, current=self.schema.format_column
        )
        self.keyword_combo = self._combo(
            optional_label=NOT_CONFIGURED, current=self.schema.keyword_column
        )

        form.addRow("Document filename:", self.document_combo)
        form.addRow("X identifier:", self.x_combo)
        form.addRow("Y identifier:", self.y_combo)
        form.addRow("PDF page reference:", self.page_combo)
        form.addRow("Format code:", self.format_combo)
        form.addRow("Search keyword:", self.keyword_combo)
        layout.addLayout(form)

        layout.addWidget(QLabel("Editable MID columns:"))
        self.interaction_list = QListWidget()
        self.interaction_list.setSelectionMode(QListWidget.MultiSelection)
        selected = set(self.schema.interaction_columns)
        # Identifier columns typed in above may not be in the sheet yet, but
        # they still have to be selectable as editable fields.
        listed = list(
            dict.fromkeys([*self.columns, *sorted(selected - set(self.columns))])
        )
        for column in listed:
            item = QListWidgetItem(column)
            item.setSelected(column in selected)
            self.interaction_list.addItem(item)
        layout.addWidget(self.interaction_list)

        self.new_columns_hint = QLabel("")
        self.new_columns_hint.setWordWrap(True)
        layout.addWidget(self.new_columns_hint)
        for combo in (self.x_combo, self.y_combo):
            combo.currentTextChanged.connect(self._refresh_new_column_hint)
        self._refresh_new_column_hint()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _combo_value(combo: QComboBox) -> str:
        if combo.isEditable():
            text = combo.currentText().strip()
            return "" if text in PLACEHOLDERS else text
        return str(combo.currentData() or "")

    def _refresh_new_column_hint(self):
        """Tell the user which named columns are not in the sheet yet."""
        known = set(self.columns)
        new_columns = sorted(
            {
                self._combo_value(self.x_combo),
                self._combo_value(self.y_combo),
            }
            - known
            - {""}
        )
        if new_columns:
            self.new_columns_hint.setText(
                f"Will be created when the MID loads: {', '.join(new_columns)}. "
                "Select them above to make them editable."
            )
        else:
            self.new_columns_hint.setText("")

    def accept(self):
        interaction_columns = [
            item.text() for item in self.interaction_list.selectedItems()
        ]
        try:
            schema = MIDSchema(
                x_column=self._combo_value(self.x_combo),
                y_column=self._combo_value(self.y_combo),
                interaction_columns=tuple(interaction_columns),
                document_column=self._combo_value(self.document_combo),
                page_column=self._combo_value(self.page_combo),
                format_column=self._combo_value(self.format_combo),
                keyword_column=self._combo_value(self.keyword_combo),
            )
            schema.validate_configuration()
            schema.validate_columns(self.columns)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid MID Configuration", str(exc))
            return

        self.updated_schema = schema
        super().accept()
