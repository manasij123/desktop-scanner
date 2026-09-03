// Document-boundary guess — the starting point for the crop editor, which
// the user then nudges by hand. Two strategies, best-scoring one wins:
//
//   A. Largest bright region. Otsu-threshold the luma to split paper from
//      the surface behind it, keep the biggest connected blob, and take
//      its four corner extremes. Robust when the document is the dominant
//      bright object on a darker/patterned background (a card on a bed,
//      paper on a desk) — the case the old edge-extreme method got badly
//      wrong, dragging the crop into the dark background.
//   B. Sobel edge extremes. The previous method — still better when the
//      document fills nearly the whole frame with weak border contrast.
//
// Falls back to a slight inset of the whole frame if neither is plausible.

const FALLBACK_INSET = 0.02
const WORK = 460 // px long side for the analysis pass

export function detectCorners(source, srcW, srcH) {
  const s = Math.min(1, WORK / Math.max(srcW, srcH))
  const w = Math.max(16, Math.round(srcW * s))
  const h = Math.max(16, Math.round(srcH * s))

  const cv = document.createElement('canvas')
  cv.width = w
  cv.height = h
  const ctx = cv.getContext('2d', { willReadFrequently: true })
  ctx.drawImage(source, 0, 0, w, h)
  const d = ctx.getImageData(0, 0, w, h).data

  const n = w * h
  const gray = new Uint8Array(n)
  for (let i = 0, p = 0; p < n; i += 4, p++) {
    gray[p] = (0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) | 0
  }

  const good = [foregroundQuad(d, w, h), sobelExtremeQuad(gray, w, h)].filter(Boolean).filter(plausible)
  if (!good.length) return fallback()
  good.sort((p, q) => score(q) - score(p))
  return good[0]
}

/* ------------------------------------------------------- strategy A
   Foreground = whatever the frame border is NOT. Model the surface colour
   from a band around the edges of the photo (nearly always background),
   mask every pixel far from it, keep the biggest blob and take its
   minimum-area rectangle. Robust for "document on a contrasting surface"
   regardless of the document's own colours or brightness. */

function foregroundQuad(d, w, h) {
  const n = w * h
  const bw = Math.min(46, Math.max(4, Math.round(Math.min(w, h) * 0.06)))

  // sample each edge band separately, so a graded background (a photo that
  // is dark along the top and bright along the bottom) is still modelled
  // correctly — the killer for a single global mean.
  const edge = (x0, x1, y0, y1) => {
    let r = 0, g = 0, b = 0, c = 0
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
      const i = (y * w + x) * 4
      r += d[i]; g += d[i + 1]; b += d[i + 2]; c++
    }
    if (!c) return [0, 0, 0, 0]
    r /= c; g /= c; b /= c
    let v = 0
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
      const i = (y * w + x) * 4
      v += (d[i] - r) ** 2 + (d[i + 1] - g) ** 2 + (d[i + 2] - b) ** 2
    }
    return [r, g, b, Math.sqrt(v / c)]
  }
  const top = edge(0, w, 0, bw)
  const bot = edge(0, w, h - bw, h)
  const lef = edge(0, bw, 0, h)
  const rig = edge(w - bw, w, 0, h)
  const means = [top, bot, lef, rig]
  // threshold off the 2nd-cleanest edge, not the noisiest — a patterned
  // sheet along one border must not inflate it and hide the document
  const sds = means.map((m) => m[3]).sort((p, q) => p - q)
  const thr2 = Math.max(28, Math.min(70, sds[1] * 2.4 + 14)) ** 2

  const mask = new Uint8Array(n)
  for (let y = 0; y < h; y++) {
    const fy = y / (h - 1)
    for (let x = 0; x < w; x++) {
      const fx = x / (w - 1)
      const i = (y * w + x) * 4
      let da = 0
      for (let k = 0; k < 3; k++) {
        const eb = 0.5 * (top[k] * (1 - fy) + bot[k] * fy) + 0.5 * (lef[k] * (1 - fx) + rig[k] * fx)
        da += (d[i + k] - eb) ** 2
      }
      mask[y * w + x] = da > thr2 ? 1 : 0
    }
  }

  const mn = Math.min(w, h)
  const rOpen = Math.max(2, Math.round(mn * 0.02))
  const rClose = Math.max(4, Math.round(mn * 0.04))
  morph(mask, w, h, rOpen, false)   // open  — shed bedsheet specks near the card
  morph(mask, w, h, rOpen, true)
  morph(mask, w, h, rClose, true)   // close — bridge the card's own dark bands
  morph(mask, w, h, rClose, false)  //         so the thin top strip stays joined

  const comp = largestComponent(mask, w, h)
  if (!comp) return null
  const frac = comp.count / n
  if (frac < 0.06 || frac > 0.97) return null

  // silhouette points -> convex hull -> minimum-area enclosing rectangle:
  // for a card (which *is* a rectangle) this tracks all four corners even
  // when the blob's own extremes sit on an inner feature.
  const pts = silhouette(comp.pixels, w, h)
  const hull = convexHull(pts)
  if (hull.length < 3) return null
  const rect = minAreaRect(hull)
  if (!rect) return null
  let q = orderQuad(rect).map(([x, y]) => [x / w, y / h])
  if (quadArea(q) > 0.92) return null // grabbed ~the whole frame, not a doc
  // the enclosing rect systematically over-reads by a few % (a noisy blob
  // edge, the closing morphology) — pull every corner in toward the centre
  // so the crop sits inside the document, not a hair outside it
  const cx = (q[0][0] + q[1][0] + q[2][0] + q[3][0]) / 4
  const cy = (q[0][1] + q[1][1] + q[2][1] + q[3][1]) / 4
  const SHRINK = 0.03
  q = q.map(([x, y]) => [x + (cx - x) * SHRINK, y + (cy - y) * SHRINK])
  return q
}

