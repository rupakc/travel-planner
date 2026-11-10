// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ token: 't', user: { username: 'admin' } }),
}))
vi.mock('../services/api', () => ({ getTelemetrySummary: vi.fn() }))

import { getTelemetrySummary } from '../services/api'
import AdminPage from './AdminPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('AdminPage analytics tab', () => {
  let container, root
  const flush = () => act(async () => { await Promise.resolve() })
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })
  const tab = () => container.querySelector('[data-tid="admin.tab-Analytics"]')

  it('shows the tab and its tiles', async () => {
    getTelemetrySummary.mockResolvedValue({ days: [], top_events: [], top_screens: [] })
    await act(async () => root.render(<AdminPage />))
    await flush()
    expect(tab()).not.toBeNull()
    act(() => tab().click())
    expect(container.querySelector('[data-tid="admin.telemetry-users-today"]')).not.toBeNull()
  })

  it('hides the tab on a 404 from an older backend', async () => {
    getTelemetrySummary.mockRejectedValue({ response: { status: 404 } })
    await act(async () => root.render(<AdminPage />))
    await flush()
    expect(tab()).toBeNull()
  })

  it('keeps the tab and shows an inline error on other failures', async () => {
    getTelemetrySummary.mockRejectedValue({ response: { status: 500 } })
    await act(async () => root.render(<AdminPage />))
    await flush()
    act(() => tab().click())
    expect(container.querySelector('[role="alert"]')).not.toBeNull()
  })
})
