// Pure helpers for price watches (hotel / activity / trip) next to fare
// watches on the Alerts page. API shapes: docs/API-Reference.md.
import { formatUsd } from './fareCalendar'

/** Filter chips on the Alerts page, in order. `kind` matches watchKind(). */
export const ALERT_TABS = [
  { id: 'all', label: 'All' },
  { id: 'flight', label: 'Flights' },
  { id: 'hotel', label: 'Hotels' },
  { id: 'activity', label: 'Activities' },
  { id: 'trip', label: 'Trips' },
]

/** 'flight' for a fare watch, else the price watch's kind. */
export const watchKind = (w) => w?.kind || 'flight'

export const inTab = (w, tab) => tab === 'all' || watchKind(w) === tab

export function countByTab(watches) {
  const counts = Object.fromEntries(ALERT_TABS.map(t => [t.id, 0]))
  for (const w of watches || []) {
    counts.all += 1
    const k = watchKind(w)
    if (k in counts) counts[k] += 1
  }
  return counts
}

/** Fare and price watches have separate ids: keep their DOM ids apart. */
export const watchDomId = (w) => (w.kind ? `price-watch-${w.id}` : `watch-${w.id}`)

export const priceWatchLink = (w) => `/alerts?kind=${w.kind}&watch=${w.id}`

/** Request body for POST /price-watches: the spec rides under its kind. */
export function priceWatchBody(kind, spec, options = {}) {
  return { kind, [kind]: spec, ...options }
}

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${stable(value[k])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

/** Cache key for "is this already watched?" lookups. */
export const matchKey = (kind, spec) => `${kind}|${stable(spec || {})}`

export const isUnavailable = (w) => w?.last_observation?.status === 'unavailable'

/** What one "Check now" of a price watch found, in plain words. */
export function priceCheckMessage(res) {
  switch (res.check_status) {
    case 'checked':
      if (res.notification) return { tone: 'good', text: res.notification.title }
      if (res.last_price != null) {
        return { tone: 'neutral', text: `Checked just now: ${formatUsd(res.last_price)}. Nothing worth an alert yet.` }
      }
      return { tone: 'neutral', text: 'Checked just now.' }
    case 'unavailable':
      return { tone: 'warn', text: 'It isn’t available for your dates right now. We’ll keep checking.' }
    case 'failed':
      return { tone: 'warn', text: 'Live prices didn’t respond. We’ll try again within the hour.' }
    case 'errored':
      return { tone: 'warn', text: 'Checks are on hold after three tries in a row. Use Retry when you’re ready.' }
    case 'expired':
      return { tone: 'neutral', text: 'This watch has ended, so we’ve stopped checking.' }
    case 'postponed':
      return { tone: 'warn', text: 'Live prices are busy right now — we’ll check again tomorrow.' }
    case 'deleted':
      return { tone: 'neutral', text: 'This watch was removed.' }
    default:
      return { tone: 'neutral', text: 'Nothing was checked: this price isn’t being watched right now.' }
  }
}
