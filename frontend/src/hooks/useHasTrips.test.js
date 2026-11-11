// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'

const auth = vi.hoisted(() => ({ value: {} }))
const journey = vi.hoisted(() => ({ value: {} }))
const listTrips = vi.hoisted(() => vi.fn())
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth.value }))
vi.mock('./useJourney', () => ({ useJourney: () => journey.value }))
vi.mock('../services/tripsApi', () => ({ listTrips }))

import { useHasTrips, _resetHasTripsForTests } from './useHasTrips'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root, seen

function Probe() { seen.push(useHasTrips()); return null }
async function render() {
  root = createRoot(document.createElement('div'))
  await act(async () => root.render(createElement(Probe)))
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const signedIn = { isAuthenticated: true, token: 'tok', user: { id: 1, username: 'a' } }

beforeEach(() => {
  seen = []
  _resetHasTripsForTests()
  listTrips.mockReset()
  journey.value = { enabled: true, loaded: true }
  auth.value = signedIn
})
afterEach(() => { act(() => root.unmount()) })

describe('useHasTrips', () => {
  it('signed out: no trips, no request', async () => {
    auth.value = { isAuthenticated: false, token: null, user: null }
    await render()
    expect(seen[0]).toEqual({ hasTrips: false, loading: false })
    expect(listTrips).not.toHaveBeenCalled()
  })

  it('journey off: no trips, no request', async () => {
    journey.value = { enabled: false, loaded: true }
    await render()
    expect(seen.at(-1)).toEqual({ hasTrips: false, loading: false })
    expect(listTrips).not.toHaveBeenCalled()
  })

  it('loads, then reports whether the user has a trip', async () => {
    listTrips.mockResolvedValue({ trips: [{ id: 3 }], pinned_id: 3 })
    await render()
    expect(seen[0]).toEqual({ hasTrips: null, loading: true })
    expect(seen.at(-1)).toEqual({ hasTrips: true, loading: false })
    expect(listTrips).toHaveBeenCalledWith('tok')
  })

  it('zero trips → false', async () => {
    listTrips.mockResolvedValue({ trips: [] })
    await render()
    expect(seen.at(-1)).toEqual({ hasTrips: false, loading: false })
  })

  it('a network error counts as no trips', async () => {
    listTrips.mockRejectedValue({ status: 0, code: 'network' })
    await render()
    expect(seen.at(-1)).toEqual({ hasTrips: false, loading: false })
  })

  it('fetches once per sign-in, not on a token refresh', async () => {
    listTrips.mockResolvedValue({ trips: [{ id: 3 }] })
    await render()
    auth.value = { ...signedIn, token: 'tok2' }
    await act(async () => root.render(createElement(Probe)))
    expect(listTrips).toHaveBeenCalledTimes(1)
    expect(seen.at(-1)).toEqual({ hasTrips: true, loading: false })
  })
  it('asks again after signing out and back in', async () => {
    listTrips.mockResolvedValue({ trips: [] })
    await render()
    auth.value = { isAuthenticated: false, token: null, user: null }
    await act(async () => root.render(createElement(Probe)))
    listTrips.mockResolvedValue({ trips: [{ id: 1 }] })
    auth.value = signedIn
    await act(async () => root.render(createElement(Probe)))
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    expect(listTrips).toHaveBeenCalledTimes(2)
    expect(seen.at(-1)).toEqual({ hasTrips: true, loading: false })
  })
})