/* -------- binary morphology (separable, O(n) per axis) -------- */

function morph(mask, w, h, r, dilate) {
  pass(mask, w, h, r, dilate, false)
  pass(mask, w, h, r, dilate, true)
}
function pass(mask, w, h, r, dilate, vertical) {
  const runs = vertical ? w : h
  const len = vertical ? h : w
  const step = vertical ? w : 1
  const line = new Uint8Array(len)
  for (let i = 0; i < runs; i++) {
    const base = vertical ? i : i * w
    for (let j = 0; j < len; j++) line[j] = mask[base + j * step]
    // distance to nearest pixel of the "hit" value, both directions
    const hit = dilate ? 1 : 0
    let d = 1e9
    for (let j = 0; j < len; j++) { d = line[j] === hit ? 0 : d + 1; if (d <= r) mask[base + j * step] = dilate ? 1 : 0 }
    d = 1e9
    for (let j = len - 1; j >= 0; j--) { d = line[j] === hit ? 0 : d + 1; if (d <= r) mask[base + j * step] = dilate ? 1 : 0 }
  }
}

/* -------- geometry -------- */

// per-row and per-column extreme pixels of the blob — a cheap outline
function silhouette(pixels, w, h) {
  const rowMin = new Int32Array(h).fill(-1)
  const rowMax = new Int32Array(h).fill(-1)
  const colMin = new Int32Array(w).fill(-1)
  const colMax = new Int32Array(w).fill(-1)
  for (const p of pixels) {
    const x = p % w, y = (p / w) | 0
    if (rowMin[y] < 0 || x < rowMin[y]) rowMin[y] = x
    if (x > rowMax[y]) rowMax[y] = x
    if (colMin[x] < 0 || y < colMin[x]) colMin[x] = y
    if (y > colMax[x]) colMax[x] = y
  }
  const out = []
  for (let y = 0; y < h; y++) { if (rowMin[y] >= 0) { out.push([rowMin[y], y]); out.push([rowMax[y], y]) } }
  for (let x = 0; x < w; x++) { if (colMin[x] >= 0) { out.push([x, colMin[x]]); out.push([x, colMax[x]]) } }
  return out
}

function convexHull(pts) {
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const lower = []
  for (const q of p) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop()
    lower.push(q)
  }
  const upper = []
  for (let i = p.length - 1; i >= 0; i--) {
    const q = p[i]
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop()
    upper.push(q)
  }
  lower.pop(); upper.pop()
  return lower.concat(upper)
}

function minAreaRect(hull) {
  let best = null
  let bestArea = Infinity
  for (let i = 0; i < hull.length; i++) {
    const a = hull[i]
    const b = hull[(i + 1) % hull.length]
    let ux = b[0] - a[0], uy = b[1] - a[1]
    const l = Math.hypot(ux, uy)
    if (l < 1e-6) continue
    ux /= l; uy /= l
    const vx = -uy, vy = ux
    let uMin = Infinity, uMax = -Infinity, vMin = Infinity, vMax = -Infinity
    for (const h of hull) {
      const pu = h[0] * ux + h[1] * uy
      const pv = h[0] * vx + h[1] * vy
      if (pu < uMin) uMin = pu
      if (pu > uMax) uMax = pu
      if (pv < vMin) vMin = pv
      if (pv > vMax) vMax = pv
    }
    const area = (uMax - uMin) * (vMax - vMin)
    if (area < bestArea) {
      bestArea = area
      best = [
        [uMin * ux + vMin * vx, uMin * uy + vMin * vy],
        [uMax * ux + vMin * vx, uMax * uy + vMin * vy],
        [uMax * ux + vMax * vx, uMax * uy + vMax * vy],
        [uMin * ux + vMax * vx, uMin * uy + vMax * vy],
      ]
    }
  }
  return best
}

