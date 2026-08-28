"""QThread wrappers so the update check and the installer download never
block the UI thread (see clearscanner.core.updater)."""
from PySide6.QtCore import QThread, Signal

from clearscanner.core import updater


class UpdateCheckWorker(QThread):
    updateAvailable = Signal(str, str, str)  # version, installer_url, notes

    def run(self):
        info = updater.check_for_update()
        if info:
            self.updateAvailable.emit(*info)


class UpdateDownloadWorker(QThread):
    progress = Signal(float)      # 0.0 - 1.0
    downloaded = Signal(str)      # path to the installer .exe
    failed = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        try:
            path = updater.download_installer(self._url, self.progress.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.downloaded.emit(path)
