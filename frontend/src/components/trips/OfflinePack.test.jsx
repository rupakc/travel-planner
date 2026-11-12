// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const calls = []
const state = { shell: { ok: true, kb: 10 }, saveErr: null, swThrow: false, journey: true, offlinePack: true, online: true, stored: { pack: null, savedAt: null, loading: false } }
vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ user: state.user }) }))
vi.mock('../../hooks/useJourney', () => ({ useJourney: () => ({ enabled: state.journey, offlinePack: state.offlinePack }) }))
vi.mock('../../offline/useOnline', () => ({ useOnline: () => state.online }))
vi.mock('../../offline/useOfflinePack', () => ({ useOfflinePack: () => state.stored }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../../services/tripsApi', () => ({
  getOfflinePack: vi.fn(async () => { calls.push('fetch'); return PACK }),
}))
vi.mock('../../offline/packStore', () => ({
  savePack: vi.fn(async () => { calls.push('save'); if (state.saveErr) throw state.saveErr }),
  deletePack: vi.fn(async () => { calls.push('delete') }),
}))
vi.mock('../../offline/registerSW', () => ({
  ensureServiceWorker: vi.fn(async () => { calls.push('sw'); if (state.swThrow) throw new Error('sw'); return state.reg }),
  precacheShell: vi.fn(async () => { calls.push('precache'); return state.shell }),
}))

import OfflinePack from './OfflinePack'
import { savePack, deletePack } from '../../offline/packStore'
import { emit } from '../../telemetry/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const PACK = {
  version: 1, trip_id: 12, generated_at: '2027-03-01T10:00:00Z', title: 'Lisbon',
  emergency: { source: 'static', as_of: null, cities: [{ city: 'Lisbon', emergency_numbers: { police: '112', ambulance: '112' }, embassy: null, hospitals: [], local_phrases: [] }] },
  phrases: { language: 'pt', language_name: 'Português', items: [{ id: 'help', text: 'Socorro!', romanized: null }] },
  address_card: { hotel_name: 'Hotel Avenida', area: 'Baixa', city: 'Lisbon', take_me_to: { text: 'Leve-me para:', romanized: null } },
  currency: { local: 'EUR', home: 'USD', rate: 0.92, as_of: '2027-03-01T09:00:00Z', source: 'snapshot' },
}

let container, root
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)
const click = (el) => act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
const render = () => act(async () => root.render(<OfflinePack trip={{ id: 12 }} token="tok" />))

