"""Main application window.

Flow: Open Image -> background corner detection -> crop editor (drag to
adjust) -> Confirm Crop -> background warp -> filtered preview -> Save.
"""
import os
import tempfile
import threading

import cv2
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from clearscanner._version import __version__
from clearscanner.core import detector, filters, ocr, pdf_import
from clearscanner.output.pdf_writer import images_to_pdf
from clearscanner.ui import icons, theme
from clearscanner.ui.batch_dialog import BatchSettingsDialog
from clearscanner.ui.crop_editor import CropEditor
from clearscanner.ui.ocr_dialog import OcrResultDialog
from clearscanner.ui.ocr_worker import OcrWorker
from clearscanner.ui.page_list import PageList
from clearscanner.ui.qt_image import to_pixmap
from clearscanner.ui.scan_worker import DetectWorker, FilterWorker, WarpWorker
from clearscanner.ui.segmented_control import SegmentedControl
from clearscanner.ui.toggle_switch import ToggleSwitch
from clearscanner.ui.update_worker import UpdateCheckWorker, UpdateDownloadWorker

OPEN_FILTER = "Images and PDFs (*.png *.jpg *.jpeg *.bmp *.pdf)"
SAVE_FILTER = "JPEG (*.jpg);;PNG (*.png)"
PDF_FILTER = "PDF (*.pdf)"
DESKTOP_DIR = os.path.join(os.path.expanduser("~"), "Desktop")


