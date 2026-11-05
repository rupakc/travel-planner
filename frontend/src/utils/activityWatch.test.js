// @vitest-environment node
import { describe, it, expect } from 'vitest'
import {
  activityDate, activitySpec, activityWatchingLabel, formatPrice, perPerson, providerName,
  titleDiffers, travellersFrom,
} from './activityWatch'

const NOW = new Date(2026, 10, 5, 12) // 5 Nov 2026, local time

describe('formatPrice', () => {
  it('shows cents under 100 and whole amounts above, in the right currency', () => {
    expect(formatPrice(11.63)).toBe('$11.63')
    expect(formatPrice(9.9, 'EUR')).toBe('€9.90')
    expect(formatPrice(398, 'USD')).toBe('$398')
    expect(formatPrice(1240.4, 'usd')).toBe('$1,240')
    expect(formatPrice(77.48, 'AUD')).toBe('A$77.48')
    expect(formatPrice(1500, 'JPY')).toBe('¥1,500')
  })
  it('never throws on an unknown code', () => {
    expect(formatPrice(12.5, 'kr')).toContain('12.50')
  })
})

describe('travellersFrom', () => {
  it('uses num_travelers, else the traveller breakdown, clamped to 1–20', () => {
    expect(travellersFrom({ num_travelers: 2 })).toBe(2)
    expect(travellersFrom({ adults: 2, children: 1, seniors: 1, infants: 1 })).toBe(4)
    expect(travellersFrom({})).toBe(1)
    expect(travellersFrom(null)).toBe(1)
    expect(travellersFrom({ num_travelers: 40 })).toBe(20)
  })
})

const ITINERARY = {
  days: [
    { date: '2026-12-10', slots: [{ activity: 'Arrive in Lisbon' }] },
    { date: '2026-12-11', slots: [{ activity: 'Small group walking tour of Belém' }, { activity: 'Fado night' }] },
  ],
}

describe('activityDate', () => {
  it('finds the day a named activity is scheduled on', () => {
    expect(activityDate(ITINERARY, 'Small Group Walking Tour of Belem')).toBe('2026-12-11')
    expect(activityDate(ITINERARY, 'Fado night')).toBe('2026-12-11')
    expect(activityDate(ITINERARY, 'Sintra day trip')).toBe(null)
    expect(activityDate(null, 'x')).toBe(null)
  })
})

describe('activitySpec', () => {
  const trip = { searchData: { destination: 'Lisbon, Portugal', num_travelers: 2 }, itinerary: ITINERARY }
  it('builds name, city, travellers, the itinerary date and the AI estimate', () => {
    expect(activitySpec({ name: 'Small group walking tour of Belém', price_usd: 30 }, trip, NOW)).toEqual({
      name: 'Small group walking tour of Belém', city: 'Lisbon', travellers: 2, date: '2026-12-11', estimate_price: 30,
    })
  })
  it('prefers the activity’s own city and leaves out unknown or past dates', () => {
    expect(activitySpec({ name: 'Tram 28', city: 'Porto' }, trip, NOW)).toEqual({ name: 'Tram 28', city: 'Porto', travellers: 2 })
    expect(activitySpec({ name: 'Fado night' }, trip, new Date(2026, 11, 20))).not.toHaveProperty('date')
  })
  it('is null without a name or a city', () => {
    expect(activitySpec({ name: '' }, trip)).toBe(null)
    expect(activitySpec({ name: 'Tour' }, null)).toBe(null)
  })
})

describe('watch labels', () => {
  const w = {
    status: 'active', currency: 'EUR', last_price: 23.26, subject: { travellers: 2 },
    last_observation: { unit_price: 11.63 },
  }
  it('reads per person in the listing currency', () => {
    expect(activityWatchingLabel(w)).toBe('Watching · from €11.63 pp')
    expect(perPerson({ ...w, last_observation: null })).toBe(11.63)
    expect(activityWatchingLabel({ ...w, status: 'paused' })).toBe('Watch paused')
    expect(activityWatchingLabel({ status: 'active' })).toBe('Watching')
  })
  it('names providers in text and spots a listing that isn’t the AI name', () => {
    expect(providerName('getyourguide')).toBe('GetYourGuide')
    expect(providerName('viator')).toBe('Viator')
    expect(titleDiffers('Belem walking tour', 'Small Group Walking Tour of Belém')).toBe(true)
    expect(titleDiffers('Small group walking tour of Belem', 'Small Group Walking Tour of Belém')).toBe(false)
  })
})
