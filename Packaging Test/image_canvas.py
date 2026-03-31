# image_canvas.py
from PyQt5.QtCore import Qt, QPointF, pyqtSignal
from PyQt5.QtGui import QPixmap, QPen, QBrush
from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem

class ImageCanvas(QGraphicsView):
    """
    Lightweight canvas for a single image with precise click capture.
    - Emits natural-pixel positions (x_nat, y_nat) relative to the image.
    - Optional zoom/pan with mouse wheel + drag.
    - Draws small markers where the user clicks.
    """
    pointClicked = pyqtSignal(dict)  # {x_nat, y_nat, nat_w, nat_h, page, table}

    def __init__(self, parent=None, enable_zoom=True, zoom_factor=1.15, marker_radius=5):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.ScrollHandDrag if enable_zoom else QGraphicsView.NoDrag)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._pixmap_item: QGraphicsPixmapItem = None
        self._nat_w = 0
        self._nat_h = 0
        self._page = -1
        self._table = 0
        self._markers = []
        self._enable_zoom = enable_zoom
        self._zoom_factor = zoom_factor
        self._marker_radius = marker_radius

    # ---- Public API ---------------------------------------------------------

    def clear(self):
        self._scene.clear()
        self._pixmap_item = None
        self._markers.clear()
        self._nat_w = 0
        self._nat_h = 0

    def clear_markers(self):
        for m in self._markers:
            self._scene.removeItem(m)
        self._markers.clear()

    def set_zoom_enabled(self, enabled: bool):
        self._enable_zoom = enabled
        self.setDragMode(QGraphicsView.ScrollHandDrag if enabled else QGraphicsView.NoDrag)

    def set_image(self, qpixmap: QPixmap, meta=None, fit=True):
        """
        Set the image to display.
        qpixmap: natural-size QPixmap
        meta: optional dict with {"page": int, "table": int}
        """
        self.clear()
        if qpixmap is None:
            return
        self._pixmap_item = QGraphicsPixmapItem(qpixmap)
        self._scene.addItem(self._pixmap_item)
        self._nat_w = qpixmap.width()
        self._nat_h = qpixmap.height()
        self._page = int((meta or {}).get("page", -1))
        self._table = int((meta or {}).get("table", 0))
        self._scene.setSceneRect(0, 0, self._nat_w, self._nat_h)
        if fit:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    def fit_to_view(self):
        if self._pixmap_item:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    # ---- Events -------------------------------------------------------------

    def mousePressEvent(self, event):
        if self._pixmap_item and event.button() == Qt.LeftButton:
            scene_pt: QPointF = self.mapToScene(event.pos())
            x_nat = max(0.0, min(scene_pt.x(), float(self._nat_w)))
            y_nat = max(0.0, min(scene_pt.y(), float(self._nat_h)))

            # Drop a small marker at the click position
            r = self._marker_radius
            pen = QPen(Qt.red)
            brush = QBrush(Qt.red)
            marker = self._scene.addEllipse(x_nat - r, y_nat - r, 2*r, 2*r, pen, brush)
            marker.setZValue(10)
            self._markers.append(marker)

            self.pointClicked.emit({
                "x_nat": float(x_nat),
                "y_nat": float(y_nat),
                "nat_w": float(self._nat_w),
                "nat_h": float(self._nat_h),
                "page": self._page,
                "table": self._table,
            })

        super().mousePressEvent(event)

    def wheelEvent(self, event):
        if not self._enable_zoom:
            return super().wheelEvent(event)
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = self._zoom_factor if delta > 0 else 1.0 / self._zoom_factor
        self.scale(factor, factor)
