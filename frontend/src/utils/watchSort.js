// Sort orders of the Alerts hub: Moving / Departing soon / Newest.

export const SORTS = ['moving', 'soon', 'newest']

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

// Relative size of the last observed move, from the two newest observed prices
function movement(w) {
  const prices = (w.history || []).map(h => num(h?.price)).filter(p => p != null)
  if (prices.length >= 2) {
    const [a, b] = prices.slice(-2)
    return a ? Math.abs(b - a) / a : 0
  }
  const base = num(w.baseline_price); const last = num(w.last_price)
  return base && last != null ? Math.abs(last - base) / base : 0
}

const dateOf = (w) => (w.kind ? w.expires_on : w.departure_date) || ''
const stamp = (w) => w.created_at || ''

/** A new array in the requested order; ties keep the incoming order. */
export function sortWatches(list, sort) {
  const rows = (list || []).map((w, i) => ({ w, i }))
  const by = {
    moving: (a, b) => movement(b.w) - movement(a.w),
    soon: (a, b) => {
      const x = dateOf(a.w); const y = dateOf(b.w)
      if (!x && !y) return 0
      if (!x) return 1
      if (!y) return -1
      return x.localeCompare(y)
    },
    newest: (a, b) => stamp(b.w).localeCompare(stamp(a.w)) || (b.w.id - a.w.id),
  }[sort]
  if (!by) return [...(list || [])]
  return rows.sort((a, b) => by(a, b) || a.i - b.i).map(r => r.w)
}
