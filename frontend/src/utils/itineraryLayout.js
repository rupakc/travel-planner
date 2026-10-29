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

const cityKey = (city) => String(city || '').split(',')[0].trim().toLowerCase()
const sameCity = (a, b) => !cityKey(a) || !cityKey(b) || cityKey(a) === cityKey(b)

// Index of the original itinerary: movable activities (standard time, unique
// key) and every valid position. A movable activity's original position IS its key.
function buildModel(itinerary) {
  const dayByNumber = new Map()
  const positions = []
  const posDay = new Map()
  const slotByKey = new Map()
  const movable = []
  for (const day of daysOf(itinerary)) {
    dayByNumber.set(day.day_number, day)
    for (const tod of TIMES) {
      const pos = slotKey(day.day_number, tod)
      positions.push(pos)
      posDay.set(pos, day)
    }
  }
  const seen = new Set()
  for (const day of daysOf(itinerary)) {
    for (const slot of slotsOf(day)) {
      const key = slotKey(day.day_number, slot.time_of_day)
      if (seen.has(key)) continue
      seen.add(key)
      if (TIMES.includes(slot.time_of_day)) {
        slotByKey.set(key, slot)
        movable.push(key)
      }
    }
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
      if (typeof want === 'string' && model.posDay.has(want)) desired = want
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

function plainArrangement(itinerary) {
  return {
    ...itinerary,
    days: daysOf(itinerary).map((day) => ({
      ...day,
      slots: slotsOf(day).map((slot) => ({ ...slot, key: slotKey(day.day_number, slot.time_of_day) })),
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
      return { ...day, slots: slotsOf(day).map((slot) => ({ ...slot, key: slotKey(day.day_number, slot.time_of_day) })) }
    }
    const slots = []
    for (const tod of TIMES) {
      const key = placed.get(slotKey(day.day_number, tod))
      if (key) slots.push({ ...model.slotByKey.get(key), key, time_of_day: tod })
    }
    for (const slot of slotsOf(day)) {
      const key = slotKey(day.day_number, slot.time_of_day)
      if (!model.slotByKey.has(key) || model.slotByKey.get(key) !== slot) slots.push({ ...slot, key })
    }
    return {
      ...day,
      slots,
      daily_estimated_cost_usd: slots.reduce((sum, s) => sum + slotCost(s, edits), 0),
    }
  })

  const total = days.reduce((sum, day) => {
    const daily = isCost(day.daily_estimated_cost_usd)
      ? day.daily_estimated_cost_usd
      : daySlotCost(day, edits)
    return sum + daily
  }, 0)

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
    if (!sameCity(fromDay.city, day.city)) continue
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
  if (layout && !activeLayout(itinerary, layout)) return layout
  const target = moveTargets(itinerary, layout, key).find(
    (t) => t.day_number === dayNumber && t.time_of_day === timeOfDay,
  )
  if (!target) return layout
  const model = buildModel(itinerary)
  const resolved = resolve(model, layout)
  const from = resolved.get(key)
  const to = slotKey(dayNumber, timeOfDay)
  if (target.swapWith) resolved.set(target.swapWith.key, from)
  resolved.set(key, to)
  return layoutFrom(itinerary, resolved)
}

export function removeSlot(itinerary, layout, key) {
  if (layout && !activeLayout(itinerary, layout)) return layout
  const model = buildModel(itinerary)
  const resolved = resolve(model, layout)
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