def _card(inner: QWidget, margin: int = 10, shadow: bool = True) -> QFrame:
    """Wrap `inner` in a rounded card panel (see ui/theme.py QFrame#card)."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.addWidget(inner)
    if shadow:
        theme.apply_shadow(frame)
    return frame


def _section_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionLabel")
    return label


def _hairline(vertical: bool = False) -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.VLine if vertical else QFrame.HLine)
    line.setStyleSheet(f"color: {theme.EDGE}; background: {theme.EDGE};")
    line.setFixedWidth(1) if vertical else line.setFixedHeight(1)
    return line


def _icon_button(name: str, tooltip: str, kind: str = "icon", on_accent: bool = False) -> QPushButton:
    btn = QPushButton()
    theme.set_kind(btn, kind)
    color = "#FFFFFF" if on_accent else theme.INK_SOFT
    btn.setIcon(icons.icon(name, color, px=44))
    btn.setIconSize(icons.size(19 if kind == "icon" else 22))
    btn.setToolTip(tooltip)
    return btn


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Desktop Scanner {__version__}")
        self.resize(1200, 820)
        self.setMinimumSize(940, 640)

        self._original_image = None  # BGR ndarray, as loaded
        self._initial_corners = None  # detected/fallback corners, for Reset
        # Whether document-boundary detection fell back to the full image
        # for the CURRENT self._warped_image — gates Docs/Clear's
        # background-crush step (see filters.to_docs). Defaults False (the
        # safe "don't crush" state) until a real detection result — which
        # always runs before the first filter can be applied — says
        # otherwise.
        self._detection_fallback_used = False
        self._warped_image = None  # BGR ndarray, post-warp / pre-filter
        self._base_processed_image = None  # filter output, before Enhance sliders
        self._processed_image = None  # base + Enhance sliders applied — ready to save
        self._viewing_page_index = None  # set while re-filtering an already-added page
        self._detect_worker = None
        self._detect_request_id = 0
        self._warp_worker = None
        self._filter_worker = None
        self._filter_request_id = 0
        self._ocr_worker = None
        self._page_anim = None  # keep the running QPropertyAnimation alive
        self._active_workers = []  # see _track_worker
        self._pending_images = []  # queued paths for batch import (see _on_open)
        self._batch_index = 1
        self._batch_total = 1
        self._batch_skip_crop = False
        # Whether the load_image() call in flight right now was for a temp
        # PNG rendered from an imported PDF's page (see _on_open) — those
        # are already a clean digital page, not a photo of a physical
        # document, so detection has nothing real to find a boundary
        # against and would call it a fallback; _on_detect_finished uses
        # this to override that verdict back to "this IS a real document"
        # instead of wrongly enabling the subject/background crush meant
        # for non-document photos (see filters.to_docs's
        # allow_background_crush note) on a page that's legitimately just
        # text.
        self._current_load_is_pdf_page = False
        self._pdf_derived_paths = set()  # temp paths not yet consumed by load_image()

        self._enhance_timer = QTimer(self)
        self._enhance_timer.setSingleShot(True)
        self._enhance_timer.setInterval(30)
        self._enhance_timer.timeout.connect(self._apply_enhancement)

        self._build_ui()

        # Auto-update state (see _on_update_available); the check itself is
        # kicked off from _start_background_tasks after the window is shown.
        self._update_check_worker = None
        self._update_download_worker = None
        self._pending_update_installer = None  # path, once downloaded
        self._pending_update_version = None
        self._install_update_on_exit = False
        self._background_tasks_started = False

        # The ML model warm-up and the update check both do heavy work
        # (loading onnxruntime, a network round-trip) that fights the UI
        # thread for the GIL during construction and first paint. Defer
        # them until the window is actually on screen and idle.
        QTimer.singleShot(1200, self._start_background_tasks)

    def _start_background_tasks(self):
        if self._background_tasks_started:
            return
        self._background_tasks_started = True
        threading.Thread(target=detector.warm_up, daemon=True).start()
        self._start_update_check()

    # ---- UI construction -------------------------------------------------

    def _build_ui(self):
        rail = self._build_rail()

        # ---- header row --------------------------------------------------
        self._title_label = QLabel("Add a document")
        self._title_label.setObjectName("pageTitle")

        self._batch_progress_label = QLabel("")
        self._batch_progress_label.setObjectName("hint")

        self._print_btn = QPushButton("  Print")
        self._print_btn.setIcon(icons.icon("print", theme.INK_SOFT, px=44))
        self._print_btn.setIconSize(icons.size(16))
        self._print_btn.clicked.connect(self._on_print)
        self._print_btn.setEnabled(False)

        self._export_btn = QPushButton("  Export PDF")
        theme.set_kind(self._export_btn, "primary")
        self._export_btn.setIcon(icons.icon("download", "#FFFFFF", px=44))
        self._export_btn.setIconSize(icons.size(16))
        self._export_btn.clicked.connect(self._on_export_pdf)
        self._export_btn.setEnabled(False)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(self._title_label)
        header.addSpacing(10)
        header.addWidget(self._batch_progress_label)
        header.addStretch()
        header.addWidget(self._print_btn)
        header.addWidget(self._export_btn)

        # ---- work area --------------------------------------------------
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_crop_page())
        self._stack.addWidget(self._build_preview_page())

        self._page_list = PageList()
        self._page_list.pagesChanged.connect(self._on_pages_changed)
        self._page_list.pageSelected.connect(self._on_page_selected)
        self._page_list.setFixedWidth(212)

        content = QHBoxLayout()
        content.setSpacing(18)
        content.addWidget(self._page_list)
        content.addWidget(self._stack, stretch=1)

        main_col = QVBoxLayout()
        main_col.setContentsMargins(24, 18, 24, 16)
        main_col.setSpacing(14)
        main_col.addLayout(header)
        main_col.addWidget(_hairline())
        main_col.addLayout(content, stretch=1)

        root = QHBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(rail)
        root.addLayout(main_col, stretch=1)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())
        self.statusBar().setSizeGripEnabled(False)

    def _build_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(66)

        logo = QLabel()
        logo.setPixmap(icons.icon("scan", theme.ACCENT, px=52).pixmap(24, 24))
        logo.setObjectName("railLogo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(44, 44)

        add_btn = QPushButton()
        theme.set_kind(add_btn, "rail-primary")
        add_btn.setIcon(icons.icon("plus", "#FFFFFF", px=44))
        add_btn.setIconSize(icons.size(20))
        add_btn.setToolTip("Add photos or a PDF")
        add_btn.clicked.connect(self._on_open)

        info_btn = QPushButton()
        theme.set_kind(info_btn, "rail")
        info_btn.setIcon(icons.icon("info", theme.MUTED, px=44))
        info_btn.setIconSize(icons.size(18))
        info_btn.setToolTip("About Desktop Scanner")
        info_btn.clicked.connect(self._on_about)

        layout = QVBoxLayout(rail)
        layout.setContentsMargins(11, 14, 11, 14)
        layout.setSpacing(12)
        layout.addWidget(logo, alignment=Qt.AlignHCenter)
        layout.addSpacing(4)
        layout.addWidget(add_btn, alignment=Qt.AlignHCenter)
        layout.addStretch()
        layout.addWidget(info_btn, alignment=Qt.AlignHCenter)
        return rail

    def _build_crop_page(self) -> QWidget:
        self._crop_editor = CropEditor()

        reset_btn = QPushButton("  Reset to auto-detect")
        theme.set_kind(reset_btn, "ghost")
        reset_btn.setIcon(icons.icon("reset", theme.INK_SOFT, px=44))
        reset_btn.setIconSize(icons.size(15))
        reset_btn.clicked.connect(self._on_reset_corners)

        rotate_left_btn = _icon_button("rotate-left", "Rotate left")
        rotate_left_btn.clicked.connect(lambda: self._on_rotate_source(cv2.ROTATE_90_COUNTERCLOCKWISE))
        rotate_right_btn = _icon_button("rotate-right", "Rotate right")
        rotate_right_btn.clicked.connect(lambda: self._on_rotate_source(cv2.ROTATE_90_CLOCKWISE))

        confirm_btn = _icon_button("check", "Confirm crop", kind="icon-primary", on_accent=True)
        confirm_btn.clicked.connect(self._on_confirm_crop)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(reset_btn)
        bar.addStretch()
        bar.addWidget(rotate_left_btn)
        bar.addWidget(rotate_right_btn)
        bar.addSpacing(10)
        bar.addWidget(confirm_btn)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(_card(self._crop_editor, margin=8), stretch=1)
        layout.addLayout(bar)

        page = QWidget()
        page.setLayout(layout)
        return page

    def _build_preview_page(self) -> QWidget:
        self._preview = QLabel("No image loaded")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumSize(400, 380)
        self._preview.setObjectName("hint")
        # Ignored (not the QLabel default of Preferred): a QLabel's sizeHint
        # tracks whatever pixmap is currently set, so leaving the default
        # policy in place meant every _show_preview() call (e.g. every ~30ms
        # while dragging an Enhance slider) nudged the layout, which
        # resized the label, which changed the sizeHint again — a feedback
        # loop that showed up as the preview visibly jittering up/down.
        self._preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._filter_tabs = SegmentedControl(
            filters.COLOR_MODES, on_change=self._on_filter_changed, default="clear"
        )
        self._filter_tabs.setMaximumWidth(400)

        self._bw_toggle = ToggleSwitch("Colour", "B&W")
        self._bw_toggle.toggled.connect(self._on_bw_changed)

        style_row = QHBoxLayout()
        style_row.setSpacing(12)
        style_row.addWidget(_section_label("Scan style"))
        style_row.addSpacing(2)
        style_row.addWidget(self._filter_tabs)
        style_row.addStretch()
        style_row.addWidget(_section_label("Colour"))
        style_row.addWidget(self._bw_toggle)

        self._enhance_panel = self._build_enhance_panel()
        self._enhance_panel.setVisible(False)

        # ---- action row ----
        self._recrop_btn = QPushButton("  Re-crop")
        theme.set_kind(self._recrop_btn, "ghost")
        self._recrop_btn.setIcon(icons.icon("crop", theme.INK_SOFT, px=44))
        self._recrop_btn.setIconSize(icons.size(15))
        self._recrop_btn.clicked.connect(self._on_recrop)

        self._enhance_btn = QPushButton("  Adjust")
        self._enhance_btn.setCheckable(True)
        theme.set_kind(self._enhance_btn, "ghost")
        self._enhance_btn.setIcon(icons.icon("sliders", theme.INK_SOFT, px=44))
        self._enhance_btn.setIconSize(icons.size(15))
        self._enhance_btn.toggled.connect(self._on_enhance_toggled)

        self._ocr_lang_combo = QComboBox()
        self._ocr_lang_combo.addItems(ocr.LANGUAGES.keys())
        self._ocr_lang_combo.setCurrentText("English + Bengali")
        self._ocr_lang_combo.setToolTip("OCR language")

        self._ocr_btn = QPushButton("  Extract text")
        theme.set_kind(self._ocr_btn, "ghost")
        self._ocr_btn.setIcon(icons.icon("text", theme.INK_SOFT, px=44))
        self._ocr_btn.setIconSize(icons.size(15))
        self._ocr_btn.clicked.connect(self._on_extract_text)
        self._ocr_btn.setEnabled(False)

        self._save_btn = QPushButton("Save copy")
        self._save_btn.clicked.connect(self._on_save)
        self._save_btn.setEnabled(False)

        self._add_page_btn = QPushButton("  Add to document")
        theme.set_kind(self._add_page_btn, "primary")
        self._add_page_btn.setIcon(icons.icon("plus", "#FFFFFF", px=44))
        self._add_page_btn.setIconSize(icons.size(15))
        self._add_page_btn.clicked.connect(self._on_add_to_document)
        self._add_page_btn.setEnabled(False)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(self._recrop_btn)
        action_row.addWidget(self._enhance_btn)
        action_row.addSpacing(6)
        action_row.addWidget(self._ocr_lang_combo)
        action_row.addWidget(self._ocr_btn)
        action_row.addStretch()
        action_row.addWidget(self._save_btn)
        action_row.addWidget(self._add_page_btn)

        controls = QFrame()
        controls.setObjectName("card")
        cl = QVBoxLayout(controls)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(12)
        cl.addLayout(style_row)
        cl.addWidget(self._enhance_panel)
        cl.addWidget(_hairline())
        cl.addLayout(action_row)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(_card(self._preview, margin=8), stretch=1)
        layout.addWidget(controls)

        page = QWidget()
        page.setLayout(layout)

        # QScrollArea guards the over-constrained case: preview has a hard
        # minimum and the Adjust panel adds height when open — on a short
        # window a scrollbar reaches what doesn't fit rather than the
        # preview overflowing its card.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _build_enhance_panel(self) -> QWidget:
        """Brightness / Contrast / Saturation touch-up sliders, layered on
        top of whichever preset is selected (core.filters.apply_enhancement)
        — hidden until "Adjust" is toggled. Saturation only applies in
        Colour (see _update_saturation_visibility)."""
        panel = QFrame()
        panel.setObjectName("innerPanel")

        header = QHBoxLayout()
        header.addWidget(_section_label("Fine adjust"))
        header.addStretch()
        reset_btn = _icon_button("reset", "Reset adjustments")
        reset_btn.clicked.connect(self._on_reset_enhance)
        header.addWidget(reset_btn)

        self._brightness_slider, brightness_row = self._make_enhance_slider("Brightness")
        self._contrast_slider, contrast_row = self._make_enhance_slider("Contrast")
        self._saturation_slider, self._saturation_row = self._make_enhance_slider("Saturation")

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(9)
        outer.addLayout(header)
        outer.addWidget(brightness_row)
        outer.addWidget(contrast_row)
        outer.addWidget(self._saturation_row)
        return panel

    def _make_enhance_slider(self, label_text: str):
        label = QLabel(label_text)
        label.setObjectName("hint")
        label.setFixedWidth(74)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(-100, 100)
        slider.setValue(0)

        value_label = QLabel("0")
        value_label.setObjectName("valueChip")
        value_label.setFixedWidth(38)
        value_label.setAlignment(Qt.AlignCenter)
        slider.valueChanged.connect(lambda v, lbl=value_label: lbl.setText(f"{v:+d}" if v else "0"))
        slider.valueChanged.connect(lambda _v: self._enhance_timer.start())

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)
        row_layout.addWidget(label)
        row_layout.addWidget(slider, stretch=1)
        row_layout.addWidget(value_label)
        return slider, row

    # ---- Worker lifetime -----------------------------------------------

    def _track_worker(self, worker):
        """Keep a QThread's Python reference alive until it finishes.

        Every dispatch site also assigns the new worker to an attribute
        like self._detect_worker — but if the user retriggers the same
        action quickly (double-clicking rotate, clicking a filter tab
        again before the previous one lands), that attribute gets
        reassigned to the new worker while the old one may still be
        running. With no reference left, Python garbage-collects the old
        QThread object out from under its still-running OS thread, which
        crashes PySide6 outright. Keeping every in-flight worker in a
        list until its `finished` signal fires avoids that.
        """
        self._active_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._active_workers.remove(w) if w in self._active_workers else None)

    # ---- Page transitions -----------------------------------------------

    def _animate_to_page(self, index: int):
        self._title_label.setText("Adjust the edges" if index == 0 else "Review & export")
        if self._stack.currentIndex() == index:
            return
        self._stack.setCurrentIndex(index)
        widget = self._stack.currentWidget()

        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(240)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda w=widget: w.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._page_anim = anim

    # ---- Open + detect -----------------------------------------------

    def _on_open(self):
        selected, _ = QFileDialog.getOpenFileNames(self, "Open Image(s) or PDF", "", OPEN_FILTER)
        if not selected:
            return

        paths = self._expand_pdfs(selected)
        if not paths:
            return  # every selected PDF failed to open; already warned

        self._batch_skip_crop = False
        if len(paths) > 1:
            dialog = BatchSettingsDialog(len(paths), self)
            if dialog.exec() != QDialog.Accepted:
                return
            self._batch_skip_crop = not dialog.border_adjustment()
            self._filter_tabs.setCurrent(dialog.mode())
            self._bw_toggle.setCurrent(dialog.bw())
            self._update_saturation_visibility()

        self._pending_images = list(paths[1:])
        self._batch_total = len(paths)
        self._batch_index = 1
        self._update_batch_label()
        self.load_image(paths[0])

    def _expand_pdfs(self, selected: list) -> list:
        """Replace any selected .pdf with its rendered pages (each saved to
        a temp PNG) so the rest of the import flow — which works in terms
        of image file paths — doesn't need to know PDFs exist at all.
        Pages are queued in the same order as the files were selected."""
        paths = []
        for path in selected:
            if not path.lower().endswith(".pdf"):
                paths.append(path)
                continue
            try:
                pages = pdf_import.render_pdf_pages(path)
            except Exception as exc:
                QMessageBox.warning(self, "Error", f"Could not read PDF:\n{path}\n\n{exc}")
                continue
            for page in pages:
                fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="dsc_pdf_")
                os.close(fd)
                cv2.imwrite(tmp_path, page)
                paths.append(tmp_path)
                self._pdf_derived_paths.add(tmp_path)
        return paths

    def _update_batch_label(self):
        if self._batch_total > 1:
            self._batch_progress_label.setText(f"Image {self._batch_index} of {self._batch_total}")
        else:
            self._batch_progress_label.setText("")

    def load_image(self, path: str):
        image = cv2.imread(path)
        # Checked (and the entry consumed) now, not later in
        # _on_detect_finished — by then this set may already hold a
        # DIFFERENT page's temp path (batch import loads the next queued
        # image well before detection on this one finishes), so "was THIS
        # load a PDF page" has to be captured as this load's own state.
        self._current_load_is_pdf_page = path in self._pdf_derived_paths
        if self._current_load_is_pdf_page:
            self._pdf_derived_paths.discard(path)
            try:
                os.remove(path)  # read into memory above; the temp file has no further use
            except OSError:
                pass

        if image is None:
            QMessageBox.warning(self, "Error", f"Could not read image:\n{path}")
            self._load_next_pending()
            return

        self._original_image = image
        self._viewing_page_index = None  # loading a new image, not viewing/re-filtering an old page
        self._start_detect()

    def _load_next_pending(self):
        """Batch import: after finishing one image, move straight to the
        next queued one instead of making the user click "Add Page" again
        for every photo."""
        if not self._pending_images:
            return
        self._batch_index += 1
        self._update_batch_label()
        self.load_image(self._pending_images.pop(0))

    def _start_detect(self):
        self._detect_request_id += 1
        request_id = self._detect_request_id
        is_pdf_page = self._current_load_is_pdf_page
        self.statusBar().showMessage("Detecting document edges...")

        worker = DetectWorker(self._original_image)
        worker.resultReady.connect(
            lambda corners, fb, rid=request_id, pdf=is_pdf_page: self._on_detect_finished(corners, fb, rid, pdf)
        )
        worker.errorOccurred.connect(self._on_worker_failed)
        self._detect_worker = worker
        self._track_worker(worker)
        worker.start()

    def _on_detect_finished(self, corners, fallback_used, request_id: int, is_pdf_page: bool = False):
        if request_id != self._detect_request_id:
            return  # a newer rotate/load superseded this request — discard
        self._initial_corners = corners
        self._detection_fallback_used = False if is_pdf_page else fallback_used
        self._crop_editor.set_image(self._original_image, corners)

        # Batch mode with "Border adjustment" off: skip straight to warp
        # using the detected/fallback corners as-is, no per-image crop UI.
        if self._batch_skip_crop and self._batch_total > 1:
            self.statusBar().showMessage(
                f"Auto-processing image {self._batch_index} of {self._batch_total}...", 3000
            )
            self._on_confirm_crop()
            return

        self._animate_to_page(0)
        suffix = f"  (image {self._batch_index} of {self._batch_total})" if self._batch_total > 1 else ""
        if fallback_used:
            self.statusBar().showMessage(
                f"Could not auto-detect document edges — drag the corners manually.{suffix}", 6000
            )
        else:
            self.statusBar().showMessage(f"Document edges detected — adjust if needed.{suffix}", 4000)

    def _on_reset_corners(self):
        if self._original_image is not None and self._initial_corners is not None:
            self._crop_editor.set_image(self._original_image, self._initial_corners)

    def _on_rotate_source(self, rotate_code):
        if self._original_image is None:
            return
        self._original_image = cv2.rotate(self._original_image, rotate_code)
        self._start_detect()

    # ---- Confirm crop -> warp -----------------------------------------

    def _on_confirm_crop(self):
        corners = self._crop_editor.corners()
        if self._original_image is None or corners is None:
            return

        self._save_btn.setEnabled(False)
        self.statusBar().showMessage("Warping...")

        worker = WarpWorker(self._original_image, corners)
        worker.resultReady.connect(self._on_warp_finished)
        worker.errorOccurred.connect(self._on_worker_failed)
        self._warp_worker = worker
        self._track_worker(worker)
        worker.start()

    def _on_warp_finished(self, warped):
        self._warped_image = warped
        self._viewing_page_index = None  # a fresh crop, not re-filtering an existing page
        self._filter_tabs.setEnabled(True)
        self._bw_toggle.setEnabled(True)
        self._recrop_btn.setEnabled(True)
        self._on_reset_enhance()  # a new source image starts with neutral Enhance
        self._animate_to_page(1)
        self.statusBar().showMessage("Cropped.", 3000)
        self._apply_filter()

    def _on_recrop(self):
        self._animate_to_page(0)

    def _on_worker_failed(self, message):
        self.statusBar().clearMessage()
        QMessageBox.critical(self, "Scan failed", message)

    # ---- Filter + preview -----------------------------------------------

    def _on_filter_changed(self, _mode):
        if self._warped_image is not None:
            self._apply_filter()

    def _on_bw_changed(self, _checked=False):
        # Style tabs stay live in both Colour and B&W — every mode has its
        # own matching B&W rendering (see core/filters.py), it isn't one
        # generic monochrome output that makes the tabs moot.
        self._update_saturation_visibility()
        if self._warped_image is not None:
            self._apply_filter()

    def _update_saturation_visibility(self):
        # A grayscale page has no color channel for Saturation to touch.
        self._saturation_row.setVisible(not self._bw_toggle.isChecked())

    def _apply_filter(self):
        if self._warped_image is None:
            return
        mode = self._filter_tabs.current()
        bw = self._bw_toggle.isChecked()

        # Tabs/toggle stay clickable throughout — a slower mode (e.g. "Clear"
        # at ~1.5s on a big photo) must never eat a click made while it's
        # still running. Each request gets a ticket; only the reply matching
        # the CURRENT ticket is allowed to update the preview, so a fast
        # click that lands after a slow one can't be clobbered when the
        # slow one's result arrives late.
        self._filter_request_id += 1
        request_id = self._filter_request_id
        self.statusBar().showMessage("Applying filter...")

        worker = FilterWorker(self._warped_image, mode, bw, allow_background_crush=self._detection_fallback_used)
        worker.resultReady.connect(lambda processed, rid=request_id: self._on_filter_applied(processed, rid))
        worker.errorOccurred.connect(self._on_worker_failed)
        self._filter_worker = worker
        self._track_worker(worker)
        worker.start()

    def _on_filter_applied(self, processed, request_id: int):
        if request_id != self._filter_request_id:
            return  # a newer click superseded this request — discard
        self._base_processed_image = processed
        # Re-picking a filter/B&W keeps whatever Enhance adjustment is
        # currently dialed in (it reads as "compare presets with my
        # touch-up applied", not a reason to discard the touch-up).
        self._processed_image = filters.apply_enhancement(
            processed,
            self._brightness_slider.value(),
            self._contrast_slider.value(),
            self._saturation_slider.value(),
        )
        self._show_preview(self._processed_image)
        self._save_btn.setEnabled(True)
        self._ocr_btn.setEnabled(True)
        self.statusBar().clearMessage()

        if self._viewing_page_index is not None:
            # Re-filtering an already-added page — update it in place
            # rather than adding a duplicate.
            self._page_list.update_page(self._viewing_page_index, self._processed_image)
            return

        self._add_page_btn.setEnabled(True)
        # Mid-batch, filter/color were already decided once in the dialog
        # — there's nothing left for the user to pick per image, so add it
        # and move on automatically instead of waiting for another click.
        if self._batch_total > 1:
            self._on_add_to_document()

    def _on_enhance_toggled(self, checked: bool):
        self._enhance_panel.setVisible(checked)

    def _apply_enhancement(self):
        """Recompute the displayed/exported image from the last filter
        result plus the current slider values. Runs synchronously on the UI
        thread (unlike _apply_filter's QThread dispatch) — brightness/
        contrast/saturation are plain per-pixel arithmetic, cheap even on a
        full-res photo, and a slider drag fires this continuously, so the
        request-id machinery apply_filter needs would just be overhead
        here. self._enhance_timer debounces bursts of valueChanged signals
        from a fast drag down to one recompute per ~30ms.
        """
        if self._base_processed_image is None:
            return
        self._processed_image = filters.apply_enhancement(
            self._base_processed_image,
            self._brightness_slider.value(),
            self._contrast_slider.value(),
            self._saturation_slider.value(),
        )
        self._show_preview(self._processed_image)
        if self._viewing_page_index is not None:
            self._page_list.update_page(self._viewing_page_index, self._processed_image)

    def _on_reset_enhance(self):
        self._brightness_slider.setValue(0)
        self._contrast_slider.setValue(0)
        self._saturation_slider.setValue(0)

    def _show_preview(self, image):
        # Downscale with OpenCV (INTER_AREA does proper area averaging) before
        # building the QPixmap, rather than handing Qt's own scaled() the
        # full-resolution pixmap: a full-res photo shrunk by Qt's
        # SmoothTransformation to a small preview pane is a large reduction
        # ratio in one step, and Qt's scaler isn't a true area/decimation
        # filter — small high-contrast graphics (a seal, an embedded photo)
        # came out of it with a visible colored ringing halo around them
        # that isn't present at full resolution. Shrinking the source pixels
        # first avoids that; any further Qt-side scaling is then a much
        # smaller adjustment, not the real reduction.
        target = self._preview.size()
        h, w = image.shape[:2]
        scale = min(target.width() / w, target.height() / h, 1.0)
        if scale < 1.0:
            image = cv2.resize(
                image, (max(1, round(w * scale)), max(1, round(h * scale))),
                interpolation=cv2.INTER_AREA,
            )
        pixmap = to_pixmap(image)
        pixmap = pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._preview.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._processed_image is not None and self._stack.currentIndex() == 1:
            self._show_preview(self._processed_image)

    # ---- Save --------------------------------------------------------

    def _on_save(self):
        if self._processed_image is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Scanned Image", "scan.jpg", SAVE_FILTER)
        if not path:
            return
        if not cv2.imwrite(path, self._processed_image):
            QMessageBox.warning(self, "Error", f"Could not save image:\n{path}")
        else:
            self.statusBar().showMessage(f"Saved: {path}", 5000)

    # ---- OCR -----------------------------------------------------------

    def _on_extract_text(self):
        if self._processed_image is None:
            return
        if not ocr.is_available():
            QMessageBox.warning(
                self,
                "Tesseract not found",
                "The Tesseract-OCR engine isn't installed or couldn't be found.\n"
                "Install it (e.g. via winget: UB-Mannheim.TesseractOCR) and try again.",
            )
            return

        lang = ocr.LANGUAGES[self._ocr_lang_combo.currentText()]
        self._ocr_btn.setEnabled(False)
        self.statusBar().showMessage("Running OCR...")

        worker = OcrWorker(self._processed_image, lang)
        worker.resultReady.connect(self._on_ocr_finished)
        worker.errorOccurred.connect(self._on_ocr_failed)
        self._ocr_worker = worker
        self._track_worker(worker)
        worker.start()

    def _on_ocr_finished(self, text: str):
        self._ocr_btn.setEnabled(True)
        self.statusBar().showMessage("OCR complete.", 3000)
        dialog = OcrResultDialog(text, self)
        dialog.exec()

    def _on_ocr_failed(self, message: str):
        self._ocr_btn.setEnabled(True)
        self.statusBar().clearMessage()
        QMessageBox.critical(self, "OCR failed", message)

    # ---- Multi-page document -------------------------------------------

    def _on_add_to_document(self):
        if self._processed_image is None:
            return
        self._page_list.add_page(self._processed_image, self._warped_image, self._detection_fallback_used)
        was_batch = self._batch_total > 1

        if self._pending_images:
            remaining = len(self._pending_images)
            self.statusBar().showMessage(
                f"Added as page {self._page_list.count()}. Loading next image ({remaining} left)...", 3000
            )
            self._load_next_pending()
        else:
            if was_batch:
                QMessageBox.information(
                    self, "Batch complete",
                    f"Added {self._batch_total} image(s) as {self._page_list.count()} page(s)."
                )
            self.statusBar().showMessage(f"Added as page {self._page_list.count()}.", 3000)
            self._batch_total = 1
            self._batch_index = 1
            self._batch_skip_crop = False
            self._update_batch_label()

    def _on_pages_changed(self):
        count = self._page_list.count()
        self._export_btn.setEnabled(count > 0)
        self._export_btn.setText(f"Export PDF ({count})" if count else "Export PDF")
        self._print_btn.setEnabled(count > 0)

    def _on_page_selected(self, index: int):
        """Clicking a thumbnail in the sidebar shows that page in the main
        preview — it was previously just a rotate/delete target selector,
        with no visible effect on the (unrelated) currently-shown preview.

        Filter tabs/B&W stay live: picking a different one re-filters this
        page from its stored pre-filter source and updates it in place
        (see _viewing_page_index / _on_filter_applied) — it does NOT stack
        a new filter on top of the already-filtered thumbnail.
        """
        pages = self._page_list.pages()
        if not (0 <= index < len(pages)):
            return

        self._viewing_page_index = index
        self._base_processed_image = pages[index]
        self._processed_image = pages[index]
        self._warped_image = self._page_list.warped_page(index)
        self._detection_fallback_used = self._page_list.fallback_used_for_page(index)
        self._on_reset_enhance()  # viewing a different page starts a fresh Enhance session
        self._show_preview(self._processed_image)
        self._animate_to_page(1)

        # Already in the document — re-adding would duplicate it. Re-crop
        # would need the original (pre-warp) photo, which we don't keep
        # per page, so that one stays unsupported for existing pages.
        self._add_page_btn.setEnabled(False)
        self._recrop_btn.setEnabled(False)
        self._filter_tabs.setEnabled(True)
        self._bw_toggle.setEnabled(True)
        self.statusBar().showMessage(f"Viewing page {index + 1} — pick a filter to update it.", 4000)

    def _on_export_pdf(self):
        pages = self._page_list.pages()
        if not pages:
            return
        default_path = os.path.join(DESKTOP_DIR, "document.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", default_path, PDF_FILTER)
        if not path:
            return
        try:
            images_to_pdf(pages, path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"Exported {len(pages)} page(s): {path}", 5000)

    def _on_print(self):
        pages = self._page_list.pages()
        if not pages:
            return

        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.Accepted:
            return

        painter = QPainter(printer)
        try:
            for i, page in enumerate(pages):
                if i > 0:
                    printer.newPage()
                target = printer.pageRect(QPrinter.DevicePixel)
                pixmap = to_pixmap(page).scaled(
                    target.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                x = target.x() + (target.width() - pixmap.width()) / 2
                y = target.y() + (target.height() - pixmap.height()) / 2
                painter.drawPixmap(int(x), int(y), pixmap)
        finally:
            painter.end()
        self.statusBar().showMessage(f"Sent {len(pages)} page(s) to the printer.", 5000)

    # ---- About -------------------------------------------------------

    def _on_about(self):
        QMessageBox.about(
            self,
            "Desktop Scanner",
            f"<b>Desktop Scanner</b> {__version__}<br><br>"
            "Turn photos and PDFs of documents into clean, straightened, "
            "multi-page scans — entirely on your computer.<br><br>"
            '<a href="https://manasij123.github.io/desktop-scanner/">manasij123.github.io/desktop-scanner</a>',
        )

    # ---- Auto-update -------------------------------------------------

    def _start_update_check(self):
        worker = UpdateCheckWorker()
        worker.updateAvailable.connect(self._on_update_available)
        self._update_check_worker = worker
        self._track_worker(worker)
        worker.start()

    def _on_update_available(self, version: str, url: str, _notes: str):
        # Pull the new installer down quietly — the user isn't told anything
        # until it's on disk and ready to apply in one step.
        self._pending_update_version = version
        self.statusBar().showMessage(f"Downloading update {version}...", 4000)
        worker = UpdateDownloadWorker(url)
        worker.downloaded.connect(self._on_update_downloaded)
        worker.failed.connect(lambda msg: self.statusBar().showMessage(f"Update download failed: {msg}", 5000))
        self._update_download_worker = worker
        self._track_worker(worker)
        worker.start()

    def _on_update_downloaded(self, installer_path: str):
        self._pending_update_installer = installer_path
        version = self._pending_update_version or ""
        box = QMessageBox(self)
        box.setWindowTitle("Update ready")
        box.setIcon(QMessageBox.Information)
        box.setText(f"Desktop Scanner {version} has been downloaded.")
        box.setInformativeText(
            "The update installs in a few seconds. You can apply it now (the app "
            "closes and reopens) or the next time you close Desktop Scanner."
        )
        now_btn = box.addButton("Install && Restart", QMessageBox.AcceptRole)
        box.addButton("Install on Exit", QMessageBox.RejectRole)
        box.exec()

        if box.clickedButton() is now_btn:
            self._apply_pending_update(relaunch=True)
        else:
            self._install_update_on_exit = True
            self.statusBar().showMessage(f"Update {version} will install when you close the app.", 6000)

    def _apply_pending_update(self, relaunch: bool):
        from clearscanner.core import updater

        if not self._pending_update_installer:
            return
        try:
            updater.apply_update(self._pending_update_installer, relaunch=relaunch)
        except Exception as exc:
            QMessageBox.warning(self, "Update failed", f"Could not start the installer:\n{exc}")
            return
        self._pending_update_installer = None
        QApplication.quit()

    def closeEvent(self, event):
        if self._install_update_on_exit and self._pending_update_installer:
            self._install_update_on_exit = False
            self._apply_pending_update(relaunch=False)
        super().closeEvent(event)
