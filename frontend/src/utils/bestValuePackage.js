import { computePlanCost, getBudgetStatus, sameFlight } from './planHelpers'

// Deterministic "best-value package" over the streamed search results.
// Every pick is a real listed item. Agent output is LLM-driven, so every
// number is coerced and anything non-finite counts as unknown.

const FLIGHT_PRICE_WINDOW = 1.15
const MAX_ACTIVITY_PRICE = 30
const MIN_CHEAP_HOTEL_REVIEW = 7
const CAPS = {
  activitiesPerCity: 3,
  activities: 6,
  walkingTours: 3,
  placesPerCity: 2,
  places: 4,
}

const num = (v) => {
  if (typeof v !== 'number' && !(typeof v === 'string' && v.trim() !== '')) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

const listOf = (section) =>
  section && !section.error && Array.isArray(section.results) ? section.results.filter(Boolean) : []

const cityKey = (v) => String(v ?? '').trim().toLowerCase()

// Unknown numbers sort last
const byDesc = (get) => (a, b) => {
  const x = get(a)
  const y = get(b)
  if (x === null && y === null) return 0
  if (x === null) return 1
  if (y === null) return -1
  return y - x
}
const byAsc = (get) => (a, b) => {
  const x = get(a)
  const y = get(b)
  if (x === null && y === null) return 0
  if (x === null) return 1
  if (y === null) return -1
  return x - y
}

// Stable multi-key sort
const sortBy = (arr, ...cmps) =>
  arr
    .map((v, i) => [v, i])
    .sort((a, b) => {
      for (const c of cmps) {
        const r = c(a[0], b[0])
        if (r) return r
      }
      return a[1] - b[1]
    })
    .map(([v]) => v)

const money = (n) => `$${Math.round(n).toLocaleString()}`

// ---- flights ----

const flightPrice = (f) => num(f.price_usd)
const flightStops = (f) => (num(f.outbound?.stops ?? f.stops) ?? 0) + (num(f.return?.stops) ?? 0)
const flightDuration = (f) => {
  const out = num(f.outbound?.duration_minutes ?? f.duration_minutes)
  if (out === null) return null
  return out + (num(f.return?.duration_minutes) ?? 0)
}

function pickFlight(flights) {
  let cands = flights.filter((f) => flightPrice(f) > 0)
  if (cands.some((f) => f.source !== 'estimate')) cands = cands.filter((f) => f.source !== 'estimate')
  if (!cands.length) return null
  const cheapest = Math.min(...cands.map(flightPrice))
  const pool = cands.filter((f) => flightPrice(f) <= cheapest * FLIGHT_PRICE_WINDOW)
  const best = sortBy(pool, byAsc(flightStops), byAsc(flightDuration), byAsc(flightPrice))[0]
  const extra = flightPrice(best) - cheapest
  const reason =
    Math.round(extra) > 0
      ? `Fewer stops or shorter for ${money(extra)} more than the cheapest fare`
      : 'Cheapest fare'
  return { item: best, reason }
}

function pickFlights(flightsSection) {
  if (!flightsSection || flightsSection.error) return { single: null, legs: [] }
  if (flightsSection.legs?.length > 0) {
    const legs = []
    flightsSection.legs.forEach((leg, i) => {
      const pick = pickFlight((Array.isArray(leg?.results) ? leg.results : []).filter(Boolean))
      if (!pick) return
      const legIndex = pick.item.leg_index ?? leg.leg_index ?? i
      const item = pick.item.leg_index === legIndex ? pick.item : { ...pick.item, leg_index: legIndex }
      legs.push({ item, reason: pick.reason, city: pick.item.city ?? leg.to })
    })
    return { single: null, legs: legs.sort((a, b) => a.item.leg_index - b.item.leg_index) }
  }
  return { single: pickFlight(listOf(flightsSection)), legs: [] }
}

// ---- hotels ----

const nightly = (h) => num(h.price_per_night_usd)
const review = (h) => num(h.review_score)

function hotelCandidates(hotelsSection, searchData) {
  let cands = listOf(hotelsSection).filter((h) => nightly(h) > 0)
  const first = searchData?.destinations?.length > 1 ? searchData.destinations[0] : null
  if (first) {
    const inCity = cands.filter((h) => cityKey(h.city) === cityKey(first))
    if (inCity.length) cands = inCity
  }
  return cands
}

function pickHotel(cands, searchData) {
  if (!cands.length) return null
  const starsOf = (h) => {
    const s = num(h.star_rating)
    return s === null ? null : Math.round(s)
  }
  let pool = cands.filter((h) => starsOf(h) === 3)
  if (!pool.length) pool = cands.filter((h) => starsOf(h) === 4)
  if (!pool.length) pool = cands
  const best = sortBy(pool, byDesc(review), byAsc(nightly))[0]
  const stars = starsOf(best)
  const city = searchData?.destinations?.length > 1 ? best.city || searchData.destinations[0] : null
  const label =
    stars === 3
      ? 'Mid-range (3★), best-reviewed in its class'
      : stars > 0
        ? `${stars}★, best-reviewed in its class`
        : 'Best-reviewed in its class'
  return { item: best, reason: city ? `${label} · ${city}` : label }
}

// ---- activities / tours / places ----

function takePerCity(sorted, perCity, total) {
  const counts = new Map()
  const out = []
  for (const x of sorted) {
    const k = x.city ?? ''
    if ((counts.get(k) || 0) >= perCity) continue
    counts.set(k, (counts.get(k) || 0) + 1)
    out.push(x)
    if (out.length >= total) break
  }
  return out
}

function pickActivities(section) {
  const cands = listOf(section).filter((a) => {
    const p = num(a.price_usd)
    return a.name && p !== null && p >= 0 && p <= MAX_ACTIVITY_PRICE
  })
  const sorted = sortBy(cands, byDesc((a) => num(a.similarity_score)), byAsc((a) => num(a.price_usd)))
  return takePerCity(sorted, CAPS.activitiesPerCity, CAPS.activities).map((a) => {
    const p = num(a.price_usd)
    const base = p === 0 ? 'Free' : money(p)
    return { item: a, reason: num(a.similarity_score) >= 0.5 ? `${base} · matches your interests` : base }
  })
}

function pickWalkingTours(section) {
  const sorted = sortBy(
    listOf(section).filter((t) => t.url),
    (a, b) => Number(!!b.top_pick) - Number(!!a.top_pick),
    byDesc((t) => num(t.rating)),
  )
  const perCity = takePerCity(sorted, 1, Infinity)
  const ranked = sortBy(perCity, (a, b) => Number(!!b.top_pick) - Number(!!a.top_pick), byDesc((t) => num(t.rating)))
  return ranked
    .slice(0, CAPS.walkingTours)
    .map((t) => ({ item: t, reason: t.price_note || 'Free walking tour' }))
}

function pickPlaces(section) {
  const free = listOf(section).filter((p) => p.name && num(p.admission_fee_usd) === 0)
  const sorted = sortBy(free, byDesc((p) => num(p.rating)))
  return takePerCity(sorted, CAPS.placesPerCity, CAPS.places).map((p) => ({ item: p, reason: 'Free entry' }))
}

// ---- SIM ----

function tripDays(searchData) {
  const { departure_date: dep, return_date: ret } = searchData || {}
  if (!dep || !ret) return null
  const d = (new Date(ret) - new Date(dep)) / 86400000
  return Number.isFinite(d) ? Math.round(d) + 1 : null
}

function pickSim(section, searchData) {
  const plans = section && !section.error && Array.isArray(section.plans) ? section.plans.filter(Boolean) : []
  const priced = plans.filter((p) => num(p.price_usd) > 0)
  if (!priced.length) return null
  const days = tripDays(searchData)
  const cheapest = (arr) => sortBy(arr, byAsc((p) => num(p.price_usd)))[0]
  if (days !== null) {
    const covering = priced.filter((p) => {
      const v = num(p.validity_days)
      return v === null || v >= days
    })
    if (covering.length) return { item: cheapest(covering), reason: `Covers your ${days}-day trip` }
  }
  return { item: cheapest(priced), reason: 'Cheapest plan' }
}

// ---- builder ----

export function buildBestValuePackage(results, searchData) {
  const r = results || {}
  const flights = pickFlights(r.flights)
  const hotelCands = hotelCandidates(r.hotels, searchData)
  let hotel = pickHotel(hotelCands, searchData)
  if (!flights.single && !flights.legs.length && !hotel) return null

  const activities = pickActivities(r.activities)
  const tours = pickWalkingTours(r.walking_tours)
  const places = pickPlaces(r.places_to_see)
  const sim = pickSim(r.sim, searchData)

  const selectionsFor = (h) => ({
    flight: flights.single?.item ?? null,
    flights: flights.legs.map((l) => l.item),
    hotel: h?.item ?? null,
    activities: activities.map((a) => a.item),
    walking_tours: tours.map((t) => t.item),
    places_to_see: places.map((p) => p.item),
    sim: sim?.item ?? null,
  })

  let selections = selectionsFor(hotel)
  let total = computePlanCost(selections, searchData)

  // Budget fit: only the hotel is ever swapped
  const budget = num(searchData?.budget_usd)
  if (hotel && budget > 0 && total > budget) {
    const cost = (h) => computePlanCost({ hotel: h }, searchData)
    const cheaper = sortBy(
      hotelCands.filter((h) => review(h) === null || review(h) >= MIN_CHEAP_HOTEL_REVIEW),
      byAsc(cost),
    )[0]
    if (cheaper && cost(cheaper) < cost(hotel.item)) {
      hotel = { item: cheaper, reason: 'Cheaper stay to fit your budget' }
      selections = selectionsFor(hotel)
      total = computePlanCost(selections, searchData)
    }
  }

  const items = []
  if (flights.single) items.push({ type: 'flight', ...flights.single })
  flights.legs.forEach((l) => items.push({ type: 'flights', ...l }))
  if (hotel) items.push({ type: 'hotel', ...hotel })
  activities.forEach((a) => items.push({ type: 'activities', ...a, city: a.item.city }))
  tours.forEach((t) => items.push({ type: 'walking_tours', ...t, city: t.item.city }))
  places.forEach((p) => items.push({ type: 'places_to_see', ...p, city: p.item.city }))
  if (sim) items.push({ type: 'sim', ...sim })

  return { items, selections, total, budget: getBudgetStatus(total, searchData?.budget_usd) }
}

// ---- apply / compare ----

const keyed = (key) => (a, b) => a?.[key] != null && a[key] === b?.[key]
const sameHotel = keyed('name')
const sameSim = (a, b) =>
  !!a && !!b && (a.provider != null || a.plan_name != null) && a.provider === b.provider && a.plan_name === b.plan_name
const IDENTITY = { activities: keyed('name'), places_to_see: keyed('name'), walking_tours: keyed('url') }

export function applyPackage(selections, pkg) {
  const sel = selections || {}
  const next = { ...sel }
  const p = pkg.selections
  if (p.flight) next.flight = p.flight
  if (p.flights.length) {
    const covered = new Set(p.flights.map((f) => f.leg_index))
    next.flights = [...(sel.flights || []).filter((f) => !covered.has(f.leg_index)), ...p.flights].sort(
      (a, b) => a.leg_index - b.leg_index,
    )
  }
  if (p.hotel) next.hotel = p.hotel
  if (p.sim) next.sim = p.sim
  for (const [key, same] of Object.entries(IDENTITY)) {
    if (!p[key].length) continue
    const existing = sel[key] || []
    const added = []
    for (const x of p[key]) if (![...existing, ...added].some((e) => same(e, x))) added.push(x)
    next[key] = [...existing, ...added]
  }
  return next
}

export function isPackageApplied(selections, pkg) {
  const p = pkg.selections
  const s = selections || {}
  if (p.flight && !sameFlight(s.flight, p.flight)) return false
  if (!p.flights.every((f) => (s.flights || []).some((e) => sameFlight(e, f)))) return false
  if (p.hotel && !sameHotel(s.hotel, p.hotel)) return false
  if (p.sim && !sameSim(s.sim, p.sim)) return false
  return Object.entries(IDENTITY).every(([key, same]) =>
    p[key].every((x) => (s[key] || []).some((e) => same(e, x))),
  )
}

// Labels of picks the user already made that applying would replace
export function packageConflicts(selections, pkg) {
  const p = pkg.selections
  const s = selections || {}
  const out = []
  const flightClash =
    (p.flight && s.flight && !sameFlight(s.flight, p.flight)) ||
    p.flights.some((f) => (s.flights || []).some((e) => e.leg_index === f.leg_index && !sameFlight(e, f)))
  if (flightClash) out.push('flight')
  if (p.hotel && s.hotel && !sameHotel(s.hotel, p.hotel)) out.push('hotel')
  if (p.sim && s.sim && !sameSim(s.sim, p.sim)) out.push('SIM')
  return out
}
