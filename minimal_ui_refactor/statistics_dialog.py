"""The statistics window, and the picker that chooses what the sidebar shows.

Two dialogs, kept together because they present the same set of metrics:

:class:`StatisticsDialog`
    Read-only. Shows every metric, always, and keeps ticking while it is open.
:class:`StatisticsSelectionDialog`
    Reached from Settings. Chooses which metrics are pinned to the sidebar.
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from session_metrics import METRIC_SPECS, normalize_metric_keys

#: How often the open statistics window re-reads the metrics. Session time is
#: the only value that moves on its own, and it is shown to the second only
#: below a minute, so a second is as often as this could matter.
REFRESH_MILLISECONDS = 1000


class StatisticsDialog(QDialog):
    """Every metric for the current session. Read-only, and live while open."""

    def __init__(self, metrics, parent=None):
        super().__init__(parent)
        self.metrics = metrics
        self.setWindowTitle("Session Statistics")
        self.value_labels = {}
        self._init_ui()
        self.refresh()

        # Stopped in closeEvent: a timer left running on a closed dialog keeps
        # the object alive and goes on reading the metrics for nothing.
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MILLISECONDS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Measured since this run of the application started. "
            "Nothing here is saved when it closes."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555;")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        for spec in METRIC_SPECS:
            value = QLabel("")
            # Selectable so a user can copy a figure into a note or an email.
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setStyleSheet("font-weight: bold;")
            self.value_labels[spec.key] = value

            caption = QLabel(spec.description)
            caption.setWordWrap(True)
            caption.setStyleSheet("color: #666; font-size: 11px;")

            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 6)
            cell_layout.setSpacing(1)
            cell_layout.addWidget(value)
            cell_layout.addWidget(caption)

            form.addRow(f"{spec.label}:", cell)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def refresh(self):
        """Re-read every metric. Safe to call when the metrics are missing."""
        snapshot = self.metrics.snapshot() if self.metrics is not None else {}
        for key, label in self.value_labels.items():
            label.setText(snapshot.get(key, "—"))

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


class StatisticsSelectionDialog(QDialog):
    """Which metrics are pinned above the entry counter in the sidebar."""

    def __init__(self, selected_keys=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Statistics on the Main Window")
        self.boxes = {}
        self._init_ui(normalize_metric_keys(selected_keys))

    def _init_ui(self, selected):
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Choose which statistics appear in the information panel, just "
            "above the entry counter. All of them are always available under "
            "User → Statistics."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        for spec in METRIC_SPECS:
            box = QCheckBox(spec.label)
            box.setChecked(spec.key in selected)
            box.setToolTip(spec.description)
            self.boxes[spec.key] = box
            layout.addWidget(box)

        shortcuts = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_all.clicked.connect(lambda: self._set_all(True))
        shortcuts.addWidget(select_all)

        clear_all = QPushButton("Clear All")
        clear_all.clicked.connect(lambda: self._set_all(False))
        shortcuts.addWidget(clear_all)
        shortcuts.addStretch(1)
        layout.addLayout(shortcuts)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, checked: bool) -> None:
        for box in self.boxes.values():
            box.setChecked(checked)

    def selected_keys(self) -> list[str]:
        """The chosen metric keys, in presentation order."""
        return normalize_metric_keys(
            [key for key, box in self.boxes.items() if box.isChecked()]
        )
