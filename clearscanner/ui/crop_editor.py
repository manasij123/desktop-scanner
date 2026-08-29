"""Manual 4-corner crop editor: drag corners freely, or drag an edge's
midpoint handle to snap that whole side straight (horizontal/vertical)."""
import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from clearscanner.core.transform import order_points
from clearscanner.ui import theme

HANDLE_RADIUS = 8
HANDLE_RADIUS_HOVER = 11
HIT_RADIUS = HANDLE_RADIUS * 2.5

# self._corners is [tl, tr, br, bl] (see order_points). Each edge here is
# (start_idx, end_idx, orientation) — "horizontal" means dragging that
# edge's handle sets both endpoints to the same Y (a level top/bottom
# edge); "vertical" means it sets both to the same X (a plumb side edge).
EDGES = [
    (0, 1, "horizontal"),  # top
    (1, 2, "vertical"),    # right
    (2, 3, "horizontal"),  # bottom
    (3, 0, "vertical"),    # left
]


class CropEditor(QWidget):
    cornersChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._image = None
        self._corners = None  # float32 ndarray, shape (4, 2), ORIGINAL image coords
        self._pixmap = None
        self._draw_rect = QRectF()
        self._scale = 1.0
        self._dragging = None  # ("corner", idx) or ("edge", idx), or None
        self._hovering = None

    def set_image(self, image, corners):
        self._image = image
        self._corners = order_points(corners.copy())

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        qimage = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(qimage)
        self.update()

    def corners(self):
        return self._corners.copy() if self._corners is not None else None

    def _edge_midpoint(self, edge_idx):
        a, b, _orientation = EDGES[edge_idx]
        return (self._corners[a] + self._corners[b]) / 2

    def _recompute_layout(self):
        if self._pixmap is None or self.width() == 0 or self.height() == 0:
            return
        pix_w, pix_h = self._pixmap.width(), self._pixmap.height()
        scale = min(self.width() / pix_w, self.height() / pix_h)
        draw_w, draw_h = pix_w * scale, pix_h * scale
        x = (self.width() - draw_w) / 2
        y = (self.height() - draw_h) / 2
        self._draw_rect = QRectF(x, y, draw_w, draw_h)
        self._scale = scale

    def _to_widget(self, pt) -> QPointF:
        x, y = pt
        return QPointF(self._draw_rect.x() + x * self._scale, self._draw_rect.y() + y * self._scale)

    def _to_image(self, pt: QPointF):
        x = (pt.x() - self._draw_rect.x()) / self._scale
        y = (pt.y() - self._draw_rect.y()) / self._scale
        return x, y

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recompute_layout()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(theme.SURFACE_SUNK))
        if self._pixmap is None:
            painter.end()
            return

        self._recompute_layout()
        painter.drawPixmap(self._draw_rect, self._pixmap, QRectF(self._pixmap.rect()))

        accent = QColor(theme.ACCENT)
        corner_pts = [self._to_widget(p) for p in self._corners]
        edge_pts = [self._to_widget(self._edge_midpoint(i)) for i in range(4)]

        painter.setPen(QPen(accent, 2))
        for i in range(4):
            painter.drawLine(corner_pts[i], corner_pts[(i + 1) % 4])

        painter.setPen(Qt.NoPen)
        for i, p in enumerate(corner_pts):
            self._draw_handle(painter, p, active=("corner", i) == self._dragging or ("corner", i) == self._hovering)

        for i, p in enumerate(edge_pts):
            self._draw_handle(
                painter, p, active=("edge", i) == self._dragging or ("edge", i) == self._hovering, square=True
            )

        painter.end()

    def _draw_handle(self, painter: QPainter, p: QPointF, active: bool, square: bool = False):
        accent = QColor(theme.ACCENT)
        radius = HANDLE_RADIUS_HOVER if active else HANDLE_RADIUS
        if active:
            glow = QColor(theme.ACCENT)
            glow.setAlpha(70)
            painter.setBrush(glow)
            if square:
                painter.drawRect(QRectF(p.x() - radius - 6, p.y() - radius - 6, (radius + 6) * 2, (radius + 6) * 2))
            else:
                painter.drawEllipse(p, radius + 6, radius + 6)
        painter.setBrush(accent)
        if square:
            side = radius * 1.5
            painter.drawRect(QRectF(p.x() - side / 2, p.y() - side / 2, side, side))
        else:
            painter.drawEllipse(p, radius, radius)

    def _hit_test(self, pos: QPointF):
        """Return ("corner", idx) or ("edge", idx) for whichever handle is
        under `pos`, corners taking priority since they sit at the ends of
        the edge handles' lines. None if nothing is close enough."""
        if self._corners is None:
            return None
        for i, c in enumerate(self._corners):
            if (self._to_widget(c) - pos).manhattanLength() <= HIT_RADIUS:
                return ("corner", i)
        for i in range(4):
            if (self._to_widget(self._edge_midpoint(i)) - pos).manhattanLength() <= HIT_RADIUS:
                return ("edge", i)
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = self._hit_test(event.position())

    def mouseMoveEvent(self, event):
        if self._image is None:
            return

        if self._dragging is None:
            hit = self._hit_test(event.position())
            if hit != self._hovering:
                self._hovering = hit
                self.update()
            self.setCursor(QCursor(Qt.OpenHandCursor) if hit is not None else QCursor(Qt.ArrowCursor))
            return

        self.setCursor(QCursor(Qt.ClosedHandCursor))
        x, y = self._to_image(event.position())
        h, w = self._image.shape[:2]
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))

        kind, idx = self._dragging
        if kind == "corner":
            self._corners[idx] = [x, y]
        else:
            a, b, orientation = EDGES[idx]
            if orientation == "horizontal":
                self._corners[a][1] = y
                self._corners[b][1] = y
            else:
                self._corners[a][0] = x
                self._corners[b][0] = x

        self.update()
        self.cornersChanged.emit()

    def mouseReleaseEvent(self, event):
        self._dragging = None
        self.setCursor(QCursor(Qt.ArrowCursor))
