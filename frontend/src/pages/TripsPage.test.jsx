// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const settings = { hide_game: false }
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok', user: { id: 1 } }) }))
vi.mock('../hooks/useJourney', () => ({ useJourney: () => ({ enabled: true, loaded: true }) }))
vi.mock('../components/account/SettingsSync', () => ({ useAccountSettings: () => ({ settings }) }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../services/tripsApi', () => ({
  listTrips: vi.fn(), getPrep: vi.fn(), getTripStats: vi.fn(), createTrip: vi.fn(), notifyTripsChanged: vi.fn(),
}))

import * as api from '../services/tripsApi'
import { emit } from '../telemetry/client'
import TripsPage from './TripsPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const trip = (o) => ({
  id: 1, title: 'T', destination: 'Rome', destinations: ['Rome'], start_date: null, end_date: null,
  phase: 'dreaming', day_index: null, prep: { done: 0, total: 0, percent: 0, complete: false }, ...o,
})
const TRIPS = [
  trip({ id: 1, title: 'Lisbon trip', destination: 'Lisbon', phase: 'on_the_road', day_index: 3, start_date: '2026-11-10', end_date: '2026-11-15' }),
  trip({ id: 2, title: 'Dream Peru', phase: 'dreaming' }),
  trip({ id: 3, title: 'Soon Paris', phase: 'ready', start_date: '2026-12-01' }),
  trip({ id: 4, title: 'Later Japan', phase: 'planning', start_date: '2027-05-01', prep: { done: 3, total: 9, percent: 33, complete: false } }),
  trip({ id: 5, title: 'Old Kenya', phase: 'memories', start_date: '2026-01-01', end_date: '2026-01-08' }),
]

let container, root
const flush = async () => { await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const render = async () => {
  await act(async () => root.render(<MemoryRouter><TripsPage /></MemoryRouter>))
  await flush()
}
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)

beforeEach(() => {
  vi.clearAllMocks()
  settings.hide_game = false
  api.listTrips.mockResolvedValue({ trips: TRIPS, pinned_id: 1, today: '2026-11-12' })
  api.getTripStats.mockResolvedValue({ countries: [{ code: 'PT' }, { code: 'IT' }], bucket_goal: 30 })
  api.getPrep.mockResolvedValue({ items: [{ id: 'passport', status: 'done' }, { id: 'insurance', status: 'todo', due: '2026-11-24' }] })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('TripsPage', () => {
  it('groups cards in phase order', async () => {
    await render()
    const groups = [...container.querySelectorAll('[data-tid^="trips-group-"]')].map((g) => g.dataset.tid)
    expect(groups).toEqual(['trips-group-ready', 'trips-group-planning', 'trips-group-dreaming', 'trips-group-memories'])
    expect(tid('trips-group-planning').textContent).toContain('Later Japan')
  })

  it('shows Day 3 in Lisbon for the pinned on-the-road trip', async () => {
    await render()
    expect(tid('trips-next-line').textContent).toBe('Day 3 in Lisbon')
    expect(tid('trips-next-open-today')).toBeTruthy()
    expect(emit).toHaveBeenCalledWith('trip_view', { surface: 'hub', phase: 'on_the_road' })
  })

  it('shows the next prep item for a pinned ready trip, and fetches prep only for it', async () => {
    api.listTrips.mockResolvedValue({ trips: TRIPS, pinned_id: 3, today: '2026-11-12' })
    await render()
    expect(api.getPrep).toHaveBeenCalledTimes(1)
    expect(api.getPrep).toHaveBeenCalledWith('tok', 3)
    expect(tid('trips-next-line').textContent).toMatch(/^Next: Travel insurance by .*2026/)
  })

  it('does not call getPrep when the pinned trip is not ready', async () => {
    await render()
    expect(api.getPrep).not.toHaveBeenCalled()
  })

  it('creating a Dreaming trip adds a card under Dreaming', async () => {
    api.createTrip.mockResolvedValue(trip({ id: 9, title: 'Someday Iceland', phase: 'dreaming' }))
    await render()
    await act(async () => { tid('trips-create').click() })
    const input = tid('trips-create-title')
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    await act(async () => { setter.call(input, 'Someday Iceland'); input.dispatchEvent(new Event('input', { bubbles: true })) })
    await act(async () => { tid('trips-create-dialog').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    await flush()
    expect(api.createTrip).toHaveBeenCalledWith('tok', { title: 'Someday Iceland' })
    expect(api.notifyTripsChanged).toHaveBeenCalled()
    expect(emit).toHaveBeenCalledWith('trip_action', { action: 'create' })
    expect(tid('trips-group-dreaming').textContent).toContain('Someday Iceland')
    expect(tid('trips-create-dialog')).toBeNull()
  })

  it('shows Retry after a network failure and recovers', async () => {
    api.listTrips.mockRejectedValueOnce({ code: 'network' })
    await render()
    expect(container.textContent).toContain("Couldn't load this right now.")
    await act(async () => { tid('trips-retry').click() })
    await flush()
    expect(tid('trips-next-panel')).toBeTruthy()
  })

  it('shows the bucket ring, hidden with hide_game', async () => {
    await render()
    expect(tid('trips-bucket-ring').textContent).toContain('2 / 30')
    act(() => root.unmount())
    root = createRoot(container)
    settings.hide_game = true
    await render()
    expect(tid('trips-bucket-ring')).toBeNull()
  })

  it('Plan it carries the destination to Explore', async () => {
    api.listTrips.mockResolvedValue({ trips: [trip({ id: 7, title: 'Rome idea', destination: 'Rome' })], pinned_id: 7, today: '2026-11-12' })
    await render()
    expect(tid('trips-next-plan-it').getAttribute('href')).toBe('/explore')
  })

  it('a successful create clears the load error', async () => {
    api.listTrips.mockRejectedValueOnce({ code: 'network' })
    api.createTrip.mockResolvedValue(trip({ id: 9, title: 'Idea' }))
    await render()
    await act(async () => { tid('trips-create').click() })
    const input = tid('trips-create-title')
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    await act(async () => { setter.call(input, 'Idea'); input.dispatchEvent(new Event('input', { bubbles: true })) })
    await act(async () => { tid('trips-create-dialog').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    await flush()
    expect(tid('trips-retry')).toBeNull()
  })

  it('shows the empty state', async () => {
    api.listTrips.mockResolvedValue({ trips: [], pinned_id: null, today: '2026-11-12' })
    await render()
    expect(tid('trips-empty-plan').getAttribute('href')).toBe('/explore')
    expect(tid('trips-empty-idea')).toBeTruthy()
  })
})
