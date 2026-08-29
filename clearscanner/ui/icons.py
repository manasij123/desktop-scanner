"""Crisp line icons rendered from inline SVG — no icon-font or asset files.

icon("rotate-left", color) -> QIcon.  Stroke colour defaults to the theme
ink so icons sit right on light buttons; pass an explicit colour for
accent / on-accent buttons.
"""
from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from clearscanner.ui import theme

# 24x24 viewbox, 1.9px stroke, round caps/joins — one consistent family.
_PATHS = {
    "plus":          '<path d="M12 5v14M5 12h14"/>',
    "rotate-left":   '<path d="M3 8h9a6 6 0 1 1-6 6"/><path d="M3 4v4h4"/>',
    "rotate-right":  '<path d="M21 8h-9a6 6 0 1 0 6 6"/><path d="M21 4v4h-4"/>',
    "check":         '<path d="M4 12.5l5 5L20 6.5"/>',
    "x":             '<path d="M6 6l12 12M18 6L6 18"/>',
    "trash":         '<path d="M4 7h16M10 4h4M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    "sliders":       '<path d="M4 8h10M18 8h2M4 16h4M12 16h8"/><circle cx="16" cy="8" r="2.3"/><circle cx="10" cy="16" r="2.3"/>',
    "text":          '<path d="M5 6h14M5 6v-1M19 6v-1M12 6v13M9 19h6"/>',
    "print":         '<path d="M7 9V4h10v5M7 17H5V9h14v8h-2M7 14h10v6H7z"/>',
    "download":      '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
    "crop":          '<path d="M7 3v14h14M3 7h14v14"/>',
    "info":          '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "image":         '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M4 17l5-5 4 4 3-3 4 4"/>',
    "layers":        '<path d="M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17l9 5 9-5"/>',
    "reset":         '<path d="M3 12a9 9 0 1 0 3-6.7M3 4v4h4"/>',
    "scan":          '<path d="M4 8V5a1 1 0 0 1 1-1h3M20 8V5a1 1 0 0 0-1-1h-3M4 16v3a1 1 0 0 0 1 1h3M20 16v3a1 1 0 0 1-1 1h-3M4 12h16"/>',
}

_cache: dict = {}


def _svg(name: str, color: str, fill: bool) -> bytes:
    body = _PATHS[name]
    paint = f'fill="{color}" stroke="none"' if fill else f'fill="none" stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {paint}>{body}</svg>'
    ).encode("utf-8")


def icon(name: str, color: str | None = None, *, fill: bool = False, px: int = 40) -> QIcon:
    color = color or theme.INK_SOFT
    key = (name, color, fill, px)
    if key in _cache:
        return _cache[key]

    renderer = QSvgRenderer(QByteArray(_svg(name, color, fill)))
    image = QImage(px, px, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    ic = QIcon(QPixmap.fromImage(image))
    _cache[key] = ic
    return ic


def size(px: int) -> QSize:
    return QSize(px, px)
