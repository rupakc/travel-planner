// Pure helpers for the scratch map: decode the compact Natural Earth data,
// project lon/lat to SVG space, and work out which countries are visited.

export const MAP_WIDTH = 1000
const LAT_MAX = 84
const LAT_MIN = -58
const LON_SPAN = 360
const LAT_SPAN = LAT_MAX - LAT_MIN
export const MAP_HEIGHT = Math.round((MAP_WIDTH * LAT_SPAN) / LON_SPAN)

// Equirectangular projection into [0, MAP_WIDTH] x [0, MAP_HEIGHT] (Antarctica is cropped).
export function project(lon, lat) {
  const x = ((lon + 180) / LON_SPAN) * MAP_WIDTH
  const y = ((LAT_MAX - Math.max(LAT_MIN, Math.min(LAT_MAX, lat))) / LAT_SPAN) * MAP_HEIGHT
  return [x, y]
}

// data = { s: scale, f: [[ISO2, [ring, ...]], ...] }; each ring is a flat,
// delta-encoded integer list (x0, y0, dx1, dy1, ...) in 1/s degrees.
export function decodeCountries(data) {
  const s = data?.s || 10
  return (data?.f || []).map(([code, rings]) => ({
    code,
    rings: rings.map((r) => {
      const pts = []
      let x = 0
      let y = 0
      for (let i = 0; i + 1 < r.length; i += 2) {
        x += r[i]
        y += r[i + 1]
        pts.push([x / s, y / s])
      }
      return pts
    }),
  }))
}

const r1 = (n) => Math.round(n * 10) / 10

export function countryPath(rings) {
  return rings
    .map((ring) => 'M' + ring.map(([lon, lat]) => project(lon, lat).map(r1).join(' ')).join('L') + 'Z')
    .join('')
}

// Upper-cased ISO2 set from the stats shape ([{code, name}] or plain codes).
export function visitedSet(countries) {
  const set = new Set()
  for (const c of countries || []) {
    const code = String(typeof c === 'string' ? c : c?.code || '').toUpperCase()
    if (/^[A-Z]{2}$/.test(code)) set.add(code)
  }
  return set
}

export function regionName(code, lang) {
  try {
    const name = new Intl.DisplayNames([lang], { type: 'region' }).of(code)
    if (name && name !== code) return name
  } catch { /* unsupported locale or code */ }
  return code
}
