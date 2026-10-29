// Budget planner: splits the trip budget into Flights / Stay / Activities /
// Everything else and checks the already-loaded results against each share.
// Units follow the My Plan drawer: flight price_usd per person, hotel
// nightly × nights, activity price_usd. Agent prices are LLM output, so any
// non-finite or non-positive price is "unknown": never fits, never "over".

export const PLANNER_KEYS = ['flights', 'stay', 'activities']
const ACTIVITY_SHARE = 0.15
const DEFAULT_NIGHTS = 7

const num = (v) => {
  if (typeof v !== 'number' && !(typeof v === 'string' && v.trim() !== '')) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
const positive = (v) => {
  const n = num(v)
  return n !== null && n > 0 ? n : null
}

const listOf = (section) =>
  section && !section.error && Array.isArray(section.results) ? section.results.filter(Boolean) : []

const median = (nums) => {
  const v = nums.slice().sort((x, y) => x - y)
  const mid = Math.floor(v.length / 2)
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2
}

export function tripNights(searchData) {
  const { departure_date: dep, return_date: ret } = searchData || {}
  if (!dep || !ret) return DEFAULT_NIGHTS
  const d = (new Date(ret) - new Date(dep)) / 86400000
  return Number.isFinite(d) ? Math.max(1, Math.round(d)) : DEFAULT_NIGHTS
}

// Same fields as planHelpers.sameFlight, as a Set-friendly string
export function flightKey(f) {
  return [f?.leg_index ?? '', f?.price_usd, f?.outbound?.airline ?? f?.airline, f?.outbound?.flight_number ?? f?.flight_number].join('|')
}

// Flight legs to check: [{ fares }]; a one-way/round-trip search is one leg
function flightLegs(section) {
  if (!section || section.error) return []
  if (section.legs?.length > 0) {
    return section.legs.map((leg) => ({ fares: (Array.isArray(leg?.results) ? leg.results : []).filter(Boolean) }))
  }
  return [{ fares: listOf(section) }]
}

const cheapestFare = (fares) => {
  const prices = fares.map((f) => positive(f.price_usd)).filter((p) => p !== null)
  return prices.length ? Math.min(...prices) : null
}

// Keep the three categories, put the rest in `other`; if they overshoot the
// total, scale them down proportionally (floored) so other stays ≥ 0.
function fitToTotal({ flights, stay, activities }, total) {
  const parts = { flights, stay, activities }
  const used = flights + stay + activities
  if (used > total) {
    const scale = total / used
    for (const k of PLANNER_KEYS) parts[k] = Math.floor(parts[k] * scale)
  }
  return { ...parts, other: total - (parts.flights + parts.stay + parts.activities) }
}

export function defaultAllocation(searchData, results) {
  const budget = positive(searchData?.budget_usd)
  if (budget === null) return null
  const total = Math.round(budget)
  const r = results || {}

  const legCheapest = flightLegs(r.flights).map((leg) => cheapestFare(leg.fares)).filter((p) => p !== null)
  const flights = legCheapest.length ? Math.round(legCheapest.reduce((t, p) => t + p, 0)) : 0

  const nightlies = listOf(r.hotels).map((h) => positive(h.price_per_night_usd)).filter((p) => p !== null)
  const stay = nightlies.length ? Math.round(median(nightlies) * tripNights(searchData)) : 0

  return fitToTotal({ flights, stay, activities: Math.round(total * ACTIVITY_SHARE) }, total)
}

const sumOf = (a) => a.flights + a.stay + a.activities + a.other

// Move one category; the difference comes from / goes to `other`, clamped so
// `other` never drops below 0. The total stays constant.
export function reallocate(allocation, key, value, total = sumOf(allocation)) {
  if (!PLANNER_KEYS.includes(key)) return allocation
  const rest = PLANNER_KEYS.filter((k) => k !== key).reduce((t, k) => t + allocation[k], 0)
  const v = Math.min(Math.max(0, Math.round(num(value) ?? 0)), Math.max(0, total - rest))
  return { ...allocation, [key]: v, other: total - rest - v }
}

// The user edited the total: `other` absorbs the change first
export function withTotal(allocation, total) {
  const t = Math.max(0, Math.round(num(total) ?? 0))
  return fitToTotal(allocation, t)
}

function fitFlights(section, share) {
  const fits = new Set()
  const over = new Set()
  const legs = flightLegs(section)
  const multi = !!section?.legs?.length
  const cheapest = legs.map((leg) => cheapestFare(leg.fares))
  const cheapestTotal = cheapest.reduce((t, p) => t + (p ?? 0), 0)
  legs.forEach((leg, i) => {
    // A leg with no priced fare is unknown as a whole
    if (cheapest[i] === null) return
    const cap = multi ? (share * cheapest[i]) / cheapestTotal : share
    for (const f of leg.fares) {
      const p = positive(f.price_usd)
      if (p === null) continue
      ;(p <= cap ? fits : over).add(flightKey(f))
    }
  })
  return { fits, over, count: fits.size, total: fits.size + over.size }
}

function fitHotels(section, share, nights) {
  const fits = new Set()
  const over = new Set()
  for (const h of listOf(section)) {
    const nightly = positive(h.price_per_night_usd)
    if (!h.name || nightly === null) continue
    ;(nightly * nights <= share ? fits : over).add(h.name)
  }
  return { fits, over, count: fits.size, total: fits.size + over.size }
}

function pickActivities(section, share) {
  const priced = listOf(section)
    .map((a, i) => ({ a, i, p: num(a.price_usd), s: num(a.similarity_score) }))
    .filter((x) => x.a.name && x.p !== null && x.p >= 0)
  priced.sort((x, y) => {
    if (x.s !== y.s) {
      if (x.s === null) return 1
      if (y.s === null) return -1
      return y.s - x.s
    }
    return x.p - y.p || x.i - y.i
  })
  const picked = new Set()
  let spent = 0
  for (const { a, p } of priced) {
    if (p === 0) picked.add(a.name)
    else if (spent + p <= share) {
      picked.add(a.name)
      spent += p
    }
  }
  return { picked, spent: Math.round(spent * 100) / 100 }
}

export function fitResults(results, allocation, searchData) {
  const r = results || {}
  const nights = tripNights(searchData)
  return {
    hotels: fitHotels(r.hotels, allocation.stay, nights),
    flights: fitFlights(r.flights, allocation.flights),
    activities: pickActivities(r.activities, allocation.activities),
    nights,
  }
}

// Predicates for buildBestValuePackage's { caps } option
export function capsFromFit(fit) {
  return {
    hotel: (h) => fit.hotels.fits.has(h?.name),
    flight: (f) => fit.flights.fits.has(flightKey(f)),
  }
}
