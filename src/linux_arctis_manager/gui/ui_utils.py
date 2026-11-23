import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6 import QtSvg
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QApplication,
                               QComboBox, QTabBar, QWidget)

ICON_PATH = Path(__file__).parent / 'images' / 'app_icon.svg'

def get_icon_pixmap(icon_path: Path = ICON_PATH, color: QPalette.ColorRole = QPalette.ColorRole.Text) -> QPixmap:
    brush_color = QApplication.palette().color(color)

    xml_tree = ET.parse(icon_path.absolute().as_posix())
    xml_root = xml_tree.getroot()

    for path in xml_root.findall('.//{http://www.w3.org/2000/svg}path'):
        path.set('fill', brush_color.name())

    xml_str = ET.tostring(xml_root)

    svg_renderer = QtSvg.QSvgRenderer(xml_str)

    # Create the empty image
    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    # Initialize the painter
    painter = QPainter(image)
    painter.setBrush(brush_color)
    painter.setPen(Qt.PenStyle.NoPen)

    # Render the image on the QImage
    svg_renderer.render(painter)

    # Rendering end
    painter.end()

    pixmap = QPixmap.fromImage(image)

    return pixmap


CLICKABLE_WIDGET_TYPES = (QAbstractButton, QComboBox, QAbstractSlider, QTabBar)


class PointingCursorFilter(QObject):
    """Give every enabled clickable widget a pointing-hand cursor.

    Installed once on the QApplication so widgets built later (e.g. the
    settings controls generated from D-Bus metadata) are covered too. Disabled
    widgets fall back to the default arrow so they don't look pressable.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Polish, QEvent.Type.EnabledChange) \
                and isinstance(watched, CLICKABLE_WIDGET_TYPES):
            apply_pointing_cursor(watched)

        return False


def apply_pointing_cursor(widget: QWidget) -> None:
    if widget.isEnabled():
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
    else:
        widget.unsetCursor()


def install_pointing_cursor_filter(app: QApplication) -> PointingCursorFilter:
    cursor_filter = PointingCursorFilter(app)
    app.installEventFilter(cursor_filter)

    return cursor_filter
