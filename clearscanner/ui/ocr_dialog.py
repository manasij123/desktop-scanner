"""Dialog showing OCR-extracted text, with copy/save actions."""
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from clearscanner.ui import theme


class OcrResultDialog(QDialog):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Extracted Text")
        self.resize(560, 480)

        self._text_edit = QTextEdit()
        self._text_edit.setPlainText(text)

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self._on_copy)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        save_btn = QPushButton("Save as .txt")
        theme.set_kind(save_btn, "primary")
        save_btn.clicked.connect(self._on_save)

        btn_row = QHBoxLayout()
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        btn_row.addWidget(save_btn)

        layout = QVBoxLayout()
        layout.addWidget(self._text_edit, stretch=1)
        layout.addLayout(btn_row)
        self.setLayout(layout)

    def _on_copy(self):
        QApplication.clipboard().setText(self._text_edit.toPlainText())

    def _on_save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Text", "scan.txt", "Text (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._text_edit.toPlainText())
        except OSError as exc:
            QMessageBox.warning(self, "Error", f"Could not save file:\n{exc}")
