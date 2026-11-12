// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, useLocation } from 'react-router-dom'

const auth = { token: 'tok' }
const v2 = { on: true, livePrices: true }
vi.mock('../../context/AuthContext', () => ({ useOptionalAuth: () => auth }))
vi.mock('../../hooks/useAlertsV2', () => ({ useAlertsV2: () => v2 }))
vi.mock('../../services/alertsApi', () => ({ quickWatch: vi.fn() }))
vi.mock('../../services/api', () => ({ deleteFareWatch: vi.fn(), deletePriceWatch: vi.fn() }))
vi.mock('../../telemetry/client', () => ({ emit: vi.fn() }))

import * as alertsApi from '../../services/alertsApi'
import * as api from '../../services/api'
import { emit } from '../../telemetry/client'
import QuickWatchButton, { _resetQuickWatchToast } from './QuickWatchButton'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root; let host; let unmounted = false
const Loc = () => <span data-testid="loc">{useLocation().pathname}</span>
const render = async (props = {}) => {
  await act(async () => {
    root.render(<MemoryRouter><QuickWatchButton kind="hotel" title="Hotel Lux" spec={{ a: 1 }} surface="results" {...props} /><Loc /></MemoryRouter>)
  })
}
const btn = () => host.querySelector('[data-tid="quick-watch"]')
const tap = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const deferred = () => { let resolve; let reject; const p = new Promise((a, b) => { resolve = a; reject = b }); return { p, resolve, reject } }

beforeEach(() => {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  unmounted = false; vi.clearAllMocks(); auth.token = 'tok'; v2.livePrices = true
})
afterEach(() => { if (!unmounted) act(() => root.unmount()); host.remove(); act(() => _resetQuickWatchToast()) })

