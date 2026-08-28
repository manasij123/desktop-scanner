import cv2
import numpy as np
from pathlib import Path

D = Path(r"F:\Projects\DesktopScanner\benchmark\results\dance_hallroom_ablation")
CASE = Path(r"F:\Projects\DesktopScanner\benchmark\cases\dance_hallroom_photo")
OUT = Path(r"C:\Users\manas\AppData\Local\Temp\claude\f--Projects-DesktopScanner\6110caf2-f5db-44a4-9d6d-0f2174459eda\scratchpad")


def resize_h(img, h):
    hh, ww = img.shape[:2]
    s = h / hh
    return cv2.resize(img, (int(ww * s), h))


def label(img, text):
    c = np.full((img.shape[0] + 26, img.shape[1], 3), 255, dtype=np.uint8)
    c[26:] = img
    cv2.putText(c, text, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return c


H = 380
imgs = {}
for name, cap in [
    ("A_current", "A current (full)"),
    ("B_no_tonal_push", "B no tonal_push"),
    ("C_no_clear_extra", "C no clear_extra"),
    ("D_no_both", "D no both"),
]:
    img = cv2.imread(str(D / f"{name}.png"))
    imgs[name] = label(resize_h(img, H), cap)

ref = cv2.imread(str(CASE / "reference_clearscan_color_clear.jpeg"))
imgs["ref"] = label(resize_h(ref, H), "REFERENCE (ClearScanner)")
orig = cv2.imread(str(CASE / "original.png"))
imgs["orig"] = label(resize_h(orig, H), "ORIGINAL")

gap = np.full((H + 26, 8, 3), 128, dtype=np.uint8)
row1 = np.hstack([imgs["orig"], gap, imgs["A_current"], gap, imgs["B_no_tonal_push"]])
row2 = np.hstack([imgs["ref"], gap, imgs["C_no_clear_extra"], gap, imgs["D_no_both"]])
w = max(row1.shape[1], row2.shape[1])


def pad(r):
    if r.shape[1] == w:
        return r
    return np.hstack([r, np.full((r.shape[0], w - r.shape[1], 3), 255, dtype=np.uint8)])


sheet = np.vstack([pad(row1), np.full((10, w, 3), 255, dtype=np.uint8), pad(row2)])
cv2.imwrite(str(OUT / "dh_ablation_sheet.png"), sheet)
print("done")
