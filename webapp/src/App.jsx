import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ScanEngine, estimatePaperConfidence } from './engine/pipeline.js'
import { detectCorners } from './engine/detect.js'
import { buildPdf, readJpegInfo } from './engine/pdfWriter.js'
import * as backend from './engine/backend.js'
import { Icon } from './icons.jsx'

/* ---------------------------------------------------------------- constants */

const STYLES = [
  { id: 'original', label: 'Original', sw: 'sw-original', desc: 'As shot — no clean-up' },
  { id: 'photo', label: 'Photo', sw: 'sw-photo', desc: 'Gentle lift, keeps the look' },
  { id: 'docs', label: 'Docs', sw: 'sw-docs', desc: 'Clean white paper, natural text' },
  { id: 'clear', label: 'Clear', sw: 'sw-clear', desc: 'Max contrast — for a real document' },
]

// pick the default style from how document-like the source looks
function smartMode(conf, flat) {
  if (conf != null && conf < 0.25) return 'original'   // dark scene / colourful photo / screenshot
  if (flat || conf == null || conf >= 0.88) return 'clear'
  return 'docs'
}
const OCR_LANGS = [
  ['eng', 'English'],
  ['eng+ben', 'English + Bengali'],
]
const ACCEPT = 'image/png,image/jpeg,image/webp,image/bmp'
const PREVIEW_DIM = 1000  // px long side for a server preview render (speed)
const EXPORT_DIM = 2600   // px long side for the committed / exported page
const DEFAULT_OPTS = {
  mode: 'clear', bw: false, recover: false, sharpen: false,
  brightness: 0, contrast: 0, saturation: 0,
}
const EDGES = [
  [0, 1, 'h'], [1, 2, 'v'], [2, 3, 'h'], [3, 0, 'v'],
]

/* ------------------------------------------------------------------ helpers */

function fit(w, h, cap) {
  const s = Math.min(1, cap / Math.max(w, h))
  return [Math.max(1, Math.round(w * s)), Math.max(1, Math.round(h * s))]
}

// working-resolution ceiling for the source. A modern phone camera shoots
// 12–108 MP; decoding that full-res OOMs a low-RAM device, so cap harder there.
function srcCap() {
  const mem = navigator.deviceMemory || 0 // GB, Chromium only (undefined elsewhere)
  if (mem && mem <= 3) return 2000
  try { if (matchMedia('(pointer: coarse)').matches) return 2600 } catch { /* no matchMedia */ }
  return 3600
}

// Pull width/height straight from the file header — no decode, so we can ask
// createImageBitmap to decode *directly* to a downscaled bitmap and never
// hold the full-res image in memory.
async function imageSize(file) {
  try {
    const b = new Uint8Array(await file.slice(0, 1 << 20).arrayBuffer())
    const dv = new DataView(b.buffer)
    if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) // PNG
      return { w: dv.getUint32(16), h: dv.getUint32(20) }
    if (b[0] === 0x52 && b[1] === 0x49 && b[8] === 0x57 && b[9] === 0x45) { // WEBP (RIFF/WEBP)
      const f = String.fromCharCode(b[12], b[13], b[14], b[15])
      if (f === 'VP8 ') return { w: dv.getUint16(26, true) & 0x3fff, h: dv.getUint16(28, true) & 0x3fff }
      if (f === 'VP8L') { const n = dv.getUint32(21, true); return { w: (n & 0x3fff) + 1, h: ((n >> 14) & 0x3fff) + 1 } }
      if (f === 'VP8X') return {
        w: ((b[24] | (b[25] << 8) | (b[26] << 16)) & 0xffffff) + 1,
        h: ((b[27] | (b[28] << 8) | (b[29] << 16)) & 0xffffff) + 1,
      }
    }
    if (b[0] === 0xff && b[1] === 0xd8) { // JPEG — walk the marker segments to SOFn
      let i = 2
      while (i + 9 < b.length) {
        if (b[i] !== 0xff) { i++; continue }
        let m = b[i + 1]
        while (m === 0xff) { i++; m = b[i + 1] }
        if (m === 0xd8 || m === 0xd9 || (m >= 0xd0 && m <= 0xd7)) { i += 2; continue }
        if (m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc)
          return { h: (b[i + 5] << 8) | b[i + 6], w: (b[i + 7] << 8) | b[i + 8] }
        const len = (b[i + 2] << 8) | b[i + 3]
        if (len < 2) break
        i += 2 + len
      }
    }
  } catch { /* unknown format — fall back to a plain decode */ }
  return null
}

async function loadSource(file) {
  const cap = srcCap()
  const dim = await imageSize(file)
  let down = null
  if (dim && dim.w > 0 && dim.h > 0 && Math.max(dim.w, dim.h) > cap) {
    const s = cap / Math.max(dim.w, dim.h)
    down = { resizeWidth: Math.max(1, Math.round(dim.w * s)), resizeHeight: Math.max(1, Math.round(dim.h * s)), resizeQuality: 'medium' }
  }

  // 'from-image' so an EXIF-rotated phone photo comes out upright. Try the
  // decode-downscale first; degrade the options one step at a time, and only
  // fall back to a full-res decode if every downscaled attempt is rejected.
  let bmp = null
  const attempts = [
    { imageOrientation: 'from-image', ...(down || {}) },
    down && { imageOrientation: 'from-image', resizeWidth: down.resizeWidth, resizeHeight: down.resizeHeight },
    down && { ...down },
    down && { resizeWidth: down.resizeWidth, resizeHeight: down.resizeHeight },
    { imageOrientation: 'from-image' },
    {},
  ].filter(Boolean)
  for (const o of attempts) {
    try { bmp = await createImageBitmap(file, o); break } catch { /* next */ }
  }
  if (!bmp) throw new Error('Could not open that photo — it may be too large for this device')

  // Always hand the engine a <canvas>, never a raw ImageBitmap: the two upload
  // with opposite Y orientation under UNPACK_FLIP_Y, and rotate90() also yields
  // a canvas — one source type keeps the pipeline's flip handling correct.
  const [w, h] = fit(bmp.width, bmp.height, cap)
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  c.getContext('2d').drawImage(bmp, 0, 0, w, h)
  bmp.close?.()
  // `file` is only ever used for server uploads, and it's re-sent on every
  // render — a raw phone photo is 5-10 MB, so ship a compact JPEG of the
  // already-capped, EXIF-resolved canvas instead.
  const upload = await srcToFile(c)
  return { el: c, w, h, file: upload }
}

function srcToFile(canvas, q = 0.9) {
  return new Promise((res) =>
    canvas.toBlob((b) => res(new File([b], 'scan.jpg', { type: 'image/jpeg' })), 'image/jpeg', q))
}

/** Rotate a working source 90°. dir 1 = clockwise, -1 = counter-clockwise. */
function rotate90(src, dir) {
  const c = document.createElement('canvas')
  c.width = src.h
  c.height = src.w
  const ctx = c.getContext('2d')
  ctx.translate(c.width / 2, c.height / 2)
  ctx.rotate((dir * Math.PI) / 2)
  ctx.drawImage(src.el, -src.w / 2, -src.h / 2)
  return { el: c, w: c.width, h: c.height }
}

/** Rotate a normalized [TL,TR,BR,BL] quad to match a 90° image rotation. */
function rotateQuad(q, dir) {
  const p = dir === 1 ? q.map(([x, y]) => [1 - y, x]) : q.map(([x, y]) => [y, 1 - x])
  return dir === 1 ? [p[3], p[0], p[1], p[2]] : [p[1], p[2], p[3], p[0]]
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}

let _tess = null
function loadTesseract() {
  if (window.Tesseract) return Promise.resolve(window.Tesseract)
  if (_tess) return _tess
  _tess = new Promise((res, rej) => {
    const s = document.createElement('script')
    s.src = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js'
    s.onload = () => res(window.Tesseract)
    s.onerror = () => { _tess = null; rej(new Error('Could not reach the OCR engine')) }
    document.head.appendChild(s)
  })
  return _tess
}

let _n = 0
const uid = () => `${Date.now().toString(36)}-${(_n++).toString(36)}`

// the phone layout swaps the side-by-side editor for a gallery ⇄ page-editor flow
const onPhone = () => { try { return matchMedia('(max-width: 620px)').matches } catch { return false } }

