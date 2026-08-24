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

from mid_schema import MIDSchema, entry_label_choices, normalize_sheet_name


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

        self.entry_label_combo = QComboBox()
        for key, label in entry_label_choices():
            self.entry_label_combo.addItem(label, key)
        index = self.entry_label_combo.findData(self.schema.entry_label)
        if index >= 0:
            self.entry_label_combo.setCurrentIndex(index)
        self.entry_label_combo.setToolTip(
            "How each row is named in the viewer, the status bar, and the logs."
        )
        form.addRow("Entry label:", self.entry_label_combo)
        layout.addLayout(form)

        self.entry_label_preview = QLabel("")
        self.entry_label_preview.setWordWrap(True)
        layout.addWidget(self.entry_label_preview)
        self.entry_label_combo.currentIndexChanged.connect(
            self._refresh_entry_label_preview
        )
        for combo in (self.x_combo, self.y_combo, self.document_combo):
            combo.currentTextChanged.connect(self._refresh_entry_label_preview)
        self._refresh_entry_label_preview()

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
            # Selection only takes on an item the list already owns, so this
            # has to follow addItem — otherwise reopening the dialog and
            # pressing OK would clear every editable column.
            self.interaction_list.addItem(item)
            item.setSelected(column in selected)
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

    def _refresh_entry_label_preview(self):
        """Show the chosen format applied to the columns selected above."""
        x_column = self._combo_value(self.x_combo)
        y_column = self._combo_value(self.y_combo)
        document_column = self._combo_value(self.document_combo)
        # Sample each configured column with its own name, so the preview
        # reads as the real thing rather than as placeholders.
        sample = {
            column: value
            for column, value in (
                (x_column, x_column or "X"),
                (y_column, y_column or "Y"),
                (document_column, document_column or "filename.pdf"),
            )
            if column
        }
        try:
            schema = MIDSchema(
                x_column=x_column,
                y_column=y_column,
                # Only the label matters here, so sidestep the configuration
                # rules the OK button is responsible for enforcing.
                interaction_columns=("preview",),
                document_column=document_column,
                entry_label=str(self.entry_label_combo.currentData() or ""),
            )
            preview = schema.observation_label(sample)
        except ValueError:
            preview = ""
        self.entry_label_preview.setText(
            f"Rows will be labelled: {preview}" if preview else ""
        )

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

    def build_schema(self) -> MIDSchema:
        """The schema the current selections describe.

        Raises ``ValueError`` when they do not describe a usable one, which is
        what the OK button turns into a warning.
        """
        interaction_columns = [
            item.text() for item in self.interaction_list.selectedItems()
        ]
        schema = MIDSchema(
            x_column=self._combo_value(self.x_combo),
            y_column=self._combo_value(self.y_combo),
            interaction_columns=tuple(interaction_columns),
            document_column=self._combo_value(self.document_combo),
            page_column=self._combo_value(self.page_combo),
            format_column=self._combo_value(self.format_combo),
            keyword_column=self._combo_value(self.keyword_combo),
            entry_label=str(self.entry_label_combo.currentData() or ""),
        )
        schema.validate_configuration()
        schema.validate_columns(self.columns)
        return schema

    def accept(self):
        try:
            schema = self.build_schema()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid MID Configuration", str(exc))
            return

        self.updated_schema = schema
        super().accept()
