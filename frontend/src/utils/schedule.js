import { TIMES, slotRanks } from './itineraryLayout'
import { haversineKm } from './geo'

// Estimated clock times for an arranged itinerary (see arrangeItinerary).
// Re-run after every edit: times are derived from each slot's position, its
// own duration and the distance from the stop before it, so they are never
// stored. Times are local wall-clock "HH:MM" strings with no time zone.

// Minutes past midnight each standard time starts at, at the earliest
const ANCHORS = { morning: 9 * 60, afternoon: 13 * 60 + 30, evening: 18 * 60 + 30 }
const DEFAULT_MINUTES = { morning: 180, afternoon: 180, evening: 150 }
// Duplicate and non-standard slots (e.g. "late night") have no default of their own
const OTHER_DEFAULT_MINUTES = 120
const MIN_HOURS = 0.25
const MAX_HOURS = 12

const DETOUR = 1.3 // street distance vs. straight line
const WALK_MAX_KM = 1.5
const WALK_KMH = 4.5
const TRANSIT_KMH = 20
const TRANSIT_OVERHEAD_MINUTES = 10 // getting to the stop, waiting
const UNKNOWN_TRAVEL_MINUTES = 20 // buffer when either stop has no coordinates

const LATE_MINUTES = 45
const DAY_END = 23 * 60

const pad = (n) => String(n).padStart(2, '0')
const clock = (minutes) => `${pad(Math.floor(minutes / 60) % 24)}:${pad(minutes % 60)}`
const roundUpTo5 = (minutes) => Math.max(5, Math.ceil(minutes / 5) * 5)

const isFiniteNumber = (n) => typeof n === 'number' && Number.isFinite(n)

function coords(slot) {
  const { lat, lng } = slot
  if (!isFiniteNumber(lat) || !isFiniteNumber(lng)) return null
  if (Math.abs(lat) > 90 || Math.abs(lng) > 180) return null
  return { lat, lng }
}

function durationMinutes(slot) {
  const hours = slot.duration_hours
  if (isFiniteNumber(hours) && hours >= MIN_HOURS && hours <= MAX_HOURS) return Math.round(hours * 60)
  return DEFAULT_MINUTES[slot.time_of_day] ?? OTHER_DEFAULT_MINUTES
}

/** Travel from `prev` to `slot`, or null when either lacks coordinates. */
function transitBetween(prev, slot) {
  const a = coords(prev)
  const b = coords(slot)
  if (!a || !b) return null
  const km = haversineKm(a.lat, a.lng, b.lat, b.lng) * DETOUR
  const walk = km <= WALK_MAX_KM
  const minutes = walk ? (km / WALK_KMH) * 60 : (km / TRANSIT_KMH) * 60 + TRANSIT_OVERHEAD_MINUTES
  return { minutes: roundUpTo5(minutes), mode: walk ? 'walk' : 'transit', km: Math.round(km * 10) / 10 }
}

function scheduleDay(day, edits) {
  const slots = Array.isArray(day?.slots) ? day.slots : []
  if (!slots.some((slot) => TIMES.includes(slot.time_of_day))) return day

  // slotRanks lists ranks in slot order. A whole rank is the first slot of a
  // standard time and starts no earlier than that time's anchor; a fractional
  // one (duplicate or non-standard time) simply follows the stop before it.
  const ranks = [...slotRanks(day).values()]
  const order = slots.map((_, i) => i).sort((a, b) => ranks[a] - ranks[b])

  const out = [...slots]
  const warnings = []
  let prev = null // { slot, end }
  for (const i of order) {
    const slot = slots[i]
    const anchor = Number.isInteger(ranks[i]) ? ANCHORS[TIMES[ranks[i]]] : null
    if (anchor == null && !prev) continue // nothing to follow: left untimed

    const transit = prev ? transitBetween(prev.slot, slot) : null
    const earliest = prev ? prev.end + (transit ? transit.minutes : UNKNOWN_TRAVEL_MINUTES) : 0
    const start = Math.max(anchor ?? 0, earliest)
    const end = start + durationMinutes(slot)
    out[i] = { ...slot, start_time: clock(start), end_time: clock(end), transit_from_prev: transit }

    if (anchor != null && start - anchor > LATE_MINUTES) {
      const name = edits?.[slot.key]?.activity || slot.activity || 'An activity'
      warnings.push(`${name} starts at ${clock(start)} — later than planned`)
    }
    prev = { slot, end }
  }
  if (prev && prev.end > DAY_END) warnings.push(`Day ${day.day_number} runs past 23:00`)
  return { ...day, slots: out, schedule_warnings: warnings }
}

/**
 * Add estimated `start_time`, `end_time` and `transit_from_prev` to every slot
 * of arranged days, and `schedule_warnings` to every day. `edits` (by slot key)
 * only rename activities in warnings; durations and coordinates always come
 * from the slot itself. Returns new objects; days with no standard-time slot
 * are returned as they are.
 */
export function scheduleDays(days, edits = {}) {
  return (Array.isArray(days) ? days : []).map((day) => scheduleDay(day, edits))
}
