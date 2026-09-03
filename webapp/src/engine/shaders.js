// GLSL ES 3.00 (WebGL2). Two full-screen passes:
//   1. WARP  — perspective-correct unwarp of the detected page quad
//   2. GRADE — illumination flatten + tone + local contrast + unsharp +
//              snap-to-white + B&W + the live Enhance sliders, one pass
// The GRADE pass leans on the warp texture's mip chain (generated once,
// GPU-native) as a free multi-radius blur: a coarse LOD is the "paper
// level" background estimate, a mid LOD the local mean, a tight LOD the
// unsharp reference. That's the "own way" here — the desktop build reran
// ~50 CPU passes per tweak; this is a couple of GPU passes, sub-frame.

export const VERT = `#version 300 es
in vec2 a_pos;
out vec2 v_uv;
void main() {
  // canvas-top reads v_uv.y = 0 (top-left origin, y-down) — see gl.js
  v_uv = vec2(a_pos.x * 0.5 + 0.5, 1.0 - (a_pos.y * 0.5 + 0.5));
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`

export const WARP_FRAG = `#version 300 es
precision highp float;
in vec2 v_uv;
out vec4 outColor;
uniform sampler2D u_src;
uniform mat3 u_H;          // dest uv -> source uv (projective)
void main() {
  // homography expects dest-v measured downward from the crop's top edge;
  // v_uv.y here runs the other way (see the shared vertex shader), so flip it
  vec3 p = u_H * vec3(v_uv.x, 1.0 - v_uv.y, 1.0);
  vec2 uv = p.xy / p.z;
  vec3 c = texture(u_src, clamp(uv, 0.0, 1.0)).rgb;
  float inside = step(0.0, uv.x) * step(uv.x, 1.0) * step(0.0, uv.y) * step(uv.y, 1.0);
  outColor = vec4(mix(vec3(1.0), c, inside), 1.0);   // pad outside crop with white
}`

