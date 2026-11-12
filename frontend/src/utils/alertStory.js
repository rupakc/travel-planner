// Pure helpers for the price story (docs/Alerts-API.md). They mirror the
// backend rules and are checked against backend/tests/fixtures/alerts/story_cases.json.

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const round2 = (v) => Math.round(v * 100) / 100
const prices = (points) => (points || []).map((p) => num(p?.price)).filter((p) => p !== null)

export const lowestOf = (points) => { const p = prices(points); return p.length ? Math.min(...p) : null }
export const latestOf = (points) => { const p = prices(points); return p.length ? p[p.length - 1] : null }

const nearestRank = (sorted, q) => sorted[Math.ceil(q * sorted.length) - 1]

/** {low, high, source} or null: Google's range for flights, else p25/p75 of >= 6 points. */
export function typicalFor({ kind, points, google_typical: google } = {}) {
  if (kind === 'flight') {
    return Array.isArray(google) && google.length === 2 ? { low: google[0], high: google[1], source: 'google' } : null
  }
  const p = prices(points).sort((a, b) => a - b)
  if (p.length < 6) return null
  return { low: nearestRank(p, 0.25), high: nearestRank(p, 0.75), source: 'history' }
}

/**
 * 'great' | 'good' | 'typical' | 'high' | null for a price against {low, high}.
 * With `{checkedDaysAgo, livePrices}`, a stale no-live-prices story is null.
 */
export function verdictFor(price, typical, { checkedDaysAgo = null, livePrices = true } = {}) {
  if (num(price) === null || !typical) return null
  if (!livePrices && checkedDaysAgo !== null && checkedDaysAgo > 3) return null
  const { low, high } = typical
  if (price < low) return 'great'
  if (price <= low + 0.25 * (high - low)) return 'good'
  if (price <= high) return 'typical'
  return 'high'
}

/** The kind's alert step at a price (price_rules). */
export function stepFor(kind, price) {
  if (kind === 'activity') return Math.max(1, 0.05 * price)
  if (kind === 'trip') return Math.max(25, 0.04 * price)
  return Math.max(15, 0.05 * price)
}

function wholeDays(a, b) {
  if (a?.days_ago !== undefined && b?.days_ago !== undefined) return a.days_ago - b.days_ago
  const ms = new Date(b?.at) - new Date(a?.at)
  return Number.isFinite(ms) ? Math.floor(ms / 86400000) : 0
}

/**
 * {code, params} for a PriceStory, first matching rule wins. Takes the story
 * (`kind, target, points, typical, verdict, checked_days_ago, live_prices`);
 * a missing `verdict` is derived from `typical`.
 */
export function adviceFor(story = {}) {
  const points = story.points || []
  const latest = latestOf(points)
  const lowest = lowestOf(points)
  const checked = story.checked_days_ago ?? story.checkedDaysAgo ?? null
  const live = story.live_prices ?? story.livePrices ?? true
  if (latest === null) return { code: 'pending', params: {} }
  if (!live && checked !== null && checked > 3) return { code: 'checks_paused', params: { days: checked } }
  const target = num(story.target)
  if (target !== null) {
    if (latest <= target) return { code: 'below_target', params: { by: round2(target - latest) } }
    if (latest - target <= stepFor(story.kind, target)) return { code: 'near_target', params: { gap: round2(latest - target) } }
  }
  if (latest === lowest && points.length >= 3) return { code: 'at_lowest', params: {} }
  const verdict = story.verdict !== undefined
    ? story.verdict
    : verdictFor(latest, story.typical, { checkedDaysAgo: checked, livePrices: live })
  if (verdict === 'great' || verdict === 'good') return { code: 'below_typical', params: {} }
  if (verdict === 'typical') return { code: 'within_typical', params: {} }
  if (verdict === 'high') return { code: 'above_typical', params: {} }
  if (points.length >= 5) {
    const last5 = points.slice(-5)
    const p = last5.map((x) => x.price)
    const min = Math.min(...p)
    if (Math.max(...p) - min <= 0.01 * min) return { code: 'steady', params: { days: wholeDays(last5[0], last5[4]) } }
  }
  return { code: 'few_checks', params: { n: points.length } }
}

/** How many of `points` ({price}) are at or below `target`. */
export function countAtOrBelow(points, target) {
  return prices(points).filter((p) => p <= target).length
}

/** Whole days between an ISO time and `now`, or null. */
export function checkedDaysAgo(iso, now = Date.now()) {
  const t = new Date(iso).getTime()
  if (!iso || !Number.isFinite(t)) return null
  return Math.max(0, Math.floor((now - t) / 86400000))
}
