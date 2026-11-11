// Plan completeness: five parts, 20 points each. Pure; tolerates missing keys.
const WEIGHT = 20

function nightsOf(searchData) {
  const stops = Array.isArray(searchData?.destination_nights) ? searchData.destination_nights : null
  if (stops) {
    const sum = stops.reduce((n, v) => n + (Number(typeof v === 'object' ? v?.nights : v) || 0), 0)
    if (sum >= 1) return sum
  }
  const a = Date.parse(searchData?.departure_date)
  const b = Date.parse(searchData?.return_date)
  if (Number.isFinite(a) && Number.isFinite(b) && b > a) return Math.max(1, Math.round((b - a) / 86400000))
  return 1
}

function itineraryOf(selections, searchData) {
  return searchData?.itinerary || searchData?.results?.itinerary || selections?.itinerary || null
}

function daysFraction(selections, searchData) {
  const days = Array.isArray(itineraryOf(selections, searchData)?.days) ? itineraryOf(selections, searchData).days : []
  const filled = days.filter((d) => Array.isArray(d?.slots) && d.slots.length > 0).length
  return Math.min(1, filled / nightsOf(searchData))
}

/** -> {percent, parts: [{id, done, fraction}]} */
export function planCompleteness(selections, searchData, { visaChecked = false } = {}) {
  const s = selections || {}
  const fractions = {
    flights: s.flight || (Array.isArray(s.flights) && s.flights.length) ? 1 : 0,
    stay: s.hotel ? 1 : 0,
    days: daysFraction(s, searchData),
    visa: visaChecked ? 1 : 0,
    packing: s.packing_list && typeof s.packing_list === 'object' && Object.keys(s.packing_list).length > 0 ? 1 : 0,
  }
  const parts = Object.entries(fractions).map(([id, fraction]) => ({ id, done: fraction >= 1, fraction }))
  return { percent: Math.round(parts.reduce((n, p) => n + WEIGHT * p.fraction, 0)), parts }
}