describe('QuickWatchButton', () => {
  it('hidden when live_prices is false', async () => {
    v2.livePrices = false
    await render()
    expect(btn()).toBeNull()
  })

  it('optimistic on, rollback on error', async () => {
    const d = deferred()
    alertsApi.quickWatch.mockReturnValue(d.p)
    await render()
    expect(btn().getAttribute('aria-pressed')).toBe('false')
    await tap(btn())
    expect(btn().getAttribute('aria-pressed')).toBe('true')
    expect(btn().textContent).toContain('Watching')
    await act(async () => { d.reject({ status: 422, code: 'spec_invalid' }) })
    expect(btn().getAttribute('aria-pressed')).toBe('false')
    expect(host.querySelector('[data-tid="quick-watch-error"]')).not.toBeNull()
  })

  it('shows the toast and undo deletes the created watch', async () => {
    alertsApi.quickWatch.mockResolvedValue({ kind: 'hotel', watch: { id: 5 }, existing: false })
    api.deletePriceWatch.mockResolvedValue({})
    await render()
    await tap(btn())
    expect(document.body.textContent).toContain("We'll check this price for you")
    await tap(document.querySelector('[data-tid="quick-watch-undo"]'))
    expect(api.deletePriceWatch).toHaveBeenCalledWith(5, 'tok')
    expect(btn().getAttribute('aria-pressed')).toBe('false')
    expect(document.querySelector('[data-tid="quick-watch-toast"]')).toBeNull()
  })

  it('undo still works after the button unmounts', async () => {
    alertsApi.quickWatch.mockResolvedValue({ kind: 'hotel', watch: { id: 5 }, existing: false })
    api.deletePriceWatch.mockResolvedValue({})
    await render()
    await tap(btn())
    await act(async () => { root.unmount() }); unmounted = true
    await tap(document.querySelector('[data-tid="quick-watch-undo"]'))
    expect(api.deletePriceWatch).toHaveBeenCalledWith(5, 'tok')
    expect(document.querySelector('[data-tid="quick-watch-toast"]')).toBeNull()
  })

  it('failed undo shows an error and keeps the button pressed', async () => {
    alertsApi.quickWatch.mockResolvedValue({ kind: 'hotel', watch: { id: 5 }, existing: false })
    api.deletePriceWatch.mockRejectedValue({ status: 500 })
    await render()
    await tap(btn())
    await tap(document.querySelector('[data-tid="quick-watch-undo"]'))
    expect(document.querySelector('[data-tid="quick-watch-toast"]').textContent).toContain("Couldn't undo")
    expect(btn().getAttribute('aria-pressed')).toBe('true')
  })

  it('undo has a busy guard: one DELETE, no false failure', async () => {
    alertsApi.quickWatch.mockResolvedValue({ kind: 'hotel', watch: { id: 5 }, existing: false })
    const d = deferred()
    api.deletePriceWatch.mockReturnValue(d.p)
    await render()
    await tap(btn())
    const undo = document.querySelector('[data-tid="quick-watch-undo"]')
    await tap(undo); await tap(undo)
    expect(api.deletePriceWatch).toHaveBeenCalledTimes(1)
    await act(async () => { d.resolve({}) })
    expect(document.querySelector('[data-tid="quick-watch-toast"]')).toBeNull()
    expect(document.body.textContent).not.toContain("Couldn't undo")
  })

  it('two watches keep two toasts, each with its own undo', async () => {
    alertsApi.quickWatch.mockResolvedValueOnce({ kind: 'hotel', watch: { id: 5 }, existing: false })
      .mockResolvedValueOnce({ kind: 'hotel', watch: { id: 6 }, existing: false })
    api.deletePriceWatch.mockResolvedValue({})
    await act(async () => {
      root.render(<MemoryRouter>
        <QuickWatchButton kind="hotel" title="A" spec={{}} /><QuickWatchButton kind="hotel" title="B" spec={{}} />
      </MemoryRouter>)
    })
    const [a, b] = host.querySelectorAll('[data-tid="quick-watch"]')
    await tap(a); await tap(b)
    expect(document.querySelectorAll('[data-tid="quick-watch-toast"]')).toHaveLength(2)
    await tap(document.querySelectorAll('[data-tid="quick-watch-undo"]')[0])
    expect(api.deletePriceWatch).toHaveBeenCalledWith(5, 'tok')
    expect(document.querySelectorAll('[data-tid="quick-watch-toast"]')).toHaveLength(1)
    await tap(document.querySelector('[data-tid="quick-watch-undo"]'))
    expect(api.deletePriceWatch).toHaveBeenCalledWith(6, 'tok')
  })

  it('tapping while pressed does nothing more', async () => {
    alertsApi.quickWatch.mockResolvedValue({ kind: 'hotel', watch: { id: 5 }, existing: false })
    await render()
    await tap(btn()); await tap(btn())
    expect(api.deletePriceWatch).not.toHaveBeenCalled()
    expect(alertsApi.quickWatch).toHaveBeenCalledTimes(1)
  })

  it('undo on a flight deletes a fare watch', async () => {
    alertsApi.quickWatch.mockResolvedValue({ kind: 'flight', watch: { id: 9 }, existing: false })
    api.deleteFareWatch.mockResolvedValue({})
    await render({ kind: 'flight' })
    await tap(btn())
    await tap(document.querySelector('[data-tid="quick-watch-undo"]'))
    expect(api.deleteFareWatch).toHaveBeenCalledWith(9, 'tok')
  })

  it('existing shows already watching with a link to the story', async () => {
    alertsApi.quickWatch.mockResolvedValue({ kind: 'hotel', watch: { id: 5 }, existing: true })
    await render()
    await tap(btn())
    const link = host.querySelector('[data-tid="quick-watch-existing"]')
    expect(link.textContent).toContain('Already watching')
    expect(link.getAttribute('href')).toBe('/alerts?kind=hotel&watch=5')
    expect(document.querySelector('[data-tid="quick-watch-toast"]')).toBeNull()
  })

  it('double tap sends one request', async () => {
    const d = deferred()
    alertsApi.quickWatch.mockReturnValue(d.p)
    await render()
    await tap(btn()); await tap(btn())
    expect(alertsApi.quickWatch).toHaveBeenCalledTimes(1)
    await act(async () => { d.resolve({ kind: 'hotel', watch: { id: 1 }, existing: false }) })
  })

  it('409 shows limit text', async () => {
    alertsApi.quickWatch.mockRejectedValue({ status: 409, code: 'watch_limit', detail: 'x' })
    await render()
    await tap(btn())
    expect(host.querySelector('[data-tid="quick-watch-error"]').textContent).toContain('limit of active watches')
    expect(btn().getAttribute('aria-pressed')).toBe('false')
    expect(emit).toHaveBeenCalledWith('alert_quick_watch', { kind: 'hotel', action: 'blocked', surface: 'results' })
  })

  it('telemetry has kind, action and surface, no title', async () => {
    alertsApi.quickWatch.mockResolvedValue({ kind: 'hotel', watch: { id: 5 }, existing: false })
    await render()
    await tap(btn())
    expect(emit).toHaveBeenCalledWith('alert_quick_watch', { kind: 'hotel', action: 'add', surface: 'results' })
    expect(JSON.stringify(emit.mock.calls)).not.toContain('Hotel Lux')
  })

  it('signed out tap opens sign-in', async () => {
    auth.token = null
    await render()
    await tap(btn())
    expect(host.querySelector('[data-testid="loc"]').textContent).toBe('/login')
    expect(alertsApi.quickWatch).not.toHaveBeenCalled()
  })
})
