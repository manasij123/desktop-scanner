"""QThread workers: keep OpenCV work off the UI thread.

DetectWorker finds the document's 4-corner contour (fast — runs on a
downscaled copy, see core.detector). WarpWorker performs the actual
perspective warp on the full-resolution image once the user has
confirmed/adjusted the corners in the crop editor. FilterWorker runs a
color/B&W preset — on a full-resolution photo some presets take up to
~1.5s, which would otherwise freeze the window on every tab click.
"""
from PySide6.QtCore import QThread, Signal

from clearscanner.core import detector, filters, transform


class DetectWorker(QThread):
    resultReady = Signal(object, bool)  # corners (np.ndarray), fallback_used
    errorOccurred = Signal(str)

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self._image = image

    def run(self):
        try:
            corners = detector.find_document_contour(self._image)
            fallback_used = corners is None
            if fallback_used:
                corners = detector.full_image_corners(self._image)
        except Exception as exc:  # surface pipeline errors to the UI instead of crashing the thread
            self.errorOccurred.emit(str(exc))
            return
        self.resultReady.emit(corners, fallback_used)


class WarpWorker(QThread):
    resultReady = Signal(object)  # warped BGR ndarray
    errorOccurred = Signal(str)

    def __init__(self, image, corners, parent=None):
        super().__init__(parent)
        self._image = image
        self._corners = corners

    def run(self):
        try:
            warped = transform.four_point_transform(self._image, self._corners)
        except Exception as exc:
            self.errorOccurred.emit(str(exc))
            return
        self.resultReady.emit(warped)


class FilterWorker(QThread):
    resultReady = Signal(object)  # processed ndarray (BGR or grayscale)
    errorOccurred = Signal(str)

    def __init__(self, image, mode: str, bw: bool, allow_background_crush: bool = False,
                 recover_ink: bool = False, parent=None):
        super().__init__(parent)
        self._image = image
        self._mode = mode
        self._bw = bw
        self._allow_background_crush = allow_background_crush
        self._recover_ink = recover_ink

    def run(self):
        try:
            processed = filters.apply_filter(
                self._image, self._mode, bw=self._bw,
                allow_background_crush=self._allow_background_crush,
                recover_ink=self._recover_ink,
            )
        except Exception as exc:
            self.errorOccurred.emit(str(exc))
            return
        self.resultReady.emit(processed)


class HdWorker(QThread):
    """Real-ESRGAN detail enhancement of a warped page — several seconds on
    CPU, so it reports progress and runs off the UI thread."""
    progress = Signal(float)     # 0.0 - 1.0
    resultReady = Signal(object)  # enhanced BGR ndarray
    errorOccurred = Signal(str)

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self._image = image

    def run(self):
        try:
            from clearscanner.core import upscale

            out = upscale.enhance(self._image, progress=self.progress.emit)
        except Exception as exc:
            self.errorOccurred.emit(str(exc))
            return
        self.resultReady.emit(out)
