"""On-device detail enhancement ("Sharpen") for a slightly soft scan.

Deliberately NOT a learned super-resolution model. Real-ESRGAN and the
like reconstruct *plausible* detail — great for a photo, but on a document
they hallucinate: letters and digits get quietly rewritten ("Enrollment"
-> "Enrollmoni", an Aadhaar number's digits changed), and a QR / barcode
turns to mush. For a document scanner that is unacceptable.

Instead this does an honest job: a Lanczos upscale (when the scan is small
enough to benefit) followed by a two-scale unsharp mask — a wide gentle
pass for local contrast and a tight strong pass for edge acutance. It
makes soft text visibly crisper and never invents a character. Fast
enough (< 1 s) that the worker-thread + progress machinery is kept only
for interface compatibility.
"""
import cv2
import numpy as np

_OUTPUT_CAP = 2600  # px, long side of the returned image


def is_available() -> bool:
    """Always — no model file or extra runtime needed any more."""
    return True


def enhance(bgr: np.ndarray, progress=None) -> np.ndarray:
    """Return a sharper copy of `bgr`. `progress`, if given, is called with
    a 0.0-1.0 fraction as the work proceeds."""
    if progress:
        progress(0.05)

    h, w = bgr.shape[:2]
    long = max(h, w)
    # Only upscale a scan that's actually small; a big one just gets the
    # sharpen. Cap so a huge input doesn't balloon.
    if long < 1400:
        factor = 2.0
    elif long < 2000:
        factor = 1.5
    else:
        factor = 1.0
    if factor * long > _OUTPUT_CAP:
        factor = _OUTPUT_CAP / long

    # a light edge-preserving denoise first, so the sharpen doesn't just
    # amplify sensor noise / JPEG blocking
    img = cv2.bilateralFilter(bgr, d=5, sigmaColor=35, sigmaSpace=35)
    if progress:
        progress(0.3)

    if factor > 1.01:
        img = cv2.resize(img, (round(w * factor), round(h * factor)), interpolation=cv2.INTER_LANCZOS4)
    if progress:
        progress(0.55)

    f = img.astype(np.float32)
    wide = cv2.GaussianBlur(f, (0, 0), 3.0)
    f = f + 0.55 * (f - wide)            # local-contrast / "clarity"
    if progress:
        progress(0.8)
    tight = cv2.GaussianBlur(f, (0, 0), 1.0)
    f = f + 1.15 * (f - tight)           # edge acutance
    if progress:
        progress(0.97)

    out = np.clip(f, 0, 255).astype(np.uint8)
    if progress:
        progress(1.0)
    return out
