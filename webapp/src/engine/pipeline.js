import { createGL, createProgram, makeFullscreenTriangle, bindAttrib, createTargetTexture, uploadSourceTexture } from './gl.js'
import { VERT, WARP_FRAG, GRADE_FRAG } from './shaders.js'
import { quadToUnitSquareInverse, outputSizeFor } from './homography.js'

const PREVIEW_CAP = 1500   // px long side for live interaction
const EXPORT_CAP = 2600    // px long side for the stored / exported page

/**
 * ScanEngine — owns one WebGL2 context and runs the two-pass
 * warp -> grade pipeline. The warped texture is cached, so dragging a
 * slider only re-runs the (cheap) grade pass.
 */
export class ScanEngine {
  constructor(canvas) {
    const { gl } = createGL(canvas)
    this.gl = gl
    this.canvas = canvas
    this.tri = makeFullscreenTriangle(gl)

    this.warpProg = createProgram(gl, VERT, WARP_FRAG)
    this.gradeProg = createProgram(gl, VERT, GRADE_FRAG)

    this.src = null            // { tex, w, h }
    this.warpTarget = null     // { tex, fbo, w, h }
    this._warpKey = ''
    this.paperConf = 0.85
  }

  /** source: ImageBitmap | HTMLCanvasElement | HTMLImageElement */
  setSource(source, width, height) {
    const gl = this.gl
    if (this.src) gl.deleteTexture(this.src.tex)
    const tex = uploadSourceTexture(gl, source)
    this.src = { tex, w: width, h: height }
    this._warpKey = ''
    this.paperConf = estimatePaperConfidence(source, width, height)
  }

