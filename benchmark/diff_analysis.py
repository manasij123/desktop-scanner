"""Region + channel-level diff between our NEW Clear Color output (post
detector-fix) and the ClearScanner reference, to find exactly where the
remaining gap concentrates before touching any more code."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CASE = Path(__file__).resolve().parent / "cases" / "dance_hallroom_photo"
TRACE = Path(__file__).resolve().parent / "results" / "dance_hallroom_after_detector_fix"
OUT = Path(r"C:\Users\manas\AppData\Local\Temp\claude\f--Projects-DesktopScanner\6110caf2-f5db-44a4-9d6d-0f2174459eda\scratchpad")

ours = cv2.imread(str(TRACE / "new_clear_color.png"))
ref = cv2.imread(str(CASE / "reference_clearscan_color_clear.jpeg"))
print("shapes:", ours.shape, ref.shape)
if ours.shape[:2] != ref.shape[:2]:
    ref = cv2.resize(ref, (ours.shape[1], ours.shape[0]))

lab_o = cv2.cvtColor(ours, cv2.COLOR_BGR2LAB).astype(np.float32)
lab_r = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype(np.float32)
hsv_o = cv2.cvtColor(ours, cv2.COLOR_BGR2HSV).astype(np.float32)
hsv_r = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV).astype(np.float32)

l_diff = lab_o[..., 0] - lab_r[..., 0]          # + = ours brighter
a_diff = lab_o[..., 1] - lab_r[..., 1]
b_diff = lab_o[..., 2] - lab_r[..., 2]
s_diff = hsv_o[..., 1] - hsv_r[..., 1]          # + = ours more saturated

def heat(diff, scale=2.0):
    v = np.clip(diff * scale + 128, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(v, cv2.COLORMAP_JET)

cv2.imwrite(str(OUT / "diff_L.png"), heat(l_diff, 2.0))
cv2.imwrite(str(OUT / "diff_sat.png"), heat(s_diff, 2.0))
print(f"L diff  (ours-ref): mean={l_diff.mean():+.1f} | positive(ours brighter) frac={float((l_diff>15).mean()):.3f} | negative frac={float((l_diff<-15).mean()):.3f}")
print(f"Sat diff(ours-ref): mean={s_diff.mean():+.1f} | ours-less-saturated(<-15) frac={float((s_diff<-15).mean()):.3f}")

# ---- named regions ----
regions = {
    "wall_upper": (0, 200, 550, 1170),
    "right_face": (150, 420, 700, 1000),
    "right_hand_skin": (420, 560, 850, 1080),
    "left_face": (150, 420, 30, 330),
    "orange_sari": (400, 650, 750, 1050),
    "blue_blouse": (350, 550, 620, 850),
    "doorway_shadow": (60, 400, 380, 620),
}

print(f"\n{'region':18s} {'L_ours':>7s} {'L_ref':>7s} {'dL':>6s} | {'S_ours':>7s} {'S_ref':>7s} {'dS':>6s} | {'a_ours':>7s} {'a_ref':>7s} | {'b_ours':>7s} {'b_ref':>7s}")
for name, (y0, y1, x0, x1) in regions.items():
    lo = lab_o[y0:y1, x0:x1, 0].mean(); lr = lab_r[y0:y1, x0:x1, 0].mean()
    so = hsv_o[y0:y1, x0:x1, 1].mean(); sr = hsv_r[y0:y1, x0:x1, 1].mean()
    ao = lab_o[y0:y1, x0:x1, 1].mean(); ar = lab_r[y0:y1, x0:x1, 1].mean()
    bo = lab_o[y0:y1, x0:x1, 2].mean(); br = lab_r[y0:y1, x0:x1, 2].mean()
    print(f"{name:18s} {lo:7.1f} {lr:7.1f} {lo-lr:+6.1f} | {so:7.1f} {sr:7.1f} {so-sr:+6.1f} | {ao:7.1f} {ar:7.1f} | {bo:7.1f} {br:7.1f}")
