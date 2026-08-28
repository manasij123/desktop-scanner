"""Experimental-only ablation: does NOT touch filters.py. Builds 4 variants
of the Clear pipeline on the dance_hallroom_photo original, switching the
two tonal-push steps (docs' own whiten/darken push, and Clear's second
wider-band push) on/off independently, everything else held identical.
Purpose: prove or disprove that these two steps are what's driving the
output away from the ClearScanner reference, before touching production
code. See benchmark/trace_dance_hallroom.py for the full staged trace this
builds on.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearscanner.core import detector, filters  # noqa: E402

CASE = Path(__file__).resolve().parent / "cases" / "dance_hallroom_photo"
OUT = Path(__file__).resolve().parent / "results" / "dance_hallroom_ablation"
OUT.mkdir(parents=True, exist_ok=True)

original = cv2.imread(str(CASE / "original.png"))
reference = cv2.imread(str(CASE / "reference_clearscan_color_clear.jpeg"))
confidence = filters._paper_confidence(original)
print("paper_confidence:", confidence)


def build_variant(image, use_tonal_push: bool, use_clear_extra_push: bool):
    smoothed = cv2.bilateralFilter(image, d=5, sigmaColor=40, sigmaSpace=40)
    lab = cv2.cvtColor(smoothed, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l_illum = filters._correct_illumination(l, paper_confidence=confidence)
    l_clahe = cv2.createCLAHE(clipLimit=filters._CLAHE_CLIP_LIMIT, tileGridSize=(8, 8)).apply(l_illum)

    if use_tonal_push:
        pushed = filters._darken_shadows(filters._whiten_highlights(l_clahe))
        l_docs = np.clip(l_clahe.astype(np.float32) * (1 - confidence) + pushed.astype(np.float32) * confidence,
                          0, 255).astype(np.uint8)
    else:
        l_docs = l_clahe

    l_docs_sharp = filters._unsharp(l_docs, amount=1.3, sigma=1.0)
    l_final, a_final, b_final = filters._white_balance_lab(l_docs_sharp, a, b)
    docs_color = cv2.cvtColor(cv2.merge((l_final, a_final, b_final)), cv2.COLOR_LAB2BGR)

    lab2 = cv2.cvtColor(docs_color, cv2.COLOR_BGR2LAB)
    l2, a2, b2 = cv2.split(lab2)
    if use_clear_extra_push:
        pushed_l2 = filters._darken_shadows(
            filters._whiten_highlights(l2, blend_start=188, white_point=238), blend_start=105, black_point=52
        )
        l2_blend = np.clip(l2.astype(np.float32) * (1 - confidence) + pushed_l2.astype(np.float32) * confidence,
                            0, 255).astype(np.uint8)
    else:
        l2_blend = l2

    clear_pre_sharp = cv2.cvtColor(cv2.merge((l2_blend, a2, b2)), cv2.COLOR_LAB2BGR)
    clear_final = filters._unsharp(clear_pre_sharp, amount=0.6, sigma=1.0)
    return clear_final


def metrics(img, ref):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    total = gray.size
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sat = hsv[..., 1].astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edge_strength = float(np.sqrt(gx ** 2 + gy ** 2).mean())

    ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32)
    ref_hsv = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV)
    ref_sat = ref_hsv[..., 1].astype(np.float32)

    return {
        "mean": round(float(gray.mean()), 1),
        "std": round(float(gray.std()), 1),
        "frac_hi_245": round(float((gray >= 245).sum()) / total, 3),
        "frac_lo_10": round(float((gray <= 10).sum()) / total, 3),
        "frac_mid_40_220": round(float(((gray >= 40) & (gray <= 220)).sum()) / total, 3),
        "sat_mean": round(float(sat.mean()), 1),
        "edge_strength": round(edge_strength, 1),
        "luminance_MAE_vs_ref": round(float(np.abs(gray - ref_gray).mean()), 1),
        "sat_MAE_vs_ref": round(float(np.abs(sat - ref_sat).mean()), 1),
    }


variants = {
    "A_current":            (True, True),
    "B_no_tonal_push":      (False, True),
    "C_no_clear_extra":     (True, False),
    "D_no_both":            (False, False),
}

results = {}
for name, (use_tp, use_ce) in variants.items():
    out = build_variant(original, use_tp, use_ce)
    cv2.imwrite(str(OUT / f"{name}.png"), out)
    m = metrics(out, reference)
    results[name] = m
    print(f"{name:20s} {m}")

# sanity: A should equal filters.to_clear(original, False) exactly (fallback_used is False for this image)
direct = filters.to_clear(original, False)
a_img = cv2.imread(str(OUT / "A_current.png"))
diff = np.abs(direct.astype(np.int16) - a_img.astype(np.int16)).mean()
print(f"\nsanity: A vs filters.to_clear() direct = {diff:.4f} (should be ~0)")

ref_m = metrics(reference, reference)
print(f"\n{'REFERENCE (ClearScanner)':20s} {ref_m}")
orig_gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY).astype(np.float32)
print(f"ORIGINAL mean/std: {orig_gray.mean():.1f}/{orig_gray.std():.1f}  "
      f"frac_hi_245={float((orig_gray>=245).sum())/orig_gray.size:.3f}  "
      f"frac_lo_10={float((orig_gray<=10).sum())/orig_gray.size:.3f}  "
      f"frac_mid={float(((orig_gray>=40)&(orig_gray<=220)).sum())/orig_gray.size:.3f}")
