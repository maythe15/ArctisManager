from PySide6.QtCore import (Property, QEasingCurve, QEvent, QPoint,
                            QPropertyAnimation, QRectF, Qt)
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QCheckBox, QWidget

LEFT_MARGIN = 3
HEIGHT = 26
KNOB = HEIGHT - 2 * LEFT_MARGIN

# Same colours as the app's chips (#presetChip / #mixGroupChip in main_app.py).
TRACK_OFF = QColor('#0f1419')
TRACK_ON = QColor('#22425f')
BORDER_OFF = QColor('#34465a')
BORDER_ON = QColor('#5fb3f3')
KNOB_OFF = QColor('#7f92a5')
KNOB_ON = QColor('#5fb3f3')
DISABLED = QColor('#2e3c4d')


class QToggle(QCheckBox):
    def __init__(self, parent: QWidget|None = None, width: int = 48, is_checkbox: bool = False):
        '''
        Args:
            parent: The parent widget
            width: The width of the toggle
            is_checkbox: Kept for compatibility; the toggle always fills with the accent colour when on
        '''
        super().__init__(parent)

        self.setFixedSize(width, HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.is_checkbox = is_checkbox
        self._hovered = False

        self._circle_position = float(LEFT_MARGIN)
        self.animation = QPropertyAnimation(self, b'circle_position', self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutExpo)
        self.animation.setDuration(300)

        self.checkStateChanged.connect(self.start_animation_transition)

    def _knob_end(self, checked: bool) -> float:
        return float(self.width() - LEFT_MARGIN - KNOB) if checked else float(LEFT_MARGIN)

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        # Not shown yet (initial state): no animation, the knob starts where it belongs.
        if not self.isVisible():
            self.animation.stop()
            self._circle_position = self._knob_end(checked)
            self.update()

    def start_animation_transition(self, value: Qt.CheckState):
        self.animation.stop()
        self.animation.setEndValue(self._knob_end(value == Qt.CheckState.Checked))
        self.animation.start()

    @Property(float)
    def circle_position(self) -> float:
        return self._circle_position

    @circle_position.setter
    def circle_position(self, value: float):
        self._circle_position = value
        self.update()

    def hitButton(self, pos: QPoint) -> bool:
        return self.contentsRect().contains(pos)

    def event(self, e: QEvent) -> bool:
        if e.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            self._hovered = e.type() == QEvent.Type.Enter
            self.update()

        return super().event(e)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        checked = self.isChecked()
        enabled = self.isEnabled()

        # Track
        border = BORDER_ON if (checked or self._hovered) and enabled else (DISABLED if not enabled else BORDER_OFF)
        painter.setPen(QPen(border, 1))
        painter.setBrush(TRACK_ON if checked and enabled else TRACK_OFF)
        track = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        # Knob
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush((KNOB_ON if checked else KNOB_OFF) if enabled else DISABLED)
        painter.drawEllipse(QRectF(self._circle_position, LEFT_MARGIN, KNOB, KNOB))

        painter.end()
