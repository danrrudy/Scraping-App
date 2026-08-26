"""Centre pane: the viewer for whatever content the user is working with."""

from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QTransform
from PyQt5.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from image_canvas import ImageCanvas
from module_settings import (
    BoolSetting,
    ChoiceSetting,
    ModuleSettings,
    register_module_settings,
)

from .widgets import png_bytes_to_qpixmap

PAGE_VIEW = "page"
CANVAS_VIEW = "canvas"

#: Rotation is stored in degrees clockwise and always normalised to these.
ROTATIONS = (0, 90, 180, 270)

# What a click on the page does. Left-click is always the forward direction
# and right-click its reverse, whichever of these is chosen.
CLICK_ROTATE = "Rotate the page"
CLICK_ZOOM = "Zoom in and out"
CLICK_PAGE = "Change page"
CLICK_ENTRY = "Change entry"
CLICK_NOTHING = "Nothing"

CLICK_ACTIONS = (CLICK_ROTATE, CLICK_ZOOM, CLICK_PAGE, CLICK_ENTRY, CLICK_NOTHING)

#: Zoom is a multiple of the fit-to-window size, so 1.0 is "the whole page".
MINIMUM_ZOOM = 1.0
MAXIMUM_ZOOM = 6.0
ZOOM_STEP = 1.4


