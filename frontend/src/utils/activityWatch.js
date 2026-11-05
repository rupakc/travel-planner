// Pure helpers for activity price watches (GetYourGuide / Viator "from"
// prices as Google shows them). API shape: docs/API-Reference.md.

import { formatPrice } from './priceWatch'

export { formatPrice }

const PROVIDERS = { getyourguide: 'GetYourGuide', viator: 'Viator' }

/** "GetYourGuide" / "Viator" (text only — no logos). */
export const providerName = (p) => PROVIDERS[p] || p || 'the listing'

const fold = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '')
  .toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()

/** True when the listing's title isn't just the AI's name for it. */
export const titleDiffers = (name, title) => !!title && !!name && fold(name) !== fold(title)

/** Travellers on the search: num_travelers, else adults + children + seniors; 1–20. */
export function travellersFrom(sd) {
  const n = Number(sd?.num_travelers)
  let total = Number.isFinite(n) && n >= 1 ? Math.floor(n) : 0
  if (!total) {
    total = ['adults', 'children', 'seniors'].reduce((t, k) => t + (Number(sd?.[k]) > 0 ? Math.floor(Number(sd[k])) : 0), 0)
  }
  return Math.min(Math.max(total || 1, 1), 20)
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

/** Local tomorrow (ISO). A date after it is in the future in every
 * timezone, so the server (which counts in UTC) accepts it too. */
const localTomorrow = (now) => {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)
  const pad = (v) => String(v).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** The itinerary day an activity is scheduled on (ISO), or null. */
export function activityDate(itinerary, name) {
  const target = fold(name)
  if (!target) return null
  for (const day of itinerary?.days || []) {
    const hit = (day.slots || []).some((slot) => {
      const text = fold(slot?.activity)
      return text === target || (target.length >= 6 && text.includes(target))
    })
    if (hit && ISO_DAY.test(day.date || '')) return day.date
  }
  return null
}

/**
 * The spec to watch an activity card's price: { name, city, travellers,
 * date?, estimate_price? }, or null when the card can't be watched (no
 * name / city). `trip` is { searchData, itinerary } from the page. A date
 * that isn't after tomorrow is left out (the watch then runs 180 days).
 */
export function activitySpec(activity, trip = null, now = new Date()) {
  const name = String(activity?.name || '').trim()
  const destination = String(trip?.searchData?.destination || '').split(',')[0]
  const city = String(activity?.city || destination).trim()
  if (!name || !city) return null
  const spec = { name, city, travellers: travellersFrom(trip?.searchData) }
  const date = activityDate(trip?.itinerary, name)
  if (date && date > localTomorrow(now)) spec.date = date
  const estimate = Number(activity?.price_usd)
  if (Number.isFinite(estimate) && estimate > 0) spec.estimate_price = estimate
  return spec
}

/** The watch's currency (the listing's own). */
export const watchCurrency = (w) => w?.currency || w?.subject?.currency || 'USD'

/** Per-person "from" price of the latest look (or the baseline). */
export function perPerson(w) {
  const unit = w?.last_observation?.unit_price
  if (unit != null) return unit
  const total = w?.last_price ?? w?.baseline_price
  const n = w?.subject?.travellers || 1
  return total != null ? total / n : null
}

/** The watch to mark as this card's own after the dialog: not a picked suggestion. */
export const ownWatch = (watch, meta) => (meta?.viaSuggestion ? null : watch)

/**
 * The trip a chat message's activities belong to: the session context it
 * streamed, else its planning destination or trip map, else `fallback`
 * (the page's trip). `{ searchData, itinerary }` or `fallback`.
 */
export function messageTrip(message, fallback = null) {
  const ctx = message?.tripContext
  if (ctx?.destination) return { searchData: ctx, itinerary: null }
  const destination = message?.planDestination || message?.tripMap?.cities?.[0]?.city
  if (!destination) return fallback
  const travellers = message?.tripMap?.num_travelers ?? fallback?.searchData?.num_travelers
  return {
    searchData: travellers != null ? { destination, num_travelers: travellers } : { destination },
    itinerary: null,
  }
}

/** "Watching · from $11.63 pp" (or paused / no price yet). */
export function activityWatchingLabel(w) {
  if (w?.status === 'paused') return 'Watch paused'
  const unit = perPerson(w)
  return unit != null ? `Watching · from ${formatPrice(unit, watchCurrency(w))} pp` : 'Watching'
}
