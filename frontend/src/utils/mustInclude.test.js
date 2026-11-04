// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { sameLinkPlace, isLogisticsSlot, ensureMustInclude } from './mustInclude'

// Mirrors backend/tests/test_must_include.py so both sides agree

describe('sameLinkPlace', () => {
  it.each([
    ['Sé Cathedral', 'Lisbon Sé Cathedral at opening time'],
    ['Tram 28', 'Ride Tram 28 through Graça'],
    ['LX Factory', 'Brunch and shops at LX Factory'],
    ['Santos & Cais do Sodre', 'Santos & Cais do Sodré neighbourhood'],
    ['Timeout Market', 'Dinner at the TimeOut Market'],
    ['Principe Real', 'Príncipe Real neighbourhood walk'],
  ])('%s matches "%s"', (name, text) => expect(sameLinkPlace(name, text)).toBe(true))

  it.each([
    ['Sé Cathedral', 'Visit the Jerónimos cathedral-like monastery'],
    ['Tram 28', 'Take the tram to Belém'],
    ['LX Factory', 'Lunch at a former factory canteen in Marvila'],
    ['Spot 1', 'Spot 10'],
  ])('%s does not match "%s"', (name, text) => expect(sameLinkPlace(name, text)).toBe(false))
})

describe('isLogisticsSlot', () => {
  it.each([
    'Alfa Pendular train Lisbon → Porto', 'Shinkansen to Kyoto', 'Train from Lisbon',
    'Check into your hotel in Porto', 'Ferry across the Tagus', 'Drive to Sintra',
    'Arrive at Lisbon, transfer to hotel', 'Departure flight',
  ])('protects "%s"', (activity) => expect(isLogisticsSlot({ activity }, [])).toBe(true))

  it('protects moves between the trip\'s stops and transport categories', () => {
    expect(isLogisticsSlot({ activity: 'On to Porto' }, ['Porto'])).toBe(true)
    expect(isLogisticsSlot({ activity: 'Morning', category: 'transport' }, [])).toBe(true)
    expect(isLogisticsSlot({ activity: 'Gulbenkian Museum' }, ['Porto'])).toBe(false)
  })
})

const slot = (time_of_day, activity, extra = {}) => ({ time_of_day, activity, duration_hours: 2, estimated_cost_usd: 25, ...extra })
const fallback = () => ({
  days: [
    { day_number: 1, slots: [slot('morning', 'Arrive at Lisbon, transfer to your hotel'), slot('afternoon', 'Check in to your hotel'), slot('evening', 'Welcome dinner')] },
    { day_number: 2, slots: [slot('morning', 'Time Out Market'), slot('afternoon', 'Free time — explore Lisbon'), slot('evening', 'Oceanário', { booking_url: 'https://x.example' })] },
    { day_number: 3, slots: [slot('morning', 'Final breakfast'), slot('afternoon', 'Check out and head to airport'), slot('evening', 'Departure flight')] },
  ],
})

describe('ensureMustInclude (client fallback itinerary)', () => {
  const sd = {
    destination: 'Lisbon, Portugal',
    must_include: [
      { name: 'Time Out Market', kind: 'food', city: 'Lisbon', quote: 'start here' },
      { name: 'Belém Tower', kind: 'sight', city: 'Lisbon', note: 'Go early' },
      { name: 'Pena Palace', kind: 'sight', city: 'Lisbon', town: 'Sintra' },
    ],
  }

  it('marks named places, fills free time, then replaceable slots, never logistics', () => {
    const out = ensureMustInclude(fallback(), sd)
    const linked = out.days.flatMap((d) => d.slots.filter((s) => s.from_link).map((s) => [d.day_number, s.link_place, s.activity]))
    expect(linked).toContainEqual([2, 'Time Out Market', 'Time Out Market'])
    expect(linked.map((l) => l[1]).sort()).toEqual(['Belém Tower', 'Pena Palace', 'Time Out Market'])
    expect(linked.every(([day]) => day === 2)).toBe(true)
    const pena = out.days[1].slots.find((s) => s.link_place === 'Pena Palace')
    expect(pena.location).toContain('Sintra')
    expect(pena.estimated_cost_usd).toBeNull()
    expect(pena.booking_url).toBeUndefined()
    expect(out.days[0].slots[0].from_link).toBeUndefined()
    expect(out.link_coverage).toEqual({ total: 3, scheduled: expect.any(Array), extras: [], missing: [] })
  })

  it('puts places with no free slot into day notes', () => {
    const many = { ...sd, must_include: Array.from({ length: 6 }, (_, i) => ({ name: `Spot ${i}`, kind: 'sight', city: 'Lisbon' })) }
    const out = ensureMustInclude(fallback(), many)
    expect(out.link_coverage.scheduled.length + out.link_coverage.extras.length).toBe(6)
    expect(out.link_coverage.extras.length).toBeGreaterThan(0)
    expect(out.days.flatMap((d) => d.link_extras || []).map((x) => x.name)).toEqual(out.link_coverage.extras)
    // arrival and departure logistics are still untouched
    expect(out.days[0].slots[0].activity).toMatch(/^Arrive/)
    expect(out.days[2].slots[2].activity).toBe('Departure flight')
  })

  it('is idempotent and a no-op without places', () => {
    const once = ensureMustInclude(fallback(), sd)
    expect(ensureMustInclude(once, sd)).toEqual(once)
    expect(ensureMustInclude(fallback(), {})).toEqual(fallback())
  })
})
