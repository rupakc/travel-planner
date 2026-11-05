// Pure helpers for price watches (hotel / activity / trip) next to fare
// watches on the Alerts page. API shapes: docs/API-Reference.md.

const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
const codeOf = (currency) => (typeof currency === 'string' && currency.trim() ? currency.trim() : 'USD')

/** Minor-unit digits a currency normally shows (0 for JPY; 2 when Intl doesn't know the code). */
function currencyDigits(code) {
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: code }).resolvedOptions().maximumFractionDigits
  } catch {
    return 2
  }
}

/**
 * A price in its own currency: "$70", "$9.90", "€24", "$398", "$1,234".
 * Cents show only when the amount is under 100 AND not a whole amount (or
 * always with `cents: true`), so deltas read "−$70" / "−$1.73" — the same
 * rule as the backend `price_watch.format_price` used in emails and notices.
 * A code Intl can't use falls back to "CODE 5" / "CODE 5.50".
 */
export function formatPrice(amount, currency = 'USD', { cents = false } = {}) {
  if (!isNum(amount)) return ''
  const code = codeOf(currency)
  const rounded = Math.round(amount * 100) / 100
  const fractional = Math.abs(rounded) < 100 && rounded !== Math.round(rounded)
  const digits = (cents || fractional) && currencyDigits(code) > 0 ? 2 : 0
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency', currency: code, minimumFractionDigits: digits, maximumFractionDigits: digits,
    }).format(amount)
  } catch {
    return `${code} ${amount.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
  }
}

/** "$" / "€" for a code (the code itself when Intl has no symbol for it). */
export function currencySymbol(currency = 'USD') {
  const code = codeOf(currency)
  try {
    const part = new Intl.NumberFormat('en-US', { style: 'currency', currency: code })
      .formatToParts(0).find(p => p.type === 'currency')
    return part?.value || code
  } catch {
    return code
  }
}

/** Words for labels: "US dollars" for USD, else the code ("EUR"). */
export const currencyLabel = (currency = 'USD') => (codeOf(currency) === 'USD' ? 'US dollars' : codeOf(currency))

/** A typed target price (symbols, commas and spaces allowed). */
export function checkPriceTarget(raw) {
  const text = String(raw ?? '')
  const value = Number(text.replace(/[^\d.-]/g, ''))
  if (!text.trim() || !Number.isFinite(value) || value <= 0) {
    return { error: 'Enter a price, like 450.', value: null }
  }
  return { error: null, value }
}

/** Latest price vs the price when watching started, in the watch's currency. */
export function priceWatchChange(w) {
  if (!isNum(w?.baseline_price) || !isNum(w?.last_price)) return null
  const delta = Math.round((w.last_price - w.baseline_price) * 100) / 100
  if (Math.abs(delta) < 0.005) return { delta: 0, direction: 'same', text: 'Same as when you started' }
  const amount = formatPrice(Math.abs(delta), w.currency)
  return delta < 0
    ? { delta, direction: 'down', text: `${amount} less than when you started` }
    : { delta, direction: 'up', text: `${amount} more than when you started` }
}

/** Filter chips on the Alerts page, in order. `kind` matches watchKind(). */
export const ALERT_TABS = [
  { id: 'all', label: 'All', noun: 'watch' },
  { id: 'flight', label: 'Flights', noun: 'flight watch',
    empty: 'No flights watched yet. Search a trip and choose “Watch fare” in the Flights section.' },
  { id: 'hotel', label: 'Hotels', noun: 'hotel watch',
    empty: 'No hotels watched yet. Watch a hotel from its card in your results.' },
  { id: 'activity', label: 'Activities', noun: 'activity watch',
    empty: 'No activities watched yet. Watch an activity from its card in your results.' },
  { id: 'trip', label: 'Trips', noun: 'trip watch',
    empty: 'No trips watched yet. Save a plan, then choose “Watch whole trip”.' },
]

/** What the filter shows, for a polite live region: "Showing 1 hotel watch". */
export function filterStatus(tab, n) {
  const t = ALERT_TABS.find(x => x.id === tab) || ALERT_TABS[0]
  return `Showing ${n} ${t.noun}${n === 1 ? '' : 'es'}`
}

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
        return { tone: 'neutral', text: `Checked just now: ${formatPrice(res.last_price, res.currency)}. Nothing worth an alert yet.` }
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

/** Dialog wording per kind ("Watch this hotel" …); unknown kinds read generically. */
const KIND_NOUNS = { hotel: 'hotel', activity: 'activity', trip: 'trip' }
export const kindNoun = (kind) => KIND_NOUNS[kind] || 'price'
