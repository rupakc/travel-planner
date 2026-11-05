// @vitest-environment node
import { describe, it, expect } from 'vitest'
import {
  groupTotals, totalDifference, tripPreviewParts, isWatchablePlan, percent, rowBadge, rowPrice, tripReplanFare, tripRows,
  tripWatchingLabel, whatChanged,
} from './tripWatch'

const row = (over) => ({
  id: 'x', type: 'other', group: 'other', label: 'X', live: false, price: 10, currency: 'USD',
  in_total: true, status: 'estimate', ...over,
})
const FLIGHT = row({ id: 'flight', type: 'flight', group: 'flights', label: 'Flights', live: true, status: 'ok', price: 542, previous_price: 612, delta: -70 })
const HOTEL = row({ id: 'hotel', type: 'hotel', group: 'stay', label: 'Lumen Hotel', live: true, status: 'ok', price: 356, previous_price: 398, delta: -42 })
const SIM = row({ id: 'sim', label: 'SIM / eSIM', price: 13 })

describe('tripRows', () => {
  it('prefers the latest breakdown, else the frozen components', () => {
    expect(tripRows({ last_observation: { breakdown: [FLIGHT] }, subject: { components: [SIM] } })).toEqual([FLIGHT])
    expect(tripRows({ subject: { components: [SIM] } })).toEqual([SIM])
    expect(tripRows(null)).toEqual([])
  })
})

describe('groupTotals', () => {
  it('sums USD parts per group in a fixed order and skips parts outside the total', () => {
    const eur = row({ id: 'a', type: 'activity', group: 'activities', price: 50, currency: 'EUR', in_total: false })
    const g = groupTotals([SIM, HOTEL, FLIGHT, eur])
    expect(g.map(x => [x.key, x.amount])).toEqual([['flights', 542], ['stay', 356], ['other', 13]])
    expect(g.reduce((t, x) => t + x.share, 0)).toBeCloseTo(1)
  })
  it('formats tiny shares', () => {
    expect(percent(0.001)).toBe('<1%')
    expect(percent(0.426)).toBe('43%')
  })
})

describe('rowBadge and rowPrice', () => {
  it('labels live, estimate and degraded parts', () => {
    expect(rowBadge(FLIGHT).label).toBe('Live')
    expect(rowBadge(SIM).label).toBe('Estimate')
    expect(rowBadge(SIM).title).toMatch(/never trigger alerts/)
    expect(rowBadge({ ...HOTEL, status: 'unavailable' }).label).toBe('Unavailable')
    expect(rowBadge({ ...HOTEL, status: 'error' }).label).toBe('Not checked')
    expect(rowBadge({ ...HOTEL, status: 'stale' }).label).toBe('Live · earlier check')
  })
  it('shows a non-USD estimate in its own currency', () => {
    expect(rowPrice(row({ price: 24, currency: 'EUR' }))).toBe('€24.00')
    expect(rowPrice(FLIGHT)).toBe('$542')
  })
})

describe('whatChanged', () => {
  const w = (rows, n = 2) => ({ check_count: n, last_observation: { breakdown: rows } })
  it('names the live groups that moved, biggest drop first', () => {
    expect(whatChanged(w([HOTEL, FLIGHT, SIM]))).toBe('Last check: flights −$70.00, hotel −$42.00.')
  })
  it('groups activities and ignores estimates', () => {
    const a1 = row({ id: 'a1', type: 'activity', group: 'activities', live: true, status: 'ok', delta: -5 })
    const a2 = row({ id: 'a2', type: 'activity', group: 'activities', live: true, status: 'ok', delta: -7 })
    expect(whatChanged(w([a1, a2, { ...SIM, delta: -3 }]))).toBe('Last check: activities −$12.00.')
  })
  it('says when nothing moved and names parts it could not price', () => {
    const gone = { ...HOTEL, status: 'unavailable', delta: 0 }
    expect(whatChanged(w([{ ...FLIGHT, delta: 0 }, gone])))
      .toBe('Last check: no live price moved. Couldn’t price Lumen Hotel — kept the last live price.')
  })
  it('is null before the first re-check', () => {
    expect(whatChanged(w([FLIGHT], 1))).toBeNull()
    expect(whatChanged({})).toBeNull()
  })
})

describe('labels and plans', () => {
  it('reads "Watching · $2,140"', () => {
    expect(tripWatchingLabel({ status: 'active', last_price: 2140 })).toBe('Watching · $2,140')
    expect(tripWatchingLabel({ status: 'paused', last_price: 2140 })).toBe('Watch paused')
  })
  it('watches saved plans that have not departed', () => {
    const now = new Date('2026-11-05T00:00:00Z')
    expect(isWatchablePlan({ id: 3, search_data: { departure_date: '2026-12-10' } }, now)).toBe(true)
    expect(isWatchablePlan({ id: 3, search_data: { departure_date: '2026-11-05' } }, now)).toBe(false)
    expect(isWatchablePlan({ search_data: { departure_date: '2026-12-10' } }, now)).toBe(false)
  })
  it('re-plans from the live flight route', () => {
    const fare = { origin_label: 'Berlin', destination_label: 'Lisbon' }
    expect(tripReplanFare({ subject: { components: [{ type: 'flight', subject: fare }] } })).toBe(fare)
    expect(tripReplanFare({ subject: { components: [SIM] } })).toBeNull()
  })
})

describe('tripPreviewParts', () => {
  const sd = { departure_date: '2099-12-10', return_date: '2099-12-14', num_travelers: 2 }
  it('counts like the watch: activities per person × travellers', () => {
    const parts = tripPreviewParts({
      flight: { price_usd: 612 }, hotel: { total_price_usd: 398 },
      activities: [{ price_usd: 30 }, { price_usd: 20 }], sim: { price_usd: 13 },
    }, sd)
    expect(parts).toEqual([
      { key: 'flights', label: 'Flights', amount: 612, note: 'tracked as the cheapest fare on your dates' },
      { key: 'hotel', label: 'Hotel', amount: 398, note: null },
      { key: 'activities', label: 'Activities', amount: 100, note: 'per person × 2' },
      { key: 'sim', label: 'SIM / eSIM', amount: 13, note: null },
    ])
  })
  it('skips parts without a price', () => {
    expect(tripPreviewParts({ activities: [{ name: 'Free walk' }] }, sd)).toEqual([])
  })
})

describe('totalDifference', () => {
  const rows = [
    { id: 'flight', type: 'flight', live: true, price: 612 },
    { id: 'activity-0', type: 'activity', live: true, price: 60, unit: 'per person' },
  ]
  const w = { baseline_price: 685, subject: { travellers: 2, components: rows } }
  it('explains why the watched total differs from My Plan', () => {
    expect(totalDifference(w, 640)).toEqual({
      watched: 685, plan: 640, delta: 45,
      reasons: ['flights are the cheapest live fare on your dates, not the flight you picked', 'activities are counted per person × 2'],
    })
  })
  it('is null when they agree or there is no plan total', () => {
    expect(totalDifference(w, 685.4)).toBeNull()
    expect(totalDifference(w, null)).toBeNull()
  })
})
