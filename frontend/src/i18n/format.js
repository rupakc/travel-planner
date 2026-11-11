// Locale-aware formatting through Intl.*, following the current i18n
// language. Every helper falls back to something readable instead of throwing.
import i18n from 'i18next'
import { intlLocale } from './languages'

export { intlLocale }

const locale = () => intlLocale(i18n.resolvedLanguage || i18n.language)

export function fmtNumber(n, opts) {
  try { return new Intl.NumberFormat(locale(), opts).format(n) } catch { return String(n) }
}

export function fmtCurrency(n, currency) {
  try {
    return new Intl.NumberFormat(locale(), { style: 'currency', currency }).format(n)
  } catch {
    return fmtNumber(n)
  }
}

export function fmtDate(d, opts) {
  const date = d instanceof Date ? d : new Date(d)
  if (Number.isNaN(date.getTime())) return ''
  try { return new Intl.DateTimeFormat(locale(), opts).format(date) } catch { return date.toISOString() }
}

const UNITS = [
  ['year', 365 * 24 * 3600e3],
  ['month', 30 * 24 * 3600e3],
  ['week', 7 * 24 * 3600e3],
  ['day', 24 * 3600e3],
  ['hour', 3600e3],
  ['minute', 60e3],
  ['second', 1e3],
]

// `ms` is a signed offset from now: negative is the past ("3 hours ago"),
// positive the future ("in 2 days"). Under a minute reads as "now".
export function fmtRelative(ms) {
  const abs = Math.abs(ms)
  try {
    const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' })
    if (abs < 60e3) return rtf.format(0, 'second')
    const [unit, size] = UNITS.find(([, s]) => abs >= s)
    return rtf.format(Math.round(ms / size), unit)
  } catch {
    return ''
  }
}
