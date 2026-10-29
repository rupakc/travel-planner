// @vitest-environment node
import { describe, it, expect } from 'vitest'
import {
  TIMES, slotKey, itineraryFingerprint, activeLayout, arrangeItinerary, moveTargets,
  moveSlot, removeSlot, restoreSlot, layoutChangeCount, syncPlannedSlots,
} from './itineraryLayout'
import { EMPTY_SELECTIONS } from './planHelpers'

const mkDay = (n, city, costs = [10, 20, 30], extra = {}) => ({
  day_number: n, date: `2027-04-0${n}`, city, theme: `Theme ${n}`,
  slots: TIMES.map((t, i) => ({ time_of_day: t, activity: `D${n} ${t}`, estimated_cost_usd: costs[i] })),
  daily_estimated_cost_usd: costs.reduce((a, b) => a + b, 0),
  ...extra,
})

const itinerary = () => ({
  days: [mkDay(1, 'Tokyo'), mkDay(2, 'Tokyo, Japan'), mkDay(3, 'Kyoto')],
  total_estimated_cost_usd: 180,
})

const layoutOf = (it, positions) => ({ fingerprint: itineraryFingerprint(it), positions })
const find = (arranged, key) => {
  for (const d of arranged.days) for (const s of d.slots) if (s.key === key) return { day: d.day_number, slot: s }
  return null
}

describe('basics', () => {
  it('builds keys and exposes times', () => {
    expect(TIMES).toEqual(['morning', 'afternoon', 'evening'])
    expect(slotKey(2, 'evening')).toBe('2-evening')
  })

  it('EMPTY_SELECTIONS has a null layout', () => {
    expect(EMPTY_SELECTIONS.itinerary_layout).toBeNull()
  })

  it('fingerprint is stable and sensitive to activity changes', () => {
    const a = itinerary()
    const b = itinerary()
    expect(itineraryFingerprint(a)).toBe(itineraryFingerprint(b))
    b.days[0].slots[0].activity = 'Other'
    expect(itineraryFingerprint(a)).not.toBe(itineraryFingerprint(b))
  })
})

describe('no layout', () => {
  it('returns the original days with keys and changed:false', () => {
    const it0 = itinerary()
    const arranged = arrangeItinerary(it0, null)
    expect(arranged.changed).toBe(false)
    expect(arranged.removed).toEqual([])
    expect(arranged.days.map((d) => d.slots.map((s) => s.key))).toEqual([
      ['1-morning', '1-afternoon', '1-evening'],
      ['2-morning', '2-afternoon', '2-evening'],
      ['3-morning', '3-afternoon', '3-evening'],
    ])
    expect(arranged.days[0].slots[0].activity).toBe('D1 morning')
    expect(arranged.total_estimated_cost_usd).toBe(180)
  })

  it('does not mutate its input', () => {
    const it0 = itinerary()
    const snap = JSON.stringify(it0)
    arrangeItinerary(it0, layoutOf(it0, { '1-morning': '2-evening' }))
    expect(JSON.stringify(it0)).toBe(snap)
  })
})

