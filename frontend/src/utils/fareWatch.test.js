import { describe, it, expect } from 'vitest'
import {
  tripFromSearch, tripFromPlan, tripKey, isWatchableTrip, watchStatus, priceChange,
  sparkGeometry, relativeTime, untilTime, defaultTarget, checkTarget, rangePosition,
  formatDateRange, travellersLabel, replanSearchData, notificationLink, newestUnseen,
  watchingLabel, routeLabel, cheapestFlightPrice,
} from './fareWatch'

const NOW = new Date('2026-11-04T12:00:00Z')

const watch = (over = {}) => ({
  id: 7, status: 'active', origin_label: 'Berlin, Germany', destination_label: 'Lisbon, Portugal',
  origin_code: 'BER', destination_code: 'LIS', departure_date: '2026-12-01', return_date: '2026-12-08',
  num_travelers: 2, baseline_price: 500, last_price: 454, lowest_price: 454, check_count: 3,
  alert_mode: 'any_drop', target_price: null, flexible_days: 0, history: [], ...over,
})

describe('trips', () => {
  it('builds a trip from search data and from a plan', () => {
    const sd = { origin: 'BER', destination: 'Lisbon', departure_date: '2026-12-01', return_date: '', num_travelers: 2, nationality: 'German' }
    expect(tripFromSearch(sd)).toEqual({ origin: 'BER', destination: 'Lisbon', departure_date: '2026-12-01', return_date: null, num_travelers: 2, destinations: null })
    expect(tripFromPlan({ id: 3, search_data: sd })).toMatchObject({ plan_id: 3, destination: 'Lisbon' })
    expect(tripFromSearch(null)).toBeNull()
  })

  it('keys trips case- and space-insensitively', () => {
    const a = tripKey({ origin: ' ber ', destination: 'Lisbon', departure_date: '2026-12-01', return_date: null, num_travelers: 2 })
    const b = tripKey({ origin: 'BER', destination: 'lisbon', departure_date: '2026-12-01', num_travelers: 2 })
    expect(a).toBe(b)
    expect(a).not.toBe(tripKey({ origin: 'BER', destination: 'lisbon', departure_date: '2026-12-01', num_travelers: 3 }))
  })

  it('watches only single-city trips departing after today', () => {
    const t = { origin: 'BER', destination: 'LIS', departure_date: '2026-11-05', num_travelers: 1 }
    expect(isWatchableTrip(t, NOW)).toBe(true)
    expect(isWatchableTrip({ ...t, departure_date: '2026-11-04' }, NOW)).toBe(false)
    expect(isWatchableTrip({ ...t, destinations: ['Paris', 'Rome'] }, NOW)).toBe(false)
    expect(isWatchableTrip({ ...t, destinations: ['LIS'] }, NOW)).toBe(true)
    expect(isWatchableTrip({ ...t, origin: '' }, NOW)).toBe(false)
    expect(isWatchableTrip(null, NOW)).toBe(false)
  })
})

describe('watchStatus', () => {
  it.each([
    [{}, 'dropped', 'Price dropped'],
    [{ last_price: 520 }, 'watching', 'Watching'],
    [{ last_price: 500 }, 'watching', 'Watching'],
    [{ baseline_price: null, last_price: null, check_count: 0 }, 'pending', 'Getting today’s price'],
    [{ status: 'paused' }, 'paused', 'Paused'],
    [{ status: 'expired' }, 'expired', 'Ended'],
    [{ status: 'error' }, 'problem', 'Can’t check right now'],
  ])('%o → %s', (over, key, label) => {
    expect(watchStatus(watch(over))).toMatchObject({ key, label })
  })
})

describe('priceChange', () => {
  it('describes drops, rises and no change in plain words', () => {
    expect(priceChange(watch())).toMatchObject({ delta: -46, direction: 'down', text: '$46 less than when you started' })
    expect(priceChange(watch({ last_price: 530 }))).toMatchObject({ delta: 30, direction: 'up', text: '$30 more than when you started' })
    expect(priceChange(watch({ last_price: 500.4 }))).toMatchObject({ direction: 'same', text: 'Same as when you started' })
    expect(priceChange(watch({ baseline_price: null }))).toBeNull()
  })
})

