"""Centre pane: the viewer for whatever content the user is working with."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QTransform
from PyQt5.QtWidgets import QLabel, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from image_canvas import ImageCanvas
from module_settings import BoolSetting, ModuleSettings, register_module_settings

from .widgets import png_bytes_to_qpixmap

PAGE_VIEW = "page"
CANVAS_VIEW = "canvas"

#: Rotation is stored in degrees clockwise and always normalised to these.
ROTATIONS = (0, 90, 180, 270)


class PageLabel(QLabel):
    """The page image, which the user can rotate by clicking it."""

    rotateRequested = pyqtSignal(int)  # +90 clockwise, -90 counter-clockwise

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.rotateRequested.emit(90)
        elif event.button() == Qt.RightButton:
            self.rotateRequested.emit(-90)
        else:
            super().mousePressEvent(event)


@register_module_settings
class DocumentView(QWidget):
    """Shows either a rendered page image or an interactive image canvas.

    The two viewers live in a stack so that exactly one is visible at a time.
    Previously the canvas was parented to the main window but never added to a
    layout, so ``show()`` opened it as a stray top-level window.
    """

    MODULE_SETTINGS = ModuleSettings(
        module_id="document_view",
        display_name="Document Viewer",
        settings=(
            BoolSetting(
                "clickRotation",
                "Rotate the page by clicking it",
                default=True,
                help="Left-click turns the page 90° clockwise, right-click 90° "
                "counter-clockwise.",
            ),
            BoolSetting(
                "keepRotationBetweenPages",
                "Keep the rotation when changing page",
                default=False,
                help="Off: each page starts upright. On: a sideways document "
                "stays turned as you page through it.",
            ),
        ),
    )

    #: Emitted after the user rotates, with the new angle in degrees clockwise.
    rotationChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.page_label = PageLabel("Load a document to begin.")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setMinimumSize(100, 100)
        self.page_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.page_label.setContextMenuPolicy(Qt.PreventContextMenu)
        self.page_label.rotateRequested.connect(self.rotate_by)

        self.image_canvas = ImageCanvas(self, enable_zoom=True)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.page_label)
        self._stack.addWidget(self.image_canvas)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._source_pixmap = None
        self._rotation = 0
        self._settings = dict(self.MODULE_SETTINGS.defaults)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def apply_settings(self, values) -> None:
        self._settings = self.MODULE_SETTINGS.resolve(values)
        if not self._settings["clickRotation"]:
            self.set_rotation(0)

    def setting(self, key):
        return self._settings.get(key)

    # ------------------------------------------------------------------
    # Rotation
    # ------------------------------------------------------------------
    def rotation(self) -> int:
        return self._rotation

    def rotate_by(self, degrees: int) -> None:
        """Turn the page. Ignored when click rotation is switched off."""
        if not self._settings.get("clickRotation", True):
            return
        self.set_rotation(self._rotation + degrees)

    def set_rotation(self, degrees: int) -> None:
        rotation = int(degrees) % 360
        # Snap to a quarter turn so the angle is always one of ROTATIONS.
        rotation = min(ROTATIONS, key=lambda angle: abs(angle - rotation))
        if rotation == self._rotation:
            return
        self._rotation = rotation
        self.refresh()
        self.rotationChanged.emit(self._rotation)

    def _reset_rotation_for_new_page(self) -> None:
        if not self._settings.get("keepRotationBetweenPages", False):
            self._rotation = 0

    # ------------------------------------------------------------------
    # Presenting state
    # ------------------------------------------------------------------
    def show_page_pixmap(self, pixmap) -> None:
        """Display a full-page render, scaled to the available area."""
        self._reset_rotation_for_new_page()
        self._source_pixmap = pixmap
        self._stack.setCurrentWidget(self.page_label)
        self.refresh()

    def show_page_png(self, png_bytes) -> None:
        """Display a page overlay supplied as raw PNG bytes."""
        pixmap = png_bytes_to_qpixmap(png_bytes)
        if pixmap is not None:
            self.show_page_pixmap(pixmap)

    def show_canvas_image(self, pixmap, meta=None, fit=True) -> None:
        """Display a clickable image (for example an extracted table)."""
        if pixmap is None:
            return
        self.image_canvas.set_image(pixmap, meta=meta or {}, fit=fit)
        self._stack.setCurrentWidget(self.image_canvas)

    def refresh(self) -> None:
        """Rescale — and rotate — the current page render after a resize."""
        if self._source_pixmap is None:
            return
        pixmap = self._source_pixmap
        if self._rotation:
            pixmap = pixmap.transformed(
                QTransform().rotate(self._rotation), Qt.SmoothTransformation
            )
        self.page_label.setPixmap(
            pixmap.scaled(
                self.page_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    def clear(self) -> None:
        self._source_pixmap = None
        self._rotation = 0
        self.page_label.clear()
        self.image_canvas.clear()
        self._stack.setCurrentWidget(self.page_label)

    # ------------------------------------------------------------------
    # Reading state
    # ------------------------------------------------------------------
    def active_view(self) -> str:
        return (
            CANVAS_VIEW
            if self._stack.currentWidget() is self.image_canvas
            else PAGE_VIEW
        )

    def page_pixmap(self):
        return self._source_pixmap
