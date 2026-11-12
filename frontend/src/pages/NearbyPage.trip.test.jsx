// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const auth = { token: 'tok', user: { id: 7, username: 'u' }, preferences: {} }
const journey = { enabled: true }
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../hooks/useJourney', () => ({ useJourney: () => journey }))
vi.mock('../services/api', () => ({ fetchNearby: vi.fn() }))
vi.mock('../services/tripsApi', () => ({ listTrips: vi.fn(), putPlace: vi.fn() }))
vi.mock('../game/announce', () => ({ announceGame: vi.fn() }))
vi.mock('../offline/outbox', () => ({ enqueue: vi.fn() }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../utils/analytics', () => ({ track: vi.fn() }))

import * as api from '../services/api'
import * as trips from '../services/tripsApi'
import { announceGame } from '../game/announce'
import { emit } from '../telemetry/client'
import NearbyPage from './NearbyPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const LOCAL = {
  place: { name: 'Lisbon', lat: 38.72, lng: -9.14 },
  sections: [{ id: 'see', title: 'Places to see', items: [{ name: 'Belém Tower' }] }],
}
const DATA = {
  place: { name: 'Lisbon', lat: 38.72, lng: -9.14 },
  sections: [{ id: 'see', title: 'Places to see', items: [{ name: 'Belém Tower', place_id: 'p1', maps_uri: 'https://maps.google.com/?cid=1' }] }],
}
let container, root
const click = async (el) => { await act(async () => { el.click() }) }
const flush = async () => { await act(async () => { await new Promise(r => setTimeout(r, 0)) }) }
const byTid = (tid) => container.querySelector(`[data-tid="${tid}"]`)

async function openResults() {
  await act(async () => { root.render(<NearbyPage />) })
  await flush()
  await click(byTid('nearby.use-location'))
  await flush()
}

beforeEach(() => {
  vi.clearAllMocks()
  journey.enabled = true
  Object.defineProperty(navigator, 'geolocation', { configurable: true, value: {
    getCurrentPosition: (ok) => ok({ coords: { latitude: 38.722345, longitude: -9.139612 } }),
  } })
  api.fetchNearby.mockResolvedValue(DATA)
  trips.listTrips.mockResolvedValue({ pinned_id: 5, trips: [{ id: 5, phase: 'on_the_road' }] })
  trips.putPlace.mockResolvedValue({ game: { awards: [{ points: 1 }] } })
  container = document.createElement('div'); document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('Near me during a trip', () => {
  it('hides I\'m here for Google-Maps-grounded items, so their names are never stored', async () => {
    api.fetchNearby.mockResolvedValue(DATA)
    await openResults()
    expect(byTid('nearby.here')).toBeNull()
    expect(trips.putPlace).not.toHaveBeenCalled()
  })

  it('shows I\'m here only with an on-the-road pinned trip', async () => {
    api.fetchNearby.mockResolvedValue(LOCAL)
    await openResults()
    expect(byTid('nearby.here')).not.toBeNull()
  })

  it('hides it for a trip that is not on the road', async () => {
    trips.listTrips.mockResolvedValue({ pinned_id: 5, trips: [{ id: 5, phase: 'ready' }] })
    api.fetchNearby.mockResolvedValue(LOCAL)
    await openResults()
    expect(byTid('nearby.here')).toBeNull()
  })

  it('a tap sends the visit with coordinates, announces and shows Visited', async () => {
    api.fetchNearby.mockResolvedValue(LOCAL)
    await openResults()
    await click(byTid('nearby.here'))
    await flush()
    const [token, id, key, body] = trips.putPlace.mock.calls[0]
    expect([token, id, key]).toEqual(['tok', 5, 'nearby:belem-tower'])
    expect(body).toMatchObject({ name: 'Belém Tower', kind: 'nearby', visited: true, lat: 38.722, lng: -9.14 })
    expect(body.day).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(announceGame).toHaveBeenCalledWith({ awards: [{ points: 1 }] })
    expect(emit).toHaveBeenCalledWith('today_action', { action: 'visited' })
    expect(byTid('nearby.visited')).not.toBeNull()
    expect(byTid('nearby.here')).toBeNull()
  })

  it('journey off: no listTrips call and no button', async () => {
    journey.enabled = false
    await openResults()
    expect(trips.listTrips).not.toHaveBeenCalled()
    expect(byTid('nearby.here')).toBeNull()
  })
})
