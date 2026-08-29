"""Startup splash: loops the branded scan-intro GIF while the rest of the
app (heavy imports, the main window) loads on a worker thread, then fades
into the main window.

The caller drives dismissal with finish() rather than a fixed timer —
loading a frozen build can take much longer than one GIF loop, and the
splash needs to stay up for all of it. MIN_DURATION just stops it
flickering past when loading happens to be fast (warm disk cache)."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QWidget

from clearscanner.ui import theme

SPLASH_WIDTH = 640
SPLASH_HEIGHT = 360
MIN_DURATION = 1600
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
        self._elapsed = QTimer(self)
        self._min_elapsed = False
        self._finish_requested = False

    def play(self):
        """Center on the primary screen and start looping the intro
        animation. Call finish() once the app is ready to take over."""
        screen = QApplication.primaryScreen()
        geo = screen.geometry() if screen else None
        if geo is not None:
            self.move(geo.center().x() - SPLASH_WIDTH // 2, geo.center().y() - SPLASH_HEIGHT // 2)
        self.show()
        self._movie.start()
        QTimer.singleShot(MIN_DURATION, self._on_min_elapsed)

    def _on_min_elapsed(self):
        self._min_elapsed = True
        if self._finish_requested:
            self._fade_out()

    def finish(self):
        """Ask the splash to fade and hand off. If MIN_DURATION hasn't
        passed yet the fade is deferred until it has."""
        if self._finish_requested:
            return
        self._finish_requested = True
        if self._min_elapsed:
            self._fade_out()

    def _fade_out(self):
        if self._fade_anim is not None:
            return
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
