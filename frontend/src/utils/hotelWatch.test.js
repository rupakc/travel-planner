// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { hotelGuests, hotelStay, hotelWatchSpec, hotelPreview, matchedElsewhere } from './hotelWatch'

const TODAY = new Date('2026-11-05T12:00:00Z')
const SEARCH = { destination: 'Lisbon, Portugal', departure_date: '2026-12-10', return_date: '2026-12-14', num_travelers: 2, adults: 2 }
const HOTEL = { name: 'Lumen Hotel', price_per_night_usd: 100, total_price_usd: 410 }

describe('hotelGuests', () => {
  it('counts every traveller as a guest (Google Hotels takes adults only), one room up to 4', () => {
    expect(hotelGuests({ adults: 2 })).toEqual({ adults: 2, rooms: 1 })
    expect(hotelGuests({ adults: 2, children: 2, seniors: 0 })).toEqual({ adults: 4, rooms: 1 })
    expect(hotelGuests({ adults: 0, seniors: 1 })).toEqual({ adults: 1, rooms: 1 })
    expect(hotelGuests({ num_travelers: 5 })).toEqual({ adults: 5, rooms: 2 })
    expect(hotelGuests({ adults: 9 })).toEqual({ adults: 9, rooms: 3 })
    expect(hotelGuests({})).toEqual({ adults: 1, rooms: 1 })
    expect(hotelGuests({ adults: 30 })).toEqual({ adults: 16, rooms: 4 })
  })
})

describe('hotelStay', () => {
  it('uses the trip dates for a single-city trip', () => {
    expect(hotelStay(HOTEL, SEARCH, TODAY)).toEqual({ check_in: '2026-12-10', check_out: '2026-12-14', city: 'Lisbon, Portugal' })
    expect(hotelStay({ ...HOTEL, city: 'Lisbon' }, SEARCH, TODAY).city).toBe('Lisbon')
  })
  it('is null for a hotel in another city than the trip’s', () => {
    expect(hotelStay({ ...HOTEL, city: 'Tokyo' }, SEARCH, TODAY)).toBeNull()
    expect(hotelStay({ ...HOTEL, city: 'lisboa' }, SEARCH, TODAY)).toBeNull()
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
  it('scales the one-room AI estimate to the rooms watched', () => {
    expect(hotelWatchSpec(HOTEL, { ...SEARCH, adults: 6 }, TODAY)).toMatchObject({ adults: 6, rooms: 2, estimate_total: 820 })
  })
  it('is null without a name or dates', () => {
    expect(hotelWatchSpec({ ...HOTEL, name: ' ' }, SEARCH, TODAY)).toBeNull()
    expect(hotelWatchSpec(HOTEL, { ...SEARCH, return_date: null }, TODAY)).toBeNull()
  })
})

describe('hotelPreview', () => {
  it('describes the stay as guests and rooms and never offers the estimate as the price', () => {
    const spec = hotelWatchSpec(HOTEL, SEARCH, TODAY)
    expect(hotelPreview(HOTEL, spec)).toEqual({
      title: 'Lumen Hotel', subtitle: '10–14 Dec · 4 nights · 2 guests · 1 room', price: null,
      estimate: 410, estimateLabel: 'AI estimate for 1 room, whole stay', currency: 'USD',
    })
    expect(hotelPreview(HOTEL, { ...spec, check_out: '2026-12-11', adults: 1 }).subtitle).toBe('10–11 Dec · 1 night · 1 guest · 1 room')
    expect(hotelPreview(HOTEL, { ...spec, check_in: '2026-12-30', check_out: '2027-01-02' }).subtitle).toBe('30 Dec – 2 Jan · 3 nights · 2 guests · 1 room')
  })
  it('names the per-room basis when more than one room is watched', () => {
    const spec = hotelWatchSpec(HOTEL, { ...SEARCH, adults: 6 }, TODAY)
    const p = hotelPreview(HOTEL, spec)
    expect(p.subtitle).toBe('10–14 Dec · 4 nights · 6 guests · 2 rooms')
    expect(p.estimate).toBe(820)
    expect(p.estimateLabel).toBe('AI estimate: 2 rooms × $410, whole stay')
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
