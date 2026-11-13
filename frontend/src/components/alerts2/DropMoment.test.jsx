// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, useLocation } from 'react-router-dom'

const state = { latestDrop: null, findDrop: vi.fn(async () => null), markDropShown: vi.fn() }
const settings = { hide_game: false }
const emit = vi.fn()
vi.mock('../../context/AlertsContext', async () => {
  const real = await vi.importActual('../../context/AlertsContext')
  return { ...real, useAlerts: () => state }
})
vi.mock('../account/SettingsSync', () => ({ useAccountSettings: () => ({ settings }) }))
vi.mock('../../telemetry/client', () => ({ emit: (...a) => emit(...a) }))
vi.mock('./SavingsShareCard', () => ({ default: ({ onClose }) => <div data-tid="share-stub"><button onClick={onClose}>x</button></div> }))

import DropMoment from './DropMoment'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const drop = { from: 469, to: 412, amount: 57, pct: 12, currency: 'USD', target_hit: false, observed: true }
const note = (over = {}) => ({
  id: 9, kind: 'fare_drop', title: 't', body: 'b', read_at: null,
  data: { watch_id: 7, watch_kind: 'hotel', title: 'Hotel Sol', drop, game: { awards: [{ rule: 'deal_hunter', points: 15 }] },
    links: { book: 'https://example.com/book' }, ...over.data },
  ...over.top,
})

let container, root, loc
function Loc() { loc = useLocation(); return null }

const mount = async (url = '/alerts') => {
  await act(async () => root.render(<MemoryRouter initialEntries={[url]}><DropMoment /><Loc /><button id="opener">o</button></MemoryRouter>))
}
const mm = (reduce) => { window.matchMedia = () => ({ matches: reduce }) }