/* ================================================================== APP */

export default function App() {
  const [stage, setStage] = useState('empty') // empty | crop | preview
  const [pages, setPages] = useState([])
  const [work, setWork] = useState(null)
  const [corners, setCorners] = useState(null)
  const [baseCorners, setBaseCorners] = useState(null)
  const [opts, setOpts] = useState(DEFAULT_OPTS)
  const [editingId, setEditingId] = useState(null)
  const [compare, setCompare] = useState(false)
  const [showAdjust, setShowAdjust] = useState(false)
  const [showOcr, setShowOcr] = useState(false)
  const [galleryOpen, setGalleryOpen] = useState(false)  // mobile: the multi-page grid
  const [docConf, setDocConf] = useState(null)   // 0..1 "looks like a document"
  const [hintOff, setHintOff] = useState(false)  // "not a document" banner dismissed

  const [ocrLang, setOcrLang] = useState('eng')
  const [ocrText, setOcrText] = useState('')
  const [ocrBusy, setOcrBusy] = useState(false)

  const [busy, setBusy] = useState(null)
  const [status, setStatus] = useState('Ready')
  const [toasts, setToasts] = useState([])
  const [dragOver, setDragOver] = useState(false)

  // ---- server (FastAPI backend) ----
  const [apiUrl, setApiUrl] = useState(backend.savedApiUrl)
  const [suggestedApi, setSuggestedApi] = useState('') // from config.json, offered in the modal
  const [serverInfo, setServerInfo] = useState(null) // { ok, ocr } | null
  const [checking, setChecking] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showConnHelp, setShowConnHelp] = useState(false)

  // ---- batch import (pick several photos -> one style dialog -> step through crop) ----
  const [showBatchDialog, setShowBatchDialog] = useState(false)
  const [batchPending, setBatchPending] = useState(null) // File[] awaiting the dialog
  const [batchInfo, setBatchInfo] = useState(null)       // { index, total } while a batch is running
  const [srvPreview, setSrvPreview] = useState(null) // object URL of the server-rendered preview
  const [srvBusy, setSrvBusy] = useState(false)
  const useServer = !!(serverInfo && serverInfo.ok && apiUrl)

  const glRef = useRef(null)
  const cropRef = useRef(null)
  const engineRef = useRef(null)
  const bgRef = useRef(null)
  const queueRef = useRef([])
  const batchRef = useRef(null)  // { border, mode, bw, index, total } while a batch is running
  const dragRef = useRef(null)
  const rafRef = useRef(0)
  const statusTimer = useRef(0)
  const grayRef = useRef(null)   // low-res luminance of the current source, for edge-snap

  /* small grayscale buffer of the source so the crop handles can snap to
     real document edges as you drag (like a phone scanner app) */
  useEffect(() => {
    if (!work?.el) { grayRef.current = null; return }
    try {
      const GW = Math.min(760, work.w)
      const s = GW / work.w
      const w = Math.max(2, Math.round(work.w * s))
      const h = Math.max(2, Math.round(work.h * s))
      const c = document.createElement('canvas')
      c.width = w; c.height = h
      const cx = c.getContext('2d', { willReadFrequently: true })
      cx.drawImage(work.el, 0, 0, w, h)
      const d = cx.getImageData(0, 0, w, h).data
      const g = new Float32Array(w * h)
      for (let i = 0, j = 0; j < g.length; i += 4, j++) g[j] = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]
      grayRef.current = { g, w, h }
    } catch { grayRef.current = null }
  }, [work])

  /* ---- toast / status ---- */
  const toast = useCallback((text, kind = '') => {
    const id = uid()
    setToasts((t) => [...t, { id, text, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3000)
  }, [])
  const say = useCallback((msg, sticky = false) => {
    setStatus(msg)
    clearTimeout(statusTimer.current)
    if (!sticky) statusTimer.current = setTimeout(() => setStatus('Ready'), 3500)
  }, [])

  /* ---- deploy-time config: the hosted backend URL to offer (opt-in) ---- */
  useEffect(() => {
    let dead = false
    backend.fetchRuntimeConfig().then((cfg) => {
      if (dead || !cfg.apiUrl) return
      setSuggestedApi(cfg.apiUrl)
      // only auto-select it if the deploy says so AND the user hasn't chosen
      if (cfg.serverDefault && backend.savedApiUrl() === '') setApiUrl(cfg.apiUrl)
    })
    return () => { dead = true }
  }, [])

  /* ---- server health (re-checked whenever the URL changes) ---- */
  useEffect(() => {
    let dead = false
    if (!apiUrl) { setServerInfo(null); return }
    setChecking(true)
    backend.checkHealth(apiUrl).then((info) => {
      if (dead) return
      setServerInfo(info)
      setChecking(false)
    })
    return () => { dead = true }
  }, [apiUrl])

  const applyApiUrl = useCallback((url) => {
    const clean = (url || '').trim().replace(/\/+$/, '')
    backend.persistApiUrl(clean)
    setApiUrl(clean)
  }, [])

  /* ---- engine ---- */
  const engine = useCallback(() => {
    if (!engineRef.current && glRef.current) {
      try {
        engineRef.current = new ScanEngine(glRef.current)
      } catch (e) {
        toast(e.message || 'WebGL2 is unavailable in this browser', 'error')
        return null
      }
    }
    return engineRef.current
  }, [toast])
  useEffect(() => () => engineRef.current?.dispose(), [])

  // A committed page keeps its compact JPEG (src.file); the heavy decoded
  // canvas (src.el) is dropped whenever nobody's editing and rebuilt on demand.
  // Otherwise every page pins a ~25 MB canvas and a few of them OOM a phone
  // (white screen) the moment the crop editor starts its redraw loop.
  const dropIdleSources = useCallback(() => {
    if (!onPhone()) return  // desktop has the headroom — keep page switching instant
    setPages((ps) => ps.map((x) => (x.src?.el ? { ...x, src: { ...x.src, el: null } } : x)))
  }, [])
  const showGallery = useCallback(() => { dropIdleSources(); setGalleryOpen(true) }, [dropIdleSources])

  /* ---- import ---- */
  const beginSource = useCallback(async (file) => {
    setGalleryOpen(false)
    dropIdleSources()  // free other pages' canvases before decoding a new one
    setBusy('Reading image…')
    try {
      const src = await loadSource(file)
      let quad = detectCorners(src.el, src.w, src.h)
      src.fallback = false
      src.flat = false
      let conf = estimatePaperConfidence(src.el, src.w, src.h)
      if (useServer) {
        setBusy('Finding the document…')
        const d = await backend.detect(apiUrl, src.file).catch(() => null)
        if (d && Array.isArray(d.corners)) {
          quad = d.corners
          src.fallback = !!d.fallback
          src.flat = !!d.flat
          if (typeof d.confidence === 'number') conf = d.confidence
        }
      }
      src.conf = conf
      const batch = batchRef.current
      const finalOpts = {
        ...DEFAULT_OPTS,
        mode: batch ? batch.mode : smartMode(conf, src.flat),
        bw: batch ? batch.bw : false,
        recover: false, sharpen: false, brightness: 0, contrast: 0, saturation: 0,
      }
      setWork(src)
      setCorners(quad)
      setBaseCorners(quad)
      setEditingId(null)
      setDocConf(conf)
      setHintOff(false)
      setSrvPreview((u) => { if (u) URL.revokeObjectURL(u); return null })
      setOpts(finalOpts)
      setShowAdjust(false)
      setShowOcr(false)

      if (batch && !batch.border) {
        // "Border adjustment" off: skip the review screen, commit the
        // detected crop straight away and move on to the next queued photo
        setStage('preview')
        say(`Adding page ${batch.index} of ${batch.total}…`, true)
        await commitBatchPage(src, quad, finalOpts)
        return
      }
      setStage('crop')
      say(batch
        ? `Page ${batch.index} of ${batch.total} — drag the corners, then confirm`
        : 'Drag the corners to match the page, then confirm', true)
    } catch (e) {
      toast(e.message || 'Could not open that image', 'error')
    } finally {
      setBusy(null)
    }
  }, [toast, say, useServer, apiUrl, dropIdleSources])

  const startFiles = useCallback((fileList) => {
    const files = [...fileList].filter((f) => f.type.startsWith('image/'))
    if (!files.length) { toast('Pick a PNG, JPEG or WebP image', 'error'); return }
    if (files.length > 1) {
      setBatchPending(files)
      setShowBatchDialog(true)
      return
    }
    batchRef.current = null
    setBatchInfo(null)
    queueRef.current = []
    beginSource(files[0])
  }, [toast, beginSource])

  const startBatch = useCallback((settings) => {
    const files = batchPending
    setShowBatchDialog(false)
    setBatchPending(null)
    if (!files || !files.length) return
    batchRef.current = { ...settings, index: 1, total: files.length }
    setBatchInfo({ index: 1, total: files.length })
    queueRef.current = files.slice(1)
    beginSource(files[0])
  }, [batchPending, beginSource])

  const nextQueued = useCallback(() => {
    const f = queueRef.current.shift()
    if (f) {
      if (batchRef.current) {
        batchRef.current = { ...batchRef.current, index: batchRef.current.index + 1 }
        setBatchInfo({ index: batchRef.current.index, total: batchRef.current.total })
      }
      beginSource(f)
      return true
    }
    if (batchRef.current) { batchRef.current = null; setBatchInfo(null) }
    return false
  }, [beginSource])

  const pickFiles = useCallback(() => {
    const inp = document.createElement('input')
    inp.type = 'file'
    inp.accept = ACCEPT
    inp.multiple = true
    inp.onchange = () => inp.files.length && startFiles(inp.files)
    inp.click()
  }, [startFiles])

  // phone: open the rear camera straight to a capture (falls back to a
  // normal file dialog on a desktop browser, which is fine)
  const captureFromCamera = useCallback(() => {
    const inp = document.createElement('input')
    inp.type = 'file'
    inp.accept = 'image/*'
    inp.capture = 'environment'
    inp.onchange = () => inp.files.length && startFiles(inp.files)
    inp.click()
  }, [startFiles])

  /* ---- crop editor ----
     The image is drawn inset by a margin inside the canvas so every corner
     of the photo — even one right at its edge — sits away from the canvas
     border and stays easy to grab. All corner coords stay normalised to
     the image (0..1); `cropGeom` maps image space <-> canvas pixels. */
  const cropGeom = useCallback(() => {
    const [iw, ih] = fit(work.w, work.h, 1300)
    const m = Math.round(Math.min(iw, ih) * 0.06)
    return { iw, ih, m, cw: iw + 2 * m, ch: ih + 2 * m }
  }, [work])

  const drawCrop = useCallback(() => {
    const cv = cropRef.current
    if (!cv || !work || !corners) return
    const { iw, ih, m, cw, ch } = cropGeom()
    if (cv.width !== cw || cv.height !== ch) { cv.width = cw; cv.height = ch }
    const ctx = cv.getContext('2d')
    ctx.clearRect(0, 0, cw, ch)
    ctx.drawImage(work.el, m, m, iw, ih)
    const P = corners.map(([x, y]) => [m + x * iw, m + y * ih])

    // dim only inside the photo but outside the quad
    ctx.save()
    ctx.beginPath()
    ctx.rect(m, m, iw, ih)
    ctx.moveTo(P[0][0], P[0][1])
    for (let i = 1; i < 4; i++) ctx.lineTo(P[i][0], P[i][1])
    ctx.closePath()
    ctx.fillStyle = 'rgba(47,47,92,0.44)'
    ctx.fill('evenodd')
    ctx.restore()

    const CROP = '#4ADE80'
    ctx.beginPath()
    ctx.moveTo(P[0][0], P[0][1])
    for (let i = 1; i < 4; i++) ctx.lineTo(P[i][0], P[i][1])
    ctx.closePath()
    ctx.lineJoin = 'round'
    ctx.strokeStyle = CROP
    ctx.lineWidth = 9
    ctx.stroke()

    for (const [a, b] of EDGES) {
      const mx = (P[a][0] + P[b][0]) / 2
      const my = (P[a][1] + P[b][1]) / 2
      ctx.fillStyle = CROP
      ctx.fillRect(mx - 8.5, my - 8.5, 17, 17)
      ctx.lineWidth = 3
      ctx.strokeStyle = '#fff'
      ctx.strokeRect(mx - 8.5, my - 8.5, 17, 17)
    }
    for (const [x, y] of P) {
      ctx.beginPath()
      ctx.arc(x, y, 11, 0, Math.PI * 2)
      ctx.fillStyle = CROP
      ctx.fill()
      ctx.lineWidth = 3.5
      ctx.strokeStyle = '#fff'
      ctx.stroke()
    }
  }, [work, corners, cropGeom])

  // coalesce the redraw to one per frame — a fast finger drag fires far more
  // pointermove events than the screen refreshes, and each redraw scales the
  // whole source image
  useEffect(() => {
    if (stage !== 'crop') return
    const id = requestAnimationFrame(drawCrop)
    return () => cancelAnimationFrame(id)
  }, [stage, drawCrop])

  const ptr = (e) => {
    const cv = cropRef.current
    const r = cv.getBoundingClientRect()
    const { iw, ih, m, cw, ch } = cropGeom()
    const cx = ((e.clientX - r.left) / r.width) * cw
    const cy = ((e.clientY - r.top) / r.height) * ch
    return [
      Math.max(0, Math.min(1, (cx - m) / iw)),
      Math.max(0, Math.min(1, (cy - m) / ih)),
    ]
  }
  const hit = (nx, ny) => {
    const cv = cropRef.current
    const r = cv.getBoundingClientRect()
    const { iw, ih, cw, ch } = cropGeom()
    const tx = (26 * cw) / (r.width * iw)
    const ty = (26 * ch) / (r.height * ih)
    for (let i = 0; i < 4; i++)
      if (Math.abs(corners[i][0] - nx) < tx && Math.abs(corners[i][1] - ny) < ty)
        return { kind: 'corner', idx: i }
    for (let i = 0; i < 4; i++) {
      const [a, b] = EDGES[i]
      const mx = (corners[a][0] + corners[b][0]) / 2
      const my = (corners[a][1] + corners[b][1]) / 2
      if (Math.abs(mx - nx) < tx && Math.abs(my - ny) < ty) return { kind: 'edge', idx: i }
    }
    return null
  }
  /* magnetic snap for a crop line dragged to `coord` (normalised).
     axis 'y' = a horizontal edge (span is the x range), 'x' = vertical.
     `ref` (optional) = the same line's position in the auto-detected quad.
     1. look for a real page BOUNDARY in the image near `coord` and lock to it
        — a boundary is one monotonic step between two regions of different
        brightness, spanning most of the edge, so a page of text lines inside
        the document doesn't pull the handle in.
     2. otherwise, if we're close to the auto-detected edge, ease onto that.
     3. otherwise free drag. */
  const snapLine = (axis, coord, span0, span1, ref) => {
    const G = grayRef.current
    if (G) {
      const { g, w, h } = G
      const along = axis === 'y' ? w : h
      const across = axis === 'y' ? h : w
      const posPix = coord * across
      const win = Math.max(6, Math.round(across * 0.03))
      const pad = Math.max(3, Math.round(across * 0.012))   // how far out to read each side
      const N = 22
      const offs = []
      let sgn = 0
      for (let k = 0; k < N; k++) {
        const t = span0 + (span1 - span0) * ((k + 0.5) / N)
        const a = Math.round(t * along)
        if (a < pad + 1 || a >= along - pad - 1) continue
        let bestG = 0, bestOff = null
        for (let o = -win; o <= win; o++) {
          const c = Math.round(posPix + o)
          if (c < pad + 1 || c >= across - pad - 1) continue
          const hi = axis === 'y' ? (c + 1) * w + a : c * w + (a + 1)
          const lo = axis === 'y' ? (c - 1) * w + a : c * w + (a - 1)
          const grad = Math.abs(g[hi] - g[lo])
          if (grad > bestG) { bestG = grad; bestOff = o }
        }
        if (bestOff == null || bestG < 20) continue
        // is it a STEP between two regions (a real boundary), not a thin line?
        const c = Math.round(posPix + bestOff)
        const outer = axis === 'y' ? (c - pad) * w + a : c * w + (a - pad)
        const inner = axis === 'y' ? (c + pad) * w + a : c * w + (a + pad)
        const diff = g[inner] - g[outer]
        if (Math.abs(diff) < 26) continue                   // both sides similar -> ignore (text, shading)
        offs.push(bestOff); sgn += Math.sign(diff)
      }
      if (offs.length >= N * 0.6 && Math.abs(sgn) >= offs.length * 0.7) {
        offs.sort((p, q) => p - q)
        const spread = offs[Math.floor(offs.length * 0.85)] - offs[Math.floor(offs.length * 0.15)]
        if (spread <= win * 0.55) return (posPix + offs[offs.length >> 1]) / across
      }
    }
    if (ref != null && Math.abs(coord - ref) < 0.02) return ref
    return coord
  }

  const onDown = (e) => {
    const h = hit(...ptr(e))
    if (!h) return
    dragRef.current = h
    cropRef.current.setPointerCapture(e.pointerId)
  }
  const onMove = (e) => {
    if (!dragRef.current) return
    const [nx, ny] = ptr(e)
    setCorners((prev) => {
      const q = prev.map((p) => [...p])
      const { kind, idx } = dragRef.current
      const B = baseCorners
      if (kind === 'corner') {
        // snap each axis to a nearby edge line through the horizontal / vertical neighbour
        const hN = [1, 0, 3, 2][idx], vN = [3, 2, 1, 0][idx]
        const sy = snapLine('y', ny, Math.min(nx, q[hN][0]), Math.max(nx, q[hN][0]), B?.[idx]?.[1])
        const sx = snapLine('x', nx, Math.min(ny, q[vN][1]), Math.max(ny, q[vN][1]), B?.[idx]?.[0])
        q[idx] = [sx, sy]
      } else {
        // Translate the edge (keep the offset between its two corners) rather
        // than snapping both to one shared coordinate — a perspective shot's
        // top/bottom edge is rarely level, and flattening it there would
        // undo the auto-detected skew every time this handle is touched.
        const [a, b, o] = EDGES[idx]
        if (o === 'h') {
          const rf = B ? (B[a][1] + B[b][1]) / 2 : null
          const target = snapLine('y', ny, Math.min(q[a][0], q[b][0]), Math.max(q[a][0], q[b][0]), rf)
          const dy = target - (q[a][1] + q[b][1]) / 2
          q[a][1] = Math.max(0, Math.min(1, q[a][1] + dy))
          q[b][1] = Math.max(0, Math.min(1, q[b][1] + dy))
        } else {
          const rf = B ? (B[a][0] + B[b][0]) / 2 : null
          const target = snapLine('x', nx, Math.min(q[a][1], q[b][1]), Math.max(q[a][1], q[b][1]), rf)
          const dx = target - (q[a][0] + q[b][0]) / 2
          q[a][0] = Math.max(0, Math.min(1, q[a][0] + dx))
          q[b][0] = Math.max(0, Math.min(1, q[b][0] + dx))
        }
      }
      return q
    })
  }
  const onUp = (e) => {
    dragRef.current = null
    try { cropRef.current.releasePointerCapture(e.pointerId) } catch { /* already released */ }
  }

  const rotateSource = async (dir) => {
    if (!work) return
    const rot = rotate90(work, dir)
    rot.fallback = work.fallback
    rot.flat = work.flat
    rot.conf = work.conf
    rot.file = await srcToFile(rot.el)  // keep .file in step with .el so a page can rehydrate from it
    setWork(rot)
    setCorners((c) => rotateQuad(c, dir))
    setBaseCorners((c) => rotateQuad(c, dir))
    // in the preview the WebGL engine holds the pre-rotation source; re-bind
    // it so the live render picks up the new orientation (server path re-uploads
    // rot.file on its own)
    if (!useServer) engineRef.current?.setSource(rot.el, rot.w, rot.h)
  }
  const resetCorners = () => setCorners(baseCorners)

  const confirmCrop = async () => {
    if (!work) return
    if (!useServer) {
      const eng = engine()
      if (!eng) return
      eng.setSource(work.el, work.w, work.h)
    }
    if (batchRef.current) {
      // batch import with "Border adjustment" on: confirming a page's crop
      // commits it immediately and steps straight to the next page's crop —
      // there's no per-page style screen since the batch dialog already set it
      await commitBatchPage(work, corners, opts)
      return
    }
    setStage('preview')
    say(editingId ? 'Adjust the look, then update the page' : 'Pick a look, then add the page')
  }

  /* ---- on-device preview render (WebGL) ---- */
  const renderPreview = useCallback(() => {
    const eng = engineRef.current
    if (useServer || !eng || stage !== 'preview' || !corners || galleryOpen) return
    eng.render(
      corners,
      compare
        ? { mode: 'original', bw: false, recover: false, sharpen: false, brightness: 0, contrast: 0, saturation: 0 }
        : opts,
    )
  }, [useServer, stage, corners, opts, compare, galleryOpen])

  const schedule = useCallback(() => {
    cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(renderPreview)
  }, [renderPreview])

  useEffect(() => { if (stage === 'preview') schedule() }, [stage, schedule])
  useEffect(() => {
    const onResize = () => (stage === 'crop' ? drawCrop() : stage === 'preview' && schedule())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [stage, drawCrop, schedule])

  /* ---- server preview render (debounced HTTP round-trip) ---- */
  useEffect(() => {
    if (!useServer || stage !== 'preview' || !work?.file || !corners || galleryOpen) return
    const o = compare ? { ...DEFAULT_OPTS, mode: 'original' } : opts
    const t = setTimeout(async () => {
      setSrvBusy(true)
      try {
        const blob = await backend.render(apiUrl, work.file, corners, o, {
          maxDim: PREVIEW_DIM, fallback: work.fallback, quality: 78,
        })
        setSrvPreview((prev) => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(blob) })
      } catch (e) {
        toast(e.message || 'Server render failed', 'error')
      } finally {
        setSrvBusy(false)
      }
    }, 320)
    return () => clearTimeout(t)
  }, [useServer, stage, work, corners, opts, compare, apiUrl, toast, galleryOpen])

  /* ---- commit / export ---- */
  const renderFinal = async (src, quad, o) => {
    if (useServer) {
      return backend.render(apiUrl, src.file, quad, o, { maxDim: EXPORT_DIM, fallback: src.fallback })
    }
    return engineRef.current.toBlob(quad, o)
  }

  const gradePage = async (src, quad, o) => {
    const blob = await renderFinal(src, quad, o)
    const bytes = new Uint8Array(await blob.arrayBuffer())
    const info = readJpegInfo(bytes)
    const eng = engineRef.current
    return {
      url: URL.createObjectURL(blob), bytes,
      w: info.width || eng?.canvas.width || 0, h: info.height || eng?.canvas.height || 0,
      components: info.components || 3,
      src, corners: quad, opts: o,
    }
  }

  // shared by both batch paths: "Border adjustment" off (called from beginSource
  // with the just-detected src/quad) and on (called from confirmCrop with the
  // user-adjusted work/corners) — grades the page, adds it, and steps to the
  // next queued photo, landing on the grid (phone) / last page (desktop) when done
  const commitBatchPage = async (src, quad, o) => {
    if (!useServer) {
      const eng = engine()
      if (eng) eng.setSource(src.el, src.w, src.h)
    }
    setBusy('Rendering page…')
    try {
      const pg = await gradePage(src, quad, o)
      const id = uid()
      const idx = batchRef.current?.index
      setPages((p) => [...p, { id, ...pg }])
      setEditingId(id)
      toast(idx ? `Added page ${idx}` : 'Added page', 'good')
      if (!nextQueued()) {
        if (onPhone()) showGallery()
        else { setStage('preview'); say('Batch imported — review the pages') }
      }
    } catch (e) {
      toast(e.message || 'Could not render that page', 'error')
      if (!nextQueued() && onPhone()) showGallery()
    } finally {
      setBusy(null)
    }
  }

  const addToDocument = async () => {
    setBusy('Rendering page…')
    try {
      const pg = await gradePage(work, corners, opts)
      const id = uid()
      setPages((p) => [...p, { id, ...pg }])
      setEditingId(id)
      say(`Added as page ${pages.length + 1}`)
      toast(`Added page ${pages.length + 1}`, 'good')
      if (!nextQueued() && onPhone()) showGallery()
    } catch (e) {
      toast(e.message || 'Could not render the page', 'error')
    } finally { setBusy(null) }
  }

  const updatePage = async () => {
    setBusy('Updating page…')
    try {
      const pg = await gradePage(work, corners, opts)
      setPages((p) => p.map((x) => {
        if (x.id !== editingId) return x
        URL.revokeObjectURL(x.url)
        return { ...x, ...pg }
      }))
      say('Page updated')
      toast('Page updated', 'good')
      // advance a multi-import if one's in progress, else fall back to the grid
      if (!nextQueued() && onPhone()) showGallery()
    } catch (e) {
      toast(e.message || 'Could not update the page', 'error')
    } finally { setBusy(null) }
  }

  const saveJpg = async () => {
    setBusy('Exporting…')
    try {
      downloadBlob(await renderFinal(work, corners, opts), 'scan.jpg')
      say('Saved scan.jpg')
    } catch (e) { toast(e.message || 'Export failed', 'error') }
    finally { setBusy(null) }
  }

  const exportPdf = () => {
    if (!pages.length) return
    try {
      const blob = buildPdf(pages.map((p) => ({ bytes: p.bytes, width: p.w, height: p.h, components: p.components })))
      downloadBlob(blob, 'document.pdf')
      say(`Exported ${pages.length} page${pages.length > 1 ? 's' : ''} to document.pdf`)
      toast('PDF exported', 'good')
    } catch (e) { toast(e.message || 'Could not build the PDF', 'error') }
  }

  const printDoc = () => {
    if (!pages.length) return
    const w = window.open('', '_blank')
    if (!w) { toast('Allow pop-ups to print', 'error'); return }
    const imgs = pages.map((p) => `<img src="${p.url}" style="width:100%;page-break-after:always;display:block">`).join('')
    w.document.write(`<title>Desktop Scanner</title><style>@page{margin:12mm}body{margin:0}</style>${imgs}<script>onload=()=>{print();setTimeout(close,300)}<\/script>`)
    w.document.close()
  }

  /* ---- page list ---- */
  const openPage = async (pg) => {
    let src = pg.src
    if (!src?.el) {
      setBusy('Loading page…')
      try {
        const re = await loadSource(src.file)
        src = { ...src, el: re.el, w: re.w, h: re.h, file: re.file }
        setPages((ps) => ps.map((x) => (x.id === pg.id ? { ...x, src } : x)))
      } catch {
        toast('Could not reopen that page', 'error'); setBusy(null); return
      }
      setBusy(null)
    }
    if (!useServer) {
      const eng = engine()
      if (!eng) return
      eng.setSource(src.el, src.w, src.h)
    }
    setWork(src)
    setCorners(pg.corners)
    setBaseCorners(pg.corners)
    setOpts(pg.opts)
    setEditingId(pg.id)
    setDocConf(src.conf ?? null)
    setHintOff(true)  // already committed — don't nag when re-styling
    setShowAdjust(false)
    setShowOcr(false)
    setOcrText('')
    setSrvPreview((u) => { if (u) URL.revokeObjectURL(u); return null })
    setStage('preview')
    say(`Viewing page ${pages.findIndex((p) => p.id === pg.id) + 1} — change the look to update it`)
  }

  const removePage = (id) => {
    const idx = pages.findIndex((x) => x.id === id)
    if (idx < 0) return
    URL.revokeObjectURL(pages[idx].url)
    const next = pages.filter((x) => x.id !== id)
    setPages(next)
    say('Page removed')
    if (!next.length) { setGalleryOpen(false); setEditingId(null); setStage('empty'); setWork(null); setCorners(null) }
    else if (editingId === id && !galleryOpen) openPage(next[Math.min(idx, next.length - 1)])
    else if (editingId === id) setEditingId(null)
  }

  const movePage = (from, to) => setPages((p) => {
    if (to < 0 || to >= p.length) return p
    const n = [...p]
    const [it] = n.splice(from, 1)
    n.splice(to, 0, it)
    return n
  })

  /* ---- OCR ---- */
  const runOcr = async () => {
    if (ocrBusy || !corners) return
    setOcrBusy(true)
    setOcrText('')
    try {
      if (useServer) {
        if (serverInfo && serverInfo.ocr === false) throw new Error('Tesseract is not installed on the server')
        setBusy('Rendering page for OCR…')
        const page = await backend.render(apiUrl, work.file, corners, { ...opts, bw: true }, {
          maxDim: EXPORT_DIM, fallback: work.fallback,
        })
        setBusy('Reading text…')
        setOcrText((await backend.ocr(apiUrl, page, ocrLang)).trim() || '(no text found)')
      } else {
        setBusy('Loading OCR…')
        const T = await loadTesseract()
        const blob = await engineRef.current.toBlob(corners, { ...opts, bw: true }, 0.95)
        setBusy('Reading text…')
        const { data } = await T.recognize(blob, ocrLang, {
          logger: (m) => m.status === 'recognizing text' && setBusy(`Reading text… ${Math.round(m.progress * 100)}%`),
        })
        setOcrText(data.text.trim() || '(no text found)')
      }
      say('Text extracted')
    } catch (e) { toast(e.message || 'OCR failed', 'error') }
    finally { setOcrBusy(false); setBusy(null) }
  }

  /* ---- drag & drop anywhere ---- */
  useEffect(() => {
    const stop = (e) => { e.preventDefault(); e.stopPropagation() }
    const onDrop = (e) => { stop(e); setDragOver(false); if (e.dataTransfer?.files?.length) startFiles(e.dataTransfer.files) }
    const onOver = (e) => { stop(e); setDragOver(true) }
    const onLeave = (e) => { stop(e); if (e.relatedTarget === null) setDragOver(false) }
    window.addEventListener('dragover', onOver)
    window.addEventListener('drop', onDrop)
    window.addEventListener('dragleave', onLeave)
    return () => {
      window.removeEventListener('dragover', onOver)
      window.removeEventListener('drop', onDrop)
      window.removeEventListener('dragleave', onLeave)
    }
  }, [startFiles])

  /* ---- backdrop parallax ---- */
  useEffect(() => {
    let raf = 0
    const onMove = (e) => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const x = (e.clientX / window.innerWidth - 0.5) * -16
        const y = (e.clientY / window.innerHeight - 0.5) * -16
        if (bgRef.current) bgRef.current.style.transform = `translate(${x}px, ${y}px)`
      })
    }
    window.addEventListener('mousemove', onMove)
    return () => { window.removeEventListener('mousemove', onMove); cancelAnimationFrame(raf) }
  }, [])

  /* ---- derived ---- */
  const activeIdx = editingId ? pages.findIndex((p) => p.id === editingId) : -1
  const recoverable = opts.mode === 'docs' || opts.mode === 'clear'
  const title = useMemo(() => {
    if (stage === 'crop') {
      if (batchInfo) return [`Page ${batchInfo.index} of ${batchInfo.total}`, 'Drag the corners to match the page, then confirm']
      return ['Adjust the edges', 'Drag the corners to match the document, then confirm']
    }
    if (stage === 'preview') {
      if (batchInfo) return [`Page ${batchInfo.index} of ${batchInfo.total}`, 'Rendering this batch page…']
      return editingId && activeIdx >= 0
        ? ['Review & export', `Page ${activeIdx + 1} of ${pages.length} — tune the look, then update`]
        : ['Review & export', 'Pick a look and fine-tune, then add the page to your document']
    }
    return ['Add a document', 'Drop a photo anywhere, or use the photo / camera buttons to start']
  }, [stage, editingId, activeIdx, pages.length, batchInfo])

  /* ================================================================ render */

  return (
    <div id="app">
      <div className="backdrop" ref={bgRef} />

      <nav className="rail">
        <div className="rail-logo">
          <img src={`${import.meta.env.BASE_URL}logo.png`} alt="Desktop Scanner" />
        </div>
        <button className="rail-btn primary" title="Add from photos" onClick={pickFiles}>
          <Icon name="image" size={19} />
        </button>
        <button className="rail-btn" title="Take a photo" onClick={captureFromCamera}>
          <Icon name="camera" size={19} />
        </button>
        <div className="rail-spacer" />
        <button
          className="rail-btn"
          title="About"
          onClick={() => toast('Desktop Scanner — runs entirely in your browser')}
        >
          <Icon name="info" size={19} />
        </button>
      </nav>

      <div className="shell">
        <header className={`topbar${pages.length > 0 && stage === 'preview' && !galleryOpen ? ' has-back' : ''}`}>
          {pages.length > 0 && stage === 'preview' && !galleryOpen && (
            <button className="topbar-back" onClick={showGallery} title="Back to pages">
              <Icon name="chevron-left" size={20} />
            </button>
          )}
          <div className="titles">
            <span className="page-title">{title[0]}</span>
            <span className="page-sub">{title[1]}</span>
          </div>
          <div className="topbar-logo" aria-hidden="true">
            <img src={`${import.meta.env.BASE_URL}logo.png`} alt="" />
          </div>
          <div className="topbar-spacer" />
          {stage === 'preview' && (
            <div className="topbar-actions">
              <button className="btn ghost" onClick={saveJpg} title="Save a JPG copy">
                <Icon name="download" size={15} /> <span className="hide-sm">Save </span>JPG
              </button>
              {editingId
                ? <button className="btn primary glow" onClick={updatePage} title="Update this page">
                    <Icon name="check" size={15} /> Update
                  </button>
                : <button className="btn primary glow" onClick={addToDocument} title="Add to document">
                    <Icon name="plus" size={15} /> Add
                  </button>}
            </div>
          )}
          <button
            className={`srv-chip${useServer ? ' on' : ''}`}
            onClick={() => setShowSettings(true)}
            title={useServer ? `Rendering on ${apiUrl}` : 'Rendering on this device — click to connect a server'}
          >
            <span className="srv-dot" />
            {checking ? 'Checking…' : useServer ? 'Server' : 'On-device'}
          </button>
          {(pages.length > 0 || busy) && (
            <div className="ring-wrap">
              <Ring value={pages.length / 8} num={pages.length} spinning={!!busy} />
              <span className="ring-cap">{busy ? 'WORKING' : 'PAGES'}</span>
            </div>
          )}
          <button className="btn ghost" onClick={printDoc} disabled={!pages.length} title="Print">
            <Icon name="print" size={16} /> <span className="hide-sm">Print</span>
          </button>
          <button className="btn primary glow" onClick={exportPdf} disabled={!pages.length} title="Export PDF">
            <Icon name="download" size={16} /> <span className="hide-sm">Export </span>PDF
            {pages.length > 0 && <span className="btn-count">({pages.length})</span>}
          </button>
        </header>

        <div className="hairline" />

        <div className="work">
          <PageList
            pages={pages}
            editingId={editingId}
            onOpen={openPage}
            onRemove={removePage}
            onMove={movePage}
            onAdd={pickFiles}
          />

          <div className="stage">
            {/* preview card is always mounted so the WebGL context survives
                a trip through the crop editor */}
            <div className="stage-main" hidden={stage !== 'preview'}>
              <div className="card">
                <canvas ref={glRef} id="glCanvas" className="preview" hidden={useServer} />
                {useServer && srvPreview && (
                  <img src={srvPreview} className="preview" alt="scan preview" />
                )}
                {stage === 'preview' && (busy || srvBusy || (useServer && !srvPreview)) && (
                  <div className="veil">
                    <div className="spinner" />
                    {busy || (useServer ? 'Rendering on the server…' : 'Working…')}
                  </div>
                )}
              </div>
            </div>

            {stage === 'empty' && (
              <div
                className={`dropcard${dragOver ? ' over' : ''}`}
                onClick={pickFiles}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && pickFiles()}
              >
                <div className="dropcard-ring"><Icon name="image" size={24} /></div>
                <b>Drop a photo of a page</b>
                <span>JPEG, PNG or WebP · {useServer ? 'rendered on the connected server' : 'stays on this device'}</span>
              </div>
            )}

            {stage === 'crop' && (
              <div className="stage-main">
                <div className="card">
                  <canvas
                    ref={cropRef}
                    className="cropper"
                    onPointerDown={onDown}
                    onPointerMove={onMove}
                    onPointerUp={onUp}
                    onPointerCancel={onUp}
                  />
                  {busy && <div className="veil"><div className="spinner" />{busy}</div>}
                </div>
                <div className="cropbar">
                  <button className="btn ghost sm" onClick={resetCorners} title="Reset to auto-detect">
                    <Icon name="reset" size={15} /> <span className="hide-sm">Reset to auto-detect</span>
                  </button>
                  <div className="cropbar-spacer" />
                  <button className="iconbtn" title="Rotate left" onClick={() => rotateSource(-1)}>
                    <Icon name="rotate-left" size={17} />
                  </button>
                  <button className="iconbtn" title="Rotate right" onClick={() => rotateSource(1)}>
                    <Icon name="rotate-right" size={17} />
                  </button>
                  <button className="iconbtn primary" title="Confirm crop" onClick={confirmCrop}>
                    <Icon name="check" size={22} />
                  </button>
                </div>
              </div>
            )}

            {stage === 'preview' && (
              <>

                <aside className="controls">
                  <div className="ctl-styles">
                  {docConf != null && docConf < 0.3 && !hintOff && (
                    <div className="doc-hint">
                      <div className="doc-hint-row">
                        <Icon name="info" size={14} />
                        <span>This doesn't look like a document.</span>
                        <button className="doc-hint-x" onClick={() => setHintOff(true)} title="Dismiss">
                          <Icon name="x" size={12} />
                        </button>
                      </div>
                      <div className="doc-hint-btns">
                        <button className="btn ghost sm" onClick={() => setOpts((o) => ({ ...o, mode: 'photo' }))}>
                          Use Photo
                        </button>
                        <button className="btn ghost sm" onClick={() => setOpts((o) => ({ ...o, mode: 'original' }))}>
                          Use Original
                        </button>
                      </div>
                    </div>
                  )}

                  <span className="seclabel">Scan style</span>
                  <div className="segmented vertical">
                    {STYLES.map((s) => (
                      <button
                        key={s.id}
                        className={`seg-btn${opts.mode === s.id ? ' active' : ''}`}
                        title={s.desc}
                        onClick={() => setOpts((o) => ({ ...o, mode: s.id }))}
                      >
                        <span className={`seg-swatch ${s.sw}`} />
                        {s.label}
                      </button>
                    ))}
                  </div>
                  <span className="mode-desc">{STYLES.find((s) => s.id === opts.mode)?.desc}</span>

                  <span className="seclabel">Colour</span>
                  <div className="pilltoggle">
                    <button
                      className={`pill-opt${!opts.bw ? ' active' : ''}`}
                      onClick={() => setOpts((o) => ({ ...o, bw: false }))}
                    >
                      Colour
                    </button>
                    <button
                      className={`pill-opt${opts.bw ? ' active' : ''}`}
                      onClick={() => setOpts((o) => ({ ...o, bw: true }))}
                    >
                      B&amp;W
                    </button>
                  </div>
                  </div>

                  <div className="ctl-tools">
                  <div className="hairline mob-hide" />

                  <span className="seclabel">Tools</span>
                  <div className="ctl-ribbon">
                    <div className="ctl-rotate">
                      <button className="ctl-btn" onClick={() => rotateSource(-1)} title="Rotate left">
                        <Icon name="rotate-left" size={16} /> <span>Left</span>
                      </button>
                      <button className="ctl-btn" onClick={() => rotateSource(1)} title="Rotate right">
                        <Icon name="rotate-right" size={16} /> <span>Right</span>
                      </button>
                    </div>

                    <button className="ctl-btn" onClick={() => setStage('crop')} title="Re-crop">
                      <Icon name="crop" size={16} /> <span>Re-crop</span>
                    </button>
                    <button
                      className={`ctl-btn${opts.sharpen ? ' active' : ''}`}
                      onClick={() => setOpts((o) => ({ ...o, sharpen: !o.sharpen }))}
                      title="Crisp up slightly soft text and lines"
                    >
                      <Icon name="sparkle" size={16} /> <span>Sharpen</span>
                      {opts.sharpen && <Icon name="check" size={15} className="ctl-check" />}
                    </button>
                    <button
                      className={`ctl-btn${opts.recover ? ' active' : ''}`}
                      disabled={!recoverable}
                      onClick={() => setOpts((o) => ({ ...o, recover: !o.recover }))}
                      title={recoverable ? 'Re-ink strokes a glare washed out (Docs / Clear)' : 'Switch to Docs or Clear first'}
                    >
                      <Icon name="text" size={16} /> <span>Recover</span>
                      {opts.recover && recoverable && <Icon name="check" size={15} className="ctl-check" />}
                    </button>
                    <button
                      className={`ctl-btn${showAdjust ? ' active' : ''}`}
                      onClick={() => { setShowAdjust((s) => !s); setShowOcr(false) }}
                      title="Brightness, contrast, saturation"
                    >
                      <Icon name="sliders" size={16} /> <span>Fine adjust</span>
                      {showAdjust && <Icon name="check" size={15} className="ctl-check" />}
                    </button>
                    <button
                      className={`ctl-btn${showOcr ? ' active' : ''}`}
                      onClick={() => { setShowOcr((s) => !s); setShowAdjust(false) }}
                      title="Extract text (OCR)"
                    >
                      <Icon name="text" size={16} /> <span>OCR</span>
                      {showOcr && <Icon name="check" size={15} className="ctl-check" />}
                    </button>
                  </div>

                  {showAdjust && (
                    <>
                      <div className="sheet-scrim" onClick={() => setShowAdjust(false)} />
                      <div className="ctl-sheet">
                        <div className="sheet-head">
                          <span className="sheet-grip" />
                          <div className="sheet-head-actions">
                            <button
                              className="iconbtn sm"
                              title="Reset adjustments"
                              onClick={() => setOpts((o) => ({ ...o, brightness: 0, contrast: 0, saturation: 0 }))}
                            >
                              <Icon name="reset" size={13} />
                            </button>
                            <button className="iconbtn sm" title="Done" onClick={() => setShowAdjust(false)}>
                              <Icon name="x" size={13} />
                            </button>
                          </div>
                        </div>
                        <Slider label="Brightness" value={opts.brightness} onChange={(v) => setOpts((o) => ({ ...o, brightness: v }))} />
                        <Slider label="Contrast" value={opts.contrast} onChange={(v) => setOpts((o) => ({ ...o, contrast: v }))} />
                        {!opts.bw && (
                          <Slider label="Saturation" value={opts.saturation} onChange={(v) => setOpts((o) => ({ ...o, saturation: v }))} />
                        )}
                      </div>
                    </>
                  )}

                  {showOcr && (
                    <>
                      <div className="sheet-scrim" onClick={() => setShowOcr(false)} />
                      <div className="ctl-sheet">
                        <div className="sheet-head">
                          <span className="sheet-grip" />
                          <div className="sheet-head-actions">
                            <button className="iconbtn sm" title="Done" onClick={() => setShowOcr(false)}>
                              <Icon name="x" size={13} />
                            </button>
                          </div>
                        </div>
                        <select className="ocr-select" value={ocrLang} onChange={(e) => setOcrLang(e.target.value)}>
                          {OCR_LANGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                        <button className="btn primary block" onClick={runOcr} disabled={ocrBusy}>
                          <Icon name="text" size={15} /> {ocrBusy ? 'Reading…' : 'Extract text'}
                        </button>
                        {ocrText && (
                          <>
                            <div className="ocr-out">{ocrText}</div>
                            <button
                              className="btn ghost sm block"
                              onClick={() => { navigator.clipboard?.writeText(ocrText); toast('Copied', 'good') }}
                            >
                              <Icon name="download" size={13} /> Copy text
                            </button>
                          </>
                        )}
                      </div>
                    </>
                  )}

                  </div>

                  <div className="ctl-actions">
                    <label className="compare-chk">
                      <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
                      Compare with original
                    </label>
                    <button className="btn ghost block" onClick={saveJpg}>
                      <Icon name="download" size={15} /> Save copy (JPG)
                    </button>
                    {editingId
                      ? <button className="btn primary block glow" onClick={updatePage}><Icon name="check" size={16} /> Update page</button>
                      : <button className="btn primary block glow" onClick={addToDocument}><Icon name="plus" size={16} /> Add to document</button>}
                  </div>
                </aside>
              </>
            )}
          </div>
        </div>

        <div className="statusbar">
          <span className={`dot${busy ? ' busy' : ''}`} />
          <span className="sb-msg">{busy || status}</span>
          <span className="statusbar-spacer" />
          {checking ? (
            <span className="srv-stat">checking server…</span>
          ) : useServer ? (
            <span className="srv-stat ok">server · connected</span>
          ) : (
            <button
              className="srv-stat bad"
              onClick={() => setShowConnHelp(true)}
              title="How to connect a server"
            >
              server · not connected
              <span className="srv-stat-i"><Icon name="info" size={11} /></span>
            </button>
          )}
        </div>
      </div>

      {galleryOpen && pages.length > 0 && (
        <MobileGallery
          pages={pages}
          onOpen={(pg) => { setGalleryOpen(false); openPage(pg) }}
          onRemove={removePage}
          onMove={movePage}
          onExport={exportPdf}
          onAddPhoto={pickFiles}
          onCamera={captureFromCamera}
        />
      )}

      {showSettings && (
        <ServerSettings
          apiUrl={apiUrl}
          suggested={suggestedApi}
          info={serverInfo}
          checking={checking}
          onApply={applyApiUrl}
          onClose={() => setShowSettings(false)}
        />
      )}

      {showConnHelp && (
        <ConnectHelp
          onOpenSettings={() => { setShowConnHelp(false); setShowSettings(true) }}
          onClose={() => setShowConnHelp(false)}
        />
      )}

      {showBatchDialog && batchPending && (
        <BatchDialog
          count={batchPending.length}
          onCancel={() => { setShowBatchDialog(false); setBatchPending(null) }}
          onStart={startBatch}
        />
      )}

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.kind === 'good' && <Icon name="check" size={14} />}
            {t.kind === 'error' && <Icon name="x" size={14} />}
            {t.text}
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---- "how do I connect a server" helper ---- */
function ConnectHelp({ onOpenSettings, onClose }) {
  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <b>Connect a processing server</b>
          <button className="iconbtn sm" onClick={onClose}><Icon name="x" size={14} /></button>
        </div>
        <p className="modal-note">
          The app works on-device now — your photos stay in the browser. Connect a
          server to render through the full desktop pipeline: cleaner shadows,
          whiter paper, crisper text.
        </p>
        <ol className="help-steps">
          <li>Top-right — click the <b>On-device</b> chip.</li>
          <li>Enter the server address (or tap <b>Use hosted server</b>).</li>
          <li>Click <b>Connect</b>.</li>
        </ol>
        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Close</button>
          <button className="btn primary" onClick={onOpenSettings}>Open server settings</button>
        </div>
      </div>
    </div>
  )
}

