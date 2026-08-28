"""Document edge + contour detection.

Three strategies are tried, in order, on a downscaled copy of the image:
1. ML segmentation (rembg/u2netp) — a small pretrained salient-object
   model. This is what actually rescues the hard case classical CV
   can't: an open notebook where two adjacent pages are both bright
   white against a cluttered desk, so plain edge/brightness heuristics
   grab both pages (or the whole desk) instead of just one. The model
   was trained to isolate "the one foreground thing", which turns out
   to isolate a single page correctly far more often than Canny or
   Otsu-threshold blobs do.
2. Edge/contour based — works when the document has a clean, high-
   contrast boundary against its background (cheap, no model needed).
3. Brightness based — finds the largest bright, paper-colored blob.

If none find a plausible 4-corner document, the caller falls back to
the full image / manual crop.
"""
import threading
import weakref

import cv2
import numpy as np

DETECT_WIDTH = 500
MIN_AREA_FRACTION = 0.2
# Minimum mean Sobel gradient magnitude sampled along a detected quad's own
# perimeter — found via a non-document photo (a phone lock-screen
# screenshot) where the ML segmentation strategy confidently returned a
# large, plausible-looking quad that didn't correspond to any real edge in
# the image at all (it cut straight through a plain suit jacket). A real
# document boundary is a genuine visual edge (paper against a table,
# ink-dark border, etc.) and reliably measured 80-100+ here on real photos;
# the spurious quad measured under 20. Below this, the "detection" is
# almost certainly not a real document edge, so it's discarded rather than
# trusted.
MIN_BOUNDARY_EDGE_STRENGTH = 35.0

# Minimum fraction of a detected quad's INTERIOR that reads as paper-like
# (bright + low-chroma, same test core.filters._paper_confidence uses for
# a whole image) — found via a real outdoor photo (two people dancing in
# colorful sarees under a sunlit archway) where the ML strategy returned a
# large quad along the archway's pillars that passed the edge-strength
# check above (architectural edges are genuine, strong edges too, just not
# a document's) with edge_plausible=True, so the whole page went through
# full-strength Docs/Clear processing meant for a photographed document —
# blowing out the sunlit wall and, worse, any sunlit skin caught inside
# the same quad, toward pure white. A real document's interior is mostly
# paper background (minority ink/photo content); measured on real cases:
# a genuine Aadhaar-card/notebook-page quad's interior reads 0.66-0.96
# paper-like, while the false-positive archway quad reads 0.20-0.45 —
# comfortable margin at 0.5.
MIN_INTERIOR_PAPER_FRACTION = 0.5

_ml_session = None  # lazily created, reused across calls
_ml_session_lock = threading.Lock()


def _interior_paper_fraction(small: np.ndarray, corners: np.ndarray) -> float:
    """Fraction of the quad's interior that's bright and near-neutral in
    color — see MIN_INTERIOR_PAPER_FRACTION above for why this catches
    what the perimeter-edge-strength check alone can't."""
    mask = np.zeros(small.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [corners.astype(np.int32)], 255)
    region = mask > 0
    if not region.any():
        return 0.0
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    l, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.sqrt((a - 128) ** 2 + (b - 128) ** 2)
    paper_like = (l > 120) & (chroma < 15)
    return float(paper_like[region].mean())


def _is_plausible_boundary(small: np.ndarray, corners: np.ndarray) -> bool:
    """Reject a detected quad whose edges don't correspond to any real
    visual boundary in the image (see MIN_BOUNDARY_EDGE_STRENGTH above),
    or whose interior doesn't look like a document page at all even
    though its edges are real (see MIN_INTERIOR_PAPER_FRACTION above)."""
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(gx * gx + gy * gy)

    h, w = gray.shape
    samples = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        for t in np.linspace(0.0, 1.0, 40):
            x, y = a * (1 - t) + b * t
            xi, yi = int(round(x)), int(round(y))
            if 0 <= xi < w and 0 <= yi < h:
                samples.append(grad[yi, xi])
    edge_ok = bool(samples) and float(np.mean(samples)) >= MIN_BOUNDARY_EDGE_STRENGTH
    return edge_ok and _interior_paper_fraction(small, corners) >= MIN_INTERIOR_PAPER_FRACTION


def _largest_quad(contours, min_area: float):
    """Return the largest contour's 4 corners (via approxPolyDP, falling
    back to a min-area rotated rect) if it's big enough, else None."""
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < min_area:
        return None

    perimeter = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * perimeter, True)
    if len(approx) == 4:
        return approx.reshape(4, 2).astype("float32")

    rect = cv2.minAreaRect(largest)
    return cv2.boxPoints(rect).astype("float32")


def _get_ml_session():
    global _ml_session
    if _ml_session is not None:
        return _ml_session
    # The startup warm_up() thread and the first real detection can both
    # race in here at once (app launches, user clicks "Add Page" before
    # warm-up finishes) — without a lock both would call new_session()
    # concurrently, which is unsafe and just wastes a redundant load.
    with _ml_session_lock:
        if _ml_session is None:
            from rembg import new_session
            _ml_session = new_session("u2netp")
    return _ml_session


