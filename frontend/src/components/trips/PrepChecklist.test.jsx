// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../../services/tripsApi', () => ({ getPrep: vi.fn(), setPrepItem: vi.fn() }))
vi.mock('../../game/announce', () => ({ announceGame: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../../hooks/useJourney', () => ({ useJourney: () => ({ enabled: true }) }))

import PrepChecklist from './PrepChecklist'
import { getPrep, setPrepItem } from '../../services/tripsApi'
import { announceGame } from '../../game/announce'
import { emit } from '../../telemetry/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const IDS = ['visa', 'passport', 'bookings', 'insurance', 'documents', 'stress_test', 'sim', 'money', 'packing', 'emergency_card', 'checkin', 'offline_pack']
const item = (id, over = {}) => ({ id, status: 'todo', auto: id === 'offline_pack', due: '2027-04-01', overdue: false, facts: {}, ...over })
const prep = (over = {}, doneIds = []) => {
  const items = IDS.map((id) => item(id, { status: doneIds.includes(id) ? 'done' : 'todo', ...(over[id] || {}) }))
  const live = items.filter((i) => i.status !== 'na')
  const done = live.filter((i) => i.status === 'done').length
  return { items, done, total: live.length, percent: Math.floor((100 * done) / live.length), complete: done === live.length }
}
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })

describe('PrepChecklist', () => {
  let container, root
  const mount = async () => { await act(async () => { root.render(<PrepChecklist trip={{ id: 7 }} token="tok" />) }); await flush() }
  const q = (tid) => container.querySelector(`[data-tid="${tid}"]`)

  beforeEach(() => {
    container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
    vi.clearAllMocks()
    window.matchMedia = (query) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} })
  })
  afterEach(() => { act(() => root.unmount()); container.remove(); delete window.matchMedia })

  it('puts a na visa under Not needed', async () => {
    getPrep.mockResolvedValue(prep({ visa: { status: 'na' } }))
    await mount()
    expect(q('prep-not-needed').querySelector('[data-tid="prep-item-visa"]')).not.toBeNull()
    expect(container.querySelectorAll('ul')[0].querySelector('[data-tid="prep-item-visa"]')).toBeNull()
  })

  it('has no checkbox on offline_pack', async () => {
    getPrep.mockResolvedValue(prep())
    await mount()
    expect(q('prep-item-offline_pack')).not.toBeNull()
    expect(q('prep-toggle-offline_pack')).toBeNull()
    expect(q('prep-toggle-passport')).not.toBeNull()
  })

  it('rolls a toggle back on a 500', async () => {
    getPrep.mockResolvedValue(prep())
    setPrepItem.mockRejectedValue({ status: 500 })
    await mount()
    await act(async () => { q('prep-toggle-passport').click() })
    await flush()
    expect(q('prep-toggle-passport').checked).toBe(false)
    expect(q('prep-toggle-error')).not.toBeNull()
    expect(emit).not.toHaveBeenCalled()
  })

  it('shows Ready to go and announces the game delta on completion', async () => {
    const almost = IDS.filter((i) => i !== 'passport')
    getPrep.mockResolvedValue(prep({}, almost))
    const delta = { xp: 50, awards: [{ rule: 'trip_ready' }], badges: [], level_up: null }
    setPrepItem.mockResolvedValue({ ...prep({}, IDS), item: item('passport', { status: 'done' }), game: delta })
    await mount()
    expect(q('prep-ready-go')).toBeNull()
    await act(async () => { q('prep-toggle-passport').click() })
    await flush()
    expect(q('prep-ready-go').textContent).toBe('Ready to go')
    expect(announceGame).toHaveBeenCalledWith(delta)
    expect(emit).toHaveBeenCalledWith('prep_toggle', { item: 'passport', done: true })
    expect(emit).toHaveBeenCalledWith('prep_complete', { items: 12 })
    expect(container.querySelector('.confetti')).not.toBeNull()
  })

  it('renders no confetti under reduced motion', async () => {
    window.matchMedia = (query) => ({ matches: true, media: query, addEventListener() {}, removeEventListener() {} })
    getPrep.mockResolvedValue(prep({}, IDS.filter((i) => i !== 'passport')))
    setPrepItem.mockResolvedValue({ ...prep({}, IDS), item: item('passport', { status: 'done' }), game: null })
    await mount()
    await act(async () => { q('prep-toggle-passport').click() })
    await flush()
    expect(q('prep-ready-go')).not.toBeNull()
    expect(container.querySelector('.confetti')).toBeNull()
  })
})
