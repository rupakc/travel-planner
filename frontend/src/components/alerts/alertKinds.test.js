// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { keepDeltaTogether } from './alertKinds'

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