function orderQuad(pts) {
  const cx = (pts[0][0] + pts[1][0] + pts[2][0] + pts[3][0]) / 4
  const cy = (pts[0][1] + pts[1][1] + pts[2][1] + pts[3][1]) / 4
  const sorted = pts.slice().sort((a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx))
  // rotate so the top-left (min x+y) comes first, keep clockwise order
  let k = 0
  let bestV = Infinity
  for (let i = 0; i < 4; i++) {
    const v = sorted[i][0] + sorted[i][1]
    if (v < bestV) { bestV = v; k = i }
  }
  return [sorted[k], sorted[(k + 1) % 4], sorted[(k + 2) % 4], sorted[(k + 3) % 4]]
}

function largestComponent(mask, w, h) {
  const n = w * h
  const seen = new Uint8Array(n)
  const stack = []
  let bestPixels = null
  let bestCount = 0
  for (let start = 0; start < n; start++) {
    if (!mask[start] || seen[start]) continue
    const pixels = []
    stack.push(start)
    seen[start] = 1
    while (stack.length) {
      const p = stack.pop()
      pixels.push(p)
      const x = p % w, y = (p / w) | 0
      if (x > 0 && mask[p - 1] && !seen[p - 1]) { seen[p - 1] = 1; stack.push(p - 1) }
      if (x < w - 1 && mask[p + 1] && !seen[p + 1]) { seen[p + 1] = 1; stack.push(p + 1) }
      if (y > 0 && mask[p - w] && !seen[p - w]) { seen[p - w] = 1; stack.push(p - w) }
      if (y < h - 1 && mask[p + w] && !seen[p + w]) { seen[p + w] = 1; stack.push(p + w) }
    }
    if (pixels.length > bestCount) { bestCount = pixels.length; bestPixels = pixels }
  }
  return bestPixels ? { pixels: bestPixels, count: bestCount } : null
}

/* ------------------------------------------------------- strategy B */

function sobelExtremeQuad(g, w, h) {
  const mag = new Float32Array(w * h)
  let maxMag = 0
  for (let y = 2; y < h - 2; y++) {
    for (let x = 2; x < w - 2; x++) {
      const o = y * w + x
      const gx =
        -g[o - w - 1] - 2 * g[o - 1] - g[o + w - 1] +
        g[o - w + 1] + 2 * g[o + 1] + g[o + w + 1]
      const gy =
        -g[o - w - 1] - 2 * g[o - w] - g[o - w + 1] +
        g[o + w - 1] + 2 * g[o + w] + g[o + w + 1]
      const m = Math.hypot(gx, gy)
      mag[o] = m
      if (m > maxMag) maxMag = m
    }
  }
  if (maxMag < 1) return null

  const thresh = maxMag * 0.28
  const mx = Math.round(w * 0.02)
  const my = Math.round(h * 0.02)
  let tl = null, tr = null, br = null, bl = null
  let tlV = Infinity, trV = -Infinity, brV = -Infinity, blV = Infinity
  let count = 0
  for (let y = my; y < h - my; y++) {
    for (let x = mx; x < w - mx; x++) {
      if (mag[y * w + x] < thresh) continue
      count++
      const a = x + y, b = x - y
      if (a < tlV) { tlV = a; tl = [x, y] }
      if (a > brV) { brV = a; br = [x, y] }
      if (b > trV) { trV = b; tr = [x, y] }
      if (b < blV) { blV = b; bl = [x, y] }
    }
  }
  if (count < 40 || !tl) return null
  return [tl, tr, br, bl].map(([x, y]) => [x / w, y / h])
}

/* ------------------------------------------------------- shared */

function fallback() {
  const a = FALLBACK_INSET
  return [[a, a], [1 - a, a], [1 - a, 1 - a], [a, 1 - a]]
}

function quadArea(q) {
  let s = 0
  for (let i = 0; i < 4; i++) {
    const [x1, y1] = q[i]
    const [x2, y2] = q[(i + 1) % 4]
    s += x1 * y2 - x2 * y1
  }
  return Math.abs(s) / 2
}

function isConvex(q) {
  let sign = 0
  for (let i = 0; i < 4; i++) {
    const [ax, ay] = q[i]
    const [bx, by] = q[(i + 1) % 4]
    const [cx, cy] = q[(i + 2) % 4]
    const cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
    const cs = Math.sign(cross)
    if (cs !== 0) {
      if (sign === 0) sign = cs
      else if (cs !== sign) return false
    }
  }
  return true
}

function plausible(q) {
  const area = quadArea(q)
  if (area < 0.12 || area > 0.98) return false
  // side lengths — reject slivers
  let min = Infinity, max = 0
  for (let i = 0; i < 4; i++) {
    const [x1, y1] = q[i]
    const [x2, y2] = q[(i + 1) % 4]
    const len = Math.hypot(x2 - x1, y2 - y1)
    min = Math.min(min, len)
    max = Math.max(max, len)
  }
  if (min < 0.12 || max / min > 7) return false
  return true
}

function score(q) {
  return quadArea(q) * (isConvex(q) ? 1 : 0.25)
}
