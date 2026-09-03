import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles/theme.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

// dismiss the branded splash (index.html) once React has painted, but keep it
// up long enough for the scan-sweep to read as intentional, not a flash
{
  const splash = document.getElementById('splash')
  if (splash) {
    const MIN_MS = 1650   // ~3 loops of the intro gif before it clears
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const wait = Math.max(0, MIN_MS - (Date.now() - (window.__splashAt || Date.now())))
      setTimeout(() => {
        splash.classList.add('gone')
        splash.addEventListener('transitionend', () => splash.remove(), { once: true })
        setTimeout(() => splash.remove(), 700)
      }, wait)
    }))
  }
}

// offline service worker (served verbatim from public/) — production only, so
// it never caches stale chunks in front of the dev server's HMR.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    const base = import.meta.env.BASE_URL || '/'
    navigator.serviceWorker.register(base + 'sw.js').catch(() => {})
  })
}
