"""A compact two-state pill toggle (e.g. Colour / B&W), animated.

Emits toggled(bool) — checked == the right-hand option.
"""
from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QAbstractButton

from clearscanner.ui import theme

_W, _H = 128, 34
_PAD = 3


class ToggleSwitch(QAbstractButton):
    def __init__(self, left_label: str, right_label: str, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(_W, _H)
        self._left = left_label
        self._right = right_label
        self._knob = 0.0  # 0 = left, 1 = right
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(_W, _H)

    def _animate(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._knob)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def get_knob(self):
        return self._knob

    def set_knob(self, v):
        self._knob = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def setCurrent(self, right: bool):
        """Set state without animating (used to sync from code)."""
        self.blockSignals(True)
        self.setChecked(right)
        self.blockSignals(False)
        self._knob = 1.0 if right else 0.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # track
        p.setPen(QColor(theme.EDGE))
        p.setBrush(QColor(theme.SURFACE_SUNK))
        p.drawRoundedRect(QRectF(0.5, 0.5, _W - 1, _H - 1), _H / 2, _H / 2)

        # sliding knob
        knob_w = _W / 2 - _PAD
        x = _PAD + self._knob * (_W / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(x, _PAD, knob_w, _H - 2 * _PAD), (_H - 2 * _PAD) / 2, (_H - 2 * _PAD) / 2)

        # labels
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        font.setWeight(QFont.DemiBold)
        p.setFont(font)

        left_rect = QRectF(0, 0, _W / 2, _H)
        right_rect = QRectF(_W / 2, 0, _W / 2, _H)
        p.setPen(QColor("#FFFFFF") if self._knob < 0.5 else QColor(theme.INK_SOFT))
        p.drawText(left_rect, Qt.AlignCenter, self._left)
        p.setPen(QColor("#FFFFFF") if self._knob >= 0.5 else QColor(theme.INK_SOFT))
        p.drawText(right_rect, Qt.AlignCenter, self._right)
