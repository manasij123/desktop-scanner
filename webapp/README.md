# Desktop Scanner — web

A browser port of the scanner. Same workflow as the desktop app —
import → adjust the crop → pick a look → export a multi-page PDF.

**Two processing modes**, switched from the `On-device / Server` chip in the
top bar:

- **On-device** (default) — everything runs client-side in WebGL/JS. No
  upload, no install, works offline after the first load (`public/sw.js`).
  Fast, but the filter is a 2-pass GPU approximation of the desktop pipeline.
- **Server** — enter the URL of the FastAPI backend in [`../server`](../server).
  Detection, rendering and OCR then run through the **real `clearscanner`
  desktop pipeline** — output identical to the Windows app. The photo is
  uploaded to that server; nothing is stored (stateless).

## How it differs from the desktop build

| | Desktop (PySide6 + OpenCV) | Web (this) |
|---|---|---|
| Page detection | rembg / u2netp ML + Canny + Otsu | classic Sobel-extremes guess (`src/engine/detect.js`) |
| Warp + filters | ~50 CPU passes per tweak | **server mode:** the same code · **on-device:** two WebGL2 passes — warp → grade — sub-frame (`src/engine/`) |
| PDF export | img2pdf | dependency-free writer (`src/engine/pdfWriter.js`), always client-side |
| OCR | bundled Tesseract | **server mode:** the same · **on-device:** `tesseract.js` from a CDN on first use |
| Import | images + PDF pages | images only |
| Rotate | crop editor + page list | crop editor (`Re-crop` reopens it for any page) |

The GRADE fragment shader (`src/engine/shaders.js`) reuses the warped
texture's mip chain as a free multi-radius blur: a coarse LOD is the
paper-level background estimate, a mid LOD the local mean, a tight LOD the
unsharp reference — the same illumination-flatten / tone / local-contrast
/ snap-to-white recipe as `clearscanner/core/filters.py`, in one pass.

## Develop

```bash
cd webapp
npm install
npm run dev        # vite dev server
npm run build      # emits ../docs/app/  (committed; GitHub Pages serves it)
npm run preview    # serve the production build locally
```

`vite.config.js` sets `base: '/desktop-scanner/app/'` and builds straight
into `docs/app/`, so the existing Pages site picks it up with no extra
deploy step — it goes live at
`https://manasij123.github.io/desktop-scanner/app/`.

## Layout

| Path | What's there |
|---|---|
| `src/App.jsx` | the whole UI — landing, crop editor, preview workspace, page rail, export |
| `src/engine/pipeline.js` | `ScanEngine` — owns the WebGL2 context, warp → grade, `toBlob` |
| `src/engine/shaders.js` | the two GLSL ES 3.00 passes |
| `src/engine/detect.js` | fast classical corner guess for the crop editor |
| `src/engine/homography.js` | unit-square → quad projective solve |
| `src/engine/pdfWriter.js` | minimal multi-page JPEG-into-PDF writer |
| `src/engine/backend.js` | client for the FastAPI backend (server mode) |
| `src/styles/theme.css` | design system — the light "glass" dashboard, deliberately mirroring `clearscanner/ui/theme.py` + `backdrop.py` |
| `src/icons.jsx` | line-icon set matching `clearscanner/ui/icons.py` |
| `public/` | `sw.js` (offline cache), `manifest.webmanifest`, icons |

The UI is an **application shell**, not a landing page: a violet→magenta
icon rail, a header with the process title and a page-count ring, a
frosted `PAGES` panel, the crop/preview stage, and a 240px control panel
(scan style · colour · re-crop · sharpen · recover · fine-adjust · OCR ·
save · add) over a painted violet→cream backdrop — the same shape as the
desktop window.
