"""Editor for settings that belong to a module rather than the application.

The dialog draws whatever each module declares in its ``MODULE_SETTINGS``, so
adding a setting to a panel needs no change here.

Which modules appear depends on the mode: outside dev mode only the modules
currently on screen, in dev mode everything the program knows about plus
anything the settings file remembers.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import module_settings
from logger import setup_logger


class ModuleSettingsDialog(QDialog):
    """One tab per module, each drawn from that module's declared settings."""

    def __init__(self, settings, active_modules=(), mode="user", parent=None):
        super().__init__(parent)
        self.logger = setup_logger()
        self.setWindowTitle("Module Settings")
        self.resize(560, 460)

        self.settings = settings
        self.mode = str(mode or "user").lower()
        self.module_ids = module_settings.visible_modules(
            settings, active_modules, mode=self.mode
        )
        self.active_modules = tuple(active_modules)
        self.updated_settings = {}
        self._editors: dict[str, dict[str, QWidget]] = {}

        self._init_ui()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _init_ui(self):
        layout = QVBoxLayout(self)

        if self.mode == "dev":
            note = (
                "Dev mode: every module the application knows about, including "
                "ones that are not loaded right now."
            )
        else:
            note = "Settings for the modules currently loaded."
        explanation = QLabel(note)
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.tabs = QTabWidget()
        for module_id in self.module_ids:
            spec = module_settings.module_spec(module_id)
            if spec is None:
                self.tabs.addTab(self._unknown_module_tab(module_id), module_id)
                continue
            self.tabs.addTab(self._module_tab(spec), spec.display_name)
        if not self.module_ids:
            self.tabs.addTab(
                self._message_tab("No configurable modules are loaded."), "Modules"
            )
        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _module_tab(self, spec):
        page = QWidget()
        form = QFormLayout(page)
        values = module_settings.resolve(self.settings, spec.module_id)
        editors = {}

        loaded = spec.module_id in self.active_modules
        if not loaded:
            note = QLabel("This module is not loaded; changes apply when it is.")
            note.setStyleSheet("color: #8A6100;")
            note.setWordWrap(True)
            form.addRow(note)

        for setting in spec.settings:
            editor = self._editor_for(setting, values.get(setting.key))
            editors[setting.key] = editor
            form.addRow(setting.label, editor)
            if setting.help:
                help_label = QLabel(setting.help)
                help_label.setWordWrap(True)
                help_label.setStyleSheet("color: #555; font-size: 11px;")
                form.addRow("", help_label)

        self._editors[spec.module_id] = editors
        return page

    @staticmethod
    def _editor_for(setting, value):
        if setting.kind == "bool":
            editor = QCheckBox()
            editor.setChecked(bool(value))
            return editor

        if setting.kind == "int":
            editor = QSpinBox()
            editor.setRange(setting.minimum, setting.maximum)
            editor.setValue(int(value or 0))
            return editor

        if setting.kind == "choice":
            editor = QComboBox()
            editor.addItems([str(choice) for choice in setting.choices])
            editor.setCurrentText(str(value or ""))
            return editor

        editor = QLineEdit()
        editor.setText("" if value is None else str(value))
        return editor

    @staticmethod
    def _read_editor(setting, editor):
        if setting.kind == "bool":
            return editor.isChecked()
        if setting.kind == "int":
            return editor.value()
        if setting.kind == "choice":
            return editor.currentText()
        return editor.text().strip()

    def _unknown_module_tab(self, module_id):
        stored = (self.settings.get(module_settings.SETTINGS_KEY, {}) or {}).get(
            module_id, {}
        )
        lines = "\n".join(f"{key}: {value}" for key, value in sorted(stored.items()))
        return self._message_tab(
            "This module is remembered from an earlier session but is not "
            "available in this build. Its settings are kept as they are.\n\n"
            + (lines or "(no stored values)")
        )

    @staticmethod
    def _message_tab(text):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------
    def accept(self):
        # Start from what is already stored so modules we did not draw — ones
        # from an earlier session, or hidden outside dev mode — are preserved.
        stored = dict(self.settings.get(module_settings.SETTINGS_KEY, {}) or {})

        for module_id, editors in self._editors.items():
            spec = module_settings.module_spec(module_id)
            if spec is None:
                continue
            stored[module_id] = {
                setting.key: self._read_editor(setting, editors[setting.key])
                for setting in spec.settings
                if setting.key in editors
            }

        self.updated_settings[module_settings.SETTINGS_KEY] = stored
        self.logger.info(f"Saved settings for {len(self._editors)} module(s)")
        super().accept()
