import { useEffect, useMemo, useState } from 'react'
import { airportCity } from '../services/api'
import { isAirportCode } from '../utils/cityNames'

// code → city name, or null when the lookup found none or failed (the
// backend then names the city itself). Shared by every watch button.
const known = new Map()
const pending = new Map()

function lookup(code) {
  if (!pending.has(code)) {
    pending.set(code, Promise.resolve()
      .then(() => airportCity(code))
      .then(city => { known.set(code, city || null) }, () => { known.set(code, null) }))
  }
  return pending.get(code)
}

/**
 * `name(value)` turning any airport code among `values` into its city
 * ("LIS" → "Lisbon", other text unchanged), or null while a code is still
 * being looked up (local airport data — no live price calls).
 */
export function useAirportCities(values) {
  const key = [...new Set(values.filter(isAirportCode).map(v => v.trim()))].sort().join(',')
  const ready = !key || key.split(',').every(c => known.has(c))
  const [, settled] = useState(0)
  useEffect(() => {
    if (ready) return undefined
    let live = true
    Promise.all(key.split(',').map(lookup)).then(() => { if (live) settled(n => n + 1) })
    return () => { live = false }
  }, [key, ready])
  return useMemo(() => (ready
    ? (v) => (isAirportCode(v) && known.get(v.trim())) || v
    : null), [ready])
}