MASK_WIDTH = 400  # px, longer side — a subject/background mask is a soft
                   # blend weight, not a hard boundary, so it doesn't need
                   # full resolution the way a corner detection does

# Single-entry cache, keyed by a weakref to the ndarray itself — to_clear()
# needs the same mask twice (once via to_docs(), once for its own extra
# crush), and re-picking Docs/Clear/B&W on the same page in the UI
# re-derives from the same stored warped-source array every time, so this
# alone was making the ML inference (the slow part of the whole pipeline)
# run 2-3x more than it needed to for one on-screen image. A weakref key
# (not the array contents — hashing a multi-megapixel photo on every call
# would cost more than the inference it's meant to save) means a
# different array that happened to reuse a freed one's memory address
# can't produce a false cache hit the way a raw id() key could.
_mask_cache_key = None
_mask_cache_value = None


def get_subject_mask(image: np.ndarray) -> np.ndarray | None:
    """Soft-edged foreground/subject mask, same height/width as `image`,
    0=background, 255=subject — via the same rembg/u2netp model used for
    document-boundary detection above, here used for its original purpose
    (salient-object segmentation) rather than corner-finding. Returns None
    if the model isn't available (caller should skip subject-aware
    processing rather than error out).

    Runs on a downscaled copy for speed, same reasoning as detection: a
    mask is a smooth per-pixel blend weight, so upscaling one computed at
    ~400px loses nothing a full-resolution inference would have given
    beyond dpi that gets blurred away below anyway (see the Gaussian blur
    on the upscaled result, which also gives the subject/background
    transition a soft edge instead of a hard cutout).
    """
    global _mask_cache_key, _mask_cache_value
    if _mask_cache_key is not None and _mask_cache_key() is image:
        return _mask_cache_value

    try:
        from rembg import remove
    except Exception:
        return None

    h, w = image.shape[:2]
    scale = MASK_WIDTH / max(h, w) if max(h, w) > MASK_WIDTH else 1.0
    small = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale)))) if scale != 1.0 else image

    try:
        session = _get_ml_session()
        mask_small = np.array(remove(small, session=session, only_mask=True))
    except Exception:
        return None

    mask = cv2.resize(mask_small, (w, h), interpolation=cv2.INTER_LINEAR)
    sigma = max(w, h) * 0.01
    mask = cv2.GaussianBlur(mask, (0, 0), sigma)

    _mask_cache_key = weakref.ref(image)
    _mask_cache_value = mask
    return mask


def warm_up():
    """Load the ML model now instead of on first use. First load takes a
    few seconds (session/runtime init, plus a one-time download if the
    weights aren't cached yet) — call this from a background thread right
    after app startup so it's ready before the user opens their first
    image, instead of stalling that first detection."""
    try:
        _get_ml_session()
    except Exception:
        pass  # detection just falls through to the classical strategies


def _detect_by_ml(small: np.ndarray, min_area: float):
    try:
        from rembg import remove
        session = _get_ml_session()
        mask = np.array(remove(small, session=session, only_mask=True))
    except Exception:
        # Model not downloadable / onnxruntime unavailable / etc. — fall
        # back to the classical strategies below rather than erroring out.
        return None

    _, thresh = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return _largest_quad(contours, min_area)


def _detect_by_edges(small: np.ndarray, min_area: float):
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 75, 200)
    edged = cv2.dilate(edged, None, iterations=1)

    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4 and cv2.contourArea(approx) > min_area:
            return approx.reshape(4, 2).astype("float32")
    return None


def _detect_by_brightness(small: np.ndarray, min_area: float):
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    # Otsu picks a data-driven cutoff between bright paper and a (usually
    # darker) background — no manual threshold tuning needed.
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return _largest_quad(contours, min_area)


def find_document_contour(image: np.ndarray) -> np.ndarray | None:
    """Find the 4-corner contour of a document in `image`.

    Detection runs on a downscaled copy for speed; returned points are
    scaled back to the original image's coordinate space. Returns None
    if no suitable 4-point contour is found (caller should fall back
    to the full image / manual crop).
    """
    h, w = image.shape[:2]
    scale = DETECT_WIDTH / w if w > DETECT_WIDTH else 1.0
    small = cv2.resize(image, (int(w * scale), int(h * scale))) if scale != 1.0 else image.copy()
    min_area = MIN_AREA_FRACTION * small.shape[0] * small.shape[1]

    # Each strategy gets a chance in turn; a candidate that doesn't
    # correspond to any real edge in the image (see _is_plausible_boundary)
    # is discarded just like a None result, so e.g. a spurious ML mask
    # doesn't block the classical strategies from getting a real answer.
    for strategy in (_detect_by_ml, _detect_by_edges, _detect_by_brightness):
        corners = strategy(small, min_area)
        if corners is not None and _is_plausible_boundary(small, corners):
            return corners / scale
    return None


def full_image_corners(image: np.ndarray) -> np.ndarray:
    """Fallback corners covering the entire image."""
    h, w = image.shape[:2]
    return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
