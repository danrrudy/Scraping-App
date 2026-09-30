from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QFileDialog, QMessageBox, QInputDialog, QComboBox
)
import os
from logger import setup_logger
import shutil

# Base Extractor Template is the abstract interface for implementing individual Extractor tools
BASE_EXTRACTOR_TEMPLATE = os.path.join(os.path.dirname(__file__), "base_extractor.py")

# ExtractionToolDialog is the popup window where the user selects, defines, and integrates their extraction tools
class ExtractionToolDialog(QDialog):
    # Dialog instances do basic window setup, grab the user's settings, and sets variables for file management
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure extraction Tools")
        self.settings = settings.copy()
        self.updated_settings = {}
        self.extraction_tools = self.settings.get("extractionTools", {})
        self.directory = self.settings.get("extractionToolDirectory", "")
        # Create a logger instance for the tool dialog
        self.logger = setup_logger()
        
        self.init_ui()


    # Create the UI instance
    def init_ui(self):
        self.logger.debug("Creating extraction_tool_dialog UI")
        layout = QVBoxLayout()

        # File Selection UI
        self.dir_edit = QLineEdit(self.directory)
        browse_btn = QPushButton("Browse Directory")
        browse_btn.clicked.connect(self.select_directory)
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Tool Directory:"))
        dir_layout.addWidget(self.dir_edit)
        dir_layout.addWidget(browse_btn)
        layout.addLayout(dir_layout)

        # extraction Tools UI
        self.tool_list = QListWidget()
        self.refresh_tool_list()
        layout.addWidget(QLabel("Configured Tools:"))
        layout.addWidget(self.tool_list)

        add_btn = QPushButton("Add extraction Tool")
        add_btn.clicked.connect(self.add_extraction_tool)
        layout.addWidget(add_btn)

        rem_btn = QPushButton("Remove extraction Tool")
        rem_btn.clicked.connect(self.remove_extraction_tool)
        layout.addWidget(rem_btn)

        edit_btn = QPushButton("Edit Tool")
        edit_btn.clicked.connect(self.edit_extraction_tool)
        layout.addWidget(edit_btn)

        # Drop-down menu for the default Extractor
        layout.addWidget(QLabel("Default Extractor:"))
        self.default_combo = QComboBox()
        self.refresh_default_combo()
        layout.addWidget(self.default_combo)

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept_dialog)
        layout.addWidget(ok_btn)

        self.setLayout(layout)
        self.logger.debug("extraction tool dialog UI created")

        # Check if the "./Extractors" directory exists; if not, create it
        Extractor_dir = self.dir_edit.text()
        if Extractor_dir and not os.path.exists(Extractor_dir):
            self.logger.warning("./Extractors does not exist! attempting to create directory")
            try:
                os.makedirs(Extractor_dir)

            except Exception as e:
                self.logger.error("Failed to Create ./Extractors! Tools will not be loaded!")
                QMessageBox.critical(self, "Error", f"Failed to create Extractor directory:\n{e}")
                return

    # Helper function for selecting a directory
    def select_directory(self):
        path = QFileDialog.getExistingDirectory(self, "Select extraction Tool Directory")
        if path:
            self.dir_edit.setText(path)
            self.directory = path
            self.logger.info(f"logger directory changed to {path}")

    # Grabs the list of extraction tools and updates the UI accordingly
    def refresh_tool_list(self):
        self.tool_list.clear()
        for name, config in self.extraction_tools.items():
            self.tool_list.addItem(f"{name} -> {config['path']} (Types: {config['format_types']})")
            self.logger.debug(f"Refreshing, tool added: {name}")
        self.logger.debug("Tool list refreshed")

    # Grabs the list of extraction tools and updates the default Extractor drop-down menu
    def refresh_default_combo(self):
        self.default_combo.clear()
        tool_names = list(self.extraction_tools.keys())
        self.default_combo.addItems(tool_names)
        default_name = self.settings.get("defaultExtractor", "")
        if default_name in tool_names:
            self.default_combo.setCurrentText(default_name)

    # Main logic handler for tool addition
    def add_extraction_tool(self):
        name, ok = QInputDialog.getText(self, "Tool Name", "Enter a name for the extraction tool:")
        if not ok or not name:
            self.logger.info("Tool addition canceled")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select Python File", self.directory, "Python Files (*.py)")
        if not path:
            return
        self.logger.info(f"extraction tool added from: {path}")

        # Ignore base classes (manually hardcoded, should not be modified by end user)
        filename = os.path.basename(path)
        if filename == "base.Extractor.py":
            self.logger.warning("User attempted to load a restricted base Extractor class")
            QMessageBox.warning(self, "Invalid File", "This file is a base class and cannot be used directly!")
            return

        types_str, ok = QInputDialog.getText(self, "Format Codes", "Enter format type codes (comma-separated):")
        if not ok:
            return

        try:
            type_codes = [int(code.strip()) for code in types_str.split(",")]
            self.logger.info(f"{name} mapped to formats: {types_str}")
        except ValueError:
            self.logger.warning(f"Format code rejected from input: {types_str}")
            QMessageBox.warning(self, "Invalid Input", "Format codes must be integers.")
            return
        self.extraction_tools[name] = {"path": path, "format_types": type_codes}
        self.refresh_tool_list()
        self.refresh_default_combo()

    # Remove a extraction tool definition and its associated settings, then update UI
    def remove_extraction_tool(self):
        selected_item = self.tool_list.currentItem()
        if not selected_item:
            self.logger.warning("No tool selected to remove!")
            QMessageBox.warning(self, "No Selection", "Please select a tool to remove")
            return

        tool_name = selected_item.text().split("->")[0].strip()
        confirm = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Are you sure you want to remove '{tool_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.extraction_tools.pop(tool_name, None)
            self.logger.info(f"Removed extraction tool: {tool_name}")
            self.refresh_tool_list()
            self.refresh_default_combo()

    # Allows the user to change the document type assignments for the selected Extractor
    def edit_extraction_tool(self):
        selected_item = self.tool_list.currentItem()
        if not selected_item:
            self.logger.warning("No tool selected to edit!")
            QMessageBox.warning(self, "No Selection", "Please select a tool to edit")
            return

        tool_name = selected_item.text().split("->")[0].strip()
        config = self.extraction_tools.get(tool_name, {})

        # Prompy for new format types
        types_str, ok = QInputDialog.getText(
            self,
            "Edit Format Codes",
            f"Current: {config.get('format_types', [])}\nEnter new Format Codes (comma-separated)"
        )
        if not ok:
            return
        try:
            type_codes = [int(code.strip()) for code in types_str.split(",")]
            config["format_types"] = type_codes
            self.extraction_tools[tool_name] = config
            self.logger.info(f"Remapped {tool_name} to format codes {type_codes}")
            self.refresh_tool_list()
            self.refresh_default_combo()
        except ValueError:
            self.logger.warning("Invalid Format Codes!")
            QMessageBox.warning(self, "Invalid Input", "Format codes must be integers")


    def accept_dialog(self):
        self.updated_settings["extractionToolDirectory"] = self.dir_edit.text()
        self.updated_settings["extractionTools"] = self.extraction_tools
        self.updated_settings["defaultExtractor"] = self.default_combo.currentText()
        self.logger.info("extraction tools saved")
        
        self.accept()
