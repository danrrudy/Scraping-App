"""Small, reusable widget helpers shared by the UI panels."""

from __future__ import annotations

from PyQt5.QtCore import QByteArray
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QSizePolicy

#: Minimum height of a sidebar/panel text editor, in pixels.
TEXT_BOX_MIN_HEIGHT = 16

#: Minimum width of a sidebar text editor. Small deliberately: a widget's
#: minimum is what stops the pane it lives in from being made narrower, and
#: the sidebar shares a splitter with the document and the content panel.
TEXT_BOX_MIN_WIDTH = 90

#: How tall a sidebar field editor may grow. The editors are vertically
#: expanding, which is right in the content panel where one editor owns the
#: pane, but in the sidebar a stack of them will otherwise soak up every pixel
#: the scroll area is willing to give and push the controls off the bottom.
FIELD_BOX_MAX_HEIGHT = 64

#: How short a sidebar field editor may be squeezed. The sidebar compresses
#: these to avoid a scrollbar, and this is the floor: below about a line of
#: text the field stops being usable, and a scrollbar is the better trade.
FIELD_BOX_MIN_HEIGHT = 24

#: Minimum width of a sidebar button. A button's own minimumSizeHint is the
#: full width of its text, so a long label like "Add Observation from this
#: Document" would otherwise hold the whole sidebar open by itself. Setting an
#: explicit minimum overrides that hint.
BUTTON_MIN_WIDTH = 70


def configure_button(button):
    """Apply the application's standard sizing to a push button.

    The button may be squeezed narrower than its label, so the label is also
    its tooltip: a clipped button is still identifiable by hovering it.
    """
    # Wide but not tall: a vertically expanding button in a stack of a dozen
    # takes every spare pixel the column has, which pushed the sidebar past
    # the height of its own pane. The stretch at the end of the control block
    # absorbs the slack instead.
    button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    button.setMinimumHeight(24)
    button.setMinimumWidth(BUTTON_MIN_WIDTH)
    if not button.toolTip():
        button.setToolTip(button.text())
    return button


def configure_text_box(text_box):
    """Apply the application's standard sizing to a text editor.

    Tab moves to the next widget rather than inserting a tab character; a
    multi-line editor would otherwise swallow Tab and trap the focus.
    """
    text_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    text_box.setMinimumWidth(TEXT_BOX_MIN_WIDTH)
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
