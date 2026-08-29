"""Render an existing PDF's pages to images so they can go through the same
enhancement pipeline as a photographed page — the common request this
serves: a scanned PDF whose pages have a dingy grey (not true white)
background, which reads fine on screen but burns through toner fast when
printed, since a printer treats "light grey" as ink to lay down over the
whole page rather than skip. Docs/Clear already do exactly the paper-white
/ text-dark cleanup this needs; the only missing piece was getting a PDF's
pages into the app as images at all.
"""
import cv2
import numpy as np

RENDER_DPI = 300  # matches a typical camera-photo page at print resolution


def render_pdf_pages(path: str, dpi: int = RENDER_DPI) -> list[np.ndarray]:
    """Return each page of the PDF at `path` as a BGR ndarray, in order."""
    import pymupdf as fitz  # lazy: pymupdf is ~1s to import and only PDF imports need it

    pages = []
    zoom = dpi / 72.0  # PDF units are 1/72 inch; fitz's default render is 72 DPI
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(path) as doc:
        for page in doc:
            pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB)
            arr = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
            pages.append(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
    return pages
