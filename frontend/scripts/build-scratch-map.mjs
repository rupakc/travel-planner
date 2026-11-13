// Offline generator: Natural Earth 110m admin-0 countries (public domain)
// -> compact delta-encoded JSON for the scratch map.
// Usage: node scripts/build-scratch-map.mjs ne_110m_admin_0_countries.geojson
import { readFileSync, writeFileSync } from 'node:fs'

const SCALE = 10 // 0.1 degree units
const src = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const out = { s: SCALE, f: [] }
for (const ft of src.features) {
  let code = ft.properties.ISO_A2
  if (code === '-99') code = ft.properties.ISO_A2_EH
  if (!/^[A-Z]{2}$/.test(code) || code === 'AQ') continue
  const g = ft.geometry
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates
  const rings = []
  for (const poly of polys) {
    // Outer rings only: 110m holes (lakes, enclaves) are not worth the bytes.
    const enc = []
    let px = 0
    let py = 0
    poly[0].forEach(([lon, lat], i) => {
      const x = Math.round(lon * SCALE)
      const y = Math.round(lat * SCALE)
      if (i === 0) enc.push(x, y)
      else enc.push(x - px, y - py)
      px = x
      py = y
    })
    rings.push(enc)
  }
  out.f.push([code, rings])
}
writeFileSync(new URL('../src/assets/worldCountries.json', import.meta.url), JSON.stringify(out))
console.log(out.f.length, 'countries')
