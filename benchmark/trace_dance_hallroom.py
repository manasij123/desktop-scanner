"""Diagnosis-only trace for the dance_hallroom_photo benchmark case — NO
parameter tuning, NO code changes. Renders every stage of the Color/Clear
pipeline on the real original photo and measures where it first diverges.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearscanner.core import detector, filters  # noqa: E402

CASE = Path(__file__).resolve().parent / "cases" / "dance_hallroom_photo"
OUT = Path(__file__).resolve().parent / "results" / "dance_hallroom_trace"
OUT.mkdir(parents=True, exist_ok=True)

original = cv2.imread(str(CASE / "original.png"))
ref_clearscan = cv2.imread(str(CASE / "reference_clearscan_color_clear.jpeg"))
ref_ours = cv2.imread(str(CASE / "reference_desktopscanner_color_clear.jpg"))

print("shapes:", original.shape, ref_clearscan.shape, ref_ours.shape)

corners = detector.find_document_contour(original)
fallback_used = corners is None
print("find_document_contour ->", "None (fallback)" if fallback_used else corners.tolist())
print("fallback_used:", fallback_used, " => allow_background_crush would be", fallback_used, "in the real app")

confidence = filters._paper_confidence(original)
print("paper_confidence:", confidence)

mask = detector.get_subject_mask(original)
if mask is not None:
    print("subject mask overall mean:", round(float(mask.mean()), 1))


def save(name, img):
    cv2.imwrite(str(OUT / f"{name}.png"), img)


def hist_stats(img, label):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    flat = gray.astype(np.float32)
    total = flat.size
    frac_hi = float((flat >= 245).sum()) / total
    frac_lo = float((flat <= 10).sum()) / total
    frac_mid = float(((flat >= 40) & (flat <= 220)).sum()) / total
    print(f"  {label:28s} mean={flat.mean():6.1f} std={flat.std():6.1f}  >=245:{frac_hi:6.3f}  <=10:{frac_lo:6.3f}  40-220:{frac_mid:6.3f}")
    return dict(mean=flat.mean(), std=flat.std(), frac_hi=frac_hi, frac_lo=frac_lo, frac_mid=frac_mid)


print("\n=== top-level histogram comparison ===")
hist_stats(original, "ORIGINAL")
hist_stats(ref_clearscan, "REFERENCE (ClearScanner)")
hist_stats(ref_ours, "REFERENCE (our app, exported)")

print("\n=== regenerating via CURRENT filters.py, staged ===")
image = original
save("00_original", image)

# ---- to_docs's own steps, unrolled ----
smoothed = cv2.bilateralFilter(image, d=5, sigmaColor=40, sigmaSpace=40)
save("01_bilateral", smoothed)
hist_stats(smoothed, "01 bilateral")

lab = cv2.cvtColor(smoothed, cv2.COLOR_BGR2LAB)
l, a, b = cv2.split(lab)
pre_correction_l = l.copy()

bg_map = filters._background_map(l)
save("02_background_map_L", bg_map)
hist_stats(bg_map, "02 background_map(L)")

l_illum = filters._correct_illumination(l, paper_confidence=confidence)
save("03_illum_corrected_L", l_illum)
hist_stats(l_illum, "03 illum_corrected(L)")
tmp_lab = cv2.merge((l_illum, a, b))
save("03b_illum_corrected_BGR", cv2.cvtColor(tmp_lab, cv2.COLOR_LAB2BGR))

l_step = l_illum
mask_gate = mask if fallback_used else None
if mask_gate is not None:
    l_step = filters._protect_subject(l_illum, pre_correction_l, mask_gate)
    save("03c_after_subject_protect_L", l_step)
    hist_stats(l_step, "03c after _protect_subject(L)")
else:
    print("  (allow_background_crush is False for this image in real usage -> _protect_subject NEVER RUNS)")

l_clahe = cv2.createCLAHE(clipLimit=filters._CLAHE_CLIP_LIMIT, tileGridSize=(8, 8)).apply(l_step)
save("04_clahe_L", l_clahe)
hist_stats(l_clahe, "04 clahe(L)")
save("04b_clahe_BGR", cv2.cvtColor(cv2.merge((l_clahe, a, b)), cv2.COLOR_LAB2BGR))

pushed = filters._darken_shadows(filters._whiten_highlights(l_clahe))
l_pushed = np.clip(l_clahe.astype(np.float32) * (1 - confidence) + pushed.astype(np.float32) * confidence,
                    0, 255).astype(np.uint8)
save("05_tonal_push_L", l_pushed)
hist_stats(l_pushed, "05 tonal_push(L) [docs-strength push]")
save("05b_tonal_push_BGR", cv2.cvtColor(cv2.merge((l_pushed, a, b)), cv2.COLOR_LAB2BGR))

l_docs = l_pushed
if mask_gate is not None:
    l_docs = filters._darken_background(l_docs, mask_gate, filters._BG_CRUSH_DOCS)
    save("05c_after_bg_crush_L", l_docs)
    hist_stats(l_docs, "05c after _darken_background (docs)")

l_docs_sharp = filters._unsharp(l_docs, amount=1.3, sigma=1.0)
save("06_unsharp_L", l_docs_sharp)
hist_stats(l_docs_sharp, "06 unsharp(L)")

l_final, a_final, b_final = filters._white_balance_lab(l_docs_sharp, a, b)
docs_color = cv2.cvtColor(cv2.merge((l_final, a_final, b_final)), cv2.COLOR_LAB2BGR)
save("07_to_docs_color_FINAL", docs_color)
hist_stats(docs_color, "07 to_docs() FINAL")

# ---- to_clear's extra pass on top of docs ----
lab2 = cv2.cvtColor(docs_color, cv2.COLOR_BGR2LAB)
l2, a2, b2 = cv2.split(lab2)
pre_push_l2 = l2.copy()
pushed_l2 = filters._darken_shadows(
    filters._whiten_highlights(l2, blend_start=188, white_point=238), blend_start=105, black_point=52
)
l2_blend = np.clip(l2.astype(np.float32) * (1 - confidence) + pushed_l2.astype(np.float32) * confidence,
                    0, 255).astype(np.uint8)
save("08_clear_extra_push_L", l2_blend)
hist_stats(l2_blend, "08 clear extra push(L)")

if mask_gate is not None:
    l2_blend = filters._protect_subject(l2_blend, pre_push_l2, mask_gate)
    save("08b_after_subject_protect2_L", l2_blend)
    hist_stats(l2_blend, "08b after _protect_subject #2")

clear_pre_sharp = cv2.cvtColor(cv2.merge((l2_blend, a2, b2)), cv2.COLOR_LAB2BGR)
clear_sharp = filters._unsharp(clear_pre_sharp, amount=0.6, sigma=1.0)
save("09_clear_sharpened", clear_sharp)
hist_stats(clear_sharp, "09 clear sharpened")

final_clear = clear_sharp
if mask_gate is not None:
    final_clear = filters._darken_background(clear_sharp, mask_gate, filters._BG_CRUSH_CLEAR_EXTRA)
    save("09b_after_bg_crush2", final_clear)
    hist_stats(final_clear, "09b after _darken_background (clear extra)")

save("10_to_clear_FINAL_regenerated", final_clear)
hist_stats(final_clear, "10 to_clear() FINAL (regenerated, current code)")

# sanity: matches filters.to_clear() directly?
direct = filters.to_clear(original, fallback_used)
diff = np.abs(direct.astype(np.int16) - final_clear.astype(np.int16)).mean()
print(f"\nsanity: mean abs diff between unrolled trace and filters.to_clear() direct call = {diff:.4f} (should be ~0)")