describe('sparkGeometry', () => {
  const hist = [{ price: 500 }, { price: 480 }, { price: null }, { price: 520 }, { price: 454 }]

  it('maps prices left→right, cheaper lower on screen is NOT used: higher price = higher line', () => {
    const g = sparkGeometry(hist, { width: 100, height: 20, pad: 0 })
    expect(g.points).toHaveLength(4)
    expect(g.points[0].x).toBe(0)
    expect(g.points[3].x).toBe(100)
    // 520 is the max → top (y=0); 454 the min → bottom (y=20)
    expect(g.points[2].y).toBe(0)
    expect(g.points[3].y).toBe(20)
    expect(g.line.startsWith('M0 ')).toBe(true)
    expect(g.min).toBe(454)
    expect(g.max).toBe(520)
  })

  it('includes the target in the scale and returns its y', () => {
    const g = sparkGeometry(hist, { width: 100, height: 20, pad: 0, target: 400 })
    expect(g.min).toBe(400)
    expect(g.targetY).toBe(20)
  })

  it('handles flat lines, a single point and no data', () => {
    const flat = sparkGeometry([{ price: 300 }, { price: 300 }], { width: 100, height: 20, pad: 0 })
    expect(flat.points.every(p => p.y === 10)).toBe(true)
    const one = sparkGeometry([{ price: 300 }], { width: 100, height: 20, pad: 0 })
    expect(one.points).toEqual([{ x: 100, y: 10, price: 300 }])
    expect(sparkGeometry([], { width: 100, height: 20 })).toBeNull()
  })
})

describe('time words', () => {
  it.each([
    ['2026-11-04T11:59:40Z', 'just now'],
    ['2026-11-04T11:55:00Z', '5 min ago'],
    ['2026-11-04T10:00:00Z', '2 h ago'],
    ['2026-11-03T10:00:00Z', 'yesterday'],
    ['2026-11-01T12:00:00Z', '3 days ago'],
  ])('relativeTime(%s) = %s', (iso, text) => {
    expect(relativeTime(iso, NOW)).toBe(text)
  })

  it('untilTime', () => {
    expect(untilTime('2026-11-04T15:00:00Z', NOW)).toBe('in 3 h')
    expect(untilTime('2026-11-04T12:20:00Z', NOW)).toBe('in 20 min')
    expect(untilTime('2026-11-04T11:00:00Z', NOW)).toBe('soon')
    expect(untilTime('2026-11-06T12:00:00Z', NOW)).toBe('in 2 days')
    expect(untilTime(null, NOW)).toBe('')
  })
})

describe('target helpers', () => {
  it('defaults to the low end of Google’s typical range when it is below today', () => {
    expect(defaultTarget({ typical_price_range: [452, 620] }, 500)).toBe(450)
    expect(defaultTarget({ typical_price_range: [520, 620] }, 500)).toBe(450)
    expect(defaultTarget(null, 500)).toBe(450)
    expect(defaultTarget(null, null)).toBe('')
  })

  it('validates a target', () => {
    expect(checkTarget('', 500).error).toMatch(/price/)
    expect(checkTarget('abc', 500).error).toBeTruthy()
    expect(checkTarget('0', 500).error).toBeTruthy()
    expect(checkTarget('-4', 500).error).toBeTruthy()
    expect(checkTarget('450', 500)).toEqual({ error: null, note: null, value: 450 })
    expect(checkTarget('$1,200', 1500).value).toBe(1200)
    expect(checkTarget('520', 500).note).toMatch(/already/)
  })

  it('places today’s price on the typical range bar', () => {
    expect(rangePosition([400, 600], 500)).toBeCloseTo(50, 0)
    expect(rangePosition([400, 600], 100)).toBe(0)
    expect(rangePosition([400, 600], 900)).toBe(100)
    expect(rangePosition(null, 500)).toBeNull()
  })
})

