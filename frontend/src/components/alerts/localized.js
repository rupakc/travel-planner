// Locale-aware wording for the watch cards: how long ago a price was checked,
// the status chip, the change since the watch began and trip dates. English
// keeps the app's existing short forms (utils/fareWatch, utils/fareCalendar);
// other languages go through the `alerts` catalogue and Intl.
import i18n from '../../i18n'
import { fmtDate, intlLocale } from '../../i18n/format'
import { formatDateRange as formatDateRangeEn } from '../../utils/fareWatch'
import { formatDay as formatDayEn } from '../../utils/fareCalendar'

const tt = (key, opts) => i18n.t(`alerts:${key}`, opts)
const lang = () => i18n.resolvedLanguage || i18n.language || 'en'
const isEnglish = () => lang().startsWith('en')
const utc = (iso) => new Date(`${iso}T00:00:00Z`)

/** "Checked …" age: just now / 5 min ago / 3 h ago / yesterday / 4 days ago. */
export function agoLabel(iso, now = new Date()) {
  if (!iso) return ''
  const secs = (now - new Date(iso)) / 1000
  if (secs < 60) return tt('time.justNow')
  const mins = Math.floor(secs / 60)
  if (mins < 60) return tt('time.minAgo', { n: mins })
  const hours = Math.floor(mins / 60)
  if (hours < 24) return tt('time.hourAgo', { n: hours })
  const days = Math.floor(hours / 24)
  return days === 1 ? tt('time.yesterday') : tt('time.daysAgo', { n: days })
}

/** "Next check …": soon / in 5 min / in 3 h / in 2 days. */
export function untilLabel(iso, now = new Date()) {
  if (!iso) return ''
  const mins = Math.round((new Date(iso) - now) / 60000)
  if (mins <= 0) return tt('time.soon')
  if (mins < 60) return tt('time.inMin', { n: mins })
  const hours = Math.round(mins / 60)
  if (hours < 24) return tt('time.inHours', { n: hours })
  return tt('time.inDays', { n: Math.round(hours / 24) })
}

/** Status chip text for a `watchStatus()` result (its `key`). */
export const statusLabel = (status) => tt(`status.${status.key}`)

/** "$12 less than when you started" for a `priceChange()` / `priceWatchChange()` result. */
export function changeText(change, money) {
  if (change.direction === 'same') return tt('change.same')
  return tt(change.direction === 'down' ? 'change.less' : 'change.more', { amount: money(Math.abs(change.delta)) })
}

/** "Tue 3 Nov" in the viewer's language. */
export function dayLabel(iso) {
  if (isEnglish()) return formatDayEn(iso)
  return fmtDate(utc(iso), { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })
}

/** Weekday and date apart, for the fare calendar cells. */
export function dayParts(iso) {
  if (isEnglish()) {
    const [weekday, ...date] = formatDayEn(iso).split(' ')
    return { weekday, date: date.join(' ') }
  }
  const d = utc(iso)
  return {
    weekday: fmtDate(d, { weekday: 'short', timeZone: 'UTC' }),
    date: fmtDate(d, { day: 'numeric', month: 'short', timeZone: 'UTC' }),
  }
}

/** "1–8 Dec" / "28 Nov – 5 Dec" / just the departure for one-way trips. */
export function rangeLabel(dep, ret) {
  if (isEnglish()) return formatDateRangeEn(dep, ret)
  try {
    const sameYear = !ret || dep.slice(0, 4) === ret.slice(0, 4)
    const fmt = new Intl.DateTimeFormat(intlLocale(lang()), {
      day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }), timeZone: 'UTC',
    })
    return ret ? fmt.formatRange(utc(dep), utc(ret)) : fmt.format(utc(dep))
  } catch {
    return ret ? `${dep} – ${ret}` : dep
  }
}

/** "Tue 3 Nov – Tue 10 Nov" (just the departure for one-way trips). */
export const tripRangeLabel = (dep, ret) => (ret ? `${dayLabel(dep)} – ${dayLabel(ret)}` : dayLabel(dep))
