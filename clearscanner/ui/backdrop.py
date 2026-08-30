"""The window's painted background: a soft violet→cream gradient with a
few large, blurry colour blooms. Low-frequency on purpose — the frosted
(semi-transparent) panels on top read as glass without needing a real
backdrop blur, which Qt has no primitive for.
"""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

_BLOOMS = [
    # (x-frac, y-frac, radius-frac, r, g, b, alpha)
    (-0.05, -0.10, 0.60, 0x6C, 0x5C, 0xF5, 64),   # violet, top-left
    (1.05, 0.10, 0.55, 0x4F, 0x93, 0xEC, 46),     # cool blue, upper-right
    (0.80, 1.10, 0.60, 0xEE, 0x6F, 0xC6, 40),     # pink, bottom
    (0.12, 1.05, 0.50, 0x2E, 0xC6, 0x9E, 26),     # mint, bottom-left
]


class Backdrop(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        base = QLinearGradient(0, 0, w * 0.4, h)
        base.setColorAt(0.0, QColor("#ECE7FB"))
        base.setColorAt(0.5, QColor("#F1ECF3"))
        base.setColorAt(1.0, QColor("#F4EFE6"))
        p.fillRect(self.rect(), base)

        for xf, yf, rf, r, g, b, a in _BLOOMS:
            cx, cy = xf * w, yf * h
            rad = rf * max(w, h)
            grad = QRadialGradient(QPointF(cx, cy), rad)
            grad.setColorAt(0.0, QColor(r, g, b, a))
            grad.setColorAt(1.0, QColor(r, g, b, 0))
            p.fillRect(self.rect(), grad)
