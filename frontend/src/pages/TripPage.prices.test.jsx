// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const v2 = vi.hoisted(() => ({ on: true, livePrices: true }))
const api = vi.hoisted(() => ({
  listFareWatches: vi.fn(), listPriceWatches: vi.fn(), getStory: vi.fn(),
}))
vi.mock('../hooks/useAlertsV2', () => ({ useAlertsV2: () => v2 }))
vi.mock('../hooks/useJourney', () => ({ useJourney: () => ({ enabled: true, tripsApi: true, offlinePack: true, loaded: true }) }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ token: 'tok', user: { id: 7 } }), useOptionalAuth: () => ({ token: 'tok', user: { id: 7 } }) }))
vi.mock('../telemetry/client', () => ({ emit: vi.fn() }))
vi.mock('../offline/useOfflinePack', () => ({ useOfflinePack: () => ({ pack: null, savedAt: null, loading: false }) }))
vi.mock('../offline/useOnline', () => ({ useOnline: () => true }))
vi.mock('../services/tripsApi', () => ({
  getTrip: vi.fn(async () => ({
    id: 3, title: 'Lisbon', destination: 'Lisbon', destinations: ['Lisbon'], start_date: '2027-04-01', end_date: '2027-04-08',
    phase: 'planning', phase_source: 'auto', days_to_start: 100, day_index: null, prep: { done: 0, total: 1, percent: 0 },
  })),
  patchTrip: vi.fn(), deleteTrip: vi.fn(), notifyTripsChanged: vi.fn(),
}))
vi.mock('../services/api', () => ({ listFareWatches: api.listFareWatches, listPriceWatches: api.listPriceWatches }))
vi.mock('../services/alertsApi', () => ({ getStory: api.getStory }))
vi.mock('../components/trips/TripOverview', () => ({ default: () => <div data-testid="overview" /> }))
vi.mock('../components/alerts2/WatchSuggestions', () => ({
  default: (p) => <span data-testid="suggest" data-plan={p.planId} data-force={String(!!p.force)} />,
}))

import TripPage from './TripPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root
beforeEach(() => {
  v2.on = true; v2.livePrices = true
  api.listFareWatches.mockResolvedValue([
    { id: 1, plan_id: 3, status: 'active', origin_label: 'New York', destination_label: 'Lisbon', last_price: 400, currency: 'USD' },
    { id: 2, plan_id: 99, status: 'active', origin_label: 'Paris', destination_label: 'Rome' },
  ])
  api.listPriceWatches.mockResolvedValue([
    { id: 5, kind: 'hotel', plan_id: 3, status: 'active', title: 'Lumen Hotel', last_price: 480, currency: 'USD' },
    { id: 6, kind: 'hotel', plan_id: null, status: 'active', title: 'Other Hotel' },
  ])
  api.getStory.mockImplementation(async (t, kind) => (kind === 'flight' ? { verdict: 'good' } : { verdict: null, pending_first_check: true }))
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ id: 3, name: 'Lisbon', search_data: {}, selections: {} }) })))
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); vi.clearAllMocks() })
const render = async () => {
  await act(async () => root.render(
    <MemoryRouter initialEntries={['/trips/3/overview']}>
      <Routes><Route path="*" element={<TripPage tripId={3} tab="overview" />} /></Routes>
    </MemoryRouter>,
  ))
  await act(async () => {})
  await act(async () => {})
}
const tid = (id) => container.querySelector(`[data-tid="${id}"]`)

describe('Trip Prices card', () => {
  it('lists watches for this plan_id', async () => {
    await render()
    const text = tid('trip.prices').textContent
    expect(text).toContain('New York → Lisbon')
    expect(text).toContain('Lumen Hotel')
    expect(text).not.toContain('Paris')
    expect(text).not.toContain('Other Hotel')
    expect(tid('trip.prices.verdict').textContent).toBe('Good price')
    expect(text).toContain('First check pending')
    expect(tid('trip.prices.hub').getAttribute('href')).toBe('/alerts')
  })

  it('"Watch prices for this trip" opens suggestions with force', async () => {
    await render()
    expect(container.querySelector('[data-testid="suggest"]')).toBeNull()
    await act(async () => tid('trip.prices.suggest').click())
    const s = container.querySelector('[data-testid="suggest"]')
    expect(s.dataset.plan).toBe('3')
    expect(s.dataset.force).toBe('true')
  })

  it('flag off: no card', async () => {
    v2.on = false
    await render()
    expect(tid('trip.prices')).toBeNull()
    expect(api.listFareWatches).not.toHaveBeenCalled()
  })
})
