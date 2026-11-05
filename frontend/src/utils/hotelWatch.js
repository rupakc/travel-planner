// Pure helpers for hotel price watches: which stay a hotel card is for (dates,
// guests, rooms) and the spec the backend's hotel source matches to a live
// Google Hotels property. API shapes: docs/API-Reference.md.
import { formatUsd } from './fareCalendar'
import { allocateDays, cityKey } from './mustInclude'

const MAX_ADULTS = 16
const MAX_ROOMS = 8
const DAY_MS = 86400000

/** Prices on hotel watches. The one place to switch to the shared
 * currency-aware formatter (utils/priceWatch formatPrice) when it lands. */
export const money = (amount, currency = 'USD') => formatUsd(amount)

const isoDay = (d) => d.toISOString().slice(0, 10)
const addDays = (iso, n) => isoDay(new Date(Date.parse(`${iso}T00:00:00Z`) + n * DAY_MS))
const nightsBetween = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / DAY_MS)
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

/** Everyone in the party as Google Hotels guests, two to a room. */
export function hotelGuests(sd) {
  const counted = (Number(sd?.adults) || 0) + (Number(sd?.seniors) || 0) + (Number(sd?.children) || 0)
  const guests = Math.min(MAX_ADULTS, Math.max(1, counted || Number(sd?.num_travelers) || 1))
  return { adults: guests, rooms: Math.min(MAX_ROOMS, Math.ceil(guests / 2)) }
}

/**
 * The stay a hotel card is for: { check_in, check_out, city }, or null when
 * the dates can't be told (no return date, a multi-city hotel we can't place
 * in one of the trip's cities) or check-in is today or past.
 */
export function hotelStay(hotel, sd, now = new Date()) {
  if (!hotel || !sd?.departure_date || !sd?.return_date) return null
  const stops = sd.destinations || []
  let stay
  if (stops.length > 1) {
    const at = stops.findIndex(c => hotel.city && cityKey(c) === cityKey(hotel.city))
    if (at < 0) return null
    const total = Math.max(stops.length, nightsBetween(sd.departure_date, sd.return_date))
    const alloc = allocateDays(stops.length, total, sd.destination_nights)
    const start = alloc.slice(0, at).reduce((t, d) => t + d, 0)
    stay = {
      check_in: addDays(sd.departure_date, start),
      check_out: addDays(sd.departure_date, start + alloc[at]),
      city: hotel.city,
    }
  } else {
    stay = { check_in: sd.departure_date, check_out: sd.return_date, city: hotel.city || sd.destination }
  }
  if (!stay.city || nightsBetween(stay.check_in, stay.check_out) < 1) return null
  return stay.check_in > isoDay(now) ? stay : null
}

/** POST /price-watches `hotel` spec for a hotel card, or null if it can't be watched. */
export function hotelWatchSpec(hotel, sd, now = new Date()) {
  const name = String(hotel?.name || '').trim()
  const stay = name && hotelStay(hotel, sd, now)
  if (!stay) return null
  const spec = { name, city: stay.city, check_in: stay.check_in, check_out: stay.check_out, ...hotelGuests(sd) }
  const nightly = Number(hotel.price_per_night_usd)
  const estimate = Number(hotel.total_price_usd) > 0 ? Number(hotel.total_price_usd)
    : nightly > 0 ? Math.round(nightly * nightsBetween(stay.check_in, stay.check_out)) : null
  if (estimate) spec.estimate_total = estimate
  return spec
}

/** '10–14 Dec', '30 Dec – 2 Jan' (UTC calendar days). */
function stayDates(ci, co) {
  const fmt = (iso, month) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', ...(month ? { month: 'short' } : {}), timeZone: 'UTC' })
  return ci.slice(0, 7) === co.slice(0, 7) ? `${fmt(ci, false)}–${fmt(co, true)}` : `${fmt(ci, true)} – ${fmt(co, true)}`
}

/** What the dialog shows before the live look ({ title, subtitle, price, priceLabel }). */
export function hotelPreview(hotel, spec) {
  const parts = [stayDates(spec.check_in, spec.check_out), plural(nightsBetween(spec.check_in, spec.check_out), 'night'), plural(spec.adults, 'adult')]
  if (spec.rooms > 1) parts.push(plural(spec.rooms, 'room'))
  return {
    title: hotel.name,
    subtitle: parts.join(' · '),
    price: spec.estimate_total ?? null,
    priceLabel: 'AI estimate for the stay',
  }
}

const fold = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()

/** True when Google Hotels lists the watched property under another name than the card's. */
export function matchedElsewhere(watch) {
  const asked = watch?.subject?.requested_name
  return !!asked && !!watch.title && fold(asked) !== fold(watch.title)
}