/* ---- importing several photos at once: one style, applied to the whole batch ---- */
function BatchDialog({ count, onCancel, onStart }) {
  const [border, setBorder] = useState(true)
  const [mode, setMode] = useState('docs')
  const [bw, setBw] = useState(false)
  return (
    <div className="modal-scrim" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <b>Import {count} pages</b>
          <button className="iconbtn sm" onClick={onCancel}><Icon name="x" size={14} /></button>
        </div>
        <p className="modal-note">
          Pick one look for all {count} photos — you can still fine-tune any page afterwards.
        </p>

        <span className="seclabel">Scan style</span>
        <div className="segmented vertical">
          {STYLES.map((s) => (
            <button
              key={s.id}
              className={`seg-btn${mode === s.id ? ' active' : ''}`}
              title={s.desc}
              onClick={() => setMode(s.id)}
            >
              <span className={`seg-swatch ${s.sw}`} />
              {s.label}
            </button>
          ))}
        </div>

        <span className="seclabel">Colour</span>
        <div className="pilltoggle">
          <button className={`pill-opt${!bw ? ' active' : ''}`} onClick={() => setBw(false)}>Colour</button>
          <button className={`pill-opt${bw ? ' active' : ''}`} onClick={() => setBw(true)}>B&amp;W</button>
        </div>

        <label className="compare-chk" style={{ marginTop: 6 }}>
          <input type="checkbox" checked={border} onChange={(e) => setBorder(e.target.checked)} />
          Border adjustment — review and nudge each page's crop
        </label>
        {!border && (
          <p className="modal-note" style={{ marginTop: -4 }}>
            Off: pages import straight from the detected edges, no crop screen per page.
          </p>
        )}

        <div className="modal-actions">
          <button className="btn ghost" onClick={onCancel}>Cancel</button>
          <button className="btn primary" onClick={() => onStart({ border, mode, bw })}>
            Import {count} pages
          </button>
        </div>
      </div>
    </div>
  )
}

