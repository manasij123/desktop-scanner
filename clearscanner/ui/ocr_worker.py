"""QThread worker: run OCR off the UI thread (Tesseract can take a few seconds)."""
from PySide6.QtCore import QThread, Signal

from clearscanner.core import ocr


class OcrWorker(QThread):
    resultReady = Signal(str)
    errorOccurred = Signal(str)

    def __init__(self, image, lang: str, parent=None):
        super().__init__(parent)
        self._image = image
        self._lang = lang

    def run(self):
        try:
            text = ocr.extract_text(self._image, lang=self._lang)
        except Exception as exc:
            self.errorOccurred.emit(str(exc))
            return
        self.resultReady.emit(text)
