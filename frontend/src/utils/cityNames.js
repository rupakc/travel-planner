// Airport codes → city names for price watches. The search form stores the
// destination as an airport code ("LIS"); watch subjects, their copy and the
// Google queries behind them need the city ("Lisbon").

/** An ALL-CAPS three-letter airport code ("LIS"), as the search form stores. */
export const isAirportCode = (v) => typeof v === 'string' && /^[A-Z]{3}$/.test(v.trim())

/** The city `/airports/search` rows give `code`, or null. */
export function cityForCode(code, rows) {
  const row = (rows || []).find(r => r?.iata_code === code)
  return row?.city || null
}

/** `sd` with its destination and multi-city legs named by `name` (code → city). */
export function withCityNames(sd, name) {
  if (!sd) return sd
  const out = { ...sd }
  if ('destination' in sd) out.destination = name(sd.destination)
  if (Array.isArray(sd.destinations)) out.destinations = sd.destinations.map(name)
  return out
}
