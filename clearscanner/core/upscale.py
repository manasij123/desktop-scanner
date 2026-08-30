"""On-device detail enhancement ("HD") via Real-ESRGAN general-x4v3.

A ~4.9 MB ONNX model, run on the onnxruntime the app already bundles for
rembg. It reconstructs real detail — a slightly soft phone photo of a page
comes out with genuinely crisp text — rather than just sharpening what's
there. It's 4x, so the input is capped and the output resized back to a
sensible working size; runs tiled so memory stays flat and progress can
be reported.

enhance() is CPU-bound and takes a few seconds — always call it from a
worker thread (see ui/scan_worker.HdWorker).
"""
import os
import threading

import cv2
import numpy as np

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "models", "realesr-general-x4v3.onnx")

SCALE = 4
_INPUT_CAP = 1100      # px, long side — a softer photo above this gains nothing from SR
_OUTPUT_CAP = 2600     # px, long side of the returned image
_TILE = 224            # SR input tile (before the model's 4x)
_OVERLAP = 16          # tile overlap, trimmed after — kills seams

_session = None
_session_lock = threading.Lock()


def is_available() -> bool:
    return os.path.exists(_MODEL_PATH)


def _get_session():
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is None:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 1)
            _session = ort.InferenceSession(
                os.path.abspath(_MODEL_PATH), sess_options=opts, providers=["CPUExecutionProvider"]
            )
    return _session


def _run_tile(session, rgb_tile: np.ndarray) -> np.ndarray:
    x = rgb_tile.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
    y = session.run(None, {session.get_inputs()[0].name: x})[0]
    y = np.clip(y[0].transpose(1, 2, 0), 0.0, 1.0) * 255.0
    return y.astype(np.uint8)


def enhance(bgr: np.ndarray, progress=None) -> np.ndarray:
    """Return a detail-enhanced copy of `bgr`. `progress`, if given, is
    called with a 0.0-1.0 fraction as tiles complete."""
    session = _get_session()

    h0, w0 = bgr.shape[:2]
    long0 = max(h0, w0)
    src = bgr
    if long0 > _INPUT_CAP:
        s = _INPUT_CAP / long0
        src = cv2.resize(bgr, (round(w0 * s), round(h0 * s)), interpolation=cv2.INTER_AREA)

    rgb = cv2.cvtColor(src, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    out = np.empty((h * SCALE, w * SCALE, 3), dtype=np.uint8)

    ys = list(range(0, h, _TILE))
    xs = list(range(0, w, _TILE))
    total = len(ys) * len(xs)
    done = 0
    for y in ys:
        for x in xs:
            y1 = max(0, y - _OVERLAP)
            x1 = max(0, x - _OVERLAP)
            y2 = min(h, y + _TILE + _OVERLAP)
            x2 = min(w, x + _TILE + _OVERLAP)
            up = _run_tile(session, rgb[y1:y2, x1:x2])

            # place the un-overlapped centre
            ty1 = (y - y1) * SCALE
            tx1 = (x - x1) * SCALE
            ph = min(_TILE, h - y) * SCALE
            pw = min(_TILE, w - x) * SCALE
            out[y * SCALE:y * SCALE + ph, x * SCALE:x * SCALE + pw] = up[ty1:ty1 + ph, tx1:tx1 + pw]

            done += 1
            if progress:
                progress(done / total)

    result = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)

    # bring it back to a working size — 2x the (capped) source is plenty
    target_long = min(_OUTPUT_CAP, max(h, w) * 2)
    cur_long = max(result.shape[:2])
    if cur_long > target_long:
        s = target_long / cur_long
        result = cv2.resize(
            result, (round(result.shape[1] * s), round(result.shape[0] * s)), interpolation=cv2.INTER_AREA
        )
    return result
