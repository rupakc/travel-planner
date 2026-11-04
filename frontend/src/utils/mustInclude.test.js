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

// ── Fix round 2 (mirrors backend tests) ──────────────────────────────────
import { cityForDay } from './mustInclude'

describe('ordered phrase matching', () => {
  it.each([
    ['Tokyo Tower', "Tokyo Skytree — Japan's tallest tower, sunset views"],
    ['Lisbon Cathedral', 'Walk Lisbon-style tiled cafés then visit a cathedral in Tokyo'],
    ['Osaka Castle', 'Day trip: Osaka street food, then the castle-town lanes of Kawagoe'],
    ['Ark Hills', 'Roppongi Park Hills rooftop'],
    ['Tower Tokyo', 'Tokyo Tower at night'],
  ])('%s does not match "%s"', (name, text) => expect(sameLinkPlace(name, text)).toBe(false))

  it.each([
    ['LX Factory', 'Brunch at LXFactory'],
    ['Senso-ji', 'Sensoji at dawn'],
    ['Sensoji', 'Senso-ji at dawn'],
    ['Senso-ji', 'Senso ji temple'],
    ['Timeout Market', 'Dinner at the Time Out Market'],
    ['Giolitti', "Gelato at Giolitti's"],
    ['Praça das Flores', 'Praca Das Flores picnic'],
  ])('%s matches "%s"', (name, text) => expect(sameLinkPlace(name, text)).toBe(true))
})

describe('travel slots match but are never replaced', () => {
  const sd = {
    destination: 'Lisbon, Portugal',
    must_include: [
      { name: 'Tram 28', kind: 'transport', city: 'Lisbon' },
      { name: 'Pena Palace', kind: 'sight', city: 'Lisbon', town: 'Sintra' },
      { name: 'Ferry Building', kind: 'food', city: 'Lisbon' },
    ],
  }
  const itin = () => ({
    days: [
      { day_number: 1, slots: [slot('morning', 'Arrive in Lisbon')] },
      { day_number: 2, slots: [slot('morning', 'Hop on Tram 28 from Martim Moniz, then head to the castle'), slot('afternoon', 'Train to Sintra for Pena Palace'), slot('evening', 'Ferry Building food hall lunch')] },
      { day_number: 3, slots: [slot('morning', 'Belém pastries'), slot('afternoon', 'Alfama walk'), slot('evening', 'Fado dinner')] },
      { day_number: 4, slots: [slot('morning', 'Check out and fly home')] },
    ],
  })

  it('marks them in place and leaves the other days alone', () => {
    const out = ensureMustInclude(itin(), sd)
    expect(out.days[1].slots.map((s) => s.link_place)).toEqual(['Tram 28', 'Pena Palace', 'Ferry Building'])
    expect(out.days[2].slots.map((s) => s.activity)).toEqual(['Belém pastries', 'Alfama walk', 'Fado dinner'])
  })

  it('arrival hotel slots still never claim a place', () => {
    const out = ensureMustInclude({
      days: [
        { day_number: 1, slots: [slot('morning', 'Arrive in Lisbon, transfer to Memmo Alfama Hotel')] },
        { day_number: 2, slots: [slot('morning', 'Museum'), slot('afternoon', 'Free time')] },
        { day_number: 3, slots: [slot('evening', 'Departure flight')] },
      ],
    }, { destination: 'Lisbon', must_include: [{ name: 'Alfama', kind: 'area', city: 'Lisbon' }] })
    expect(out.days[0].slots[0].from_link).toBeUndefined()
    expect(out.days[1].slots[1].link_place).toBe('Alfama')
  })

  it('puts unmatched transport places in day notes, never slots', () => {
    const out = ensureMustInclude(fallback(), { destination: 'Lisbon', must_include: [{ name: 'Tram 28', kind: 'transport', city: 'Lisbon' }] })
    expect(out.days.some((d) => d.slots.some((s) => s.from_link))).toBe(false)
    expect(out.link_coverage.extras).toEqual(['Tram 28'])
  })

  it.each(['Lisbon – Porto on the Alfa Pendular (3h)', 'Hikari bullet service, Lisbon ⇒ Porto'])(
    'protects keyword-less transit "%s"', (activity) => {
      const out = ensureMustInclude({
        days: [
          { day_number: 1, slots: [slot('morning', 'Arrive')] },
          { day_number: 2, slots: [slot('morning', activity), slot('afternoon', 'Market')] },
          { day_number: 3, slots: [slot('evening', 'Departure flight')] },
        ],
      }, { destination: 'Porto, Portugal', destinations: ['Lisbon, Portugal', 'Porto, Portugal'], must_include: Array.from({ length: 4 }, (_, i) => ({ name: `Spot ${i}`, kind: 'sight' })) })
      expect(out.days[1].slots[0].activity).toBe(activity)
    })
})

describe('totals and cities', () => {
  it('takes a replaced slot\'s cost out of the day and trip totals', () => {
    const itin = {
      days: [
        { day_number: 1, slots: [slot('morning', 'Arrive')] },
        { day_number: 2, daily_estimated_cost_usd: 100, slots: [slot('morning', 'Gulbenkian Museum', { estimated_cost_usd: 20 }), slot('afternoon', 'Shopping', { estimated_cost_usd: 30 })] },
        { day_number: 3, slots: [slot('evening', 'Departure flight')] },
      ],
      total_estimated_cost_usd: 300,
    }
    const out = ensureMustInclude(itin, { destination: 'Lisbon', must_include: [{ name: 'Livraria Lello', kind: 'shopping', city: 'Lisbon' }] })
    const replaced = out.days[1].slots.find((s) => s.from_link)
    const old = replaced.time_of_day === 'morning' ? 20 : 30
    expect(out.days[1].daily_estimated_cost_usd).toBe(100 - old)
    expect(out.total_estimated_cost_usd).toBe(300 - old)
  })

  it('gives fallback days their city from the stops and nights', () => {
    const sd = { departure_date: '2026-12-01', return_date: '2026-12-05', destination: 'Porto, Portugal', destinations: ['Lisbon, Portugal', 'Porto, Portugal'], destination_nights: [2, null] }
    expect([1, 2, 3, 4, 5].map((n) => cityForDay(n, sd))).toEqual(['Lisbon', 'Lisbon', 'Porto', 'Porto', 'Porto'])
    expect(cityForDay(1, { destination: 'Lisbon, Portugal' })).toBeNull()
  })

  it('places a city\'s place on that city\'s fallback day', () => {
    const sd = {
      departure_date: '2026-12-01', return_date: '2026-12-05', destination: 'Porto, Portugal',
      destinations: ['Lisbon, Portugal', 'Porto, Portugal'], destination_nights: [2, null],
      must_include: [{ name: 'Livraria Lello', kind: 'shopping', city: 'Porto' }],
    }
    const days = [1, 2, 3, 4, 5].map((n) => ({ day_number: n, slots: [slot('morning', n === 1 ? 'Arrive' : n === 5 ? 'Departure flight' : 'Free time — explore')] }))
    const out = ensureMustInclude({ days }, sd)
    const day = out.days.find((d) => d.slots.some((s) => s.from_link))
    expect(day.day_number).toBe(4) // Porto, and not its travel-in day 3
  })
})
