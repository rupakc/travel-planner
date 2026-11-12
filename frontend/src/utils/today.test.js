// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { todaySlots, nextUp } from './today'
import { arrangeItinerary } from './itineraryLayout'
import { scheduleDays } from './schedule'

const itinerary = { days: [{ day_number: 1, city: 'Lisbon', slots: [
  { time_of_day: 'morning', activity: 'A' }, { time_of_day: 'afternoon', activity: 'B' }, { time_of_day: 'evening', activity: 'C' },
] }, { day_number: 2, city: 'Lisbon', slots: [{ time_of_day: 'morning', activity: 'D' }] }] }
const days = scheduleDays(arrangeItinerary(itinerary, null, {}).days, {})

describe('today helpers', () => {
  it('todaySlots picks the day and tolerates bad input', () => {
    expect(todaySlots(days, 2).map((s) => s.activity)).toEqual(['D'])
    expect(todaySlots(days, 0)).toEqual([])
    expect(todaySlots(null, 1)).toEqual([])
  })
  it('nextUp at 13:05 picks the afternoon slot', () => {
    const slots = todaySlots(days, 1)
    expect(nextUp(slots, new Date(2027, 3, 1, 13, 5)).activity).toBe('B')
    expect(nextUp(slots, new Date(2027, 3, 1, 8, 0)).activity).toBe('A')
    expect(nextUp(slots, new Date(2027, 3, 1, 23, 0))).toBeNull()
    expect(nextUp([], new Date())).toBeNull()
  })
})