describe('DropMoment', () => {
  beforeEach(() => {
    state.latestDrop = null
    state.findDrop = vi.fn(async () => null)
    state.markDropShown = vi.fn(() => { state.latestDrop = null })
    settings.hide_game = false
    emit.mockReset()
    mm(true)
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(async () => { await act(async () => root.unmount()); container.remove() })

  it('no card for notes without drop', async () => {
    await mount()
    expect(container.querySelector('[data-tid="dropMoment.card"]')).toBeNull()
  })

  it('shows once and marks the notification shown, emitting enum-only telemetry', async () => {
    state.latestDrop = note()
    await mount()
    expect(container.querySelector('[data-tid="dropMoment.card"]')).not.toBeNull()
    expect(state.markDropShown).toHaveBeenCalledWith(9)
    expect(emit).toHaveBeenCalledWith('alert_drop_seen', { kind: 'hotel', target_hit: false, via: 'in_app' })
    expect(container.textContent).toContain('$57')
    expect(container.textContent).not.toMatch(/you saved/i)
  })

  it('reduced motion shows the final amount at once and no confetti; target hit shows confetti', async () => {
    state.latestDrop = note({ data: { drop: { ...drop, target_hit: true } } })
    await mount()
    expect(container.querySelector('[data-tid="dropMoment.amount"]').textContent).toContain('57')
    expect(container.querySelector('[data-tid="dropMoment.price"]').textContent).toContain('412')
    expect(container.querySelector('[data-tid="dropMoment.confetti"]')).not.toBeNull()
    expect(emit).toHaveBeenCalledWith('alert_drop_seen', expect.objectContaining({ target_hit: true }))
  })

  it('no confetti without target hit', async () => {
    state.latestDrop = note()
    await mount()
    expect(container.querySelector('[data-tid="dropMoment.confetti"]')).toBeNull()
  })

  it('counts up with motion allowed', async () => {
    mm(false)
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] })
    state.latestDrop = note()
    await mount()
    const visible = () => container.querySelector('[data-tid="dropMoment.amount"] [aria-hidden="true"]').textContent
    expect(visible()).not.toContain('57')
    await act(async () => { vi.advanceTimersByTime(1200) })
    expect(visible()).toContain('57')
    vi.useRealTimers()
  })

  it('shows an earned badge by name, and hides it with hide_game', async () => {
    state.latestDrop = note({ data: { game: { awards: [{ rule: 'deal_hunter', points: 15 }], badges: [{ id: 'deal_hunter' }] } } })
    await mount()
    expect(container.querySelector('[data-tid="dropMoment.badge"]').textContent).toMatch(/Badge earned: \S+/)
    await act(async () => root.unmount())
    root = createRoot(container)
    settings.hide_game = true
    await mount()
    expect(container.querySelector('[data-tid="dropMoment.badge"]')).toBeNull()
  })

  it('xp hidden when hide_game', async () => {
    state.latestDrop = note()
    await mount()
    expect(container.querySelector('[data-tid="dropMoment.xp"]').textContent).toContain('15')
    await act(async () => root.unmount())
    root = createRoot(container)
    settings.hide_game = true
    await mount()
    expect(container.querySelector('[data-tid="dropMoment.xp"]')).toBeNull()
  })

  it('deep link opens with via push and strips the param', async () => {
    state.findDrop = vi.fn(async () => note())
    await mount('/alerts?drop=9')
    expect(state.findDrop).toHaveBeenCalledWith(9)
    expect(container.querySelector('[data-tid="dropMoment.card"]')).not.toBeNull()
    expect(emit).toHaveBeenCalledWith('alert_drop_seen', expect.objectContaining({ via: 'push' }))
    expect(loc.search).toBe('')
  })

  it('escape closes and restores focus', async () => {
    document.body.appendChild(Object.assign(document.createElement('button'), { id: 'outside' }))
    const outside = document.getElementById('outside')
    outside.focus()
    state.latestDrop = note()
    await mount()
    const card = container.querySelector('[data-tid="dropMoment.card"]')
    expect(card.contains(document.activeElement)).toBe(true)
    await act(async () => { card.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(container.querySelector('[data-tid="dropMoment.card"]')).toBeNull()
    expect(document.activeElement).toBe(outside)
    outside.remove()
  })

  it('story action goes to the watch and book link is present', async () => {
    state.latestDrop = note()
    await mount()
    expect(container.querySelector('[data-tid="dropMoment.book"]').getAttribute('href')).toBe('https://example.com/book')
    await act(async () => { container.querySelector('[data-tid="dropMoment.story"]').click() })
    expect(loc.pathname + loc.search).toBe('/alerts?watch=hotel:7')
  })

  it('closing a card does not open the next unseen drop in the same session', async () => {
    state.latestDrop = note()
    state.markDropShown = vi.fn(() => { state.latestDrop = note({ top: { id: 10 } }) })
    await mount()
    const card = container.querySelector('[data-tid="dropMoment.card"]')
    await act(async () => { card.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    await mount()
    expect(container.querySelector('[data-tid="dropMoment.card"]')).toBeNull()
    expect(state.markDropShown).toHaveBeenCalledTimes(1)
  })

  it('announces the final amount in an sr-only span, not an aria-label on the paragraph', async () => {
    state.latestDrop = note()
    await mount()
    const p = container.querySelector('[data-tid="dropMoment.amount"]')
    expect(p.hasAttribute('aria-label')).toBe(false)
    expect(p.querySelector('.sr-only').textContent).toContain('$57')
  })

  it('closing a deep-linked card does not open the next unseen drop', async () => {
    state.findDrop = vi.fn(async () => note())
    state.latestDrop = note({ top: { id: 10 } })
    state.markDropShown = vi.fn()
    await mount('/alerts?drop=9')
    const card = container.querySelector('[data-tid="dropMoment.card"]')
    expect(card).not.toBeNull()
    await act(async () => { card.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(container.querySelector('[data-tid="dropMoment.card"]')).toBeNull()
    expect(state.markDropShown).toHaveBeenCalledTimes(1)
  })
})
