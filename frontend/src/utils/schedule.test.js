// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { listedInScheduleOrder, scheduleDays, timeRange, transitLabel } from './schedule'
import { arrangeItinerary, moveSlot, removeSlot } from './itineraryLayout'

// A point `km` north of `lat` (1° of latitude ≈ 111.19 km)
const north = (lat, km) => lat + km / ((6371 * Math.PI) / 180)

const slot = (time_of_day, activity, extra = {}) => ({ time_of_day, activity, ...extra })
const day = (day_number, slots, extra = {}) => ({ day_number, city: 'Lisbon', slots, ...extra })
const arranged = (itinerary, layout = null, edits = {}) => arrangeItinerary(itinerary, layout, edits).days
const times = (d) => d.slots.map((s) => [s.start_time, s.end_time])

describe('scheduleDays — anchors and durations', () => {
  it('starts each bucket at its anchor with default durations', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [slot('morning', 'A'), slot('afternoon', 'B'), slot('evening', 'C')])] }))
    expect(times(d)).toEqual([['09:00', '12:00'], ['13:30', '16:30'], ['18:30', '21:00']])
    expect(d.schedule_warnings).toEqual([])
  })

  it('uses duration_hours when finite and between 0.25 and 12', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('morning', 'A', { duration_hours: 1.5 }),
      slot('afternoon', 'B', { duration_hours: 0.25 }),
      slot('evening', 'C', { duration_hours: 4 }),
    ])] }))
    expect(times(d)).toEqual([['09:00', '10:30'], ['13:30', '13:45'], ['18:30', '22:30']])
  })

  it('falls back to the default for invalid durations', () => {
    const bad = [0, 0.1, 13, -2, NaN, Infinity, '2', null]
    for (const duration_hours of bad) {
      const [d] = scheduleDays(arranged({ days: [day(1, [slot('morning', 'A', { duration_hours })])] }))
      expect(d.slots[0].end_time).toBe('12:00')
    }
  })

  it('returns new objects and does not mutate its input', () => {
    const days = arranged({ days: [day(1, [slot('morning', 'A')])] })
    const snapshot = JSON.parse(JSON.stringify(days))
    const out = scheduleDays(days)
    expect(out).not.toBe(days)
    expect(out[0]).not.toBe(days[0])
    expect(out[0].slots[0]).not.toBe(days[0].slots[0])
    expect(days).toEqual(snapshot)
  })

  it('keeps every other slot and day field', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [slot('morning', 'A', { location: 'X', estimated_cost_usd: 5 })], { theme: 'T' })] }))
    expect(d).toMatchObject({ day_number: 1, city: 'Lisbon', theme: 'T' })
    expect(d.slots[0]).toMatchObject({ key: '1-morning', activity: 'A', location: 'X', estimated_cost_usd: 5 })
  })

  it('handles missing or empty input', () => {
    expect(scheduleDays(undefined)).toEqual([])
    expect(scheduleDays([])).toEqual([])
  })
})

describe('scheduleDays — travel between stops', () => {
  const at = (km) => ({ lat: north(38.7, km / 1.3), lng: -9.14 })

  it('gives the first slot of a day no transit', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [slot('morning', 'A', at(0))])] }))
    expect(d.slots[0].transit_from_prev).toBeNull()
  })

  it('walks short hops (≤ 1.5 km after a 1.3 detour) at 4.5 km/h, rounded up to 5 min', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('morning', 'A', { ...at(0), duration_hours: 3.5 }),
      slot('afternoon', 'B', at(0.8)),
    ])] }))
    // 0.8 km / 4.5 km/h = 10.7 min -> 15
    expect(d.slots[1].transit_from_prev).toEqual({ minutes: 15, mode: 'walk', km: 0.8 })
    // 12:30 end + 15 min = 12:45, before the 13:30 anchor
    expect(d.slots[1].start_time).toBe('13:30')
  })

  it('takes transit for longer hops at 20 km/h plus 10 min', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('morning', 'A', at(0)),
      slot('afternoon', 'B', at(4)),
    ])] }))
    // 4 km / 20 km/h = 12 min + 10 = 22 -> 25
    expect(d.slots[1].transit_from_prev).toEqual({ minutes: 25, mode: 'transit', km: 4 })
  })

  it('pushes a start back when the previous stop plus travel runs past the anchor', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('morning', 'A', { ...at(0), duration_hours: 4.5 }),
      slot('afternoon', 'B', at(4)),
    ])] }))
    // 13:30 end + 25 min transit
    expect(times(d)[1]).toEqual(['13:55', '16:55'])
  })

  it('assumes a 20-minute buffer when either stop lacks coordinates', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('morning', 'A', { ...at(0), duration_hours: 4.5 }),
      slot('afternoon', 'B', { lat: null, lng: -9.1 }),
      slot('evening', 'C', { lat: 'x', lng: 1, duration_hours: 0.5 }),
    ])] }))
    expect(d.slots[1].transit_from_prev).toBeNull()
    expect(d.slots[1].start_time).toBe('13:50')
    expect(d.slots[2].transit_from_prev).toBeNull()
  })

  it('ignores out-of-range coordinates', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('morning', 'A', { lat: 95, lng: 0 }),
      slot('afternoon', 'B', { lat: 0, lng: 0 }),
    ])] }))
    expect(d.slots[1].transit_from_prev).toBeNull()
  })
})

