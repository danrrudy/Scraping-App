# SettingsDialog Class
# This Class implements a pop-up window for the user to modify program settings. These can be written to or read from JSON.

from copy import deepcopy

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QFormLayout, QLineEdit, QHBoxLayout, QMessageBox, QFileDialog, QComboBox, QInputDialog, QWidget
import json
import os
import pandas as pd
from logger import setup_logger
from scraping_tool_dialog import ScrapingToolDialog
from extraction_tool_dialog import ExtractionToolDialog
from class_dialog import ClassDialog
from mid_schema_dialog import MIDSchemaDialog
from checkbox_dialog import CheckboxDialog
from module_settings_dialog import ModuleSettingsDialog
import module_settings
from field_button_dialog import FieldButtonDialog
from statistics_dialog import StatisticsSelectionDialog
import mid_template


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None, active_modules=(), mode="user"):
        """``active_modules`` are the module ids currently on screen.

        Outside dev mode the module settings tab shows only those; dev mode
        shows every module the program knows about.
        """
        super().__init__(parent)
        self.setWindowTitle("Settings")
        # Make a copy of the settings so that changes can be confirmed
        self.settings = deepcopy(settings)
        self.active_modules = tuple(active_modules)
        self.mode = str(mode or settings.get("userMode", "User")).lower()
        self._init_ui()

    def _init_ui(self):
        self.logger = setup_logger()
        layout = QVBoxLayout(self)

        # Mapping of setting keys to possible options
        self.options = {
            "fontSize": ["10", "12", "14", "16", "18"],
            "loggingLevel": ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
            #logFileDirectory: Filepath, no options
            "consoleOutput": ["File", "Console", "Both"],
            "userMode": ["User", "Dev", "Reviewer"]
        }

        # Create a form layout to display and edit settings
        form_layout = QFormLayout()
        # unsaved settings changes
        self.inputs = {}

        # Pull scraping tools to load the default selector
        scraping_tools = self.settings.get("scrapingTools", {})
        scraper_names = list(scraping_tools.keys())
        self.options["defaultScraper"] = scraper_names

        # For each key/value pair in the options dictionary above, create a QComboBox (drop-down)
        for key, value in self.settings.items():
            if key in self.options:
                combo = QComboBox()
                combo.addItems(self.options[key])
                combo.setCurrentText(str(value))
                form_layout.addRow(key, combo)
                self.inputs[key] = combo
            
            # Set up handling for the user to select MID location and sheet selection
            # Sheet selection is handled here to keep it tied to file selection
            elif key == "MIDLocation":
                path_layout = QHBoxLayout()
                path_edit = QLineEdit(str(value))
                sheet_edit = QLineEdit(self.settings.get("MIDSheetName", ""))
                sheet_edit.setReadOnly(True)

                browse_button = QPushButton("Browse")
                browse_button.clicked.connect(
                    lambda _, le=path_edit, se=sheet_edit: self.handle_mid_selection(le,se)
                    )

                path_layout.addWidget(path_edit)
                path_layout.addWidget(browse_button)
                path_layout.addWidget(sheet_edit)
                form_layout.addRow("Master Input Document", path_layout)
                form_layout.addRow("Selected Sheet", sheet_edit)

                self.generate_mid_button = QPushButton("Generate Empty MID…")
                self.generate_mid_button.setToolTip(
                    "Build a starter spreadsheet listing every document in the "
                    "data directory, one row each."
                )
                self.generate_mid_button.clicked.connect(
                    lambda _, le=path_edit, se=sheet_edit: (
                        self.generate_empty_mid(le, se)
                    )
                )
                form_layout.addRow("", self.generate_mid_button)

                self.inputs["MIDSheetName"] = sheet_edit
                self.inputs[key] = path_edit
            
            # MID Sheet Name is handled in the above MIDLocation layout, skip to avoid duplication
            elif key == "MIDSheetName":
                continue
            # Do not allow the user to manually edit the JSON for scrapingTools, this must happen through the dedicated window
            elif key == "scrapingTools":
                continue
            elif key == "extractionTools":
                continue
            elif key == "evaluationClasses":
                continue
            elif key == "midSchema":
                continue
            # Structured settings get dedicated editors, not raw JSON text
            elif key == "checkboxes":
                continue
            elif key == "fieldButtons":
                continue
            elif key == "statisticsOnMainWindow":
                continue
            elif key == module_settings.SETTINGS_KEY:
                continue

            # Set up the file path editor for logfiles
            elif key == "logFileDirectory":
                path_layout = QHBoxLayout()
                path_edit = QLineEdit(str(value))
                browse_button = QPushButton("Browse")
                browse_button.clicked.connect(
                    lambda _, le=path_edit: self.browse_directory(le)
                )
                path_layout.addWidget(path_edit)
                path_layout.addWidget(browse_button)
                form_layout.addRow("Log File Directory", path_layout)
                self.inputs[key] = path_edit

            # For settings that do not have specified options or special handling, create a text line edit field
            else:
                line_edit = QLineEdit(str(value))
                form_layout.addRow(key, line_edit)
                self.inputs[key] = line_edit
        layout.addLayout(form_layout)

        # Create buttons for saving, loading, and confirming changes
        button_layout = QHBoxLayout()

        self.mid_schema_button = QPushButton("Configure MID Columns")
        self.mid_schema_button.clicked.connect(self.open_mid_schema_dialog)
        button_layout.addWidget(self.mid_schema_button)

        self.scraping_button = QPushButton("Set Up Scraping Tools")
        self.scraping_button.clicked.connect(self.open_scraping_tool_dialog)
        button_layout.addWidget(self.scraping_button)

        self.extraction_button = QPushButton("Set Up Extraction Tools")
        self.extraction_button.clicked.connect(self.open_extraction_tool_dialog)
        button_layout.addWidget(self.extraction_button)

        self.classes_button = QPushButton("Modify Classes")
        self.classes_button.clicked.connect(self.open_class_dialog)
        button_layout.addWidget(self.classes_button)

        self.checkbox_button = QPushButton("Configure Checkboxes")
        self.checkbox_button.clicked.connect(self.open_checkbox_dialog)
        button_layout.addWidget(self.checkbox_button)

        self.field_button_button = QPushButton("Configure Field Buttons")
        self.field_button_button.clicked.connect(self.open_field_button_dialog)
        button_layout.addWidget(self.field_button_button)

        self.module_button = QPushButton("Module Settings")
        self.module_button.clicked.connect(self.open_module_settings_dialog)
        button_layout.addWidget(self.module_button)

        self.statistics_button = QPushButton("Configure Statistics")
        self.statistics_button.setToolTip(
            "Choose which session statistics appear on the main window."
        )
        self.statistics_button.clicked.connect(self.open_statistics_dialog)
        button_layout.addWidget(self.statistics_button)

        self.save_button = QPushButton("Save Settings")
        self.save_button.clicked.connect(self.save_settings)
        button_layout.addWidget(self.save_button)

        self.load_button = QPushButton("Load Settings")
        self.load_button.clicked.connect(self.load_settings)
        button_layout.addWidget(self.load_button)

        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)



        layout.addLayout(button_layout)

    def save_settings(self):
        """Save the current settings to a JSON file."""
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Settings", "user_settings.json", "JSON Files (*.json)")
        if file_path:
            # Update our settings dictionary from the input fields
            for key, widget in self.inputs.items():
                if isinstance(widget, QComboBox):
                    self.settings[key] = widget.currentText()
                else:
                    self.settings[key] = widget.text()
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, indent=2)
                QMessageBox.information(self, "Success", "Settings saved successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save settings:\n{e}")

    def load_settings(self):
        """Load settings from a JSON file and update the dialog fields."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Settings", "", "JSON Files (*.json)")
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    loaded_settings = json.load(f)
                # Update our internal settings and refresh input fields
                self.settings.update(loaded_settings)

                for key, value in loaded_settings.items():
                    if key in self.inputs:
                        widget = self.inputs[key]
                        if isinstance(widget, QComboBox):
                            index = widget.findText(str(value))
                            if index != -1:
                                widget.setCurrentIndex(index)
                        elif isinstance(widget, QLineEdit):
                            widget.setText(str(value))

                QMessageBox.information(self, "Success", "Settings loaded successfully.")
                self.logger.info("Settings loaded from file")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load settings:\n{e}")

    def accept(self):
        # Update the settings dictionary from the QLineEdits before accepting
        for key, widget in self.inputs.items():
            if isinstance(widget, QComboBox):
                self.settings[key] = widget.currentText()
            else:
                self.settings[key] = widget.text()

        super().accept()

    # Helper function to interactively select a file
    def browse_file(self, line_edit, caption="Select File", file_filter="All Files (*)"):
        file_path, _ = QFileDialog.getOpenFileName(self, caption, "", file_filter)
        if file_path:
            line_edit.setText(file_path)

    # Helper function to interactively select a directory
    def browse_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", "")
        if directory:
            line_edit.setText(directory)

    # Helper function to interactively select the MID and sheet (if there are multiple)
    def handle_mid_selection(self, line_edit, sheet_edit):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Master Input Document",
            "",
            "Excel Files (*.xlsx *.xls)"
        )
        if file_path:
            sheet = self.prompt_for_excel_sheet(file_path)
            print(f"[DEBUG] Selected sheet: '{sheet}'")

            if sheet:
                line_edit.setText(file_path)
                sheet_edit.setText(sheet)
                self.settings["MIDLocation"] = file_path
                self.settings["MIDSheetName"] = sheet
            else: return

    # Sub-function for handle_mid_selection for choosing an excel sheet
    def prompt_for_excel_sheet(self, file_path):
        try:
            xls = pd.ExcelFile(file_path)
            sheets = xls.sheet_names
        except Exception as e:
            QMessageBox.critical(self, "Invalid Excel File", f"Could not read sheet names: \n{e}")

            return None

        sheet_name, ok = QInputDialog.getItem(
            self,
            "Select Sheet",
            "This file contains multiple sheets. Please select the one to use:",
            sheets,
            editable = False
        )
        return sheet_name if ok else None

    # Creates an instance of ScrapingToolDialog for interactive tool definitions
    def open_scraping_tool_dialog(self):
        dialog = ScrapingToolDialog(self.settings, self)
        if dialog.exec_():
            # Update settings with user edits
            self.settings.update(dialog.updated_settings)
            self.logger.info("Scraping tools updated")

            scraping_tools = self.settings.get("scrapingTools", {})
            scraper_names = list(scraping_tools.keys())

            if "defaultScraper" in self.inputs:
                widget = self.inputs["defaultScraper"]
                if isinstance(widget, QComboBox):
                    widget.clear()
                    widget.addItems(scraper_names)
                    current_default = self.settings.get("defaultScraper", "")
                    if current_default in scraper_names:
                        widget.setCurrentText(current_default)

    def open_module_settings_dialog(self):
        """Edit the settings each loaded module defines for itself."""
        mode = self.mode
        if "userMode" in self.inputs:
            # Honour a mode the user has just changed but not yet applied.
            mode = self.inputs["userMode"].currentText().lower()

        dialog = ModuleSettingsDialog(
            self.settings, self.active_modules, mode, self
        )
        if dialog.exec_() == QDialog.Accepted:
            self.settings.update(dialog.updated_settings)
            self.logger.info("Module settings updated")

    def generate_empty_mid(self, path_edit, sheet_edit):
        """Write a starter MID listing every document in the data directory.

        The data directory is read from the dialog's own field rather than the
        saved settings, so a directory the user has just typed in is the one
        used. On success the new file becomes the selected MID: producing it
        and then having to browse to it would be a pointless extra step.
        """
        data_directory = self._current_data_directory()
        if not data_directory or not os.path.isdir(data_directory):
            QMessageBox.warning(
                self,
                "No Data Directory",
                "Set a valid data directory first: the new MID lists the "
                "documents found in it.",
            )
            return

        stems = mid_template.document_stems(data_directory)
        if not stems:
            QMessageBox.warning(
                self,
                "Nothing to List",
                "No documents found in:\n" + data_directory,
            )
            return

        suggested = os.path.join(data_directory, "MID_template.xlsx")
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save the new MID",
            suggested,
            "Excel Workbook (*.xlsx);;CSV (*.csv)",
        )
        if not target:
            self.logger.info("Empty MID generation cancelled by user")
            return

        column = mid_template.document_column_for(self.settings)
        try:
            written = mid_template.write_template(
                target,
                stems,
                column=column,
                sheet_name=mid_template.DEFAULT_SHEET_NAME,
            )
        except Exception as exc:
            self.logger.error("Failed to write the new MID: %s", exc)
            QMessageBox.critical(
                self,
                "Could Not Write MID",
                "The file could not be written:\n" + str(exc),
            )
            return

        path_edit.setText(written)
        # A CSV has no sheets; the loader ignores the name for one.
        sheet_edit.setText(
            ""
            if written.lower().endswith(".csv")
            else mid_template.DEFAULT_SHEET_NAME
        )
        self.logger.info(
            "Generated an empty MID with %d row(s) at %s", len(stems), written
        )
        QMessageBox.information(
            self,
            "MID Created",
            "Listed {count} document(s) from:\n{source}\n\n"
            "Column: {column}\nSaved to: {target}\n\n"
            "It is now the selected MID. Add your own columns to it, and "
            "duplicate a row wherever one document carries several "
            "observations.".format(
                count=len(stems),
                source=data_directory,
                column=column,
                target=written,
            ),
        )

    def _current_data_directory(self) -> str:
        """The data directory as the dialog currently has it."""
        editor = self.inputs.get("dataDirectory")
        if editor is not None and hasattr(editor, "text"):
            typed = editor.text().strip()
            if typed:
                return typed
        return str(self.settings.get("dataDirectory", "")).strip()

    def open_statistics_dialog(self):
        """Choose which session statistics are pinned to the main window."""
        dialog = StatisticsSelectionDialog(
            self.settings.get("statisticsOnMainWindow", []), self
        )
        if dialog.exec_() == QDialog.Accepted:
            chosen = dialog.selected_keys()
            self.settings["statisticsOnMainWindow"] = chosen
            self.logger.info(
                "Statistics shown on the main window: %s",
                ", ".join(chosen) if chosen else "none",
            )

    def open_checkbox_dialog(self):
        """Define the sidebar checkboxes and the MID columns they write to."""
        dialog = CheckboxDialog(self.settings, self)
        if dialog.exec_() == QDialog.Accepted:
            self.settings.update(dialog.updated_settings)
            self.logger.info("Checkbox configuration updated")

    def open_field_button_dialog(self):
        """Define buttons that compute one editable field from the others."""
        if "midSchema" not in self.settings:
            QMessageBox.warning(
                self, "Field Buttons", "Configure the MID columns first."
            )
            return
        dialog = FieldButtonDialog(self.settings, self)
        if dialog.exec_() == QDialog.Accepted:
            self.settings.update(dialog.updated_settings)
            self.logger.info("Field button configuration updated")

    def open_mid_schema_dialog(self):
        """Configure identifier and editable columns from the selected MID."""
        if "MIDLocation" in self.inputs:
            self.settings["MIDLocation"] = self.inputs["MIDLocation"].text()
        if "MIDSheetName" in self.inputs:
            self.settings["MIDSheetName"] = self.inputs["MIDSheetName"].text()

        try:
            dialog = MIDSchemaDialog(self.settings, self)
        except ValueError as exc:
            QMessageBox.warning(self, "MID Configuration", str(exc))
            return

        if dialog.exec_() == QDialog.Accepted:
            self.settings["midSchema"] = dialog.updated_schema.to_mapping()
            self.logger.info("MID column configuration updated")

    # Creates an instance of ExtractionToolDialog for interactive tool definitions
    def open_extraction_tool_dialog(self):
        dialog = ExtractionToolDialog(self.settings, self)
        if dialog.exec_():
            # Update settings with user edits
            self.settings.update(dialog.updated_settings)
            self.logger.info("Extraction tools updated")

            extraction_tools = self.settings.get("extractionTools", {})
            extractor_names = list(extraction_tools.keys())

            if "defaultExtractor" in self.inputs:
                widget = self.inputs["defaultExtractor"]
                if isinstance(widget, QComboBox):
                    widget.clear()
                    widget.addItems(extractor_names)
                    current_default = self.settings.get("defaultExtractor", "")
                    if current_default in extractor_names:
                        widget.setCurrentText(current_default)

        # Creates an instance of ExtractionToolDialog for interactive tool definitions
    def open_class_dialog(self):
        dialog = ClassDialog(self.settings, self)
        if dialog.exec_():
            # Update settings with user edits
            self.settings.update(dialog.updated_settings)
            self.logger.info("Status Classes updated")

            classes = self.settings.get("evaluationClasses", {})
            class_names = list(classes.keys())

            if "defaultClass" in self.inputs:
                widget = self.inputs["defaultClass"]
                if isinstance(widget, QComboBox):
                    widget.clear()
                    widget.addItems(class_names)
                    current_default = self.settings.get("defaultClass", "")
                    if current_default in class_names:
                        widget.setCurrentText(current_default)

    # Future addition: "Reset to Defaults" button


