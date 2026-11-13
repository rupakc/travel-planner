import { useEffect } from 'react'
import { MapContainer, TileLayer, Polyline, CircleMarker, useMap } from 'react-leaflet'

function Fit({ points }) {
  const map = useMap()
  const sig = points.map((p) => p.join(',')).join(';')
  useEffect(() => {
    map.invalidateSize()
    if (points.length >= 2) map.fitBounds(points, { padding: [24, 24], maxZoom: 14 })
    else if (points.length === 1) map.setView(points[0], 12)
  }, [sig])
  return null
}

// The trip's route on a map: a polyline with a dot at the start and the end.
// Loaded lazily by Recap so Leaflet stays out of the main bundle.
export default function RecapMap({ points, label }) {
  if (!points?.length) return null
  const last = points[points.length - 1]
  return (
    <div className="h-56 sm:h-72 w-full overflow-hidden rounded-xl border border-gray-200" role="img" aria-label={label}
      data-tid="recap.map">
      <MapContainer center={points[0]} zoom={12} style={{ height: '100%', width: '100%' }} scrollWheelZoom={false}>
        <TileLayer
          attribution='&copy; <a data-tid="recap.map-attribution" href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Fit points={points} />
        {points.length > 1 && <Polyline positions={points} pathOptions={{ color: '#0f766e', weight: 4, opacity: 0.85 }} />}
        <CircleMarker center={points[0]} radius={7} pathOptions={{ color: '#0f766e', fillColor: '#ffffff', fillOpacity: 1 }} />
        {points.length > 1 && (
          <CircleMarker center={last} radius={7} pathOptions={{ color: '#0f766e', fillColor: '#0f766e', fillOpacity: 1 }} />
        )}
      </MapContainer>
    </div>
  )
}
