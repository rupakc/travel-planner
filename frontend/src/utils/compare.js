// Pure helpers for the trip-comparison feature.

/**
 * A cleared <input type="date"> is ''; the API wants null (one-way / open
 * ended), otherwise TravelSearchRequest rejects the request with a 422.
 * @param {string|null|undefined} value
 */
export const apiReturnDate = (value) => value || null

/**
 * Build one TravelSearchRequest per destination. Mirrors the shape the
 * known-destination search builds (SearchPage.startSearch) so "Plan this
 * trip" can run the exact compared request. Only `destination` varies; blank
 * and duplicate (case-insensitive) destinations are dropped and multi-city
 * fields are cleared.
 * @param {object} form shared fields plus `destinations: string[]`
 */
export function buildCompareRequests(form) {
  // `destination` and `extraStops` are destructured only to keep them out of `shared`
  const { destinations = [], destination: _d, extraStops: _s, ...shared } = form || {}
  const seen = new Set()
  const unique = []
  for (const raw of destinations) {
    const dest = (raw || '').trim()
    const key = dest.toLowerCase()
    if (!dest || seen.has(key)) continue
    seen.add(key)
    unique.push(dest)
  }
  const travelers = Math.max(
    1,
    (shared.adults || 0) + (shared.children || 0) + (shared.seniors || 0) + (shared.infants || 0),
  )
  const budget = shared.budget_usd ? parseFloat(shared.budget_usd) : null
  return unique.map((destination) => ({
    ...shared,
    num_travelers: travelers,
    budget_usd: Number.isFinite(budget) ? budget : null,
    return_date: apiReturnDate(shared.return_date),
    destination,
    destinations: null,
    destination_nights: null,
  }))
}

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

// rowKey -> [extractor, which value is best: 'min' (lowest) | 'max' (highest)]
export const ROW_RULES = {
  // A partial total omits unknown costs, so it can't be called the cheapest
  estimate: [(s) => (s?.estimate?.partial === true ? null : num(s?.estimate?.total_usd)), 'min'],
  flight: [(s) => num(s?.flight?.price_usd), 'min'],
  hotel: [(s) => num(s?.hotel?.typical_nightly_usd), 'min'],
  weather: [(s) => num(s?.weather?.poor_days), 'min'],
  ease: [(s) => num(s?.ease?.total), 'max'],
  safety: [(s) => num(s?.ease?.safety), 'max'],
  english: [(s) => num(s?.ease?.english), 'max'],
  daily: [(s) => num(s?.daily_cost_usd), 'min'],
}

/**
 * For each numeric row, the set of column indexes holding the best value.
 * Ties mark every tied column. Rows with fewer than two known (finite
 * numeric) values are omitted.
 * @param {Array<object|null>} summaries indexed by column
 * @returns {{[rowKey: string]: Set<number>}}
 */
export function bestByRow(summaries) {
  const out = {}
  for (const [key, [get, dir]] of Object.entries(ROW_RULES)) {
    const vals = (summaries || [])
      .map((s, i) => [i, s ? get(s) : null])
      .filter(([, v]) => v !== null)
    if (vals.length < 2) continue
    const best = dir === 'min' ? Math.min(...vals.map(([, v]) => v)) : Math.max(...vals.map(([, v]) => v))
    out[key] = new Set(vals.filter(([, v]) => v === best).map(([i]) => i))
  }
  return out
}

export const fmtUsd = (v) => (num(v) === null ? '—' : `$${Math.round(v).toLocaleString('en-US')}`)

export function fmtDuration(minutes) {
  const m = num(minutes)
  if (m === null || m <= 0) return null
  return `${Math.floor(m / 60)}h ${Math.round(m % 60)}m`
}

/**
 * Short, human reason for a failed compare call: the API's string `detail`
 * when there is one, otherwise a generic hint by status. Always a string.
 * @param {unknown} err axios error (or anything thrown)
 */
export function compareErrorReason(err) {
  const res = err && typeof err === 'object' ? err.response : null
  const detail = res?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  const status = res?.status
  if (typeof status === 'number' && status >= 400 && status < 500) return 'Please check the trip details'
  return 'Service unavailable — try again'
}
