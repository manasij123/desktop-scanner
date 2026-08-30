"""Ad-hoc checks for the two filter fixes made for the ID-card / birth-
certificate case ("Another"):

1. _colored_fill_mask + _protect_colored_fills — a strongly-coloured
   letterhead band (Aadhaar's orange / green bars) must survive Docs/Clear
   as a clean solid fill with its knocked-out text still readable, not the
   bleached grey mush with half-eaten lettering it used to become.

2. the smooth-near-white escalator in _snap_paper_to_white — a crumpled
   page's many small crease shadows must flatten to pure white, not leave
   amoeba-shaped grey clouds.

Run: venv/Scripts/python.exe benchmark/check_colored_fills_and_wrinkle.py
"""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearscanner.core import detector, filters, transform  # noqa: E402

CASES = Path(__file__).resolve().parent / "cases"
OUT = Path(__file__).resolve().parent / "results" / "colored_fills"
OUT.mkdir(parents=True, exist_ok=True)


def warp(path):
    img = cv2.imread(str(path))
    corners = detector.find_document_contour(img)
    if corners is None:
        return img, True
    return transform.four_point_transform(img, corners), False


def bg_flatness(gray):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, k)
    bg = cv2.morphologyEx(bg, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (75, 75)))
    paper = bg[bg > 180]
    return paper.std() if paper.size else 0.0


def synth_wrinkle(bgr, seed=7):
    """Alpha-blend many soft random crease shadows over a page."""
    h, w = bgr.shape[:2]
    rng = np.random.default_rng(seed)
    shade = np.zeros((h, w), np.float32)
    for _ in range(14):
        x0, y0 = int(rng.integers(0, w)), int(rng.integers(0, h))
        x1 = int(np.clip(x0 + rng.integers(-w // 2, w // 2), 0, w - 1))
        y1 = int(np.clip(y0 + rng.integers(-h // 2, h // 2), 0, h - 1))
        m = np.zeros((h, w), np.float32)
        cv2.line(m, (x0, y0), (x1, y1), 1.0, thickness=int(rng.integers(20, 70)))
        shade += cv2.GaussianBlur(m, (0, 0), int(rng.integers(25, 55))) * rng.uniform(0.10, 0.28)
    shade = np.clip(shade, 0, 0.55)[..., None]
    return np.clip(bgr.astype(np.float32) * (1 - shade * 0.55) - shade * 18, 0, 255).astype(np.uint8)


print("== colored letterhead bands (aadhaar_card) ==")
w, fb = warp(CASES / "aadhaar_card" / "original.jpg")
for mode in ("docs", "clear"):
    for bw in (False, True):
        out = filters.apply_filter(w, mode, bw=bw, allow_background_crush=fb)
        g = out if out.ndim == 2 else cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        tag = f"{mode}_{'bw' if bw else 'color'}"
        # a clean band fill lands lots of pixels in the mid-grey plateau
        mid = np.mean((g > 95) & (g < 165)) * 100
        print(f"  {tag:12s} mid-grey fill {mid:5.1f}%   bg-flatness std {bg_flatness(g):.1f}")
        cv2.imwrite(str(OUT / f"aadhaar_{tag}.png"), out)

print("\n== crumpled page (synthetic wrinkle over notebook_page) ==")
w, _ = warp(CASES / "notebook_page" / "original.jpg")
w = cv2.resize(w, (0, 0), fx=0.5, fy=0.5)
wr = synth_wrinkle(w)
cv2.imwrite(str(OUT / "wrinkle_input.png"), wr)
for mode in ("docs", "clear"):
    out = filters.apply_filter(wr, mode, bw=False, allow_background_crush=False)
    g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    dingy = np.mean((g >= 200) & (g < 235)) * 100
    white = np.mean(g >= 252) * 100
    print(f"  {mode:5s} dingy-grey {dingy:4.1f}%   pure-white {white:4.1f}%   bg-flatness std {bg_flatness(g):.1f}")
    cv2.imwrite(str(OUT / f"wrinkle_{mode}.png"), out)

print(f"\nimages -> {OUT}")
