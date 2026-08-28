"""Post-fix verification for dance_hallroom_photo, per the exact checklist
requested: confirm fallback_used flips, subject mask still exists,
_protect_subject actually runs, regenerate the full Clear pipeline, and
compare metrics + close-up face crops against the previous output and the
ClearScanner reference. filters.py was NOT touched by this fix — only
detector._is_plausible_boundary().
"""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearscanner.core import detector, filters  # noqa: E402

CASE = Path(__file__).resolve().parent / "cases" / "dance_hallroom_photo"
OUT = Path(__file__).resolve().parent / "results" / "dance_hallroom_after_detector_fix"
OUT.mkdir(parents=True, exist_ok=True)

original = cv2.imread(str(CASE / "original.png"))
reference = cv2.imread(str(CASE / "reference_clearscan_color_clear.jpeg"))
previous_output = cv2.imread(str(CASE / "reference_desktopscanner_color_clear.jpg"))

# ---- checklist 1-2 ----
corners = detector.find_document_contour(original)
fallback_used = corners is None
print("1. find_document_contour(original) ->", "None" if fallback_used else corners)
print("2. fallback_used =", fallback_used)
assert fallback_used, "STOP: detector fix did not flip fallback_used to True"

# ---- checklist 3 ----
mask = detector.get_subject_mask(original)
print("3. subject mask present:", mask is not None, " mean:", round(float(mask.mean()), 1) if mask is not None else None)
assert mask is not None

# ---- checklist 4: prove _protect_subject actually executes and changes pixels ----
confidence = filters._paper_confidence(original)
smoothed = cv2.bilateralFilter(original, d=5, sigmaColor=40, sigmaSpace=40)
lab = cv2.cvtColor(smoothed, cv2.COLOR_BGR2LAB)
l, a, b = cv2.split(lab)
pre_correction_l = l.copy()
l_illum = filters._correct_illumination(l, paper_confidence=confidence)
l_protected = filters._protect_subject(l_illum, pre_correction_l, mask)
changed_frac = float((l_protected != l_illum).mean())
print(f"4. _protect_subject changes {changed_frac*100:.1f}% of L-channel pixels vs unprotected illum-correction "
      f"(non-zero => it is actually executing and doing work)")
assert changed_frac > 0.01

# ---- checklist 5: regenerate full Clear pipeline via the real apply_filter() path ----
new_output = filters.apply_filter(original, mode="clear", bw=False, allow_background_crush=fallback_used)
cv2.imwrite(str(OUT / "new_clear_color.png"), new_output)
print("5. regenerated via filters.apply_filter(mode='clear', bw=False, allow_background_crush=True)")


def hist_stats(img, ref, label_):
    if img.shape[:2] != ref.shape[:2]:
        img = cv2.resize(img, (ref.shape[1], ref.shape[0]))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sat = hsv[..., 1].astype(np.float32)
    ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32)
    ref_hsv = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV)
    ref_sat = ref_hsv[..., 1].astype(np.float32)
    total = gray.size
    stats = {
        "mean": round(float(gray.mean()), 1),
        "std": round(float(gray.std()), 1),
        "frac_hi_245": round(float((gray >= 245).sum()) / total, 3),
        "frac_lo_10": round(float((gray <= 10).sum()) / total, 3),
        "frac_mid_40_220": round(float(((gray >= 40) & (gray <= 220)).sum()) / total, 3),
        "sat_mean": round(float(sat.mean()), 1),
        "luminance_MAE_vs_ref": round(float(np.abs(gray - ref_gray).mean()), 1),
        "sat_MAE_vs_ref": round(float(np.abs(sat - ref_sat).mean()), 1),
    }
    print(f"  {label_:22s} {stats}")
    return stats


print("\n=== checklist 6/8: metrics, before vs after vs reference ===")
hist_stats(original, reference, "ORIGINAL")
hist_stats(previous_output, reference, "PREVIOUS output (bug)")
hist_stats(new_output, reference, "NEW output (post detector-fix)")
hist_stats(reference, reference, "REFERENCE (ClearScanner)")


# ---- checklist 7: face + wall close-ups, old vs new vs reference ----
def crop2x(img, y0, y1, x0, x1):
    c = img[y0:y1, x0:x1]
    return cv2.resize(c, (c.shape[1] * 2, c.shape[0] * 2), interpolation=cv2.INTER_NEAREST)


regions = {
    "right_dancer_face": (150, 420, 700, 1000),
    "left_dancer_face": (150, 420, 30, 330),
    "wall_carving": (0, 200, 550, 1000),
    "doorway_crowd": (200, 480, 380, 780),
}
for name, (y0, y1, x0, x1) in regions.items():
    for tag, img in [("old", previous_output), ("new", new_output), ("ref", reference)]:
        cv2.imwrite(str(OUT / f"crop_{name}_{tag}.png"), crop2x(img, y0, y1, x0, x1))
print("7. wrote close-up crops to", OUT)
