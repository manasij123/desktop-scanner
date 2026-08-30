"""Tab-style selector (e.g. Original / Photo / Docs / Clear) — horizontal
by default, or a vertical stack for a side panel."""
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from clearscanner.ui import theme

LABELS = {
    "original": "Original", "photo": "Photo", "docs": "Docs", "clear": "Clear",
    "color": "Color", "bw": "B/W",
}


class SegmentedControl(QFrame):
    def __init__(self, options, on_change=None, default=None, vertical=False, parent=None):
        super().__init__(parent)
        self.setObjectName("tabBar")
        self._on_change = on_change
        self._buttons = {}

        layout = (QVBoxLayout if vertical else QHBoxLayout)(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        n = len(list(options))

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for option in options:
            btn = QPushButton(LABELS.get(option, option.title()))
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setFixedHeight(34 if vertical else btn.sizeHint().height())
            theme.set_kind(btn, "tab")
            btn.clicked.connect(lambda _checked, o=option: self._select(o))
            layout.addWidget(btn)
            self._group.addButton(btn)
            self._buttons[option] = btn

        if vertical:
            self.setFixedHeight(34 * n + 3 * (n - 1) + 8)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        selected = self._buttons.get(default) or next(iter(self._buttons.values()), None)
        if selected is not None:
            selected.setChecked(True)

    def _select(self, option: str):
        if self._on_change is not None:
            self._on_change(option)

    def current(self) -> str:
        for option, btn in self._buttons.items():
            if btn.isChecked():
                return option
        return ""

    def setCurrent(self, option: str):
        btn = self._buttons.get(option)
        if btn is not None:
            btn.setChecked(True)
