"""The window's painted background: a soft mesh of colour blooms over a
violet→cream base. Rendered once to an oversized pixmap; cursor parallax
is then just an offset blit, so it stays smooth. Qt has no true
backdrop-blur — a low-frequency background is what lets the frosted panels
on top read as glass without one.
"""
from PySide6.QtCore import Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

_MARGIN = 30  # px of over-render on every side, for parallax headroom

_BLOOMS = [
    # (x-frac, y-frac, radius-frac, r, g, b, alpha, parallax-depth)
    (-0.08, -0.14, 0.66, 0x6A, 0x54, 0xF7, 96, 1.00),
    (1.08, 0.02, 0.60, 0x47, 0x8C, 0xF0, 70, 0.75),
    (0.88, 1.16, 0.66, 0xF0, 0x63, 0xC2, 62, 0.60),
    (0.05, 1.10, 0.52, 0x24, 0xC6, 0x9C, 36, 0.45),
    (0.48, 0.40, 0.46, 0xBE, 0x8C, 0xFF, 30, 0.30),
]


class Backdrop(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._cache = QPixmap()
        self._px = 0.0
        self._py = 0.0
        self._ax = QPropertyAnimation(self, b"parallaxX", self)
        self._ay = QPropertyAnimation(self, b"parallaxY", self)
        for a in (self._ax, self._ay):
            a.setDuration(650)
            a.setEasingCurve(QEasingCurve.OutCubic)

    def get_px(self):
        return self._px

    def set_px(self, v):
        self._px = v
        self.update()

    def get_py(self):
        return self._py

    def set_py(self, v):
        self._py = v
        self.update()

    parallaxX = Property(float, get_px, set_px)
    parallaxY = Property(float, get_py, set_py)

    def drift_to(self, nx: float, ny: float):
        nx = max(-1.0, min(1.0, nx))
        ny = max(-1.0, min(1.0, ny))
        for anim, cur, target in ((self._ax, self._px, nx), (self._ay, self._py, ny)):
            anim.stop()
            anim.setStartValue(cur)
            anim.setEndValue(target)
            anim.start()

    def resizeEvent(self, _e):
        self._render_cache()

    def _render_cache(self):
        w = max(1, self.width() + 2 * _MARGIN)
        h = max(1, self.height() + 2 * _MARGIN)
        pm = QPixmap(w, h)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)

        base = QLinearGradient(0, 0, w * 0.4, h)
        base.setColorAt(0.0, QColor("#E7E0FB"))
        base.setColorAt(0.5, QColor("#EEE8F1"))
        base.setColorAt(1.0, QColor("#F3EEE4"))
        p.fillRect(pm.rect(), base)

        for xf, yf, rf, r, g, b, a, _depth in _BLOOMS:
            cx = xf * (w - 2 * _MARGIN) + _MARGIN
            cy = yf * (h - 2 * _MARGIN) + _MARGIN
            rad = rf * max(w, h)
            grad = QRadialGradient(QPointF(cx, cy), rad)
            grad.setColorAt(0.0, QColor(r, g, b, a))
            grad.setColorAt(1.0, QColor(r, g, b, 0))
            p.fillRect(pm.rect(), grad)
        p.end()
        self._cache = pm
        self.update()

    def paintEvent(self, _event):
        if self._cache.isNull():
            self._render_cache()
        p = QPainter(self)
        ox = -_MARGIN + int(self._px * -_MARGIN * 0.8)
        oy = -_MARGIN + int(self._py * -_MARGIN * 0.8)
        p.drawPixmap(QPoint(ox, oy), self._cache)
