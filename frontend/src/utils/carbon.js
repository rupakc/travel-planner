// Request builder for POST /api/carbon/trip (docs/Carbon-Footprint.md).
// The backend does all the arithmetic; this only trims what the page holds
// down to the fields the calculator reads, so the body stays small (the
// endpoint caps it at 512 KB) and a new field on a result never changes it.

export const DIETS = ['mixed', 'meat_heavy', 'pescatarian', 'vegetarian', 'vegan']
export const CATEGORY_KEYS = ['flights', 'stays', 'ground', 'food', 'activities']

const SEARCH_FIELDS = [
  'origin', 'destination', 'destinations', 'destination_nights',
  'departure_date', 'return_date', 'num_travelers', 'adults', 'children', 'seniors',
]

const pick = (obj, keys) => {
  const out = {}
  for (const k of keys) if (obj?.[k] !== undefined && obj?.[k] !== null) out[k] = obj[k]
  return out
}

function trimLeg(leg) {
  if (!leg || typeof leg !== 'object') return undefined
  const out = pick(leg, ['origin', 'destination', 'stops', 'emissions', 'leg_index', 'flight_number', 'departure_date'])
  if (Array.isArray(leg.layovers)) out.layovers = leg.layovers.map((l) => pick(l, ['airport']))
  if (Array.isArray(leg.segments)) out.segments = leg.segments.map((s) => pick(s, ['flight_number', 'origin', 'destination', 'departure_date']))
  return out
}

export function trimFlight(f) {
  if (!f || typeof f !== 'object') return null
  const out = trimLeg(f)
  if (f.outbound) out.outbound = trimLeg(f.outbound)
  if (f.return) out.return = trimLeg(f.return)
  return out
}

const trimHotel = (h) => (h && typeof h === 'object' ? pick(h, ['name', 'city', 'country_code']) : null)

export function trimItinerary(it) {
  const days = Array.isArray(it?.days) ? it.days : null
  if (!days?.length) return null
  return {
    days: days.slice(0, 60).map((d) => ({
      slots: (Array.isArray(d?.slots) ? d.slots : []).slice(0, 12).map((s) => pick(s, ['activity', 'lat', 'lng'])),
    })),
  }
}

const priceOf = (r) => {
  const v = Number(r?.price_usd ?? r?.price)
  return r && (r.price_usd ?? r.price) != null && Number.isFinite(v) && v > 0 ? v : Infinity
}

/** The lowest-priced result (the first among equals; a missing or 0 price,
 * which SerpAPI gives when it has none, sorts last). */
export function cheapest(list) {
  const rs = (Array.isArray(list) ? list : []).filter((r) => r && typeof r === 'object')
  return rs.reduce((best, r) => (best == null || priceOf(r) < priceOf(best) ? r : best), null)
}

const cheapestTrimmed = (list) => {
  const c = trimFlight(cheapest(list))
  return c ? [c] : []
}

/** Body for a whole search result (the Results page card). */
export function carbonRequestFromResults({ searchData, results, diet }) {
  const fl = results?.flights
  let flights = {}
  if (Array.isArray(fl?.legs) && fl.legs.length) {
    flights = { legs: fl.legs.map((l) => ({ results: cheapestTrimmed(l?.results) })) }
  } else if (Array.isArray(fl?.results)) {
    flights = { results: cheapestTrimmed(fl.results) }
  }
  const hotel = trimHotel(results?.hotels?.results?.[0])
  const body = {
    search: pick(searchData, SEARCH_FIELDS),
    results: { flights, hotels: { results: hotel ? [hotel] : [] } },
    diet: DIETS.includes(diet) ? diet : 'mixed',
  }
  const itinerary = trimItinerary(results?.itinerary)
  if (itinerary) body.itinerary = itinerary
  return body
}

/** Body for a plan's selections (the My Plan drawer card). */
export function carbonRequestFromSelections({ searchData, selections, itinerary, diet }) {
  const s = selections || {}
  const body = {
    search: pick(searchData, SEARCH_FIELDS),
    selections: {
      flight: trimFlight(s.flight),
      flights: (s.flights || []).map(trimFlight).filter(Boolean),
      hotel: trimHotel(s.hotel),
      getting_around: (s.getting_around || []).map((o) => pick(o, ['type', 'scope'])),
      activities: (s.activities || []).map((a) => pick(a, ['name'])),
    },
    diet: DIETS.includes(diet) ? diet : 'mixed',
  }
  const it = trimItinerary(itinerary)
  if (it) body.itinerary = it
  return body
}

/** True when a selection has anything the footprint counts beyond meals. */
export function selectionsHaveTravel(selections) {
  const s = selections || {}
  return !!(s.flight || s.flights?.length || s.hotel)
}

/** Share (0-1) as a whole percent, "<1%" for small non-zero shares. */
export function pctLabel(share) {
  if (!(share > 0)) return '0%'
  if (share < 0.005) return '<1%'
  return `${Math.round(share * 100)}%`
}
