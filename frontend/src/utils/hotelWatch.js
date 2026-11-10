// Pure helpers for hotel price watches: which stay a hotel card is for (dates,
// guests, rooms) and the spec the backend's hotel source matches to a live
// Google Hotels property. API shapes: docs/API-Reference.md.
import { allocateDays, cityKey } from './mustInclude'
import i18n from '../i18n'
import { intlLocale } from '../i18n/format'
import { isEnglish } from './fareCalendar'
import { formatPrice } from './priceWatch'

const tt = (key, opts) => i18n.t(`alerts:${key}`, opts)

const MAX_ADULTS = 16
const GUESTS_PER_ROOM = 4
const DAY_MS = 86400000


const isoDay = (d) => d.toISOString().slice(0, 10)
const addDays = (iso, n) => isoDay(new Date(Date.parse(`${iso}T00:00:00Z`) + n * DAY_MS))
const nightsBetween = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / DAY_MS)

/**
 * The party as Google Hotels guests. Google Hotels (and our adapter) price
 * adults only, so every traveller — children and seniors too — is a guest;
 * one room for up to 4, then one room per 4.
 */
export function hotelGuests(sd) {
  const counted = (Number(sd?.adults) || 0) + (Number(sd?.seniors) || 0) + (Number(sd?.children) || 0)
  const guests = Math.min(MAX_ADULTS, Math.max(1, counted || Number(sd?.num_travelers) || 1))
  return { adults: guests, rooms: guests <= GUESTS_PER_ROOM ? 1 : Math.ceil(guests / GUESTS_PER_ROOM) }
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
    // A hotel from another city than the trip's isn't this trip's stay
    if (hotel.city && sd.destination && cityKey(hotel.city) !== cityKey(sd.destination)) return null
    stay = { check_in: sd.departure_date, check_out: sd.return_date, city: hotel.city || sd.destination }
  }
  if (!stay.city || nightsBetween(stay.check_in, stay.check_out) < 1) return null
  return stay.check_in > isoDay(now) ? stay : null
}

/** The hotel's AI price for one room and the whole stay (the hotel agent
 * prices one room), or null. */
function perRoomEstimate(hotel, nights) {
  const total = Number(hotel?.total_price_usd)
  if (total > 0) return total
  const nightly = Number(hotel?.price_per_night_usd)
  return nightly > 0 ? Math.round(nightly * nights) : null
}

/** POST /price-watches `hotel` spec for a hotel card, or null if it can't be
 * watched. `estimate_total` is the AI estimate scaled to the rooms watched. */
export function hotelWatchSpec(hotel, sd, now = new Date()) {
  const name = String(hotel?.name || '').trim()
  const stay = name && hotelStay(hotel, sd, now)
  if (!stay) return null
  const spec = { name, city: stay.city, check_in: stay.check_in, check_out: stay.check_out, ...hotelGuests(sd) }
  const perRoom = perRoomEstimate(hotel, nightsBetween(stay.check_in, stay.check_out))
  if (perRoom) spec.estimate_total = perRoom * spec.rooms
  return spec
}

/** '10–14 Dec', '30 Dec – 2 Jan' (UTC calendar days). */
function stayDates(ci, co) {
  if (!isEnglish()) {
    try {
      const fmt = new Intl.DateTimeFormat(intlLocale(i18n.resolvedLanguage || i18n.language), { day: 'numeric', month: 'short', timeZone: 'UTC' })
      return fmt.formatRange(new Date(`${ci}T00:00:00Z`), new Date(`${co}T00:00:00Z`))
    } catch { return `${ci} – ${co}` }
  }
  const fmt = (iso, month) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', ...(month ? { month: 'short' } : {}), timeZone: 'UTC' })
  return ci.slice(0, 7) === co.slice(0, 7) ? `${fmt(ci, false)}–${fmt(co, true)}` : `${fmt(ci, true)} – ${fmt(co, true)}`
}

/**
 * What the dialog shows before the live look: { title, subtitle, price,
 * estimate, estimateLabel, currency }. `price` stays null — the AI estimate
 * is no live price and must not seed the target — and the estimate says
 * what it covers.
 */
export function hotelPreview(hotel, spec) {
  const nights = nightsBetween(spec.check_in, spec.check_out)
  const rooms = spec.rooms || 1
  const parts = [
    stayDates(spec.check_in, spec.check_out),
    tt('hotel.nights', { count: nights }), tt('hotel.guests', { count: spec.adults }), tt('hotel.rooms', { count: rooms }),
  ]
  const perRoom = perRoomEstimate(hotel, nights)
  return {
    title: hotel.name,
    subtitle: parts.join(' · '),
    price: null,
    estimate: spec.estimate_total ?? null,
    estimateLabel: rooms > 1 && perRoom
      ? tt('hotel.estimateRooms', { rooms, price: formatPrice(perRoom) })
      : tt('hotel.estimateOne'),
    currency: 'USD',
  }
}

const fold = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()

/** True when Google Hotels lists the watched property under another name than the card's. */
export function matchedElsewhere(watch) {
  const asked = watch?.subject?.requested_name
  return !!asked && !!watch.title && fold(asked) !== fold(watch.title)
}
