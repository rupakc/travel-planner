// Pure helpers for price watches (hotel / activity / trip) next to fare
// watches on the Alerts page. API shapes: docs/API-Reference.md.
import i18n from '../i18n'
import { intlLocale } from '../i18n/format'

const tt = (key, opts) => i18n.t(`alerts:${key}`, opts)
const locale = () => intlLocale(i18n.resolvedLanguage || i18n.language)

const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
const codeOf = (currency) => (typeof currency === 'string' && currency.trim() ? currency.trim() : 'USD')

/** Minor-unit digits a currency normally shows (0 for JPY; 2 when Intl doesn't know the code). */
function currencyDigits(code) {
  try {
    return new Intl.NumberFormat(locale(), { style: 'currency', currency: code }).resolvedOptions().maximumFractionDigits
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
    return new Intl.NumberFormat(locale(), {
      style: 'currency', currency: code, minimumFractionDigits: digits, maximumFractionDigits: digits,
    }).format(amount)
  } catch {
    return `${code} ${amount.toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
  }
}

/** "$" / "€" for a code (the code itself when Intl has no symbol for it). */
export function currencySymbol(currency = 'USD') {
  const code = codeOf(currency)
  try {
    const part = new Intl.NumberFormat(locale(), { style: 'currency', currency: code })
      .formatToParts(0).find(p => p.type === 'currency')
    return part?.value || code
  } catch {
    return code
  }
}

/** Words for labels: "US dollars" for USD, else the code ("EUR"). */
export const currencyLabel = (currency = 'USD') => (codeOf(currency) === 'USD' ? tt('currency.usd') : codeOf(currency))

/** A typed target price (symbols, commas and spaces allowed). */
export function checkPriceTarget(raw) {
  const text = String(raw ?? '')
  const value = Number(text.replace(/[^\d.-]/g, ''))
  if (!text.trim() || !Number.isFinite(value) || value <= 0) {
    return { error: tt('target.errorPrice'), value: null }
  }
  return { error: null, value }
}

/** Latest price vs the price when watching started, in the watch's currency. */
export function priceWatchChange(w) {
  if (!isNum(w?.baseline_price) || !isNum(w?.last_price)) return null
  const delta = Math.round((w.last_price - w.baseline_price) * 100) / 100
  if (Math.abs(delta) < 0.005) return { delta: 0, direction: 'same', text: tt('change.same') }
  const amount = formatPrice(Math.abs(delta), w.currency)
  return delta < 0
    ? { delta, direction: 'down', text: tt('change.less', { amount }) }
    : { delta, direction: 'up', text: tt('change.more', { amount }) }
}

/** Filter chips on the Alerts page, in order. `kind` matches watchKind(). */
const TAB_IDS = ['all', 'flight', 'hotel', 'activity', 'trip']
// label / empty read at use time so they follow a language switch
export const ALERT_TABS = TAB_IDS.map(id => ({
  id,
  get label() { return tt(`tabs.${id}`) },
  get empty() { return id === 'all' ? undefined : tt(`tabs.empty.${id}`) },
}))

/** What the filter shows, for a polite live region: "Showing 1 hotel watch". */
export function filterStatus(tab, n) {
  const t = ALERT_TABS.find(x => x.id === tab) || ALERT_TABS[0]
  return tt(`tabs.status.${t.id}`, { count: n })
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
        return { tone: 'neutral', text: tt('checks.justNow', { price: formatPrice(res.last_price, res.currency) }) }
      }
      return { tone: 'neutral', text: tt('checksPrice.checked') }
    case 'unavailable':
      return { tone: 'warn', text: tt('checksPrice.unavailable') }
    case 'failed':
      return { tone: 'warn', text: tt('checksPrice.failed') }
    case 'errored':
      return { tone: 'warn', text: tt('checksPrice.errored') }
    case 'expired':
      return { tone: 'neutral', text: tt('checksPrice.expired') }
    case 'postponed':
      return { tone: 'warn', text: tt('checksPrice.postponed') }
    case 'deleted':
      return { tone: 'neutral', text: tt('checks.deleted') }
    default:
      return { tone: 'neutral', text: tt('checksPrice.default') }
  }
}

/** Dialog wording per kind ("Watch this hotel" …); unknown kinds read generically. */
const KIND_NOUNS = { hotel: 'hotel', activity: 'activity', trip: 'trip' }
export const kindNoun = (kind) => KIND_NOUNS[kind] || 'price'
