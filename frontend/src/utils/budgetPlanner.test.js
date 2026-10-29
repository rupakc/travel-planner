// @vitest-environment node
import { describe, it, expect } from 'vitest'
import {
  tripNights,
  flightKey,
  defaultAllocation,
  reallocate,
  withTotal,
  fitResults,
  capsFromFit,
} from './budgetPlanner'
import { buildBestValuePackage } from './bestValuePackage'

// 2026-04-01 → 2026-04-08 = 7 nights
const sd = (over = {}) => ({ departure_date: '2026-04-01', return_date: '2026-04-08', budget_usd: 3000, ...over })
const flight = (n, price, over = {}) => ({
  airline: 'Air', flight_number: n, price_usd: price, source: 'live',
  outbound: { airline: 'Air', flight_number: n, stops: 0, duration_minutes: 600 }, ...over,
})
const hotel = (name, nightly, over = {}) => ({ name, price_per_night_usd: nightly, star_rating: 3, review_score: 8, ...over })
const activity = (name, price, score, over = {}) => ({ name, price_usd: price, similarity_score: score, ...over })
const sum = (a) => a.flights + a.stay + a.activities + a.other

describe('tripNights', () => {
  it('counts nights from dates, minimum 1, default 7', () => {
    expect(tripNights(sd())).toBe(7)
    expect(tripNights(sd({ return_date: '2026-04-01' }))).toBe(1)
    expect(tripNights({})).toBe(7)
    expect(tripNights(null)).toBe(7)
    expect(tripNights(sd({ return_date: 'nope' }))).toBe(7)
  })
})

describe('flightKey', () => {
  it('is stable per fare and differs by leg, price, airline and number', () => {
    const f = flight('A1', 500)
    expect(flightKey(f)).toBe(flightKey({ ...f }))
    expect(flightKey(f)).not.toBe(flightKey(flight('A2', 500)))
    expect(flightKey(f)).not.toBe(flightKey(flight('A1', 501)))
    expect(flightKey(f)).not.toBe(flightKey({ ...f, leg_index: 1 }))
  })
})

describe('defaultAllocation', () => {
  const results = {
    flights: { results: [flight('A', 800), flight('B', 650), flight('J', 'varies')] },
    hotels: { results: [hotel('H1', 100), hotel('H2', 150), hotel('H3', 200), hotel('Bad', 'n/a')] },
  }

  it('returns null without a positive budget', () => {
    expect(defaultAllocation(sd({ budget_usd: null }), results)).toBeNull()
    expect(defaultAllocation(sd({ budget_usd: 0 }), results)).toBeNull()
    expect(defaultAllocation(sd({ budget_usd: 'lots' }), results)).toBeNull()
  })

  it('cheapest fare, median nightly × nights, 15% activities, rest to other', () => {
    expect(defaultAllocation(sd(), results)).toEqual({ flights: 650, stay: 1050, activities: 450, other: 850 })
  })

  it('sums exactly to the budget as integers', () => {
    const a = defaultAllocation(sd({ budget_usd: 2999.6 }), { flights: { results: [flight('A', 333.33)] } })
    expect(Object.values(a).every(Number.isInteger)).toBe(true)
    expect(sum(a)).toBe(3000)
  })

  it('multi-city sums the cheapest priced fare per leg', () => {
    const r = {
      flights: {
        legs: [
          { leg_index: 0, results: [flight('A', 200, { leg_index: 0 }), flight('B', 150, { leg_index: 0 })] },
          { leg_index: 1, results: [flight('C', 100, { leg_index: 1 })] },
          { leg_index: 2, results: [] },
        ],
      },
    }
    expect(defaultAllocation(sd(), r).flights).toBe(250)
  })

  it('scales flights/stay/activities down so other is never negative', () => {
    const a = defaultAllocation(sd({ budget_usd: 1000 }), results)
    expect(sum(a)).toBe(1000)
    expect(a.other).toBeGreaterThanOrEqual(0)
    expect(a.flights).toBeLessThan(650)
    expect(a.stay).toBeLessThan(1050)
    // proportions kept (within rounding)
    expect(a.stay / a.flights).toBeCloseTo(1050 / 650, 1)
  })

  it('missing or errored sections allocate 0', () => {
    const a = defaultAllocation(sd(), { flights: { error: 'x' } })
    expect(a).toEqual({ flights: 0, stay: 0, activities: 450, other: 2550 })
  })
})

