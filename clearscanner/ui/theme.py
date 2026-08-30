"""App-wide visual theme — a soft "glass" dashboard: a painted violet→cream
backdrop (see ui/backdrop.py) with frosted, semi-transparent panels and a
single violet accent that deepens into magenta on the side rail.

Requires QApplication.setStyle("Fusion") — the native Windows style
ignores border-radius / rgba backgrounds / custom checked colours on
QPushButton & QComboBox, so Fusion is what makes this render.
"""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QPushButton, QWidget

# ---- solid tokens (safe to pass to QColor / SVG) --------------------
BG          = "#F1EEF8"   # pale violet — the fallback behind the backdrop
SURFACE     = "#FFFFFF"
SURFACE_2   = "#F7F4FB"
SURFACE_SUNK = "#ECE7F3"  # crop-editor letterbox, thumbnail canvas

INK         = "#221F35"   # primary text — deep indigo-ink
INK_SOFT    = "#585569"
MUTED       = "#8C8899"

EDGE        = "#DED8EC"   # hairline (solid, for QColor use)
EDGE_STRONG = "#CFC8E2"

ACCENT       = "#5B4BE6"
ACCENT_HOVER = "#6D5DF5"
ACCENT_PRESSED = "#4A3AC8"
ACCENT_INK   = "#4536C4"
ACCENT_WASH  = "#EBE8FF"

DANGER       = "#D6453F"
DANGER_HOVER = "#E85952"
GOOD         = "#1F9D6B"
ON_ACCENT    = "#FFFFFF"

RADIUS      = 11
RADIUS_LG   = 18
RADIUS_PILL = 999

# ---- glass fills (QSS only — rgba strings, don't feed to QColor) ----
_GLASS       = "rgba(255, 255, 255, 0.55)"   # cards
_GLASS_HI    = "rgba(255, 255, 255, 0.82)"   # inputs / default buttons
_GLASS_SUNK  = "rgba(110, 96, 150, 0.12)"    # segmented / slider track
_GLASS_LINE  = "rgba(255, 255, 255, 0.92)"   # bright top-highlight border on glass
_EDGE_Q      = "rgba(96, 84, 140, 0.18)"
_RAIL        = "qlineargradient(x1:0, y1:0, x2:0.3, y2:1, stop:0 #6E5EF5, stop:1 #8B44D6)"

# Back-compat aliases (older call sites).
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
* {{ font-family: {_FONT}; }}

QWidget {{ color: {INK}; font-size: 13px; }}
QMainWindow, QDialog {{ background-color: {BG}; }}
QDialog QWidget {{ background: transparent; }}

QLabel {{ background: transparent; color: {INK}; }}
QLabel:disabled {{ color: {MUTED}; }}

QToolTip {{
    background-color: {INK};
    color: #F4F2FA;
    border: none;
    border-radius: 7px;
    padding: 5px 9px;
    font-size: 12px;
}}

/* ---- buttons ---------------------------------------------------- */
QPushButton {{
    background-color: {_GLASS_HI};
    color: {INK};
    border: 1px solid {_EDGE_Q};
    border-radius: {RADIUS}px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover  {{ background-color: rgba(255,255,255,0.95); border-color: {MUTED}; }}
QPushButton:pressed {{ background-color: rgba(236,231,243,0.95); }}
QPushButton:disabled {{ color: {MUTED}; background-color: rgba(255,255,255,0.42); border-color: {_EDGE_Q}; }}

QPushButton[kind="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7767FF, stop:1 #5A45E0);
    border: 1px solid #6B5BF0;
    color: {ON_ACCENT};
    font-weight: 700;
}}
QPushButton[kind="primary"]:hover  {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8776FF, stop:1 #6A55F0);
    border-color: #8776FF;
}}
QPushButton[kind="primary"]:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton[kind="primary"]:disabled {{
    background: #CDC7F0; border-color: #CDC7F0; color: #FFFFFF;
}}

