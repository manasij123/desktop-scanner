"""Shared BGR/grayscale ndarray -> QPixmap conversion. OpenCV is BGR, Qt is
RGB — every place that displays, thumbnails, or prints a scanned image needs
this same conversion, so it lives in one place instead of being copy-pasted."""
import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap


def to_pixmap(image: np.ndarray) -> QPixmap:
    if image.ndim == 2:
        h, w = image.shape
        qimage = QImage(image.data, w, h, w, QImage.Format_Grayscale8)
    else:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        qimage = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)

    # .copy() deep-copies into a Qt-owned buffer so the pixmap survives
    # after the source numpy array goes out of scope.
    return QPixmap.fromImage(qimage.copy())