describe('scheduleDays — warnings', () => {
  it('warns when a start is pushed more than 45 min past its anchor', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('morning', 'A', { duration_hours: 5 }),
      slot('afternoon', 'B'),
    ])] }))
    // 14:00 end + 20 min buffer = 14:20 (50 min late)
    expect(d.slots[1].start_time).toBe('14:20')
    expect(d.schedule_warnings).toEqual(['B starts at 14:20 — later than planned'])
  })

  it('does not warn at exactly 45 minutes late', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('morning', 'A', { duration_hours: 4.9166666667 }),
      slot('afternoon', 'B'),
    ])] }))
    // 09:00 + 295 min = 13:55, +20 = 14:15 (45 min late)
    expect(d.slots[1].start_time).toBe('14:15')
    expect(d.schedule_warnings).toEqual([])
  })

  it('warns when the day runs past 23:00', () => {
    const [d] = scheduleDays(arranged({ days: [day(3, [slot('evening', 'Fado', { duration_hours: 5 })])] }))
    expect(times(d)).toEqual([['18:30', '23:30']])
    expect(d.schedule_warnings).toEqual(['Day 3 runs past 23:00'])
  })

  it('does not warn when the day ends exactly at 23:00', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [slot('evening', 'Fado', { duration_hours: 4.5 })])] }))
    expect(d.slots[0].end_time).toBe('23:00')
    expect(d.schedule_warnings).toEqual([])
  })

  it('wraps clock times past midnight', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [slot('evening', 'Night tour', { duration_hours: 8 })])] }))
    expect(times(d)).toEqual([['18:30', '02:30']])
  })

  it('names the EDITED activity in warnings', () => {
    const itinerary = { days: [day(1, [slot('morning', 'A', { duration_hours: 5 }), slot('afternoon', 'B')])] }
    const edits = { '1-afternoon': { activity: 'Tile Museum' } }
    const [d] = scheduleDays(arranged(itinerary, null, edits), edits)
    expect(d.schedule_warnings).toEqual(['Tile Museum starts at 14:20 — later than planned'])
    // display only: the slot itself is not renamed
    expect(d.slots[1].activity).toBe('B')
  })

  it('ignores edits for durations and coordinates', () => {
    const itinerary = { days: [day(1, [slot('morning', 'A', { duration_hours: 2 })])] }
    const edits = { '1-morning': { activity: 'Z', location: 'Elsewhere', duration_hours: 9, lat: 1, lng: 1 } }
    const [d] = scheduleDays(arranged(itinerary, null, edits), edits)
    expect(times(d)).toEqual([['09:00', '11:00']])
  })
})

