# Desktop Scanner web backend.  (kept at repo root so `gcloud run deploy
# --source .` and most PaaS pick it up; build context = repo root.)
#
# Local:
#   docker build -t desktop-scanner-api .
#   docker run -p 8080:8080 -e DSC_ALLOW_ORIGINS='*' desktop-scanner-api
#
# Deploy target: Google Cloud Run (see server/DEPLOY.md). Listens on $PORT
# (Cloud Run injects 8080); honours DSC_ALLOW_ORIGINS / DSC_MAX_CONCURRENCY /
# DSC_CACHE_SCALE.
FROM python:3.12-slim

# OpenCV (headless) runtime libs + Tesseract for /ocr
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    U2NET_HOME=/home/user/.u2net \
    XDG_CACHE_HOME=/home/user/.cache \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DSC_ALLOW_ORIGINS=https://manasij123.github.io \
    DSC_CACHE_SCALE=0.6

WORKDIR /app
COPY --chown=user:user server/requirements.txt server/requirements.txt
USER user
RUN pip install --no-cache-dir --user -r server/requirements.txt

# bake the u2netp segmentation model (~4 MB) into the image so a cold
# container's first request isn't a download. Before the source COPY so a
# code change doesn't re-run it.
RUN python -c "from rembg import new_session; new_session('u2netp')"

COPY --chown=user:user clearscanner/ clearscanner/
COPY --chown=user:user server/ server/

ENV TESSDATA_PREFIX=/app/clearscanner/assets/tessdata
EXPOSE 8080

# one worker: pipeline.py holds in-process caches, and cv2/numpy/onnx
# release the GIL so a single worker still overlaps requests. Concurrency
# is bounded in main.py (DSC_MAX_CONCURRENCY).
CMD ["sh", "-c", "exec uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
