import { useEffect } from 'react'
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet'
import L from 'leaflet'

import markerIconUrl from 'leaflet/dist/images/marker-icon.png'
import markerIcon2xUrl from 'leaflet/dist/images/marker-icon-2x.png'
import markerShadowUrl from 'leaflet/dist/images/marker-shadow.png'

delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconUrl: markerIconUrl,
  iconRetinaUrl: markerIcon2xUrl,
  shadowUrl: markerShadowUrl,
})

function FitBounds({ positions }) {
  const map = useMap()
  useEffect(() => {
    if (positions.length >= 2) {
      map.fitBounds(positions, { padding: [30, 30] })
    } else if (positions.length === 1) {
      map.setView(positions[0], 13)
    }
  }, []) // intentional: fit bounds once on mount
  return null
}

function haversineKm(lat1, lng1, lat2, lng2) {
  const R = 6371
  const dL = (lat2 - lat1) * Math.PI / 180
  const dG = (lng2 - lng1) * Math.PI / 180
  const a =
    Math.sin(dL / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dG / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function nearestNeighborOrder(stops) {
  if (stops.length <= 2) return stops
  const visited = new Array(stops.length).fill(false)
  const result = [stops[0]]
  visited[0] = true
  let cur = 0
  for (let i = 1; i < stops.length; i++) {
    let best = -1
    let minD = Infinity
    for (let j = 0; j < stops.length; j++) {
      if (!visited[j]) {
        const d = haversineKm(stops[cur].lat, stops[cur].lng, stops[j].lat, stops[j].lng)
        if (d < minD) { minD = d; best = j }
      }
    }
    if (best === -1) break
    visited[best] = true
    result.push(stops[best])
    cur = best
  }
  return result
}

function makeNumberedIcon(num, color = '#0d9488') {
  return L.divIcon({
    html: `<div style="background:${color};color:#fff;width:22px;height:22px;border-radius:50%;
           display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;
           border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35)">${num}</div>`,
    className: '',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    popupAnchor: [0, -14],
  })
}

const CITY_COLORS = ['#0d9488', '#6366f1', '#f59e0b', '#ef4444', '#8b5cf6']

export default function TripMap({ days }) {
  if (!days?.length) return null

  const cityList = [...new Set(days.map(d => d.city).filter(Boolean))]
  const cityColor = Object.fromEntries(
    cityList.map((c, i) => [c, CITY_COLORS[i % CITY_COLORS.length]])
  )

  const allStops = []
  days.forEach(day => {
    const dayStops = (day.slots || [])
      .filter(
        s =>
          s.lat != null &&
          s.lng != null &&
          s.lat >= -90 && s.lat <= 90 &&
          s.lng >= -180 && s.lng <= 180
      )
      .map(s => ({
        lat: s.lat,
        lng: s.lng,
        activity: s.activity,
        location: s.location,
        time: s.time_of_day,
        day: day.day_number,
        city: day.city || s.city || null,
      }))
    allStops.push(...nearestNeighborOrder(dayStops))
  })

  if (allStops.length === 0) return null

  const positions = allStops.map(s => [s.lat, s.lng])
  const initialCenter = positions[0]

  return (
    <div className="rounded-xl overflow-hidden border border-gray-200 mt-3" style={{ height: 300 }}>
      <MapContainer
        center={initialCenter}
        zoom={12}
        style={{ height: '100%', width: '100%' }}
        scrollWheelZoom={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds positions={positions} />
        <Polyline
          positions={positions}
          color="#0d9488"
          weight={2}
          opacity={0.55}
          dashArray="7 5"
        />
        {allStops.map((stop, i) => {
          const color = stop.city ? (cityColor[stop.city] || '#0d9488') : '#0d9488'
          return (
            <Marker key={i} position={[stop.lat, stop.lng]} icon={makeNumberedIcon(i + 1, color)}>
              <Popup>
                <div style={{ fontSize: 12, lineHeight: 1.4 }}>
                  <p style={{ fontWeight: 600, margin: 0 }}>{stop.activity}</p>
                  {stop.location && (
                    <p style={{ color: '#6b7280', margin: '2px 0 0' }}>{stop.location}</p>
                  )}
                  <p style={{ color: '#0d9488', margin: '2px 0 0' }}>
                    Day {stop.day}{stop.city ? ` · ${stop.city}` : ''} · {stop.time}
                  </p>
                </div>
              </Popup>
            </Marker>
          )
        })}
      </MapContainer>
    </div>
  )
}