  _ensureWarp(corners, cap) {
    const gl = this.gl
    const [w, h] = outputSizeFor(corners, this.src.w, this.src.h, cap)
    const key = cap + '|' + corners.flat().map((n) => n.toFixed(4)).join(',')
    if (key === this._warpKey && this.warpTarget && this.warpTarget.w === w && this.warpTarget.h === h) {
      return this.warpTarget
    }
    if (this.warpTarget) {
      gl.deleteTexture(this.warpTarget.tex)
      gl.deleteFramebuffer(this.warpTarget.fbo)
    }
    const target = createTargetTexture(gl, w, h)
    const H = quadToUnitSquareInverse(corners)

    gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo)
    gl.viewport(0, 0, w, h)
    gl.useProgram(this.warpProg.prog)
    bindAttrib(gl, this.tri, gl.getAttribLocation(this.warpProg.prog, 'a_pos'))
    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, this.src.tex)
    gl.uniform1i(this.warpProg.uniforms.u_src, 0)
    gl.uniformMatrix3fv(this.warpProg.uniforms.u_H, false, H)
    gl.drawArrays(gl.TRIANGLES, 0, 3)

    gl.bindTexture(gl.TEXTURE_2D, target.tex)
    gl.generateMipmap(gl.TEXTURE_2D)
    gl.bindFramebuffer(gl.FRAMEBUFFER, null)

    this._warpKey = key
    this.warpTarget = target
    return target
  }

  _grade(target, opts, toFbo /* optional */) {
    const gl = this.gl
    const { w, h } = target
    const minDim = Math.min(w, h)
    const lod = (px) => Math.max(0.0, Math.log2(Math.max(1, minDim / px)))

    const dst = toFbo || null
    gl.bindFramebuffer(gl.FRAMEBUFFER, dst ? dst.fbo : null)
    gl.viewport(0, 0, dst ? dst.w : w, dst ? dst.h : h)

    gl.useProgram(this.gradeProg.prog)
    bindAttrib(gl, this.tri, gl.getAttribLocation(this.gradeProg.prog, 'a_pos'))
    const u = this.gradeProg.uniforms
    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, target.tex)
    gl.uniform1i(u.u_img, 0)
    gl.uniform1f(u.u_bgLod, lod(26))
    gl.uniform1f(u.u_localLod, lod(95))
    gl.uniform1f(u.u_sharpLod, Math.max(0.55, lod(680)))
    gl.uniform1i(u.u_mode, MODES.indexOf(opts.mode))
    gl.uniform1f(u.u_bw, opts.bw ? 1 : 0)
    gl.uniform1f(u.u_paperConf, this.paperConf)
    gl.uniform1f(u.u_recover, opts.recover ? 1 : 0)
    gl.uniform1f(u.u_sharpen, opts.sharpen ? 1 : 0)
    gl.uniform1f(u.u_brightness, (opts.brightness || 0) / 100)
    gl.uniform1f(u.u_contrast, (opts.contrast || 0) / 100)
    gl.uniform1f(u.u_saturation, (opts.saturation || 0) / 100)
    gl.drawArrays(gl.TRIANGLES, 0, 3)
  }

  /** Live preview straight to the visible canvas. Returns [w,h] drawn. */
  render(corners, opts) {
    if (!this.src) return [0, 0]
    const target = this._ensureWarp(corners, PREVIEW_CAP)
    if (this.canvas.width !== target.w || this.canvas.height !== target.h) {
      this.canvas.width = target.w
      this.canvas.height = target.h
    }
    this._grade(target, opts, null)
    return [target.w, target.h]
  }

  /** Full-resolution grade, returned as a JPEG blob for the page store / export. */
  async toBlob(corners, opts, quality = 0.92) {
    const gl = this.gl
    const target = this._ensureWarp(corners, EXPORT_CAP)
    const out = createTargetTexture(gl, target.w, target.h)
    this._grade(target, opts, out)

    const px = new Uint8Array(target.w * target.h * 4)
    gl.bindFramebuffer(gl.FRAMEBUFFER, out.fbo)
    gl.readPixels(0, 0, target.w, target.h, gl.RGBA, gl.UNSIGNED_BYTE, px)
    gl.bindFramebuffer(gl.FRAMEBUFFER, null)
    gl.deleteTexture(out.tex)
    gl.deleteFramebuffer(out.fbo)

    // readPixels is bottom-up; flip rows into an ImageData
    const cv = document.createElement('canvas')
    cv.width = target.w
    cv.height = target.h
    const ctx = cv.getContext('2d')
    const imgData = ctx.createImageData(target.w, target.h)
    const row = target.w * 4
    for (let y = 0; y < target.h; y++) {
      const s = (target.h - 1 - y) * row
      imgData.data.set(px.subarray(s, s + row), y * row)
    }
    ctx.putImageData(imgData, 0, 0)
    return await new Promise((res) => cv.toBlob(res, 'image/jpeg', quality))
  }

  dispose() {
    const gl = this.gl
    if (this.src) gl.deleteTexture(this.src.tex)
    if (this.warpTarget) {
      gl.deleteTexture(this.warpTarget.tex)
      gl.deleteFramebuffer(this.warpTarget.fbo)
    }
  }
}

export const MODES = ['original', 'photo', 'docs', 'clear']

// Rough "is this a page" score: fraction of the frame that reads as
// bright, low-saturation paper. Feeds the shader's correction gate so a
// photo of a screen / a dark scene isn't blown out — and the mode hint
// (a colourful scene / dark screenshot shouldn't default to "Clear").
export function estimatePaperConfidence(source, w, h) {
  const s = Math.min(1, 160 / Math.max(w, h))
  const sw = Math.max(2, Math.round(w * s))
  const sh = Math.max(2, Math.round(h * s))
  const cv = document.createElement('canvas')
  cv.width = sw
  cv.height = sh
  const ctx = cv.getContext('2d', { willReadFrequently: true })
  ctx.drawImage(source, 0, 0, sw, sh)
  const d = ctx.getImageData(0, 0, sw, sh).data
  let paper = 0
  const n = sw * sh
  for (let i = 0; i < d.length; i += 4) {
    const r = d[i], g = d[i + 1], b = d[i + 2]
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b)
    const sat = mx === 0 ? 0 : (mx - mn) / mx
    if (mx > 150 && sat < 0.22) paper++
  }
  const frac = paper / n
  return Math.max(0.15, Math.min(1, (frac - 0.12) / 0.5 + 0.15))
}
