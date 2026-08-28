"""App-wide modern dark theme: QSS stylesheet + small style helpers.

Requires QApplication.setStyle("Fusion") — the native Windows style
ignores several QSS properties (border-radius, custom hover colors) on
QPushButton/QComboBox, so Fusion is what makes this theme actually render.
"""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QPushButton, QWidget

BG = "#1a1d21"
BG_ELEV = "#22262b"
BG_ELEV_2 = "#2a2f36"
BG_ELEV_3 = "#333941"
BORDER = "#343a42"
BORDER_SOFT = "#2b2f35"
TEXT = "#e8eaed"
TEXT_MUTED = "#9aa0a6"
TEXT_DIM = "#5b6067"
ACCENT = "#4da3ff"
ACCENT_HOVER = "#6db4ff"
ACCENT_PRESSED = "#3b8ce0"
ACCENT_SOFT = "#21374d"
DANGER = "#e2726b"
DANGER_HOVER = "#ea948e"
RADIUS = 10
RADIUS_LG = 16

APP_STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}}

QLabel {{
    background: transparent;
}}

QPushButton {{
    background-color: {BG_ELEV_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 8px 18px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {BG_ELEV_3};
    border-color: #454c56;
}}
QPushButton:pressed {{
    background-color: #26292f;
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    background-color: #202327;
    border-color: {BORDER_SOFT};
}}

QPushButton[kind="primary"] {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: #0c1116;
    font-weight: 600;
}}
QPushButton[kind="primary"]:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton[kind="primary"]:pressed {{
    background-color: {ACCENT_PRESSED};
}}
QPushButton[kind="primary"]:disabled {{
    background-color: #2c3a4a;
    border-color: #2c3a4a;
    color: #6c7a89;
}}

QPushButton[kind="danger"] {{
    color: {DANGER};
    border-color: {BORDER};
}}
QPushButton[kind="danger"]:hover {{
    background-color: #3a2323;
    color: {DANGER_HOVER};
    border-color: {DANGER_HOVER};
}}

QPushButton[kind="tab"] {{
    background-color: transparent;
    border: none;
    border-radius: {RADIUS}px;
    padding: 9px 18px;
    color: {TEXT_MUTED};
    font-weight: 500;
}}
QPushButton[kind="tab"]:hover:!checked {{
    background-color: {BG_ELEV_3};
    color: {TEXT};
}}
QPushButton[kind="tab"]:checked {{
    background-color: {ACCENT};
    color: #0c1116;
    font-weight: 600;
}}

QFrame#tabBar {{
    background-color: {BG_ELEV};
    border: 1px solid {BORDER};
    border-radius: {RADIUS + 4}px;
}}

QPushButton[kind="icon"] {{
    background-color: {BG_ELEV_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 0px;
    min-width: 42px;
    max-width: 42px;
    min-height: 42px;
    max-height: 42px;
    font-size: 17px;
}}
QPushButton[kind="icon"]:hover {{
    background-color: {BG_ELEV_3};
    border-color: #454c56;
}}
QPushButton[kind="icon"]:pressed {{
    background-color: #26292f;
}}
QPushButton[kind="icon"]:disabled {{
    color: {TEXT_DIM};
    background-color: #202327;
    border-color: {BORDER_SOFT};
}}
QPushButton[kind="icon-danger"] {{
    color: {DANGER};
}}
QPushButton[kind="icon-danger"]:hover {{
    background-color: #3a2323;
    color: {DANGER_HOVER};
    border-color: {DANGER_HOVER};
}}

QPushButton[kind="icon-primary"] {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: 26px;
    padding: 0px;
    min-width: 52px;
    max-width: 52px;
    min-height: 52px;
    max-height: 52px;
    font-size: 20px;
    font-weight: 700;
    color: #0c1116;
}}
QPushButton[kind="icon-primary"]:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton[kind="icon-primary"]:pressed {{
    background-color: {ACCENT_PRESSED};
}}
QPushButton[kind="icon-primary"]:disabled {{
    background-color: #2c3a4a;
    border-color: #2c3a4a;
    color: #6c7a89;
}}

QComboBox {{
    background-color: {BG_ELEV_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 6px 12px;
    min-width: 90px;
}}
QComboBox:hover {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_ELEV_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: {ACCENT};
    selection-color: #0c1116;
    outline: none;
    padding: 4px;
}}

QFrame#card {{
    background-color: {BG_ELEV};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_LG}px;
}}

QLabel#hint {{
    color: {TEXT_MUTED};
    font-size: 13px;
}}

QLabel#pageTitle {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 600;
}}

QListWidget {{
    background-color: {BG_ELEV};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_LG}px;
    padding: 10px;
    outline: none;
}}
QListWidget::item {{
    background-color: {BG_ELEV_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    margin-bottom: 10px;
    padding: 6px;
    color: {TEXT_MUTED};
}}
QListWidget::item:hover {{
    border-color: {ACCENT};
}}
QListWidget::item:selected {{
    border-color: {ACCENT};
    background-color: {ACCENT_SOFT};
    color: {TEXT};
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {BG_ELEV_3};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    border: 2px solid {BG_ELEV};
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {ACCENT_HOVER};
}}

QStatusBar {{
    background-color: {BG_ELEV};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BG_ELEV_3};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {BORDER};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def set_kind(button: QPushButton, kind: str):
    """Tag a button as 'primary' / 'danger' / default so the QSS above styles it."""
    button.setProperty("kind", kind)
    button.style().unpolish(button)
    button.style().polish(button)


def apply_shadow(widget: QWidget, blur: int = 32, y_offset: int = 10, alpha: int = 150):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)
