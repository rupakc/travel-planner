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

describe('replay for late celebration listeners', () => {
  const d = { xp: 50, awards: [{ rule: 'email_verified', points: 50 }], badges: [], level_up: null }

  it('keeps a delta announced with no replay listener and hands it to the next one, once', () => {
    vi.useFakeTimers()
    const plain = vi.fn()
    const offPlain = onGameAnnounce(plain)
    announceGame(d)              // e.g. /verify, before the signed-in layout mounts
    expect(plain).toHaveBeenCalledTimes(1)
    const late = vi.fn()
    const off = onGameAnnounce(late, { replay: true })
    expect(late).toHaveBeenCalledWith(d)
    off()
    const again = vi.fn()
    const off2 = onGameAnnounce(again, { replay: true })
    expect(again).not.toHaveBeenCalled()
    off2(); offPlain()
    vi.useRealTimers()
  })

  it('does not buffer while a replay listener is mounted', () => {
    const live = vi.fn()
    const off = onGameAnnounce(live, { replay: true })
    announceGame(d)
    off()
    const late = vi.fn()
    const off2 = onGameAnnounce(late, { replay: true })
    expect(live).toHaveBeenCalledTimes(1)
    expect(late).not.toHaveBeenCalled()
    off2()
  })

  it('drops a buffered delta after 15 s', () => {
    vi.useFakeTimers()
    announceGame(d)
    vi.advanceTimersByTime(15_001)
    const late = vi.fn()
    const off = onGameAnnounce(late, { replay: true })
    expect(late).not.toHaveBeenCalled()
    off()
    vi.useRealTimers()
  })
})
