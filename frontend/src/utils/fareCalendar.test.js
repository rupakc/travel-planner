import { describe, it, expect } from 'vitest'
import {
  shiftDates, dayOffset, cheapestDeparture, fareDelta, formatDelta,
  formatDay, formatTripRange, replanPrompt, priceInsightsChip, formatUsd, daysUntil,
} from './fareCalendar'

describe('shiftDates / dayOffset', () => {
  it('shifts both dates by the same offset, keeping trip length', () => {
    expect(shiftDates('2026-10-30', '2026-11-06', 4)).toEqual({
      departure_date: '2026-11-03', return_date: '2026-11-10',
    })
    expect(shiftDates('2026-03-01', '2026-03-08', -1)).toEqual({
      departure_date: '2026-02-28', return_date: '2026-03-07',
    })
  })

  it('keeps a missing return date missing', () => {
    expect(shiftDates('2026-10-30', null, 2)).toEqual({ departure_date: '2026-11-01', return_date: null })
  })

  it('counts whole days between dates', () => {
    expect(dayOffset('2026-10-30', '2026-11-03')).toBe(4)
    expect(dayOffset('2026-11-03', '2026-10-30')).toBe(-4)
    expect(dayOffset('2026-03-28', '2026-03-30')).toBe(2) // across a DST switch
  })
})

describe('cheapest and deltas', () => {
  const dates = [
    { departure_date: '2026-10-28', cheapest_usd: 520, is_selected: false },
    { departure_date: '2026-10-29', cheapest_usd: null, is_selected: false },
    { departure_date: '2026-10-30', cheapest_usd: 565, is_selected: true },
    { departure_date: '2026-10-31', cheapest_usd: 610, is_selected: false },
  ]

  it('finds the cheapest priced date', () => {
    expect(cheapestDeparture(dates)).toBe('2026-10-28')
    expect(cheapestDeparture([{ departure_date: 'x', cheapest_usd: null }])).toBeNull()
    expect(cheapestDeparture([])).toBeNull()
  })

  it('computes the delta against the selected date', () => {
    expect(fareDelta(dates[0], dates[2])).toBe(-45)
    expect(fareDelta(dates[3], dates[2])).toBe(45)
    expect(fareDelta(dates[1], dates[2])).toBeNull()
    expect(fareDelta(dates[0], { cheapest_usd: null })).toBeNull()
    expect(fareDelta(dates[0], undefined)).toBeNull()
  })

  it('formats deltas with a real minus sign', () => {
    expect(formatDelta(-45)).toBe('−$45')
    expect(formatDelta(1230)).toBe('+$1,230')
    expect(formatDelta(0)).toBe('same')
    expect(formatDelta(null)).toBe('')
    expect(formatDelta(-44.6)).toBe('−$45')
  })

  it('formats prices in whole dollars', () => {
    expect(formatUsd(1480.4)).toBe('$1,480')
  })
})

describe('date labels', () => {
  it('formats a day as weekday, day and month', () => {
    expect(formatDay('2026-11-03')).toBe('Tue 3 Nov')
  })

  it('formats a trip range and one-way trips', () => {
    expect(formatTripRange('2026-11-03', '2026-11-10')).toBe('Tue 3 Nov – Tue 10 Nov')
    expect(formatTripRange('2026-11-03', null)).toBe('Tue 3 Nov')
  })

  it('builds the re-plan confirmation', () => {
    expect(replanPrompt('2026-11-03', '2026-11-10')).toBe('Re-plan for Tue 3 Nov – Tue 10 Nov? This runs a new search.')
  })
})

describe('priceInsightsChip', () => {
  it('describes the price level with the typical range', () => {
    expect(priceInsightsChip({ price_level: 'low', typical_price_range: [420, 610] })).toEqual({
      level: 'low', text: 'Fares are low right now · typical $420–$610',
    })
    expect(priceInsightsChip({ price_level: 'high', typical_price_range: [1420, 1610] }).text)
      .toBe('Fares are high right now · typical $1,420–$1,610')
  })

  it('omits a missing or malformed range', () => {
    expect(priceInsightsChip({ price_level: 'typical' })).toEqual({ level: 'typical', text: 'Fares are typical right now' })
    expect(priceInsightsChip({ price_level: 'typical', typical_price_range: ['a', 3] }).text).toBe('Fares are typical right now')
  })

  it('returns null without a known level', () => {
    expect(priceInsightsChip(null)).toBeNull()
    expect(priceInsightsChip({ lowest_price: 300 })).toBeNull()
    expect(priceInsightsChip({ price_level: 'wild' })).toBeNull()
  })
})

describe('daysUntil', () => {
  const now = new Date(2026, 9, 29, 18, 30) // local 29 Oct, evening

  it('counts calendar days from today to the departure date', () => {
    expect(daysUntil('2026-11-03', now)).toBe(5)
    expect(daysUntil('2026-10-29', now)).toBe(0)
  })

  it('never goes negative and tolerates a missing date', () => {
    expect(daysUntil('2026-10-01', now)).toBe(0)
    expect(daysUntil(undefined, now)).toBe(0)
    expect(daysUntil('Tokyo, Japan', now)).toBe(0)
  })
})
