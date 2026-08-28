"""Calibration-only script (detector.py NOT modified yet). Measures a
candidate new signal -- fraction of a detected quad's INTERIOR that looks
paper-like (bright + low-chroma), same test _paper_confidence already uses
for the whole image -- on the false-positive dance_hallroom quad vs real
document cases, to find a threshold that rejects the former without
rejecting the latter.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearscanner.core import detector  # noqa: E402

CASES = Path(__file__).resolve().parent / "cases"


def interior_paper_fraction(small, corners):
    mask = np.zeros(small.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [corners.astype(np.int32)], 255)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    l, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.sqrt((a - 128) ** 2 + (b - 128) ** 2)
    paper_like = (l > 120) & (chroma < 15)
    region = mask > 0
    if not region.any():
        return 0.0
    return float(paper_like[region].mean())


def check(name, image_path):
    image = cv2.imread(str(image_path))
    if image is None:
        print(f"{name}: FAILED TO LOAD")
        return
    h, w = image.shape[:2]
    scale = detector.DETECT_WIDTH / w if w > detector.DETECT_WIDTH else 1.0
    small = cv2.resize(image, (int(w * scale), int(h * scale))) if scale != 1.0 else image.copy()
    min_area = detector.MIN_AREA_FRACTION * small.shape[0] * small.shape[1]

    for strat_name, strat in [("ml", detector._detect_by_ml), ("edges", detector._detect_by_edges), ("brightness", detector._detect_by_brightness)]:
        corners = strat(small, min_area)
        if corners is None:
            print(f"  {name:22s} [{strat_name:10s}] no candidate")
            continue
        edge_ok = detector._is_plausible_boundary(small, corners)
        frac = interior_paper_fraction(small, corners)
        print(f"  {name:22s} [{strat_name:10s}] edge_plausible={edge_ok!s:5}  interior_paper_fraction={frac:.3f}")


print("=== False-positive case (should end up LOW interior_paper_fraction) ===")
check("dance_hallroom", CASES / "dance_hallroom_photo" / "original.png")

print("\n=== Real / candidate document cases (should stay HIGH where a real quad exists) ===")
check("aadhaar_card", CASES / "aadhaar_card" / "original.jpg")
check("notebook_page", CASES / "notebook_page" / "original.jpg")
check("passport_photo", CASES / "passport_photo" / "original.jpg")

print("\n=== Other non-document cases (context) ===")
check("lockscreen", CASES / "lockscreen_nondocument" / "original.jpg")
check("color_chart", CASES / "color_chart_nondocument" / "original.png")
