"""Post-warp enhancement filters (scan look presets).

Two independent axes, matching how mobile scanner apps present this:
- COLOR_MODES: "original" (untouched) / "photo" (light touch) /
  "docs" (illumination-corrected, high contrast, still color) /
  "clear" (docs + a light sharpen) — the flagship default.
- A separate B/W toggle, which does NOT collapse to one generic
  monochrome output — each color mode has its own matching B&W
  rendering at the same processing strength (Original+B&W is a plain
  grayscale copy, Clear+B&W is the fully illumination-corrected,
  contrast-boosted "document" look), same as real scanner apps do.

Uses edge-preserving smoothing (bilateral filter) + CLAHE contrast
enhancement instead of heavy NL-means denoising — NL-means blurs fine
handwriting/text detail into a soft, plasticky look even at moderate
strength, which is not what a "scan" should look like.
"""
import cv2
import numpy as np

from clearscanner.core import detector

COLOR_MODES = ("original", "photo", "docs", "clear")
FILTER_MODES = COLOR_MODES  # back-compat alias (CLI, older callers)


_ILLUM_ESTIMATE_SIZE = 800  # px, short side

# CLAHE's clip limit — found via a real ID-card photo with an embedded ID
# photo: at the previous 2.0, CLAHE's per-tile local histogram equalization
# (meant to lift faint printed text, e.g. a light-gray address block, to
# legible contrast) was strong enough to also carve smooth continuous-tone
# regions like that embedded photo into visibly blotchy, posterized patches.
# 0.6 still lifts faint text to readable contrast but stops short of
# posterizing photographic content — verified by comparing both a text
# region (still legible) and the photo region (smooth again) across a
# clip-limit sweep.
_CLAHE_CLIP_LIMIT = 0.6

# How hard Docs/Clear crush background (non-subject) pixels toward black —
# see _darken_background. Clear's extra pass compounds with Docs' own, so
# it's a further push on top of an already-strong one, not the whole crush
# by itself (0.85 then 0.6 more of what's left, not 0.85 then 0.6 flat).
_BG_CRUSH_DOCS = 0.85
_BG_CRUSH_CLEAR_EXTRA = 0.6


