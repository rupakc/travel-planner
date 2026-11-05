// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { hotelGuests, hotelStay, hotelWatchSpec, hotelPreview, matchedElsewhere } from './hotelWatch'

const TODAY = new Date('2026-11-05T12:00:00Z')
const SEARCH = { destination: 'Lisbon, Portugal', departure_date: '2026-12-10', return_date: '2026-12-14', num_travelers: 2, adults: 2 }
const HOTEL = { name: 'Lumen Hotel', price_per_night_usd: 100, total_price_usd: 410 }

describe('hotelGuests', () => {
  it('counts everyone in the party, two to a room', () => {
    expect(hotelGuests({ adults: 2 })).toEqual({ adults: 2, rooms: 1 })
    expect(hotelGuests({ adults: 2, children: 1, seniors: 0 })).toEqual({ adults: 3, rooms: 2 })
    expect(hotelGuests({ adults: 0, seniors: 1 })).toEqual({ adults: 1, rooms: 1 })
    expect(hotelGuests({ num_travelers: 4 })).toEqual({ adults: 4, rooms: 2 })
    expect(hotelGuests({})).toEqual({ adults: 1, rooms: 1 })
    expect(hotelGuests({ adults: 30 })).toEqual({ adults: 16, rooms: 8 })
  })
})

describe('hotelStay', () => {
  it('uses the trip dates for a single-city trip', () => {
    expect(hotelStay(HOTEL, SEARCH, TODAY)).toEqual({ check_in: '2026-12-10', check_out: '2026-12-14', city: 'Lisbon, Portugal' })
    expect(hotelStay({ ...HOTEL, city: 'Lisbon' }, SEARCH, TODAY).city).toBe('Lisbon')
  })
  it('is null without both dates, or once check-in is today or past', () => {
    expect(hotelStay(HOTEL, { ...SEARCH, return_date: null }, TODAY)).toBeNull()
    expect(hotelStay(HOTEL, { ...SEARCH, departure_date: '' }, TODAY)).toBeNull()
    expect(hotelStay(HOTEL, { ...SEARCH, departure_date: '2026-11-05' }, TODAY)).toBeNull()
    expect(hotelStay(HOTEL, null, TODAY)).toBeNull()
    expect(hotelStay(null, SEARCH, TODAY)).toBeNull()
  })
  it('uses the city’s own nights on a multi-city trip', () => {
    const multi = {
      ...SEARCH, destination: 'Paris', destinations: ['Paris, France', 'Rome, Italy', 'Madrid'],
      departure_date: '2026-12-01', return_date: '2026-12-10', destination_nights: [2, null, null],
    }
    expect(hotelStay({ ...HOTEL, city: 'Paris' }, multi, TODAY)).toEqual({ check_in: '2026-12-01', check_out: '2026-12-03', city: 'Paris' })
    expect(hotelStay({ ...HOTEL, city: 'rome' }, multi, TODAY)).toEqual({ check_in: '2026-12-03', check_out: '2026-12-07', city: 'rome' })
    expect(hotelStay({ ...HOTEL, city: 'Madrid, Spain' }, multi, TODAY)).toEqual({ check_in: '2026-12-07', check_out: '2026-12-10', city: 'Madrid, Spain' })
    // A hotel we can't place in a city, or a city not on the trip: no dates
    expect(hotelStay(HOTEL, multi, TODAY)).toBeNull()
    expect(hotelStay({ ...HOTEL, city: 'Berlin' }, multi, TODAY)).toBeNull()
  })
})

describe('hotelWatchSpec', () => {
  it('builds the spec the hotel source matches, with the AI total as an estimate', () => {
    expect(hotelWatchSpec(HOTEL, SEARCH, TODAY)).toEqual({
      name: 'Lumen Hotel', city: 'Lisbon, Portugal', check_in: '2026-12-10', check_out: '2026-12-14',
      adults: 2, rooms: 1, estimate_total: 410,
    })
  })
  it('estimates the total from the nightly price when there is none', () => {
    expect(hotelWatchSpec({ name: 'X', price_per_night_usd: 90 }, SEARCH, TODAY).estimate_total).toBe(360)
    expect('estimate_total' in hotelWatchSpec({ name: 'X' }, SEARCH, TODAY)).toBe(false)
  })
  it('is null without a name or dates', () => {
    expect(hotelWatchSpec({ ...HOTEL, name: ' ' }, SEARCH, TODAY)).toBeNull()
    expect(hotelWatchSpec(HOTEL, { ...SEARCH, return_date: null }, TODAY)).toBeNull()
  })
})

describe('hotelPreview', () => {
  it('describes the stay and labels the AI price as an estimate', () => {
    const spec = hotelWatchSpec(HOTEL, SEARCH, TODAY)
    expect(hotelPreview(HOTEL, spec)).toEqual({
      title: 'Lumen Hotel', subtitle: '10–14 Dec · 4 nights · 2 adults', price: 410, priceLabel: 'AI estimate for the stay', currency: 'USD',
    })
    expect(hotelPreview(HOTEL, { ...spec, adults: 3, rooms: 2 }).subtitle).toBe('10–14 Dec · 4 nights · 3 adults · 2 rooms')
    expect(hotelPreview(HOTEL, { ...spec, check_out: '2026-12-11', adults: 1 }).subtitle).toBe('10–11 Dec · 1 night · 1 adult')
    expect(hotelPreview(HOTEL, { ...spec, check_in: '2026-12-30', check_out: '2027-01-02' }).subtitle).toBe('30 Dec – 2 Jan · 3 nights · 2 adults')
  })
})

describe('matchedElsewhere', () => {
  it('is true only when Google Hotels names a clearly different property', () => {
    expect(matchedElsewhere({ title: 'Lumen Hotel & The Lisbon Light Show', subject: { requested_name: 'Lumen Hotel' } })).toBe(true)
    expect(matchedElsewhere({ title: 'Lumen Hotel', subject: { requested_name: 'lumen  hotel' } })).toBe(false)
    expect(matchedElsewhere({ title: 'Lumen Hotel', subject: {} })).toBe(false)
    expect(matchedElsewhere(null)).toBe(false)
  })
})
