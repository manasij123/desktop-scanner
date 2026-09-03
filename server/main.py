"""Desktop Scanner — web backend.

Exposes the exact `clearscanner` desktop pipeline over HTTP so the browser
app can render server-side (ClearScan-grade output) instead of the on-device
WebGL approximation.

    uvicorn server.main:app --port 8000 --host 127.0.0.1

(local dev starts this automatically via webapp/vite.config.js)

All endpoints take the ORIGINAL uploaded photo; the client keeps a copy and
re-sends it for every render so the server stays stateless.
"""
from __future__ import annotations

import json
import os
import threading

import anyio
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from server import pipeline

MAX_UPLOAD = int(os.environ.get("DSC_MAX_UPLOAD_MB", "20")) * 1024 * 1024

app = FastAPI(title="Desktop Scanner API", version="1.0")

# The static site is served from a different origin (GitHub Pages / vite dev).
# Defaults to the published site; override with
# DSC_ALLOW_ORIGINS="https://foo,https://bar"  (or "*" to allow any).
_origins = os.environ.get("DSC_ALLOW_ORIGINS", "https://manasij123.github.io")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _origins == "*" else [o.strip() for o in _origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    # cap concurrent CPU-bound work so one client (or a burst) can't pin a
    # small shared instance — extra requests queue on the threadpool.
    try:
        anyio.to_thread.current_default_thread_limiter().total_tokens = \
            int(os.environ.get("DSC_MAX_CONCURRENCY", "4"))
    except Exception:
        pass
    # load the ML segmentation model in the background so the first /detect
    # isn't a 20 s cold start
    threading.Thread(target=pipeline.detector_warm_up, daemon=True).start()


async def _read(file: UploadFile):
    """-> (img_key, bgr). The key feeds pipeline's decode / warp caches so a
    burst of preview renders on one photo doesn't re-decode + re-warp it."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "image too large")
    try:
        return pipeline.load_source(data)
    except Exception as exc:  # noqa: BLE001 — surface any decode failure as 400
        raise HTTPException(400, f"could not read image: {exc}") from exc


def _bool(v: str | bool) -> bool:
    return v is True or str(v).lower() in ("1", "true", "yes", "on")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "ocr": pipeline.ocr_available(), "modes": list(pipeline.MODES)}


@app.post("/detect")
async def detect(image: UploadFile):
    _key, bgr = await _read(image)
    return pipeline.detect(bgr)


@app.post("/render")
async def render(
    image: UploadFile,
    corners: str = Form(...),          # JSON: [[x,y],...] normalised 0..1
    mode: str = Form("clear"),
    bw: str = Form("false"),
    recover: str = Form("false"),
    sharpen: str = Form("false"),
    fallback: str = Form("false"),     # detection fell back -> allow bg crush
    brightness: int = Form(0),
    contrast: int = Form(0),
    saturation: int = Form(0),
    max_dim: int = Form(2600),
    quality: int = Form(92),           # 78-84 for a live preview, 92 to save
):
    key, bgr = await _read(image)
    try:
        quad = json.loads(corners)
        assert isinstance(quad, list) and len(quad) == 4
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"bad corners: {exc}") from exc

    try:
        out = pipeline.render(
            bgr, quad,
            mode=mode, bw=_bool(bw), recover=_bool(recover), sharpen=_bool(sharpen),
            allow_background_crush=_bool(fallback),
            brightness=brightness, contrast=contrast, saturation=saturation,
            max_dim=max(200, min(4000, int(max_dim))),
            img_key=key,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(pipeline.encode_jpeg(out, max(40, min(95, int(quality)))), media_type="image/jpeg")


@app.post("/ocr")
async def ocr(image: UploadFile, lang: str = Form("eng")):
    if not pipeline.ocr_available():
        raise HTTPException(503, "Tesseract is not installed on the server")
    _key, bgr = await _read(image)
    return {"text": pipeline.extract_text(bgr, lang=lang)}


# Serve the built web app from the same origin when it's bundled in (the
# self-host Docker image copies it to /app/webapp_dist). Mounted last so the
# API routes above win; a same-origin frontend means no CORS to configure.
_static = os.environ.get("DSC_STATIC_DIR", "webapp_dist")
if os.path.isdir(_static):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_static, html=True), name="site")
