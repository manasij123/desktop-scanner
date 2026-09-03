// Client for the optional FastAPI backend (server/main.py). When a reachable
// API URL is configured the app renders server-side through the real
// `clearscanner` desktop pipeline instead of the on-device WebGL engine —
// same output as the desktop app. Falls back to on-device when unset or down.

const LS_KEY = 'dsc_api_url'
const norm = (u) => (u || '').trim().replace(/\/+$/, '')

export function defaultApiUrl() {
  const env = norm(import.meta.env.VITE_API_URL || '')
  if (env) return env
  // dev: vite.config.js auto-starts server/main.py on :8000, connect to it.
  // 127.0.0.1 not "localhost" — on Windows "localhost" resolves ::1 first and
  // the IPv4 fallback adds ~2 s per request.
  if (import.meta.env.DEV) return 'http://127.0.0.1:8000'
  return ''
}
export function savedApiUrl() {
  try {
    const v = localStorage.getItem(LS_KEY)
    return v === null ? defaultApiUrl() : norm(v)
  } catch {
    return defaultApiUrl()
  }
}
export function persistApiUrl(url) {
  try {
    if (norm(url)) localStorage.setItem(LS_KEY, norm(url))
    else localStorage.removeItem(LS_KEY)
  } catch {
    /* storage blocked — session-only */
  }
}

// Optional deploy-time config served next to the app (docs/app/config.json,
// from webapp/public/config.json). Lets the hosted backend URL change without
// a rebuild. { apiUrl?: string, serverDefault?: boolean }
export async function fetchRuntimeConfig() {
  try {
    const r = await fetch(import.meta.env.BASE_URL + 'config.json', { cache: 'no-cache' })
    if (!r.ok) return {}
    const j = await r.json()
    return { apiUrl: norm(j.apiUrl || ''), serverDefault: !!j.serverDefault }
  } catch {
    return {}
  }
}

const timeout = (ms) => (AbortSignal.timeout ? AbortSignal.timeout(ms) : undefined)

export async function checkHealth(url) {
  const base = norm(url)
  if (!base) return null
  // first try is quick; if it *times out* (vs. connection refused) the host
  // may be a free instance waking from sleep — retry once, patiently
  for (const ms of [6000, 22000]) {
    try {
      const r = await fetch(base + '/health', { signal: timeout(ms) })
      if (!r.ok) return null
      const j = await r.json()
      return j && j.ok ? j : null // { ok, ocr, modes }
    } catch (e) {
      if (e?.name !== 'TimeoutError' && e?.name !== 'AbortError') return null
    }
  }
  return null
}

export async function detect(url, file) {
  const fd = new FormData()
  fd.append('image', file)
  const r = await fetch(norm(url) + '/detect', { method: 'POST', body: fd, signal: timeout(60000) })
  if (!r.ok) throw new Error(await errText(r, 'detect'))
  return r.json() // { corners:[[x,y]*4] 0..1, fallback, width, height }
}

export async function render(url, file, corners, opts, { maxDim = 2600, fallback = false, quality = 92 } = {}) {
  const fd = new FormData()
  fd.append('image', file)
  fd.append('corners', JSON.stringify(corners))
  fd.append('mode', opts.mode)
  fd.append('bw', opts.bw ? 'true' : 'false')
  fd.append('recover', opts.recover ? 'true' : 'false')
  fd.append('sharpen', opts.sharpen ? 'true' : 'false')
  fd.append('fallback', fallback ? 'true' : 'false')
  fd.append('brightness', String(opts.brightness | 0))
  fd.append('contrast', String(opts.contrast | 0))
  fd.append('saturation', String(opts.saturation | 0))
  fd.append('max_dim', String(maxDim))
  fd.append('quality', String(quality))
  const r = await fetch(norm(url) + '/render', { method: 'POST', body: fd, signal: timeout(60000) })
  if (!r.ok) throw new Error(await errText(r, 'render'))
  return r.blob()
}

export async function ocr(url, blob, lang) {
  const fd = new FormData()
  fd.append('image', blob, 'page.jpg')
  fd.append('lang', lang)
  const r = await fetch(norm(url) + '/ocr', { method: 'POST', body: fd, signal: timeout(120000) })
  if (!r.ok) throw new Error(await errText(r, 'OCR'))
  return (await r.json()).text
}

async function errText(r, what) {
  try {
    const j = await r.json()
    if (j && j.detail) return `${what}: ${j.detail}`
  } catch {
    /* not JSON */
  }
  return `${what} failed (${r.status})`
}
