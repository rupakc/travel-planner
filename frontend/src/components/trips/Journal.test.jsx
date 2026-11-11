// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const online = { value: true }
vi.mock('../../hooks/useJourney', () => ({ useJourney: () => ({ enabled: journey.enabled }) }))
vi.mock('../../context/AuthContext', () => ({ useAuth: () => ({ user: { id: 7 } }) }))
vi.mock('../../offline/useOnline', () => ({ useOnline: () => online.value }))
vi.mock('../../offline/outbox', () => ({ enqueue: vi.fn(async () => {}) }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../../services/tripsApi', () => ({
  listJournal: vi.fn(async () => ({ entries: [] })),
  addJournal: vi.fn(async (t, id, body) => ({ id: 1, ...body, day: null, mood: null })),
  deleteJournal: vi.fn(async () => {}),
  listPlaces: vi.fn(async () => ({ places: [] })),
  putPlace: vi.fn(async (t, id, key, body) => ({ place: { place_key: key, ...body }, game: null })),
}))
const journey = vi.hoisted(() => ({ enabled: true }))

import Journal from './Journal'
import { enqueue } from '../../offline/outbox'
import { emit } from '../../telemetry/client'
import { addJournal, putPlace } from '../../services/tripsApi'
import { placeKey } from '../../utils/placeKey'

const trip = {
  id: 12, start_date: '2027-04-01', end_date: '2027-04-03',
  selections: { itinerary: { days: [{ day_number: 1, slots: [{ time_of_day: 'morning', activity: 'Belém Tower' }] }] } },
}

let container, root
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
const mount = async () => { await act(async () => root.render(<Journal trip={trip} token="t" />)); await flush() }
const setText = (el, value) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, value)
  el.dispatchEvent(new Event('input', { bubbles: true }))
})
const button = (name) => [...container.querySelectorAll('button')].find((b) => b.textContent.trim() === name)
const radio = (label) => container.querySelector(`[role="radio"][aria-label="${label}"]`)

beforeEach(() => {
  vi.clearAllMocks(); online.value = true; journey.enabled = true
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('Journal', () => {
  it('renders nothing when the journey is off', async () => {
    journey.enabled = false
    await mount()
    expect(container.innerHTML).toBe('')
  })

  it('blocks the counter at 4001 characters', async () => {
    await mount()
    const box = container.querySelector('textarea')
    setText(box, 'a'.repeat(4000))
    expect(button('Add entry').disabled).toBe(false)
    setText(box, 'a'.repeat(4001))
    expect(button('Add entry').disabled).toBe(true)
    expect(container.querySelector('[role="alert"]').textContent).toContain('4001 / 4000')
  })

  it('queues an add made offline', async () => {
    online.value = false
    await mount()
    setText(container.querySelector('textarea'), 'Great pastel')
    await act(async () => { button('Add entry').click() })
    await flush()
    expect(enqueue).toHaveBeenCalledTimes(1)
    const [uid, req] = enqueue.mock.calls[0]
    expect(uid).toBe(7)
    expect(req.method).toBe('POST')
    expect(req.path).toBe('/trips/12/journal')
    expect(req.body.body).toBe('Great pastel')
    expect(req.body.client_id).toBeTruthy()
    expect(addJournal).not.toHaveBeenCalled()
    expect(container.textContent).toContain('Great pastel')
    expect(emit).toHaveBeenCalledWith('journal_action', { action: 'add', queued: true })
  })

  it('rating a place calls putPlace with the place key, and place_action has no name', async () => {
    await mount()
    expect(container.textContent).toContain('Belém Tower')
    await act(async () => { radio('4 of 5 stars').click() })
    await flush()
    expect(putPlace).toHaveBeenCalledTimes(1)
    expect(putPlace.mock.calls[0].slice(0, 3)).toEqual(['t', 12, placeKey('activity', 'Belém Tower')])
    expect(putPlace.mock.calls[0][3]).toMatchObject({ name: 'Belém Tower', stars: 4 })
    expect(emit).toHaveBeenCalledWith('place_action', { action: 'rate', kind: 'activity', stars: 4 })
    const all = JSON.stringify(emit.mock.calls)
    expect(all).not.toMatch(/Bel/)
  })
})
