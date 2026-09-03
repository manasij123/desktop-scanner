import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import http from 'node:http'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(here, '..')
const API_PORT = 8000
const P = '\x1b[35m[backend]\x1b[0m'

// module scope, not per-plugin: Vite re-instantiates the plugin on every
// config-change restart, and we want the one backend to survive those.
let child = null
let starting = false

const ping = (port) =>
  new Promise((res) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/health', timeout: 1500 }, (r) => {
      r.resume()
      res(r.statusCode === 200)
    })
    req.on('error', () => res(false))
    req.on('timeout', () => { req.destroy(); res(false) })
  })

// ordered [command, leadingArgs] to try until one launches
function pythonCandidates() {
  const win = process.platform === 'win32'
  const out = []
  if (process.env.DSC_PYTHON) out.push([process.env.DSC_PYTHON, []])
  for (const rel of ['venv', '.venv']) {
    const p = path.join(repoRoot, rel, win ? 'Scripts/python.exe' : 'bin/python')
    if (existsSync(p)) out.push([p, []])
  }
  if (win) out.push(['py', ['-3']], ['python', []])
  else out.push(['python3', []], ['python', []])
  return out
}

function killChild() {
  if (!child || child.pid == null) return
  const pid = child.pid
  child = null
  try {
    if (process.platform === 'win32') spawn('taskkill', ['/pid', String(pid), '/T', '/F'])
    else process.kill(pid, 'SIGTERM')
  } catch { /* already gone */ }
}
process.once('SIGINT', killChild)
process.once('SIGTERM', killChild)
process.once('exit', killChild)

// Dev only: bring the FastAPI backend (server/main.py) up alongside Vite so
// `npm run dev` is the single command — the webapp auto-connects to it (see
// backend.js defaultApiUrl). Reuses any instance already on :8000; the child
// it starts is killed only when Vite's *process* exits, so it rides through
// config-change restarts instead of being torn down and re-raced.
function backendPlugin() {
  return {
    name: 'dsc-backend',
    apply: 'serve',
    async configureServer(server) {
      const log = server.config.logger
      if (child || starting) return
      if (await ping(API_PORT)) {
        log.info(`${P} reusing server already on :${API_PORT}`)
        return
      }
      starting = true
      const args = ['-m', 'uvicorn', 'server.main:app', '--port', String(API_PORT), '--host', '127.0.0.1']
      const candidates = pythonCandidates()

      const tryNext = (i) => {
        if (i >= candidates.length) {
          starting = false
          log.warn(`${P} no working Python found — start it yourself or install deps:\n` +
            `        pip install -r server/requirements.txt   (or set DSC_PYTHON)`)
          return
        }
        const [cmd, lead] = candidates[i]
        const c = spawn(cmd, [...lead, ...args], {
          cwd: repoRoot,
          env: { ...process.env, DSC_ALLOW_ORIGINS: '*', PYTHONUNBUFFERED: '1' },
        })
        let launched = false
        const pipe = (buf) => {
          launched = true
          starting = false
          for (const line of buf.toString().split(/\r?\n/)) {
            if (line.trim()) log.info(`${P} ${line}`)
          }
        }
        c.stdout.on('data', pipe)
        c.stderr.on('data', pipe)
        c.on('error', () => { if (!launched) { child = null; tryNext(i + 1) } })
        c.on('exit', (code) => {
          const wasChild = child === c
          if (wasChild) child = null
          if (!launched) { tryNext(i + 1); return }
          starting = false
          if (code) log.warn(`${P} exited (code ${code})`)
        })
        child = c
        log.info(`${P} starting via ${cmd} on 127.0.0.1:${API_PORT}`)
      }
      tryNext(0)
    },
  }
}

// Builds straight into docs/app/ so the existing GitHub Pages site
// (served from docs/ on main) picks it up with no extra deploy step —
// push, and it's live at /desktop-scanner/app/.
export default defineConfig({
  plugins: [react(), backendPlugin()],
  base: '/desktop-scanner/app/',
  // bind IPv4 so the dev server and the backend are both on 127.0.0.1 — Vite
  // otherwise follows "localhost" to ::1 on Windows and the two disagree
  server: { host: '127.0.0.1' },
  build: {
    outDir: '../docs/app',
    emptyOutDir: true,
  },
})
