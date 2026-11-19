import { describe, it, expect } from 'vitest'
import { cheapest, carbonRequestFromResults } from './carbon'

describe('carbon request builder', () => {
  it('picks the lowest price, missing or 0 prices last', () => {
    expect(cheapest([{ id: 1, price_usd: 0 }, { id: 2, price_usd: 300 }, { id: 3, price_usd: 120 }]).id).toBe(3)
    expect(cheapest([{ id: 1 }, { id: 2 }]).id).toBe(1)
    expect(cheapest([])).toBeNull()
    expect(cheapest(null)).toBeNull()
  })

  it('sends the cheapest flight per multi-city leg, not the first', () => {
    const body = carbonRequestFromResults({
      searchData: { origin: 'LHR', destination: 'Paris' },
      results: {
        flights: {
          legs: [
            { results: [{ origin: 'LHR', destination: 'CDG', price_usd: 400 }, { origin: 'LGW', destination: 'CDG', price_usd: 90 }] },
            { results: [{ origin: 'CDG', destination: 'FCO', price_usd: 70 }] },
          ],
        },
      },
    })
    expect(body.results.flights.legs.map((l) => l.results[0].origin)).toEqual(['LGW', 'CDG'])
  })
})
