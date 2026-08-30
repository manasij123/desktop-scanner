"""Ad-hoc check for the faint-ink recovery toggle (recover_ink=True).

Runs each case through the real detect->warp->filter path with recover_ink
OFF then ON, and reports where the two differ. What we want to see:

- notebook_page (Bengali): tiny / no change — the strokes are already
  solid, nothing to recover, and Bengali must not be damaged.
- handwriting_shadow: the back-page show-through region must NOT get
  darker (it is not real front-side ink).
- a synthetic-glare version of notebook_page: the washed-out text SHOULD
  come back toward ink.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearscanner.core import detector, filters, transform  # noqa: E402

CASES = Path(__file__).resolve().parent / "cases"
OUT = Path(__file__).resolve().parent / "results" / "recover_ink"
OUT.mkdir(parents=True, exist_ok=True)


def warp(path):
    img = cv2.imread(str(path))
    corners = detector.find_document_contour(img)
    if corners is None:
        return img, True
    return transform.four_point_transform(img, corners), False


def stats(a, b, label):
    d = a.astype(np.int16) - b.astype(np.int16)
    darker = np.count_nonzero(d > 6) / d.size          # b darker than a => recovered ink
    lighter = np.count_nonzero(d < -6) / d.size
    print(f"  {label:24s} mean|Δ|={np.abs(d).mean():.2f}  darkened={darker*100:.2f}%  lightened={lighter*100:.2f}%")


def run_case(name, synth_glare=False):
    src = CASES / name / "original.jpg"
    if not src.exists():
        print(f"skip {name} (missing)")
        return
    img, fallback = warp(src)
    tag = name + ("_glare" if synth_glare else "")
    if synth_glare:
        # veiling glare: alpha-blend a soft diagonal blob toward white,
        # which is what a reflection physically does — it compresses local
        # contrast and pushes strokes toward paper, and (unlike a pure
        # additive wash) illumination correction can't fully undo it
        h, w = img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        a = 0.8 * np.exp(-(((xx + yy) / (w + h) - 0.44) ** 2) / (2 * 0.13 ** 2))
        a = a[..., None]
        img = np.clip(img.astype(np.float32) * (1 - a) + 255.0 * a, 0, 255).astype(np.uint8)
        cv2.imwrite(str(OUT / f"{tag}_input.png"), img)

    print(f"== {tag}  (fallback={fallback}) ==")
    for mode in ("docs", "clear"):
        off = filters.apply_filter(img, mode, bw=False, allow_background_crush=fallback, recover_ink=False)
        on = filters.apply_filter(img, mode, bw=False, allow_background_crush=fallback, recover_ink=True)
        stats(off, on, f"{mode}_color")
        cv2.imwrite(str(OUT / f"{tag}_{mode}_off.png"), off)
        cv2.imwrite(str(OUT / f"{tag}_{mode}_on.png"), on)
        cv2.imwrite(str(OUT / f"{tag}_{mode}_diff.png"),
                    cv2.applyColorMap(cv2.convertScaleAbs(
                        off.astype(np.int16) - on.astype(np.int16), alpha=4), cv2.COLORMAP_JET))


for n in ("notebook_page", "handwriting_shadow", "passport_photo", "aadhaar_card"):
    run_case(n)
run_case("notebook_page", synth_glare=True)
print(f"\nimages -> {OUT}")
