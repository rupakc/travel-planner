/**
 * Pure helpers for the fare calendar strip and the Google Flights
 * price-level chip. Dates are ISO `YYYY-MM-DD` strings handled in UTC so
 * day arithmetic never drifts across DST or the viewer's time zone.
 */

const DAY_MS = 86400000
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const LEVELS = new Set(['low', 'typical', 'high'])

const toUtc = (iso) => {
  const [y, m, d] = String(iso).split('-').map(Number)
  return Date.UTC(y, m - 1, d)
}
const toIso = (ms) => new Date(ms).toISOString().slice(0, 10)
const isNum = (v) => typeof v === 'number' && Number.isFinite(v)

/** Both trip dates moved by `offset` days (trip length unchanged). */
export function shiftDates(departure, ret, offset) {
  return {
    departure_date: toIso(toUtc(departure) + offset * DAY_MS),
    return_date: ret ? toIso(toUtc(ret) + offset * DAY_MS) : null,
  }
}

/** Whole days from `from` to `to` (negative when `to` is earlier). */
export function dayOffset(from, to) {
  return Math.round((toUtc(to) - toUtc(from)) / DAY_MS)
}

/** Departure date of the cheapest priced entry, or null when none has a price. */
export function cheapestDeparture(dates) {
  let best = null
  for (const d of dates || []) {
    if (isNum(d.cheapest_usd) && (!best || d.cheapest_usd < best.cheapest_usd)) best = d
  }
  return best ? best.departure_date : null
}

/** Price difference of `entry` vs the selected date, or null if either is unpriced. */
export function fareDelta(entry, selected) {
  if (!isNum(entry?.cheapest_usd) || !isNum(selected?.cheapest_usd)) return null
  return entry.cheapest_usd - selected.cheapest_usd
}

export function formatUsd(amount) {
  return `$${Math.round(amount).toLocaleString('en-US')}`
}

/** "−$45" / "+$30" / "same"; empty for an unknown delta. */
export function formatDelta(delta) {
  if (!isNum(delta)) return ''
  const rounded = Math.round(delta)
  if (rounded === 0) return 'same'
  return `${rounded < 0 ? '−' : '+'}${formatUsd(Math.abs(rounded))}`
}

/** "Tue 3 Nov" */
export function formatDay(iso) {
  const d = new Date(toUtc(iso))
  return `${WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`
}

/** "Tue 3 Nov – Tue 10 Nov" (just the departure for one-way trips). */
export function formatTripRange(departure, ret) {
  return ret ? `${formatDay(departure)} – ${formatDay(ret)}` : formatDay(departure)
}

export function replanPrompt(departure, ret) {
  return `Re-plan for ${formatTripRange(departure, ret)}? This runs a new search.`
}

/**
 * Chip copy for Google Flights' own price verdict, or null when the level
 * is missing or unknown. `level` is low | typical | high.
 */
export function priceInsightsChip(insights) {
  const level = insights?.price_level
  if (!LEVELS.has(level)) return null
  const range = insights.typical_price_range
  const hasRange = Array.isArray(range) && range.length === 2 && range.every(isNum)
  const text = `Fares are ${level} right now${hasRange ? ` · typical ${formatUsd(range[0])}–${formatUsd(range[1])}` : ''}`
  return { level, text }
}

/**
 * Calendar days from the viewer's today to an ISO departure date; 0 for a
 * past, missing or unparseable date.
 */
export function daysUntil(iso, now = new Date()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(iso))) return 0
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.max(0, Math.round((toUtc(iso) - today) / DAY_MS))
}
