// @vitest-environment node
import { describe, it, expect } from 'vitest'
import {
  ALERT_TABS, countByTab, inTab, isUnavailable, matchKey, priceCheckMessage, priceWatchBody,
  priceWatchLink, watchKind, watchDomId,
} from './priceWatch'

const fare = { id: 7, origin_code: 'BER', destination_code: 'LIS', status: 'active' }
const hotel = { id: 7, kind: 'hotel', title: 'Lumen Hotel', status: 'active' }
const trip = { id: 9, kind: 'trip', title: 'Lisbon trip', status: 'expired' }

describe('watch kinds and tabs', () => {
  it('fare watches are flights; price watches carry their kind', () => {
    expect(watchKind(fare)).toBe('flight')
    expect(watchKind(hotel)).toBe('hotel')
  })

  it('has All · Flights · Hotels · Activities · Trips', () => {
    expect(ALERT_TABS.map(t => t.label)).toEqual(['All', 'Flights', 'Hotels', 'Activities', 'Trips'])
  })

  it('counts and filters per tab', () => {
    const list = [fare, hotel, trip]
    expect(countByTab(list)).toEqual({ all: 3, flight: 1, hotel: 1, activity: 0, trip: 1 })
    expect(list.filter(w => inTab(w, 'hotel'))).toEqual([hotel])
    expect(list.filter(w => inTab(w, 'all'))).toEqual(list)
  })

  it('fare and price watches with the same id get different DOM ids and links', () => {
    expect(watchDomId(fare)).toBe('watch-7')
    expect(watchDomId(hotel)).toBe('price-watch-7')
    expect(priceWatchLink(hotel)).toBe('/alerts?kind=hotel&watch=7')
  })
})

describe('matchKey', () => {
  it('is stable regardless of key order', () => {
    expect(matchKey('hotel', { b: 1, a: 'x' })).toBe(matchKey('hotel', { a: 'x', b: 1 }))
    expect(matchKey('hotel', { a: 1 })).not.toBe(matchKey('activity', { a: 1 }))
  })
})

describe('priceWatchBody', () => {
  it('nests the spec under its kind', () => {
    expect(priceWatchBody('hotel', { name: 'Lumen' }, { alert_mode: 'any_drop' }))
      .toEqual({ kind: 'hotel', hotel: { name: 'Lumen' }, alert_mode: 'any_drop' })
  })
})

describe('isUnavailable', () => {
  it('reads the latest look', () => {
    expect(isUnavailable({ last_observation: { status: 'unavailable' } })).toBe(true)
    expect(isUnavailable({ last_observation: { status: 'ok' } })).toBe(false)
    expect(isUnavailable({})).toBe(false)
  })
})

describe('priceCheckMessage', () => {
  it.each([
    [{ check_status: 'checked', notification: { title: 'Dropped to $352' } }, 'good', 'Dropped to $352'],
    [{ check_status: 'checked', last_price: 398 }, 'neutral', 'Checked just now: $398'],
    [{ check_status: 'unavailable' }, 'warn', 'isn’t available'],
    [{ check_status: 'failed' }, 'warn', 'within the hour'],
    [{ check_status: 'errored' }, 'warn', 'on hold'],
    [{ check_status: 'expired' }, 'neutral', 'ended'],
    [{ check_status: 'postponed' }, 'warn', 'tomorrow'],
    [{ check_status: 'deleted' }, 'neutral', 'removed'],
    [{ check_status: 'skipped' }, 'neutral', 'isn’t being watched'],
  ])('%o', (res, tone, text) => {
    const m = priceCheckMessage(res)
    expect(m.tone).toBe(tone)
    expect(m.text).toContain(text)
  })
})