describe('moves', () => {
  it('moves into an empty (removed) spot', () => {
    const it0 = itinerary()
    let l = removeSlot(it0, null, '2-evening')
    l = moveSlot(it0, l, '1-morning', 2, 'evening')
    const a = arrangeItinerary(it0, l)
    expect(find(a, '1-morning')).toMatchObject({ day: 2, slot: { time_of_day: 'evening', activity: 'D1 morning' } })
    expect(a.days[0].slots.map((s) => s.key)).toEqual(['1-afternoon', '1-evening'])
    expect(a.removed.map((r) => r.key)).toEqual(['2-evening'])
    expect(a.changed).toBe(true)
  })

  it('swaps when the target is occupied', () => {
    const it0 = itinerary()
    const l = moveSlot(it0, null, '1-morning', 2, 'afternoon')
    const a = arrangeItinerary(it0, l)
    expect(find(a, '1-morning')).toMatchObject({ day: 2, slot: { time_of_day: 'afternoon' } })
    expect(find(a, '2-afternoon')).toMatchObject({ day: 1, slot: { time_of_day: 'morning' } })
    expect(layoutChangeCount(it0, l)).toBe(2)
  })

  it('keeps slots sorted morning to evening after a move', () => {
    const it0 = itinerary()
    const l = moveSlot(it0, null, '1-evening', 1, 'morning')
    const a = arrangeItinerary(it0, l)
    expect(a.days[0].slots.map((s) => s.time_of_day)).toEqual(['morning', 'afternoon', 'evening'])
    expect(a.days[0].slots[0].activity).toBe('D1 evening')
  })

  it('moving to its own position is a no-op', () => {
    const it0 = itinerary()
    const l = layoutOf(it0, {})
    expect(moveSlot(it0, l, '1-morning', 1, 'morning')).toBe(l)
    expect(moveSlot(it0, null, '1-morning', 1, 'morning')).toBeNull()
  })

  it('rejects cross-city moves and swaps, and excludes them from targets', () => {
    const it0 = itinerary()
    const l = layoutOf(it0, {})
    expect(moveSlot(it0, l, '1-morning', 3, 'morning')).toBe(l)
    const targets = moveTargets(it0, l, '1-morning')
    expect(targets.some((t) => t.day_number === 3)).toBe(false)
    expect(targets).toHaveLength(5)
    // Tokyo vs "Tokyo, Japan" is the same city
    expect(targets.find((t) => t.day_number === 2 && t.time_of_day === 'morning').swapWith)
      .toEqual({ key: '2-morning', activity: 'D2 morning' })
  })

  it('allows moves when a city is missing', () => {
    const it0 = itinerary()
    delete it0.days[2].city
    expect(moveTargets(it0, null, '1-morning').some((t) => t.day_number === 3)).toBe(true)
  })

  it('lists free spots without swapWith', () => {
    const it0 = itinerary()
    const l = removeSlot(it0, null, '2-evening')
    const t = moveTargets(it0, l, '1-morning').find((x) => x.day_number === 2 && x.time_of_day === 'evening')
    expect(t.swapWith).toBeNull()
  })
})

describe('remove and restore', () => {
  it('removes a slot and lists it', () => {
    const it0 = itinerary()
    const a = arrangeItinerary(it0, removeSlot(it0, null, '1-afternoon'))
    expect(find(a, '1-afternoon')).toBeNull()
    expect(a.removed).toHaveLength(1)
    expect(a.removed[0].slot.activity).toBe('D1 afternoon')
    expect(a.days[0].slots).toHaveLength(2)
  })

  it('restores to the original position when free', () => {
    const it0 = itinerary()
    const l = restoreSlot(it0, removeSlot(it0, null, '1-afternoon'), '1-afternoon')
    const a = arrangeItinerary(it0, l)
    expect(find(a, '1-afternoon')).toMatchObject({ day: 1, slot: { time_of_day: 'afternoon' } })
    expect(a.changed).toBe(false)
  })

  it('restores to the first free spot of the original day when the original is taken', () => {
    const it0 = itinerary()
    let l = removeSlot(it0, null, '1-afternoon')
    l = removeSlot(it0, l, '1-morning')
    l = moveSlot(it0, l, '2-evening', 1, 'afternoon')
    const a = arrangeItinerary(it0, restoreSlot(it0, l, '1-afternoon'))
    expect(find(a, '1-afternoon')).toMatchObject({ day: 1, slot: { time_of_day: 'morning' } })
  })

  it('stays removed when the original day is full', () => {
    const it0 = itinerary()
    let l = removeSlot(it0, null, '1-afternoon')
    l = moveSlot(it0, l, '2-evening', 1, 'afternoon')
    expect(restoreSlot(it0, l, '1-afternoon')).toBe(l)
  })

  it('restore of a slot that is not removed is a no-op', () => {
    const it0 = itinerary()
    const l = layoutOf(it0, {})
    expect(restoreSlot(it0, l, '1-morning')).toBe(l)
  })
})

