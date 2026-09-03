/* Desktop Scanner (web) — offline service worker.
   No build-step manifest: the app shell is small and its asset names are
   hashed, so instead of precaching a fixed list this caches every
   successful GET as it is fetched and serves from cache when the network
   is gone. Bump CACHE to invalidate everything on a new deploy. */

const CACHE = 'dsc-web-v7'
const CORE = ['./', './index.html', './manifest.webmanifest', './logo.png', './favicon.png', './intro.gif']

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(CORE))
      .then(() => self.skipWaiting())
      .catch(() => {}),
  )
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (e) => {
  const { request } = e
  if (request.method !== 'GET') return

  // Navigations: network first (fresh app), fall back to the cached shell.
  if (request.mode === 'navigate') {
    e.respondWith(
      fetch(request)
        .then((res) => {
          caches.open(CACHE).then((c) => c.put('./', res.clone())).catch(() => {})
          return res
        })
        .catch(() => caches.match('./', { ignoreSearch: true }).then((r) => r || caches.match('./index.html'))),
    )
    return
  }

  // Everything else (JS/CSS chunks, fonts, the OCR engine from a CDN):
  // cache first, then network, and stash whatever comes back.
  e.respondWith(
    caches.match(request).then(
      (hit) =>
        hit ||
        fetch(request)
          .then((res) => {
            if (res && (res.ok || res.type === 'opaque')) {
              const copy = res.clone()
              caches.open(CACHE).then((c) => c.put(request, copy)).catch(() => {})
            }
            return res
          })
          .catch(() => hit),
    ),
  )
})