describe('reallocate', () => {
  const base = { flights: 600, stay: 1000, activities: 400, other: 1000 }

  it('takes from other when a category grows, gives back when it shrinks', () => {
    expect(reallocate(base, 'stay', 1500, 3000)).toEqual({ ...base, stay: 1500, other: 500 })
    expect(reallocate(base, 'flights', 200, 3000)).toEqual({ ...base, flights: 200, other: 1400 })
  })

  it('clamps when other would go below zero, and at zero from below', () => {
    expect(reallocate(base, 'activities', 5000, 3000)).toEqual({ ...base, activities: 1400, other: 0 })
    expect(reallocate(base, 'activities', -50, 3000)).toEqual({ ...base, activities: 0, other: 1400 })
  })

  it('keeps the total constant and ignores other / unknown keys', () => {
    expect(sum(reallocate(base, 'stay', 1234, 3000))).toBe(3000)
    expect(reallocate(base, 'other', 10, 3000)).toBe(base)
    expect(reallocate(base, 'nope', 10, 3000)).toBe(base)
  })
})

describe('withTotal', () => {
  const base = { flights: 600, stay: 1000, activities: 400, other: 1000 }
  it('a larger or smaller total moves other first', () => {
    expect(withTotal(base, 4000)).toEqual({ ...base, other: 2000 })
    expect(withTotal(base, 2500)).toEqual({ ...base, other: 500 })
  })
  it('scales categories down when other cannot absorb the cut', () => {
    const a = withTotal(base, 1000)
    expect(sum(a)).toBe(1000)
    expect(a.other).toBeGreaterThanOrEqual(0)
    expect(a.stay).toBeLessThan(1000)
  })
  it('negative or junk totals become 0', () => {
    expect(sum(withTotal(base, -5))).toBe(0)
    expect(sum(withTotal(base, 'x'))).toBe(0)
  })
})

describe('fitResults', () => {
  const alloc = { flights: 700, stay: 1050, activities: 100, other: 1150 }

  it('hotels fit when nightly × nights ≤ stay; junk prices are unknown', () => {
    const r = { hotels: { results: [hotel('Cheap', 100), hotel('Edge', 150), hotel('Dear', 151), hotel('Junk', 'varies'), hotel('Zero', 0)] } }
    const fit = fitResults(r, alloc, sd())
    expect(fit.nights).toBe(7)
    expect([...fit.hotels.fits]).toEqual(['Cheap', 'Edge'])
    expect([...fit.hotels.over]).toEqual(['Dear'])
    expect(fit.hotels.count).toBe(2)
    expect(fit.hotels.total).toBe(3)
  })

  it('flights fit when price ≤ flights share; junk prices never fit nor count', () => {
    const ok = flight('OK', 700)
    const dear = flight('DEAR', 701)
    const junk = flight('J', 'tbd')
    const fit = fitResults({ flights: { results: [ok, dear, junk] } }, alloc, sd())
    expect(fit.flights.fits.has(flightKey(ok))).toBe(true)
    expect(fit.flights.fits.has(flightKey(dear))).toBe(false)
    expect(fit.flights.over.has(flightKey(dear))).toBe(true)
    expect(fit.flights.over.has(flightKey(junk))).toBe(false)
    expect(fit.flights.count).toBe(1)
    expect(fit.flights.total).toBe(2)
  })

  it('multi-city: each leg gets the flights share in proportion to its cheapest fare', () => {
    // cheapest: leg0 300, leg1 100 → total 400; share 600 → leg0 cap 450, leg1 cap 150
    const a0 = flight('A0', 300, { leg_index: 0 })
    const b0 = flight('B0', 450, { leg_index: 0 })
    const c0 = flight('C0', 451, { leg_index: 0 })
    const a1 = flight('A1', 100, { leg_index: 1 })
    const b1 = flight('B1', 160, { leg_index: 1 })
    const unknownLeg = flight('U2', 'n/a', { leg_index: 2 })
    const r = {
      flights: {
        legs: [
          { leg_index: 0, results: [a0, b0, c0] },
          { leg_index: 1, results: [a1, b1] },
          { leg_index: 2, results: [unknownLeg] },
        ],
      },
    }
    const fit = fitResults(r, { ...alloc, flights: 600 }, sd())
    expect([a0, b0, a1].every((f) => fit.flights.fits.has(flightKey(f)))).toBe(true)
    expect([c0, b1].every((f) => fit.flights.over.has(flightKey(f)))).toBe(true)
    expect(fit.flights.fits.has(flightKey(unknownLeg))).toBe(false)
    expect(fit.flights.over.has(flightKey(unknownLeg))).toBe(false)
    expect(fit.flights.count).toBe(3)
    expect(fit.flights.total).toBe(5)
  })

  it('activities: greedy by similarity desc, ties cheaper first, free ones always fit', () => {
    const r = {
      activities: {
        results: [
          activity('Big', 80, 0.9),
          activity('TieDear', 30, 0.7),
          activity('TieCheap', 15, 0.7),
          activity('Free', 0, 0.1),
          activity('Junk', 'varies', 1),
          activity('Late', 5, 0.2),
        ],
      },
    }
    const fit = fitResults(r, alloc, sd())
    // 80 (Big) + 15 (TieCheap) = 95; TieDear 30 would exceed 100; Late 5 → 100
    expect([...fit.activities.picked].sort()).toEqual(['Big', 'Free', 'Late', 'TieCheap'])
    expect(fit.activities.spent).toBe(100)
  })

  it('free activities fit even with a zero share', () => {
    const fit = fitResults({ activities: { results: [activity('Free', 0, 0.5), activity('Paid', 1, 0.9)] } }, { ...alloc, activities: 0 }, sd())
    expect([...fit.activities.picked]).toEqual(['Free'])
    expect(fit.activities.spent).toBe(0)
  })

  it('tolerates missing / errored sections', () => {
    const fit = fitResults({ hotels: { error: 'boom' } }, alloc, {})
    expect(fit.hotels).toMatchObject({ count: 0, total: 0 })
    expect(fit.flights).toMatchObject({ count: 0, total: 0 })
    expect(fit.activities.spent).toBe(0)
    expect(fit.nights).toBe(7)
  })
})

