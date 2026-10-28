// Recent searches: the Search form as submitted, stored per user so a past
// trip can be reloaded into the form and tweaked rather than retyped.

const DAY_MS = 86400000
// Expired searches are moved this far out, matching the form's default dates
const SHIFT_DAYS = 7

// Dates are plain YYYY-MM-DD strings; doing the arithmetic in UTC keeps
// daylight-saving changes from skewing the day count.
const toUtc = (iso) => {
  const [y, m, d] = iso.split('-').map(Number)
  return Date.UTC(y, m - 1, d)
}
const fromUtc = (ms) => new Date(ms).toISOString().split('T')[0]

const shortCity = (place) => (place || '').split(',')[0].trim()

/**
 * A submitted search request (from the Search page or the Results page's
 * Search Criteria panel) → the payload POSTed to /api/recent-searches.
 * `destinations` is journey-ordered with the final destination last, so
 * every city before it is a stop on the way.
 */
export function toRecentSearch(searchData) {
  const journey = searchData.destinations || []
  const stops = journey.slice(0, -1).map((city, i) => ({
    city,
    nights: searchData.destination_nights?.[i] ?? null,
  }))
  return {
    origin: searchData.origin,
    destination: searchData.destination,
    departure_date: searchData.departure_date,
    return_date: searchData.return_date || null,
    stops,
    nationality: searchData.nationality || '',
    residence_permits: searchData.residence_permits || [],
    existing_visas: searchData.existing_visas || [],
    interests: searchData.interests || [],
    budget_usd: searchData.budget_usd || null,
    adults: searchData.adults ?? Math.max(1, searchData.num_travelers ?? 1),
    children: searchData.children ?? 0,
    seniors: searchData.seniors ?? 0,
    infants: searchData.infants ?? 0,
    accessibility_needs: searchData.accessibility_needs || [],
    serendipity: searchData.serendipity ?? 0.5,
  }
}

/**
 * A saved search → Search form state. Past dates can't be searched, so they
 * move a week out from `today` while keeping the trip length.
 */
export function recentSearchToForm(search, today) {
  let departure = search.departure_date
  let ret = search.return_date || ''
  const datesShifted = departure < today
  if (datesShifted) {
    const tripLength = ret ? toUtc(ret) - toUtc(departure) : 0
    departure = fromUtc(toUtc(today) + SHIFT_DAYS * DAY_MS)
    ret = ret ? fromUtc(toUtc(departure) + tripLength) : ''
  }

  const adults = search.adults ?? 1
  const children = search.children ?? 0
  const seniors = search.seniors ?? 0
  const infants = search.infants ?? 0

  return {
    form: {
      origin: search.origin,
      destination: search.destination,
      departure_date: departure,
      return_date: ret,
      nationality: search.nationality || '',
      residence_permits: search.residence_permits || [],
      existing_visas: search.existing_visas || [],
      interests: search.interests || [],
      budget_usd: search.budget_usd ? String(search.budget_usd) : '',
      num_travelers: Math.max(1, adults + children + seniors + infants),
      adults, children, seniors, infants,
      accessibility_needs: search.accessibility_needs || [],
      serendipity: search.serendipity ?? 0.5,
    },
    extraStops: (search.stops || []).map((s) => ({ city: s.city, nights: s.nights ? String(s.nights) : '' })),
    datesShifted,
  }
}

const formatDay = (iso, withYear) =>
  new Date(toUtc(iso)).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', ...(withYear ? { year: 'numeric' } : {}), timeZone: 'UTC',
  })

function formatDates(departure, ret) {
  if (!ret) return formatDay(departure, true)
  const sameYear = departure.slice(0, 4) === ret.slice(0, 4)
  return `${formatDay(departure, !sameYear)} – ${formatDay(ret, true)}`
}

/** Short labels for a recent-search card. */
export function describeRecentSearch(search) {
  const route = [search.origin, ...(search.stops || []).map((s) => s.city), search.destination]
    .map(shortCity)
    .join(' → ')
  return {
    route,
    dates: formatDates(search.departure_date, search.return_date),
    interests: search.interests || [],
    travelers: Math.max(1, (search.adults ?? 1) + (search.children ?? 0) + (search.seniors ?? 0) + (search.infants ?? 0)),
  }
}
