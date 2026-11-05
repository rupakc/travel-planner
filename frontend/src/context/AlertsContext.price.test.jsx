// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const authState = { token: 'tok' }
vi.mock('./AuthContext', () => ({ useAuth: () => authState }))
vi.mock('../services/api', () => ({
  getCapabilities: vi.fn(async () => ({ serpapi: true, fareWatch: true, email: false })),
  getUnreadCount: vi.fn(async () => 0),
  listNotifications: vi.fn(async () => ({ items: [] })),
  markNotificationsRead: vi.fn(),
  matchFareWatch: vi.fn(),
  matchPriceWatch: vi.fn(),
}))

import * as api from '../services/api'
import { AlertsProvider, useAlerts, usePriceWatchFor } from './AlertsContext'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let seen, hooked
function Probe() { seen = useAlerts(); return null }
function Hooked({ spec }) { [hooked] = usePriceWatchFor('hotel', spec); return null }

describe('price watch lookups', () => {
  let container, root
  beforeEach(() => {
    container = document.createElement('div')
    root = createRoot(container)
    api.matchPriceWatch.mockReset().mockResolvedValue({ id: 3, kind: 'hotel' })
  })
  afterEach(() => act(() => root.unmount()))

  it('asks once per subject and re-asks after watches change', async () => {
    await act(async () => root.render(<AlertsProvider><Probe /></AlertsProvider>))
    const spec = { name: 'Lumen', city: 'Lisbon' }
    expect(await seen.priceWatchFor('hotel', spec)).toEqual({ id: 3, kind: 'hotel' })
    await seen.priceWatchFor('hotel', { city: 'Lisbon', name: 'Lumen' })
    expect(api.matchPriceWatch).toHaveBeenCalledTimes(1)
    expect(api.matchPriceWatch).toHaveBeenCalledWith({ kind: 'hotel', hotel: spec }, 'tok')
    await act(async () => seen.watchesChanged())
    await seen.priceWatchFor('hotel', spec)
    expect(api.matchPriceWatch).toHaveBeenCalledTimes(2)
  })

  it('a failed lookup reads as not watched and is retried next time', async () => {
    api.matchPriceWatch.mockRejectedValueOnce(new Error('offline'))
    await act(async () => root.render(<AlertsProvider><Probe /></AlertsProvider>))
    expect(await seen.priceWatchFor('hotel', { name: 'x' })).toBeNull()
    expect(await seen.priceWatchFor('hotel', { name: 'x' })).toEqual({ id: 3, kind: 'hotel' })
  })

  it('usePriceWatchFor keeps the watch for a subject', async () => {
    await act(async () => root.render(<AlertsProvider><Hooked spec={{ name: 'Lumen' }} /></AlertsProvider>))
    expect(hooked).toEqual({ id: 3, kind: 'hotel' })
  })
})
