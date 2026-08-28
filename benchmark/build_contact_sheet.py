import cv2
import numpy as np
from pathlib import Path

CASE = Path(r"F:\Projects\DesktopScanner\benchmark\cases\dance_hallroom_photo")
TRACE = Path(r"F:\Projects\DesktopScanner\benchmark\results\dance_hallroom_trace")
OUT = Path(r"C:\Users\manas\AppData\Local\Temp\claude\f--Projects-DesktopScanner\6110caf2-f5db-44a4-9d6d-0f2174459eda\scratchpad")

def resize_h(img, h):
    hh, ww = img.shape[:2]
    scale = h / hh
    return cv2.resize(img, (int(ww * scale), h))

def label(img, text):
    canvas = np.full((img.shape[0] + 26, img.shape[1], 3), 255, dtype=np.uint8)
    canvas[26:] = img
    cv2.putText(canvas, text, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return canvas

# ---- A: three-way comparison ----
H = 460
orig = resize_h(cv2.imread(str(CASE / "original.png")), H)
clearscan = resize_h(cv2.imread(str(CASE / "reference_clearscan_color_clear.jpeg")), H)
ours = resize_h(cv2.imread(str(CASE / "reference_desktopscanner_color_clear.jpg")), H)
gap = np.full((H + 26, 10, 3), 128, dtype=np.uint8)
row = np.hstack([label(orig, "ORIGINAL"), gap, label(clearscan, "ClearScanner (Clear/Color)"), gap, label(ours, "DesktopScanner (Clear/Color)")])
cv2.imwrite(str(OUT / "dh_threeway.png"), row)

# ---- C: intermediate-stage contact sheet ----
stages = [
    ("00_original", "0. original"),
    ("01_bilateral", "1. bilateral"),
    ("02_background_map_L", "2. background_map(L)"),
    ("03b_illum_corrected_BGR", "3. illum-corrected  <-- first big jump"),
    ("04b_clahe_BGR", "4. + CLAHE"),
    ("05b_tonal_push_BGR", "5. + whiten/darken push"),
    ("07_to_docs_color_FINAL", "6. to_docs() final"),
    ("10_to_clear_FINAL_regenerated", "7. to_clear() final"),
]
h2 = 220
tiles = []
for fname, cap in stages:
    img = cv2.imread(str(TRACE / f"{fname}.png"))
    tiles.append(label(resize_h(img, h2), cap))

gap2 = np.full((h2 + 26, 8, 3), 128, dtype=np.uint8)
row1 = np.hstack(sum([[t, gap2] for t in tiles[:4]], [])[:-1])
row2 = np.hstack(sum([[t, gap2] for t in tiles[4:]], [])[:-1])
w = max(row1.shape[1], row2.shape[1])
def pad_w(r, w):
    if r.shape[1] == w:
        return r
    pad = np.full((r.shape[0], w - r.shape[1], 3), 255, dtype=np.uint8)
    return np.hstack([r, pad])
row1 = pad_w(row1, w)
row2 = pad_w(row2, w)
vgap = np.full((10, w, 3), 255, dtype=np.uint8)
sheet = np.vstack([row1, vgap, row2])
cv2.imwrite(str(OUT / "dh_contactsheet.png"), sheet)
print("done")
