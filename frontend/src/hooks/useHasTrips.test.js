// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'

const auth = vi.hoisted(() => ({ value: {} }))
const journey = vi.hoisted(() => ({ value: {} }))
const listTrips = vi.hoisted(() => vi.fn())
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth.value }))
vi.mock('./useJourney', () => ({ useJourney: () => journey.value }))
vi.mock('../services/tripsApi', () => ({ listTrips, TRIPS_CHANGED_EVENT: 'voyager:trips-changed' }))

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

  it('shares one request between callers', async () => {
    listTrips.mockResolvedValue({ trips: [{ id: 3 }] })
    function Two() { return [createElement(Probe, { key: 1 }), createElement(Probe, { key: 2 })] }
    root = createRoot(document.createElement('div'))
    await act(async () => root.render(createElement(Two)))
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    expect(listTrips).toHaveBeenCalledTimes(1)
    expect(seen.slice(-2)).toEqual([{ hasTrips: true, loading: false }, { hasTrips: true, loading: false }])
  })

  // RequireAuth unmounts Layout and NavBar on sign-out; the next sign-in mounts them again.
  it('asks again when remounted after sign-out (same user)', async () => {
    listTrips.mockResolvedValue({ trips: [] })
    await render()
    act(() => root.unmount())
    listTrips.mockResolvedValue({ trips: [{ id: 1 }] })
    await render()
    expect(listTrips).toHaveBeenCalledTimes(2)
    expect(seen.at(-1)).toEqual({ hasTrips: true, loading: false })
  })

  it('asks again for another user, never showing the previous answer', async () => {
    listTrips.mockResolvedValue({ trips: [{ id: 1 }] })
    await render()
    act(() => root.unmount())
    auth.value = { isAuthenticated: true, token: 'other', user: { id: 2, username: 'b' } }
    listTrips.mockResolvedValue({ trips: [] })
    seen = []
    await render()
    expect(seen[0]).toEqual({ hasTrips: null, loading: true })
    expect(listTrips).toHaveBeenLastCalledWith('other')
    expect(seen.at(-1)).toEqual({ hasTrips: false, loading: false })
  })

  it('voyager:trips-changed asks again in place, keeping the old answer meanwhile', async () => {
    listTrips.mockResolvedValue({ trips: [] })
    await render()
    expect(seen.at(-1)).toEqual({ hasTrips: false, loading: false })
    let resolve
    listTrips.mockReturnValue(new Promise((r) => { resolve = r }))
    await act(async () => { window.dispatchEvent(new Event('voyager:trips-changed')) })
    expect(listTrips).toHaveBeenCalledTimes(2)
    expect(seen.at(-1)).toEqual({ hasTrips: false, loading: false })
    await act(async () => { resolve({ trips: [{ id: 9 }] }) })
    expect(seen.at(-1)).toEqual({ hasTrips: true, loading: false })
  })

  it('ignores the event once nothing is mounted', async () => {
    listTrips.mockResolvedValue({ trips: [] })
    await render()
    act(() => root.unmount())
    window.dispatchEvent(new Event('voyager:trips-changed'))
    expect(listTrips).toHaveBeenCalledTimes(1)
    await render()
  })
})
