// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { socialOn } from './useSocial'

describe('socialOn', () => {
  it('is on only for features.social = 1 (or true)', () => {
    expect(socialOn({ features: { social: 1 } })).toBe(true)
    expect(socialOn({ features: { social: true } })).toBe(true)
    expect(socialOn({ features: { social: 0 } })).toBe(false)
    expect(socialOn({ features: {} })).toBe(false)
    expect(socialOn({})).toBe(false)
    expect(socialOn(null)).toBe(false)
  })
})
