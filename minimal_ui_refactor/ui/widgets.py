"""Small, reusable widget helpers shared by the UI panels."""

from __future__ import annotations

from PyQt5.QtCore import QByteArray
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QSizePolicy

#: Minimum height of a sidebar/panel text editor, in pixels.
TEXT_BOX_MIN_HEIGHT = 16


def configure_button(button):
    """Apply the application's standard sizing to a push button."""
    button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    button.setMinimumHeight(24)
    return button


def configure_text_box(text_box):
    """Apply the application's standard sizing to a text editor.

    Tab moves to the next widget rather than inserting a tab character; a
    multi-line editor would otherwise swallow Tab and trap the focus.
    """
    text_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    text_box.setMinimumWidth(150)
    text_box.setMinimumHeight(TEXT_BOX_MIN_HEIGHT)
    text_box.setTabChangesFocus(True)
    return text_box


def pil_to_qpixmap(pil_image):
    """Convert a PIL image to a QPixmap, or return ``None`` when given ``None``."""
    if pil_image is None:
        return None
    if pil_image.mode in ("RGBA", "LA"):
        image_format = QImage.Format_RGBA8888
        converted = pil_image.convert("RGBA")
        bytes_per_line = pil_image.width * 4
    else:
        image_format = QImage.Format_RGB888
        converted = pil_image.convert("RGB")
        bytes_per_line = pil_image.width * 3

    data = converted.tobytes("raw", converted.mode)
    image = QImage(
        data, converted.width, converted.height, bytes_per_line, image_format
    ).copy()
    return QPixmap.fromImage(image)


def fitz_pixmap_to_qpixmap(pixmap):
    """Convert a PyMuPDF pixmap (from a page render) to a QPixmap."""
    if pixmap is None:
        return None
    image = QImage(
        pixmap.samples,
        pixmap.width,
        pixmap.height,
        pixmap.stride,
        QImage.Format_RGB888,
    ).copy()
    return QPixmap.fromImage(image)


def png_bytes_to_qpixmap(png_bytes):
    """Convert raw PNG bytes to a QPixmap."""
    if not png_bytes:
        return None
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(png_bytes), "PNG")
    return pixmap
