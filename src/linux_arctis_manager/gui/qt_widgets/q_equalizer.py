from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QKeyEvent, QLinearGradient,
                           QMouseEvent, QPainter, QPainterPath, QPaintEvent,
                           QPen, QWheelEvent)
from PySide6.QtWidgets import QSizePolicy, QWidget

COLOR_PANEL = QColor('#101820')
COLOR_BORDER = QColor('#263241')
COLOR_GRID = QColor('#1f2b38')
COLOR_ZERO = QColor('#3a4c60')
COLOR_TRACK = QColor('#22303f')
COLOR_ACCENT = QColor('#5fb3f3')
COLOR_HANDLE_BORDER = QColor('#0f1419')
COLOR_TEXT = QColor('#dbe7f3')
COLOR_MUTED = QColor('#91a4b7')
COLOR_SELECTED_COLUMN = QColor(95, 179, 243, 22)

MARGIN_LEFT = 56
MARGIN_RIGHT = 16
MARGIN_TOP = 34
MARGIN_BOTTOM = 34
HANDLE_RADIUS = 7
COMMIT_DELAY_MS = 250


class QEqualizerGraph(QWidget):
    '''
    Graphic equalizer: one vertical fader per band over a level grid, with the response curve
    drawn through the band handles. Drag a handle, scroll over a band, or use the arrow keys
    (left/right selects, up/down/page up/page down changes); double-click resets a band.

    `band_changed(name, value)` is emitted when a change is committed (on release, or shortly
    after the last scroll/key step), so the device receives one command per gesture.
    '''
    band_changed = Signal(str, int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('equalizerGraph')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(420, 280)

        self._bands: list[dict[str, Any]] = []
        self._scale: list[dict[str, Any]] = []
        self._baseline: float | None = None
        self._selected = 0
        self._hovered = -1
        self._dragging = -1
        self._pending: dict[str, int] = {}

        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(COMMIT_DELAY_MS)
        self._commit_timer.timeout.connect(self._commit_pending)

    # ----- data -----

    def set_bands(self, bands: list[dict[str, Any]], scale: list[dict[str, Any]], baseline: float | None = None) -> None:
        '''
        Update from the view model; values being edited locally are kept until committed.
        `baseline` is the neutral level (0 dB) the curve fills from; defaults to mid-range.
        '''
        local_names = set(self._pending)
        if self._dragging >= 0 and self._dragging < len(self._bands):
            local_names.add(self._bands[self._dragging]['name'])
        current = {band['name']: band for band in self._bands}

        new_bands = []
        for band in bands:
            band = dict(band)
            if band['name'] in local_names and band['name'] in current:
                band['value'] = current[band['name']]['value']
                band['value_label'] = current[band['name']]['value_label']
            new_bands.append(band)

        self._bands = new_bands
        self._scale = list(scale)
        self._baseline = baseline
        self._selected = min(self._selected, max(len(self._bands) - 1, 0))
        self.setAccessibleName(f'Equalizer, {len(self._bands)} bands')
        self.update()

    def set_locked(self, locked: bool) -> None:
        '''
        Read-only mode, e.g. while a fixed preset is active: input is ignored and the graph is dimmed.
        A change still being edited is committed first, so it is not lost or shown over the preset.
        '''
        if locked == (not self.isEnabled()):
            return
        if locked:
            if self._dragging >= 0:
                self._queue(self._dragging)
                self._dragging = -1
            self._commit_timer.stop()
            self._commit_pending()
        self.setEnabled(not locked)

    def bands(self) -> list[dict[str, Any]]:
        return [dict(band) for band in self._bands]

    def selected_band(self) -> int:
        return self._selected

    def sizeHint(self) -> QSize:
        return QSize(720, 300)

    # ----- geometry -----

    def _plot_rect(self) -> QRectF:
        return QRectF(
            MARGIN_LEFT,
            MARGIN_TOP,
            max(self.width() - MARGIN_LEFT - MARGIN_RIGHT, 1),
            max(self.height() - MARGIN_TOP - MARGIN_BOTTOM, 1),
        )

    def _column_width(self) -> float:
        return self._plot_rect().width() / max(len(self._bands), 1)

    def _band_x(self, index: int) -> float:
        return self._plot_rect().left() + (index + 0.5) * self._column_width()

    def _value_y(self, band: dict[str, Any], value: float) -> float:
        rect = self._plot_rect()
        span = band['max'] - band['min'] or 1
        return rect.bottom() - (value - band['min']) / span * rect.height()

    def _scale_y(self, value: float) -> float:
        # The scale shares the range of the bands (same YAML definition).
        reference = self._bands[0] if self._bands else {'min': 0, 'max': 1}
        return self._value_y(reference, value)

    def _band_at(self, x: float) -> int:
        if not self._bands:
            return -1
        index = int((x - self._plot_rect().left()) // self._column_width())
        return min(max(index, 0), len(self._bands) - 1)

    def _value_at(self, band: dict[str, Any], y: float) -> int:
        rect = self._plot_rect()
        ratio = (rect.bottom() - y) / rect.height()
        raw = band['min'] + ratio * (band['max'] - band['min'])
        return self._snap(band, raw)

    @staticmethod
    def _snap(band: dict[str, Any], value: float) -> int:
        step = band.get('step', 1) or 1
        snapped = band['min'] + round((value - band['min']) / step) * step
        return int(min(max(snapped, band['min']), band['max']))

    def _zero_value(self) -> float | None:
        '''The neutral level (0 dB), or the middle of the range.'''
        if self._baseline is not None:
            return self._baseline
        if self._bands:
            return (self._bands[0]['min'] + self._bands[0]['max']) / 2
        return None

    # ----- editing -----

    def _label_for(self, band: dict[str, Any], value: int) -> str:
        labels = band.get('value_labels')
        if isinstance(labels, dict):
            return str(labels.get(value, value))
        return str(value)

    def _set_local_value(self, index: int, value: int) -> bool:
        band = self._bands[index]
        value = self._snap(band, value)
        if value == band['value']:
            return False
        band['value'] = value
        band['value_label'] = self._label_for(band, value)
        self.update()
        return True

    def _queue(self, index: int) -> None:
        band = self._bands[index]
        self._pending[band['name']] = band['value']
        self._commit_timer.start()

    def _commit_pending(self) -> None:
        pending, self._pending = self._pending, {}
        for name, value in pending.items():
            self.band_changed.emit(name, value)

    def _step_selected(self, steps: int) -> None:
        if not self._bands:
            return
        band = self._bands[self._selected]
        if self._set_local_value(self._selected, band['value'] + steps * band.get('step', 1)):
            self._queue(self._selected)

    # ----- events -----

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._bands or not self.isEnabled():
            return super().mousePressEvent(event)
        index = self._band_at(event.position().x())
        self._selected = index
        self._dragging = index
        self._set_local_value(index, self._value_at(self._bands[index], event.position().y()))
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging >= 0:
            self._set_local_value(self._dragging, self._value_at(self._bands[self._dragging], event.position().y()))
            return
        hovered = self._band_at(event.position().x()) if self._plot_rect().adjusted(0, -MARGIN_TOP, 0, 0).contains(event.position()) else -1
        if hovered != self._hovered:
            self._hovered = hovered
            if hovered >= 0:
                band = self._bands[hovered]
                self.setToolTip(f"{band['label']}: {band['value_label']}")
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging >= 0 and event.button() == Qt.MouseButton.LeftButton:
            index, self._dragging = self._dragging, -1
            self._queue(index)
            self._commit_timer.stop()
            self._commit_pending()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if not self._bands or not self.isEnabled():
            return
        index = self._band_at(event.position().x())
        self._dragging = -1
        if self._set_local_value(index, self._bands[index].get('default', self._bands[index]['value'])) or self._bands[index]['name'] in self._pending:
            self._queue(index)
            self._commit_timer.stop()
            self._commit_pending()

    def leaveEvent(self, event) -> None:
        self._hovered = -1
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._bands or not self.isEnabled():
            return super().wheelEvent(event)
        delta = event.angleDelta().y()
        if delta == 0:
            return super().wheelEvent(event)
        self._selected = self._band_at(event.position().x())
        self._step_selected(1 if delta > 0 else -1)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._bands:
            return super().keyPressEvent(event)
        key = event.key()
        if key == Qt.Key.Key_Left:
            self._selected = max(self._selected - 1, 0)
        elif key == Qt.Key.Key_Right:
            self._selected = min(self._selected + 1, len(self._bands) - 1)
        elif key == Qt.Key.Key_Up:
            self._step_selected(1)
        elif key == Qt.Key.Key_Down:
            self._step_selected(-1)
        elif key == Qt.Key.Key_PageUp:
            self._step_selected(4)
        elif key == Qt.Key.Key_PageDown:
            self._step_selected(-4)
        else:
            return super().keyPressEvent(event)
        self.update()

    # ----- painting -----

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.5)

        painter.setPen(QPen(COLOR_BORDER, 1))
        painter.setBrush(COLOR_PANEL)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        rect = self._plot_rect()
        small = QFont(self.font())
        small.setPixelSize(11)
        bold = QFont(small)
        bold.setBold(True)

        self._paint_scale(painter, rect, small)
        if not self._bands:
            painter.end()
            return

        self._paint_columns(painter, rect, small, bold)
        self._paint_curve(painter, rect)
        self._paint_handles(painter)
        painter.end()

    def _paint_scale(self, painter: QPainter, rect: QRectF, font: QFont) -> None:
        zero = self._zero_value()
        painter.setFont(font)
        for tick in self._scale:
            y = self._scale_y(tick['value'])
            is_zero = zero is not None and tick['value'] == zero
            pen = QPen(COLOR_ZERO if is_zero else COLOR_GRID, 1.5 if is_zero else 1)
            if not is_zero:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(COLOR_TEXT if is_zero else COLOR_MUTED)
            painter.drawText(
                QRectF(4, y - 8, MARGIN_LEFT - 12, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                str(tick['label']),
            )

    def _paint_columns(self, painter: QPainter, rect: QRectF, font: QFont, bold: QFont) -> None:
        column_width = self._column_width()
        for index, band in enumerate(self._bands):
            x = self._band_x(index)
            active = self.isEnabled() and index in (self._selected, self._hovered, self._dragging)
            if index == self._selected and self.hasFocus() or index == self._dragging:
                painter.fillRect(QRectF(x - column_width / 2 + 2, rect.top(), column_width - 4, rect.height()), COLOR_SELECTED_COLUMN)

            painter.setPen(QPen(COLOR_TRACK, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

            zero = self._zero_value()
            if zero is not None:
                painter.setPen(QPen(COLOR_ACCENT if active else COLOR_ACCENT.darker(150), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(QPointF(x, self._value_y(band, zero)), QPointF(x, self._value_y(band, band['value'])))

            painter.setFont(bold if active else font)
            painter.setPen(COLOR_TEXT if active else COLOR_MUTED)
            painter.drawText(
                QRectF(x - column_width / 2, 6, column_width, MARGIN_TOP - 10),
                Qt.AlignmentFlag.AlignCenter,
                str(band['value_label']).replace(' dB', ''),
            )
            painter.drawText(
                QRectF(x - column_width / 2, rect.bottom() + 6, column_width, MARGIN_BOTTOM - 10),
                Qt.AlignmentFlag.AlignCenter,
                str(band['label']),
            )

    def _curve_points(self) -> list[QPointF]:
        return [QPointF(self._band_x(i), self._value_y(band, band['value'])) for i, band in enumerate(self._bands)]

    def _curve_path(self, points: list[QPointF]) -> QPainterPath:
        '''Smooth curve through the band points (Catmull-Rom converted to cubic Béziers).'''
        path = QPainterPath(points[0])
        for i in range(len(points) - 1):
            p0 = points[i - 1] if i > 0 else points[i]
            p1, p2 = points[i], points[i + 1]
            p3 = points[i + 2] if i + 2 < len(points) else p2
            c1 = p1 + (p2 - p0) * (1 / 6)
            c2 = p2 - (p3 - p1) * (1 / 6)
            path.cubicTo(c1, c2, p2)
        return path

    def _paint_curve(self, painter: QPainter, rect: QRectF) -> None:
        points = self._curve_points()
        if len(points) < 2:
            return

        # Extend flat to the plot edges, like a response curve.
        edge_points = [QPointF(rect.left(), points[0].y()), *points, QPointF(rect.right(), points[-1].y())]
        curve = QPainterPath(edge_points[0])
        curve.lineTo(points[0])
        curve.connectPath(self._curve_path(points))
        curve.lineTo(edge_points[-1])

        zero = self._zero_value()
        baseline = self._scale_y(zero) if zero is not None else rect.bottom()
        fill = QPainterPath(curve)
        fill.lineTo(rect.right(), baseline)
        fill.lineTo(rect.left(), baseline)
        fill.closeSubpath()

        gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
        top = QColor(COLOR_ACCENT)
        top.setAlpha(70)
        middle = QColor(COLOR_ACCENT)
        middle.setAlpha(12)
        gradient.setColorAt(0, top)
        gradient.setColorAt(0.5, middle)
        gradient.setColorAt(1, top)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(fill)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(COLOR_ACCENT, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(curve)

    def _paint_handles(self, painter: QPainter) -> None:
        for index, point in enumerate(self._curve_points()):
            active = self.isEnabled() and index in (self._selected, self._hovered, self._dragging)
            radius = HANDLE_RADIUS + (2 if active else 0)
            if index == self._dragging or (index == self._selected and self.hasFocus()):
                ring = QColor(COLOR_ACCENT)
                ring.setAlpha(60)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(ring)
                painter.drawEllipse(point, radius + 5, radius + 5)
            painter.setPen(QPen(COLOR_HANDLE_BORDER, 2))
            painter.setBrush(QColor('#ffffff') if active else COLOR_ACCENT)
            painter.drawEllipse(point, radius, radius)
