// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { signupAvailable, resetAvailable, featureOn } from './useClientConfig'

describe('featureOn', () => {
  it('accepts true and the integer 1 that /config sends (play, social), nothing else', () => {
    expect(featureOn({ features: { play: 1 } }, 'play')).toBe(true)
    expect(featureOn({ features: { game: true } }, 'game')).toBe(true)
    expect(featureOn({ features: { play: 0 } }, 'play')).toBe(false)
    expect(featureOn({ features: { play: 2 } }, 'play')).toBe(false)
    expect(featureOn({ features: { play: 'yes' } }, 'play')).toBe(false)
    expect(featureOn({}, 'play')).toBe(false)
  })
})

describe('availability helpers', () => {
  it('are false without an auth block (old backend)', () => {
    expect(signupAvailable({})).toBe(false)
    expect(resetAvailable({})).toBe(false)
    expect(signupAvailable(undefined)).toBe(false)
  })
  it('follow the flags', () => {
    expect(signupAvailable({ auth: { signup_available: true } })).toBe(true)
    expect(resetAvailable({ auth: { password_reset_available: false } })).toBe(false)
  })
})

describe('config loading', () => {
  beforeEach(() => { vi.resetModules() })
  it('a 404 gives {} and signup stays hidden', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }))
    const m = await import('./useClientConfig')
    const cfg = await m.loadClientConfig()
    expect(cfg).toEqual({})
    expect(m.signupAvailable(cfg)).toBe(false)
  })
  it('a network error gives {} and fetches once', async () => {
    const f = vi.fn().mockRejectedValue(new Error('down'))
    vi.stubGlobal('fetch', f)
    const m = await import('./useClientConfig')
    expect(await m.loadClientConfig()).toEqual({})
    await m.loadClientConfig()
    expect(f).toHaveBeenCalledTimes(1)
  })
})
