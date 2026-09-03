// Unit-square -> arbitrary-quad projective mapping (Heckbert's classic
// closed-form solve — the same trick every texture-mapping renderer uses
// for a 4-point "pin" warp). Given the four SOURCE corners a scan's page
// occupies (in source-texture UV space, TL/TR/BR/BL order), this returns
// the 3x3 matrix M such that for any destination UV in [0,1]^2,
//   [X Y W]^T = M * [u v 1]^T ,  sourceUV = (X/W, Y/W)
// computed fresh per output pixel in the warp fragment shader — exact
// perspective-correct sampling, no per-vertex interpolation error.
export function quadToUnitSquareInverse(corners) {
  const [[x0, y0], [x1, y1], [x2, y2], [x3, y3]] = corners

  const dx1 = x1 - x2, dx2 = x3 - x2
  const dx3 = x0 - x1 + x2 - x3
  const dy1 = y1 - y2, dy2 = y3 - y2
  const dy3 = y0 - y1 + y2 - y3

  let a, b, c, d, e, f, g, h, i = 1
  if (Math.abs(dx3) < 1e-9 && Math.abs(dy3) < 1e-9) {
    // already affine (a parallelogram) — no perspective term
    a = x1 - x0; b = x2 - x1; c = x0
    d = y1 - y0; e = y2 - y1; f = y0
    g = 0; h = 0
  } else {
    const den = dx1 * dy2 - dx2 * dy1
    g = (dx3 * dy2 - dx2 * dy3) / den
    h = (dx1 * dy3 - dx3 * dy1) / den
    a = x1 - x0 + g * x1
    b = x3 - x0 + h * x3
    c = x0
    d = y1 - y0 + g * y1
    e = y3 - y0 + h * y3
    f = y0
  }

  // column-major flat array for gl.uniformMatrix3fv (transpose=false):
  // columns are [a,d,g] [b,e,h] [c,f,i]
  return new Float32Array([a, d, g, b, e, h, c, f, i])
}

/** Output canvas size (px) for a set of source-space (0..1) corners given
 * the source image's pixel dimensions — keeps the page's real aspect
 * ratio instead of stretching it into a square. */
export function outputSizeFor(corners, srcW, srcH, capLongSide) {
  const P = corners.map(([u, v]) => [u * srcW, v * srcH])
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1])
  const w = Math.max(dist(P[0], P[1]), dist(P[3], P[2]))
  const h = Math.max(dist(P[0], P[3]), dist(P[1], P[2]))
  const long = Math.max(w, h)
  const scale = long > capLongSide ? capLongSide / long : 1
  return [Math.max(2, Math.round(w * scale)), Math.max(2, Math.round(h * scale))]
}
