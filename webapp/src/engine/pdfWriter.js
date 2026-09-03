// Minimal, dependency-free multi-page PDF writer. Each page embeds one
// JPEG verbatim (DCTDecode) fitted to A4, preserving aspect. Keeps the
// export instant and offline — no library, no CDN.

const A4 = [595.28, 841.89] // pt, portrait

/** pages: [{ bytes: Uint8Array, width, height }]  (JPEG bytes + pixel size) */
export function buildPdf(pages) {
  const chunks = []
  const offsets = []
  let length = 0
  const push = (str) => {
    const bytes = typeof str === 'string' ? new TextEncoder().encode(str) : str
    chunks.push(bytes)
    length += bytes.length
  }
  const obj = (n, body) => {
    offsets[n] = length
    push(`${n} 0 obj\n`)
    push(body)
    push('\nendobj\n')
  }

  push('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')

  const nPages = pages.length
  const kids = []
  let objNum = 3 + nPages * 3 // catalog=1, pages=2, then 3 objs per page

  // catalog + pages tree
  obj(1, '<< /Type /Catalog /Pages 2 0 R >>')

  pages.forEach((pg, i) => {
    const pageObj = 3 + i * 3
    const imgObj = pageObj + 1
    const contentObj = pageObj + 2
    kids.push(`${pageObj} 0 R`)

    // fit image to A4, centred
    const [pw, ph] = A4
    const ar = pg.width / pg.height
    let dw = pw, dh = pw / ar
    if (dh > ph) { dh = ph; dw = ph * ar }
    const ox = (pw - dw) / 2
    const oy = (ph - dh) / 2

    obj(pageObj,
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pw.toFixed(2)} ${ph.toFixed(2)}] ` +
      `/Resources << /XObject << /Im${i} ${imgObj} 0 R >> >> /Contents ${contentObj} 0 R >>`)

    const cs = pg.components === 1 ? '/DeviceGray' : '/DeviceRGB'
    offsets[imgObj] = length
    push(`${imgObj} 0 obj\n`)
    push(`<< /Type /XObject /Subtype /Image /Width ${pg.width} /Height ${pg.height} ` +
         `/ColorSpace ${cs} /BitsPerComponent 8 /Filter /DCTDecode /Length ${pg.bytes.length} >>\nstream\n`)
    push(pg.bytes)
    push('\nendstream\nendobj\n')

    const stream = `q\n${dw.toFixed(2)} 0 0 ${dh.toFixed(2)} ${ox.toFixed(2)} ${oy.toFixed(2)} cm\n/Im${i} Do\nQ\n`
    obj(contentObj, `<< /Length ${stream.length} >>\nstream\n${stream}endstream`)
  })

  obj(2, `<< /Type /Pages /Count ${nPages} /Kids [ ${kids.join(' ')} ] >>`)

  // xref
  const xrefStart = length
  const total = objNum // highest obj number used +1-ish; recompute
  const maxObj = 2 + nPages * 3
  push(`xref\n0 ${maxObj + 1}\n`)
  push('0000000000 65535 f \n')
  for (let n = 1; n <= maxObj; n++) {
    const off = (offsets[n] || 0).toString().padStart(10, '0')
    push(`${off} 00000 n \n`)
  }
  push(`trailer\n<< /Size ${maxObj + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`)

  // concat
  const out = new Uint8Array(length)
  let p = 0
  for (const c of chunks) { out.set(c, p); p += c.length }
  return new Blob([out], { type: 'application/pdf' })
}

/** read a JPEG's pixel size + component count from its SOF marker */
export function readJpegInfo(bytes) {
  let i = 2 // skip SOI
  while (i < bytes.length) {
    if (bytes[i] !== 0xff) { i++; continue }
    const marker = bytes[i + 1]
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      const height = (bytes[i + 5] << 8) | bytes[i + 6]
      const width = (bytes[i + 7] << 8) | bytes[i + 8]
      const components = bytes[i + 9]
      return { width, height, components }
    }
    const len = (bytes[i + 2] << 8) | bytes[i + 3]
    i += 2 + len
  }
  return { width: 0, height: 0, components: 3 }
}
