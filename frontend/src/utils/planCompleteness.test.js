import { describe, it, expect } from 'vitest'
import { planCompleteness } from './planCompleteness'

const search = { departure_date: '2026-05-01', return_date: '2026-05-08' }
const day = (n) => ({ day_number: n, slots: [{ activity: 'x' }] })

describe('planCompleteness', () => {
  it('is 0 when empty', () => {
    const r = planCompleteness({}, search, { visaChecked: false })
    expect(r.percent).toBe(0)
    expect(r.parts.map((p) => p.id)).toEqual(['flights', 'stay', 'days', 'visa', 'packing'])
  })
  it('is 100 when everything is done', () => {
    const itinerary = { days: [1, 2, 3, 4, 5, 6, 7].map(day) }
    const r = planCompleteness(
      { flight: { id: 1 }, hotel: { id: 2 }, itinerary, packing_list: { categories: [{ name: 'Clothes' }], total_items: 4, checked_count: 1 } },
      search, { visaChecked: true })
    expect(r.percent).toBe(100)
  })
  it('counts 3 of 7 days as 3/7', () => {
    const r = planCompleteness({ itinerary: { days: [day(1), day(2), day(3), { day_number: 4, slots: [] }] } }, search, {})
    expect(r.parts.find((p) => p.id === 'days').fraction).toBeCloseTo(3 / 7)
    expect(r.percent).toBe(Math.round(20 * 3 / 7))
  })
  it('treats a null or empty packing_list as not done', () => {
    expect(planCompleteness({ packing_list: null }, search).parts[4].done).toBe(false)
    expect(planCompleteness({ packing_list: { categories: [], total_items: 0 } }, search).parts[4].done).toBe(false)
  })
  it('reads days from a realistic saved plan (itinerary + layout)', () => {
    const itinerary = { days: [
      { day_number: 1, slots: [{ time_of_day: 'morning', activity: 'Temple' }] },
      { day_number: 2, slots: [{ time_of_day: 'morning', activity: 'Market' }] },
    ] }
    const sel = { itinerary, itinerary_layout: null, itinerary_edits: {}, itinerary_slots: [], packing_list: null }
    expect(planCompleteness(sel, search).parts[2].fraction).toBeCloseTo(2 / 7)
  })
  it('accepts flights array and does not throw on missing keys', () => {
    expect(planCompleteness(undefined, undefined).percent).toBe(0)
    expect(planCompleteness({ flights: [{}] }, null, {}).percent).toBe(20)
  })
})
