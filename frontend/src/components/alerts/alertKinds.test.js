// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { keepDeltaTogether, kindOf, alertKindFor, ALERT_KINDS } from './alertKinds'

describe('keepDeltaTogether', () => {
  it('joins the minus sign to the amount so the delta never splits', () => {
    expect(keepDeltaTogether('Berlin → Lisbon dropped to $150 (−$70)'))
      .toBe('Berlin → Lisbon dropped to $150 (−⁠$70)')
  })
  it('leaves other text and non-strings alone', () => {
    expect(keepDeltaTogether('Watch expired')).toBe('Watch expired')
    expect(keepDeltaTogether(undefined)).toBe(undefined)
  })
})

describe('trip kinds', () => {
  it('have their own icon and action, not the watch_expired fallback', () => {
    for (const k of ['trip_t30', 'trip_t7', 'trip_t1', 'trip_morning']) {
      expect(kindOf(k)).toBe(ALERT_KINDS[k])
      expect(alertKindFor({ kind: k }).action).toMatch(/^Open /)
    }
  })
})
