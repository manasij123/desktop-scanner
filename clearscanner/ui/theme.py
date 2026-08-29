"""App-wide visual theme — a light, editorial palette shared with the
download site: warm off-white canvas, ink-indigo text, one violet accent.

Requires QApplication.setStyle("Fusion") — the native Windows style
ignores several QSS properties (border-radius, custom hover/checked
colours) on QPushButton/QComboBox, so Fusion is what makes this render.
"""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QPushButton, QWidget

# ---- palette ---------------------------------------------------------
BG          = "#F3F1EA"   # warm off-white app canvas
SURFACE     = "#FFFFFF"   # cards, panels, inputs
SURFACE_2   = "#FBFAF6"   # hover / subtle fill on a light surface
SURFACE_SUNK = "#ECE9E0"  # sunken tracks (segmented control, slider groove)

INK         = "#1E1B2E"   # primary text — warm near-black
INK_SOFT    = "#514E60"   # secondary text
MUTED       = "#8B8794"   # captions, disabled text

EDGE        = "#E6E1D5"   # hairline borders
EDGE_STRONG = "#D5CFC0"   # dividers, stronger outlines

ACCENT       = "#5B4BE6"  # violet — the one accent
ACCENT_HOVER = "#6E5EF5"
ACCENT_PRESSED = "#4A3CCB"
ACCENT_WASH  = "#ECE9FF"  # soft violet fill for selected / active surfaces
ACCENT_INK   = "#463AC8"  # violet text that reads on a light ground

DANGER       = "#D6453F"
DANGER_HOVER = "#E85952"
DANGER_WASH  = "#FCEBEA"
GOOD         = "#1F9D6B"

ON_ACCENT   = "#FFFFFF"   # text on a filled accent button

RADIUS      = 10
RADIUS_LG   = 16
RADIUS_PILL = 999

# Back-compat aliases (a few call sites still use the old dark-theme names).
BG_ELEV = SURFACE
BG_ELEV_2 = SURFACE_2
BG_ELEV_3 = SURFACE_SUNK
BORDER = EDGE
BORDER_SOFT = EDGE
TEXT = INK
TEXT_MUTED = MUTED
TEXT_DIM = MUTED
ACCENT_SOFT = ACCENT_WASH

_FONT = '"Segoe UI Variable Text", "Segoe UI", "Inter", system-ui, sans-serif'

