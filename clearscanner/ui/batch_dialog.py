"""Modal shown before a multi-image batch import: pick settings shared by
every image in the batch (crop step on/off, filter mode, color/B&W) once,
instead of re-deciding for each photo."""
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from clearscanner.core import filters
from clearscanner.ui.segmented_control import LABELS


class BatchSettingsDialog(QDialog):
    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Processing")
        self.setModal(True)
        self.setMinimumWidth(340)

        title = QLabel(f"Processing {count} images")
        title.setObjectName("pageTitle")

        self._border_check = QCheckBox("Border adjustment (crop each image manually)")
        self._border_check.setChecked(True)

        self._filter_combo = QComboBox()
        for mode in filters.COLOR_MODES:
            self._filter_combo.addItem(LABELS.get(mode, mode.title()), mode)
        self._filter_combo.setCurrentIndex(self._filter_combo.findData("clear"))

        self._color_combo = QComboBox()
        self._color_combo.addItems(["Color", "B/W"])

        form = QFormLayout()
        form.addRow(self._border_check)
        form.addRow("Filter:", self._filter_combo)
        form.addRow("Color:", self._color_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addSpacing(6)
        layout.addLayout(form)
        layout.addSpacing(6)
        layout.addWidget(buttons)

    def border_adjustment(self) -> bool:
        return self._border_check.isChecked()

    def mode(self) -> str:
        return self._filter_combo.currentData()

    def bw(self) -> bool:
        return self._color_combo.currentText() == "B/W"
