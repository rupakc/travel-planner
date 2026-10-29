// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { buildCompareRequests, bestByRow, fmtUsd, fmtDuration, compareErrorReason } from './compare'

const base = {
  origin: 'NYC', departure_date: '2026-04-01', return_date: '2026-04-08',
  nationality: 'American', residence_permits: [], existing_visas: [],
  interests: ['food'], budget_usd: '3000', adults: 2, children: 1, seniors: 0, infants: 0,
}

describe('buildCompareRequests', () => {
  it('shares fields and differs only in destination', () => {
    const reqs = buildCompareRequests({ ...base, destinations: ['Tokyo', 'Paris'] })
    expect(reqs).toHaveLength(2)
    const { destination: a, ...restA } = reqs[0]
    const { destination: b, ...restB } = reqs[1]
    expect([a, b]).toEqual(['Tokyo', 'Paris'])
    expect(restA).toEqual(restB)
    expect(reqs[0]).toMatchObject({ num_travelers: 3, budget_usd: 3000, destinations: null, destination_nights: null, origin: 'NYC' })
    expect(reqs[0]).not.toHaveProperty('extraStops')
  })
  it('drops blanks and case-insensitive duplicates, trims', () => {
    const reqs = buildCompareRequests({ ...base, destinations: ['Tokyo', '  ', 'tokyo ', 'Paris', ''] })
    expect(reqs.map((r) => r.destination)).toEqual(['Tokyo', 'Paris'])
  })
  it('empty budget becomes null', () => {
    expect(buildCompareRequests({ ...base, budget_usd: '', destinations: ['Rome'] })[0].budget_usd).toBeNull()
  })
  it('blank return date becomes null (one-way), set one is kept', () => {
    expect(buildCompareRequests({ ...base, return_date: '', destinations: ['Rome'] })[0].return_date).toBeNull()
    expect(buildCompareRequests({ ...base, destinations: ['Rome'] })[0].return_date).toBe('2026-04-08')
  })
})

const s = (over) => ({
  estimate: { total_usd: 1000 }, flight: { price_usd: 500 }, hotel: { typical_nightly_usd: 100 },
  weather: { poor_days: 2 }, ease: { total: 80, safety: 15, english: 10 }, daily_cost_usd: 90, ...over,
})

describe('bestByRow', () => {
  it('picks lowest for costs and highest for scores', () => {
    const best = bestByRow([s(), s({ estimate: { total_usd: 800 }, ease: { total: 90, safety: 12, english: 10 }, weather: { poor_days: 0 } })])
    expect([...best.estimate]).toEqual([1])
    expect([...best.weather]).toEqual([1])
    expect([...best.ease]).toEqual([1])
    expect([...best.safety]).toEqual([0])
  })
  it('marks ties', () => {
    expect([...bestByRow([s(), s()]).english].sort()).toEqual([0, 1])
  })
  it('skips rows with fewer than two values and ignores junk/null columns', () => {
    const best = bestByRow([s(), null, s({ flight: null, daily_cost_usd: 'x' })])
    expect(best.flight).toBeUndefined()
    expect(best.daily).toBeUndefined()
    expect(best.estimate).toBeDefined()
  })
  it('never awards Best cost to a partial estimate', () => {
    const best = bestByRow([
      s({ estimate: { total_usd: 400, partial: true } }),
      s({ estimate: { total_usd: 1000, partial: false } }),
      s({ estimate: { total_usd: 1200, partial: false } }),
    ])
    expect([...best.estimate]).toEqual([1])
    const onlyOneComplete = bestByRow([
      s({ estimate: { total_usd: 400, partial: true } }),
      s({ estimate: { total_usd: 1000, partial: false } }),
    ])
    expect(onlyOneComplete.estimate).toBeUndefined()
  })
})

describe('compareErrorReason', () => {
  const httpErr = (status, data) => ({ response: { status, data } })
  it('uses a string detail', () => {
    expect(compareErrorReason(httpErr(422, { detail: 'Compare supports single destinations only' })))
      .toBe('Compare supports single destinations only')
    expect(compareErrorReason(httpErr(502, { detail: 'All sources failed' }))).toBe('All sources failed')
  })
  it('generic text for non-string 4xx detail', () => {
    expect(compareErrorReason(httpErr(422, { detail: [{ loc: ['body', 'return_date'], msg: 'bad' }] })))
      .toBe('Please check the trip details')
    expect(compareErrorReason(httpErr(400, {}))).toBe('Please check the trip details')
  })
  it('generic text for 5xx and network errors', () => {
    expect(compareErrorReason(httpErr(500, { detail: { x: 1 } }))).toBe('Service unavailable — try again')
    expect(compareErrorReason(new Error('Network Error'))).toBe('Service unavailable — try again')
    expect(compareErrorReason(undefined)).toBe('Service unavailable — try again')
  })
})

describe('formatters', () => {
  it('format values', () => {
    expect(fmtUsd(1234.4)).toBe('$1,234')
    expect(fmtUsd(null)).toBe('—')
    expect(fmtDuration(125)).toBe('2h 5m')
    expect(fmtDuration(null)).toBeNull()
  })
})
