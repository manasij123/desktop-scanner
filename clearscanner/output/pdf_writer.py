"""Combine processed page images into a single multi-page PDF.

Every page is a fixed standard size (A4) with the image centered and
scaled to the largest size that fits without cropping or stretching —
matching what real scanner apps produce, and what most viewers/printers
expect a "page" to be, rather than a PDF where each page is a different
custom size matching its source photo's raw pixel dimensions.
"""
import cv2

# img2pdf is imported lazily inside images_to_pdf — it's only needed on
# export, and keeping it off the startup import path speeds app launch.


def images_to_pdf(images, output_path: str):
    """Write `images` (BGR or grayscale ndarrays, in order) as one PDF."""
    if not images:
        raise ValueError("No pages to export.")

    import img2pdf

    page_size = img2pdf.parse_pagesize_rectarg("a4")
    layout_fun = img2pdf.get_layout_fun(pagesize=page_size, fit=img2pdf.FitMode.into)

    encoded = []
    for img in images:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise RuntimeError("Failed to encode a page image.")
        encoded.append(buf.tobytes())

    with open(output_path, "wb") as f:
        f.write(img2pdf.convert(encoded, layout_fun=layout_fun))
