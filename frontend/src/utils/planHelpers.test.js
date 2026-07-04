// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { computePlanCost, countSelections, sameFlight, EMPTY_SELECTIONS } from './planHelpers'

const legFlight = (legIndex, price, airline = 'TestAir', flightNumber = 'TA1') => ({
  leg_index: legIndex,
  price_usd: price,
  outbound: { airline, flight_number: flightNumber, stops: 0 },
})

describe('sameFlight', () => {
  it('matches identical per-leg flights', () => {
    expect(sameFlight(legFlight(0, 100), legFlight(0, 100))).toBe(true)
  })

  it('distinguishes legs, prices and airlines', () => {
    expect(sameFlight(legFlight(0, 100), legFlight(1, 100))).toBe(false)
    expect(sameFlight(legFlight(0, 100), legFlight(0, 200))).toBe(false)
    expect(sameFlight(legFlight(0, 100, 'A'), legFlight(0, 100, 'B'))).toBe(false)
  })

  it('handles flat legacy flights and null', () => {
    const flat = { airline: 'X', flight_number: '1', price_usd: 50 }
    expect(sameFlight(flat, { ...flat })).toBe(true)
    expect(sameFlight(null, flat)).toBe(false)
    expect(sameFlight(flat, undefined)).toBe(false)
  })
})

describe('countSelections with multi-city flights', () => {
  it('counts each selected leg', () => {
    const sel = { ...EMPTY_SELECTIONS, flights: [legFlight(0, 100), legFlight(1, 90)] }
    expect(countSelections(sel)).toBe(2)
  })

  it('EMPTY_SELECTIONS counts zero and includes flights key', () => {
    expect(EMPTY_SELECTIONS.flights).toEqual([])
    expect(countSelections(EMPTY_SELECTIONS)).toBe(0)
  })
})

describe('computePlanCost with multi-city flights', () => {
  it('sums all leg prices', () => {
    const sel = { flights: [legFlight(0, 100), legFlight(1, 90), legFlight(2, 110)] }
    expect(computePlanCost(sel)).toBe(300)
  })

  it('ignores legs without prices and combines with hotel', () => {
    const sel = {
      flights: [legFlight(0, 100), { leg_index: 1 }],
      hotel: { total_price_usd: 500 },
    }
    expect(computePlanCost(sel)).toBe(600)
  })
})