beforeEach(() => {
  vi.clearAllMocks()
  calls.length = 0
  Object.assign(state, { shell: { ok: true, kb: 10 }, saveErr: null, swThrow: false, journey: true, offlinePack: true, user: { id: 7 }, online: true, reg: {}, stored: { pack: null, savedAt: null, loading: false } })
  Object.defineProperty(navigator, 'storage', {
    configurable: true,
    value: { persist: vi.fn(async () => { calls.push('persist'); return true }) },
  })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('OfflinePack', () => {
  it('renders nothing when the journey is off', async () => {
    state.journey = false
    await render()
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing and never touches the service worker when the kill switch is on', async () => {
    state.offlinePack = false
    await render()
    expect(container.innerHTML).toBe('')
    expect(calls).toEqual([])
  })

  it('saves in order and shows Saved', async () => {
    await render()
    await click(tid('offlinePack.save'))
    expect(calls).toEqual(['fetch', 'save', 'sw', 'precache', 'persist'])
    expect(savePack).toHaveBeenCalledWith('7', PACK)
    expect(tid('offlinePack.status').textContent).toMatch(/Saved/)
    expect(tid('offlinePack.tabnote')).toBeNull()
    expect(emit).toHaveBeenCalledWith('offline_pack', expect.objectContaining({ action: 'save', result: 'ok' }))
    expect(tid('offlinePack.emergency.call.police').getAttribute('href')).toBe('tel:112')
    expect(tid('offlinePack.emergency.source').textContent).toBe('From our reference list')
  })

  it('without a service worker still saves the data and notes the tab', async () => {
    state.reg = null
    await render()
    await click(tid('offlinePack.save'))
    expect(savePack).toHaveBeenCalled()
    expect(calls).not.toContain('precache')
    expect(tid('offlinePack.tabnote').textContent).toBe('Works while this tab stays open')
    expect(tid('offlinePack.status').textContent).toMatch(/Saved/)
    expect(emit).toHaveBeenCalledWith('offline_pack', expect.objectContaining({ result: 'unsupported' }))
  })

  it('offline renders the stored pack and disables Refresh', async () => {
    state.online = false
    state.stored = { pack: PACK, savedAt: '2027-03-01T10:00:00Z', loading: false }
    await render()
    expect(container.textContent).toContain('Hotel Avenida')
    expect(container.textContent).toContain('Socorro!')
    expect(tid('offlinePack.refresh').disabled).toBe(true)
    expect(calls).toEqual([])
  })

  it('a null rate shows the notice and no converter', async () => {
    state.stored = { pack: { ...PACK, currency: { local: 'EUR', home: 'USD', rate: null, as_of: null, source: null } }, savedAt: null, loading: false }
    await render()
    expect(tid('offlinePack.currency.norate')).not.toBeNull()
    expect(tid('offlinePack.currency.amount')).toBeNull()
  })

  it('converts with the dated, approximate rate', async () => {
    state.stored = { pack: PACK, savedAt: null, loading: false }
    await render()
    const input = tid('offlinePack.currency.amount')
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    await act(async () => { set.call(input, '100'); input.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(tid('offlinePack.currency.result').textContent).toContain('92')
    expect(tid('offlinePack.currency').textContent).toMatch(/Rate from .*approximate/)
  })

  it('opens a phrase full screen', async () => {
    state.stored = { pack: PACK, savedAt: null, loading: false }
    await render()
    await click(tid('offlinePack.phrase.show.help'))
    expect(tid('offlinePack.phrase.full').textContent).toContain('Socorro!')
    await click(tid('offlinePack.phrase.close'))
    expect(tid('offlinePack.phrase.full')).toBeNull()
  })

  it('Remove deletes the saved pack', async () => {
    state.stored = { pack: PACK, savedAt: null, loading: false }
    await render()
    await click(tid('offlinePack.remove'))
    expect(deletePack).toHaveBeenCalledWith('7', 12)
    expect(tid('offlinePack.save')).not.toBeNull()
    expect(tid('offlinePack.emergency')).toBeNull()
  })

  it('Refresh fetches and saves again', async () => {
    state.stored = { pack: PACK, savedAt: '2027-03-01T10:00:00Z', loading: false }
    await render()
    await click(tid('offlinePack.refresh'))
    expect(calls).toEqual(['fetch', 'save', 'sw', 'precache', 'persist'])
    expect(emit).toHaveBeenCalledWith('offline_pack', expect.objectContaining({ action: 'refresh', result: 'ok' }))
  })

  it('a storage error shows the quota message and saves nothing', async () => {
    state.saveErr = Object.assign(new Error('full'), { name: 'QuotaExceededError' })
    await render()
    await click(tid('offlinePack.save'))
    expect(tid('offlinePack.error').textContent).toMatch(/Not enough storage/)
    expect(tid('offlinePack.status')).toBeNull()
    expect(emit).toHaveBeenCalledWith('offline_pack', expect.objectContaining({ result: 'quota' }))
  })

  it('a generic save error shows the retry message', async () => {
    state.saveErr = new Error('boom')
    await render()
    await click(tid('offlinePack.save'))
    expect(tid('offlinePack.error').textContent).toMatch(/Could not save/)
    expect(emit).toHaveBeenCalledWith('offline_pack', expect.objectContaining({ result: 'error' }))
  })

  it('precacheShell not ok keeps the data and shows the tab note', async () => {
    state.shell = { ok: false, kb: 0 }
    await render()
    await click(tid('offlinePack.save'))
    expect(tid('offlinePack.tabnote')).not.toBeNull()
    expect(tid('offlinePack.status').textContent).toMatch(/Saved/)
    expect(emit).toHaveBeenCalledWith('offline_pack', expect.objectContaining({ result: 'unsupported' }))
  })

  it('a service worker failure after the data is saved still shows the pack with the tab note', async () => {
    state.swThrow = true
    await render()
    await click(tid('offlinePack.save'))
    expect(savePack).toHaveBeenCalled()
    expect(tid('offlinePack.error')).toBeNull()
    expect(tid('offlinePack.status').textContent).toMatch(/Saved/)
    expect(tid('offlinePack.tabnote')).not.toBeNull()
  })

  it('Remove emits a remove event', async () => {
    state.stored = { pack: PACK, savedAt: null, loading: false }
    await render()
    await click(tid('offlinePack.remove'))
    expect(emit).toHaveBeenCalledWith('offline_pack', { action: 'remove', result: 'ok', kb: 0 })
  })

  it('without a user id Save is disabled and nothing is saved', async () => {
    state.user = null
    await render()
    expect(tid('offlinePack.save').disabled).toBe(true)
    expect(savePack).not.toHaveBeenCalled()
  })

  it('labels the rate with its date and source, and tags local text with its language', async () => {
    state.stored = { pack: PACK, savedAt: null, loading: false }
    await render()
    expect(tid('offlinePack.currency').textContent).toMatch(/Rate from .*\(saved with your trip\), approximate/)
    expect(tid('offlinePack.currency').textContent).toMatch(/2027/)
    expect([...container.querySelectorAll('[lang="pt"]')].map((e) => e.textContent).join(' ')).toContain('Socorro!')
  })
})