describe('labels', () => {
  it('formats dates, travellers, routes and the watching chip', () => {
    expect(formatDateRange('2026-12-01', '2026-12-08')).toBe('1–8 Dec')
    expect(formatDateRange('2026-11-28', '2026-12-05')).toBe('28 Nov – 5 Dec')
    expect(formatDateRange('2026-12-28', '2027-01-04')).toBe('28 Dec 2026 – 4 Jan 2027')
    expect(formatDateRange('2026-12-01', null)).toBe('1 Dec')
    expect(travellersLabel(1)).toBe('total for 1 traveller')
    expect(travellersLabel(3)).toBe('total for 3 travellers')
    expect(routeLabel(watch())).toBe('Berlin → Lisbon')
    expect(routeLabel(watch({ origin_label: '', origin_code: 'LHR,LGW' }))).toBe('LHR → Lisbon')
    expect(watchingLabel(watch())).toBe('Watching · $454')
    expect(watchingLabel(watch({ last_price: null }))).toBe('Watching')
    expect(watchingLabel(watch({ status: 'paused' }))).toBe('Watch paused')
  })
})

describe('replanSearchData', () => {
  const prefs = { nationality: 'German', interests: ['food'], residence_permits: ['EU'], existing_visas: [], accessibility_needs: [] }

  it('re-runs the watched trip with the traveller’s preferences', () => {
    const sd = replanSearchData(watch(), prefs)
    expect(sd).toMatchObject({
      origin: 'Berlin, Germany', destination: 'Lisbon, Portugal',
      departure_date: '2026-12-01', return_date: '2026-12-08',
      num_travelers: 2, adults: 2, children: 0, nationality: 'German', interests: ['food'],
    })
  })

  it('uses the cheapest nearby dates when asked and known', () => {
    const w = watch({ history: [{ price: 500, cheapest_departure_date: '2026-12-03', cheapest_return_date: '2026-12-10' }] })
    expect(replanSearchData(w, prefs, { cheapest: true })).toMatchObject({ departure_date: '2026-12-03', return_date: '2026-12-10' })
    expect(replanSearchData(watch(), prefs, { cheapest: true }).departure_date).toBe('2026-12-01')
  })

  it('works without preferences', () => {
    expect(replanSearchData(watch(), null)).toMatchObject({ nationality: '', interests: [] })
  })
})

describe('notifications', () => {
  it('links to the watch on the alerts page', () => {
    expect(notificationLink({ data: { watch_id: 7, links: { alerts: '/alerts?watch=7' } } })).toBe('/alerts?watch=7')
    expect(notificationLink({ data: { watch_id: 9 } })).toBe('/alerts?watch=9')
    expect(notificationLink({ data: {} })).toBe('/alerts')
    expect(notificationLink({ kind: 'trip_t7', data: { link: '/trips/4' } })).toBe('/trips/4')
    expect(notificationLink({ data: { link: 'https://x.test', watch_id: 2 } })).toBe('/alerts?watch=2')
  })

  it('finds the newest notification not yet seen', () => {
    const items = [{ id: 5 }, { id: 4 }, { id: 2 }]
    expect(newestUnseen(items, 4)).toEqual({ id: 5 })
    expect(newestUnseen(items, 5)).toBeNull()
    expect(newestUnseen([], 0)).toBeNull()
  })
})

describe('cheapestFlightPrice', () => {
  it('is the lowest priced flight card, or null', () => {
    expect(cheapestFlightPrice({ results: [{ price_usd: 530 }, { price_usd: 480 }, { price_usd: 0 }, {}] })).toBe(480)
    expect(cheapestFlightPrice({ results: [] })).toBeNull()
    expect(cheapestFlightPrice(null)).toBeNull()
    expect(cheapestFlightPrice({ legs: [{}], results: [{ price_usd: 100 }] })).toBeNull()
  })
})
