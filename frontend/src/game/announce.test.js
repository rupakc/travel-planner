// @vitest-environment node
import { describe, it, expect, vi } from 'vitest'
import { announceGame, onGameAnnounce } from './announce'

describe('announce', () => {
  it('delivers deltas and ignores null/empty', () => {
    const fn = vi.fn()
    const off = onGameAnnounce(fn)
    announceGame(null)
    announceGame({ xp: 5, awards: [], badges: [], level_up: null })
    expect(fn).not.toHaveBeenCalled()
    const d = { xp: 55, awards: [{ rule: 'x', points: 50 }], badges: [], level_up: null }
    announceGame(d)
    expect(fn).toHaveBeenCalledWith(d)
    off()
    announceGame(d)
    expect(fn).toHaveBeenCalledTimes(1)
  })
})