export const GRADE_FRAG = `#version 300 es
precision highp float;
in vec2 v_uv;
out vec4 outColor;

uniform sampler2D u_img;      // the warped page, mipmapped
uniform float u_bgLod;        // coarse -> paper-level background
uniform float u_localLod;     // mid    -> local mean (CLAHE-ish)
uniform float u_sharpLod;     // tight  -> unsharp reference
uniform int   u_mode;         // 0 original, 1 photo, 2 docs, 3 clear
uniform float u_bw;           // 0 colour, 1 mono
uniform float u_paperConf;    // 0..1
uniform float u_recover;      // 0..1
uniform float u_sharpen;      // 0..1 — extra unsharp on top
uniform float u_brightness;   // -1..1
uniform float u_contrast;     // -1..1
uniform float u_saturation;   // -1..1

const vec3 LUMA = vec3(0.299, 0.587, 0.114);
float luma(vec3 c) { return dot(c, LUMA); }

float whiten(float x, float start, float wp) {
  float t = clamp((x - start) / max(wp - start, 0.001), 0.0, 1.0);
  t = t * t * (3.0 - 2.0 * t);
  return x + t * (1.0 - x);
}
float darken(float x, float start, float bp) {
  float t = clamp((start - x) / max(start - bp, 0.001), 0.0, 1.0);
  t = t * t * (3.0 - 2.0 * t);
  return x - t * x;
}

// Drive anything darker than the paper level down toward black so text reads
// solid, whatever its ink colour, and before any B&W conversion. lo is the
// tone below which a pixel counts as ink; k is how hard to crush it. Hue is
// preserved (all channels scale by the same luma ratio). Saturated pixels
// (a coloured letterhead band, a stamp) are content, not ink — spared.
vec3 deepenInk(vec3 c, float lo, float k) {
  float L = max(dot(c, LUMA), 0.0008);
  float mx = max(max(c.r, c.g), c.b);
  float mn = min(min(c.r, c.g), c.b);
  float sat = mx > 0.001 ? (mx - mn) / mx : 0.0;
  float g = 1.0 + 3.4 * k;
  float crushed = pow(clamp(L / lo, 0.0, 1.0), g) * lo;
  float t = smoothstep(lo * 1.45, lo * 0.28, L) * (1.0 - smoothstep(0.22, 0.5, sat));
  float Ln = mix(L, crushed, t);
  return c * (Ln / L);
}

vec3 applyEnhance(vec3 c) {
  c += u_brightness * 0.5;
  c = (c - 0.5) * (1.0 + u_contrast) + 0.5;
  float g = dot(clamp(c, 0.0, 1.0), LUMA);
  c = mix(vec3(g), c, 1.0 + u_saturation);
  return clamp(c, 0.0, 1.0);
}

void main() {
  vec3 src      = texture(u_img, v_uv).rgb;
  vec3 local    = textureLod(u_img, v_uv, u_localLod).rgb;
  vec3 sharpRef = textureLod(u_img, v_uv, u_sharpLod).rgb;

  // Paper level = the local coarse blur, but taken as the BRIGHTEST of the
  // reading here and a few readings pulled toward the page centre. Near an
  // edge (where CLAMP_TO_EDGE would otherwise average in the dark crop
  // border and starve the flatten — the grey top strip) this recovers the
  // real paper level a little further in; over a big dark feature (QR, the
  // photo) it lifts to the surrounding paper instead of leaving a ghost.
  vec3 bg = textureLod(u_img, v_uv, u_bgLod).rgb;
  vec2 toC = (vec2(0.5) - v_uv);
  bg = max(bg, textureLod(u_img, v_uv + toC * 0.12, u_bgLod).rgb);

  if (u_mode == 0) {                       // ORIGINAL — sliders (+ optional sharpen)
    vec3 s = src;
    if (u_sharpen > 0.5) s = clamp(s + 0.6 * (s - sharpRef), 0.0, 1.0);
    outColor = vec4(applyEnhance(s), 1.0);
    return;
  }

  // 1. illumination flatten — divide by the paper level
  float bgL = luma(bg);
  vec3 corrected = src / max(bg, vec3(0.06));
  // the mode choice IS the document confidence — don't let the whole-photo
  // paperConf (which a card on a busy surface drags down) starve the
  // flatten, or a shadowed corner / the top strip stays grey
  float docGate = mix(u_paperConf, 1.0, 0.7);
  float gate = smoothstep(0.32, 0.72, bgL) * docGate;
  vec3 img = mix(src, clamp(corrected, 0.0, 1.35), gate);

  // "paperness" — low only where the coarse background is genuinely dark
  // (a slab of surround a loose crop caught), so that stays muted grey
  // rather than a black slab; a merely shadowed part of the page keeps ~1.
  float paperness = clamp(smoothstep(0.26, 0.56, bgL) + 0.18, 0.0, 1.0);

  if (u_mode == 1) {                       // PHOTO — gentle lift + a light ink deepen
    img = mix(src, img, 0.55 * u_paperConf + 0.1);
    img = deepenInk(clamp(img, 0.0, 1.0), 0.50, 0.30 * paperness);
    if (u_sharpen > 0.5) img = clamp(img + 0.5 * (img - sharpRef), 0.0, 1.0);
    outColor = vec4(applyEnhance(clamp(img, 0.0, 1.0)), 1.0);
    return;
  }

  // 2. faded-ink recovery (opt-in)
  if (u_recover > 0.001) {
    float deficit = clamp(luma(local) - luma(img), 0.0, 1.0);
    float faint = smoothstep(0.03, 0.16, deficit) * (1.0 - smoothstep(0.30, 0.50, deficit));
    float edge = clamp(length(src - sharpRef) * 6.0, 0.0, 1.0);
    img = clamp(img - faint * edge * u_recover * (0.28 + deficit * 0.6), 0.0, 1.0);
  }

  // 3. local contrast — soft CLAHE stand-in
  float localBoost = 1.0 + ((u_mode == 3) ? 0.34 : 0.20) * paperness;
  img = clamp(mix(local, img, localBoost), 0.0, 1.0);

  // 4. B&W first for the doc modes — once colour is gone a coloured band
  //    should read as ink, not be spared by deepenInk's saturation guard
  img = mix(img, vec3(luma(img)), u_bw);

  // 5. highlight lift — pull the flattened paper up to white
  float wStart = (u_mode == 3) ? 0.78 : 0.83;
  float wPoint = (u_mode == 3) ? 0.95 : 0.99;
  float L0 = max(luma(img), 0.0008);
  img = clamp(img * (whiten(L0, wStart, wPoint) / L0), 0.0, 1.0);

  // 6. deepen ink toward solid black (Clear harder than Docs)
  img = deepenInk(img, (u_mode == 3) ? 0.74 : 0.62, ((u_mode == 3) ? 0.85 : 0.58) * paperness);

  // 7. snap flat, near-white, low-detail regions the last step to pure paper
  float mx = max(max(img.r, img.g), img.b);
  float mn = min(min(img.r, img.g), img.b);
  float sat = mx > 0.001 ? (mx - mn) / mx : 0.0;
  float detail = clamp(length(img - local) * 8.0, 0.0, 1.0);
  float nearWhite = smoothstep(0.86, 0.98, luma(img))
                  * (1.0 - detail)
                  * (1.0 - smoothstep(0.06, 0.20, sat));
  img = mix(img, vec3(1.0), nearWhite * paperness * ((u_mode == 3) ? 0.9 : 0.6));

  // 8. unsharp (Sharpen toggle roughly doubles it)
  float amt = ((u_mode == 3) ? 1.0 : 0.78) * (u_sharpen > 0.5 ? 2.1 : 1.0);
  img = clamp(img + amt * (img - sharpRef), 0.0, 1.0);

  outColor = vec4(applyEnhance(img), 1.0);
}`
