// @vitest-environment node
import { describe, it, expect } from 'vitest'

import {
  REMIX_PRESETS,
  applyRemix,
  snapshotMetrics,
  diffMetrics,
  formatMetricValue,
} from './remix'

const baseSearch = {
  origin: 'NYC',
  destination: 'Tokyo',
  departure_date: '2026-08-10',
  return_date: '2026-08-17',
  budget_usd: 3000,
  nationality: 'American',
  pace: 'balanced',
}

describe('REMIX_PRESETS', () => {
  it('exposes five presets with ids, labels and apply functions', () => {
    expect(REMIX_PRESETS).toHaveLength(5)
    for (const p of REMIX_PRESETS) {
      expect(p.id).toBeTruthy()
      expect(p.label).toBeTruthy()
      expect(typeof p.apply).toBe('function')
    }
  })
})

describe('applyRemix', () => {
  it('week_later shifts both dates by 7 days, preserving duration', () => {
    const out = applyRemix(baseSearch, 'week_later')
    expect(out.departure_date).toBe('2026-08-17')
    expect(out.return_date).toBe('2026-08-24')
  })

  it('week_later crosses month boundaries correctly', () => {
    const out = applyRemix(
      { ...baseSearch, departure_date: '2026-08-28', return_date: '2026-08-30' },
      'week_later'
    )
    expect(out.departure_date).toBe('2026-09-04')
    expect(out.return_date).toBe('2026-09-06')
  })

  it('week_later on a one-way trip only shifts departure', () => {
    const out = applyRemix({ ...baseSearch, return_date: null }, 'week_later')
    expect(out.departure_date).toBe('2026-08-17')
    expect(out.return_date).toBeNull()
  })

  it('half_budget halves and rounds the budget', () => {
    expect(applyRemix({ ...baseSearch, budget_usd: 3333 }, 'half_budget').budget_usd).toBe(1667)
  })

  it('half_budget with no budget is a no-op', () => {
    const noBudget = { ...baseSearch, budget_usd: null }
    expect(applyRemix(noBudget, 'half_budget')).toBe(noBudget)
  })

  it('luxe doubles the budget', () => {
    expect(applyRemix(baseSearch, 'luxe').budget_usd).toBe(6000)
  })

  it('slower_pace sets pace to relaxed and touches nothing else', () => {
    const out = applyRemix(baseSearch, 'slower_pace')
    expect(out.pace).toBe('relaxed')
    expect(out.departure_date).toBe(baseSearch.departure_date)
    expect(out.budget_usd).toBe(baseSearch.budget_usd)
  })

  it('long_weekend sets return to departure + 3 days', () => {
    expect(applyRemix(baseSearch, 'long_weekend').return_date).toBe('2026-08-13')
  })

  it('unknown preset returns the input unchanged', () => {
    expect(applyRemix(baseSearch, 'nope')).toBe(baseSearch)
  })

  it('does not mutate the input object', () => {
    const copy = { ...baseSearch }
    applyRemix(baseSearch, 'week_later')
    expect(baseSearch).toEqual(copy)
  })

  it('handles malformed departure_date gracefully', () => {
    const bad = { ...baseSearch, departure_date: 'not-a-date' }
    expect(applyRemix(bad, 'week_later')).toBe(bad)
    expect(applyRemix(bad, 'long_weekend')).toBe(bad)
  })
})

describe('snapshotMetrics', () => {
  const results = {
    flights: { results: [{ price_usd: 900 }, { price_usd: 750 }, { price_usd: 'x' }] },
    hotels: { results: [{ price_per_night_usd: 120 }, { price_per_night_usd: 95 }] },
    itinerary: { total_estimated_cost_usd: 1400 },
    weather: {
      days: [{ is_poor: true }, { is_poor: false }, { is_poor: true }],
    },
  }

  it('extracts min flight, min hotel nightly, itinerary total and poor weather days', () => {
    expect(snapshotMetrics(results)).toEqual({
      min_flight_usd: 750,
      min_hotel_nightly_usd: 95,
      itinerary_total_usd: 1400,
      poor_weather_days: 2,
    })
  })

  it('returns nulls for missing or empty sections', () => {
    expect(snapshotMetrics({})).toEqual({
      min_flight_usd: null,
      min_hotel_nightly_usd: null,
      itinerary_total_usd: null,
      poor_weather_days: null,
    })
  })

  it('ignores error payloads and non-numeric prices', () => {
    const snap = snapshotMetrics({
      flights: { error: 'boom' },
      hotels: { results: [{ price_per_night_usd: -5 }] },
      itinerary: { total_estimated_cost_usd: 'NaN' },
    })
    expect(snap.min_flight_usd).toBeNull()
    expect(snap.min_hotel_nightly_usd).toBeNull()
    expect(snap.itinerary_total_usd).toBeNull()
  })
})

describe('diffMetrics', () => {
  it('computes deltas with direction and improvement flags', () => {
    const before = {
      min_flight_usd: 900,
      min_hotel_nightly_usd: 100,
      itinerary_total_usd: 1400,
      poor_weather_days: 3,
    }
    const after = {
      min_flight_usd: 700,
      min_hotel_nightly_usd: 130,
      itinerary_total_usd: 1400,
      poor_weather_days: 1,
    }
    const rows = diffMetrics(before, after)
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]))

    expect(byKey.min_flight_usd).toMatchObject({
      delta: -200,
      direction: 'down',
      improved: true,
    })
    expect(byKey.min_hotel_nightly_usd).toMatchObject({
      delta: 30,
      direction: 'up',
      improved: false,
    })
    expect(byKey.itinerary_total_usd).toMatchObject({
      delta: 0,
      direction: 'same',
      improved: null,
    })
    expect(byKey.poor_weather_days).toMatchObject({ delta: -2, improved: true })
  })

  it('skips metrics missing on either side', () => {
    const rows = diffMetrics({ min_flight_usd: 900 }, { min_flight_usd: null })
    expect(rows).toEqual([])
  })
})

describe('formatMetricValue', () => {
  it('formats usd values with $ and thousands separators', () => {
    expect(formatMetricValue(1234.6, 'usd')).toBe('$1,235')
  })

  it('formats counts as plain strings and null as em dash', () => {
    expect(formatMetricValue(3, 'count')).toBe('3')
    expect(formatMetricValue(null, 'usd')).toBe('—')
  })
})
