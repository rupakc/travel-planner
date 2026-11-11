import { describe, it, expect } from 'vitest'
import { initials, avatarHue } from './initials'

describe('initials', () => {
  it('takes one grapheme per word, for any script', () => {
    expect(initials('জন দো', 'x')).toBe('জদ')
    expect(initials('Jane Doe', 'x')).toBe('JD')
    expect(initials('महेश कुमार', 'x')).toBe('मक')
    expect(initials('山田', 'x')).toBe('山')
  })
  it('falls back to the username', () => {
    expect(initials(null, 'jane_doe')).toBe('J')
    expect(initials('  ', 'bob')).toBe('B')
    expect(initials(null, null)).toBe('?')
  })
  it('keeps at most two', () => {
    expect(initials('a b c d', 'x')).toBe('AB')
  })
})

describe('avatarHue', () => {
  it('is stable and within 0..359', () => {
    expect(avatarHue('jane')).toBe(avatarHue('jane'))
    for (const n of ['a', 'jane_doe', 'বাংলা', '']) {
      const h = avatarHue(n)
      expect(h).toBeGreaterThanOrEqual(0)
      expect(h).toBeLessThan(360)
    }
    expect(avatarHue('jane')).not.toBe(avatarHue('john'))
  })
})
