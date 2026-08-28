"""Startup splash: loops the branded scan-intro GIF for a fixed window
(long enough to actually watch the animation, and to give the main
window's background model warm-up a real head start), then fades into
the main window."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QWidget

from clearscanner.ui import theme

SPLASH_WIDTH = 640
SPLASH_HEIGHT = 360
# The GIF's own metadata loops it forever (loopCount() == -1) — there's no
# "play once" switch to ask Qt for (QMovie's loop count is read-only, set
# by the file), so total on-screen time is controlled here instead, not by
# waiting for the animation to end. ~0.5s per loop, so this is good for
# several full loops.
TOTAL_DURATION = 2600
FADE_DURATION = 350


class SplashScreen(QWidget):
    finished = Signal()

    def __init__(self, gif_path: str, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setFixedSize(SPLASH_WIDTH, SPLASH_HEIGHT)
        self.setStyleSheet(f"background-color: {theme.BG};")

        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setGeometry(0, 0, SPLASH_WIDTH, SPLASH_HEIGHT)

        self._movie = QMovie(gif_path)
        self._movie.setScaledSize(QSize(SPLASH_WIDTH, SPLASH_HEIGHT))
        self._label.setMovie(self._movie)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(1.0)

        self._fade_anim = None

    def play(self):
        """Center on the primary screen and start looping the intro
        animation; a fade into the main window follows automatically
        after TOTAL_DURATION."""
        screen = QApplication.primaryScreen()
        geo = screen.geometry() if screen else None
        if geo is not None:
            self.move(geo.center().x() - SPLASH_WIDTH // 2, geo.center().y() - SPLASH_HEIGHT // 2)
        self.show()
        self._movie.start()
        QTimer.singleShot(TOTAL_DURATION, self._fade_out)

    def _fade_out(self):
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(FADE_DURATION)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.InCubic)
        self._fade_anim.finished.connect(self._on_finished)
        self._fade_anim.start()

    def _on_finished(self):
        self._movie.stop()
        self.close()
        self.finished.emit()
