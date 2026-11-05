// @vitest-environment node
import { describe, it, expect } from 'vitest'
import {
  activityDate, activitySpec, activityWatchingLabel, formatPrice, messageTrip, perPerson, providerName,
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

describe('fix round 1', () => {
  it('sends a date only when it is after tomorrow locally (the server counts in UTC)', () => {
    const it = (date) => ({ days: [{ date, slots: [{ activity: 'Fado night' }] }] })
    const trip = (date) => ({ searchData: { destination: 'Lisbon' }, itinerary: it(date) })
    expect(activitySpec({ name: 'Fado night' }, trip('2026-11-06'), NOW)).not.toHaveProperty('date')
    expect(activitySpec({ name: 'Fado night' }, trip('2026-11-07'), NOW).date).toBe('2026-11-07')
  })

  describe('messageTrip: a chat message’s own trip', () => {
    const fallback = { searchData: { destination: 'Rome', num_travelers: 4 }, itinerary: null }
    it('uses the session context the message streamed', () => {
      const m = { tripContext: { destination: 'Lisbon', num_travelers: 2 } }
      expect(messageTrip(m, fallback)).toEqual({ searchData: { destination: 'Lisbon', num_travelers: 2 }, itinerary: null })
    })
    it('prefers the search it ran (search_context) over the session context', () => {
      const m = { searchContext: { destination: 'Porto', num_travelers: 3 }, tripContext: { destination: 'Lisbon' } }
      expect(messageTrip(m, fallback).searchData.destination).toBe('Porto')
    })
    it('else its planning destination or trip map', () => {
      expect(messageTrip({ planDestination: 'Porto' }, null).searchData.destination).toBe('Porto')
      const m = { tripMap: { cities: [{ city: 'Kyoto' }], num_travelers: 3 } }
      expect(messageTrip(m, null).searchData).toEqual({ destination: 'Kyoto', num_travelers: 3 })
    })
    it('falls back to the page’s trip, then to nothing', () => {
      expect(messageTrip({}, fallback)).toBe(fallback)
      expect(messageTrip({}, null)).toBe(null)
    })
    it('makes chat activity rows watchable without a page-level destination', () => {
      const trip = messageTrip({ planDestination: 'Lisbon, Portugal' }, { searchData: null, itinerary: null })
      expect(activitySpec({ name: 'Tram 28 ride' }, trip, NOW)).toEqual({ name: 'Tram 28 ride', city: 'Lisbon', travellers: 1 })
    })
  })
})
