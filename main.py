"""Desktop Scanner app entry point."""
import os
import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect

from clearscanner.ui import theme
from clearscanner.ui.main_window import MainWindow
from clearscanner.ui.splash_screen import SplashScreen

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "clearscanner", "assets")
ICON_PATH = os.path.join(ASSETS_DIR, "icon.ico")
SPLASH_GIF_PATH = os.path.join(ASSETS_DIR, "splash_animation.gif")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # QSS (border-radius, custom hover colors) needs this to render on Windows
    app.setStyleSheet(theme.APP_STYLESHEET)
    app.setWindowIcon(QIcon(ICON_PATH))

    # Built now (not after the splash finishes) so its background model
    # warm-up thread gets a head start during the splash animation instead
    # of only starting once the user can already see the main window.
    window = MainWindow()

    def show_main_window():
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

    splash = SplashScreen(SPLASH_GIF_PATH)
    splash.finished.connect(show_main_window)
    splash.play()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
