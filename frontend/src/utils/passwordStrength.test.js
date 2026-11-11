// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { passwordStrength } from './passwordStrength'

describe('passwordStrength', () => {
  it('rates repeats low', () => {
    const r = passwordStrength('aaaaaaaaaa')
    expect(r.score).toBeLessThan(2)
    expect(r.hints).toContain('repeats')
  })
  it('rates a passphrase well', () => {
    expect(passwordStrength('correct horse battery').score).toBeGreaterThanOrEqual(3)
  })
  it('rates short passwords 0 with a hint', () => {
    expect(passwordStrength('Ab1!').score).toBe(0)
    expect(passwordStrength('Ab1!').hints).toContain('tooShort')
  })
  it('treats 8-9 characters as too short (the server minimum is 10)', () => {
    expect(passwordStrength('Zq7!vL9x').hints).toContain('tooShort')
    expect(passwordStrength('Zq7!vL9xw').score).toBe(0)
    expect(passwordStrength('Zq7!vL9xwT').hints).not.toContain('tooShort')
  })
  it('flags sequences', () => {
    expect(passwordStrength('abcd1234efgh').hints).toContain('sequence')
  })
  it('penalises an embedded username or email name', () => {
    const base = passwordStrength('rupak-Zq7!vL9x').score
    const hit = passwordStrength('rupak-Zq7!vL9x', { username: 'rupak' })
    expect(hit.score).toBeLessThan(base)
    expect(hit.hints).toContain('identity')
    expect(passwordStrength('janedoe-Zq7!vL9x', { email: 'janedoe@x.com' }).hints).toContain('identity')
  })
  it('handles empty input', () => {
    expect(passwordStrength('')).toEqual({ score: 0, hints: [] })
    expect(passwordStrength(undefined).score).toBe(0)
  })
})
