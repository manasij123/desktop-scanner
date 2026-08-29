"""Desktop Scanner app entry point.

The splash goes up first, before the expensive imports (cv2, PySide6
widgets, the core pipeline) — those run on a worker thread while the GIF
animates, so the user sees something within a second instead of staring
at nothing for the many seconds a cold frozen build takes to load.
"""
import os
import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect

from clearscanner.ui import theme
from clearscanner.ui.splash_screen import SplashScreen


def _close_boot_splash():
    """Dismiss the PyInstaller bootloader splash (frozen builds only)."""
    try:
        import pyi_splash  # provided by the bootloader when a Splash is bundled
        pyi_splash.close()
    except Exception:
        pass


ASSETS_DIR = os.path.join(os.path.dirname(__file__), "clearscanner", "assets")
ICON_PATH = os.path.join(ASSETS_DIR, "icon.ico")
SPLASH_GIF_PATH = os.path.join(ASSETS_DIR, "splash_animation.gif")


class _Loader(QThread):
    """Runs the heavy imports off the UI thread so the splash stays smooth."""
    ready = Signal()
    failed = Signal(str)

    def run(self):
        try:
            import clearscanner.ui.main_window  # noqa: F401  (populates the import cache)
        except BaseException as exc:  # a hung splash is worse than a visible error
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.ready.emit()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # QSS (border-radius, custom hover colors) needs this to render on Windows
    app.setStyleSheet(theme.APP_STYLESHEET)
    app.setWindowIcon(QIcon(ICON_PATH))

    splash = SplashScreen(SPLASH_GIF_PATH)
    splash.play()
    _close_boot_splash()  # hand off from the static boot splash to the animated one

    state = {}

    def build_window():
        # Import is instant now — the worker thread already loaded the module.
        from clearscanner.ui.main_window import MainWindow

        state["window"] = MainWindow()
        splash.finished.connect(reveal_window)
        splash.finish()

    def on_load_failed(message):
        from PySide6.QtWidgets import QMessageBox

        splash.close()
        QMessageBox.critical(None, "Desktop Scanner failed to start", message)
        app.quit()

    def reveal_window():
        window = state["window"]
        window.show()
        effect = QGraphicsOpacityEffect(window)
        window.setGraphicsEffect(effect)
        fade_in = QPropertyAnimation(effect, b"opacity", window)
        fade_in.setDuration(300)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)
        fade_in.finished.connect(lambda: window.setGraphicsEffect(None))
        fade_in.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        window._splash_fade_in = fade_in  # keep alive until it finishes

    loader = _Loader()
    loader.ready.connect(build_window)
    loader.failed.connect(on_load_failed)
    loader.start()
    state["loader"] = loader  # keep the QThread alive

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
