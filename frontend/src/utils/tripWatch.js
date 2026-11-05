// Pure helpers for whole-trip price watches (kind "trip"). A trip watch's
// components come from the server: subject.components (frozen at creation)
// and, per check, last_observation.breakdown — each row
// { id, type, group, label, live, price, currency, in_total, source,
//   status, unit_price?, unit?, previous_price?, delta?, link? }.
// Status: ok | unavailable | stale | error (live parts), estimate.
import { formatPrice } from './priceWatch'

/** Stacked-bar groups, in order, with their (literal, Tailwind-safe) colours. */
export const TRIP_GROUPS = [
  { key: 'flights', label: 'Flights', color: 'bg-sky-500' },
  { key: 'stay', label: 'Stay', color: 'bg-purple-500' },
  { key: 'activities', label: 'Activities', color: 'bg-green-500' },
  { key: 'other', label: 'Other', color: 'bg-pink-500' },
]

const isNum = (v) => typeof v === 'number' && Number.isFinite(v)

/** The watch's components as of its latest look (creation if none). */
export function tripRows(watch) {
  const rows = watch?.last_observation?.breakdown
  if (Array.isArray(rows) && rows.length) return rows
  return watch?.subject?.components || []
}

export const countsInTotal = (row) => row.in_total !== false && isNum(row.price)

/** The price of one component, in its own currency. */
export const rowPrice = (row) => formatPrice(row.price, row.currency || 'USD')

/** Share of the total per group (USD parts only), biggest first within order. */
export function groupTotals(rows) {
  const sums = Object.fromEntries(TRIP_GROUPS.map(g => [g.key, 0]))
  for (const r of rows || []) {
    if (!countsInTotal(r)) continue
    const key = r.group in sums ? r.group : 'other'
    sums[key] += r.price
  }
  const total = Object.values(sums).reduce((t, v) => t + v, 0)
  return TRIP_GROUPS
    .filter(g => sums[g.key] > 0)
    .map(g => ({ ...g, amount: sums[g.key], share: total > 0 ? sums[g.key] / total : 0 }))
}

export const percent = (share) => (share > 0 && share < 0.005 ? '<1%' : `${Math.round(share * 100)}%`)

/** Badge for one row: what kind of price it is and how fresh. */
export function rowBadge(row) {
  if (!row.live) return { label: 'Estimate', tone: 'slate', title: 'An AI estimate from your search, held fixed. Estimates never trigger alerts.' }
  switch (row.status) {
    case 'unavailable':
      return { label: 'Unavailable', tone: 'amber', title: 'Not available in the last check — showing the last live price we saw.' }
    case 'error':
      return { label: 'Not checked', tone: 'amber', title: 'The last check of this part failed — showing the last live price we saw.' }
    case 'stale':
      return { label: 'Live · earlier check', tone: 'sky', title: 'Checked in an earlier round (we re-check up to 5 activities each time).' }
    default:
      return { label: 'Live', tone: 'emerald', title: 'Live price from the last check.' }
  }
}

const signed = (delta) => `${delta < 0 ? '−' : '+'}${formatPrice(Math.abs(delta))}`

const GROUP_WORDS = { flights: 'flights', stay: 'hotel', activities: 'activities', other: 'other' }

/**
 * One line about the latest check: which live parts moved ("flights −$70,
 * hotel −$42"), or that nothing did; parts that couldn't be priced are
 * named. Null before the first re-check.
 */
export function whatChanged(watch) {
  const rows = watch?.last_observation?.breakdown
  if (!Array.isArray(rows) || (watch.check_count || 0) < 2) return null
  const byGroup = new Map()
  for (const r of rows) {
    if (!r.live || r.status !== 'ok' || !isNum(r.delta) || !countsInTotal(r)) continue
    byGroup.set(r.group, (byGroup.get(r.group) || 0) + r.delta)
  }
  const moves = [...byGroup.entries()]
    .filter(([, d]) => Math.round(d) !== 0)
    .sort((a, b) => a[1] - b[1])
    .map(([g, d]) => `${GROUP_WORDS[g] || g} ${signed(d)}`)
  const missing = rows.filter(r => r.live && (r.status === 'unavailable' || r.status === 'error')).map(r => r.label)
  let text = moves.length ? `Last check: ${moves.join(', ')}.` : 'Last check: no live price moved.'
  if (missing.length) text += ` Couldn’t price ${missing.join(', ')} — kept the last live price.`
  return text
}

export const liveCount = (rows) => (rows || []).filter(r => r.live).length
export const estimateCount = (rows) => (rows || []).filter(r => !r.live).length

/** "Watching · $2,140" for a trip watch (paused reads so). */
export function tripWatchingLabel(watch) {
  if (watch.status === 'paused') return 'Watch paused'
  const price = watch.last_price ?? watch.baseline_price
  return isNum(price) ? `Watching · ${formatPrice(price)}` : 'Watching'
}

/** A saved plan can be watched when it has an id and hasn't departed. */
export function isWatchablePlan(plan, now = new Date()) {
  const dep = plan?.search_data?.departure_date
  return !!plan?.id && !!dep && dep > now.toISOString().slice(0, 10)
}

/** A fresh search for the watched trip ("Re-plan"), from the live flight's
 * route when there is one; null without a route. */
export function tripReplanFare(watch) {
  const flight = (watch?.subject?.components || []).find(c => c.type === 'flight' && c.subject?.origin_label)
  return flight ? flight.subject : null
}
