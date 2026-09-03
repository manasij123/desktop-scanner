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
const SRC_CAP = 3600
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

async function loadSource(file) {
  // 'from-image' so a phone photo with an EXIF orientation tag is drawn
  // upright — the canvas (and the re-encoded, tag-less upload JPEG) must not
  // depend on the browser's default, which varies.
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' }).catch(() => createImageBitmap(file))
  // Always hand the engine a <canvas>, never a raw ImageBitmap: the two
  // upload with opposite Y orientation under UNPACK_FLIP_Y, and rotate90()
  // also yields a canvas — one consistent source type keeps the pipeline's
  // flip handling correct end to end.
  const [w, h] = fit(bmp.width, bmp.height, SRC_CAP)
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

function srcToFile(canvas, q = 0.88) {
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
  const [srvPreview, setSrvPreview] = useState(null) // object URL of the server-rendered preview
  const [srvBusy, setSrvBusy] = useState(false)
  const useServer = !!(serverInfo && serverInfo.ok && apiUrl)

  const glRef = useRef(null)
  const cropRef = useRef(null)
  const engineRef = useRef(null)
  const bgRef = useRef(null)
  const queueRef = useRef([])
  const dragRef = useRef(null)
  const rafRef = useRef(0)
  const statusTimer = useRef(0)

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

  /* ---- import ---- */
  const beginSource = useCallback(async (file) => {
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
      setWork(src)
      setCorners(quad)
      setBaseCorners(quad)
      setEditingId(null)
      setDocConf(conf)
      setHintOff(false)
      setSrvPreview((u) => { if (u) URL.revokeObjectURL(u); return null })
      setOpts((o) => ({
        ...o, mode: smartMode(conf, src.flat),
        recover: false, sharpen: false, brightness: 0, contrast: 0, saturation: 0,
      }))
      setShowAdjust(false)
      setStage('crop')
      say('Drag the corners to match the page, then confirm', true)
    } catch (e) {
      toast(e.message || 'Could not open that image', 'error')
    } finally {
      setBusy(null)
    }
  }, [toast, say, useServer, apiUrl])

  const startFiles = useCallback((fileList) => {
    const files = [...fileList].filter((f) => f.type.startsWith('image/'))
    if (!files.length) { toast('Pick a PNG, JPEG or WebP image', 'error'); return }
    queueRef.current = files.slice(1)
    beginSource(files[0])
  }, [toast, beginSource])

  const nextQueued = useCallback(() => {
    const f = queueRef.current.shift()
    if (f) { beginSource(f); return true }
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
    ctx.fillStyle = 'rgba(34,31,53,0.44)'
    ctx.fill('evenodd')
    ctx.restore()

    ctx.beginPath()
    ctx.moveTo(P[0][0], P[0][1])
    for (let i = 1; i < 4; i++) ctx.lineTo(P[i][0], P[i][1])
    ctx.closePath()
    ctx.strokeStyle = '#5B4BE6'
    ctx.lineWidth = 2
    ctx.stroke()

    ctx.fillStyle = '#5B4BE6'
    for (const [a, b] of EDGES) {
      const mx = (P[a][0] + P[b][0]) / 2
      const my = (P[a][1] + P[b][1]) / 2
      ctx.fillRect(mx - 5.5, my - 5.5, 11, 11)
    }
    for (const [x, y] of P) {
      ctx.beginPath()
      ctx.arc(x, y, 7, 0, Math.PI * 2)
      ctx.fillStyle = '#5B4BE6'
      ctx.fill()
      ctx.lineWidth = 2.5
      ctx.strokeStyle = '#fff'
      ctx.stroke()
    }
  }, [work, corners, cropGeom])

  useEffect(() => { if (stage === 'crop') drawCrop() }, [stage, drawCrop])

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
      if (kind === 'corner') q[idx] = [nx, ny]
      else {
        const [a, b, o] = EDGES[idx]
        if (o === 'h') { q[a][1] = ny; q[b][1] = ny }
        else { q[a][0] = nx; q[b][0] = nx }
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
    rot.file = useServer ? await srcToFile(rot.el) : work.file
    setWork(rot)
    setCorners(rotateQuad(corners, dir))
    setBaseCorners(rotateQuad(baseCorners, dir))
  }
  const resetCorners = () => setCorners(baseCorners)

  const confirmCrop = () => {
    if (!work) return
    if (!useServer) {
      const eng = engine()
      if (!eng) return
      eng.setSource(work.el, work.w, work.h)
    }
    setStage('preview')
    say(editingId ? 'Adjust the look, then update the page' : 'Pick a look, then add the page')
  }

  /* ---- on-device preview render (WebGL) ---- */
  const renderPreview = useCallback(() => {
    const eng = engineRef.current
    if (useServer || !eng || stage !== 'preview' || !corners) return
    eng.render(
      corners,
      compare
        ? { mode: 'original', bw: false, recover: false, sharpen: false, brightness: 0, contrast: 0, saturation: 0 }
        : opts,
    )
  }, [useServer, stage, corners, opts, compare])

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
    if (!useServer || stage !== 'preview' || !work?.file || !corners) return
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
  }, [useServer, stage, work, corners, opts, compare, apiUrl, toast])

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

  const addToDocument = async () => {
    setBusy('Rendering page…')
    try {
      const pg = await gradePage(work, corners, opts)
      const id = uid()
      setPages((p) => [...p, { id, ...pg }])
      setEditingId(id)
      say(`Added as page ${pages.length + 1}`)
      toast(`Added page ${pages.length + 1}`, 'good')
      nextQueued()
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
      nextQueued() // advance if a multi-import is still in progress
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
  const openPage = (pg) => {
    if (!useServer) {
      const eng = engine()
      if (!eng) return
      eng.setSource(pg.src.el, pg.src.w, pg.src.h)
    }
    setWork(pg.src)
    setCorners(pg.corners)
    setBaseCorners(pg.corners)
    setOpts(pg.opts)
    setEditingId(pg.id)
    setDocConf(pg.src.conf ?? null)
    setHintOff(true)  // already committed — don't nag when re-styling
    setShowAdjust(false)
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
    if (editingId === id) {
      if (next.length) openPage(next[Math.min(idx, next.length - 1)])
      else { setEditingId(null); setStage('empty'); setWork(null); setCorners(null) }
    }
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
    if (stage === 'crop') return ['Adjust the edges', 'Drag the corners to match the document, then confirm']
    if (stage === 'preview')
      return editingId && activeIdx >= 0
        ? ['Review & export', `Page ${activeIdx + 1} of ${pages.length} — tune the look, then update`]
        : ['Review & export', 'Pick a look and fine-tune, then add the page to your document']
    return ['Add a document', 'Drop a photo anywhere, or use the + button to get started']
  }, [stage, editingId, activeIdx, pages.length])

  /* ================================================================ render */

  return (
    <div id="app">
      <div className="backdrop" ref={bgRef} />

      <nav className="rail">
        <div className="rail-logo"><Icon name="scan" size={22} /></div>
        <button className="rail-btn primary" title="Add photos" onClick={pickFiles}>
          <Icon name="plus" size={20} />
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
        <header className="topbar">
          <div className="titles">
            <span className="page-title">{title[0]}</span>
            <span className="page-sub">{title[1]}</span>
          </div>
          <div className="topbar-spacer" />
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
          <button className="btn ghost" onClick={printDoc} disabled={!pages.length}>
            <Icon name="print" size={16} /> Print
          </button>
          <button className="btn primary glow" onClick={exportPdf} disabled={!pages.length}>
            <Icon name="download" size={16} /> Export PDF
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
                  <button className="btn ghost sm" onClick={resetCorners}>
                    <Icon name="reset" size={15} /> Reset to auto-detect
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
                  <div className="controls-scroll">
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

                  <div className="hairline" />

                  <button className="ctl-btn" onClick={() => setStage('crop')}>
                    <Icon name="crop" size={16} /> Re-crop
                  </button>
                  <button
                    className={`ctl-btn${opts.sharpen ? ' active' : ''}`}
                    onClick={() => setOpts((o) => ({ ...o, sharpen: !o.sharpen }))}
                    title="Crisp up slightly soft text and lines"
                  >
                    <Icon name="sparkle" size={16} /> Sharpen
                    {opts.sharpen && <Icon name="check" size={15} className="ctl-check" />}
                  </button>
                  <button
                    className={`ctl-btn${opts.recover ? ' active' : ''}`}
                    disabled={!recoverable}
                    onClick={() => setOpts((o) => ({ ...o, recover: !o.recover }))}
                    title={recoverable ? 'Re-ink strokes a glare washed out (Docs / Clear)' : 'Switch to Docs or Clear first'}
                  >
                    <Icon name="text" size={16} /> Recover faded text
                    {opts.recover && recoverable && <Icon name="check" size={15} className="ctl-check" />}
                  </button>
                  <button
                    className={`ctl-btn${showAdjust ? ' active' : ''}`}
                    onClick={() => setShowAdjust((s) => !s)}
                  >
                    <Icon name="sliders" size={16} /> Fine adjust
                    {showAdjust && <Icon name="check" size={15} className="ctl-check" />}
                  </button>

                  {showAdjust && (
                    <div className="enhance">
                      <div className="enhance-head">
                        <span className="seclabel" style={{ marginTop: 0 }}>Brightness · Contrast{!opts.bw ? ' · Saturation' : ''}</span>
                        <button
                          className="iconbtn sm"
                          style={{ marginLeft: 'auto' }}
                          title="Reset adjustments"
                          onClick={() => setOpts((o) => ({ ...o, brightness: 0, contrast: 0, saturation: 0 }))}
                        >
                          <Icon name="reset" size={13} />
                        </button>
                      </div>
                      <Slider label="Brightness" value={opts.brightness} onChange={(v) => setOpts((o) => ({ ...o, brightness: v }))} />
                      <Slider label="Contrast" value={opts.contrast} onChange={(v) => setOpts((o) => ({ ...o, contrast: v }))} />
                      {!opts.bw && (
                        <Slider label="Saturation" value={opts.saturation} onChange={(v) => setOpts((o) => ({ ...o, saturation: v }))} />
                      )}
                    </div>
                  )}

                  <div className="hairline" />

                  <span className="seclabel">Text (OCR)</span>
                  <select className="ocr-select" value={ocrLang} onChange={(e) => setOcrLang(e.target.value)}>
                    {OCR_LANGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                  <button className="ctl-btn" onClick={runOcr} disabled={ocrBusy}>
                    <Icon name="text" size={16} /> {ocrBusy ? 'Reading…' : 'Extract text'}
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

                  <div className="controls-foot">
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
          {busy || status}
          <span className="statusbar-spacer" />
          <span className="statusbar-mode">{useServer ? `server · ${apiUrl.replace(/^https?:\/\//, '')}` : 'on-device'}</span>
        </div>
      </div>

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
    <aside className="pagelist">
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
          No pages yet.<br />Add a photo with the + button.
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
