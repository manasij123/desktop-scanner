"""Thin wrappers that compose the existing `clearscanner` desktop pipeline
into request-sized steps. No new image logic lives here — this is the same
detector / transform / filters / upscale / ocr the PySide6 app uses, so the
web output matches the desktop one exactly."""
from __future__ import annotations

import hashlib
import io
import os
import threading
from collections import OrderedDict

# Keep the native libs from each spawning a thread per host core and
# thrashing — `os.cpu_count()` reports the HOST's cores, not this
# container's cgroup share, so on a 1-vCPU cloud slice the default would
# oversubscribe ~16:1 and every rembg inference stalls. DSC_THREADS pins it
# (set it to the machine's real vCPU count); otherwise be conservative.
# Set before cv2 / onnxruntime import so it takes effect.
_DISABLE_ML = str(os.environ.get("DSC_DISABLE_ML", "")).lower() in ("1", "true", "yes", "on")
_THREADS = os.environ.get("DSC_THREADS") or str(max(1, min(4, (os.cpu_count() or 2) // 2)))
os.environ.setdefault("OMP_NUM_THREADS", _THREADS)
os.environ.setdefault("OPENBLAS_NUM_THREADS", _THREADS)
os.environ.setdefault("OMP_THREAD_LIMIT", _THREADS)
os.environ.setdefault("ONNXRUNTIME_INTRA_OP_NUM_THREADS", _THREADS)
os.environ.setdefault("ORT_LOGGING_LEVEL", "3")

import cv2
import numpy as np

from clearscanner.core import detector, filters, ocr, transform, upscale

if _DISABLE_ML:
    # DSC_DISABLE_ML: skip the rembg/u2netp segmentation entirely — it pulls
    # in onnxruntime + scikit-image + numba (~150 MB RAM, a slow first
    # import) and needs real CPU. No-op the ML entry points in the frozen
    # clearscanner detector so nothing ever imports rembg; detection falls
    # back to Canny / Otsu, plenty for a document on a plain surface.
    detector._detect_by_ml = lambda *a, **k: None
    detector.get_subject_mask = lambda *a, **k: None

cv2.setNumThreads(int(_THREADS))

MODES = filters.COLOR_MODES  # ("original", "photo", "docs", "clear")

# A document render never needs more than this on the long side; decoding and
# holding a 15 MP array for every slider tick is the single biggest cost.
SOURCE_CAP = 3600


class _LRU:
    """Tiny thread-safe LRU. Values are big ndarrays, so the caps are small."""

    def __init__(self, cap: int):
        self.cap = cap
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def put(self, key, val):
        with self._lock:
            self._d[key] = val
            self._d.move_to_end(key)
            while len(self._d) > self.cap:
                self._d.popitem(last=False)


# decoded frames + warps are big; cap counts low, and lower still on a
# memory-constrained host (Cloud Run 1Gi etc.) via DSC_CACHE_SCALE.
_cscale = max(0.2, float(os.environ.get("DSC_CACHE_SCALE", "1")))
_decoded_cache = _LRU(max(2, round(4 * _cscale)))   # img_key -> BGR
_warp_cache = _LRU(max(3, round(8 * _cscale)))      # (img_key, corners, max_dim, sharpen) -> warped BGR


def detector_warm_up() -> None:
    """Load the ML segmentation model ahead of the first request."""
    if _DISABLE_ML:
        return
    try:
        detector.warm_up()
    except Exception:
        pass


# ------------------------------------------------------------------ decode

def load_bgr(data: bytes, cap: int | None = SOURCE_CAP) -> np.ndarray:
    """Decode uploaded image bytes to a BGR ndarray, applying EXIF rotation
    (phone photos are almost always stored rotated with an orientation tag).

    `cap` bounds the long side — JPEG `draft` mode then does the downscale
    *inside* the decoder (power-of-two DCT scaling), so a 15 MP phone photo
    decodes ~4x faster and never materialises at full size."""
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(data))
    if cap:
        try:
            img.draft("RGB", (cap, cap))   # JPEG-only fast path, silently ignored otherwise
        except Exception:
            pass
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    if cap and max(bgr.shape[:2]) > cap:
        s = cap / max(bgr.shape[:2])
        bgr = cv2.resize(bgr, (round(bgr.shape[1] * s), round(bgr.shape[0] * s)),
                         interpolation=cv2.INTER_AREA)
    return bgr


def load_source(data: bytes) -> tuple[bytes, np.ndarray]:
    """`load_bgr` with an LRU on the upload's content hash — the client
    re-sends the same photo for detect + every slider render, so decoding it
    once per editing session instead of once per request is a big win."""
    key = hashlib.blake2b(data, digest_size=16).digest()
    hit = _decoded_cache.get(key)
    if hit is None:
        hit = load_bgr(data)
        _decoded_cache.put(key, hit)
    return key, hit


def encode_jpeg(bgr: np.ndarray, quality: int = 92) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


# ------------------------------------------------------------------ detect

FULL_FRAME = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def _is_flat_page(bgr: np.ndarray) -> bool:
    """Is this already a flat document — a PDF export, a flatbed scan, a
    phone-scanner crop, handwriting filling a full sheet? Then
    find_document_contour only does harm: it hunts for an inner rectangle
    (a bordered instruction box, a table) and crops the real content away
    (an e-EPIC voter card lost everything but its footnotes this way).
    Tell: the frame's outer border band is almost entirely paper-white."""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    small = cv2.resize(g, (360, max(1, round(360 * h / w))))
    b = max(2, round(min(small.shape) * 0.04))
    edge = np.concatenate([
        small[:b].ravel(), small[-b:].ravel(),
        small[:, :b].ravel(), small[:, -b:].ravel(),
    ])
    return float((edge > 175).mean()) > 0.82 and float(edge.mean()) > 215


def _confidence(bgr: np.ndarray) -> float:
    """0..1 "does this look like a photographed paper document" — the same
    LAB bright-and-neutral fraction the filters use, on a downscaled copy.
    Drives the web app's mode hint (a dark screenshot / a colourful scene
    shouldn't default to the harsh "Clear" enhancement)."""
    s = min(1.0, 480.0 / max(bgr.shape[:2]))
    small = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else bgr
    return round(float(filters._paper_confidence(small)), 3)


def _quad_area(q) -> float:
    q = np.asarray(q, np.float32)
    return float(abs(cv2.contourArea(q)))


def _plausible_quad(q) -> bool:
    """q: normalised [4][2]. Reject slivers / near-degenerate / near-whole-frame."""
    a = _quad_area(q)
    if a < 0.10 or a > 0.97:
        return False
    q = np.asarray(q, np.float32)
    sides = [float(np.linalg.norm(q[i] - q[(i + 1) % 4])) for i in range(4)]
    lo, hi = min(sides), max(sides)
    return lo > 0.12 and hi / max(lo, 1e-6) < 7.0


def _mask_quad(bgr: np.ndarray):
    """Foreground segmentation mask (rembg/u2netp) -> largest blob -> convex
    hull -> MINIMUM-AREA RECTANGLE. More robust than approxPolyDP on the
    wiggly segmentation contour (which is rarely exactly 4 points and
    otherwise degrades to a loose axis-aligned box). Recovers the cases the
    classical path drops — a white ticket on a black table, an ID card on a
    patterned sheet. Returns a normalised [4][2] quad or None."""
    if _DISABLE_ML:
        return None
    mask = detector.get_subject_mask(bgr)
    if mask is None:
        return None
    h, w = bgr.shape[:2]
    s = 560.0 / max(h, w)
    m = cv2.resize(mask, (max(8, round(w * s)), max(8, round(h * s))), interpolation=cv2.INTER_AREA)
    _, binm = cv2.threshold(m, 110, 255, cv2.THRESH_BINARY)
    mn = min(binm.shape)
    ko = max(3, int(mn * 0.02) | 1)
    kc = max(3, int(mn * 0.045) | 1)
    ell = cv2.MORPH_ELLIPSE
    binm = cv2.morphologyEx(binm, cv2.MORPH_OPEN, cv2.getStructuringElement(ell, (ko, ko)))
    binm = cv2.morphologyEx(binm, cv2.MORPH_CLOSE, cv2.getStructuringElement(ell, (kc, kc)))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(binm, 8)
    if n < 2:
        return None
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    comp_area = float(stats[idx, cv2.CC_STAT_AREA])
    frac = comp_area / float(binm.shape[0] * binm.shape[1])
    # too small = a stray blob; too big = the model grabbed most of the
    # scene (a full-sheet capture is _is_flat_page's job, not this)
    if frac < 0.05 or frac > 0.80:
        return None

    ys, xs = np.where(labels == idx)
    hull = cv2.convexHull(np.column_stack([xs, ys]).astype(np.int32))
    rect = cv2.minAreaRect(hull)
    (rw, rh) = rect[1]
    if rw < 4 or rh < 4:
        return None
    # a real document silhouette FILLS its rotated bounding box; sparse ink
    # strokes on a full sheet (a signature, a handwritten note — rembg
    # segments the writing, not the paper) fill only a fraction of it, so
    # min-area-rect there would crop tight around the text and lose the page
    if comp_area / (rw * rh) < 0.60:
        return None

    box = cv2.boxPoints(rect)
    c = box.mean(axis=0)
    box = box + (c - box) * 0.025  # the mask + close over-read a hair
    bh, bw = binm.shape
    return [[float(x) / bw, float(y) / bh] for x, y in box]


def detect(bgr: np.ndarray) -> dict:
    """Return the document quad as a normalised [TL,TR,BR,BL] list, a
    `fallback` flag (detection gave up), a `flat` flag (already a flat
    page), and a `confidence` score for the mode hint."""
    h, w = bgr.shape[:2]
    conf = _confidence(bgr)
    base = {"fallback": False, "flat": False, "confidence": conf, "width": w, "height": h}

    if _is_flat_page(bgr):
        return {**base, "corners": FULL_FRAME, "flat": True}

    # a small copy for the plausibility gate (edge-strength + interior-paper),
    # which is what keeps a suit-jacket / sunlit-archway false positive out
    dw = detector.DETECT_WIDTH
    ds = dw / w if w > dw else 1.0
    small = cv2.resize(bgr, (round(w * ds), round(h * ds))) if ds != 1.0 else bgr.copy()

    def _ret(q_norm):
        ordered = transform.order_points(np.array(q_norm, np.float32))
        return {**base, "corners": [[float(x), float(y)] for x, y in ordered]}

    def _small_pts(q_norm):
        pts = np.array([[x * small.shape[1], y * small.shape[0]] for x, y in q_norm], np.float32)
        return transform.order_points(pts)

    # 1. segmentation mask -> convex hull -> min-area rect. rembg IS the
    #    "edge detector" here, so no Sobel gate — but the interior must read
    #    as a page, and a tiny crop of an all-paper frame means the model
    #    latched onto a photo / logo / the ink itself, not the sheet.
    mq = _mask_quad(bgr)
    if mq is not None and _plausible_quad(mq):
        area = _quad_area(mq)
        tiny_in_paper = area < 0.35 and conf >= 0.92
        mq_ipf = detector._interior_paper_fraction(small, _small_pts(mq))
        if mq_ipf >= 0.5 and not tiny_in_paper:
            # a white document on a pale patterned cloth: rembg swallows some
            # of the cloth into the subject, so its quad runs wide — right up
            # to the frame edge. Only then is it worth a second (costly)
            # classical pass; if that found a clearly tighter quad whose
            # interior is *cleaner* paper, trust it instead.
            xs = [p[0] for p in mq]
            ys = [p[1] for p in mq]
            hugs_edge = min(xs) < 0.025 or max(xs) > 0.975 or min(ys) < 0.025 or max(ys) > 0.975
            if hugs_edge:
                cc = detector.find_document_contour(small)
                if cc is not None:
                    cq = [[float(x) / small.shape[1], float(y) / small.shape[0]] for x, y in cc]
                    if (_plausible_quad(cq) and _quad_area(cq) < area * 0.9
                            and detector._interior_paper_fraction(small, _small_pts(cq)) >= mq_ipf + 0.02):
                        return _ret(cq)
            return _ret(mq)

    # 2. the existing classical detector (edge / brightness / approxPolyDP-ML,
    #    already vetted by its own _is_plausible_boundary inside)
    cc = detector.find_document_contour(small)
    if cc is not None:
        cq = [[float(x) / small.shape[1], float(y) / small.shape[0]] for x, y in cc]
        if _plausible_quad(cq):
            return _ret(cq)

    return {**base, "corners": FULL_FRAME, "fallback": True}


# ------------------------------------------------------------------ render

def _build_warp(bgr: np.ndarray, corners_norm, max_dim: int, sharpen: bool) -> np.ndarray:
    h, w = bgr.shape[:2]
    pts = np.array([[x * w, y * h] for x, y in corners_norm], dtype="float32")

    # size the warp output from the quad, and if it would land well above
    # max_dim, downscale the SOURCE first — an INTER_CUBIC warpPerspective of
    # a 15 MP frame just to INTER_AREA it down right after is the slow path.
    (tl, tr, br, bl) = transform.order_points(pts)
    out_long = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl),
                   np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    if out_long > max_dim * 1.2:
        s = (max_dim * 1.2) / out_long
        bgr = cv2.resize(bgr, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
        pts = pts * s

    warped = transform.four_point_transform(bgr, pts)
    long = max(warped.shape[:2])
    if long > max_dim:
        s = max_dim / long
        warped = cv2.resize(
            warped, (round(warped.shape[1] * s), round(warped.shape[0] * s)),
            interpolation=cv2.INTER_AREA,
        )
    if sharpen:
        warped = upscale.enhance(warped)
    return warped


def render(
    bgr: np.ndarray,
    corners_norm: list[list[float]],
    *,
    mode: str = "clear",
    bw: bool = False,
    recover: bool = False,
    sharpen: bool = False,
    allow_background_crush: bool | None = None,
    brightness: int = 0,
    contrast: int = 0,
    saturation: int = 0,
    max_dim: int = 2600,
    img_key: bytes | None = None,
) -> np.ndarray:
    """Full page render: warp -> (sharpen) -> filter preset -> enhance.

    The warp is the same for every style / slider drag on one crop, so it is
    cached on (image, corners, max_dim, sharpen) — a burst of preview renders
    then only re-runs the filter pass."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")

    do_sharpen = bool(sharpen) and mode != "original"
    ckey = None
    if img_key is not None:
        ckey = (img_key, tuple(round(v, 4) for pt in corners_norm for v in pt), int(max_dim), do_sharpen)
        warped = _warp_cache.get(ckey)
    else:
        warped = None
    if warped is None:
        warped = _build_warp(bgr, corners_norm, max_dim, do_sharpen)
        if ckey is not None:
            _warp_cache.put(ckey, warped)

    # allow_background_crush: default to the detection fallback flag's intent
    # — only crush the background when the crop is the whole frame (a photo,
    # not a tightly-cropped document). If the caller didn't say, assume a
    # real document (no crush), which is the safe choice.
    crush = bool(allow_background_crush) if allow_background_crush is not None else False

    processed = filters.apply_filter(
        warped, mode=mode, bw=bw,
        allow_background_crush=crush, recover_ink=recover,
    )
    if mode in ("docs", "clear"):
        processed = _clean_bands(processed, warped, bw=bw)
    if brightness or contrast or saturation:
        processed = filters.apply_enhancement(processed, brightness, contrast, saturation)
    return processed


# ----------------------------------------------------- letterhead bands

def _hsv_bgr(hue: float, sat: float, val: float) -> np.ndarray:
    px = np.uint8([[[int(hue) % 180, int(sat), int(val)]]])
    return cv2.cvtColor(px, cv2.COLOR_HSV2BGR)[0, 0].astype(np.float32)


def _clean_bands(rendered: np.ndarray, warped: np.ndarray, *, bw: bool) -> np.ndarray:
    """Re-render the two coloured letterhead bars on an ID card (the orange
    "Government of India" / green "Unique Identification Authority" strips on
    an Aadhaar) as clean solid fills with crisp white knocked-out text.

    Docs/Clear otherwise wreck a faded or colour-cast band: the illumination
    divide + snap-to-white read the faint wash as slightly-off-white paper
    and bleach it to a ghost, or (with a cyan/magenta photocopy cast) keep
    the wrong colour, blotchy.

    Detection is deliberately narrow — it fires ONLY on the ID-card
    signature: exactly two thin saturated strips inside the top third,
    a calm white gap between them, and white paper both above the first
    and below the second. A plain document, a page of coloured handwriting,
    a photo, a single-banded letterhead — none of those match, so they are
    returned untouched."""
    gray_out = rendered.ndim == 2
    orig = rendered
    if gray_out:
        rendered = cv2.cvtColor(rendered, cv2.COLOR_GRAY2BGR)
    if warped.ndim == 2:
        warped = cv2.cvtColor(warped, cv2.COLOR_GRAY2BGR)
    H, W = rendered.shape[:2]
    s = 700.0 / max(H, W)
    ws = cv2.resize(warped, (max(8, round(W * s)), max(8, round(H * s))), interpolation=cv2.INTER_AREA)
    hh, ww = ws.shape[:2]
    hsv = cv2.cvtColor(cv2.GaussianBlur(ws, (0, 0), 1.4), cv2.COLOR_BGR2HSV)
    Sc = hsv[..., 1].astype(np.float32)
    Vc = hsv[..., 2].astype(np.float32)
    Hc = hsv[..., 0].astype(np.float32)

    # per-row median saturation / value. Median (not mean) so the knocked-out
    # white text inside a band doesn't drag the row down — a real wash keeps
    # the row's *typical* pixel coloured.
    row_s = cv2.blur(np.median(Sc, axis=1).reshape(-1, 1), (1, 5)).ravel()
    row_v = np.median(Vc, axis=1)

    lo_y = max(2, int(hh * 0.05))          # skip the sheet's own top edge / shadow
    hi_y = int(hh * 0.35)                  # the letterhead lives in the top third
    base = float(np.percentile(row_s[: int(hh * 0.5)], 35))
    thr = max(13.0, base + 9.0, base * 1.9)

    runs, y = [], lo_y
    while y < hi_y:
        if row_s[y] > thr:
            y0 = y
            while y < hi_y and row_s[y] > thr:
                y += 1
            runs.append((y0, y))
        else:
            y += 1
    bands = [(a, b) for (a, b) in runs if 0.012 * hh <= (b - a) <= 0.085 * hh]

    def _band_hue(y0, y1):
        """circular mean / spread of the band's coloured pixels — orange sits
        on the 0/180 hue seam, so a plain std reads it as a rainbow."""
        m = Sc[y0:y1] > 25
        if int(m.sum()) < 20:
            return -1.0, 99.0
        ang = Hc[y0:y1][m] * (np.pi / 90.0)
        C, S = float(np.cos(ang).mean()), float(np.sin(ang).mean())
        R = min(1.0, (C * C + S * S) ** 0.5)
        spread = float(np.sqrt(max(0.0, -2.0 * np.log(max(1e-6, R)))) * (90.0 / np.pi))
        cmean = (np.degrees(np.arctan2(S, C)) % 360.0) / 2.0
        return cmean, spread

    ok = False
    if len(bands) == 2:
        (a0, a1), (b0, b1) = bands
        gap_calm = (b0 - a1) >= 0.015 * hh and float(row_s[a1:b0].mean()) < thr * 0.6
        gap_white = float(row_v[a1:b0].mean()) > 230.0
        top_from = max(1, int(hh * 0.02))
        above_white = a0 <= int(hh * 0.035) or float(row_v[top_from:a0].mean()) > 225.0
        c0 = min(hh, b1 + int(hh * 0.02))
        c1 = min(hh, int(hh * 0.42))
        below_white = (c1 - c0) > 3 and float(row_v[c0:c1].mean()) > 236.0 and float(row_s[c0:c1].mean()) < 10.0
        (hue_a, spread_a), (hue_b, spread_b) = _band_hue(a0, a1), _band_hue(b0, b1)
        uniform = spread_a < 28.0 and spread_b < 28.0
        dh = abs(hue_a - hue_b)
        two_colour = hue_a >= 0 and hue_b >= 0 and min(dh, 180.0 - dh) >= 12.0
        ok = gap_calm and gap_white and above_white and below_white and uniform and two_colour
    if not ok:
        return orig

    grayw = cv2.cvtColor(ws, cv2.COLOR_BGR2GRAY).astype(np.float32)
    outs = cv2.resize(rendered, (ww, hh), interpolation=cv2.INTER_AREA).astype(np.float32)
    mask = np.zeros((hh, ww), np.float32)
    target = outs.copy()
    pad = max(1, int(hh * 0.010))

    # a real Aadhaar band 0 is orange (hue near the 0/180 seam), band 1 green.
    # if the scan reads that way we keep its own hue (a scanner renders the
    # bar as an orange-red gradient, not a flat fill); if it doesn't (a cyan /
    # magenta photocopy cast) we force the canonical colours.
    warm = min(hue_a, 180.0 - hue_a) <= 22.0
    grn = 32.0 <= hue_b <= 92.0
    natural = warm and grn

    for i, (y0, y1) in enumerate(bands):
        y0 = max(lo_y, y0 - pad)
        y1 = min(hi_y, y1 + pad)
        # horizontal extent: where the row actually carries colour, widened to
        # the sheet edges (a faded band still spans the card, we just can't
        # see all of it)
        col = ((Sc[y0:y1] > max(14.0, thr * 0.7)) & (Vc[y0:y1] > 60)).mean(axis=0) > 0.25
        xs = np.where(col)[0]
        if xs.size >= ww * 0.35:
            x0 = max(int(ww * 0.02), int(xs[0]) - int(ww * 0.02))
            x1 = min(int(ww * 0.98), int(xs[-1] + 1) + int(ww * 0.02))
        else:
            x0, x1 = int(ww * 0.06), int(ww * 0.94)

        # local levels stretch confined to the strip: a morphological OPEN is
        # the band body (the bright white text erodes away), CLOSE is the text
        # peaks. t == 0 on the body, 1 on the knocked-out text. The (hi-lo)
        # floor keeps the faded right end of the bar solid instead of
        # amplifying its noise into speckle.
        g = grayw[y0:y1, x0:x1]
        k = max(5, int((y1 - y0) * 0.9) | 1)
        el = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        lo = cv2.GaussianBlur(cv2.morphologyEx(g, cv2.MORPH_OPEN, el), (0, 0), k * 0.5)
        hi = cv2.GaussianBlur(cv2.morphologyEx(g, cv2.MORPH_CLOSE, el), (0, 0), k * 0.5)
        t = np.clip((g - lo) / np.maximum(hi - lo, 48.0), 0.0, 1.0) ** 1.35

        if bw:
            body = np.array([150.0, 150.0, 150.0], np.float32) if i == 0 else np.array([92.0, 92.0, 92.0], np.float32)
        elif natural:
            hue = float(np.clip(hue_a, 4, 16)) if i == 0 else float(np.clip(hue_b, 38, 74))
            body = _hsv_bgr(hue, 165 if i == 0 else 175, 178 if i == 0 else 120)
        else:
            body = _hsv_bgr(9 if i == 0 else 58, 185, 172 if i == 0 else 120)

        blk = body[None, None, :] * (1.0 - t[..., None]) + 249.0 * t[..., None]
        target[y0:y1, x0:x1] = blk
        mask[y0:y1, x0:x1] = 1.0

    mask = cv2.GaussianBlur(mask, (0, 0), 2.0)[..., None]
    blended = outs * (1.0 - mask) + target * mask
    full = cv2.resize(np.clip(blended, 0, 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_LINEAR)
    return cv2.cvtColor(full, cv2.COLOR_BGR2GRAY) if gray_out else full


# ------------------------------------------------------------------ ocr

def ocr_available() -> bool:
    try:
        return ocr.is_available()
    except Exception:
        return False


def extract_text(bgr: np.ndarray, lang: str = "eng") -> str:
    return ocr.extract_text(bgr, lang=lang)
