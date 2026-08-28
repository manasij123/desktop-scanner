"""Sidebar widget: ordered list of scanned pages (thumbnails), with
drag-to-reorder, rotate, delete, and re-filtering an already-added page."""
import cv2
import numpy as np
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from clearscanner.ui import theme
from clearscanner.ui.qt_image import to_pixmap

THUMB_SIZE = QSize(120, 160)
WARPED_ROLE = Qt.UserRole + 1
FALLBACK_ROLE = Qt.UserRole + 2


def _make_thumbnail(image: np.ndarray) -> np.ndarray:
    """Fit `image` inside THUMB_SIZE preserving its aspect ratio, letterboxed
    on a neutral background — a plain resize-to-box would stretch pages
    that aren't already close to THUMB_SIZE's own ratio (e.g. a wide/flat
    crop shown squashed tall in the sidebar), making the thumbnail lie
    about the page's actual shape."""
    display = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    h, w = display.shape[:2]
    tw, th = THUMB_SIZE.width(), THUMB_SIZE.height()

    scale = min(tw / w, th / h)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    resized = cv2.resize(display, (new_w, new_h), interpolation=cv2.INTER_AREA)

    canvas = np.full((th, tw, 3), (0x36, 0x2f, 0x2a), dtype=np.uint8)  # theme.BG_ELEV_2 "#2a2f36", BGR order
    x, y = (tw - new_w) // 2, (th - new_h) // 2
    canvas[y:y + new_h, x:x + new_w] = resized
    return canvas


class PageList(QWidget):
    pagesChanged = Signal()
    pageSelected = Signal(int)  # emitted whenever the highlighted row changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages: list[np.ndarray] = []  # processed (thumbnail/export) images
        # Pre-filter warped source per page — kept alongside so re-picking a
        # filter/B&W for an *already-added* page re-derives from the clean
        # source instead of stacking a filter on top of an already-filtered
        # image (which looks wrong and can't be undone).
        self._warped_pages: list[np.ndarray] = []
        # Whether THIS page's own document-boundary detection fell back to
        # the full image — gates Docs/Clear's background-crush step (see
        # filters.to_docs), which does real damage if applied to a genuine
        # document photo. Stored per page (not just as a single "current"
        # flag on the window) so re-filtering an older page after loading a
        # different image can't pick up the wrong image's detection outcome.
        self._fallback_flags: list[bool] = []

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setIconSize(THUMB_SIZE)
        self._list.setGridSize(QSize(THUMB_SIZE.width() + 24, THUMB_SIZE.height() + 34))
        self._list.setMovement(QListWidget.Snap)
        self._list.setFlow(QListWidget.TopToBottom)
        self._list.setWrapping(False)
        self._list.setDragDropMode(QAbstractItemView.InternalMove)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.model().rowsMoved.connect(self._sync_order_from_widget)
        self._list.currentRowChanged.connect(self._on_current_row_changed)
        theme.apply_shadow(self._list)

        rotate_left_btn = QPushButton("↺")
        theme.set_kind(rotate_left_btn, "icon")
        rotate_left_btn.setToolTip("Rotate Left")
        rotate_left_btn.clicked.connect(lambda: self._rotate_selected(cv2.ROTATE_90_COUNTERCLOCKWISE))

        rotate_right_btn = QPushButton("↻")
        theme.set_kind(rotate_right_btn, "icon")
        rotate_right_btn.setToolTip("Rotate Right")
        rotate_right_btn.clicked.connect(lambda: self._rotate_selected(cv2.ROTATE_90_CLOCKWISE))

        delete_btn = QPushButton("✕")
        theme.set_kind(delete_btn, "icon-danger")
        delete_btn.setToolTip("Delete Page")
        delete_btn.clicked.connect(self._delete_selected)

        icon_row = QHBoxLayout()
        icon_row.setSpacing(8)
        icon_row.addWidget(rotate_left_btn)
        icon_row.addWidget(rotate_right_btn)
        icon_row.addStretch()
        icon_row.addWidget(delete_btn)

        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.addWidget(self._list, stretch=1)
        layout.addSpacing(4)
        layout.addLayout(icon_row)
        self.setLayout(layout)

    # ---- public API --------------------------------------------------

    def add_page(self, processed: np.ndarray, warped: np.ndarray = None, fallback_used: bool = False):
        self._pages.append(processed)
        self._warped_pages.append(warped if warped is not None else processed)
        self._fallback_flags.append(fallback_used)
        self._refresh()
        self._list.setCurrentRow(len(self._pages) - 1)
        self.pagesChanged.emit()

    def update_page(self, index: int, processed: np.ndarray):
        """Replace a page's displayed/exported image in place (re-filter),
        without touching its stored warped source or its position."""
        if not (0 <= index < len(self._pages)):
            return
        self._pages[index] = processed
        selected = self._list.currentRow()
        self._refresh()
        self._list.setCurrentRow(selected)
        self.pagesChanged.emit()

    def pages(self) -> list:
        return list(self._pages)

    def warped_page(self, index: int):
        return self._warped_pages[index] if 0 <= index < len(self._warped_pages) else None

    def fallback_used_for_page(self, index: int) -> bool:
        return self._fallback_flags[index] if 0 <= index < len(self._fallback_flags) else False

    def count(self) -> int:
        return len(self._pages)

    # ---- internal ------------------------------------------------------

    def _selected_index(self):
        row = self._list.currentRow()
        return row if 0 <= row < len(self._pages) else None

    def _on_current_row_changed(self, row: int):
        if 0 <= row < len(self._pages):
            self.pageSelected.emit(row)

    def _rotate_selected(self, rotate_code):
        idx = self._selected_index()
        if idx is None:
            return
        self._pages[idx] = cv2.rotate(self._pages[idx], rotate_code)
        self._warped_pages[idx] = cv2.rotate(self._warped_pages[idx], rotate_code)
        self._refresh()
        self._list.setCurrentRow(idx)
        self.pagesChanged.emit()

    def _delete_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        del self._pages[idx]
        del self._warped_pages[idx]
        del self._fallback_flags[idx]
        self._refresh()
        self.pagesChanged.emit()

    def _sync_order_from_widget(self, *_args):
        new_pages = []
        new_warped = []
        new_fallback = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            new_pages.append(item.data(Qt.UserRole))
            new_warped.append(item.data(WARPED_ROLE))
            new_fallback.append(item.data(FALLBACK_ROLE))
        self._pages = new_pages
        self._warped_pages = new_warped
        self._fallback_flags = new_fallback
        self._renumber_labels()
        self.pagesChanged.emit()

    def _renumber_labels(self):
        for i in range(self._list.count()):
            self._list.item(i).setText(f"Page {i + 1}")

    def _refresh(self):
        self._list.blockSignals(True)
        self._list.clear()
        for i, img in enumerate(self._pages):
            thumb = _make_thumbnail(img)
            item = QListWidgetItem(QIcon(to_pixmap(thumb)), f"Page {i + 1}")
            item.setData(Qt.UserRole, img)
            item.setData(WARPED_ROLE, self._warped_pages[i])
            item.setData(FALLBACK_ROLE, self._fallback_flags[i])
            self._list.addItem(item)
        self._list.blockSignals(False)
