/**
 * Pure helpers for fare watches and alerts: trip matching, status and
 * price wording, sparkline geometry, target validation and re-planning.
 * Dates are ISO `YYYY-MM-DD` strings read in UTC.
 */
import i18n from '../i18n'
import { intlLocale } from '../i18n/format'
import { formatUsd, isEnglish, utcDate } from './fareCalendar'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const tt = (key, opts) => i18n.t(`alerts:${key}`, opts)
const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
const parts = (iso) => String(iso).split('-').map(Number)

// ── Trips ────────────────────────────────────────────────────────────────────

/** The fields a fare watch needs, from a search request. */
export function tripFromSearch(sd) {
  if (!sd) return null
  return {
    origin: sd.origin || '',
    destination: sd.destination || '',
    departure_date: sd.departure_date || '',
    return_date: sd.return_date || null,
    num_travelers: sd.num_travelers || 1,
    destinations: sd.destinations || null,
  }
}

export function tripFromPlan(plan) {
  const trip = tripFromSearch(plan?.search_data)
  return trip ? { ...trip, plan_id: plan.id } : null
}

export function tripKey(t) {
  const norm = (v) => String(v || '').trim().toLowerCase()
  return [norm(t.origin), norm(t.destination), t.departure_date, t.return_date || '', t.num_travelers || 1].join('|')
}

/** Single-destination trip with both ends and a departure after today. */
export function isWatchableTrip(trip, now = new Date()) {
  if (!trip?.origin || !trip?.destination || !trip?.departure_date) return false
  if (trip.destinations && trip.destinations.length > 1) return false
  return trip.departure_date > now.toISOString().slice(0, 10)
}

/** Cheapest flight card of a single-city flights result (the watch's
 * "today" price), or null. Multi-city results don't count. */
export function cheapestFlightPrice(flights) {
  if (!flights || flights.legs?.length) return null
  const prices = (flights.results || []).map(r => r.price_usd).filter(p => isNum(p) && p > 0)
  return prices.length ? Math.min(...prices) : null
}

// ── Labels ───────────────────────────────────────────────────────────────────

const city = (label, code) => (String(label || '').split(',')[0].trim()) || String(code || '').split(',')[0]

export function routeLabel(w) {
  return `${city(w.origin_label, w.origin_code)} → ${city(w.destination_label, w.destination_code)}`
}

function intlRange(dep, ret) {
  try {
    const sameYear = !ret || dep.slice(0, 4) === ret.slice(0, 4)
    const lng = i18n.resolvedLanguage || i18n.language
    const fmt = new Intl.DateTimeFormat(intlLocale(lng), {
      day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }), timeZone: 'UTC',
    })
    return ret ? fmt.formatRange(utcDate(dep), utcDate(ret)) : fmt.format(utcDate(dep))
  } catch {
    return ret ? `${dep} – ${ret}` : dep
  }
}

/** "1–8 Dec", "28 Nov – 5 Dec", "28 Dec 2026 – 4 Jan 2027", "1 Dec". */
export function formatDateRange(dep, ret) {
  if (!isEnglish()) return intlRange(dep, ret)
  const [y1, m1, d1] = parts(dep)
  if (!ret) return `${d1} ${MONTHS[m1 - 1]}`
  const [y2, m2, d2] = parts(ret)
  if (y1 !== y2) return `${d1} ${MONTHS[m1 - 1]} ${y1} – ${d2} ${MONTHS[m2 - 1]} ${y2}`
  if (m1 !== m2) return `${d1} ${MONTHS[m1 - 1]} – ${d2} ${MONTHS[m2 - 1]}`
  return `${d1}–${d2} ${MONTHS[m2 - 1]}`
}

export function travellersLabel(n) {
  return tt('travellersTotal', { count: n })
}

/** Text for a "watched" entry point: "Watching · $454". */
export function watchingLabel(w) {
  if (w.status === 'paused') return tt('btn.watchPaused')
  return isNum(w.last_price) ? tt('btn.watchingPrice', { price: formatUsd(w.last_price) }) : tt('btn.watching')
}

// ── Status + change ──────────────────────────────────────────────────────────

const TONES = { pending: 'sky', watching: 'sky', dropped: 'emerald', paused: 'slate', expired: 'slate', problem: 'amber' }

export function watchStatus(w) {
  let key = 'watching'
  if (w.status === 'paused') key = 'paused'
  else if (w.status === 'expired') key = 'expired'
  else if (w.status === 'error') key = 'problem'
  else if (!isNum(w.baseline_price)) key = 'pending'
  else if (isNum(w.last_price) && w.last_price < w.baseline_price - 0.5) key = 'dropped'
  return { key, label: tt(`status.${key}`), tone: TONES[key] }
}

/** Latest price vs the price when watching started. */
export function priceChange(w) {
  if (!isNum(w.baseline_price) || !isNum(w.last_price)) return null
  const delta = Math.round(w.last_price - w.baseline_price)
  if (delta === 0) return { delta: 0, direction: 'same', text: tt('change.same') }
  const amount = formatUsd(Math.abs(delta))
  return delta < 0
    ? { delta, direction: 'down', text: tt('change.less', { amount }) }
    : { delta, direction: 'up', text: tt('change.more', { amount }) }
}

