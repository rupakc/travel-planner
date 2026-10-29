// Drag-and-drop itinerary editing: a layout overlay keyed by each activity's
// ORIGINAL slot key ("<day_number>-<time_of_day>"). Edits, notes, plan picks and
// calendar UIDs all stay attached to that key, so moving an activity never
// re-keys anything. Layout shape:
//   { fingerprint, positions: { [originalKey]: "<day>-<tod>" | null } }
// null = removed; an absent key stays where it was.

export const TIMES = ['morning', 'afternoon', 'evening']

export const slotKey = (dayNumber, timeOfDay) => `${dayNumber}-${timeOfDay}`

// FNV-1a: a short, stable fingerprint (not for security)
function hash(text) {
  let h = 0x811c9dc5
  for (const ch of String(text)) {
    h ^= ch.codePointAt(0)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(36)
}

const daysOf = (itinerary) => (Array.isArray(itinerary?.days) ? itinerary.days : [])
const slotsOf = (day) => (Array.isArray(day?.slots) ? day.slots : [])

export function itineraryFingerprint(itinerary) {
  const lines = []
  for (const day of daysOf(itinerary)) {
    for (const slot of slotsOf(day)) lines.push(`${day.day_number}|${slot.time_of_day}|${slot.activity}`)
  }
  return hash(lines.join('\n'))
}

export function activeLayout(itinerary, layout) {
  if (!layout || typeof layout !== 'object') return null
  const { positions } = layout
  if (!positions || typeof positions !== 'object' || Array.isArray(positions)) return null
  if (layout.fingerprint !== itineraryFingerprint(itinerary)) return null
  return layout
}

// Keys of a day's slots, in order. The first slot with a given time keeps
// "<day>-<tod>"; later ones with the same time get "#2", "#3", ... suffixes.
function dayKeys(day) {
  const counts = new Map()
  return slotsOf(day).map((slot) => {
    const base = slotKey(day.day_number, slot.time_of_day)
    const n = (counts.get(base) || 0) + 1
    counts.set(base, n)
    return n === 1 ? base : `${base}#${n}`
  })
}

// A slot is movable when its time is standard and it is the first slot of
// that time on its day (its key is exactly "<day>-<tod>").
const isMovableSlot = (day, slot, key) => TIMES.includes(slot.time_of_day) && key === slotKey(day.day_number, slot.time_of_day)

// Sort rank of every slot of an ORIGINAL day: a movable slot ranks at its
// time's index; any other slot ranks just after the movable slot preceding it
// (-0.5 when none). "Free time" placeholders use the bare time index.
export function slotRanks(day) {
  const ranks = new Map()
  let rank = -1
  const keys = dayKeys(day)
  slotsOf(day).forEach((slot, i) => {
    if (isMovableSlot(day, slot, keys[i])) {
      rank = TIMES.indexOf(slot.time_of_day)
      ranks.set(keys[i], rank)
    } else {
      ranks.set(keys[i], rank + 0.5)
    }
  })
  return ranks
}

// A day's place names: "Montserrat & Barcelona, Spain" -> {montserrat, barcelona}.
function placeNames(city) {
  return new Set(
    String(city || '')
      .split(',')[0]
      .split(/&|\/|\+|\band\b/i)
      .map((part) => part.trim().toLowerCase())
      .filter(Boolean),
  )
}

// City rule: two days are compatible when their place-name sets share a name,
// or either day has no city (single-city trips, day trips like "X & Barcelona").
export function citiesCompatible(a, b) {
  const left = placeNames(a)
  const right = placeNames(b)
  if (!left.size || !right.size) return true
  for (const name of left) if (right.has(name)) return true
  return false
}

// Index of the original itinerary: movable activities (standard time, unique
// key) and every valid position. A movable activity's original position IS its key.
// Positions exist only on days that have at least one standard-time slot.
function buildModel(itinerary) {
  const positions = []
  const posDay = new Map()
  const slotByKey = new Map()
  const movable = []
  for (const day of daysOf(itinerary)) {
    if (!slotsOf(day).some((slot) => TIMES.includes(slot.time_of_day))) continue
    for (const tod of TIMES) {
      const pos = slotKey(day.day_number, tod)
      positions.push(pos)
      posDay.set(pos, day)
    }
  }
  for (const day of daysOf(itinerary)) {
    const keys = dayKeys(day)
    slotsOf(day).forEach((slot, i) => {
      const key = keys[i]
      if (isMovableSlot(day, slot, key)) {
        slotByKey.set(key, slot)
        movable.push(key)
      }
    })
  }
  return { posDay, positions, slotByKey, movable }
}

// Effective position of every movable key: string, or null when removed.
function resolve(model, layout) {
  const map = new Map()
  const taken = new Set()
  const claims = layout?.positions || {}
  for (const key of model.movable) {
    let desired = key
    if (Object.prototype.hasOwnProperty.call(claims, key)) {
      const want = claims[key]
      if (want === null) {
        map.set(key, null)
        continue
      }
      if (
        typeof want === 'string' && model.posDay.has(want)
        && citiesCompatible(model.posDay.get(key).city, model.posDay.get(want).city)
      ) desired = want
    }
    if (!taken.has(desired)) {
      taken.add(desired)
      map.set(key, desired)
    } else if (!taken.has(key)) {
      taken.add(key)
      map.set(key, key)
    } else {
      map.set(key, null)
    }
  }
  return map
}

const occupantOf = (resolved, pos) => {
  for (const [key, at] of resolved) if (at === pos) return key
  return null
}

// Sparse layout from a resolved map: only keys away from their original spot.
function layoutFrom(itinerary, resolved) {
  const positions = {}
  for (const [key, at] of resolved) if (at !== key) positions[key] = at
  return { fingerprint: itineraryFingerprint(itinerary), positions }
}

function isCost(n) {
  return typeof n === 'number' && Number.isFinite(n)
}

function slotCost(slot, edits) {
  const edited = edits?.[slot.key]?.cost
  const cost = edited ?? slot.estimated_cost_usd
  return isCost(cost) ? cost : 0
}

const withKeys = (day) => {
  const keys = dayKeys(day)
  return slotsOf(day).map((slot, i) => ({ ...slot, key: keys[i] }))
}

function plainArrangement(itinerary) {
  return {
    ...itinerary,
    days: daysOf(itinerary).map((day) => ({
      ...day,
      slots: withKeys(day),
    })),
    removed: [],
    changed: false,
  }
}

export function arrangeItinerary(itinerary, layout, edits = {}) {
  const active = activeLayout(itinerary, layout)
  if (!active) return plainArrangement(itinerary)
  const model = buildModel(itinerary)
  const resolved = resolve(model, active)

  const changedDays = new Set()
  const removed = []
  for (const [key, at] of resolved) {
    if (at === key) continue
    changedDays.add(model.posDay.get(key).day_number)
    if (at === null) removed.push({ key, slot: { ...model.slotByKey.get(key), key } })
    else changedDays.add(model.posDay.get(at).day_number)
  }
  if (!changedDays.size) return plainArrangement(itinerary)

  const placed = new Map() // position -> key
  for (const [key, at] of resolved) if (at) placed.set(at, key)

  const days = daysOf(itinerary).map((day) => {
    if (!changedDays.has(day.day_number)) {
      return { ...day, slots: withKeys(day) }
    }
    // Odd-time and duplicate slots stay put: sorted just after the standard
    // time that preceded them in the original day (before everything if none).
    const entries = []
    TIMES.forEach((tod, rank) => {
      const key = placed.get(slotKey(day.day_number, tod))
      if (key) entries.push({ rank, slot: { ...model.slotByKey.get(key), key, time_of_day: tod } })
    })
    const keys = dayKeys(day)
    const ranks = slotRanks(day)
    slotsOf(day).forEach((slot, i) => {
      if (!isMovableSlot(day, slot, keys[i])) entries.push({ rank: ranks.get(keys[i]), slot: { ...slot, key: keys[i] } })
    })
    const slots = entries.sort((a, b) => a.rank - b.rank).map((e) => e.slot)
    return {
      ...day,
      slots,
      daily_estimated_cost_usd: slots.reduce((sum, s) => sum + slotCost(s, edits), 0),
    }
  })

  const dayCost = (day) => (isCost(day.daily_estimated_cost_usd) ? day.daily_estimated_cost_usd : daySlotCost(day, edits))
  let total
  if (isCost(itinerary.total_estimated_cost_usd)) {
    total = itinerary.total_estimated_cost_usd
    daysOf(itinerary).forEach((original, i) => {
      if (!changedDays.has(original.day_number)) return
      const before = isCost(original.daily_estimated_cost_usd) ? original.daily_estimated_cost_usd : daySlotCost(original, {})
      total += days[i].daily_estimated_cost_usd - before
    })
  } else {
    total = days.reduce((sum, day) => sum + dayCost(day), 0)
  }

  return { ...itinerary, days, total_estimated_cost_usd: total, removed, changed: true }
}

function daySlotCost(day, edits) {
  return slotsOf(day).reduce((sum, s) => sum + slotCost(s, edits), 0)
}

export function moveTargets(itinerary, layout, key) {
  const active = activeLayout(itinerary, layout)
  const model = buildModel(itinerary)
  const resolved = resolve(model, active)
  const from = resolved.get(key)
  if (!from) return []
  const fromDay = model.posDay.get(from)
  const targets = []
  for (const pos of model.positions) {
    if (pos === from) continue
    const day = model.posDay.get(pos)
    if (!citiesCompatible(fromDay.city, day.city)) continue
    const occupant = occupantOf(resolved, pos)
    targets.push({
      day_number: day.day_number,
      time_of_day: pos.slice(String(day.day_number).length + 1),
      swapWith: occupant ? { key: occupant, activity: model.slotByKey.get(occupant).activity } : null,
    })
  }
  return targets
}

export function moveSlot(itinerary, layout, key, dayNumber, timeOfDay) {
  const target = moveTargets(itinerary, layout, key).find(
    (t) => t.day_number === dayNumber && t.time_of_day === timeOfDay,
  )
  if (!target) return layout
  const model = buildModel(itinerary)
  const resolved = resolve(model, activeLayout(itinerary, layout))
  const from = resolved.get(key)
  const to = slotKey(dayNumber, timeOfDay)
  if (target.swapWith) resolved.set(target.swapWith.key, from)
  resolved.set(key, to)
  return layoutFrom(itinerary, resolved)
}

export function removeSlot(itinerary, layout, key) {
  const model = buildModel(itinerary)
  const resolved = resolve(model, activeLayout(itinerary, layout))
  if (!resolved.get(key)) return layout
  resolved.set(key, null)
  return layoutFrom(itinerary, resolved)
}

export function restoreSlot(itinerary, layout, key) {
  if (!layout || !activeLayout(itinerary, layout)) return layout
  const model = buildModel(itinerary)
  const resolved = resolve(model, layout)
  if (!resolved.has(key) || resolved.get(key) !== null) return layout
  const originalDay = model.posDay.get(key)
  const candidates = [key, ...TIMES.map((t) => slotKey(originalDay.day_number, t))]
  const free = candidates.find((pos) => !occupantOf(resolved, pos))
  if (!free) return layout
  resolved.set(key, free)
  return layoutFrom(itinerary, resolved)
}

export function layoutChangeCount(itinerary, layout) {
  const active = activeLayout(itinerary, layout)
  if (!active) return 0
  let count = 0
  for (const [key, at] of resolve(buildModel(itinerary), active)) if (at !== key) count += 1
  return count
}

export function syncPlannedSlots(itinerarySlots, arranged) {
  const where = new Map()
  for (const day of arranged?.days || []) {
    for (const slot of day.slots || []) where.set(slot.key, { day_number: day.day_number, time_of_day: slot.time_of_day })
  }
  return (itinerarySlots || []).map((entry) => {
    const at = where.get(entry?.key)
    if (!at || (at.day_number === entry.day_number && at.time_of_day === entry.time_of_day)) return entry
    return { ...entry, ...at }
  })
}
