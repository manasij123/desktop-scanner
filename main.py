"""Desktop Scanner app entry point.

The splash goes up first, before the expensive imports (cv2, PySide6
widgets, the core pipeline) — those run on a worker thread while the GIF
animates, so the user sees something within a second instead of staring
at nothing for the many seconds a cold frozen build takes to load.

Files can be dropped straight onto the app: onto the running window, or
onto the app icon / a shortcut (Windows then launches us with their paths
as arguments). A second launch with file paths hands them to the instance
already running (see the QLocalServer single-instance handoff) instead of
opening a second window.
"""
import os
import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect

from clearscanner.ui import theme
from clearscanner.ui.splash_screen import SplashScreen

_IPC_NAME = "DesktopScanner.singleton.v1"


def _close_boot_splash():
    """Dismiss the PyInstaller bootloader splash (frozen builds only)."""
    try:
        import pyi_splash  # provided by the bootloader when a Splash is bundled
        pyi_splash.close()
    except Exception:
        pass


def _paths_from_argv() -> list:
    """Absolute paths of any real files passed on the command line — what
    Windows hands us when images/PDFs are dropped on the exe or a shortcut."""
    return [os.path.abspath(a) for a in sys.argv[1:] if os.path.isfile(a)]


def _hand_off_to_running_instance(paths: list) -> bool:
    """If another copy is already running, send it our file paths and
    return True (this process should then just exit)."""
    sock = QLocalSocket()
    sock.connectToServer(_IPC_NAME)
    if not sock.waitForConnected(250):
        return False
    sock.write(("\n".join(paths)).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1500)
    sock.disconnectFromServer()
    return True


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

    argv_paths = _paths_from_argv()
    if _hand_off_to_running_instance(argv_paths):
        return  # an instance is already up; it has taken our files

    app.setStyle("Fusion")  # QSS (border-radius, custom hover colors) needs this to render on Windows
    app.setStyleSheet(theme.APP_STYLESHEET)
    app.setWindowIcon(QIcon(ICON_PATH))

    splash = SplashScreen(SPLASH_GIF_PATH)
    splash.play()
    _close_boot_splash()  # hand off from the static boot splash to the animated one

    state = {}

    def deliver_files(paths):
        window = state.get("window")
        if window is None or not paths:
            return
        window.raise_()
        window.activateWindow()
        window.open_paths(list(paths))

    # Listen for a second launch handing us dropped files.
    QLocalServer.removeServer(_IPC_NAME)  # clear a socket left behind by a crash
    server = QLocalServer()
    server.listen(_IPC_NAME)

    def on_ipc_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def read_and_deliver():
            data = bytes(conn.readAll()).decode("utf-8", "replace")
            conn.deleteLater()
            deliver_files([p for p in data.splitlines() if p])

        conn.readyRead.connect(read_and_deliver)

    server.newConnection.connect(on_ipc_connection)
    state["server"] = server

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
        if argv_paths:
            # let the reveal paint first, then start on the dropped files
            QTimer.singleShot(0, lambda: deliver_files(argv_paths))

    loader = _Loader()
    loader.ready.connect(build_window)
    loader.failed.connect(on_load_failed)
    loader.start()
    state["loader"] = loader  # keep the QThread alive

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