APP_STYLESHEET = f"""
* {{
    font-family: {_FONT};
}}

QWidget {{
    background-color: {BG};
    color: {INK};
    font-size: 13px;
}}
QMainWindow, QDialog {{ background-color: {BG}; }}

QLabel {{ background: transparent; color: {INK}; }}
QLabel:disabled {{ color: {MUTED}; }}

QToolTip {{
    background-color: {INK};
    color: #F5F4FA;
    border: none;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 12px;
}}

/* ---- buttons ---------------------------------------------------- */
QPushButton {{
    background-color: {SURFACE};
    color: {INK};
    border: 1px solid {EDGE_STRONG};
    border-radius: {RADIUS}px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {SURFACE_2};
    border-color: {MUTED};
}}
QPushButton:pressed {{
    background-color: {SURFACE_SUNK};
}}
QPushButton:disabled {{
    color: {MUTED};
    background-color: {SURFACE_2};
    border-color: {EDGE};
}}

QPushButton[kind="primary"] {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: {ON_ACCENT};
    font-weight: 600;
}}
QPushButton[kind="primary"]:hover  {{ background-color: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[kind="primary"]:pressed {{ background-color: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton[kind="primary"]:disabled {{
    background-color: #C9C3F3;
    border-color: #C9C3F3;
    color: #FFFFFF;
}}

QPushButton[kind="ghost"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {INK_SOFT};
    font-weight: 600;
}}
QPushButton[kind="ghost"]:hover {{ background-color: {SURFACE_2}; color: {INK}; border-color: {EDGE}; }}
QPushButton[kind="ghost"]:pressed {{ background-color: {SURFACE_SUNK}; }}

QPushButton[kind="danger"] {{
    background-color: {SURFACE};
    color: {DANGER};
    border-color: {EDGE_STRONG};
}}
QPushButton[kind="danger"]:hover {{
    background-color: {DANGER_WASH};
    color: {DANGER_HOVER};
    border-color: {DANGER_HOVER};
}}

/* segmented-control buttons */
QPushButton[kind="tab"] {{
    background-color: transparent;
    border: none;
    border-radius: {RADIUS - 2}px;
    padding: 8px 18px;
    color: {INK_SOFT};
    font-weight: 600;
}}
QPushButton[kind="tab"]:hover:!checked {{
    background-color: {SURFACE};
    color: {INK};
}}
QPushButton[kind="tab"]:checked {{
    background-color: {ACCENT};
    color: {ON_ACCENT};
}}

QFrame#tabBar {{
    background-color: {SURFACE_SUNK};
    border: 1px solid {EDGE};
    border-radius: {RADIUS + 3}px;
}}

/* ---- left icon rail ---------------------------------------- */
QFrame#rail {{
    background-color: {SURFACE};
    border: none;
    border-right: 1px solid {EDGE};
}}
QLabel#railLogo {{
    background-color: {ACCENT_WASH};
    border: 1px solid {EDGE};
    border-radius: 12px;
}}
QPushButton[kind="rail"], QPushButton[kind="rail-primary"] {{
    border-radius: 13px;
    padding: 0;
    min-width: 44px; max-width: 44px;
    min-height: 44px; max-height: 44px;
}}
QPushButton[kind="rail"] {{
    background-color: transparent;
    border: 1px solid transparent;
}}
QPushButton[kind="rail"]:hover {{ background-color: {SURFACE_SUNK}; }}
QPushButton[kind="rail-primary"] {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
}}
QPushButton[kind="rail-primary"]:hover {{ background-color: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[kind="rail-primary"]:pressed {{ background-color: {ACCENT_PRESSED}; }}

/* nested panel inside a card (the Adjust sliders) */
QFrame#innerPanel {{
    background-color: {SURFACE_2};
    border: 1px solid {EDGE};
    border-radius: {RADIUS}px;
}}

QLabel#valueChip {{
    color: {ACCENT_INK};
    background-color: {ACCENT_WASH};
    border-radius: 6px;
    padding: 2px 0;
    font-size: 11px;
    font-weight: 700;
}}

/* icon buttons */
QPushButton[kind="icon"] {{
    background-color: {SURFACE};
    border: 1px solid {EDGE_STRONG};
    border-radius: {RADIUS}px;
    padding: 0px;
    min-width: 40px; max-width: 40px;
    min-height: 40px; max-height: 40px;
    font-size: 16px;
}}
QPushButton[kind="icon"]:hover {{ background-color: {SURFACE_2}; border-color: {MUTED}; }}
QPushButton[kind="icon"]:pressed {{ background-color: {SURFACE_SUNK}; }}
QPushButton[kind="icon"]:disabled {{ color: {MUTED}; background-color: {SURFACE_2}; border-color: {EDGE}; }}

QPushButton[kind="icon-danger"] {{ color: {DANGER}; }}
QPushButton[kind="icon-danger"]:hover {{
    background-color: {DANGER_WASH}; color: {DANGER_HOVER}; border-color: {DANGER_HOVER};
}}

QPushButton[kind="icon-primary"] {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: 26px;
    padding: 0px;
    min-width: 52px; max-width: 52px;
    min-height: 52px; max-height: 52px;
    font-size: 20px;
    font-weight: 700;
    color: {ON_ACCENT};
}}
QPushButton[kind="icon-primary"]:hover {{ background-color: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[kind="icon-primary"]:pressed {{ background-color: {ACCENT_PRESSED}; }}
QPushButton[kind="icon-primary"]:disabled {{ background-color: #C9C3F3; border-color: #C9C3F3; }}

/* ---- inputs --------------------------------------------------- */
QComboBox {{
    background-color: {SURFACE};
    border: 1px solid {EDGE_STRONG};
    border-radius: {RADIUS}px;
    padding: 7px 12px;
    min-width: 90px;
    color: {INK};
}}
QComboBox:hover {{ border-color: {MUTED}; }}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    border: 1px solid {EDGE_STRONG};
    border-radius: 8px;
    selection-background-color: {ACCENT_WASH};
    selection-color: {ACCENT_INK};
    outline: none;
    padding: 4px;
}}

QTextEdit {{
    background-color: {SURFACE};
    border: 1px solid {EDGE_STRONG};
    border-radius: {RADIUS}px;
    padding: 10px 12px;
    color: {INK};
    selection-background-color: {ACCENT_WASH};
    selection-color: {ACCENT_INK};
}}
QTextEdit:focus {{ border-color: {ACCENT}; }}

QCheckBox {{ spacing: 8px; color: {INK}; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid {EDGE_STRONG};
    border-radius: 5px;
    background: {SURFACE};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: none;
}}

/* ---- surfaces ------------------------------------------------- */
QFrame#card {{
    background-color: {SURFACE};
    border: 1px solid {EDGE};
    border-radius: {RADIUS_LG}px;
}}

QLabel#pageTitle {{
    color: {INK};
    font-size: 16px;
    font-weight: 700;
    letter-spacing: -0.2px;
}}
QLabel#hint {{
    color: {MUTED};
    font-size: 12.5px;
}}
QLabel#sectionLabel {{
    color: {INK_SOFT};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ---- page-list sidebar -------------------------------------- */
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    background-color: {SURFACE_2};
    border: 1px solid {EDGE};
    border-radius: {RADIUS}px;
    margin-bottom: 9px;
    padding: 5px;
    color: {INK_SOFT};
}}
QListWidget::item:hover {{ border-color: {MUTED}; }}
QListWidget::item:selected {{
    border-color: {ACCENT};
    background-color: {ACCENT_WASH};
    color: {ACCENT_INK};
}}

/* ---- sliders ------------------------------------------------- */
QSlider::groove:horizontal {{
    height: 5px;
    background: {SURFACE_SUNK};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {SURFACE};
    border: 2px solid {ACCENT};
    width: 15px; height: 15px;
    margin: -7px 0;
    border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{ border-color: {ACCENT_HOVER}; background: {ACCENT_WASH}; }}

/* ---- chrome ------------------------------------------------- */
QStatusBar {{
    background-color: {SURFACE};
    color: {INK_SOFT};
    border-top: 1px solid {EDGE};
    font-size: 12px;
}}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {EDGE_STRONG};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {EDGE_STRONG}; border-radius: 4px; min-width: 28px; }}
QScrollBar::handle:horizontal:hover {{ background: {MUTED}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""


def set_kind(button: QPushButton, kind: str):
    """Tag a button ('primary' / 'ghost' / 'danger' / 'tab' / 'icon' / …)
    so the QSS above styles it."""
    button.setProperty("kind", kind)
    button.style().unpolish(button)
    button.style().polish(button)


def apply_shadow(widget: QWidget, blur: int = 40, y_offset: int = 14, alpha: int = 26):
    """Soft, slightly-cool drop shadow for cards on the light canvas."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(31, 27, 46, alpha))
    widget.setGraphicsEffect(effect)
