// Trip phase and day arithmetic. Mirrors backend/app/services/trip_phase.py;
// both pass backend/tests/fixtures/journey/trip_phase_cases.json.

export const READY_WINDOW_DAYS = 14

const DAY_MS = 86400000

// 'YYYY-MM-DD' -> UTC day number, or null.
function toDayNumber(value) {
  if (typeof value !== 'string') return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
  if (!m) return null
  const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return Number.isNaN(ms) ? null : Math.round(ms / DAY_MS)
}

function lastDay(s, e) {
  return e !== null && e >= s ? e : s
}

export function effectivePhase({
  start,
  end,
  override,
  today,
  prepComplete = false,
  readyWindowDays = READY_WINDOW_DAYS,
}) {
  if (override) return override
  const s = toDayNumber(start)
  const t = toDayNumber(today)
  if (s === null || t === null) return 'dreaming'
  const last = lastDay(s, toDayNumber(end))
  if (t > last) return 'memories'
  if (t >= s) return 'on_the_road'
  if (prepComplete || s - t <= readyWindowDays) return 'ready'
  return 'planning'
}

export function dayIndex(start, end, today) {
  const s = toDayNumber(start)
  const t = toDayNumber(today)
  if (s === null || t === null) return null
  const last = lastDay(s, toDayNumber(end))
  return t >= s && t <= last ? t - s + 1 : null
}

export function daysToStart(start, today) {
  const s = toDayNumber(start)
  const t = toDayNumber(today)
  if (s === null || t === null || t >= s) return null
  return s - t
}

// The local calendar date as 'YYYY-MM-DD' (not the UTC date).
export function localToday(now = new Date()) {
  const y = String(now.getFullYear()).padStart(4, '0')
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}