describe('scheduleDays — layout', () => {
  const itinerary = {
    days: [
      day(1, [slot('morning', 'Castle', { duration_hours: 2 }), slot('afternoon', 'Tram', { duration_hours: 1 }), slot('evening', 'Fado', { duration_hours: 2 })]),
      day(2, [slot('morning', 'Belem', { duration_hours: 4 }), slot('afternoon', 'LX Factory', { duration_hours: 2 })]),
    ],
  }

  it('times a moved activity at its new position, keeping its own duration', () => {
    const layout = moveSlot(itinerary, null, '1-morning', 2, 'evening')
    const days = scheduleDays(arranged(itinerary, layout))
    const castle = days[1].slots.find((s) => s.key === '1-morning')
    expect(castle.time_of_day).toBe('evening')
    expect([castle.start_time, castle.end_time]).toEqual(['18:30', '20:30'])
    expect(days[0].slots.map((s) => s.key)).toEqual(['1-afternoon', '1-evening'])
    expect(times(days[0])).toEqual([['13:30', '14:30'], ['18:30', '20:30']])
  })

  it('swaps: both activities take their new anchors', () => {
    const layout = moveSlot(itinerary, null, '1-morning', 1, 'evening')
    const [d] = scheduleDays(arranged(itinerary, layout))
    expect(d.slots.map((s) => [s.activity, s.start_time, s.end_time])).toEqual([
      ['Fado', '09:00', '11:00'], ['Tram', '13:30', '14:30'], ['Castle', '18:30', '20:30'],
    ])
  })

  it('does not schedule removed activities', () => {
    const layout = removeSlot(itinerary, null, '2-morning')
    const days = scheduleDays(arranged(itinerary, layout))
    expect(days[1].slots.map((s) => s.activity)).toEqual(['LX Factory'])
    expect(days[1].slots[0].transit_from_prev).toBeNull()
    expect(days[1].slots[0].start_time).toBe('13:30')
  })

  it('times slots in rank order even when listed out of order', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('evening', 'C', { duration_hours: 1 }),
      slot('morning', 'A', { duration_hours: 12 }),
    ])] }))
    // morning runs 09:00–21:00, so evening starts 21:20 and is flagged
    expect(d.slots.map((s) => [s.activity, s.start_time])).toEqual([['C', '21:20'], ['A', '09:00']])
    expect(d.slots[0].transit_from_prev).toBeNull()
    expect(d.schedule_warnings).toEqual(['C starts at 21:20 — later than planned'])
  })

  it('times a duplicate standard slot right after the stop before it, without a lateness warning', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('morning', 'A', { duration_hours: 1 }),
      slot('morning', 'A2', { duration_hours: 1 }),
      slot('afternoon', 'B'),
    ])] }))
    expect(times(d)).toEqual([['09:00', '10:00'], ['10:20', '11:20'], ['13:30', '16:30']])
    expect(d.schedule_warnings).toEqual([])
  })

  it('times a non-standard slot after the stop before it (2 h default); untimed when nothing precedes it', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('dawn', 'Sunrise', { lat: 10, lng: 10 }),
      slot('morning', 'A', { duration_hours: 4.5, lat: 10, lng: 10 }),
      slot('late night', 'Club'),
      slot('afternoon', 'B'),
    ])] }))
    expect(d.slots[0]).not.toHaveProperty('start_time')
    expect(d.slots[0]).not.toHaveProperty('transit_from_prev')
    // an untimed stop is not "the previous stop"
    expect(d.slots[1].transit_from_prev).toBeNull()
    expect(times(d).slice(1)).toEqual([['09:00', '13:30'], ['13:50', '15:50'], ['16:10', '19:10']])
    expect(d.schedule_warnings).toEqual(['B starts at 16:10 — later than planned'])
  })

  it('leaves days with no standard slots untouched', () => {
    const odd = day(1, [slot('dawn', 'Sunrise')])
    const days = arranged({ days: [odd, day(2, [])] })
    const out = scheduleDays(days)
    expect(out[0]).toBe(days[0])
    expect(out[1]).toBe(days[1])
  })
})

describe('scheduleDays — day offsets', () => {
  it('counts the days past the trip day each start and end falls on', () => {
    const [d] = scheduleDays(arranged({ days: [day(1, [
      slot('morning', 'A', { duration_hours: 12 }),
      slot('afternoon', 'B', { duration_hours: 12 }),
      slot('evening', 'C', { duration_hours: 12 }),
    ])] }))
    expect(d.slots.map((s) => [s.start_time, s.start_day_offset, s.end_time, s.end_day_offset])).toEqual([
      ['09:00', 0, '21:00', 0],
      ['21:20', 0, '09:20', 1],
      ['09:40', 1, '21:40', 1],
    ])
  })
})

describe('listedInScheduleOrder', () => {
  it('is true when slots are listed in the order they are timed', () => {
    expect(listedInScheduleOrder(day(1, [slot('morning', 'A'), slot('lunch', 'L'), slot('evening', 'C')]))).toBe(true)
    expect(listedInScheduleOrder(day(1, []))).toBe(true)
  })

  it('is false when a later-timed slot is listed first', () => {
    expect(listedInScheduleOrder(day(1, [slot('evening', 'C'), slot('morning', 'A')]))).toBe(false)
  })
})

describe('timeRange', () => {
  it('formats a timed slot as "start–end" and is empty otherwise', () => {
    expect(timeRange({ start_time: '09:00', end_time: '12:00' })).toBe('09:00–12:00')
    expect(timeRange({ start_time: '09:00' })).toBe('')
    expect(timeRange({})).toBe('')
    expect(timeRange(null)).toBe('')
  })
})

describe('transitLabel', () => {
  it('describes a walk with its distance', () => {
    expect(transitLabel({ minutes: 15, mode: 'walk', km: 0.8 })).toBe('🚶 15 min walk · 0.8 km')
  })

  it('omits distances under 100 m', () => {
    expect(transitLabel({ minutes: 5, mode: 'walk', km: 0 })).toBe('🚶 5 min walk')
    expect(transitLabel({ minutes: 5, mode: 'walk', km: 0.1 })).toBe('🚶 5 min walk · 0.1 km')
  })

  it('describes a transit hop as approximate', () => {
    expect(transitLabel({ minutes: 25, mode: 'transit', km: 4 })).toBe('🚇 ~25 min by transit')
  })

  it('is empty when travel is unknown', () => {
    expect(transitLabel(null)).toBe('')
    expect(transitLabel(undefined)).toBe('')
  })
})