/* ---- server settings dialog ---- */
function ServerSettings({ apiUrl, suggested, info, checking, onApply, onClose }) {
  const [val, setVal] = useState(apiUrl || suggested || '')
  const [probe, setProbe] = useState(null) // null | 'checking' | {ok,ocr} | 'fail'
  const test = async () => {
    setProbe('checking')
    const h = await backend.checkHealth(val)
    setProbe(h || 'fail')
  }
  const connected = info && info.ok && apiUrl && val.trim().replace(/\/+$/, '') === apiUrl
  const showSuggested = suggested && val.trim().replace(/\/+$/, '') !== suggested
  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <b>Processing server</b>
          <button className="iconbtn sm" onClick={onClose}><Icon name="x" size={14} /></button>
        </div>
        <p className="modal-note">
          On-device is the default — your photo never leaves the browser. Connect a
          server to render through the full desktop pipeline (same output as the
          Windows app); the photo is then uploaded to it and not stored.
        </p>
        <input
          className="ocr-select"
          style={{ fontFamily: 'var(--mono)', fontSize: 12 }}
          placeholder={suggested || 'http://127.0.0.1:8000'}
          value={val}
          onChange={(e) => { setVal(e.target.value); setProbe(null) }}
          onKeyDown={(e) => e.key === 'Enter' && test()}
          autoFocus
        />
        {showSuggested && (
          <button className="btn ghost sm" style={{ marginTop: 6 }}
            onClick={() => { setVal(suggested); setProbe(null) }}>
            Use hosted server
          </button>
        )}
        <div className="modal-row">
          <button className="btn ghost sm" onClick={test} disabled={probe === 'checking'}>
            {probe === 'checking' ? 'Testing…' : 'Test'}
          </button>
          {probe && probe !== 'checking' && (
            <span className={`probe ${probe === 'fail' ? 'bad' : 'good'}`}>
              {probe === 'fail'
                ? 'No response'
                : `Connected${probe.ocr ? ' · OCR ready' : ' · no OCR'}`}
            </span>
          )}
          {!probe && connected && <span className="probe good">Currently connected</span>}
        </div>
        <div className="modal-actions">
          <button className="btn ghost" onClick={() => { onApply(''); onClose() }}>Use on-device</button>
          <button className="btn primary" onClick={() => { onApply(val); onClose() }}>
            {val.trim() ? 'Connect' : 'Save'}
          </button>
        </div>
        {checking && <div className="modal-note" style={{ marginTop: 8 }}>Checking saved server…</div>}
      </div>
    </div>
  )
}

