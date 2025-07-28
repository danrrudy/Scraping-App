# SettingsDialog Class
# This Class implements a pop-up window for the user to modify program settings. These can be written to or read from JSON.

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QFormLayout, QLineEdit, QHBoxLayout, QMessageBox, QFileDialog, QComboBox, QInputDialog, QWidget
import json
import pandas as pd
from logger import setup_logger
from scraping_tool_dialog import ScrapingToolDialog


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        # Make a copy of the settings so that changes can be confirmed
        self.settings = settings.copy()
        self._init_ui()

    def _init_ui(self):
        logger = setup_logger()
        layout = QVBoxLayout(self)

        # Mapping of setting keys to possible options
        self.options = {
            "fontSize": ["10", "12", "14", "16", "18"],
            "loggingLevel": ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
            #logFileDirectory: Filepath, no options
            "consoleOutput": ["File", "Console", "Both"]
        }

        # Create a form layout to display and edit settings
        form_layout = QFormLayout()
        self.inputs = {}
        # For each key/value pair in the settings dictionary, create a QLineEdit
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
                self.inputs["MIDSheetName"] = sheet_edit
                self.inputs[key] = path_edit
            
            # MID Sheet Name is handled in the above MIDLocation layout, skip to avoid duplication
            elif key == "MIDSheetName":
                continue
            # Do not allow the user to manually edit the JSON for scrapingTools, this must happen through the dedicated window
            elif key == "scrapingTools":
                continue

            # Set up the file path editor for logfiles
            elif key == "logFileDirectory":
                path_layout = QHBoxLayout()
                path_edit = QLineEdit(str(value))
                browse_button = QPushButton("Browse")
                browse_button.clicked.connect(
                    lambda _, le=path_edit: self.brose_directory(le)
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

        self.scraping_button = QPushButton("Set Up Scraping Tools")
        self.scraping_button.clicked.connect(self.open_scraping_tool_dialog)
        button_layout.addWidget(self.scraping_button)

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

    def open_scraping_tool_dialog(self):
        dialog = ScrapingToolDialog(self.settings, self)
        if dialog.exec_():
            # Update settings with user edits
            self.settings.update(dialog.updated_settings)
            self.logger.info("Scraping tools updated")

    # Future addition: "Reset to Defaults" button