def _background_map(channel: np.ndarray, extra_blur_frac: float = 0.0) -> np.ndarray:
    """Estimate the slow-varying "background" of a single-channel image —
    used both for L-channel shading (divide it out) and for A/B-channel
    color cast (recenter around it) — see _correct_illumination and
    _white_balance_lab below.

    Estimate with a large morphological close (big enough to erase text
    strokes, small enough to track slow lighting/color gradients), on a
    downscaled copy: this is a low-frequency signal, so downscaling loses
    no real accuracy, but running a ~250px-wide morphological kernel
    directly on a full 12MP+ photo took 5+ seconds — on an 800px copy the
    same kernel (now proportionally ~65px) finishes in a fraction of a
    second. `extra_blur_frac`, if given, adds a Gaussian blur on top —
    IMPORTANT: this runs before the upscale back to full size below, not
    after. Blurring at full 12MP+ resolution with a sigma wide enough to
    matter (needed for A/B color-cast smoothing) took 30+ seconds; the
    same relative blur on the ≤800px copy is instant, and upscaling a
    result that's already smooth doesn't need to redo that work.
    """
    h, w = channel.shape
    scale = min(1.0, _ILLUM_ESTIMATE_SIZE / min(h, w))
    small = cv2.resize(channel, (max(1, int(w * scale)), max(1, int(h * scale))),
                        interpolation=cv2.INTER_AREA) if scale < 1.0 else channel

    small_h, small_w = small.shape
    kernel_size = max(15, int(min(small_h, small_w) * 0.08) | 1)  # odd, ~8% of the shorter side
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    background_small = cv2.morphologyEx(small, cv2.MORPH_CLOSE, kernel)

    if extra_blur_frac > 0:
        # A sigma wide enough to matter (proportional to the 800px copy)
        # makes cv2.GaussianBlur build an enormous explicit kernel — it
        # was the actual cost here, ~4.5s per channel, not the earlier
        # full-resolution blur this was supposed to have already fixed.
        # We only want a very low-frequency smoothing anyway, so shrink
        # further first (150px is still plenty to represent a color-cast
        # gradient) and blur that instead — same visual result, a tiny
        # fraction of the pixels and a much smaller kernel.
        tiny_size = 150
        tiny_scale = min(1.0, tiny_size / min(small_h, small_w))
        tiny = (
            cv2.resize(background_small, (max(1, int(small_w * tiny_scale)), max(1, int(small_h * tiny_scale))),
                       interpolation=cv2.INTER_AREA)
            if tiny_scale < 1.0 else background_small
        )
        sigma = max(3, int(min(tiny.shape) * extra_blur_frac))
        tiny = cv2.GaussianBlur(tiny, (0, 0), sigma)
        background_small = (
            cv2.resize(tiny, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
            if tiny_scale < 1.0 else tiny
        )

    return (
        cv2.resize(background_small, (w, h), interpolation=cv2.INTER_LINEAR)
        if scale < 1.0 else background_small
    )


def _paper_confidence(image: np.ndarray, low_frac: float = 0.15, high_frac: float = 0.35) -> float:
    """0-1 score for "does this look like a real photographed paper
    document" — the fraction of the image that's bright AND close to
    neutral in color (paper, even if not perfectly flattened or white-
    balanced yet), smoothstepped between low_frac/high_frac.

    Docs/Clear's whole approach (flatten shading toward white, push text
    toward black) assumes a document with a paper background exists at
    all — found necessary via a systematic color-swatch test chart with
    no paper anywhere in it: even with _correct_illumination's own
    brightness-based blend (see below), a chart that's uniformly bright
    and colorful still read as "background is bright, apply full
    correction," collapsing a 13-step grayscale ramp down to essentially
    just black-or-white and stripping most saturated colors toward pale
    pastels. Brightness alone can't tell a colorful chart from a shaded
    real page — chroma can: a real paper background reads as low-chroma
    even when unevenly lit, while a colorful chart or a photographed
    scene doesn't, regardless of how bright it is. Thresholds found by
    checking this fraction against two real documents (0.57, 0.97) and
    two non-document images (0.11, 0.05) — a comfortable margin exists
    between the two groups at 0.15-0.35.
    """
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    l, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.sqrt((a - 128) ** 2 + (b - 128) ** 2)
    paper_like = (l > 120) & (chroma < 15)
    frac = float(paper_like.mean())
    t = np.clip((frac - low_frac) / max(high_frac - low_frac, 1e-6), 0.0, 1.0)
    return float(t * t * (3 - 2 * t))  # smoothstep


def _correct_illumination(
    channel: np.ndarray, blend_low: int = 90, blend_high: int = 160, paper_confidence: float = 1.0
) -> np.ndarray:
    """Flatten uneven lighting/shadows so the page background reads as
    evenly bright regardless of shading — divide out the estimated
    background. This is the step that gives real scanner apps their flat,
    evenly-white background; a plain contrast stretch alone can't fix a
    shadow gradient. Works on any single-channel image.

    Docs/Clear run on any photo, not just ones of an actual paper document
    (found via a photo of a phone screen — a dark, colorful image with no
    paper in it at all): dividing by the estimated background always
    assumes that background SHOULD be white, so on an image whose
    background estimate is itself dark, the divide blows small pixel-to-
    pixel variation up into huge swings — a speckled, wildly overbright
    mess instead of a legitimate correction. The correction is therefore
    scaled per-pixel by how bright the background estimate reads (a genuine
    paper background, even shaded, measures ~130+), times paper_confidence
    (see _paper_confidence) to also spare a uniformly bright but non-paper
    image — a colour-swatch chart's ~13-step grey ramp would otherwise
    collapse toward white.

    When paper_confidence is near 1 (the whole frame really is a page) the
    per-pixel brightness gate is widened downward — blend_low/high slide
    from 90/160 toward ~45/115 — so the divide still fully flattens a hard
    cast shadow (a shadowed page background reads ~120-140, which the
    unwidened gate only half-corrected, leaving a visible grey shade band —
    found via a handwriting photo with a sharp diagonal shade line,
    benchmarked against a real scanner app that erased it). The gate is
    only widened, not removed: a genuinely dark region (bg < ~80 — an unlit
    doorway behind the subjects in a non-document photo that still scored
    high paper_confidence off its bright wall) stays protected from being
    blown open.
    """
    background = _background_map(channel)
    corrected = cv2.divide(channel, background, scale=255)

    full_page = np.clip((paper_confidence - 0.8) / 0.2, 0.0, 1.0)
    full_page = full_page * full_page * (3 - 2 * full_page)  # smoothstep
    lo = blend_low - full_page * 45.0
    hi = blend_high - full_page * 45.0

    bg = background.astype(np.float32)
    bright_strength = np.clip((bg - lo) / max(hi - lo, 1.0), 0.0, 1.0)
    bright_strength = bright_strength * bright_strength * (3 - 2 * bright_strength)  # smoothstep
    strength = bright_strength * paper_confidence
    blended = channel.astype(np.float32) * (1 - strength) + corrected.astype(np.float32) * strength
    return np.clip(blended, 0, 255).astype(np.uint8)


def _white_balance_lab(l: np.ndarray, a: np.ndarray, b: np.ndarray):
    """Neutralize the ambient color cast (warm indoor light, etc.) so the
    page background renders as actually white instead of tinted — without
    this, illumination-correcting only L still leaves a yellowish/sepia
    background, since a color cast lives in the A/B channels, not L.

    Shift A and B by a single constant so the page's own paper tone lands
    on neutral (128) — real color content (ink, highlights) shifts by the
    same amount, preserving contrast.

    The paper tone is the mean A/B over near-neutral (low-chroma) pixels
    only, found via a real ID-card photo with a wide orange/green
    letterhead band: an earlier version estimated a spatially-varying
    background the same way _correct_illumination does for L (morphological
    closing + blur), but closing is a brightness-domain operation — on a
    chrominance channel it let saturated color blocks bleed into the
    "background" estimate for paper near them, and correcting against that
    contaminated estimate visibly overcorrected the paper into cyan/pink. A
    color cast is a single ambient light color, not something that varies
    place to place the way shading does, so a single global constant (from
    only the pixels that already look like paper/ink, not printed color)
    is both simpler and immune to that contamination.
    """
    chroma = np.sqrt((a.astype(np.float32) - 128) ** 2 + (b.astype(np.float32) - 128) ** 2)
    paper_mask = chroma < 10
    paper_a = a[paper_mask].mean() if paper_mask.any() else 128.0
    paper_b = b[paper_mask].mean() if paper_mask.any() else 128.0
    a = np.clip(a.astype(np.float32) - paper_a + 128, 0, 255).astype(np.uint8)
    b = np.clip(b.astype(np.float32) - paper_b + 128, 0, 255).astype(np.uint8)
    return l, a, b


def to_original(image: np.ndarray) -> np.ndarray:
    return image.copy()


def _levels_stretch(channel: np.ndarray, low_p: float = 3.5, high_p: float = 96.5) -> np.ndarray:
    """Linear contrast stretch between the given percentiles — CLAHE alone
    is a local/adaptive enhancer and plateaus well short of a punchy
    "photo" look (measured against a real scanner app's Photo mode: CLAHE
    at any clip limit only reached ~30 std vs. their ~57); a global levels
    stretch is what actually gets there."""
    lo, hi = np.percentile(channel, [low_p, high_p])
    stretched = (channel.astype(np.float32) - lo) * (255.0 / max(hi - lo, 1.0))
    return np.clip(stretched, 0, 255).astype(np.uint8)


def to_photo(image: np.ndarray) -> np.ndarray:
    smoothed = cv2.bilateralFilter(image, d=5, sigmaColor=40, sigmaSpace=40)
    lab = cv2.cvtColor(smoothed, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = _levels_stretch(l)
    l = cv2.createCLAHE(clipLimit=_CLAHE_CLIP_LIMIT, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def _whiten_highlights(channel: np.ndarray, blend_start: int = 200, white_point: int = 245) -> np.ndarray:
    """Push already-bright pixels (paper background, bleed-through from the
    other side of the page) the rest of the way to pure 255, while leaving
    darker pixels (ink) untouched — matches a real scanner app's Docs/Clear
    background, which stays crystal white "no matter what shows through
    from the other side", not just brighter-than-before.

    A flat brightness add (the previous approach) raises everything
    equally and still tops out shy of true white; a plain white-point
    stretch does nothing once the brightest pixels are already near
    saturated. This instead ramps only the upper tone range smoothly (an
    smoothstep ease, so there's no visible seam) up to full white — text
    strokes, which sit well below blend_start, pass through unchanged.

    blend_start/white_point were originally 150/190 — found via a real
    ID-card photo with an embedded ID photo that paper and midtone
    photographic content (e.g. a face) occupy overlapping brightness
    ranges after illumination correction (both commonly sit in the 130-255
    range), so a wide catch band meant to grab "paper" was also steeply
    reshaping the embedded photo's own tonal gradient, visibly posterizing
    it into blotchy patches. Illumination correction already brings true
    paper close to white on its own (measured ~240 mean in a real sample);
    narrowing the band to only the pixels that are already very close to
    white leaves normal photographic midtones alone while still pushing
    genuine paper the rest of the way to pure white.
    """
    x = channel.astype(np.float32)
    t = np.clip((x - blend_start) / max(white_point - blend_start, 1), 0.0, 1.0)
    t = t * t * (3 - 2 * t)  # smoothstep: eases in/out instead of a sharp knee
    return np.clip(x + t * (255 - x), 0, 255).astype(np.uint8)


def _recover_faint_ink(channel: np.ndarray, strength: float = 1.0,
                       reference: np.ndarray | None = None) -> np.ndarray:
    """Re-ink real strokes that a bright light / reflection washed out to
    near-white, WITHOUT re-inking show-through from the far side of the
    page. Runs on an already illumination-corrected L (or gray) channel,
    before the highlight/shadow push; `reference` is that channel BEFORE
    illumination correction (used to locate the glare).

    A pixel's `deficit` = how much darker it is than its own local paper
    level (a big morphological close). Confident ink is `deficit` far
    below paper; a faint mark (small `deficit`) is the ambiguous case:
    faded ink under glare, or bleed-through. Three gates separate them,
    and a mark has to pass all three:

    1. It sits in a bright-light region. The whole reason a real stroke
       goes pale is a reflection near clipping; `reference`'s local paper
       level still shows where that fell. Ordinary paper, shadow, and
       (critically) back-page show-through on normally-lit paper are all
       outside it, so they're left alone.
    2. It belongs to a stroke that is confidently dark somewhere. A faded
       stroke crossing a glare patch is one connected mark with solid
       ends; an isolated show-through blob contains no confident ink and
       is dropped whole.
    3. Its edges are crisp. A real pen/print stroke keeps sharp edges
       even when pale; show-through has diffused through the fibres and
       is soft. High local Laplacian energy => ink.

    Everything else (paper, show-through, photographic midtones) is left
    for the normal pipeline.
    """
    if strength <= 0:
        return channel
    x = channel.astype(np.float32)
    local_paper = _background_map(channel).astype(np.float32)
    deficit = np.clip(local_paper - x, 0.0, None)

    confident_ink = (deficit > 50.0).astype(np.uint8)
    faint_band = (deficit > 7.0) & (deficit <= 50.0)

    # --- Gate 1: bright-light / glare region only ----------------------
    if reference is not None:
        ref_paper = _background_map(np.clip(reference, 0, 255).astype(np.uint8)).astype(np.float32)
        glare = np.clip((ref_paper - 220.0) / 22.0, 0.0, 1.0)
        if float(glare.max()) < 0.05:
            return channel  # nothing bright enough to be a washed-out reflection
    else:
        glare = np.ones_like(x)

    # --- Gate 2: connected to confident ink --------------------------
    mark = cv2.morphologyEx((deficit > 8.0).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    _, labels = cv2.connectedComponents(mark, connectivity=8)
    keep = np.unique(labels[confident_ink.astype(bool)])
    keep = keep[keep != 0]
    linked = np.isin(labels, keep).astype(np.float32)

    # --- Gate 3: crisp edges ----------------------------------------
    lap = np.abs(cv2.Laplacian(x, cv2.CV_32F, ksize=3))
    edge = cv2.GaussianBlur(lap, (0, 0), 1.4)
    edge_conf = np.clip((edge - 3.0) / 10.0, 0.0, 1.0)

    weight = faint_band.astype(np.float32) * linked * glare * (0.4 + 0.6 * edge_conf)
    weight = cv2.GaussianBlur(weight, (0, 0), 0.8)

    # ramp the shove in with deficit: a marginally-faint pixel barely
    # moves; a clearly-faded stroke gets pushed solidly into ink range
    ramp = np.clip((deficit - 7.0) / 12.0, 0.0, 1.0)
    pull = weight * ramp * strength * (deficit * 1.05 + 30.0)
    return np.clip(x - pull, 0.0, 255.0).astype(np.uint8)


def _darken_shadows(channel: np.ndarray, blend_start: int = 90, black_point: int = 40) -> np.ndarray:
    """Mirror of _whiten_highlights for the low end: push already-dark
    pixels (ink) the rest of the way toward pure black, smoothly, leaving
    paper-background tones untouched. Combined with _whiten_highlights
    this is what gives "Docs" its crisp, printed-document look — like
    text exported straight from a word processor to PDF — instead of the
    softer gray ink strokes a plain photo has.

    blend_start/black_point narrowed the same way and for the same reason
    as _whiten_highlights above (110/65 originally) — a real dark ink
    stroke lands well below even this narrower band, so text still goes
    fully black, but a photo's shadow-side skin tones no longer get
    caught and crushed into blotchy near-black patches.
    """
    x = channel.astype(np.float32)
    t = np.clip((blend_start - x) / max(blend_start - black_point, 1), 0.0, 1.0)
    t = t * t * (3 - 2 * t)  # smoothstep
    return np.clip(x - t * x, 0, 255).astype(np.uint8)


def _darken_background(image: np.ndarray, mask: np.ndarray, strength: float) -> np.ndarray:
    """Push pixels the subject mask calls background toward black,
    proportional to how confidently they're background — subject pixels
    (mask near 255) are left alone. Works on a single channel (L) or a
    full BGR image alike.

    Found necessary via a non-document photo (a phone lock-screen
    wallpaper) compared against a real scanner app's own output on the
    same photo: its background there measured near-black while its
    subject stayed bright, even though in the ORIGINAL photo the
    background region was measurably brighter than the subject — no
    global tone curve can do that (a monotonic brightness mapping can't
    reverse which of two regions is brighter), so matching it needs an
    actual subject/background split, not a smarter curve. See
    detector.get_subject_mask for where the mask itself comes from.

    Also protects background pixels by how bright THEY already are, not
    just by the mask — found via the same test image, whose background
    includes a status bar and app icons that are genuinely white UI
    elements, not part of the photographed scene. "Background" (outside
    the subject mask) isn't the same thing as "should go dark"; a bright
    background pixel should stay bright, only a dark/mid-tone one should
    get crushed toward black.
    """
    bg_weight = 1.0 - (mask.astype(np.float32) / 255.0)
    brightness = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    protect_bright = brightness.astype(np.float32) / 255.0
    bg_weight = bg_weight * (1.0 - protect_bright)
    if image.ndim == 3:
        bg_weight = bg_weight[..., np.newaxis]
    out = image.astype(np.float32) * (1.0 - bg_weight * strength)
    return np.clip(out, 0, 255).astype(image.dtype)


def _protect_subject(corrected: np.ndarray, pre_correction: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Blend `corrected` back toward `pre_correction` wherever `mask` calls
    the pixel subject rather than paper — only meant to run for a confirmed
    non-document photo (see to_docs's allow_background_crush note; this
    shares that same mask).

    _correct_illumination's divide-by-estimated-background assumes the
    background IS paper lighting to flatten toward white. Found broken via
    a real digital passport-style photo (a face filling most of the frame
    against a plain light backdrop, benchmarked against a real scanner
    app's own output on the identical photo): the morphological-close
    kernel that estimates "background" is sized to erase document TEXT
    strokes, far smaller than a face's own broad tonal structure, so on
    this photo it produced a "background" that was almost a copy of the
    face itself — dividing a channel by an estimate of itself pushes the
    result toward the scale ceiling regardless of the face's real tones.
    Measured on that photo: face-region median brightness went 170 (raw)
    to 249 (post illumination-correction), before CLAHE or the highlight/
    shadow push even ran — so the already-careful tuning downstream (see
    _whiten_highlights, _darken_shadows, narrowed for exactly this kind of
    photographic content) never got a chance to act on real face tones,
    since they were already blown out this early. Restoring the subject's
    pre-correction tones here, before CLAHE runs, lets that existing
    tuning treat it like the ordinary photographic content it already
    handles correctly elsewhere (e.g. a small embedded ID photo).
    """
    subject = mask.astype(np.float32) / 255.0
    blended = corrected.astype(np.float32) * (1 - subject) + pre_correction.astype(np.float32) * subject
    return np.clip(blended, 0, 255).astype(corrected.dtype)


def _unsharp(image: np.ndarray, amount: float = 0.4, sigma: float = 1.2) -> np.ndarray:
    """Unsharp mask: crisps edges without the grain/halo a much stronger
    pass would add. Works on grayscale or BGR (cv2 ops are channel-agnostic).
    """
    blurred = cv2.GaussianBlur(image, (0, 0), sigma)
    sharpened = image.astype(np.float32) + amount * (image.astype(np.float32) - blurred.astype(np.float32))
    return np.clip(sharpened, 0, 255).astype(np.uint8)


# If more than this fraction of the ML "subject" region reads as paper
# (bright + near-neutral), the mask isn't isolating a photographic subject
# — it's isolating document content, and the subject/background crush must
# not run. allow_background_crush is only a guess that this isn't a real
# document (it's set when corner detection fell back to the whole frame); a
# tightly-cropped photo of a genuine page trips that guess too, and there
# the segmentation model returns the text itself as the "subject". Crushing
# then re-introduces a grey shadow halo around the text (via _protect_subject
# restoring pre-correction tones) — the exact thing Docs/Clear exist to
# remove. Measured: a real face/photo subject reads ~0.03-0.08 paper-like,
# a handwriting-on-card "subject" reads ~0.73.
_SUBJECT_MASK_MAX_PAPER_FRAC = 0.4


def _subject_mask_for_crush(image: np.ndarray) -> np.ndarray | None:
    """detector.get_subject_mask, but returns None when the masked region is
    itself mostly paper — i.e. the caller's allow_background_crush guess was
    wrong and this is a real document. See _SUBJECT_MASK_MAX_PAPER_FRAC."""
    mask = detector.get_subject_mask(image)
    if mask is None:
        return None
    region = mask > 128
    if not region.any():
        return None
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    l, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.sqrt((a - 128) ** 2 + (b - 128) ** 2)
    paper_like = (l > 120) & (chroma < 15)
    if float(paper_like[region].mean()) > _SUBJECT_MASK_MAX_PAPER_FRAC:
        return None
    return mask


def _snap_paper_to_white(channel: np.ndarray, paper_confidence: float, mask: np.ndarray | None = None):
    """Final cleanup for a confident document: wipe everything that isn't
    real content the rest of the way to pure white, so a faint residual
    shade — or show-through from the far side of the page — lands on 255
    instead of the 248-254 the tone push leaves it at. Whether a pixel is
    content is judged locally, not by an absolute level: a pixel far below
    its own local paper estimate is kept (real ink sits ~200 below; even a
    faint printed-grey block is 60-150 below), while one within ~12-40 of
    local paper — clean paper, an anti-alias halo, show-through — is ramped
    to white.

    Returns (out, keep): `keep` is 1 where the pixel was left alone and 0
    where it was forced white; a colour caller applies the same ramp to A/B
    (see _snap_lab) so the wiped area goes neutral too. Scaled by
    paper_confidence so a non-document image is untouched, and held back
    over `mask` (a real photographic subject) where one was found.

    A pixel is only wiped when BOTH tests agree it's background: close to
    its local paper level AND already bright (>~195). The brightness test
    is what stops a soft subject-mask edge — or any mid-tone near content —
    from being pulled to white and leaving a pale halo; a genuine faint
    shade to remove has already been lifted past 195 by the tone push
    upstream.
    """
    local = _background_map(channel).astype(np.float32)
    ch = channel.astype(np.float32)

    below = local - ch
    keep_flat = np.clip((below - 12.0) / 28.0, 0.0, 1.0)
    keep_flat = keep_flat * keep_flat * (3 - 2 * keep_flat)  # smoothstep

    dark = np.clip((215.0 - ch) / 40.0, 0.0, 1.0)
    dark = dark * dark * (3 - 2 * dark)  # smoothstep: 1 where pixel is dark (<175), 0 where bright (>215)

    keep = np.maximum(keep_flat, dark)
    keep = 1.0 - paper_confidence * (1.0 - keep)
    if mask is not None:
        keep = np.maximum(keep, mask.astype(np.float32) / 255.0)
    out = ch * keep + 255.0 * (1.0 - keep)
    return np.clip(out, 0, 255).astype(np.uint8), keep


def _snap_lab(l: np.ndarray, a: np.ndarray, b: np.ndarray, paper_confidence: float, mask: np.ndarray | None = None):
    """_snap_paper_to_white on L, with the same ramp applied to A/B so a
    wiped-white area is also colour-neutral."""
    l, keep = _snap_paper_to_white(l, paper_confidence, mask)
    a = np.clip((a.astype(np.float32) - 128.0) * keep + 128.0, 0, 255).astype(np.uint8)
    b = np.clip((b.astype(np.float32) - 128.0) * keep + 128.0, 0, 255).astype(np.uint8)
    return l, a, b


def to_docs(image: np.ndarray, allow_background_crush: bool = False, recover_ink: bool = False) -> np.ndarray:
    """Document-optimized but still color: shadow-flattening AND color-cast
    removal, so the background actually reads as clean white rather than
    a brighter version of whatever tint the ambient light left on it, plus
    a highlight/shadow contrast push and unsharp so text reads crisp and
    printed — like a page exported straight from a word processor to PDF
    — rather than the softer tones a plain photo has.

    allow_background_crush must only be set by a caller that has confirmed
    this ISN'T a real scanned document (see main_window's fallback_used).
    Found necessary the hard way: the subject/background segmentation this
    enables (see _darken_background) exists for arbitrary non-document
    photos, but tried on an actual document it does real damage — a
    notebook page has no single "salient object" for the segmentation
    model to find, so it read the *entire page* as background and crushed
    the whole thing toward black; a photo ID card's segmentation instead
    confidently latched onto some small central region as "the subject"
    and vignette-darkened the real document content around it. Both looked
    like the feature working exactly as intended, just on the wrong photo.
    """
    confidence = _paper_confidence(image)
    smoothed = cv2.bilateralFilter(image, d=5, sigmaColor=40, sigmaSpace=40)
    lab = cv2.cvtColor(smoothed, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    pre_correction_l = l
    l = _correct_illumination(l, paper_confidence=confidence)
    # Computed once and reused below for _darken_background too — both are
    # gated on allow_background_crush (confirmed non-document photo) since
    # the ML segmentation behind it is the slow part of this pipeline; see
    # _protect_subject for why a photographic subject needs protecting
    # from the illumination correction just applied above.
    mask = _subject_mask_for_crush(image) if allow_background_crush else None
    if mask is not None:
        l = _protect_subject(l, pre_correction_l, mask)
    if recover_ink:
        l = _recover_faint_ink(l, strength=confidence, reference=pre_correction_l)
    l = cv2.createCLAHE(clipLimit=_CLAHE_CLIP_LIMIT, tileGridSize=(8, 8)).apply(l)
    # Same paper_confidence blend as _correct_illumination above, applied
    # to the highlight/shadow push too — on the systematic color-chart
    # test image this is what was actually collapsing a 13-step grayscale
    # ramp down to essentially just black-or-white.
    pushed = _darken_shadows(_whiten_highlights(l))
    l = np.clip(l.astype(np.float32) * (1 - confidence) + pushed.astype(np.float32) * confidence,
                0, 255).astype(np.uint8)
    if mask is not None:
        l = _darken_background(l, mask, _BG_CRUSH_DOCS)
    l = _unsharp(l, amount=1.3, sigma=1.0)
    l, a, b = _white_balance_lab(l, a, b)
    l, a, b = _snap_lab(l, a, b, confidence, mask)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def to_clear(image: np.ndarray, allow_background_crush: bool = False, recover_ink: bool = False) -> np.ndarray:
    """The flagship default: Docs processing, pushed further — Clear should
    read even crisper than Docs, not just a same-strength restyle, and
    (for a confirmed non-document photo) with its background crushed
    further still — see _BG_CRUSH_CLEAR_EXTRA and to_docs's
    allow_background_crush note.

    A second, wider-band highlight/shadow push on top of Docs' own is
    included even for real documents — found necessary because sharpening
    alone (the only thing that used to differ) reads as a subtle, easy-to-
    miss difference at normal preview size; toggling Docs/Clear needs to be
    obviously different on sight, the way a real scanner app's is."""
    confidence = _paper_confidence(image)
    docs = to_docs(image, allow_background_crush, recover_ink)
    lab = cv2.cvtColor(docs, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    pre_push_l = l
    pushed_l = _darken_shadows(_whiten_highlights(l, blend_start=188, white_point=238), blend_start=105, black_point=52)
    l = np.clip(l.astype(np.float32) * (1 - confidence) + pushed_l.astype(np.float32) * confidence,
                0, 255).astype(np.uint8)
    # This second, wider-band push needs the same subject protection as
    # to_docs's own — otherwise a photo protected in to_docs would still
    # get blown out here, just one step later (see _protect_subject).
    mask = _subject_mask_for_crush(image) if allow_background_crush else None
    if mask is not None:
        l = _protect_subject(l, pre_push_l, mask)
    pushed = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    sharpened = _unsharp(pushed, amount=0.6, sigma=1.0)
    if mask is not None:
        sharpened = _darken_background(sharpened, mask, _BG_CRUSH_CLEAR_EXTRA)
    # to_docs already snapped the background; the extra push + unsharp above
    # can leave 1-3 levels of haze back, so snap once more.
    l, a, b = cv2.split(cv2.cvtColor(sharpened, cv2.COLOR_BGR2LAB))
    l, a, b = _snap_lab(l, a, b, confidence, mask)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def to_original_bw(image: np.ndarray) -> np.ndarray:
    """Original, but monochrome: a plain grayscale copy, no enhancement."""
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def to_photo_bw(image: np.ndarray) -> np.ndarray:
    """Photo, but monochrome: light denoise + contrast, no shadow-flattening."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, d=5, sigmaColor=40, sigmaSpace=40)
    gray = _levels_stretch(gray)
    return cv2.createCLAHE(clipLimit=_CLAHE_CLIP_LIMIT, tileGridSize=(8, 8)).apply(gray)


def to_docs_bw(image: np.ndarray, allow_background_crush: bool = False, recover_ink: bool = False) -> np.ndarray:
    """Docs, but monochrome: shadow-flattened, highlight/shadow contrast
    pushed, and unsharped — crisp printed-page look, same as color Docs.
    See to_docs's allow_background_crush note — only set this for a
    confirmed non-document photo."""
    confidence = _paper_confidence(image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, d=5, sigmaColor=40, sigmaSpace=40)
    pre_correction_gray = gray
    gray = _correct_illumination(gray, paper_confidence=confidence)
    mask = _subject_mask_for_crush(image) if allow_background_crush else None
    if mask is not None:
        gray = _protect_subject(gray, pre_correction_gray, mask)
    if recover_ink:
        gray = _recover_faint_ink(gray, strength=confidence, reference=pre_correction_gray)
    gray = cv2.createCLAHE(clipLimit=_CLAHE_CLIP_LIMIT, tileGridSize=(8, 8)).apply(gray)
    pushed = _darken_shadows(_whiten_highlights(gray))
    gray = np.clip(gray.astype(np.float32) * (1 - confidence) + pushed.astype(np.float32) * confidence,
                    0, 255).astype(np.uint8)
    if mask is not None:
        gray = _darken_background(gray, mask, _BG_CRUSH_DOCS)
    gray = _unsharp(gray, amount=1.3, sigma=1.0)
    return _snap_paper_to_white(gray, confidence, mask)[0]


def to_clear_bw(image: np.ndarray, allow_background_crush: bool = False, recover_ink: bool = False) -> np.ndarray:
    """The flagship B&W: Docs pushed further still — mirrors to_clear,
    including its second, wider-band tonal push (see to_clear)."""
    confidence = _paper_confidence(image)
    docs = to_docs_bw(image, allow_background_crush, recover_ink)
    pushed = _darken_shadows(_whiten_highlights(docs, blend_start=188, white_point=238), blend_start=105, black_point=52)
    gray = np.clip(docs.astype(np.float32) * (1 - confidence) + pushed.astype(np.float32) * confidence,
                    0, 255).astype(np.uint8)
    mask = _subject_mask_for_crush(image) if allow_background_crush else None
    if mask is not None:
        gray = _protect_subject(gray, docs, mask)
    sharpened = _unsharp(gray, amount=0.6, sigma=1.0)
    if mask is not None:
        sharpened = _darken_background(sharpened, mask, _BG_CRUSH_CLEAR_EXTRA)
    return _snap_paper_to_white(sharpened, confidence, mask)[0]


# to_bw kept as an alias — it's the strongest/flagship B&W preset and a few
# call sites (older scripts, docs) still reference it by this name.
to_bw = to_clear_bw


def apply_enhancement(
    image: np.ndarray, brightness: int = 0, contrast: int = 0, saturation: int = 0
) -> np.ndarray:
    """Live brightness/contrast/saturation touch-up layered on top of a
    color-mode preset's output (the "Enhance" sliders). Deliberately kept
    separate from — and much cheaper than — the presets above: this runs on
    every slider tick while the user is dragging, so it does plain per-pixel
    arithmetic instead of illumination correction/CLAHE/unsharp.

    Contrast pivots around mid-gray (128) rather than 0, so pushing contrast
    up brightens highlights and darkens shadows symmetrically instead of
    just darkening the whole image. Saturation only applies to color images
    — a grayscale (B&W) page has no color channel to boost.
    """
    alpha = 1.0 + (contrast / 100.0) * 0.5  # contrast in [-100,100] -> alpha in [0.5, 1.5]
    beta = brightness * 0.8 + 128 * (1 - alpha)
    out = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)

    if saturation and out.ndim == 3:
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + saturation / 100.0), 0, 255)
        out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return out

_HANDLERS = {
    ("original", False): to_original,
    ("original", True): to_original_bw,
    ("photo", False): to_photo,
    ("photo", True): to_photo_bw,
    ("docs", False): to_docs,
    ("docs", True): to_docs_bw,
    ("clear", False): to_clear,
    ("clear", True): to_clear_bw,
}


def apply_filter(
    image: np.ndarray, mode: str = "clear", bw: bool = False,
    allow_background_crush: bool = False, recover_ink: bool = False
) -> np.ndarray:
    """Apply `mode` (see COLOR_MODES) in color, or its matching B&W
    rendering if `bw` is True — every mode has both (see module docstring).

    allow_background_crush and recover_ink only affect docs/clear (see
    to_docs) — pass them through as-is for those; Original/Photo have no
    such step, so they're simply ignored for them rather than raising.
    """
    handler = _HANDLERS.get((mode, bw))
    if handler is None:
        raise ValueError(f"Unknown filter mode: {mode!r} (expected one of {COLOR_MODES})")
    if mode in ("docs", "clear"):
        return handler(image, allow_background_crush, recover_ink)
    return handler(image)
