// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { drawSavingsCard, savingsCardLines, shareSavings } from './savingsCard'

const t = (k, o = {}) => `${k}${Object.keys(o).length ? ' ' + JSON.stringify(o) : ''}`
const fmt = (a, c) => `${c} ${a}`

const fakeCtx = () => {
  const texts = []
  return {
    texts,
    fillText: (s) => texts.push(s), measureText: (s) => ({ width: String(s).length * 10 }),
    fillRect() {}, set fillStyle(_) {}, set font(_) {}, set textAlign(_) {}, set textBaseline(_) {},
  }
}

afterEach(() => { vi.restoreAllMocks(); delete navigator.canShare; delete navigator.share })

describe('savings card', () => {
  it('has no estimate and no title when the watch was deleted', () => {
    const s = { total_usd: 245, by_currency: { EUR: 12 }, drops_caught: 4,
      best: { kind: 'hotel', watch_id: 3, title: null, caught: 120, currency: 'USD' } }
    const lines = savingsCardLines(s, t, fmt)
    expect(lines.best).toContain('bestNoTitle')
    expect(lines.best).not.toContain('title')
    const ctx = fakeCtx()
    drawSavingsCard(ctx, s, lines, 'light')
    const all = ctx.texts.join(' ').toLowerCase()
    expect(all).not.toContain('estimate')
    expect(all).not.toContain('null')
    expect(lines.chips).toEqual(['EUR 12'])
    expect(lines.headline).toContain('USD 245')
  })

  it('accepts a minimal savings object', () => {
    const lines = savingsCardLines({ total_usd: 57, by_currency: {}, drops_caught: 1 }, t, fmt)
    expect(lines.best).toBeNull()
    expect(lines.headline).toContain('USD 57')
  })

  it('uses no USD total for a EUR-only tally', () => {
    const lines = savingsCardLines({ total_usd: 0, by_currency: { EUR: 12 }, drops_caught: 1 }, t, fmt)
    expect(lines.headline).toBe('card.headlineOther')
  })
})

describe('shareSavings', () => {
  it('falls back to download without navigator.canShare', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    expect(await shareSavings(new Blob(['x']), 'text')).toBe('download')
    expect(click).toHaveBeenCalled()
  })

  it('uses the native sheet when files can be shared', async () => {
    navigator.canShare = () => true
    navigator.share = vi.fn().mockResolvedValue()
    expect(await shareSavings(new Blob(['x']), 'text')).toBe('native')
  })

  it('copies text when there is no blob route', async () => {
    const writeText = vi.fn().mockResolvedValue()
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    expect(await shareSavings(null, 'hello')).toBe('copy')
    expect(writeText).toHaveBeenCalledWith('hello')
  })
})