class PageLabel(QLabel):
    """The page image. What clicking it does is the viewer's decision."""

    #: ``(+1, position)`` for a left-click, ``(-1, position)`` for a right one.
    #: The position is in label coordinates, so a zoom can centre on it.
    clicked = pyqtSignal(int, object)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(1, event.pos())
        elif event.button() == Qt.RightButton:
            self.clicked.emit(-1, event.pos())
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
            ChoiceSetting(
                "clickAction",
                "Clicking the page",
                choices=CLICK_ACTIONS,
                default=CLICK_ROTATE,
                help="Left-click goes forwards, right-click backwards: turn "
                "the page, zoom in and out, step through pages, or step "
                "through MID entries.",
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
    #: A click asked to move a page. +1 forwards, -1 back.
    pageStepRequested = pyqtSignal(int)
    #: A click asked to move a MID entry. +1 forwards, -1 back.
    entryStepRequested = pyqtSignal(int)
    #: Emitted after the zoom changes, with the new multiple of fit-to-window.
    zoomChanged = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.page_label = PageLabel("Load a document to begin.")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setMinimumSize(100, 100)
        self.page_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.page_label.setContextMenuPolicy(Qt.PreventContextMenu)
        self.page_label.clicked.connect(self._on_page_clicked)

        # The page lives in a scroll area so that zooming past fit-to-window
        # has somewhere to overflow to and the user can drag around it.
        # Not resizable: the label is sized explicitly in refresh().
        self.page_scroll = QScrollArea(self)
        self.page_scroll.setWidget(self.page_label)
        self.page_scroll.setWidgetResizable(False)
        self.page_scroll.setAlignment(Qt.AlignCenter)
        self.page_scroll.setFrameShape(QScrollArea.NoFrame)
        # The page is fitted to this viewport, and a viewport reaches its real
        # size some time after the widget around it does. Watching it directly
        # is what makes the first render come out full size rather than
        # stranded at whatever the viewport measured at construction.
        self.page_scroll.viewport().installEventFilter(self)

        self.image_canvas = ImageCanvas(self, enable_zoom=True)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.page_scroll)
        self._stack.addWidget(self.image_canvas)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._source_pixmap = None
        self._rotation = 0
        self._zoom = MINIMUM_ZOOM
        self._settings = dict(self.MODULE_SETTINGS.defaults)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def apply_settings(self, values) -> None:
        self._settings = self.MODULE_SETTINGS.resolve(values)
        # Whatever the click no longer does, undo: a page left rotated or
        # zoomed by a mode the user has just switched away from cannot be put
        # back by clicking it.
        action = self.click_action()
        if action != CLICK_ROTATE:
            self.set_rotation(0)
        if action != CLICK_ZOOM:
            self.set_zoom(MINIMUM_ZOOM)

    def click_action(self) -> str:
        return self._settings.get("clickAction", CLICK_ROTATE)

    def setting(self, key):
        return self._settings.get(key)

    # ------------------------------------------------------------------
    # Rotation
    # ------------------------------------------------------------------
    def rotation(self) -> int:
        return self._rotation

    def rotate_by(self, degrees: int) -> None:
        """Turn the page. Ignored unless clicking is set to rotate."""
        if self.click_action() != CLICK_ROTATE:
            return
        self.set_rotation(self._rotation + degrees)

    # ------------------------------------------------------------------
    # Clicking
    # ------------------------------------------------------------------
    def _on_page_clicked(self, direction: int, position) -> None:
        """Route a click to whichever behaviour the user chose.

        Page and entry steps are requests, not actions: only the controller
        knows whether there is a next page to go to, and moving an entry has
        to commit the sidebar first.
        """
        action = self.click_action()
        if action == CLICK_ROTATE:
            self.set_rotation(self._rotation + 90 * direction)
        elif action == CLICK_ZOOM:
            self.zoom_by(direction, position)
        elif action == CLICK_PAGE:
            self.pageStepRequested.emit(direction)
        elif action == CLICK_ENTRY:
            self.entryStepRequested.emit(direction)

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------
    def zoom(self) -> float:
        return self._zoom

    def zoom_by(self, direction: int, position=None) -> None:
        """Step the zoom, keeping what was clicked in view."""
        factor = ZOOM_STEP if direction > 0 else 1.0 / ZOOM_STEP
        self.set_zoom(self._zoom * factor, position)

    def set_zoom(self, zoom: float, position=None) -> None:
        zoom = max(MINIMUM_ZOOM, min(MAXIMUM_ZOOM, float(zoom)))
        if abs(zoom - self._zoom) < 1e-6:
            return

        # Where the click fell, as a fraction of the page, so the same part of
        # the document is still under the pointer after the resize.
        anchor = None
        if position is not None and self.page_label.width() and self.page_label.height():
            anchor = (
                position.x() / self.page_label.width(),
                position.y() / self.page_label.height(),
            )

        self._zoom = zoom
        self.refresh()
        if anchor is not None:
            self._centre_on(anchor)
        self.zoomChanged.emit(self._zoom)

    def _centre_on(self, anchor) -> None:
        """Scroll so the given fraction of the page sits in the middle."""
        fraction_x, fraction_y = anchor
        horizontal = self.page_scroll.horizontalScrollBar()
        vertical = self.page_scroll.verticalScrollBar()
        viewport = self.page_scroll.viewport()
        horizontal.setValue(
            int(fraction_x * self.page_label.width() - viewport.width() / 2)
        )
        vertical.setValue(
            int(fraction_y * self.page_label.height() - viewport.height() / 2)
        )

    def _reset_zoom_for_new_page(self) -> None:
        self._zoom = MINIMUM_ZOOM

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
        self._reset_zoom_for_new_page()
        self._source_pixmap = pixmap
        self._stack.setCurrentWidget(self.page_scroll)
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
        """Rescale — rotating and zooming — the current page render."""
        if self._source_pixmap is None:
            return
        pixmap = self._source_pixmap
        if self._rotation:
            pixmap = pixmap.transformed(
                QTransform().rotate(self._rotation), Qt.SmoothTransformation
            )

        # Fit to the viewport first, then apply the zoom on top, so zoom 1.0
        # always means "the whole page" however the window has been resized.
        viewport = self.page_scroll.viewport().size()
        if viewport.width() < 2 or viewport.height() < 2:
            # Not laid out yet. Leaving the pixmap alone keeps the previous
            # sensible render until resizeEvent brings us back with a size.
            return
        target = pixmap.size()
        target.scale(viewport, Qt.KeepAspectRatio)
        if self._zoom != MINIMUM_ZOOM:
            target *= self._zoom

        scaled = pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.page_label.setPixmap(scaled)
        # The scroll area is not resizable, so the label carries its own size;
        # at zoom 1.0 it fills the viewport and no scrollbars appear.
        self.page_label.resize(scaled.size())

    def eventFilter(self, watched, event):
        """Re-fit the page whenever the area it is drawn in changes size."""
        if (
            watched is self.page_scroll.viewport()
            and event.type() == QEvent.Resize
        ):
            self.refresh()
        return super().eventFilter(watched, event)

    def clear(self) -> None:
        self._source_pixmap = None
        self._rotation = 0
        self._zoom = MINIMUM_ZOOM
        self.page_label.clear()
        self.image_canvas.clear()
        self._stack.setCurrentWidget(self.page_scroll)

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