describe('safety', () => {
  it('ignores a layout whose fingerprint does not match', () => {
    const it0 = itinerary()
    const l = { fingerprint: 'nope', positions: { '1-morning': null } }
    expect(activeLayout(it0, l)).toBeNull()
    const a = arrangeItinerary(it0, l)
    expect(a.changed).toBe(false)
    expect(find(a, '1-morning')).not.toBeNull()
    expect(moveSlot(it0, l, '1-evening', 1, 'morning')).toBe(l)
    expect(layoutChangeCount(it0, l)).toBe(0)
  })

  it('ignores malformed layouts', () => {
    const it0 = itinerary()
    expect(activeLayout(it0, null)).toBeNull()
    expect(activeLayout(it0, { fingerprint: itineraryFingerprint(it0), positions: 'x' })).toBeNull()
    expect(activeLayout(it0, { fingerprint: itineraryFingerprint(it0), positions: [] })).toBeNull()
    expect(activeLayout(it0, 'junk')).toBeNull()
    expect(arrangeItinerary(it0, { fingerprint: itineraryFingerprint(it0), positions: 5 }).changed).toBe(false)
  })

  it('ignores positions on a nonexistent day or a non-standard time', () => {
    const it0 = itinerary()
    const l = layoutOf(it0, { '1-morning': '9-morning', '1-afternoon': '2-late night', '1-evening': 42 })
    const a = arrangeItinerary(it0, l)
    expect(a.changed).toBe(false)
    expect(find(a, '1-morning').day).toBe(1)
    expect(layoutChangeCount(it0, l)).toBe(0)
  })

  it('resolves colliding claims deterministically: first in original order wins', () => {
    const it0 = itinerary()
    // both claim 2-morning; 1-morning wins, 1-afternoon returns to its free original spot
    let l = layoutOf(it0, { '1-morning': '2-morning', '1-afternoon': '2-morning' })
    let a = arrangeItinerary(it0, l)
    expect(find(a, '1-morning')).toMatchObject({ day: 2, slot: { time_of_day: 'morning' } })
    expect(find(a, '1-afternoon')).toMatchObject({ day: 1, slot: { time_of_day: 'afternoon' } })
    // 2-morning (still absent => original spot) loses to the earlier claimant and its original is taken: removed
    expect(a.removed.map((r) => r.key)).toEqual(['2-morning'])
    expect(arrangeItinerary(it0, l)).toEqual(a)
  })

  it('renders odd times where they are, not movable and not a target', () => {
    const it0 = itinerary()
    it0.days[0].slots.push({ time_of_day: 'late night', activity: 'Karaoke' })
    expect(moveTargets(it0, null, '1-late night')).toEqual([])
    expect(moveTargets(it0, null, '1-morning').some((t) => t.time_of_day === 'late night')).toBe(false)
    expect(moveSlot(it0, null, '1-late night', 2, 'morning')).toBeNull()
    expect(removeSlot(it0, null, '1-late night')).toBeNull()
    const l = moveSlot(it0, null, '1-morning', 1, 'evening')
    const a = arrangeItinerary(it0, l)
    expect(find(a, '1-late night').slot.activity).toBe('Karaoke')
  })
})

describe('costs', () => {
  it('recomputes only changed days, with edit overrides, skipping junk', () => {
    const it0 = itinerary()
    it0.days[0].slots[1].estimated_cost_usd = 'abc'
    it0.days[1].daily_estimated_cost_usd = 999 // untouched day keeps its value
    const l = moveSlot(it0, null, '1-evening', 1, 'morning') // swap inside day 1
    const edits = { '1-evening': { cost: 100 }, '1-morning': { cost: null } }
    const a = arrangeItinerary(it0, l, edits)
    expect(a.days[0].daily_estimated_cost_usd).toBe(100 + 10)
    expect(a.days[1].daily_estimated_cost_usd).toBe(999)
    expect(a.days[2].daily_estimated_cost_usd).toBe(60)
    expect(a.total_estimated_cost_usd).toBe(110 + 999 + 60)
  })

  it('leaves numbers identical when nothing changed', () => {
    const it0 = itinerary()
    const a = arrangeItinerary(it0, layoutOf(it0, {}), { '1-morning': { cost: 500 } })
    expect(a.changed).toBe(false)
    expect(a.days[0].daily_estimated_cost_usd).toBe(60)
    expect(a.total_estimated_cost_usd).toBe(180)
  })
})

describe('syncPlannedSlots', () => {
  it('updates moved entries and keeps removed ones', () => {
    const it0 = itinerary()
    let l = moveSlot(it0, null, '1-morning', 2, 'afternoon')
    l = removeSlot(it0, l, '3-morning')
    const arranged = arrangeItinerary(it0, l)
    const slots = [
      { key: '1-morning', day_number: 1, time_of_day: 'morning', activity: 'D1 morning' },
      { key: '3-morning', day_number: 3, time_of_day: 'morning', activity: 'D3 morning' },
      { key: '1-evening', day_number: 1, time_of_day: 'evening', activity: 'D1 evening' },
    ]
    const out = syncPlannedSlots(slots, arranged)
    expect(out).not.toBe(slots)
    expect(out[0]).toMatchObject({ key: '1-morning', day_number: 2, time_of_day: 'afternoon' })
    expect(out[1]).toBe(slots[1])
    expect(out[2]).toBe(slots[2])
    const same = syncPlannedSlots(slots, arrangeItinerary(it0, null))
    expect(same).toEqual(slots)
    expect(same[0]).toBe(slots[0])
  })
})
