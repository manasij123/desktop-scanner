"""OCR text extraction via the Tesseract engine (through pytesseract).

Tesseract is a separate system install (not a pip package) — see
_WINDOWS_DEFAULT_PATHS below. It's built for printed text; handwriting
recognition will be unreliable.
"""
import os
import shutil

import cv2
import pytesseract

_WINDOWS_DEFAULT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

# Bundled language data (eng + ben) — used instead of the system Tesseract
# install's tessdata so we don't need admin rights to add languages, and so
# a future PyInstaller build carries its own language files.
_TESSDATA_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "tessdata")

LANGUAGES = {"English": "eng", "English + Bengali": "eng+ben"}


def _configure_tesseract_path():
    if shutil.which("tesseract"):
        return
    for path in _WINDOWS_DEFAULT_PATHS:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return


def is_available() -> bool:
    _configure_tesseract_path()
    cmd = pytesseract.pytesseract.tesseract_cmd
    return bool(shutil.which(cmd) or os.path.exists(cmd))


def extract_text(image, lang: str = "eng") -> str:
    """Run OCR on a processed page (BGR or grayscale ndarray) and return text."""
    _configure_tesseract_path()
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    # Set directly (not via a "--tessdata-dir <path>" config string): pytesseract
    # splits the config string with shlex, which mangles Windows backslash paths.
    os.environ["TESSDATA_PREFIX"] = os.path.abspath(_TESSDATA_DIR)
    return pytesseract.image_to_string(image, lang=lang)
