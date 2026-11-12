import { describe, it, expect } from 'vitest'
import { alertsV2State } from './useAlertsV2'

const f = (features) => ({ features })

describe('alertsV2State', () => {
  it('is on by config', () => {
    expect(alertsV2State(f({ alerts_api: 2, price_alerts_v2: true, live_prices: true }), null))
      .toEqual({ on: true, livePrices: true, source: 'config' })
  })

  it('reports no live prices without a key', () => {
    expect(alertsV2State(f({ alerts_api: 2, price_alerts_v2: true, live_prices: false }), null))
      .toMatchObject({ on: true, livePrices: false })
  })

  it('is on by override only when alerts_api is 2', () => {
    expect(alertsV2State(f({ alerts_api: 2 }), '1')).toMatchObject({ on: true, source: 'override' })
    expect(alertsV2State(f({ alerts_api: 1 }), '1').on).toBe(false)
    expect(alertsV2State(f({ alerts_api: true }), '1').on).toBe(false)
  })

  it('is off on an old backend whatever is stored', () => {
    expect(alertsV2State(f({ price_alerts_v2: true }), '1')).toEqual({ on: false, livePrices: false, source: 'off' })
    expect(alertsV2State({}, '1').on).toBe(false)
    expect(alertsV2State(undefined, '1').on).toBe(false)
  })

  it('tp_alerts2=0 turns it off even when the server enables it', () => {
    expect(alertsV2State(f({ alerts_api: 2, price_alerts_v2: true }), '0').on).toBe(false)
  })

  it('is off without the flag or override', () => {
    expect(alertsV2State(f({ alerts_api: 2 }), null).on).toBe(false)
  })
})
