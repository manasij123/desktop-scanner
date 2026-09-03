# Desktop Scanner — web backend

A small FastAPI service that runs the **exact `clearscanner` desktop pipeline**
(OpenCV corner detection + perspective warp + the tuned filter presets +
Tesseract OCR) over HTTP, so the browser app at `../webapp` can render
server-side and get desktop-grade output instead of the on-device WebGL
approximation.

Stateless: the client keeps the original photo and re-sends it with every
request.

## Run

Nothing to do by hand for local dev — `cd webapp && npm run dev` starts this
server automatically (see `webapp/vite.config.js`) and the app auto-connects.

To run it on its own:

```sh
# from the repo root (so `import clearscanner` resolves)
python -m venv venv && venv/Scripts/activate      # or: source venv/bin/activate
pip install -r server/requirements.txt            # self-contained: FastAPI + the clearscanner core deps

uvicorn server.main:app --port 8000 --host 127.0.0.1
```

Use `--host 127.0.0.1` (not `0.0.0.0` / `localhost`): on Windows a client that
dials `localhost` tries IPv6 `::1` first and eats a ~2 s fallback per request.

(If you already have a venv for the desktop app, just add the three web
deps: `pip install fastapi "uvicorn[standard]" python-multipart`.)

Open <http://127.0.0.1:8000/docs> for the interactive API.

**OCR** needs a system Tesseract install (`/ocr` returns 503 without it) —
`winget install UB-Mannheim.TesseractOCR` on Windows, `apt install tesseract-ocr`
on Debian/Ubuntu. `eng` + `ben` language data ships in `clearscanner/assets/tessdata/`.

## Connect the web app

Local dev connects automatically. For a hosted build, bake the API URL in:

```sh
cd webapp && VITE_API_URL=https://scan-api.example.com npm run build
```

## Endpoints

| Method | Path       | Body (multipart)                                                             | Returns |
|--------|------------|------------------------------------------------------------------------------|---------|
| GET    | `/health`  | –                                                                          | `{ ok, ocr, modes }` |
| POST   | `/detect`  | `image`                                                                     | `{ corners:[[x,y]×4] 0..1, fallback, width, height }` |
| POST   | `/render`  | `image`, `corners` (JSON), `mode`, `bw`, `recover`, `sharpen`, `fallback`, `brightness`, `contrast`, `saturation`, `max_dim`, `quality` | `image/jpeg` |
| POST   | `/ocr`     | `image`, `lang`                                                             | `{ text }` |

## Config (env)

| var | default | |
|-----|---------|-|
| `DSC_ALLOW_ORIGINS` | `https://manasij123.github.io` | comma-separated CORS allow-list, or `*` |
| `DSC_MAX_CONCURRENCY` | `4` | cap on simultaneous CPU-bound requests |
| `DSC_MAX_UPLOAD_MB` | `20` | reject uploads above this |
| `DSC_CACHE_SCALE` | `1` | scales the decode/warp LRU sizes (lower on a small host) |

Drop `rembg` + `onnxruntime` from `requirements.txt` to skip ML document
segmentation (falls back to edge/brightness detection — lighter image, ~200 MB
less, no model download).

## Docker

The `Dockerfile` is at the **repo root** (build context = repo root):

```sh
docker build -t desktop-scanner-api .
docker run -p 8080:8080 -e DSC_ALLOW_ORIGINS='*' desktop-scanner-api
```

## Deploy

See [`DEPLOY.md`](DEPLOY.md) — Google Cloud Run (free tier), plus the frontend
`config.json` wiring.
