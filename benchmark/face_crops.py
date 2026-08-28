import cv2
from pathlib import Path

D = Path(r"F:\Projects\DesktopScanner\benchmark")
OUT = Path(r"C:\Users\manas\AppData\Local\Temp\claude\f--Projects-DesktopScanner\6110caf2-f5db-44a4-9d6d-0f2174459eda\scratchpad")

ours = cv2.imread(str(D / "results" / "dance_hallroom_trace" / "10_to_clear_FINAL_regenerated.png"))
ref = cv2.imread(str(D / "cases" / "dance_hallroom_photo" / "reference_clearscan_color_clear.jpeg"))
orig = cv2.imread(str(D / "cases" / "dance_hallroom_photo" / "original.png"))
print("shapes", ours.shape, ref.shape, orig.shape)

crops = {
    "right_dancer_face": (150, 420, 700, 1000),
    "left_dancer_face": (150, 420, 30, 330),
    "crowd_faces": (200, 480, 380, 780),
}
for name, (y0, y1, x0, x1) in crops.items():
    for tag, img in [("orig", orig), ("ours", ours), ("ref", ref)]:
        crop = img[y0:y1, x0:x1]
        crop = cv2.resize(crop, (crop.shape[1] * 2, crop.shape[0] * 2), interpolation=cv2.INTER_NEAREST)
        out_path = OUT / f"face_{name}_{tag}.png"
        cv2.imwrite(str(out_path), crop)
        print("wrote", out_path)