// ── Sparkline ────────────────────────────────────────────────────────────────

/**
 * Points for a price sparkline (higher price = higher on screen), with the
 * target price folded into the scale. Null when there is no price.
 */
export function sparkGeometry(history, { width, height, pad = 2, target = null }) {
  const prices = (history || []).map(h => h.price).filter(isNum)
  if (!prices.length) return null
  const scale = isNum(target) ? [...prices, target] : prices
  const min = Math.min(...scale)
  const max = Math.max(...scale)
  const span = max - min
  const inner = height - pad * 2
  const yOf = (p) => (span === 0 ? height / 2 : pad + (1 - (p - min) / span) * inner)
  const step = prices.length > 1 ? width / (prices.length - 1) : 0
  const points = prices.map((price, i) => ({
    x: prices.length > 1 ? Math.round(i * step * 100) / 100 : width,
    y: Math.round(yOf(price) * 100) / 100,
    price,
  }))
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${p.x} ${p.y}`).join(' ')
  return {
    points, line, min, max,
    area: `${line} L${points[points.length - 1].x} ${height} L${points[0].x} ${height} Z`,
    targetY: isNum(target) ? Math.round(yOf(target) * 100) / 100 : null,
  }
}

// ── Time ─────────────────────────────────────────────────────────────────────

export function relativeTime(iso, now = new Date()) {
  if (!iso) return ''
  const secs = (now - new Date(iso)) / 1000
  if (secs < 60) return tt('time.justNow')
  const mins = Math.floor(secs / 60)
  if (mins < 60) return tt('time.minAgo', { count: mins })
  const hours = Math.floor(mins / 60)
  if (hours < 24) return tt('time.hourAgo', { count: hours })
  const days = Math.floor(hours / 24)
  return days === 1 ? tt('time.yesterday') : tt('time.daysAgo', { count: days })
}

export function untilTime(iso, now = new Date()) {
  if (!iso) return ''
  const mins = Math.round((new Date(iso) - now) / 60000)
  if (mins <= 0) return tt('time.soon')
  if (mins < 60) return tt('time.inMin', { count: mins })
  const hours = Math.round(mins / 60)
  if (hours < 24) return tt('time.inHours', { count: hours })
  return tt('time.inDays', { count: Math.round(hours / 24) })
}

// ── Target ───────────────────────────────────────────────────────────────────

const roundDown5 = (v) => Math.floor(v / 5) * 5

/** Pre-filled target: the low end of Google's typical range if it's below
 * today's price, else 10 % under today's price. */
export function defaultTarget(insights, price) {
  const low = insights?.typical_price_range?.[0]
  if (isNum(low) && (!isNum(price) || low < price)) return roundDown5(low)
  return isNum(price) ? roundDown5(price * 0.9) : ''
}

export function checkTarget(raw, price) {
  const value = Number(String(raw ?? '').replace(/[$,\s]/g, ''))
  if (String(raw ?? '').trim() === '' || !Number.isFinite(value) || value <= 0) {
    return { error: tt('target.errorUsd'), note: null, value: null }
  }
  const note = isNum(price) && value >= price
    ? tt('target.note', { price: formatUsd(price) })
    : null
  return { error: null, note, value }
}

/** Where today's price sits on Google's typical range, 0–100 (clamped). */
export function rangePosition(range, price) {
  if (!Array.isArray(range) || range.length !== 2 || !isNum(price)) return null
  const [lo, hi] = range
  if (!(hi > lo)) return null
  return Math.max(0, Math.min(100, ((price - lo) / (hi - lo)) * 100))
}

// ── Re-plan ──────────────────────────────────────────────────────────────────

/** A full search request for the watched trip (optionally its cheapest
 * nearby dates), filled from the traveller's saved preferences. */
export function replanSearchData(w, prefs, { cheapest = false } = {}) {
  let dep = w.departure_date
  let ret = w.return_date || null
  if (cheapest) {
    const latest = [...(w.history || [])].reverse().find(h => h.cheapest_departure_date)
    if (latest) { dep = latest.cheapest_departure_date; ret = latest.cheapest_return_date || null }
  }
  const p = prefs || {}
  return {
    origin: w.origin_label || w.origin_code,
    destination: w.destination_label || w.destination_code,
    departure_date: dep,
    return_date: ret,
    num_travelers: w.num_travelers,
    adults: w.num_travelers,
    children: 0, seniors: 0, infants: 0,
    nationality: p.nationality || '',
    interests: p.interests || [],
    residence_permits: p.residence_permits || [],
    existing_visas: p.existing_visas || [],
    accessibility_needs: p.accessibility_needs || [],
    budget_usd: null,
    destinations: null,
    destination_nights: null,
  }
}

// ── Notifications ────────────────────────────────────────────────────────────

export function notificationLink(n) {
  const data = n?.data || {}
  if (typeof data.link === 'string' && data.link.startsWith('/trips/')) return data.link
  if (data.links?.alerts) return data.links.alerts
  return data.watch_id ? `/alerts?watch=${data.watch_id}` : '/alerts'
}

/** The newest item with an id above `seenId` (items newest first). */
export function newestUnseen(items, seenId) {
  const first = (items || [])[0]
  return first && first.id > seenId ? first : null
}
