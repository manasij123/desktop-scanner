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

from clearscanner.core import detector, filters, ocr, pdf_import
from clearscanner.output.pdf_writer import images_to_pdf
from clearscanner.ui import theme
from clearscanner.ui.batch_dialog import BatchSettingsDialog
from clearscanner.ui.crop_editor import CropEditor
from clearscanner.ui.ocr_dialog import OcrResultDialog
from clearscanner.ui.ocr_worker import OcrWorker
from clearscanner.ui.page_list import PageList
from clearscanner.ui.qt_image import to_pixmap
from clearscanner.ui.scan_worker import DetectWorker, FilterWorker, WarpWorker
from clearscanner.ui.segmented_control import SegmentedControl

OPEN_FILTER = "Images and PDFs (*.png *.jpg *.jpeg *.bmp *.pdf)"
SAVE_FILTER = "JPEG (*.jpg);;PNG (*.png)"
PDF_FILTER = "PDF (*.pdf)"
DESKTOP_DIR = os.path.join(os.path.expanduser("~"), "Desktop")


def _card(inner: QWidget, margin: int = 10) -> QFrame:
    """Wrap `inner` in a rounded, shadowed card panel (see ui/theme.py)."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.addWidget(inner)
    theme.apply_shadow(frame)
    return frame


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Desktop Scanner")
        self.resize(1000, 720)

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
        threading.Thread(target=detector.warm_up, daemon=True).start()

    # ---- UI construction -------------------------------------------------

    def _build_ui(self):
        brand = QLabel("Desktop Scanner")
        brand.setObjectName("pageTitle")

        open_btn = QPushButton("+ Add Page(s)")
        open_btn.setToolTip("Select one or more images — you'll crop/filter each in turn")
        theme.set_kind(open_btn, "primary")
        open_btn.clicked.connect(self._on_open)

        self._batch_progress_label = QLabel("")
        self._batch_progress_label.setObjectName("hint")

        self._export_btn = QPushButton("Export PDF")
        theme.set_kind(self._export_btn, "primary")
        self._export_btn.clicked.connect(self._on_export_pdf)
        self._export_btn.setEnabled(False)

        self._print_btn = QPushButton("Print")
        self._print_btn.clicked.connect(self._on_print)
        self._print_btn.setEnabled(False)

        top_bar = QHBoxLayout()
        top_bar.addWidget(brand)
        top_bar.addSpacing(24)
        top_bar.addWidget(open_btn)
        top_bar.addSpacing(16)
        top_bar.addWidget(self._batch_progress_label)
        top_bar.addStretch()
        top_bar.addWidget(self._print_btn)
        top_bar.addWidget(self._export_btn)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_crop_page())
        self._stack.addWidget(self._build_preview_page())

        self._page_list = PageList()
        self._page_list.pagesChanged.connect(self._on_pages_changed)
        self._page_list.pageSelected.connect(self._on_page_selected)
        self._page_list.setFixedWidth(200)

        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(self._page_list)
        content.addWidget(self._stack, stretch=1)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)
        layout.addLayout(top_bar)
        layout.addLayout(content, stretch=1)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())

    def _build_crop_page(self) -> QWidget:
        self._crop_editor = CropEditor()

        hint = QLabel("Drag the corners to match the document edges, then confirm.")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)

        reset_btn = QPushButton("Reset to Auto-Detect")
        reset_btn.clicked.connect(self._on_reset_corners)

        rotate_left_btn = QPushButton("↺")
        theme.set_kind(rotate_left_btn, "icon")
        rotate_left_btn.setToolTip("Rotate Left")
        rotate_left_btn.clicked.connect(lambda: self._on_rotate_source(cv2.ROTATE_90_COUNTERCLOCKWISE))

        rotate_right_btn = QPushButton("↻")
        theme.set_kind(rotate_right_btn, "icon")
        rotate_right_btn.setToolTip("Rotate Right")
        rotate_right_btn.clicked.connect(lambda: self._on_rotate_source(cv2.ROTATE_90_CLOCKWISE))

        confirm_btn = QPushButton("✓")
        theme.set_kind(confirm_btn, "icon-primary")
        confirm_btn.setToolTip("Confirm Crop")
        confirm_btn.clicked.connect(self._on_confirm_crop)

        bottom_bar = QHBoxLayout()
        bottom_bar.addWidget(reset_btn)
        bottom_bar.addStretch()
        bottom_bar.addWidget(rotate_left_btn)
        bottom_bar.addWidget(rotate_right_btn)
        bottom_bar.addSpacing(12)
        bottom_bar.addWidget(confirm_btn)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.addWidget(hint)
        layout.addWidget(_card(self._crop_editor), stretch=1)
        layout.addLayout(bottom_bar)

        page = QWidget()
        page.setLayout(layout)
        return page

    def _build_preview_page(self) -> QWidget:
        self._preview = QLabel("No image loaded")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumSize(400, 400)
        self._preview.setObjectName("hint")
        # Ignored (not the QLabel default of Preferred): a QLabel's sizeHint
        # tracks whatever pixmap is currently set, so leaving the default
        # policy in place meant every _show_preview() call (e.g. every ~30ms
        # while dragging an Enhance slider) nudged the layout, which
        # resized the label, which changed the sizeHint again — a feedback
        # loop that showed up as the preview visibly jittering up/down.
        # Ignored tells the layout to size this label purely from the
        # surrounding stretch (still floored by setMinimumSize above),
        # never from its own content.
        self._preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._filter_tabs = SegmentedControl(
            filters.COLOR_MODES, on_change=self._on_filter_changed, default="clear"
        )
        self._filter_tabs.setMaximumWidth(420)

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setFixedHeight(30)
        divider.setStyleSheet(f"color: {theme.BORDER};")

        self._bw_tabs = SegmentedControl(("color", "bw"), on_change=self._on_bw_changed, default="color")
        self._bw_tabs.setMaximumWidth(160)

        self._recrop_btn = QPushButton("Re-crop")
        self._recrop_btn.clicked.connect(self._on_recrop)

        self._enhance_btn = QPushButton("Enhance")
        self._enhance_btn.setCheckable(True)
        theme.set_kind(self._enhance_btn, "tab")
        self._enhance_btn.toggled.connect(self._on_enhance_toggled)

        self._save_btn = QPushButton("Save As...")
        self._save_btn.clicked.connect(self._on_save)
        self._save_btn.setEnabled(False)

        self._add_page_btn = QPushButton("Add to Document")
        theme.set_kind(self._add_page_btn, "primary")
        self._add_page_btn.clicked.connect(self._on_add_to_document)
        self._add_page_btn.setEnabled(False)

        top_bar = QHBoxLayout()
        top_bar.addStretch()
        top_bar.addWidget(self._filter_tabs)
        top_bar.addSpacing(14)
        top_bar.addWidget(divider)
        top_bar.addSpacing(14)
        top_bar.addWidget(self._bw_tabs)
        top_bar.addStretch()

        self._enhance_panel = self._build_enhance_panel()
        self._enhance_panel.setVisible(False)

        bottom_bar = QHBoxLayout()
        bottom_bar.addWidget(self._recrop_btn)
        bottom_bar.addWidget(self._enhance_btn)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self._save_btn)
        bottom_bar.addWidget(self._add_page_btn)

        ocr_label = QLabel("OCR:")
        ocr_label.setObjectName("hint")

        self._ocr_lang_combo = QComboBox()
        self._ocr_lang_combo.addItems(ocr.LANGUAGES.keys())
        self._ocr_lang_combo.setCurrentText("English + Bengali")

        self._ocr_btn = QPushButton("Extract Text")
        self._ocr_btn.clicked.connect(self._on_extract_text)
        self._ocr_btn.setEnabled(False)

        ocr_bar = QHBoxLayout()
        ocr_bar.addWidget(ocr_label)
        ocr_bar.addWidget(self._ocr_lang_combo)
        ocr_bar.addWidget(self._ocr_btn)
        ocr_bar.addStretch()

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.addLayout(top_bar)
        layout.addWidget(_card(self._preview), stretch=1)
        layout.addWidget(self._enhance_panel)
        layout.addLayout(bottom_bar)
        layout.addLayout(ocr_bar)

        page = QWidget()
        page.setLayout(layout)

        # The preview image has a hard minimum size (see self._preview
        # above) and the Enhance panel adds ~150px of its own when open —
        # on a short window those can together demand more height than the
        # window actually has. Without a scroll area, Qt resolves that
        # over-constrained layout by compressing the preview card below its
        # own minimum, which the label refuses to honor: it overflows its
        # card and overlaps whatever comes after it, and because every
        # Enhance slider tick re-triggers this same unstable layout
        # resolution, the overlap visibly shifts — which read as the whole
        # page "jumping". A QScrollArea sidesteps the conflict entirely:
        # everything gets its real minimum size, and a scrollbar (only
        # appearing when needed) reaches whatever doesn't fit.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _build_enhance_panel(self) -> QWidget:
        """Brightness / Contrast / Saturation touch-up sliders, applied on
        top of whichever color-mode preset is selected (see
        core.filters.apply_enhancement) — hidden until "Enhance" is toggled
        on. Saturation only makes sense in Color (see _update_saturation_visibility)."""
        panel = QFrame()
        panel.setObjectName("card")
        theme.apply_shadow(panel)

        header = QHBoxLayout()
        title = QLabel("Enhance")
        title.setObjectName("hint")
        reset_btn = QPushButton("↺")
        theme.set_kind(reset_btn, "icon")
        reset_btn.setToolTip("Reset adjustments")
        reset_btn.clicked.connect(self._on_reset_enhance)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(reset_btn)

        self._brightness_slider, brightness_row = self._make_enhance_slider("Brightness")
        self._contrast_slider, contrast_row = self._make_enhance_slider("Contrast")
        self._saturation_slider, self._saturation_row = self._make_enhance_slider("Saturation")

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)
        outer.addLayout(header)
        outer.addWidget(brightness_row)
        outer.addWidget(contrast_row)
        outer.addWidget(self._saturation_row)
        return panel

    def _make_enhance_slider(self, label_text: str):
        label = QLabel(label_text)
        label.setObjectName("hint")
        label.setFixedWidth(80)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(-100, 100)
        slider.setValue(0)

        value_label = QLabel("0")
        value_label.setObjectName("hint")
        value_label.setFixedWidth(32)
        value_label.setAlignment(Qt.AlignRight)
        slider.valueChanged.connect(lambda v, lbl=value_label: lbl.setText(str(v)))
        slider.valueChanged.connect(lambda _v: self._enhance_timer.start())

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
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
            self._bw_tabs.setCurrent("bw" if dialog.bw() else "color")
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
        self._bw_tabs.setEnabled(True)
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

    def _on_bw_changed(self, _mode):
        # Mode tabs stay clickable in both Color and B/W — every mode has
        # its own matching B&W rendering (see core/filters.py), it isn't
        # one generic monochrome output that makes the tabs moot.
        self._update_saturation_visibility()
        if self._warped_image is not None:
            self._apply_filter()

    def _update_saturation_visibility(self):
        # A grayscale page has no color channel for Saturation to touch.
        self._saturation_row.setVisible(self._bw_tabs.current() != "bw")

    def _apply_filter(self):
        if self._warped_image is None:
            return
        mode = self._filter_tabs.current()
        bw = self._bw_tabs.current() == "bw"

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
        self._bw_tabs.setEnabled(True)
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