QPushButton[kind="ghost"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {INK_SOFT};
    font-weight: 600;
}}
QPushButton[kind="ghost"]:hover  {{ background-color: {_GLASS}; color: {INK}; border-color: {_EDGE_Q}; }}
QPushButton[kind="ghost"]:pressed {{ background-color: {_GLASS_SUNK}; }}
QPushButton[kind="ghost"]:checked {{ background-color: {ACCENT_WASH}; color: {ACCENT_INK}; border-color: {_EDGE_Q}; }}

QPushButton[kind="danger"] {{ background-color: {_GLASS_HI}; color: {DANGER}; border-color: {_EDGE_Q}; }}
QPushButton[kind="danger"]:hover {{ background-color: rgba(253,235,234,0.95); color: {DANGER_HOVER}; border-color: {DANGER_HOVER}; }}

/* segmented-control buttons */
QPushButton[kind="tab"] {{
    background-color: transparent;
    border: none;
    border-radius: {RADIUS - 3}px;
    padding: 8px 18px;
    color: {INK_SOFT};
    font-weight: 600;
}}
QPushButton[kind="tab"]:hover:!checked {{ background-color: rgba(255,255,255,0.7); color: {INK}; }}
QPushButton[kind="tab"]:checked {{ background-color: {ACCENT}; color: {ON_ACCENT}; }}

QFrame#tabBar {{
    background-color: {_GLASS_SUNK};
    border: 1px solid {_EDGE_Q};
    border-radius: {RADIUS + 2}px;
}}

/* icon buttons */
QPushButton[kind="icon"] {{
    background-color: {_GLASS_HI};
    border: 1px solid {_EDGE_Q};
    border-radius: {RADIUS}px;
    padding: 0px;
    min-width: 40px; max-width: 40px;
    min-height: 40px; max-height: 40px;
}}
QPushButton[kind="icon"]:hover  {{ background-color: rgba(255,255,255,0.98); border-color: {MUTED}; }}
QPushButton[kind="icon"]:pressed {{ background-color: rgba(236,231,243,0.95); }}
QPushButton[kind="icon"]:disabled {{ background-color: rgba(255,255,255,0.4); }}

QPushButton[kind="icon-danger"] {{ }}
QPushButton[kind="icon-danger"]:hover {{
    background-color: rgba(253,235,234,0.95); border-color: {DANGER_HOVER};
}}

QPushButton[kind="icon-primary"] {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: 27px;
    padding: 0px;
    min-width: 54px; max-width: 54px;
    min-height: 54px; max-height: 54px;
    color: {ON_ACCENT};
}}
QPushButton[kind="icon-primary"]:hover  {{ background-color: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[kind="icon-primary"]:pressed {{ background-color: {ACCENT_PRESSED}; }}
QPushButton[kind="icon-primary"]:disabled {{ background-color: #C7C0F0; border-color: #C7C0F0; }}

/* ---- inputs --------------------------------------------------- */
QComboBox {{
    background-color: {_GLASS_HI};
    border: 1px solid {_EDGE_Q};
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
    border-radius: 9px;
    selection-background-color: {ACCENT_WASH};
    selection-color: {ACCENT_INK};
    outline: none;
    padding: 4px;
}}

QTextEdit {{
    background-color: rgba(255,255,255,0.85);
    border: 1px solid {_EDGE_Q};
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
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* ---- surfaces ------------------------------------------------- */
/* content sits on a near-solid card; floating controls are glass. */
QFrame#card {{
    background-color: rgba(255,255,255,0.86);
    border: 1px solid {_GLASS_LINE};
    border-radius: {RADIUS_LG}px;
}}
QFrame#glassCard {{
    background-color: {_GLASS};
    border: 1px solid {_GLASS_LINE};
    border-radius: {RADIUS_LG}px;
}}
QFrame#innerPanel {{
    background-color: rgba(255,255,255,0.40);
    border: 1px solid {_EDGE_Q};
    border-radius: {RADIUS}px;
}}

