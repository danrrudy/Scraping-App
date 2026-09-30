from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QFileDialog, QMessageBox, QInputDialog, QComboBox
)
import os
from logger import setup_logger
import shutil

# Base Extractor Template is the abstract interface for implementing individual Extractor tools
BASE_Extractor_TEMPLATE = os.path.join(os.path.dirname(__file__), "base_Extractor.py")

# ExtractionToolDialog is the popup window where the user selects, defines, and integrates their extraction tools
class ClassDialog(QDialog):
    # Dialog instances do basic window setup, grab the user's settings, and sets variables for file management
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Evaluation Classes")
        self.settings = settings.copy()
        self.updated_settings = {}
        self.classes = self.settings.get("evaluationClasses", {})
        # Create a logger instance for the tool dialog
        self.logger = setup_logger()
        
        self.init_ui()


    # Create the UI instance
    def init_ui(self):
        self.logger.debug("Creating class_dialog UI")
        layout = QVBoxLayout()

        # extraction Tools UI
        self.class_list = QListWidget()
        self.refresh_class_list()
        layout.addWidget(QLabel("Classes:"))
        layout.addWidget(self.class_list)

        add_btn = QPushButton("Add Class")
        add_btn.clicked.connect(self.add_class)
        layout.addWidget(add_btn)

        rem_btn = QPushButton("Remove Class")
        rem_btn.clicked.connect(self.remove_class)
        layout.addWidget(rem_btn)

        edit_btn = QPushButton("Edit Class")
        edit_btn.clicked.connect(self.edit_class)
        layout.addWidget(edit_btn)

        # Drop-down menu for the default Extractor
        layout.addWidget(QLabel("Default Class:"))
        self.default_combo = QComboBox()
        self.refresh_default_combo()
        layout.addWidget(self.default_combo)

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept_dialog)
        layout.addWidget(ok_btn)

        self.setLayout(layout)
        self.logger.debug("Evaluation Class dialog UI created")



    # Grabs the list of extraction tools and updates the UI accordingly
    def refresh_class_list(self):
        self.class_list.clear()
        for name, options in self.classes.items():
            opts = options.get("option_types", [])
            item = QListWidgetItem(f"{name}: {opts}")
            item.setData(0x0100, name)
            self.class_list.addItem(item)
            self.logger.debug(f"Refreshing, class added: {name}")
        self.logger.debug("Class list refreshed")

    # Grabs the list of extraction tools and updates the default Extractor drop-down menu
    def refresh_default_combo(self):
        self.default_combo.clear()
        class_names = list(self.classes.keys())
        self.default_combo.addItems(class_names)
        default_name = self.settings.get("defaultClass", "")
        if default_name in class_names:
            self.default_combo.setCurrentText(default_name)

    # Main logic handler for tool addition
    def add_class(self):
        name, ok = QInputDialog.getText(self, "Class Name", "Enter a name for the Classification Scheme:")
        if not ok or not name:
            self.logger.info("Class addition canceled")
            return

        options_str, ok = QInputDialog.getText(self, "Options", "Enter evaluation options for this class (comma-separated):")
        if not ok:
            return

        try:
            options = [option.strip() for option in options_str.split(",")]
            self.logger.info(f"{name} Saved with options: {options_str}")
        except ValueError:
            self.logger.warning(f"Format code rejected from input: {options_str}")
            QMessageBox.warning(self, "Invalid Input", "Format codes must be integers.")
            return
        self.classes[name] = {"name": name, "option_types": options}
        self.refresh_class_list()
        self.refresh_default_combo()

    # Remove a extraction tool definition and its associated settings, then update UI
    def remove_class(self):
        selected_item = self.class_list.currentItem()
        if not selected_item:
            self.logger.warning("No tool selected to remove!")
            QMessageBox.warning(self, "No Selection", "Please select a tool to remove")
            return

        class_name = selected_item.data(0x0100)

        confirm = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Are you sure you want to remove '{class_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.classes.pop(class_name, None)
            self.logger.info(f"Removed class: {class_name}")
            self.refresh_class_list()
            self.refresh_default_combo()

    # Allows the user to change the document type assignments for the selected Extractor
    def edit_class(self):
        selected_item = self.class_list.currentItem()
        if not selected_item:
            self.logger.warning("No tool selected to edit!")
            QMessageBox.warning(self, "No Selection", "Please select a tool to edit")
            return

        class_name = selected_item.data(0x0100)
        config = self.classes.get(class_name, {})

        # Prompy for new format types
        options_str, ok = QInputDialog.getText(
            self,
            "Edit Options",
            f"Current: {config.get('option_types', [])}\nEnter new options (comma-separated)"
        )
        if not ok:
            return
        
        try:
            options = [option.strip() for option in options_str.split(",") if option.split()]
            config["option_types"] = options
            config["name"] = class_name
            self.classes[class_name] = config
            self.logger.info(f"Remapped {class_name} to format codes {options}")
            self.refresh_class_list()
            self.refresh_default_combo()
        except ValueError:
            self.logger.warning("Invalid Format Codes!")
            QMessageBox.warning(self, "Invalid Input", "Format codes must be integers")


    def accept_dialog(self):
        self.updated_settings["evaluationClasses"] = self.classes
        self.updated_settings["defaultClass"] = self.default_combo.currentText()
        self.logger.info("classes saved")
        
        self.accept()
