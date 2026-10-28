// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { computePlanCost, computePlanCostBreakdown, countSelections, sameFlight, EMPTY_SELECTIONS } from './planHelpers'

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

describe('computePlanCostBreakdown', () => {
  const fullPlan = {
    ...EMPTY_SELECTIONS,
    flight: { price_usd: 900 },
    flights: [legFlight(0, 150), legFlight(1, 50)],
    hotel: { total_price_usd: 1400 },
    activities: [{ price_usd: 60 }, { price_usd: 40 }, { name: 'Free walk' }],
    sim: { price_usd: 25 },
  }

  it('splits the plan into categories, biggest cost first', () => {
    expect(computePlanCostBreakdown(fullPlan)).toEqual([
      { key: 'hotel', label: 'Hotel', amount: 1400 },
      { key: 'flights', label: 'Flights', amount: 1100 },
      { key: 'activities', label: 'Activities', amount: 100 },
      { key: 'sim', label: 'SIM / eSIM', amount: 25 },
    ])
  })

  it('parts always add up to computePlanCost', () => {
    const parts = computePlanCostBreakdown(fullPlan)
    expect(parts.reduce((t, p) => t + p.amount, 0)).toBe(computePlanCost(fullPlan))
  })

  it('leaves out categories with nothing priced', () => {
    const sel = { ...EMPTY_SELECTIONS, hotel: { total_price_usd: 300 }, activities: [{ name: 'Free walk' }] }
    expect(computePlanCostBreakdown(sel)).toEqual([{ key: 'hotel', label: 'Hotel', amount: 300 }])
  })

  it('is empty for an empty plan or missing selections', () => {
    expect(computePlanCostBreakdown(EMPTY_SELECTIONS)).toEqual([])
    expect(computePlanCostBreakdown(null)).toEqual([])
  })

  it('prices a nightly-rate hotel by the trip length', () => {
    const sel = { hotel: { price_per_night_usd: 100 } }
    const trip = { departure_date: '2027-04-01', return_date: '2027-04-05' }
    expect(computePlanCostBreakdown(sel, trip)).toEqual([{ key: 'hotel', label: 'Hotel', amount: 400 }])
  })

  it('assumes 7 nights for a nightly-rate hotel when dates are unknown', () => {
    const sel = { hotel: { price_per_night_usd: 100 } }
    expect(computePlanCostBreakdown(sel)[0].amount).toBe(700)
  })

  it('accepts numeric strings and ignores prices that are not numbers', () => {
    const sel = { activities: [{ price_usd: '30' }, { price_usd: 'varies' }], sim: { price_usd: 'n/a' } }
    expect(computePlanCostBreakdown(sel)).toEqual([{ key: 'activities', label: 'Activities', amount: 30 }])
    expect(computePlanCost(sel)).toBe(30)
  })
})
