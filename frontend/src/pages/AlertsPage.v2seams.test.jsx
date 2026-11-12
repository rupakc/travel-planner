// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

const auth = { token: 'tok', user: { username: 'u', email: null }, preferences: {} }
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth, useOptionalAuth: () => auth }))
vi.mock('../context/AlertsContext', () => ({
  useAlerts: () => ({
    caps: { serpapi: true, fareWatch: true, email: true }, watchesChanged: vi.fn(), refresh: vi.fn(), markSeen: vi.fn(),
  }),
}))
vi.mock('../context/SearchDataContext', () => ({ useSearchData: () => ({ setPendingSearchData: vi.fn() }) }))
vi.mock('../utils/analytics', () => ({ track: vi.fn() }))

const WATCH = {
  id: 7, status: 'active', origin_label: 'Berlin', destination_label: 'Lisbon', departure_date: '2099-12-01',
  return_date: '2099-12-08', num_travelers: 1, baseline_price: 500, last_price: 454, lowest_price: 454,
  check_count: 2, alert_mode: 'any_drop', target_price: null, flexible_days: 0, email_enabled: false,
  history: [{ price: 500 }, { price: 454 }],
}
vi.mock('../services/api', () => ({
  listFareWatches: vi.fn(async () => [WATCH]), listPriceWatches: vi.fn(async () => []),
  checkFareWatchNow: vi.fn(), checkPriceWatchNow: vi.fn(), updateFareWatch: vi.fn(), updatePriceWatch: vi.fn(),
  deleteFareWatch: vi.fn(), deletePriceWatch: vi.fn(), liveCheckWatch: vi.fn(),
}))
vi.mock('../components/alerts2/AlertsV2Header', () => ({ default: () => <div data-testid="v2-header" /> }))
vi.mock('../components/alerts2/WatchCardExtras', () => ({ default: () => <div data-testid="v2-extras" /> }))

let features = {}
vi.mock('../hooks/useClientConfig', () => ({
  useClientConfig: () => ({ config: { features }, loaded: true }),
}))

import AlertsPage from './AlertsPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root

async function show() {
  await act(async () => root.render(<MemoryRouter initialEntries={['/alerts']}><AlertsPage /></MemoryRouter>))
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  localStorage.clear()
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('AlertsPage v2 seams', () => {
  it('old backend keeps the classic alerts page', async () => {
    features = { price_alerts_v2: true }
    localStorage.setItem('tp_alerts2', '1')
    await show()
    expect(container.textContent).toContain('Lisbon')
    expect(container.querySelector('[data-testid="v2-header"]')).toBeNull()
    expect(container.querySelector('[data-testid="v2-extras"]')).toBeNull()
  })

  it('mounts the header and card extras when v2 is on', async () => {
    features = { alerts_api: 2, price_alerts_v2: true }
    await show()
    expect(container.querySelector('[data-testid="v2-header"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="v2-extras"]')).not.toBeNull()
  })

  it('stays classic with alerts_api 2 but no flag or override', async () => {
    features = { alerts_api: 2 }
    await show()
    expect(container.querySelector('[data-testid="v2-header"]')).toBeNull()
  })
})
