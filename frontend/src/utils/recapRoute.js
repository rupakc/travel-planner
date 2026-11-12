import { haversineKm } from './geo'

const finite = (n) => typeof n === 'number' && Number.isFinite(n)
const valid = (s) => finite(s?.lat) && finite(s?.lng) && Math.abs(s.lat) <= 90 && Math.abs(s.lng) <= 180

/**
 * The route the itinerary planned: the coordinates of every slot that has
 * them, in day and slot order (pass the arranged days). Slots without
 * coordinates are skipped. `km` is the haversine sum to one decimal, or null
 * with fewer than two points.
 */
export function plannedRoute(arrangedDays) {
  const points = []
  for (const day of Array.isArray(arrangedDays) ? arrangedDays : []) {
    for (const slot of Array.isArray(day?.slots) ? day.slots : []) {
      if (valid(slot)) points.push([slot.lat, slot.lng])
    }
  }
  if (points.length < 2) return { points, km: null }
  let km = 0
  for (let i = 1; i < points.length; i += 1) {
    km += haversineKm(points[i - 1][0], points[i - 1][1], points[i][0], points[i][1])
  }
  return { points, km: Math.round(km * 10) / 10 }
}