/* ============================================================ subcomponents */

function Ring({ value, num, spinning }) {
  const v = Math.max(0, Math.min(1, value)) * 100
  return (
    <div className={`ring${spinning ? ' spin' : ''}`}>
      <svg viewBox="0 0 36 36">
        <circle className="ring-track" cx="18" cy="18" r="15.5" pathLength="100" />
        <circle className="ring-arc" cx="18" cy="18" r="15.5" pathLength="100" style={{ strokeDashoffset: 100 - v }} />
      </svg>
      {!spinning && <span className="ring-num">{num}</span>}
    </div>
  )
}

function PageList({ pages, editingId, onOpen, onRemove, onMove, onAdd }) {
  const drag = useRef(null)
  return (
    <aside className="pagelist" data-empty={pages.length === 0 ? '' : undefined}>
      <div className="pagelist-head">
        <span className="pagelist-title">{pages.length ? `PAGES · ${pages.length}` : 'PAGES'}</span>
        <div className="pagelist-tools">
          <button
            className="iconbtn sm danger"
            title="Delete current page"
            disabled={!editingId}
            onClick={() => onRemove(editingId)}
          >
            <Icon name="trash" size={14} />
          </button>
        </div>
      </div>

      {pages.length === 0 ? (
        <div className="thumb-empty">
          <Icon name="layers" size={26} />
          No pages yet.<br />Add one with the button below.
        </div>
      ) : (
        <div className="thumbs">
          {pages.map((p, i) => (
            <div
              key={p.id}
              className={`thumb${p.id === editingId ? ' active' : ''}`}
              draggable
              onDragStart={() => (drag.current = i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => { if (drag.current != null && drag.current !== i) onMove(drag.current, i); drag.current = null }}
              onClick={() => onOpen(p)}
              title={`Page ${i + 1}`}
            >
              <img src={p.url} alt={`Page ${i + 1}`} />
              <span className="thumb-badge">{i + 1}</span>
            </div>
          ))}
        </div>
      )}

      <button className="btn ghost sm block" style={{ marginTop: 8 }} onClick={onAdd}>
        <Icon name="plus" size={14} /> Add page
      </button>
    </aside>
  )
}

/* phone: the whole document as a grid of pages — tap one to edit it */
function MobileGallery({ pages, onOpen, onRemove, onMove, onExport, onAddPhoto, onCamera }) {
  const from = useRef(null)
  const [over, setOver] = useState(null)

  const end = () => {
    if (from.current != null && over != null && from.current !== over) onMove(from.current, over)
    from.current = null
    setOver(null)
  }
  const track = (e) => {
    if (from.current == null) return
    const card = document.elementFromPoint(e.clientX, e.clientY)?.closest?.('[data-idx]')
    if (card) setOver(Number(card.dataset.idx))
  }

  return (
    <div className="mgallery">
      <header className="mg-head">
        <div className="mg-title">
          <b>Document</b>
          <span>{pages.length} page{pages.length === 1 ? '' : 's'}</span>
        </div>
        <button className="btn primary sm glow" onClick={onExport}>
          <Icon name="download" size={14} /> PDF
        </button>
      </header>

      <div className="mg-grid">
        {pages.map((p, i) => (
          <div
            key={p.id}
            data-idx={i}
            className={`mg-card${from.current === i ? ' dragging' : ''}${over === i && from.current != null && from.current !== i ? ' drop' : ''}`}
          >
            <button className="mg-card-open" onClick={() => from.current == null && onOpen(p)}>
              <img src={p.url} alt={`Page ${i + 1}`} draggable={false} />
            </button>
            <span className="mg-num">{String(i + 1).padStart(2, '0')}</span>
            <button
              className="mg-grip"
              title="Drag to reorder"
              onPointerDown={(e) => { e.currentTarget.setPointerCapture?.(e.pointerId); from.current = i; setOver(i) }}
              onPointerMove={track}
              onPointerUp={end}
              onPointerCancel={end}
            >
              <Icon name="grid" size={11} />
            </button>
            <button className="mg-del" title="Remove page" onClick={() => onRemove(p.id)}>
              <Icon name="trash" size={13} />
            </button>
          </div>
        ))}
        <button className="mg-card mg-add" onClick={onAddPhoto}>
          <Icon name="plus" size={22} />
          <span>Add page</span>
        </button>
      </div>

      <div className="mg-bar">
        <button onClick={onAddPhoto} title="Add from photos"><Icon name="image" size={20} /></button>
        <button onClick={onCamera} title="Take a photo"><Icon name="camera" size={20} /></button>
        <span className="mg-bar-sp" />
        <button onClick={onExport} title="Export PDF"><Icon name="download" size={20} /></button>
      </div>
    </div>
  )
}

function Slider({ label, value, onChange }) {
  return (
    <div className="slider-row">
      <span className="slider-label">{label}</span>
      <input
        className="slider"
        type="range"
        min={-100}
        max={100}
        value={value}
        style={{ '--fill': `${(value + 100) / 2}%` }}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <span className="slider-val">{value > 0 ? `+${value}` : value}</span>
    </div>
  )
}
