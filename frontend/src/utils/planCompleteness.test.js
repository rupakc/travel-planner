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
      { flight: { id: 1 }, hotel: { id: 2 }, packing_list: { checked_items: {} } },
      { ...search, itinerary }, { visaChecked: true })
    expect(r.percent).toBe(100)
  })
  it('counts 3 of 7 days as 3/7', () => {
    const r = planCompleteness({}, { ...search, itinerary: { days: [day(1), day(2), day(3), { slots: [] }] } }, {})
    expect(r.parts.find((p) => p.id === 'days').fraction).toBeCloseTo(3 / 7)
    expect(r.percent).toBe(Math.round(20 * 3 / 7))
  })
  it('accepts flights array and does not throw on missing keys', () => {
    expect(planCompleteness(undefined, undefined).percent).toBe(0)
    expect(planCompleteness({ flights: [{}] }, null, {}).percent).toBe(20)
  })
})
