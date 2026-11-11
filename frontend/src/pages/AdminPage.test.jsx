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

  it('keeps the tab absent until the probe settles', async () => {
    getTelemetrySummary.mockReturnValue(new Promise(() => {}))
    await act(async () => root.render(<AdminPage />))
    await flush()
    expect(tab()).toBeNull()
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

describe('AdminPage passwords', () => {
  let container, root
  const q = (tid) => container.querySelector(`[data-tid="${tid}"]`)
  const setVal = async (el, v) => act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
  beforeEach(async () => {
    getTelemetrySummary.mockReturnValue(new Promise(() => {}))
    vi.stubGlobal('fetch', vi.fn(async (url) => (String(url).startsWith('/api/admin/users')
      ? new Response(JSON.stringify([{ username: 'bob', email: '', is_admin: false, is_active: true, is_first_login: false }]), { status: 200 })
      : new Response('{}', { status: 404 }))))
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    await act(async () => root.render(<AdminPage />))
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  })
  afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals() })

  it('the reset modal says and enforces 10 characters', async () => {
    act(() => q('admin.reset-password').click())
    expect(q('admin.reset-new-password').getAttribute('placeholder')).toBe('Min. 10 characters')
    await setVal(q('admin.reset-new-password'), 'nine-char')
    await setVal(q('admin.reset-confirm-password'), 'nine-char')
    await act(async () => { q('admin.reset-submit').closest('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    expect(container.textContent).toContain('Password must be at least 10 characters')
    expect(fetch.mock.calls.some(([u]) => String(u).includes('reset-password'))).toBe(false)
  })

  it('the create form hints 10 characters and translates a refused password', async () => {
    act(() => q('admin.create-user').click())
    expect(q('admin.new-password').getAttribute('placeholder')).toBe('Min. 10 characters')
    expect(q('admin.new-password').getAttribute('minlength')).toBe('10')
    fetch.mockImplementation(async () => new Response(JSON.stringify({ detail: 'x', error_code: 'password_too_short' }), { status: 400 }))
    await act(async () => { q('admin.create-submit').closest('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    expect(container.textContent).toContain('That password is too short.')
  })
})

