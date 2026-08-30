"""Small custom-drawn UI pieces — a progress/count ring and a stat pill —
used for the header infographics and the processing indicator."""
from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from clearscanner.ui import theme


class Ring(QWidget):
    """A thin arc ring with a value in the middle. `fraction` 0-1 fills the
    arc; set `text` for the centre label. Animates fraction changes."""

    def __init__(self, diameter: int = 40, parent=None):
        super().__init__(parent)
        self._d = diameter
        self.setFixedSize(diameter, diameter)
        self._frac = 0.0
        self._text = ""
        self._track = QColor(theme.EDGE_STRONG)
        self._arc = QColor(theme.ACCENT)
        self._spin = False
        self._angle = 0
        self._anim = QPropertyAnimation(self, b"fraction", self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._spin_anim = QPropertyAnimation(self, b"angle", self)
        self._spin_anim.setDuration(900)
        self._spin_anim.setStartValue(0)
        self._spin_anim.setEndValue(360)
        self._spin_anim.setLoopCount(-1)

    def sizeHint(self):
        return QSize(self._d, self._d)

    def set_value(self, fraction: float, text: str = ""):
        self._text = text
        self._anim.stop()
        self._anim.setStartValue(self._frac)
        self._anim.setEndValue(max(0.0, min(1.0, fraction)))
        self._anim.start()

    def set_spinning(self, on: bool):
        self._spin = on
        if on:
            self._spin_anim.start()
        else:
            self._spin_anim.stop()
        self.update()

    def get_fraction(self):
        return self._frac

    def set_fraction(self, v):
        self._frac = v
        self.update()

    fraction = Property(float, get_fraction, set_fraction)

    def get_angle(self):
        return self._angle

    def set_angle(self, v):
        self._angle = v
        self.update()

    angle = Property(int, get_angle, set_angle)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = 3.0
        rect = QRectF(m, m, self._d - 2 * m, self._d - 2 * m)

        p.setPen(QPen(self._track, 3.0, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 0, 360 * 16)

        p.setPen(QPen(self._arc, 3.0, Qt.SolidLine, Qt.RoundCap))
        if self._spin:
            p.drawArc(rect, -self._angle * 16, -110 * 16)
        else:
            p.drawArc(rect, 90 * 16, -int(self._frac * 360 * 16))

        if self._text:
            f = QFont(self.font())
            f.setPointSizeF(9.0 if len(self._text) < 3 else 7.5)
            f.setWeight(QFont.Bold)
            p.setFont(f)
            p.setPen(QColor(theme.INK))
            p.drawText(self.rect(), Qt.AlignCenter, self._text)


class StatPill(QWidget):
    """A tiny rounded chip: an optional leading Ring, a big value and a
    quiet caption — the header 'infographic' unit."""

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

        self.setObjectName("statPill")
        self.ring = Ring(34)
        self._value = QLabel("—")
        self._value.setStyleSheet(f"font-size:14px;font-weight:800;color:{theme.INK};")
        cap = QLabel(caption.upper())
        cap.setStyleSheet(f"font-size:9px;font-weight:800;letter-spacing:0.8px;color:{theme.MUTED};")

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        text.addWidget(self._value)
        text.addWidget(cap)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 12, 6)
        row.setSpacing(9)
        row.addWidget(self.ring)
        row.addLayout(text)

    def set(self, value: str, fraction: float = 0.0, ring_text: str = ""):
        self._value.setText(value)
        self.ring.set_value(fraction, ring_text)
