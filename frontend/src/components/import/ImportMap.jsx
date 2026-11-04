import { useEffect, useMemo, useRef } from 'react'
import { MapContainer, TileLayer, Marker, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import { kindOf } from './kinds'

// The preview map: one numbered pin per selected place, coloured by kind.
// Exact (Google-located) places get solid pins; places only known to their
// town are hollow, fanned out around the town centre so none hide another.

function FitBounds({ points }) {
  const map = useMap()
  const signature = points.map((p) => p.join(',')).join(';')
  useEffect(() => {
    if (points.length >= 2) map.fitBounds(points, { padding: [28, 28], maxZoom: 14 })
    else if (points.length === 1) map.setView(points[0], 12)
  }, [signature])
  return null
}

function pinIcon(number, kind, approximate, delayMs) {
  const color = kindOf(kind).color
  const drop = delayMs == null ? '' : `class="import-pin" style="animation-delay:${delayMs}ms;`
  const style = approximate
    ? `background:#fff;color:${color};border:2.5px solid ${color}`
    : `background:${color};color:#fff;border:2px solid #fff`
  return L.divIcon({
    html: `<div ${drop || 'style="'}${style};width:24px;height:24px;border-radius:50%;
      display:flex;align-items:center;justify-content:center;font:700 11px/1 Inter,system-ui,sans-serif;
      box-shadow:0 1px 4px rgba(15,23,42,.35)">${number}</div>`,
    className: '',
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    tooltipAnchor: [0, -14],
  })
}

/** Fan out pins that share a spot (approximate ones sit on the town centre). */
export function spreadPins(places) {
  const groups = new Map()
  for (const p of places) {
    const key = `${p.lat.toFixed(4)},${p.lng.toFixed(4)}`
    groups.set(key, [...(groups.get(key) || []), p])
  }
  const out = []
  for (const group of groups.values()) {
    if (group.length === 1) {
      out.push({ ...group[0], pinLat: group[0].lat, pinLng: group[0].lng })
      continue
    }
    const radius = 0.004 + group.length * 0.0004
    group.forEach((p, i) => {
      const angle = (2 * Math.PI * i) / group.length
      out.push({
        ...p,
        pinLat: p.lat + radius * Math.sin(angle),
        pinLng: p.lng + (radius * Math.cos(angle)) / Math.max(0.2, Math.cos((p.lat * Math.PI) / 180)),
      })
    })
  }
  return out
}

export default function ImportMap({ places }) {
  // Pins drop in once, when the preview first appears; later edits (ticking,
  // renaming) reuse the same icons so nothing jumps.
  const icons = useRef(new Map())
  const firstPaint = useRef(true)
  useEffect(() => { firstPaint.current = false }, [])
  const iconFor = (p, i) => {
    const key = `${p.number}|${p.kind}|${p.approximate ? 1 : 0}`
    if (!icons.current.has(key)) {
      icons.current.set(key, pinIcon(p.number, p.kind, p.approximate, firstPaint.current ? i * 70 : null))
    }
    return icons.current.get(key)
  }
  const pins = useMemo(
    () => spreadPins(places.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lng))),
    [places],
  )
  if (!pins.length) return null
  const points = pins.map((p) => [p.pinLat, p.pinLng])
  return (
    <div className="h-64 overflow-hidden rounded-2xl ring-1 ring-gray-200 sm:h-80" role="region" aria-label="Map of the places found">
      <MapContainer center={points[0]} zoom={12} style={{ height: '100%', width: '100%' }} scrollWheelZoom={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds points={points} />
        {pins.map((p, i) => (
          <Marker key={p.id} position={[p.pinLat, p.pinLng]} icon={iconFor(p, i)}
            alt={p.name} keyboard>
            <Tooltip>
              <strong>{p.name}</strong>
              {p.approximate ? <><br /><span>Approximate location — somewhere in {p.city}</span></> : null}
            </Tooltip>
          </Marker>
        ))}
      </MapContainer>
    </div>
  )
}
