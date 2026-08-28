"""Systematic benchmark runner for the Docs/Clear/Photo pipeline.

Replaces "does this one image look okay?" trial-and-error with a
repeatable pass: every case under benchmark/cases/<name>/ gets run through
the real detection -> warp -> filter pipeline (mirroring what
ui/main_window.py actually does, including the same fallback_used logic
that gates allow_background_crush), for all 8 color-mode x bw combos.
Proxy quality metrics are computed for every output, and — where a real
scanner app's own reference screenshot is available for a case — an actual
difference-from-reference score too.

Usage:
    python benchmark/run_benchmark.py            # run everything
    python benchmark/run_benchmark.py passport_photo   # just one case

Adding a new case: make benchmark/cases/<name>/, drop an original.<ext>
photo in it. Optionally add reference_<mode>_<color|bw>.<ext> screenshots
from a real scanner app for direct comparison, plus a meta.json if the
reference screenshots need cropping (see passport_photo/meta.json for the
convention: reference_crop_top/bottom as 0-1 fractions to strip phone UI
chrome before comparing).
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearscanner.core import detector, filters  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent / "cases"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

MODES = [(m, bw) for m in ("docs", "clear") for bw in (False, True)]
IMG_EXTS = (".jpg", ".jpeg", ".png")


def _find(case_dir: Path, stem: str) -> Path | None:
    for ext in IMG_EXTS:
        p = case_dir / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def _mode_key(mode: str, bw: bool) -> str:
    return f"{mode}_{'bw' if bw else 'color'}"


def _load_meta(case_dir: Path) -> dict:
    meta_path = case_dir / "meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return {}


def _process_like_the_app(image: np.ndarray):
    """Mirror main_window.py: detect -> warp if a plausible quad was
    found, else use the full image with fallback_used=True (the same
    signal that gates allow_background_crush there)."""
    corners = detector.find_document_contour(image)
    if corners is None:
        return image, True
    from clearscanner.core import transform
    warped = transform.four_point_transform(image, corners)
    return warped, False


_FLAT_KERNEL = np.ones((3, 3), np.uint8)


def _posterization_score(channel: np.ndarray, lo: int = 60, hi: int = 200) -> float:
    """Fraction of mid-tone-band pixels sitting in a perfectly flat 3x3
    neighborhood (local max == local min) — real photographic gradients
    almost never are (natural texture/noise means adjacent pixels differ
    by at least 1); posterization/banding creates large flat plateaus with
    hard step edges between them. 0 = smooth gradient, higher = more
    banded/posterized-looking. (An earlier version of this metric counted
    distinct gray levels present anywhere in the image, which — on any
    image with more than a few hundred pixels — trivially hit "all 141
    levels present somewhere" regardless of whether the image was smooth
    or posterized; it never actually distinguished the two.)

    Only meaningful where midtones actually exist — see
    midtone_coverage_frac, which catches the complementary failure (a
    photographic subject blown out to highlights has almost nothing left
    in this band for a posterization score to even measure; that bug
    would silently score as "0 posterization" here without it — this is
    exactly what happened to the passport-photo washout bug this
    benchmark was built to catch)."""
    mask = (channel >= lo) & (channel <= hi)
    if not mask.any():
        return 0.0
    local_max = cv2.dilate(channel, _FLAT_KERNEL)
    local_min = cv2.erode(channel, _FLAT_KERNEL)
    flat = (local_max.astype(np.int16) - local_min.astype(np.int16)) == 0
    return float((flat & mask).sum()) / float(mask.sum())


def _proxy_metrics(bgr: np.ndarray, bw: bool) -> dict:
    gray = bgr if bw else cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    flat = gray.reshape(-1)
    bright_thresh = np.percentile(flat, 85)
    dark_thresh = np.percentile(flat, 10)
    paper_whiteness = float(flat[flat >= bright_thresh].mean())
    content_darkness = float(flat[flat <= dark_thresh].mean())
    posterization = _posterization_score(gray)
    midtone_coverage = float(((gray >= 60) & (gray <= 200)).mean())
    crushed_frac = float((flat < 30).mean())

    metrics = {
        "paper_whiteness": round(paper_whiteness, 1),
        "content_darkness": round(content_darkness, 1),
        "posterization_score": round(posterization, 4),
        "midtone_coverage_frac": round(midtone_coverage, 4),
        "very_dark_pixel_frac": round(crushed_frac, 4),
    }
    if not bw:
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        l, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
        chroma = np.sqrt((a - 128) ** 2 + (b - 128) ** 2)
        bg_mask = l >= bright_thresh
        metrics["background_color_cast"] = round(float(chroma[bg_mask].mean()) if bg_mask.any() else 0.0, 1)
    return metrics


def _prep_for_compare(img: np.ndarray, target_shape) -> np.ndarray:
    return cv2.resize(img, (target_shape[1], target_shape[0]), interpolation=cv2.INTER_AREA)


def _reference_diff(ours: np.ndarray, reference: np.ndarray, crop_top: float, crop_bottom: float, bw: bool) -> dict:
    h, w = reference.shape[:2]
    ref_crop = reference[int(h * crop_top):int(h * crop_bottom), :]
    ref_resized = _prep_for_compare(ref_crop, ours.shape[:2])

    ours_g = ours if bw else cv2.cvtColor(ours, cv2.COLOR_BGR2GRAY)
    ref_g = ref_resized if (bw and ref_resized.ndim == 2) else cv2.cvtColor(ref_resized, cv2.COLOR_BGR2GRAY)

    brightness_delta = float(ours_g.astype(np.float32).mean() - ref_g.astype(np.float32).mean())
    mae = float(np.abs(ours_g.astype(np.float32) - ref_g.astype(np.float32)).mean())
    out = {"brightness_delta_vs_ref": round(brightness_delta, 1), "mean_abs_diff_vs_ref": round(mae, 1)}

    if not bw:
        ours_lab = cv2.cvtColor(ours, cv2.COLOR_BGR2LAB).astype(np.float32)
        ref_lab = cv2.cvtColor(ref_resized, cv2.COLOR_BGR2LAB).astype(np.float32)
        chroma_delta = float(
            np.sqrt((ours_lab[..., 1] - 128) ** 2 + (ours_lab[..., 2] - 128) ** 2).mean()
            - np.sqrt((ref_lab[..., 1] - 128) ** 2 + (ref_lab[..., 2] - 128) ** 2).mean()
        )
        out["chroma_delta_vs_ref"] = round(chroma_delta, 1)
    return out


def run_case(case_dir: Path) -> dict:
    name = case_dir.name
    original_path = _find(case_dir, "original")
    if original_path is None:
        print(f"  [skip] {name}: no original.* found")
        return {}

    image = cv2.imread(str(original_path))
    if image is None:
        print(f"  [skip] {name}: failed to load {original_path}")
        return {}

    meta = _load_meta(case_dir)
    crop_top = meta.get("reference_crop_top", 0.0)
    crop_bottom = meta.get("reference_crop_bottom", 1.0)

    processed, fallback_used = _process_like_the_app(image)
    out_dir = RESULTS_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)

    case_report = {"fallback_used": fallback_used, "modes": {}}

    for mode, bw in MODES:
        key = _mode_key(mode, bw)
        out = filters.apply_filter(processed, mode=mode, bw=bw, allow_background_crush=fallback_used)
        cv2.imwrite(str(out_dir / f"{key}.png"), out)

        entry = _proxy_metrics(out, bw)

        ref_path = _find(case_dir, f"reference_{key}")
        if ref_path is not None:
            reference = cv2.imread(str(ref_path))
            if reference is not None:
                entry.update(_reference_diff(out, reference, crop_top, crop_bottom, bw))

        case_report["modes"][key] = entry

    return case_report


def main():
    only = sys.argv[1:] or None
    all_results = {}
    for case_dir in sorted(CASES_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        if only and case_dir.name not in only:
            continue
        print(f"== {case_dir.name} ==")
        result = run_case(case_dir)
        if result:
            all_results[case_dir.name] = result
            for key, entry in result["modes"].items():
                print(f"  {key:14s} {entry}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS_DIR / "report.json"
    report_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nFull report written to {report_path}")


if __name__ == "__main__":
    main()