QLabel#pageTitle {{ color: {INK}; font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }}
QLabel#subTitle {{ color: {MUTED}; font-size: 12px; font-weight: 500; }}
QLabel#hint {{ color: {MUTED}; font-size: 12.5px; }}
QLabel#sectionLabel {{ color: {INK_SOFT}; font-size: 10px; font-weight: 800; letter-spacing: 1.1px; }}

QWidget#statPill {{
    background-color: rgba(255,255,255,0.55);
    border: 1px solid {_GLASS_LINE};
    border-radius: 13px;
}}
QWidget#floatBar {{
    background-color: rgba(255,255,255,0.72);
    border: 1px solid {_GLASS_LINE};
    border-radius: {RADIUS + 6}px;
}}
QLabel#valueChip {{
    color: {ACCENT_INK};
    background-color: {ACCENT_WASH};
    border-radius: 7px;
    padding: 2px 0;
    font-size: 11px;
    font-weight: 800;
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ---- left icon rail ---------------------------------------- */
QFrame#rail {{
    background: {_RAIL};
    border: none;
}}
QLabel#railLogo {{
    background-color: rgba(255,255,255,0.18);
    border: 1px solid rgba(255,255,255,0.30);
    border-radius: 13px;
}}
QPushButton[kind="rail"], QPushButton[kind="rail-primary"] {{
    border-radius: 14px;
    padding: 0;
    min-width: 44px; max-width: 44px;
    min-height: 44px; max-height: 44px;
}}
QPushButton[kind="rail"] {{ background-color: transparent; border: 1px solid transparent; }}
QPushButton[kind="rail"]:hover {{ background-color: rgba(255,255,255,0.16); }}
QPushButton[kind="rail-primary"] {{
    background-color: rgba(255,255,255,0.22);
    border: 1px solid rgba(255,255,255,0.35);
}}
QPushButton[kind="rail-primary"]:hover  {{ background-color: rgba(255,255,255,0.34); }}
QPushButton[kind="rail-primary"]:pressed {{ background-color: rgba(255,255,255,0.16); }}

/* ---- page-list sidebar -------------------------------------- */
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{
    background-color: rgba(255,255,255,0.55);
    border: 1px solid {_EDGE_Q};
    border-radius: {RADIUS}px;
    margin-bottom: 9px;
    padding: 5px;
    color: {INK_SOFT};
}}
QListWidget::item:hover {{ border-color: {MUTED}; }}
QListWidget::item:selected {{ border-color: {ACCENT}; background-color: {ACCENT_WASH}; color: {ACCENT_INK}; }}

/* ---- sliders ------------------------------------------------- */
QSlider::groove:horizontal {{ height: 5px; background: {_GLASS_SUNK}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: #FFFFFF;
    border: 2px solid {ACCENT};
    width: 15px; height: 15px;
    margin: -7px 0;
    border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{ border-color: {ACCENT_HOVER}; background: {ACCENT_WASH}; }}

/* ---- chrome ------------------------------------------------- */
QStatusBar {{
    background-color: rgba(255,255,255,0.55);
    color: {INK_SOFT};
    border-top: 1px solid {_EDGE_Q};
    font-size: 12px;
}}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {EDGE_STRONG}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {EDGE_STRONG}; border-radius: 4px; min-width: 28px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""


def set_kind(button: QPushButton, kind: str):
    button.setProperty("kind", kind)
    button.style().unpolish(button)
    button.style().polish(button)


def apply_shadow(widget: QWidget, blur: int = 50, y_offset: int = 18, alpha: int = 45):
    """Soft, violet-tinted drop shadow that lifts the frosted panels off
    the painted backdrop."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(58, 40, 105, alpha))
    widget.setGraphicsEffect(effect)


def apply_glow(widget: QWidget, blur: int = 34, alpha: int = 120):
    """A coloured bloom under the primary action — makes it read as the
    one thing to click."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 6)
    effect.setColor(QColor(91, 75, 230, alpha))
    widget.setGraphicsEffect(effect)
