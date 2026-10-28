// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { toRecentSearch, recentSearchToForm, describeRecentSearch } from './recentSearches'

const form = {
  origin: 'New York, USA (JFK)',
  destination: 'Tokyo, Japan (HND)',
  departure_date: '2027-04-01',
  return_date: '2027-04-08',
  nationality: 'American',
  residence_permits: ['Schengen'],
  existing_visas: [],
  interests: ['food', 'history'],
  budget_usd: '3000',
  num_travelers: 3,
  adults: 2, children: 1, seniors: 0, infants: 0,
  accessibility_needs: [],
  serendipity: 0.7,
}

// The search request both SearchPage and the Results "Search Criteria" panel
// submit: the form plus journey-ordered destinations (stops first, the To
// city last) and per-stop nights.
const searchData = (overrides = {}) => ({
  ...form,
  budget_usd: 3000,
  destinations: null,
  destination_nights: null,
  ...overrides,
})

describe('toRecentSearch', () => {
  it('captures every field needed to refill the form', () => {
    expect(toRecentSearch(searchData())).toEqual({
      origin: 'New York, USA (JFK)',
      destination: 'Tokyo, Japan (HND)',
      departure_date: '2027-04-01',
      return_date: '2027-04-08',
      stops: [],
      nationality: 'American',
      residence_permits: ['Schengen'],
      existing_visas: [],
      interests: ['food', 'history'],
      budget_usd: 3000,
      adults: 2, children: 1, seniors: 0, infants: 0,
      accessibility_needs: [],
      serendipity: 0.7,
    })
  })

  it('turns the multi-city journey into stops, without the final destination', () => {
    const sd = searchData({
      destinations: ['Seoul, South Korea', 'Osaka, Japan', 'Tokyo, Japan (HND)'],
      destination_nights: [2, null, null],
    })
    expect(toRecentSearch(sd).stops).toEqual([
      { city: 'Seoul, South Korea', nights: 2 },
      { city: 'Osaka, Japan', nights: null },
    ])
  })

  it('tolerates missing nights for the stops', () => {
    const sd = searchData({ destinations: ['Seoul, South Korea', 'Tokyo, Japan (HND)'], destination_nights: undefined })
    expect(toRecentSearch(sd).stops).toEqual([{ city: 'Seoul, South Korea', nights: null }])
  })

  it('sends an empty budget or return date as null', () => {
    const saved = toRecentSearch(searchData({ budget_usd: null, return_date: '' }))
    expect(saved.budget_usd).toBeNull()
    expect(saved.return_date).toBeNull()
  })

  it('defaults traveler counts on searches that only carry num_travelers', () => {
    const { adults, children, seniors, infants, ...rest } = searchData()
    void adults; void children; void seniors; void infants
    const saved = toRecentSearch({ ...rest, num_travelers: 2 })
    expect([saved.adults, saved.children, saved.seniors, saved.infants]).toEqual([2, 0, 0, 0])
  })
})

describe('recentSearchToForm', () => {
  const saved = toRecentSearch(searchData({ destinations: ['Seoul, South Korea', 'Tokyo, Japan (HND)'], destination_nights: [2, null] }))

  it('restores the form and stops exactly when the dates are still ahead', () => {
    const { form: restored, extraStops, datesShifted } = recentSearchToForm(saved, '2027-01-15')
    expect(datesShifted).toBe(false)
    expect(restored).toEqual({
      origin: form.origin,
      destination: form.destination,
      departure_date: '2027-04-01',
      return_date: '2027-04-08',
      nationality: 'American',
      residence_permits: ['Schengen'],
      existing_visas: [],
      interests: ['food', 'history'],
      budget_usd: '3000',
      num_travelers: 3,
      adults: 2, children: 1, seniors: 0, infants: 0,
      accessibility_needs: [],
      serendipity: 0.7,
    })
    expect(extraStops).toEqual([{ city: 'Seoul, South Korea', nights: '2' }])
  })

  it('a departure of today still counts as ahead', () => {
    expect(recentSearchToForm(saved, '2027-04-01').datesShifted).toBe(false)
  })

  it('moves past dates a week out and keeps the trip length', () => {
    const { form: restored, datesShifted } = recentSearchToForm(saved, '2027-06-28')
    expect(datesShifted).toBe(true)
    expect(restored.departure_date).toBe('2027-07-05')
    expect(restored.return_date).toBe('2027-07-12')
  })

  it('shifts a one-way search without inventing a return date', () => {
    const oneWay = { ...saved, return_date: null }
    const { form: restored } = recentSearchToForm(oneWay, '2027-06-28')
    expect(restored.departure_date).toBe('2027-07-05')
    expect(restored.return_date).toBe('')
  })

  it('fills defaults for fields missing from older entries', () => {
    const minimal = { origin: 'A', destination: 'B', departure_date: '2027-04-01' }
    const { form: restored, extraStops } = recentSearchToForm(minimal, '2027-01-01')
    expect(restored.interests).toEqual([])
    expect(restored.adults).toBe(1)
    expect(restored.num_travelers).toBe(1)
    expect(restored.budget_usd).toBe('')
    expect(restored.serendipity).toBe(0.5)
    expect(extraStops).toEqual([])
  })
})

describe('describeRecentSearch', () => {
  it('summarises route, dates, interests and travellers', () => {
    const saved = toRecentSearch(searchData({ destinations: ['Seoul, South Korea', 'Tokyo, Japan (HND)'], destination_nights: [2, null] }))
    expect(describeRecentSearch(saved)).toEqual({
      route: 'New York → Seoul → Tokyo',
      dates: 'Apr 1 – Apr 8, 2027',
      interests: ['food', 'history'],
      travelers: 3,
    })
  })

  it('handles one-way trips and dates across years', () => {
    expect(describeRecentSearch({ origin: 'A', destination: 'B', departure_date: '2027-12-30' }).dates).toBe('Dec 30, 2027')
    expect(describeRecentSearch({ origin: 'A', destination: 'B', departure_date: '2027-12-30', return_date: '2028-01-04' }).dates)
      .toBe('Dec 30, 2027 – Jan 4, 2028')
  })
})
