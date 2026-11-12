import { arrangeItinerary } from './itineraryLayout'

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

// Saved-plan shape (PlanViewModal, planExport): selections.itinerary = {days: [{day_number, slots}]},
// with the user's moves/edits in selections.itinerary_layout / itinerary_edits. Days are read the way
// the app displays them (arrangeItinerary).
function daysFraction(selections, searchData) {
  const itinerary = selections?.itinerary
  if (!Array.isArray(itinerary?.days)) return 0
  const days = arrangeItinerary(itinerary, selections.itinerary_layout, selections.itinerary_edits || {}).days || []
  const filled = days.filter((d) => Array.isArray(d?.slots) && d.slots.length > 0).length
  return Math.min(1, filled / nightsOf(searchData))
}

// selections.packing_list is null or the saved state object {categories, total_items, checked_count, ...}.
function hasPacking(p) {
  return !!p && typeof p === 'object' && (p.total_items > 0 || (Array.isArray(p.categories) && p.categories.length > 0))
}

/** -> {percent, parts: [{id, done, fraction}]} */
export function planCompleteness(selections, searchData, { visaChecked = false } = {}) {
  const s = selections || {}
  const fractions = {
    flights: s.flight || (Array.isArray(s.flights) && s.flights.length) ? 1 : 0,
    stay: s.hotel ? 1 : 0,
    days: daysFraction(s, searchData),
    visa: visaChecked ? 1 : 0,
    packing: hasPacking(s.packing_list) ? 1 : 0,
  }
  const parts = Object.entries(fractions).map(([id, fraction]) => ({ id, done: fraction >= 1, fraction }))
  return { percent: Math.round(parts.reduce((n, p) => n + WEIGHT * p.fraction, 0)), parts }
}