describe('best-value package with caps', () => {
  const results = {
    flights: { results: [flight('CHEAP', 400, { outbound: { airline: 'Air', flight_number: 'CHEAP', stops: 2, duration_minutes: 900 } }), flight('DIRECT', 450)] },
    hotels: { results: [hotel('Mid', 200, { review_score: 9 }), hotel('Budget', 80, { star_rating: 2, review_score: 7.5 })] },
  }
  const fitFor = (a) => capsFromFit(fitResults(results, a, sd()))

  it('limits the hotel and flight pools to what fits', () => {
    const caps = fitFor({ flights: 420, stay: 700, activities: 0, other: 1880 })
    const pkg = buildBestValuePackage(results, sd(), { caps })
    expect(pkg.selections.hotel.name).toBe('Budget')
    expect(pkg.selections.flight.flight_number).toBe('CHEAP')
    const uncapped = buildBestValuePackage(results, sd())
    expect(uncapped.selections.hotel.name).toBe('Mid')
    expect(uncapped.selections.flight.flight_number).toBe('DIRECT')
  })

  it('falls back to the uncapped behaviour when nothing fits', () => {
    const caps = fitFor({ flights: 10, stay: 10, activities: 0, other: 2980 })
    const pkg = buildBestValuePackage(results, sd(), { caps })
    expect(pkg.selections.hotel.name).toBe('Mid')
    expect(pkg.selections.flight.flight_number).toBe('DIRECT')
  })

  it('caps apply per multi-city leg', () => {
    const a0 = flight('A0', 300, { leg_index: 0, outbound: { airline: 'Air', flight_number: 'A0', stops: 1, duration_minutes: 600 } })
    const b0 = flight('B0', 330, { leg_index: 0 })
    const r = { flights: { legs: [{ leg_index: 0, results: [a0, b0] }] } }
    const caps = capsFromFit(fitResults(r, { flights: 310, stay: 0, activities: 0, other: 0 }, sd()))
    expect(buildBestValuePackage(r, sd(), { caps }).selections.flights[0].flight_number).toBe('A0')
    expect(buildBestValuePackage(r, sd()).selections.flights[0].flight_number).toBe('B0')
  })
})
